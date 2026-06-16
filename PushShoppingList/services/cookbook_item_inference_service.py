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
from PushShoppingList.services.recipe_extract_service import build_openai_chat_payload
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
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
      "notes": ""
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


def normalize_ai_ingredients(value):
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
            "preparation": clean_text(item.get("notes") or item.get("preparation")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
            "purchasable_item": clean_text(item.get("purchasable_item") or item.get("buy_as")),
            "buy_as": clean_text(item.get("buy_as") or item.get("purchasable_item")),
            "purchase_group": clean_text(item.get("purchase_group")),
        }
        ingredients.append(row)

    normalized = {"ingredients": ingredients}
    normalize_extracted_ingredient_fields(normalized)
    return recipe_edit_service.sanitize_ingredients(normalized.get("ingredients", []))


def normalize_ai_equipment(value):
    return recipe_edit_service.sanitize_equipment_list(value)


def normalize_ai_instructions(value):
    return recipe_edit_service.sanitize_instruction_list(value)


def normalize_ai_payload(parsed):
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
        "ingredients": normalize_ai_ingredients(parsed.get("ingredients")),
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

    normalized = normalize_ai_payload(parsed)
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

    def run_one(index, recipe):
        recipe_url = recipe.get("url", "")
        recipe_name = recipe.get("name", "") or recipe_url
        emit_progress({
            "phase": "details",
            "event": "started",
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
            "index": index,
            "total": total,
        })
        return infer_missing_details_for_recipe(
            recipe_url,
            cookbook_id=cookbook.get("id", ""),
            cookbook_name=cookbook.get("name", ""),
            overwrite_ai_fields=overwrite_ai_fields,
            preview_only=preview_only,
            user_id=user_id,
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_recipe = {
            executor.submit(run_one, index, recipe): (index, recipe)
            for index, recipe in enumerate(recipes, start=1)
        }
        completed = 0
        for future in as_completed(future_to_recipe):
            index, recipe = future_to_recipe[future]
            try:
                result = future.result()
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
