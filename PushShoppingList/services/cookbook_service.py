import json
import re
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
COOKBOOKS_FILE = BASE_DIR / "cookbooks.json"
COOKBOOKS_LOCK = threading.RLock()


def normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def cookbook_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(name)).strip("-")
    return slug or "cookbook"


def clean_ingredient(value):
    return " ".join(str(value or "").strip().split())


def normalize_cookbooks_payload(payload):
    cookbooks = []
    seen_ids = set()
    raw_cookbooks = payload.get("cookbooks", []) if isinstance(payload, dict) else []

    for cookbook in raw_cookbooks:
        name = str(cookbook.get("name") or "").strip()

        if not name:
            continue

        cookbook_id = str(cookbook.get("id") or cookbook_slug(name)).strip()
        if not cookbook_id or cookbook_id in seen_ids:
            cookbook_id = unique_cookbook_id({"cookbooks": cookbooks}, name)

        seen_ids.add(cookbook_id)
        ingredients = []
        seen_ingredients = set()

        for ingredient in cookbook.get("ingredients", []):
            ingredient = clean_ingredient(ingredient)
            ingredient_key = normalize_text(ingredient)

            if ingredient and ingredient_key not in seen_ingredients:
                ingredients.append(ingredient)
                seen_ingredients.add(ingredient_key)

        cookbooks.append({
            "id": cookbook_id,
            "name": name,
            "ingredients": ingredients,
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
    name = str(name or "").strip()

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
            "ingredients": [],
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


def move_ingredients_to_cookbook(cookbook_id, ingredients):
    clean_ingredients = []
    selected_keys = set()

    for ingredient in ingredients:
        ingredient = clean_ingredient(ingredient)
        ingredient_key = normalize_text(ingredient)

        if ingredient and ingredient_key not in selected_keys:
            clean_ingredients.append(ingredient)
            selected_keys.add(ingredient_key)

    if not clean_ingredients:
        raise ValueError("Select at least one ingredient.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Choose a cookbook.")

        for cookbook in payload["cookbooks"]:
            cookbook["ingredients"] = [
                ingredient
                for ingredient in cookbook.get("ingredients", [])
                if normalize_text(ingredient) not in selected_keys
            ]

        target["ingredients"].extend(clean_ingredients)
        return save_cookbooks(payload)


def remove_ingredient_from_cookbook(cookbook_id, ingredient):
    ingredient_key = normalize_text(ingredient)

    if not ingredient_key:
        raise ValueError("Ingredient is required.")

    with COOKBOOKS_LOCK:
        payload = load_cookbooks()
        target = find_cookbook(payload, cookbook_id)

        if target is None:
            raise ValueError("Cookbook was not found.")

        target["ingredients"] = [
            current
            for current in target.get("ingredients", [])
            if normalize_text(current) != ingredient_key
        ]

        return save_cookbooks(payload)


def cookbook_view(shopping_items):
    payload = load_cookbooks()
    ingredient_assignments = {}

    for cookbook in payload["cookbooks"]:
        for ingredient in cookbook.get("ingredients", []):
            ingredient_assignments[normalize_text(ingredient)] = cookbook.get("name", "")

    ingredients = []
    for item in shopping_items:
        item_key = normalize_text(item)
        ingredients.append({
            "name": item,
            "cookbook_name": ingredient_assignments.get(item_key, ""),
            "assigned": bool(ingredient_assignments.get(item_key)),
        })

    return {
        "cookbooks": payload["cookbooks"],
        "ingredients": ingredients,
    }
