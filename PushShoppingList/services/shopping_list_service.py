import json
import threading
from pathlib import Path

from PushShoppingList.services.ingredient_option_service import resolve_ingredient_requirements
from PushShoppingList.services.ingredient_option_service import shopping_item_name
from PushShoppingList.services.recipe_extract_service import normalize_ingredient_for_shopping_list
from PushShoppingList.services.storage_service import scoped_package_path

BASE_DIR = Path(__file__).resolve().parent.parent
SHOPPING_LIST_FILE = scoped_package_path("shopping_list.txt")
SHOPPING_LIST_SELECTIONS_FILE = scoped_package_path("shopping_list_recipe_selections.json")
SHOPPING_LIST_LOCK = threading.RLock()


def load_items():
    with SHOPPING_LIST_LOCK:
        if not SHOPPING_LIST_FILE.exists():
            return []

        return [
            line.strip()
            for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def save_items(items):
    with SHOPPING_LIST_LOCK:
        SHOPPING_LIST_FILE.write_text(
            "\n".join(items) + ("\n" if items else ""),
            encoding="utf-8",
        )


def load_recipe_selections():
    with SHOPPING_LIST_LOCK:
        if not SHOPPING_LIST_SELECTIONS_FILE.exists():
            return {"recipes": {}}
        try:
            payload = json.loads(
                SHOPPING_LIST_SELECTIONS_FILE.read_text(encoding="utf-8-sig")
            )
        except Exception:
            return {"recipes": {}}
        recipes = payload.get("recipes") if isinstance(payload, dict) else {}
        return {"recipes": recipes if isinstance(recipes, dict) else {}}


def save_recipe_selections(payload):
    recipes = payload.get("recipes") if isinstance(payload, dict) else {}
    normalized = {"recipes": recipes if isinstance(recipes, dict) else {}}
    with SHOPPING_LIST_LOCK:
        SHOPPING_LIST_SELECTIONS_FILE.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return normalized


def save_recipe_option_selections(recipe_url, selections):
    recipe_url = str(recipe_url or "").strip()
    selections = selections if isinstance(selections, dict) else {}
    if not recipe_url:
        return {}
    with SHOPPING_LIST_LOCK:
        payload = load_recipe_selections()
        payload["recipes"][recipe_url] = {
            str(requirement_id): str(option_id)
            for requirement_id, option_id in selections.items()
            if str(requirement_id).strip() and str(option_id).strip()
        }
        save_recipe_selections(payload)
        return dict(payload["recipes"][recipe_url])


def _resolved_item_names(new_items):
    names = []
    unresolved = []
    for item in new_items or []:
        if isinstance(item, dict):
            resolution = resolve_ingredient_requirements([item])
            unresolved.extend(resolution["unresolved_requirements"])
            names.extend(
                shopping_item_name(selected_item)
                for selected_item in resolution["items"]
                if shopping_item_name(selected_item)
            )
        else:
            names.append(item)
    return names, unresolved


def add_items(new_items):
    candidate_names, unresolved = _resolved_item_names(new_items)
    added = []
    with SHOPPING_LIST_LOCK:
        items = load_items()
        existing_items = set(items)

        for item in candidate_names:
            item = normalize_ingredient_for_shopping_list(item)

            if item and item not in existing_items:
                items.append(item)
                existing_items.add(item)
                added.append(item)

        save_items(items)
    return {
        "added": added,
        "selection_needed": bool(unresolved),
        "unresolved_requirements": unresolved,
    }


def finalize_recipe_items(recipe_url, recipe_data, selections=None):
    resolution = resolve_ingredient_requirements(
        recipe_data,
        selections,
        require_all=True,
    )
    selected_names = [
        shopping_item_name(item)
        for item in resolution["items"]
        if shopping_item_name(item)
    ]
    result = add_items(selected_names)
    saved_selections = save_recipe_option_selections(
        recipe_url,
        resolution["selected_options"],
    )
    return {
        **result,
        "recipe_url": str(recipe_url or "").strip(),
        "selected_options": saved_selections,
        "selection_needed": False,
        "unresolved_requirements": [],
    }
