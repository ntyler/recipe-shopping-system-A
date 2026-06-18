import json
import re
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path

from flask import g
from flask import has_request_context

from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.storage_service import scoped_package_path

BASE_DIR = Path(__file__).resolve().parent.parent
COOKBOOKS_FILE = scoped_package_path("cookbooks.json")
COOKBOOKS_LOCK = threading.RLock()
UNCLASSIFIED_COOKBOOK_NAME = "unclassified"
COOKBOOK_CATEGORY_FIELDS = (
    "meal_type",
    "cuisine",
    "main_ingredient",
    "cooking_method",
    "occasion",
    "dietary_preference",
    "prep_time_group",
)
COOKBOOK_CATEGORY_ALL_FIELDS = (*COOKBOOK_CATEGORY_FIELDS, "custom_categories")
COOKBOOK_RECIPE_METADATA_FIELDS = (
    "source_type",
    "recipe_status",
    "menu_section",
    "section_name",
    "menu_item_name",
    "item_name",
    "restaurant_id",
    "menu_id",
    "menu_section_id",
    "menu_item_id",
    "menu_order_url",
    "deep_link_url",
    "menu_description",
    "menu_price",
    "parent_menu_snapshot_id",
    "menu_mega_snapshot_id",
    "menu_snapshot_id",
    "recipe_amount",
    "yield",
    "inferred_by_model",
    "inferred_at",
    "inference_confidence",
)
COOKBOOK_RECIPE_BOOLEAN_METADATA_FIELDS = (
    "ai_inferred",
    "needs_ai_recipe",
)
CATEGORY_SOURCE_USER_SELECTED = "user_selected"
CATEGORY_SOURCE_AI_INFERRED = "ai_inferred"
CATEGORY_SOURCE_BLANK = "blank"
CATEGORY_SOURCE_VALUES = {
    CATEGORY_SOURCE_USER_SELECTED,
    CATEGORY_SOURCE_AI_INFERRED,
    CATEGORY_SOURCE_BLANK,
}

COOKBOOK_MENU_MODES = (
    {
        "key": "restaurant_menu",
        "label": "🍽️ Restaurant Menu",
        "section_field": "restaurant_menu_category",
        "sections": (
            "🥖 Starters",
            "🥗 Salads",
            "🥣 Soups",
            "🍝 Pasta",
            "🐔 Chicken Entrees",
            "🥩 Beef Entrees",
            "🐟 Seafood",
            "🥬 Vegetarian",
            "🍚 Sides",
            "🍰 Desserts",
            "🍹 Drinks",
        ),
        "fallback": "🍽️ Other Recipes",
    },
    {
        "key": "cuisine",
        "label": "🌎 Cuisine",
        "section_field": "cuisine",
        "sections": (
            "🇺🇸 American",
            "🇲🇽 Mexican",
            "🇮🇹 Italian",
            "🇯🇵 Japanese",
            "🇹🇭 Thai",
            "🇨🇳 Chinese",
            "🇮🇳 Indian",
            "🇫🇷 French",
            "🌍 Other / Fusion",
        ),
        "fallback": "🌍 Other / Fusion",
    },
    {
        "key": "main_ingredient",
        "label": "🥩 Main Ingredient",
        "section_field": "main_ingredient",
        "sections": (
            "🐔 Chicken",
            "🥩 Beef",
            "🐷 Pork",
            "🐟 Seafood",
            "🥚 Eggs",
            "🫘 Beans",
            "🥬 Vegetarian",
            "🌱 Vegan",
            "🍝 Pasta",
            "🍚 Rice / Grains",
            "🥔 Potatoes",
            "🧀 Cheese",
        ),
        "fallback": "🍽️ Other",
    },
    {
        "key": "meal_type",
        "label": "🍳 Meal Type",
        "section_field": "meal_type",
        "sections": (
            "🍳 Breakfast",
            "🥪 Lunch",
            "🍽️ Dinner",
            "🥗 Side Dish",
            "🍰 Dessert",
            "🍹 Drink",
            "🥣 Soup",
            "🍱 Meal Prep",
            "🍿 Snack",
        ),
        "fallback": "🍽️ Dinner",
    },
    {
        "key": "cooking_method",
        "label": "🔥 Cooking Method",
        "section_field": "cooking_method",
        "sections": (
            "🔥 Grilled",
            "🍳 Skillet",
            "🥘 One Pot",
            "🍲 Slow Cooker",
            "♨️ Oven Baked",
            "🥗 No Cook",
            "🧊 Make Ahead",
            "⚡ Quick Meal",
        ),
        "fallback": "🍽️ Other",
    },
    {
        "key": "occasion",
        "label": "🎉 Occasion",
        "section_field": "occasion",
        "sections": (
            "❤️ Date Night",
            "👨‍👩‍👧 Family Dinner",
            "🎉 Party Food",
            "🏈 Game Day",
            "🎄 Holiday",
            "☀️ Summer",
            "❄️ Winter",
            "🧺 Potluck",
        ),
        "fallback": "🍽️ Everyday",
    },
    {
        "key": "dietary_preference",
        "label": "🥗 Dietary Preference",
        "section_field": "dietary_preference",
        "sections": (
            "🥩 High Protein",
            "🥗 Low Carb",
            "🌱 Vegan",
            "🌱 Vegetarian",
            "🌾 Gluten Free",
            "🥛 Dairy Free",
            "🧂 Low Sodium",
            "🔥 Spicy",
            "🍬 Low Sugar",
        ),
        "fallback": "🍽️ Flexible",
    },
    {
        "key": "prep_time",
        "label": "⏱️ Prep Time",
        "section_field": "prep_time_group",
        "sections": (
            "⚡ Under 15 Minutes",
            "⏱️ 15–30 Minutes",
            "🕐 30–60 Minutes",
            "⏳ Over 1 Hour",
            "🧊 Make Ahead",
        ),
        "fallback": "⏱️ Time Not Set",
    },
    {
        "key": "alphabetical",
        "label": "🔤 Alphabetical",
        "section_field": "alphabetical_group",
        "sections": tuple(chr(value) for value in range(ord("A"), ord("Z") + 1)),
        "fallback": "#",
    },
    {
        "key": "custom_categories",
        "label": "⭐ Custom Categories",
        "section_field": "custom_categories",
        "sections": (
            "⭐ Sophia’s Favorites",
            "🛒 Tyler’s Meal Prep",
            "🧪 Things We Want To Try",
            "☀️ Summer BBQ",
            "🍽️ Weeknight Dinners",
        ),
        "fallback": "⭐ Uncategorized",
    },
)

COOKBOOK_CATEGORY_CHOICES = {
    "meal_type": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "meal_type"),
    "cuisine": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "cuisine"),
    "main_ingredient": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "main_ingredient"),
    "cooking_method": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "cooking_method"),
    "occasion": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "occasion"),
    "dietary_preference": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "dietary_preference"),
    "prep_time_group": next(mode["sections"] for mode in COOKBOOK_MENU_MODES if mode["key"] == "prep_time"),
}


class CookbookRecipeConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        count = len(conflicts)
        recipe_label = "recipe" if count == 1 else "recipes"
        super().__init__(f"{count} selected {recipe_label} already exists in this cookbook.")


class CookbookCategoryOverwriteConflict(ValueError):
    def __init__(self, recipe_name):
        self.recipe_name = recipe_name
        super().__init__("This recipe already has saved cookbook categories. Confirm before replacing them.")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def cookbook_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(name)).strip("-")
    return slug or "cookbook"


def clean_text(value):
    return " ".join(str(value or "").strip().split())


def recipe_key(value):
    return normalize_recipe_url_key(value)


def clean_text_list(value):
    if isinstance(value, str):
        return [clean_text(value)] if clean_text(value) else []

    if not isinstance(value, list):
        return []

    items = []
    for item in value:
        text = clean_text(item)
        if text:
            items.append(text)

    return items


def clean_custom_categories(value):
    def split_categories(text):
        return [
            cleaned
            for part in re.split(r"[,\n]+", str(text or ""))
            for cleaned in [clean_text(part)]
            if cleaned
        ]

    if isinstance(value, str):
        return split_categories(value)

    if not isinstance(value, list):
        return []

    items = []
    for item in value:
        items.extend(split_categories(item))

    return items


def clean_cover_image(value):
    if not isinstance(value, dict):
        return {}

    cover_image = {}

    for field in ("url", "path", "mime_type", "alt", "source"):
        field_value = clean_text(value.get(field))

        if field_value:
            cover_image[field] = field_value

    for field in ("width", "height"):
        field_value = value.get(field)

        if isinstance(field_value, (int, float)) and field_value > 0:
            cover_image[field] = int(field_value)

    if not cover_image.get("url") and not cover_image.get("path"):
        return {}

    return cover_image


def clean_recipe_sections(value):
    if not isinstance(value, dict):
        return {}

    sections = {}
    allowed_fields = [
        "name",
        "display_name",
        "quantity",
        "base_quantity",
        "scaled_quantity",
        "unit",
        "base_display",
        "quantity_display",
        "url",
    ]

    for section_name, section_items in value.items():
        section_name = clean_text(section_name).upper()
        if not section_name or not isinstance(section_items, list):
            continue

        cleaned_items = []
        for item in section_items:
            if not isinstance(item, dict):
                continue

            cleaned_item = {}
            for field in allowed_fields:
                field_value = item.get(field)
                if field_value is None:
                    continue
                if isinstance(field_value, (int, float)):
                    cleaned_item[field] = field_value
                else:
                    field_value = clean_text(field_value)
                    if field_value:
                        cleaned_item[field] = field_value

            if cleaned_item.get("name") or cleaned_item.get("display_name"):
                cleaned_items.append(cleaned_item)

        if cleaned_items:
            sections[section_name] = cleaned_items

    return sections


def clean_recipe_record(value):
    if isinstance(value, str):
        value = {"url": value}

    if not isinstance(value, dict):
        return None

    url = clean_text(value.get("url"))
    key = recipe_key(url)

    if not key:
        return None

    name = clean_text(value.get("name")) or url
    source_href = clean_text(value.get("source_href")) or url
    source_display_url = clean_text(value.get("source_display_url")) or url
    quantity = value.get("quantity") if value.get("quantity") is not None else 1

    record = {
        "url": url,
        "name": name,
        "number": value.get("number"),
        "source_href": source_href,
        "source_display_url": source_display_url,
        "quantity": quantity,
        "description": clean_text(value.get("description")),
        "servings": clean_text(value.get("servings")),
        "level": clean_text(value.get("level")),
        "prep_time": clean_text(value.get("prep_time")),
        "inactive_time": clean_text(value.get("inactive_time")),
        "cook_time": clean_text(value.get("cook_time")),
        "total_time": clean_text(value.get("total_time")),
        "rating": clean_recipe_rating(value.get("rating")),
        "archive_pdf_available": bool(value.get("archive_pdf_available")),
        "base_servings": clean_text(value.get("base_servings")),
        "scaled_servings": clean_text(value.get("scaled_servings")),
        "equipment_items": clean_text_list(value.get("equipment_items")),
        "instruction_items": clean_text_list(value.get("instruction_items")),
        "sections": clean_recipe_sections(value.get("sections")),
        "custom_categories": clean_custom_categories(value.get("custom_categories")),
        "categories": clean_custom_categories(value.get("categories")),
        "restaurant_menu_category": clean_text(value.get("restaurant_menu_category")),
        "alphabetical_group": clean_text(value.get("alphabetical_group")),
        "category_metadata_user_set": bool(value.get("category_metadata_user_set")),
    }

    for field in COOKBOOK_RECIPE_METADATA_FIELDS:
        record[field] = clean_text(value.get(field))

    for field in COOKBOOK_RECIPE_BOOLEAN_METADATA_FIELDS:
        record[field] = bool(value.get(field))

    for field in COOKBOOK_CATEGORY_FIELDS:
        record[field] = clean_text(value.get(field))

    record["category_metadata_sources"] = stored_category_sources(
        value,
        stored_category_metadata(record),
    )

    cover_image = clean_cover_image(value.get("cover_image"))

    if cover_image:
        record["cover_image"] = cover_image

    return record


def clean_recipe_rating(value):
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, min(5, rating))


def recipe_snapshot_lookup(recipe_rows):
    lookup = {}

    for recipe in recipe_rows or []:
        record = clean_recipe_record(recipe)
        if record:
            lookup[recipe_key(record["url"])] = record

    return lookup


def recipe_ingredients_for_record(recipe):
    ingredients = []
    seen = set()

    for section_items in (recipe.get("sections") or {}).values():
        for item in section_items or []:
            if not isinstance(item, dict):
                continue

            ingredient = clean_text(item.get("name") or item.get("display_name"))
            ingredient_key = normalize_text(ingredient)

            if ingredient and ingredient_key not in seen:
                ingredients.append(ingredient)
                seen.add(ingredient_key)

    return ingredients


def text_items_from_records(items, field_names):
    values = []

    for item in items or []:
        if isinstance(item, dict):
            text = ""
            for field in field_names:
                text = clean_text(item.get(field))
                if text:
                    break
        else:
            text = clean_text(item)

        if text:
            values.append(text)

    return values


def ingredient_sections_from_recipe_data(ingredients):
    section_items = []

    for ingredient in ingredients or []:
        if isinstance(ingredient, dict):
            name = clean_text(
                ingredient.get("ingredient")
                or ingredient.get("name")
                or ingredient.get("display_name")
                or ingredient.get("purchasable_item")
                or ingredient.get("buy_as")
                or ingredient.get("original_text")
            )
        else:
            name = clean_text(ingredient)

        if name:
            section_items.append({"name": name})

    return {"INGREDIENTS": section_items} if section_items else {}


def cookbook_recipe_record_for_url(recipe_url):
    return cookbook_recipe_context_for_url(recipe_url).get("record", {})


def cookbook_recipe_assignment_for_url(recipe_url):
    return cookbook_recipe_context_for_url(recipe_url).get("assignment", {})


def load_cookbooks_raw_payload():
    with COOKBOOKS_LOCK:
        if not COOKBOOKS_FILE.exists():
            return {"cookbooks": []}

        try:
            payload = json.loads(COOKBOOKS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"cookbooks": []}

        return payload if isinstance(payload, dict) else {"cookbooks": []}


def find_cookbook_recipe_context(recipe_url):
    target_key = recipe_key(recipe_url)

    if not target_key:
        return {"record": {}, "assignment": {}}

    payload = load_cookbooks_raw_payload()
    raw_cookbooks = payload.get("cookbooks", []) if isinstance(payload, dict) else []

    for cookbook in raw_cookbooks:
        if not isinstance(cookbook, dict):
            continue

        cookbook_name = clean_text(cookbook.get("name"))
        if not cookbook_name:
            continue

        cookbook_id = clean_text(cookbook.get("id")) or cookbook_slug(cookbook_name)
        assignment = {
            "cookbook_id": cookbook_id,
            "cookbook_name": cookbook_name,
            "cookbook_is_unclassified": is_unclassified_cookbook(cookbook),
        }

        for recipe in cookbook.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            if recipe_key(raw_url) != target_key:
                continue

            record = clean_recipe_record(recipe)
            if not record:
                return {"record": {}, "assignment": {}}

            return {
                "record": record,
                "assignment": assignment,
            }

    return {"record": {}, "assignment": {}}


def cookbook_recipe_context_for_url(recipe_url):
    target_key = recipe_key(recipe_url)

    if not target_key:
        return {"record": {}, "assignment": {}}

    if has_request_context():
        cached = getattr(g, "_cookbook_recipe_contexts", None)
        if cached is None:
            cached = {}
            g._cookbook_recipe_contexts = cached
        if target_key not in cached:
            cached[target_key] = find_cookbook_recipe_context(recipe_url)
        return cached[target_key]

    return find_cookbook_recipe_context(recipe_url)


def normalized_label_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def category_choice_label(field, value):
    text = clean_text(value)

    if not text:
        return ""

    text_key = normalized_label_key(text)
    for choice in COOKBOOK_CATEGORY_CHOICES.get(field, ()):
        if normalized_label_key(choice) == text_key:
            return choice

    return text


def clean_category_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    cleaned = {
        field: category_choice_label(field, payload.get(field))
        for field in COOKBOOK_CATEGORY_FIELDS
    }
    cleaned["custom_categories"] = clean_custom_categories(payload.get("custom_categories"))
    return cleaned


def category_field_has_value(field, value):
    if field == "custom_categories":
        return bool(clean_custom_categories(value))

    return bool(clean_text(value))


def normalize_category_source(value):
    source = clean_text(value)
    return source if source in CATEGORY_SOURCE_VALUES else ""


def clean_category_source_payload(sources, categories=None):
    sources = sources if isinstance(sources, dict) else {}
    categories = categories if isinstance(categories, dict) else {}
    cleaned = {}

    for field in COOKBOOK_CATEGORY_ALL_FIELDS:
        value = categories.get(field)

        if not category_field_has_value(field, value):
            cleaned[field] = CATEGORY_SOURCE_BLANK
            continue

        source = normalize_category_source(sources.get(field))
        if source and source != CATEGORY_SOURCE_BLANK:
            cleaned[field] = source
            continue

        # Older saved records did not have per-field sources. Treat any
        # existing nonblank value as user-selected so missing-only AI inference
        # cannot rewrite legacy saved categories.
        cleaned[field] = CATEGORY_SOURCE_USER_SELECTED

    return cleaned


def stored_category_sources(recipe, metadata=None):
    recipe = recipe if isinstance(recipe, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else stored_category_metadata(recipe)
    return clean_category_source_payload(
        recipe.get("category_metadata_sources"),
        metadata,
    )


def category_sources_have_user_selected(sources):
    sources = sources if isinstance(sources, dict) else {}
    return any(source == CATEGORY_SOURCE_USER_SELECTED for source in sources.values())


def category_metadata_source_label(metadata, sources):
    metadata = metadata if isinstance(metadata, dict) else {}
    sources = sources if isinstance(sources, dict) else {}

    if not category_metadata_has_values(metadata):
        return "Blank"

    if category_sources_have_user_selected(sources):
        return "Saved"

    if any(source == CATEGORY_SOURCE_AI_INFERRED for source in sources.values()):
        return "AI inferred"

    return "Saved"


def stored_category_metadata(recipe):
    recipe = recipe if isinstance(recipe, dict) else {}
    metadata = {}

    for field in COOKBOOK_CATEGORY_FIELDS:
        value = recipe.get(field)
        if field == "prep_time_group":
            value = value or recipe.get("prep_time_category")
        metadata[field] = category_choice_label(field, value)

    metadata["custom_categories"] = clean_custom_categories(recipe.get("custom_categories"))
    return metadata


def category_metadata_has_values(metadata):
    return any(metadata.get(field) for field in COOKBOOK_CATEGORY_FIELDS) or bool(metadata.get("custom_categories"))


def category_metadata_changed(left, right):
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}

    for field in COOKBOOK_CATEGORY_FIELDS:
        if clean_text(left.get(field)) != clean_text(right.get(field)):
            return True

    return clean_custom_categories(left.get("custom_categories")) != clean_custom_categories(right.get("custom_categories"))


def recipe_text_for_inference(recipe):
    parts = [
        recipe.get("name"),
        recipe.get("description"),
        recipe.get("prep_time"),
        recipe.get("cook_time"),
        recipe.get("total_time"),
    ]
    parts.extend(recipe.get("equipment_items") or [])
    parts.extend(recipe.get("instruction_items") or [])
    parts.extend(recipe_ingredients_for_record(recipe))
    return normalize_text(" ".join(clean_text(part) for part in parts if clean_text(part)))


def text_has_any(text, *terms):
    return any(term in text for term in terms)


def duration_minutes(value):
    text = normalize_text(value)

    if not text:
        return None

    minutes = 0.0
    matched = False

    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m)\b", text):
        amount = float(number)
        matched = True
        if unit.startswith("h"):
            minutes += amount * 60
        else:
            minutes += amount

    if matched:
        return int(round(minutes))

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return int(round(float(text)))

    return None


def infer_prep_time_group(recipe, text):
    if text_has_any(text, "make ahead", "overnight", "freezer"):
        return "🧊 Make Ahead"

    minutes = duration_minutes(recipe.get("total_time"))
    if minutes is None:
        minutes = duration_minutes(recipe.get("prep_time"))

    if minutes is None:
        title_match = re.search(r"\b(\d{1,3})\s*(?:minute|min)\b", text)
        minutes = int(title_match.group(1)) if title_match else None

    if minutes is None:
        return ""
    if minutes < 15:
        return "⚡ Under 15 Minutes"
    if minutes <= 30:
        return "⏱️ 15–30 Minutes"
    if minutes <= 60:
        return "🕐 30–60 Minutes"
    return "⏳ Over 1 Hour"


def infer_recipe_categories(recipe):
    text = recipe_text_for_inference(recipe)
    metadata = {
        "meal_type": "",
        "cuisine": "",
        "main_ingredient": "",
        "cooking_method": "",
        "occasion": "",
        "dietary_preference": "",
        "prep_time_group": "",
    }

    if text_has_any(text, "margarita", "cocktail", "latte", "smoothie", "lemonade", "drink", "beverage"):
        metadata["meal_type"] = "🍹 Drink"
    elif text_has_any(text, "cake", "cookie", "brownie", "pie", "cobbler", "muffin", "chocolate", "dessert", "ice cream"):
        metadata["meal_type"] = "🍰 Dessert"
    elif text_has_any(text, "soup", "stew", "chowder", "bisque"):
        metadata["meal_type"] = "🥣 Soup"
    elif text_has_any(text, "breakfast", "pancake", "waffle", "omelet", "frittata", "scramble"):
        metadata["meal_type"] = "🍳 Breakfast"
    elif text_has_any(text, "sandwich", "wrap", "panini"):
        metadata["meal_type"] = "🥪 Lunch"
    elif text_has_any(text, "side dish", "side", "potatoes", "rice pilaf"):
        metadata["meal_type"] = "🥗 Side Dish"
    elif text_has_any(text, "meal prep", "meal-prep", "bowl"):
        metadata["meal_type"] = "🍱 Meal Prep"
    elif text_has_any(text, "snack", "pretzel", "popcorn", "dip"):
        metadata["meal_type"] = "🍿 Snack"
    else:
        metadata["meal_type"] = "🍽️ Dinner"

    if text_has_any(text, "taco", "burrito", "enchilada", "fajita", "salsa", "queso", "margarita", "carnitas", "verde", "tortilla"):
        metadata["cuisine"] = "🇲🇽 Mexican"
    elif text_has_any(text, "alfredo", "pasta", "ravioli", "lasagna", "spaghetti", "pizza", "parmesan", "risotto", "pesto"):
        metadata["cuisine"] = "🇮🇹 Italian"
    elif text_has_any(text, "sushi", "ramen", "teriyaki", "miso", "udon"):
        metadata["cuisine"] = "🇯🇵 Japanese"
    elif text_has_any(text, "thai", "pad thai", "coconut curry", "thai basil"):
        metadata["cuisine"] = "🇹🇭 Thai"
    elif text_has_any(text, "stir fry", "lo mein", "fried rice", "dumpling", "kung pao"):
        metadata["cuisine"] = "🇨🇳 Chinese"
    elif text_has_any(text, "tikka", "masala", "dal", "naan", "paneer", "garam", "vindaloo"):
        metadata["cuisine"] = "🇮🇳 Indian"
    elif text_has_any(text, "quiche", "ratatouille", "crepe", "souffle", "croissant", "coq au vin"):
        metadata["cuisine"] = "🇫🇷 French"
    elif text_has_any(text, "burger", "chili", "bbq", "barbecue", "meatloaf", "casserole", "mac and cheese", "pancake", "muffin"):
        metadata["cuisine"] = "🇺🇸 American"
    else:
        metadata["cuisine"] = "🌍 Other / Fusion"

    if text_has_any(text, "chicken", "turkey"):
        metadata["main_ingredient"] = "🐔 Chicken"
    elif text_has_any(text, "beef", "steak", "ground beef", "short rib", "brisket"):
        metadata["main_ingredient"] = "🥩 Beef"
    elif text_has_any(text, "pork", "bacon", "ham", "sausage", "prosciutto"):
        metadata["main_ingredient"] = "🐷 Pork"
    elif text_has_any(text, "fish", "salmon", "tuna", "shrimp", "crab", "cod", "seafood", "lobster"):
        metadata["main_ingredient"] = "🐟 Seafood"
    elif text_has_any(text, "egg", "eggs", "omelet", "frittata"):
        metadata["main_ingredient"] = "🥚 Eggs"
    elif text_has_any(text, "bean", "beans", "lentil", "chickpea", "black bean"):
        metadata["main_ingredient"] = "🫘 Beans"
    elif text_has_any(text, "pasta", "spaghetti", "ravioli", "lasagna", "noodle", "macaroni"):
        metadata["main_ingredient"] = "🍝 Pasta"
    elif text_has_any(text, "rice", "quinoa", "grain", "farro", "barley"):
        metadata["main_ingredient"] = "🍚 Rice / Grains"
    elif text_has_any(text, "potato", "potatoes", "sweet potato"):
        metadata["main_ingredient"] = "🥔 Potatoes"
    elif text_has_any(text, "cheese", "ricotta", "mozzarella", "cheddar", "parmesan"):
        metadata["main_ingredient"] = "🧀 Cheese"
    elif text_has_any(text, "vegetarian", "vegan", "tofu", "tempeh", "jackfruit", "vegetable", "spinach", "mushroom", "salad"):
        metadata["main_ingredient"] = "🥬 Vegetarian"

    if text_has_any(text, "grill", "grilled", "bbq", "barbecue"):
        metadata["cooking_method"] = "🔥 Grilled"
    elif text_has_any(text, "skillet", "pan fry", "pan-fry", "saute", "sauté"):
        metadata["cooking_method"] = "🍳 Skillet"
    elif text_has_any(text, "one pot", "one-pot", "dutch oven"):
        metadata["cooking_method"] = "🥘 One Pot"
    elif text_has_any(text, "slow cooker", "crockpot", "crock pot"):
        metadata["cooking_method"] = "🍲 Slow Cooker"
    elif text_has_any(text, "baked", "bake", "oven", "roast", "casserole"):
        metadata["cooking_method"] = "♨️ Oven Baked"
    elif metadata["meal_type"] == "🍹 Drink" or text_has_any(text, "no cook", "no-cook", "salad"):
        metadata["cooking_method"] = "🥗 No Cook"
    elif text_has_any(text, "make ahead", "overnight", "freezer"):
        metadata["cooking_method"] = "🧊 Make Ahead"
    elif text_has_any(text, "quick", "easy") or (duration_minutes(recipe.get("total_time")) or 999) <= 30:
        metadata["cooking_method"] = "⚡ Quick Meal"

    if text_has_any(text, "date night", "steak", "lobster", "alfredo"):
        metadata["occasion"] = "❤️ Date Night"
    elif text_has_any(text, "party", "appetizer", "sliders", "dip"):
        metadata["occasion"] = "🎉 Party Food"
    elif text_has_any(text, "game day", "wings", "nachos", "buffalo", "chili"):
        metadata["occasion"] = "🏈 Game Day"
    elif text_has_any(text, "holiday", "christmas", "thanksgiving", "easter"):
        metadata["occasion"] = "🎄 Holiday"
    elif text_has_any(text, "summer", "bbq", "barbecue", "grilled"):
        metadata["occasion"] = "☀️ Summer"
    elif text_has_any(text, "winter", "soup", "stew", "chili"):
        metadata["occasion"] = "❄️ Winter"
    elif text_has_any(text, "potluck", "casserole", "pasta salad"):
        metadata["occasion"] = "🧺 Potluck"
    elif metadata["meal_type"] == "🍽️ Dinner":
        metadata["occasion"] = "👨‍👩‍👧 Family Dinner"

    if metadata["main_ingredient"] in {"🐔 Chicken", "🥩 Beef", "🐷 Pork", "🐟 Seafood", "🥚 Eggs"} or "protein" in text:
        metadata["dietary_preference"] = "🥩 High Protein"
    if text_has_any(text, "low carb", "keto") or (metadata["meal_type"] == "🥗 Side Dish" and "salad" in text):
        metadata["dietary_preference"] = "🥗 Low Carb"
    if "vegan" in text:
        metadata["dietary_preference"] = "🌱 Vegan"
    elif metadata["main_ingredient"] == "🥬 Vegetarian" or "vegetarian" in text:
        metadata["dietary_preference"] = "🌱 Vegetarian"
    if text_has_any(text, "gluten free", "gluten-free"):
        metadata["dietary_preference"] = "🌾 Gluten Free"
    if text_has_any(text, "dairy free", "dairy-free"):
        metadata["dietary_preference"] = "🥛 Dairy Free"
    if text_has_any(text, "low sodium", "low-sodium"):
        metadata["dietary_preference"] = "🧂 Low Sodium"
    if text_has_any(text, "spicy", "jalapeno", "jalapeño", "buffalo", "hot sauce"):
        metadata["dietary_preference"] = "🔥 Spicy"
    if text_has_any(text, "low sugar", "low-sugar", "sugar free", "sugar-free"):
        metadata["dietary_preference"] = "🍬 Low Sugar"

    metadata["prep_time_group"] = infer_prep_time_group(recipe, text)
    metadata["restaurant_menu_category"] = infer_restaurant_menu_category(metadata, text)
    metadata["alphabetical_group"] = infer_alphabetical_group(recipe.get("name"))
    return metadata


def infer_restaurant_menu_category(metadata, text):
    meal_type = metadata.get("meal_type")
    main = metadata.get("main_ingredient")

    if meal_type == "🍹 Drink":
        return "🍹 Drinks"
    if meal_type == "🍰 Dessert":
        return "🍰 Desserts"
    if text_has_any(text, "starter", "appetizer", "dip", "snack", "pretzel"):
        return "🥖 Starters"
    if text_has_any(text, "salad"):
        return "🥗 Salads"
    if meal_type == "🥣 Soup":
        return "🥣 Soups"
    if main == "🍝 Pasta" or text_has_any(text, "pasta", "alfredo", "ravioli", "lasagna", "spaghetti"):
        return "🍝 Pasta"
    if main == "🐔 Chicken":
        return "🐔 Chicken Entrees"
    if main == "🥩 Beef":
        return "🥩 Beef Entrees"
    if main == "🐟 Seafood":
        return "🐟 Seafood"
    if main in {"🥬 Vegetarian", "🌱 Vegan"}:
        return "🥬 Vegetarian"
    if meal_type == "🥗 Side Dish":
        return "🍚 Sides"
    return ""


def infer_alphabetical_group(name):
    match = re.search(r"[A-Za-z]", str(name or ""))
    return match.group(0).upper() if match else "#"


def restaurant_menu_category_from_stored_metadata(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    return infer_restaurant_menu_category(metadata, "")


def recipe_short_description(recipe):
    description = clean_text(recipe.get("description"))

    if description:
        return description

    ingredients = recipe_ingredients_for_record(recipe)[:3]
    if ingredients:
        return f"Featuring {', '.join(ingredients)}."

    instructions = clean_text(" ".join(recipe.get("instruction_items") or []))
    if instructions:
        return instructions[:137].rstrip() + ("..." if len(instructions) > 137 else "")

    return ""


def apply_recipe_menu_metadata(recipe):
    if not isinstance(recipe, dict):
        return recipe

    stored = stored_category_metadata(recipe)
    sources = stored_category_sources(recipe, stored)

    for field in COOKBOOK_CATEGORY_FIELDS:
        recipe[field] = stored.get(field, "")

    recipe["custom_categories"] = stored.get("custom_categories") or []
    recipe["restaurant_menu_category"] = (
        clean_text(recipe.get("restaurant_menu_category"))
        or restaurant_menu_category_from_stored_metadata(stored)
    )
    recipe["alphabetical_group"] = clean_text(recipe.get("alphabetical_group")) or infer_alphabetical_group(recipe.get("name"))
    recipe["category_metadata_sources"] = sources
    recipe["category_metadata_user_set"] = category_sources_have_user_selected(sources)
    recipe["category_metadata_source"] = category_metadata_source_label(stored, sources)
    recipe["short_description"] = recipe_short_description(recipe)
    recipe["menu_tags"] = recipe_menu_tags(recipe)
    recipe["category_display"] = build_recipe_category_display(recipe)
    recipe["menu_search_text"] = recipe_menu_search_text(recipe)
    return recipe


def recipe_category_metadata_for_editor(recipe_url, recipe_data=None, recipe_meta=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    stored_record = cookbook_recipe_record_for_url(recipe_url)
    stored_metadata = stored_category_metadata(stored_record)
    record = {
        **stored_record,
        "url": clean_text(recipe_url) or stored_record.get("url", ""),
        "name": (
            clean_text(recipe_meta.get("name"))
            or clean_text(recipe_data.get("display_name"))
            or clean_text(recipe_data.get("recipe_title"))
            or stored_record.get("name")
            or clean_text(recipe_url)
        ),
        "description": clean_text(recipe_data.get("description")) or stored_record.get("description", ""),
        "prep_time": clean_text(recipe_data.get("prep_time")) or stored_record.get("prep_time", ""),
        "cook_time": clean_text(recipe_data.get("cook_time")) or stored_record.get("cook_time", ""),
        "total_time": clean_text(recipe_data.get("total_time")) or stored_record.get("total_time", ""),
    }

    sections = ingredient_sections_from_recipe_data(recipe_data.get("ingredients", []))
    if sections:
        record["sections"] = sections

    equipment_items = text_items_from_records(
        recipe_data.get("equipment", []),
        ("equipment", "text", "name"),
    )
    if equipment_items:
        record["equipment_items"] = equipment_items

    instruction_items = text_items_from_records(
        recipe_data.get("instructions", []),
        ("instruction", "text"),
    )
    if instruction_items:
        record["instruction_items"] = instruction_items

    for field in COOKBOOK_CATEGORY_FIELDS:
        record[field] = stored_metadata.get(field, "")

    record["custom_categories"] = stored_metadata.get("custom_categories", [])
    record["category_metadata_user_set"] = bool(
        stored_record.get("category_metadata_user_set")
    ) or category_metadata_has_values(stored_metadata)

    apply_recipe_menu_metadata(record)

    return {
        **{
            field: record.get(field, "")
            for field in COOKBOOK_CATEGORY_FIELDS
        },
        "custom_categories": record.get("custom_categories", []),
        "restaurant_menu_category": record.get("restaurant_menu_category", ""),
        "alphabetical_group": record.get("alphabetical_group", ""),
        "category_metadata_sources": record.get("category_metadata_sources", {}),
        "category_metadata_user_set": bool(record.get("category_metadata_user_set")),
        "category_metadata_source": record.get("category_metadata_source", ""),
        "short_description": record.get("short_description", ""),
        "menu_tags": record.get("menu_tags", []),
    }


def add_recipe_category_display_value(tags, seen, value, field=None, split=False):
    values = clean_custom_categories(value) if split else clean_text_list(value)

    if field:
        values = [
            category_choice_label(field, value)
            for value in values
        ]

    for value in values:
        key = normalized_label_key(value)
        if value and key and key not in seen:
            tags.append(value)
            seen.add(key)


def recipe_category_display_values(recipe):
    tags = []
    seen = set()

    for field in (
        "meal_type",
        "cuisine",
        "main_ingredient",
        "cooking_method",
        "occasion",
        "dietary_preference",
    ):
        add_recipe_category_display_value(tags, seen, recipe.get(field), field=field)

    add_recipe_category_display_value(
        tags,
        seen,
        recipe.get("prep_time_group") or recipe.get("prep_time_category"),
        field="prep_time_group",
    )
    add_recipe_category_display_value(tags, seen, recipe.get("custom_categories"), split=True)
    add_recipe_category_display_value(tags, seen, recipe.get("categories"), split=True)

    return tags


def recipe_menu_tags(recipe):
    return recipe_category_display_values(recipe)


def build_recipe_category_display(recipe):
    tags = recipe_category_display_values(recipe if isinstance(recipe, dict) else {})
    return ", ".join(tags) if tags else "Blank"


def recipe_menu_search_text(recipe):
    parts = [
        recipe.get("name"),
        recipe.get("short_description"),
        recipe.get("meal_type"),
        recipe.get("cuisine"),
        recipe.get("main_ingredient"),
        recipe.get("cooking_method"),
        recipe.get("occasion"),
        recipe.get("dietary_preference"),
        recipe.get("prep_time_group"),
        recipe.get("restaurant_menu_category"),
    ]
    parts.extend(recipe.get("custom_categories") or [])
    parts.extend(clean_custom_categories(recipe.get("categories")))
    parts.extend(recipe_ingredients_for_record(recipe))
    return normalize_text(" ".join(clean_text(part) for part in parts if clean_text(part)))


def cookbook_menu_sort_options():
    return [
        {
            "key": mode["key"],
            "label": mode["label"],
        }
        for mode in COOKBOOK_MENU_MODES
    ]


def cookbook_category_choices():
    return {
        field: list(choices)
        for field, choices in COOKBOOK_CATEGORY_CHOICES.items()
    }


def recipe_section_labels_for_mode(recipe, mode):
    field = mode.get("section_field", "")

    if mode.get("key") == "custom_categories":
        return clean_text_list(recipe.get("custom_categories")) or [mode.get("fallback")]

    value = clean_text(recipe.get(field))
    return [value or mode.get("fallback")]


def cookbook_menu_sections(recipes):
    sections_by_mode = {}

    for mode in COOKBOOK_MENU_MODES:
        ordered_labels = list(mode.get("sections") or [])
        section_recipes = {label: [] for label in ordered_labels}
        fallback = mode.get("fallback")

        if fallback and fallback not in section_recipes:
            section_recipes[fallback] = []

        for recipe in recipes or []:
            for label in recipe_section_labels_for_mode(recipe, mode):
                label = clean_text(label) or fallback

                if not label:
                    continue

                if label not in section_recipes:
                    section_recipes[label] = []
                    ordered_labels.append(label)

                section_recipes[label].append(recipe)

        labels = [
            label
            for label in ordered_labels
            if label in section_recipes
        ]
        if fallback and fallback in section_recipes and fallback not in labels:
            labels.append(fallback)

        sections_by_mode[mode["key"]] = [
            {
                "label": label,
                "recipes": section_recipes.get(label, []),
            }
            for label in labels
        ]

    return sections_by_mode


def prepare_cookbook_menu_view(view):
    view = view if isinstance(view, dict) else {}
    view["menu_sort_options"] = cookbook_menu_sort_options()
    view["category_choices"] = cookbook_category_choices()

    for cookbook in view.get("cookbooks", []):
        for recipe in cookbook.get("recipes", []):
            apply_recipe_menu_metadata(recipe)

        cookbook["menu_sections"] = cookbook_menu_sections(cookbook.get("recipes", []))

    for recipe in view.get("recipes", []):
        apply_recipe_menu_metadata(recipe)

    return view


def normalize_cookbooks_payload(payload):
    cookbooks = []
    seen_ids = set()
    raw_cookbooks = payload.get("cookbooks", []) if isinstance(payload, dict) else []

    for cookbook in raw_cookbooks:
        if not isinstance(cookbook, dict):
            continue

        name = clean_text(cookbook.get("name"))

        if not name:
            continue

        cookbook_id = clean_text(cookbook.get("id")) or cookbook_slug(name)
        if not cookbook_id or cookbook_id in seen_ids:
            cookbook_id = unique_cookbook_id({"cookbooks": cookbooks}, name)

        seen_ids.add(cookbook_id)
        recipes = []
        seen_recipes = set()

        for recipe in cookbook.get("recipes", []):
            record = clean_recipe_record(recipe)
            if not record:
                continue

            key = recipe_key(record["url"])
            if key not in seen_recipes:
                recipes.append(record)
                seen_recipes.add(key)

        cookbooks.append({
            "id": cookbook_id,
            "name": name,
            "recipes": recipes,
        })

    return {"cookbooks": cookbooks}


def load_cookbooks():
    with COOKBOOKS_LOCK:
        if not COOKBOOKS_FILE.exists():
            return {"cookbooks": []}

        try:
            payload = json.loads(COOKBOOKS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"cookbooks": []}

        return normalize_cookbooks_payload(payload)


def clear_cookbook_request_cache():
    if not has_request_context():
        return

    for name in (
        "_cookbook_recipe_contexts",
        "_cookbook_recipe_index",
    ):
        if hasattr(g, name):
            delattr(g, name)


def save_cookbooks(payload):
    with COOKBOOKS_LOCK:
        normalized = normalize_cookbooks_payload(payload)
        COOKBOOKS_FILE.write_text(
            json.dumps(normalized, indent=2) + "\n",
            encoding="utf-8",
        )
        clear_cookbook_request_cache()
        return normalized


def unique_cookbook_id(payload, name):
    existing = {
        str(cookbook.get("id") or "")
        for cookbook in payload.get("cookbooks", [])
    }
    base = cookbook_slug(name)

    if base not in existing:
        return base

    index = 2
    while f"{base}-{index}" in existing:
        index += 1

    return f"{base}-{index}"


def find_cookbook(payload, cookbook_id):
    for cookbook in payload.get("cookbooks", []):
        if cookbook.get("id") == cookbook_id:
            return cookbook

    return None


def find_cookbook_by_name(payload, name):
    name_key = normalize_text(name)

    for cookbook in payload.get("cookbooks", []):
        if normalize_text(cookbook.get("name")) == name_key:
            return cookbook

    return None


def is_unclassified_cookbook(cookbook):
    cookbook = cookbook or {}
    unclassified_key = normalize_text(UNCLASSIFIED_COOKBOOK_NAME)

    return (
        normalize_text(cookbook.get("name")) == unclassified_key
        or normalize_text(cookbook.get("id")) == unclassified_key
    )


def ensure_unclassified_cookbook(payload):
    unclassified = find_cookbook_by_name(payload, UNCLASSIFIED_COOKBOOK_NAME)

    if unclassified is None:
        unclassified = {
            "id": unique_cookbook_id(payload, UNCLASSIFIED_COOKBOOK_NAME),
            "name": UNCLASSIFIED_COOKBOOK_NAME,
            "recipes": [],
        }
        payload.setdefault("cookbooks", []).append(unclassified)

    unclassified.setdefault("recipes", [])
    return unclassified


def add_recipe_to_unclassified(payload, recipe):
    record = clean_recipe_record(recipe)

    if not record:
        return False

    unclassified = ensure_unclassified_cookbook(payload)
    key = recipe_key(record.get("url"))
    existing_keys = {
        recipe_key(item.get("url"))
        for item in unclassified.get("recipes", [])
        if recipe_key(item.get("url"))
    }

    if key and key not in existing_keys:
        unclassified.setdefault("recipes", []).append(record)
        return True

    return False


def build_cookbook_recipe_index():
    payload = load_cookbooks()
    assignments = {}
    records_by_key = {}

    for cookbook in payload.get("cookbooks", []):
        cookbook_id = cookbook.get("id", "")
        cookbook_name = cookbook.get("name", "")
        cookbook_is_unclassified = is_unclassified_cookbook(cookbook)

        for recipe in cookbook.get("recipes", []):
            record = clean_recipe_record(recipe)
            key = recipe_key(record.get("url") if record else recipe.get("url"))

            if key and key not in assignments:
                assignments[key] = {
                    "cookbook_id": cookbook_id,
                    "cookbook_name": cookbook_name,
                    "cookbook_is_unclassified": cookbook_is_unclassified,
                }

            if key and record and key not in records_by_key:
                records_by_key[key] = record

    return {
        "assignments": assignments,
        "records_by_key": records_by_key,
    }


def cookbook_recipe_index():
    if has_request_context():
        cached = getattr(g, "_cookbook_recipe_index", None)
        if cached is None:
            cached = build_cookbook_recipe_index()
            g._cookbook_recipe_index = cached
        return cached

    return build_cookbook_recipe_index()


def recipe_cookbook_assignments():
    return cookbook_recipe_index().get("assignments", {})


def ensure_unclassified_cookbook_for_recipes(recipes):
    recipe_records = []
    seen_keys = set()

    for recipe in recipes or []:
        record = clean_recipe_record(recipe)
        if not record:
            continue

        key = recipe_key(record.get("url"))
        if key and key not in seen_keys:
            recipe_records.append(record)
            seen_keys.add(key)

    if not recipe_records:
        return load_cookbooks()

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        assigned_keys = {
            recipe_key(recipe.get("url"))
            for cookbook in payload.get("cookbooks", [])
            for recipe in cookbook.get("recipes", [])
            if recipe_key(recipe.get("url"))
        }
        unclassified = find_cookbook_by_name(payload, UNCLASSIFIED_COOKBOOK_NAME)
        changed = False

        for record in recipe_records:
            key = recipe_key(record.get("url"))

            if not key or key in assigned_keys:
                continue

            if unclassified is None:
                unclassified = ensure_unclassified_cookbook(payload)

            unclassified.setdefault("recipes", []).append(record)
            assigned_keys.add(key)
            changed = True

        if changed:
            return save_cookbooks(payload)

        return payload


def create_cookbook(name):
    name = clean_text(name)

    if not name:
        raise ValueError("Cookbook name is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        name_key = normalize_text(name)

        if any(normalize_text(cookbook.get("name")) == name_key for cookbook in payload["cookbooks"]):
            raise ValueError("A cookbook with that name already exists.")

        new_cookbook = {
            "id": unique_cookbook_id(payload, name),
            "name": name,
            "recipes": [],
        }
        payload["cookbooks"].append(new_cookbook)

        saved = save_cookbooks(payload)
        return find_cookbook(saved, new_cookbook["id"]) or new_cookbook


def find_or_create_cookbook(name):
    name = clean_text(name)

    if not name:
        raise ValueError("Cookbook name is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        existing = find_cookbook_by_name(payload, name)

        if existing is not None:
            existing.setdefault("recipes", [])
            return existing

        new_cookbook = {
            "id": unique_cookbook_id(payload, name),
            "name": name,
            "recipes": [],
        }
        payload["cookbooks"].append(new_cookbook)

        saved = save_cookbooks(payload)
        return find_cookbook(saved, new_cookbook["id"]) or new_cookbook


def resolve_cookbook_destination(cookbook_id="", cookbook_name="", create_missing=False):
    cookbook_id = clean_text(cookbook_id)
    cookbook_name = clean_text(cookbook_name)

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()

        if cookbook_id:
            cookbook = find_cookbook(payload, cookbook_id)
            if cookbook is not None:
                cookbook.setdefault("recipes", [])
                return cookbook

        if cookbook_name:
            if normalize_text(cookbook_name) == normalize_text(UNCLASSIFIED_COOKBOOK_NAME):
                cookbook = ensure_unclassified_cookbook(payload)
                saved = save_cookbooks(payload)
                return find_cookbook(saved, cookbook.get("id", "")) or cookbook

            cookbook = find_cookbook_by_name(payload, cookbook_name)
            if cookbook is not None:
                cookbook.setdefault("recipes", [])
                return cookbook

            if create_missing:
                new_cookbook = {
                    "id": unique_cookbook_id(payload, cookbook_name),
                    "name": cookbook_name,
                    "recipes": [],
                }
                payload["cookbooks"].append(new_cookbook)
                saved = save_cookbooks(payload)
                return find_cookbook(saved, new_cookbook["id"]) or new_cookbook

        return None


def delete_cookbook(cookbook_id):
    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        if is_unclassified_cookbook(target):
            raise ValueError("The unclassified cookbook cannot be deleted.")

        for recipe in target.get("recipes", []):
            add_recipe_to_unclassified(payload, recipe)

        payload["cookbooks"] = [
            cookbook
            for cookbook in payload["cookbooks"]
            if cookbook.get("id") != cookbook_id
        ]
        return save_cookbooks(payload)


def delete_cookbook_and_purge_recipe_urls(cookbook_id):
    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        if is_unclassified_cookbook(target):
            raise ValueError("The unclassified cookbook cannot be purged.")

        purge_keys = set()
        purge_urls = []

        for recipe in target.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            url = clean_text(raw_url)
            key = recipe_key(url)

            if key and key not in purge_keys:
                purge_keys.add(key)
                purge_urls.append(url)

        payload["cookbooks"] = [
            cookbook
            for cookbook in payload["cookbooks"]
            if cookbook.get("id") != cookbook_id
        ]

        if purge_keys:
            for cookbook in payload["cookbooks"]:
                cookbook["recipes"] = [
                    recipe
                    for recipe in cookbook.get("recipes", [])
                    if recipe_key(recipe.get("url") if isinstance(recipe, dict) else recipe) not in purge_keys
                ]

        save_cookbooks(payload)
        return purge_urls


def purge_unclassified_cookbook_recipe_urls(cookbook_id):
    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        if not is_unclassified_cookbook(target):
            raise ValueError("Only the unclassified cookbook can purge recipes without deleting the cookbook.")

        purge_keys = set()
        purge_urls = []

        for recipe in target.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            url = clean_text(raw_url)
            key = recipe_key(url)

            if key and key not in purge_keys:
                purge_keys.add(key)
                purge_urls.append(url)

        target_id = target.get("id")
        for cookbook in payload.get("cookbooks", []):
            if cookbook.get("id") == target_id:
                cookbook["recipes"] = []
                continue

            if purge_keys:
                cookbook["recipes"] = [
                    recipe
                    for recipe in cookbook.get("recipes", [])
                    if recipe_key(recipe.get("url") if isinstance(recipe, dict) else recipe) not in purge_keys
                ]

        save_cookbooks(payload)
        return purge_urls


def rename_cookbook(cookbook_id, name):
    name = clean_text(name)

    if not name:
        raise ValueError("Cookbook name is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        if is_unclassified_cookbook(target):
            raise ValueError("The unclassified cookbook cannot be renamed.")

        name_key = normalize_text(name)
        for cookbook in payload["cookbooks"]:
            if cookbook.get("id") != cookbook_id and normalize_text(cookbook.get("name")) == name_key:
                raise ValueError("A cookbook with that name already exists.")

        target["name"] = name
        return save_cookbooks(payload)


def reorder_cookbooks(cookbook_ids):
    requested_ids = []
    seen_requested = set()

    for cookbook_id in cookbook_ids or []:
        cookbook_id = clean_text(cookbook_id)

        if cookbook_id and cookbook_id not in seen_requested:
            requested_ids.append(cookbook_id)
            seen_requested.add(cookbook_id)

    if not requested_ids:
        raise ValueError("Cookbook order is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        current_cookbooks = payload.get("cookbooks", [])
        current_by_id = {
            cookbook.get("id"): cookbook
            for cookbook in current_cookbooks
            if cookbook.get("id")
        }
        ordered_cookbooks = []
        seen = set()

        for cookbook_id in requested_ids:
            cookbook = current_by_id.get(cookbook_id)

            if cookbook is not None and cookbook_id not in seen:
                ordered_cookbooks.append(cookbook)
                seen.add(cookbook_id)

        for cookbook in current_cookbooks:
            cookbook_id = cookbook.get("id")

            if cookbook_id and cookbook_id not in seen:
                ordered_cookbooks.append(cookbook)
                seen.add(cookbook_id)

        if current_cookbooks and not ordered_cookbooks:
            raise ValueError("No cookbooks matched the requested order.")

        payload["cookbooks"] = ordered_cookbooks
        return save_cookbooks(payload).get("cookbooks", [])


def move_recipes_to_cookbook(
    cookbook_id,
    recipe_urls,
    recipe_rows=None,
    overwrite_existing=False,
    insert_before_recipe_url="",
    insert_after_recipe_url="",
):
    available_recipes = recipe_snapshot_lookup(recipe_rows)

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Choose a cookbook.")

        stored_recipes = {}
        for cookbook in payload["cookbooks"]:
            for recipe in cookbook.get("recipes", []):
                record = clean_recipe_record(recipe)
                if not record:
                    continue

                key = recipe_key(record["url"])
                if key and key not in stored_recipes:
                    stored_recipes[key] = record

        selected_recipes = []
        selected_keys = set()

        for recipe_url in recipe_urls:
            key = recipe_key(recipe_url)
            if not key or key in selected_keys:
                continue

            record = available_recipes.get(key) or stored_recipes.get(key) or clean_recipe_record(recipe_url)
            if record:
                selected_recipes.append(record)
                selected_keys.add(key)

        if not selected_recipes:
            raise ValueError("Select at least one recipe.")

        target_recipes_by_key = {
            recipe_key(recipe.get("url")): recipe
            for recipe in target.get("recipes", [])
            if recipe_key(recipe.get("url"))
        }
        conflicts = []

        if not overwrite_existing:
            for recipe in selected_recipes:
                key = recipe_key(recipe.get("url"))
                existing_recipe = target_recipes_by_key.get(key)

                if existing_recipe:
                    conflicts.append({
                        "url": recipe.get("url", ""),
                        "name": recipe.get("name") or existing_recipe.get("name") or recipe.get("url", ""),
                    })

        if conflicts:
            raise CookbookRecipeConflict(conflicts)

        for cookbook in payload["cookbooks"]:
            cookbook["recipes"] = [
                recipe
                for recipe in cookbook.get("recipes", [])
                if recipe_key(recipe.get("url")) not in selected_keys
            ]

        before_key = recipe_key(insert_before_recipe_url)
        after_key = recipe_key(insert_after_recipe_url)
        target_recipes = target.setdefault("recipes", [])
        insert_index = len(target_recipes)

        if before_key:
            for index, recipe in enumerate(target_recipes):
                if recipe_key(recipe.get("url")) == before_key:
                    insert_index = index
                    break
        elif after_key:
            for index, recipe in enumerate(target_recipes):
                if recipe_key(recipe.get("url")) == after_key:
                    insert_index = index + 1
                    break

        target["recipes"] = [
            *target_recipes[:insert_index],
            *selected_recipes,
            *target_recipes[insert_index:],
        ]
        return save_cookbooks(payload)


def remove_recipe_from_cookbook(cookbook_id, recipe_url):
    target_key = recipe_key(recipe_url)

    if not target_key:
        raise ValueError("Recipe is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        removed_recipes = [
            recipe
            for recipe in target.get("recipes", [])
            if recipe_key(recipe.get("url")) == target_key
        ]
        target["recipes"] = [
            recipe
            for recipe in target.get("recipes", [])
            if recipe_key(recipe.get("url")) != target_key
        ]

        if not is_unclassified_cookbook(target):
            for recipe in removed_recipes:
                add_recipe_to_unclassified(payload, recipe)

        return save_cookbooks(payload)


def selected_recipe_keys_and_urls(recipe_urls):
    selected_keys = set()
    selected_urls = []

    for recipe_url in recipe_urls or []:
        url = clean_text(recipe_url)
        key = recipe_key(url)

        if not key or key in selected_keys:
            continue

        selected_keys.add(key)
        selected_urls.append(url)

    if not selected_keys:
        raise ValueError("Select at least one cookbook recipe.")

    return selected_keys, selected_urls


def remove_recipes_from_cookbook(cookbook_id, recipe_urls):
    selected_keys, _selected_urls = selected_recipe_keys_and_urls(recipe_urls)

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        removed_recipes = []
        kept_recipes = []

        for recipe in target.get("recipes", []):
            if recipe_key(recipe.get("url")) in selected_keys:
                removed_recipes.append(recipe)
                continue

            kept_recipes.append(recipe)

        if not removed_recipes:
            raise ValueError("Selected cookbook recipes were not found.")

        target["recipes"] = kept_recipes

        if not is_unclassified_cookbook(target):
            for recipe in removed_recipes:
                add_recipe_to_unclassified(payload, recipe)

        save_cookbooks(payload)
        return [
            clean_text(recipe.get("url"))
            for recipe in removed_recipes
            if clean_text(recipe.get("url"))
        ]


def purge_selected_cookbook_recipe_urls(cookbook_id, recipe_urls):
    selected_keys, _selected_urls = selected_recipe_keys_and_urls(recipe_urls)

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        purge_keys = set()
        purge_urls = []

        for recipe in target.get("recipes", []):
            raw_url = recipe.get("url") if isinstance(recipe, dict) else recipe
            url = clean_text(raw_url)
            key = recipe_key(url)

            if key and key in selected_keys and key not in purge_keys:
                purge_keys.add(key)
                purge_urls.append(url)

        if not purge_keys:
            raise ValueError("Selected cookbook recipes were not found.")

        for cookbook in payload.get("cookbooks", []):
            cookbook["recipes"] = [
                recipe
                for recipe in cookbook.get("recipes", [])
                if recipe_key(recipe.get("url") if isinstance(recipe, dict) else recipe) not in purge_keys
            ]

        save_cookbooks(payload)
        return purge_urls


def update_cookbook_recipe_categories(
    cookbook_id,
    recipe_url,
    categories,
    confirm_overwrite=False,
    category_sources=None,
):
    target_key = recipe_key(recipe_url)

    if not target_key:
        raise ValueError("Recipe is required.")

    cleaned_categories = clean_category_payload(categories)
    cleaned_sources = clean_category_source_payload(category_sources, cleaned_categories)

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        recipe = None
        for candidate in target.get("recipes", []):
            if recipe_key(candidate.get("url")) == target_key:
                recipe = candidate
                break

        if recipe is None:
            raise ValueError("Recipe was not found in this cookbook.")

        existing_metadata = stored_category_metadata(recipe)
        has_manual_metadata = bool(recipe.get("category_metadata_user_set")) or category_metadata_has_values(existing_metadata)

        if (
            has_manual_metadata
            and category_metadata_changed(existing_metadata, cleaned_categories)
            and not confirm_overwrite
        ):
            raise CookbookCategoryOverwriteConflict(recipe.get("name") or recipe_url)

        for field in COOKBOOK_CATEGORY_FIELDS:
            recipe[field] = cleaned_categories.get(field, "")

        recipe["custom_categories"] = cleaned_categories.get("custom_categories", [])
        recipe["category_metadata_sources"] = cleaned_sources
        recipe["category_metadata_user_set"] = category_sources_have_user_selected(cleaned_sources)
        recipe["category_metadata_source"] = category_metadata_source_label(cleaned_categories, cleaned_sources)
        recipe["category_metadata_updated_at"] = now_iso() if category_metadata_has_values(cleaned_categories) else ""
        return save_cookbooks(payload)


def purge_recipe_from_all_cookbooks(recipe_url):
    target_key = recipe_key(recipe_url)

    if not target_key:
        raise ValueError("Recipe is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        removed_count = 0

        for cookbook in payload.get("cookbooks", []):
            kept_recipes = []

            for recipe in cookbook.get("recipes", []):
                if recipe_key(recipe.get("url")) == target_key:
                    removed_count += 1
                    continue

                kept_recipes.append(recipe)

            cookbook["recipes"] = kept_recipes

        save_cookbooks(payload)
        return removed_count


def cookbook_recipes_for_urls(recipe_urls):
    selected_keys = []
    seen_selected = set()

    for recipe_url in recipe_urls:
        key = recipe_key(recipe_url)
        if key and key not in seen_selected:
            selected_keys.append(key)
            seen_selected.add(key)

    if not selected_keys:
        raise ValueError("Select at least one cookbook recipe.")

    payload = load_cookbooks()
    selected_key_set = set(selected_keys)
    found_recipes = {}

    for cookbook in payload["cookbooks"]:
        for recipe in cookbook.get("recipes", []):
            record = clean_recipe_record(recipe)
            if not record:
                continue

            key = recipe_key(record["url"])
            if key in selected_key_set and key not in found_recipes:
                found_recipes[key] = record

    recipes = [
        found_recipes[key]
        for key in selected_keys
        if key in found_recipes
    ]

    if not recipes:
        raise ValueError("Selected cookbook recipes were not found.")

    return recipes


def hydrate_recipe(stored_recipe, current_recipes):
    stored_recipe = clean_recipe_record(stored_recipe)
    if not stored_recipe:
        return None

    current_recipe = current_recipes.get(recipe_key(stored_recipe["url"]))
    recipe = current_recipe or stored_recipe
    hydrated_recipe = {
        **stored_recipe,
        **recipe,
    }

    for field in COOKBOOK_CATEGORY_FIELDS:
        if not clean_text(hydrated_recipe.get(field)) and clean_text(stored_recipe.get(field)):
            hydrated_recipe[field] = stored_recipe[field]

    if (
        not clean_custom_categories(hydrated_recipe.get("custom_categories"))
        and clean_custom_categories(stored_recipe.get("custom_categories"))
    ):
        hydrated_recipe["custom_categories"] = stored_recipe["custom_categories"]

    if (
        not clean_custom_categories(hydrated_recipe.get("categories"))
        and clean_custom_categories(stored_recipe.get("categories"))
    ):
        hydrated_recipe["categories"] = stored_recipe["categories"]

    if (
        stored_recipe.get("category_metadata_sources")
        and not recipe.get("category_metadata_sources")
    ):
        hydrated_recipe["category_metadata_sources"] = stored_recipe["category_metadata_sources"]

    if (
        stored_recipe.get("category_metadata_user_set")
        and not recipe.get("category_metadata_user_set")
    ):
        hydrated_recipe["category_metadata_user_set"] = stored_recipe["category_metadata_user_set"]

    if not hydrated_recipe.get("cover_image") and stored_recipe.get("cover_image"):
        hydrated_recipe["cover_image"] = stored_recipe["cover_image"]

    return hydrated_recipe


def cookbook_view(recipe_rows):
    payload = load_cookbooks()
    current_recipes = recipe_snapshot_lookup(recipe_rows)
    recipe_assignments = {}
    view_cookbooks = []

    for cookbook in payload["cookbooks"]:
        recipes = []
        for stored_recipe in cookbook.get("recipes", []):
            recipe = hydrate_recipe(stored_recipe, current_recipes)
            if not recipe:
                continue

            recipe["cookbook_id"] = cookbook.get("id", "")
            recipe["cookbook_name"] = cookbook.get("name", "")
            recipes.append(recipe)
            recipe_assignments[recipe_key(recipe["url"])] = cookbook.get("name", "")

        view_cookbooks.append({
            **cookbook,
            "is_unclassified": is_unclassified_cookbook(cookbook),
            "recipes": recipes,
        })

    recipes = []
    for recipe in recipe_rows or []:
        record = clean_recipe_record(recipe)
        if not record:
            continue

        key = recipe_key(record["url"])
        cookbook_name = recipe_assignments.get(key, "")
        recipes.append({
            **record,
            "number": recipe.get("number"),
            "cookbook_name": cookbook_name,
            "assigned": bool(cookbook_name),
        })

    view = {
        "cookbooks": view_cookbooks,
        "recipes": recipes,
    }

    return prepare_cookbook_menu_view(view)
