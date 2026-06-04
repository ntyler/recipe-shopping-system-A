import json

from flask import render_template

from PushShoppingList.app import create_app
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def configure_user_data(monkeypatch, tmp_path, admin_email="admin@example.com"):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(user_account_service, "ADMIN_EMAIL", admin_email.lower())


def create_user(user_id, email):
    return {
        "user_id": user_id,
        "username": email,
        "email": email,
        "password_hash": "",
        "avatar_path": "",
        "created_at": "2026-06-03T00:00:00Z",
        "updated_at": "2026-06-03T00:00:00Z",
    }


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def store_data_dir(tmp_path, user_id):
    return tmp_path / "user_data" / user_id / "recipe-extractor" / "data"


def write_store_settings(tmp_path, user_id, payload):
    data_dir = store_data_dir(tmp_path, user_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "store_settings.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def read_store_settings(tmp_path, user_id):
    return json.loads((store_data_dir(tmp_path, user_id) / "store_settings.json").read_text(encoding="utf-8"))


def legacy_store_data_dir(tmp_path):
    return tmp_path / "legacy-extractor" / "data"


def write_legacy_store_settings(tmp_path, payload):
    data_dir = legacy_store_data_dir(tmp_path)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "store_settings.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def read_legacy_store_settings(tmp_path):
    return json.loads((legacy_store_data_dir(tmp_path) / "store_settings.json").read_text(encoding="utf-8"))


def read_store_credentials(tmp_path, user_id):
    credentials_file = store_data_dir(tmp_path, user_id) / "store_credentials.json"
    return json.loads(credentials_file.read_text(encoding="utf-8"))


def seed_user_and_store(monkeypatch, tmp_path, user):
    configure_user_data(monkeypatch, tmp_path)
    user_account_service.save_users({"users": [user]})
    write_store_settings(
        tmp_path,
        user["user_id"],
        {
            "stores": {
                "aldi": {
                    "label": "Aldi",
                    "url": "https://old.example/search?q=",
                    "urlStoreSelector": "https://old.example/stores",
                },
            },
            "enabled_stores": ["aldi"],
        },
    )


def test_non_admin_can_only_update_store_credentials(monkeypatch, tmp_path):
    user = create_user("regular-user", "user@example.com")
    seed_user_and_store(monkeypatch, tmp_path, user)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, user["user_id"])
        response = client.post(
            "/update_store/aldi",
            data={
                "store_label": "Changed",
                "store_url": "https://changed.example/search?q=",
                "urlStoreSelector": "https://changed.example/stores",
                "store_username": "shopper@example.com",
                "store_password": "secret",
            },
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    settings = read_store_settings(tmp_path, user["user_id"])
    assert settings["stores"]["aldi"]["label"] == "Aldi"
    assert settings["stores"]["aldi"]["url"] == "https://old.example/search?q="
    assert settings["stores"]["aldi"]["urlStoreSelector"] == "https://old.example/stores"

    credentials = read_store_credentials(tmp_path, user["user_id"])
    assert credentials["credentials"]["aldi"] == {
        "username": "shopper@example.com",
        "password": "secret",
    }


def test_non_admin_can_toggle_but_cannot_manage_store_definitions(monkeypatch, tmp_path):
    user = create_user("regular-user", "user@example.com")
    seed_user_and_store(monkeypatch, tmp_path, user)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, user["user_id"])
        add_response = client.post(
            "/add_store",
            data={"ajax": "1", "store_label": "Target", "store_url": "https://target.example/search?q="},
            headers={"X-Requested-With": "fetch"},
        )
        toggle_response = client.post(
            "/save_store_settings",
            data={"ajax": "1"},
            headers={"X-Requested-With": "fetch"},
        )
        delete_response = client.post(
            "/delete_store/aldi",
            data={"ajax": "1"},
            headers={"X-Requested-With": "fetch"},
        )

    assert toggle_response.status_code == 200
    assert add_response.status_code == 403
    assert delete_response.status_code == 403

    settings = read_store_settings(tmp_path, user["user_id"])
    assert settings["enabled_stores"] == []
    assert list(settings["stores"].keys()) == ["aldi"]


def test_store_options_toggle_controls_render_without_admin():
    app = create_app()

    with app.test_request_context("/"):
        html = render_template(
            "sections/store_options.html",
            current_user=None,
            available_stores={
                "aldi": {
                    "label": "Aldi",
                    "url": "https://aldi.example/search?q=",
                    "urlStoreSelector": "https://aldi.example/stores",
                },
            },
            enabled_stores=[],
            nearest_store_locations={},
            nearest_store_results={},
            nearest_store_search_radius_miles=5,
        )

    assert 'data-store-can-toggle="true"' in html
    assert 'name="enabled_stores"' in html
    assert 'data-store-toggle-menu-action="aldi"' in html
    assert "Activate store" in html
    assert "Edit login" not in html
    assert "Delete store" not in html


def test_guest_can_toggle_enabled_stores(monkeypatch, tmp_path):
    configure_user_data(monkeypatch, tmp_path)
    monkeypatch.setattr(storage_service, "LEGACY_EXTRACTOR_DIR", tmp_path / "legacy-extractor")
    write_legacy_store_settings(
        tmp_path,
        {
            "stores": {
                "aldi": {
                    "label": "Aldi",
                    "url": "https://aldi.example/search?q=",
                    "urlStoreSelector": "https://aldi.example/stores",
                },
                "meijer": {
                    "label": "Meijer",
                    "url": "https://meijer.example/search?q=",
                    "urlStoreSelector": "https://meijer.example/stores",
                },
            },
            "enabled_stores": ["aldi"],
        },
    )
    app = create_app()

    with app.test_client() as client:
        response = client.post(
            "/save_store_settings",
            data={"ajax": "1", "enabled_stores": "meijer"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json()["enabled_stores"] == ["meijer"]
    assert read_legacy_store_settings(tmp_path)["enabled_stores"] == ["meijer"]


def test_admin_can_manage_store_fields(monkeypatch, tmp_path):
    admin = create_user("admin-user", "admin@example.com")
    seed_user_and_store(monkeypatch, tmp_path, admin)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, admin["user_id"])
        update_response = client.post(
            "/update_store/aldi",
            data={
                "store_label": "ALDI Market",
                "store_url": "https://admin.example/search?q=",
                "urlStoreSelector": "https://admin.example/stores",
            },
            headers={"X-Requested-With": "fetch"},
        )
        add_response = client.post(
            "/add_store",
            data={"ajax": "1", "store_label": "Target", "store_url": "https://target.example/search?q="},
            headers={"X-Requested-With": "fetch"},
        )
        toggle_response = client.post(
            "/save_store_settings",
            data={"ajax": "1"},
            headers={"X-Requested-With": "fetch"},
        )

    assert update_response.status_code == 200
    assert toggle_response.status_code == 200
    assert add_response.status_code == 200

    settings = read_store_settings(tmp_path, admin["user_id"])
    assert settings["stores"]["aldi"]["label"] == "ALDI Market"
    assert settings["stores"]["aldi"]["url"] == "https://admin.example/search?q="
    assert settings["stores"]["aldi"]["urlStoreSelector"] == "https://admin.example/stores"
    assert settings["enabled_stores"] == []
    assert "target" in settings["stores"]


def test_rules_home_stores_saves_enabled_store_changes_for_non_admin(monkeypatch, tmp_path):
    user = create_user("regular-user", "user@example.com")
    seed_user_and_store(monkeypatch, tmp_path, user)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, user["user_id"])
        response = client.post(
            "/api/rules_display/home_stores",
            json={
                "address": {"street": "1 Main St", "city": "Testville", "state": "IN"},
                "enabled_stores": [],
                "rows": [],
            },
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 200
    assert response.get_json()["enabled_stores"] == []
    assert read_store_settings(tmp_path, user["user_id"])["enabled_stores"] == []
