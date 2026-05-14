import html
import json
import re
from fractions import Fraction

from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request
from flask import render_template

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.food_rules_service import shopping_item_food_rule_status
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.home_address_service import save_home_address
from PushShoppingList.services.item_state_service import load_item_state
from PushShoppingList.services.item_state_service import save_item_manual_qty
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.recipe_quantity_service import ingredient_key
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import save_items
from PushShoppingList.services.store_settings_service import load_store_settings

main_bp = Blueprint("main_bp", __name__)


DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "urlStoreSelector": "https://info.aldi.us/stores",
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "urlStoreSelector": "https://www.kroger.com/stores/search",
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "urlStoreSelector": "https://www.walmart.com/",
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "urlStoreSelector": "https://www.meijer.com/",
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "urlStoreSelector": "https://www.target.com/store-locator/find-stores",
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "urlStoreSelector": "https://www.costco.com/s?keyword=&openFMW=true",
    },
}


def normalize(text):
    return " ".join(str(text).strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def shopping_items_only(items):
    return [
        item
        for item in items
        if not is_section_header(item)
    ]


def section_counts(items):
    counts = {}
    current_section = None

    for item in items:
        if is_section_header(item):
            current_section = item.replace("===", "").strip()
            counts.setdefault(current_section, 0)
            continue

        if current_section:
            counts[current_section] = counts.get(current_section, 0) + 1

    return counts


def recipe_view_rows(recipe_urls):
    rows = []
    recipe_ingredient_data = load_recipe_ingredients()

    for index, recipe in enumerate(recipe_urls, start=1):
        recipe_quantity = int(recipe.get("quantity") or 1)
        recipe_data = load_saved_recipe_output(recipe["url"])
        recipe_meta = recipe_ingredient_data.get(normalize_recipe_url_key(recipe["url"]), {})
        use_scaled_meta = int(recipe_meta.get("quantity") or 1) == recipe_quantity
        scaled_ingredients = recipe_meta.get("scaled_ingredients", {}) if use_scaled_meta else {}
        scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None
        sections = build_recipe_sections(recipe_data, recipe_quantity, scaled_ingredients)

        rows.append({
            "number": index,
            "name": recipe_data.get("recipe_title") or recipe["name"],
            "url": recipe["url"],
            "quantity": recipe_quantity,
            "base_servings": recipe_data.get("servings"),
            "scaled_servings": scaled_servings or scale_servings(recipe_data.get("servings"), recipe_quantity),
            "equipment_items": normalize_text_list(recipe_data.get("equipment", [])),
            "instruction_items": normalize_instruction_items(recipe_data.get("instructions", [])),
            "nutrition_items": normalize_nutrition_items(recipe_data.get("nutrition", {})),
            "sections": sections,
        })

    return rows


def recipe_url_log_rows(recipe_urls):
    rows = []

    for recipe in recipe_urls:
        recipe_data = load_saved_recipe_output(recipe["url"])
        rows.append({
            **recipe,
            "food_rule_status": recipe_food_rule_status(recipe_data),
        })

    return rows


def recipe_food_rule_status(recipe_data):
    flagged_items = []

    for ingredient in recipe_data.get("ingredients", []) or []:
        if isinstance(ingredient, dict):
            name = str(ingredient.get("ingredient") or ingredient.get("original_text") or "").strip()
            text = " ".join([
                str(ingredient.get("ingredient") or ""),
                str(ingredient.get("original_text") or ""),
                str(ingredient.get("preparation") or ""),
            ])
        else:
            name = str(ingredient or "").strip()
            text = name

        if not text.strip():
            continue

        status = shopping_item_food_rule_status(text)
        if not status.get("needs_review"):
            continue

        issue_text = status.get("marker", "").replace("Food rule review: ", "")
        label = name or "Ingredient"
        flagged_items.append(f"{label}: {issue_text}" if issue_text else label)

    seen = set()
    unique_items = []
    for item in flagged_items:
        key = item.lower()
        if key not in seen:
            unique_items.append(item)
            seen.add(key)

    return {
        "needs_review": bool(unique_items),
        "marker": "Food rule review: " + "; ".join(unique_items) if unique_items else "",
        "count": len(unique_items),
    }


def recipe_quantity_lookup(recipe_rows):
    quantities = {}

    for recipe in recipe_rows:
        for section_items in recipe.get("sections", {}).values():
            for item in section_items:
                display_name = item.get("display_name") or item.get("name")
                quantity_display = item.get("quantity_display") or item.get("base_display")

                if not display_name or not quantity_display:
                    continue

                key = normalize(display_name)
                quantities.setdefault(key, []).append(str(quantity_display).strip())

    return {
        key: summarize_quantity_displays(values)
        for key, values in quantities.items()
    }


def recipe_quantity_sources_lookup(recipe_rows):
    sources = {}

    for recipe in recipe_rows:
        recipe_number = recipe.get("number")
        recipe_label = f"Recipe {recipe_number} Qty" if recipe_number else "Recipe Qty"

        for section_items in recipe.get("sections", {}).values():
            for item in section_items:
                display_name = item.get("display_name") or item.get("name")
                quantity_display = item.get("quantity_display") or item.get("base_display")

                if not display_name or not quantity_display:
                    continue

                key = normalize(display_name)
                sources.setdefault(key, []).append({
                    "label": recipe_label,
                    "ingredient": str(item.get("name") or display_name).strip(),
                    "default_quantity": str(item.get("base_display") or "").strip(),
                    "default_quantity_value": str(item.get("base_quantity") or "").strip(),
                    "default_unit": str(item.get("unit") or "").strip(),
                    "recipe_number": recipe_number,
                    "recipe_quantity": recipe.get("quantity") or 1,
                    "url": recipe.get("url") or "",
                    "quantity": str(quantity_display).strip(),
                })

    return sources


def apply_manual_item_quantities(item_quantities, item_state):
    quantities = dict(item_quantities)

    for item_key, state in item_state.items():
        if not isinstance(state, dict):
            continue

        manual_qty = str(state.get("manual_qty") or "").strip()
        if manual_qty:
            quantities[normalize(item_key)] = manual_qty

    return quantities


def summarize_quantity_displays(values):
    cleaned_values = [
        value
        for value in values
        if value
    ]

    if not cleaned_values:
        return ""

    if len(cleaned_values) == 1:
        return cleaned_values[0]

    summed = sum_quantity_displays(cleaned_values)
    if summed:
        return summed

    unique_values = []
    seen = set()

    for value in cleaned_values:
        key = normalize(value)

        if key not in seen:
            unique_values.append(value)
            seen.add(key)

    return " + ".join(unique_values)


def sum_quantity_displays(values):
    parsed_values = [
        parse_quantity_display(value)
        for value in values
    ]

    if not parsed_values or any(value is None for value in parsed_values):
        return ""

    units = {value["unit"] for value in parsed_values}

    if len(units) != 1:
        return ""

    unit = next(iter(units))
    low_total = sum(value["low"] for value in parsed_values)
    high_values = [
        value["high"]
        for value in parsed_values
        if value["high"] is not None
    ]
    high_total = sum(high_values) if high_values else None

    if high_total is not None and high_total != low_total:
        quantity_text = f"{format_fraction(low_total)} to {format_fraction(high_total)}"
    else:
        quantity_text = format_fraction(low_total)

    return format_quantity_unit(quantity_text, unit)


def parse_quantity_display(value):
    text = str(value or "").strip()

    if not text or " OR " in text.upper():
        return None

    match = re.match(
        r"^(?P<low>\d+(?:\s+\d+/\d+|/\d+)?)(?:\s*(?:-|to)\s*(?P<high>\d+(?:\s+\d+/\d+|/\d+)?))?(?:\s+(?P<unit>.+))?$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    low = parse_quantity_fraction(match.group("low"))
    high = parse_quantity_fraction(match.group("high")) if match.group("high") else None

    if low is None or (match.group("high") and high is None):
        return None

    return {
        "low": low,
        "high": high,
        "unit": normalize_quantity_unit(match.group("unit")),
    }


def normalize_quantity_unit(unit):
    unit = str(unit or "").strip()
    unit_key = unit.lower()
    singular_units = {
        "cups": "cup",
        "teaspoons": "teaspoon",
        "tablespoons": "tablespoon",
        "ounces": "ounce",
        "pounds": "pound",
        "grams": "gram",
        "kilograms": "kilogram",
        "milliliters": "milliliter",
        "liters": "liter",
        "pinches": "pinch",
        "dashes": "dash",
        "cloves": "clove",
        "sticks": "stick",
    }

    return singular_units.get(unit_key, unit)


def load_saved_recipe_output(recipe_url):
    recipe_key = normalize_recipe_url_key(recipe_url)

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if normalize_recipe_url_key(data.get("source_url", "")) == recipe_key:
            return data

    return {}


def build_recipe_sections(recipe_data, recipe_quantity=1, scaled_ingredients=None):
    sections = {section: [] for section in STORE_SECTION_ORDER.keys()}
    scaled_ingredients = scaled_ingredients or {}

    for ingredient in recipe_data.get("ingredients", []) or []:
        if not isinstance(ingredient, dict):
            continue

        name = str(ingredient.get("ingredient", "") or "").strip()
        if not name:
            continue

        section = str(ingredient.get("store_section", "") or "MISC").strip().upper()
        if section not in sections:
            section = "MISC"

        scaled_value = scaled_ingredients.get(name) or scaled_ingredients.get(ingredient_key(name)) or {}
        scaled_quantity = scaled_value.get("quantity") if isinstance(scaled_value, dict) else None
        scaled_unit = scaled_value.get("unit") if isinstance(scaled_value, dict) else None
        scaled_display = scaled_value.get("display") if isinstance(scaled_value, dict) else None
        fallback_quantity = scale_quantity(ingredient.get("quantity"), recipe_quantity)
        display_name = name
        base_display = format_quantity_unit(ingredient.get("quantity"), ingredient.get("unit"))
        quantity_display = scaled_display
        alternative = parse_quantity_alternative(
            name,
            ingredient.get("quantity"),
            ingredient.get("unit"),
            recipe_quantity,
            scaled_quantity or fallback_quantity,
        )

        if alternative:
            display_name = alternative["name"]
            base_display = alternative["base_display"]
            quantity_display = alternative["scaled_display"] if recipe_quantity > 1 else alternative["base_display"]

        sections[section].append({
            "name": name,
            "display_name": display_name,
            "quantity": ingredient.get("quantity"),
            "base_quantity": ingredient.get("quantity"),
            "scaled_quantity": scaled_quantity or fallback_quantity,
            "unit": scaled_unit if scaled_unit is not None else ingredient.get("unit"),
            "base_display": base_display,
            "quantity_display": quantity_display,
            "url": recipe_data.get("source_url"),
        })

    return {
        section: sorted(items, key=lambda item: normalize(item["name"]))
        for section, items in sections.items()
        if items
    }


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


def parse_quantity_alternative(name, quantity, unit, recipe_quantity, scaled_quantity):
    match = re.match(
        r"^(?P<first>.+?)\s+or\s+(?P<quantity>\d+(?:\s+\d+/\d+|/\d+)?|\d+/\d+)\s+(?P<unit>[A-Za-z]+)\s+(?P<second>.+)$",
        str(name or "").strip(),
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    first_name = match.group("first").strip()
    second_quantity = match.group("quantity").strip()
    second_unit = match.group("unit").strip()
    second_name = match.group("second").strip()
    first_base = format_quantity_unit(quantity, unit)
    second_base = format_quantity_unit(second_quantity, second_unit)
    first_scaled = format_quantity_unit(scaled_quantity, unit)
    second_scaled = format_quantity_unit(scale_quantity(second_quantity, recipe_quantity), second_unit)

    return {
        "name": f"{first_name} OR {second_name}",
        "base_display": f"{first_base} OR {second_base}",
        "scaled_display": f"{first_scaled} OR {second_scaled}",
    }


def format_quantity_unit(quantity, unit):
    quantity = str(quantity or "").strip()
    unit = str(unit or "").strip()

    if not quantity:
        return ""

    return f"{quantity} {unit}".strip()


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


def normalize_text_list(value):
    if not value:
        return []

    if isinstance(value, str):
        return [value]

    if not isinstance(value, list):
        return []

    items = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("name") or item.get("text") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            items.append(text)

    return items


def normalize_instruction_items(value):
    if not isinstance(value, list):
        return normalize_text_list(value)

    items = []
    for item in value:
        if isinstance(item, dict):
            text = clean_display_text(item.get("instruction") or item.get("text") or "")
        else:
            text = clean_display_text(item)

        if text:
            items.append(text)

    return items


def clean_display_text(value):
    return " ".join(html.unescape(str(value or "")).split())


def normalize_nutrition_items(nutrition):
    if not isinstance(nutrition, dict):
        return []

    labels = {
        "serving_basis": "Serving basis",
        "calories": "Calories",
        "carbohydrates": "Carbohydrates",
        "protein": "Protein",
        "fat": "Fat",
        "saturated_fat": "Saturated fat",
        "polyunsaturated_fat": "Polyunsaturated fat",
        "monounsaturated_fat": "Monounsaturated fat",
        "trans_fat": "Trans fat",
        "cholesterol": "Cholesterol",
        "sodium": "Sodium",
        "potassium": "Potassium",
        "fiber": "Fiber",
        "sugar": "Sugar",
        "vitamin_a": "Vitamin A",
        "vitamin_c": "Vitamin C",
        "calcium": "Calcium",
        "iron": "Iron",
    }

    items = [
        {"label": label, "value": value}
        for key, label in labels.items()
        for value in [nutrition.get(key)]
        if value
    ]

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                label = item.get("label") or item.get("name") or "Other"
                value = item.get("value") or item.get("amount")
                if value:
                    items.append({"label": label, "value": value})

    return items


def build_store_view(items, item_state, available_stores, enabled_stores):
    section_order = []
    item_sections = {}
    current_section = "MISC"

    for item in items:
        if is_section_header(item):
            current_section = item.replace("===", "").strip()
            if current_section not in section_order:
                section_order.append(current_section)
            continue

        item_sections[item] = current_section

    if "MISC" not in section_order:
        section_order.append("MISC")

    store_keys = [
        store_key
        for store_key in enabled_stores
        if store_key in available_stores
    ]
    buckets = {store_key: {} for store_key in store_keys}
    buckets["unselected"] = {}

    for item, section in item_sections.items():
        selected_store = item_state.get(normalize(item), {}).get("store")
        bucket_key = selected_store if selected_store in store_keys else "unselected"
        buckets[bucket_key].setdefault(section, []).append(item)

    display_rows = []

    for store_key in store_keys + ["unselected"]:
        sections = buckets.get(store_key, {})
        cleaned_sections = []

        for section in section_order:
            section_items = sections.get(section, [])
            if section_items:
                cleaned_sections.append({
                    "name": section,
                    "items": sorted(section_items, key=normalize),
                })

        if not cleaned_sections:
            continue

        store = available_stores.get(store_key, {})
        display_rows.append({
            "key": store_key,
            "label": store.get("label", "Unselected" if store_key == "unselected" else store_key.title()),
            "sections": cleaned_sections,
        })

    return display_rows


@main_bp.route("/")
def index():
    items = load_items()
    store_settings = load_store_settings()
    recipe_urls = recipe_url_rows()
    recipe_log_rows = recipe_url_log_rows(recipe_urls)
    item_state = load_item_state()
    recipe_rows = recipe_view_rows(recipe_urls)
    recipe_item_quantities = recipe_quantity_lookup(recipe_rows)
    recipe_item_quantity_sources = recipe_quantity_sources_lookup(recipe_rows)
    item_quantities = apply_manual_item_quantities(
        recipe_item_quantities,
        item_state,
    )

    return render_template(
        "index.html",
        message="",
        raw_items="\n".join(items),
        items=items,
        current_urls=recipe_log_rows,
        home_address=load_home_address(),
        available_stores=store_settings["stores"],
        enabled_stores=store_settings["enabled_stores"],
        shopping_items=shopping_items_only(items),
        item_state=item_state,
        item_quantities=item_quantities,
        recipe_item_quantities=recipe_item_quantities,
        recipe_item_quantity_sources=recipe_item_quantity_sources,
        section_counts=section_counts(items),
        store_view=build_store_view(
            items,
            item_state,
            store_settings["stores"],
            store_settings["enabled_stores"],
        ),
        recipe_view_rows=recipe_rows,
        normalize=normalize,
        is_section_header=is_section_header,
        food_rule_status=shopping_item_food_rule_status,
    )


@main_bp.route("/clear", methods=["POST"])
def clear_list():
    save_items([])
    save_recipe_urls([])
    save_recipe_ingredients({})

    return redirect("/")


@main_bp.route("/save", methods=["POST"])
def save_list():
    raw_items = request.form.get("items", "")
    items = [
        line.strip()
        for line in raw_items.splitlines()
        if line.strip()
    ]

    save_items(items)
    sort_ingredients()

    return redirect("/")


@main_bp.route("/sort", methods=["POST"])
def sort_list():
    sort_ingredients()

    return redirect("/")


@main_bp.route("/save_home_address", methods=["POST"])
def save_home_address_route():
    saved_address = save_home_address(request.form)

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        return jsonify({
            "ok": True,
            "home_address": saved_address,
        })

    return redirect("/#home-address-section")


@main_bp.route("/save_item_qty", methods=["POST"])
def save_item_qty_route():
    item_key = normalize(request.form.get("item_key", ""))
    manual_qty = str(request.form.get("manual_qty", "") or "").strip()

    if item_key:
        save_item_manual_qty(item_key, manual_qty)

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        return jsonify({
            "ok": True,
            "item_key": item_key,
            "manual_qty": manual_qty,
        })

    return redirect("/")
