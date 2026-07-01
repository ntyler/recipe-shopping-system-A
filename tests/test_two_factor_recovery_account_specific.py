from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.routes import account_routes
from PushShoppingList.services import user_account_service as accounts


def firebase_user(user_id, email, firebase_uid):
    return {
        "user_id": user_id,
        "username": email,
        "email": email,
        "auth_provider": "firebase",
        "firebase_uid": firebase_uid,
        "first_name": email.split("@", 1)[0],
        "last_name": "",
        "ntfy_topic": f"topic-{user_id}",
        "created_at": "2026-06-04T12:00:00Z",
        "two_factor": {
            "enabled": True,
            "secret": f"secret-{user_id}",
            "backup_codes": [],
            "trusted_devices": [],
        },
    }


def test_two_factor_recovery_token_targets_owner_not_signed_in_session(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
            firebase_user("admin", "admin@example.com", "firebase-admin"),
        ],
    })

    recovery = accounts.request_two_factor_recovery("freepdf")
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"
            session["firebase_uid"] = "firebase-admin"
            session["email"] = "admin@example.com"

        page = client.get(f"/?two_factor_recovery_token={recovery['token']}")
        html = page.data.decode("utf-8")

        assert page.status_code == 200
        assert "user@example.com" in html
        assert "Signed-in browser session" in html
        assert "admin@example.com" in html

        response = client.post(
            "/account/2fa/recovery/complete",
            data={"two_factor_recovery_token": recovery["token"]},
        )

        assert response.status_code == 302
        assert "two_factor_disabled=1" in response.headers["Location"]

        payload = accounts.load_users()
        recovered_user = accounts.find_user_by_id_in_payload(payload, "freepdf")
        signed_in_user = accounts.find_user_by_id_in_payload(payload, "admin")

        assert not accounts.two_factor_enabled(recovered_user)
        assert accounts.two_factor_enabled(signed_in_user)

        with client.session_transaction() as session:
            assert session.get("user_id") is None
            assert session.get("firebase_uid") is None


def test_two_factor_recovery_page_disables_invalid_token_submit():
    app = create_app()

    with app.test_client() as client:
        response = client.get("/?two_factor_recovery_token=not-a-real-token")
        html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Unable to verify this disable link." in html
    assert "Disable Link Invalid" in html
    assert "disabled" in html


def test_two_factor_recovery_token_page_hides_pending_sign_in_form(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
        ],
    })
    recovery = accounts.request_two_factor_recovery("freepdf")
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["pending_2fa_user_id"] = "freepdf"
            session["pending_2fa_provider"] = "firebase"

        response = client.get(f"/?two_factor_recovery_token={recovery['token']}")
        html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Disable Two-Factor Authentication" in html
    assert "user@example.com" in html
    assert "Cancel" in html
    assert "Two-Factor Verification" not in html
    assert "Verify Code" not in html


def test_pending_two_factor_session_cannot_request_recovery_email(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
        ],
    })
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["pending_2fa_user_id"] = "freepdf"
            session["pending_2fa_provider"] = "firebase"

        response = client.post("/account/2fa/recovery/request")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#userAccountSection")

    user = accounts.find_user_by_id("freepdf")
    assert accounts.two_factor_enabled(user)
    assert "two_factor_recovery" not in user


def test_local_admin_two_factor_unlock_defaults_to_admin_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
            firebase_user("admin", "admin@example.com", "firebase-admin"),
        ],
    })

    admin_result = accounts.admin_disable_two_factor_for_identity("admin@example.com")

    assert admin_result["ok"]
    assert admin_result["changed"]
    admin_user = accounts.find_user_by_id("admin")
    assert not accounts.two_factor_enabled(admin_user)
    assert admin_user["two_factor_disabled_by_admin_actor"] == "local_admin_script"

    non_admin_result = accounts.admin_disable_two_factor_for_identity("user@example.com")

    assert not non_admin_result["ok"]
    assert accounts.two_factor_enabled(accounts.find_user_by_id("freepdf"))

    allowed_result = accounts.admin_disable_two_factor_for_identity(
        "user@example.com",
        allow_non_admin=True,
        reason="support-approved unlock",
    )

    assert allowed_result["ok"]
    assert allowed_result["changed"]
    non_admin_user = accounts.find_user_by_id("freepdf")
    assert not accounts.two_factor_enabled(non_admin_user)
    assert non_admin_user["two_factor_disabled_by_admin_reason"] == "support-approved unlock"


def test_firebase_resync_after_completed_two_factor_does_not_restart_challenge(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
        ],
    })
    app = create_app()

    with app.test_request_context("/auth/firebase-login"):
        session["user_id"] = "freepdf"
        session["firebase_uid"] = "firebase-freepdf"

        result = accounts.sign_in_firebase_user({
            "uid": "firebase-freepdf",
            "email": "user@example.com",
            "email_verified": True,
        })

        assert result["ok"]
        assert not result.get("requires_2fa")
        assert session.get("user_id") == "freepdf"
        assert session.get("firebase_uid") == "firebase-freepdf"
        assert session.get("pending_2fa_user_id") is None


def test_firebase_resync_for_unsigned_session_still_requires_two_factor(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [
            firebase_user("freepdf", "user@example.com", "firebase-freepdf"),
        ],
    })
    app = create_app()

    with app.test_request_context("/auth/firebase-login"):
        result = accounts.sign_in_firebase_user({
            "uid": "firebase-freepdf",
            "email": "user@example.com",
            "email_verified": True,
        })

        assert result["ok"]
        assert result["requires_2fa"]
        assert session.get("user_id") is None
        assert session.get("pending_2fa_user_id") == "freepdf"


def test_remember_device_skips_local_two_factor_for_thirty_days(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    user = firebase_user("local-user", "local@example.com", "")
    user["auth_provider"] = "local"
    user["password_hash"] = accounts.generate_password_hash("secret-password")
    user["account_status"] = "active"
    user["two_factor"]["secret"] = ""
    user["two_factor"]["backup_codes"] = accounts.hash_backup_codes(["ABC123"])
    accounts.save_users({"users": [user]})
    app = create_app()

    with app.test_client() as client:
        sign_in_response = client.post(
            "/account/sign-in",
            data={"identity": "local@example.com", "password": "secret-password"},
        )
        assert sign_in_response.status_code == 302

        with client.session_transaction() as test_session:
            assert test_session.get("pending_2fa_user_id") == "local-user"

        verify_response = client.post(
            "/account/2fa/verify",
            data={"code": "ABC123", "remember_device": "1"},
        )

        assert verify_response.status_code == 302
        remember_cookie = next(
            (
                cookie
                for cookie in verify_response.headers.getlist("Set-Cookie")
                if cookie.startswith("shopping_2fa_trust=")
            ),
            "",
        )
        assert "Max-Age=2592000" in remember_cookie
        assert "expires=" in remember_cookie.lower()
        assert "HttpOnly" in remember_cookie
        assert "Path=/" in remember_cookie

        client.post("/account/sign-out")
        remembered_response = client.post(
            "/account/sign-in",
            data={"identity": "local@example.com", "password": "secret-password"},
        )

        assert remembered_response.status_code == 302
        with client.session_transaction() as test_session:
            assert test_session.get("user_id") == "local-user"
            assert test_session.get("pending_2fa_user_id") is None


def test_remember_device_skips_firebase_two_factor_for_thirty_days(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(
        account_routes,
        "firebase_user_from_id_token",
        lambda _token: {
            "ok": True,
            "firebase_user": {
                "uid": "firebase-freepdf",
                "email": "user@example.com",
                "email_verified": True,
            },
        },
    )
    user = firebase_user("freepdf", "user@example.com", "firebase-freepdf")
    user["two_factor"]["secret"] = ""
    user["two_factor"]["backup_codes"] = accounts.hash_backup_codes(["ABC123"])
    accounts.save_users({"users": [user]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as test_session:
            test_session["pending_2fa_user_id"] = "freepdf"
            test_session["pending_2fa_provider"] = "firebase"

        verify_response = client.post(
            "/account/2fa/verify",
            data={"code": "ABC123", "remember_device": "1"},
        )

        assert verify_response.status_code == 302
        assert "shopping_2fa_trust=" in "\n".join(verify_response.headers.getlist("Set-Cookie"))

        with client.session_transaction() as test_session:
            test_session.clear()

        firebase_response = client.post(
            "/auth/firebase-login",
            json={"idToken": "test-token"},
        )
        result = firebase_response.get_json()

        assert firebase_response.status_code == 200
        assert result["success"]
        assert not result.get("requires_2fa")
        with client.session_transaction() as test_session:
            assert test_session.get("user_id") == "freepdf"
            assert test_session.get("pending_2fa_user_id") is None


def test_two_factor_setup_confirmation_requires_explicit_new_setup_flag():
    old_user = firebase_user("old", "old@example.com", "firebase-old")
    new_user = firebase_user("new", "new@example.com", "firebase-new")
    new_user["two_factor"]["setup_confirmation_required"] = True
    new_user["two_factor"]["setup_confirmed_at"] = ""

    assert not accounts.two_factor_setup_confirmation_pending(old_user)
    assert accounts.two_factor_setup_confirmation_pending(new_user)
