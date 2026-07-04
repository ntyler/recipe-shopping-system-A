from PushShoppingList.app import create_app
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
                "/sections/recipe-view",
            )
        }

    expected_roots = {
        "/sections/current-recipes": 'id="currentRecipeUrlLogCard"',
        "/sections/cookbooks": 'id="cookbooksCard"',
        "/sections/rules": 'id="rulesCard"',
        "/sections/recipe-view": 'id="shoppingViewsSection"',
    }
    for path, response in responses.items():
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert response.content_type.startswith("text/html")
        assert expected_roots[path] in html
        assert "<h1>Shopping List</h1>" not in html


def test_logged_out_sensitive_lazy_section_returns_auth_error_not_index(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/sections/store-options")

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "Sign in before managing this workspace."
    assert b"<h1>Shopping List</h1>" not in response.data
