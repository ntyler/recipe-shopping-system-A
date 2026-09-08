import sqlite3

import pytest

from PushShoppingList.services import ingredient_deletion_service as deletion
from PushShoppingList.services import recipe_ingredient_requirement_service as requirements
from PushShoppingList.services import recipe_master_data_service as md
from test_recipe_master_data_routes import configure_master_data_app, seed_master_records, sign_in


@pytest.fixture
def deletion_app(monkeypatch, tmp_path):
    app, _db, _users = configure_master_data_app(monkeypatch, tmp_path)
    seed_master_records()
    return app


def unused_ingredient(name="Unused paprika", owner="user-a"):
    with md.recipe_master_connection(user_id=owner) as connection:
        md.upsert_master_record(connection, "ingredients", owner, name, store_section="MISC")
    return md.master_record_for_name("ingredients", owner, name)


def add_alias(record, alias="Sweet paprika", owner=None):
    with md.recipe_master_connection(user_id=record["user_id"]) as connection:
        connection.execute(
            """INSERT INTO ingredient_aliases
               (user_id, ingredient_id, alias_name, normalized_alias, created_at, updated_at)
               VALUES (?, ?, ?, ?, '2026-09-07', '2026-09-07')""",
            (owner or record["user_id"], record["id"], alias, alias.lower()),
        )


@pytest.mark.parametrize("confirmation", [None, False, "true", "false", 1])
def test_delete_requires_explicit_boolean_confirmation(deletion_app, confirmation):
    record = unused_ingredient()
    with deletion_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": confirmation})
    assert response.status_code == 400
    assert "Confirm deletion" in response.json["error"]
    assert md.master_record_for_id("ingredients", record["id"], user_id="user-a")


def test_confirmed_unused_delete_removes_only_record_and_owned_aliases(deletion_app):
    record = unused_ingredient()
    add_alias(record)
    tomato = md.master_record_for_name("ingredients", "user-a", "Tomato")
    with deletion_app.test_client() as client:
        sign_in(client, "user-a")
        context = client.get(f'/api/master-data/ingredients/{record["id"]}/editor').json["record"]
        assert context["can_delete"] and not context["delete_blocked_reason"]
        assert context["delete_recipe_count"] == context["delete_reference_count"] == 0
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": True})
        assert response.status_code == 200 and response.json["result"]["deleted"]
        assert client.get(f'/api/master-data/ingredients/{record["id"]}/editor').status_code == 404
    assert md.master_record_for_name("ingredients", "user-a", "Tomato") == tomato
    with md.existing_recipe_master_read_connection() as connection:
        assert not connection.execute("SELECT 1 FROM ingredient_aliases WHERE ingredient_id = ?", (record["id"],)).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0] == 2


def test_delete_is_scoped_and_admin_can_delete_other_owned_unused_record(deletion_app):
    record = unused_ingredient(owner="user-b")
    with deletion_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": True, "user_id": "user-b"})
        assert response.status_code == 404
        sign_in(client, "admin-user")
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": True})
        assert response.status_code == 200


@pytest.mark.parametrize("seeded", [False, True], ids=["workspace", "stored-system-seed"])
def test_workspace_and_system_seeded_ingredients_are_protected_from_admin(deletion_app, seeded):
    record = unused_ingredient(owner="user-a" if seeded else md.LOCAL_USER_ID)
    if seeded:
        with md.recipe_master_connection() as connection:
            connection.execute("ALTER TABLE ingredients ADD COLUMN is_seeded INTEGER NOT NULL DEFAULT 0")
            connection.execute("UPDATE ingredients SET is_seeded = 1 WHERE id = ?", (record["id"],))
    with deletion_app.test_client() as client:
        sign_in(client, "admin-user")
        context = client.get(f'/api/master-data/ingredients/{record["id"]}/editor').json["record"]
        assert not context["can_delete"] and "protected" in context["delete_blocked_reason"]
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": True})
        assert response.status_code == 409 and "protected" in response.json["error"]
    assert md.master_record_for_id("ingredients", record["id"], user_id=record["user_id"])


def test_delete_rechecks_recipe_usage_after_previously_unused_context(deletion_app):
    record = unused_ingredient()
    with deletion_app.test_client() as client:
        sign_in(client, "user-a")
        assert client.get(f'/api/master-data/ingredients/{record["id"]}/editor').json["record"]["can_delete"]
        md.sync_recipe_master_records(
            "https://example.com/new-use", recipe_data={"ingredients": [{"ingredient": record["name"]}]}, user_id="user-a",
        )
        with md.existing_recipe_master_read_connection() as connection:
            before = [dict(row) for row in connection.execute("SELECT * FROM recipe_ingredients")]
        response = client.post(f'/admin/master-data/ingredients/{record["id"]}/delete', json={"confirm": True})
    assert response.status_code == 409
    assert response.json["result"]["delete_recipe_count"] == 1
    assert "Merge duplicate" in response.json["error"] and "break recipe references" in response.json["error"]
    with md.existing_recipe_master_read_connection() as connection:
        assert [dict(row) for row in connection.execute("SELECT * FROM recipe_ingredients")] == before


@pytest.mark.parametrize("buy_as", ["Unused paprika", "Sweet paprika"], ids=["canonical", "alias"])
def test_buy_as_references_prevent_deletion_without_name_references(deletion_app, buy_as):
    record = unused_ingredient()
    add_alias(record)
    with md.recipe_master_connection(user_id="user-a") as connection:
        connection.execute("UPDATE recipe_ingredients SET buy_as = ? WHERE user_id = 'user-a'", (buy_as,))
    detail = deletion.ingredient_deletion_details([record])[record["id"]]
    assert not detail["can_delete"] and detail["delete_recipe_count"] == 1
    result = deletion.delete_ingredient_master_record(record["id"], confirm=True, user_id="user-a")
    assert result["status"] == 409


@pytest.mark.parametrize("reference", ["id", "buy_as", "alias", "purchasable_item", "unlinked-name"])
def test_normalized_option_only_references_prevent_deletion(deletion_app, reference):
    record = unused_ingredient()
    add_alias(record)
    recipe_url = "https://example.com/normalized-only"
    requirements.save_recipe_ingredient_requirements(
        recipe_url, {"ingredients": [{"recipe_ingredient_id": "test-requirement", "ingredient": "Cumin"}]},
        user_id="user-a", sync_compatibility=False,
    )
    with md.recipe_master_connection(user_id="user-a") as connection:
        item = connection.execute(
            """SELECT item.id FROM recipe_ingredient_option_items item
               JOIN recipe_ingredient_options option ON option.id = item.option_id
               JOIN recipe_ingredient_requirements requirement ON requirement.id = option.requirement_id
               WHERE requirement.recipe_id = ?""", (md.recipe_id_for_url(recipe_url),),
        ).fetchone()
        assert item
        if reference == "id":
            connection.execute("UPDATE recipe_ingredient_option_items SET ingredient_id = ? WHERE id = ?", (record["id"], item["id"]))
        elif reference == "unlinked-name":
            connection.execute("UPDATE recipe_ingredient_option_items SET ingredient_id = NULL, normalized_name = ? WHERE id = ?", (record["normalized_name"], item["id"]))
        else:
            field = "purchasable_item" if reference == "purchasable_item" else "buy_as"
            connection.execute(f"UPDATE recipe_ingredient_option_items SET {field} = ? WHERE id = ?", ("Sweet paprika" if reference == "alias" else record["name"], item["id"]))
        before = dict(connection.execute("SELECT * FROM recipe_ingredient_option_items WHERE id = ?", (item["id"],)).fetchone())
    detail = deletion.ingredient_deletion_details([record])[record["id"]]
    assert detail["delete_recipe_count"] == detail["delete_reference_count"] == 1
    result = deletion.delete_ingredient_master_record(record["id"], confirm=True, user_id="user-a")
    assert result["status"] == 409
    with md.existing_recipe_master_read_connection() as connection:
        assert dict(connection.execute("SELECT * FROM recipe_ingredient_option_items WHERE id = ?", (item["id"],)).fetchone()) == before


@pytest.mark.parametrize("foreign_reference", ["recipe", "option", "alias"])
def test_foreign_workspace_references_prevent_unsafe_cascades(deletion_app, foreign_reference):
    record = unused_ingredient()
    if foreign_reference == "recipe":
        with md.recipe_master_connection(user_id="user-b") as connection:
            connection.execute("UPDATE recipe_ingredients SET ingredient_id = ? WHERE user_id = 'user-b'", (record["id"],))
    elif foreign_reference == "option":
        requirements.save_recipe_ingredient_requirements(
            "https://example.com/foreign-option", {"ingredients": [{"ingredient": "Cumin"}]},
            user_id="user-b", sync_compatibility=False,
        )
        with md.recipe_master_connection(user_id="user-b") as connection:
            connection.execute(
                """UPDATE recipe_ingredient_option_items SET ingredient_id = ?
                     WHERE option_id IN (
                         SELECT option.id FROM recipe_ingredient_options option
                         JOIN recipe_ingredient_requirements requirement ON requirement.id = option.requirement_id
                         WHERE requirement.user_id = 'user-b'
                     )""", (record["id"],),
            )
    else:
        add_alias(record, owner="user-b")
    result = deletion.delete_ingredient_master_record(record["id"], confirm=True, user_id="user-a")
    assert result["status"] == 409
    assert result["delete_recipe_count"] == result["delete_reference_count"] == 0
    assert "another workspace" in result["error"]
    assert md.master_record_for_id("ingredients", record["id"], user_id="user-a")


def test_same_name_in_other_workspace_does_not_block_owned_unused_delete(deletion_app):
    record = unused_ingredient()
    with md.recipe_master_connection(user_id="user-b") as connection:
        connection.execute("UPDATE recipe_ingredients SET buy_as = ? WHERE user_id = 'user-b'", (record["name"],))
    assert deletion.delete_ingredient_master_record(record["id"], confirm=True, user_id="user-a")["ok"]


def test_matching_name_and_buy_as_count_one_reference_per_stored_row(deletion_app):
    record = md.master_record_for_name("ingredients", "user-a", "Tomato")
    add_alias(record, "Red tomato")
    with md.recipe_master_connection(user_id="user-a") as connection:
        connection.execute("UPDATE recipe_ingredients SET buy_as = 'Red tomato' WHERE ingredient_id = ?", (record["id"],))
        connection.execute("UPDATE recipe_ingredient_option_items SET buy_as = 'Tomato', purchasable_item = 'Red tomato' WHERE ingredient_id = ?", (record["id"],))
        expected = connection.execute("SELECT COUNT(*) FROM recipe_ingredients WHERE ingredient_id = ?", (record["id"],)).fetchone()[0]
        expected += connection.execute("SELECT COUNT(*) FROM recipe_ingredient_option_items WHERE ingredient_id = ?", (record["id"],)).fetchone()[0]
    detail = deletion.ingredient_deletion_details([record])[record["id"]]
    assert detail["delete_recipe_count"] == 1
    assert detail["delete_reference_count"] == expected


def test_eligibility_check_and_delete_hold_the_database_write_lock(deletion_app, monkeypatch):
    record = unused_ingredient()
    read_details = deletion._deletion_details
    attempted = []
    def check_competing_write(connection, records):
        with sqlite3.connect(str(md.recipe_master_db_path()), timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("UPDATE recipe_ingredients SET ingredient_id = ? WHERE user_id = 'user-a'", (record["id"],))
        attempted.append(True)
        return read_details(connection, records)
    monkeypatch.setattr(deletion, "_deletion_details", check_competing_write)
    assert deletion.delete_ingredient_master_record(record["id"], confirm=True, user_id="user-a")["ok"]
    assert attempted == [True]


def test_delete_compacts_only_the_owners_store_section_order(deletion_app):
    records = [unused_ingredient(name=f"Unused paprika {index}") for index in range(3)]
    foreign = unused_ingredient(owner="user-b")
    with md.existing_recipe_master_read_connection() as connection:
        before = [dict(row) for row in connection.execute("SELECT id, user_id, store_section, sort_order, updated_at FROM ingredients ORDER BY id")]
    assert deletion.delete_ingredient_master_record(records[1]["id"], confirm=True, user_id="user-a")["ok"]
    with md.existing_recipe_master_read_connection() as connection:
        after = [dict(row) for row in connection.execute("SELECT id, user_id, store_section, sort_order, updated_at FROM ingredients ORDER BY id")]
    assert [row["sort_order"] for row in after if row["id"] in {records[0]["id"], records[2]["id"]}] == [0, 1]
    assert next(row for row in after if row["id"] == foreign["id"]) == next(row for row in before if row["id"] == foreign["id"])
    assert all(row["updated_at"] == next(old["updated_at"] for old in before if old["id"] == row["id"]) for row in after)
