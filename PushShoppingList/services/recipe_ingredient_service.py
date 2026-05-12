import json
from pathlib import Path

from PushShoppingList.services.recipe_extract_service import (
    OUTPUT_FOLDER,
    extract_ingredients_from_result,
)
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import save_items


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
RECIPE_INGREDIENTS_FILE = (
    PROJECT_DIR /
    "recipe-extractor" /
    "data" /
    "recipe_ingredients.json"
)

RECIPE_INGREDIENTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_recipe_ingredients():
    if not RECIPE_INGREDIENTS_FILE.exists():
        return {}

    try:
        return json.loads(RECIPE_INGREDIENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_recipe_ingredients(data):
    RECIPE_INGREDIENTS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_ingredients_for_recipe(url, ingredients):
    url = str(url or "").strip()

    if not url:
        return

    data = load_recipe_ingredients()
    data[normalize_recipe_url_key(url)] = {
        "url": url,
        "ingredients": unique_ingredients(ingredients),
    }
    save_recipe_ingredients(data)


def remove_recipe_and_unused_ingredients(url):
    target_key = normalize_recipe_url_key(url)
    data = load_recipe_ingredients()

    removed_ingredients = recipe_ingredients_for_key(target_key, data)

    if target_key in data:
        del data[target_key]
        save_recipe_ingredients(data)

    if removed_ingredients:
        remove_unused_ingredients_from_shopping_list(removed_ingredients, data)


def recipe_ingredients_for_key(recipe_key, data):
    recipe_data = data.get(recipe_key)

    if recipe_data:
        return recipe_data.get("ingredients", [])

    return load_ingredients_from_saved_output(recipe_key)


def load_ingredients_from_saved_output(recipe_key):
    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            json_data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        source_url = json_data.get("source_url", "")

        if normalize_recipe_url_key(source_url) == recipe_key:
            return extract_ingredients_from_result(json_data)

    return []


def remove_unused_ingredients_from_shopping_list(removed_ingredients, remaining_recipe_data):
    removed_keys = {
        ingredient_key(ingredient)
        for ingredient in removed_ingredients
    }
    remaining_keys = {
        ingredient_key(ingredient)
        for recipe_data in remaining_recipe_data.values()
        for ingredient in recipe_data.get("ingredients", [])
    }
    keys_to_remove = removed_keys - remaining_keys

    if not keys_to_remove:
        return

    filtered_items = []

    for item in load_items():
        if is_section_header(item):
            filtered_items.append(item)
            continue

        if ingredient_key(item) not in keys_to_remove:
            filtered_items.append(item)

    save_items(remove_empty_sections(filtered_items))


def unique_ingredients(ingredients):
    unique_items = []
    seen = set()

    for ingredient in ingredients:
        ingredient = str(ingredient or "").strip()
        key = ingredient_key(ingredient)

        if ingredient and key not in seen:
            unique_items.append(ingredient)
            seen.add(key)

    return unique_items


def ingredient_key(text):
    return " ".join(str(text or "").strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def remove_empty_sections(items):
    cleaned_items = []
    pending_header = None

    for item in items:
        if is_section_header(item):
            pending_header = item
            continue

        if pending_header:
            cleaned_items.append(pending_header)
            pending_header = None

        cleaned_items.append(item)

    return cleaned_items
