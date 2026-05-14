import json

from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import extract_ingredients_from_result
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.recipe_url_service import load_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity


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


def load_editable_recipe(url):
    url = str(url or "").strip()
    recipe_data = load_recipe_output(url) or {"source_url": url}
    meta = load_recipe_ingredients().get(normalize_recipe_url_key(url), {})

    return {
        "ok": True,
        "recipe": {
            "source_url": recipe_data.get("source_url") or url,
            "type": recipe_url_type(url),
            "display_name": meta.get("name") or recipe_data.get("recipe_title") or "",
            "quantity": normalize_recipe_quantity(meta.get("quantity", 1)),
            "recipe_title": recipe_data.get("recipe_title") or "",
            "servings": recipe_data.get("servings") or "",
            "ingredients": normalize_edit_ingredients(recipe_data.get("ingredients", [])),
            "equipment": normalize_text_rows(recipe_data.get("equipment", [])),
            "instructions": normalize_instruction_rows(recipe_data.get("instructions", [])),
            "nutrition": normalize_nutrition_rows(recipe_data.get("nutrition", {})),
        },
        "food_rules": load_food_rules(),
        "store_sections": list(STORE_SECTION_ORDER.keys()),
    }


def save_editable_recipe(original_url, payload):
    original_url = str(original_url or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    source_url = str(payload.get("source_url") or original_url).strip()

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not source_url:
        source_url = original_url

    existing_data = load_recipe_output(original_url) or {"source_url": original_url}
    recipe_data = {
        **existing_data,
        "source_url": source_url,
        "recipe_title": str(payload.get("recipe_title") or "").strip(),
        "servings": str(payload.get("servings") or "").strip(),
        "ingredients": sanitize_ingredients(payload.get("ingredients", [])),
        "equipment": sanitize_text_list(payload.get("equipment", [])),
        "instructions": sanitize_text_list(payload.get("instructions", [])),
        "nutrition": sanitize_nutrition(payload.get("nutrition", [])),
    }

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

    return load_editable_recipe(source_url)


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
    data[key] = {
        "url": url,
        "quantity": quantity,
        "name": existing.get("name"),
        "scaled_servings": existing.get("scaled_servings"),
        "scaled_ingredients": existing.get("scaled_ingredients", {}),
        "ingredients": extract_ingredients_from_result(recipe_data),
    }
    save_recipe_ingredients(data)


def normalize_edit_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    return [
        {
            "section": item.get("section") or "",
            "original_text": item.get("original_text") or "",
            "quantity": item.get("quantity") or "",
            "unit": item.get("unit") or "",
            "ingredient": item.get("ingredient") or "",
            "preparation": item.get("preparation") or "",
            "optional": bool(item.get("optional")),
            "store_section": item.get("store_section") or classify_store_section(item.get("ingredient") or ""),
        }
        for item in ingredients
        if isinstance(item, dict)
    ]


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
        return normalize_text_rows(value)

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_nutrition_rows(nutrition):
    if not isinstance(nutrition, dict):
        return []

    rows = [
        {"key": key, "value": str(nutrition.get(key) or "")}
        for key in NUTRITION_FIELDS
        if nutrition.get(key)
    ]

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

        store_section = str(item.get("store_section") or "").strip().upper()
        if store_section not in STORE_SECTION_ORDER:
            store_section = classify_store_section(name or original_text)

        ingredients.append({
            "section": nullable_string(item.get("section")),
            "original_text": original_text,
            "quantity": nullable_string(item.get("quantity")),
            "unit": nullable_string(item.get("unit")),
            "ingredient": name or original_text,
            "preparation": nullable_string(item.get("preparation")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
        })

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
