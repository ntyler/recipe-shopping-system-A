from io import BytesIO

import pytest
from flask import abort
from flask import jsonify
from flask import redirect
from flask import send_file
from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.routes import account_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


STRONG_PRODUCTION_KEY = "production-only-7d94f88b5b0f4f99a189e990d20b46c5"


def configure_identity_paths(monkeypatch, tmp_path, users=()):
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(storage_service, "PACKAGE_DIR", tmp_path / "legacy-package")
    monkeypatch.setattr(storage_service, "LEGACY_EXTRACTOR_DIR", tmp_path / "legacy-extractor")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    user_account_service.save_users({"users": list(users)})


@pytest.mark.parametrize(
    "secret_key",
    (
        None,
        "short-secret",
        "a" * 64,
        "dev-shopping-list-session-key",
        "replace-with-random-local-secret",
    ),
)
def test_production_rejects_missing_known_default_and_weak_secret_keys(monkeypatch, secret_key):
    monkeypatch.setenv("SHOPPING_APP_ENV", "production")
    if secret_key is None:
        monkeypatch.delenv("SHOPPING_APP_SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SHOPPING_APP_SECRET_KEY", secret_key)

    with pytest.raises(RuntimeError, match="SHOPPING_APP_SECRET_KEY"):
        create_app()


def test_testing_requires_an_explicit_deterministic_secret_key(monkeypatch):
    monkeypatch.setenv("SHOPPING_APP_ENV", "testing")
    monkeypatch.delenv("SHOPPING_APP_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Testing requires an explicit deterministic"):
        create_app()


def test_explicit_local_development_uses_random_ephemeral_key_with_warning(monkeypatch):
    monkeypatch.setenv("SHOPPING_APP_ENV", "development")
    monkeypatch.delenv("SHOPPING_APP_SECRET_KEY", raising=False)

    with pytest.warns(RuntimeWarning, match="ephemeral local-development key"):
        first = create_app()
    with pytest.warns(RuntimeWarning, match="ephemeral local-development key"):
        second = create_app()

    assert first.secret_key != second.secret_key
    assert len(first.secret_key) >= 32
    assert first.config["SESSION_COOKIE_SECURE"] is False


def test_production_cookie_configuration_is_secure(monkeypatch):
    monkeypatch.setenv("SHOPPING_APP_ENV", "production")
    monkeypatch.setenv("SHOPPING_APP_SECRET_KEY", STRONG_PRODUCTION_KEY)
    app = create_app()

    @app.get("/_security-test/session-cookie")
    def set_test_session_cookie():
        session["test"] = "value"
        return "ok"

    with app.test_client() as client:
        response = client.get("/_security-test/session-cookie")

    cookie = "\n".join(response.headers.getlist("Set-Cookie"))
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_unknown_signed_session_is_cleared_and_never_selects_legacy_or_user_workspace(
    monkeypatch,
    tmp_path,
):
    configure_identity_paths(monkeypatch, tmp_path)
    legacy_secret = tmp_path / "legacy-package" / "shopping_list.txt"
    legacy_secret.parent.mkdir(parents=True)
    legacy_secret.write_text("private legacy groceries", encoding="utf-8")
    app = create_app({"TESTING": True})

    with app.test_client() as client:
        with client.session_transaction() as signed_session:
            signed_session["user_id"] = "stale-private-account"
            signed_session["email"] = "stale@example.com"
            signed_session["is_admin"] = True

        protected = client.get("/sections/current-recipes")
        auth_state = client.get("/auth/session")

        with client.session_transaction() as signed_session:
            assert "user_id" not in signed_session
            assert "email" not in signed_session
            assert "is_admin" not in signed_session

    assert protected.status_code == 401
    assert "stale-private-account" not in protected.get_data(as_text=True)
    assert "private legacy groceries" not in protected.get_data(as_text=True)
    assert protected.headers["Cache-Control"] == "private, no-store"
    assert auth_state.status_code == 200
    assert auth_state.get_json()["authenticated"] is False
    assert auth_state.get_json()["user"] is None
    assert not (tmp_path / "users" / "stale-private-account").exists()


def test_storage_helpers_reject_anonymous_and_stale_request_contexts(monkeypatch, tmp_path):
    configure_identity_paths(monkeypatch, tmp_path)
    app = create_app({"TESTING": True})

    with app.test_request_context("/"):
        session["user_id"] = "unknown-user"
        assert storage_service.active_user_id() == ""
        assert storage_service.active_guest_session_id() == ""
        with pytest.raises(RuntimeError, match="No authenticated user workspace"):
            storage_service.user_data_root()
        with pytest.raises(RuntimeError, match="No authenticated recipe workspace"):
            storage_service.extractor_root()
        with pytest.raises(RuntimeError, match="No authenticated user workspace"):
            storage_service.workspace_data_root()


def test_guest_blocked_account_mutations_execute_guard_before_public_bypass(
    monkeypatch,
    tmp_path,
):
    configure_identity_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        account_routes,
        "update_user_profile",
        lambda *_args, **_kwargs: pytest.fail("profile mutation route executed"),
    )
    monkeypatch.setattr(
        account_routes,
        "delete_account_with_token",
        lambda *_args, **_kwargs: pytest.fail("account deletion route executed"),
    )
    app = create_app({"TESTING": True})

    with app.test_client() as client:
        client.get("/guest/start")
        profile = client.post("/account/profile", data={"display_name": "Guest"})
        token_delete = client.post(
            "/account/delete/complete",
            data={"account_delete_token": "capability-token"},
            headers={"X-Requested-With": "fetch"},
        )

    assert profile.status_code == 302
    assert profile.headers["Cache-Control"] == "private, no-store"
    assert token_delete.status_code == 403
    assert token_delete.get_json()["guest_restricted"] is True
    assert token_delete.headers["Cache-Control"] == "private, no-store"


def test_central_private_cache_policy_covers_response_types_and_statuses():
    app = create_app({"TESTING": True})
    app.config.update(PROPAGATE_EXCEPTIONS=False)

    @app.get("/_security-test/html")
    def cache_html():
        return "<p>private</p>"

    @app.get("/_security-test/json")
    def cache_json():
        return jsonify({"ok": True})

    @app.get("/_security-test/file")
    def cache_file():
        return send_file(BytesIO(b"private bytes"), mimetype="application/octet-stream")

    @app.get("/_security-test/redirect")
    def cache_redirect():
        return redirect("/_security-test/html")

    @app.get("/_security-test/empty")
    def cache_empty():
        return "", 204

    @app.get("/_security-test/error/<int:status>")
    def cache_error(status):
        abort(status)

    @app.get("/_security-test/exception")
    def cache_exception():
        raise RuntimeError("representative private failure")

    with app.test_client() as client:
        responses = [
            client.get("/_security-test/html"),
            client.get("/_security-test/json"),
            client.get("/_security-test/file"),
            client.get("/_security-test/redirect"),
            client.get("/_security-test/empty"),
            *(client.get(f"/_security-test/error/{status}") for status in (400, 401, 403, 404)),
            client.get("/_security-test/exception"),
        ]

    assert [response.status_code for response in responses] == [
        200,
        200,
        200,
        302,
        204,
        400,
        401,
        403,
        404,
        500,
    ]
    for response in responses:
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"
