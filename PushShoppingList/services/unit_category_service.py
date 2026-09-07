"""Workspace unit categories. IDs are independent of editable display names."""

import unicodedata
import uuid

from PushShoppingList.services.ingredient_unit_service import UNIT_REGISTRY_CATEGORIES


def clean_text(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def default_categories(units=()):
    return [
        {"id": key, "key": key, "label": label, "description": "", "required": True,
         "sort_order": index, "unit_count": sum(u["category"] == key for u in units)}
        for index, (key, label) in enumerate(UNIT_REGISTRY_CATEGORIES)
    ]


def ensure_schema(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workspace_unit_categories (
            user_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_required INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL,
            PRIMARY KEY (user_id, id),
            UNIQUE (user_id, normalized_name)
        )
    """)
    # Existing unit.category values already are stable IDs; no unit rewrite is needed.
    for row in connection.execute("SELECT DISTINCT user_id FROM workspace_units").fetchall():
        seed_categories(connection, row[0])


def seed_categories(connection, user_id):
    existing_ids = {r[0] for r in connection.execute(
        "SELECT id FROM workspace_unit_categories WHERE user_id=?", (user_id,))}
    for category in default_categories():
        if category["id"] in existing_ids:
            continue
        connection.execute("""
            INSERT INTO workspace_unit_categories
                (user_id, id, name, normalized_name, is_required, sort_order)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, id) DO NOTHING
        """, (user_id, category["id"], category["label"],
              category["label"].casefold(), category["sort_order"]))


def read_categories(connection, user_id, units=()):
    if connection is None or not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_unit_categories'"
    ).fetchone():
        return default_categories(units)
    rows = connection.execute("""
        SELECT c.*, (SELECT COUNT(*) FROM workspace_units u
            WHERE u.user_id=c.user_id AND u.category=c.id) AS unit_count
        FROM workspace_unit_categories c WHERE c.user_id=? ORDER BY c.sort_order, c.id
    """, (user_id,)).fetchall()
    if not rows:
        return default_categories(units)
    return [{"id": r["id"], "key": r["id"], "label": r["name"],
             "description": r["description"], "required": bool(r["is_required"]),
             "sort_order": r["sort_order"], "unit_count": r["unit_count"]} for r in rows]


def mutate_category(values, category_id="", *, action="save", user_id=None):
    from PushShoppingList.services import recipe_master_data_service as master
    from PushShoppingList.services.ingredient_unit_service import clear_unit_registry_cache

    user_id = str(user_id or master.scoped_recipe_user_id()).strip()
    values = values if isinstance(values, dict) else {}
    with master.recipe_master_connection(user_id=user_id) as connection:
        # Schema/seeding writes acquire SQLite's writer lock before validation,
        # keeping duplicate checks, reassignment and ordering in one transaction.
        master._seed_workspace_unit_registry(connection, user_id)
        categories = read_categories(connection, user_id)
        existing = next((c for c in categories if c["id"] == category_id), None)
        if category_id and not existing:
            return {"ok": False, "status": 404, "error": "Category not found."}
        if action == "delete":
            if not existing:
                return {"ok": False, "status": 404, "error": "Category not found."}
            if existing["required"]:
                return {"ok": False, "status": 409, "error": "Required system categories cannot be deleted."}
            target = values.get("reassign_to")
            if existing["unit_count"] and not target:
                return {"ok": False, "status": 409, "error": "Choose a category to reassign all units before deleting.",
                        "unit_count": existing["unit_count"]}
            if target and not any(c["id"] == target and c["id"] != category_id for c in categories):
                return {"ok": False, "status": 422, "error": "Choose a different category in this workspace."}
            if target:
                offset = connection.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM workspace_units WHERE user_id=? AND category=?",
                                            (user_id, target)).fetchone()[0]
                moved = connection.execute("SELECT id FROM workspace_units WHERE user_id=? AND category=? ORDER BY sort_order, id",
                                           (user_id, category_id)).fetchall()
                connection.executemany("UPDATE workspace_units SET category=?, sort_order=?, updated_at=? WHERE user_id=? AND id=?",
                                       [(target, offset + i, master.utc_now_iso(), user_id, row[0]) for i, row in enumerate(moved)])
                target_rows = connection.execute("SELECT id FROM workspace_units WHERE user_id=? AND category=? ORDER BY sort_order, id",
                                                 (user_id, target)).fetchall()
                connection.executemany("UPDATE workspace_units SET sort_order=? WHERE user_id=? AND id=?",
                                       [(i, user_id, row[0]) for i, row in enumerate(target_rows)])
            connection.execute("DELETE FROM workspace_unit_categories WHERE user_id=? AND id=?", (user_id, category_id))
            ordered = [c["id"] for c in categories if c["id"] != category_id]
            message = "Category deleted." if not existing["unit_count"] else "Units reassigned and category deleted."
        elif action == "move_to":
            position = values.get("position")
            if not existing or type(position) is not int or not 1 <= position <= len(categories):
                return {"ok": False, "status": 422, "error": "Choose a valid category position."}
            ordered = [c["id"] for c in categories if c["id"] != category_id]
            ordered.insert(position - 1, category_id)
            message = "Category order saved."
        elif action == "save":
            raw_name = values.get("name")
            raw_description = values.get("description")
            name = clean_text(raw_name) if isinstance(raw_name, str) else ""
            description = clean_text(raw_description) if isinstance(raw_description, str) else ""
            errors = {}
            if not name:
                errors["name"] = "Enter a category name."
            elif len(name) > 60:
                errors["name"] = "Category names must be 60 characters or fewer."
            elif any(c["id"] != category_id and clean_text(c["label"]).casefold() == name.casefold() for c in categories):
                errors["name"] = "A category with this name already exists."
            if raw_description is not None and not isinstance(raw_description, str):
                errors["description"] = "Enter a description as text."
            elif len(description) > 300:
                errors["description"] = "Descriptions must be 300 characters or fewer."
            if errors:
                return {"ok": False, "status": 422, "errors": errors, "error": next(iter(errors.values()))}
            if existing:
                connection.execute("UPDATE workspace_unit_categories SET name=?, normalized_name=?, description=? WHERE user_id=? AND id=?",
                                   (name, name.casefold(), description, user_id, category_id))
            else:
                category_id = "category_" + uuid.uuid4().hex
                connection.execute("INSERT INTO workspace_unit_categories (user_id,id,name,normalized_name,description,sort_order) VALUES (?,?,?,?,?,?)",
                                   (user_id, category_id, name, name.casefold(), description, len(categories)))
            ordered = None
            message = "Category updated." if existing else "Category added."
        else:
            return {"ok": False, "status": 422, "error": "Unknown category action."}
        if ordered is not None:
            connection.executemany("UPDATE workspace_unit_categories SET sort_order=? WHERE user_id=? AND id=?",
                                   [(index, user_id, key) for index, key in enumerate(ordered)])
    clear_unit_registry_cache()
    return {"ok": True, "category_id": category_id, "message": message,
            "created": action == "save" and not existing,
            "deleted_category_id": category_id if action == "delete" else None,
            "reassign_to": values.get("reassign_to") if action == "delete" else None}
