import json
import os
import re
from fractions import Fraction

from openai import OpenAI

from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients


MODEL = "gpt-4o-mini"
client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=30)

    return client


def update_recipe_quantity(url, quantity):
    quantity = normalize_recipe_quantity(quantity)
    recipe_data = load_saved_recipe_output(url)
    scaled = calculate_scaled_recipe_values(recipe_data, quantity)

    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    recipe_record = data.get(key, {"url": url, "ingredients": []})
    recipe_record["url"] = url
    recipe_record["quantity"] = quantity
    recipe_record["scaled_servings"] = scaled.get("servings")
    recipe_record["scaled_ingredients"] = scaled.get("ingredients", {})
    data[key] = recipe_record
    save_recipe_ingredients(data)

    return {
        "ok": True,
        "url": url,
        "quantity": quantity,
        "servings": recipe_record["scaled_servings"],
        "ingredients": recipe_record["scaled_ingredients"],
    }


def update_recipe_ingredient_quantity(url, ingredient_name, quantity, unit):
    recipe_path, recipe_data = load_saved_recipe_output_with_path(url)
    ingredient_name = str(ingredient_name or "").strip()
    quantity = str(quantity or "").strip()
    unit = str(unit or "").strip()

    if not recipe_path or not recipe_data or not ingredient_name:
        return {
            "ok": False,
            "error": "Recipe ingredient not found.",
        }

    target_key = ingredient_key(ingredient_name)
    updated_item = None

    for item in recipe_data.get("ingredients", []) or []:
        if not isinstance(item, dict):
            continue

        if ingredient_key(item.get("ingredient")) != target_key:
            continue

        item["quantity"] = quantity or None
        item["recipe_qty"] = quantity or None
        item["unit"] = unit or None
        updated_item = item
        break

    if not updated_item:
        return {
            "ok": False,
            "error": "Recipe ingredient not found.",
        }

    recipe_path.write_text(
        json.dumps(recipe_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(url), {})
    recipe_quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    scaled = update_recipe_quantity(url, recipe_quantity)

    return {
        "ok": True,
        "url": url,
        "ingredient": updated_item.get("ingredient"),
        "quantity": updated_item.get("quantity"),
        "unit": updated_item.get("unit"),
        "recipe_quantity": recipe_quantity,
        "scaled": scaled,
    }


def calculate_scaled_recipe_values(recipe_data, quantity):
    if not recipe_data:
        return {
            "servings": None,
            "ingredients": {},
        }

    local_scaled = calculate_scaled_values_locally(recipe_data, quantity)

    if os.getenv("OPENAI_API_KEY"):
        try:
            api_scaled = calculate_scaled_values_with_openai(recipe_data, quantity)
            return repair_unscaled_api_values(recipe_data, quantity, api_scaled, local_scaled)
        except Exception as exc:
            print(f"Recipe quantity API scaling failed; using local fallback: {exc}")

    return local_scaled


def repair_unscaled_api_values(recipe_data, quantity, api_scaled, local_scaled):
    if quantity <= 1:
        return api_scaled

    api_ingredients = api_scaled.get("ingredients", {})
    local_ingredients = local_scaled.get("ingredients", {})

    for item in recipe_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient", "") or "").strip()
        if not name:
            continue

        api_value = api_ingredients.get(name) or api_ingredients.get(ingredient_key(name))
        local_value = local_ingredients.get(name)

        if not isinstance(api_value, dict) or not isinstance(local_value, dict):
            continue

        original_display = format_quantity_display(item.get("quantity"), item.get("unit"))
        api_display = str(api_value.get("display") or "").strip()

        if original_display and api_display == original_display:
            api_ingredients[name] = local_value

    api_scaled["ingredients"] = api_ingredients
    return api_scaled


def calculate_scaled_values_with_openai(recipe_data, quantity):
    ingredients = [
        {
            "ingredient": item.get("ingredient"),
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
        }
        for item in recipe_data.get("ingredients", [])
        if isinstance(item, dict) and item.get("ingredient")
    ]

    prompt = f"""
Scale this recipe from 1 batch to {quantity} batches.

Return ONLY valid JSON.

Rules:
- Use the original quantities and units as the source of truth.
- Multiply every ingredient quantity by {quantity}.
- Simplify fractions.
- Preserve ranges as ranges.
- Pluralize units naturally when needed.
- If a quantity is missing, return display as an empty string.
- Scale the servings text from the original servings field.
- Do not add ingredients.
- Do not remove ingredients.

Original servings:
{recipe_data.get("servings")}

Ingredients:
{json.dumps(ingredients, ensure_ascii=False)}

Output shape:
{{
  "servings": "scaled servings text or null",
  "ingredients": {{
    "ingredient name": {{
      "quantity": "scaled quantity or null",
      "unit": "unit or null",
      "display": "quantity and unit together, or empty string"
    }}
  }}
}}
"""

    response = get_openai_client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You scale recipe ingredient quantities and return only valid JSON.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    record_openai_usage(response, "recipe-quantity-scaling", model=MODEL)
    data = json.loads(clean_json_response(response.choices[0].message.content))
    return normalize_scaled_values(data)


def calculate_scaled_values_locally(recipe_data, quantity):
    scaled_ingredients = {}

    for item in recipe_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient", "") or "").strip()
        if not name:
            continue

        scaled_quantity = scale_quantity(item.get("quantity"), quantity)
        unit = item.get("unit")
        scaled_ingredients[name] = {
            "quantity": scaled_quantity,
            "unit": unit,
            "display": format_quantity_display(scaled_quantity, unit),
        }

    return {
        "servings": scale_servings(recipe_data.get("servings"), quantity),
        "ingredients": scaled_ingredients,
    }


def normalize_scaled_values(data):
    ingredients = data.get("ingredients", {})
    normalized_ingredients = {}

    if isinstance(ingredients, dict):
        for name, value in ingredients.items():
            if not isinstance(value, dict):
                continue

            ingredient_name = str(name or "").strip()
            if not ingredient_name:
                continue

            quantity = value.get("quantity")
            unit = value.get("unit")
            display = value.get("display") or format_quantity_display(quantity, unit)
            normalized_ingredients[ingredient_name] = {
                "quantity": quantity,
                "unit": unit,
                "display": str(display or "").strip(),
            }

    return {
        "servings": data.get("servings"),
        "ingredients": normalized_ingredients,
    }


def load_saved_recipe_output(recipe_url):
    _json_path, data = load_saved_recipe_output_with_path(recipe_url)
    return data


def load_saved_recipe_output_with_path(recipe_url):
    recipe_key = normalize_recipe_url_key(recipe_url)

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if normalize_recipe_url_key(data.get("source_url", "")) == recipe_key:
            return json_path, data

    return None, {}


def ingredient_key(text):
    return " ".join(str(text or "").strip().lower().split())


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return text


def scale_servings(servings, multiplier):
    servings_text = str(servings or "").strip()

    if not servings_text or multiplier == 1:
        return servings

    match = re.search(r"\d+(?:\.\d+)?", servings_text)
    if not match:
        return servings

    scaled = format_number(float(match.group(0)) * multiplier)
    return servings_text[:match.start()] + scaled + servings_text[match.end():]


def scale_quantity(quantity, multiplier):
    quantity_text = str(quantity or "").strip()

    if not quantity_text or multiplier == 1:
        return quantity

    range_match = re.match(r"^(.+?)\s*(?:-|to)\s*(.+)$", quantity_text)
    if range_match:
        left = scale_quantity_part(range_match.group(1), multiplier)
        right = scale_quantity_part(range_match.group(2), multiplier)
        separator = " to " if " to " in quantity_text else "-"
        return f"{left}{separator}{right}"

    return scale_quantity_part(quantity_text, multiplier)


def scale_quantity_part(value, multiplier):
    parsed = parse_quantity_fraction(value)

    if parsed is None:
        return value

    return format_fraction(parsed * multiplier)


def parse_quantity_fraction(value):
    text = str(value or "").strip()
    mixed_match = re.match(r"^(\d+)\s+(\d+)/(\d+)$", text)

    if mixed_match:
        whole, numerator, denominator = mixed_match.groups()
        return Fraction(int(whole), 1) + Fraction(int(numerator), int(denominator))

    fraction_match = re.match(r"^(\d+)/(\d+)$", text)
    if fraction_match:
        numerator, denominator = fraction_match.groups()
        return Fraction(int(numerator), int(denominator))

    decimal_match = re.match(r"^\d+(?:\.\d+)?$", text)
    if decimal_match:
        return Fraction(text)

    return None


def format_fraction(value):
    value = Fraction(value)

    if value.denominator == 1:
        return str(value.numerator)

    whole = value.numerator // value.denominator
    remainder = value - whole

    if whole:
        return f"{whole} {remainder.numerator}/{remainder.denominator}"

    return f"{remainder.numerator}/{remainder.denominator}"


def format_number(value):
    if float(value).is_integer():
        return str(int(value))

    return f"{value:g}"


def format_quantity_display(quantity, unit):
    quantity = str(quantity or "").strip()
    unit = str(unit or "").strip()

    if not quantity:
        return ""

    return f"{quantity} {unit}".strip()
