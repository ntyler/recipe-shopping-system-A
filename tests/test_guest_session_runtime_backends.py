import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from flask import Flask

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import guest_session_migration_service as migration
from PushShoppingList.services import guest_session_service as guests


GUEST_ID = "0123456789abcdef0123456789abcdef"


def fixed_clock():
    return datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def guest_record(guest_id=GUEST_ID):
    return {
        "id": guest_id,
        "session_id": guest_id,
        "created_at": "2026-08-14T12:00:00Z",
        "expires_at": "2099-08-15T12:00:00Z",
        "used_at": "2026-08-14T12:00:00Z",
        "is_active": True,
        "lifecycle_state": "active",
        "temporary_data_json": {"draft": {"title": "Soup"}},
    }


@pytest.fixture
def runtime_paths(monkeypatch, tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    monkeypatch.setattr(guests, "GUEST_SESSIONS_FILE", source)
    monkeypatch.setattr(guests, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(guests, "GUEST_SESSION_DB_PATH", database)
    monkeypatch.delenv(guests.GUEST_SESSION_BACKEND_ENV, raising=False)
    return source, database


def install(database):
    application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )


def apply_source(source, database):
    preview = migration.preview_guest_session_migration(source, clock=fixed_clock)
    assert preview.ready
    return migration.apply_guest_session_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        clock=fixed_clock,
    )


def test_json_is_default_and_legacy_is_an_explicit_alias(runtime_paths, monkeypatch):
    assert guests.guest_session_backend_mode() == "json"
    guests.save_guest_sessions({"guest_sessions": [guest_record()]})

    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "legacy")

    assert guests.guest_session_backend_mode() == "legacy"
    assert guests.load_guest_sessions()["guest_sessions"][0]["id"] == GUEST_ID


def test_json_create_holds_one_lock_across_the_whole_read_modify_write(
    runtime_paths,
    monkeypatch,
):
    original_save = guests._save_json_guest_sessions_unlocked

    def slow_save(payload):
        time.sleep(0.003)
        return original_save(payload)

    monkeypatch.setattr(guests, "_save_json_guest_sessions_unlocked", slow_save)
    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(lambda _index: guests.create_guest_session(), range(24)))

    stored = guests.load_guest_sessions()["guest_sessions"]
    assert len(stored) == 24
    assert len({record["id"] for record in records}) == 24
    assert {record["id"] for record in stored} == {record["id"] for record in records}


def test_empty_migration_creates_authoritative_coverage_for_db_only(
    runtime_paths,
    monkeypatch,
):
    source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": []})
    original = source.read_bytes()

    result = apply_source(source, database)
    coverage = migration.database_coverage_status(database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_only")

    assert result.session_count == 0
    assert result.no_op is False
    assert coverage == {
        "status": "covered",
        "source_sha256": result.source_sha256,
        "record_count": 0,
        "migration_run_valid": True,
    }
    assert guests.load_guest_sessions() == {"guest_sessions": []}
    assert source.read_bytes() == original


def test_db_only_preserves_uuid_expiration_active_cookie_and_legacy_file(
    runtime_paths,
    monkeypatch,
):
    source, database = runtime_paths
    record = guest_record()
    guests.save_guest_sessions({"guest_sessions": [record]})
    original = source.read_bytes()
    apply_source(source, database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_only")
    monkeypatch.setattr(guests, "now_iso", lambda: "2026-08-14T13:00:00Z")

    app = Flask(__name__)
    app.secret_key = "guest-runtime-cookie-secret"
    with app.test_request_context("/"):
        cookie = guests.sign_guest_session_id(GUEST_ID)
        restored = guests.restore_guest_session_from_cookie(cookie)

    stored = application_data.get_guest_session(GUEST_ID, db_path=database)
    assert restored["id"] == GUEST_ID
    assert restored["expires_at"] == record["expires_at"]
    assert restored["is_active"] is True
    assert stored["id"] == GUEST_ID
    assert stored["session_id"] == GUEST_ID
    assert stored["expires_at"] == record["expires_at"]
    assert stored["used_at"] == "2026-08-14T13:00:00Z"
    assert source.read_bytes() == original


def test_db_preferred_falls_back_only_for_a_pristine_uninitialized_domain(
    runtime_paths,
    monkeypatch,
):
    source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": [guest_record()]})
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_preferred")

    assert guests.load_guest_sessions()["guest_sessions"][0]["id"] == GUEST_ID
    assert not database.exists()


def test_db_preferred_fails_closed_when_durable_rows_lack_registry_coverage(
    runtime_paths,
    monkeypatch,
):
    _source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": [guest_record("json-guest")]})
    install(database)
    application_data.insert_guest_session(guest_record("partial-db-guest"), db_path=database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_preferred")

    with pytest.raises(guests.GuestSessionStorageError, match="migration is incomplete"):
        guests.load_guest_sessions()


def test_db_preferred_rejects_missing_migrated_identity_despite_registry_marker(
    runtime_paths,
    monkeypatch,
):
    source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": [guest_record()]})
    original = source.read_bytes()
    apply_source(source, database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM guest_sessions WHERE id = ?", (GUEST_ID,))

    coverage = migration.database_coverage_status(database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_preferred")

    assert coverage["status"] == "incomplete"
    with pytest.raises(guests.GuestSessionStorageError, match="migration is incomplete"):
        guests.load_guest_sessions()
    assert source.read_bytes() == original


def test_db_only_missing_schema_fails_without_creating_a_database(
    runtime_paths,
    monkeypatch,
):
    _source, database = runtime_paths
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_only")

    with pytest.raises(guests.GuestSessionStorageError, match="schema is unavailable"):
        guests.load_guest_sessions()

    assert not database.exists()


def test_shadow_write_is_atomic_when_json_replace_fails(runtime_paths, monkeypatch):
    source, database = runtime_paths
    install(database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "shadow")
    monkeypatch.setattr(
        guests.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected replace failure")),
    )

    with pytest.raises(guests.GuestSessionStorageError, match="shadow write failed"):
        guests.create_guest_session()

    assert not source.exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guest_sessions").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM workspaces WHERE workspace_type = 'guest'"
        ).fetchone()[0] == 0


def test_shadow_create_and_activity_update_preserve_exact_expiration(
    runtime_paths,
    monkeypatch,
):
    _source, database = runtime_paths
    install(database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "shadow")
    monkeypatch.setattr(
        guests,
        "now_utc",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )
    created = guests.create_guest_session()
    expires_at = created["expires_at"]
    monkeypatch.setattr(guests, "now_iso", lambda: "2026-08-14T13:00:00Z")

    updated = guests.update_guest_used_at(created)
    durable = application_data.get_guest_session(created["id"], db_path=database)

    assert updated["expires_at"] == expires_at
    assert durable["expires_at"] == expires_at
    assert durable["used_at"] == "2026-08-14T13:00:00Z"


def test_shadow_runtime_rows_can_be_backfilled_without_regenerating_identity(
    runtime_paths,
    monkeypatch,
):
    source, database = runtime_paths
    install(database)
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "shadow")
    monkeypatch.setattr(
        guests,
        "now_utc",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )
    created = guests.create_guest_session()
    monkeypatch.setattr(guests, "now_iso", lambda: "2026-08-14T13:00:00Z")
    guests.update_guest_used_at(created)

    result = apply_source(source, database)
    durable = application_data.get_guest_session(created["id"], db_path=database)

    assert result.inserted_sessions == 0
    assert durable["id"] == created["id"]
    assert durable["session_id"] == created["id"]
    assert durable["expires_at"] == created["expires_at"]
    assert durable["is_active"] is True


def test_purge_tombstone_fences_writes_before_valid_legacy_state(
    runtime_paths,
):
    _source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": [guest_record()]})
    install(database)
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES (?, ?, ?, 'purging', ?)
            """,
            (
                GUEST_ID,
                "guest:%s" % GUEST_ID,
                "purge-run",
                "2026-08-14T13:00:00Z",
            ),
        )

    assert guests.guest_session_is_valid(guest_record()) is True
    assert guests.guest_session_can_accept_writes(GUEST_ID) is False
    app = Flask(__name__)
    app.secret_key = "guest-runtime-cookie-secret"
    with app.test_request_context("/"):
        cookie = guests.sign_guest_session_id(GUEST_ID)
        assert guests.restore_guest_session_from_cookie(cookie) is None


def test_db_purging_lifecycle_fences_cookie_restore(runtime_paths, monkeypatch):
    source, database = runtime_paths
    guests.save_guest_sessions({"guest_sessions": [guest_record()]})
    apply_source(source, database)
    application_data.update_guest_session(
        GUEST_ID,
        is_active=False,
        lifecycle_state="purging",
        db_path=database,
    )
    monkeypatch.setenv(guests.GUEST_SESSION_BACKEND_ENV, "db_only")

    app = Flask(__name__)
    app.secret_key = "guest-runtime-cookie-secret"
    with app.test_request_context("/"):
        cookie = guests.sign_guest_session_id(GUEST_ID)
        assert guests.restore_guest_session_from_cookie(cookie) is None

    assert guests.guest_session_can_accept_writes(GUEST_ID) is False
