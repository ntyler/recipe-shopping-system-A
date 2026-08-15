import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone

import pytest
from flask import Flask

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import guest_session_migration_service as migration
from PushShoppingList.services import guest_session_service


ACTIVE_ID = "0123456789abcdef0123456789abcdef"
SECOND_ID = "fedcba9876543210fedcba9876543210"
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def fixed_clock():
    return FIXED_NOW


def guest_record(
    guest_id=ACTIVE_ID,
    *,
    session_id=None,
    created_at="2026-01-01T00:00:00Z",
    expires_at="2026-01-02T00:00:00Z",
    used_at="2026-01-01T01:00:00Z",
    is_active=True,
    temporary_data=None,
    ended_at=None,
    lifecycle_state=None,
    updated_at=None,
):
    record = {
        "id": guest_id,
        "session_id": session_id if session_id is not None else guest_id,
        "created_at": created_at,
        "expires_at": expires_at,
        "used_at": used_at,
        "is_active": is_active,
        "temporary_data_json": (
            {} if temporary_data is None else temporary_data
        ),
    }
    if ended_at is not None:
        record["ended_at"] = ended_at
    if lifecycle_state is not None:
        record["lifecycle_state"] = lifecycle_state
    if updated_at is not None:
        record["updated_at"] = updated_at
    return record


def write_registry(path, records, *, bom=False):
    raw = json.dumps(
        {"guest_sessions": records},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def install_schema(database):
    return application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )


def active_set_hash(*guest_ids):
    return hashlib.sha256(
        migration.canonical_json(sorted(guest_ids)).encode("utf-8")
    ).hexdigest()


def test_preview_is_bom_strict_payload_free_and_never_opens_or_creates_sqlite(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "legacy" / "guest_sessions.json"
    absent_db_parent = tmp_path / "must-not-exist"
    active = guest_record(
        temporary_data={"private": "never-report-this-payload"},
    )
    inactive = guest_record(
        SECOND_ID,
        created_at="2025-12-01T00:00:00Z",
        expires_at="2025-12-02T00:00:00Z",
        used_at="2025-12-01T01:00:00Z",
        is_active=False,
    )
    original = write_registry(source, [active, inactive], bom=True)
    original_mtime = source.stat().st_mtime_ns

    def forbidden_database_resolution(*_args, **_kwargs):
        raise AssertionError("preview must not resolve or open SQLite")

    monkeypatch.setattr(
        application_data,
        "application_data_db_path",
        forbidden_database_resolution,
    )

    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    assert preview.ready is True
    assert preview.source_sha256 == hashlib.sha256(original).hexdigest()
    assert preview.session_count == 2
    assert preview.active_count == 1
    assert preview.inactive_count == 1
    assert preview.expired_count == 1
    assert preview.active_unexpired_count == 1
    assert preview.active_unexpired_sha256 == active_set_hash(ACTIVE_ID)
    report = json.dumps(preview.to_dict(), sort_keys=True)
    assert ACTIVE_ID not in report
    assert SECOND_ID not in report
    assert "never-report-this-payload" not in report
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_mtime
    assert not absent_db_parent.exists()


def test_preview_active_unexpired_boundary_is_strict(tmp_path):
    source = tmp_path / "guest_sessions.json"
    record = guest_record(expires_at="2026-01-01T12:00:00Z")
    write_registry(source, [record])

    before = migration.preview_guest_session_migration(
        source,
        clock=lambda: datetime(
            2026, 1, 1, 11, 59, 59, tzinfo=timezone.utc
        ),
    )
    at_boundary = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    assert before.active_unexpired_count == 1
    assert before.expired_count == 0
    assert at_boundary.active_count == 1
    assert at_boundary.active_unexpired_count == 0
    assert at_boundary.expired_count == 1
    assert at_boundary.active_unexpired_sha256 == active_set_hash()


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (
            b'{"guest_sessions":[{"id":"first","id":"second"}]}',
            "duplicate_json_key",
        ),
        (
            b'{"guest_sessions":[{"id":"one","session_id":"one",'
            b'"created_at":"2026-01-01T00:00:00Z",'
            b'"expires_at":"2026-01-02T00:00:00Z",'
            b'"used_at":"2026-01-01T00:00:00Z","is_active":true,'
            b'"temporary_data_json":{},"unknown":"value"}]}',
            "unknown_guest_session_field",
        ),
        (
            b'{"guest_sessions":[{"id":"one","session_id":"one",'
            b'"created_at":"2026-01-01T00:00:00Z",'
            b'"expires_at":"2026-01-02T00:00:00Z",'
            b'"used_at":"2026-01-01T00:00:00Z","is_active":true,'
            b'"temporary_data_json":{"number":NaN}}]}',
            "invalid_json_value",
        ),
        (b"\xff\xfe\x00", "invalid_utf8"),
        (b'{"guest_sessions":{}}', "guest_sessions_not_array"),
    ],
)
def test_preview_fails_closed_on_ambiguous_or_invalid_json(
    tmp_path,
    raw,
    error_code,
):
    source = tmp_path / "guest_sessions.json"
    source.write_bytes(raw)

    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    assert preview.ready is False
    assert preview.status == "invalid"
    assert preview.error_code == error_code
    assert preview.session_count == 0
    assert preview.source_sha256 is None


@pytest.mark.parametrize(
    ("records", "error_code"),
    [
        (
            [guest_record("same", session_id="one"), guest_record("same", session_id="two")],
            "duplicate_guest_id",
        ),
        (
            [guest_record("one", session_id="same"), guest_record("two", session_id="same")],
            "duplicate_session_id",
        ),
        (
            [guest_record("one", session_id="two"), guest_record("two", session_id="three")],
            "duplicate_guest_identity",
        ),
        (
            [guest_record(created_at="2026-01-01T00:00:00")],
            "invalid_created_at",
        ),
        (
            [guest_record(is_active=False, lifecycle_state="active")],
            "inconsistent_guest_lifecycle",
        ),
    ],
)
def test_preview_rejects_duplicate_identities_and_invalid_record_semantics(
    tmp_path,
    records,
    error_code,
):
    source = tmp_path / "guest_sessions.json"
    write_registry(source, records)

    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    assert preview.ready is False
    assert preview.error_code == error_code


def test_apply_preserves_exact_rows_active_set_signed_id_and_verified_backup(
    tmp_path,
):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    backup_path = tmp_path / "backup" / "guest_sessions.json"
    active = guest_record(
        created_at="2026-01-01T00:00:00.123456+00:00",
        expires_at="2026-01-02T00:00:00.123456+00:00",
        used_at="2026-01-01T01:02:03.654321+00:00",
        updated_at="2026-01-01T01:02:03.654321+00:00",
        temporary_data={
            "draft": {"private": "temporary-value"},
            "items": [1, "two"],
        },
    )
    inactive_id = " Inactive/opaque guest "
    inactive_session_id = " inactive/session alias "
    inactive = guest_record(
        inactive_id,
        session_id=inactive_session_id,
        created_at="2025-12-01T00:00:00Z",
        expires_at="2025-12-02T00:00:00Z",
        used_at="2025-12-01T03:00:00Z",
        is_active=False,
        ended_at="2025-12-02T00:00:01Z",
    )
    original = write_registry(source, [active, inactive], bom=True)
    original_mtime = source.stat().st_mtime_ns
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    def create_backup(source_path, expected_sha256):
        backup_path.parent.mkdir(parents=True)
        shutil.copy2(source_path, backup_path)
        return {
            "backup_path": backup_path,
            "verified": True,
            "source_sha256": expected_sha256,
            "byte_count": backup_path.stat().st_size,
        }

    result = migration.apply_guest_session_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        backup_callback=create_backup,
        clock=fixed_clock,
    )

    assert result.inserted_sessions == 2
    assert result.unchanged_sessions == 0
    assert result.preserved_newer_used_at == 0
    assert result.active_unexpired_count == 1
    assert result.active_unexpired_sha256 == active_set_hash(ACTIVE_ID)
    assert result.backup == {
        "requested": True,
        "verified": True,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "byte_count": len(original),
    }
    assert result.validation["stored_rows"] == 2
    assert result.validation["coverage_rows"] == 2
    assert result.validation["foreign_key_violations"] == 0
    assert result.validation["quick_check"] == "ok"
    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_mtime

    stored_active = application_data.get_guest_session(
        ACTIVE_ID,
        db_path=database,
    )
    assert stored_active["id"] == ACTIVE_ID
    assert stored_active["session_id"] == ACTIVE_ID
    assert stored_active["workspace_id"] == "guest:%s" % ACTIVE_ID
    assert stored_active["created_at"] == active["created_at"]
    assert stored_active["expires_at"] == active["expires_at"]
    assert stored_active["used_at"] == active["used_at"]
    assert stored_active["updated_at"] == active["updated_at"]
    assert stored_active["is_active"] is True
    assert stored_active["lifecycle_state"] == "active"
    assert stored_active["temporary_data"] == active["temporary_data_json"]

    stored_inactive = application_data.get_guest_session(
        inactive_id,
        db_path=database,
    )
    assert stored_inactive["id"] == inactive_id
    assert stored_inactive["session_id"] == inactive_session_id
    assert stored_inactive["is_active"] is False
    assert stored_inactive["lifecycle_state"] == "inactive"
    assert stored_inactive["ended_at"] == inactive["ended_at"]

    app = Flask(__name__)
    app.secret_key = "signed-cookie-test-secret"
    with app.app_context():
        signed_cookie = guest_session_service.sign_guest_session_id(ACTIVE_ID)
        decoded_id = guest_session_service.decode_guest_cookie(signed_cookie)
    assert decoded_id == ACTIVE_ID
    assert application_data.get_guest_session(
        decoded_id,
        db_path=database,
    )["id"] == ACTIVE_ID

    serialized_result = json.dumps(result.to_dict(), sort_keys=True)
    assert ACTIVE_ID not in serialized_result
    assert inactive_id not in serialized_result
    assert "temporary-value" not in serialized_result
    assert str(backup_path) not in serialized_result


def test_incremental_apply_uses_per_record_hashes_for_unchanged_prefix(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    first_record = guest_record()
    write_registry(source, [first_record])
    first_preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )
    migration.apply_guest_session_migration(
        first_preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        clock=fixed_clock,
    )
    before = application_data.get_guest_session(ACTIVE_ID, db_path=database)

    second_record = guest_record(
        SECOND_ID,
        used_at="2026-01-01T02:00:00Z",
    )
    write_registry(source, [first_record, second_record])
    incremental_preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )
    result = migration.apply_guest_session_migration(
        incremental_preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        clock=fixed_clock,
    )
    after = application_data.get_guest_session(ACTIVE_ID, db_path=database)

    assert result.inserted_sessions == 1
    assert result.unchanged_sessions == 1
    assert result.no_op is False
    assert after["source_sha256"] == before["source_sha256"]
    assert after["row_version"] == before["row_version"]
    assert len(application_data.list_guest_sessions(db_path=database)) == 2


def test_rerun_preserves_newer_database_used_at_without_any_write(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    original = write_registry(source, [guest_record()])
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )
    migration.apply_guest_session_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        clock=fixed_clock,
    )
    advanced = application_data.update_guest_session(
        ACTIVE_ID,
        used_at="2026-01-01T13:00:00Z",
        db_path=database,
    )

    result = migration.apply_guest_session_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=source,
        db_path=database,
        clock=fixed_clock,
    )
    stored = application_data.get_guest_session(ACTIVE_ID, db_path=database)

    assert result.no_op is True
    assert result.migration_run_id is None
    assert result.inserted_sessions == 0
    assert result.unchanged_sessions == 0
    assert result.preserved_newer_used_at == 1
    assert stored["used_at"] == "2026-01-01T13:00:00Z"
    assert stored["expires_at"] == "2026-01-02T00:00:00Z"
    assert stored["row_version"] == advanced["row_version"]
    assert source.read_bytes() == original


def test_apply_requires_exact_approval_and_rechecks_stale_source_before_schema(
    tmp_path,
):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    write_registry(source, [guest_record()])
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    with pytest.raises(migration.GuestSessionMigrationApprovalError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE.lower(),
            source_path=source,
            db_path=database,
            clock=fixed_clock,
        )
    assert not database.exists()

    changed = guest_record(used_at="2026-01-01T02:00:00Z")
    write_registry(source, [changed])
    with pytest.raises(migration.StaleGuestSessionMigrationPreviewError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            clock=fixed_clock,
        )
    assert not database.exists()


def test_apply_rejects_source_as_database_without_changing_legacy_file(tmp_path):
    source = tmp_path / "guest_sessions.json"
    original = write_registry(source, [guest_record()])
    original_mtime = source.stat().st_mtime_ns
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    with pytest.raises(migration.GuestSessionMigrationSourceError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=source,
            clock=fixed_clock,
        )

    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_mtime


def test_unverified_backup_fails_before_schema_install(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    bad_backup = tmp_path / "backup.json"
    original = write_registry(source, [guest_record()])
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    def corrupt_backup(_source_path, _expected_sha256):
        bad_backup.write_bytes(b"not-the-reviewed-source")
        return {"backup_path": bad_backup, "verified": True}

    with pytest.raises(migration.GuestSessionMigrationBackupError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            backup_callback=corrupt_backup,
            clock=fixed_clock,
        )

    assert not database.exists()
    assert source.read_bytes() == original


def test_injected_failure_rolls_back_every_guest_data_row(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    original = write_registry(
        source,
        [guest_record(), guest_record(SECOND_ID)],
    )
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    def fail_after_first(stage, context):
        if stage == "after_session" and context["session_index"] == 0:
            raise RuntimeError("injected-rollback")

    with pytest.raises(RuntimeError, match="injected-rollback"):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            failure_injector=fail_after_first,
            clock=fixed_clock,
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guest_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM migration_runs WHERE migration_kind = ?",
            (migration.SOURCE_KIND,),
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM migration_runs
            WHERE migration_kind = 'application_schema_install'
            """
        ).fetchone()[0] == 1
    assert source.read_bytes() == original


def test_database_collision_rolls_back_sessions_inserted_earlier_in_apply(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    conflicting_id = SECOND_ID
    application_data.insert_guest_session(
        guest_session_id=conflicting_id,
        session_id=conflicting_id,
        created_at="2025-01-01T00:00:00Z",
        expires_at="2025-01-02T00:00:00Z",
        used_at="2025-01-01T01:00:00Z",
        is_active=False,
        lifecycle_state="inactive",
        temporary_data={},
        source_version="1",
        source_sha256="a" * 64,
        db_path=database,
    )
    write_registry(
        source,
        [guest_record(), guest_record(conflicting_id)],
    )
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )
    with sqlite3.connect(database) as connection:
        before_counts = tuple(
            connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in (
                "workspaces",
                "guest_sessions",
                "application_source_coverage",
                "migration_runs",
            )
        )

    with pytest.raises(migration.GuestSessionMigrationCollisionError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            clock=fixed_clock,
        )

    assert application_data.get_guest_session(ACTIVE_ID, db_path=database) is None
    conflicting = application_data.get_guest_session(
        conflicting_id,
        db_path=database,
    )
    assert conflicting["expires_at"] == "2025-01-02T00:00:00Z"
    with sqlite3.connect(database) as connection:
        after_counts = tuple(
            connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            for table in (
                "workspaces",
                "guest_sessions",
                "application_source_coverage",
                "migration_runs",
            )
        )
    assert after_counts == before_counts


def test_cross_mapped_database_identities_fail_closed(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    install_schema(database)
    application_data.insert_guest_session(
        guest_session_id=SECOND_ID,
        session_id=ACTIVE_ID,
        created_at="2025-01-01T00:00:00Z",
        expires_at="2025-01-02T00:00:00Z",
        used_at="2025-01-01T01:00:00Z",
        is_active=False,
        lifecycle_state="inactive",
        temporary_data={},
        source_version="1",
        source_sha256="a" * 64,
        db_path=database,
    )
    original = write_registry(
        source,
        [guest_record(ACTIVE_ID, session_id=SECOND_ID)],
    )
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    with pytest.raises(migration.GuestSessionMigrationCollisionError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            clock=fixed_clock,
        )

    assert application_data.get_guest_session(ACTIVE_ID, db_path=database) is None
    assert application_data.get_guest_session(
        SECOND_ID,
        db_path=database,
    )["session_id"] == ACTIVE_ID
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM guest_sessions"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0] == 0
    assert source.read_bytes() == original


def test_source_change_during_apply_is_detected_and_transaction_rolls_back(
    tmp_path,
):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    write_registry(source, [guest_record()])
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    def mutate_before_commit(stage, _context):
        if stage == "before_commit":
            write_registry(
                source,
                [guest_record(used_at="2026-01-01T02:00:00Z")],
            )

    with pytest.raises(migration.StaleGuestSessionMigrationPreviewError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            failure_injector=mutate_before_commit,
            clock=fixed_clock,
        )

    assert application_data.get_guest_session(ACTIVE_ID, db_path=database) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guest_sessions").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0] == 0


def test_guest_tombstone_blocks_resurrection_and_rolls_back_apply(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    original = write_registry(source, [guest_record()])
    install_schema(database)
    with application_data.application_data_write_connection(
        database
    ) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at, completed_at,
                reason_code, source_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ACTIVE_ID,
                "guest:%s" % ACTIVE_ID,
                "purge-test",
                "purged",
                "2026-01-01T11:00:00Z",
                "2026-01-01T11:00:01Z",
                "expired",
                "b" * 64,
            ),
        )
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    with pytest.raises(migration.GuestSessionMigrationCollisionError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            clock=fixed_clock,
        )

    assert application_data.get_guest_session(ACTIVE_ID, db_path=database) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM guest_tombstones"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM workspaces"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0] == 0
    assert source.read_bytes() == original


def test_verified_backup_change_before_commit_rolls_back_apply(tmp_path):
    source = tmp_path / "guest_sessions.json"
    database = tmp_path / "application.sqlite3"
    backup = tmp_path / "backup" / "guest_sessions.json"
    original = write_registry(source, [guest_record()])
    preview = migration.preview_guest_session_migration(
        source,
        clock=fixed_clock,
    )

    def create_verified_backup(source_path, expected_sha256):
        backup.parent.mkdir(parents=True)
        shutil.copyfile(source_path, backup)
        return {
            "backup_path": backup,
            "verified": True,
            "source_sha256": expected_sha256,
            "byte_count": len(original),
        }

    def mutate_backup_before_commit(stage, _context):
        if stage == "before_commit":
            backup.write_bytes(b"changed-after-verification")

    with pytest.raises(migration.GuestSessionMigrationBackupError):
        migration.apply_guest_session_migration(
            preview,
            approval=migration.APPLY_APPROVAL_PHRASE,
            source_path=source,
            db_path=database,
            backup_callback=create_verified_backup,
            failure_injector=mutate_backup_before_commit,
            clock=fixed_clock,
        )

    assert application_data.get_guest_session(ACTIVE_ID, db_path=database) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM guest_sessions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0] == 0
    assert source.read_bytes() == original
