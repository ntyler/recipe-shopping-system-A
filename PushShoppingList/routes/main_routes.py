import html
import json

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
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
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

    for index, recipe in enumerate(recipe_urls, start=1):
        recipe_data = load_saved_recipe_output(recipe["url"])
        sections = build_recipe_sections(recipe_data)

        rows.append({
            "number": index,
            "name": recipe_data.get("recipe_title") or recipe["name"],
            "url": recipe["url"],
            "servings": recipe_data.get("servings"),
            "equipment_items": normalize_text_list(recipe_data.get("equipment", [])),
            "instruction_items": normalize_instruction_items(recipe_data.get("instructions", [])),
            "nutrition_items": normalize_nutrition_items(recipe_data.get("nutrition", {})),
            "sections": sections,
        })

    return rows


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


def build_recipe_sections(recipe_data):
    sections = {section: [] for section in STORE_SECTION_ORDER.keys()}

    for ingredient in recipe_data.get("ingredients", []) or []:
        if not isinstance(ingredient, dict):
            continue

        name = str(ingredient.get("ingredient", "") or "").strip()
        if not name:
            continue

        section = str(ingredient.get("store_section", "") or "MISC").strip().upper()
        if section not in sections:
            section = "MISC"

        sections[section].append({
            "name": name,
            "quantity": ingredient.get("quantity"),
            "unit": ingredient.get("unit"),
            "url": recipe_data.get("source_url"),
        })

    return {
        section: sorted(items, key=lambda item: normalize(item["name"]))
        for section, items in sections.items()
        if items
    }


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
    item_state = load_item_state()

    return render_template(
        "index.html",
        message="",
        raw_items="\n".join(items),
        items=items,
        current_urls=recipe_urls,
        home_address=load_home_address(),
        available_stores=store_settings["stores"],
        enabled_stores=store_settings["enabled_stores"],
        shopping_items=shopping_items_only(items),
        item_state=item_state,
        section_counts=section_counts(items),
        store_view=build_store_view(
            items,
            item_state,
            store_settings["stores"],
            store_settings["enabled_stores"],
        ),
        recipe_view_rows=recipe_view_rows(recipe_urls),
        normalize=normalize,
        is_section_header=is_section_header,
        food_rule_status=shopping_item_food_rule_status,
    )


@main_bp.route("/clear", methods=["POST"])
def clear_list():
    save_items([])

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
