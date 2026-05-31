import threading
from pathlib import Path

from PushShoppingList.services.recipe_extract_service import normalize_ingredient_for_shopping_list
from PushShoppingList.services.storage_service import scoped_package_path

BASE_DIR = Path(__file__).resolve().parent.parent
SHOPPING_LIST_FILE = scoped_package_path("shopping_list.txt")
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


def add_items(new_items):
    with SHOPPING_LIST_LOCK:
        items = load_items()

        for item in new_items:
            item = normalize_ingredient_for_shopping_list(item)

            if item and item not in items:
                items.append(item)

        save_items(items)
