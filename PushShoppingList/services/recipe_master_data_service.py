import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from PushShoppingList.services import storage_service
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key


LOCAL_USER_ID = "local"
RECIPE_MASTER_DB_PATH = Path(
    os.getenv(
        "SHOPPING_APP_RECIPE_MASTER_DB",
        storage_service.PACKAGE_DIR / "user_data" / "recipe_master.sqlite3",
    )
)
RECIPE_MASTER_DB_LOCK = threading.RLock()
BACKFILL_MIGRATION_NAME = "recipe_master_user_scoped_backfill_v1"
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
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
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
            quantity TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            buy_as TEXT NOT NULL DEFAULT '',
            store_section TEXT NOT NULL DEFAULT '',
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
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
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ingredients_user_name ON ingredients(user_id, normalized_name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_equipment_user_name ON equipment(user_id, normalized_name)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_user_recipe ON recipe_ingredients(user_id, recipe_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_ingredient ON recipe_ingredients(ingredient_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_equipment_user_recipe ON recipe_equipment(user_id, recipe_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_recipe_equipment_equipment ON recipe_equipment(equipment_id)")


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


def master_record_filters(user_id=None, search=None, include_all_users=False):
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
        where.append("(LOWER(m.name) LIKE ? OR LOWER(m.normalized_name) LIKE ?)")
        params.extend([search_like, search_like])

    return where, params


def list_master_records(
    table_name,
    user_id=None,
    search=None,
    limit=100,
    offset=0,
    sort="updated_at_desc",
    include_all_users=False,
):
    config = master_record_table_config(table_name)
    limit = bounded_master_limit(limit)
    offset = bounded_master_offset(offset)
    order_clause = MASTER_RECORD_SORTS.get(sort, MASTER_RECORD_SORTS["updated_at_desc"])
    where, params = master_record_filters(
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
    )
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    usage_table = config["usage_table"]
    usage_fk = config["usage_fk"]

    with existing_recipe_master_connection() as connection:
        if connection is None:
            return []

        rows = connection.execute(
            f"""
            SELECT
                m.id,
                m.user_id,
                m.name,
                m.normalized_name,
                m.image_url,
                m.image_path,
                m.created_at,
                m.updated_at,
                COUNT(u.id) AS usage_count
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

    return [
        {
            **dict(row),
            "usage_count": int(row["usage_count"] or 0),
        }
        for row in rows
    ]


def count_master_records(table_name, user_id=None, search=None, include_all_users=False):
    master_record_table_config(table_name)
    where, params = master_record_filters(
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
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


def list_ingredients(user_id=None, search=None, limit=100, offset=0, sort="updated_at_desc", include_all_users=False):
    return list_master_records(
        "ingredients",
        user_id=user_id,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        include_all_users=include_all_users,
    )


def list_equipment(user_id=None, search=None, limit=100, offset=0, sort="updated_at_desc", include_all_users=False):
    return list_master_records(
        "equipment",
        user_id=user_id,
        search=search,
        limit=limit,
        offset=offset,
        sort=sort,
        include_all_users=include_all_users,
    )


def count_ingredients(user_id=None, search=None, include_all_users=False):
    return count_master_records(
        "ingredients",
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
    )


def count_equipment(user_id=None, search=None, include_all_users=False):
    return count_master_records(
        "equipment",
        user_id=user_id,
        search=search,
        include_all_users=include_all_users,
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


def ingredient_rows_from_sources(ingredients=None, recipe_data=None):
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

        name = ingredient_name_from_item(item)
        if not name:
            continue

        if isinstance(item, dict):
            original_text = clean_text(item.get("original_recipe_text") or item.get("original_text") or item.get("text") or name)
            quantity = clean_text(item.get("quantity") or item.get("recipe_qty"))
            unit = clean_text(item.get("unit"))
            buy_as = clean_text(item.get("buy_as") or item.get("purchasable_item") or item.get("purchase_group"))
            store_section = clean_text(item.get("store_section") or item.get("section"))
            optional = truthy(item.get("optional"))
            image_url, image_path = compact_image_fields(item, "ingredient_image_url", "image_url")
        else:
            original_text = name
            quantity = ""
            unit = ""
            buy_as = ""
            store_section = ""
            optional = False
            image_url = ""
            image_path = ""

        rows.append({
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "buy_as": buy_as,
            "store_section": store_section,
            "original_recipe_text": original_text,
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
            image_url, image_path = compact_image_fields(item, "equipment_image_url", "image_url")
        else:
            original_text = name
            optional = False
            image_url = ""
            image_path = ""

        rows.append({
            "name": name,
            "original_recipe_text": original_text,
            "optional": optional,
            "sort_order": index,
            "image_url": image_url,
            "image_path": image_path,
        })
    return rows


def upsert_master_record(connection, table_name, user_id, name, image_url="", image_path=""):
    if table_name not in {"ingredients", "equipment"}:
        raise ValueError("Unsupported master table.")

    name = clean_text(name)
    normalized_name = normalized_master_name(name)
    if not user_id or not normalized_name:
        return None

    now = utc_now_iso()
    connection.execute(
        f"""
        INSERT INTO {table_name} (
            user_id, name, normalized_name, image_url, image_path, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, normalized_name) DO UPDATE SET
            name = CASE WHEN excluded.name != '' THEN excluded.name ELSE {table_name}.name END,
            image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE {table_name}.image_url END,
            image_path = CASE WHEN excluded.image_path != '' THEN excluded.image_path ELSE {table_name}.image_path END,
            updated_at = excluded.updated_at
        """,
        (user_id, name, normalized_name, clean_text(image_url), clean_text(image_path), now, now),
    )
    row = connection.execute(
        f"""
        SELECT id
          FROM {table_name}
         WHERE user_id = ?
           AND normalized_name = ?
        """,
        (user_id, normalized_name),
    ).fetchone()
    return int(row["id"]) if row else None


def recipe_id_for_url(recipe_url):
    return normalize_recipe_url_key(recipe_url)


def sync_recipe_master_records(recipe_url, ingredients=None, recipe_data=None, user_id=None):
    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return {"ok": False, "error": "Recipe URL and user id are required."}

    ingredient_rows = ingredient_rows_from_sources(ingredients=ingredients, recipe_data=recipe_data)
    equipment_rows = equipment_rows_from_recipe_data(recipe_data)

    with recipe_master_connection() as connection:
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
            ingredient_id = upsert_master_record(
                connection,
                "ingredients",
                user_id,
                row["name"],
                image_url=row.get("image_url", ""),
                image_path=row.get("image_path", ""),
            )
            if not ingredient_id:
                continue
            connection.execute(
                """
                INSERT INTO recipe_ingredients (
                    user_id, recipe_id, ingredient_id, quantity, unit, buy_as,
                    store_section, original_recipe_text, optional, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    recipe_id,
                    ingredient_id,
                    row.get("quantity", ""),
                    row.get("unit", ""),
                    row.get("buy_as", ""),
                    row.get("store_section", ""),
                    row.get("original_recipe_text", ""),
                    1 if row.get("optional") else 0,
                    int(row.get("sort_order") or 0),
                ),
            )
            ingredient_count += 1

        equipment_count = 0
        for row in equipment_rows:
            equipment_id = upsert_master_record(
                connection,
                "equipment",
                user_id,
                row["name"],
                image_url=row.get("image_url", ""),
                image_path=row.get("image_path", ""),
            )
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


def remove_recipe_master_records_for_recipe(recipe_url, user_id=None):
    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    if not user_id or not recipe_id:
        return 0

    with recipe_master_connection() as connection:
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


def backfill_recipe_master_records_for_user(user_id, extractor_data_root=None, progress_callback=None):
    user_id = scoped_recipe_user_id(user_id)
    if extractor_data_root is None:
        extractor_data_root = storage_service.extractor_root(user_id) / "data"
    extractor_data_root = Path(extractor_data_root)
    metadata = load_json_file(extractor_data_root / "recipe_ingredients.json")
    if not isinstance(metadata, dict) or not metadata:
        _emit_backfill_progress(progress_callback, "user_start", {
            "user_id": user_id,
            "recipe_count": 0,
        })
        _emit_backfill_progress(progress_callback, "user_done", {
            "user_id": user_id,
            "recipes": 0,
            "ingredient_rows": 0,
            "equipment_rows": 0,
        })
        return {"ok": True, "user_id": user_id, "recipes": 0, "ingredient_rows": 0, "equipment_rows": 0}

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

    summary = {
        "ok": True,
        "user_id": user_id,
        "recipes": recipes,
        "ingredient_rows": ingredient_rows,
        "equipment_rows": equipment_rows,
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
    elif table_name == "recipe_equipment":
        join_table = "recipe_equipment"
        master_table = "equipment"
        master_fk = "equipment_id"
    else:
        raise ValueError("Unsupported recipe row table.")

    user_id = scoped_recipe_user_id(user_id)
    recipe_id = recipe_id_for_url(recipe_url)
    with recipe_master_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT r.*, m.name, m.normalized_name, m.image_url, m.image_path
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
