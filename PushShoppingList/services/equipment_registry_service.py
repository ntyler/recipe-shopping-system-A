"""Workspace-scoped equipment registry edits, order, deletion and merging.

Display edits preserve the detector/canonical identity used by saved recipes.
Alias writes use the optional structured schema's compatible alias table without
enabling structured parsing or creating its recipe requirement tables.
"""

from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services.equipment_normalization_service import normalized_equipment_key


def _error(message, status=400, field=None):
    result = {"ok": False, "status": status, "error": message}
    if field:
        result["errors"] = {field: message}
    return result


def _row(connection, owner, record_id):
    return connection.execute("SELECT * FROM equipment WHERE user_id = ? AND id = ?", (owner, record_id)).fetchone()


def _aliases(connection, owner, record_id):
    if not md.recipe_master_table_exists(connection, "equipment_aliases"):
        return {}
    return {row["alias_key"]: row["alias_name"] for row in connection.execute(
        "SELECT alias_key, alias_name FROM equipment_aliases WHERE user_id = ? AND equipment_id = ? AND status = 'active' ORDER BY alias_key",
        (owner, record_id),
    )}


def _ensure_aliases(connection):
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_user_id_id ON equipment(user_id, id)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS equipment_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL, alias_name TEXT NOT NULL, alias_key TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual', status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, alias_key),
            FOREIGN KEY(user_id, equipment_id) REFERENCES equipment(user_id, id) ON DELETE RESTRICT
        )
    """)


def _write_alias(connection, owner, record_id, alias_key, alias_name):
    """Keep existing alias IDs stable because structured options may use them."""
    columns = md.recipe_master_column_names(connection, "equipment_aliases")
    now = md.utc_now_iso()
    existing = connection.execute(
        "SELECT 1 FROM equipment_aliases WHERE user_id = ? AND alias_key = ?", (owner, alias_key),
    ).fetchone()
    values = {"equipment_id": record_id, "alias_name": alias_name, "status": "active"}
    if "updated_at" in columns:
        values["updated_at"] = now
    if existing:
        connection.execute(
            "UPDATE equipment_aliases SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE user_id = ? AND alias_key = ?",
            (*values.values(), owner, alias_key),
        )
    else:
        values.update(user_id=owner, alias_key=alias_key)
        if "created_at" in columns:
            values["created_at"] = now
        connection.execute(
            "INSERT INTO equipment_aliases (" + ", ".join(values) + ") VALUES (" + ", ".join("?" for _ in values) + ")",
            tuple(values.values()),
        )


def _section_order(connection, owner, section):
    has_order = "sort_order" in md.recipe_master_column_names(connection, "equipment")
    order = "sort_order, id" if has_order else "updated_at DESC, id DESC"
    return [row["id"] for row in connection.execute(
        f"SELECT id FROM equipment WHERE user_id = ? AND equipment_section = ? ORDER BY {order}",
        (owner, section),
    )]


def _reference_details(connection, row):
    """Block unsafe deletion even when a malformed foreign-owner link exists."""
    row = dict(row)
    owner, record_id = row["user_id"], row["id"]
    recipes = set()
    foreign = False
    reference_count = 0
    for reference in connection.execute(
        "SELECT user_id, recipe_id FROM recipe_equipment WHERE equipment_id = ?", (record_id,),
    ):
        if reference["user_id"] != owner:
            foreign = True
        else:
            recipes.add(reference["recipe_id"])
            reference_count += 1
    if md.recipe_master_table_exists(connection, "recipe_equipment_options"):
        for reference in connection.execute("""
            SELECT o.user_id, r.user_id AS recipe_owner, r.recipe_id FROM recipe_equipment_options o
            LEFT JOIN recipe_equipment_requirements r ON r.id = o.requirement_id
            WHERE o.equipment_id = ? OR o.matched_alias_id IN (
                SELECT id FROM equipment_aliases WHERE equipment_id = ?
            )
        """, (record_id, record_id)):
            if reference["user_id"] != owner or reference["recipe_owner"] != owner:
                foreign = True
            else:
                recipes.add(reference["recipe_id"])
                reference_count += 1
    if md.recipe_master_table_exists(connection, "equipment_aliases"):
        foreign = foreign or bool(connection.execute(
            "SELECT 1 FROM equipment_aliases WHERE equipment_id = ? AND user_id <> ? LIMIT 1", (record_id, owner),
        ).fetchone())
    protected = bool(md.truthy(row.get("is_seeded")) or not owner or owner == md.LOCAL_USER_ID)
    if protected:
        reason = "This equipment record is protected and cannot be deleted."
    elif foreign:
        reason = "This equipment has protected references and cannot be safely deleted or merged."
    elif reference_count:
        reason = "This equipment is used by recipes. Reassign its usage or use Merge duplicate before deleting."
    else:
        reason = ""
    return {"can_delete": not reason, "delete_blocked_reason": reason,
            "delete_recipe_count": len(recipes), "delete_reference_count": reference_count,
            "has_protected_references": foreign, "is_protected": protected}


def _record(connection, row):
    result = dict(row)
    owner, record_id = result["user_id"], result["id"]
    result["detected_name"] = result["name"]
    override = result.pop("display_name_override", "")
    result["name"] = override or result["name"]
    result["has_display_name_override"] = bool(override)
    result["equipment_type"] = result["equipment_section"]
    result["aliases"] = list(_aliases(connection, owner, record_id).values())
    ordered = _section_order(connection, owner, result["equipment_section"])
    result["sort_order"] = ordered.index(record_id)
    result["section_count"] = len(ordered)
    result.update(_reference_details(connection, row))
    result["usage_count"] = result["delete_recipe_count"]
    count = connection.execute("SELECT COUNT(*) FROM equipment WHERE user_id = ?", (owner,)).fetchone()[0]
    result["merge_blocked_reason"] = (
        "This equipment has protected references and cannot be safely merged."
        if result["has_protected_references"] or result["is_protected"] else "Add another equipment item before merging duplicates." if count < 2 else ""
    )
    result["can_merge"] = not result["merge_blocked_reason"]
    return result


def equipment_editor_record(record_id, user_id=None):
    owner = md.scoped_equipment_user_id(user_id)
    with md.existing_recipe_master_read_connection() as connection:
        row = _row(connection, owner, record_id) if connection else None
        return _record(connection, row) if row else None


def equipment_action_details(records):
    records = list(records)
    if not records:
        return {}
    result = {}
    with md.existing_recipe_master_read_connection() as connection:
        if connection is None:
            return result
        counts = {}
        for record in records:
            row = _row(connection, record["user_id"], record["id"])
            if not row:
                continue
            detail = _reference_details(connection, row)
            owner = record["user_id"]
            if owner not in counts:
                counts[owner] = connection.execute("SELECT COUNT(*) FROM equipment WHERE user_id = ?", (owner,)).fetchone()[0]
            reason = (
                "This equipment has protected references and cannot be safely merged."
                if detail["has_protected_references"] or detail["is_protected"] else "Add another equipment item before merging duplicates." if counts[owner] < 2 else ""
            )
            detail.update(can_merge=not reason, merge_blocked_reason=reason)
            result[int(record["id"])] = detail
    return result


def _order_error(order):
    if not isinstance(order, dict):
        return _error("Equipment order must include a position and the complete Equipment Type order.")
    error = md._ingredient_order_request_error(order.get("position"), order.get("expected_ids"))
    if error:
        error["error"] = error["error"].replace("ingredient", "equipment").replace("section", "Equipment Type")
    return error


def _name_conflict(connection, owner, record_id, key, *, allowed_ids=()):
    for other in connection.execute("SELECT * FROM equipment WHERE user_id = ? AND id <> ?", (owner, record_id)):
        other = dict(other)
        if other["id"] in allowed_ids:
            continue
        if key in {normalized_equipment_key(other.get(column)) for column in (
            "name", "normalized_name", "display_name_override", "canonical_name", "canonical_key",
        )}:
            return True
    if md.recipe_master_table_exists(connection, "equipment_aliases"):
        alias = connection.execute(
            "SELECT equipment_id FROM equipment_aliases WHERE user_id = ? AND alias_key = ? AND equipment_id <> ?",
            (owner, key, record_id),
        ).fetchone()
        if alias and alias["equipment_id"] not in allowed_ids:
            return True
    return False


def update_equipment_master_record(record_id, payload, user_id=None):
    owner = md.scoped_equipment_user_id(user_id)
    if not md.master_record_for_id("equipment", record_id, user_id=owner):
        return _error("Equipment was not found.", 404)
    payload = payload if isinstance(payload, dict) else {}
    name = payload.get("name", payload.get("display_name"))
    reset = payload.get("reset") is True
    if name is not None and (not isinstance(name, str) or not md.clean_text(name) or len(md.clean_text(name)) > 160):
        if not reset:
            return _error("Equipment name must contain 1 to 160 characters.", field="name")
    aliases = payload.get("aliases")
    if aliases is not None and (not isinstance(aliases, list) or len(aliases) > 100 or any(
        not isinstance(alias, str) or not md.clean_text(alias) or len(md.clean_text(alias)) > 160 for alias in aliases
    )):
        return _error("Aliases must be a list of up to 100 names, each at most 160 characters.", field="aliases")
    section = payload.get("equipment_section", payload.get("equipment_type"))
    if section is not None:
        section = md.equipment_section_from_source(section) if isinstance(section, str) else ""
        if not section:
            return _error("Choose a valid Equipment Type.", field="equipment_section")
    order = payload.get("order")
    if order is not None and (error := _order_error(order)):
        return error
    with md.existing_recipe_master_connection(user_id=owner, initialize_schema=False) as connection:
        if connection is None:
            return _error("Equipment was not found.", 404)
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, owner, record_id)
        if not row:
            return _error("Equipment was not found.", 404)
        row = dict(row)
        section = section or row["equipment_section"]
        display_name = row["name"] if reset else md.clean_text(name) if name is not None else row["display_name_override"] or row["name"]
        override = "" if display_name == row["name"] else display_name
        key = normalized_equipment_key(display_name)
        if _name_conflict(connection, owner, record_id, key):
            return _error("This name belongs to another equipment item. Use Merge duplicate to combine them.", 409, "name")
        existing = _aliases(connection, owner, record_id)
        requested = existing.copy() if aliases is None else {normalized_equipment_key(alias): md.clean_text(alias) for alias in aliases}
        requested.pop(key, None)
        for alias_key, alias_name in requested.items():
            if not alias_key or _name_conflict(connection, owner, record_id, alias_key):
                return _error(f'The alias "{alias_name}" belongs to another equipment item.', 409, "aliases")
        ordered = None
        if order is not None:
            original = _section_order(connection, owner, row["equipment_section"])
            if order["expected_ids"] != original:
                return _error("This Equipment Type changed. Refresh before reordering; your edits have been kept.", 409)
            if section == row["equipment_section"]:
                if order["position"] > len(original):
                    return _error("The position is outside this Equipment Type.")
                ordered = [value for value in original if value != record_id]
            else:
                ordered = _section_order(connection, owner, section)
            ordered.insert(min(order["position"] - 1, len(ordered)), record_id)
        changed = override != row["display_name_override"] or section != row["equipment_section"] or requested != existing
        order_changed = ordered is not None and ordered != original
        # Validate everything before schema changes, aliases or row fields.
        md.migrate_equipment_order(connection)
        if "equipment_section_user_confirmed" not in md.recipe_master_column_names(connection, "equipment"):
            connection.execute("ALTER TABLE equipment ADD COLUMN equipment_section_user_confirmed INTEGER NOT NULL DEFAULT 0")
        if changed:
            connection.execute("""UPDATE equipment SET display_name_override = ?, equipment_section = ?,
                equipment_section_user_confirmed = CASE WHEN ? THEN 1 ELSE equipment_section_user_confirmed END,
                updated_at = ? WHERE user_id = ? AND id = ?""",
                               (override, section, section != row["equipment_section"], md.utc_now_iso(), owner, record_id))
        if requested != existing:
            _ensure_aliases(connection)
            # Retire removed aliases instead of invalidating matched_alias_id on saved options.
            for alias_key in existing.keys() - requested.keys():
                connection.execute("UPDATE equipment_aliases SET status = 'retired' WHERE user_id = ? AND equipment_id = ? AND alias_key = ?",
                                   (owner, record_id, alias_key))
            for alias_key, alias_name in requested.items():
                if existing.get(alias_key) != alias_name:
                    _write_alias(connection, owner, record_id, alias_key, alias_name)
        if order_changed:
            connection.executemany("UPDATE equipment SET sort_order = ? WHERE id = ? AND user_id = ?",
                                   [(index, value, owner) for index, value in enumerate(ordered)])
        saved = _record(connection, _row(connection, owner, record_id))
        saved.update(changed=changed or order_changed, ordered_ids=ordered)
        return {"ok": True, "record": saved, "result": saved, "message": "Equipment saved."}


def move_equipment_master_record(record_id, position, expected_ids, user_id=None):
    result = update_equipment_master_record(record_id, {"order": {"position": position, "expected_ids": expected_ids}}, user_id=user_id)
    if result.get("ok"):
        result.update(ordered_ids=result["record"]["ordered_ids"], position=position)
    return result


def delete_equipment_master_record(record_id, *, confirm=False, user_id=None):
    owner = md.scoped_equipment_user_id(user_id)
    if not md.master_record_for_id("equipment", record_id, user_id=owner):
        return _error("Equipment was not found.", 404)
    if confirm is not True:
        return _error("Confirm deletion of this equipment item.")
    with md.existing_recipe_master_connection(user_id=owner, initialize_schema=False) as connection:
        if connection is None:
            return _error("Equipment was not found.", 404)
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, owner, record_id)
        if not row:
            return _error("Equipment was not found.", 404)
        details = _reference_details(connection, row)
        if not details["can_delete"]:
            return {**_error(details["delete_blocked_reason"], 409), **details}
        md.migrate_equipment_order(connection)
        if md.recipe_master_table_exists(connection, "equipment_aliases"):
            connection.execute("DELETE FROM equipment_aliases WHERE user_id = ? AND equipment_id = ?", (owner, record_id))
        connection.execute("DELETE FROM equipment WHERE user_id = ? AND id = ?", (owner, record_id))
        return {"ok": True, "deleted_id": record_id, "message": "Equipment deleted."}


def merge_equipment_master_records(record_id, target_id, user_id=None):
    owner = md.scoped_equipment_user_id(user_id)
    if not md.master_record_for_id("equipment", record_id, user_id=owner):
        return _error("Equipment was not found.", 404)
    try:
        if isinstance(target_id, bool) or isinstance(target_id, float):
            raise ValueError
        target_id = int(target_id)
    except (TypeError, ValueError):
        return _error("Choose the equipment item to keep.")
    if target_id == record_id:
        return _error("Choose another equipment item to merge into.")
    if not md.master_record_for_id("equipment", target_id, user_id=owner):
        return _error("Equipment was not found.", 404)
    with md.existing_recipe_master_connection(user_id=owner, initialize_schema=False) as connection:
        if connection is None:
            return _error("Equipment was not found.", 404)
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        source, target = _row(connection, owner, record_id), _row(connection, owner, target_id)
        if not source or not target:
            return _error("Equipment was not found.", 404)
        source, target = dict(source), dict(target)
        details = [_reference_details(connection, item) for item in (source, target)]
        if any(item["has_protected_references"] or item["is_protected"] for item in details):
            return _error("This equipment has protected references and cannot be safely merged.", 409)
        aliases = _aliases(connection, owner, record_id)
        for field in ("name", "normalized_name", "display_name_override", "canonical_name", "canonical_key"):
            if source.get(field):
                aliases[normalized_equipment_key(source[field])] = source[field]
        for key in list(aliases):
            if _name_conflict(connection, owner, target_id, key, allowed_ids=(record_id,)):
                return _error("An equipment alias belongs to another item. Resolve it before merging.", 409)
        md.migrate_equipment_order(connection)
        _ensure_aliases(connection)
        # Transfer existing alias IDs intact before adding the old source names.
        connection.execute("UPDATE equipment_aliases SET equipment_id = ? WHERE user_id = ? AND equipment_id = ?", (target_id, owner, record_id))
        for key, value in aliases.items():
            _write_alias(connection, owner, target_id, key, value)
        moved = connection.execute("UPDATE recipe_equipment SET equipment_id = ? WHERE user_id = ? AND equipment_id = ?", (target_id, owner, record_id)).rowcount
        if md.recipe_master_table_exists(connection, "recipe_equipment_options"):
            moved += connection.execute("""
                UPDATE recipe_equipment_options SET equipment_id = ?, canonical_name = ?, canonical_key = ?, updated_at = ?
                WHERE user_id = ? AND equipment_id = ?
            """, (target_id, target.get("canonical_name") or target["name"], target.get("canonical_key") or normalized_equipment_key(target["name"]),
                  md.utc_now_iso(), owner, record_id)).rowcount
        if "merged_into_id" in target:
            connection.execute("UPDATE equipment SET merged_into_id = ? WHERE user_id = ? AND merged_into_id = ?", (target_id, owner, record_id))
        connection.execute("UPDATE equipment SET image_url = CASE WHEN image_url = '' THEN ? ELSE image_url END, image_path = CASE WHEN image_path = '' THEN ? ELSE image_path END, updated_at = ? WHERE user_id = ? AND id = ?",
                           (source["image_url"], source["image_path"], md.utc_now_iso(), owner, target_id))
        connection.execute("DELETE FROM equipment WHERE user_id = ? AND id = ?", (owner, record_id))
        return {"ok": True, "source_id": record_id, "target_id": target_id, "source_name": source["display_name_override"] or source["name"],
                "target_name": target["display_name_override"] or target["name"], "moved_reference_count": moved,
                "record": _record(connection, _row(connection, owner, target_id)), "message": "Equipment merged; recipe usage and aliases were preserved."}
