import json

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


@pytest.fixture
def ingredient_type_app(monkeypatch, tmp_path):
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
    response = client.get("/api/master-data/types")
    assert response.status_code == 200
    return response.get_json()["registry"]


def type_named(registry, name):
    return next(item for item in registry["types"] if item["name"] == name)


def create_type(client, name):
    response = client.post(
        "/api/master-data/types",
        json={"name": name, "active": True},
    )
    assert response.status_code == 201
    return response.get_json()


def test_types_page_matches_master_data_navigation_and_exposes_editors(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        response = client.get("/admin/master-data/types")

    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.title.get_text(strip=True) == "Types"
    assert soup.select_one("[data-type-master-page]") is not None
    assert soup.select_one("h1#typesTitle").get_text(strip=True) == "Types"
    assert soup.select_one("[data-type-master-add-button]").get_text(strip=True) == "Add Type"
    type_category_list = soup.select_one(
        ".unit-master-catalog > .unit-master-category-list.type-master-category-list"
    )
    assert type_category_list is not None
    type_categories = type_category_list.find_all(
        "section",
        class_="type-master-category",
        recursive=False,
    )
    assert len(type_categories) == 1
    assert type_categories[0].has_attr("data-type-master-category")
    assert soup.select_one("dialog[data-type-master-dialog]") is not None
    assert soup.select_one("dialog[data-type-master-usage-dialog]") is not None
    assert len(soup.select("[data-type-master-row]")) == 6
    active_tab = soup.select_one("nav.master-data-tabs a.active")
    assert active_tab.get_text(strip=True) == "Types"
    assert active_tab["href"].startswith("/admin/master-data/types")
    assert soup.select_one('script[src*="/static/js/types.js"]') is not None


def test_custom_type_persists_reaches_editor_and_is_workspace_isolated(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Protein boost")
        custom = type_named(created["registry"], "Protein boost")
        assert custom["custom"] is True
        assert custom["active"] is True

    with ingredient_type_app.test_client() as next_client:
        sign_in(next_client, "user-a")
        assert type_named(registry_for(next_client), "Protein boost")["id"] == custom["id"]
        editor = next_client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "user-a",
                "url": "https://example.test/recipes/type-registry",
            },
        )
        soup = BeautifulSoup(editor.get_data(as_text=True), "html.parser")
        editor_registry = json.loads(soup.select_one("#ingredientTypeConfig").string)
        assert type_named(editor_registry, "Protein boost")["id"] == custom["id"]

    with ingredient_type_app.test_client() as other_client:
        sign_in(other_client, "user-b")
        assert all(
            item["name"] != "Protein boost"
            for item in registry_for(other_client)["types"]
        )
        forbidden = other_client.patch(
            f'/api/master-data/types/{custom["id"]}',
            json={"name": "Taken", "active": True},
        )
        assert forbidden.status_code == 404


def test_rename_migrates_usage_and_safe_delete_requires_deactivation(
    ingredient_type_app,
):
    recipe_url = "https://example.test/recipes/protein-shake"
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Protein boost")
        type_id = created["type_id"]
        master_data.sync_recipe_master_records(
            recipe_url,
            recipe_data={
                "recipe_title": "Protein Shake",
                "ingredients": [{
                    "ingredient": "protein powder",
                    "quantity": "1",
                    "unit": "scoop",
                    "section": "Protein boost",
                }],
            },
            user_id="user-a",
        )

        registry = registry_for(client)
        assert type_named(registry, "Protein boost")["recipe_count"] == 1
        references = client.get(f"/api/master-data/types/{type_id}/references")
        assert references.status_code == 200
        reference_payload = references.get_json()
        assert reference_payload["total"] == 1
        assert reference_payload["total_reference_count"] == 1
        assert reference_payload["references"][0]["matches"][0]["ingredient_name"] == (
            "protein powder"
        )

        renamed = client.patch(
            f"/api/master-data/types/{type_id}",
            json={"name": "Protein", "active": True},
        )
        assert renamed.status_code == 200
        assert type_named(renamed.get_json()["registry"], "Protein")["recipe_count"] == 1
        with master_data.recipe_master_connection() as connection:
            stored = connection.execute(
                "SELECT ingredient_type FROM recipe_ingredients WHERE user_id = ?",
                ("user-a",),
            ).fetchone()
            normalized_option = connection.execute(
                """
                SELECT item.ingredient_type
                  FROM recipe_ingredient_option_items item
                  JOIN recipe_ingredient_options option ON option.id = item.option_id
                  JOIN recipe_ingredient_requirements requirement
                    ON requirement.id = option.requirement_id
                 WHERE requirement.user_id = ?
                """,
                ("user-a",),
            ).fetchone()
        assert stored["ingredient_type"] == "Protein"
        assert normalized_option["ingredient_type"] == "Protein"

        blocked = client.delete(f"/api/master-data/types/{type_id}")
        assert blocked.status_code == 409
        assert "Deactivate it instead" in blocked.get_json()["error"]

        deactivated = client.patch(
            f"/api/master-data/types/{type_id}",
            json={"name": "Protein", "active": False},
        )
        assert deactivated.status_code == 200
        assert type_named(deactivated.get_json()["registry"], "Protein")["active"] is False


def test_unused_custom_type_can_be_deleted_and_built_ins_are_protected(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        created = create_type(client, "Finisher")
        deleted = client.delete(f'/api/master-data/types/{created["type_id"]}')
        assert deleted.status_code == 200
        assert deleted.get_json()["deleted"] is True
        assert all(
            item["name"] != "Finisher"
            for item in deleted.get_json()["registry"]["types"]
        )

        main_disabled = client.patch(
            "/api/master-data/types/main",
            json={"name": "Main", "active": False},
        )
        assert main_disabled.status_code == 422
        built_in_delete = client.delete("/api/master-data/types/garnish")
        assert built_in_delete.status_code == 422


def test_legacy_import_is_persistent_and_duplicate_safe(ingredient_type_app):
    with ingredient_type_app.test_client() as client:
        sign_in(client, "user-a")
        imported = client.post(
            "/api/master-data/types/import-local",
            json={"types": ["Protein", "protein", "Finisher", ""]},
        )
        assert imported.status_code == 200
        payload = imported.get_json()
        assert payload["imported"] == ["Protein", "Finisher"]
        assert payload["skipped"] == ["protein"]
        assert {item["name"] for item in payload["registry"]["types"]} >= {
            "Protein",
            "Finisher",
        }


def test_type_mutations_require_authentication_and_validate_names(
    ingredient_type_app,
):
    with ingredient_type_app.test_client() as client:
        denied = client.post(
            "/api/master-data/types",
            json={"name": "Private", "active": True},
        )
        assert denied.status_code == 401

        sign_in(client, "user-a")
        empty = client.post(
            "/api/master-data/types",
            json={"name": " ", "active": True},
        )
        assert empty.status_code == 422
        too_long = client.post(
            "/api/master-data/types",
            json={"name": "x" * 41, "active": True},
        )
        assert too_long.status_code == 422
