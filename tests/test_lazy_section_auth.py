from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def configure_auth_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    user_account_service.save_users({"users": []})


def test_logged_out_lazy_sections_require_authentication_without_rendering_workspace_data(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        responses = {
            path: client.get(path)
            for path in (
                "/sections/current-recipes",
                "/sections/cookbooks",
                "/sections/rules",
                "/sections/store-options",
                "/sections/recipe-view",
            )
        }

    for path, response in responses.items():
        assert response.status_code == 401
        assert response.is_json
        assert response.get_json()["error"] == "Sign in before managing this workspace."
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"


def test_logged_out_store_options_never_loads_or_exposes_legacy_credentials(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        main_routes,
        "load_store_settings",
        lambda: {
            "stores": {
                "secret_store": {
                    "label": "Secret Store",
                    "url": "https://example.com/search?q=",
                    "urlStoreSelector": "https://example.com/stores",
                    "username": "secret@example.com",
                    "password": "top-secret-password",
                },
            },
            "enabled_stores": ["secret_store"],
        },
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/sections/store-options")

    html = response.get_data(as_text=True)
    assert response.status_code == 401
    assert "Secret Store" not in html
    assert "secret@example.com" not in html
    assert "top-secret-password" not in html
    assert response.headers["Cache-Control"] == "private, no-store"


def test_registered_and_guest_lazy_sections_use_only_their_explicit_workspaces(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    user_account_service.save_users({
        "users": [{
            "user_id": "registered-user",
            "username": "registered-user",
            "email": "registered@example.com",
            "account_status": "active",
        }],
    })
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as signed_session:
            signed_session["user_id"] = "registered-user"
        registered = client.get("/sections/current-recipes")

    with app.test_client() as client:
        client.get("/guest/start")
        guest = client.get("/sections/current-recipes")
        with client.session_transaction() as guest_session:
            assert "user_id" not in guest_session

    for response in (registered, guest):
        assert response.status_code == 200
        assert 'id="currentRecipeUrlLogCard"' in response.get_data(as_text=True)
        assert response.headers["Cache-Control"] == "private, no-store"


def test_logged_out_index_uses_standalone_auth_instead_of_workspace(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "data-public-auth-page" in html
    assert "data-public-auth-layout" in html
    assert "data-app-layout" not in html
    assert "data-settings-workspace" not in html
    assert 'id="storeOptionsSection"' not in html
    assert 'data-lazy-section="store-options"' not in html
