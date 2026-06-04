from PushShoppingList.app import create_app
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
            firebase_user("freepdf", "freepdfjobsearch@gmail.com", "firebase-freepdf"),
            firebase_user("admin", "ntylerbert@gmail.com", "firebase-admin"),
        ],
    })

    recovery = accounts.request_two_factor_recovery("freepdf")
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"
            session["firebase_uid"] = "firebase-admin"
            session["email"] = "ntylerbert@gmail.com"

        page = client.get(f"/?two_factor_recovery_token={recovery['token']}")
        html = page.data.decode("utf-8")

        assert page.status_code == 200
        assert "freepdfjobsearch@gmail.com" in html
        assert "Signed-in browser session" in html
        assert "ntylerbert@gmail.com" in html

        response = client.post(
            "/account/2fa/recovery/complete",
            data={"two_factor_recovery_token": recovery["token"]},
        )

        assert response.status_code == 302

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
            firebase_user("freepdf", "freepdfjobsearch@gmail.com", "firebase-freepdf"),
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
    assert "freepdfjobsearch@gmail.com" in html
    assert "Cancel" in html
    assert "Two-Factor Verification" not in html
    assert "Verify Code" not in html
