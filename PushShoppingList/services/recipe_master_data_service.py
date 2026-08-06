import json
import os
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from PushShoppingList.services import storage_service
from PushShoppingList.services.ingredient_unit_service import canonical_unit_aliases
from PushShoppingList.services.ingredient_unit_service import canonical_unit_options
from PushShoppingList.services.ingredient_unit_service import canonical_unit
from PushShoppingList.services.ingredient_unit_service import misplaced_unit_ingredient_details
from PushShoppingList.services.ingredient_unit_service import normalize_ingredient_unit_fields
from PushShoppingList.services.ingredient_unit_service import UNIT_REGISTRY_CATEGORIES
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_name


LOCAL_USER_ID = "local"
RECIPE_MASTER_DB_PATH = Path(
    os.getenv(
        "SHOPPING_APP_RECIPE_MASTER_DB",
        storage_service.PACKAGE_DIR / "user_data" / "recipe_master.sqlite3",
    )
)
RECIPE_MASTER_DB_LOCK = threading.RLock()
BACKFILL_MIGRATION_NAME = "recipe_master_user_scoped_store_section_backfill_v2"
UNIT_NORMALIZATION_MIGRATION_NAME = "ingredient_unit_normalization_v1"
INGREDIENT_STORE_SECTION_ORDER = {
    "PRODUCE": 1,
    "MEAT & SEAFOOD": 2,
    "DAIRY & EGGS": 3,
    "FROZEN": 4,
    "DRY GOODS": 5,
    "PASTA, RICE & GRAINS": 6,
    "BAKING": 7,
    "CANNED": 8,
    "SAUCES & CONDIMENTS": 9,
    "SNACKS": 10,
    "BEVERAGES": 11,
    "SPICES & SEASONINGS": 12,
    "OILS & VINEGARS": 13,
    "BAKERY": 14,
    "DELI": 15,
    "HOUSEHOLD": 16,
    "PERSONAL CARE": 17,
    "PET SUPPLIES": 18,
    "MISC": 19,
}
INGREDIENT_STORE_SECTION_DISPLAY_NAMES = {
    "PRODUCE": "Produce",
    "MEAT & SEAFOOD": "Meat & Seafood",
    "DAIRY & EGGS": "Dairy & Eggs",
    "FROZEN": "Frozen",
    "DRY GOODS": "Dry Goods",
    "PASTA, RICE & GRAINS": "Pasta, Rice & Grains",
    "BAKING": "Baking",
    "CANNED": "Canned Goods",
    "SAUCES & CONDIMENTS": "Sauces & Condiments",
    "SNACKS": "Snacks",
    "BEVERAGES": "Beverages",
    "SPICES & SEASONINGS": "Spices",
    "OILS & VINEGARS": "Oils & Vinegars",
    "BAKERY": "Bakery",
    "DELI": "Deli",
    "HOUSEHOLD": "Household",
    "PERSONAL CARE": "Personal Care",
    "PET SUPPLIES": "Pet Supplies",
    "MISC": "Misc",
}
INGREDIENT_STORE_SECTION_ICONS = {
    "PRODUCE": "leaf",
    "MEAT & SEAFOOD": "fish",
    "DAIRY & EGGS": "dairy",
    "FROZEN": "snowflake",
    "DRY GOODS": "package",
    "PASTA, RICE & GRAINS": "wheat",
    "BAKING": "whisk",
    "CANNED": "can",
    "SAUCES & CONDIMENTS": "sauce",
    "SNACKS": "cookie",
    "BEVERAGES": "cup",
    "SPICES & SEASONINGS": "jar",
    "OILS & VINEGARS": "oil",
    "BAKERY": "bread",
    "DELI": "sandwich",
    "HOUSEHOLD": "broom",
    "PERSONAL CARE": "personal-care",
    "PET SUPPLIES": "paw",
    "MISC": "basket",
}
INGREDIENT_STORE_SECTION_ICON_OPTIONS = (
    "leaf",
    "fish",
    "dairy",
    "snowflake",
    "package",
    "wheat",
    "whisk",
    "can",
    "sauce",
    "cookie",
    "cup",
    "jar",
    "oil",
    "bread",
    "sandwich",
    "home",
    "broom",
    "heart",
    "personal-care",
    "paw",
    "basket",
)
INGREDIENT_STORE_SECTION_ALIASES = {
    "DAIRY": "DAIRY & EGGS",
    "MEAT AND SEAFOOD": "MEAT & SEAFOOD",
    "DAIRY AND EGGS": "DAIRY & EGGS",
    "CANNED GOODS": "CANNED",
    "PASTA RICE AND GRAINS": "PASTA, RICE & GRAINS",
    "PASTA, RICE AND GRAINS": "PASTA, RICE & GRAINS",
    "SAUCES AND CONDIMENTS": "SAUCES & CONDIMENTS",
    "SPICES": "SPICES & SEASONINGS",
    "SPICES AND SEASONINGS": "SPICES & SEASONINGS",
    "OILS AND VINEGARS": "OILS & VINEGARS",
}
INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION = "2.0"
INGREDIENT_STORE_SECTION_SOURCES = {
    "recipe_override",
    "user_master_data",
    "global_master_data",
    "deterministic_rule",
    "ai",
    "manual",
    "legacy",
    "fallback",
}
INGREDIENT_FORMS = (
    "fresh",
    "ground",
    "powdered",
    "dried",
    "frozen",
    "canned",
    "bottled",
    "paste",
    "crystallized",
)
GLOBAL_INGREDIENT_STORE_SECTION_MAPPINGS = {
    "ground ginger": "SPICES & SEASONINGS",
    "ginger powder": "SPICES & SEASONINGS",
    "powdered ginger": "SPICES & SEASONINGS",
    "fresh ginger": "PRODUCE",
    "ginger root": "PRODUCE",
    "garlic powder": "SPICES & SEASONINGS",
    "onion powder": "SPICES & SEASONINGS",
    "fresh garlic": "PRODUCE",
    "fresh onion": "PRODUCE",
    "ground cinnamon": "SPICES & SEASONINGS",
    "paprika": "SPICES & SEASONINGS",
    "cumin": "SPICES & SEASONINGS",
    "turmeric": "SPICES & SEASONINGS",
    "frozen mixed vegetables": "FROZEN",
    "canned vegetables": "CANNED",
    "long grain rice": "PASTA, RICE & GRAINS",
    "vegetable oil": "OILS & VINEGARS",
    "soy sauce": "SAUCES & CONDIMENTS",
    "peruvian chorizo": "MEAT & SEAFOOD",
}
INGREDIENT_CANONICAL_ALIASES = {
    "ground ginger": ("ginger", "ground"),
    "ginger powder": ("ginger", "powdered"),
    "powdered ginger": ("ginger", "powdered"),
    "dried ginger": ("ginger", "dried"),
    "fresh ginger": ("ginger", "fresh"),
    "ginger root": ("ginger", "fresh"),
    "garlic powder": ("garlic", "powdered"),
    "onion powder": ("onion", "powdered"),
    "fresh garlic": ("garlic", "fresh"),
    "fresh onion": ("onion", "fresh"),
    "ground cinnamon": ("cinnamon", "ground"),
    "frozen mixed vegetables": ("mixed vegetables", "frozen"),
    "canned vegetables": ("vegetables", "canned"),
}
PERUVIAN_PEPPER_PATTERN = r"\b(?:inca pepper|aji amarillo|aji panca)\b"
PERUVIAN_PEPPER_SAUCE_PATTERN = (
    rf"{PERUVIAN_PEPPER_PATTERN}.*\b(?:sauce|salsa|paste)\b"
    rf"|\b(?:sauce|salsa|paste)\b.*{PERUVIAN_PEPPER_PATTERN}"
)
PERUVIAN_PEPPER_PLAIN_PATTERN = (
    rf"{PERUVIAN_PEPPER_PATTERN}(?!\s+(?:sauce|salsa|paste)\b)"
)
INGREDIENT_STORE_SECTION_KEYWORD_RULES = (
    (
        (
            r"\b(?:broth|stock|bouillon|consomme)\b",
        ),
        "CANNED",
    ),
    (
        (
            r"\b(?:sauce|salsa|ketchup|mustard|mayonnaise|mayo|pesto|chutney|paste)\b",
        ),
        "SAUCES & CONDIMENTS",
    ),
    (
        (
            PERUVIAN_PEPPER_PATTERN,
        ),
        "PRODUCE",
    ),
    (
        (
            r"\b(?:crema|sour cream|heavy cream|half and half|cream cheese)\b",
            r"\b(?:milk|butter|yogurt|yoghurt|cheese|ricotta|parmesan|mozzarella|cheddar)\b",
            r"\b(?:egg|eggs|yolk|yolks)\b",
        ),
        "DAIRY & EGGS",
    ),
    (
        (
            r"\b(?:salt|black pepper|white pepper|cayenne pepper|red pepper flakes|peppercorn|peppercorns)\b",
            r"\b(?:cinnamon|nutmeg|paprika|cumin|seasoning|spice|spices)\b",
            r"\b(?:garlic powder|onion powder|chili powder|chile powder)\b",
        ),
        "SPICES & SEASONINGS",
    ),
    (
        (
            r"\b(?:potato|potatoes|sweet potato|sweet potatoes|yuca|cassava)\b",
            r"\b(?:onion|garlic|tomato|tomatoes|lemon|lime|basil|parsley|cilantro)\b",
            r"\b(?:spinach|lettuce|carrot|carrots|celery|corn|mushroom|mushrooms|avocado)\b",
            r"\b(?:bell pepper|bell peppers|jalapeno|jalapenos|scallion|scallions)\b",
        ),
        "PRODUCE",
    ),
    (
        (
            r"\b(?:beef|chicken|pork|turkey|fish|shrimp|salmon|sausage|chorizo|bacon|ham)\b",
        ),
        "MEAT & SEAFOOD",
    ),
    (
        (
            r"\b(?:pasta|spaghetti|linguine|rice|oats|quinoa|breadcrumbs|bread crumbs)\b",
        ),
        "PASTA, RICE & GRAINS",
    ),
    (
        (
            r"\b(?:flour|sugar|powdered sugar|confectioners sugar|confectioners' sugar)\b",
            r"\b(?:yeast|baking powder|baking soda|chocolate|cocoa powder|corn syrup|vanilla extract)\b",
        ),
        "BAKING",
    ),
    (
        (
            r"\b(?:oil|olive oil|vegetable oil|vinegar)\b",
        ),
        "OILS & VINEGARS",
    ),
    (
        (
            r"\b(?:bread|rolls|bun|buns|baguette|tortilla|tortillas)\b",
        ),
        "BAKERY",
    ),
)
INGREDIENT_STORE_SECTION_CONFLICT_OVERRIDES = (
    ("CANNED", "MEAT & SEAFOOD", r"\b(?:broth|stock|bouillon|consomme)\b"),
    ("SAUCES & CONDIMENTS", "MEAT & SEAFOOD", r"\b(?:sauce|salsa|paste|pesto)\b"),
    ("SAUCES & CONDIMENTS", "DAIRY & EGGS", r"\b(?:sauce|salsa|paste|pesto)\b"),
    (
        "SAUCES & CONDIMENTS",
        "PRODUCE",
        PERUVIAN_PEPPER_SAUCE_PATTERN,
    ),
    (
        "SAUCES & CONDIMENTS",
        "SPICES & SEASONINGS",
        PERUVIAN_PEPPER_SAUCE_PATTERN,
    ),
    (
        "PRODUCE",
        "SAUCES & CONDIMENTS",
        PERUVIAN_PEPPER_PLAIN_PATTERN,
    ),
    (
        "PRODUCE",
        "SPICES & SEASONINGS",
        PERUVIAN_PEPPER_PLAIN_PATTERN,
    ),
)
EQUIPMENT_SECTION_ORDER = {
    "COOKWARE": 1,
    "BAKEWARE": 2,
    "APPLIANCES": 3,
    "PREP TOOLS": 4,
    "MEASURING": 5,
    "MIXING BOWLS": 6,
    "SERVING & STORAGE": 7,
    "MISC": 8,
}
EQUIPMENT_SECTION_ALIASES = {
    "COOKWARE & PANS": "COOKWARE",
    "POTS & PANS": "COOKWARE",
    "POTS AND PANS": "COOKWARE",
    "BAKING": "BAKEWARE",
    "BAKING TOOLS": "BAKEWARE",
    "SMALL APPLIANCES": "APPLIANCES",
    "PREP": "PREP TOOLS",
    "TOOLS": "PREP TOOLS",
    "UTENSILS": "PREP TOOLS",
    "MEASURING TOOLS": "MEASURING",
    "BOWLS": "MIXING BOWLS",
    "STORAGE": "SERVING & STORAGE",
    "SERVING": "SERVING & STORAGE",
    "SERVING AND STORAGE": "SERVING & STORAGE",
}
EQUIPMENT_SECTION_KEYWORD_RULES = (
    (
        (
            r"\b(?:baking sheet|baking tray|sheet pan|cookie sheet|muffin tin|cake pan|loaf pan|pie dish|ramekin|casserole dish)\b",
        ),
        "BAKEWARE",
    ),
    (
        (
            r"\b(?:pot|pots|saucepan|saucepans|pan|pans|skillet|skillets|frying pan|dutch oven|stockpot|wok)\b",
        ),
        "COOKWARE",
    ),
    (
        (
            r"\b(?:blender|food processor|processor|mixer|stand mixer|hand mixer|slow cooker|instant pot|pressure cooker|air fryer|microwave|toaster|oven)\b",
        ),
        "APPLIANCES",
    ),
    (
        (
            r"\b(?:measuring cup|measuring cups|measuring spoon|measuring spoons|scale|thermometer|timer)\b",
        ),
        "MEASURING",
    ),
    (
        (
            r"\b(?:mixing bowl|mixing bowls|bowl|bowls)\b",
        ),
        "MIXING BOWLS",
    ),
    (
        (
            r"\b(?:container|containers|storage|jar|jars|platter|plate|plates|serving dish|serving bowl|tray)\b",
        ),
        "SERVING & STORAGE",
    ),
    (
        (
            r"\b(?:knife|knives|cutting board|board|spatula|whisk|tongs|peeler|grater|zester|strainer|sieve|colander|ladle|spoon|fork|masher|press|brush|rolling pin)\b",
        ),
        "PREP TOOLS",
    ),
)
MASTER_RECORD_TABLES = {
    "ingredients": {
        "usage_table": "recipe_ingredients",
        "usage_fk": "ingredient_id",
    },
    "equipment": {
        "usage_table": "recipe_equipment",
        "usage_fk": "equipment_id",
    },
}
MASTER_RECORD_SORTS = {
    "updated_at_desc": "m.updated_at DESC, m.id DESC",
    "usage_count_desc": "usage_count DESC, m.updated_at DESC, m.id DESC",
    "name_asc": "m.normalized_name ASC, m.name ASC, m.id ASC",
}
RECIPE_MASTER_BACKFILL_PROGRESS_LOCK = threading.RLock()
RECIPE_MASTER_BACKFILL_PROGRESS_RUNS = {}
MAX_RECIPE_MASTER_BACKFILL_RUNS = 8
MAX_RECIPE_MASTER_BACKFILL_ITEMS = 500


def utc_now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _new_backfill_progress(job_id, include_legacy=True, force=False):
    now = utc_now_iso()
    return {
        "job_id": str(job_id or "").strip(),
        "status": "starting",
        "summary": "Preparing recipe master backfill.",
        "include_legacy": bool(include_legacy),
        "force": bool(force),
        "started_at": now,
        "updated_at": now,
        "users_total": 0,
        "users_completed": 0,
        "recipes_total": 0,
        "recipes_completed": 0,
        "ingredient_rows": 0,
        "equipment_rows": 0,
        "current_user_id": "",
        "current_item_key": "",
        "items": [],
    }


def _prune_backfill_progress_runs():
    if len(RECIPE_MASTER_BACKFILL_PROGRESS_RUNS) <= MAX_RECIPE_MASTER_BACKFILL_RUNS:
        return

    removable = sorted(
        (
            progress
            for progress in RECIPE_MASTER_BACKFILL_PROGRESS_RUNS.values()
            if progress.get("status") not in {"starting", "running"}
        ),
        key=lambda progress: str(progress.get("updated_at") or ""),
    )
    for progress in removable:
        if len(RECIPE_MASTER_BACKFILL_PROGRESS_RUNS) <= MAX_RECIPE_MASTER_BACKFILL_RUNS:
            break
        RECIPE_MASTER_BACKFILL_PROGRESS_RUNS.pop(progress.get("job_id"), None)


def start_recipe_master_backfill_progress(job_id, include_legacy=True, force=False):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None

    with RECIPE_MASTER_BACKFILL_PROGRESS_LOCK:
        progress = _new_backfill_progress(job_id, include_legacy=include_legacy, force=force)
        RECIPE_MASTER_BACKFILL_PROGRESS_RUNS[job_id] = progress
        _prune_backfill_progress_runs()
        return dict(progress)


def recipe_master_backfill_progress(job_id=None):
    with RECIPE_MASTER_BACKFILL_PROGRESS_LOCK:
        if job_id:
            progress = RECIPE_MASTER_BACKFILL_PROGRESS_RUNS.get(str(job_id or "").strip())
        else:
            progress = None
            for candidate in RECIPE_MASTER_BACKFILL_PROGRESS_RUNS.values():
                if progress is None or str(candidate.get("updated_at") or "") > str(progress.get("updated_at") or ""):
                    progress = candidate
        if not progress:
            return None
        return json.loads(json.dumps(progress))


def _backfill_item_key(user_id, recipe_url, recipe_key):
    user_id = clean_text(user_id) or LOCAL_USER_ID
    recipe_key = clean_text(recipe_key) or recipe_id_for_url(recipe_url) or clean_text(recipe_url)
    return f"{user_id}:{recipe_key}"


def _backfill_recipe_label(record, output_record, recipe_url, recipe_key):
    for source in (output_record, record):
        if not isinstance(source, dict):
            continue
        for field in ("name", "title", "recipe_name"):
            label = clean_text(source.get(field))
            if label:
                return label
    return clean_text(recipe_url) or clean_text(recipe_key) or "Recipe"


def _progress_items(progress):
    items = progress.setdefault("items", [])
    if len(items) > MAX_RECIPE_MASTER_BACKFILL_ITEMS:
        progress["items"] = items[-MAX_RECIPE_MASTER_BACKFILL_ITEMS:]
    return progress["items"]


def _find_progress_item(progress, item_key):
    for item in _progress_items(progress):
        if item.get("key") == item_key:
            return item
    return None


def _upsert_progress_item(progress, payload, state):
    item_key = clean_text(payload.get("item_key"))
    if not item_key:
        return None

    item = _find_progress_item(progress, item_key)
    if item is None:
        item = {
            "key": item_key,
            "user_id": clean_text(payload.get("user_id")),
            "recipe_url": clean_text(payload.get("recipe_url")),
            "label": clean_text(payload.get("label")) or clean_text(payload.get("recipe_url")) or "Recipe",
            "state": state,
            "ingredient_count": 0,
            "equipment_count": 0,
            "error": "",
            "updated_at": utc_now_iso(),
        }
        _progress_items(progress).append(item)

    item.update({
        "user_id": clean_text(payload.get("user_id")) or item.get("user_id", ""),
        "recipe_url": clean_text(payload.get("recipe_url")) or item.get("recipe_url", ""),
        "label": clean_text(payload.get("label")) or item.get("label", "Recipe"),
        "state": state,
        "updated_at": utc_now_iso(),
    })

    if "ingredient_count" in payload:
        item["ingredient_count"] = int(payload.get("ingredient_count") or 0)
    if "equipment_count" in payload:
        item["equipment_count"] = int(payload.get("equipment_count") or 0)
    if payload.get("error"):
        item["error"] = clean_text(payload.get("error"))

    _progress_items(progress)
    return item


def update_recipe_master_backfill_progress(job_id, event, payload=None):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None
    payload = payload if isinstance(payload, dict) else {}

    with RECIPE_MASTER_BACKFILL_PROGRESS_LOCK:
        progress = RECIPE_MASTER_BACKFILL_PROGRESS_RUNS.get(job_id)
        if progress is None:
            progress = _new_backfill_progress(job_id)
            RECIPE_MASTER_BACKFILL_PROGRESS_RUNS[job_id] = progress

        now = utc_now_iso()
        progress["updated_at"] = now

        if event == "started":
            progress.update({
                "status": "running",
                "summary": "Backfill is running.",
                "users_total": int(payload.get("users_total") or 0),
                "recipes_total": int(payload.get("recipes_total") or 0),
            })
        elif event == "skipped":
            progress.update({
                "status": "skipped",
                "summary": "Backfill was skipped because the migration marker already exists.",
            })
        elif event == "user_start":
            progress.update({
                "status": "running",
                "current_user_id": clean_text(payload.get("user_id")),
                "summary": f"Scanning {clean_text(payload.get('user_id')) or 'user'} recipes.",
            })
        elif event == "recipe_start":
            item = _upsert_progress_item(progress, payload, "running")
            progress.update({
                "status": "running",
                "current_item_key": item.get("key") if item else "",
                "summary": f"Running {item.get('label') if item else 'recipe'}.",
            })
        elif event == "recipe_done":
            item = _upsert_progress_item(progress, payload, "done")
            progress["recipes_completed"] = int(progress.get("recipes_completed") or 0) + 1
            progress["ingredient_rows"] = int(progress.get("ingredient_rows") or 0) + int(payload.get("ingredient_count") or 0)
            progress["equipment_rows"] = int(progress.get("equipment_rows") or 0) + int(payload.get("equipment_count") or 0)
            progress["summary"] = f"Finished {item.get('label') if item else 'recipe'}."
        elif event == "recipe_failed":
            item = _upsert_progress_item(progress, payload, "failed")
            progress.update({
                "status": "failed",
                "summary": f"Failed {item.get('label') if item else 'recipe'}.",
            })
        elif event == "user_done":
            progress["users_completed"] = int(progress.get("users_completed") or 0) + 1
            progress["current_user_id"] = ""
        elif event == "complete":
            progress.update({
                "status": "complete",
                "summary": "Backfill finished.",
                "users_total": int(payload.get("users") or progress.get("users_total") or 0),
                "recipes_total": int(payload.get("recipes") or progress.get("recipes_total") or 0),
                "recipes_completed": int(payload.get("recipes") or progress.get("recipes_completed") or 0),
                "ingredient_rows": int(payload.get("ingredient_rows") or progress.get("ingredient_rows") or 0),
                "equipment_rows": int(payload.get("equipment_rows") or progress.get("equipment_rows") or 0),
                "current_item_key": "",
                "current_user_id": "",
            })
        elif event == "failed":
            progress.update({
                "status": "failed",
                "summary": clean_text(payload.get("error")) or "Backfill failed.",
            })

        return recipe_master_backfill_progress(job_id)


def _emit_backfill_progress(progress_callback, event, payload=None):
    if not callable(progress_callback):
        return
    try:
        progress_callback(event, payload or {})
    except Exception:
        return


def recipe_master_db_path():
    return Path(os.getenv("SHOPPING_APP_RECIPE_MASTER_DB") or RECIPE_MASTER_DB_PATH)


def get_recipe_master_db_path():
    return recipe_master_db_path()


def recipe_master_db_exists():
    return recipe_master_db_path().is_file()


def recipe_master_db_status():
    db_path = recipe_master_db_path()
    return {
        "path": str(db_path),
        "exists": db_path.is_file(),
        "parent_exists": db_path.parent.exists(),
    }


def scoped_recipe_user_id(user_id=None):
    user_id = str(user_id or "").strip()
    if user_id:
        return user_id

    active_user = storage_service.active_user_id()
    if active_user:
        return active_user

    guest_session_id = storage_service.active_guest_session_id()
    if guest_session_id:
        return f"guest:{guest_session_id}"

    return LOCAL_USER_ID


@contextmanager
def recipe_master_connection():
    db_path = recipe_master_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with RECIPE_MASTER_DB_LOCK:
        connection = sqlite3.connect(str(db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            ensure_recipe_master_schema(connection)
            yield connection
            connection.commit()
        finally:
            connection.close()


@contextmanager
def existing_recipe_master_connection():
    db_path = recipe_master_db_path()
    if not db_path.is_file():
        yield None
        return

    with RECIPE_MASTER_DB_LOCK:
        connection = sqlite3.connect(str(db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            ensure_recipe_master_schema(connection)
            yield connection
            connection.commit()
        finally:
            connection.close()


def ensure_recipe_master_schema(connection=None):
    if connection is None:
        with recipe_master_connection():
            return

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_units (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS unit_aliases (
            alias TEXT PRIMARY KEY,
            canonical_unit_id TEXT NOT NULL,
            FOREIGN KEY(canonical_unit_id) REFERENCES canonical_units(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_units (
            user_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            category TEXT NOT NULL,
            is_seeded INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, id),
            UNIQUE(user_id, normalized_name),
            FOREIGN KEY(id) REFERENCES canonical_units(id) ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_unit_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            canonical_unit_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_alias),
            FOREIGN KEY(user_id, canonical_unit_id)
                REFERENCES workspace_units(user_id, id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_unit_registry_seeds (
            user_id TEXT PRIMARY KEY,
            seed_version TEXT NOT NULL,
            seeded_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_ingredient_types (
            user_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            is_seeded INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, id),
            UNIQUE(user_id, normalized_name)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_ingredient_type_registry_seeds (
            user_id TEXT PRIMARY KEY,
            seed_version TEXT NOT NULL,
            seeded_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            canonical_ingredient TEXT NOT NULL DEFAULT '',
            form TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT 'MISC',
            store_section_source TEXT NOT NULL DEFAULT 'legacy',
            store_section_confidence REAL NOT NULL DEFAULT 0,
            store_section_user_confirmed INTEGER NOT NULL DEFAULT 0,
            classifier_version TEXT NOT NULL DEFAULT '',
            store_section_reason TEXT NOT NULL DEFAULT '',
            store_section_rule TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ingredient_id INTEGER NOT NULL,
            alias_name TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_alias),
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_duplicate_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            left_ingredient_id INTEGER NOT NULL,
            right_ingredient_id INTEGER NOT NULL,
            left_name TEXT NOT NULL,
            right_name TEXT NOT NULL,
            left_normalized_name TEXT NOT NULL,
            right_normalized_name TEXT NOT NULL,
            classification TEXT NOT NULL DEFAULT 'pending',
            status TEXT NOT NULL DEFAULT 'pending',
            confidence REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            suggested_target_id INTEGER DEFAULT NULL,
            signals_json TEXT NOT NULL DEFAULT '{}',
            model TEXT NOT NULL DEFAULT '',
            analysis_source TEXT NOT NULL DEFAULT 'local',
            ai_second_opinion_json TEXT NOT NULL DEFAULT '{}',
            ai_second_opinion_fingerprint TEXT NOT NULL DEFAULT '',
            ai_second_opinion_model TEXT NOT NULL DEFAULT '',
            ai_second_opinion_at TEXT NOT NULL DEFAULT '',
            decision_previous_classification TEXT NOT NULL DEFAULT '',
            decision_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, left_ingredient_id, right_ingredient_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_duplicate_scans (
            user_id TEXT PRIMARY KEY,
            scanned_at TEXT NOT NULL,
            scanned_count INTEGER NOT NULL DEFAULT 0,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_merge_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source_ingredient_id INTEGER NOT NULL,
            target_ingredient_id INTEGER NOT NULL,
            source_name TEXT NOT NULL,
            target_name TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            merged_at TEXT NOT NULL,
            undone_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_store_section_reclassification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            change_count INTEGER NOT NULL DEFAULT 0,
            applied_at TEXT NOT NULL,
            undone_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ingredient_store_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            section_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT 'basket',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_builtin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, section_key)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            equipment_section TEXT NOT NULL DEFAULT 'MISC',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            ingredient_id INTEGER NOT NULL,
            raw_name TEXT NOT NULL DEFAULT '',
            normalized_name TEXT NOT NULL DEFAULT '',
            canonical_ingredient TEXT NOT NULL DEFAULT '',
            form TEXT NOT NULL DEFAULT '',
            quantity TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            unit_id TEXT DEFAULT NULL,
            unit_raw TEXT NOT NULL DEFAULT '',
            size TEXT NOT NULL DEFAULT '',
            preparation TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            unit_review_required INTEGER NOT NULL DEFAULT 0,
            unit_review_value TEXT NOT NULL DEFAULT '',
            unit_custom INTEGER NOT NULL DEFAULT 0,
            buy_as TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT '',
            store_section_source TEXT NOT NULL DEFAULT 'legacy',
            store_section_confidence REAL NOT NULL DEFAULT 0,
            store_section_user_confirmed INTEGER NOT NULL DEFAULT 0,
            classifier_version TEXT NOT NULL DEFAULT '',
            store_section_reason TEXT NOT NULL DEFAULT '',
            store_section_rule TEXT NOT NULL DEFAULT '',
            original_recipe_text TEXT NOT NULL DEFAULT '',
            ingredient_type TEXT NOT NULL DEFAULT 'main',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE,
            FOREIGN KEY(unit_id) REFERENCES canonical_units(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredient_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL DEFAULT '',
            default_option_id TEXT DEFAULT NULL,
            selection_required INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, recipe_id, requirement_id),
            FOREIGN KEY(id, default_option_id)
                REFERENCES recipe_ingredient_options(requirement_id, option_id)
                DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredient_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_id TEXT NOT NULL,
            requirement_id INTEGER NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            option_type TEXT NOT NULL DEFAULT 'substitution'
                CHECK(option_type IN ('original', 'recipe_choice', 'substitution', 'custom')),
            recipe_authored INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(requirement_id, option_id),
            FOREIGN KEY(requirement_id)
                REFERENCES recipe_ingredient_requirements(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredient_option_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_id INTEGER NOT NULL,
            ingredient_id INTEGER DEFAULT NULL,
            raw_name TEXT NOT NULL DEFAULT '',
            normalized_name TEXT NOT NULL DEFAULT '',
            canonical_ingredient TEXT NOT NULL DEFAULT '',
            form TEXT NOT NULL DEFAULT '',
            quantity TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            unit_id TEXT DEFAULT NULL,
            unit_raw TEXT NOT NULL DEFAULT '',
            size TEXT NOT NULL DEFAULT '',
            preparation TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            unit_review_required INTEGER NOT NULL DEFAULT 0,
            unit_review_value TEXT NOT NULL DEFAULT '',
            unit_custom INTEGER NOT NULL DEFAULT 0,
            buy_as TEXT NOT NULL DEFAULT '',
            purchasable_item TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT '',
            store_section_source TEXT NOT NULL DEFAULT 'legacy',
            store_section_confidence REAL NOT NULL DEFAULT 0,
            store_section_user_confirmed INTEGER NOT NULL DEFAULT 0,
            classifier_version TEXT NOT NULL DEFAULT '',
            store_section_reason TEXT NOT NULL DEFAULT '',
            store_section_rule TEXT NOT NULL DEFAULT '',
            original_recipe_text TEXT NOT NULL DEFAULT '',
            ingredient_type TEXT NOT NULL DEFAULT 'main',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(option_id)
                REFERENCES recipe_ingredient_options(id) ON DELETE CASCADE,
            FOREIGN KEY(ingredient_id)
                REFERENCES ingredients(id) ON DELETE SET NULL,
            FOREIGN KEY(unit_id) REFERENCES canonical_units(id)
        )
        """
    )
    migrate_recipe_ingredient_option_item_ingredient_fk(connection)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredient_requirement_sync (
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            requirement_count INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(user_id, recipe_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredient_requirement_migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL,
            source_root TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            summary_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_master_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS unit_normalization_reports (
            migration_name TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    for unit in canonical_unit_options():
        connection.execute(
            """
            INSERT INTO canonical_units (id, name, category, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                sort_order = excluded.sort_order
            """,
            (unit["id"], unit["name"], unit["category"], int(unit["sort_order"])),
        )
    unit_id_by_name = {unit["name"]: unit["id"] for unit in canonical_unit_options()}
    for alias, canonical_name in canonical_unit_aliases().items():
        connection.execute(
            """
            INSERT INTO unit_aliases (alias, canonical_unit_id)
            VALUES (?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                canonical_unit_id = excluded.canonical_unit_id
            """,
            (alias, unit_id_by_name[canonical_name]),
        )
    ingredient_columns = recipe_master_column_names(connection, "ingredients")
    ingredient_column_definitions = {
        "store_section": "TEXT NOT NULL DEFAULT 'MISC'",
        "canonical_ingredient": "TEXT NOT NULL DEFAULT ''",
        "form": "TEXT NOT NULL DEFAULT ''",
        "store_section_source": "TEXT NOT NULL DEFAULT 'legacy'",
        "store_section_confidence": "REAL NOT NULL DEFAULT 0",
        "store_section_user_confirmed": "INTEGER NOT NULL DEFAULT 0",
        "classifier_version": "TEXT NOT NULL DEFAULT ''",
        "store_section_reason": "TEXT NOT NULL DEFAULT ''",
        "store_section_rule": "TEXT NOT NULL DEFAULT ''",
    }
    for column_name, column_definition in ingredient_column_definitions.items():
        if column_name not in ingredient_columns:
            connection.execute(
                f"ALTER TABLE ingredients ADD COLUMN {column_name} {column_definition}"
            )
    equipment_columns = recipe_master_column_names(connection, "equipment")
    if "equipment_section" not in equipment_columns:
        connection.execute(
            "ALTER TABLE equipment ADD COLUMN equipment_section TEXT NOT NULL DEFAULT 'MISC'"
        )
    recipe_ingredient_columns = recipe_master_column_names(connection, "recipe_ingredients")
    recipe_ingredient_column_definitions = {
        "raw_name": "TEXT NOT NULL DEFAULT ''",
        "normalized_name": "TEXT NOT NULL DEFAULT ''",
        "canonical_ingredient": "TEXT NOT NULL DEFAULT ''",
        "form": "TEXT NOT NULL DEFAULT ''",
        "unit_id": "TEXT DEFAULT NULL",
        "unit_raw": "TEXT NOT NULL DEFAULT ''",
        "size": "TEXT NOT NULL DEFAULT ''",
        "preparation": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "unit_review_required": "INTEGER NOT NULL DEFAULT 0",
        "unit_review_value": "TEXT NOT NULL DEFAULT ''",
        "unit_custom": "INTEGER NOT NULL DEFAULT 0",
        "store_section_source": "TEXT NOT NULL DEFAULT 'legacy'",
        "store_section_confidence": "REAL NOT NULL DEFAULT 0",
        "store_section_user_confirmed": "INTEGER NOT NULL DEFAULT 0",
        "classifier_version": "TEXT NOT NULL DEFAULT ''",
        "store_section_reason": "TEXT NOT NULL DEFAULT ''",
        "store_section_rule": "TEXT NOT NULL DEFAULT ''",
        "ingredient_type": "TEXT NOT NULL DEFAULT 'main'",
    }
    for column_name, column_definition in recipe_ingredient_column_definitions.items():
        if column_name not in recipe_ingredient_columns:
            connection.execute(
                f"ALTER TABLE recipe_ingredients ADD COLUMN {column_name} {column_definition}"
            )
    option_item_columns = recipe_master_column_names(
        connection,
        "recipe_ingredient_option_items",
    )
    if "ingredient_type" not in option_item_columns:
        connection.execute(
            "ALTER TABLE recipe_ingredient_option_items "
            "ADD COLUMN ingredient_type TEXT NOT NULL DEFAULT 'main'"
        )
    duplicate_review_columns = recipe_master_column_names(
        connection,
        "ingredient_duplicate_reviews",
    )
    duplicate_review_column_definitions = {
        "ai_second_opinion_json": "TEXT NOT NULL DEFAULT '{}'",
        "ai_second_opinion_fingerprint": "TEXT NOT NULL DEFAULT ''",
        "ai_second_opinion_model": "TEXT NOT NULL DEFAULT ''",
        "ai_second_opinion_at": "TEXT NOT NULL DEFAULT ''",
        "decision_previous_classification": "TEXT NOT NULL DEFAULT ''",
        "decision_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column_name, column_definition in duplicate_review_column_definitions.items():
        if column_name not in duplicate_review_columns:
            connection.execute(
                "ALTER TABLE ingredient_duplicate_reviews "
                f"ADD COLUMN {column_name} {column_definition}"
            )
    migrate_existing_recipe_ingredient_units(connection)
    normalize_existing_ingredient_store_sections(connection)
    normalize_existing_equipment_sections(connection)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredients_user_name ON ingredients(user_id, normalized_name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_aliases_ingredient ON ingredient_aliases(ingredient_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_aliases_user_name ON ingredient_aliases(user_id, normalized_alias)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_duplicate_reviews_user_status ON ingredient_duplicate_reviews(user_id, status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_duplicate_reviews_pair ON ingredient_duplicate_reviews(left_ingredient_id, right_ingredient_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_merge_history_user_undo ON ingredient_merge_history(user_id, undone_at, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_store_section_reclassification_history_user_undo ON ingredient_store_section_reclassification_history(user_id, undone_at, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredient_store_sections_user_order ON ingredient_store_sections(user_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredients_user_section ON ingredients(user_id, store_section)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_equipment_user_name ON equipment(user_id, normalized_name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_equipment_user_section ON equipment(user_id, equipment_section)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_user_recipe ON recipe_ingredients(user_id, recipe_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_ingredient ON recipe_ingredients(ingredient_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_unit ON recipe_ingredients(unit_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_units_user_order ON workspace_units(user_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_unit_aliases_unit ON workspace_unit_aliases(user_id, canonical_unit_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_ingredient_types_user_order ON workspace_ingredient_types(user_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workspace_ingredient_types_user_active ON workspace_ingredient_types(user_id, is_active, sort_order)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_requirements_user_recipe_order ON recipe_ingredient_requirements(user_id, recipe_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_options_requirement_order ON recipe_ingredient_options(requirement_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_option_items_option_order ON recipe_ingredient_option_items(option_id, sort_order, id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_option_items_ingredient ON recipe_ingredient_option_items(ingredient_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_option_items_unit ON recipe_ingredient_option_items(unit_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_type ON recipe_ingredients(user_id, ingredient_type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_option_items_type ON recipe_ingredient_option_items(ingredient_type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_requirement_sync_synced ON recipe_ingredient_requirement_sync(synced_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_requirement_migration_runs_status_started ON recipe_ingredient_requirement_migration_runs(status, started_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_equipment_user_recipe ON recipe_equipment(user_id, recipe_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_equipment_equipment ON recipe_equipment(equipment_id)")


UNIT_REGISTRY_SEED_VERSION = "canonical_units_v1"
UNIT_REGISTRY_CATEGORY_KEYS = frozenset(key for key, _label in UNIT_REGISTRY_CATEGORIES)


def clean_unit_registry_text(value):
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip(),
    )


def unit_registry_key(value):
    value = clean_unit_registry_text(value).lower().replace(".", "")
    value = re.sub(r"[_-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _workspace_unit_id_for_reference(row, unit_ids, unit_id_by_key):
    direct_unit_id = clean_text(row["unit_id"])
    if direct_unit_id in unit_ids:
        return direct_unit_id

    for field in ("unit", "unit_raw"):
        resolved_unit_id = unit_id_by_key.get(unit_registry_key(row[field]))
        if resolved_unit_id:
            return resolved_unit_id
    return ""


def _workspace_unit_usage_counts(connection, user_id, units, aliases_by_id):
    unit_ids = {str(unit["id"]) for unit in units}
    unit_id_by_key = {}
    recipe_ids_by_unit = {unit_id: set() for unit_id in unit_ids}
    for unit in units:
        unit_id = str(unit["id"])
        unit_id_by_key[unit_registry_key(unit["name"])] = unit_id
        for alias in aliases_by_id.get(unit_id, []):
            unit_id_by_key[unit_registry_key(alias)] = unit_id

    rows = connection.execute(
        """
        SELECT r.recipe_id, r.unit_id, r.unit, r.unit_raw
          FROM recipe_ingredients r
         WHERE r.user_id = ?
        UNION ALL
        SELECT requirement.recipe_id, item.unit_id, item.unit, item.unit_raw
          FROM recipe_ingredient_option_items item
          JOIN recipe_ingredient_options option ON option.id = item.option_id
          JOIN recipe_ingredient_requirements requirement
            ON requirement.id = option.requirement_id
         WHERE requirement.user_id = ?
        """,
        (user_id, user_id),
    ).fetchall()
    for row in rows:
        recipe_id = clean_text(row["recipe_id"])
        if not recipe_id:
            continue
        unit_id = _workspace_unit_id_for_reference(
            row,
            unit_ids,
            unit_id_by_key,
        )
        if unit_id:
            recipe_ids_by_unit[unit_id].add(recipe_id)

    return {
        unit_id: len(recipe_ids)
        for unit_id, recipe_ids in recipe_ids_by_unit.items()
    }


def _workspace_unit_registry_payload_from_connection(connection, user_id):
    unit_rows = connection.execute(
        """
        SELECT id, name, category, is_seeded, sort_order, created_at, updated_at
          FROM workspace_units
         WHERE user_id = ?
         ORDER BY sort_order ASC, normalized_name ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    if not unit_rows:
        return None

    alias_rows = connection.execute(
        """
        SELECT canonical_unit_id, alias, normalized_alias
          FROM workspace_unit_aliases
         WHERE user_id = ?
         ORDER BY LENGTH(alias) ASC, normalized_alias ASC
        """,
        (user_id,),
    ).fetchall()
    aliases_by_id = {}
    for row in alias_rows:
        aliases_by_id.setdefault(str(row["canonical_unit_id"]), []).append(
            str(row["alias"])
        )

    units = []
    aliases = {}
    for row in unit_rows:
        unit_id = str(row["id"])
        name = str(row["name"])
        unit_aliases = aliases_by_id.get(unit_id, [])
        unit = {
            "id": unit_id,
            "name": name,
            "category": str(row["category"]),
            "sort_order": int(row["sort_order"] or 0),
            "seeded": bool(row["is_seeded"]),
            "custom": not bool(row["is_seeded"]),
            "aliases": unit_aliases,
            "updated_at": str(row["updated_at"] or ""),
        }
        units.append(unit)
        aliases[unit_registry_key(name)] = name
        for alias in unit_aliases:
            aliases[unit_registry_key(alias)] = name

    return {
        "units": units,
        "aliases": aliases,
        "categories": [
            {"key": key, "label": label}
            for key, label in UNIT_REGISTRY_CATEGORIES
        ],
    }


def workspace_unit_recipe_references(unit_id, user_id=None, limit=100):
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    unit_id = str(unit_id or "").strip()
    try:
        limit = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        limit = 100

    with recipe_master_connection() as connection:
        _seed_workspace_unit_registry(connection, user_id)
        registry = _workspace_unit_registry_payload_from_connection(connection, user_id)
        unit = next(
            (
                item
                for item in (registry or {}).get("units", [])
                if str(item.get("id")) == unit_id
            ),
            None,
        )
        if not unit:
            return {
                "unit": None,
                "references": [],
                "total": 0,
                "total_reference_count": 0,
                "limit": limit,
            }

        unit_ids = {
            str(item["id"])
            for item in registry.get("units", [])
        }
        unit_id_by_key = {}
        for item in registry.get("units", []):
            item_id = str(item["id"])
            unit_id_by_key[unit_registry_key(item["name"])] = item_id
            for alias in item.get("aliases", []):
                unit_id_by_key[unit_registry_key(alias)] = item_id

        ingredient_rows = connection.execute(
            """
            SELECT
                r.id,
                'ingredient' AS reference_kind,
                r.recipe_id,
                COALESCE(NULLIF(source_ingredient.name, ''), NULLIF(r.raw_name, ''),
                         NULLIF(r.normalized_name, ''), '') AS ingredient_name,
                r.quantity,
                r.unit,
                r.unit_id,
                r.unit_raw,
                r.preparation,
                r.notes,
                r.original_recipe_text,
                r.optional,
                r.sort_order,
                '' AS option_label,
                '' AS requirement_label,
                '' AS option_type
              FROM recipe_ingredients r
              LEFT JOIN ingredients source_ingredient
                ON source_ingredient.id = r.ingredient_id
               AND source_ingredient.user_id = r.user_id
             WHERE r.user_id = ?
            """,
            (user_id,),
        ).fetchall()
        option_rows = connection.execute(
            """
            SELECT
                item.id,
                'option' AS reference_kind,
                requirement.recipe_id,
                COALESCE(NULLIF(source_ingredient.name, ''), NULLIF(item.raw_name, ''),
                         NULLIF(item.normalized_name, ''), '') AS ingredient_name,
                item.quantity,
                item.unit,
                item.unit_id,
                item.unit_raw,
                item.preparation,
                item.notes,
                item.original_recipe_text,
                item.optional,
                item.sort_order,
                option.label AS option_label,
                requirement.label AS requirement_label,
                option.option_type AS option_type
              FROM recipe_ingredient_option_items item
              JOIN recipe_ingredient_options option ON option.id = item.option_id
              JOIN recipe_ingredient_requirements requirement
                ON requirement.id = option.requirement_id
              LEFT JOIN ingredients source_ingredient
                ON source_ingredient.id = item.ingredient_id
               AND source_ingredient.user_id = requirement.user_id
             WHERE requirement.user_id = ?
            """,
            (user_id,),
        ).fetchall()

    metadata = recipe_reference_metadata(user_id)
    references_by_recipe = {}
    total_reference_count = 0
    matching_rows = sorted(
        [*ingredient_rows, *option_rows],
        key=lambda row: (
            clean_text(row["recipe_id"]).lower(),
            0 if clean_text(row["reference_kind"]) == "ingredient" else 1,
            int(row["sort_order"] or 0),
            int(row["id"] or 0),
        ),
    )
    match_keys_by_recipe = {}
    for row in matching_rows:
        resolved_unit_id = _workspace_unit_id_for_reference(
            row,
            unit_ids,
            unit_id_by_key,
        )
        if resolved_unit_id != unit_id:
            continue

        recipe_id = clean_text(row["recipe_id"])
        metadata_record = metadata.get(recipe_id)
        metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
        recipe_url = clean_text(metadata_record.get("url")) or recipe_id
        reference = references_by_recipe.setdefault(recipe_id, {
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "recipe_title": recipe_reference_title(recipe_id, metadata_record),
            "cover_image": dict(metadata_record.get("cover_image"))
            if isinstance(metadata_record.get("cover_image"), dict)
            else {},
            "matches": [],
        })
        original_text = clean_text(row["original_recipe_text"])
        ingredient_name = clean_text(row["ingredient_name"])
        quantity = clean_text(row["quantity"])
        unit_name = clean_text(row["unit"])
        preparation = clean_text(row["preparation"])
        notes = clean_text(row["notes"])
        if original_text:
            ingredient_line = original_text
        else:
            ingredient_line = " ".join(
                value for value in (quantity, unit_name, ingredient_name) if value
            )
            if preparation:
                ingredient_line = f"{ingredient_line}, {preparation}" if ingredient_line else preparation
            if notes:
                ingredient_line = f"{ingredient_line} ({notes})" if ingredient_line else notes
        matched_as = clean_text(row["unit_raw"]) or unit_name
        option_label = clean_text(row["option_label"])
        requirement_label = clean_text(row["requirement_label"])
        option_type = clean_text(row["option_type"])
        match_key = (
            unit_registry_key(ingredient_line or ingredient_name),
            unit_registry_key(matched_as),
            unit_registry_key(ingredient_name),
        )
        recipe_match_keys = match_keys_by_recipe.setdefault(recipe_id, set())
        if option_type == "original" and match_key in recipe_match_keys:
            continue
        recipe_match_keys.add(match_key)
        total_reference_count += 1
        reference["matches"].append({
            "id": int(row["id"] or 0),
            "kind": clean_text(row["reference_kind"]),
            "ingredient_line": ingredient_line or ingredient_name or "Ingredient line",
            "ingredient_name": ingredient_name,
            "matched_as": matched_as,
            "is_alias_match": bool(
                matched_as
                and unit_registry_key(matched_as) != unit_registry_key(unit["name"])
            ),
            "context": option_label or requirement_label,
            "optional": bool(row["optional"]),
        })

    references = list(references_by_recipe.values())
    return {
        "unit": unit,
        "references": references[:limit],
        "total": len(references),
        "total_reference_count": total_reference_count,
        "limit": limit,
    }


def read_workspace_unit_registry(user_id=None):
    """Read a seeded workspace registry without triggering schema recursion."""
    user_id = str(user_id or "").strip()
    db_path = recipe_master_db_path()
    if not user_id or not db_path.is_file():
        return None

    with RECIPE_MASTER_DB_LOCK:
        connection = sqlite3.connect(str(db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            table = connection.execute(
                """
                SELECT name FROM sqlite_master
                 WHERE type = 'table' AND name = 'workspace_units'
                """
            ).fetchone()
            if not table:
                return None
            return _workspace_unit_registry_payload_from_connection(connection, user_id)
        except sqlite3.OperationalError:
            return None
        finally:
            connection.close()


def _seed_workspace_unit_registry(connection, user_id):
    marker = connection.execute(
        "SELECT seed_version FROM workspace_unit_registry_seeds WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if marker:
        return False

    timestamp = utc_now_iso()
    for unit in canonical_unit_options():
        connection.execute(
            """
            INSERT OR IGNORE INTO workspace_units (
                user_id, id, name, normalized_name, category, is_seeded,
                sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                user_id,
                unit["id"],
                unit["name"],
                unit_registry_key(unit["name"]),
                unit["category"],
                int(unit["sort_order"]),
                timestamp,
                timestamp,
            ),
        )

    unit_id_by_name = {unit["name"]: unit["id"] for unit in canonical_unit_options()}
    for alias, canonical_name in canonical_unit_aliases().items():
        if unit_registry_key(alias) == unit_registry_key(canonical_name):
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO workspace_unit_aliases (
                user_id, canonical_unit_id, alias, normalized_alias,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                unit_id_by_name[canonical_name],
                clean_unit_registry_text(alias),
                unit_registry_key(alias),
                timestamp,
                timestamp,
            ),
        )

    connection.execute(
        """
        INSERT INTO workspace_unit_registry_seeds (user_id, seed_version, seeded_at)
        VALUES (?, ?, ?)
        """,
        (user_id, UNIT_REGISTRY_SEED_VERSION, timestamp),
    )
    return True


def ensure_workspace_unit_registry(user_id=None):
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    with recipe_master_connection() as connection:
        _seed_workspace_unit_registry(connection, user_id)
        payload = _workspace_unit_registry_payload_from_connection(connection, user_id)
    from PushShoppingList.services.ingredient_unit_service import clear_unit_registry_cache

    clear_unit_registry_cache()
    return payload


def workspace_unit_registry_with_usage(user_id=None):
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    with recipe_master_connection() as connection:
        _seed_workspace_unit_registry(connection, user_id)
        payload = _workspace_unit_registry_payload_from_connection(connection, user_id)
        usage_counts = _workspace_unit_usage_counts(
            connection,
            user_id,
            payload.get("units", []),
            {
                str(unit["id"]): list(unit.get("aliases", []))
                for unit in payload.get("units", [])
            },
        )
        for unit in payload.get("units", []):
            unit["recipe_count"] = int(
                usage_counts.get(str(unit["id"])) or 0
            )
    return payload


def _unit_registry_validation(connection, user_id, values, unit_id=""):
    canonical_name = clean_unit_registry_text(values.get("canonical_name") or values.get("name"))
    category = unit_registry_key(values.get("category")).replace(" ", "_")
    raw_aliases = values.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raw_aliases = []

    errors = {}
    alias_errors = {}
    if not canonical_name:
        errors["canonical_name"] = "Enter a canonical name."
    elif len(canonical_name) > 60:
        errors["canonical_name"] = "Canonical names must be 60 characters or fewer."
    canonical_key = unit_registry_key(canonical_name)
    if canonical_name and not canonical_key:
        errors["canonical_name"] = "Enter a canonical name with letters or numbers."
    if category not in UNIT_REGISTRY_CATEGORY_KEYS:
        errors["category"] = "Choose one of the system-managed unit categories."

    aliases = []
    alias_keys = set()
    for index, raw_alias in enumerate(raw_aliases):
        alias = clean_unit_registry_text(raw_alias)
        alias_key = unit_registry_key(alias)
        if not alias:
            alias_errors[str(index)] = "Aliases cannot be blank."
        elif len(alias) > 60:
            alias_errors[str(index)] = "Aliases must be 60 characters or fewer."
        elif not alias_key:
            alias_errors[str(index)] = "Enter an alias with letters or numbers."
        elif alias_key == canonical_key:
            alias_errors[str(index)] = "The canonical name does not need to be an alias."
        elif alias_key in alias_keys:
            alias_errors[str(index)] = "Remove this duplicate alias."
        else:
            aliases.append(alias)
            alias_keys.add(alias_key)

    rows = connection.execute(
        """
        SELECT id, name, normalized_name, is_seeded, category
          FROM workspace_units WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    units_by_key = {
        str(row["normalized_name"]): row
        for row in rows
        if str(row["id"]) != unit_id
    }
    alias_rows = connection.execute(
        """
        SELECT a.canonical_unit_id, a.alias, a.normalized_alias, u.name
          FROM workspace_unit_aliases a
          JOIN workspace_units u
            ON u.user_id = a.user_id AND u.id = a.canonical_unit_id
         WHERE a.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    aliases_by_key = {
        str(row["normalized_alias"]): row
        for row in alias_rows
        if str(row["canonical_unit_id"]) != unit_id
    }

    if canonical_key in units_by_key:
        errors["canonical_name"] = (
            f'{units_by_key[canonical_key]["name"]} is already a canonical unit.'
        )
    elif canonical_key in aliases_by_key:
        errors["canonical_name"] = (
            f'{aliases_by_key[canonical_key]["alias"]} is already an alias for '
            f'{aliases_by_key[canonical_key]["name"]}.'
        )

    for index, alias in enumerate(raw_aliases):
        if str(index) in alias_errors:
            continue
        alias_key = unit_registry_key(alias)
        if alias_key in units_by_key:
            alias_errors[str(index)] = (
                f'{units_by_key[alias_key]["name"]} is already a canonical unit.'
            )
        elif alias_key in aliases_by_key:
            alias_errors[str(index)] = (
                f'{aliases_by_key[alias_key]["alias"]} is already an alias for '
                f'{aliases_by_key[alias_key]["name"]}.'
            )
    if alias_errors:
        errors["aliases"] = alias_errors

    return {
        "canonical_name": canonical_name,
        "canonical_key": canonical_key,
        "category": category,
        "aliases": aliases,
        "alias_keys": alias_keys,
        "errors": errors,
    }


def validate_workspace_unit_candidate(values, unit_id="", user_id=None):
    """Validate a unit draft without saving it.

    This keeps AI-assisted drafts and normal form submissions on exactly the
    same normalization and collision rules.
    """
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    unit_id = str(unit_id or "").strip()
    values = values if isinstance(values, dict) else {}
    with recipe_master_connection() as connection:
        _seed_workspace_unit_registry(connection, user_id)
        if unit_id:
            existing = connection.execute(
                "SELECT id FROM workspace_units WHERE user_id = ? AND id = ?",
                (user_id, unit_id),
            ).fetchone()
            if not existing:
                return {"ok": False, "status": 404, "error": "Unit not found."}
        validated = _unit_registry_validation(
            connection,
            user_id,
            values,
            unit_id=unit_id,
        )

    return {
        "ok": not bool(validated["errors"]),
        "status": 200 if not validated["errors"] else 422,
        "candidate": {
            "canonical_name": validated["canonical_name"],
            "category": validated["category"],
            "aliases": list(validated["aliases"]),
        },
        "errors": validated["errors"],
    }


def _workspace_unit_alias_keys(connection, user_id, unit_id):
    return {
        str(row["normalized_alias"])
        for row in connection.execute(
            """
            SELECT normalized_alias FROM workspace_unit_aliases
             WHERE user_id = ? AND canonical_unit_id = ?
            """,
            (user_id, unit_id),
        ).fetchall()
    }


def save_workspace_unit(values, unit_id="", user_id=None):
    """Create or edit one scoped unit in a duplicate-safe transaction."""
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    unit_id = str(unit_id or "").strip()
    values = values if isinstance(values, dict) else {}
    with recipe_master_connection() as connection:
        _seed_workspace_unit_registry(connection, user_id)
        existing = None
        if unit_id:
            existing = connection.execute(
                """
                SELECT id, name, normalized_name, category, is_seeded, sort_order,
                       created_at, updated_at
                  FROM workspace_units WHERE user_id = ? AND id = ?
                """,
                (user_id, unit_id),
            ).fetchone()
            if not existing:
                return {"ok": False, "status": 404, "error": "Unit not found."}

        validated = _unit_registry_validation(
            connection,
            user_id,
            values,
            unit_id=unit_id,
        )
        if validated["errors"]:
            if not unit_id and "canonical_name" in validated["errors"]:
                repeated = connection.execute(
                    """
                    SELECT id, category, is_seeded
                      FROM workspace_units
                     WHERE user_id = ? AND normalized_name = ?
                    """,
                    (user_id, validated["canonical_key"]),
                ).fetchone()
                if repeated and not bool(repeated["is_seeded"]):
                    repeated_aliases = _workspace_unit_alias_keys(
                        connection,
                        user_id,
                        str(repeated["id"]),
                    )
                    if (
                        str(repeated["category"]) == validated["category"]
                        and repeated_aliases == validated["alias_keys"]
                    ):
                        payload = _workspace_unit_registry_payload_from_connection(
                            connection,
                            user_id,
                        )
                        return {
                            "ok": True,
                            "created": False,
                            "unit_id": str(repeated["id"]),
                            "message": f'{validated["canonical_name"]} is already saved.',
                            "registry": payload,
                        }
            return {
                "ok": False,
                "status": 422,
                "error": "Correct the highlighted unit fields.",
                "errors": validated["errors"],
            }

        timestamp = utc_now_iso()
        previous_name = str(existing["name"]) if existing else ""
        previous_keys = {unit_registry_key(previous_name)} if previous_name else set()
        if existing:
            previous_keys.update(_workspace_unit_alias_keys(connection, user_id, unit_id))
            connection.execute(
                """
                UPDATE workspace_units
                   SET name = ?, normalized_name = ?, category = ?, updated_at = ?
                 WHERE user_id = ? AND id = ?
                """,
                (
                    validated["canonical_name"],
                    validated["canonical_key"],
                    validated["category"],
                    timestamp,
                    user_id,
                    unit_id,
                ),
            )
        else:
            unit_id = f"custom_{uuid.uuid4().hex}"
            sort_order = int(connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM workspace_units WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO canonical_units (id, name, category, sort_order)
                VALUES (?, ?, 'custom', ?)
                """,
                (unit_id, unit_id, sort_order),
            )
            connection.execute(
                """
                INSERT INTO workspace_units (
                    user_id, id, name, normalized_name, category, is_seeded,
                    sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    user_id,
                    unit_id,
                    validated["canonical_name"],
                    validated["canonical_key"],
                    validated["category"],
                    sort_order,
                    timestamp,
                    timestamp,
                ),
            )

        aliases = list(validated["aliases"])
        if previous_name and unit_registry_key(previous_name) != validated["canonical_key"]:
            if unit_registry_key(previous_name) not in {unit_registry_key(item) for item in aliases}:
                aliases.append(previous_name)
        connection.execute(
            "DELETE FROM workspace_unit_aliases WHERE user_id = ? AND canonical_unit_id = ?",
            (user_id, unit_id),
        )
        for alias in aliases:
            connection.execute(
                """
                INSERT INTO workspace_unit_aliases (
                    user_id, canonical_unit_id, alias, normalized_alias,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    unit_id,
                    alias,
                    unit_registry_key(alias),
                    timestamp,
                    timestamp,
                ),
            )

        if existing and previous_name != validated["canonical_name"]:
            rows = connection.execute(
                """
                SELECT id, unit, unit_id FROM recipe_ingredients
                 WHERE user_id = ? AND (unit_id = ? OR unit_id IS NULL OR unit_id = '')
                """,
                (user_id, unit_id),
            ).fetchall()
            for row in rows:
                if str(row["unit_id"] or "") == unit_id or unit_registry_key(row["unit"]) in previous_keys:
                    connection.execute(
                        "UPDATE recipe_ingredients SET unit = ?, unit_id = ? WHERE id = ?",
                        (validated["canonical_name"], unit_id, int(row["id"])),
                    )
            option_rows = connection.execute(
                """
                SELECT item.id, item.unit, item.unit_id
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ?
                   AND (item.unit_id = ? OR item.unit_id IS NULL OR item.unit_id = '')
                """,
                (user_id, unit_id),
            ).fetchall()
            for row in option_rows:
                if str(row["unit_id"] or "") == unit_id or unit_registry_key(row["unit"]) in previous_keys:
                    connection.execute(
                        "UPDATE recipe_ingredient_option_items SET unit = ?, unit_id = ? WHERE id = ?",
                        (validated["canonical_name"], unit_id, int(row["id"])),
                    )

        payload = _workspace_unit_registry_payload_from_connection(connection, user_id)

    from PushShoppingList.services.ingredient_unit_service import clear_unit_registry_cache

    clear_unit_registry_cache()
    return {
        "ok": True,
        "created": not bool(existing),
        "unit_id": unit_id,
        "message": (
            f'{validated["canonical_name"]} added.'
            if not existing
            else f'{validated["canonical_name"]} updated.'
        ),
        "registry": payload,
    }


def import_workspace_unit_names(values, user_id=None):
    user_id = str(user_id or scoped_recipe_user_id()).strip()
    values = values if isinstance(values, list) else []
    imported = []
    skipped = []
    for value in values:
        name = clean_unit_registry_text(value)
        if not name:
            continue
        result = save_workspace_unit(
            {"canonical_name": name, "category": "count_package", "aliases": []},
            user_id=user_id,
        )
        if result.get("ok") and result.get("created"):
            imported.append(name)
        else:
            skipped.append({"name": name, "error": result.get("error") or result.get("message")})
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "message": f"Imported {len(imported)} browser unit{'s' if len(imported) != 1 else ''}.",
        "registry": ensure_workspace_unit_registry(user_id),
    }


def recipe_master_column_names(connection, table_name):
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in rows
    }


def migrate_recipe_ingredient_option_item_ingredient_fk(connection):
    """Upgrade early draft schemas from RESTRICT to lossless SET NULL."""
    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(recipe_ingredient_option_items)"
    ).fetchall()
    ingredient_fk = next(
        (
            row
            for row in foreign_keys
            if str(row["table"]) == "ingredients"
            and str(row["from"]) == "ingredient_id"
        ),
        None,
    )
    if ingredient_fk and str(ingredient_fk["on_delete"]).upper() == "SET NULL":
        return False

    replacement_table = "recipe_ingredient_option_items_fk_v2"
    connection.execute(f"DROP TABLE IF EXISTS {replacement_table}")
    connection.execute(
        f"""
        CREATE TABLE {replacement_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_id INTEGER NOT NULL,
            ingredient_id INTEGER DEFAULT NULL,
            raw_name TEXT NOT NULL DEFAULT '',
            normalized_name TEXT NOT NULL DEFAULT '',
            canonical_ingredient TEXT NOT NULL DEFAULT '',
            form TEXT NOT NULL DEFAULT '',
            quantity TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            unit_id TEXT DEFAULT NULL,
            unit_raw TEXT NOT NULL DEFAULT '',
            size TEXT NOT NULL DEFAULT '',
            preparation TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            unit_review_required INTEGER NOT NULL DEFAULT 0,
            unit_review_value TEXT NOT NULL DEFAULT '',
            unit_custom INTEGER NOT NULL DEFAULT 0,
            buy_as TEXT NOT NULL DEFAULT '',
            purchasable_item TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT '',
            store_section_source TEXT NOT NULL DEFAULT 'legacy',
            store_section_confidence REAL NOT NULL DEFAULT 0,
            store_section_user_confirmed INTEGER NOT NULL DEFAULT 0,
            classifier_version TEXT NOT NULL DEFAULT '',
            store_section_reason TEXT NOT NULL DEFAULT '',
            store_section_rule TEXT NOT NULL DEFAULT '',
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(option_id)
                REFERENCES recipe_ingredient_options(id) ON DELETE CASCADE,
            FOREIGN KEY(ingredient_id)
                REFERENCES ingredients(id) ON DELETE SET NULL,
            FOREIGN KEY(unit_id) REFERENCES canonical_units(id)
        )
        """
    )
    columns = (
        "id", "option_id", "ingredient_id", "raw_name", "normalized_name",
        "canonical_ingredient", "form", "quantity", "unit", "unit_id",
        "unit_raw", "size", "preparation", "notes", "unit_review_required",
        "unit_review_value", "unit_custom", "buy_as", "purchasable_item",
        "store_section", "store_section_source", "store_section_confidence",
        "store_section_user_confirmed", "classifier_version",
        "store_section_reason", "store_section_rule", "original_recipe_text",
        "optional", "sort_order", "metadata_json", "created_at", "updated_at",
    )
    column_list = ", ".join(columns)
    connection.execute(
        f"INSERT INTO {replacement_table} ({column_list}) "
        f"SELECT {column_list} FROM recipe_ingredient_option_items"
    )
    connection.execute("DROP TABLE recipe_ingredient_option_items")
    connection.execute(
        f"ALTER TABLE {replacement_table} RENAME TO recipe_ingredient_option_items"
    )
    return True


def migrate_existing_recipe_ingredient_units(connection):
    """Normalize legacy master rows once and retain an auditable summary."""
    if migration_already_applied(connection, UNIT_NORMALIZATION_MIGRATION_NAME):
        report_row = connection.execute(
            "SELECT report_json FROM unit_normalization_reports WHERE migration_name = ?",
            (UNIT_NORMALIZATION_MIGRATION_NAME,),
        ).fetchone()
        if report_row:
            try:
                return json.loads(report_row["report_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return {"ok": True, "skipped": True}

    summary = {
        "ok": True,
        "migration": UNIT_NORMALIZATION_MIGRATION_NAME,
        "rows_scanned": 0,
        "aliases_replaced": 0,
        "size_values_moved": 0,
        "ingredient_names_moved": 0,
        "invalid_units_cleared": 0,
        "ambiguous_rows_flagged": 0,
    }
    rows = connection.execute(
        """
        SELECT r.id, r.quantity, r.unit, r.original_recipe_text,
               i.name AS ingredient
          FROM recipe_ingredients r
          JOIN ingredients i ON i.id = r.ingredient_id
        """
    ).fetchall()
    for stored_row in rows:
        summary["rows_scanned"] += 1
        before_unit = clean_text(stored_row["unit"])
        before_ingredient = clean_text(stored_row["ingredient"])
        normalized = normalize_ingredient_unit_fields({
            "quantity": clean_text(stored_row["quantity"]),
            "unit": before_unit,
            "ingredient": before_ingredient,
            "original_text": clean_text(stored_row["original_recipe_text"]),
        }, log_unrecognized=False)
        after_unit = clean_text(normalized.get("unit"))
        if before_unit and canonical_unit(before_unit) and after_unit != before_unit:
            summary["aliases_replaced"] += 1
        if normalized.get("size"):
            summary["size_values_moved"] += 1
        if before_unit.lower() in {"pepper", "onion", "garlic"}:
            summary["ingredient_names_moved"] += 1
        if before_unit and not after_unit and normalized.get("unit_review_required"):
            summary["invalid_units_cleared"] += 1
        if normalized.get("unit_review_required"):
            summary["ambiguous_rows_flagged"] += 1

        connection.execute(
            """
            UPDATE recipe_ingredients
               SET quantity = ?, unit = ?, unit_id = ?, unit_raw = ?, size = ?,
                   preparation = ?, unit_review_required = ?, unit_review_value = ?
             WHERE id = ?
            """,
            (
                clean_text(normalized.get("quantity")),
                after_unit,
                clean_text(normalized.get("unit_id")) or None,
                clean_text(normalized.get("unit_raw")),
                clean_text(normalized.get("size")),
                clean_text(normalized.get("preparation")),
                1 if normalized.get("unit_review_required") else 0,
                clean_text(normalized.get("unit_review_value")),
                int(stored_row["id"]),
            ),
        )
    mark_migration_applied(connection, UNIT_NORMALIZATION_MIGRATION_NAME)
    connection.execute(
        """
        INSERT OR REPLACE INTO unit_normalization_reports (
            migration_name, report_json, created_at
        ) VALUES (?, ?, ?)
        """,
        (UNIT_NORMALIZATION_MIGRATION_NAME, json.dumps(summary, sort_keys=True), utc_now_iso()),
    )
    return summary


def normalize_ingredient_store_section_key(value):
    section = re.sub(r"\s+", " ", str(value or "").strip().upper())
    if not section:
        return ""
    return INGREDIENT_STORE_SECTION_ALIASES.get(section, section)[:80]


def default_ingredient_store_section_details():
    return [
        {
            "id": 0,
            "section_key": section_key,
            "display_name": INGREDIENT_STORE_SECTION_DISPLAY_NAMES.get(
                section_key,
                section_key.title(),
            ),
            "icon": INGREDIENT_STORE_SECTION_ICONS.get(section_key, "basket"),
            "sort_order": int(sort_order),
            "is_builtin": True,
            "is_active": True,
            "ingredient_count": 0,
            "recipe_reference_count": 0,
        }
        for section_key, sort_order in INGREDIENT_STORE_SECTION_ORDER.items()
    ]


def ensure_ingredient_store_sections_for_user(connection, user_id):
    user_id = scoped_recipe_user_id(user_id)
    timestamp = utc_now_iso()
    for section in default_ingredient_store_section_details():
        connection.execute(
            """
            INSERT OR IGNORE INTO ingredient_store_sections (
                user_id,
                section_key,
                display_name,
                icon,
                sort_order,
                is_builtin,
                is_active,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (
                user_id,
                section["section_key"],
                section["display_name"],
                section["icon"],
                section["sort_order"],
                timestamp,
                timestamp,
            ),
        )
    return user_id


def ingredient_store_section_details(user_id=None, include_inactive=False, create=False):
    scoped_user_id = scoped_recipe_user_id(user_id)
    db_path = recipe_master_db_path()
    if not create and not db_path.is_file():
        return default_ingredient_store_section_details()

    connection_manager = recipe_master_connection if create else existing_recipe_master_connection
    with connection_manager() as connection:
        if connection is None:
            return default_ingredient_store_section_details()
        ensure_ingredient_store_sections_for_user(connection, scoped_user_id)
        active_clause = "" if include_inactive else "AND s.is_active = 1"
        rows = connection.execute(
            f"""
            SELECT
                s.id,
                s.user_id,
                s.section_key,
                s.display_name,
                s.icon,
                s.sort_order,
                s.is_builtin,
                s.is_active,
                s.created_at,
                s.updated_at,
                (
                    SELECT COUNT(*)
                      FROM ingredients i
                     WHERE i.user_id = s.user_id
                       AND i.store_section = s.section_key
                ) AS ingredient_count,
                (
                    SELECT COUNT(*)
                      FROM recipe_ingredients ri
                     WHERE ri.user_id = s.user_id
                       AND ri.store_section = s.section_key
                ) AS recipe_reference_count
              FROM ingredient_store_sections s
             WHERE s.user_id = ?
               {active_clause}
             ORDER BY s.sort_order ASC, LOWER(s.display_name) ASC, s.id ASC
            """,
            (scoped_user_id,),
        ).fetchall()
        return [
            {
                **dict(row),
                "is_builtin": bool(row["is_builtin"]),
                "is_active": bool(row["is_active"]),
                "ingredient_count": int(row["ingredient_count"] or 0),
                "recipe_reference_count": int(row["recipe_reference_count"] or 0),
            }
            for row in rows
        ]


def ingredient_store_section_usage(section_id, user_id=None):
    try:
        section_id = int(section_id or 0)
    except (TypeError, ValueError):
        section_id = 0
    if section_id <= 0:
        return None

    scoped_user_id = scoped_recipe_user_id(user_id)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return None

        section_row = connection.execute(
            """
            SELECT id, section_key, display_name, icon, is_active
              FROM ingredient_store_sections
             WHERE id = ?
               AND user_id = ?
            """,
            (section_id, scoped_user_id),
        ).fetchone()
        if not section_row:
            return None

        section = dict(section_row)
        section["is_active"] = bool(section["is_active"])
        ingredient_rows = connection.execute(
            """
            SELECT
                i.id,
                i.name,
                i.normalized_name,
                i.image_url,
                COUNT(ri.id) AS recipe_reference_count
              FROM ingredients i
              LEFT JOIN recipe_ingredients ri
                ON ri.user_id = i.user_id
               AND ri.ingredient_id = i.id
             WHERE i.user_id = ?
               AND i.store_section = ?
             GROUP BY i.id, i.name, i.normalized_name, i.image_url
             ORDER BY LOWER(i.name) ASC, i.id ASC
            """,
            (scoped_user_id, section["section_key"]),
        ).fetchall()
        reference_rows = connection.execute(
            """
            SELECT
                ri.id,
                ri.recipe_id,
                ri.ingredient_id,
                ri.raw_name,
                ri.canonical_ingredient,
                ri.normalized_name,
                ri.original_recipe_text,
                i.name AS master_ingredient_name
              FROM recipe_ingredients ri
              LEFT JOIN ingredients i
                ON i.id = ri.ingredient_id
               AND i.user_id = ri.user_id
             WHERE ri.user_id = ?
               AND ri.store_section = ?
             ORDER BY LOWER(ri.recipe_id) ASC, ri.sort_order ASC, ri.id ASC
            """,
            (scoped_user_id, section["section_key"]),
        ).fetchall()

    ingredients = [
        {
            "id": int(row["id"]),
            "name": clean_text(row["name"]) or "Ingredient",
            "normalized_name": clean_text(row["normalized_name"]),
            "image_url": clean_text(row["image_url"]),
            "recipe_reference_count": int(row["recipe_reference_count"] or 0),
        }
        for row in ingredient_rows
    ]

    metadata = recipe_reference_metadata(scoped_user_id)
    recipes_by_id = {}
    for row in reference_rows:
        recipe_id = clean_text(row["recipe_id"])
        metadata_record = metadata.get(recipe_id)
        metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
        cover_image = metadata_record.get("cover_image")
        recipe = recipes_by_id.setdefault(
            recipe_id,
            {
                "recipe_id": recipe_id,
                "recipe_url": clean_text(metadata_record.get("url")) or recipe_id,
                "recipe_title": recipe_reference_title(recipe_id, metadata_record),
                "cover_image": (
                    dict(cover_image)
                    if isinstance(cover_image, dict)
                    else {}
                ),
                "reference_count": 0,
                "ingredients": [],
            },
        )
        recipe["reference_count"] += 1
        ingredient_name = (
            clean_text(row["master_ingredient_name"])
            or clean_text(row["raw_name"])
            or clean_text(row["canonical_ingredient"])
            or clean_text(row["normalized_name"])
            or clean_text(row["original_recipe_text"])
            or "Ingredient"
        )
        if ingredient_name not in recipe["ingredients"]:
            recipe["ingredients"].append(ingredient_name)

    recipes = sorted(
        recipes_by_id.values(),
        key=lambda item: (
            clean_text(item.get("recipe_title")).lower(),
            clean_text(item.get("recipe_id")).lower(),
        ),
    )
    return {
        "section": section,
        "ingredients": ingredients,
        "recipes": recipes,
        "ingredient_total": len(ingredients),
        "recipe_reference_total": len(reference_rows),
        "recipe_total": len(recipes),
    }


def ingredient_store_section_options(user_id=None, include_inactive=False):
    return [
        section["section_key"]
        for section in ingredient_store_section_details(
            user_id=user_id,
            include_inactive=include_inactive,
        )
    ]


def ingredient_store_section_from_source(value, user_id=None, connection=None):
    section = normalize_ingredient_store_section_key(value)
    if not section:
        return ""
    if section in INGREDIENT_STORE_SECTION_ORDER:
        return section

    scoped_user_id = clean_text(user_id)
    if not scoped_user_id:
        return ""
    if connection is not None:
        row = connection.execute(
            """
            SELECT section_key
              FROM ingredient_store_sections
             WHERE user_id = ?
               AND (
                    section_key = ?
                    OR UPPER(display_name) = ?
               )
             LIMIT 1
            """,
            (scoped_recipe_user_id(scoped_user_id), section, section),
        ).fetchone()
        return clean_text(row["section_key"]) if row else ""
    if not recipe_master_db_path().is_file():
        return ""
    with existing_recipe_master_connection() as existing_connection:
        if existing_connection is None:
            return ""
        return ingredient_store_section_from_source(
            section,
            user_id=scoped_user_id,
            connection=existing_connection,
        )


def clean_ingredient_store_section(value, default="MISC", user_id=None, connection=None):
    return ingredient_store_section_from_source(
        value,
        user_id=user_id,
        connection=connection,
    ) or default


def clean_ingredient_store_section_icon(value):
    icon = clean_text(value).lower()
    return icon if icon in INGREDIENT_STORE_SECTION_ICON_OPTIONS else "basket"


def create_ingredient_store_section(display_name, icon="basket", user_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    display_name = re.sub(r"\s+", " ", clean_text(display_name))[:80]
    section_key = normalize_ingredient_store_section_key(display_name)
    if not display_name or not section_key:
        return {"ok": False, "status": 400, "error": "Store Section name is required."}

    with recipe_master_connection() as connection:
        ensure_ingredient_store_sections_for_user(connection, scoped_user_id)
        duplicate = connection.execute(
            """
            SELECT id
              FROM ingredient_store_sections
             WHERE user_id = ?
               AND (
                    section_key = ?
                    OR LOWER(display_name) = LOWER(?)
               )
             LIMIT 1
            """,
            (scoped_user_id, section_key, display_name),
        ).fetchone()
        if duplicate:
            return {
                "ok": False,
                "status": 409,
                "error": "That Store Section already exists in this workspace.",
            }
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order
              FROM ingredient_store_sections
             WHERE user_id = ?
            """,
            (scoped_user_id,),
        ).fetchone()
        sort_order = int(row["max_sort_order"] or 0) + 1
        timestamp = utc_now_iso()
        cursor = connection.execute(
            """
            INSERT INTO ingredient_store_sections (
                user_id,
                section_key,
                display_name,
                icon,
                sort_order,
                is_builtin,
                is_active,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
            """,
            (
                scoped_user_id,
                section_key,
                display_name,
                clean_ingredient_store_section_icon(icon),
                sort_order,
                timestamp,
                timestamp,
            ),
        )
        return {
            "ok": True,
            "status": 201,
            "id": int(cursor.lastrowid),
            "section_key": section_key,
            "display_name": display_name,
        }


def update_ingredient_store_section_definition(
    section_id,
    *,
    action="save",
    display_name="",
    icon="basket",
    position=None,
    user_id=None,
):
    try:
        section_id = int(section_id or 0)
    except (TypeError, ValueError):
        section_id = 0
    if section_id <= 0:
        return {"ok": False, "status": 400, "error": "Store Section is required."}

    scoped_user_id = scoped_recipe_user_id(user_id)
    action = clean_text(action).lower() or "save"
    with recipe_master_connection() as connection:
        ensure_ingredient_store_sections_for_user(connection, scoped_user_id)
        row = connection.execute(
            """
            SELECT *
              FROM ingredient_store_sections
             WHERE id = ?
               AND user_id = ?
            """,
            (section_id, scoped_user_id),
        ).fetchone()
        if not row:
            return {"ok": False, "status": 404, "error": "Store Section was not found."}

        if action == "move_to":
            try:
                requested_position = int(position)
            except (TypeError, ValueError):
                return {
                    "ok": False,
                    "status": 400,
                    "error": "A valid Store Section position is required.",
                }
            ordered_rows = connection.execute(
                """
                SELECT id
                  FROM ingredient_store_sections
                 WHERE user_id = ?
                 ORDER BY sort_order ASC, id ASC
                """,
                (scoped_user_id,),
            ).fetchall()
            ordered_ids = [int(item["id"]) for item in ordered_rows]
            current_index = ordered_ids.index(section_id)
            target_index = max(0, min(len(ordered_ids) - 1, requested_position - 1))
            changed = current_index != target_index
            if changed:
                ordered_ids.pop(current_index)
                ordered_ids.insert(target_index, section_id)
                timestamp = utc_now_iso()
                connection.executemany(
                    """
                    UPDATE ingredient_store_sections
                       SET sort_order = ?,
                           updated_at = ?
                     WHERE id = ?
                       AND user_id = ?
                    """,
                    [
                        (index, timestamp, ordered_id, scoped_user_id)
                        for index, ordered_id in enumerate(ordered_ids, start=1)
                    ],
                )
            return {
                "ok": True,
                "status": 200,
                "changed": changed,
                "position": target_index + 1,
                "display_name": row["display_name"],
            }

        if action in {"move_up", "move_down"}:
            comparator = "<" if action == "move_up" else ">"
            direction = "DESC" if action == "move_up" else "ASC"
            adjacent = connection.execute(
                f"""
                SELECT id, sort_order
                  FROM ingredient_store_sections
                 WHERE user_id = ?
                   AND sort_order {comparator} ?
                 ORDER BY sort_order {direction}, id {direction}
                 LIMIT 1
                """,
                (scoped_user_id, int(row["sort_order"] or 0)),
            ).fetchone()
            if adjacent:
                connection.execute(
                    "UPDATE ingredient_store_sections SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (int(adjacent["sort_order"]), utc_now_iso(), section_id),
                )
                connection.execute(
                    "UPDATE ingredient_store_sections SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (int(row["sort_order"]), utc_now_iso(), int(adjacent["id"])),
                )
            return {
                "ok": True,
                "status": 200,
                "changed": bool(adjacent),
                "display_name": row["display_name"],
            }

        if action == "archive":
            if bool(row["is_builtin"]):
                return {
                    "ok": False,
                    "status": 409,
                    "error": "Built-in Store Sections cannot be archived.",
                }
            connection.execute(
                """
                UPDATE ingredient_store_sections
                   SET is_active = 0,
                       updated_at = ?
                 WHERE id = ?
                """,
                (utc_now_iso(), section_id),
            )
            return {
                "ok": True,
                "status": 200,
                "changed": bool(row["is_active"]),
                "display_name": row["display_name"],
            }

        if action == "delete":
            if bool(row["is_builtin"]):
                return {
                    "ok": False,
                    "status": 409,
                    "error": "Built-in Store Sections cannot be deleted.",
                }
            usage = connection.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                          FROM ingredients
                         WHERE user_id = ?
                           AND store_section = ?
                    ) AS ingredient_count,
                    (
                        SELECT COUNT(*)
                          FROM recipe_ingredients
                         WHERE user_id = ?
                           AND store_section = ?
                    ) AS recipe_reference_count
                """,
                (
                    scoped_user_id,
                    row["section_key"],
                    scoped_user_id,
                    row["section_key"],
                ),
            ).fetchone()
            ingredient_count = int(usage["ingredient_count"] or 0)
            recipe_reference_count = int(usage["recipe_reference_count"] or 0)
            if ingredient_count > 0 or recipe_reference_count > 0:
                return {
                    "ok": False,
                    "status": 409,
                    "error": (
                        "Reassign this Store Section's master ingredients and "
                        "recipe references before deleting it."
                    ),
                    "ingredient_count": ingredient_count,
                    "recipe_reference_count": recipe_reference_count,
                }
            connection.execute(
                """
                DELETE FROM ingredient_store_sections
                 WHERE id = ?
                   AND user_id = ?
                   AND is_builtin = 0
                """,
                (section_id, scoped_user_id),
            )
            remaining_rows = connection.execute(
                """
                SELECT id
                  FROM ingredient_store_sections
                 WHERE user_id = ?
                 ORDER BY sort_order ASC, id ASC
                """,
                (scoped_user_id,),
            ).fetchall()
            timestamp = utc_now_iso()
            connection.executemany(
                """
                UPDATE ingredient_store_sections
                   SET sort_order = ?,
                       updated_at = ?
                 WHERE id = ?
                   AND user_id = ?
                """,
                [
                    (index, timestamp, int(item["id"]), scoped_user_id)
                    for index, item in enumerate(remaining_rows, start=1)
                ],
            )
            return {
                "ok": True,
                "status": 200,
                "changed": True,
                "deleted": True,
                "display_name": row["display_name"],
            }

        if action == "restore":
            connection.execute(
                """
                UPDATE ingredient_store_sections
                   SET is_active = 1,
                       updated_at = ?
                 WHERE id = ?
                """,
                (utc_now_iso(), section_id),
            )
            return {
                "ok": True,
                "status": 200,
                "changed": not bool(row["is_active"]),
                "display_name": row["display_name"],
            }

        if action != "save":
            return {"ok": False, "status": 400, "error": "Unsupported Store Section action."}

        display_name = re.sub(r"\s+", " ", clean_text(display_name))[:80]
        if not display_name:
            return {"ok": False, "status": 400, "error": "Store Section name is required."}
        duplicate = connection.execute(
            """
            SELECT id
              FROM ingredient_store_sections
             WHERE user_id = ?
               AND LOWER(display_name) = LOWER(?)
               AND id != ?
             LIMIT 1
            """,
            (scoped_user_id, display_name, section_id),
        ).fetchone()
        if duplicate:
            return {
                "ok": False,
                "status": 409,
                "error": "That Store Section name already exists in this workspace.",
            }
        clean_icon = clean_ingredient_store_section_icon(icon)
        changed = (
            display_name != row["display_name"]
            or clean_icon != row["icon"]
        )
        connection.execute(
            """
            UPDATE ingredient_store_sections
               SET display_name = ?,
                   icon = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (display_name, clean_icon, utc_now_iso(), section_id),
        )
        return {
            "ok": True,
            "status": 200,
            "changed": changed,
            "display_name": display_name,
        }


def ingredient_store_section_sort_key(section):
    return INGREDIENT_STORE_SECTION_ORDER.get(
        clean_ingredient_store_section(section),
        INGREDIENT_STORE_SECTION_ORDER["MISC"],
    )


def ingredient_store_section_match_text(value):
    normalized = unicodedata.normalize("NFKD", clean_text(value).lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9&']+", " ", ascii_text).strip()


def clean_ingredient_store_section_source(value, default="fallback"):
    source = clean_text(value).lower().replace(" ", "_")
    return source if source in INGREDIENT_STORE_SECTION_SOURCES else default


def ingredient_store_section_confidence(value, default=0.0):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = float(default or 0.0)
    return max(0.0, min(1.0, confidence))


def normalize_ingredient_classification_context(value, preparation=""):
    item = value if isinstance(value, dict) else {}
    raw_name = clean_text(
        item.get("raw_name")
        or item.get("original_recipe_text")
        or item.get("original_text")
        or item.get("ingredient")
        or item.get("name")
        or value
    )
    preparation = clean_text(
        item.get("preparation")
        or item.get("notes")
        or preparation
    )
    supplied_normalized_name = clean_text(
        item.get("normalized_name")
        or item.get("parsed_name")
        or item.get("ingredient")
        or item.get("name")
    )
    normalized_name = ingredient_store_section_match_text(supplied_normalized_name or raw_name)
    normalized_name = re.sub(
        r"^(?:(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+)\s+)+",
        "",
        normalized_name,
    )
    normalized_name = re.sub(
        r"^(?:cups?|teaspoons?|tsp|tablespoons?|tbsp|pounds?|lbs?|ounces?|oz|grams?|g|kilograms?|kg|links?|cloves?|cans?|jars?|bottles?|packages?|bags?|stalks?|pieces?)\b\s*",
        "",
        normalized_name,
    )
    normalized_name = re.sub(r"^(?:small|medium|large)\b\s*", "", normalized_name).strip()

    canonical_ingredient = normalized_name
    form = ""
    alias_match = None
    for alias in sorted(INGREDIENT_CANONICAL_ALIASES, key=len, reverse=True):
        if normalized_name == alias or re.search(rf"\b{re.escape(alias)}\b", normalized_name):
            alias_match = alias
            canonical_ingredient, form = INGREDIENT_CANONICAL_ALIASES[alias]
            break

    combined_text = " ".join(part for part in (normalized_name, preparation.lower()) if part)
    if not form:
        for candidate in INGREDIENT_FORMS:
            if re.search(rf"\b{re.escape(candidate)}\b", combined_text):
                form = candidate
                break

    if not alias_match:
        canonical_ingredient = re.sub(
            rf"\b(?:{'|'.join(re.escape(candidate) for candidate in INGREDIENT_FORMS)})\b",
            " ",
            normalized_name,
        )
        canonical_ingredient = re.sub(r"\broot\b", " ", canonical_ingredient)
        canonical_ingredient = re.sub(r"\s+", " ", canonical_ingredient).strip() or normalized_name

    return {
        "raw_name": raw_name,
        "normalized_name": normalized_name,
        "canonical_ingredient": canonical_ingredient,
        "form": form,
        "preparation": preparation,
    }


def validated_ai_store_section_result(value):
    if isinstance(value, str):
        value = {"store_section": value}
    if not isinstance(value, dict):
        return None
    section = ingredient_store_section_from_source(value.get("store_section"))
    if not section:
        return None
    return {
        "store_section": section,
        "confidence": ingredient_store_section_confidence(value.get("confidence"), 0.5),
        "reason": clean_text(value.get("reason")) or "Validated AI store-section classification.",
        "normalized_name": ingredient_store_section_match_text(value.get("normalized_name")),
    }


def ingredient_store_section_form_rule(context):
    context = context if isinstance(context, dict) else {}
    normalized_name = context.get("normalized_name") or ""
    canonical = context.get("canonical_ingredient") or normalized_name
    form = context.get("form") or ""

    if form == "frozen":
        return "FROZEN", "form.frozen"
    if form == "canned":
        return "CANNED", "form.canned"

    if canonical in {"ginger", "garlic", "onion"}:
        if form in {"ground", "powdered", "dried"}:
            return "SPICES & SEASONINGS", f"{canonical}.dried_form"
        if form == "paste":
            return "SAUCES & CONDIMENTS", f"{canonical}.paste"
        if canonical == "ginger" and form == "crystallized":
            return "BAKING", "ginger.crystallized"
        return "PRODUCE", f"{canonical}.fresh_or_root"

    if canonical in {"cinnamon", "paprika", "cumin", "turmeric"}:
        if canonical == "turmeric" and form == "fresh":
            return "PRODUCE", "turmeric.fresh"
        return "SPICES & SEASONINGS", f"{canonical}.seasoning"

    if form in {"ground", "powdered", "dried"} and re.search(
        r"\b(?:basil|parsley|cilantro|oregano|thyme|rosemary|sage|spice|seasoning)\b",
        normalized_name,
    ):
        return "SPICES & SEASONINGS", "herb.dried_form"
    if form == "fresh" and re.search(
        r"\b(?:basil|parsley|cilantro|oregano|thyme|rosemary|sage)\b",
        normalized_name,
    ):
        return "PRODUCE", "herb.fresh"
    if form in {"paste", "bottled"} and re.search(
        r"\b(?:sauce|salsa|paste|pesto|ginger|garlic|pepper|tomato)\b",
        normalized_name,
    ):
        return "SAUCES & CONDIMENTS", f"form.{form}_condiment"
    return "", ""


def ingredient_store_section_keyword_rule(value):
    text = ingredient_store_section_match_text(value)
    if not text:
        return "", ""
    for rule_index, (patterns, section) in enumerate(INGREDIENT_STORE_SECTION_KEYWORD_RULES, start=1):
        for pattern in patterns:
            if re.search(pattern, text):
                return section, f"keyword.{rule_index}"
    return "", ""


def log_ingredient_store_section_result(result):
    if not isinstance(result, dict):
        return
    print(
        "[StoreSectionClassifier] "
        f"section=\"{recipe_master_log_value(result.get('store_section'))}\" "
        f"source={clean_ingredient_store_section_source(result.get('store_section_source'))} "
        f"confidence={ingredient_store_section_confidence(result.get('store_section_confidence')):.2f} "
        f"classifier_version={clean_text(result.get('classifier_version')) or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION} "
        f"rule=\"{recipe_master_log_value(result.get('store_section_rule'))}\" "
        f"normalized_name=\"{recipe_master_log_value(result.get('normalized_name'))}\""
    )


def classify_ingredient_store_section_result(
    value,
    *,
    recipe_override=None,
    recipe_override_confirmed=False,
    user_master_data=None,
    global_master_data=None,
    legacy_section=None,
    ai_result=None,
    default="MISC",
    log_result=True,
):
    context = normalize_ingredient_classification_context(value)

    def build_result(section, source, confidence, reason, rule=""):
        result = {
            **context,
            "store_section": clean_ingredient_store_section(section, default=default),
            "store_section_source": clean_ingredient_store_section_source(source),
            "store_section_confidence": ingredient_store_section_confidence(confidence),
            "store_section_user_confirmed": bool(
                source in {"recipe_override", "manual"} and recipe_override_confirmed
            ),
            "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": clean_text(reason),
            "store_section_rule": clean_text(rule),
        }
        if log_result:
            log_ingredient_store_section_result(result)
        return result

    override_section = ingredient_store_section_from_source(recipe_override)
    if override_section and recipe_override_confirmed:
        return build_result(
            override_section,
            "recipe_override",
            1.0,
            "User-confirmed section for this recipe ingredient.",
            "recipe.user_confirmed",
        )

    master = user_master_data if isinstance(user_master_data, dict) else {"store_section": user_master_data}
    master_section = ingredient_store_section_from_source(master.get("store_section"))
    if master_section:
        return build_result(
            master_section,
            "user_master_data",
            master.get("store_section_confidence", 1.0),
            master.get("store_section_reason") or "Matched user Ingredient Master Data.",
            master.get("store_section_rule") or "master.user_exact",
        )

    normalized_name = context["normalized_name"]
    legacy = ingredient_store_section_from_source(legacy_section)

    def preserve_nonconflicting_legacy(candidate_section):
        return bool(
            legacy
            and legacy != "MISC"
            and not ingredient_store_section_should_use_classification(
                normalized_name,
                legacy,
                candidate_section,
            )
        )

    global_mapping = global_master_data if isinstance(global_master_data, dict) else GLOBAL_INGREDIENT_STORE_SECTION_MAPPINGS
    global_section = ingredient_store_section_from_source(global_mapping.get(normalized_name))
    if global_section:
        return build_result(
            global_section,
            "global_master_data",
            1.0,
            "Matched the global normalized ingredient mapping.",
            f"global.{normalized_name.replace(' ', '_')}",
        )

    form_section, form_rule = ingredient_store_section_form_rule(context)
    if form_section:
        return build_result(
            form_section,
            "deterministic_rule",
            0.99,
            "Matched an ingredient-form-aware deterministic rule.",
            form_rule,
        )

    keyword_section, keyword_rule = ingredient_store_section_keyword_rule(
        " ".join(part for part in (normalized_name, context["preparation"]) if part)
    )
    if keyword_section:
        if preserve_nonconflicting_legacy(keyword_section):
            return build_result(
                legacy,
                "legacy",
                0.6,
                "Preserved a valid non-conflicting legacy store-section assignment.",
                "legacy.valid_section",
            )
        return build_result(
            keyword_section,
            "deterministic_rule",
            0.95,
            "Matched a deterministic ingredient keyword rule.",
            keyword_rule,
        )

    if legacy and legacy != "MISC":
        return build_result(
            legacy,
            "legacy",
            0.6,
            "Preserved a valid legacy store-section assignment.",
            "legacy.valid_section",
        )

    validated_ai = validated_ai_store_section_result(ai_result)
    if validated_ai and validated_ai["store_section"] != "MISC":
        return build_result(
            validated_ai["store_section"],
            "ai",
            validated_ai["confidence"],
            validated_ai["reason"],
            "ai.validated",
        )

    return build_result(
        default,
        "fallback",
        0.0,
        "No recipe override, master mapping, deterministic rule, or valid AI classification matched.",
        "fallback.misc",
    )


def equipment_section_options():
    return list(EQUIPMENT_SECTION_ORDER.keys())


def equipment_section_from_source(value):
    section = re.sub(r"\s+", " ", str(value or "").strip().upper())
    if not section:
        return ""
    section = EQUIPMENT_SECTION_ALIASES.get(section, section)
    return section if section in EQUIPMENT_SECTION_ORDER else ""


def clean_equipment_section(value, default="MISC"):
    return equipment_section_from_source(value) or default


def equipment_section_sort_key(section):
    return EQUIPMENT_SECTION_ORDER.get(
        clean_equipment_section(section),
        EQUIPMENT_SECTION_ORDER["MISC"],
    )


def equipment_section_match_text(value):
    return ingredient_store_section_match_text(value)


def classify_equipment_section(value):
    text = equipment_section_match_text(value)
    if not text:
        return ""

    for patterns, section in EQUIPMENT_SECTION_KEYWORD_RULES:
        if any(re.search(pattern, text) for pattern in patterns):
            return section

    return ""


def resolve_equipment_section(value, source_section=None, default="MISC"):
    section = clean_equipment_section(source_section, default="")
    classified = classify_equipment_section(value)
    if classified and (not section or section == "MISC"):
        return classified
    return section or classified or default


def classify_ingredient_store_section(value):
    result = classify_ingredient_store_section_result(
        value,
        default="",
        log_result=False,
    )
    return result.get("store_section") or ""


def ingredient_store_section_should_use_classification(value, current_section, classified_section):
    current_section = clean_ingredient_store_section(current_section, default="")
    classified_section = clean_ingredient_store_section(classified_section, default="")
    if not classified_section:
        return False
    if not current_section or current_section == "MISC":
        return True
    if current_section == classified_section:
        return True

    text = ingredient_store_section_match_text(value)
    for desired_section, conflicting_section, pattern in INGREDIENT_STORE_SECTION_CONFLICT_OVERRIDES:
        if (
            classified_section == desired_section
            and current_section == conflicting_section
            and re.search(pattern, text)
        ):
            return True

    return False


def resolve_ingredient_store_section(value, source_section=None, default="MISC"):
    section = clean_ingredient_store_section(source_section, default="")
    classified = classify_ingredient_store_section(value)
    if ingredient_store_section_should_use_classification(value, section, classified):
        section = classified
    result = classify_ingredient_store_section_result(
        value,
        legacy_section=section or source_section,
        default=default,
    )
    return result.get("store_section") or default


def normalize_existing_ingredient_store_sections(connection):
    try:
        rows = connection.execute(
            "SELECT id, user_id, store_section FROM ingredients"
        ).fetchall()
    except sqlite3.OperationalError:
        return

    for row in rows:
        raw_section = str(row["store_section"] or "")
        section = clean_ingredient_store_section(
            raw_section,
            user_id=row["user_id"],
            connection=connection,
        )
        if section != raw_section:
            connection.execute(
                "UPDATE ingredients SET store_section = ? WHERE id = ?",
                (section, int(row["id"])),
            )


def normalize_existing_equipment_sections(connection):
    try:
        rows = connection.execute(
            "SELECT id, name, normalized_name, equipment_section FROM equipment"
        ).fetchall()
    except sqlite3.OperationalError:
        return

    for row in rows:
        raw_section = str(row["equipment_section"] or "")
        section = resolve_equipment_section(
            " ".join(
                part
                for part in (row["name"], row["normalized_name"])
                if part
            ),
            raw_section,
        )
        if section != raw_section:
            connection.execute(
                "UPDATE equipment SET equipment_section = ? WHERE id = ?",
                (section, int(row["id"])),
            )


def master_record_table_config(table_name):
    table_name = str(table_name or "").strip()
    config = MASTER_RECORD_TABLES.get(table_name)
    if not config:
        raise ValueError("Unsupported master table.")
    return config


def bounded_master_limit(value, default=100, maximum=500):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, maximum))


def bounded_master_offset(value):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        offset = 0
    return max(0, offset)


def master_record_filters(
    table_name,
    user_id=None,
    search=None,
    include_all_users=False,
    store_section=None,
    equipment_section=None,
):
    where = []
    params = []

    user_id = clean_text(user_id)
    if include_all_users:
        if user_id:
            where.append("m.user_id = ?")
            params.append(user_id)
    else:
        where.append("m.user_id = ?")
        params.append(scoped_recipe_user_id(user_id))

    search = clean_text(search)
    if search:
        search_like = f"%{search.lower()}%"
        if table_name == "ingredients":
            where.append(
                """
                (
                    LOWER(m.name) LIKE ?
                    OR LOWER(m.normalized_name) LIKE ?
                    OR EXISTS (
                        SELECT 1
                          FROM ingredient_aliases a
                         WHERE a.user_id = m.user_id
                           AND a.ingredient_id = m.id
                           AND (
                               LOWER(a.alias_name) LIKE ?
                               OR LOWER(a.normalized_alias) LIKE ?
                           )
                    )
                )
                """
            )
            params.extend([search_like, search_like, search_like, search_like])
        else:
            where.append("(LOWER(m.name) LIKE ? OR LOWER(m.normalized_name) LIKE ?)")
            params.extend([search_like, search_like])

    if table_name == "ingredients":
        section = ingredient_store_section_from_source(
            store_section,
            user_id=user_id,
        )
        if section:
            where.append("m.store_section = ?")
            params.append(section)
    elif table_name == "equipment":
        section = equipment_section_from_source(equipment_section)
        if section:
            where.append("m.equipment_section = ?")
            params.append(section)

    return where, params


def list_master_records(
    table_name,
    user_id=None,
    search=None,
    limit=100,
    offset=0,
    sort="updated_at_desc",
    include_all_users=False,
    store_section=None,
    equipment_section=None,
):
    config = master_record_table_config(table_name)
    limit = bounded_master_limit(limit)
    offset = bounded_master_offset(offset)
    order_clause = MASTER_RECORD_SORTS.get(sort, MASTER_RECORD_SORTS["updated_at_desc"])
    where, params = master_record_filters(
        table_name,
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
        store_section=store_section,
        equipment_section=equipment_section,
    )
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    usage_table = config["usage_table"]
    usage_fk = config["usage_fk"]
    if table_name == "ingredients":
        section_select = ",\n                m.store_section"
        alias_select = """,
                COALESCE((
                    SELECT GROUP_CONCAT(alias_rows.alias_name, CHAR(31))
                      FROM (
                          SELECT a.alias_name
                            FROM ingredient_aliases a
                           WHERE a.user_id = m.user_id
                             AND a.ingredient_id = m.id
                           ORDER BY a.normalized_alias ASC
                       ) alias_rows
                ), '') AS aliases_serialized"""
        usage_select = """,
                COUNT(DISTINCT u.recipe_id) AS ingredient_name_usage_count,
                (
                    SELECT COUNT(DISTINCT buy_usage.recipe_id)
                      FROM recipe_ingredients buy_usage
                     WHERE buy_usage.user_id = m.user_id
                       AND (
                            LOWER(TRIM(buy_usage.buy_as)) = LOWER(TRIM(m.normalized_name))
                            OR EXISTS (
                                SELECT 1
                                  FROM ingredient_aliases buy_alias
                                 WHERE buy_alias.user_id = m.user_id
                                   AND buy_alias.ingredient_id = m.id
                                   AND buy_alias.normalized_alias = LOWER(TRIM(buy_usage.buy_as))
                            )
                       )
                ) AS buy_as_usage_count,
                (
                    SELECT COUNT(*)
                      FROM (
                            SELECT name_usage.recipe_id
                              FROM recipe_ingredients name_usage
                             WHERE name_usage.user_id = m.user_id
                               AND name_usage.ingredient_id = m.id
                            UNION
                            SELECT total_buy_usage.recipe_id
                              FROM recipe_ingredients total_buy_usage
                             WHERE total_buy_usage.user_id = m.user_id
                               AND (
                                    LOWER(TRIM(total_buy_usage.buy_as)) = LOWER(TRIM(m.normalized_name))
                                    OR EXISTS (
                                        SELECT 1
                                          FROM ingredient_aliases total_buy_alias
                                         WHERE total_buy_alias.user_id = m.user_id
                                           AND total_buy_alias.ingredient_id = m.id
                                           AND total_buy_alias.normalized_alias = LOWER(TRIM(total_buy_usage.buy_as))
                                    )
                               )
                      ) unique_usage_recipes
                ) AS usage_count"""
    elif table_name == "equipment":
        section_select = ",\n                m.equipment_section"
        alias_select = ""
        usage_select = ",\n                COUNT(u.id) AS usage_count"
    else:
        section_select = ""
        alias_select = ""
        usage_select = ",\n                COUNT(u.id) AS usage_count"

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return []

        rows = connection.execute(
            f"""
            SELECT
                m.id,
                m.user_id,
                m.name,
                m.normalized_name{section_select},
                m.image_url,
                m.image_path,
                m.created_at,
                m.updated_at{alias_select}{usage_select}
              FROM {table_name} m
              LEFT JOIN {usage_table} u
                ON u.{usage_fk} = m.id
               AND u.user_id = m.user_id
              {where_clause}
             GROUP BY m.id
             ORDER BY {order_clause}
             LIMIT ?
            OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

    results = []
    for row in rows:
        row_data = dict(row)
        if table_name == "ingredients":
            row_data["store_section"] = clean_ingredient_store_section(row_data.get("store_section"))
            row_data["store_section_order"] = ingredient_store_section_sort_key(row_data["store_section"])
            aliases_serialized = clean_text(row_data.pop("aliases_serialized", ""))
            row_data["aliases"] = [
                clean_text(alias)
                for alias in aliases_serialized.split(chr(31))
                if clean_text(alias)
            ]
            row_data["ingredient_name_usage_count"] = int(
                row["ingredient_name_usage_count"] or 0
            )
            row_data["buy_as_usage_count"] = int(row["buy_as_usage_count"] or 0)
        elif table_name == "equipment":
            row_data["equipment_section"] = clean_equipment_section(row_data.get("equipment_section"))
            row_data["equipment_section_order"] = equipment_section_sort_key(row_data["equipment_section"])
        row_data["usage_count"] = int(row["usage_count"] or 0)
        results.append(row_data)
    return results


def count_master_records(
    table_name,
    user_id=None,
    search=None,
    include_all_users=False,
    store_section=None,
    equipment_section=None,
):
    master_record_table_config(table_name)
    where, params = master_record_filters(
        table_name,
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
        store_section=store_section,
        equipment_section=equipment_section,
    )
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return 0

        row = connection.execute(
            f"""
            SELECT COUNT(*) AS record_count
              FROM {table_name} m
              {where_clause}
            """,
            params,
        ).fetchone()

    return int(row["record_count"] or 0) if row else 0


def list_ingredients(
    user_id=None,
    search=None,
    limit=100,
    offset=0,
    sort="updated_at_desc",
    include_all_users=False,
    store_section=None,
    equipment_section=None,
):
    return list_master_records(
        "ingredients",
        user_id=user_id,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        include_all_users=include_all_users,
        store_section=store_section,
    )


def list_equipment(
    user_id=None,
    search=None,
    limit=100,
    offset=0,
    sort="updated_at_desc",
    include_all_users=False,
    store_section=None,
    equipment_section=None,
):
    return list_master_records(
        "equipment",
        user_id=user_id,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        include_all_users=include_all_users,
        equipment_section=equipment_section or store_section,
    )


def count_ingredients(user_id=None, search=None, include_all_users=False, store_section=None, equipment_section=None):
    return count_master_records(
        "ingredients",
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
        store_section=store_section,
    )


def count_equipment(user_id=None, search=None, include_all_users=False, store_section=None, equipment_section=None):
    return count_master_records(
        "equipment",
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
        equipment_section=equipment_section or store_section,
    )


def count_master_usage(table_name, record_id, user_id=None):
    config = master_record_table_config(table_name)
    try:
        record_id = int(record_id or 0)
    except (TypeError, ValueError):
        record_id = 0
    if record_id <= 0:
        return 0

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return 0

        row = connection.execute(
            f"""
            SELECT COUNT(*) AS usage_count
              FROM {config["usage_table"]}
             WHERE user_id = ?
               AND {config["usage_fk"]} = ?
            """,
            (scoped_recipe_user_id(user_id), record_id),
        ).fetchone()

    return int(row["usage_count"] or 0) if row else 0


def count_ingredient_usage(record_id, user_id=None):
    return count_master_usage("ingredients", record_id, user_id=user_id)


def count_equipment_usage(record_id, user_id=None):
    return count_master_usage("equipment", record_id, user_id=user_id)


def master_record_for_id(table_name, record_id, user_id=None, include_all_users=False):
    if table_name not in {"ingredients", "equipment"}:
        raise ValueError("Unsupported master table.")
    try:
        record_id = int(record_id or 0)
    except (TypeError, ValueError):
        record_id = 0
    if record_id <= 0:
        return None

    where = ["id = ?"]
    params = [record_id]
    user_id = clean_text(user_id)
    if include_all_users:
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
    else:
        where.append("user_id = ?")
        params.append(scoped_recipe_user_id(user_id))

    if table_name == "ingredients":
        section_select = ", store_section"
    elif table_name == "equipment":
        section_select = ", equipment_section"
    else:
        section_select = ""
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return None

        row = connection.execute(
            f"""
            SELECT
                id,
                user_id,
                name,
                normalized_name{section_select},
                image_url,
                image_path,
                created_at,
                updated_at
              FROM {table_name}
             WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchone()

    if not row:
        return None

    row_data = dict(row)
    if table_name == "ingredients":
        row_data["store_section"] = clean_ingredient_store_section(row_data.get("store_section"))
    elif table_name == "equipment":
        row_data["equipment_section"] = clean_equipment_section(row_data.get("equipment_section"))
    return row_data


def recipe_reference_metadata_path(user_id):
    user_id = clean_text(user_id)
    if user_id == LOCAL_USER_ID:
        return storage_service.LEGACY_EXTRACTOR_DIR / "data" / "recipe_ingredients.json"
    if user_id.startswith("guest:"):
        guest_id = storage_service.safe_user_id(user_id.split(":", 1)[1])
        return storage_service.GUEST_DATA_DIR / guest_id / "recipe-extractor" / "data" / "recipe_ingredients.json"
    safe_user_id = storage_service.safe_user_id(user_id)
    return storage_service.USER_DATA_DIR / safe_user_id / "recipe-extractor" / "data" / "recipe_ingredients.json"


def recipe_reference_metadata(user_id):
    data = load_json_file(recipe_reference_metadata_path(user_id))
    return data if isinstance(data, dict) else {}


def recipe_reference_title(recipe_id, metadata_record=None):
    metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
    for field in ("name", "recipe_title", "display_name", "title"):
        title = clean_text(metadata_record.get(field))
        if title:
            return title

    recipe_url = clean_text(metadata_record.get("url")) or clean_text(recipe_id)
    return recipe_url_name(recipe_url) if recipe_url else "Recipe"


def list_master_record_recipe_references(
    table_name,
    record_id,
    user_id=None,
    include_all_users=False,
    limit=25,
):
    config = master_record_table_config(table_name)
    record = master_record_for_id(
        table_name,
        record_id,
        user_id=user_id,
        include_all_users=include_all_users,
    )
    if not record:
        return {
            "record": None,
            "references": [],
            "total": 0,
            "total_reference_count": 0,
            "ingredient_name_recipe_count": 0,
            "buy_as_recipe_count": 0,
        }

    limit = bounded_master_limit(limit, default=25, maximum=500)
    usage_table = config["usage_table"]
    usage_fk = config["usage_fk"]
    if table_name == "ingredients":
        detail_columns = """
                r.ingredient_id,
                source_ingredient.name AS ingredient_name,
                r.quantity,
                r.unit,
                r.unit_id,
                r.unit_raw,
                r.size,
                r.preparation,
                r.notes,
                r.unit_review_required,
                r.unit_review_value,
                r.unit_custom,
                r.buy_as,
                r.store_section,
                r.original_recipe_text,
                r.optional,
                r.sort_order
        """
    else:
        detail_columns = """
                0 AS ingredient_id,
                '' AS ingredient_name,
                '' AS quantity,
                '' AS unit,
                '' AS unit_id,
                '' AS unit_raw,
                '' AS size,
                '' AS preparation,
                '' AS notes,
                0 AS unit_review_required,
                '' AS unit_review_value,
                0 AS unit_custom,
                '' AS buy_as,
                '' AS store_section,
                r.original_recipe_text,
                r.optional,
                r.sort_order
        """

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {
                "record": record,
                "references": [],
                "total": 0,
                "total_reference_count": 0,
                "ingredient_name_recipe_count": 0,
                "buy_as_recipe_count": 0,
            }

        if table_name == "ingredients":
            alias_rows = connection.execute(
                """
                SELECT normalized_alias
                  FROM ingredient_aliases
                 WHERE user_id = ?
                   AND ingredient_id = ?
                """,
                (record["user_id"], int(record["id"])),
            ).fetchall()
            target_names = sorted({
                normalized_master_name(record.get("normalized_name") or record.get("name")),
                *(
                    normalized_master_name(alias_row["normalized_alias"])
                    for alias_row in alias_rows
                ),
            } - {""})
            buy_as_placeholders = ", ".join("?" for _ in target_names)
            buy_as_match_sql = f"LOWER(TRIM(r.buy_as)) IN ({buy_as_placeholders})"
            summary_row = connection.execute(
                f"""
                SELECT
                    COUNT(DISTINCT CASE
                        WHEN r.ingredient_id = ? THEN r.recipe_id
                    END) AS ingredient_name_recipe_count,
                    COUNT(DISTINCT CASE
                        WHEN {buy_as_match_sql} THEN r.recipe_id
                    END) AS buy_as_recipe_count,
                    COUNT(DISTINCT r.recipe_id) AS total_recipe_count,
                    COUNT(*) AS reference_count
                  FROM recipe_ingredients r
                 WHERE r.user_id = ?
                   AND (
                        r.ingredient_id = ?
                        OR {buy_as_match_sql}
                   )
                """,
                (
                    int(record["id"]),
                    *target_names,
                    record["user_id"],
                    int(record["id"]),
                    *target_names,
                ),
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT
                    r.id,
                    r.user_id,
                    r.recipe_id,
                    {detail_columns}
                  FROM recipe_ingredients r
                  LEFT JOIN ingredients source_ingredient
                    ON source_ingredient.id = r.ingredient_id
                   AND source_ingredient.user_id = r.user_id
                 WHERE r.user_id = ?
                   AND (
                        r.ingredient_id = ?
                        OR {buy_as_match_sql}
                   )
                 ORDER BY LOWER(r.recipe_id) ASC, r.sort_order ASC, r.id ASC
                 LIMIT ?
                """,
                (
                    record["user_id"],
                    int(record["id"]),
                    *target_names,
                    limit,
                ),
            ).fetchall()
        else:
            target_names = []
            summary_row = connection.execute(
                f"""
                SELECT
                    COUNT(DISTINCT r.recipe_id) AS total_recipe_count,
                    COUNT(*) AS reference_count
                  FROM {usage_table} r
                 WHERE r.user_id = ?
                   AND r.{usage_fk} = ?
                """,
                (record["user_id"], int(record["id"])),
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT
                    r.id,
                    r.user_id,
                    r.recipe_id,
                    {detail_columns}
                  FROM {usage_table} r
                 WHERE r.user_id = ?
                   AND r.{usage_fk} = ?
                 ORDER BY LOWER(r.recipe_id) ASC, r.sort_order ASC, r.id ASC
                 LIMIT ?
                """,
                (record["user_id"], int(record["id"]), limit),
            ).fetchall()

    metadata = recipe_reference_metadata(record["user_id"])
    references = []
    for row in rows:
        row_data = dict(row)
        recipe_id = clean_text(row_data.get("recipe_id"))
        metadata_record = metadata.get(recipe_id)
        metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
        recipe_url = clean_text(metadata_record.get("url")) or recipe_id
        ingredient_name = clean_text(row_data.get("ingredient_name"))
        buy_as = clean_text(row_data.get("buy_as"))
        cover_image = metadata_record.get("cover_image")
        references.append({
            "id": int(row_data.get("id") or 0),
            "user_id": clean_text(row_data.get("user_id")),
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "recipe_title": recipe_reference_title(recipe_id, metadata_record),
            "cover_image": dict(cover_image) if isinstance(cover_image, dict) else {},
            "ingredient_name": ingredient_name,
            "matches_ingredient_name": bool(
                table_name == "ingredients"
                and int(row_data.get("ingredient_id") or 0) == int(record["id"])
            ),
            "matches_buy_as": bool(
                table_name == "ingredients"
                and normalized_master_name(buy_as) in target_names
            ),
            "quantity": clean_text(row_data.get("quantity")),
            "unit": clean_text(row_data.get("unit")),
            "unit_id": clean_text(row_data.get("unit_id")),
            "unit_raw": clean_text(row_data.get("unit_raw")),
            "size": clean_text(row_data.get("size")),
            "preparation": clean_text(row_data.get("preparation")),
            "notes": clean_text(row_data.get("notes")),
            "unit_review_required": bool(row_data.get("unit_review_required")),
            "unit_review_value": clean_text(row_data.get("unit_review_value")),
            "unit_custom": bool(row_data.get("unit_custom")),
            "buy_as": buy_as,
            "store_section": clean_ingredient_store_section(row_data.get("store_section"), default="")
            if table_name == "ingredients"
            else "",
            "original_recipe_text": clean_text(row_data.get("original_recipe_text")),
            "optional": bool(row_data.get("optional")),
            "sort_order": int(row_data.get("sort_order") or 0),
        })

    return {
        "record": record,
        "references": references,
        "total": int(summary_row["total_recipe_count"] or 0) if summary_row else 0,
        "total_reference_count": int(summary_row["reference_count"] or 0)
        if summary_row
        else 0,
        "ingredient_name_recipe_count": int(summary_row["ingredient_name_recipe_count"] or 0)
        if table_name == "ingredients" and summary_row
        else 0,
        "buy_as_recipe_count": int(summary_row["buy_as_recipe_count"] or 0)
        if table_name == "ingredients" and summary_row
        else 0,
        "limit": limit,
    }


def update_ingredient_store_section(ingredient_id, store_section, user_id=None, allow_other_users=False):
    try:
        ingredient_id = int(ingredient_id or 0)
    except (TypeError, ValueError):
        ingredient_id = 0
    if ingredient_id <= 0:
        return {"ok": False, "error": "Ingredient record is required."}

    section = clean_ingredient_store_section(store_section)
    scoped_user_id = scoped_recipe_user_id(user_id)

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "error": "Recipe master database was not found."}

        params = [ingredient_id]
        user_clause = ""
        if not allow_other_users:
            user_clause = "AND user_id = ?"
            params.append(scoped_user_id)

        row = connection.execute(
            f"""
            SELECT id, user_id, normalized_name, store_section,
                   store_section_source, store_section_user_confirmed
              FROM ingredients
             WHERE id = ?
               {user_clause}
            """,
            params,
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Ingredient record was not found."}

        previous_section = clean_ingredient_store_section(row["store_section"])
        changed = previous_section != section
        should_confirm = (
            not truthy(row["store_section_user_confirmed"])
            or clean_ingredient_store_section_source(row["store_section_source"], default="legacy") != "manual"
        )
        if changed or should_confirm:
            connection.execute(
                """
                UPDATE ingredients
                   SET store_section = ?,
                       store_section_source = 'manual',
                       store_section_confidence = 1,
                       store_section_user_confirmed = 1,
                       classifier_version = ?,
                       store_section_reason = 'User confirmed this Ingredient Master Data section.',
                       store_section_rule = 'manual.master_data',
                       updated_at = ?
                 WHERE id = ?
                   AND user_id = ?
                """,
                (
                    section,
                    INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    utc_now_iso(),
                    int(row["id"]),
                    row["user_id"],
                ),
            )

        return {
            "ok": True,
            "changed": changed,
            "ingredient_id": int(row["id"]),
            "user_id": row["user_id"],
            "normalized_name": row["normalized_name"],
            "store_section": section,
            "previous_store_section": previous_section,
        }


def review_misc_ingredient_store_sections(user_id=None, apply=False):
    scoped_user_id = scoped_recipe_user_id(user_id)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "error": "Recipe master database was not found."}

        rows = connection.execute(
            """
            SELECT *
              FROM ingredients
             WHERE user_id = ?
               AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
               AND COALESCE(store_section_user_confirmed, 0) = 0
             ORDER BY normalized_name ASC, id ASC
            """,
            (scoped_user_id,),
        ).fetchall()
        changes = []
        for row in rows:
            row_data = dict(row)
            result = classify_ingredient_store_section_result(
                {
                    "raw_name": row_data.get("name"),
                    "normalized_name": row_data.get("normalized_name"),
                    "canonical_ingredient": row_data.get("canonical_ingredient"),
                    "form": row_data.get("form"),
                },
                default="MISC",
            )
            if result["store_section"] == "MISC":
                continue
            change = {
                "ingredient_id": int(row_data["id"]),
                "ingredient": clean_text(row_data.get("name")),
                "normalized_name": clean_text(result.get("normalized_name")),
                "image_url": clean_text(row_data.get("image_url")),
                "current_store_section": "MISC",
                "proposed_store_section": result["store_section"],
                "store_section_source": result["store_section_source"],
                "store_section_confidence": result["store_section_confidence"],
                "classifier_version": result["classifier_version"],
                "reason": result["store_section_reason"],
                "rule": result["store_section_rule"],
            }
            changes.append(change)
            if not apply:
                continue
            connection.execute(
                """
                UPDATE ingredients
                   SET canonical_ingredient = ?,
                       form = ?,
                       store_section = ?,
                       store_section_source = ?,
                       store_section_confidence = ?,
                       classifier_version = ?,
                       store_section_reason = ?,
                       store_section_rule = ?,
                       updated_at = ?
                 WHERE id = ?
                   AND user_id = ?
                   AND COALESCE(store_section_user_confirmed, 0) = 0
                   AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
                """,
                (
                    result["canonical_ingredient"],
                    result["form"],
                    result["store_section"],
                    result["store_section_source"],
                    result["store_section_confidence"],
                    result["classifier_version"],
                    result["store_section_reason"],
                    result["store_section_rule"],
                    utc_now_iso(),
                    int(row_data["id"]),
                    scoped_user_id,
                ),
            )
            connection.execute(
                """
                UPDATE recipe_ingredients
                   SET store_section = ?,
                       store_section_source = ?,
                       store_section_confidence = ?,
                       classifier_version = ?,
                       store_section_reason = ?,
                       store_section_rule = ?
                 WHERE ingredient_id = ?
                   AND user_id = ?
                   AND COALESCE(store_section_user_confirmed, 0) = 0
                   AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
                """,
                (
                    result["store_section"],
                    result["store_section_source"],
                    result["store_section_confidence"],
                    result["classifier_version"],
                    result["store_section_reason"],
                    result["store_section_rule"],
                    int(row_data["id"]),
                    scoped_user_id,
                ),
            )

    return {
        "ok": True,
        "applied": bool(apply),
        "user_id": scoped_user_id,
        "reviewed_count": len(rows),
        "changed_count": len(changes),
        "unresolved_count": max(0, len(rows) - len(changes)),
        "changes": changes,
    }


INGREDIENT_STORE_SECTION_HISTORY_FIELDS = (
    "id",
    "user_id",
    "canonical_ingredient",
    "form",
    "store_section",
    "store_section_source",
    "store_section_confidence",
    "store_section_user_confirmed",
    "classifier_version",
    "store_section_reason",
    "store_section_rule",
    "updated_at",
)
RECIPE_INGREDIENT_STORE_SECTION_HISTORY_FIELDS = (
    "id",
    "user_id",
    "ingredient_id",
    "store_section",
    "store_section_source",
    "store_section_confidence",
    "store_section_user_confirmed",
    "classifier_version",
    "store_section_reason",
    "store_section_rule",
)


def store_section_history_snapshot(row, fields):
    row_data = dict(row) if row is not None else {}
    return {field: row_data.get(field) for field in fields}


def ingredient_store_section_reclassification_history_summary(row):
    if not row:
        return None
    return {
        "batch_id": int(row["id"]),
        "user_id": clean_text(row["user_id"]),
        "change_count": int(row["change_count"] or 0),
        "applied_at": clean_text(row["applied_at"]),
    }


def latest_undoable_ingredient_store_section_reclassification(user_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT id, user_id, change_count, applied_at
              FROM ingredient_store_section_reclassification_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (scoped_user_id,),
        ).fetchone()
    return ingredient_store_section_reclassification_history_summary(row)


def misc_ingredient_store_section_review_candidates(
    user_id=None,
    scope="all",
    ingredient_ids=None,
    limit=100,
):
    scoped_user_id = scoped_recipe_user_id(user_id)
    scope = clean_text(scope).lower()
    if scope not in {"all", "suggested", "unresolved"}:
        scope = "all"
    try:
        limit = max(1, min(100, int(limit or 100)))
    except (TypeError, ValueError):
        limit = 100
    selected_ids = set()
    id_filter_requested = bool(ingredient_ids)
    for value in ingredient_ids or []:
        try:
            ingredient_id = int(value or 0)
        except (TypeError, ValueError):
            ingredient_id = 0
        if ingredient_id > 0:
            selected_ids.add(ingredient_id)

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "error": "Recipe master database was not found."}
        params = [scoped_user_id]
        id_clause = ""
        if id_filter_requested and not selected_ids:
            return {
                "ok": True,
                "user_id": scoped_user_id,
                "scope": scope,
                "candidate_count": 0,
                "candidates": [],
            }
        if selected_ids:
            placeholders = ", ".join("?" for _value in selected_ids)
            id_clause = f"AND id IN ({placeholders})"
            params.extend(sorted(selected_ids))
        rows = connection.execute(
            f"""
            SELECT *
              FROM ingredients
             WHERE user_id = ?
               AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
               AND COALESCE(store_section_user_confirmed, 0) = 0
               {id_clause}
             ORDER BY normalized_name ASC, id ASC
            """,
            params,
        ).fetchall()

        candidates = []
        for row in rows:
            row_data = dict(row)
            result = classify_ingredient_store_section_result(
                {
                    "raw_name": row_data.get("name"),
                    "normalized_name": row_data.get("normalized_name"),
                    "canonical_ingredient": row_data.get("canonical_ingredient"),
                    "form": row_data.get("form"),
                },
                default="MISC",
                log_result=False,
            )
            has_suggestion = result["store_section"] != "MISC"
            if scope == "suggested" and not has_suggestion:
                continue
            if scope == "unresolved" and has_suggestion:
                continue
            candidates.append({
                "ingredient_id": int(row_data["id"]),
                "ingredient": clean_text(row_data.get("name")),
                "normalized_name": clean_text(result.get("normalized_name")),
                "image_url": clean_text(row_data.get("image_url")),
                "canonical_ingredient": clean_text(result.get("canonical_ingredient")),
                "form": clean_text(result.get("form")),
                "current_store_section": "MISC",
                "deterministic": (
                    {
                        "store_section": result["store_section"],
                        "confidence": result["store_section_confidence"],
                        "reason": result["store_section_reason"],
                        "rule": result["store_section_rule"],
                        "source": result["store_section_source"],
                    }
                    if has_suggestion
                    else None
                ),
                "recipe_context": [],
            })
            if len(candidates) >= limit:
                break

        candidate_by_id = {
            candidate["ingredient_id"]: candidate
            for candidate in candidates
        }
        if candidate_by_id:
            placeholders = ", ".join("?" for _value in candidate_by_id)
            context_rows = connection.execute(
                f"""
                SELECT ingredient_id, recipe_id, original_recipe_text,
                       preparation, notes
                  FROM recipe_ingredients
                 WHERE user_id = ?
                   AND ingredient_id IN ({placeholders})
                 ORDER BY ingredient_id ASC, sort_order ASC, id ASC
                """,
                (scoped_user_id, *candidate_by_id.keys()),
            ).fetchall()
            for context_row in context_rows:
                ingredient_id = int(context_row["ingredient_id"])
                recipe_context = candidate_by_id[ingredient_id]["recipe_context"]
                if len(recipe_context) >= 3:
                    continue
                recipe_context.append({
                    "recipe_id": clean_text(context_row["recipe_id"]),
                    "source_text": clean_text(context_row["original_recipe_text"]),
                    "preparation": clean_text(context_row["preparation"]),
                    "notes": clean_text(context_row["notes"]),
                })

    return {
        "ok": True,
        "user_id": scoped_user_id,
        "scope": scope,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def apply_misc_ingredient_store_section_decisions(user_id=None, decisions=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    normalized_decisions = []
    seen_ids = set()
    for decision in decisions or []:
        if not isinstance(decision, dict):
            continue
        try:
            ingredient_id = int(decision.get("ingredient_id") or 0)
        except (TypeError, ValueError):
            ingredient_id = 0
        section = ingredient_store_section_from_source(decision.get("store_section"))
        if ingredient_id <= 0 or ingredient_id in seen_ids or not section:
            continue
        seen_ids.add(ingredient_id)
        normalized_decisions.append({
            "ingredient_id": ingredient_id,
            "store_section": section,
            "decision_source": clean_text(decision.get("decision_source")).lower(),
            "confidence": ingredient_store_section_confidence(decision.get("confidence")),
            "reason": clean_text(decision.get("reason")),
        })
    if not normalized_decisions:
        return {"ok": False, "status": 400, "error": "Choose at least one store-section decision."}

    changed = []
    kept_misc = 0
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "Recipe master database was not found."}
        prepared_decisions = []
        for decision in normalized_decisions:
            row = connection.execute(
                """
                SELECT *
                  FROM ingredients
                 WHERE id = ?
                   AND user_id = ?
                   AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
                   AND COALESCE(store_section_user_confirmed, 0) = 0
                 LIMIT 1
                """,
                (decision["ingredient_id"], scoped_user_id),
            ).fetchone()
            if not row:
                continue

            row_data = dict(row)
            deterministic = classify_ingredient_store_section_result(
                {
                    "raw_name": row_data.get("name"),
                    "normalized_name": row_data.get("normalized_name"),
                    "canonical_ingredient": row_data.get("canonical_ingredient"),
                    "form": row_data.get("form"),
                },
                default="MISC",
                log_result=False,
            )
            decision_source = decision["decision_source"]
            if decision["store_section"] == "MISC":
                metadata = {
                    **normalize_ingredient_classification_context({
                        "raw_name": row_data.get("name"),
                        "normalized_name": row_data.get("normalized_name"),
                        "canonical_ingredient": row_data.get("canonical_ingredient"),
                        "form": row_data.get("form"),
                    }),
                    "store_section": "MISC",
                    "store_section_source": "manual",
                    "store_section_confidence": decision["confidence"],
                    "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    "store_section_reason": decision["reason"] or "User confirmed that this ingredient should remain in Misc.",
                    "store_section_rule": "manual.keep_misc",
                }
                user_confirmed = True
                kept_misc += 1
            elif decision_source == "deterministic":
                if deterministic["store_section"] != decision["store_section"]:
                    return {
                        "ok": False,
                        "status": 409,
                        "error": f"The rule-based recommendation for {clean_text(row_data.get('name'))} changed. Preview again.",
                    }
                metadata = deterministic
                user_confirmed = False
            else:
                chose_ai_opinion = decision_source == "ai"
                metadata = {
                    **normalize_ingredient_classification_context({
                        "raw_name": row_data.get("name"),
                        "normalized_name": row_data.get("normalized_name"),
                        "canonical_ingredient": row_data.get("canonical_ingredient"),
                        "form": row_data.get("form"),
                    }),
                    "store_section": decision["store_section"],
                    "store_section_source": "manual",
                    "store_section_confidence": decision["confidence"],
                    "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    "store_section_reason": decision["reason"] or (
                        "User selected an AI second opinion during store-section maintenance."
                        if chose_ai_opinion
                        else "User selected the final store section during store-section maintenance."
                    ),
                    "store_section_rule": (
                        "manual.ai_second_opinion"
                        if chose_ai_opinion
                        else "manual.store_section_choice"
                    ),
                }
                user_confirmed = True

            recipe_rows_before = connection.execute(
                """
                SELECT id, user_id, ingredient_id, store_section,
                       store_section_source, store_section_confidence,
                       store_section_user_confirmed, classifier_version,
                       store_section_reason, store_section_rule
                  FROM recipe_ingredients
                 WHERE ingredient_id = ?
                   AND user_id = ?
                   AND COALESCE(store_section_user_confirmed, 0) = 0
                   AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
                 ORDER BY id ASC
                """,
                (decision["ingredient_id"], scoped_user_id),
            ).fetchall()
            prepared_decisions.append({
                "decision": decision,
                "row_data": row_data,
                "metadata": metadata,
                "user_confirmed": user_confirmed,
                "ingredient_before": store_section_history_snapshot(
                    row,
                    INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
                ),
                "recipe_ingredients_before": [
                    store_section_history_snapshot(
                        recipe_row,
                        RECIPE_INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
                    )
                    for recipe_row in recipe_rows_before
                ],
            })

        # Validate the entire batch before writing so a stale rule-based choice
        # cannot leave earlier decisions partially applied.
        history_changes = []
        for prepared in prepared_decisions:
            decision = prepared["decision"]
            row_data = prepared["row_data"]
            metadata = prepared["metadata"]
            user_confirmed = prepared["user_confirmed"]
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE ingredients
                   SET canonical_ingredient = ?, form = ?, store_section = ?,
                       store_section_source = ?, store_section_confidence = ?,
                       store_section_user_confirmed = ?, classifier_version = ?,
                       store_section_reason = ?, store_section_rule = ?, updated_at = ?
                 WHERE id = ? AND user_id = ?
                """,
                (
                    clean_text(metadata.get("canonical_ingredient")),
                    clean_text(metadata.get("form")),
                    decision["store_section"],
                    clean_ingredient_store_section_source(metadata.get("store_section_source")),
                    ingredient_store_section_confidence(metadata.get("store_section_confidence")),
                    1 if user_confirmed else 0,
                    clean_text(metadata.get("classifier_version")) or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    clean_text(metadata.get("store_section_reason")),
                    clean_text(metadata.get("store_section_rule")),
                    now,
                    decision["ingredient_id"],
                    scoped_user_id,
                ),
            )
            connection.execute(
                """
                UPDATE recipe_ingredients
                   SET store_section = ?, store_section_source = ?,
                       store_section_confidence = ?, store_section_user_confirmed = ?,
                       classifier_version = ?, store_section_reason = ?, store_section_rule = ?
                 WHERE ingredient_id = ?
                   AND user_id = ?
                   AND COALESCE(store_section_user_confirmed, 0) = 0
                   AND COALESCE(NULLIF(TRIM(store_section), ''), 'MISC') = 'MISC'
                """,
                (
                    decision["store_section"],
                    clean_ingredient_store_section_source(metadata.get("store_section_source")),
                    ingredient_store_section_confidence(metadata.get("store_section_confidence")),
                    1 if user_confirmed else 0,
                    clean_text(metadata.get("classifier_version")) or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    clean_text(metadata.get("store_section_reason")),
                    clean_text(metadata.get("store_section_rule")),
                    decision["ingredient_id"],
                    scoped_user_id,
                ),
            )
            ingredient_after = connection.execute(
                """
                SELECT id, user_id, canonical_ingredient, form, store_section,
                       store_section_source, store_section_confidence,
                       store_section_user_confirmed, classifier_version,
                       store_section_reason, store_section_rule, updated_at
                  FROM ingredients
                 WHERE id = ? AND user_id = ?
                """,
                (decision["ingredient_id"], scoped_user_id),
            ).fetchone()
            recipe_ids = [
                int(recipe_row["id"])
                for recipe_row in prepared["recipe_ingredients_before"]
            ]
            recipe_rows_after = []
            if recipe_ids:
                placeholders = ", ".join("?" for _value in recipe_ids)
                recipe_rows_after = connection.execute(
                    f"""
                    SELECT id, user_id, ingredient_id, store_section,
                           store_section_source, store_section_confidence,
                           store_section_user_confirmed, classifier_version,
                           store_section_reason, store_section_rule
                      FROM recipe_ingredients
                     WHERE user_id = ? AND id IN ({placeholders})
                     ORDER BY id ASC
                    """,
                    (scoped_user_id, *recipe_ids),
                ).fetchall()
            history_changes.append({
                "ingredient_name": clean_text(row_data.get("name")),
                "ingredient_before": prepared["ingredient_before"],
                "ingredient_after": store_section_history_snapshot(
                    ingredient_after,
                    INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
                ),
                "recipe_ingredients_before": prepared["recipe_ingredients_before"],
                "recipe_ingredients_after": [
                    store_section_history_snapshot(
                        recipe_row,
                        RECIPE_INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
                    )
                    for recipe_row in recipe_rows_after
                ],
            })
            log_ingredient_store_section_result({
                **metadata,
                "store_section": decision["store_section"],
                "store_section_user_confirmed": user_confirmed,
            })
            changed.append({
                "ingredient_id": decision["ingredient_id"],
                "ingredient": clean_text(row_data.get("name")),
                "store_section": decision["store_section"],
                "decision_source": decision["decision_source"] or "manual",
            })

        batch_id = 0
        applied_at = ""
        if history_changes:
            applied_at = utc_now_iso()
            history_cursor = connection.execute(
                """
                INSERT INTO ingredient_store_section_reclassification_history (
                    user_id, snapshot_json, change_count, applied_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    scoped_user_id,
                    json.dumps(
                        {"version": 1, "changes": history_changes},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    len(history_changes),
                    applied_at,
                ),
            )
            batch_id = int(history_cursor.lastrowid)

    return {
        "ok": True,
        "applied": True,
        "user_id": scoped_user_id,
        "changed_count": len(changed),
        "kept_misc_count": kept_misc,
        "changes": changed,
        "batch_id": batch_id,
        "applied_at": applied_at,
        "undo_available": batch_id > 0,
    }


def undo_last_ingredient_store_section_reclassification(
    user_id=None,
    expected_batch_id=None,
    expected_ingredient_id=None,
    preview_only=False,
):
    scoped_user_id = scoped_recipe_user_id(user_id)
    try:
        expected_batch_id = int(expected_batch_id or 0)
    except (TypeError, ValueError):
        expected_batch_id = 0
    try:
        expected_ingredient_id = int(expected_ingredient_id or 0)
    except (TypeError, ValueError):
        expected_ingredient_id = 0

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {
                "ok": False,
                "status": 404,
                "error": "No store-section reclassification is available to undo.",
            }
        history = connection.execute(
            """
            SELECT id, user_id, snapshot_json, change_count, applied_at
              FROM ingredient_store_section_reclassification_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (scoped_user_id,),
        ).fetchone()
        if not history:
            return {
                "ok": False,
                "status": 404,
                "error": "No store-section reclassification is available to undo.",
            }
        if expected_batch_id > 0 and expected_batch_id != int(history["id"]):
            return {
                "ok": False,
                "status": 409,
                "error": "A newer reclassification was applied. Refresh before undoing.",
            }
        try:
            snapshot = json.loads(history["snapshot_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            snapshot = None
        changes = snapshot.get("changes") if isinstance(snapshot, dict) else None
        if not isinstance(changes, list) or not changes:
            return {
                "ok": False,
                "status": 409,
                "error": "This reclassification cannot be undone because its restore data is unavailable.",
            }

        changes_to_restore = changes
        remaining_changes = []
        if expected_ingredient_id > 0:
            changes_to_restore = [
                change
                for change in changes
                if isinstance(change, dict)
                and int((change.get("ingredient_after") or {}).get("id") or 0)
                == expected_ingredient_id
            ]
            if not changes_to_restore:
                return {
                    "ok": False,
                    "status": 404,
                    "error": "That store-section decision is no longer available in the undo history.",
                }
            remaining_changes = [
                change
                for change in changes
                if change not in changes_to_restore
            ]

        validated_changes = []
        for change in changes_to_restore:
            change = change if isinstance(change, dict) else {}
            ingredient_before = change.get("ingredient_before")
            ingredient_after = change.get("ingredient_after")
            recipe_before = change.get("recipe_ingredients_before")
            recipe_after = change.get("recipe_ingredients_after")
            if not (
                isinstance(ingredient_before, dict)
                and isinstance(ingredient_after, dict)
                and isinstance(recipe_before, list)
                and isinstance(recipe_after, list)
            ):
                return {
                    "ok": False,
                    "status": 409,
                    "error": "This reclassification cannot be undone because its restore data is incomplete.",
                }
            ingredient_id = int(ingredient_after.get("id") or 0)
            ingredient_name = clean_text(change.get("ingredient_name")) or "An ingredient"
            if (
                ingredient_id <= 0
                or int(ingredient_before.get("id") or 0) != ingredient_id
                or clean_text(ingredient_before.get("user_id")) != scoped_user_id
                or clean_text(ingredient_after.get("user_id")) != scoped_user_id
            ):
                return {
                    "ok": False,
                    "status": 409,
                    "error": "This reclassification does not match the current workspace.",
                }
            current_ingredient = connection.execute(
                """
                SELECT id, user_id, canonical_ingredient, form, store_section,
                       store_section_source, store_section_confidence,
                       store_section_user_confirmed, classifier_version,
                       store_section_reason, store_section_rule, updated_at
                  FROM ingredients
                 WHERE id = ? AND user_id = ?
                """,
                (ingredient_id, scoped_user_id),
            ).fetchone()
            current_ingredient = store_section_history_snapshot(
                current_ingredient,
                INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
            )
            if current_ingredient != ingredient_after:
                return {
                    "ok": False,
                    "status": 409,
                    "error": f"{ingredient_name} changed after this reclassification, so it cannot be safely undone.",
                }

            recipe_before_by_id = {
                int(row.get("id") or 0): row
                for row in recipe_before
                if isinstance(row, dict) and int(row.get("id") or 0) > 0
            }
            recipe_after_by_id = {
                int(row.get("id") or 0): row
                for row in recipe_after
                if isinstance(row, dict) and int(row.get("id") or 0) > 0
            }
            if set(recipe_before_by_id) != set(recipe_after_by_id):
                return {
                    "ok": False,
                    "status": 409,
                    "error": "This reclassification cannot be undone because its recipe restore data is incomplete.",
                }
            current_recipe_by_id = {}
            if recipe_after_by_id:
                recipe_ids = sorted(recipe_after_by_id)
                placeholders = ", ".join("?" for _value in recipe_ids)
                current_recipe_rows = connection.execute(
                    f"""
                    SELECT id, user_id, ingredient_id, store_section,
                           store_section_source, store_section_confidence,
                           store_section_user_confirmed, classifier_version,
                           store_section_reason, store_section_rule
                      FROM recipe_ingredients
                     WHERE user_id = ? AND id IN ({placeholders})
                    """,
                    (scoped_user_id, *recipe_ids),
                ).fetchall()
                current_recipe_by_id = {
                    int(row["id"]): store_section_history_snapshot(
                        row,
                        RECIPE_INGREDIENT_STORE_SECTION_HISTORY_FIELDS,
                    )
                    for row in current_recipe_rows
                }
            if current_recipe_by_id != recipe_after_by_id:
                return {
                    "ok": False,
                    "status": 409,
                    "error": f"A recipe using {ingredient_name} changed after this reclassification, so it cannot be safely undone.",
                }
            validated_changes.append({
                "ingredient_before": ingredient_before,
                "recipe_before_by_id": recipe_before_by_id,
            })

        if preview_only:
            return {
                "ok": True,
                "preview": True,
                "batch_id": int(history["id"]),
                "user_id": scoped_user_id,
                "ingredient_id": expected_ingredient_id,
                "change_count": len(validated_changes),
                "remaining_change_count": len(remaining_changes),
                "recipe_reference_count": sum(
                    len(change["recipe_before_by_id"])
                    for change in validated_changes
                ),
            }

        restored_recipe_count = 0
        for change in validated_changes:
            ingredient = change["ingredient_before"]
            connection.execute(
                """
                UPDATE ingredients
                   SET canonical_ingredient = ?, form = ?, store_section = ?,
                       store_section_source = ?, store_section_confidence = ?,
                       store_section_user_confirmed = ?, classifier_version = ?,
                       store_section_reason = ?, store_section_rule = ?, updated_at = ?
                 WHERE id = ? AND user_id = ?
                """,
                (
                    ingredient.get("canonical_ingredient"),
                    ingredient.get("form"),
                    ingredient.get("store_section"),
                    ingredient.get("store_section_source"),
                    ingredient.get("store_section_confidence"),
                    ingredient.get("store_section_user_confirmed"),
                    ingredient.get("classifier_version"),
                    ingredient.get("store_section_reason"),
                    ingredient.get("store_section_rule"),
                    ingredient.get("updated_at"),
                    ingredient.get("id"),
                    scoped_user_id,
                ),
            )
            for recipe in change["recipe_before_by_id"].values():
                cursor = connection.execute(
                    """
                    UPDATE recipe_ingredients
                       SET store_section = ?, store_section_source = ?,
                           store_section_confidence = ?, store_section_user_confirmed = ?,
                           classifier_version = ?, store_section_reason = ?,
                           store_section_rule = ?
                     WHERE id = ? AND user_id = ? AND ingredient_id = ?
                    """,
                    (
                        recipe.get("store_section"),
                        recipe.get("store_section_source"),
                        recipe.get("store_section_confidence"),
                        recipe.get("store_section_user_confirmed"),
                        recipe.get("classifier_version"),
                        recipe.get("store_section_reason"),
                        recipe.get("store_section_rule"),
                        recipe.get("id"),
                        scoped_user_id,
                        recipe.get("ingredient_id"),
                    ),
                )
                restored_recipe_count += max(0, int(cursor.rowcount or 0))

        undone_at = ""
        if remaining_changes:
            connection.execute(
                """
                UPDATE ingredient_store_section_reclassification_history
                   SET snapshot_json = ?, change_count = ?
                 WHERE id = ? AND user_id = ? AND undone_at IS NULL
                """,
                (
                    json.dumps(
                        {"version": 1, "changes": remaining_changes},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    len(remaining_changes),
                    int(history["id"]),
                    scoped_user_id,
                ),
            )
        else:
            undone_at = utc_now_iso()
            connection.execute(
                """
                UPDATE ingredient_store_section_reclassification_history
                   SET undone_at = ?
                 WHERE id = ? AND user_id = ? AND undone_at IS NULL
                """,
                (undone_at, int(history["id"]), scoped_user_id),
            )
        next_history = connection.execute(
            """
            SELECT id, user_id, change_count, applied_at
              FROM ingredient_store_section_reclassification_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (scoped_user_id,),
        ).fetchone()

        return {
            "ok": True,
            "changed": True,
            "batch_id": int(history["id"]),
            "user_id": scoped_user_id,
            "ingredient_id": expected_ingredient_id,
            "restored_ingredient_count": len(validated_changes),
            "restored_recipe_count": restored_recipe_count,
            "remaining_change_count": len(remaining_changes),
            "undone_at": undone_at,
            "next_batch": ingredient_store_section_reclassification_history_summary(next_history),
        }


def ingredient_store_section_reclassification_undo_preview(
    user_id=None,
    batch_id=None,
    ingredient_id=None,
):
    scoped_user_id = scoped_recipe_user_id(user_id)
    try:
        batch_id = int(batch_id or 0)
    except (TypeError, ValueError):
        batch_id = 0
    try:
        ingredient_id = int(ingredient_id or 0)
    except (TypeError, ValueError):
        ingredient_id = 0

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {
                "ok": False,
                "status": 404,
                "error": "No store-section reclassification is available to undo.",
            }
        history_rows = connection.execute(
            """
            SELECT id, user_id, snapshot_json, change_count, applied_at
              FROM ingredient_store_section_reclassification_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
            """,
            (scoped_user_id,),
        ).fetchall()
        if not history_rows:
            return {
                "ok": False,
                "status": 404,
                "error": "No store-section reclassification is available to undo.",
            }
        selected_history = next(
            (row for row in history_rows if int(row["id"]) == batch_id),
            history_rows[0] if batch_id <= 0 else None,
        )
        if selected_history is None:
            return {
                "ok": False,
                "status": 404,
                "error": "That store-section apply is no longer available in the undo history.",
            }
        selected_index = next(
            index
            for index, row in enumerate(history_rows)
            if int(row["id"]) == int(selected_history["id"])
        )

        parsed_snapshots = {}
        for row in history_rows:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            parsed_snapshots[int(row["id"])] = snapshot if isinstance(snapshot, dict) else {}

        selected_snapshot = parsed_snapshots.get(int(selected_history["id"]), {})
        selected_changes = selected_snapshot.get("changes")
        if not isinstance(selected_changes, list) or not selected_changes:
            return {
                "ok": False,
                "status": 409,
                "error": "This store-section apply cannot be previewed because its restore data is unavailable.",
            }
        if ingredient_id > 0:
            selected_changes = [
                change
                for change in selected_changes
                if isinstance(change, dict)
                and int((change.get("ingredient_after") or {}).get("id") or 0)
                == ingredient_id
            ]
            if not selected_changes:
                return {
                    "ok": False,
                    "status": 404,
                    "error": "That store-section decision is no longer available in the undo history.",
                }
        else:
            first_change = next(
                (
                    change
                    for change in selected_changes
                    if isinstance(change, dict)
                    and int((change.get("ingredient_after") or {}).get("id") or 0) > 0
                ),
                None,
            )
            selected_changes = [first_change] if first_change else []
            ingredient_id = int(
                ((first_change or {}).get("ingredient_after") or {}).get("id") or 0
            )
            if not selected_changes or ingredient_id <= 0:
                return {
                    "ok": False,
                    "status": 409,
                    "error": "This store-section apply cannot be previewed because its restore data is incomplete.",
                }

        selected_recipe_row_ids = sorted({
            int(recipe_row.get("id") or 0)
            for change in selected_changes
            if isinstance(change, dict)
            for recipe_row in (change.get("recipe_ingredients_after") or [])
            if isinstance(recipe_row, dict)
            and str(recipe_row.get("id") or "").isdigit()
            and int(recipe_row.get("id") or 0) > 0
        })
        ingredient_ids = sorted({
            int((change.get("ingredient_after") or {}).get("id") or 0)
            for change in selected_changes
            if isinstance(change, dict)
            and isinstance(change.get("ingredient_after"), dict)
            and int((change.get("ingredient_after") or {}).get("id") or 0) > 0
        })
        ingredient_images = {}
        if ingredient_ids:
            placeholders = ", ".join("?" for _value in ingredient_ids)
            image_rows = connection.execute(
                f"""
                SELECT id, name, image_url
                  FROM ingredients
                 WHERE user_id = ? AND id IN ({placeholders})
                """,
                (scoped_user_id, *ingredient_ids),
            ).fetchall()
            ingredient_images = {
                int(row["id"]): {
                    "name": clean_text(row["name"]),
                    "image_url": clean_text(row["image_url"]),
                }
                for row in image_rows
            }

        recipe_reference_rows = []
        if selected_recipe_row_ids:
            placeholders = ", ".join("?" for _value in selected_recipe_row_ids)
            recipe_reference_rows = connection.execute(
                f"""
                SELECT r.id, r.recipe_id, r.original_recipe_text,
                       r.quantity, r.unit, r.size, r.preparation,
                       i.name AS ingredient_name
                  FROM recipe_ingredients r
                  LEFT JOIN ingredients i
                    ON i.id = r.ingredient_id AND i.user_id = r.user_id
                 WHERE r.user_id = ? AND r.id IN ({placeholders})
                 ORDER BY LOWER(r.recipe_id) ASC, r.sort_order ASC, r.id ASC
                """,
                (scoped_user_id, *selected_recipe_row_ids),
            ).fetchall()

    latest_batch_id = int(history_rows[0]["id"])
    latest_batch_validation = undo_last_ingredient_store_section_reclassification(
        user_id=scoped_user_id,
        expected_batch_id=latest_batch_id,
        preview_only=True,
    )
    selected_validation = undo_last_ingredient_store_section_reclassification(
        user_id=scoped_user_id,
        expected_batch_id=int(selected_history["id"]),
        expected_ingredient_id=ingredient_id,
        preview_only=True,
    )
    recipe_metadata = recipe_reference_metadata(scoped_user_id)
    recipe_reference_groups = {}
    for row in recipe_reference_rows:
        row_data = dict(row)
        recipe_id = clean_text(row_data.get("recipe_id"))
        if not recipe_id:
            continue
        metadata_record = recipe_metadata.get(recipe_id)
        metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
        reference = recipe_reference_groups.setdefault(recipe_id, {
            "recipe_id": recipe_id,
            "recipe_url": clean_text(metadata_record.get("url")) or recipe_id,
            "recipe_title": recipe_reference_title(recipe_id, metadata_record),
            "ingredient_reference_count": 0,
            "ingredients": [],
        })
        reference["ingredient_reference_count"] += 1
        ingredient_name = clean_text(row_data.get("ingredient_name"))
        if ingredient_name and ingredient_name not in reference["ingredients"]:
            reference["ingredients"].append(ingredient_name)
    recipe_references = list(recipe_reference_groups.values())

    def snapshot_reference_count(snapshot):
        changes = snapshot.get("changes") if isinstance(snapshot, dict) else []
        if not isinstance(changes, list):
            return 0
        return sum(
            len(change.get("recipe_ingredients_after") or [])
            for change in changes
            if isinstance(change, dict)
            and isinstance(change.get("recipe_ingredients_after"), list)
        )

    undoable_batches = []
    for index, row in enumerate(history_rows):
        row_batch_id = int(row["id"])
        is_next = index == 0
        can_undo_now = is_next and bool(latest_batch_validation.get("ok"))
        undoable_batches.append({
            **ingredient_store_section_reclassification_history_summary(row),
            "undo_order": index + 1,
            "is_next_undo": is_next,
            "newer_undo_count": index,
            "older_undo_count": max(0, len(history_rows) - index - 1),
            "recipe_reference_count": snapshot_reference_count(
                parsed_snapshots.get(row_batch_id, {})
            ),
            "can_undo_now": can_undo_now,
            "blocked_reason": "" if can_undo_now else (
                clean_text(latest_batch_validation.get("error"))
                if is_next
                else f"Undo {index} newer store-section apply batch{'es' if index != 1 else ''} first."
            ),
        })

    history_items = []
    newer_item_count = 0
    for batch_index, row in enumerate(history_rows):
        row_batch_id = int(row["id"])
        row_changes = parsed_snapshots.get(row_batch_id, {}).get("changes")
        row_changes = row_changes if isinstance(row_changes, list) else []
        for change_index, change in enumerate(row_changes):
            change = change if isinstance(change, dict) else {}
            before = change.get("ingredient_before")
            after = change.get("ingredient_after")
            recipe_after = change.get("recipe_ingredients_after")
            if not isinstance(before, dict) or not isinstance(after, dict):
                continue
            row_ingredient_id = int(after.get("id") or 0)
            if row_ingredient_id <= 0:
                continue
            is_selected = (
                row_batch_id == int(selected_history["id"])
                and row_ingredient_id == ingredient_id
            )
            can_undo_now = batch_index == 0
            if is_selected:
                can_undo_now = bool(selected_validation.get("ok"))
            history_items.append({
                "history_item_id": f"{row_batch_id}:{row_ingredient_id}",
                "batch_id": row_batch_id,
                "ingredient_id": row_ingredient_id,
                "ingredient": clean_text(change.get("ingredient_name")) or "Ingredient",
                "applied_store_section": clean_ingredient_store_section(after.get("store_section"))
                or "MISC",
                "restored_store_section": clean_ingredient_store_section(before.get("store_section"))
                or "MISC",
                "recipe_reference_count": len(recipe_after)
                if isinstance(recipe_after, list)
                else 0,
                "applied_at": clean_text(row["applied_at"]),
                "batch_change_count": len(row_changes),
                "batch_item_order": change_index + 1,
                "newer_undo_count": newer_item_count + change_index,
                "can_undo_now": can_undo_now,
                "blocked_reason": "" if can_undo_now else (
                    clean_text(selected_validation.get("error"))
                    if is_selected and batch_index == 0
                    else f"Undo the {newer_item_count} newer store-section decision"
                    f"{'s' if newer_item_count != 1 else ''} first."
                ),
            })
        newer_item_count += len(row_changes)

    change_previews = []
    for change in selected_changes:
        change = change if isinstance(change, dict) else {}
        before = change.get("ingredient_before")
        after = change.get("ingredient_after")
        recipe_after = change.get("recipe_ingredients_after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        ingredient_id = int(after.get("id") or 0)
        image_record = ingredient_images.get(ingredient_id, {})
        change_previews.append({
            "ingredient_id": ingredient_id,
            "ingredient": clean_text(change.get("ingredient_name"))
            or clean_text(image_record.get("name"))
            or "Ingredient",
            "image_url": clean_text(image_record.get("image_url")),
            "applied_store_section": clean_ingredient_store_section(after.get("store_section")) or "MISC",
            "restored_store_section": clean_ingredient_store_section(before.get("store_section")) or "MISC",
            "applied_source": clean_ingredient_store_section_source(after.get("store_section_source")),
            "restored_source": clean_ingredient_store_section_source(before.get("store_section_source")),
            "recipe_reference_count": len(recipe_after) if isinstance(recipe_after, list) else 0,
        })

    newer_undo_count = selected_index
    selected_is_next = selected_index == 0
    selected_can_undo = selected_is_next and bool(selected_validation.get("ok"))
    selected_blocked_reason = "" if selected_can_undo else (
        clean_text(selected_validation.get("error"))
        if selected_is_next
        else f"Undo {selected_index} newer store-section apply batch{'es' if selected_index != 1 else ''} first."
    )
    selected_history_item = next(
        (
            item
            for item in history_items
            if int(item.get("batch_id") or 0) == int(selected_history["id"])
            and int(item.get("ingredient_id") or 0) == ingredient_id
        ),
        {},
    )
    return {
        "ok": True,
        **ingredient_store_section_reclassification_history_summary(selected_history),
        "ingredient_id": ingredient_id,
        "batch_change_count": int(selected_history["change_count"] or 0),
        "change_count": len(change_previews),
        "changes": change_previews,
        "recipe_reference_count": sum(
            int(change.get("recipe_reference_count") or 0)
            for change in change_previews
        ),
        "affected_recipe_count": len(recipe_references),
        "recipe_references": recipe_references,
        "newer_undo_count": newer_undo_count,
        "newer_undo_item_count": int(selected_history_item.get("newer_undo_count") or 0),
        "older_undo_count": max(0, len(history_rows) - selected_index - 1),
        "is_next_undo": selected_is_next,
        "can_undo_now": selected_can_undo,
        "blocked_reason": selected_blocked_reason,
        "undoable_batches": undoable_batches,
        "history_items": history_items,
        "other_undo_count": max(0, len(history_items) - 1),
    }


def update_ingredient_master_record(
    ingredient_id,
    name,
    normalized_name,
    store_section,
    user_id=None,
    allow_other_users=False,
):
    try:
        ingredient_id = int(ingredient_id or 0)
    except (TypeError, ValueError):
        ingredient_id = 0
    if ingredient_id <= 0:
        return {"ok": False, "status": 400, "error": "Ingredient record is required."}

    scoped_user_id = scoped_recipe_user_id(user_id)
    name = clean_text(name)[:160]
    normalized_name = normalized_master_name(normalized_name or name)[:160]
    section_input = store_section
    if not name:
        return {"ok": False, "status": 400, "error": "Ingredient name is required."}
    if not normalized_name:
        return {"ok": False, "status": 400, "error": "Normalized name is required."}

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "Recipe master database was not found."}

        params = [ingredient_id]
        user_clause = ""
        if not allow_other_users:
            user_clause = "AND user_id = ?"
            params.append(scoped_user_id)

        row = connection.execute(
            f"""
            SELECT id, user_id, name, normalized_name, store_section
              FROM ingredients
             WHERE id = ?
               {user_clause}
            """,
            params,
        ).fetchone()
        if not row:
            return {"ok": False, "status": 404, "error": "Ingredient record was not found."}
        section = clean_ingredient_store_section(
            section_input,
            user_id=row["user_id"],
            connection=connection,
        )

        duplicate = connection.execute(
            """
            SELECT id
              FROM ingredients
             WHERE user_id = ?
               AND normalized_name = ?
               AND id != ?
            """,
            (row["user_id"], normalized_name, int(row["id"])),
        ).fetchone()
        if duplicate:
            return {
                "ok": False,
                "status": 409,
                "error": "That normalized ingredient already exists in this workspace.",
            }

        alias_conflict = connection.execute(
            """
            SELECT ingredient_id
              FROM ingredient_aliases
             WHERE user_id = ?
               AND normalized_alias = ?
            """,
            (row["user_id"], normalized_name),
        ).fetchone()
        if alias_conflict and int(alias_conflict["ingredient_id"]) != int(row["id"]):
            return {
                "ok": False,
                "status": 409,
                "error": "That normalized ingredient is already an alias for another master ingredient.",
            }
        if alias_conflict:
            connection.execute(
                """
                DELETE FROM ingredient_aliases
                 WHERE user_id = ?
                   AND normalized_alias = ?
                   AND ingredient_id = ?
                """,
                (row["user_id"], normalized_name, int(row["id"])),
            )

        previous = {
            "name": clean_text(row["name"]),
            "normalized_name": normalized_master_name(row["normalized_name"]),
            "store_section": clean_ingredient_store_section(row["store_section"]),
        }
        changed = (
            previous["name"] != name
            or previous["normalized_name"] != normalized_name
            or previous["store_section"] != section
        )
        section_changed = previous["store_section"] != section
        if changed:
            connection.execute(
                """
                UPDATE ingredients
                   SET name = ?,
                       normalized_name = ?,
                       store_section = ?,
                       store_section_source = CASE WHEN ? THEN 'manual' ELSE store_section_source END,
                       store_section_confidence = CASE WHEN ? THEN 1 ELSE store_section_confidence END,
                       store_section_user_confirmed = CASE WHEN ? THEN 1 ELSE store_section_user_confirmed END,
                       classifier_version = CASE WHEN ? THEN ? ELSE classifier_version END,
                       store_section_reason = CASE WHEN ? THEN 'User confirmed this Ingredient Master Data section.' ELSE store_section_reason END,
                       store_section_rule = CASE WHEN ? THEN 'manual.master_data' ELSE store_section_rule END,
                       updated_at = ?
                 WHERE id = ?
                   AND user_id = ?
                """,
                (
                    name,
                    normalized_name,
                    section,
                    section_changed,
                    section_changed,
                    section_changed,
                    section_changed,
                    INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    section_changed,
                    section_changed,
                    utc_now_iso(),
                    int(row["id"]),
                    row["user_id"],
                ),
            )

        return {
            "ok": True,
            "changed": changed,
            "ingredient_id": int(row["id"]),
            "user_id": row["user_id"],
            "name": name,
            "normalized_name": normalized_name,
            "store_section": section,
            "previous": previous,
        }


def ingredient_merge_history_summary(row):
    if not row:
        return None
    return {
        "merge_id": int(row["id"]),
        "user_id": clean_text(row["user_id"]),
        "source_ingredient_id": int(row["source_ingredient_id"]),
        "source_name": clean_text(row["source_name"]),
        "target_ingredient_id": int(row["target_ingredient_id"]),
        "target_name": clean_text(row["target_name"]),
        "merged_at": clean_text(row["merged_at"]),
    }


INGREDIENT_MERGE_RESTORE_FIELDS = (
    "id",
    "user_id",
    "name",
    "normalized_name",
    "store_section",
    "image_url",
    "image_path",
    "created_at",
    "updated_at",
)
INGREDIENT_MERGE_ALIAS_FIELDS = (
    "id",
    "user_id",
    "ingredient_id",
    "alias_name",
    "normalized_alias",
    "created_at",
    "updated_at",
)


def normalized_ingredient_option_item_reference_ids(
    connection,
    user_id,
    ingredient_id,
):
    """Return normalized option-item references owned by one workspace."""
    rows = connection.execute(
        """
        SELECT item.id
          FROM recipe_ingredient_option_items item
          JOIN recipe_ingredient_options option
            ON option.id = item.option_id
          JOIN recipe_ingredient_requirements requirement
            ON requirement.id = option.requirement_id
         WHERE requirement.user_id = ?
           AND item.ingredient_id = ?
         ORDER BY item.id ASC
        """,
        (user_id, ingredient_id),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def validate_ingredient_merge_undo_candidate(connection, history, scoped_user_id):
    def failure(message):
        return {"ok": False, "status": 409, "error": message}

    if not history:
        return {"ok": False, "status": 404, "error": "No ingredient merge is available to undo."}
    try:
        snapshot = json.loads(history["snapshot_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return failure("This merge cannot be undone because its restore data is unavailable.")

    source = snapshot.get("source") if isinstance(snapshot, dict) else None
    target = snapshot.get("target") if isinstance(snapshot, dict) else None
    merged_target = snapshot.get("merged_target") if isinstance(snapshot, dict) else None
    aliases_before = snapshot.get("aliases_before") if isinstance(snapshot, dict) else None
    merged_aliases = snapshot.get("merged_aliases") if isinstance(snapshot, dict) else None
    if not all(isinstance(value, dict) for value in (source, target, merged_target)):
        return failure("This merge cannot be undone because its restore data is incomplete.")
    aliases_before = aliases_before if isinstance(aliases_before, list) else []
    merged_aliases = merged_aliases if isinstance(merged_aliases, list) else []
    source_id = int(history["source_ingredient_id"])
    target_id = int(history["target_ingredient_id"])
    if (
        int(source.get("id") or 0) != source_id
        or int(target.get("id") or 0) != target_id
        or clean_text(source.get("user_id")) != scoped_user_id
        or clean_text(target.get("user_id")) != scoped_user_id
    ):
        return failure("This merge cannot be undone because its restore data does not match the workspace.")

    current_target = connection.execute(
        """
        SELECT id, user_id, name, normalized_name, store_section,
               image_url, image_path, created_at, updated_at
          FROM ingredients
         WHERE id = ? AND user_id = ?
        """,
        (target_id, scoped_user_id),
    ).fetchone()
    current_target_data = dict(current_target) if current_target else {}
    if not current_target or any(
        current_target_data.get(field) != merged_target.get(field)
        for field in INGREDIENT_MERGE_RESTORE_FIELDS
    ):
        return failure("The surviving ingredient changed after this merge, so it cannot be safely restored.")

    current_aliases = connection.execute(
        """
        SELECT id, user_id, ingredient_id, alias_name, normalized_alias,
               created_at, updated_at
          FROM ingredient_aliases
         WHERE user_id = ? AND ingredient_id = ?
         ORDER BY normalized_alias ASC
        """,
        (scoped_user_id, target_id),
    ).fetchall()

    def alias_signatures(rows):
        return sorted(
            tuple(dict(row).get(field) for field in INGREDIENT_MERGE_ALIAS_FIELDS)
            for row in rows or []
        )

    if alias_signatures(current_aliases) != alias_signatures(merged_aliases):
        return failure("The surviving ingredient aliases changed after this merge, so it cannot be safely restored.")

    source_conflict = connection.execute(
        """
        SELECT id
          FROM ingredients
         WHERE id = ?
            OR (user_id = ? AND normalized_name = ?)
         LIMIT 1
        """,
        (source_id, scoped_user_id, normalized_master_name(source.get("normalized_name"))),
    ).fetchone()
    if source_conflict:
        return failure("The removed ingredient name is in use again, so this merge cannot be undone safely.")

    restored_alias_names = sorted({
        normalized_master_name(alias.get("normalized_alias"))
        for alias in aliases_before
        if isinstance(alias, dict) and normalized_master_name(alias.get("normalized_alias"))
    })
    if restored_alias_names:
        placeholders = ", ".join("?" for _value in restored_alias_names)
        alias_conflict = connection.execute(
            f"""
            SELECT normalized_alias
              FROM ingredient_aliases
             WHERE user_id = ?
               AND normalized_alias IN ({placeholders})
               AND ingredient_id != ?
             LIMIT 1
            """,
            (scoped_user_id, *restored_alias_names, target_id),
        ).fetchone()
        if alias_conflict:
            return failure(
                f"The alias {alias_conflict['normalized_alias']} is in use, so this merge cannot be undone safely."
            )

    moved_reference_ids = sorted({
        int(reference_id)
        for reference_id in snapshot.get("moved_reference_ids", [])
        if str(reference_id).isdigit() and int(reference_id) > 0
    })
    if moved_reference_ids:
        placeholders = ", ".join("?" for _value in moved_reference_ids)
        moved_reference_rows = connection.execute(
            f"""
            SELECT id, ingredient_id
              FROM recipe_ingredients
             WHERE user_id = ? AND id IN ({placeholders})
            """,
            (scoped_user_id, *moved_reference_ids),
        ).fetchall()
        if len(moved_reference_rows) != len(moved_reference_ids) or any(
            int(row["ingredient_id"]) != target_id for row in moved_reference_rows
        ):
            return failure("A moved recipe reference changed after this merge, so it cannot be safely restored.")

    moved_option_item_ids = sorted({
        int(reference_id)
        for reference_id in snapshot.get("moved_option_item_ids", [])
        if str(reference_id).isdigit() and int(reference_id) > 0
    })
    if moved_option_item_ids:
        placeholders = ", ".join("?" for _value in moved_option_item_ids)
        moved_option_item_rows = connection.execute(
            f"""
            SELECT item.id, item.ingredient_id
              FROM recipe_ingredient_option_items item
              JOIN recipe_ingredient_options option
                ON option.id = item.option_id
              JOIN recipe_ingredient_requirements requirement
                ON requirement.id = option.requirement_id
             WHERE requirement.user_id = ?
               AND item.id IN ({placeholders})
            """,
            (scoped_user_id, *moved_option_item_ids),
        ).fetchall()
        if len(moved_option_item_rows) != len(moved_option_item_ids) or any(
            int(row["ingredient_id"] or 0) != target_id
            for row in moved_option_item_rows
        ):
            return failure(
                "A moved normalized recipe option reference changed after this merge, "
                "so it cannot be safely restored."
            )

    return {
        "ok": True,
        "snapshot": snapshot,
        "source": source,
        "target": target,
        "merged_target": merged_target,
        "aliases_before": aliases_before,
        "merged_aliases": merged_aliases,
        "source_id": source_id,
        "target_id": target_id,
        "moved_reference_ids": moved_reference_ids,
        "moved_option_item_ids": moved_option_item_ids,
    }


def ingredient_merge_undo_stack_summary(row, index, total, validation=None):
    summary = ingredient_merge_history_summary(row)
    snapshot = {}
    try:
        snapshot = json.loads(row["snapshot_json"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    target = snapshot.get("target") if isinstance(snapshot.get("target"), dict) else {}
    moved_reference_ids = {
        int(reference_id)
        for reference_id in snapshot.get("moved_reference_ids", [])
        if str(reference_id).isdigit() and int(reference_id) > 0
    }
    moved_option_item_ids = {
        int(reference_id)
        for reference_id in snapshot.get("moved_option_item_ids", [])
        if str(reference_id).isdigit() and int(reference_id) > 0
    }
    summary.update({
        "undo_order": index + 1,
        "is_next_undo": index == 0,
        "newer_undo_count": index,
        "older_undo_count": max(0, total - index - 1),
        "restored_reference_count": len(moved_reference_ids),
        "normalized_restored_reference_count": len(moved_option_item_ids),
        "source_image_url": clean_text(source.get("image_url")),
        "target_image_url": clean_text(target.get("image_url")),
        "can_undo_now": bool(validation and validation.get("ok")),
        "blocked_reason": "" if validation and validation.get("ok") else clean_text(
            validation.get("error") if isinstance(validation, dict) else ""
        ),
    })
    return summary


def ingredient_merge_undo_preview(user_id=None, reference_limit=8, merge_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    reference_limit = bounded_master_limit(reference_limit, default=8, maximum=25)
    try:
        merge_id = int(merge_id or 0)
    except (TypeError, ValueError):
        merge_id = 0
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "No ingredient merge is available to undo."}
        history_rows = connection.execute(
            """
            SELECT id, user_id, source_ingredient_id, target_ingredient_id,
                   source_name, target_name, snapshot_json, merged_at
              FROM ingredient_merge_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
            """,
            (scoped_user_id,),
        ).fetchall()
        if not history_rows:
            return {"ok": False, "status": 404, "error": "No ingredient merge is available to undo."}
        history = next(
            (row for row in history_rows if int(row["id"]) == merge_id),
            history_rows[0] if merge_id <= 0 else None,
        )
        if history is None:
            return {
                "ok": False,
                "status": 404,
                "error": "That merge is no longer available in the undo history.",
            }
        selected_index = next(
            index for index, row in enumerate(history_rows) if int(row["id"]) == int(history["id"])
        )
        validations = {
            int(row["id"]): validate_ingredient_merge_undo_candidate(
                connection,
                row,
                scoped_user_id,
            )
            for row in history_rows
        }
        undoable_merges = [
            ingredient_merge_undo_stack_summary(
                row,
                index,
                len(history_rows),
                validations.get(int(row["id"])),
            )
            for index, row in enumerate(history_rows)
        ]
        selected_validation = validations.get(int(history["id"]), {})

        try:
            snapshot = json.loads(history["snapshot_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return {
                "ok": False,
                "status": 409,
                "error": "This merge cannot be previewed because its restore data is unavailable.",
            }

        source = snapshot.get("source") if isinstance(snapshot, dict) else None
        target = snapshot.get("target") if isinstance(snapshot, dict) else None
        merged_target = snapshot.get("merged_target") if isinstance(snapshot, dict) else None
        if not all(isinstance(value, dict) for value in (source, target, merged_target)):
            return {
                "ok": False,
                "status": 409,
                "error": "This merge cannot be previewed because its restore data is incomplete.",
            }

        moved_reference_ids = sorted({
            int(reference_id)
            for reference_id in snapshot.get("moved_reference_ids", [])
            if str(reference_id).isdigit() and int(reference_id) > 0
        })
        moved_option_item_ids = sorted({
            int(reference_id)
            for reference_id in snapshot.get("moved_option_item_ids", [])
            if str(reference_id).isdigit() and int(reference_id) > 0
        })
        reference_rows = []
        if moved_reference_ids:
            placeholders = ", ".join("?" for _value in moved_reference_ids)
            reference_rows = connection.execute(
                f"""
                SELECT id, recipe_id, quantity, unit, size, preparation,
                       original_recipe_text, sort_order
                  FROM recipe_ingredients
                 WHERE user_id = ? AND id IN ({placeholders})
                 ORDER BY LOWER(recipe_id) ASC, sort_order ASC, id ASC
                 LIMIT ?
                """,
                (scoped_user_id, *moved_reference_ids, reference_limit),
            ).fetchall()

        metadata = recipe_reference_metadata(scoped_user_id)
        references = []
        for row in reference_rows:
            row_data = dict(row)
            recipe_id = clean_text(row_data.get("recipe_id"))
            metadata_record = metadata.get(recipe_id)
            metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
            references.append({
                "id": int(row_data.get("id") or 0),
                "recipe_id": recipe_id,
                "recipe_title": recipe_reference_title(recipe_id, metadata_record),
                "original_recipe_text": clean_text(row_data.get("original_recipe_text")),
                "quantity": clean_text(row_data.get("quantity")),
                "unit": clean_text(row_data.get("unit")),
                "size": clean_text(row_data.get("size")),
                "preparation": clean_text(row_data.get("preparation")),
            })

        aliases_before = snapshot.get("aliases_before")
        aliases_before = aliases_before if isinstance(aliases_before, list) else []
        source_id = int(history["source_ingredient_id"])
        target_id = int(history["target_ingredient_id"])

        def ingredient_preview(record, ingredient_id):
            return {
                "ingredient_id": ingredient_id,
                "name": clean_text(record.get("name")),
                "normalized_name": clean_text(record.get("normalized_name")),
                "store_section": clean_ingredient_store_section(record.get("store_section")),
                "image_url": clean_text(record.get("image_url")),
                "aliases": sorted({
                    clean_text(alias.get("alias_name"))
                    for alias in aliases_before
                    if isinstance(alias, dict)
                    and int(alias.get("ingredient_id") or 0) == ingredient_id
                    and clean_text(alias.get("alias_name"))
                }),
            }

        field_labels = {
            "name": "Name",
            "normalized_name": "Normalized name",
            "store_section": "Store section",
            "image_url": "Image",
        }
        target_changes = []
        for field, label in field_labels.items():
            current_value = clean_text(merged_target.get(field))
            restored_value = clean_text(target.get(field))
            if current_value == restored_value:
                continue
            target_changes.append({
                "field": field,
                "label": label,
                "current": current_value,
                "restored": restored_value,
            })

        newer_undo_count = selected_index
        older_undo_count = max(0, len(history_rows) - selected_index - 1)

        return {
            "ok": True,
            **ingredient_merge_history_summary(history),
            "source_restore": ingredient_preview(source, source_id),
            "target_restore": ingredient_preview(target, target_id),
            "target_current": {
                "ingredient_id": target_id,
                "name": clean_text(merged_target.get("name")),
                "normalized_name": clean_text(merged_target.get("normalized_name")),
                "store_section": clean_ingredient_store_section(merged_target.get("store_section")),
                "image_url": clean_text(merged_target.get("image_url")),
            },
            "target_changes": target_changes,
            "restored_reference_count": len(moved_reference_ids),
            "normalized_restored_reference_count": len(moved_option_item_ids),
            "reference_previews": references,
            "reference_preview_truncated": len(moved_reference_ids) > len(references),
            "older_undo_count": older_undo_count,
            "has_older_merge": older_undo_count > 0,
            "newer_undo_count": newer_undo_count,
            "is_next_undo": newer_undo_count == 0,
            "can_undo_now": bool(selected_validation.get("ok")),
            "blocked_reason": "" if selected_validation.get("ok") else clean_text(
                selected_validation.get("error")
            ),
            "undoable_merges": undoable_merges,
        }


def latest_undoable_ingredient_merge(user_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT id, user_id, source_ingredient_id, target_ingredient_id,
                   source_name, target_name, merged_at
              FROM ingredient_merge_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (scoped_user_id,),
        ).fetchone()
    return ingredient_merge_history_summary(row)


def merge_ingredient_master_records(
    source_ingredient_id,
    target_ingredient_id,
    user_id=None,
    allow_other_users=False,
):
    try:
        source_ingredient_id = int(source_ingredient_id or 0)
        target_ingredient_id = int(target_ingredient_id or 0)
    except (TypeError, ValueError):
        source_ingredient_id = 0
        target_ingredient_id = 0

    if source_ingredient_id <= 0 or target_ingredient_id <= 0:
        return {"ok": False, "status": 400, "error": "Source and target ingredients are required."}
    if source_ingredient_id == target_ingredient_id:
        return {"ok": False, "status": 400, "error": "Choose a different canonical ingredient."}

    scoped_user_id = scoped_recipe_user_id(user_id)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "Recipe master database was not found."}

        rows = connection.execute(
            """
            SELECT id, user_id, name, normalized_name, store_section,
                   image_url, image_path, created_at, updated_at
              FROM ingredients
             WHERE id IN (?, ?)
            """,
            (source_ingredient_id, target_ingredient_id),
        ).fetchall()
        rows_by_id = {int(row["id"]): row for row in rows}
        source = rows_by_id.get(source_ingredient_id)
        target = rows_by_id.get(target_ingredient_id)
        if not source or not target:
            return {"ok": False, "status": 404, "error": "One of those ingredient records was not found."}
        if not allow_other_users and (
            source["user_id"] != scoped_user_id
            or target["user_id"] != scoped_user_id
        ):
            return {"ok": False, "status": 404, "error": "Ingredient record was not found."}
        if source["user_id"] != target["user_id"]:
            return {"ok": False, "status": 400, "error": "Ingredients can only be merged within the same workspace."}

        source_snapshot = dict(source)
        target_snapshot = dict(target)
        source_alias_rows = connection.execute(
            """
            SELECT id, user_id, ingredient_id, alias_name, normalized_alias,
                   created_at, updated_at
              FROM ingredient_aliases
             WHERE user_id = ?
               AND ingredient_id = ?
             ORDER BY normalized_alias ASC
            """,
            (source["user_id"], source_ingredient_id),
        ).fetchall()
        target_alias_rows = connection.execute(
            """
            SELECT id, user_id, ingredient_id, alias_name, normalized_alias,
                   created_at, updated_at
              FROM ingredient_aliases
             WHERE user_id = ?
               AND ingredient_id = ?
             ORDER BY normalized_alias ASC
            """,
            (source["user_id"], target_ingredient_id),
        ).fetchall()
        moved_reference_rows = connection.execute(
            """
            SELECT id
              FROM recipe_ingredients
             WHERE user_id = ? AND ingredient_id = ?
             ORDER BY id ASC
            """,
            (source["user_id"], source_ingredient_id),
        ).fetchall()
        moved_option_item_ids = normalized_ingredient_option_item_reference_ids(
            connection,
            source["user_id"],
            source_ingredient_id,
        )
        duplicate_review_rows = connection.execute(
            """
            SELECT id, status, classification, suggested_target_id, updated_at
              FROM ingredient_duplicate_reviews
             WHERE user_id = ?
               AND (left_ingredient_id = ? OR right_ingredient_id = ?)
             ORDER BY id ASC
            """,
            (source["user_id"], source_ingredient_id, source_ingredient_id),
        ).fetchall()
        aliases_before_merge = [
            dict(row)
            for row in (*source_alias_rows, *target_alias_rows)
        ]
        alias_candidates = {
            normalized_master_name(source["name"]): clean_text(source["name"]),
            normalized_master_name(source["normalized_name"]): clean_text(source["name"]),
        }
        for alias_row in source_alias_rows:
            normalized_alias = normalized_master_name(alias_row["normalized_alias"])
            if normalized_alias:
                alias_candidates[normalized_alias] = clean_text(alias_row["alias_name"]) or normalized_alias
        alias_candidates.pop(normalized_master_name(target["normalized_name"]), None)
        alias_candidates = {
            normalized_alias: alias_name
            for normalized_alias, alias_name in alias_candidates.items()
            if normalized_alias
        }

        if alias_candidates:
            placeholders = ", ".join("?" for _ in alias_candidates)
            alias_conflict = connection.execute(
                f"""
                SELECT normalized_alias
                  FROM ingredient_aliases
                 WHERE user_id = ?
                   AND normalized_alias IN ({placeholders})
                   AND ingredient_id NOT IN (?, ?)
                 LIMIT 1
                """,
                (
                    source["user_id"],
                    *alias_candidates.keys(),
                    source_ingredient_id,
                    target_ingredient_id,
                ),
            ).fetchone()
            if alias_conflict:
                return {
                    "ok": False,
                    "status": 409,
                    "error": f"The alias {alias_conflict['normalized_alias']} belongs to another ingredient.",
                }

        now = utc_now_iso()
        target_section = clean_ingredient_store_section(target["store_section"])
        source_section = clean_ingredient_store_section(source["store_section"])
        merged_section = source_section if target_section == "MISC" and source_section != "MISC" else target_section
        merged_image_url = clean_text(target["image_url"]) or clean_text(source["image_url"])
        merged_image_path = clean_text(target["image_path"]) or clean_text(source["image_path"])

        moved_reference_cursor = connection.execute(
            """
            UPDATE recipe_ingredients
               SET ingredient_id = ?
             WHERE user_id = ?
               AND ingredient_id = ?
            """,
            (target_ingredient_id, source["user_id"], source_ingredient_id),
        )
        normalized_moved_reference_count = 0
        if moved_option_item_ids:
            placeholders = ", ".join("?" for _value in moved_option_item_ids)
            moved_option_item_cursor = connection.execute(
                f"""
                UPDATE recipe_ingredient_option_items
                   SET ingredient_id = ?
                 WHERE ingredient_id = ?
                   AND id IN ({placeholders})
                """,
                (
                    target_ingredient_id,
                    source_ingredient_id,
                    *moved_option_item_ids,
                ),
            )
            normalized_moved_reference_count = max(
                0,
                int(moved_option_item_cursor.rowcount or 0),
            )
        connection.execute(
            """
            UPDATE ingredient_aliases
               SET ingredient_id = ?,
                   updated_at = ?
             WHERE user_id = ?
               AND ingredient_id = ?
            """,
            (target_ingredient_id, now, source["user_id"], source_ingredient_id),
        )
        for normalized_alias, alias_name in alias_candidates.items():
            connection.execute(
                """
                INSERT INTO ingredient_aliases (
                    user_id, ingredient_id, alias_name, normalized_alias, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, normalized_alias) DO UPDATE SET
                    ingredient_id = excluded.ingredient_id,
                    alias_name = excluded.alias_name,
                    updated_at = excluded.updated_at
                """,
                (
                    source["user_id"],
                    target_ingredient_id,
                    alias_name,
                    normalized_alias,
                    now,
                    now,
                ),
            )
        connection.execute(
            """
            DELETE FROM ingredient_aliases
             WHERE user_id = ?
               AND ingredient_id = ?
               AND normalized_alias = ?
            """,
            (source["user_id"], target_ingredient_id, normalized_master_name(target["normalized_name"])),
        )
        connection.execute(
            """
            UPDATE ingredients
               SET store_section = ?,
                   image_url = ?,
                   image_path = ?,
                   updated_at = ?
             WHERE id = ?
               AND user_id = ?
            """,
            (
                merged_section,
                merged_image_url,
                merged_image_path,
                now,
                target_ingredient_id,
                source["user_id"],
            ),
        )
        connection.execute(
            "DELETE FROM ingredients WHERE id = ? AND user_id = ?",
            (source_ingredient_id, source["user_id"]),
        )
        combined_usage_row = connection.execute(
            """
            SELECT COUNT(*) AS usage_count
              FROM recipe_ingredients
             WHERE user_id = ?
               AND ingredient_id = ?
            """,
            (source["user_id"], target_ingredient_id),
        ).fetchone()
        alias_rows = connection.execute(
            """
            SELECT alias_name
              FROM ingredient_aliases
             WHERE user_id = ?
               AND ingredient_id = ?
             ORDER BY normalized_alias ASC
            """,
            (source["user_id"], target_ingredient_id),
        ).fetchall()
        merged_target = connection.execute(
            """
            SELECT id, user_id, name, normalized_name, store_section,
                   image_url, image_path, created_at, updated_at
              FROM ingredients
             WHERE id = ? AND user_id = ?
            """,
            (target_ingredient_id, source["user_id"]),
        ).fetchone()
        merged_alias_rows = connection.execute(
            """
            SELECT id, user_id, ingredient_id, alias_name, normalized_alias,
                   created_at, updated_at
              FROM ingredient_aliases
             WHERE user_id = ? AND ingredient_id = ?
             ORDER BY normalized_alias ASC
            """,
            (source["user_id"], target_ingredient_id),
        ).fetchall()
        merge_snapshot = {
            "version": 2,
            "source": source_snapshot,
            "target": target_snapshot,
            "aliases_before": aliases_before_merge,
            "moved_reference_ids": [int(row["id"]) for row in moved_reference_rows],
            "moved_option_item_ids": moved_option_item_ids,
            "duplicate_reviews_before": [dict(row) for row in duplicate_review_rows],
            "merged_target": dict(merged_target),
            "merged_aliases": [dict(row) for row in merged_alias_rows],
        }
        history_cursor = connection.execute(
            """
            INSERT INTO ingredient_merge_history (
                user_id, source_ingredient_id, target_ingredient_id,
                source_name, target_name, snapshot_json, merged_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["user_id"],
                source_ingredient_id,
                target_ingredient_id,
                clean_text(source["name"]),
                clean_text(target["name"]),
                json.dumps(merge_snapshot, separators=(",", ":"), sort_keys=True),
                now,
            ),
        )

        return {
            "ok": True,
            "changed": True,
            "user_id": source["user_id"],
            "source_ingredient_id": source_ingredient_id,
            "source_name": clean_text(source["name"]),
            "target_ingredient_id": target_ingredient_id,
            "target_name": clean_text(target["name"]),
            "target_normalized_name": normalized_master_name(target["normalized_name"]),
            "moved_reference_count": max(0, int(moved_reference_cursor.rowcount or 0)),
            "normalized_moved_reference_count": normalized_moved_reference_count,
            "combined_usage_count": int(combined_usage_row["usage_count"] or 0),
            "aliases": [clean_text(alias_row["alias_name"]) for alias_row in alias_rows],
            "store_section": merged_section,
            "image_url": merged_image_url,
            "merge_id": int(history_cursor.lastrowid),
            "merged_at": now,
        }


def undo_last_ingredient_master_merge(user_id=None, expected_merge_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    try:
        expected_merge_id = int(expected_merge_id or 0)
    except (TypeError, ValueError):
        expected_merge_id = 0
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "No ingredient merge is available to undo."}

        if expected_merge_id > 0:
            history = connection.execute(
                """
                SELECT id, user_id, source_ingredient_id, target_ingredient_id,
                       source_name, target_name, snapshot_json, merged_at
                  FROM ingredient_merge_history
                 WHERE user_id = ? AND id = ? AND undone_at IS NULL
                 LIMIT 1
                """,
                (scoped_user_id, expected_merge_id),
            ).fetchone()
        else:
            history = connection.execute(
                """
                SELECT id, user_id, source_ingredient_id, target_ingredient_id,
                       source_name, target_name, snapshot_json, merged_at
                  FROM ingredient_merge_history
                 WHERE user_id = ? AND undone_at IS NULL
                 ORDER BY id DESC
                 LIMIT 1
                """,
                (scoped_user_id,),
            ).fetchone()
        if not history:
            return {
                "ok": False,
                "status": 404,
                "error": "That ingredient merge is no longer available to undo.",
            }

        validation = validate_ingredient_merge_undo_candidate(connection, history, scoped_user_id)
        if not validation.get("ok"):
            return validation
        snapshot = validation["snapshot"]
        source = validation["source"]
        target = validation["target"]
        aliases_before = validation["aliases_before"]
        source_id = validation["source_id"]
        target_id = validation["target_id"]
        moved_reference_ids = validation["moved_reference_ids"]
        moved_option_item_ids = validation["moved_option_item_ids"]

        connection.execute(
            """
            INSERT INTO ingredients (
                id, user_id, name, normalized_name, store_section,
                image_url, image_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(source.get(field) for field in INGREDIENT_MERGE_RESTORE_FIELDS),
        )
        connection.execute(
            """
            UPDATE ingredients
               SET name = ?, normalized_name = ?, store_section = ?,
                   image_url = ?, image_path = ?, created_at = ?, updated_at = ?
             WHERE id = ? AND user_id = ?
            """,
            (
                target.get("name"),
                target.get("normalized_name"),
                target.get("store_section"),
                target.get("image_url"),
                target.get("image_path"),
                target.get("created_at"),
                target.get("updated_at"),
                target_id,
                scoped_user_id,
            ),
        )
        connection.execute(
            "DELETE FROM ingredient_aliases WHERE user_id = ? AND ingredient_id IN (?, ?)",
            (scoped_user_id, source_id, target_id),
        )
        for alias in aliases_before:
            if not isinstance(alias, dict):
                continue
            connection.execute(
                """
                INSERT INTO ingredient_aliases (
                    id, user_id, ingredient_id, alias_name, normalized_alias,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(alias.get(field) for field in INGREDIENT_MERGE_ALIAS_FIELDS),
            )

        restored_reference_count = 0
        if moved_reference_ids:
            placeholders = ", ".join("?" for _value in moved_reference_ids)
            restored_cursor = connection.execute(
                f"""
                UPDATE recipe_ingredients
                   SET ingredient_id = ?
                 WHERE user_id = ? AND ingredient_id = ? AND id IN ({placeholders})
                """,
                (source_id, scoped_user_id, target_id, *moved_reference_ids),
            )
            restored_reference_count = max(0, int(restored_cursor.rowcount or 0))

        normalized_restored_reference_count = 0
        if moved_option_item_ids:
            placeholders = ", ".join("?" for _value in moved_option_item_ids)
            restored_option_item_cursor = connection.execute(
                f"""
                UPDATE recipe_ingredient_option_items
                   SET ingredient_id = ?
                 WHERE ingredient_id = ?
                   AND id IN ({placeholders})
                """,
                (source_id, target_id, *moved_option_item_ids),
            )
            normalized_restored_reference_count = max(
                0,
                int(restored_option_item_cursor.rowcount or 0),
            )

        duplicate_reviews = snapshot.get("duplicate_reviews_before", [])
        for review in duplicate_reviews if isinstance(duplicate_reviews, list) else []:
            if not isinstance(review, dict):
                continue
            connection.execute(
                """
                UPDATE ingredient_duplicate_reviews
                   SET status = ?, classification = ?, suggested_target_id = ?, updated_at = ?
                 WHERE id = ? AND user_id = ?
                """,
                (
                    review.get("status"),
                    review.get("classification"),
                    review.get("suggested_target_id"),
                    review.get("updated_at"),
                    review.get("id"),
                    scoped_user_id,
                ),
            )

        undone_at = utc_now_iso()
        connection.execute(
            "UPDATE ingredient_merge_history SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
            (undone_at, int(history["id"])),
        )
        next_history = connection.execute(
            """
            SELECT id, user_id, source_ingredient_id, target_ingredient_id,
                   source_name, target_name, merged_at
              FROM ingredient_merge_history
             WHERE user_id = ? AND undone_at IS NULL
             ORDER BY id DESC
             LIMIT 1
            """,
            (scoped_user_id,),
        ).fetchone()

        return {
            "ok": True,
            "changed": True,
            "merge_id": int(history["id"]),
            "user_id": scoped_user_id,
            "source_ingredient_id": source_id,
            "source_name": clean_text(source.get("name")),
            "target_ingredient_id": target_id,
            "target_name": clean_text(target.get("name")),
            "restored_reference_count": restored_reference_count,
            "normalized_restored_reference_count": normalized_restored_reference_count,
            "undone_at": undone_at,
            "next_merge": ingredient_merge_history_summary(next_history),
        }


def ingredient_master_records_for_items(items, user_id=None):
    scoped_user_id = scoped_recipe_user_id(user_id)
    ingredient_ids = set()
    normalized_names = set()

    for item in items or []:
        if not isinstance(item, dict):
            continue

        for id_key in ("ingredient_id", "master_ingredient_id"):
            try:
                ingredient_id = int(item.get(id_key) or 0)
            except (TypeError, ValueError):
                ingredient_id = 0
            if ingredient_id > 0:
                ingredient_ids.add(ingredient_id)

        for name_key in (
            "master_normalized_name",
            "normalized_name",
            "ingredient",
            "name",
            "parsed_name",
            "purchasable_item",
            "buy_as",
        ):
            normalized_name = normalized_master_name(item.get(name_key))
            if normalized_name:
                normalized_names.add(normalized_name)

    if not ingredient_ids and not normalized_names:
        return {"by_id": {}, "by_normalized_name": {}}

    where_parts = ["user_id = ?"]
    params = [scoped_user_id]
    match_parts = []
    if ingredient_ids:
        placeholders = ", ".join("?" for _ in ingredient_ids)
        match_parts.append(f"id IN ({placeholders})")
        params.extend(sorted(ingredient_ids))
    if normalized_names:
        placeholders = ", ".join("?" for _ in normalized_names)
        match_parts.append(f"normalized_name IN ({placeholders})")
        params.extend(sorted(normalized_names))
        match_parts.append(
            f"""
            id IN (
                SELECT ingredient_id
                  FROM ingredient_aliases
                 WHERE user_id = ?
                   AND normalized_alias IN ({placeholders})
            )
            """
        )
        params.append(scoped_user_id)
        params.extend(sorted(normalized_names))

    where_parts.append("(" + " OR ".join(match_parts) + ")")

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return {"by_id": {}, "by_normalized_name": {}}

        rows = connection.execute(
            f"""
            SELECT id, user_id, name, normalized_name, canonical_ingredient, form,
                   store_section, store_section_source, store_section_confidence,
                   store_section_user_confirmed, classifier_version,
                   store_section_reason, store_section_rule, image_url, image_path
              FROM ingredients
             WHERE {' AND '.join(where_parts)}
            """,
            params,
        ).fetchall()

        ingredient_row_ids = [int(row["id"]) for row in rows]
        alias_rows = []
        if ingredient_row_ids:
            placeholders = ", ".join("?" for _ in ingredient_row_ids)
            alias_rows = connection.execute(
                f"""
                SELECT ingredient_id, normalized_alias
                  FROM ingredient_aliases
                 WHERE user_id = ?
                   AND ingredient_id IN ({placeholders})
                """,
                (scoped_user_id, *ingredient_row_ids),
            ).fetchall()

    by_id = {}
    by_normalized_name = {}
    for row in rows:
        row_data = dict(row)
        row_data["store_section"] = clean_ingredient_store_section(row_data.get("store_section"))
        by_id[int(row_data["id"])] = row_data
        by_normalized_name[row_data["normalized_name"]] = row_data
    for alias_row in alias_rows:
        ingredient = by_id.get(int(alias_row["ingredient_id"]))
        if ingredient:
            by_normalized_name[clean_text(alias_row["normalized_alias"])] = ingredient

    return {"by_id": by_id, "by_normalized_name": by_normalized_name}


def recipe_master_user_ids():
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return []

        rows = connection.execute(
            """
            SELECT user_id
              FROM ingredients
             WHERE user_id != ''
            UNION
            SELECT user_id
              FROM equipment
             WHERE user_id != ''
             ORDER BY user_id ASC
            """
        ).fetchall()

    return [str(row["user_id"]) for row in rows]


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalized_master_name(value):
    return clean_text(value).lower()


def truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def compact_image_fields(record, *url_keys):
    record = record if isinstance(record, dict) else {}
    image_url = ""
    image_path = ""
    for key in url_keys:
        image_url = clean_text(record.get(key))
        if image_url:
            break
    for key in ("image_path", "equipment_image_path", "ingredient_image_path"):
        image_path = clean_text(record.get(key))
        if image_path:
            break
    if not image_path and isinstance(record.get("cover_image"), dict):
        image_path = clean_text(record["cover_image"].get("path"))
    return image_url, image_path


def ingredient_name_from_item(item):
    if isinstance(item, dict):
        return clean_text(
            item.get("ingredient")
            or item.get("name")
            or item.get("text")
            or item.get("original_text")
            or item.get("item")
        )
    return clean_text(item)


def ingredient_has_open_suspicious_review(item):
    if not isinstance(item, dict):
        return False

    review = item.get("food_review")
    if not isinstance(review, dict):
        return False

    status = clean_text(review.get("status")).lower()
    if status in {"accepted", "ignored", "reviewed"}:
        return False

    return (
        clean_text(review.get("kind")).lower() == "suspicious_ingredient"
        and truthy(review.get("needs_review"))
    )


def equipment_name_from_item(item):
    if isinstance(item, dict):
        return clean_text(
            item.get("equipment")
            or item.get("name")
            or item.get("text")
            or item.get("item")
        )
    return clean_text(item)


def ingredient_rows_from_sources(
    ingredients=None,
    recipe_data=None,
    user_id=None,
    connection=None,
):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    raw_data = recipe_data.get("raw") if isinstance(recipe_data.get("raw"), dict) else {}
    candidates = None

    if isinstance(raw_data.get("ingredients"), list):
        candidates = raw_data.get("ingredients")
    elif isinstance(recipe_data.get("ingredients"), list):
        candidates = recipe_data.get("ingredients")
    elif isinstance(ingredients, list):
        candidates = ingredients
    else:
        candidates = []

    rows = []
    for index, item in enumerate(candidates, start=1):
        if ingredient_has_open_suspicious_review(item):
            continue

        source_item = dict(item) if isinstance(item, dict) else item
        raw_name = (
            clean_text(source_item.get("raw_name"))
            or ingredient_name_from_item(source_item)
            if isinstance(source_item, dict)
            else ingredient_name_from_item(source_item)
        )
        if isinstance(item, dict):
            item = normalize_ingredient_unit_fields(dict(item))

        name = ingredient_name_from_item(item)
        if not name:
            continue

        if isinstance(item, dict):
            try:
                ingredient_id = int(item.get("ingredient_id") or item.get("master_ingredient_id") or 0)
            except (TypeError, ValueError):
                ingredient_id = 0
            original_text = clean_text(item.get("original_recipe_text") or item.get("original_text") or item.get("text") or name)
            quantity = clean_text(item.get("quantity") or item.get("recipe_qty"))
            unit = clean_text(item.get("unit"))
            unit_id = clean_text(item.get("unit_id"))
            unit_raw = clean_text(item.get("unit_raw"))
            size = clean_text(item.get("size"))
            preparation = clean_text(item.get("preparation"))
            notes = clean_text(item.get("notes"))
            unit_review_required = truthy(item.get("unit_review_required"))
            unit_review_value = clean_text(item.get("unit_review_value"))
            unit_custom = truthy(item.get("unit_custom"))
            buy_as = clean_text(item.get("buy_as") or item.get("purchasable_item") or item.get("purchase_group"))
            normalized_name = normalized_master_name(
                item.get("master_normalized_name") or item.get("normalized_name")
            )
            store_section_custom = truthy(item.get("store_section_custom"))
            if store_section_custom:
                custom_store_section = re.sub(
                    r"\s+",
                    " ",
                    str(item.get("store_section") or "").strip(),
                )[:60]
                store_section = (
                    ingredient_store_section_from_source(
                        custom_store_section,
                        user_id=user_id,
                        connection=connection,
                    )
                    or custom_store_section
                )
                classification = {
                    **normalize_ingredient_classification_context(item),
                    "store_section": store_section,
                    "store_section_source": "manual",
                    "store_section_confidence": 1.0,
                    "store_section_user_confirmed": True,
                    "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                    "store_section_reason": "User selected a custom store section.",
                    "store_section_rule": "manual.custom_section",
                }
            else:
                supplied_source = clean_ingredient_store_section_source(
                    item.get("store_section_source"),
                    default="legacy",
                )
                user_confirmed = truthy(item.get("store_section_user_confirmed"))
                classification = classify_ingredient_store_section_result(
                    {
                        **item,
                        "raw_name": raw_name or item.get("raw_name") or original_text or name,
                        "normalized_name": normalized_name or item.get("normalized_name") or name,
                        "preparation": preparation,
                    },
                    recipe_override=item.get("store_section") if user_confirmed else None,
                    recipe_override_confirmed=user_confirmed,
                    legacy_section=(
                        item.get("store_section") or item.get("section")
                        if supplied_source != "ai"
                        else None
                    ),
                    ai_result=(
                        {
                            "store_section": item.get("store_section"),
                            "confidence": item.get("store_section_confidence"),
                            "reason": item.get("store_section_reason"),
                            "normalized_name": normalized_name,
                        }
                        if supplied_source == "ai"
                        else None
                    ),
                    default="MISC",
                )
                store_section = classification["store_section"]
                if supplied_source == "manual" and truthy(item.get("store_section_save_to_master")):
                    classification.update({
                        "store_section_source": "manual",
                        "store_section_user_confirmed": True,
                        "store_section_confidence": 1.0,
                        "store_section_reason": "User confirmed this section for future occurrences.",
                        "store_section_rule": "manual.master_data",
                    })
            optional = truthy(item.get("optional"))
            ingredient_type = clean_text(
                item.get("section")
                or item.get("ingredient_type")
                or item.get("type")
            ) or ("optional" if optional else "main")
            image_url, image_path = compact_image_fields(item, "ingredient_image_url", "image_url")
        else:
            ingredient_id = 0
            original_text = name
            quantity = ""
            unit = ""
            unit_id = ""
            unit_raw = ""
            size = ""
            preparation = ""
            notes = ""
            unit_review_required = False
            unit_review_value = ""
            unit_custom = False
            buy_as = ""
            normalized_name = ""
            store_section = ""
            store_section_custom = False
            classification = {
                **normalize_ingredient_classification_context(name),
                "store_section": "",
                "store_section_source": "fallback",
                "store_section_confidence": 0.0,
                "store_section_user_confirmed": False,
                "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                "store_section_reason": "",
                "store_section_rule": "",
            }
            optional = False
            ingredient_type = "main"
            image_url = ""
            image_path = ""

        rows.append({
            "ingredient_id": ingredient_id,
            "name": name,
            "raw_name": raw_name or classification.get("raw_name") or original_text or name,
            "normalized_name": normalized_name or classification.get("normalized_name") or "",
            "canonical_ingredient": classification.get("canonical_ingredient") or "",
            "form": classification.get("form") or "",
            "quantity": quantity,
            "unit": unit,
            "unit_id": unit_id,
            "unit_raw": unit_raw,
            "size": size,
            "preparation": preparation,
            "notes": notes,
            "unit_review_required": unit_review_required,
            "unit_review_value": unit_review_value,
            "unit_custom": unit_custom,
            "buy_as": buy_as,
            "store_section": store_section,
            "store_section_custom": store_section_custom,
            "store_section_source": classification.get("store_section_source") or "fallback",
            "store_section_confidence": ingredient_store_section_confidence(
                classification.get("store_section_confidence")
            ),
            "store_section_user_confirmed": truthy(
                classification.get("store_section_user_confirmed")
            ),
            "store_section_save_to_master": truthy(
                item.get("store_section_save_to_master") if isinstance(item, dict) else False
            ),
            "classifier_version": classification.get("classifier_version") or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": classification.get("store_section_reason") or "",
            "store_section_rule": classification.get("store_section_rule") or "",
            "original_recipe_text": original_text,
            "ingredient_type": ingredient_type,
            "optional": optional,
            "sort_order": index,
            "image_url": image_url,
            "image_path": image_path,
        })
    return rows


def equipment_rows_from_recipe_data(recipe_data=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    raw_data = recipe_data.get("raw") if isinstance(recipe_data.get("raw"), dict) else {}
    if isinstance(raw_data.get("equipment"), list):
        candidates = raw_data.get("equipment")
    elif isinstance(recipe_data.get("equipment"), list):
        candidates = recipe_data.get("equipment")
    else:
        candidates = []

    rows = []
    for index, item in enumerate(candidates, start=1):
        name = equipment_name_from_item(item)
        if not name:
            continue

        if isinstance(item, dict):
            original_text = clean_text(item.get("original_recipe_text") or item.get("original_text") or item.get("text") or name)
            optional = truthy(item.get("optional"))
            equipment_section = resolve_equipment_section(
                " ".join(part for part in (name, original_text) if part),
                item.get("equipment_section") or item.get("section") or item.get("type"),
                default="",
            )
            image_url, image_path = compact_image_fields(item, "equipment_image_url", "image_url")
        else:
            original_text = name
            optional = False
            equipment_section = ""
            image_url = ""
            image_path = ""

        rows.append({
            "name": name,
            "equipment_section": equipment_section,
            "original_recipe_text": original_text,
            "optional": optional,
            "sort_order": index,
            "image_url": image_url,
            "image_path": image_path,
        })
    return rows


def upsert_master_record(
    connection,
    table_name,
    user_id,
    name,
    image_url="",
    image_path="",
    store_section=None,
    force_store_section=False,
    store_section_metadata=None,
    equipment_section=None,
):
    if table_name not in {"ingredients", "equipment"}:
        raise ValueError("Unsupported master table.")

    name = clean_text(name)
    normalized_name = normalized_master_name(name)
    if not user_id or not normalized_name:
        return None

    now = utc_now_iso()
    if table_name == "ingredients":
        metadata = store_section_metadata if isinstance(store_section_metadata, dict) else {}
        supplied_source = clean_ingredient_store_section_source(
            metadata.get("store_section_source"),
            default="legacy",
        )
        classification = classify_ingredient_store_section_result(
            {
                **metadata,
                "raw_name": metadata.get("raw_name") or name,
                "normalized_name": metadata.get("normalized_name") or normalized_name,
            },
            recipe_override=store_section if truthy(metadata.get("store_section_user_confirmed")) else None,
            recipe_override_confirmed=truthy(metadata.get("store_section_user_confirmed")),
            legacy_section=store_section if supplied_source != "ai" else None,
            ai_result=(
                {
                    "store_section": store_section,
                    "confidence": metadata.get("store_section_confidence"),
                    "reason": metadata.get("store_section_reason"),
                    "normalized_name": metadata.get("normalized_name") or normalized_name,
                }
                if supplied_source == "ai"
                else None
            ),
        )
        store_section = classification["store_section"]
        canonical_ingredient = clean_text(
            metadata.get("canonical_ingredient") or classification.get("canonical_ingredient")
        )
        ingredient_form = clean_text(metadata.get("form") or classification.get("form"))
        section_source = clean_ingredient_store_section_source(
            metadata.get("store_section_source") or classification.get("store_section_source")
        )
        section_confidence = ingredient_store_section_confidence(
            metadata.get("store_section_confidence"),
            classification.get("store_section_confidence"),
        )
        section_user_confirmed = truthy(
            metadata.get("store_section_user_confirmed")
            or classification.get("store_section_user_confirmed")
        )
        classifier_version = clean_text(
            metadata.get("classifier_version") or classification.get("classifier_version")
        )
        section_reason = clean_text(
            metadata.get("store_section_reason") or classification.get("store_section_reason")
        )
        section_rule = clean_text(
            metadata.get("store_section_rule") or classification.get("store_section_rule")
        )
        previous_row = connection.execute(
            """
            SELECT id, store_section, store_section_user_confirmed
              FROM ingredients
             WHERE user_id = ?
               AND normalized_name = ?
            """,
            (user_id, normalized_name),
        ).fetchone()
        alias_row = None
        if previous_row is None:
            alias_row = connection.execute(
                """
                SELECT i.id, i.name, i.normalized_name, i.store_section
                  FROM ingredient_aliases a
                  JOIN ingredients i
                    ON i.id = a.ingredient_id
                   AND i.user_id = a.user_id
                 WHERE a.user_id = ?
                   AND a.normalized_alias = ?
                """,
                (user_id, normalized_name),
            ).fetchone()
        if alias_row is not None:
            previous_section = clean_ingredient_store_section(alias_row["store_section"])
            next_section = (
                store_section
                if force_store_section or previous_section == "MISC"
                else previous_section
            )
            clean_image_url = clean_text(image_url)
            clean_image_path = clean_text(image_path)
            connection.execute(
                """
                UPDATE ingredients
                   SET store_section = ?,
                       canonical_ingredient = CASE WHEN ? != '' THEN ? ELSE canonical_ingredient END,
                       form = CASE WHEN ? != '' THEN ? ELSE form END,
                       store_section_source = CASE WHEN ? THEN ? ELSE store_section_source END,
                       store_section_confidence = CASE WHEN ? THEN ? ELSE store_section_confidence END,
                       store_section_user_confirmed = CASE WHEN ? THEN ? ELSE store_section_user_confirmed END,
                       classifier_version = CASE WHEN ? THEN ? ELSE classifier_version END,
                       store_section_reason = CASE WHEN ? THEN ? ELSE store_section_reason END,
                       store_section_rule = CASE WHEN ? THEN ? ELSE store_section_rule END,
                       image_url = CASE WHEN ? != '' THEN ? ELSE image_url END,
                       image_path = CASE WHEN ? != '' THEN ? ELSE image_path END,
                       updated_at = ?
                 WHERE id = ?
                   AND user_id = ?
                """,
                (
                    next_section,
                    canonical_ingredient,
                    canonical_ingredient,
                    ingredient_form,
                    ingredient_form,
                    bool(force_store_section or previous_section == "MISC"),
                    section_source,
                    bool(force_store_section or previous_section == "MISC"),
                    section_confidence,
                    bool(force_store_section or previous_section == "MISC"),
                    1 if section_user_confirmed else 0,
                    bool(force_store_section or previous_section == "MISC"),
                    classifier_version,
                    bool(force_store_section or previous_section == "MISC"),
                    section_reason,
                    bool(force_store_section or previous_section == "MISC"),
                    section_rule,
                    clean_image_url,
                    clean_image_url,
                    clean_image_path,
                    clean_image_path,
                    now,
                    int(alias_row["id"]),
                    user_id,
                ),
            )
            return {
                "id": int(alias_row["id"]),
                "name": clean_text(alias_row["name"]),
                "normalized_name": normalized_master_name(alias_row["normalized_name"]),
                "matched_alias": normalized_name,
                "store_section": next_section,
                "previous_store_section": previous_section,
                "store_section_changed": previous_section != next_section,
                "store_section_inserted": False,
            }
        previous_section = (
            clean_ingredient_store_section(previous_row["store_section"])
            if previous_row
            else ""
        )
        store_section_update_sql = (
            "excluded.store_section"
            if force_store_section
            else """
                CASE
                    WHEN COALESCE(NULLIF(TRIM(ingredients.store_section), ''), 'MISC') = 'MISC'
                        THEN excluded.store_section
                    ELSE ingredients.store_section
                END
            """
        )
        metadata_update_condition = (
            "1"
            if force_store_section
            else "COALESCE(NULLIF(TRIM(ingredients.store_section), ''), 'MISC') = 'MISC'"
        )
        connection.execute(
            f"""
            INSERT INTO ingredients (
                user_id, name, normalized_name, canonical_ingredient, form,
                store_section, store_section_source, store_section_confidence,
                store_section_user_confirmed, classifier_version, store_section_reason,
                store_section_rule, image_url, image_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, normalized_name) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE ingredients.name END,
                canonical_ingredient = CASE WHEN excluded.canonical_ingredient != '' THEN excluded.canonical_ingredient ELSE ingredients.canonical_ingredient END,
                form = CASE WHEN excluded.form != '' THEN excluded.form ELSE ingredients.form END,
                store_section = {store_section_update_sql},
                store_section_source = CASE WHEN {metadata_update_condition} THEN excluded.store_section_source ELSE ingredients.store_section_source END,
                store_section_confidence = CASE WHEN {metadata_update_condition} THEN excluded.store_section_confidence ELSE ingredients.store_section_confidence END,
                store_section_user_confirmed = CASE WHEN {metadata_update_condition} THEN excluded.store_section_user_confirmed ELSE ingredients.store_section_user_confirmed END,
                classifier_version = CASE WHEN {metadata_update_condition} THEN excluded.classifier_version ELSE ingredients.classifier_version END,
                store_section_reason = CASE WHEN {metadata_update_condition} THEN excluded.store_section_reason ELSE ingredients.store_section_reason END,
                store_section_rule = CASE WHEN {metadata_update_condition} THEN excluded.store_section_rule ELSE ingredients.store_section_rule END,
                image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE ingredients.image_url END,
                image_path = CASE WHEN excluded.image_path != '' THEN excluded.image_path ELSE ingredients.image_path END,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                name,
                normalized_name,
                canonical_ingredient,
                ingredient_form,
                store_section,
                section_source,
                section_confidence,
                1 if section_user_confirmed else 0,
                classifier_version,
                section_reason,
                section_rule,
                clean_text(image_url),
                clean_text(image_path),
                now,
                now,
            ),
        )
    else:
        equipment_section = resolve_equipment_section(name, equipment_section)
        previous_row = connection.execute(
            """
            SELECT id, equipment_section
              FROM equipment
             WHERE user_id = ?
               AND normalized_name = ?
            """,
            (user_id, normalized_name),
        ).fetchone()
        previous_section = (
            clean_equipment_section(previous_row["equipment_section"])
            if previous_row
            else ""
        )
        connection.execute(
            """
            INSERT INTO equipment (
                user_id, name, normalized_name, equipment_section, image_url, image_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, normalized_name) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE equipment.name END,
                equipment_section = CASE
                    WHEN COALESCE(NULLIF(TRIM(equipment.equipment_section), ''), 'MISC') = 'MISC'
                        THEN excluded.equipment_section
                    ELSE equipment.equipment_section
                END,
                image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE equipment.image_url END,
                image_path = CASE WHEN excluded.image_path != '' THEN excluded.image_path ELSE equipment.image_path END,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                name,
                normalized_name,
                equipment_section,
                clean_text(image_url),
                clean_text(image_path),
                now,
                now,
            ),
        )
    if table_name == "ingredients":
        select_columns = "id, store_section"
    elif table_name == "equipment":
        select_columns = "id, equipment_section"
    else:
        select_columns = "id"
    row = connection.execute(
        f"""
        SELECT {select_columns}
          FROM {table_name}
         WHERE user_id = ?
           AND normalized_name = ?
        """,
        (user_id, normalized_name),
    ).fetchone()
    if not row:
        return None

    result = {"id": int(row["id"])}
    if table_name == "ingredients":
        current_section = clean_ingredient_store_section(row["store_section"])
        result.update({
            "store_section": current_section,
            "previous_store_section": previous_section,
            "store_section_changed": previous_section != current_section,
            "store_section_inserted": previous_section == "",
        })
    elif table_name == "equipment":
        current_section = clean_equipment_section(row["equipment_section"])
        result.update({
            "equipment_section": current_section,
            "previous_equipment_section": previous_section,
            "equipment_section_changed": previous_section != current_section,
            "equipment_section_inserted": previous_section == "",
        })
    return result


def recipe_id_for_url(recipe_url):
    return normalize_recipe_url_key(recipe_url)


def update_ingredient_master_record_from_recipe_row(
    connection,
    user_id,
    row,
    force_store_section=False,
):
    try:
        ingredient_id = int(row.get("ingredient_id") or 0)
    except (TypeError, ValueError):
        ingredient_id = 0
    normalized_name = normalized_master_name(
        row.get("normalized_name")
        or row.get("name")
        or row.get("raw_name")
    )
    if ingredient_id <= 0 and not normalized_name:
        return None

    master_row = None
    if ingredient_id > 0 and normalized_name:
        # IDs embedded in saved recipe JSON can outlive a merge or otherwise
        # become stale. Trust one only when the row name still identifies that
        # same user's master record, either canonically or through an alias.
        master_row = connection.execute(
            """
            SELECT ingredient.id, ingredient.name, ingredient.normalized_name,
                   ingredient.store_section, ingredient.store_section_source,
                   ingredient.store_section_confidence,
                   ingredient.store_section_user_confirmed,
                   ingredient.classifier_version,
                   ingredient.store_section_reason,
                   ingredient.store_section_rule,
                   ingredient.canonical_ingredient, ingredient.form,
                   ingredient.image_url, ingredient.image_path
              FROM ingredients ingredient
             WHERE ingredient.id = ?
               AND ingredient.user_id = ?
               AND (
                    ingredient.normalized_name = ?
                    OR EXISTS (
                        SELECT 1
                          FROM ingredient_aliases alias
                         WHERE alias.user_id = ingredient.user_id
                           AND alias.ingredient_id = ingredient.id
                           AND alias.normalized_alias = ?
                    )
               )
            """,
            (ingredient_id, user_id, normalized_name, normalized_name),
        ).fetchone()

    if master_row is None and normalized_name:
        master_row = connection.execute(
            """
            SELECT id, name, normalized_name, store_section, store_section_source,
                   store_section_confidence, store_section_user_confirmed,
                   classifier_version, store_section_reason, store_section_rule,
                   canonical_ingredient, form, image_url, image_path
              FROM ingredients
             WHERE normalized_name = ?
               AND user_id = ?
            """,
            (normalized_name, user_id),
        ).fetchone()
    if not master_row:
        return None

    matched_ingredient_id = int(master_row["id"])
    previous_section = clean_ingredient_store_section(master_row["store_section"])
    master_confirmed = truthy(master_row["store_section_user_confirmed"])
    classification = classify_ingredient_store_section_result(
        {
            **row,
            "raw_name": row.get("raw_name") or row.get("original_recipe_text") or row.get("name"),
        },
        recipe_override=row.get("store_section") if truthy(row.get("store_section_user_confirmed")) else None,
        recipe_override_confirmed=truthy(row.get("store_section_user_confirmed")),
        legacy_section=row.get("store_section"),
    )
    if force_store_section and clean_ingredient_store_section_source(
        row.get("store_section_source"),
        default="legacy",
    ) == "manual":
        classification.update({
            "store_section_source": "manual",
            "store_section_user_confirmed": True,
            "store_section_confidence": 1.0,
            "store_section_reason": "User confirmed this section for future occurrences.",
            "store_section_rule": "manual.master_data",
        })
    proposed_section = classification["store_section"]
    next_section = previous_section
    can_replace_master = force_store_section or (previous_section == "MISC" and not master_confirmed)
    if not row.get("store_section_custom") and can_replace_master:
        next_section = proposed_section

    metadata = classification if can_replace_master else dict(master_row)

    image_url = clean_text(row.get("image_url"))
    image_path = clean_text(row.get("image_path"))
    next_image_url = image_url or clean_text(master_row["image_url"])
    next_image_path = image_path or clean_text(master_row["image_path"])
    changed = (
        previous_section != next_section
        or (
            can_replace_master
            and (
                clean_ingredient_store_section_source(master_row["store_section_source"], default="legacy")
                != clean_ingredient_store_section_source(metadata.get("store_section_source"), default="legacy")
                or truthy(master_row["store_section_user_confirmed"])
                != truthy(metadata.get("store_section_user_confirmed"))
                or clean_text(master_row["classifier_version"]) != clean_text(metadata.get("classifier_version"))
            )
        )
        or clean_text(master_row["image_url"]) != next_image_url
        or clean_text(master_row["image_path"]) != next_image_path
    )
    if changed:
        connection.execute(
            """
            UPDATE ingredients
               SET store_section = ?,
                   canonical_ingredient = ?,
                   form = ?,
                   store_section_source = ?,
                   store_section_confidence = ?,
                   store_section_user_confirmed = ?,
                   classifier_version = ?,
                   store_section_reason = ?,
                   store_section_rule = ?,
                   image_url = ?,
                   image_path = ?,
                   updated_at = ?
             WHERE id = ?
               AND user_id = ?
            """,
            (
                next_section,
                clean_text(metadata.get("canonical_ingredient")),
                clean_text(metadata.get("form")),
                clean_ingredient_store_section_source(metadata.get("store_section_source"), default="legacy"),
                ingredient_store_section_confidence(metadata.get("store_section_confidence")),
                1 if truthy(metadata.get("store_section_user_confirmed")) else 0,
                clean_text(metadata.get("classifier_version")),
                clean_text(metadata.get("store_section_reason")),
                clean_text(metadata.get("store_section_rule")),
                next_image_url,
                next_image_path,
                utc_now_iso(),
                matched_ingredient_id,
                user_id,
            ),
        )

    return {
        "id": matched_ingredient_id,
        "name": master_row["name"],
        "normalized_name": master_row["normalized_name"],
        "store_section": next_section,
        "store_section_source": clean_ingredient_store_section_source(metadata.get("store_section_source"), default="legacy"),
        "store_section_confidence": ingredient_store_section_confidence(metadata.get("store_section_confidence")),
        "store_section_user_confirmed": truthy(metadata.get("store_section_user_confirmed")),
        "classifier_version": clean_text(metadata.get("classifier_version")),
        "store_section_reason": clean_text(metadata.get("store_section_reason")),
        "store_section_rule": clean_text(metadata.get("store_section_rule")),
        "previous_store_section": previous_section,
        "store_section_changed": previous_section != next_section,
        "store_section_inserted": False,
    }


def _sync_recipe_master_records_with_connection(
    connection,
    recipe_url,
    ingredients=None,
    recipe_data=None,
    user_id=None,
    force_store_sections_from_recipe=False,
):
    """Synchronize compatibility rows inside the caller-owned transaction."""
    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return {"ok": False, "error": "Recipe URL and user id are required."}
    if connection is None:
        raise ValueError("A recipe master database connection is required.")

    ingredient_rows = ingredient_rows_from_sources(
        ingredients=ingredients,
        recipe_data=recipe_data,
        user_id=user_id,
        connection=connection,
    )
    equipment_rows = equipment_rows_from_recipe_data(recipe_data)

    with nullcontext(connection) as connection:
        connection.execute(
            "DELETE FROM recipe_ingredients WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )
        connection.execute(
            "DELETE FROM recipe_equipment WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )

        ingredient_count = 0
        for row in ingredient_rows:
            save_section_to_master = truthy(row.get("store_section_save_to_master"))
            force_master_section = bool(
                force_store_sections_from_recipe and save_section_to_master
            )
            ingredient_result = update_ingredient_master_record_from_recipe_row(
                connection,
                user_id,
                row,
                force_store_section=force_master_section,
            )
            if not ingredient_result:
                master_metadata = dict(row)
                master_store_section = row.get("store_section", "")
                row_section_source = clean_ingredient_store_section_source(
                    row.get("store_section_source"),
                    default="legacy",
                )
                if not save_section_to_master and row_section_source in {"manual", "recipe_override"}:
                    master_metadata.update({
                        "store_section_source": "deterministic_rule",
                        "store_section_user_confirmed": False,
                        "store_section_save_to_master": False,
                    })
                    master_store_section = ""
                ingredient_result = upsert_master_record(
                    connection,
                    "ingredients",
                    user_id,
                    row["name"],
                    image_url=row.get("image_url", ""),
                    image_path=row.get("image_path", ""),
                    store_section=master_store_section,
                    force_store_section=force_master_section,
                    store_section_metadata=master_metadata,
                )
            ingredient_id = ingredient_result["id"] if ingredient_result else None
            if not ingredient_id:
                continue
            if (
                force_master_section
                and ingredient_result.get("store_section_changed")
            ):
                print(
                    "[IngredientMaster] "
                    f"action=store_section_updated_from_recipe "
                    f"ingredient=\"{recipe_master_log_value(row['name'])}\" "
                    f"section=\"{ingredient_result.get('store_section') or 'MISC'}\" "
                    f"user_id={user_id}"
                )
            connection.execute(
                """
                INSERT INTO recipe_ingredients (
                    user_id, recipe_id, ingredient_id, raw_name, normalized_name,
                    canonical_ingredient, form, quantity, unit, unit_id,
                    unit_raw, size, preparation, notes, unit_review_required,
                    unit_review_value, unit_custom, buy_as, store_section,
                    store_section_source, store_section_confidence,
                    store_section_user_confirmed, classifier_version,
                    store_section_reason, store_section_rule,
                    original_recipe_text, ingredient_type, optional, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    recipe_id,
                    ingredient_id,
                    row.get("raw_name", ""),
                    row.get("normalized_name", ""),
                    row.get("canonical_ingredient", ""),
                    row.get("form", ""),
                    row.get("quantity", ""),
                    row.get("unit", ""),
                    row.get("unit_id") or None,
                    row.get("unit_raw", ""),
                    row.get("size", ""),
                    row.get("preparation", ""),
                    row.get("notes", ""),
                    1 if row.get("unit_review_required") else 0,
                    row.get("unit_review_value", ""),
                    1 if row.get("unit_custom") else 0,
                    row.get("buy_as", ""),
                    row.get("store_section", ""),
                    clean_ingredient_store_section_source(row.get("store_section_source")),
                    ingredient_store_section_confidence(row.get("store_section_confidence")),
                    1 if row.get("store_section_user_confirmed") else 0,
                    row.get("classifier_version", ""),
                    row.get("store_section_reason", ""),
                    row.get("store_section_rule", ""),
                    row.get("original_recipe_text", ""),
                    row.get("ingredient_type", "main"),
                    1 if row.get("optional") else 0,
                    int(row.get("sort_order") or 0),
                ),
            )
            ingredient_count += 1

        equipment_count = 0
        for row in equipment_rows:
            equipment_result = upsert_master_record(
                connection,
                "equipment",
                user_id,
                row["name"],
                image_url=row.get("image_url", ""),
                image_path=row.get("image_path", ""),
                equipment_section=row.get("equipment_section", ""),
            )
            equipment_id = equipment_result["id"] if equipment_result else None
            if not equipment_id:
                continue
            connection.execute(
                """
                INSERT INTO recipe_equipment (
                    user_id, recipe_id, equipment_id, original_recipe_text, optional, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    recipe_id,
                    equipment_id,
                    row.get("original_recipe_text", ""),
                    1 if row.get("optional") else 0,
                    int(row.get("sort_order") or 0),
                ),
            )
            equipment_count += 1

    return {
        "ok": True,
        "user_id": user_id,
        "recipe_id": recipe_id,
        "ingredient_count": ingredient_count,
        "equipment_count": equipment_count,
    }


def sync_recipe_master_records(
    recipe_url,
    ingredients=None,
    recipe_data=None,
    user_id=None,
    force_store_sections_from_recipe=False,
):
    scoped_user_id = scoped_recipe_user_id(user_id)
    if not scoped_user_id or not recipe_id_for_url(recipe_url):
        return {"ok": False, "error": "Recipe URL and user id are required."}

    with recipe_master_connection() as connection:
        if (
            isinstance(recipe_data, dict)
            and isinstance(recipe_data.get("ingredients"), list)
        ):
            # Import lazily to keep schema initialization independent from the
            # normalized repository module.  Existing callers (image edits,
            # extraction, purchase mappings, and explicit master syncs) now
            # update the authoritative hierarchy and legacy rows together.
            from PushShoppingList.services.recipe_ingredient_requirement_service import (
                save_recipe_ingredient_requirements,
            )

            return save_recipe_ingredient_requirements(
                recipe_url,
                recipe_data,
                user_id=scoped_user_id,
                connection=connection,
                sync_compatibility=True,
                force_store_sections_from_recipe=force_store_sections_from_recipe,
            )
        return _sync_recipe_master_records_with_connection(
            connection,
            recipe_url,
            ingredients=ingredients,
            recipe_data=recipe_data,
            user_id=scoped_user_id,
            force_store_sections_from_recipe=force_store_sections_from_recipe,
        )


def remove_recipe_master_records_for_recipe(recipe_url, user_id=None):
    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return 0

    with recipe_master_connection() as connection:
        connection.execute(
            "DELETE FROM recipe_ingredient_requirements WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )
        connection.execute(
            "DELETE FROM recipe_ingredient_requirement_sync WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )
        ingredient_cursor = connection.execute(
            "DELETE FROM recipe_ingredients WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )
        equipment_cursor = connection.execute(
            "DELETE FROM recipe_equipment WHERE user_id = ? AND recipe_id = ?",
            (user_id, recipe_id),
        )
        return int(ingredient_cursor.rowcount or 0) + int(equipment_cursor.rowcount or 0)


def load_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _normalize_unit_rows_for_migration(rows, summary):
    if not isinstance(rows, list):
        return False
    changed = False
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        before = json.dumps(item, sort_keys=True, default=str)
        before_unit = clean_text(item.get("unit"))
        normalize_ingredient_unit_fields(item, log_unrecognized=False)
        after = json.dumps(item, sort_keys=True, default=str)
        if before == after:
            continue
        changed = True
        summary["rows_updated"] += 1
        if before_unit and canonical_unit(before_unit) and clean_text(item.get("unit")) != before_unit:
            summary["aliases_replaced"] += 1
        if item.get("size"):
            summary["size_values_moved"] += 1
        if item.get("unit_review_required"):
            summary["ambiguous_rows_flagged"] += 1
    return changed


def normalize_saved_recipe_units(extractor_data_root):
    """Backfill canonical unit fields in saved user JSON without changing quantities."""
    extractor_data_root = Path(extractor_data_root)
    summary = {
        "files_updated": 0,
        "rows_updated": 0,
        "aliases_replaced": 0,
        "size_values_moved": 0,
        "ambiguous_rows_flagged": 0,
    }
    paths = [extractor_data_root / "recipe_ingredients.json"]
    output_folder = extractor_data_root / "output"
    if output_folder.exists():
        paths.extend(path for path in output_folder.glob("*.json") if path.name != "sorted_ingredients.json")

    for path in paths:
        if not path.is_file():
            continue
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        changed = False
        records = payload.values() if path.name == "recipe_ingredients.json" else (payload,)
        for record in records:
            if not isinstance(record, dict):
                continue
            changed = _normalize_unit_rows_for_migration(record.get("ingredients"), summary) or changed
            changed = _normalize_unit_rows_for_migration(record.get("ingredient_details"), summary) or changed
            raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
            changed = _normalize_unit_rows_for_migration(raw.get("ingredients"), summary) or changed
        if changed:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            summary["files_updated"] += 1
    return summary


def repair_saved_misplaced_unit_ingredients(extractor_data_root):
    """Repair only high-confidence unit/ingredient swaps in saved recipe JSON."""
    extractor_data_root = Path(extractor_data_root)
    summary = {
        "files_updated": 0,
        "records_updated": 0,
        "rows_repaired": 0,
    }
    paths = [extractor_data_root / "recipe_ingredients.json"]
    output_folder = extractor_data_root / "output"
    if output_folder.exists():
        paths.extend(path for path in output_folder.glob("*.json") if path.name != "sorted_ingredients.json")

    for path in paths:
        if not path.is_file():
            continue
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        changed = False
        records = payload.values() if path.name == "recipe_ingredients.json" else (payload,)
        for record in records:
            if not isinstance(record, dict):
                continue
            record_changed = False
            collections = [record.get("ingredients"), record.get("ingredient_details")]
            raw = record.get("raw") if isinstance(record.get("raw"), dict) else {}
            inference = record.get("recipe_inference") if isinstance(record.get("recipe_inference"), dict) else {}
            collections.extend((raw.get("ingredients"), inference.get("ingredients")))
            for rows in collections:
                if not isinstance(rows, list):
                    continue
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    ingredient = clean_text(
                        item.get("ingredient")
                        or item.get("name")
                        or item.get("parsed_name")
                        or item.get("normalized_name")
                    )
                    original_text = clean_text(
                        item.get("original_text") or item.get("original_recipe_text")
                    )
                    if not misplaced_unit_ingredient_details(
                        ingredient,
                        original_text,
                        item.get("unit"),
                    ):
                        continue
                    normalize_ingredient_unit_fields(item, log_unrecognized=False)
                    summary["rows_repaired"] += 1
                    record_changed = True

            if record_changed and path.name == "recipe_ingredients.json":
                details = record.get("ingredient_details")
                if isinstance(details, list):
                    ingredient_names = []
                    scaled_ingredients = {}
                    for item in details:
                        if not isinstance(item, dict):
                            continue
                        name = clean_text(
                            item.get("normalized_name")
                            or item.get("ingredient")
                            or item.get("parsed_name")
                            or item.get("original_text")
                        )
                        if not name:
                            continue
                        if name not in ingredient_names:
                            ingredient_names.append(name)
                        quantity = clean_text(item.get("quantity"))
                        unit = clean_text(item.get("unit"))
                        display = " ".join(value for value in (quantity, unit) if value)
                        scaled_ingredients[name] = {
                            "quantity": quantity,
                            "unit": unit or None,
                            "display": display,
                        }
                    record["ingredients"] = ingredient_names
                    record["scaled_ingredients"] = scaled_ingredients

            if record_changed:
                changed = True
                summary["records_updated"] += 1
        if changed:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            summary["files_updated"] += 1
    return summary


def recipe_outputs_by_key(output_folder):
    output_folder = Path(output_folder)
    if not output_folder.exists():
        return {}

    outputs = {}
    for json_path in output_folder.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue
        payload = load_json_file(json_path)
        if not isinstance(payload, dict):
            continue
        source_url = clean_text(payload.get("source_url"))
        recipe_key = recipe_id_for_url(source_url)
        if recipe_key:
            outputs[recipe_key] = payload
    return outputs


def count_backfill_recipes_for_root(extractor_data_root):
    metadata = load_json_file(Path(extractor_data_root) / "recipe_ingredients.json")
    return len(metadata) if isinstance(metadata, dict) else 0


def recipe_master_log_value(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def backfill_ingredient_store_sections_for_user(user_id):
    user_id = scoped_recipe_user_id(user_id)
    print(f"[IngredientMaster] action=store_section_backfill_start user_id={user_id}")
    updated = 0
    defaulted = 0

    with recipe_master_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                m.id,
                m.normalized_name,
                m.store_section AS master_store_section,
                r.store_section AS recipe_store_section
              FROM ingredients m
              LEFT JOIN recipe_ingredients r
                ON r.ingredient_id = m.id
               AND r.user_id = m.user_id
             WHERE m.user_id = ?
             ORDER BY m.id ASC, r.id ASC
            """,
            (user_id,),
        ).fetchall()

        ingredients = {}
        for row in rows:
            ingredient_id = int(row["id"])
            ingredient = ingredients.setdefault(
                ingredient_id,
                {
                    "id": ingredient_id,
                    "normalized_name": row["normalized_name"],
                    "current_section": clean_ingredient_store_section(row["master_store_section"]),
                    "section_counts": {},
                },
            )
            section = ingredient_store_section_from_source(row["recipe_store_section"])
            if section and section != "MISC":
                ingredient["section_counts"][section] = ingredient["section_counts"].get(section, 0) + 1

        now = utc_now_iso()
        for ingredient in ingredients.values():
            section_counts = ingredient["section_counts"]
            section_source = "recipe_ingredients_most_common"
            if section_counts:
                most_common_section = sorted(
                    section_counts,
                    key=lambda candidate: (
                        -section_counts[candidate],
                        INGREDIENT_STORE_SECTION_ORDER.get(candidate, INGREDIENT_STORE_SECTION_ORDER["MISC"]),
                        candidate,
                    ),
                )[0]
                section = resolve_ingredient_store_section(
                    ingredient["normalized_name"],
                    most_common_section,
                )
                if section != most_common_section:
                    section_source = "classifier"
                print(
                    "[IngredientMaster] "
                    f"action=store_section_set ingredient_id={ingredient['id']} "
                    f"normalized_name=\"{recipe_master_log_value(ingredient['normalized_name'])}\" "
                    f"section=\"{section}\" source=\"{section_source}\""
                )
            else:
                section = resolve_ingredient_store_section(ingredient["normalized_name"])
                defaulted += 1
                section_source = "classifier" if section != "MISC" else "default"
                print(
                    "[IngredientMaster] "
                    f"action=store_section_defaulted ingredient_id={ingredient['id']} "
                    f"normalized_name=\"{recipe_master_log_value(ingredient['normalized_name'])}\" "
                    f"section=\"{section}\" source=\"{section_source}\""
                )

            if ingredient["current_section"] != section:
                cursor = connection.execute(
                    """
                    UPDATE ingredients
                       SET store_section = ?,
                           updated_at = ?
                     WHERE id = ?
                       AND user_id = ?
                    """,
                    (section, now, ingredient["id"], user_id),
                )
                updated += int(cursor.rowcount or 0)

    print(
        "[IngredientMaster] "
        f"action=store_section_backfill_complete updated={updated} defaulted={defaulted}"
    )
    return {"updated": updated, "defaulted": defaulted}


def backfill_recipe_master_records_for_user(user_id, extractor_data_root=None, progress_callback=None):
    user_id = scoped_recipe_user_id(user_id)
    if extractor_data_root is None:
        extractor_data_root = storage_service.extractor_root(user_id) / "data"
    extractor_data_root = Path(extractor_data_root)
    unit_normalization = normalize_saved_recipe_units(extractor_data_root)
    metadata = load_json_file(extractor_data_root / "recipe_ingredients.json")
    if not isinstance(metadata, dict) or not metadata:
        store_section_result = backfill_ingredient_store_sections_for_user(user_id)
        _emit_backfill_progress(progress_callback, "user_start", {
            "user_id": user_id,
            "recipe_count": 0,
        })
        _emit_backfill_progress(progress_callback, "user_done", {
            "user_id": user_id,
            "recipes": 0,
            "ingredient_rows": 0,
            "equipment_rows": 0,
            "store_section_updated": store_section_result["updated"],
            "store_section_defaulted": store_section_result["defaulted"],
            "unit_normalization": unit_normalization,
        })
        return {
            "ok": True,
            "user_id": user_id,
            "recipes": 0,
            "ingredient_rows": 0,
            "equipment_rows": 0,
            "store_section_updated": store_section_result["updated"],
            "store_section_defaulted": store_section_result["defaulted"],
            "unit_normalization": unit_normalization,
        }

    outputs = recipe_outputs_by_key(extractor_data_root / "output")
    recipes = 0
    ingredient_rows = 0
    equipment_rows = 0
    _emit_backfill_progress(progress_callback, "user_start", {
        "user_id": user_id,
        "recipe_count": len(metadata),
    })

    for recipe_key, record in metadata.items():
        record = record if isinstance(record, dict) else {}
        recipe_url = clean_text(record.get("url")) or clean_text(recipe_key)
        recipe_id = recipe_id_for_url(recipe_url)
        output_record = outputs.get(recipe_id, {})
        item_payload = {
            "item_key": _backfill_item_key(user_id, recipe_url, recipe_key),
            "user_id": user_id,
            "recipe_url": recipe_url,
            "label": _backfill_recipe_label(record, output_record, recipe_url, recipe_key),
        }
        recipe_data = {
            **record,
            **(output_record if isinstance(output_record, dict) else {}),
            "ingredients": (
                output_record.get("ingredients")
                if isinstance(output_record.get("ingredients"), list)
                else record.get("ingredients")
            ),
            "equipment": output_record.get("equipment") if isinstance(output_record.get("equipment"), list) else [],
        }
        _emit_backfill_progress(progress_callback, "recipe_start", item_payload)
        try:
            result = sync_recipe_master_records(
                recipe_url,
                ingredients=record.get("ingredients") if isinstance(record.get("ingredients"), list) else [],
                recipe_data=recipe_data,
                user_id=user_id,
            )
        except Exception as exc:
            _emit_backfill_progress(progress_callback, "recipe_failed", {
                **item_payload,
                "error": str(exc),
            })
            raise
        if result.get("ok"):
            recipes += 1
            ingredient_count = int(result.get("ingredient_count") or 0)
            equipment_count = int(result.get("equipment_count") or 0)
            ingredient_rows += ingredient_count
            equipment_rows += equipment_count
            _emit_backfill_progress(progress_callback, "recipe_done", {
                **item_payload,
                "ingredient_count": ingredient_count,
                "equipment_count": equipment_count,
            })

    store_section_result = backfill_ingredient_store_sections_for_user(user_id)
    summary = {
        "ok": True,
        "user_id": user_id,
        "recipes": recipes,
        "ingredient_rows": ingredient_rows,
        "equipment_rows": equipment_rows,
        "store_section_updated": store_section_result["updated"],
        "store_section_defaulted": store_section_result["defaulted"],
        "unit_normalization": unit_normalization,
    }
    _emit_backfill_progress(progress_callback, "user_done", summary)
    return summary


def iter_user_data_roots(include_legacy=True):
    if include_legacy:
        legacy_data_root = storage_service.LEGACY_EXTRACTOR_DIR / "data"
        if legacy_data_root.exists():
            yield LOCAL_USER_ID, legacy_data_root

    users_root = storage_service.USER_DATA_DIR
    if users_root.exists():
        for user_root in users_root.iterdir():
            if not user_root.is_dir():
                continue
            user_id = user_root.name
            extractor_data_root = user_root / "recipe-extractor" / "data"
            if extractor_data_root.exists():
                yield user_id, extractor_data_root


def migration_already_applied(connection, name):
    row = connection.execute(
        "SELECT name FROM recipe_master_migrations WHERE name = ?",
        (name,),
    ).fetchone()
    return bool(row)


def mark_migration_applied(connection, name):
    connection.execute(
        """
        INSERT OR REPLACE INTO recipe_master_migrations (name, applied_at)
        VALUES (?, ?)
        """,
        (name, utc_now_iso()),
    )


def backfill_all_recipe_master_records(include_legacy=True, force=False, progress_callback=None):
    with recipe_master_connection() as connection:
        if not force and migration_already_applied(connection, BACKFILL_MIGRATION_NAME):
            result = {"ok": True, "skipped": True, "users": 0, "recipes": 0}
            _emit_backfill_progress(progress_callback, "skipped", result)
            return result

    user_roots = list(iter_user_data_roots(include_legacy=include_legacy))
    total_recipes = sum(count_backfill_recipes_for_root(root) for _user_id, root in user_roots)
    _emit_backfill_progress(progress_callback, "started", {
        "users_total": len(user_roots),
        "recipes_total": total_recipes,
    })
    summaries = []
    for user_id, extractor_data_root in user_roots:
        summaries.append(
            backfill_recipe_master_records_for_user(
                user_id,
                extractor_data_root=extractor_data_root,
                progress_callback=progress_callback,
            )
        )

    with recipe_master_connection() as connection:
        mark_migration_applied(connection, BACKFILL_MIGRATION_NAME)

    result = {
        "ok": True,
        "skipped": False,
        "users": len(summaries),
        "recipes": sum(int(item.get("recipes") or 0) for item in summaries),
        "ingredient_rows": sum(int(item.get("ingredient_rows") or 0) for item in summaries),
        "equipment_rows": sum(int(item.get("equipment_rows") or 0) for item in summaries),
        "store_section_updated": sum(int(item.get("store_section_updated") or 0) for item in summaries),
        "store_section_defaulted": sum(int(item.get("store_section_defaulted") or 0) for item in summaries),
        "summaries": summaries,
    }
    _emit_backfill_progress(progress_callback, "complete", result)
    return result


def master_record_for_name(table_name, user_id, name):
    if table_name not in {"ingredients", "equipment"}:
        raise ValueError("Unsupported master table.")
    user_id = scoped_recipe_user_id(user_id)
    normalized_name = normalized_master_name(name)
    with recipe_master_connection() as connection:
        row = connection.execute(
            f"""
            SELECT *
              FROM {table_name}
             WHERE user_id = ?
               AND normalized_name = ?
            """,
            (user_id, normalized_name),
        ).fetchone()
    return dict(row) if row else None


def recipe_master_rows(table_name, recipe_url, user_id=None):
    if table_name == "recipe_ingredients":
        join_table = "recipe_ingredients"
        master_table = "ingredients"
        master_fk = "ingredient_id"
        master_columns = (
            "m.name, m.normalized_name, m.canonical_ingredient AS master_canonical_ingredient, "
            "m.form AS master_form, m.store_section AS master_store_section, "
            "m.store_section_source AS master_store_section_source, "
            "m.store_section_confidence AS master_store_section_confidence, "
            "m.store_section_user_confirmed AS master_store_section_user_confirmed, "
            "m.classifier_version AS master_classifier_version, "
            "m.store_section_reason AS master_store_section_reason, "
            "m.store_section_rule AS master_store_section_rule, m.image_url, m.image_path"
        )
    elif table_name == "recipe_equipment":
        join_table = "recipe_equipment"
        master_table = "equipment"
        master_fk = "equipment_id"
        master_columns = "m.name, m.normalized_name, m.equipment_section AS master_equipment_section, m.image_url, m.image_path"
    else:
        raise ValueError("Unsupported recipe row table.")

    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    with existing_recipe_master_connection() as connection:
        if connection is None:
            return []

        rows = connection.execute(
            f"""
            SELECT r.*, {master_columns}
              FROM {join_table} r
              JOIN {master_table} m
                ON m.id = r.{master_fk}
               AND m.user_id = r.user_id
             WHERE r.user_id = ?
               AND r.recipe_id = ?
             ORDER BY r.sort_order ASC, r.id ASC
            """,
            (user_id, recipe_id),
        ).fetchall()
    return [dict(row) for row in rows]
