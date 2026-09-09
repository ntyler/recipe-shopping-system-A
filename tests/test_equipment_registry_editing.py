"""Atomic registry edits and reference-preserving Equipment operations."""

import sqlite3

import pytest

from PushShoppingList.services import equipment_registry_service as registry
from PushShoppingList.services import recipe_master_data_service as md
from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from test_recipe_master_data_routes import configure_master_data_app, sign_in, set_master_data_admin_access


@pytest.fixture
def equipment(monkeypatch, tmp_path):
    app, database, _ = configure_master_data_app(monkeypatch, tmp_path)
    ids = {}
    with md.recipe_master_connection(user_id="user-a") as connection:
        for owner, name, section in (
            ("user-a", "Pot", "COOKWARE"), ("user-a", "Pan", "COOKWARE"),
            ("user-a", "Skillet", "COOKWARE"), ("user-a", "Tray", "BAKEWARE"),
            ("user-b", "Secret pot", "COOKWARE"),
        ):
            result = md.upsert_master_record(connection, "equipment", owner, name, equipment_section=section)
            ids[name] = result["id"]
    return app, database, ids


def rows(database, owner="user-a", section="COOKWARE"):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT * FROM equipment WHERE user_id = ? AND equipment_section = ? ORDER BY sort_order, id", (owner, section),
        )]


def test_atomic_edit_preserves_identity_aliases_and_source_destination_order(equipment):
    _, database, ids = equipment
    before = rows(database)
    order = [row["id"] for row in before]
    result = registry.update_equipment_master_record(ids["Pot"], {
        "name": "Family stockpot", "aliases": ["Soup pot", "STOCK POT"], "equipment_section": "BAKEWARE",
        "order": {"position": 1, "expected_ids": order},
    }, user_id="user-a")
    assert result["ok"]
    saved = result["record"]
    assert saved["name"] == "Family stockpot"
    assert saved["detected_name"] == "Pot"
    assert saved["aliases"] == ["Soup pot", "STOCK POT"]
    assert saved["sort_order"] == 0 and saved["section_count"] == 2
    assert [row["id"] for row in rows(database, section="BAKEWARE")] == [ids["Pot"], ids["Tray"]]
    assert [row["sort_order"] for row in rows(database)] == [0, 1]
    detected = rows(database, section="BAKEWARE")[0]
    assert detected["name"] == "Pot" and detected["normalized_name"] == "pot"
    listed = md.list_equipment(user_id="user-a", sort="manual_order")
    assert [row["id"] for row in listed if row["equipment_section"] == "BAKEWARE"] == [ids["Pot"], ids["Tray"]]
    with md.existing_recipe_master_read_connection() as connection:
        assert md.recipe_master_table_exists(connection, "equipment_aliases")
        assert not md.recipe_master_table_exists(connection, "recipe_equipment_requirements")


@pytest.mark.parametrize("change,status", [
    ({"aliases": ["Pan"]}, 409), ({"name": "Pan"}, 409),
    ({"aliases": [""]}, 400), ({"aliases": "pot"}, 400),
    ({"equipment_section": "unknown"}, 400), ({"name": ""}, 400),
    ({"order": {"position": True, "expected_ids": [1]}}, 400),
    ({"order": {"position": 1, "expected_ids": [1]}}, 409),
])
def test_validation_and_stale_order_reject_all_pending_fields(equipment, change, status):
    _, database, ids = equipment
    before = database.read_bytes()
    result = registry.update_equipment_master_record(ids["Pot"], {
        "name": "Family pot", "equipment_section": "BAKEWARE", "aliases": ["Stockpot"], **change,
    }, user_id="user-a")
    assert result["status"] == status
    assert database.read_bytes() == before


def test_order_conflicts_and_database_failure_leave_row_and_aliases_unchanged(equipment):
    _, database, ids = equipment
    ordered = [row["id"] for row in rows(database)]
    original_times = {row["id"]: row["updated_at"] for row in rows(database)}
    result = registry.move_equipment_master_record(ids["Skillet"], 1, ordered, user_id="user-a")
    assert result["ok"]
    assert result["ordered_ids"] == [ids["Skillet"], ids["Pot"], ids["Pan"]]
    assert {row["id"]: row["updated_at"] for row in rows(database)} == original_times
    assert registry.move_equipment_master_record(ids["Pan"], 1, ordered, user_id="user-a")["status"] == 409
    with sqlite3.connect(database) as connection:
        connection.execute(f"""CREATE TRIGGER reject_equipment_order BEFORE UPDATE OF sort_order ON equipment
            WHEN NEW.id = {ids['Pot']} AND NEW.sort_order = 0 BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    before = database.read_bytes()
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        registry.update_equipment_master_record(ids["Pot"], {
            "name": "Changed pot", "aliases": ["Changed alias"],
            "order": {"position": 1, "expected_ids": result["ordered_ids"]},
        }, user_id="user-a")
    assert database.read_bytes() == before


def test_append_delete_type_move_and_migration_are_compact(equipment):
    _, database, ids = equipment
    registry.update_equipment_master_record(ids["Pot"], {"equipment_section": "BAKEWARE"}, user_id="user-a")
    assert [row["id"] for row in rows(database, section="BAKEWARE")] == [ids["Tray"], ids["Pot"]]
    assert registry.delete_equipment_master_record(ids["Pan"], confirm=True, user_id="user-a")["ok"]
    with md.recipe_master_connection(user_id="user-a") as connection:
        spare = md.upsert_master_record(connection, "equipment", "user-a", "Spare pan", equipment_section="COOKWARE")["id"]
        assert md.migrate_equipment_order(connection) == 0
    assert [row["id"] for row in rows(database)] == [ids["Skillet"], spare]
    assert [row["sort_order"] for row in rows(database)] == [0, 1]


def test_manual_misc_type_survives_schema_repair_and_recipe_reimport(equipment):
    _, database, ids = equipment
    assert registry.update_equipment_master_record(ids["Pot"], {"equipment_section": "MISC"}, user_id="user-a")["ok"]
    with md.recipe_master_connection(user_id="user-a") as connection:
        md.upsert_master_record(connection, "equipment", "user-a", "Pot", equipment_section="COOKWARE")
    assert rows(database, section="MISC")[0]["id"] == ids["Pot"]


def test_duplicate_aliases_are_normalized_and_readding_preserves_identity(equipment):
    _, _, ids = equipment
    result = registry.update_equipment_master_record(ids["Pot"], {"aliases": ["Stock-pot", "Stock pot"]}, user_id="user-a")
    assert result["record"]["aliases"] == ["Stock pot"]
    with md.existing_recipe_master_read_connection() as connection:
        alias_id = connection.execute("SELECT id FROM equipment_aliases").fetchone()[0]
    registry.update_equipment_master_record(ids["Pot"], {"aliases": []}, user_id="user-a")
    registry.update_equipment_master_record(ids["Pot"], {"aliases": ["stock pot"]}, user_id="user-a")
    with md.existing_recipe_master_read_connection() as connection:
        assert connection.execute("SELECT id FROM equipment_aliases WHERE status='active'").fetchone()[0] == alias_id


def test_delete_requires_confirmation_and_blocks_legacy_or_foreign_references(equipment):
    _, database, ids = equipment
    assert registry.delete_equipment_master_record(ids["Pot"], user_id="user-a")["status"] == 400
    with md.recipe_master_connection(user_id="user-a") as connection:
        connection.execute("INSERT INTO recipe_equipment(user_id,recipe_id,equipment_id) VALUES(?,?,?)", ("user-a", "own recipe", ids["Pot"]))
        connection.execute("INSERT INTO recipe_equipment(user_id,recipe_id,equipment_id) VALUES(?,?,?)", ("user-b", "private recipe", ids["Pan"]))
    before = database.read_bytes()
    for name in ("Pot", "Pan"):
        assert registry.delete_equipment_master_record(ids[name], confirm=True, user_id="user-a")["status"] == 409
    assert registry.merge_equipment_master_records(ids["Pan"], ids["Skillet"], user_id="user-a")["status"] == 409
    assert database.read_bytes() == before


def test_merge_preserves_recipe_text_and_reimports_resolve_surviving_alias(equipment):
    _, database, ids = equipment
    with md.recipe_master_connection(user_id="user-a") as connection:
        connection.execute("INSERT INTO recipe_equipment(user_id,recipe_id,equipment_id,original_recipe_text) VALUES(?,?,?,?)",
                           ("user-a", "recipe", ids["Pot"], "Pot, optional"))
    registry.update_equipment_master_record(ids["Pot"], {"name": "My pot", "aliases": ["Soup vessel"]}, user_id="user-a")
    result = registry.merge_equipment_master_records(ids["Pot"], ids["Pan"], user_id="user-a")
    assert result["ok"] and result["moved_reference_count"] == 1
    assert set(result["record"]["aliases"]) == {"pot", "My pot", "Soup vessel"}
    assert md.master_record_for_id("equipment", ids["Pot"], user_id="user-a") is None
    with md.recipe_master_connection(user_id="user-a") as connection:
        row = connection.execute("SELECT equipment_id,original_recipe_text FROM recipe_equipment WHERE recipe_id='recipe'").fetchone()
        assert tuple(row) == (ids["Pan"], "Pot, optional")
        assert md.upsert_master_record(connection, "equipment", "user-a", "Pot")["id"] == ids["Pan"]
    assert md.count_equipment(user_id="user-a") == 3


def test_merge_dialog_form_submission_uses_selected_target(equipment):
    app, _, ids = equipment
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.post(f"/admin/master-data/equipment/{ids['Pot']}/merge", data={
            "target_equipment_id": str(ids["Pan"]), "redirect_url": "/admin/master-data/equipment",
        }, headers={"X-Requested-With": "fetch"})
        assert response.status_code == 200
        assert response.json["result"]["target_id"] == ids["Pan"]


def test_structured_alias_ids_and_options_survive_edit_and_merge(equipment, monkeypatch):
    _, _, ids = equipment
    monkeypatch.setenv("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED", "true")
    registry.update_equipment_master_record(ids["Pot"], {"aliases": ["Soup vessel"]}, user_id="user-a")
    with md.recipe_master_connection(user_id="user-a") as connection:
        requirements.ensure_structured_equipment_schema(connection, authorized=True)
        alias_id = connection.execute("SELECT id FROM equipment_aliases WHERE equipment_id=?", (ids["Pot"],)).fetchone()[0]
        req_id = connection.execute("INSERT INTO recipe_equipment_requirements(requirement_id,user_id,recipe_id,created_at,updated_at) VALUES('req','user-a','recipe','now','now')").lastrowid
        connection.execute("""INSERT INTO recipe_equipment_options(option_id,user_id,requirement_id,equipment_id,matched_alias_id,created_at,updated_at)
                              VALUES('option','user-a',?,?,?,'now','now')""", (req_id, ids["Pot"], alias_id))
    monkeypatch.setenv("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED", "false")
    assert registry.delete_equipment_master_record(ids["Pot"], confirm=True, user_id="user-a")["status"] == 409
    assert registry.update_equipment_master_record(ids["Pot"], {"aliases": []}, user_id="user-a")["ok"]
    assert registry.merge_equipment_master_records(ids["Pot"], ids["Pan"], user_id="user-a")["ok"]
    with md.existing_recipe_master_read_connection() as connection:
        alias = connection.execute("SELECT id,equipment_id,status FROM equipment_aliases WHERE id=?", (alias_id,)).fetchone()
        assert tuple(alias) == (alias_id, ids["Pan"], "retired")
        option = connection.execute("SELECT equipment_id,matched_alias_id FROM recipe_equipment_options").fetchone()
        assert tuple(option) == (ids["Pan"], alias_id)


@pytest.mark.parametrize("admin", [False, True])
def test_new_http_surfaces_ignore_forged_workspace_and_keep_foreign_database_unchanged(equipment, admin):
    app, database, ids = equipment
    set_master_data_admin_access("user-a", admin)
    with app.test_client() as client:
        sign_in(client, "user-a")
        before = database.read_bytes()
        foreign = ids["Secret pot"]
        for method, path, payload in (
            ("PATCH", f"/api/master-data/equipment/{foreign}", {"name": "Leak"}),
            ("PATCH", f"/api/master-data/equipment/{foreign}/order", {"position": 1, "expected_ids": [foreign]}),
            ("POST", f"/admin/master-data/equipment/{foreign}/delete", {"confirm": True}),
            ("POST", f"/admin/master-data/equipment/{ids['Pot']}/merge", {"target_equipment_id": foreign}),
            ("GET", f"/api/master-data/equipment/{foreign}/editor", None),
            ("GET", f"/api/master-data/equipment/{foreign}/merge-options", None),
        ):
            response = client.open(path + "?scope=all&user_id=user-b", method=method, json=payload)
            assert response.status_code == 404
            assert "Secret pot" not in response.get_data(as_text=True)
        assert database.read_bytes() == before
        response = client.patch(f"/api/master-data/equipment/{ids['Pot']}?user_id=user-b", json={
            "display_name": "My pot", "equipment_type": "BAKEWARE", "aliases": ["Family pot"], "user_id": "user-b",
        })
        assert response.status_code == 200
        assert response.json["record"]["equipment_type"] == "BAKEWARE"
        assert rows(database, "user-b")[0]["display_name_override"] == ""
