import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service
from PushShoppingList.services.ingredient_unit_service import canonical_unit
from PushShoppingList.services.ingredient_unit_service import normalize_ingredient_unit_fields


@pytest.fixture
def unit_registry_app(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({
            "users": [
                {
                    "user_id": "user-a",
                    "username": "user-a",
                    "email": "user-a@example.com",
                    "account_status": "active",
                },
                {
                    "user_id": "user-b",
                    "username": "user-b",
                    "email": "user-b@example.com",
                    "account_status": "active",
                },
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        master_data,
        "RECIPE_MASTER_DB_PATH",
        tmp_path / "recipe_master.sqlite3",
    )
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_DATA_DIR",
        tmp_path / "guests",
    )
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

    app = create_app()
    app.config.update(TESTING=True)
    return app


def sign_in(client, user_id):
    with client.session_transaction() as active_session:
        active_session["user_id"] = user_id


def registry_for(client):
    response = client.get("/api/master-data/units")
    assert response.status_code == 200
    return response.get_json()["registry"]


def unit_named(registry, name):
    return next(unit for unit in registry["units"] if unit["name"] == name)


def test_create_unit_with_multiple_aliases_persists_and_reaches_editor_menu(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scoops", "sc"],
            },
        )
        assert created.status_code == 201
        payload = created.get_json()
        assert payload["ok"] is True
        assert unit_named(payload["registry"], "scoop")["aliases"] == ["sc", "scoops"]

    with unit_registry_app.test_client() as next_client:
        sign_in(next_client, "user-a")
        persisted = registry_for(next_client)
        assert unit_named(persisted, "scoop")["custom"] is True
        editor = next_client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "user-a",
                "url": "https://example.test/recipes/persistent-unit",
            },
        )
        assert editor.status_code == 200
        soup = BeautifulSoup(editor.get_data(as_text=True), "html.parser")
        editor_registry = json.loads(soup.select_one("#ingredientUnitConfig").string)
        assert unit_named(editor_registry, "scoop")["id"] == payload["unit_id"]
        assert editor_registry["aliases"]["sc"] == "scoop"


def test_edit_custom_name_and_add_remove_aliases_updates_normalization(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        created = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scoops", "scoopful"],
            },
        ).get_json()
        unit_id = created["unit_id"]
        edited = client.put(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "measuring scoop",
                "category": "volume",
                "aliases": ["scoops", "ms"],
            },
        )
        assert edited.status_code == 200
        unit = unit_named(edited.get_json()["registry"], "measuring scoop")
        assert unit["category"] == "volume"
        assert set(unit["aliases"]) == {"scoop", "scoops", "ms"}
        assert "scoopful" not in edited.get_json()["registry"]["aliases"]

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            normalized = normalize_ingredient_unit_fields({
                "ingredient": "protein powder",
                "quantity": "1",
                "unit": "ms",
            })
            assert normalized["unit"] == "measuring scoop"
            assert normalized["unit_id"] == unit_id

        removed = client.patch(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "measuring scoop",
                "category": "volume",
                "aliases": ["ms"],
            },
        ).get_json()
        assert unit_named(removed["registry"], "measuring scoop")["aliases"] == ["ms"]


def test_edit_seeded_unit_keeps_stable_id_and_migrates_recipe_references(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        registry = registry_for(client)
        teaspoon = unit_named(registry, "teaspoon")

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            master_data.sync_recipe_master_records(
                "https://example.test/recipes/seeded-rename",
                recipe_data={
                    "ingredients": [{
                        "ingredient": "salt",
                        "quantity": "1",
                        "unit": "teaspoon",
                    }],
                },
                user_id="user-a",
            )
            recipe_edit_service.save_recipe_output(
                "https://example.test/recipes/seeded-rename",
                {
                    "source_url": "https://example.test/recipes/seeded-rename",
                    "ingredients": [{
                        "ingredient": "salt",
                        "quantity": "1",
                        "unit": "teaspoon",
                        "unit_id": teaspoon["id"],
                    }],
                },
            )

        edited = client.put(
            f'/api/master-data/units/{teaspoon["id"]}',
            json={
                "canonical_name": "measuring teaspoon",
                "category": "volume",
                "aliases": ["tsp", "tsps", "teaspoons"],
            },
        )
        assert edited.status_code == 200
        renamed = unit_named(edited.get_json()["registry"], "measuring teaspoon")
        assert renamed["id"] == teaspoon["id"]
        assert renamed["seeded"] is True
        assert "teaspoon" in renamed["aliases"]

        with master_data.recipe_master_connection() as connection:
            stored = connection.execute(
                """
                SELECT unit, unit_id FROM recipe_ingredients
                 WHERE user_id = ? AND recipe_id = ?
                """,
                (
                    "user-a",
                    master_data.recipe_id_for_url(
                        "https://example.test/recipes/seeded-rename"
                    ),
                ),
            ).fetchone()
        assert stored["unit"] == "measuring teaspoon"
        assert stored["unit_id"] == teaspoon["id"]

        with unit_registry_app.test_request_context("/"):
            session["user_id"] = "user-a"
            assert canonical_unit("teaspoon")["name"] == "measuring teaspoon"
            assert canonical_unit("tsp")["id"] == teaspoon["id"]
            saved_recipe = recipe_edit_service.load_editable_recipe(
                "https://example.test/recipes/seeded-rename"
            )
            assert saved_recipe["recipe"]["ingredients"][0]["unit"] == "measuring teaspoon"
            assert saved_recipe["recipe"]["ingredients"][0]["unit_id"] == teaspoon["id"]

        refreshed = registry_for(client)
        assert unit_named(refreshed, "measuring teaspoon")["id"] == teaspoon["id"]


def test_collisions_and_repeated_submissions_do_not_create_duplicates(
    unit_registry_app,
):
    request_payload = {
        "canonical_name": "scoop",
        "category": "count_package",
        "aliases": ["scp", "scoops"],
    }
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        first = client.post("/api/master-data/units", json=request_payload)
        repeated = client.post("/api/master-data/units", json=request_payload)
        assert first.status_code == 201
        assert repeated.status_code == 200
        assert repeated.get_json()["created"] is False
        assert sum(
            unit["name"] == "scoop"
            for unit in repeated.get_json()["registry"]["units"]
        ) == 1

        canonical_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "SCOOP",
                "category": "volume",
                "aliases": [],
            },
        )
        assert canonical_collision.status_code == 422
        assert "canonical_name" in canonical_collision.get_json()["errors"]

        alias_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "ladle",
                "category": "volume",
                "aliases": ["scp"],
            },
        )
        assert alias_collision.status_code == 422
        assert alias_collision.get_json()["errors"]["aliases"]["0"]

        built_in_collision = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "pour",
                "category": "volume",
                "aliases": ["cup"],
            },
        )
        assert built_in_collision.status_code == 422

        duplicate_aliases = client.post(
            "/api/master-data/units",
            json={
                "canonical_name": "ladle",
                "category": "volume",
                "aliases": ["ld", "LD", ""],
            },
        )
        assert duplicate_aliases.status_code == 422
        assert set(duplicate_aliases.get_json()["errors"]["aliases"]) == {"1", "2"}


def test_registry_is_workspace_isolated_and_unit_routes_require_authorization(
    unit_registry_app,
):
    with unit_registry_app.test_client() as unauthenticated:
        denied = unauthenticated.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": [],
            },
        )
        assert denied.status_code == 401

    with unit_registry_app.test_client() as user_a:
        sign_in(user_a, "user-a")
        created = user_a.post(
            "/api/master-data/units",
            json={
                "canonical_name": "scoop",
                "category": "count_package",
                "aliases": ["scp"],
            },
        ).get_json()
        unit_id = created["unit_id"]

    with unit_registry_app.test_client() as user_b:
        sign_in(user_b, "user-b")
        registry = registry_for(user_b)
        assert all(unit["name"] != "scoop" for unit in registry["units"])
        forbidden_edit = user_b.put(
            f"/api/master-data/units/{unit_id}",
            json={
                "canonical_name": "stolen scoop",
                "category": "volume",
                "aliases": [],
            },
        )
        assert forbidden_edit.status_code == 404
        assert "scoop" not in forbidden_edit.get_data(as_text=True).lower()


def test_units_page_exposes_accessible_persistent_editor_and_import_offer(
    unit_registry_app,
):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get(
            "/admin/master-data/units",
            query_string={"viewer_user_id": "user-a"},
        )
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.select_one("[data-unit-master-add-button]").get_text(strip=True) == "Add Unit"
    dialog = soup.select_one("dialog[data-unit-master-dialog]")
    assert dialog is not None
    assert dialog.select_one("[data-unit-master-name]") is not None
    assert dialog.select_one("[data-unit-master-category-select]") is not None
    assert dialog.select_one("[data-unit-master-alias-chips]") is not None
    assert dialog.select_one("[data-unit-master-save]") is not None
    assert soup.select_one("[data-unit-master-import]") is not None
    assert len(soup.select("[data-unit-master-edit-button]")) >= 30


def test_unit_editor_resets_legacy_button_sizing_and_uses_contextual_save_label():
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/units.js").read_text(encoding="utf-8")
    unit_button_rules = css[
        css.index(".unit-master-page button {"):
        css.index(".unit-master-page button:is(:hover, :focus-visible)")
    ]
    close_button_rules = css[
        css.index(".unit-master-dialog-close {"):
        css.index(".unit-master-editor-grid {")
    ]
    alias_button_rules = css[
        css.index(".unit-master-alias-chip button {"):
        css.index(".unit-master-alias-chip small {")
    ]

    assert "width: auto;" in unit_button_rules
    assert "margin: 0;" in unit_button_rules
    assert "width: 38px;" in close_button_rules
    assert "width: 24px;" in alias_button_rules
    assert 'saveButtonLabel = unit ? "Save Changes" : "Add Unit";' in script
    assert 'saveButton.textContent = saveButtonLabel;' in script


def test_legacy_browser_unit_import_skips_existing_names(unit_registry_app):
    with unit_registry_app.test_client() as client:
        sign_in(client, "user-a")
        imported = client.post(
            "/api/master-data/units/import-local",
            json={"units": ["scoop", "SCOOP", "cup", "ladle"]},
        )
        assert imported.status_code == 200
        payload = imported.get_json()
        assert set(payload["imported"]) == {"scoop", "ladle"}
        assert {item["name"] for item in payload["skipped"]} == {"SCOOP", "cup"}
        assert sum(unit["name"] == "scoop" for unit in payload["registry"]["units"]) == 1
