from pathlib import Path
from urllib.parse import urlsplit

from PushShoppingList.app import create_app
from PushShoppingList.routes import account_routes


ROOT = Path(__file__).resolve().parents[1]


def assert_canonical_home(location):
    parsed = urlsplit(location)
    assert parsed.path == "/"
    assert parsed.query == ""
    assert parsed.fragment == ""


def test_firebase_success_replaces_history_with_clean_home_and_clears_restore_state():
    script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")
    app_script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "function navigateToCanonicalHomeAfterAuthentication(options = {})" in script
    assert 'const canonicalHomeUrl = new URL("/", window.location.origin);' in script
    assert "window.history.replaceState({}, document.title, canonicalHomeUrl.pathname);" in script
    assert "window.location.replace(canonicalHomeUrl.href);" in script
    assert 'sessionStorage.setItem(POST_AUTH_HOME_RESET_KEY, "1");' in script
    assert 'window.history.scrollRestoration = "manual";' in script
    assert 'window.scrollTo({ top: 0, left: 0, behavior: "auto" });' in script
    assert 'document.querySelector("[data-app-content]")' in script
    assert 'window.openHomeWorkspace({ updateHash: false, scroll: false });' in script
    assert 'window.appShellSetActiveLink(homeLink);' in script

    for storage_key in (
        "scrollY",
        "user-account-open-panel",
        "user-account-settings-open",
        "shoppingTwoFactorPanelReturn",
        "recipe-edit-page-return-state",
        "recipe-edit-pending-action",
    ):
        assert f'"{storage_key}"' in script

    success_handler = script[
        script.index("function handleFirebaseBackendLogin"):
        script.index("function firebaseEmailActionSettings")
    ]
    assert "navigateToCanonicalHomeAfterAuthentication({ collapseAllBeforeReload: true });" in success_handler
    assert "reloadAccountSection();" in success_handler
    assert "reloadAccountSection({ collapseAllBeforeReload: true });" not in success_handler
    assert script.count("navigateToCanonicalHomeAfterAuthentication({ collapseAllBeforeReload: true });") == 2

    assert 'const POST_AUTH_HOME_RESET_KEY = "shopping-post-auth-home-reset";' in app_script
    assert "function consumePostAuthenticationHomeReset()" in app_script
    assert 'window.history.replaceState({}, document.title, window.location.pathname || "/");' in app_script
    assert "openHomeWorkspace({ updateHash: false, scroll: false });" in app_script
    assert "appShellSetActiveLink(homeLink || null);" in app_script
    assert '["consumePostAuthenticationHomeReset", consumePostAuthenticationHomeReset]' in app_script


def test_local_password_success_redirects_to_canonical_home(monkeypatch):
    monkeypatch.setattr(account_routes, "authenticate_user", lambda *_args, **_kwargs: {"ok": True})
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.post("/account/sign-in", data={"identity": "user@example.com", "password": "secret"})

    assert response.status_code == 302
    assert_canonical_home(response.headers["Location"])


def test_pending_or_failed_password_sign_in_keeps_account_destination(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)

    monkeypatch.setattr(
        account_routes,
        "authenticate_user",
        lambda *_args, **_kwargs: {"ok": True, "requires_2fa": True},
    )
    with app.test_client() as client:
        pending = client.post("/account/sign-in", data={"identity": "user@example.com", "password": "secret"})

    assert urlsplit(pending.headers["Location"]).fragment == "userAccountSection"

    monkeypatch.setattr(
        account_routes,
        "authenticate_user",
        lambda *_args, **_kwargs: {"ok": False, "errors": ["Invalid credentials."]},
    )
    with app.test_client() as client:
        failed = client.post("/account/sign-in", data={"identity": "user@example.com", "password": "wrong"})

    assert urlsplit(failed.headers["Location"]).fragment == "userAccountSection"


def test_completed_two_factor_sign_in_redirects_home_but_setup_confirmation_does_not(monkeypatch):
    monkeypatch.setattr(
        account_routes,
        "complete_two_factor_sign_in",
        lambda *_args, **_kwargs: {"ok": True, "trust_token": ""},
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        signed_in = client.post("/account/2fa/verify", data={"code": "123456"})
        assert_canonical_home(signed_in.headers["Location"])

        with client.session_transaction() as session:
            session["pending_2fa_context"] = "setup_confirmation"
        setup_confirmation = client.post("/account/2fa/verify", data={"code": "123456"})

    assert urlsplit(setup_confirmation.headers["Location"]).fragment == "userAccountSection"


def test_account_verification_auto_sign_in_redirects_home_only_on_success(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)

    monkeypatch.setattr(account_routes, "verify_account_creation", lambda _token: {"ok": True})
    with app.test_client() as client:
        success = client.get("/account/verify/success-token")
    assert_canonical_home(success.headers["Location"])

    monkeypatch.setattr(
        account_routes,
        "verify_account_creation",
        lambda _token: {"ok": False, "errors": ["Invalid token."]},
    )
    with app.test_client() as client:
        failed = client.get("/account/verify/failure-token")
    assert urlsplit(failed.headers["Location"]).fragment == "userAccountSection"
