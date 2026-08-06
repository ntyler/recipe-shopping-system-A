import json
import re
import unicodedata
import uuid

from PushShoppingList.services import recipe_master_data_service as master_data


INGREDIENT_TYPE_SEEDS = (
    ("main", "Main"),
    ("optional", "Optional"),
    ("garnish", "Garnish"),
    ("topping", "Topping"),
    ("sauce", "Sauce"),
    ("substitute", "Substitute"),
)
INGREDIENT_TYPE_SEED_VERSION = "ingredient_types_v1"


def clean_type_name(value):
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")).strip(),
    )


def type_key(value):
    value = clean_type_name(value).lower()
    value = re.sub(r"[_-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _seed_registry(connection, user_id):
    marker = connection.execute(
        """
        SELECT seed_version
          FROM workspace_ingredient_type_registry_seeds
         WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if marker:
        return False

    timestamp = master_data.utc_now_iso()
    for sort_order, (type_id, name) in enumerate(INGREDIENT_TYPE_SEEDS):
        connection.execute(
            """
            INSERT OR IGNORE INTO workspace_ingredient_types (
                user_id, id, name, normalized_name, is_seeded, is_active,
                sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?)
            """,
            (
                user_id,
                type_id,
                name,
                type_key(name),
                sort_order,
                timestamp,
                timestamp,
            ),
        )
    connection.execute(
        """
        INSERT INTO workspace_ingredient_type_registry_seeds (
            user_id, seed_version, seeded_at
        ) VALUES (?, ?, ?)
        """,
        (user_id, INGREDIENT_TYPE_SEED_VERSION, timestamp),
    )
    return True


def _registry_from_connection(connection, user_id):
    rows = connection.execute(
        """
        SELECT id, name, normalized_name, is_seeded, is_active, sort_order,
               created_at, updated_at
          FROM workspace_ingredient_types
         WHERE user_id = ?
         ORDER BY sort_order ASC, normalized_name ASC, id ASC
        """,
        (user_id,),
    ).fetchall()
    types = []
    for row in rows:
        seeded = bool(row["is_seeded"])
        types.append({
            "id": str(row["id"]),
            "name": str(row["name"]),
            "value": str(row["id"]) if seeded else str(row["name"]),
            "seeded": seeded,
            "custom": not seeded,
            "active": bool(row["is_active"]),
            "sort_order": int(row["sort_order"] or 0),
            "updated_at": str(row["updated_at"] or ""),
        })
    return {"types": types}


def _type_lookup(registry):
    lookup = {}
    for item in registry.get("types", []):
        type_id = str(item.get("id") or "")
        lookup[type_key(type_id)] = type_id
        lookup[type_key(item.get("name"))] = type_id
        lookup[type_key(item.get("value"))] = type_id
    return lookup


def _metadata_type(metadata_json):
    try:
        metadata = json.loads(str(metadata_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(metadata, dict):
        return ""
    return clean_type_name(
        metadata.get("section")
        or metadata.get("ingredient_type")
        or metadata.get("type")
    )


def _row_type_value(row):
    optional = bool(row["optional"])
    value = clean_type_name(row["ingredient_type"])
    if "metadata_json" in row.keys():
        metadata_value = _metadata_type(row["metadata_json"])
        if metadata_value and (not value or type_key(value) == "main"):
            value = metadata_value
    if optional and (not value or type_key(value) == "main"):
        return "optional"
    return value or "main"


def _type_rows(connection, user_id):
    ingredient_rows = connection.execute(
        """
        SELECT id, 'ingredient' AS reference_kind, recipe_id,
               raw_name AS ingredient_name, quantity, unit, preparation,
               notes, original_recipe_text, ingredient_type, optional,
               sort_order, '' AS option_label, '' AS requirement_label,
               '' AS option_type, '{}' AS metadata_json
          FROM recipe_ingredients
         WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    option_rows = connection.execute(
        """
        SELECT item.id, 'option' AS reference_kind, requirement.recipe_id,
               item.raw_name AS ingredient_name, item.quantity, item.unit,
               item.preparation, item.notes, item.original_recipe_text,
               item.ingredient_type, item.optional, item.sort_order,
               option.label AS option_label,
               requirement.label AS requirement_label,
               option.option_type AS option_type,
               item.metadata_json
          FROM recipe_ingredient_option_items item
          JOIN recipe_ingredient_options option ON option.id = item.option_id
          JOIN recipe_ingredient_requirements requirement
            ON requirement.id = option.requirement_id
         WHERE requirement.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return [*ingredient_rows, *option_rows]


def _usage_counts(connection, user_id, registry):
    lookup = _type_lookup(registry)
    recipe_ids_by_type = {
        str(item["id"]): set()
        for item in registry.get("types", [])
    }
    for row in _type_rows(connection, user_id):
        recipe_id = master_data.clean_text(row["recipe_id"])
        type_id = lookup.get(type_key(_row_type_value(row)))
        if recipe_id and type_id in recipe_ids_by_type:
            recipe_ids_by_type[type_id].add(recipe_id)
    return {
        type_id: len(recipe_ids)
        for type_id, recipe_ids in recipe_ids_by_type.items()
    }


def ingredient_type_registry_payload(user_id=None, include_usage=False):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    with master_data.recipe_master_connection() as connection:
        _seed_registry(connection, user_id)
        registry = _registry_from_connection(connection, user_id)
        if include_usage:
            counts = _usage_counts(connection, user_id, registry)
            for item in registry.get("types", []):
                item["recipe_count"] = int(counts.get(str(item["id"])) or 0)
    return registry


def workspace_ingredient_type_recipe_references(type_id, user_id=None, limit=100):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    type_id = str(type_id or "").strip()
    try:
        limit = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        limit = 100

    with master_data.recipe_master_connection() as connection:
        _seed_registry(connection, user_id)
        registry = _registry_from_connection(connection, user_id)
        ingredient_type = next(
            (
                item for item in registry.get("types", [])
                if str(item.get("id")) == type_id
            ),
            None,
        )
        if not ingredient_type:
            return {
                "type": None,
                "references": [],
                "total": 0,
                "total_reference_count": 0,
                "limit": limit,
            }
        lookup = _type_lookup(registry)
        matching_rows = sorted(
            _type_rows(connection, user_id),
            key=lambda row: (
                master_data.clean_text(row["recipe_id"]).lower(),
                0 if row["reference_kind"] == "ingredient" else 1,
                int(row["sort_order"] or 0),
                int(row["id"] or 0),
            ),
        )

    metadata = master_data.recipe_reference_metadata(user_id)
    references_by_recipe = {}
    match_keys_by_recipe = {}
    total_reference_count = 0
    for row in matching_rows:
        if lookup.get(type_key(_row_type_value(row))) != type_id:
            continue
        recipe_id = master_data.clean_text(row["recipe_id"])
        metadata_record = metadata.get(recipe_id)
        metadata_record = metadata_record if isinstance(metadata_record, dict) else {}
        recipe_url = master_data.clean_text(metadata_record.get("url")) or recipe_id
        reference = references_by_recipe.setdefault(recipe_id, {
            "recipe_id": recipe_id,
            "recipe_url": recipe_url,
            "recipe_title": master_data.recipe_reference_title(
                recipe_id,
                metadata_record,
            ),
            "cover_image": dict(metadata_record.get("cover_image"))
            if isinstance(metadata_record.get("cover_image"), dict)
            else {},
            "matches": [],
        })
        original_text = master_data.clean_text(row["original_recipe_text"])
        ingredient_name = master_data.clean_text(row["ingredient_name"])
        quantity = master_data.clean_text(row["quantity"])
        unit_name = master_data.clean_text(row["unit"])
        preparation = master_data.clean_text(row["preparation"])
        notes = master_data.clean_text(row["notes"])
        ingredient_line = original_text or " ".join(
            value for value in (quantity, unit_name, ingredient_name) if value
        )
        if not original_text and preparation:
            ingredient_line = f"{ingredient_line}, {preparation}" if ingredient_line else preparation
        if not original_text and notes:
            ingredient_line = f"{ingredient_line} ({notes})" if ingredient_line else notes
        option_label = master_data.clean_text(row["option_label"])
        requirement_label = master_data.clean_text(row["requirement_label"])
        match_key = (
            type_key(ingredient_line or ingredient_name),
            type_key(ingredient_name),
        )
        recipe_match_keys = match_keys_by_recipe.setdefault(recipe_id, set())
        if row["option_type"] == "original" and match_key in recipe_match_keys:
            continue
        recipe_match_keys.add(match_key)
        total_reference_count += 1
        reference["matches"].append({
            "id": int(row["id"] or 0),
            "kind": master_data.clean_text(row["reference_kind"]),
            "ingredient_line": ingredient_line or ingredient_name or "Ingredient line",
            "ingredient_name": ingredient_name,
            "context": option_label or requirement_label,
            "optional": bool(row["optional"]),
        })

    references = list(references_by_recipe.values())
    return {
        "type": ingredient_type,
        "references": references[:limit],
        "total": len(references),
        "total_reference_count": total_reference_count,
        "limit": limit,
    }


def _update_option_metadata_type(connection, user_id, previous_keys, replacement):
    rows = connection.execute(
        """
        SELECT item.id, item.ingredient_type, item.metadata_json
          FROM recipe_ingredient_option_items item
          JOIN recipe_ingredient_options option ON option.id = item.option_id
          JOIN recipe_ingredient_requirements requirement
            ON requirement.id = option.requirement_id
         WHERE requirement.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    for row in rows:
        direct_match = type_key(row["ingredient_type"]) in previous_keys
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        metadata = metadata if isinstance(metadata, dict) else {}
        metadata_value = clean_type_name(
            metadata.get("section")
            or metadata.get("ingredient_type")
            or metadata.get("type")
        )
        metadata_match = type_key(metadata_value) in previous_keys
        if not direct_match and not metadata_match:
            continue
        if metadata_match:
            metadata["section"] = replacement
            metadata.pop("ingredient_type", None)
            metadata.pop("type", None)
        connection.execute(
            """
            UPDATE recipe_ingredient_option_items
               SET ingredient_type = ?, metadata_json = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                replacement,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                master_data.utc_now_iso(),
                int(row["id"]),
            ),
        )


def _update_ingredient_rows_type(connection, user_id, previous_keys, replacement):
    rows = connection.execute(
        """
        SELECT id, ingredient_type
          FROM recipe_ingredients
         WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    for row in rows:
        if type_key(row["ingredient_type"]) not in previous_keys:
            continue
        connection.execute(
            "UPDATE recipe_ingredients SET ingredient_type = ? WHERE id = ?",
            (replacement, int(row["id"])),
        )


def save_workspace_ingredient_type(values, type_id="", user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    type_id = str(type_id or "").strip()
    values = values if isinstance(values, dict) else {}
    name = clean_type_name(values.get("name") or values.get("canonical_name"))
    active = bool(values.get("active", True))
    errors = {}
    if not name:
        errors["name"] = "Enter a type name."
    elif len(name) > 40:
        errors["name"] = "Use 40 characters or fewer."

    with master_data.recipe_master_connection() as connection:
        _seed_registry(connection, user_id)
        existing = None
        if type_id:
            existing = connection.execute(
                """
                SELECT * FROM workspace_ingredient_types
                 WHERE user_id = ? AND id = ?
                """,
                (user_id, type_id),
            ).fetchone()
            if not existing:
                return {"ok": False, "status": 404, "error": "Type not found."}
        if type_id == "main" and not active:
            errors["active"] = "Main must remain available as the default type."
        if name:
            collision = connection.execute(
                """
                SELECT id FROM workspace_ingredient_types
                 WHERE user_id = ? AND normalized_name = ?
                """,
                (user_id, type_key(name)),
            ).fetchone()
            if collision and str(collision["id"]) != type_id:
                errors["name"] = "A type with that name already exists."
        if errors:
            return {
                "ok": False,
                "status": 422,
                "error": "Correct the highlighted type fields.",
                "errors": errors,
            }

        timestamp = master_data.utc_now_iso()
        previous_name = str(existing["name"]) if existing else ""
        if existing:
            connection.execute(
                """
                UPDATE workspace_ingredient_types
                   SET name = ?, normalized_name = ?, is_active = ?, updated_at = ?
                 WHERE user_id = ? AND id = ?
                """,
                (name, type_key(name), 1 if active else 0, timestamp, user_id, type_id),
            )
            if previous_name != name and not bool(existing["is_seeded"]):
                previous_keys = {type_key(type_id), type_key(previous_name)}
                _update_ingredient_rows_type(
                    connection,
                    user_id,
                    previous_keys,
                    name,
                )
                _update_option_metadata_type(
                    connection,
                    user_id,
                    previous_keys,
                    name,
                )
        else:
            type_id = f"custom_{uuid.uuid4().hex}"
            sort_order = int(connection.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1
                  FROM workspace_ingredient_types
                 WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO workspace_ingredient_types (
                    user_id, id, name, normalized_name, is_seeded, is_active,
                    sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    type_id,
                    name,
                    type_key(name),
                    1 if active else 0,
                    sort_order,
                    timestamp,
                    timestamp,
                ),
            )
        registry = _registry_from_connection(connection, user_id)

    return {
        "ok": True,
        "created": not bool(existing),
        "type_id": type_id,
        "message": f'{name} {"added" if not existing else "updated"}.',
        "registry": registry,
    }


def delete_workspace_ingredient_type(type_id, user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    type_id = str(type_id or "").strip()
    with master_data.recipe_master_connection() as connection:
        _seed_registry(connection, user_id)
        existing = connection.execute(
            """
            SELECT * FROM workspace_ingredient_types
             WHERE user_id = ? AND id = ?
            """,
            (user_id, type_id),
        ).fetchone()
        if not existing:
            return {"ok": False, "status": 404, "error": "Type not found."}
        if bool(existing["is_seeded"]):
            return {
                "ok": False,
                "status": 422,
                "error": "Built-in types can be deactivated but not deleted.",
            }
        registry = _registry_from_connection(connection, user_id)
        usage = _usage_counts(connection, user_id, registry).get(type_id, 0)
        if usage:
            return {
                "ok": False,
                "status": 409,
                "error": (
                    f'{existing["name"]} is used by {usage} '
                    f'recipe{"s" if usage != 1 else ""}. Deactivate it instead.'
                ),
            }
        connection.execute(
            "DELETE FROM workspace_ingredient_types WHERE user_id = ? AND id = ?",
            (user_id, type_id),
        )
        registry = _registry_from_connection(connection, user_id)
    return {
        "ok": True,
        "deleted": True,
        "type_id": type_id,
        "message": f'{existing["name"]} deleted.',
        "registry": registry,
    }


def import_workspace_ingredient_type_names(values, user_id=None):
    user_id = str(user_id or master_data.scoped_recipe_user_id()).strip()
    values = values if isinstance(values, list) else []
    imported = []
    skipped = []
    for value in values:
        name = clean_type_name(value)
        if not name:
            continue
        result = save_workspace_ingredient_type(
            {"name": name, "active": True},
            user_id=user_id,
        )
        if result.get("ok") and result.get("created"):
            imported.append(name)
        else:
            skipped.append(name)
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "message": (
            f'Imported {len(imported)} custom type{"s" if len(imported) != 1 else ""}.'
            if imported
            else "No new custom types were imported."
        ),
    }
