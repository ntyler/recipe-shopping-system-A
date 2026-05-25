import json
import re
import threading
from pathlib import Path

from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key

BASE_DIR = Path(__file__).resolve().parent.parent
COOKBOOKS_FILE = BASE_DIR / "cookbooks.json"
COOKBOOKS_LOCK = threading.RLock()


class CookbookRecipeConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        count = len(conflicts)
        recipe_label = "recipe" if count == 1 else "recipes"
        super().__init__(f"{count} selected {recipe_label} already exists in this cookbook.")


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
        "archive_pdf_available": bool(value.get("archive_pdf_available")),
        "base_servings": clean_text(value.get("base_servings")),
        "scaled_servings": clean_text(value.get("scaled_servings")),
        "equipment_items": clean_text_list(value.get("equipment_items")),
        "instruction_items": clean_text_list(value.get("instruction_items")),
        "sections": clean_recipe_sections(value.get("sections")),
    }
    cover_image = clean_cover_image(value.get("cover_image"))

    if cover_image:
        record["cover_image"] = cover_image

    return record


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


def save_cookbooks(payload):
    with COOKBOOKS_LOCK:
        normalized = normalize_cookbooks_payload(payload)
        COOKBOOKS_FILE.write_text(
            json.dumps(normalized, indent=2) + "\n",
            encoding="utf-8",
        )
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


def create_cookbook(name):
    name = clean_text(name)

    if not name:
        raise ValueError("Cookbook name is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        name_key = normalize_text(name)

        if any(normalize_text(cookbook.get("name")) == name_key for cookbook in payload["cookbooks"]):
            raise ValueError("A cookbook with that name already exists.")

        payload["cookbooks"].append({
            "id": unique_cookbook_id(payload, name),
            "name": name,
            "recipes": [],
        })

        return save_cookbooks(payload)


def delete_cookbook(cookbook_id):
    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        next_cookbooks = [
            cookbook
            for cookbook in payload["cookbooks"]
            if cookbook.get("id") != cookbook_id
        ]

        if len(next_cookbooks) == len(payload["cookbooks"]):
            raise ValueError("Cookbook was not found.")

        payload["cookbooks"] = next_cookbooks
        return save_cookbooks(payload)


def rename_cookbook(cookbook_id, name):
    name = clean_text(name)

    if not name:
        raise ValueError("Cookbook name is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        name_key = normalize_text(name)
        for cookbook in payload["cookbooks"]:
            if cookbook.get("id") != cookbook_id and normalize_text(cookbook.get("name")) == name_key:
                raise ValueError("A cookbook with that name already exists.")

        target["name"] = name
        return save_cookbooks(payload)


def move_recipes_to_cookbook(cookbook_id, recipe_urls, recipe_rows=None, overwrite_existing=False):
    available_recipes = recipe_snapshot_lookup(recipe_rows)
    selected_recipes = []
    selected_keys = set()

    for recipe_url in recipe_urls:
        key = recipe_key(recipe_url)
        if not key or key in selected_keys:
            continue

        record = available_recipes.get(key) or clean_recipe_record(recipe_url)
        if record:
            selected_recipes.append(record)
            selected_keys.add(key)

    if not selected_recipes:
        raise ValueError("Select at least one recipe.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Choose a cookbook.")

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

        target["recipes"].extend(selected_recipes)
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

        target["recipes"] = [
            recipe
            for recipe in target.get("recipes", [])
            if recipe_key(recipe.get("url")) != target_key
        ]

        return save_cookbooks(payload)


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

    return {
        "cookbooks": view_cookbooks,
        "recipes": recipes,
    }
