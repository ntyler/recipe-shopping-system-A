from __future__ import annotations

import hashlib
import sqlite3

import pytest

from PushShoppingList.services import application_data_service as application_data


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_synthetic_v1(database):
    with sqlite3.connect(database) as connection:
        for statement in application_data._SCHEMA_MIGRATION_STATEMENTS[1]:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_versions VALUES (?, 1, ?, ?)",
            (
                application_data.APPLICATION_SCHEMA_COMPONENT,
                application_data.schema_checksum_sha256(1),
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO migration_runs (
                id, migration_kind, status, started_at, finished_at, summary_json
            ) VALUES (?, 'application_schema_install', 'succeeded', ?, ?, ?)
            """,
            (
                "schema:application_data:v1",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                '{"schema_version":1}',
            ),
        )
        connection.execute(
            """
            INSERT INTO workspaces (
                id, workspace_type, external_id, created_at, updated_at
            ) VALUES (?, 'guest', ?, ?, ?)
            """,
            (
                "guest-workspace-uuid",
                "guest-subject-uuid",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO guest_sessions (
                id, session_id, workspace_id, created_at, expires_at, used_at,
                updated_at, is_active, lifecycle_state, temporary_data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'active', ?)
            """,
            (
                "guest-row-uuid",
                "guest-session-uuid",
                "guest-workspace-uuid",
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                '{"cart":["preserved"]}',
            ),
        )
        connection.execute(
            """
            INSERT INTO share_links (
                token_digest, workspace_id, pdf_filename, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "a" * 64,
                "guest-workspace-uuid",
                "preserved.pdf",
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
            ),
        )


def _apply(database):
    return application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )


def test_v1_is_frozen_and_preview_is_read_only(tmp_path):
    database = tmp_path / "application.sqlite3"
    _install_synthetic_v1(database)
    before_hash = _file_sha256(database)

    status = application_data.application_schema_status(database)
    preview = application_data.install_application_schema(database)

    assert application_data.schema_checksum_sha256(1) == (
        "19a0c638b0c75832fd1389b7c1befb75dcaffe4733574d64119e825fecf5bb5a"
    )
    assert status["compatible"] is True
    assert status["available"] is False
    assert status["checksum_matches"] is True
    assert status["pending_versions"] == [2]
    assert preview["action"] == "dry_run"
    assert preview["pending_versions"] == [2]
    assert _file_sha256(database) == before_hash

    with pytest.raises(application_data.ApplicationSchemaApprovalError):
        application_data.install_application_schema(
            database,
            dry_run=False,
            authorized=False,
            approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
        )
    assert _file_sha256(database) == before_hash


def test_synthetic_v1_upgrade_preserves_ids_active_session_and_rows(tmp_path):
    database = tmp_path / "application.sqlite3"
    _install_synthetic_v1(database)

    upgraded = _apply(database)
    unchanged = _apply(database)

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        guest = connection.execute("SELECT * FROM guest_sessions").fetchone()
        workspace = connection.execute("SELECT * FROM workspaces").fetchone()
        share = connection.execute("SELECT * FROM share_links").fetchone()
        schema = connection.execute(
            "SELECT version, checksum_sha256 FROM schema_versions WHERE component = ?",
            (application_data.APPLICATION_SCHEMA_COMPONENT,),
        ).fetchone()
        runs = connection.execute(
            "SELECT id FROM migration_runs WHERE id LIKE 'schema:application_data:v%' ORDER BY id"
        ).fetchall()

    assert upgraded["action"] == "upgraded"
    assert unchanged["action"] == "unchanged"
    assert guest["id"] == "guest-row-uuid"
    assert guest["session_id"] == "guest-session-uuid"
    assert guest["workspace_id"] == "guest-workspace-uuid"
    assert guest["is_active"] == 1
    assert guest["lifecycle_state"] == "active"
    assert guest["expires_at"] == "2027-01-01T00:00:00Z"
    assert guest["temporary_data_json"] == '{"cart":["preserved"]}'
    assert workspace["id"] == "guest-workspace-uuid"
    assert workspace["external_id"] == "guest-subject-uuid"
    assert share["token_digest"] == "a" * 64
    assert share["encrypted_token_json"] == "{}"
    assert share["original_filename"] == "preserved.pdf"
    assert share["updated_at"] == "2026-01-01T00:00:00Z"
    assert schema["version"] == application_data.APPLICATION_SCHEMA_VERSION
    assert schema["checksum_sha256"] == application_data.schema_checksum_sha256()
    assert [row["id"] for row in runs] == [
        "schema:application_data:v1",
        "schema:application_data:v2",
    ]


def test_upgrade_is_atomic_and_can_be_retried_after_statement_failure(tmp_path, monkeypatch):
    database = tmp_path / "application.sqlite3"
    _install_synthetic_v1(database)
    bad_migrations = dict(application_data._SCHEMA_MIGRATION_STATEMENTS)
    bad_migrations[2] = bad_migrations[2] + (
        "INSERT INTO table_that_does_not_exist(value) VALUES (1)",
    )

    with monkeypatch.context() as scoped:
        scoped.setattr(application_data, "_SCHEMA_MIGRATION_STATEMENTS", bad_migrations)
        bad_checksums = dict(application_data._EXPECTED_SCHEMA_CHECKSUMS)
        bad_checksums[2] = application_data._computed_schema_checksum(2)
        scoped.setattr(application_data, "_EXPECTED_SCHEMA_CHECKSUMS", bad_checksums)
        with pytest.raises(sqlite3.OperationalError):
            _apply(database)

    with sqlite3.connect(database) as connection:
        version = connection.execute(
            "SELECT version FROM schema_versions WHERE component = ?",
            (application_data.APPLICATION_SCHEMA_COMPONENT,),
        ).fetchone()[0]
        share_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(share_links)")
        }
    assert version == 1
    assert "encrypted_token_json" not in share_columns
    assert application_data.application_schema_status(database)["pending_versions"] == [2]

    assert _apply(database)["action"] == "upgraded"
    assert application_data.application_schema_available(database) is True


def test_checksum_mismatch_fails_closed_for_writes_and_upgrade(tmp_path):
    database = tmp_path / "application.sqlite3"
    _install_synthetic_v1(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_versions SET checksum_sha256 = ? WHERE component = ?",
            ("f" * 64, application_data.APPLICATION_SCHEMA_COMPONENT),
        )

    status = application_data.application_schema_status(database)
    assert status["available"] is False
    assert status["compatible"] is False
    assert status["checksum_matches"] is False
    assert "schema_versions:checksum_mismatch" in status["issues"]
    with pytest.raises(application_data.ApplicationSchemaUnavailableError):
        with application_data.application_data_write_connection(database):
            pass
    with pytest.raises(application_data.ApplicationSchemaCompatibilityError):
        _apply(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version FROM schema_versions WHERE component = ?",
            (application_data.APPLICATION_SCHEMA_COMPONENT,),
        ).fetchone()[0] == 1


def test_mutating_a_released_migration_is_detected(monkeypatch):
    changed = dict(application_data._SCHEMA_MIGRATION_STATEMENTS)
    changed[1] = changed[1] + ("SELECT 1",)
    monkeypatch.setattr(application_data, "_SCHEMA_MIGRATION_STATEMENTS", changed)

    with pytest.raises(
        application_data.ApplicationDataIntegrityError,
        match="immutable application schema migration",
    ):
        application_data.schema_checksum_sha256()


def test_artifact_repository_enforces_exact_ownership_and_safe_deletion(tmp_path):
    database = tmp_path / "application.sqlite3"
    _apply(database)
    for workspace_id, subject in (("workspace-a", "user-a"), ("workspace-b", "user-b")):
        application_data.ensure_workspace(
            workspace_id,
            "user",
            subject,
            db_path=database,
        )

    inserted = application_data.upsert_artifact(
        "artifact-a",
        "workspace-a",
        "generated_pdf",
        "local",
        "generated/a.pdf",
        exact_path="D:/safe/generated/a.pdf",
        content_sha256="b" * 64,
        byte_count=123,
        exclusive_owner=True,
        metadata={"format": "pdf"},
        db_path=database,
    )
    assert inserted["action"] == "inserted"
    assert inserted["exclusive_owner"] is True
    assert inserted["metadata"] == {"format": "pdf"}
    assert application_data.get_artifact(
        "artifact-a", "workspace-b", db_path=database
    ) is None
    assert application_data.get_artifact_by_storage_key(
        "workspace-b", "local", "generated/a.pdf", db_path=database
    ) is None
    assert application_data.list_workspace_artifacts(
        "workspace-b", db_path=database
    ) == []

    with pytest.raises(application_data.ApplicationDataCollisionError):
        application_data.upsert_artifact(
            "artifact-b",
            "workspace-b",
            "generated_pdf",
            "local",
            "generated/a.pdf",
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.delete_artifact_record(
            "artifact-a", "workspace-a", db_path=database
        )

    pending = application_data.update_artifact_lifecycle(
        "artifact-a",
        "workspace-a",
        "pending_delete",
        expected_row_version=1,
        db_path=database,
    )
    assert pending["row_version"] == 2
    assert application_data.update_artifact_lifecycle(
        "artifact-a", "workspace-b", "deleted", db_path=database
    ) is None
    with pytest.raises(application_data.ApplicationDataCollisionError):
        application_data.update_artifact_lifecycle(
            "artifact-a",
            "workspace-a",
            "deleted",
            expected_row_version=1,
            db_path=database,
        )

    deleted_state = application_data.update_artifact_lifecycle(
        "artifact-a",
        "workspace-a",
        "deleted",
        expected_row_version=2,
        db_path=database,
    )
    assert deleted_state["row_version"] == 3
    assert application_data.delete_artifact_record(
        "artifact-a", "workspace-b", db_path=database
    ) is None
    removed = application_data.delete_artifact_record(
        "artifact-a",
        "workspace-a",
        expected_row_version=3,
        db_path=database,
    )
    assert removed["action"] == "deleted"
    assert application_data.delete_artifact_record(
        "artifact-a", "workspace-a", db_path=database
    ) is None

