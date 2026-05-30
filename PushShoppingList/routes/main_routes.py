import html
import json
import os
import re
from fractions import Fraction

import requests
from openai import OpenAI
from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import request
from flask import render_template
from flask import url_for

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import shopping_item_food_rule_status
from PushShoppingList.services.cookbook_service import cookbook_view
from PushShoppingList.services.cookbook_service import create_cookbook
from PushShoppingList.services.cookbook_service import cookbook_recipes_for_urls
from PushShoppingList.services.cookbook_service import CookbookRecipeConflict
from PushShoppingList.services.cookbook_service import delete_cookbook
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import move_recipes_to_cookbook
from PushShoppingList.services.cookbook_service import recipe_ingredients_for_record
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.cookbook_service import remove_recipe_from_cookbook
from PushShoppingList.services.cookbook_service import rename_cookbook
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.home_address_service import save_home_address
from PushShoppingList.services.home_store_location_service import DEFAULT_STORE_SEARCH_RADIUS_MILES
from PushShoppingList.services.home_store_location_service import format_store_search_radius
from PushShoppingList.services.home_store_location_service import load_nearest_store_results
from PushShoppingList.services.home_store_location_service import resolve_nearest_stores_for_home_address
from PushShoppingList.services.item_state_service import load_item_state
from PushShoppingList.services.item_state_service import save_item_manual_qty
from PushShoppingList.services.item_state_service import save_item_purchase_mapping
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_item
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_recipe_ingredient
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_lookup_for_items
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import add_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipe
from PushShoppingList.services.recipe_ingredient_service import update_saved_recipe_purchase_mapping
from PushShoppingList.services.recipe_quantity_service import ingredient_key
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_exists
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import recipe_scaling_from_data
from PushShoppingList.services.recipe_extract_service import scaling_multiplier_label
from PushShoppingList.services.product_selection_service import product_choices_by_item
from PushShoppingList.services.rules_display_service import load_rules_display
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.shopping_list_service import save_items
from PushShoppingList.services.store_settings_service import load_store_settings

main_bp = Blueprint("main_bp", __name__)
address_openai_client = None


def static_asset_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except OSError:
        return 1

US_STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


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
        recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
        recipe_data = load_saved_recipe_output(recipe["url"])
        recipe_meta = recipe_ingredient_data.get(normalize_recipe_url_key(recipe["url"]), {})
        cover_image = recipe_cover_image_for_view(recipe["url"], recipe_data, recipe_meta)
        nutrition_summary = recipe_view_nutrition_summary(recipe_data.get("nutrition", {}))
        use_scaled_meta = multipliers_match(recipe_meta.get("quantity", 1), recipe_quantity)
        scaled_ingredients = recipe_meta.get("scaled_ingredients", {}) if use_scaled_meta else {}
        scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None
        sections = build_recipe_sections(recipe_data, recipe_quantity, scaled_ingredients)

        rows.append({
            "number": index,
            "name": recipe_data.get("recipe_title") or recipe["name"],
            "url": recipe["url"],
            "source_href": recipe_source_href(recipe["url"]),
            "source_display_url": recipe_source_display_url(recipe["url"]),
            "cover_image": cover_image,
            "quantity": recipe_quantity,
            "scaling_options": recipe_log_scaling_options(recipe_data, recipe_quantity),
            "archive_pdf_available": recipe_archive_pdf_exists(recipe["url"]),
            "food_rule_status": recipe_food_rule_status(recipe_data),
            "base_servings": recipe_data.get("servings"),
            "scaled_servings": scaled_servings or scale_servings(recipe_data.get("servings"), recipe_quantity),
            "serving_basis": nutrition_summary["serving_basis"],
            "calories": nutrition_summary["calories"],
            "equipment_items": normalize_text_list(recipe_data.get("equipment", [])),
            "instruction_items": normalize_instruction_items(recipe_data.get("instructions", [])),
            "nutrition_items": normalize_nutrition_items(recipe_data.get("nutrition", {})),
            "sections": sections,
        })

    return rows


def recipe_view_nutrition_summary(nutrition):
    if not isinstance(nutrition, dict):
        return {"serving_basis": "", "calories": ""}

    return {
        "serving_basis": clean_display_text(nutrition.get("serving_basis")),
        "calories": clean_display_text(nutrition.get("calories")),
    }


def apply_cookbook_assignments_to_recipe_rows(rows, cookbook_assignments):
    cookbook_assignments = cookbook_assignments or {}

    for row in rows:
        recipe_key = normalize_recipe_url_key(row.get("url", ""))
        cookbook_assignment = cookbook_assignments.get(recipe_key, {})
        row["cookbook_id"] = cookbook_assignment.get("cookbook_id", "")
        row["cookbook_name"] = cookbook_assignment.get("cookbook_name", "")
        row["cookbook_is_unclassified"] = cookbook_assignment.get("cookbook_is_unclassified", False)

    return rows


def recipe_url_log_rows(recipe_urls, cookbook_assignments=None):
    rows = []
    recipe_ingredient_data = load_recipe_ingredients()
    cookbook_assignments = cookbook_assignments or {}

    for recipe in recipe_urls:
        recipe_key = normalize_recipe_url_key(recipe["url"])
        recipe_data = load_saved_recipe_output(recipe["url"])
        recipe_meta = recipe_ingredient_data.get(recipe_key, {})
        nutrition_summary = recipe_view_nutrition_summary(recipe_data.get("nutrition", {}))
        recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
        use_scaled_meta = multipliers_match(recipe_meta.get("quantity", 1), recipe_quantity)
        scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None
        cookbook_assignment = cookbook_assignments.get(recipe_key, {})
        rows.append({
            **recipe,
            "quantity": recipe_quantity,
            "scaling_options": recipe_log_scaling_options(recipe_data, recipe_quantity),
            "source_href": recipe_source_href(recipe["url"]),
            "source_display_url": recipe_source_display_url(recipe["url"]),
            "cover_image": recipe_cover_image_for_view(recipe["url"], recipe_data, recipe_meta),
            "food_rule_status": recipe_food_rule_status(recipe_data),
            "archive_pdf_available": recipe_archive_pdf_exists(recipe["url"]),
            "base_servings": recipe_data.get("servings"),
            "scaled_servings": scaled_servings or scale_servings(recipe_data.get("servings"), recipe_quantity),
            "serving_basis": nutrition_summary["serving_basis"],
            "calories": nutrition_summary["calories"],
            "cookbook_id": cookbook_assignment.get("cookbook_id", ""),
            "cookbook_name": cookbook_assignment.get("cookbook_name", ""),
            "cookbook_is_unclassified": cookbook_assignment.get("cookbook_is_unclassified", False),
        })

    return rows


def recipe_cover_image_for_view(recipe_url, recipe_data, recipe_meta=None):
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    candidates = []

    if isinstance(recipe_data, dict):
        candidates.append(recipe_data.get("cover_image"))

    candidates.append(recipe_meta.get("cover_image"))

    for cover_image in candidates:
        if not isinstance(cover_image, dict):
            continue

        src = recipe_cover_image_src(recipe_url, cover_image)

        if not src:
            continue

        alt = (
            str(cover_image.get("alt") or "").strip()
            or str((recipe_data or {}).get("recipe_title") or "").strip()
            or "Recipe cover image"
        )
        return {
            **cover_image,
            "src": src,
            "alt": alt,
        }

    return {}


def recipe_cover_image_src(recipe_url, cover_image):
    if cover_image.get("path"):
        try:
            return url_for("recipe_bp.recipe_cover_image_route", url=recipe_url)
        except RuntimeError:
            return ""

    return str(cover_image.get("url") or "").strip()


def cookbook_cover_image_for_view(recipe):
    if not isinstance(recipe, dict):
        return {}

    cover_image = recipe.get("cover_image")

    if not isinstance(cover_image, dict):
        return {}

    if cover_image.get("src"):
        alt = str(cover_image.get("alt") or recipe.get("name") or "Recipe cover image").strip()
        return {
            **cover_image,
            "alt": alt,
        }

    return recipe_cover_image_for_view(
        recipe.get("url", ""),
        {
            "recipe_title": recipe.get("name"),
            "cover_image": cover_image,
        },
        {"cover_image": cover_image},
    )


def cookbook_view_for_render(recipe_rows):
    view = cookbook_view(recipe_rows)

    for cookbook in view.get("cookbooks", []):
        for recipe in cookbook.get("recipes", []):
            recipe["cover_image"] = cookbook_cover_image_for_view(recipe)

    for recipe in view.get("recipes", []):
        recipe["cover_image"] = cookbook_cover_image_for_view(recipe)

    return view


def recipe_log_scaling_options(recipe_data, selected_multiplier):
    scaling = recipe_scaling_from_data(recipe_data, default_to_common=True)
    options = scaling.get("available_multipliers", [])
    selected_multiplier = normalize_recipe_quantity(selected_multiplier)
    normalized_options = []
    selected_found = False

    for option in options:
        value = normalize_recipe_quantity(option.get("value") if isinstance(option, dict) else option)
        selected = multipliers_match(value, selected_multiplier)
        selected_found = selected_found or selected
        normalized_options.append({
            "label": option.get("label") if isinstance(option, dict) and option.get("label") else scaling_multiplier_label(value),
            "value": value,
            "selected": selected,
        })

    if not selected_found:
        normalized_options.append({
            "label": scaling_multiplier_label(selected_multiplier),
            "value": selected_multiplier,
            "selected": True,
        })

    return sorted(normalized_options, key=lambda option: float(option["value"]))


def multipliers_match(left, right):
    return abs(float(normalize_recipe_quantity(left)) - float(normalize_recipe_quantity(right))) < 0.000001


def recipe_source_href(recipe_url):
    if imported_recipe_uses_pdf_path(recipe_url):
        return url_for("recipe_bp.recipe_archive_pdf_route", url=recipe_url)

    return recipe_url


def recipe_source_display_url(recipe_url):
    if recipe_url_type(recipe_url) == "File":
        return str(recipe_archive_pdf_path(recipe_url))

    return recipe_url


def imported_recipe_uses_pdf_path(recipe_url):
    return recipe_url_type(recipe_url) == "File" and recipe_archive_pdf_exists(recipe_url)


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
                    "recipe_ingredient": str(item.get("name") or display_name).strip(),
                    "purchasable_item": str(item.get("purchasable_item") or item.get("buy_as") or display_name).strip(),
                    "purchase_group": str(item.get("purchase_group") or item.get("purchasable_item") or item.get("buy_as") or display_name).strip(),
                    "purchase_group_key": str(item.get("purchase_group_key") or key).strip(),
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

    unit_order = []
    grouped_values = {}

    for value in parsed_values:
        unit = value["unit"]

        if unit not in grouped_values:
            unit_order.append(unit)
            grouped_values[unit] = []

        grouped_values[unit].append(value)

    return " + ".join(
        sum_parsed_quantity_group(grouped_values[unit], unit)
        for unit in unit_order
    )


def sum_parsed_quantity_group(values, unit):
    low_total = sum(value["low"] for value in values)
    has_range = any(value["high"] is not None for value in values)
    high_total = (
        sum(value["high"] if value["high"] is not None else value["low"] for value in values)
        if has_range
        else None
    )

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
        "c": "cup",
        "c.": "cup",
        "cups": "cup",
        "tsp": "teaspoon",
        "tsp.": "teaspoon",
        "teaspoons": "teaspoon",
        "tbsp": "tablespoon",
        "tbsp.": "tablespoon",
        "tbs": "tablespoon",
        "tbs.": "tablespoon",
        "tablespoons": "tablespoon",
        "oz": "ounce",
        "oz.": "ounce",
        "ounces": "ounce",
        "lb": "pound",
        "lb.": "pound",
        "lbs": "pound",
        "lbs.": "pound",
        "pounds": "pound",
        "g": "g",
        "grams": "gram",
        "kg": "kilogram",
        "kilograms": "kilogram",
        "ml": "milliliter",
        "milliliters": "milliliter",
        "l": "liter",
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
            quantity_display = alternative["scaled_display"] if not multipliers_match(recipe_quantity, 1) else alternative["base_display"]

        purchase_mapping = purchase_mapping_for_recipe_ingredient(ingredient)

        sections[section].append({
            "name": name,
            "display_name": display_name,
            "purchasable_item": purchase_mapping["purchasable_item"],
            "buy_as": purchase_mapping["buy_as"],
            "purchase_group": purchase_mapping["purchase_group"],
            "purchase_group_key": purchase_mapping["purchase_group_key"],
            "purchase_is_mapped": purchase_mapping["is_mapped"],
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
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_list(value)

    items = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = clean_display_text(item.get("instruction") or item.get("text") or "")
            step_number = item.get("step_number") or index
            step_image_url = clean_display_text(item.get("step_image_url") or item.get("image_url") or "")
            step_image_generated_at = clean_display_text(
                item.get("step_image_generated_at") or item.get("image_generated_at") or ""
            )
        else:
            text = clean_display_text(item)
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if text:
            items.append({
                "step_number": step_number,
                "text": text,
                "instruction": text,
                "step_image_url": step_image_url,
                "step_image_generated_at": step_image_generated_at,
            })

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
        purchase_mapping = purchase_mapping_for_item(item, item_state=item_state)
        purchase_state = item_state.get(purchase_mapping["purchase_group_key"], {})
        item_specific_state = item_state.get(normalize(item), {})
        selected_store = purchase_state.get("store") or item_specific_state.get("store")
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
    item_state = load_item_state()
    recipe_rows = recipe_view_rows(recipe_urls)
    ensure_unclassified_cookbook_for_recipes(recipe_rows)
    cookbook_assignments = recipe_cookbook_assignments()
    apply_cookbook_assignments_to_recipe_rows(recipe_rows, cookbook_assignments)
    recipe_log_rows = recipe_url_log_rows(recipe_urls, cookbook_assignments)
    rendered_cookbook_view = cookbook_view_for_render(recipe_rows)
    product_choices = product_choices_by_item()
    nearest_store_results = load_nearest_store_results()
    purchase_mappings = purchase_mapping_lookup_for_items(shopping_items_only(items), item_state)
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
        cookbook_view=rendered_cookbook_view,
        home_address=load_home_address(),
        nearest_store_results=nearest_store_results,
        nearest_store_locations=nearest_store_results.get("store_locations", {}),
        nearest_store_search_radius_miles=format_store_search_radius(
            nearest_store_results.get("search_radius_miles", DEFAULT_STORE_SEARCH_RADIUS_MILES)
        ),
        available_stores=store_settings["stores"],
        enabled_stores=store_settings["enabled_stores"],
        shopping_items=shopping_items_only(items),
        purchase_mappings=purchase_mappings,
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
        product_choices=product_choices,
        normalize=normalize,
        is_section_header=is_section_header,
        food_rules=load_food_rules(),
        rules_display=load_rules_display(),
        food_rule_status=shopping_item_food_rule_status,
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
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


@main_bp.route("/api/cookbooks", methods=["POST"])
def create_cookbook_route():
    try:
        cookbook = create_cookbook(request.form.get("name", ""))
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({
        "ok": True,
        "cookbook": {
            "id": cookbook.get("id", ""),
            "name": cookbook.get("name", ""),
        },
    })


@main_bp.route("/api/cookbooks/<cookbook_id>", methods=["DELETE"])
def delete_cookbook_route(cookbook_id):
    try:
        delete_cookbook(cookbook_id)
    except ValueError as err:
        status = 400 if "cannot be deleted" in str(err).lower() else 404
        return jsonify({"ok": False, "error": str(err)}), status

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/<cookbook_id>/rename", methods=["POST"])
def rename_cookbook_route(cookbook_id):
    try:
        rename_cookbook(cookbook_id, request.form.get("name", ""))
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/move_recipes", methods=["POST"])
def move_cookbook_recipes_route():
    try:
        move_recipes_to_cookbook(
            request.form.get("cookbook_id", ""),
            request.form.getlist("recipe_urls"),
            recipe_view_rows(recipe_url_rows()),
            overwrite_existing=request.form.get("overwrite_existing") == "1",
        )
    except CookbookRecipeConflict as err:
        return jsonify({
            "ok": False,
            "error": str(err),
            "conflict": "cookbook_recipe_exists",
            "conflicts": err.conflicts,
        })
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/remove_recipe", methods=["POST"])
def remove_cookbook_recipe_route():
    try:
        remove_recipe_from_cookbook(
            request.form.get("cookbook_id", ""),
            request.form.get("recipe_url", ""),
        )
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/restore_recipes", methods=["POST"])
def restore_cookbook_recipes_route():
    try:
        result = restore_cookbook_recipes_to_log(request.form.getlist("recipe_urls"))
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True, **result})


def restore_cookbook_recipes_to_log(recipe_urls):
    recipes = cookbook_recipes_for_urls(recipe_urls)
    urls = []
    ingredients_by_recipe = {}
    all_ingredients = []

    for recipe in recipes:
        url = recipe.get("url")
        ingredients = recipe_ingredients_for_record(recipe)

        if not url:
            continue

        urls.append(url)
        ingredients_by_recipe[url] = ingredients
        all_ingredients.extend(ingredients)

    if not urls:
        raise ValueError("Selected cookbook recipes were not found.")

    if not all_ingredients:
        raise ValueError("No ingredients were found for the selected cookbook recipes.")

    add_items(all_ingredients)

    for recipe in recipes:
        url = recipe.get("url")

        if not url:
            continue

        save_ingredients_for_recipe(url, ingredients_by_recipe.get(url, []), recipe)
        save_recipe_url_name(url, recipe.get("name", ""))
        save_recipe_url_quantity(url, recipe.get("quantity", 1))

    add_recipe_urls(urls)
    sort_ingredients()

    return {
        "restored_count": len(urls),
        "ingredient_count": len(all_ingredients),
    }


@main_bp.route("/sort", methods=["POST"])
def sort_list():
    sort_ingredients()

    return redirect("/")


@main_bp.route("/save_home_address", methods=["POST"])
def save_home_address_route():
    saved_address = save_home_address(request.form)
    nearest_store_results = None

    if request.form.get("action") == "run_find_nearest":
        nearest_store_results = resolve_nearest_stores_for_home_address(
            saved_address,
            search_radius_miles=request.form.get("store_search_radius_miles"),
        )

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        response = {
            "ok": True,
            "home_address": saved_address,
        }
        if nearest_store_results is not None:
            response["nearest_store_results"] = nearest_store_results
            if nearest_store_results.get("error"):
                response["warning"] = nearest_store_results.get("error")
        return jsonify(response)

    return redirect("/#storeOptionsSection" if nearest_store_results is not None else "/#home-address-section")


@main_bp.route("/api/reverse_geocode", methods=["POST"])
def reverse_geocode_route():
    data = request.get_json(silent=True) or {}

    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Latitude and longitude are required.",
        }), 400

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return jsonify({
            "ok": False,
            "error": "Latitude or longitude is out of range.",
        }), 400

    try:
        result = reverse_geocode_coordinates(latitude, longitude)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"Unable to look up address for this location: {exc}",
        }), 502

    return jsonify({
        "ok": True,
        "address": result["address"],
        "display_name": result["display_name"],
    })


@main_bp.route("/api/address_options", methods=["POST"])
def address_options_route():
    data = request.get_json(silent=True) or {}
    query = build_address_options_query(data)

    if not query:
        return jsonify({
            "ok": False,
            "error": "Enter at least part of an address before searching.",
        }), 400

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "jsonv2",
                "q": query,
                "addressdetails": 1,
                "countrycodes": "us",
                "limit": 8,
            },
            headers={
                "User-Agent": "PushShoppingList/1.0 local address lookup",
            },
            timeout=(5, 12),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"Unable to search address options: {exc}",
        }), 502

    return jsonify({
        "ok": True,
        "query": query,
        "options": normalize_address_options(payload if isinstance(payload, list) else []),
    })


@main_bp.route("/api/complete_address", methods=["POST"])
def complete_address_route():
    data = request.get_json(silent=True) or {}
    candidate_address = normalize_address_form_fields(data.get("address") or {})
    current_address = normalize_address_form_fields(data.get("current_address") or {})
    display_name = str(data.get("display_name") or "").strip()
    completed_address = complete_address_fields_locally(
        candidate_address,
        current_address,
        display_name,
    )
    completion_source = "local"

    if os.getenv("OPENAI_API_KEY") and address_needs_completion(completed_address):
        openai_address = complete_address_fields_with_openai(
            candidate_address,
            current_address,
            display_name,
        )

        if openai_address:
            completed_address = merge_completed_address_fields(
                openai_address,
                completed_address,
            )
            completion_source = "openai"

    return jsonify({
        "ok": True,
        "address": completed_address,
        "source": completion_source,
    })


def reverse_geocode_coordinates(latitude, longitude):
    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "addressdetails": 1,
        },
        headers={
            "User-Agent": "PushShoppingList/1.0 local address lookup",
        },
        timeout=(5, 12),
    )
    response.raise_for_status()
    payload = response.json()
    address = payload.get("address") if isinstance(payload, dict) else {}

    return {
        "address": reverse_geocode_address_fields(address or {}),
        "display_name": payload.get("display_name", "") if isinstance(payload, dict) else "",
    }


def build_address_options_query(data):
    query = str(data.get("query", "") or "").strip()

    if query:
        return query

    street = str(data.get("street") or data.get("address_street") or "").strip()
    city = str(data.get("city") or data.get("address_city") or "").strip()
    state = str(data.get("state") or data.get("address_state") or "").strip()
    zip_code = str(data.get("zip") or data.get("address_zip") or "").strip()

    return ", ".join(part for part in [street, city, state, zip_code] if part)


def normalize_address_options(results):
    options = []
    seen = set()

    for result in results:
        if not isinstance(result, dict):
            continue

        display_name = str(result.get("display_name") or "").strip()
        key = normalize(display_name)

        if not display_name or key in seen:
            continue

        seen.add(key)
        address = result.get("address") if isinstance(result.get("address"), dict) else {}
        options.append({
            "display_name": display_name,
            "address": reverse_geocode_address_fields(address),
            "latitude": result.get("lat"),
            "longitude": result.get("lon"),
        })

    return options


def normalize_address_form_fields(data):
    if not isinstance(data, dict):
        data = {}

    return {
        "street": address_field_value(
            data,
            "street",
            "address_street",
            "street_address",
            "streetaddress",
            "line1",
            "address1",
        ),
        "apartment": address_field_value(
            data,
            "apartment",
            "address_apartment",
            "unit",
            "line2",
            "address2",
        ),
        "city": address_field_value(data, "city", "address_city"),
        "county": address_field_value(data, "county", "address_county"),
        "state": abbreviate_us_state(address_field_value(data, "state", "address_state")),
        "zip": address_field_value(
            data,
            "zip",
            "address_zip",
            "zip_code",
            "zipcode",
            "postal_code",
            "postcode",
        ),
        "country": address_field_value(data, "country", "address_country"),
    }


def address_field_value(data, *keys):
    lower_data = {
        str(key).lower(): value
        for key, value in data.items()
    }

    for key in keys:
        value = data.get(key)

        if value in (None, ""):
            value = lower_data.get(key.lower())

        value = str(value or "").strip()

        if value:
            return value

    return ""


def complete_address_fields_locally(candidate_address, current_address, display_name):
    parsed_address = parse_display_name_address(display_name)

    return {
        "street": best_street_value(
            candidate_address.get("street"),
            parsed_address.get("street"),
            current_address.get("street"),
        ),
        "apartment": first_address_value_from_dicts(
            [candidate_address, current_address, parsed_address],
            "apartment",
        ),
        "city": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "city",
        ),
        "county": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "county",
        ),
        "state": abbreviate_us_state(first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "state",
        )),
        "zip": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "zip",
        ).split("-")[0],
        "country": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "country",
        ),
    }


def parse_display_name_address(display_name):
    parts = [
        part.strip()
        for part in str(display_name or "").split(",")
        if part.strip()
    ]
    parsed = {
        "street": "",
        "apartment": "",
        "city": "",
        "county": "",
        "state": "",
        "zip": "",
        "country": "",
    }

    for part in parts:
        zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", part)
        if zip_match and not parsed["zip"]:
            parsed["zip"] = zip_match.group(0).split("-")[0]

        state_text = re.sub(r"\b\d{5}(?:-\d{4})?\b", "", part).strip(" ,")
        state = abbreviate_us_state(state_text)
        if state != part or re.fullmatch(r"[A-Z]{2}", state):
            parsed["state"] = parsed["state"] or state

    if parts:
        parsed["street"] = parts[0]

    for part in parts[1:]:
        lowered = part.lower()

        if lowered in {"united states", "usa", "us"}:
            parsed["country"] = parsed["country"] or part
            continue

        if lowered.endswith(" county"):
            parsed["county"] = parsed["county"] or part
            continue

        if parsed["zip"] and parsed["zip"] in part:
            continue

        if parsed["state"] and part.upper() == parsed["state"]:
            continue

        if abbreviate_us_state(part) == parsed["state"]:
            continue

        parsed["city"] = parsed["city"] or part

    return parsed


def first_address_value_from_dicts(dicts, key):
    for data in dicts:
        value = str((data or {}).get(key, "") or "").strip()

        if value:
            return value

    return ""


def best_street_value(*values):
    cleaned_values = [
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    ]

    if not cleaned_values:
        return ""

    return max(cleaned_values, key=street_value_score)


def street_value_score(value):
    value = str(value or "")
    return (
        100 if re.search(r"\d", value) else 0,
        len(value.split()),
        len(value),
    )


def address_needs_completion(address):
    street = str(address.get("street") or "")

    return (
        not street
        or not re.search(r"\d", street)
        or not address.get("city")
        or not address.get("state")
        or not address.get("zip")
    )


def complete_address_fields_with_openai(candidate_address, current_address, display_name):
    global address_openai_client

    if address_openai_client is None:
        address_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=20)

    prompt = f"""
Extract the most complete US mailing address fields from the data below.

Rules:
- Return only JSON.
- Use only information present in the candidate, display text, or current form fields.
- Do not invent a house number.
- Preserve the current apartment/unit when the candidate does not include one.
- Prefer a full street address with house number over a road-only value.
- Use a two-letter US state abbreviation when possible.
- Unknown fields should be empty strings.

Candidate address fields:
{json.dumps(candidate_address, ensure_ascii=False)}

Candidate display text:
{display_name}

Current form fields:
{json.dumps(current_address, ensure_ascii=False)}

Output shape:
{{
  "street": "",
  "apartment": "",
  "city": "",
  "county": "",
  "state": "",
  "zip": "",
  "country": ""
}}
"""

    try:
        response = address_openai_client.chat.completions.create(
            model=os.getenv("OPENAI_ADDRESS_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "You extract structured US mailing address fields and return only JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        print(f"OpenAI address completion failed; using local address fields: {exc}")
        return {}

    return normalize_address_form_fields(data)


def merge_completed_address_fields(primary, fallback):
    return {
        key: str(primary.get(key) or fallback.get(key) or "").strip()
        for key in ["street", "apartment", "city", "county", "state", "zip", "country"]
    }


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text


def reverse_geocode_address_fields(address):
    road = first_address_value(address, [
        "road",
        "pedestrian",
        "footway",
        "path",
        "residential",
        "neighbourhood",
    ])
    house_number = first_address_value(address, ["house_number"])
    street = " ".join(part for part in [house_number, road] if part)
    state = first_address_value(address, ["state_code"]) or abbreviate_us_state(
        first_address_value(address, ["state"])
    )

    return {
        "street": street,
        "apartment": "",
        "city": first_address_value(address, [
            "city",
            "town",
            "village",
            "municipality",
            "hamlet",
            "county",
        ]),
        "county": first_address_value(address, ["county"]),
        "state": state,
        "zip": first_address_value(address, ["postcode"]).split("-")[0],
        "country": first_address_value(address, ["country"]),
    }


def first_address_value(address, keys):
    for key in keys:
        value = str(address.get(key, "") or "").strip()

        if value:
            return value

    return ""


def abbreviate_us_state(state):
    state = str(state or "").strip()

    if len(state) == 2:
        return state.upper()

    return US_STATE_ABBREVIATIONS.get(state.lower(), state)


@main_bp.route("/save_item_qty", methods=["POST"])
def save_item_qty_route():
    item_key = normalize(request.form.get("item_key", ""))
    manual_qty = str(request.form.get("manual_qty", "") or "").strip()
    purchasable_item = str(request.form.get("purchasable_item", "") or "").strip()

    if item_key:
        save_item_manual_qty(item_key, manual_qty)
        save_item_purchase_mapping(item_key, purchasable_item)
        update_saved_recipe_purchase_mapping(item_key, purchasable_item)

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        purchase_mapping = purchase_mapping_for_item(item_key, item_state=load_item_state())
        return jsonify({
            "ok": True,
            "item_key": item_key,
            "manual_qty": manual_qty,
            "purchasable_item": purchase_mapping["purchasable_item"],
            "purchase_group": purchase_mapping["purchase_group"],
            "purchase_group_key": purchase_mapping["purchase_group_key"],
        })

    return redirect("/")
