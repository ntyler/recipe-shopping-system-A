from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import storage_service


def configure_auth_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")


def test_logged_out_visible_lazy_sections_load_workspace_data(monkeypatch, tmp_path):
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

    expected_roots = {
        "/sections/current-recipes": 'id="currentRecipeUrlLogCard"',
        "/sections/cookbooks": 'id="cookbooksCard"',
        "/sections/rules": 'id="rulesCard"',
        "/sections/store-options": 'id="storeOptionsSection"',
        "/sections/recipe-view": 'id="shoppingViewsSection"',
    }
    for path, response in responses.items():
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert response.content_type.startswith("text/html")
        assert expected_roots[path] in html
        assert "<h1>Shopping List</h1>" not in html


def test_logged_out_store_options_section_is_read_only_and_sanitized(monkeypatch, tmp_path):
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
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    assert 'id="storeOptionsSection"' in html
    assert 'data-store-can-toggle="false"' in html
    assert 'data-store-can-edit-credentials="false"' in html
    assert 'data-store-public-view="true"' in html
    assert "Secret Store" in html
    assert "secret@example.com" not in html
    assert "top-secret-password" not in html
    assert "<h1>Shopping List</h1>" not in html


def test_logged_out_index_shows_store_options_placeholder(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-public-workspace="1"' in html
    assert 'id="storeOptionsSection"' in html
    assert 'data-lazy-section="store-options"' in html
    assert ">Store Options<" in html
    assert ">Home Address<" in html
