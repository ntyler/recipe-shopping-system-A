import json
from datetime import datetime
from datetime import timezone
from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.services import admin_support_service as support
from PushShoppingList.services import device_status_service as device_status
from PushShoppingList.services import email_service
from PushShoppingList.services import guest_session_service
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


def configure_device_status(monkeypatch, tmp_path):
    monkeypatch.setattr(device_status, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(device_status, "GUEST_DATA_DIR", tmp_path / "guest_data")
    monkeypatch.setattr(device_status, "PACKAGE_DIR", tmp_path)
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guest_data")
    monkeypatch.setattr(guest_session_service, "now_utc", lambda: datetime(2026, 7, 4, 3, 30))


def admin_user():
    return {
        "user_id": "admin",
        "username": "admin@example.com",
        "email": "admin@example.com",
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
    assert audit_entries[0]["actorPrivateEmail"] == "admin@example.com"
    assert audit_entries[0]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert audit_entries[0]["admin_email"] == "admin@example.com"
    assert audit_entries[0]["target_email"] == "customer@example.com"
    assert audit_entries[0]["targetUserEmail"] == "customer@example.com"
    assert audit_entries[0]["createdAt"]
    assert audit_entries[0]["reason"] == "helping with login issue"
    assert result["audit_entry"]["actorPrivateEmail"] == "admin@example.com"
    assert result["audit_entry"]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert result["audit_entry"]["targetUserEmail"] == "customer@example.com"
    assert result["audit_entry"]["createdAt"]
    assert result["email_notice"]["configured"] is False


def test_owner_admin_can_grant_and_revoke_delegated_admin_access(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})

    grant = support.update_account_admin_access(admin_user(), "customer", True)

    assert grant["ok"]
    assert grant["changed"] is True
    assert grant["selected_user"]["is_admin"] is True
    assert grant["selected_user"]["admin_access_enabled"] is True
    assert grant["selected_user"]["admin_access_label"] == "Granted admin"
    assert accounts.find_user_by_id("customer")["admin_access_enabled"] is True
    assert accounts.is_admin_user(accounts.find_user_by_id("customer")) is True

    revoke = support.update_account_admin_access(admin_user(), "customer", False)

    assert revoke["ok"]
    assert revoke["changed"] is True
    assert revoke["selected_user"]["is_admin"] is False
    assert revoke["selected_user"]["admin_access_enabled"] is False
    assert accounts.find_user_by_id("customer")["admin_access_enabled"] is False

    admin_access_entries = support.recent_admin_access_audit_entries()
    assert [entry["admin_access_action"] for entry in admin_access_entries] == ["Revoked", "Granted"]
    assert admin_access_entries[0]["target_email"] == "customer@example.com"
    assert support.support_access_notices_for_user(target_user(), limit=None) == []


def test_device_status_summary_includes_matching_account_email(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 2, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})

    device_status.record_device_stale_event(
        {
            "device_id": "desktop-device",
            "route": "/#userAccountSection",
            "stale_reason": "inactive-timeout",
            "timestamp": "2026-07-04T02:00:00Z",
            "last_active_at": "2026-07-04T01:00:00Z",
            "minutes_inactive": 60,
            "minutes_hidden": 0,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        },
        session_user_id="customer",
    )

    events = device_status.device_status_summary()

    assert len(events) == 1
    assert events[0]["user_id"] == "customer"
    assert events[0]["account_email"] == "customer@example.com"
    assert events[0]["account_display_name"] == "Customer Account"
    assert events[0]["device_filter_key"] == "account:customer"
    assert events[0]["device_filter_label"] == "Customer Account - customer@example.com"
    assert events[0]["activity_key"] == "inactive"
    assert events[0]["activity_label"] == "Inactive"
    assert events[0]["minutes_inactive"] == 90.0

    options = device_status.device_status_filter_options(events)
    account_type_options = device_status.device_status_account_type_filter_options(events)

    assert options == [{
        "key": "account:customer",
        "label": "Customer Account - customer@example.com",
    }]
    assert account_type_options == [{
        "key": "group:active-account",
        "label": "Active accounts (1)",
    }]


def test_device_status_summary_marks_guest_demo_expiration(monkeypatch, tmp_path):
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    guest_session_service.save_guest_sessions({
        "guest_sessions": [
            {
                "id": "active-guest",
                "expires_at": "2026-07-04T04:30:00Z",
                "is_active": True,
            },
            {
                "id": "expired-guest",
                "expires_at": "2026-07-04T02:00:00Z",
                "is_active": False,
            },
        ],
    })

    device_status.record_device_stale_event(
        {
            "device_id": "active-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:20:00Z",
            "last_active_at": "2026-07-04T03:20:00Z",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="active-guest",
    )
    device_status.record_device_stale_event(
        {
            "device_id": "expired-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:10:00Z",
            "last_active_at": "2026-07-04T02:00:00Z",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="expired-guest",
    )

    events = {
        event["guest_session_id"]: event
        for event in device_status.device_status_summary()
    }

    assert events["active-guest"]["guest_session_expired"] is False
    assert events["active-guest"]["guest_session_remaining_label"] == "01:00"
    assert events["active-guest"]["guest_session_expires_label"] == "Jul 4, 2026 4:30 AM UTC"
    assert events["active-guest"]["device_filter_label"] == "Guest Demo Active active-guest"
    assert events["expired-guest"]["guest_session_expired"] is True
    assert events["expired-guest"]["guest_session_remaining_label"] == "00:00"
    assert events["expired-guest"]["guest_session_expires_label"] == "Jul 4, 2026 2:00 AM UTC"
    assert events["expired-guest"]["device_filter_label"] == "Guest Demo expired expired-guest"


def test_admin_support_route_renders_device_status_filter(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})
    guest_session_service.save_guest_sessions({
        "guest_sessions": [
            {
                "id": "active-guest",
                "expires_at": "2026-07-04T04:30:00Z",
                "is_active": True,
            },
            {
                "id": "expired-guest",
                "expires_at": "2026-07-04T02:00:00Z",
                "is_active": False,
            },
        ],
    })
    device_status.record_device_stale_event(
        {
            "device_id": "desktop-device",
            "route": "/#userAccountSection",
            "stale_reason": "inactive-timeout",
            "timestamp": "2026-07-04T02:00:00Z",
            "last_active_at": "2026-07-04T01:00:00Z",
            "minutes_inactive": 60,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        },
        session_user_id="customer",
    )
    device_status.record_device_stale_event(
        {
            "device_id": "guest-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:10:00Z",
            "last_active_at": "2026-07-04T03:10:00Z",
            "minutes_inactive": 0,
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="active-guest",
    )
    device_status.record_device_stale_event(
        {
            "device_id": "expired-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:05:00Z",
            "last_active_at": "2026-07-04T02:00:00Z",
            "minutes_inactive": 65,
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="expired-guest",
    )
    device_status.record_device_stale_event(
        {
            "device_id": "anonymous-device",
            "route": "/",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:00:00Z",
            "last_active_at": "2026-07-04T02:55:00Z",
            "minutes_inactive": 5,
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        }
    )
    device_status.record_device_stale_event(
        {
            "device_id": "active-device",
            "route": "/items",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:20:00Z",
            "last_active_at": "2026-07-04T03:20:00Z",
            "minutes_inactive": 0,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/149.0.0.0",
        },
        session_user_id="customer",
    )
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        page = client.get("/sections/admin-support")
        html = page.data.decode("utf-8")

    assert 'data-device-status-filter' in html
    assert 'data-device-status-account-type-filter' in html
    assert 'data-device-status-activity-filter' in html
    assert '<option value="all">All accounts</option>' in html
    assert '<option value="active">Recently active</option>' in html
    assert '<option value="inactive">Inactive</option>' in html
    assert 'value="group:guest-demo"' in html
    assert "Guest Demo accounts (2)" in html
    assert 'value="group:guest-demo-active"' in html
    assert "Existing Guest Demo accounts (1)" in html
    assert 'value="group:guest-demo-expired"' in html
    assert "Expired Guest Demo accounts (1)" in html
    assert 'value="group:active-account"' in html
    assert "Active accounts (2)" in html
    assert "Unlinked browsers" not in html
    assert 'value="account:customer"' in html
    assert "Customer Account - customer@example.com" in html
    assert 'value="anonymous"' in html
    assert 'data-device-status-filter-key="account:customer"' in html
    assert 'data-device-status-filter-key="anonymous"' in html
    assert 'data-device-status-filter-key="guest:active-guest"' in html
    assert 'data-device-status-filter-key="guest:expired-guest"' in html
    assert 'data-device-status-group-key="group:guest-demo"' in html
    assert 'data-device-status-group-key="group:active-account"' in html
    assert 'data-device-status-group-key="group:unlinked-browser"' in html
    assert 'data-device-status-group-keys="group:guest-demo group:guest-demo-active"' in html
    assert 'data-device-status-group-keys="group:guest-demo group:guest-demo-expired"' in html
    assert 'data-device-status-group-keys="group:active-account"' in html
    assert 'data-device-status-group-keys="group:unlinked-browser"' in html
    assert 'data-device-status-activity-key="active"' in html
    assert 'data-device-status-activity-key="inactive"' in html
    assert "admin-device-status-activity-active" in html
    assert "admin-device-status-activity-inactive" in html
    assert "Status Recently active" in html
    assert "Status Inactive" in html


def test_admin_support_route_labels_guest_demo_expiration(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})
    guest_session_service.save_guest_sessions({
        "guest_sessions": [
            {
                "id": "active-guest",
                "expires_at": "2026-07-04T04:30:00Z",
                "is_active": True,
            },
            {
                "id": "expired-guest",
                "expires_at": "2026-07-04T02:00:00Z",
                "is_active": False,
            },
        ],
    })
    device_status.record_device_stale_event(
        {
            "device_id": "active-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:20:00Z",
            "last_active_at": "2026-07-04T03:20:00Z",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="active-guest",
    )
    device_status.record_device_stale_event(
        {
            "device_id": "expired-demo-device",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:10:00Z",
            "last_active_at": "2026-07-04T02:00:00Z",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/604.1",
        },
        guest_session_id="expired-guest",
    )
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        page = client.get("/sections/admin-support")
        html = page.data.decode("utf-8")

    assert page.status_code == 200
    assert "Guest Demo active-guest" in html
    assert "Guest Demo Active active-guest" in html
    assert "Demo Active" in html
    assert 'data-guest-expiry-chip' in html
    assert "admin-device-status-guest-active" in html
    assert "Guest Demo expired-guest" in html
    assert "Guest Demo expired expired-guest" in html
    assert "Demo expired Jul 4, 2026 2:00 AM UTC" in html
    assert "admin-device-status-guest-expired" in html
    assert "Demo deletes in" not in html


def test_device_status_route_records_active_status_for_current_user(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "customer"

        response = client.post(
            "/api/device-status",
            json={
                "device_id": "current-browser",
                "route": "/#userAccountSection",
                "stale_reason": "active-heartbeat",
                "timestamp": "2026-07-04T03:29:00Z",
                "last_active_at": "2026-07-04T03:29:00Z",
                "minutes_inactive": 0,
                "is_stale": False,
            },
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0"},
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    events = device_status.device_status_summary()

    assert len(events) == 1
    assert events[0]["user_id"] == "customer"
    assert events[0]["account_email"] == "customer@example.com"
    assert events[0]["stale_reason"] == "active-heartbeat"
    assert events[0]["is_stale"] is False
    assert events[0]["activity_key"] == "active"
    assert events[0]["activity_label"] == "Recently active"
    assert events[0]["minutes_inactive"] == 1.0


def test_device_status_route_ignores_anonymous_payload_user_id(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        response = client.post(
            "/api/device-status",
            json={
                "user_id": "anonymous",
                "device_id": "anonymous-browser",
                "route": "/",
                "stale_reason": "active-heartbeat",
                "timestamp": "2026-07-04T03:29:00Z",
                "last_active_at": "2026-07-04T03:29:00Z",
                "minutes_inactive": 0,
                "is_stale": False,
            },
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0"},
        )

    assert response.status_code == 200
    events = device_status.device_status_summary()

    assert len(events) == 1
    assert events[0]["user_id"] == ""
    assert events[0]["device_filter_key"] == "anonymous"
    assert events[0]["device_filter_label"] == "Unlinked Browser"


def test_device_status_summary_matches_unlinked_ping_to_known_same_device(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})

    device_status.record_device_stale_event(
        {
            "device_id": "same-browser",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:20:00Z",
            "last_active_at": "2026-07-04T03:20:00Z",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        },
        session_user_id="customer",
    )
    device_status.record_device_status_event(
        {
            "device_id": "same-browser",
            "route": "/#userAccountSection",
            "stale_reason": "active-heartbeat",
            "timestamp": "2026-07-04T03:29:00Z",
            "last_active_at": "2026-07-04T03:29:00Z",
            "is_stale": False,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        }
    )

    events = device_status.device_status_summary()

    assert len(events) == 1
    assert events[0]["device_id"] == "same-browser"
    assert events[0]["user_id"] == "customer"
    assert events[0]["account_email"] == "customer@example.com"
    assert events[0]["stale_reason"] == "active-heartbeat"
    assert events[0]["matched_identity_from_device"] is True
    assert events[0]["device_filter_key"] == "account:customer"
    assert events[0]["activity_label"] == "Recently active"


def test_admin_support_route_labels_unlinked_same_device_heartbeat(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    configure_device_status(monkeypatch, tmp_path)
    monkeypatch.setattr(
        device_status,
        "current_utc",
        lambda: datetime(2026, 7, 4, 3, 30, tzinfo=timezone.utc),
    )
    accounts.save_users({"users": [admin_user(), target_user()]})
    device_status.record_device_stale_event(
        {
            "device_id": "same-browser",
            "route": "/#userAccountSection",
            "stale_reason": "session-revalidation",
            "timestamp": "2026-07-04T03:20:00Z",
            "last_active_at": "2026-07-04T03:20:00Z",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        },
        session_user_id="customer",
    )
    device_status.record_device_status_event(
        {
            "device_id": "same-browser",
            "route": "/#userAccountSection",
            "stale_reason": "active-heartbeat",
            "timestamp": "2026-07-04T03:29:00Z",
            "last_active_at": "2026-07-04T03:29:00Z",
            "is_stale": False,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/149.0.0.0",
        }
    )
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        page = client.get("/sections/admin-support")
        html = page.data.decode("utf-8")

    assert page.status_code == 200
    assert "Last report Jul 4, 2026 3:29 AM UTC" in html
    assert "Account Customer Account - customer@example.com" in html
    assert "Unlinked heartbeat matched by device ID" in html
    assert "Unlinked browser session" not in html


def test_device_status_filter_hides_non_matching_rows():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'row.classList.toggle("admin-device-status-row-hidden", !matches)' in script
    assert 'const DEVICE_STATUS_ACTIVE_SEND_INTERVAL_MS = 5 * 60 * 1000;' in script
    assert 'postDeviceStatusPayload("/api/device-status", buildDeviceActivePayload(reason));' in script
    assert 'sendDeviceActiveReport("active-heartbeat", { force: true });' in script
    assert 'markDeviceUserActivity({ reportActive: true })' in script
    assert 'expiryChip.classList.toggle("admin-device-status-guest-active", isActive);' in script
    assert 'label.textContent = isActive ? "Demo Active" : "Demo expired";' in script
    assert 'const accountTypeFilter = panel.querySelector("[data-device-status-account-type-filter]");' in script
    assert 'const selectedType = accountTypeFilter ? accountTypeFilter.value || "all" : "all";' in script
    assert 'const selectedActivity = activityFilter ? activityFilter.value || "all" : "all";' in script
    assert 'const matchesAccount = selectedKey === "all" || row.dataset.deviceStatusFilterKey === selectedKey;' in script
    assert "const matchesType = selectedType === \"all\" || groupKeys.includes(selectedType);" in script
    assert 'const matchesActivity = selectedActivity === "all" || row.dataset.deviceStatusActivityKey === selectedActivity;' in script
    assert "const matches = matchesAccount && matchesType && matchesActivity;" in script
    assert 'const hasActiveFilter = selectedKey !== "all" || selectedType !== "all" || selectedActivity !== "all";' in script
    assert 'accountTypeFilter.addEventListener("change", applyFilter);' in script
    assert 'activityFilter.addEventListener("change", applyFilter);' in script
    assert ".admin-device-status-list [data-device-status-row][hidden]" in css
    assert ".admin-device-status-list [data-device-status-row].admin-device-status-row-hidden" in css
    assert ".admin-device-status-meta .admin-device-status-activity-active" in css
    assert ".admin-device-status-meta .admin-device-status-activity-inactive" in css
    assert ".admin-device-status-meta .admin-device-status-guest-active" in css
    assert ".admin-device-status-meta .admin-device-status-guest-expired" in css
    assert "display: none !important;" in css


def test_delegated_admin_cannot_manage_admin_access(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    delegated_admin = {
        **target_user(),
        "admin_access_enabled": True,
    }
    accounts.save_users({"users": [admin_user(), delegated_admin]})

    result = support.update_account_admin_access(accounts.public_user(delegated_admin), "admin", False)

    assert not result["ok"]
    assert result["errors"] == ["Only the main admin can manage admin access."]
    assert accounts.is_admin_user(accounts.find_user_by_id("customer")) is True


def test_owner_admin_access_cannot_be_revoked_from_admin_panel(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})

    result = support.update_account_admin_access(admin_user(), "admin", False)

    assert not result["ok"]
    assert result["errors"] == ["Main admin access is built in and cannot be changed here."]
    assert result["selected_user"]["admin_access_locked"] is True
    assert accounts.is_admin_user(accounts.find_user_by_id("admin")) is True


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
    assert sent[0][1]["email"] == "admin@example.com"
    assert sent[0][2]["reason"] == "checking verification state"
    assert sent[0][2]["actorPrivateEmail"] == "admin@example.com"
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
    assert notices[0]["actorPrivateEmail"] == "admin@example.com"
    assert notices[0]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert notices[0]["admin_email"] == "admin@example.com"
    assert notices[0]["admin_public_email"] == "support@recipeshoppinglist.com"
    assert notices[0]["targetUserEmail"] == "customer@example.com"
    assert notices[0]["createdAt"]
    assert [
        notice["reason"]
        for notice in support.support_access_notices_for_user(target_user(), limit=None)
    ] == ["second reason", "first reason"]
    assert [
        notice["reason"]
        for notice in support.support_access_notices_for_user(target_user(), limit=1)
    ] == ["second reason"]


def test_old_support_logs_fallback_to_public_actor_email(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    support.save_audit_entries([
        {
            "audit_id": "legacy-1",
            "action": "view_account_support_record",
            "timestamp": "2026-06-04T22:33:00Z",
            "actorEmail": "admin@example.com",
            "target_email": "customer@example.com",
            "target_user_id": "customer",
            "reason": "legacy reason",
        }
    ])

    notices = support.support_access_notices_for_user(target_user(), limit=None)

    assert len(notices) == 1
    assert notices[0]["actorPrivateEmail"] == "admin@example.com"
    assert notices[0]["actorPublicEmail"] == "support@recipeshoppinglist.com"
    assert notices[0]["targetUserEmail"] == "customer@example.com"
    assert notices[0]["createdAt"] == "2026-06-04T22:33:00Z"


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


def test_admin_access_route_updates_account_and_keeps_selected_user(monkeypatch, tmp_path):
    configure_admin_support(monkeypatch, tmp_path)
    accounts.save_users({"users": [admin_user(), target_user()]})
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "admin"

        response = client.post(
            "/account/admin-access",
            data={
                "target_user_id": "customer",
                "admin_access_action": "grant",
            },
        )

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#adminSupportSection")

        with client.session_transaction() as session:
            selected = session["admin_support_selected_user"]
            assert selected["email"] == "customer@example.com"
            assert selected["is_admin"] is True
            assert selected["admin_access_enabled"] is True

    assert accounts.find_user_by_id("customer")["admin_access_enabled"] is True


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

    assert "Account Notices" in html
    assert 'id="accountNoticesPanel"' in html
    assert "data-account-notices-panel" in html
    assert "hidden" in html
    assert "Admin support viewed your account support record." in html
    assert "support@recipeshoppinglist.com" in html
    assert "admin@example.com" not in html
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

        page = client.get("/sections/admin-support")
        html = page.data.decode("utf-8")

    assert "Recent Support Access" in html
    assert "admin@example.com - checking verification state" in html


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
    assert "admin@example.com" not in body
    assert "Reason: checking verification state" in body
    assert "account status, sign-in metadata, security settings, and workspace counts" in body
    assert "passwords, two-factor secrets, backup code values, home address, store passwords" in body
