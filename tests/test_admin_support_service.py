import json

from PushShoppingList.app import create_app
from PushShoppingList.services import admin_support_service as support
from PushShoppingList.services import email_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service as accounts


def configure_admin_support(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(accounts, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(support, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(support, "ADMIN_SUPPORT_AUDIT_FILE", tmp_path / "admin_support_audit.json")
    monkeypatch.setattr(
        support,
        "send_admin_support_access_email",
        lambda *_args, **_kwargs: {"ok": False, "configured": False},
    )


def admin_user():
    return {
        "user_id": "admin",
        "username": "ntylerbert@gmail.com",
        "email": "ntylerbert@gmail.com",
        "first_name": "Admin",
        "last_name": "User",
        "created_at": "2026-06-04T12:00:00Z",
    }


def target_user():
    return {
        "user_id": "customer",
        "username": "customer@example.com",
        "email": "customer@example.com",
        "first_name": "Customer",
        "last_name": "Account",
        "phone": "317-555-0100",
        "phone_verified_at": "2026-06-04T13:00:00Z",
        "firebase_uid": "firebase-customer-secret",
        "auth_provider": "firebase",
        "firebase_email_verified": True,
        "ntfy_topic": "private-notification-topic",
        "notifications_enabled": True,
        "password_hash": "private-password-hash",
        "created_at": "2026-06-03T12:00:00Z",
        "firebase_last_login_at": "2026-06-04T14:00:00Z",
        "two_factor": {
            "enabled": True,
            "secret": "private-two-factor-secret",
            "backup_codes": [
                {"hash": "private-backup-code-hash", "used_at": ""},
            ],
            "trusted_devices": [
                {"token_hash": "private-trusted-device-hash"},
            ],
        },
    }


def seed_workspace(tmp_path):
    data_root = tmp_path / "user_data" / "customer" / "recipe-extractor" / "data"
    (data_root / "output").mkdir(parents=True)
    (data_root / "uploads").mkdir(parents=True)
    (data_root / "output" / "one.json").write_text("{}", encoding="utf-8")
    (data_root / "output" / "two.json").write_text("{}", encoding="utf-8")
    (data_root / "uploads" / "recipe.pdf").write_text("pdf", encoding="utf-8")
    (data_root / "home_address.json").write_text(
        json.dumps({"street": "123 Private Way"}),
        encoding="utf-8",
    )
    (data_root / "store_credentials.json").write_text(
        json.dumps({"credentials": {"aldi": {"password": "store-secret"}}}),
        encoding="utf-8",
    )


def test_admin_support_record_is_sanitized_and_audited(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    seed_workspace(tmp_path)

    result = support.open_admin_support_record(
        admin_user(),
        "customer",
        "helping with login issue",
    )

    assert result["ok"]
    selected = result["selected_user"]
    serialized = json.dumps(selected)

    assert selected["email"] == "customer@example.com"
    assert selected["two_factor_enabled"] is True
    assert selected["two_factor_backup_codes_remaining"] == 1
    assert selected["workspace"]["saved_recipe_files"] == 2
    assert selected["workspace"]["uploaded_files"] == 1

    assert "private-password-hash" not in serialized
    assert "private-two-factor-secret" not in serialized
    assert "private-backup-code-hash" not in serialized
    assert "private-trusted-device-hash" not in serialized
    assert "private-notification-topic" not in serialized
    assert "firebase-customer-secret" not in serialized
    assert "317-555-0100" not in serialized
    assert "123 Private Way" not in serialized
    assert "store-secret" not in serialized

    audit_entries = support.load_audit_entries()
    assert len(audit_entries) == 1
    assert audit_entries[0]["actorUid"] == "admin"
    assert audit_entries[0]["actorPrivateEmail"] == "ntylerbert@gmail.com"
    assert audit_entries[0]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert audit_entries[0]["admin_email"] == "ntylerbert@gmail.com"
    assert audit_entries[0]["target_email"] == "customer@example.com"
    assert audit_entries[0]["reason"] == "helping with login issue"
    assert result["audit_entry"]["actorPrivateEmail"] == "ntylerbert@gmail.com"
    assert result["audit_entry"]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert result["email_notice"]["configured"] is False


def test_admin_support_record_emails_user_when_configured(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    sent = []
    monkeypatch.setattr(
        support,
        "send_admin_support_access_email",
        lambda user, admin, audit_entry: sent.append((user, admin, audit_entry)) or {
            "ok": True,
            "configured": True,
        },
    )

    result = support.open_admin_support_record(
        admin_user(),
        "customer",
        "checking verification state",
    )

    assert result["ok"]
    assert result["email_notice"]["ok"] is True
    assert len(sent) == 1
    assert sent[0][0]["email"] == "customer@example.com"
    assert sent[0][1]["email"] == "ntylerbert@gmail.com"
    assert sent[0][2]["reason"] == "checking verification state"
    assert sent[0][2]["actorPrivateEmail"] == "ntylerbert@gmail.com"
    assert sent[0][2]["actorPublicEmail"] == "support@recipeshoppinglist.com"


def test_support_access_notices_for_user_are_recent_and_targeted(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})

    support.record_support_access(admin_user(), target_user(), "first reason")
    support.record_support_access(admin_user(), target_user(), "second reason")
    support.record_support_access(
        admin_user(),
        {**target_user(), "user_id": "someone-else", "email": "other@example.com"},
        "other account",
    )

    notices = support.support_access_notices_for_user(target_user())

    assert [notice["reason"] for notice in notices] == ["second reason", "first reason"]
    assert notices[0]["actorPrivateEmail"] == "ntylerbert@gmail.com"
    assert notices[0]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert notices[0]["admin_email"] == "ntylerbert@gmail.com"
    assert notices[0]["admin_public_email"] == "support@recipeshoppinglist.com"
    assert [
        notice["reason"]
        for notice in support.support_access_notices_for_user(target_user(), limit=None)
    ] == ["second reason", "first reason"]
    assert [
        notice["reason"]
        for notice in support.support_access_notices_for_user(target_user(), limit=1)
    ] == ["second reason"]


def test_admin_support_requires_admin_and_reason(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})

    non_admin_result = support.open_admin_support_record(
        target_user(),
        "customer",
        "checking account",
    )
    missing_reason_result = support.open_admin_support_record(
        admin_user(),
        "customer",
        " ",
    )

    assert not non_admin_result["ok"]
    assert not missing_reason_result["ok"]
    assert not support.ADMIN_SUPPORT_AUDIT_FILE.exists()


def test_admin_support_route_stores_only_sanitized_record(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        response = client.post(
            "/account/admin-support",
            data={
                "target_user_id": "customer",
                "support_reason": "checking verification state",
            },
        )

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#adminSupportSection")

        with client.session_transaction() as session:
            selected = session["admin_support_selected_user"]
            assert selected["email"] == "customer@example.com"
            assert "password_hash" not in selected
            assert "phone" not in selected
            assert "ntfy_topic" not in selected

    assert len(support.load_audit_entries()) == 1


def test_admin_support_route_notice_renders_for_target_user(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        for reason in (
            "first support check",
            "second support check",
            "third support check",
            "checking verification state",
        ):
            response = client.post(
                "/account/admin-support",
                data={
                    "target_user_id": "customer",
                    "support_reason": reason,
                },
            )
            assert response.status_code == 302

        with client.session_transaction() as session:
            session.clear()
            session["user_id"] = "customer"

        page = client.get("/")
        html = page.data.decode("utf-8")

    assert "Account Access Notice" in html
    assert "Admin support viewed your account support record." in html
    assert "support@recipeshoppinglist.com" in html
    assert "ntylerbert@gmail.com" not in html
    assert "checking verification state" in html
    assert "first support check" in html
    assert "View account access history" in html
    assert 'data-recent-label="2 recent views"' in html
    assert 'data-history-label="4 total views"' in html
    assert "Full account access history" in html


def test_admin_support_internal_audit_can_show_private_actor_email(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        response = client.post(
            "/account/admin-support",
            data={
                "target_user_id": "customer",
                "support_reason": "checking verification state",
            },
        )
        assert response.status_code == 302

        page = client.get("/")
        html = page.data.decode("utf-8")

    assert "Recent Support Access" in html
    assert "ntylerbert@gmail.com - checking verification state" in html


def test_admin_support_route_reports_configured_email_failure(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    monkeypatch.setattr(
        support,
        "send_admin_support_access_email",
        lambda _user, _admin, _audit_entry: {
            "ok": False,
            "configured": True,
            "error": "SMTP failed.",
        },
    )
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        response = client.post(
            "/account/admin-support",
            data={
                "target_user_id": "customer",
                "support_reason": "checking verification state",
            },
        )
        assert response.status_code == 302

        with client.session_transaction() as session:
            assert session["admin_support_errors"] == ["SMTP failed."]


def test_non_admin_support_route_does_not_audit(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "customer"

        response = client.post(
            "/account/admin-support",
            data={
                "target_user_id": "admin",
                "support_reason": "not allowed",
            },
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#userAccountSection")
    assert not support.ADMIN_SUPPORT_AUDIT_FILE.exists()


def test_admin_support_access_email_explains_visible_and_hidden_data(monkeypatch):
    sent_messages = []

    class FakeSmtp:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            pass

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(
        email_service,
        "smtp_config",
        lambda: {
            "host": "smtp.example.com",
            "port": 587,
            "username": "",
            "password": "",
            "from_email": "support@example.com",
            "from_name": "Recipe Shopping System",
            "use_tls": False,
            "use_ssl": False,
        },
    )
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSmtp)

    result = email_service.send_admin_support_access_email(
        target_user(),
        admin_user(),
        {
            "timestamp_label": "Jun 4, 2026 10:33 PM UTC",
            "reason": "checking verification state",
        },
    )

    assert result["ok"]
    assert len(sent_messages) == 1
    message = sent_messages[0]
    body = message.get_content()

    assert message["To"] == "customer@example.com"
    assert "account support record was viewed" in message["Subject"]
    assert "Admin: support@recipeshoppinglist.com" in body
    assert "ntylerbert@gmail.com" not in body
    assert "Reason: checking verification state" in body
    assert "account status, sign-in metadata, security settings, and workspace counts" in body
    assert "passwords, two-factor secrets, backup code values, home address, store passwords" in body
