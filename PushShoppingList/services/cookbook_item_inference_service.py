import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from datetime import timezone

from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import cookbook_service
from PushShoppingList.services.openai_model_service import default_model_for_env
from PushShoppingList.services.openai_model_service import openai_model_recommendations
from PushShoppingList.services.openai_model_service import sync_openai_model_environment_from_overrides
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import apply_menu_batch_inference_to_stub
from PushShoppingList.services.recipe_extract_service import build_menu_item_recipe_batch_prompt
from PushShoppingList.services.recipe_extract_service import build_openai_chat_payload
from PushShoppingList.services.recipe_extract_service import classify_vision_ai_exception
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import compact_menu_batch_item
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
from PushShoppingList.services.recipe_extract_service import generate_menu_recipe_from_stub
from PushShoppingList.services.recipe_extract_service import menu_batch_item_from_stub
from PushShoppingList.services.recipe_extract_service import menu_item_name_is_blank_divider
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_recipe_scaling_metadata
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import recipe_ingredients_for_key
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.storage_service import active_user_id


COOKBOOK_ITEM_MODEL_ENV_VAR = "OPENAI_COOKBOOK_ITEM_MODEL"
COOKBOOK_ITEM_MODEL_FALLBACK_ENV_VARS = (
    COOKBOOK_ITEM_MODEL_ENV_VAR,
    "OPENAI_MENU_MODEL",
    "OPENAI_RECIPE_MODEL",
)
COOKBOOK_ITEM_SOURCE_TYPE = "cookbook_item_inferred"
MENU_ITEM_SOURCE_TYPE = "menu_item_inferred"
INFERRED_FIELD_METADATA_KEY = "cookbook_item_inferred_fields"
INFERRED_FIELD_SOURCE_KEY = "cookbook_item_inference_field_sources"
COOKBOOK_ITEM_INFERENCE_WORKERS = 3
COOKBOOK_ITEM_INFERENCE_MAX_WORKERS_ENV_VAR = "COOKBOOK_ITEM_INFERENCE_MAX_WORKERS"
COOKBOOK_ITEM_INFERENCE_MAX_RETRIES = 2
COOKBOOK_ITEM_BATCH_INFERENCE_MAX_ITEMS_ENV_VAR = "COOKBOOK_ITEM_BATCH_INFERENCE_MAX_ITEMS"
COOKBOOK_ITEM_BATCH_INFERENCE_MIN_ITEMS_ENV_VAR = "COOKBOOK_ITEM_BATCH_INFERENCE_MIN_ITEMS"
COOKBOOK_ITEM_BATCH_INFERENCE_TARGET_CHARS_ENV_VAR = "COOKBOOK_ITEM_BATCH_INFERENCE_TARGET_CHARS"
COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_MAX_ITEMS = 8
COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_MIN_ITEMS = 4
COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_TARGET_CHARS = 9000
COOKBOOK_ITEM_BATCH_INFERENCE_ACTION = "cookbook-item-recipe-batch-inference"
COOKBOOK_ITEM_BATCH_SPLITTABLE_ERROR_CODES = {
    "OPENAI_TIMEOUT",
    "OPENAI_CONNECTION_ERROR",
}
TEXT_DETAIL_FIELDS = (
    "recipe_amount",
    "yield",
    "servings",
    "level",
    "total_time",
    "prep_time",
    "inactive_time",
    "cook_time",
)
DETAIL_FIELDS = (*TEXT_DETAIL_FIELDS, "ingredients", "equipment", "instructions")
PLACEHOLDER_TEXT_VALUES = {
    "",
    "none",
    "null",
    "undefined",
    "n/a",
    "na",
    "not specified",
    "not provided",
    "unknown",
    "tbd",
    "todo",
    "placeholder",
}


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value):
    return " ".join(str(value or "").strip().split())


def truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def missing_text(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (list, dict)):
        return not bool(value)
    return clean_text(value).lower() in PLACEHOLDER_TEXT_VALUES


def first_clean_text(*values):
    for value in values:
        text = clean_text(value)
        if text and not missing_text(text):
            return text
    return ""


def ingredient_has_real_value(item):
    if isinstance(item, str):
        return bool(clean_text(item))
    if not isinstance(item, dict):
        return False
    for field in (
        "ingredient",
        "name",
        "original_text",
        "original_recipe_text",
        "text",
        "purchasable_item",
        "buy_as",
    ):
        if clean_text(item.get(field)):
            return True
    return False


def ingredients_have_real_values(value):
    if isinstance(value, str):
        return bool(clean_text(value))
    if not isinstance(value, list):
        return False
    return any(ingredient_has_real_value(item) for item in value)


def equipment_have_real_values(value):
    return bool(recipe_edit_service.normalize_equipment_records(value))


def instructions_have_real_values(value):
    return bool(recipe_edit_service.normalize_instruction_records(value))


def field_has_real_value(recipe_data, field):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    if field == "ingredients":
        return ingredients_have_real_values(recipe_data.get("ingredients"))
    if field == "equipment":
        return equipment_have_real_values(recipe_data.get("equipment"))
    if field == "instructions":
        return instructions_have_real_values(recipe_data.get("instructions"))
    if field == "servings":
        scaling = recipe_data.get("scaling") if isinstance(recipe_data.get("scaling"), dict) else {}
        return not missing_text(recipe_data.get("servings")) or not missing_text(scaling.get("base_servings"))
    return not missing_text(recipe_data.get(field))


def nested_recipe_raw(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    raw = recipe_data.get("raw")
    return raw if isinstance(raw, dict) else {}


def recipe_inference_record(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    raw = nested_recipe_raw(recipe_data)
    inference = recipe_data.get("recipe_inference")
    if not isinstance(inference, dict):
        inference = raw.get("recipe_inference")
    return inference if isinstance(inference, dict) else {}


def recipe_needs_menu_recipe_generation(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    raw = nested_recipe_raw(recipe_data)
    inference = recipe_inference_record(recipe_data)
    source_types = {
        clean_text(recipe_data.get("source_type")).lower(),
        clean_text(raw.get("source_type")).lower(),
    }
    statuses = {
        clean_text(recipe_data.get("recipe_status")).lower(),
        clean_text(raw.get("recipe_status")).lower(),
        clean_text(inference.get("status")).lower(),
    }
    if recipe_data.get("needs_ai_recipe") or raw.get("needs_ai_recipe"):
        return True
    if "menu_item_stub" in source_types or "stub" in statuses:
        return True
    return False


def inferred_fields_for_recipe(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    fields = recipe_data.get(INFERRED_FIELD_METADATA_KEY)
    if not isinstance(fields, list):
        fields = recipe_data.get("ai_inferred_fields")
    if not isinstance(fields, list):
        fields = []
    return {
        clean_text(field)
        for field in fields
        if clean_text(field)
    }


def should_fill_field(recipe_data, field, overwrite_ai_fields=False):
    if not field_has_real_value(recipe_data, field):
        return True
    return bool(overwrite_ai_fields and field in inferred_fields_for_recipe(recipe_data))


def missing_fields_for_recipe(recipe_data, overwrite_ai_fields=False):
    return [
        field
        for field in DETAIL_FIELDS
        if should_fill_field(recipe_data, field, overwrite_ai_fields=overwrite_ai_fields)
    ]


def cookbook_item_worker_count(total_items=None):
    try:
        configured = int(os.getenv(COOKBOOK_ITEM_INFERENCE_MAX_WORKERS_ENV_VAR, str(COOKBOOK_ITEM_INFERENCE_WORKERS)))
    except (TypeError, ValueError):
        configured = COOKBOOK_ITEM_INFERENCE_WORKERS
    configured = max(1, min(8, configured))
    if total_items:
        return max(1, min(configured, int(total_items)))
    return configured


def resolve_cookbook_item_model():
    sync_openai_model_environment_from_overrides()
    for env_var in COOKBOOK_ITEM_MODEL_FALLBACK_ENV_VARS:
        model = clean_text(os.getenv(env_var))
        if model:
            return model, f"configured:{env_var}"

    recommendations = openai_model_recommendations()
    mappings = recommendations.get("mappings", {}) if isinstance(recommendations, dict) else {}
    model = clean_text(
        mappings.get(COOKBOOK_ITEM_MODEL_ENV_VAR)
        or mappings.get("OPENAI_RECIPE_MODEL")
        or default_model_for_env(COOKBOOK_ITEM_MODEL_ENV_VAR)
        or default_model_for_env("OPENAI_RECIPE_MODEL")
    )
    return model, f"default:{COOKBOOK_ITEM_MODEL_ENV_VAR}"


def env_int(name, default_value, minimum=1, maximum=None):
    try:
        value = int(os.getenv(name, str(default_value)))
    except (TypeError, ValueError):
        value = int(default_value)
    value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def cookbook_item_batch_size_limits():
    max_items = env_int(
        COOKBOOK_ITEM_BATCH_INFERENCE_MAX_ITEMS_ENV_VAR,
        COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_MAX_ITEMS,
        minimum=1,
        maximum=25,
    )
    min_items = env_int(
        COOKBOOK_ITEM_BATCH_INFERENCE_MIN_ITEMS_ENV_VAR,
        COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_MIN_ITEMS,
        minimum=1,
        maximum=max_items,
    )
    return min_items, max_items


def cookbook_item_batch_target_chars():
    return env_int(
        COOKBOOK_ITEM_BATCH_INFERENCE_TARGET_CHARS_ENV_VAR,
        COOKBOOK_ITEM_BATCH_INFERENCE_DEFAULT_TARGET_CHARS,
        minimum=3000,
    )


def cookbook_item_inference_batches(entries):
    min_items, max_items = cookbook_item_batch_size_limits()
    target_chars = cookbook_item_batch_target_chars()
    batches = []
    current = []
    current_chars = 0

    for entry in entries or []:
        item = entry.get("menu_item") if isinstance(entry, dict) else {}
        item_chars = len(json.dumps(compact_menu_batch_item(item), ensure_ascii=False))
        should_split = (
            current
            and len(current) >= min_items
            and (
                len(current) >= max_items
                or current_chars + item_chars > target_chars
            )
        )
        if should_split:
            batches.append(current)
            current = []
            current_chars = 0

        current.append(entry)
        current_chars += item_chars

        if len(current) >= max_items:
            batches.append(current)
            current = []
            current_chars = 0

    if current:
        batches.append(current)

    return batches


def cookbook_batch_entry_item_id(entry):
    entry = entry if isinstance(entry, dict) else {}
    menu_item = entry.get("menu_item") if isinstance(entry.get("menu_item"), dict) else {}
    return clean_text(menu_item.get("menu_item_id"))


def normalize_openai_error_message(error_code, error_message, fallback=""):
    message = clean_text(error_message) or clean_text(fallback)
    if message.startswith("Vision AI "):
        message = "OpenAI " + message[len("Vision AI "):]
    if error_code == "OPENAI_TIMEOUT" and (not message or "vision" in message.lower()):
        return "Cookbook item batch inference timed out."
    return message or "Unable to infer cookbook item batch."


def coerce_batch_inference_payload(payload):
    if not isinstance(payload, dict):
        return {}
    candidates = payload.get("items") or payload.get("recipes") or payload.get("recipe_inference") or payload
    if isinstance(candidates, list):
        keyed = {}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_id = clean_text(item.get("menu_item_id") or item.get("id") or "")
            if item_id:
                keyed[item_id] = item
        return keyed
    if isinstance(candidates, dict):
        return {
            clean_text(key): value
            for key, value in candidates.items()
            if clean_text(key) and isinstance(value, dict)
        }
    return {}


def batch_failure_map(entries, batch_result):
    batch_result = batch_result if isinstance(batch_result, dict) else {}
    items = batch_result.get("items") if isinstance(batch_result.get("items"), dict) else {}
    error = (
        batch_result.get("error_message")
        or batch_result.get("error")
        or batch_result.get("technical_message")
        or "Unable to infer this cookbook item batch."
    )
    failures = {}
    for entry in entries or []:
        item_id = cookbook_batch_entry_item_id(entry)
        if item_id and isinstance(items.get(item_id), dict):
            continue
        failures[item_id or clean_text(entry.get("recipe_url")) or str(len(failures) + 1)] = {
            "error": error,
            "error_code": batch_result.get("error_code", ""),
            "exception_type": batch_result.get("exception_type", ""),
            "model": batch_result.get("model", ""),
            "model_source": batch_result.get("model_source", ""),
        }
    return failures


def batch_result_can_split(batch_result):
    batch_result = batch_result if isinstance(batch_result, dict) else {}
    error_code = clean_text(batch_result.get("error_code"))
    exception_type = clean_text(batch_result.get("exception_type")).lower()
    error_text = clean_text(batch_result.get("technical_message") or batch_result.get("error_message") or batch_result.get("error")).lower()
    return bool(
        error_code in COOKBOOK_ITEM_BATCH_SPLITTABLE_ERROR_CODES
        or exception_type in {"apitimeouterror", "timeouterror", "apiconnectionerror"}
        or "timed out" in error_text
        or "timeout" in error_text
    )


def send_cookbook_item_recipe_batch_prompt_to_openai(prompt_text, model, model_source, user_id=None):
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        model,
        COOKBOOK_ITEM_BATCH_INFERENCE_ACTION,
        [
            {
                "role": "system",
                "content": (
                    "You infer practical, clearly labeled AI-inferred recipes from cookbook and restaurant menu items. "
                    "Return only strict valid JSON keyed by menu_item_id."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action={COOKBOOK_ITEM_BATCH_INFERENCE_ACTION} "
        f"model={resolved_model} model_source={model_source} "
        f"temperature_included={temperature_included}"
    )
    response = throttled_chat_completion(
        get_openai_client(),
        payload,
        action_name=COOKBOOK_ITEM_BATCH_INFERENCE_ACTION,
        model=resolved_model,
        kind="menu",
    )
    record_openai_usage(
        response,
        COOKBOOK_ITEM_BATCH_INFERENCE_ACTION,
        model=resolved_model,
        user_id=user_id,
    )
    return response.choices[0].message.content


def _infer_menu_item_recipe_batch_once(entries, user_id=None):
    model, model_source = resolve_cookbook_item_model()
    try:
        response_text = send_cookbook_item_recipe_batch_prompt_to_openai(
            build_menu_item_recipe_batch_prompt(entries),
            model,
            model_source,
            user_id=user_id,
        )
        payload = json.loads(clean_json_response(response_text))
        items = coerce_batch_inference_payload(payload)
        if not items:
            raise ValueError("Cookbook item batch inference did not return item results.")
        return {
            "ok": True,
            "items": items,
            "failures": {},
            "model": model,
            "model_source": model_source,
            "raw_response": response_text,
        }
    except Exception as exc:
        error_code, error_message = classify_vision_ai_exception(exc)
        error_message = normalize_openai_error_message(error_code, error_message, fallback=str(exc))
        openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
        print(
            f"[OpenAI] action={COOKBOOK_ITEM_BATCH_INFERENCE_ACTION}_exception "
            f"batch_size={len(entries or [])} "
            f"model={model} model_source={model_source} "
            f"exception_type={type(exc).__name__} error={exc} "
            f"openai_error_code={openai_error_code or 'n/a'} "
            f"openai_error_param={openai_error_param or 'n/a'}"
        )
        return {
            "ok": False,
            "items": {},
            "failures": {},
            "error_code": error_code,
            "error_message": error_message,
            "technical_message": str(exc),
            "exception_type": type(exc).__name__,
            "openai_error_code": openai_error_code,
            "openai_error_param": openai_error_param,
            "model": model,
            "model_source": model_source,
        }


def combine_batch_results(results):
    combined_items = {}
    combined_failures = {}
    model = ""
    model_source = ""
    error_messages = []

    for result in results:
        result = result if isinstance(result, dict) else {}
        if not model:
            model = result.get("model", "")
        if not model_source:
            model_source = result.get("model_source", "")
        items = result.get("items") if isinstance(result.get("items"), dict) else {}
        combined_items.update(items)
        failures = result.get("failures") if isinstance(result.get("failures"), dict) else {}
        combined_failures.update(failures)
        if not result.get("ok"):
            error_messages.append(
                result.get("error_message")
                or result.get("error")
                or "Unable to infer part of this cookbook item batch."
            )

    for item_id in list(combined_failures.keys()):
        if item_id and item_id in combined_items:
            combined_failures.pop(item_id, None)

    return {
        "ok": not combined_failures,
        "items": combined_items,
        "failures": combined_failures,
        "error_message": "; ".join(dict.fromkeys(error_messages)),
        "model": model,
        "model_source": model_source,
    }


def infer_menu_item_recipe_batch(entries, user_id=None):
    entries = [entry for entry in entries or [] if isinstance(entry, dict)]
    if not entries:
        model, model_source = resolve_cookbook_item_model()
        return {
            "ok": True,
            "items": {},
            "failures": {},
            "model": model,
            "model_source": model_source,
        }

    result = _infer_menu_item_recipe_batch_once(entries, user_id=user_id)
    if result.get("ok") or len(entries) <= 1 or not batch_result_can_split(result):
        if not result.get("ok"):
            result["failures"] = batch_failure_map(entries, result)
        return result

    midpoint = max(1, len(entries) // 2)
    log_inference_event(
        "batch_split",
        batch_size=len(entries),
        left_size=midpoint,
        right_size=len(entries) - midpoint,
        error_code=result.get("error_code", ""),
        exception_type=result.get("exception_type", ""),
        model=result.get("model", ""),
    )
    left = infer_menu_item_recipe_batch(entries[:midpoint], user_id=user_id)
    right = infer_menu_item_recipe_batch(entries[midpoint:], user_id=user_id)
    return combine_batch_results([left, right])


def text_list_for_prompt(value, kind):
    if kind == "ingredients":
        rows = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, dict):
                text = first_clean_text(
                    item.get("original_text"),
                    item.get("original_recipe_text"),
                    item.get("ingredient"),
                    item.get("name"),
                    item.get("text"),
                )
            else:
                text = clean_text(item)
            if text:
                rows.append(text)
        return rows
    if kind == "equipment":
        return [
            item.get("equipment") or item.get("text") or item.get("name")
            for item in recipe_edit_service.normalize_equipment_records(value)
        ]
    if kind == "instructions":
        return [
            item.get("instruction") or item.get("text")
            for item in recipe_edit_service.normalize_instruction_records(value)
        ]
    return []


def cookbook_context_for_recipe(recipe_url, cookbook_id="", cookbook_name=""):
    assignment = cookbook_service.cookbook_recipe_assignment_for_url(recipe_url)
    return {
        "cookbook_id": clean_text(cookbook_id) or assignment.get("cookbook_id", ""),
        "cookbook_name": clean_text(cookbook_name) or assignment.get("cookbook_name", ""),
    }


def build_prompt_context(recipe_url, recipe_data, cookbook_id="", cookbook_name=""):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    cookbook_context = cookbook_context_for_recipe(recipe_url, cookbook_id, cookbook_name)
    scaling = recipe_data.get("scaling") if isinstance(recipe_data.get("scaling"), dict) else {}
    return {
        "cookbook_id": cookbook_context.get("cookbook_id", ""),
        "cookbook_name": cookbook_context.get("cookbook_name", ""),
        "recipe_id": clean_text(recipe_data.get("recipe_id") or recipe_url),
        "recipe_url": recipe_url,
        "recipe_title": first_clean_text(
            recipe_data.get("recipe_title"),
            recipe_data.get("display_name"),
            recipe_data.get("menu_item_name"),
        ),
        "menu_section": clean_text(recipe_data.get("menu_section")),
        "menu_item_name": clean_text(recipe_data.get("menu_item_name")),
        "menu_price": clean_text(recipe_data.get("menu_price")),
        "menu_description": clean_text(recipe_data.get("menu_description")),
        "source_type": clean_text(recipe_data.get("source_type")),
        "ai_inferred": bool(recipe_data.get("ai_inferred")),
        "current": {
            "recipe_amount": clean_text(recipe_data.get("recipe_amount")),
            "servings": clean_text(recipe_data.get("servings")),
            "yield": clean_text(recipe_data.get("yield")),
            "level": clean_text(recipe_data.get("level")),
            "total_time": clean_text(recipe_data.get("total_time")),
            "prep_time": clean_text(recipe_data.get("prep_time")),
            "inactive_time": clean_text(recipe_data.get("inactive_time")),
            "cook_time": clean_text(recipe_data.get("cook_time")),
            "scaling_base_servings": clean_text(scaling.get("base_servings")),
            "ingredients": text_list_for_prompt(recipe_data.get("ingredients"), "ingredients"),
            "equipment": text_list_for_prompt(recipe_data.get("equipment"), "equipment"),
            "instructions": text_list_for_prompt(recipe_data.get("instructions"), "instructions"),
        },
    }


def build_cookbook_item_prompt(recipe_url, recipe_data, missing_fields, cookbook_id="", cookbook_name=""):
    context = build_prompt_context(recipe_url, recipe_data, cookbook_id, cookbook_name)
    return f"""
Infer missing practical home-cooking recipe details for a cookbook/menu item.

Use the menu description and cookbook context. This is not the restaurant's exact recipe.
Return strict JSON only. Do not include markdown.

Conservative rules:
- Fill only useful recipe fields for a home cook.
- If the menu item description clearly states a quantity, use it.
- Example: "2 veggie golden crispy brown paper wheat wrapped..." should yield "2 spring rolls" and "2 pieces".
- If the item is an appetizer, default servings should usually be "1 appetizer serving" unless the description says otherwise.
- Difficulty must be Easy, Medium, or Hard.
- Time estimates should be realistic for home cooking.
- Ingredients should be inferred from the menu description and common restaurant preparation knowledge.
- Equipment should be practical home-kitchen equipment.
- Instructions should be short, useful, and recipe-like.
- Preserve any strong current details from the context and focus on these missing fields: {", ".join(missing_fields)}.
- Mark ingredient rows inferred=true unless the source/menu description or current recipe text explicitly contains the ingredient name.
- Do not generate unusual ingredient names such as potato milk, chicken milk, beef milk, pork milk, onion milk, garlic milk, or pepper milk unless the exact phrase appears in the source text.
- If a suspicious ingredient appears, keep it in the recipe and add warning/food_review metadata rather than deleting or silently replacing it.
- For Huancaina-style recipes, food_review correction options should prefer evaporated milk or milk over potato milk unless the source text explicitly says potato milk.

Context JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Required response shape:
{{
  "recipe_amount": "",
  "servings": "",
  "yield": "",
  "level": "",
  "total_time": "",
  "prep_time": "",
  "inactive_time": "",
  "cook_time": "",
  "ingredients": [
    {{
      "name": "",
      "quantity": "",
      "unit": "",
      "notes": "",
      "parsed_name": "",
      "normalized_name": "",
      "confidence": "medium",
      "inferred": true,
      "warning": "",
      "food_review": {{}}
    }}
  ],
  "equipment": [
    ""
  ],
  "instructions": [
    ""
  ],
  "confidence": "low | medium | high",
  "ai_inferred": true,
  "source_type": "cookbook_item_inferred"
}}
"""


def build_recipe_ingredients_regeneration_prompt(recipe_url, recipe_data, cookbook_id="", cookbook_name=""):
    context = build_prompt_context(recipe_url, recipe_data, cookbook_id, cookbook_name)
    context["regeneration_mode"] = {
        "target": "ingredients",
        "action": "replace_entire_ingredients_section",
        "current_ingredients_role": "stale_rows_to_replace",
        "preserve_current_ingredients_by_default": False,
    }
    return f"""
Regenerate only the Ingredients section for this recipe.

Use the recipe title, serving/yield details, menu/source description, equipment, and instructions to build a fresh ingredient list.
The current ingredient rows are included only as stale rows to replace and as examples of possible parsing issues.
Return strict JSON only. Do not include markdown.

Conservative rules:
- Always return a complete replacement ingredient list, even when current ingredients already exist.
- The app will replace the entire current Ingredients section with your returned array.
- Treat context.current.ingredients as stale input. Do not copy, keep, or preserve current ingredient rows just because they are present.
- Reuse a current ingredient only when the recipe title, menu/source description, equipment, or instructions independently support it.
- Do not regenerate recipe title, equipment, instructions, nutrition, categories, or PDFs.
- Do not claim this is an exact restaurant recipe.
- Prefer grocery-friendly ingredient names and put prep details in notes.
- Quantities and units must be strings.
- If exact quantities are uncertain, use realistic estimates based on the servings and instructions.
- Mark ingredient rows inferred=true unless the source/menu description or current recipe text explicitly contains the ingredient name.
- Do not generate unusual ingredient names such as potato milk, chicken milk, beef milk, pork milk, onion milk, garlic milk, or pepper milk unless the exact phrase appears in the source text.
- If a suspicious ingredient appears, keep it in the recipe and add warning/food_review metadata rather than deleting or silently replacing it.
- For Huancaina-style recipes, food_review correction options should prefer evaporated milk or milk over potato milk unless the source text explicitly says potato milk.

Context JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Required response shape:
{{
  "ingredients": [
    {{
      "name": "",
      "quantity": "",
      "unit": "",
      "notes": "",
      "optional": false,
      "purchasable_item": "",
      "purchase_group": "",
      "store_section": "",
      "parsed_name": "",
      "normalized_name": "",
      "confidence": "medium",
      "inferred": true,
      "warning": "",
      "food_review": {{}}
    }}
  ],
  "confidence": "low | medium | high",
  "regeneration_notes": ""
}}
"""


def openai_chat_content(response):
    return response.choices[0].message.content


def request_cookbook_item_details_from_openai(prompt_text, model, model_source, user_id=None):
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        model,
        "cookbook-item-detail-inference",
        [
            {
                "role": "system",
                "content": (
                    "You infer missing home-cooking recipe details from cookbook and restaurant menu item context. "
                    "Return only strict JSON matching the requested shape."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        "[OpenAI] action=cookbook-item-detail-inference "
        f"model={resolved_model} model_source={model_source} "
        f"temperature_included={temperature_included}"
    )
    response = throttled_chat_completion(
        get_openai_client(),
        payload,
        action_name="cookbook-item-detail-inference",
        model=resolved_model,
        kind="menu",
    )
    record_openai_usage(
        response,
        "cookbook-item-detail-inference",
        model=resolved_model,
        user_id=user_id,
    )
    return openai_chat_content(response)


def request_recipe_ingredients_regeneration_from_openai(prompt_text, model, model_source, user_id=None):
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        model,
        "recipe-ingredients-regeneration",
        [
            {
                "role": "system",
                "content": (
                    "You regenerate only the ingredients section of an existing recipe. "
                    "Return only strict JSON matching the requested shape."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        "[OpenAI] action=recipe-ingredients-regeneration "
        f"model={resolved_model} model_source={model_source} "
        f"temperature_included={temperature_included}"
    )
    response = throttled_chat_completion(
        get_openai_client(),
        payload,
        action_name="recipe-ingredients-regeneration",
        model=resolved_model,
        kind="menu",
    )
    record_openai_usage(
        response,
        "recipe-ingredients-regeneration",
        model=resolved_model,
        user_id=user_id,
    )
    return openai_chat_content(response)


def parse_ai_json_response(raw_json):
    parsed = json.loads(clean_json_response(raw_json))
    if isinstance(parsed, dict) and isinstance(parsed.get("recipe"), dict):
        parsed = parsed["recipe"]
    if not isinstance(parsed, dict):
        raise ValueError("Cookbook item inference did not return a JSON object.")
    return parsed


def build_original_ingredient_text(row):
    text = clean_text(row.get("original_recipe_text") or row.get("original_text"))
    if text:
        return text
    parts = [
        clean_text(row.get("quantity")),
        clean_text(row.get("unit")),
        clean_text(row.get("name") or row.get("ingredient")),
    ]
    return clean_text(" ".join(part for part in parts if part))


def normalize_ai_ingredients(value, recipe_context=None):
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        return []

    ingredients = []
    for item in value:
        if isinstance(item, str):
            item = {"original_recipe_text": item, "name": item}
        if not isinstance(item, dict):
            continue

        name = first_clean_text(
            item.get("name"),
            item.get("ingredient"),
            item.get("purchasable_item"),
            item.get("buy_as"),
            item.get("original_recipe_text"),
            item.get("original_text"),
        )
        original_text = build_original_ingredient_text(item)
        if not name and not original_text:
            continue
        store_section = clean_text(item.get("store_section")) or classify_store_section(name or original_text)
        if store_section not in STORE_SECTION_ORDER:
            store_section = classify_store_section(name or original_text)
        row = {
            "section": clean_text(item.get("section")),
            "original_text": original_text or name,
            "quantity": clean_text(item.get("quantity")),
            "recipe_qty": clean_text(item.get("recipe_qty") or item.get("quantity")),
            "unit": clean_text(item.get("unit")),
            "base_quantity": clean_text(item.get("base_quantity") or item.get("quantity")),
            "base_unit": clean_text(item.get("base_unit") or item.get("unit")),
            "ingredient": name or original_text,
            "parsed_name": clean_text(item.get("parsed_name")),
            "normalized_name": clean_text(item.get("normalized_name")),
            "preparation": clean_text(item.get("notes") or item.get("preparation")),
            "confidence": clean_text(item.get("confidence")),
            "inferred": truthy(item.get("inferred")),
            "warning": clean_text(item.get("warning")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
            "purchasable_item": clean_text(item.get("purchasable_item") or item.get("buy_as")),
            "buy_as": clean_text(item.get("buy_as") or item.get("purchasable_item")),
            "purchase_group": clean_text(item.get("purchase_group")),
        }
        ingredients.append(row)

    normalized = {
        **(recipe_context if isinstance(recipe_context, dict) else {}),
        "ingredients": ingredients,
    }
    normalize_extracted_ingredient_fields(normalized)
    return recipe_edit_service.sanitize_ingredients(normalized.get("ingredients", []))


def normalize_ai_equipment(value):
    return recipe_edit_service.sanitize_equipment_list(value)


def normalize_ai_instructions(value):
    return recipe_edit_service.sanitize_instruction_list(value)


def normalize_ai_payload(parsed, recipe_context=None):
    parsed = parsed if isinstance(parsed, dict) else {}
    confidence = clean_text(parsed.get("confidence")).lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    normalized = {
        "recipe_amount": clean_text(parsed.get("recipe_amount")),
        "servings": clean_text(parsed.get("servings")),
        "yield": clean_text(parsed.get("yield") or parsed.get("recipe_yield")),
        "level": clean_text(parsed.get("level") or parsed.get("difficulty")),
        "total_time": clean_text(parsed.get("total_time")),
        "prep_time": clean_text(parsed.get("prep_time")),
        "inactive_time": clean_text(parsed.get("inactive_time")),
        "cook_time": clean_text(parsed.get("cook_time")),
        "ingredients": normalize_ai_ingredients(parsed.get("ingredients"), recipe_context=recipe_context),
        "equipment": normalize_ai_equipment(parsed.get("equipment")),
        "instructions": normalize_ai_instructions(parsed.get("instructions")),
        "confidence": confidence,
        "ai_inferred": True,
        "source_type": clean_text(parsed.get("source_type")) or COOKBOOK_ITEM_SOURCE_TYPE,
    }
    normalize_extracted_equipment_fields(normalized)
    normalized["equipment"] = recipe_edit_service.sanitize_equipment_list(normalized.get("equipment", []))
    normalized["instructions"] = recipe_edit_service.sanitize_instruction_list(normalized.get("instructions", []))
    return normalized


def value_for_field(ai_payload, field):
    if field == "servings":
        return first_clean_text(
            ai_payload.get("servings"),
            ai_payload.get("recipe_amount"),
            ai_payload.get("yield"),
        )
    return ai_payload.get(field)


def apply_ai_payload_to_recipe(recipe_data, ai_payload, fields_to_fill, model, confidence):
    recipe_data = dict(recipe_data) if isinstance(recipe_data, dict) else {}
    updated_fields = []

    for field in fields_to_fill:
        value = value_for_field(ai_payload, field)
        if field in {"ingredients", "equipment", "instructions"}:
            if isinstance(value, list) and value:
                recipe_data[field] = value
                updated_fields.append(field)
            continue
        if not missing_text(value):
            recipe_data[field] = clean_text(value)
            updated_fields.append(field)

    if "recipe_amount" in updated_fields or "yield" in updated_fields:
        if missing_text(recipe_data.get("servings")):
            serving_value = value_for_field(ai_payload, "servings")
            if not missing_text(serving_value):
                recipe_data["servings"] = clean_text(serving_value)
                if "servings" not in updated_fields:
                    updated_fields.append("servings")

    scaling = normalize_recipe_scaling_metadata(recipe_data.get("scaling"))
    if recipe_data.get("servings") and missing_text(scaling.get("base_servings")):
        scaling["base_servings"] = recipe_data["servings"]
    recipe_data["scaling"] = scaling

    inferred_at = utc_now_iso()
    recipe_data["ai_inferred"] = True
    recipe_data["inferred_by_model"] = model
    recipe_data["inferred_at"] = inferred_at
    recipe_data["inference_confidence"] = confidence
    if clean_text(recipe_data.get("source_type")) != MENU_ITEM_SOURCE_TYPE:
        recipe_data["source_type"] = COOKBOOK_ITEM_SOURCE_TYPE

    previous_fields = inferred_fields_for_recipe(recipe_data)
    recipe_data[INFERRED_FIELD_METADATA_KEY] = sorted(previous_fields | set(updated_fields))
    sources = recipe_data.get(INFERRED_FIELD_SOURCE_KEY)
    if not isinstance(sources, dict):
        sources = {}
    for field in updated_fields:
        sources[field] = "ai_inferred"
    recipe_data[INFERRED_FIELD_SOURCE_KEY] = sources

    return recipe_data, updated_fields


def mark_recipe_ingredients_regenerated(recipe_data, model, confidence):
    recipe_data = dict(recipe_data) if isinstance(recipe_data, dict) else {}
    previous_fields = inferred_fields_for_recipe(recipe_data)
    recipe_data[INFERRED_FIELD_METADATA_KEY] = sorted(previous_fields | {"ingredients"})
    sources = recipe_data.get(INFERRED_FIELD_SOURCE_KEY)
    if not isinstance(sources, dict):
        sources = {}
    sources["ingredients"] = "ai_regenerated"
    recipe_data[INFERRED_FIELD_SOURCE_KEY] = sources
    recipe_data["ingredients_regenerated_by_model"] = model
    recipe_data["ingredients_regenerated_at"] = utc_now_iso()
    recipe_data["ingredients_inference_confidence"] = confidence
    return recipe_data


def recipe_data_for_ingredient_regeneration(recipe_url, current_recipe=None):
    recipe_url = clean_text(recipe_url)
    existing_data = recipe_edit_service.load_recipe_output(recipe_url) or {"source_url": recipe_url}
    current_recipe = current_recipe if isinstance(current_recipe, dict) else {}
    recipe_data = {
        **existing_data,
        **current_recipe,
    }
    recipe_data["source_url"] = clean_text(recipe_data.get("source_url")) or recipe_url
    recipe_data["ingredients"] = recipe_edit_service.sanitize_ingredients(
        recipe_data.get("ingredients", []),
        existing_data.get("ingredients", []),
    )
    recipe_data["equipment"] = recipe_edit_service.sanitize_equipment_list(
        recipe_data.get("equipment", []),
        existing_data.get("equipment", []),
    )
    recipe_data["instructions"] = recipe_edit_service.sanitize_instruction_list(
        recipe_data.get("instructions", []),
        existing_data.get("instructions", []),
    )
    recipe_data["scaling"] = normalize_recipe_scaling_metadata(recipe_data.get("scaling"))
    return recipe_data


def regenerate_ingredients_for_recipe(
    recipe_url,
    current_recipe=None,
    cookbook_id="",
    cookbook_name="",
    preview_only=False,
    user_id=None,
):
    recipe_url = clean_text(recipe_url)
    if not recipe_url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = recipe_data_for_ingredient_regeneration(recipe_url, current_recipe)
    cookbook_context = cookbook_context_for_recipe(recipe_url, cookbook_id, cookbook_name)
    item_name = first_clean_text(
        recipe_data.get("menu_item_name"),
        recipe_data.get("recipe_title"),
        recipe_data.get("display_name"),
        recipe_url,
    )
    model, model_source = resolve_cookbook_item_model()
    prompt = build_recipe_ingredients_regeneration_prompt(
        recipe_url,
        recipe_data,
        cookbook_context.get("cookbook_id", ""),
        cookbook_context.get("cookbook_name", ""),
    )

    raw_json = ""
    parsed = {}
    last_error = None
    for attempt in range(COOKBOOK_ITEM_INFERENCE_MAX_RETRIES + 1):
        try:
            raw_json = request_recipe_ingredients_regeneration_from_openai(
                prompt,
                model,
                model_source,
                user_id=user_id,
            )
            parsed = parse_ai_json_response(raw_json)
            break
        except Exception as exc:
            last_error = exc
            openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
            log_inference_event(
                "ingredients_regeneration_openai_failed",
                recipe_id=recipe_url,
                recipe_name=item_name,
                model=model,
                attempt=attempt + 1,
                exception_type=type(exc).__name__,
                error=str(exc),
                openai_error_code=openai_error_code or "",
                openai_error_param=openai_error_param or "",
            )
            if attempt >= COOKBOOK_ITEM_INFERENCE_MAX_RETRIES:
                break
            time.sleep(0.5 * (attempt + 1))

    if last_error is not None and not parsed:
        return {
            "ok": False,
            "recipe_url": recipe_url,
            "recipe_name": item_name,
            "error": str(last_error) or "Unable to regenerate recipe ingredients.",
            "model": model,
            "model_source": model_source,
        }

    generated_ingredients = normalize_ai_ingredients(
        parsed.get("ingredients")
        or parsed.get("regenerated_ingredients")
        or parsed.get("recipe_ingredients"),
        recipe_context=recipe_data,
    )
    if not generated_ingredients:
        return {
            "ok": False,
            "recipe_url": recipe_url,
            "recipe_name": item_name,
            "error": "Ingredient regeneration did not return any usable ingredients.",
            "model": model,
            "model_source": model_source,
            "raw_ai_json": raw_json,
            "parsed_ai_json": parsed,
        }

    confidence = clean_text(parsed.get("confidence")).lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    next_recipe_data = mark_recipe_ingredients_regenerated(recipe_data, model, confidence)
    next_recipe_data["ingredients"] = generated_ingredients

    saved_url = recipe_url
    loaded_recipe = {
        **next_recipe_data,
        "ingredients": generated_ingredients,
    }
    if not preview_only:
        saved = recipe_edit_service.save_editable_recipe(recipe_url, next_recipe_data)
        saved_recipe = saved.get("recipe") if isinstance(saved, dict) else {}
        if isinstance(saved_recipe, dict):
            saved_url = clean_text(saved_recipe.get("source_url")) or saved_url
        saved_output = recipe_edit_service.load_recipe_output(saved_url) or next_recipe_data
        saved_output = mark_recipe_ingredients_regenerated(saved_output, model, confidence)
        recipe_edit_service.save_recipe_output(saved_url, saved_output)
        recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(saved_url), {})
        quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
        recipe_edit_service.update_recipe_ingredient_record(saved_url, quantity, saved_output)
        recipe_edit_service.update_recipe_quantity(saved_url, quantity)
        update_cookbook_recipe_snapshot(cookbook_context.get("cookbook_id", ""), saved_url, saved_output)
        loaded = recipe_edit_service.load_editable_recipe(saved_url)
        loaded_recipe = loaded.get("recipe", {}) if isinstance(loaded, dict) else saved_recipe

    log_inference_event(
        "ingredients_regenerated_preview" if preview_only else "ingredients_regenerated",
        recipe_id=saved_url,
        recipe_name=item_name,
        model=model,
        preview_only=preview_only,
        raw_ai_json=raw_json,
        parsed_ai_json=parsed,
        ingredient_count=len(generated_ingredients),
    )

    return {
        "ok": True,
        "skipped": False,
        "recipe_url": saved_url,
        "recipe_name": item_name,
        "preview_only": bool(preview_only),
        "updated_fields": ["ingredients"],
        "would_update_fields": ["ingredients"] if preview_only else [],
        "model": model,
        "model_source": model_source,
        "confidence": confidence,
        "ingredients": generated_ingredients,
        "recipe": loaded_recipe,
        "raw_ai_json": raw_json,
        "parsed_ai_json": parsed,
        "saved_counts": {
            "ingredients": len(generated_ingredients),
        },
    }


def recipe_context_from_cookbook(cookbook_id):
    cookbook_id = clean_text(cookbook_id)
    payload = cookbook_service.load_cookbooks()
    cookbook = cookbook_service.find_cookbook(payload, cookbook_id)
    if cookbook is None:
        raise ValueError("Cookbook was not found.")
    return cookbook


def update_cookbook_recipe_snapshot(cookbook_id, recipe_url, recipe_data):
    target_key = normalize_recipe_url_key(recipe_url)
    if not cookbook_id or not target_key:
        return

    with cookbook_service.COOKBOOKS_LOCK:
        payload = cookbook_service.load_cookbooks()
        cookbook = cookbook_service.find_cookbook(payload, cookbook_id)
        if cookbook is None:
            return
        for recipe in cookbook.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            if normalize_recipe_url_key(raw_url) != target_key or not isinstance(recipe, dict):
                continue
            recipe["name"] = clean_text(
                recipe.get("name")
                or recipe_data.get("display_name")
                or recipe_data.get("recipe_title")
                or recipe_data.get("menu_item_name")
                or recipe_url
            )
            for field in (
                "recipe_status",
                "servings",
                "level",
                "total_time",
                "prep_time",
                "inactive_time",
                "cook_time",
                "recipe_amount",
                "yield",
                "source_type",
                "menu_section",
                "menu_item_name",
                "menu_price",
                "menu_description",
                "inferred_by_model",
                "inferred_at",
                "inference_confidence",
            ):
                if recipe_data.get(field) not in (None, "", [], {}):
                    recipe[field] = recipe_data.get(field)
            recipe["ai_inferred"] = bool(recipe_data.get("ai_inferred"))
            if "needs_ai_recipe" in recipe_data:
                recipe["needs_ai_recipe"] = bool(recipe_data.get("needs_ai_recipe"))
            recipe["base_servings"] = recipe_data.get("servings") or recipe.get("base_servings", "")
            recipe["equipment_items"] = text_list_for_prompt(recipe_data.get("equipment", []), "equipment")
            recipe["instruction_items"] = text_list_for_prompt(recipe_data.get("instructions", []), "instructions")
            recipe["sections"] = cookbook_service.ingredient_sections_from_recipe_data(
                recipe_data.get("ingredients", [])
            )
            break
        cookbook_service.save_cookbooks(payload)


def save_inferred_recipe(recipe_url, recipe_data, cookbook_id=""):
    recipe_url = clean_text(recipe_url)
    recipe_data["source_url"] = clean_text(recipe_data.get("source_url")) or recipe_url
    recipe_edit_service.save_recipe_output(recipe_data["source_url"], recipe_data)
    if normalize_recipe_url_key(recipe_data["source_url"]) != normalize_recipe_url_key(recipe_url):
        recipe_edit_service.replace_recipe_url(recipe_url, recipe_data["source_url"])
        recipe_edit_service.move_recipe_meta(recipe_url, recipe_data["source_url"])
        recipe_url = recipe_data["source_url"]

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(recipe_url), {})
    quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    recipe_edit_service.update_recipe_ingredient_record(recipe_url, quantity, recipe_data)
    recipe_edit_service.update_recipe_quantity(recipe_url, quantity)
    update_cookbook_recipe_snapshot(cookbook_id, recipe_url, recipe_data)
    return recipe_url


def menu_stub_generation_preview_result(recipe_url, recipe_data, model="", model_source=""):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    recipe_name = first_clean_text(
        recipe_data.get("menu_item_name"),
        recipe_data.get("recipe_title"),
        recipe_data.get("display_name"),
        nested_recipe_raw(recipe_data).get("menu_item_name"),
        nested_recipe_raw(recipe_data).get("recipe_title"),
        recipe_url,
    )
    return {
        "ok": True,
        "skipped": False,
        "recipe_url": recipe_url,
        "recipe_name": recipe_name,
        "preview_only": True,
        "missing_fields": list(DETAIL_FIELDS),
        "updated_fields": [],
        "would_update_fields": ["full_menu_recipe"],
        "generated_menu_recipe": False,
        "model": model or resolve_menu_model(),
        "model_source": model_source or resolve_menu_model_source(),
        "reason": "Menu item stub needs full recipe generation.",
    }


def menu_stub_generation_success_result(recipe_url, result, cookbook_id="", preview_only=False):
    result = result if isinstance(result, dict) else {}
    raw_recipe = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    recipe_data = raw_recipe or recipe_edit_service.load_recipe_output(recipe_url) or {}
    recipe_name = first_clean_text(
        result.get("menu_item_name"),
        recipe_data.get("menu_item_name"),
        recipe_data.get("recipe_title"),
        result.get("recipe_title"),
        result.get("display_name"),
        recipe_url,
    )
    saved_url = recipe_url
    loaded_recipe = recipe_data

    if not preview_only:
        saved_url = save_inferred_recipe(recipe_url, recipe_data, cookbook_id)
        loaded = recipe_edit_service.load_editable_recipe(saved_url)
        loaded_recipe = loaded.get("recipe", {}) if isinstance(loaded, dict) else recipe_data

    return {
        "ok": True,
        "skipped": False,
        "recipe_url": saved_url,
        "recipe_name": recipe_name,
        "preview_only": bool(preview_only),
        "missing_fields": list(DETAIL_FIELDS),
        "updated_fields": list(DETAIL_FIELDS),
        "would_update_fields": list(DETAIL_FIELDS) if preview_only else [],
        "generated_menu_recipe": True,
        "model": result.get("model") or result.get("model_used") or recipe_data.get("model_used") or resolve_menu_model(),
        "model_source": result.get("model_source") or recipe_data.get("model_source") or resolve_menu_model_source(),
        "confidence": recipe_data.get("extraction_confidence") or recipe_data.get("confidence") or "medium",
        "recipe": loaded_recipe,
        "saved_counts": {
            "ingredients": len((recipe_data.get("ingredients") or []) if isinstance(recipe_data.get("ingredients"), list) else []),
            "equipment": len((recipe_data.get("equipment") or []) if isinstance(recipe_data.get("equipment"), list) else []),
            "instructions": len((recipe_data.get("instructions") or []) if isinstance(recipe_data.get("instructions"), list) else []),
        },
    }


def menu_stub_generation_failure_result(recipe_url, recipe_name="", error="", model="", model_source=""):
    return {
        "ok": False,
        "skipped": False,
        "recipe_url": recipe_url,
        "recipe_name": recipe_name or recipe_url,
        "error": error or "Unable to generate a full recipe from this menu item stub.",
        "model": model or resolve_menu_model(),
        "model_source": model_source or resolve_menu_model_source(),
        "generated_menu_recipe": False,
    }


def infer_menu_stub_recipe_for_recipe(recipe_url, recipe_data, cookbook_id="", preview_only=False, user_id=None):
    if preview_only:
        return menu_stub_generation_preview_result(recipe_url, recipe_data)

    result = generate_menu_recipe_from_stub(recipe_url, recipe_data, user_id=user_id)
    if not result.get("ok"):
        return menu_stub_generation_failure_result(
            recipe_url,
            first_clean_text(recipe_data.get("menu_item_name"), recipe_data.get("recipe_title"), recipe_url),
            result.get("error") or "Unable to generate a full recipe from this menu item stub.",
            result.get("model") or result.get("model_used") or resolve_menu_model(),
            result.get("model_source") or resolve_menu_model_source(),
        )

    raw_recipe = result.get("raw") if isinstance(result.get("raw"), dict) else {}
    if not ingredients_have_real_values(raw_recipe.get("ingredients")):
        return menu_stub_generation_failure_result(
            recipe_url,
            result.get("menu_item_name") or recipe_data.get("recipe_title") or recipe_url,
            "Generated menu recipe did not include ingredients.",
            result.get("model") or result.get("model_used") or resolve_menu_model(),
            result.get("model_source") or resolve_menu_model_source(),
        )

    return menu_stub_generation_success_result(recipe_url, result, cookbook_id=cookbook_id)


def log_inference_event(stage, **values):
    safe_values = " ".join(
        f"{key}={json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else repr(value)}"
        for key, value in values.items()
    )
    print(f"[CookbookItemInference] stage={stage} {safe_values}")


def infer_missing_details_for_recipe(
    recipe_url,
    cookbook_id="",
    cookbook_name="",
    overwrite_ai_fields=False,
    preview_only=False,
    user_id=None,
):
    recipe_url = clean_text(recipe_url)
    if not recipe_url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = recipe_edit_service.load_recipe_output(recipe_url) or {"source_url": recipe_url}
    recipe_data.setdefault("source_url", recipe_url)
    cookbook_context = cookbook_context_for_recipe(recipe_url, cookbook_id, cookbook_name)
    if recipe_needs_menu_recipe_generation(recipe_data):
        return infer_menu_stub_recipe_for_recipe(
            recipe_url,
            recipe_data,
            cookbook_context.get("cookbook_id", ""),
            preview_only=preview_only,
            user_id=user_id,
        )

    missing_fields = missing_fields_for_recipe(recipe_data, overwrite_ai_fields=overwrite_ai_fields)
    item_name = first_clean_text(
        recipe_data.get("menu_item_name"),
        recipe_data.get("recipe_title"),
        recipe_data.get("display_name"),
        recipe_url,
    )
    model, model_source = resolve_cookbook_item_model()

    log_inference_event(
        "before",
        recipe_id=recipe_url,
        cookbook_id=cookbook_context.get("cookbook_id", ""),
        menu_item_name=item_name,
        menu_description=clean_text(recipe_data.get("menu_description")),
        detected_missing_fields=missing_fields,
        model=model,
    )

    if not missing_fields:
        return {
            "ok": True,
            "skipped": True,
            "reason": "Recipe already has details.",
            "recipe_url": recipe_url,
            "recipe_name": item_name,
            "missing_fields": [],
            "updated_fields": [],
            "model": model,
            "model_source": model_source,
        }

    prompt = build_cookbook_item_prompt(
        recipe_url,
        recipe_data,
        missing_fields,
        cookbook_context.get("cookbook_id", ""),
        cookbook_context.get("cookbook_name", ""),
    )
    raw_json = ""
    parsed = {}
    last_error = None
    for attempt in range(COOKBOOK_ITEM_INFERENCE_MAX_RETRIES + 1):
        try:
            raw_json = request_cookbook_item_details_from_openai(
                prompt,
                model,
                model_source,
                user_id=user_id,
            )
            parsed = parse_ai_json_response(raw_json)
            break
        except Exception as exc:
            last_error = exc
            openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
            log_inference_event(
                "openai_failed",
                recipe_id=recipe_url,
                menu_item_name=item_name,
                model=model,
                attempt=attempt + 1,
                exception_type=type(exc).__name__,
                error=str(exc),
                openai_error_code=openai_error_code or "",
                openai_error_param=openai_error_param or "",
            )
            if attempt >= COOKBOOK_ITEM_INFERENCE_MAX_RETRIES:
                break
            time.sleep(0.5 * (attempt + 1))

    if last_error is not None and not parsed:
        return {
            "ok": False,
            "recipe_url": recipe_url,
            "recipe_name": item_name,
            "error": str(last_error) or "Unable to infer cookbook item details.",
            "model": model,
            "model_source": model_source,
        }

    normalized = normalize_ai_payload(parsed, recipe_context=recipe_data)
    fields_to_fill = [
        field
        for field in missing_fields
        if should_fill_field(recipe_data, field, overwrite_ai_fields=overwrite_ai_fields)
    ]
    next_recipe_data, updated_fields = apply_ai_payload_to_recipe(
        recipe_data,
        normalized,
        fields_to_fill,
        model,
        normalized.get("confidence", "medium"),
    )
    saved_url = recipe_url
    loaded_recipe = {}
    if preview_only:
        loaded_recipe = next_recipe_data
    else:
        saved_url = save_inferred_recipe(
            recipe_url,
            next_recipe_data,
            cookbook_context.get("cookbook_id", ""),
        )
        loaded = recipe_edit_service.load_editable_recipe(saved_url)
        loaded_recipe = loaded.get("recipe", {})

    log_inference_event(
        "preview" if preview_only else "after",
        recipe_id=saved_url,
        cookbook_id=cookbook_context.get("cookbook_id", ""),
        menu_item_name=item_name,
        model=model,
        preview_only=preview_only,
        raw_ai_json=raw_json,
        parsed_ai_json=parsed,
        saved_ingredient_count=len(loaded_recipe.get("ingredients", [])),
        saved_equipment_count=len(loaded_recipe.get("equipment", [])),
        saved_instruction_count=len(loaded_recipe.get("instructions", [])),
    )

    return {
        "ok": True,
        "skipped": False,
        "recipe_url": saved_url,
        "recipe_name": item_name,
        "preview_only": bool(preview_only),
        "missing_fields": missing_fields,
        "updated_fields": updated_fields,
        "would_update_fields": updated_fields if preview_only else [],
        "model": model,
        "model_source": model_source,
        "confidence": normalized.get("confidence", "medium"),
        "recipe": loaded_recipe,
        "raw_ai_json": raw_json,
        "parsed_ai_json": parsed,
        "saved_counts": {
            "ingredients": len(loaded_recipe.get("ingredients", [])),
            "equipment": len(loaded_recipe.get("equipment", [])),
            "instructions": len(loaded_recipe.get("instructions", [])),
        },
    }


def infer_missing_details_for_cookbook(
    cookbook_id,
    overwrite_ai_fields=False,
    preview_only=False,
    user_id=None,
    progress_callback=None,
):
    cookbook = recipe_context_from_cookbook(cookbook_id)
    recipes = [
        recipe
        for recipe in cookbook.get("recipes", [])
        if isinstance(recipe, dict) and clean_text(recipe.get("url"))
    ]
    results = []
    total = len(recipes)
    if not recipes:
        return {
            "ok": True,
            "cookbook_id": cookbook.get("id", ""),
            "cookbook_name": cookbook.get("name", ""),
            "total_found": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "results": [],
        }

    worker_count = cookbook_item_worker_count(total)
    user_id = user_id or active_user_id()
    log_inference_event(
        "cookbook_start",
        cookbook_id=cookbook.get("id", ""),
        cookbook_name=cookbook.get("name", ""),
        total_found=total,
        max_workers=worker_count,
        preview_only=preview_only,
    )

    def emit_progress(event):
        if not callable(progress_callback):
            return
        try:
            progress_callback(event)
        except Exception as exc:
            log_inference_event("progress_callback_failed", error=str(exc))

    def emit_started(index, recipe, recipe_name=""):
        recipe_url = recipe.get("url", "")
        emit_progress({
            "phase": "details",
            "event": "started",
            "recipe_url": recipe_url,
            "recipe_name": recipe_name or recipe.get("name", "") or recipe_url,
            "index": index,
            "total": total,
        })

    def emit_completed(index, recipe, result, completed):
        emit_progress({
            "phase": "details",
            "event": "completed",
            "recipe_url": result.get("recipe_url") or recipe.get("url", ""),
            "recipe_name": result.get("recipe_name") or recipe.get("name", "") or recipe.get("url", ""),
            "index": index,
            "completed": completed,
            "total": total,
            "ok": bool(result.get("ok")),
            "skipped": bool(result.get("skipped")),
        })

    completed = 0
    detail_entries = []
    menu_stub_entries = []
    cookbook_batch_model, cookbook_batch_model_source = resolve_cookbook_item_model()

    for index, recipe in enumerate(recipes, start=1):
        recipe_url = recipe.get("url", "")
        recipe_data = recipe_edit_service.load_recipe_output(recipe_url) or {"source_url": recipe_url}
        recipe_data.setdefault("source_url", recipe_url)
        recipe_name = first_clean_text(
            recipe_data.get("menu_item_name"),
            recipe_data.get("recipe_title"),
            recipe_data.get("display_name"),
            recipe.get("name"),
            recipe_url,
        )
        if recipe_needs_menu_recipe_generation(recipe_data):
            if preview_only:
                emit_started(index, recipe, recipe_name)
                result = menu_stub_generation_preview_result(
                    recipe_url,
                    recipe_data,
                    cookbook_batch_model,
                    cookbook_batch_model_source,
                )
                results.append(result)
                completed += 1
                emit_completed(index, recipe, result, completed)
                continue

            menu_item = menu_batch_item_from_stub(recipe_url, recipe_data, index - 1)
            if menu_item_name_is_blank_divider(menu_item.get("item_name")):
                result = {
                    "ok": True,
                    "skipped": True,
                    "recipe_url": recipe_url,
                    "recipe_name": recipe_name,
                    "reason": "Menu divider item skipped.",
                    "missing_fields": [],
                    "updated_fields": [],
                    "model": cookbook_batch_model,
                    "model_source": cookbook_batch_model_source,
                }
                results.append(result)
                completed += 1
                emit_completed(index, recipe, result, completed)
                continue

            emit_started(index, recipe, recipe_name)
            menu_stub_entries.append({
                "index": index,
                "recipe": recipe,
                "recipe_url": recipe_url,
                "recipe_name": recipe_name,
                "stub": recipe_data,
                "menu_item": menu_item,
            })
        else:
            detail_entries.append((index, recipe))

    def infer_cookbook_stub_batch(batch):
        return batch, infer_menu_item_recipe_batch(batch, user_id=user_id)

    def process_cookbook_stub_batch(batch, batch_result):
        nonlocal completed

        batch_result = batch_result if isinstance(batch_result, dict) else {}
        result_items = batch_result.get("items") if isinstance(batch_result.get("items"), dict) else {}
        failures = batch_result.get("failures") if isinstance(batch_result.get("failures"), dict) else {}
        batch_model = batch_result.get("model") or cookbook_batch_model
        batch_model_source = batch_result.get("model_source") or cookbook_batch_model_source
        for entry in batch:
            recipe = entry["recipe"]
            recipe_url = entry["recipe_url"]
            menu_item = entry.get("menu_item") if isinstance(entry.get("menu_item"), dict) else {}
            item_id = clean_text(menu_item.get("menu_item_id"))
            item_result = result_items.get(item_id)
            item_failure = failures.get(item_id) if item_id else None
            item_failure = item_failure if isinstance(item_failure, dict) else {}
            if not isinstance(item_result, dict):
                result = menu_stub_generation_failure_result(
                    recipe_url,
                    entry.get("recipe_name") or recipe.get("name", ""),
                    item_failure.get("error")
                    or batch_result.get("error_message")
                    or batch_result.get("error")
                    or (f"Batch response did not include menu_item_id {item_id}." if item_id else "Batch response did not include this item."),
                    item_failure.get("model") or batch_model,
                    item_failure.get("model_source") or batch_model_source,
                )
            else:
                result = apply_menu_batch_inference_to_stub(
                    recipe_url,
                    entry.get("stub") or {},
                    menu_item,
                    item_result,
                    model=batch_model,
                    model_source=batch_model_source,
                )
                if not result.get("ok"):
                    result = menu_stub_generation_failure_result(
                        recipe_url,
                        entry.get("recipe_name") or recipe.get("name", ""),
                        result.get("error") or "Unable to save predicted menu recipe.",
                        batch_model,
                        batch_model_source,
                    )
                else:
                    raw_recipe = result.get("raw") if isinstance(result.get("raw"), dict) else {}
                    if not ingredients_have_real_values(raw_recipe.get("ingredients")):
                        result = menu_stub_generation_failure_result(
                            recipe_url,
                            entry.get("recipe_name") or recipe.get("name", ""),
                            "Generated menu recipe did not include ingredients.",
                            batch_model,
                            batch_model_source,
                        )
                    else:
                        result = menu_stub_generation_success_result(
                            recipe_url,
                            result,
                            cookbook_id=cookbook.get("id", ""),
                        )
            results.append(result)
            completed += 1
            emit_completed(entry["index"], recipe, result, completed)

    menu_stub_batches = cookbook_item_inference_batches(menu_stub_entries)
    if len(menu_stub_batches) > 1 and worker_count > 1:
        with ThreadPoolExecutor(max_workers=min(worker_count, len(menu_stub_batches))) as executor:
            future_batches = {
                executor.submit(infer_cookbook_stub_batch, batch): batch
                for batch in menu_stub_batches
            }
            for future in as_completed(future_batches):
                batch = future_batches[future]
                try:
                    completed_batch, batch_result = future.result()
                except Exception as exc:
                    error_code, error_message = classify_vision_ai_exception(exc)
                    batch_result = {
                        "ok": False,
                        "items": {},
                        "failures": {},
                        "error_code": error_code,
                        "error_message": normalize_openai_error_message(error_code, error_message, fallback=str(exc)),
                        "technical_message": str(exc),
                        "exception_type": type(exc).__name__,
                        "model": cookbook_batch_model,
                        "model_source": cookbook_batch_model_source,
                    }
                    completed_batch = batch
                process_cookbook_stub_batch(completed_batch, batch_result)
    else:
        for batch in menu_stub_batches:
            batch, batch_result = infer_cookbook_stub_batch(batch)
            process_cookbook_stub_batch(batch, batch_result)

    for index, recipe in detail_entries:
        emit_started(index, recipe)
        try:
            result = infer_missing_details_for_recipe(
                recipe.get("url", ""),
                cookbook_id=cookbook.get("id", ""),
                cookbook_name=cookbook.get("name", ""),
                overwrite_ai_fields=overwrite_ai_fields,
                preview_only=preview_only,
                user_id=user_id,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "recipe_url": recipe.get("url", ""),
                "recipe_name": recipe.get("name", "") or recipe.get("url", ""),
                "error": str(exc) or "Unable to infer this recipe.",
            }
            log_inference_event(
                "item_failed",
                recipe_id=result["recipe_url"],
                recipe_name=result["recipe_name"],
                error=result["error"],
            )
        results.append(result)
        completed += 1
        emit_completed(index, recipe, result, completed)

    updated = sum(1 for result in results if result.get("ok") and not result.get("skipped"))
    skipped = sum(1 for result in results if result.get("ok") and result.get("skipped"))
    failed = sum(1 for result in results if not result.get("ok"))
    return {
        "ok": failed == 0 or updated > 0 or skipped > 0,
        "cookbook_id": cookbook.get("id", ""),
        "cookbook_name": cookbook.get("name", ""),
        "total_found": total,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "preview_only": bool(preview_only),
        "max_workers": worker_count,
        "results": sorted(results, key=lambda item: clean_text(item.get("recipe_name") or item.get("recipe_url"))),
    }
