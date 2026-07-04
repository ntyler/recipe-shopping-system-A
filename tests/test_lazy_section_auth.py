from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import storage_service


def configure_auth_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")


def test_logged_out_lazy_section_request_returns_auth_error_not_index(monkeypatch, tmp_path):
    configure_auth_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/sections/current-recipes")

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "Sign in before managing this workspace."
    assert b"<h1>Shopping List</h1>" not in response.data
