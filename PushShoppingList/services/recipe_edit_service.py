import json
import os
import uuid
from urllib.parse import urlparse

from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.ingredient_text_review_service import annotate_ingredients_for_food_review
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import build_video_text_pdf_html
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import extract_ingredients_from_result
from PushShoppingList.services.recipe_extract_service import fetch_recipe_page
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_recipe_scaling_metadata
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_extract_service import write_recipe_page_pdf
from PushShoppingList.services.purchase_mapping_service import apply_purchase_mapping_to_ingredient
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import recipe_ingredients_for_key
from PushShoppingList.services.recipe_ingredient_service import remove_unused_ingredients_from_shopping_list
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.recipe_url_service import load_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity
from PushShoppingList.services.recipe_quantity_service import update_recipe_quantity
from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients


NUTRITION_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "polyunsaturated_fat",
    "monounsaturated_fat",
    "trans_fat",
    "cholesterol",
    "sodium",
    "potassium",
    "fiber",
    "sugar",
    "vitamin_a",
    "vitamin_c",
    "calcium",
    "iron",
]
DEFAULT_MANUAL_NUTRITION_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "cholesterol",
    "sodium",
    "fiber",
    "sugar",
]
NUTRITION_ESTIMATE_FIELDS = [
    field
    for field in DEFAULT_MANUAL_NUTRITION_FIELDS
    if field != "serving_basis"
]


def create_new_recipe():
    source_url = f"manual://recipe/{uuid.uuid4().hex}"
    recipe_data = {
        "source_url": source_url,
        "recipe_title": "New Recipe",
        "servings": "",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "nutrition": empty_recipe_nutrition(),
        "scaling": normalize_recipe_scaling_metadata(),
    }

    save_recipe_output(source_url, recipe_data)
    save_recipe_urls(load_recipe_urls() + [source_url])
    save_recipe_url_quantity(source_url, 1)
    save_recipe_url_name(source_url, "New Recipe")
    update_recipe_ingredient_record(source_url, 1, recipe_data)

    result = load_editable_recipe(source_url)
    result["url"] = source_url
    return result


def empty_recipe_nutrition():
    return {
        **{field: "" for field in DEFAULT_MANUAL_NUTRITION_FIELDS},
        "serving_basis": "per serving",
        "other": [],
    }


def load_editable_recipe(url):
    url = str(url or "").strip()
    recipe_data = load_recipe_output(url) or {"source_url": url}
    meta = load_recipe_ingredients().get(normalize_recipe_url_key(url), {})
    pdf = editable_recipe_pdf_info(url)
    scaling = normalize_recipe_scaling_metadata(recipe_data.get("scaling"))
    if recipe_data.get("servings") and not scaling.get("base_servings"):
        scaling["base_servings"] = str(recipe_data.get("servings") or "").strip()

    return {
        "ok": True,
        "recipe": {
            "source_url": recipe_data.get("source_url") or url,
            "source_display_url": editable_recipe_source_display_url(recipe_data.get("source_url") or url),
            "type": recipe_url_type(url),
            "display_name": meta.get("name") or recipe_data.get("recipe_title") or "",
            "quantity": normalize_recipe_quantity(meta.get("quantity", 1)),
            "recipe_title": recipe_data.get("recipe_title") or "",
            "servings": recipe_data.get("servings") or "",
            "scaling": scaling,
            "ingredients": annotate_ingredients_for_food_review(
                normalize_edit_ingredients(recipe_data.get("ingredients", []))
            ),
            "equipment": normalize_text_rows(recipe_data.get("equipment", [])),
            "instructions": normalize_instruction_rows(recipe_data.get("instructions", [])),
            "nutrition": normalize_nutrition_rows(
                recipe_data.get("nutrition", {}),
                include_defaults=recipe_url_type(url) == "Manual",
            ),
            "pdf_path": pdf["path"],
            "pdf_available": pdf["available"],
        },
        "food_rules": load_food_rules(),
        "store_sections": list(STORE_SECTION_ORDER.keys()),
    }


def editable_recipe_pdf_info(url):
    pdf_path = recipe_archive_pdf_path(url)

    return {
        "path": str(pdf_path),
        "available": pdf_path.exists(),
    }


def editable_recipe_source_display_url(url):
    if recipe_url_type(url) == "File":
        return str(recipe_archive_pdf_path(url))

    return url


def create_editable_recipe_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(url)

    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    title = (
        recipe_data.get("recipe_title")
        or load_recipe_ingredients().get(normalize_recipe_url_key(url), {}).get("name")
        or "Recipe"
    )
    html_text = build_video_text_pdf_html(
        url,
        "",
        title,
        recipe_data=recipe_data,
    )
    pdf_path = recipe_archive_pdf_path(url)
    saved_path = write_recipe_page_pdf(url, html_text, None, pdf_path)

    return {
        "ok": True,
        "url": url,
        "pdf_path": str(saved_path),
        "pdf_available": True,
    }


def create_source_url_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Source URL is required."}

    if not is_web_source_url(url):
        return create_editable_recipe_pdf(url)

    try:
        fetch_recipe_page(url)
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": f"Webpage PDF creation failed: {exc}",
        }

    pdf_path = recipe_archive_pdf_path(url)

    return {
        "ok": pdf_path.exists(),
        "url": url,
        "pdf_path": str(pdf_path),
        "pdf_available": pdf_path.exists(),
        "error": None if pdf_path.exists() else "PDF file was not created.",
    }


def is_web_source_url(url):
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def delete_editable_recipe_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    pdf_path = recipe_archive_pdf_path(url)

    try:
        pdf_path.unlink(missing_ok=True)
    except PermissionError:
        return {
            "ok": False,
            "error": "Close the PDF before deleting it.",
            "url": url,
            "pdf_path": str(pdf_path),
            "pdf_available": pdf_path.exists(),
        }

    return {
        "ok": True,
        "url": url,
        "pdf_path": str(pdf_path),
        "pdf_available": False,
    }


def save_editable_recipe(original_url, payload):
    original_url = str(original_url or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    source_url = str(payload.get("source_url") or original_url).strip()

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not source_url:
        source_url = original_url

    previous_recipe_data = load_recipe_ingredients()
    previous_ingredients = recipe_ingredients_for_key(
        normalize_recipe_url_key(original_url),
        previous_recipe_data,
    )
    existing_data = load_recipe_output(original_url) or {"source_url": original_url}
    recipe_data = {
        **existing_data,
        "source_url": source_url,
        "recipe_title": str(payload.get("recipe_title") or "").strip(),
        "servings": str(payload.get("servings") or "").strip(),
        "scaling": normalize_recipe_scaling_metadata(
            payload.get("scaling") or existing_data.get("scaling")
        ),
        "ingredients": sanitize_ingredients(payload.get("ingredients", [])),
        "equipment": sanitize_text_list(payload.get("equipment", [])),
        "instructions": sanitize_instruction_list(payload.get("instructions", [])),
        "nutrition": sanitize_nutrition(payload.get("nutrition", [])),
    }
    if recipe_data["servings"] and not recipe_data["scaling"].get("base_servings"):
        recipe_data["scaling"]["base_servings"] = recipe_data["servings"]

    normalize_extracted_ingredient_fields(recipe_data)
    normalize_extracted_equipment_fields(recipe_data)
    save_recipe_output(source_url, recipe_data)

    if normalize_recipe_url_key(source_url) != normalize_recipe_url_key(original_url):
        replace_recipe_url(original_url, source_url)
        move_recipe_meta(original_url, source_url)

    quantity = normalize_recipe_quantity(payload.get("quantity", 1))
    display_name = str(payload.get("display_name") or "").strip()

    save_recipe_url_quantity(source_url, quantity)
    save_recipe_url_name(source_url, display_name)
    update_recipe_ingredient_record(source_url, quantity, recipe_data)
    update_recipe_quantity(source_url, quantity)
    sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients)

    return load_editable_recipe(source_url)


def estimate_recipe_nutrition(payload):
    payload = payload if isinstance(payload, dict) else {}

    if not payload.get("ingredients"):
        return {
            "ok": False,
            "error": "Add at least one ingredient before estimating nutrition.",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    serving_basis = recipe_nutrition_serving_basis(payload.get("nutrition"))
    prompt = build_nutrition_estimate_prompt(payload, serving_basis)

    try:
        response = get_openai_client().chat.completions.create(
            model=os.getenv("OPENAI_NUTRITION_MODEL", MODEL),
            messages=[
                {
                    "role": "system",
                    "content": "You estimate recipe nutrition and return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        data = json.loads(clean_json_response(content))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Nutrition estimate failed: {exc}",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "Nutrition estimate returned an unexpected response.",
        }

    nutrition = data.get("nutrition") if isinstance(data.get("nutrition"), dict) else data

    rows = [{"key": "serving_basis", "value": serving_basis}]
    for key in NUTRITION_ESTIMATE_FIELDS:
        value = normalize_estimated_nutrition_value(key, nutrition.get(key))
        rows.append({"key": key, "value": value})

    return {
        "ok": True,
        "nutrition": rows,
    }


def recipe_nutrition_serving_basis(nutrition_rows):
    if isinstance(nutrition_rows, dict):
        return str(nutrition_rows.get("serving_basis") or "per serving").strip() or "per serving"

    if isinstance(nutrition_rows, list):
        for row in nutrition_rows:
            if not isinstance(row, dict):
                continue

            key = str(row.get("key") or row.get("label") or "").strip().lower()
            if key == "serving_basis":
                return str(row.get("value") or "per serving").strip() or "per serving"

    return "per serving"


def build_nutrition_estimate_prompt(recipe, serving_basis):
    recipe_payload = {
        "title": str(recipe.get("recipe_title") or recipe.get("display_name") or "").strip(),
        "servings": str(recipe.get("servings") or "").strip(),
        "serving_basis": serving_basis,
        "ingredients": nutrition_prompt_ingredients(recipe.get("ingredients", [])),
        "equipment": sanitize_text_list(recipe.get("equipment", [])),
        "instructions": nutrition_prompt_instructions(recipe.get("instructions", [])),
    }

    return f"""
Estimate the nutrition values for this recipe.

Return ONLY valid JSON with this exact shape:
{{
  "nutrition": {{
    "calories": "659 kcal",
    "carbohydrates": "57 g",
    "protein": "17 g",
    "fat": "40 g",
    "saturated_fat": "16 g",
    "cholesterol": "37 mg",
    "sodium": "649 mg",
    "fiber": "3 g",
    "sugar": "0.2 g"
  }}
}}

Rules:
- Estimate values for the serving basis: {serving_basis}.
- Use the recipe servings to divide the full recipe when servings are available.
- Use the provided ingredient quantities, units, and preparation details.
- Use common USDA-style approximations when exact brands are unknown.
- Do not invent extra ingredients.
- Return strings with units.
- calories must use kcal.
- carbohydrates, protein, fat, saturated_fat, fiber, and sugar must use g.
- cholesterol and sodium must use mg.
- If a value cannot be estimated, use an empty string.

Recipe JSON:
{json.dumps(recipe_payload, ensure_ascii=False, indent=2)}
"""


def nutrition_prompt_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            continue

        rows.append({
            "ingredient": str(item.get("ingredient") or "").strip(),
            "quantity": str(item.get("quantity") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "preparation": str(item.get("preparation") or "").strip(),
            "original_text": str(item.get("original_text") or "").strip(),
        })

    return [
        row
        for row in rows
        if row["ingredient"] or row["original_text"]
    ]


def nutrition_prompt_instructions(instructions):
    if not isinstance(instructions, list):
        return []

    rows = []
    for item in instructions:
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_estimated_nutrition_value(key, value):
    if value is None:
        return ""

    if isinstance(value, dict):
        amount = str(value.get("amount") or value.get("value") or "").strip()
        unit = str(value.get("unit") or "").strip()
        return f"{amount} {unit}".strip()

    if isinstance(value, (int, float)):
        if key == "calories":
            return f"{value:g} kcal"

        if key in {"cholesterol", "sodium"}:
            return f"{value:g} mg"

        return f"{value:g} g"

    return str(value or "").strip()


def sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients):
    ingredients = extract_ingredients_from_result(recipe_data)

    if ingredients:
        add_items(ingredients)

    remove_unused_ingredients_from_shopping_list(
        previous_ingredients,
        load_recipe_ingredients(),
    )
    sort_ingredients()


def load_recipe_output(url):
    recipe_key = normalize_recipe_url_key(url)

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if normalize_recipe_url_key(data.get("source_url", "")) == recipe_key:
            return data

    return None


def save_recipe_output(url, recipe_data):
    json_path = OUTPUT_FOLDER / f"{safe_filename(url)}.json"
    json_path.write_text(
        json.dumps(recipe_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def replace_recipe_url(original_url, source_url):
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)
    next_urls = []
    replaced = False

    for url in load_recipe_urls():
        if normalize_recipe_url_key(url) == original_key:
            if not any(normalize_recipe_url_key(item) == source_key for item in next_urls):
                next_urls.append(source_url)
            replaced = True
        else:
            next_urls.append(url)

    if not replaced:
        next_urls.append(source_url)

    save_recipe_urls(next_urls)


def move_recipe_meta(original_url, source_url):
    data = load_recipe_ingredients()
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)

    if original_key == source_key or original_key not in data:
        return

    existing = data.pop(original_key)
    destination = data.get(source_key, {})
    destination.update(existing)
    destination["url"] = source_url
    data[source_key] = destination
    save_recipe_ingredients(data)


def update_recipe_ingredient_record(url, quantity, recipe_data):
    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    existing = data.get(key, {})
    cover_image = recipe_data.get("cover_image") or existing.get("cover_image")
    record = {
        "url": url,
        "quantity": quantity,
        "name": existing.get("name"),
        "scaled_servings": existing.get("scaled_servings"),
        "scaled_ingredients": existing.get("scaled_ingredients", {}),
        "ingredients": extract_ingredients_from_result(recipe_data),
    }

    if cover_image:
        record["cover_image"] = cover_image

    data[key] = record
    save_recipe_ingredients(data)


def normalize_edit_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = [
        apply_purchase_mapping_to_ingredient({
            "section": item.get("section") or "",
            "original_text": item.get("original_text") or "",
            "quantity": item.get("quantity") or "",
            "recipe_qty": item.get("recipe_qty") or item.get("quantity") or "",
            "unit": item.get("unit") or "",
            "base_quantity": item.get("base_quantity") or item.get("quantity") or "",
            "base_unit": item.get("base_unit") or item.get("unit") or "",
            "ingredient": item.get("ingredient") or "",
            "preparation": item.get("preparation") or "",
            "optional": bool(item.get("optional")),
            "store_section": item.get("store_section") or classify_store_section(item.get("ingredient") or ""),
            "purchasable_item": item.get("purchasable_item") or item.get("buy_as") or "",
            "purchase_group": item.get("purchase_group") or "",
        })
        for item in ingredients
        if isinstance(item, dict)
    ]
    return rows


def normalize_text_rows(value):
    if isinstance(value, str):
        return [value] if value.strip() else []

    if not isinstance(value, list):
        return []

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("text") or item.get("equipment") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_instruction_rows(value):
    if not isinstance(value, list):
        return [
            {
                "step_number": index,
                "instruction": text,
            }
            for index, text in enumerate(normalize_text_rows(value), start=1)
        ]

    rows = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
        else:
            text = str(item or "").strip()
            step_number = index

        if text:
            rows.append({
                "step_number": step_number,
                "instruction": text,
            })

    return sorted(rows, key=lambda item: item["step_number"])


def normalize_nutrition_rows(nutrition, include_defaults=False):
    if not isinstance(nutrition, dict):
        return []

    rows = []
    included = set()

    if include_defaults:
        for key in DEFAULT_MANUAL_NUTRITION_FIELDS:
            fallback = "per serving" if key == "serving_basis" else ""
            rows.append({"key": key, "value": str(nutrition.get(key) or fallback)})
            included.add(key)

    for key in NUTRITION_FIELDS:
        if key in included or not nutrition.get(key):
            continue

        rows.append({"key": key, "value": str(nutrition.get(key) or "")})
        included.add(key)

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                key = str(item.get("label") or item.get("name") or "").strip()
                value = str(item.get("value") or item.get("amount") or "").strip()
                if key or value:
                    rows.append({"key": key, "value": value})

    return rows


def sanitize_ingredients(value):
    if not isinstance(value, list):
        return []

    ingredients = []
    for item in value:
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient") or "").strip()
        original_text = str(item.get("original_text") or "").strip()

        if not name and not original_text:
            continue

        store_section = classify_store_section(name or original_text)
        base_quantity = nullable_string(item.get("base_quantity"))
        base_unit = nullable_string(item.get("base_unit"))

        row = {
            "section": nullable_string(item.get("section")),
            "original_text": original_text,
            "quantity": nullable_string(item.get("quantity")),
            "recipe_qty": nullable_string(item.get("recipe_qty") or item.get("quantity")),
            "unit": nullable_string(item.get("unit")),
            "base_quantity": base_quantity or nullable_string(item.get("quantity")),
            "base_unit": base_unit or nullable_string(item.get("unit")),
            "ingredient": name or original_text,
            "preparation": nullable_string(item.get("preparation")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
            "purchasable_item": nullable_string(item.get("purchasable_item") or item.get("buy_as")),
            "purchase_group": nullable_string(item.get("purchase_group")),
        }
        ingredients.append(apply_purchase_mapping_to_ingredient(row))

    return ingredients


def sanitize_text_list(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    return [
        str(item or "").strip()
        for item in value
        if str(item or "").strip()
    ]


def sanitize_instruction_list(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    instructions = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
        else:
            text = str(item or "").strip()
            step_number = index

        if not text:
            continue

        instructions.append({
            "section": None,
            "step_number": step_number,
            "instruction": text,
            "temperature": None,
            "time": None,
            "equipment_used": [],
        })

    return sorted(instructions, key=lambda item: item["step_number"])


def normalize_step_number(value, fallback):
    try:
        step_number = float(value)
    except (TypeError, ValueError):
        return fallback

    if step_number <= 0:
        return fallback

    if step_number.is_integer():
        return int(step_number)

    return step_number


def sanitize_nutrition(value):
    if not isinstance(value, list):
        return {}

    nutrition = {}
    other = []

    for item in value:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key") or "").strip()
        value_text = str(item.get("value") or "").strip()

        if not key or not value_text:
            continue

        normalized_key = key.lower().replace(" ", "_").replace("-", "_")
        if normalized_key in NUTRITION_FIELDS:
            nutrition[normalized_key] = value_text
        else:
            other.append({"label": key, "value": value_text})

    if other:
        nutrition["other"] = other

    return nutrition


def nullable_string(value):
    text = str(value or "").strip()
    return text or None
