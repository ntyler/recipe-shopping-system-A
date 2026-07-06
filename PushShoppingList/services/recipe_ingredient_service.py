import json
from pathlib import Path

from PushShoppingList.services.recipe_extract_service import (
    OUTPUT_FOLDER,
    extract_ingredients_from_result,
    normalize_ingredient_for_shopping_list,
)
from PushShoppingList.services.purchase_mapping_service import apply_purchase_mapping_to_ingredient
from PushShoppingList.services.recipe_master_data_service import remove_recipe_master_records_for_recipe
from PushShoppingList.services.recipe_master_data_service import sync_recipe_master_records
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import save_items
from PushShoppingList.services.storage_service import scoped_extractor_data_path
from PushShoppingList.services.user_account_service import current_public_user


BASE_DIR = Path(__file__).resolve().parent
RECIPE_INGREDIENTS_FILE = scoped_extractor_data_path("recipe_ingredients.json")

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


def recipe_ingredients_record(url, ingredients, recipe_metadata=None, existing=None, user=None):
    url = str(url or "").strip()
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    cover_image = recipe_metadata.get("cover_image") or existing.get("cover_image")
    record = {
        "url": url,
        "quantity": existing.get("quantity", 1),
        "name": existing.get("name") or recipe_metadata.get("display_name") or recipe_metadata.get("recipe_title"),
        "servings": recipe_metadata.get("servings") or existing.get("servings"),
        "level": recipe_metadata.get("level") or existing.get("level"),
        "total_time": recipe_metadata.get("total_time") or existing.get("total_time"),
        "prep_time": recipe_metadata.get("prep_time") or existing.get("prep_time"),
        "inactive_time": recipe_metadata.get("inactive_time") or existing.get("inactive_time"),
        "cook_time": recipe_metadata.get("cook_time") or existing.get("cook_time"),
        "base_servings": recipe_metadata.get("servings") or existing.get("base_servings"),
        "scaled_servings": existing.get("scaled_servings"),
        "scaled_ingredients": existing.get("scaled_ingredients", {}),
        "ingredients": unique_ingredients(ingredients),
    }

    if cover_image:
        record["cover_image"] = cover_image

    # This metadata makes imported ingredient records auditable inside user-scoped storage.
    if user:
        record["owner_user_id"] = user.get("user_id", "")
        record["owner_username"] = user.get("username", "")

    return record


def save_ingredients_for_recipe(url, ingredients, recipe_metadata=None):
    url = str(url or "").strip()

    if not url:
        return

    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    data[key] = recipe_ingredients_record(
        url,
        ingredients,
        recipe_metadata,
        existing=data.get(key, {}),
        user=current_public_user(),
    )
    save_recipe_ingredients(data)
    sync_recipe_master_records(url, ingredients=ingredients, recipe_data=recipe_metadata)


def save_ingredients_for_recipes(records):
    records = records if isinstance(records, list) else []
    cleaned_records = []
    for record in records:
        record = record if isinstance(record, dict) else {}
        url = str(record.get("url") or record.get("recipe_url") or "").strip()
        if not url:
            continue
        ingredients = record.get("ingredients") if isinstance(record.get("ingredients"), list) else []
        recipe_metadata = record.get("recipe_metadata") if isinstance(record.get("recipe_metadata"), dict) else {}
        cleaned_records.append((url, ingredients, recipe_metadata))

    if not cleaned_records:
        return

    data = load_recipe_ingredients()
    user = current_public_user()
    for url, ingredients, recipe_metadata in cleaned_records:
        key = normalize_recipe_url_key(url)
        data[key] = recipe_ingredients_record(
            url,
            ingredients,
            recipe_metadata,
            existing=data.get(key, {}),
            user=user,
        )
    save_recipe_ingredients(data)
    for url, ingredients, recipe_metadata in cleaned_records:
        sync_recipe_master_records(url, ingredients=ingredients, recipe_data=recipe_metadata)


def remove_recipe_and_unused_ingredients(url):
    target_key = normalize_recipe_url_key(url)
    data = load_recipe_ingredients()

    removed_ingredients = recipe_ingredients_for_key(target_key, data)

    if target_key in data:
        del data[target_key]
        save_recipe_ingredients(data)
        remove_recipe_master_records_for_recipe(url)

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
        ingredient = normalize_ingredient_for_shopping_list(ingredient)
        key = ingredient_key(ingredient)

        if ingredient and key not in seen:
            unique_items.append(ingredient)
            seen.add(key)

    return unique_items


def update_saved_recipe_purchase_mapping(ingredient_name, purchasable_item):
    target_key = ingredient_key(ingredient_name)
    changed_paths = []

    if not target_key:
        return changed_paths

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            json_data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        changed = False
        for item in json_data.get("ingredients", []) or []:
            if not isinstance(item, dict):
                continue

            current_name = item.get("ingredient") or item.get("original_text") or ""
            if ingredient_key(current_name) != target_key:
                continue

            before = (
                item.get("purchasable_item"),
                item.get("purchase_group"),
                item.get("ingredient"),
                item.get("original_text"),
            )
            apply_purchase_mapping_to_ingredient(item, purchasable_item=purchasable_item)
            after = (
                item.get("purchasable_item"),
                item.get("purchase_group"),
                item.get("ingredient"),
                item.get("original_text"),
            )
            changed = changed or before != after

        if not changed:
            continue

        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        changed_paths.append(str(json_path))

    return changed_paths


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
