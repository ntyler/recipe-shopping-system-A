from pathlib import Path
from urllib.parse import urlsplit

import pytest

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service


ROOT = Path(__file__).resolve().parents[1]


def assert_canonical_sign_in(location):
    parsed = urlsplit(location)
    assert parsed.path == "/"
    assert parsed.query == ""
    assert parsed.fragment == ""


def configure_guest_demo_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")


def test_every_sign_out_control_uses_success_only_canonical_navigation():
    script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert 'event.target.closest("[data-firebase-sign-out-form]")' in script
    assert 'document.addEventListener("submit", async (event) =>' in script
    assert "beginSignOutProtection();" in script
    assert "await signOut(auth);" in script
    assert "const result = await logoutBackend();" in script
    assert "clearPostSignOutClientState(result);" in script
    assert "navigateToCanonicalSignInAfterSignOut();" in script
    assert 'const canonicalSignInUrl = new URL("/", window.location.origin);' in script
    assert "window.history.replaceState({}, document.title, canonicalSignInUrl.pathname);" in script
    assert "window.location.replace(canonicalSignInUrl.href);" in script
    assert 'sessionStorage.setItem(POST_SIGN_OUT_RESET_KEY, "1");' in script
    assert 'window.addEventListener("pageshow", (event) =>' in script

    handler = script[
        script.index("function bindSignOutForm()"):
        script.index("function bindTwoFactorCancelButton()")
    ]
    assert handler.index("await signOut(auth);") < handler.index("await logoutBackend();")
    assert handler.index("await logoutBackend();") < handler.index("navigateToCanonicalSignInAfterSignOut();")
    assert "catch (error)" in handler
    assert "endSignOutProtection();" in handler
    assert "showSignOutFailure(form, error);" in handler
    assert "reloadAccountSection" not in handler


@pytest.mark.parametrize(
    ("method", "path"),
    (("get", "/logout"), ("post", "/account/sign-out")),
)
def test_native_sign_out_routes_redirect_to_clean_public_sign_in(method, path):
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "signed-in-user"
            session["email"] = "user@example.com"

        response = getattr(client, method)(path)
        assert response.status_code == 302
        assert_canonical_sign_in(response.headers["Location"])

        login_page = client.get("/")
        assert 'data-public-auth-main' in login_page.get_data(as_text=True)
        assert "no-store" in login_page.headers.get("Cache-Control", "")

        with client.session_transaction() as session:
            assert "user_id" not in session
            assert "email" not in session


def test_json_sign_out_deletes_guest_workspace_and_clears_guest_identity(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        with client.session_transaction() as session:
            guest_session_id = session["guest_session_id"]

        guest_file = tmp_path / "guests" / guest_session_id / "shopping_list.txt"
        guest_file.write_text("temporary item", encoding="utf-8")

        response = client.post("/auth/logout", json={})

        assert response.status_code == 200
        assert response.get_json()["authenticated"] is False
        assert "guest_demo_session=;" in response.headers.get("Set-Cookie", "")
        assert not guest_file.exists()

        with client.session_transaction() as session:
            assert "is_guest" not in session
            assert "guest_session_id" not in session

    records = guest_session_service.load_guest_sessions()["guest_sessions"]
    assert records[0]["is_active"] is False
