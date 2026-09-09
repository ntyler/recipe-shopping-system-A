"""Alias ownership follows stable Equipment IDs throughout saves and explicit merges."""

import sqlite3

import pytest

from PushShoppingList.services import equipment_registry_service as registry
from PushShoppingList.services import master_image_preview_service as image_previews
from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services import recipe_master_data_service as md
from test_recipe_master_data_routes import configure_master_data_app, sign_in


ALIAS_NAME = "9-inch cake pan"
ALIAS_KEY = "9 inch cake pan"


@pytest.fixture
def cake_pans(monkeypatch, tmp_path):
    app, database, _ = configure_master_data_app(monkeypatch, tmp_path)
    ids = {}
    with md.recipe_master_connection(user_id="user-a") as connection:
        for name in ("Cake pan", ALIAS_NAME, "Sheet pan"):
            ids[name] = md.upsert_master_record(
                connection, "equipment", "user-a", name, equipment_section="BAKEWARE",
            )["id"]
        # Deliberately model a historical duplicate row; application validation
        # must not invalidate an already-owned alias because of that row's name.
        registry._ensure_aliases(connection)
        connection.execute(
            "INSERT INTO recipe_equipment(user_id, recipe_id, equipment_id, original_recipe_text) VALUES(?, ?, ?, ?)",
            ("user-a", "cake-recipe", ids["Cake pan"], "Cake pan, greased"),
        )
        connection.execute(
            "UPDATE equipment SET image_url = ?, image_path = ? WHERE id = ?",
            ("/static/original-pan.png", "original-pan.png", ids["Cake pan"]),
        )
    return app, database, ids


def seed_alias(database, equipment_id, name=ALIAS_NAME, key=ALIAS_KEY):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """INSERT INTO equipment_aliases
               (user_id, equipment_id, alias_name, alias_key, created_at, updated_at)
               VALUES('user-a', ?, ?, ?, 'before', 'before')""",
            (equipment_id, name, key),
        ).lastrowid


def alias_record(database, alias_id):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM equipment_aliases WHERE id = ?", (alias_id,)).fetchone())


def reference_rows(database):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT id, recipe_id, equipment_id, original_recipe_text FROM recipe_equipment ORDER BY id",
        ).fetchall()


def replacement_image(app, equipment_id):
    with app.app_context():
        token = image_previews._image_serializer("equipment").dumps({
            "equipment_id": equipment_id, "user_id": "user-a",
            "image_url": "/static/replacement-pan.png", "image_path": "replacement-pan.png",
        })
    return {"action": "replace", "token": token}


def test_unchanged_alias_owned_by_current_id_is_valid_despite_duplicate_equipment_name(cake_pans):
    _, database, ids = cake_pans
    current_id = ids["Cake pan"]
    alias_id = seed_alias(database, current_id)
    before = database.read_bytes()
    editor = registry.equipment_editor_record(current_id, user_id="user-a")
    assert editor["aliases"] == [ALIAS_NAME]
    result = registry.update_equipment_master_record(current_id, {
        "name": editor["name"], "equipment_type": editor["equipment_type"], "aliases": editor["aliases"],
    }, user_id="user-a")
    assert result["ok"], result
    assert result["record"]["id"] == current_id
    assert result["record"]["aliases"] == [ALIAS_NAME]
    assert not result["record"]["changed"]
    assert alias_record(database, alias_id)["equipment_id"] == current_id
    assert database.read_bytes() == before


@pytest.mark.parametrize("include_aliases", [False, True], ids=["aliases-omitted", "aliases-submitted"])
@pytest.mark.parametrize("field", ["image", "equipment_type", "name"])
def test_unrelated_field_edit_preserves_existing_alias_owner_and_references(cake_pans, field, include_aliases):
    app, database, ids = cake_pans
    current_id = ids["Cake pan"]
    alias_id = seed_alias(database, current_id)
    original_alias = alias_record(database, alias_id)
    original_references = reference_rows(database)
    duplicate = md.master_record_for_id("equipment", ids[ALIAS_NAME], user_id="user-a")
    payload = {field: {
        "image": replacement_image(app, current_id), "equipment_type": "COOKWARE", "name": "Family cake pan",
    }[field]}
    if include_aliases:
        payload["aliases"] = [ALIAS_NAME]
    with app.app_context():
        result = registry.update_equipment_master_record(current_id, payload, user_id="user-a")
    assert result["ok"], result
    saved = result["record"]
    assert saved["id"] == current_id
    assert saved["name"] == ("Family cake pan" if field == "name" else "Cake pan")
    assert saved["equipment_type"] == ("COOKWARE" if field == "equipment_type" else "BAKEWARE")
    assert saved["image_url"] == ("/static/replacement-pan.png" if field == "image" else "/static/original-pan.png")
    assert saved["aliases"] == [ALIAS_NAME]
    assert alias_record(database, alias_id) == original_alias
    assert reference_rows(database) == original_references
    assert md.master_record_for_id("equipment", ids[ALIAS_NAME], user_id="user-a") == duplicate


@pytest.mark.parametrize("submitted", [
    ["  9-INCH   cake\tPAN  "],
    [ALIAS_NAME, "9 INCH CAKE PAN", "  9-inch  cake pan  "],
])
def test_normalized_alias_variants_keep_current_owner_and_alias_id(cake_pans, submitted):
    _, database, ids = cake_pans
    alias_id = seed_alias(database, ids["Cake pan"])
    result = registry.update_equipment_master_record(ids["Cake pan"], {"aliases": submitted}, user_id="user-a")
    assert result["ok"], result
    assert len(result["record"]["aliases"]) == 1
    stored = alias_record(database, alias_id)
    assert stored["equipment_id"] == ids["Cake pan"]
    assert stored["alias_key"] == ALIAS_KEY
    assert stored["status"] == "active"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM equipment_aliases WHERE alias_key = ?", (ALIAS_KEY,)).fetchone()[0] == 1


@pytest.mark.parametrize("conflict_kind", ["alias", "name"])
@pytest.mark.parametrize("submitted", [ALIAS_NAME, "  9-INCH   cake\tPAN  "])
def test_genuine_conflict_reports_exact_owner_and_rejects_every_pending_change(cake_pans, conflict_kind, submitted):
    app, database, ids = cake_pans
    current_id, conflicting_id = ids["Cake pan"], ids[ALIAS_NAME]
    alias_id = seed_alias(database, conflicting_id) if conflict_kind == "alias" else None
    before = database.read_bytes()
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.patch(f"/api/master-data/equipment/{current_id}", json={
            "name": "Family cake pan", "equipment_type": "COOKWARE", "aliases": ["New alias", submitted],
            "image": replacement_image(app, current_id),
        })
    assert response.status_code == 409
    result = response.json
    cleaned_alias = md.clean_text(submitted)
    assert result["error"] == f'“{cleaned_alias}” is currently assigned to “{ALIAS_NAME}”.'
    expected_conflict = {
        "alias_name": cleaned_alias, "alias_key": ALIAS_KEY, "alias_id": alias_id,
        "equipment_id": conflicting_id, "equipment_name": ALIAS_NAME,
        "current_equipment_id": current_id, "conflict_kind": conflict_kind,
    }
    if conflict_kind == "alias":
        expected_conflict.update(alias_status="active", stored_alias_name=ALIAS_NAME, stored_alias_key=ALIAS_KEY)
    assert result["alias_conflicts"] == [expected_conflict]
    assert database.read_bytes() == before


def test_matching_display_names_do_not_grant_another_records_alias_ownership(cake_pans):
    _, database, ids = cake_pans
    alias_id = seed_alias(database, ids[ALIAS_NAME])
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE equipment SET display_name_override = 'Cake pan' WHERE id = ?", (ids[ALIAS_NAME],))
    before = database.read_bytes()
    result = registry.update_equipment_master_record(ids["Cake pan"], {
        "name": "Cake pan", "aliases": [ALIAS_NAME],
    }, user_id="user-a")
    assert result["status"] == 409
    assert result["alias_conflicts"] == [{
        "alias_name": ALIAS_NAME, "alias_key": ALIAS_KEY, "alias_id": alias_id,
        "equipment_id": ids[ALIAS_NAME], "equipment_name": "Cake pan",
        "current_equipment_id": ids["Cake pan"], "conflict_kind": "alias",
        "alias_status": "active", "stored_alias_name": ALIAS_NAME, "stored_alias_key": ALIAS_KEY,
    }]
    assert result["error"] == '“9-inch cake pan” is currently assigned to “Cake pan”.'
    assert database.read_bytes() == before


def test_alias_equal_to_current_display_name_still_checks_the_actual_alias_owner(cake_pans):
    _, database, ids = cake_pans
    alias_id = seed_alias(database, ids[ALIAS_NAME], "Cake pan", "cake pan")
    before = database.read_bytes()
    result = registry.update_equipment_master_record(ids["Cake pan"], {
        "name": "Cake pan", "aliases": ["  CAKE   PAN  "], "equipment_type": "COOKWARE",
    }, user_id="user-a")
    assert result["status"] == 409, result
    conflict, = result["alias_conflicts"]
    assert conflict["alias_key"] == "cake pan"
    assert conflict["alias_id"] == alias_id
    assert conflict["equipment_id"] == ids[ALIAS_NAME]
    assert conflict["current_equipment_id"] == ids["Cake pan"]
    assert database.read_bytes() == before


def test_retired_alias_owned_by_another_id_cannot_be_silently_reassigned(cake_pans):
    _, database, ids = cake_pans
    alias_id = seed_alias(database, ids[ALIAS_NAME])
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE equipment_aliases SET status = 'retired' WHERE id = ?", (alias_id,))
    before = database.read_bytes()
    result = registry.update_equipment_master_record(ids["Cake pan"], {"aliases": [ALIAS_NAME]}, user_id="user-a")
    assert result["status"] == 409, result
    conflict, = result["alias_conflicts"]
    assert conflict["alias_id"] == alias_id
    assert conflict["alias_status"] == "retired"
    assert conflict["equipment_id"] == ids[ALIAS_NAME]
    assert database.read_bytes() == before


@pytest.mark.parametrize("include_aliases", [False, True])
def test_existing_alias_equal_to_current_name_is_not_silently_retired(cake_pans, include_aliases):
    _, database, ids = cake_pans
    alias_id = seed_alias(database, ids["Cake pan"], "Cake pan", "cake pan")
    original = alias_record(database, alias_id)
    payload = {"equipment_type": "COOKWARE"}
    if include_aliases:
        payload["aliases"] = ["Cake pan"]
    result = registry.update_equipment_master_record(ids["Cake pan"], payload, user_id="user-a")
    assert result["ok"], result
    assert result["record"]["aliases"] == ["Cake pan"]
    assert alias_record(database, alias_id) == original


def test_merge_duplicate_explicitly_resolves_conflict_and_preserves_alias_id_and_recipe_text(cake_pans, monkeypatch):
    app, database, ids = cake_pans
    target_id, duplicate_id = ids["Cake pan"], ids[ALIAS_NAME]
    alias_id = seed_alias(database, duplicate_id)
    monkeypatch.setenv("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED", "true")
    with md.recipe_master_connection(user_id="user-a") as connection:
        requirements.ensure_structured_equipment_schema(connection, authorized=True)
        connection.execute(
            "INSERT INTO recipe_equipment(user_id, recipe_id, equipment_id, original_recipe_text) VALUES(?, ?, ?, ?)",
            ("user-a", "duplicate-recipe", duplicate_id, "9-inch cake pan, buttered"),
        )
        requirement_id = connection.execute(
            """INSERT INTO recipe_equipment_requirements
               (requirement_id, user_id, recipe_id, created_at, updated_at)
               VALUES('requirement', 'user-a', 'duplicate-recipe', 'before', 'before')""",
        ).lastrowid
        connection.execute(
            """INSERT INTO recipe_equipment_options
               (option_id, user_id, requirement_id, equipment_id, matched_alias_id, created_at, updated_at)
               VALUES('option', 'user-a', ?, ?, ?, 'before', 'before')""",
            (requirement_id, duplicate_id, alias_id),
        )
    monkeypatch.setenv("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED", "false")
    before = database.read_bytes()
    original_references = reference_rows(database)
    with app.test_client() as client:
        sign_in(client, "user-a")
        conflict = client.patch(f"/api/master-data/equipment/{target_id}", json={"aliases": [ALIAS_NAME]})
        assert conflict.status_code == 409
        assert conflict.json["alias_conflicts"][0]["equipment_id"] == duplicate_id
        assert database.read_bytes() == before
        # Only the deliberate merge request is authorized to change ownership
        # and recipe references; merely reporting or saving the conflict is not.
        response = client.post(f"/admin/master-data/equipment/{duplicate_id}/merge", json={
            "target_equipment_id": target_id,
        }, headers={"X-Requested-With": "fetch"})
        assert response.status_code == 200, response.json
        assert response.json["result"]["target_id"] == target_id
        assert response.json["result"]["moved_reference_count"] == 2
        saved = client.patch(f"/api/master-data/equipment/{target_id}", json={"aliases": [ALIAS_NAME]})
        assert saved.status_code == 200, saved.json
    stored = alias_record(database, alias_id)
    assert stored["equipment_id"] == target_id
    assert stored["alias_key"] == ALIAS_KEY
    assert stored["status"] == "active"
    assert md.master_record_for_id("equipment", duplicate_id, user_id="user-a") is None
    assert reference_rows(database) == [(row_id, recipe_id, target_id, text) for row_id, recipe_id, _, text in original_references]
    with md.existing_recipe_master_read_connection() as connection:
        option = connection.execute("SELECT equipment_id, matched_alias_id FROM recipe_equipment_options").fetchone()
        assert tuple(option) == (target_id, alias_id)


def test_merge_preserves_source_owned_alias_despite_uninvolved_equipment_name_overlap(cake_pans):
    _, database, ids = cake_pans
    source_id, target_id, uninvolved_id = ids["Cake pan"], ids["Sheet pan"], ids[ALIAS_NAME]
    alias_id = seed_alias(database, source_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO recipe_equipment(user_id, recipe_id, equipment_id, original_recipe_text) VALUES(?, ?, ?, ?)",
            ("user-a", "uninvolved-recipe", uninvolved_id, "9-inch cake pan, lined"),
        )
    uninvolved = md.master_record_for_id("equipment", uninvolved_id, user_id="user-a")
    original_references = reference_rows(database)
    result = registry.merge_equipment_master_records(source_id, target_id, user_id="user-a")
    assert result["ok"], result
    assert result["moved_reference_count"] == 1
    assert alias_record(database, alias_id)["equipment_id"] == target_id
    assert md.master_record_for_id("equipment", source_id, user_id="user-a") is None
    assert md.master_record_for_id("equipment", uninvolved_id, user_id="user-a") == uninvolved
    assert reference_rows(database) == [
        (row_id, recipe_id, target_id if equipment_id == source_id else equipment_id, text)
        for row_id, recipe_id, equipment_id, text in original_references
    ]


def test_merge_rejects_third_records_actual_alias_ownership_atomically(cake_pans):
    _, database, ids = cake_pans
    source_id, target_id, third_id = ids["Cake pan"], ids["Sheet pan"], ids[ALIAS_NAME]
    source_alias_id = seed_alias(database, source_id)
    third_alias_id = seed_alias(database, third_id, "Cake pan", "cake pan")
    before = database.read_bytes()
    result = registry.merge_equipment_master_records(source_id, target_id, user_id="user-a")
    assert result["status"] == 409, result
    assert alias_record(database, source_alias_id)["equipment_id"] == source_id
    assert alias_record(database, third_alias_id)["equipment_id"] == third_id
    assert database.read_bytes() == before


def test_merge_options_requested_target_id_overrides_name_search_and_page_limit(cake_pans):
    app, database, ids = cake_pans
    source_id, target_id = ids["Cake pan"], ids[ALIAS_NAME]
    before = database.read_bytes()
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(f"/api/master-data/equipment/{source_id}/merge-options", query_string={
            "target_equipment_id": str(target_id), "search": "Sheet", "limit": "1",
        })
    assert response.status_code == 200, response.json
    assert response.json["source"]["equipment_id"] == source_id
    target, = response.json["equipment"]
    assert target["id"] == target_id
    assert target["equipment_id"] == target_id
    assert target["name"] == ALIAS_NAME
    assert database.read_bytes() == before


def test_merge_options_rejects_source_id_as_requested_target_without_changes(cake_pans):
    app, database, ids = cake_pans
    source_id = ids["Cake pan"]
    before = database.read_bytes()
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(f"/api/master-data/equipment/{source_id}/merge-options", query_string={
            "target_equipment_id": str(source_id),
        })
    assert response.status_code == 404
    assert response.json == {"ok": False, "error": "Equipment was not found."}
    assert database.read_bytes() == before


def test_merge_options_rejects_foreign_target_despite_forged_workspace_without_exposure(cake_pans):
    app, database, ids = cake_pans
    with md.recipe_master_connection(user_id="user-b") as connection:
        foreign_id = md.upsert_master_record(
            connection, "equipment", "user-b", "Private cake pan", equipment_section="BAKEWARE",
        )["id"]
    before = database.read_bytes()
    with app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(f"/api/master-data/equipment/{ids['Cake pan']}/merge-options", query_string={
            "target_equipment_id": str(foreign_id), "user_id": "user-b", "scope": "all",
        })
    assert response.status_code == 404
    assert response.json == {"ok": False, "error": "Equipment was not found."}
    assert "Private cake pan" not in response.get_data(as_text=True)
    assert database.read_bytes() == before
