"""Delete unused ingredient records without cascading away recipe content."""

from PushShoppingList.services import recipe_master_data_service as master_data


def _deletion_details(connection, records):
    """Read both recipe representations and Buy As aliases before deletion."""
    records = list(records)
    if not records:
        return {}
    ids = [int(record["id"]) for record in records]
    placeholders = ", ".join("?" for _ in ids)
    stored = connection.execute(
        f"SELECT * FROM ingredients WHERE id IN ({placeholders})", ids,
    ).fetchall()
    owners = {int(row["id"]): row["user_id"] for row in stored}
    details = {
        int(row["id"]): {
            "can_delete": True, "delete_blocked_reason": "",
            "delete_recipe_count": 0, "delete_reference_count": 0,
        }
        for row in stored
    }
    # Direct foreign keys are checked across every owner: their ON DELETE
    # CASCADE/SET NULL behavior can otherwise damage another workspace. Text
    # references resolve only against the ingredient's own workspace registry.
    common_tables = [f"""
        selected AS (SELECT id, user_id, normalized_name FROM ingredients WHERE id IN ({placeholders})),
        names AS (
            SELECT id, user_id, LOWER(TRIM(normalized_name)) AS normalized_name FROM selected
            UNION
            SELECT m.id, m.user_id, LOWER(TRIM(alias.normalized_alias))
              FROM selected m JOIN ingredient_aliases alias
                ON alias.ingredient_id = m.id AND alias.user_id = m.user_id
        )
    """]
    # Separate indexed ID and name joins avoid comparing every recipe row with
    # every visible ingredient. UNION deduplicates rows matching both fields.
    # CROSS JOIN keeps legacy rows outermost so SQLite looks up the small name
    # registry instead of rescanning all owner recipes for each ingredient.
    reference_queries = ["""
        SELECT m.id AS ingredient_id, r.user_id, r.recipe_id, 'recipe:' || r.id AS reference_id
          FROM selected m JOIN recipe_ingredients r ON r.ingredient_id = m.id
        UNION
        SELECT names.id, r.user_id, r.recipe_id, 'recipe:' || r.id
          FROM recipe_ingredients r CROSS JOIN names
            ON names.user_id = r.user_id AND names.normalized_name = LOWER(TRIM(r.buy_as))
         WHERE TRIM(r.buy_as) != ''
    """]
    if master_data._connection_has_table(connection, "recipe_ingredient_option_items"):
        common_tables.append("""
            option_items AS (
                SELECT item.*, requirement.user_id, requirement.recipe_id
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement ON requirement.id = option.requirement_id
                 WHERE requirement.user_id IN (SELECT user_id FROM selected)
                    OR item.ingredient_id IN (SELECT id FROM selected)
            ),
            option_names AS (
                SELECT id, user_id, recipe_id, LOWER(TRIM(buy_as)) AS normalized_name
                  FROM option_items WHERE TRIM(buy_as) != ''
                UNION ALL
                SELECT id, user_id, recipe_id, LOWER(TRIM(purchasable_item))
                  FROM option_items WHERE TRIM(purchasable_item) != ''
                UNION ALL
                SELECT id, user_id, recipe_id, LOWER(TRIM(normalized_name))
                  FROM option_items WHERE ingredient_id IS NULL AND TRIM(normalized_name) != ''
                UNION ALL
                SELECT id, user_id, recipe_id, LOWER(TRIM(raw_name))
                  FROM option_items WHERE ingredient_id IS NULL AND TRIM(raw_name) != ''
            )
        """)
        reference_queries.append("""
            SELECT m.id AS ingredient_id, requirement.user_id, requirement.recipe_id,
                   'option:' || item.id AS reference_id
              FROM selected m JOIN recipe_ingredient_option_items item ON item.ingredient_id = m.id
              JOIN recipe_ingredient_options option ON option.id = item.option_id
              JOIN recipe_ingredient_requirements requirement ON requirement.id = option.requirement_id
            UNION
            SELECT names.id, item.user_id, item.recipe_id, 'option:' || item.id
              FROM option_names item JOIN names
                ON names.user_id = item.user_id AND names.normalized_name = item.normalized_name
        """)
    reference_rows = connection.execute(
        f"""
        WITH {', '.join(common_tables)}
        SELECT ingredient_id, user_id, recipe_id, COUNT(*) AS reference_count
          FROM ({' UNION '.join(reference_queries)})
         GROUP BY ingredient_id, user_id, recipe_id
        """,
        ids,
    ).fetchall()
    foreign_reference_ids = set()
    for row in reference_rows:
        if row["user_id"] != owners[int(row["ingredient_id"])]:
            foreign_reference_ids.add(int(row["ingredient_id"]))
            continue
        detail = details[int(row["ingredient_id"])]
        detail["delete_recipe_count"] += 1
        detail["delete_reference_count"] += int(row["reference_count"])

    foreign_alias_ids = {
        int(row["ingredient_id"])
        for row in connection.execute(
            f"""
            SELECT DISTINCT alias.ingredient_id
              FROM ingredient_aliases alias JOIN ingredients m ON m.id = alias.ingredient_id
             WHERE m.id IN ({placeholders}) AND alias.user_id != m.user_id
            """, ids,
        ).fetchall()
    }
    for stored_row in stored:
        record = dict(stored_row)
        detail = details[int(record["id"])]
        count = detail["delete_recipe_count"]
        # Ingredients currently come from recipes rather than a seed registry.
        # Keep shared legacy records protected, and honor a stored seed marker
        # if a database includes one; classifier provenance is not seed origin.
        if master_data.truthy(record.get("is_seeded")):
            reason = "System-seeded ingredients are protected and cannot be deleted."
        elif not record["user_id"] or record["user_id"] == master_data.LOCAL_USER_ID:
            reason = "Workspace ingredients are protected and cannot be deleted."
        elif int(record["id"]) in foreign_reference_ids:
            reason = "This ingredient has references in another workspace and cannot be safely deleted."
        elif count:
            reason = (
                f"Used by {count} recipe{'s' if count != 1 else ''}. Deleting this ingredient "
                "would break recipe references. Use Merge duplicate… to preserve the "
                "references, or reassign them before deleting."
            )
        elif int(record["id"]) in foreign_alias_ids:
            reason = "This ingredient has aliases in another workspace and cannot be safely deleted."
        else:
            reason = ""
        detail.update(can_delete=not bool(reason), delete_blocked_reason=reason)
    return details


def ingredient_deletion_details(records):
    """Return authoritative deletion eligibility for rendered rows or an editor."""
    with master_data.existing_recipe_master_read_connection() as connection:
        if connection is None:
            return {}
        return _deletion_details(connection, records)


def delete_ingredient_master_record(ingredient_id, *, confirm=False, user_id=None, allow_other_users=False):
    try:
        ingredient_id = int(ingredient_id or 0)
    except (TypeError, ValueError):
        ingredient_id = 0
    scoped_user_id = master_data.scoped_recipe_user_id(user_id)
    with master_data.existing_recipe_master_connection(user_id=scoped_user_id) as connection:
        if connection is None:
            return {"ok": False, "status": 404, "error": "Ingredient record was not found."}
        # Serialize the eligibility recheck and DELETE with competing recipe
        # writes, including writes from another process.
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        record = connection.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        if not record or (not allow_other_users and record["user_id"] != scoped_user_id):
            return {"ok": False, "status": 404, "error": "Ingredient record was not found."}
        if confirm is not True:
            return {"ok": False, "status": 400, "error": "Confirm deletion of this ingredient before continuing."}
        detail = _deletion_details(connection, [record])[ingredient_id]
        if not detail["can_delete"]:
            return {"ok": False, "status": 409, "error": detail["delete_blocked_reason"], **detail}
        connection.execute(
            "DELETE FROM ingredients WHERE id = ? AND user_id = ?",
            (ingredient_id, record["user_id"]),
        )
        return {
            "ok": True, "deleted": True, "ingredient_id": ingredient_id,
            "name": record["name"], "message": f'{record["name"]} deleted.',
        }
