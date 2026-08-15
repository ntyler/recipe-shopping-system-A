from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import durable_data_migration_service as durable_migration


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def install(database):
    return application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )


def active_guest_record(guest_id="guest-opaque-id"):
    return {
        "id": guest_id,
        "session_id": guest_id,
        "created_at": "2026-08-14T10:00:00Z",
        "expires_at": "2026-08-15T10:00:00Z",
        "used_at": "2026-08-14T11:00:00Z",
        "is_active": True,
        "lifecycle_state": "active",
        "temporary_data_json": {"cart": ["item"]},
    }


def test_import_status_read_and_dry_run_never_create_database_or_parent(tmp_path):
    database = tmp_path / "missing-parent" / "application.sqlite3"

    status = application_data.application_schema_status(database)
    dry_run = application_data.install_application_schema(database)
    with application_data.existing_application_read_connection(database) as connection:
        assert connection is None
    assert application_data.get_account("opaque-account", db_path=database) is None
    assert application_data.list_guest_sessions(db_path=database) == []

    assert status["exists"] is False
    assert status["available"] is False
    assert dry_run["action"] == "dry_run"
    assert dry_run["would_create_database"] is True
    assert not database.exists()
    assert not database.parent.exists()


@pytest.mark.parametrize(
    ("authorized", "approval"),
    [
        (False, application_data.SCHEMA_INSTALL_APPROVAL_PHRASE),
        (True, "wrong phrase"),
        (False, ""),
    ],
)
def test_schema_apply_requires_flag_and_exact_phrase_without_creating_file(
    tmp_path, authorized, approval
):
    database = tmp_path / "application.sqlite3"

    with pytest.raises(application_data.ApplicationSchemaApprovalError):
        application_data.install_application_schema(
            database,
            dry_run=False,
            authorized=authorized,
            approval=approval,
        )

    assert not database.exists()


def test_schema_install_is_additive_idempotent_and_has_no_raw_identity_columns(tmp_path):
    database = tmp_path / "recipe-master.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE existing_recipe_table (id TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO existing_recipe_table VALUES ('recipe-id', 'preserved')")

    first = install(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        account_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(accounts)")
        }
        share_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(share_links)")
        }
        before_rows = [tuple(row) for row in connection.execute(
            "SELECT component, version, checksum_sha256, installed_at FROM schema_versions"
        ).fetchall()]
        before_runs = [tuple(row) for row in connection.execute(
            "SELECT id, status, summary_json, row_version FROM migration_runs"
        ).fetchall()]
    second = install(database)
    with sqlite3.connect(database) as connection:
        after_rows = connection.execute(
            "SELECT component, version, checksum_sha256, installed_at FROM schema_versions"
        ).fetchall()
        after_runs = connection.execute(
            "SELECT id, status, summary_json, row_version FROM migration_runs"
        ).fetchall()
        preserved = connection.execute("SELECT value FROM existing_recipe_table").fetchone()[0]

    assert application_data.REQUIRED_APPLICATION_TABLES.issubset(tables)
    assert "id" in account_columns
    assert "user_id" not in account_columns
    assert "token_digest" in share_columns
    assert "token" not in share_columns
    assert first["action"] == "installed"
    assert second["action"] == "unchanged"
    assert before_rows == after_rows
    assert before_runs == after_runs
    assert preserved == "preserved"


def test_write_connection_refuses_missing_or_uninstalled_schema(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(application_data.ApplicationSchemaUnavailableError):
        with application_data.application_data_write_connection(missing):
            pass
    assert not missing.exists()

    empty = tmp_path / "empty.sqlite3"
    with sqlite3.connect(empty):
        pass
    with pytest.raises(application_data.ApplicationSchemaUnavailableError):
        with application_data.application_data_write_connection(empty):
            pass
    with sqlite3.connect(empty) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0] == 0


def test_incompatible_reserved_table_is_reported_and_not_overwritten(tmp_path):
    database = tmp_path / "incompatible.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE accounts (user_id TEXT PRIMARY KEY)")

    status = application_data.application_schema_status(database)
    with pytest.raises(application_data.ApplicationSchemaCompatibilityError):
        install(database)
    with sqlite3.connect(database) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(accounts)")]

    assert status["compatible"] is False
    assert "accounts:forbidden_user_id_column" in status["issues"]
    assert columns == ["user_id"]


def test_schema_checksum_mismatch_blocks_reads_and_reinstall(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_versions SET checksum_sha256 = ? WHERE component = ?",
            (sha("unexpected-schema"), application_data.APPLICATION_SCHEMA_COMPONENT),
        )

    status = application_data.application_schema_status(database)
    with pytest.raises(application_data.ApplicationSchemaUnavailableError):
        with application_data.application_data_write_connection(database):
            pass

    with pytest.raises(application_data.ApplicationSchemaCompatibilityError):
        install(database)

    assert status["available"] is False
    assert status["compatible"] is False
    assert status["checksum_matches"] is False
    assert "schema_versions:checksum_mismatch" in status["issues"]


def test_explicit_v1_to_v2_upgrade_preserves_share_metadata(tmp_path):
    database = tmp_path / "application.sqlite3"
    created_at = "2026-08-14T10:00:00Z"
    digest = sha("legacy-digest-only-share")
    with sqlite3.connect(database) as connection:
        for statement in application_data._SCHEMA_MIGRATION_STATEMENTS[1]:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_versions VALUES (?, 1, ?, ?)",
            (
                application_data.APPLICATION_SCHEMA_COMPONENT,
                application_data.schema_checksum_sha256(1),
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO workspaces (
                id, workspace_type, external_id, lifecycle_state,
                created_at, updated_at, metadata_json, source_sha256
            ) VALUES ('pdf-workspace', 'system', 'pdf-shares', 'active', ?, ?, '{}', '')
            """,
            (created_at, created_at),
        )
        connection.execute(
            """
            INSERT INTO share_links (
                token_digest, workspace_id, pdf_filename, created_at, expires_at
            ) VALUES (?, 'pdf-workspace', 'preserved.pdf', ?, '2099-08-14T10:00:00Z')
            """,
            (digest, created_at),
        )

    before = application_data.application_schema_status(database)
    upgraded = install(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM share_links WHERE token_digest = ?", (digest,)
        ).fetchone()

    assert before["current_version"] == 1
    assert before["pending_versions"] == [2]
    assert before["compatible"] is True
    assert upgraded["action"] == "upgraded"
    assert row["pdf_filename"] == "preserved.pdf"
    assert row["original_filename"] == "preserved.pdf"
    assert row["updated_at"] == created_at
    assert row["encrypted_token_json"] == "{}"
    assert row["encryption_key_id"] == ""
    assert "token" not in row.keys()


def test_workspace_documents_and_coverage_are_canonical_idempotent_and_versioned(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    workspace = application_data.ensure_workspace(
        " opaque-workspace ",
        "user",
        " opaque-subject ",
        metadata={"z": 1, "a": 2},
        source_sha256=sha("workspace"),
        db_path=database,
    )
    assert workspace["id"] == " opaque-workspace "
    assert workspace["external_id"] == " opaque-subject "

    inserted = application_data.upsert_durable_document(
        " opaque-workspace ",
        "shopping",
        "state",
        {"z": [2, 1], "a": "value"},
        source_kind="legacy_json",
        source_name="shopping_state",
        source_sha256=sha("source-one"),
        db_path=database,
    )
    unchanged = application_data.upsert_durable_document(
        " opaque-workspace ",
        "shopping",
        "state",
        {"a": "value", "z": [2, 1]},
        source_kind="legacy_json",
        source_name="shopping_state",
        source_sha256=sha("source-one"),
        db_path=database,
    )
    updated = application_data.upsert_durable_document(
        " opaque-workspace ",
        "shopping",
        "state",
        {"a": "changed"},
        source_kind="legacy_json",
        source_name="shopping_state",
        source_sha256=sha("source-two"),
        db_path=database,
    )
    coverage = application_data.upsert_source_coverage(
        " opaque-workspace ",
        "shopping",
        sha("safe-source-key"),
        sha("source-two"),
        summary={"record_count": 1},
        db_path=database,
    )
    coverage_again = application_data.get_source_coverage(
        " opaque-workspace ",
        "shopping",
        sha("safe-source-key"),
        db_path=database,
    )

    assert inserted["action"] == "inserted"
    assert unchanged["action"] == "unchanged"
    assert unchanged["row_version"] == 1
    assert updated["action"] == "updated"
    assert updated["row_version"] == 2
    assert updated["document"] == {"a": "changed"}
    assert coverage["action"] == "inserted"
    assert coverage_again["source_sha256"] == sha("source-two")
    assert coverage_again["status"] == "covered"
    with pytest.raises(application_data.ApplicationDataValidationError):
        application_data.upsert_durable_document(
            " opaque-workspace ",
            "shopping",
            "bad-source",
            {},
            source_name="private/path.json",
            source_sha256=sha("bad"),
            db_path=database,
        )


def test_account_repository_has_parsed_envelopes_and_fail_closed_collisions(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    application_data.ensure_workspace(
        "account-id",
        "account",
        "account-id",
        db_path=database,
    )
    fields = dict(
        username="chef",
        normalized_email="chef@example.test",
        status="active",
        password_hash="one-way-hash",
        firebase_uid="firebase-id",
        provider="local",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        profile={"display_name": "Chef"},
        auth_metadata={"reset": {"token_hash": "one-way"}},
        encrypted_secrets={
            "algorithm": "AES-256-GCM",
            "key_id": "key-1",
            "nonce": "nonce",
            "ciphertext": "ciphertext",
        },
        encryption_key_id="key-1",
        source_sha256=sha("account-source"),
    )

    inserted = application_data.upsert_account(
        "account-id", "account-id", db_path=database, **fields
    )
    unchanged = application_data.upsert_account(
        "account-id", "account-id", db_path=database, **fields
    )
    loaded = application_data.get_account("account-id", db_path=database)

    assert inserted["action"] == "inserted"
    assert unchanged["action"] == "unchanged"
    assert loaded["profile"] == {"display_name": "Chef"}
    assert loaded["auth_metadata"]["reset"]["token_hash"] == "one-way"
    assert loaded["encrypted_secrets"]["ciphertext"] == "ciphertext"
    with pytest.raises(application_data.ApplicationDataCollisionError):
        application_data.upsert_account(
            "account-id",
            "account-id",
            db_path=database,
            **dict(fields, username="different"),
        )


def test_migration_runs_are_safe_and_update_by_explicit_id(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    started = application_data.record_application_migration_run(
        "guest_session_migration",
        "running",
        run_id="run-opaque-id",
        source_sha256=sha("guest-source"),
        summary={"record_count": 2},
        db_path=database,
    )
    finished = application_data.record_application_migration_run(
        "guest_session_migration",
        "succeeded",
        run_id="run-opaque-id",
        source_sha256=sha("guest-source"),
        summary={"record_count": 2, "inserted_count": 2},
        started_at=started["started_at"],
        db_path=database,
    )

    assert started["action"] == "inserted"
    assert finished["action"] == "updated"
    assert finished["finished_at"].endswith("Z")
    assert finished["row_version"] == 2
    with pytest.raises(application_data.ApplicationDataValidationError):
        application_data.record_application_migration_run(
            "unsafe_summary",
            "failed",
            summary={"raw_token": "do-not-log"},
            db_path=database,
        )


def test_guest_repository_preserves_ids_active_expiration_and_monotonic_lifecycle(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    record = active_guest_record("guest-uuid-preserved")
    inserted = application_data.insert_guest_session(record, db_path=database)
    unchanged = application_data.insert_guest_session(record, db_path=database)
    listed = application_data.list_guest_sessions(active_only=True, db_path=database)

    assert inserted["id"] == "guest-uuid-preserved"
    assert inserted["session_id"] == "guest-uuid-preserved"
    assert inserted["workspace_id"] == "guest:guest-uuid-preserved"
    assert inserted["expires_at"] == record["expires_at"]
    assert inserted["is_active"] is True
    assert inserted["temporary_data"] == {"cart": ["item"]}
    assert unchanged["action"] == "unchanged"
    assert [item["id"] for item in listed] == ["guest-uuid-preserved"]

    used = application_data.update_guest_session(
        "guest-uuid-preserved",
        used_at="2026-08-14T12:00:00Z",
        expected_row_version=1,
        db_path=database,
    )
    assert used["used_at"] == "2026-08-14T12:00:00Z"
    assert used["expires_at"] == record["expires_at"]
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.update_guest_session(
            "guest-uuid-preserved",
            expires_at="2026-08-16T10:00:00Z",
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataCollisionError):
        application_data.update_guest_session(
            "guest-uuid-preserved",
            used_at="2026-08-14T13:00:00Z",
            expected_row_version=1,
            db_path=database,
        )

    deactivated = application_data.deactivate_guest_session(
        "guest-uuid-preserved", db_path=database
    )
    assert deactivated["is_active"] is False
    assert deactivated["lifecycle_state"] == "inactive"
    assert deactivated["expires_at"] == record["expires_at"]
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.update_guest_session(
            "guest-uuid-preserved",
            is_active=True,
            lifecycle_state="active",
            db_path=database,
        )


def test_tombstone_blocks_guest_reinsertion(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES (?, ?, ?, 'purged', ?)
            """,
            (
                "tombstoned-guest",
                "guest:tombstoned-guest",
                "purge-run",
                "2026-08-14T10:00:00Z",
            ),
        )

    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.insert_guest_session(
            active_guest_record("tombstoned-guest"), db_path=database
        )
    assert application_data.get_guest_session(
        "tombstoned-guest", db_path=database
    ) is None


def test_guest_workspace_tombstone_blocks_all_creation_primitives(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    guest_id = "late-in-flight-guest"
    workspace_id = "opaque-purged-workspace"
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES (?, ?, ?, 'purged', ?)
            """,
            (guest_id, workspace_id, "purge-run", "2026-08-14T10:00:00Z"),
        )

    assert application_data.guest_workspace_write_is_fenced(
        workspace_id,
        workspace_type="guest",
        external_id=guest_id,
        db_path=database,
    ) is True
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.ensure_workspace(
            workspace_id, "guest", guest_id, db_path=database
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.ensure_workspace(
            "alternate-workspace", "guest", guest_id, db_path=database
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_durable_document(
            workspace_id,
            "shopping",
            "state",
            {"items": []},
            source_sha256=sha("document"),
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_source_coverage(
            workspace_id,
            "shopping",
            "shopping-state",
            sha("coverage"),
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_artifact(
            "late-artifact",
            workspace_id,
            "generated_file",
            "filesystem",
            "guest/late.json",
            exact_path="late.json",
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_account(
            "late-account",
            workspace_id,
            username="late",
            normalized_email="late@example.test",
            db_path=database,
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_share_link(
            sha("late-share-token"),
            {
                "algorithm": "AES-256-GCM",
                "key_id": "key-1",
                "nonce": "nonce",
                "ciphertext": "ciphertext",
            },
            "key-1",
            workspace_id=workspace_id,
            pdf_filename="late.pdf",
            created_at="2026-08-14T10:00:00Z",
            expires_at="2026-08-15T10:00:00Z",
            db_path=database,
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM workspaces WHERE id IN (?, ?)",
            (workspace_id, "alternate-workspace"),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM durable_documents WHERE workspace_id = ?", (workspace_id,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM application_source_coverage WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM artifacts WHERE workspace_id = ?", (workspace_id,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM accounts WHERE workspace_id = ?", (workspace_id,)
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM share_links WHERE workspace_id = ?", (workspace_id,)
        ).fetchone() is None


def test_guest_workspace_tombstone_does_not_block_unrelated_user_writes(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES ('deleted-guest', 'deleted-workspace', 'purge-run', 'purged', ?)
            """,
            ("2026-08-14T10:00:00Z",),
        )

    assert application_data.guest_workspace_write_is_fenced(
        "unrelated-workspace",
        workspace_type="user",
        external_id="unrelated-user",
        db_path=database,
    ) is False
    application_data.ensure_workspace(
        "unrelated-workspace", "user", "unrelated-user", db_path=database
    )
    document = application_data.upsert_durable_document(
        "unrelated-workspace",
        "shopping",
        "state",
        {"items": ["flour"]},
        source_sha256=sha("unrelated-document"),
        db_path=database,
    )
    coverage = application_data.upsert_source_coverage(
        "unrelated-workspace",
        "shopping",
        "shopping-state",
        sha("unrelated-coverage"),
        db_path=database,
    )
    artifact = application_data.upsert_artifact(
        "unrelated-artifact",
        "unrelated-workspace",
        "generated_file",
        "filesystem",
        "users/unrelated.json",
        exact_path="unrelated.json",
        db_path=database,
    )

    assert document["workspace_id"] == "unrelated-workspace"
    assert coverage["workspace_id"] == "unrelated-workspace"
    assert artifact["workspace_id"] == "unrelated-workspace"


def test_guest_tombstone_blocks_updates_to_existing_owner_scoped_share(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    workspace_id = "guest-share-workspace"
    guest_id = "guest-share-owner"
    token_digest = sha("guest-share-token")
    encrypted_token = {
        "algorithm": "AES-256-GCM",
        "key_id": "key-1",
        "nonce": "nonce",
        "ciphertext": "ciphertext",
    }
    application_data.ensure_workspace(
        workspace_id, "guest", guest_id, db_path=database
    )
    application_data.upsert_share_link(
        token_digest,
        encrypted_token,
        "key-1",
        workspace_id=workspace_id,
        pdf_filename="guest.pdf",
        created_at="2026-08-14T10:00:00Z",
        expires_at="2026-08-15T10:00:00Z",
        db_path=database,
    )
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES (?, ?, 'purge-run', 'purging', ?)
            """,
            (guest_id, workspace_id, "2026-08-14T11:00:00Z"),
        )

    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.update_share_link_state(
            token_digest, access_count=1, db_path=database
        )
    with pytest.raises(application_data.ApplicationDataLifecycleError):
        application_data.upsert_share_link(
            token_digest,
            encrypted_token,
            "key-1",
            workspace_id=workspace_id,
            pdf_filename="guest.pdf",
            created_at="2026-08-14T10:00:00Z",
            expires_at="2026-08-16T10:00:00Z",
            allow_update=True,
            db_path=database,
        )

    persisted = application_data.get_share_link(token_digest, db_path=database)
    assert persisted["access_count"] == 0
    assert persisted["expires_at"] == "2026-08-15T10:00:00Z"


def test_guest_workspace_fence_read_does_not_create_json_mode_database(tmp_path):
    database = tmp_path / "missing-parent" / "application.sqlite3"

    assert application_data.guest_workspace_write_is_fenced(
        "guest:active-guest",
        workspace_type="guest",
        external_id="active-guest",
        db_path=database,
    ) is False
    assert not database.exists()
    assert not database.parent.exists()


def test_inactive_legacy_guest_without_lifecycle_or_ended_at_is_preserved(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    legacy = active_guest_record("inactive-legacy-guest")
    legacy["is_active"] = False
    legacy.pop("lifecycle_state")

    inserted = application_data.insert_guest_session(legacy, db_path=database)

    assert inserted["id"] == "inactive-legacy-guest"
    assert inserted["is_active"] is False
    assert inserted["lifecycle_state"] == "inactive"
    assert inserted["ended_at"] == ""
    assert inserted["expires_at"] == legacy["expires_at"]


def test_caller_owned_transaction_rolls_back_all_repository_writes(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)

    with pytest.raises(RuntimeError, match="injected failure"):
        with application_data.application_data_write_connection(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            application_data.ensure_workspace(
                "workspace", "user", "subject", connection=connection
            )
            application_data.upsert_durable_document(
                "workspace",
                "shopping",
                "state",
                {"items": []},
                source_name="shopping_state",
                source_sha256=sha("source"),
                connection=connection,
            )
            raise RuntimeError("injected failure")

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM durable_documents").fetchone()[0] == 0


def test_lazy_durable_migration_adapter_matches_foundation_contract(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "cookbooks.json").write_text(
        json.dumps({"cookbooks": [{"id": "book"}]}), encoding="utf-8"
    )
    configuration = durable_migration.DurableMigrationConfig(
        global_sources={},
        workspaces=(
            durable_migration.WorkspaceSource(
                "workspace", "user", "subject", workspace_root
            ),
        ),
        global_workspace=durable_migration.WorkspaceSource(
            "global", "system", "application", tmp_path / "global"
        ),
    )
    cookbook = next(
        item
        for item in durable_migration.DEFAULT_SOURCE_DESCRIPTORS
        if item.key == "cookbooks"
    )
    preview = durable_migration.preview_durable_data(
        configuration, descriptors=(cookbook,)
    )

    first = durable_migration.apply_durable_data(
        preview,
        configuration,
        durable_migration.application_data_service_adapter(database),
        approval=durable_migration.APPLY_APPROVAL_PHRASE,
        descriptors=(cookbook,),
    )
    second = durable_migration.apply_durable_data(
        preview,
        configuration,
        durable_migration.application_data_service_adapter(database),
        approval=durable_migration.APPLY_APPROVAL_PHRASE,
        descriptors=(cookbook,),
    )

    stored = application_data.get_durable_document(
        "workspace", "cookbooks", "catalog", db_path=database
    )
    assert first.adapter_actions == {"inserted": 1}
    assert second.adapter_actions == {"unchanged": 1}
    assert stored["document"] == {"cookbooks": [{"id": "book"}]}
    assert stored["row_version"] == 1
