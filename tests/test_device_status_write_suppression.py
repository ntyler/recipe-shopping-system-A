import hashlib

import pytest

from PushShoppingList.app import create_app
from PushShoppingList.services import device_status_service as device_status
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


TARGET_TENANT = "device-status-target"
OTHER_TENANT = "device-status-other"
TEST_SECRET_KEY = "device-status-tests-only-secret-key-2026"


def configure_isolated_app(monkeypatch, tmp_path):
    user_root = tmp_path / "users"
    guest_root = tmp_path / "guests"
    anonymous_file = tmp_path / "anonymous-device-status-events.json"

    monkeypatch.setattr(storage_service, "USER_DATA_DIR", user_root)
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", guest_root)
    monkeypatch.setattr(device_status, "USER_DATA_DIR", user_root)
    monkeypatch.setattr(device_status, "GUEST_DATA_DIR", guest_root)
    monkeypatch.setattr(device_status, "PACKAGE_DIR", tmp_path)
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", guest_root)
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(
        user_account_service,
        "USERS_FILE",
        tmp_path / "users.json",
    )
    monkeypatch.setenv("SHOPPING_APP_DEVICE_STATUS_EVENTS_FILE", str(anonymous_file))
    monkeypatch.delenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        raising=False,
    )
    user_account_service.save_users({
        "users": [
            {
                "user_id": TARGET_TENANT,
                "username": TARGET_TENANT,
                "email": "target@example.com",
                "account_status": "active",
            },
            {
                "user_id": OTHER_TENANT,
                "username": OTHER_TENANT,
                "email": "other@example.com",
                "account_status": "active",
            },
        ],
    })

    app = create_app({
        "TESTING": True,
        "SHOPPING_APP_ENV": "testing",
        "SECRET_KEY": TEST_SECRET_KEY,
    })
    return app, user_root, guest_root, anonymous_file


def post_as_registered(client, endpoint, user_id, payload=None):
    with client.session_transaction() as test_session:
        test_session.clear()
        test_session["user_id"] = user_id
    return client.post(
        endpoint,
        json=payload or {
            "device_id": "test-browser",
            "stale_reason": "active-heartbeat",
            "is_stale": False,
        },
    )


def file_fingerprint(path):
    contents = path.read_bytes()
    stat = path.stat()
    return {
        "contents": contents,
        "sha256": hashlib.sha256(contents).hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


@pytest.mark.parametrize("endpoint", ["/api/device-status", "/api/device-stale"])
def test_exact_registered_tenant_is_a_sanitized_file_immutable_noop(
    monkeypatch,
    tmp_path,
    endpoint,
):
    app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    target_file = user_root / TARGET_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE
    target_file.parent.mkdir(parents=True)
    target_file.write_bytes(b'{"entries":[{"device_id":"preserved"}]}\n')
    before = file_fingerprint(target_file)
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        TARGET_TENANT,
    )
    monkeypatch.setattr(
        device_status,
        "load_device_status_events",
        lambda *_args, **_kwargs: pytest.fail("suppressed request loaded the event file"),
    )
    monkeypatch.setattr(
        device_status,
        "save_device_status_events",
        lambda *_args, **_kwargs: pytest.fail("suppressed request saved the event file"),
    )

    with app.test_client() as client:
        response = post_as_registered(
            client,
            endpoint,
            TARGET_TENANT,
            payload={
                "device_id": "must-not-be-echoed",
                "stale_reason": "must-not-be-echoed",
            },
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "recorded": False,
        "event": {
            "timestamp": None,
            "device_id": None,
            "stale_reason": None,
        },
    }
    assert file_fingerprint(target_file) == before


def test_exact_registered_tenant_noop_does_not_create_file_or_parent(monkeypatch, tmp_path):
    app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    target_file = user_root / TARGET_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        TARGET_TENANT,
    )

    with app.test_client() as client:
        response = post_as_registered(client, "/api/device-status", TARGET_TENANT)

    assert response.status_code == 200
    assert response.get_json()["recorded"] is False
    assert not target_file.exists()
    assert not target_file.parent.exists()


def test_other_registered_tenant_retains_existing_write_behavior(monkeypatch, tmp_path):
    app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        TARGET_TENANT,
    )

    with app.test_client() as client:
        response = post_as_registered(client, "/api/device-status", OTHER_TENANT)

    other_file = user_root / OTHER_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert "recorded" not in response.get_json()
    assert other_file.is_file()
    assert not (user_root / TARGET_TENANT).exists()


def test_guest_workspace_is_never_suppressed(monkeypatch, tmp_path):
    app, _user_root, guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    guest = guest_session_service.create_guest_session()
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        guest["id"],
    )

    with app.test_client() as client:
        with client.session_transaction() as test_session:
            test_session.clear()
            test_session["is_guest"] = True
            test_session["guest_session_id"] = guest["id"]
        response = client.post(
            "/api/device-status",
            json={"device_id": "guest-browser", "is_stale": False},
        )

    guest_file = guest_root / guest["id"] / device_status.DEVICE_STATUS_EVENTS_FILE
    assert response.status_code == 200
    assert "recorded" not in response.get_json()
    assert guest_file.is_file()


def test_dual_identity_cannot_bypass_registered_tenant_suppression(monkeypatch, tmp_path):
    _app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        TARGET_TENANT,
    )
    monkeypatch.setattr(
        device_status,
        "load_device_status_events",
        lambda *_args, **_kwargs: pytest.fail("dual identity bypassed suppression"),
    )
    monkeypatch.setattr(
        device_status,
        "save_device_status_events",
        lambda *_args, **_kwargs: pytest.fail("dual identity bypassed suppression"),
    )

    event = device_status.record_device_status_event(
        {"device_id": "must-not-write"},
        session_user_id=TARGET_TENANT,
        guest_session_id="unexpected-guest-id",
    )

    assert event == {"write_suppressed": True}
    assert not (user_root / TARGET_TENANT).exists()


@pytest.mark.parametrize(
    "configured_value",
    [
        None,
        "",
        " , , ",
        f"../{TARGET_TENANT}",
        f"{TARGET_TENANT}?",
        "*",
        f"{TARGET_TENANT}*",
        "device-status-*",
        f"[{TARGET_TENANT}]",
    ],
    ids=[
        "absent",
        "blank",
        "commas-only",
        "path-alias",
        "punctuation-alias",
        "wildcard",
        "suffix-wildcard",
        "glob-prefix",
        "glob-class",
    ],
)
def test_blank_malformed_and_wildcard_values_do_not_suppress(
    monkeypatch,
    tmp_path,
    configured_value,
):
    app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    if configured_value is not None:
        monkeypatch.setenv(
            device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
            configured_value,
        )

    with app.test_client() as client:
        response = post_as_registered(client, "/api/device-status", TARGET_TENANT)

    target_file = user_root / TARGET_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE
    assert response.status_code == 200
    assert "recorded" not in response.get_json()
    assert target_file.is_file()


def test_invalid_entries_cannot_broaden_an_explicit_exact_match(monkeypatch, tmp_path):
    app, user_root, _guest_root, _anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        f"*,../{TARGET_TENANT},{TARGET_TENANT}",
    )

    with app.test_client() as client:
        target_response = post_as_registered(
            client,
            "/api/device-status",
            TARGET_TENANT,
        )
        other_response = post_as_registered(
            client,
            "/api/device-status",
            OTHER_TENANT,
        )

    assert target_response.get_json()["recorded"] is False
    assert not (user_root / TARGET_TENANT).exists()
    assert "recorded" not in other_response.get_json()
    assert (user_root / OTHER_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE).is_file()


def test_payload_or_stale_session_cannot_select_suppressed_tenant(monkeypatch, tmp_path):
    app, user_root, _guest_root, anonymous_file = configure_isolated_app(
        monkeypatch,
        tmp_path,
    )
    target_file = user_root / TARGET_TENANT / device_status.DEVICE_STATUS_EVENTS_FILE
    target_file.parent.mkdir(parents=True)
    target_file.write_bytes(b'{"entries":[{"device_id":"preserved"}]}\n')
    before = file_fingerprint(target_file)
    monkeypatch.setenv(
        device_status.DEVICE_STATUS_WRITE_SUPPRESSED_TENANTS_ENV,
        TARGET_TENANT,
    )

    with app.test_client() as client:
        response = post_as_registered(
            client,
            "/api/device-status",
            "stale-unregistered-user",
            payload={
                "user_id": TARGET_TENANT,
                "device_id": "anonymous-browser",
                "is_stale": False,
            },
        )

    assert response.status_code == 200
    assert "recorded" not in response.get_json()
    assert file_fingerprint(target_file) == before
    assert anonymous_file.is_file()
