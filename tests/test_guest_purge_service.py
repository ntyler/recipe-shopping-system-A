import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import guest_purge_service as purge
from PushShoppingList.services import guest_recipe_cleanup_service as recipe_cleanup
from PushShoppingList.services import guest_session_migration_service as guest_migration
from PushShoppingList.services import job_service
from PushShoppingList.services import recipe_master_data_service as master_data


TARGET_GUEST = "expired-guest"
OTHER_GUEST = "active-guest"
TARGET_OWNER = "guest:expired-guest"
OTHER_OWNER = "guest:active-guest"
ACCOUNT_OWNER = "registered-account"
TARGET_WORKSPACE = "workspace-uuid-expired"
OTHER_WORKSPACE = "workspace-uuid-active"
OLD_TIME = "2026-08-01T00:00:00Z"
FUTURE_TIME = "2099-08-01T00:00:00Z"


class _R2Client:
    def __init__(self, head_result=None, head_error=None):
        self.head_result = head_result
        self.head_error = head_error
        self.head_calls = []
        self.delete_calls = []

    def head_object(self, **parameters):
        self.head_calls.append(parameters)
        if self.head_error is not None:
            raise self.head_error
        return self.head_result

    def delete_object(self, **parameters):
        self.delete_calls.append(parameters)
        return {}


class _R2NotFoundError(RuntimeError):
    response = {
        "Error": {"Code": "NoSuchKey"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }


def _trusted_r2_metadata(storage_key, **values):
    return purge._canonical_json(
        {
            "storage_key": storage_key,
            "trusted_write": True,
            "owner_workspace_id": TARGET_WORKSPACE,
            **values,
        }
    )


def _quote(value):
    return '"' + str(value).replace('"', '""') + '"'


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_recipe_tables(db_path):
    with sqlite3.connect(db_path) as connection:
        for table_name in recipe_cleanup.OWNER_SCOPED_TABLES:
            connection.execute(
                f"""
                CREATE TABLE {_quote(table_name)} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    marker TEXT NOT NULL DEFAULT ''
                )
                """
            )
        connection.execute(
            """
            CREATE TABLE recipe_ingredient_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER NOT NULL,
                marker TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE recipe_ingredient_option_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                option_id INTEGER NOT NULL,
                marker TEXT NOT NULL DEFAULT ''
            )
            """
        )
        for table_name in recipe_cleanup.OWNER_SCOPED_TABLES:
            for owner in (TARGET_OWNER, OTHER_OWNER, ACCOUNT_OWNER):
                connection.execute(
                    f"INSERT INTO {_quote(table_name)} (user_id, marker) VALUES (?, ?)",
                    (owner, f"{owner}:{table_name}"),
                )
        for owner in (TARGET_OWNER, OTHER_OWNER, ACCOUNT_OWNER):
            requirement_id = connection.execute(
                "SELECT id FROM recipe_ingredient_requirements WHERE user_id = ?",
                (owner,),
            ).fetchone()[0]
            option_id = connection.execute(
                """
                INSERT INTO recipe_ingredient_options (requirement_id, marker)
                VALUES (?, ?)
                """,
                (requirement_id, f"{owner}:option"),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO recipe_ingredient_option_items (option_id, marker)
                VALUES (?, ?)
                """,
                (option_id, f"{owner}:item"),
            )


def _insert_application_rows(db_path, target_artifact, unrelated_artifact):
    application_data.install_application_schema(
        db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    application_data.insert_guest_session(
        {
            "id": TARGET_GUEST,
            "session_id": TARGET_GUEST,
            "workspace_id": TARGET_WORKSPACE,
            "created_at": OLD_TIME,
            "expires_at": "2026-08-02T00:00:00Z",
            "used_at": OLD_TIME,
            "updated_at": OLD_TIME,
            "is_active": False,
            "lifecycle_state": "inactive",
            "temporary_data_json": {"keep_until_purge": True},
        },
        db_path=db_path,
    )
    application_data.insert_guest_session(
        {
            "id": OTHER_GUEST,
            "session_id": OTHER_GUEST,
            "workspace_id": OTHER_WORKSPACE,
            "created_at": OLD_TIME,
            "expires_at": FUTURE_TIME,
            "used_at": OLD_TIME,
            "updated_at": OLD_TIME,
            "is_active": True,
            "lifecycle_state": "active",
            "temporary_data_json": {"must_survive": True},
        },
        db_path=db_path,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for workspace_id, marker in (
            (TARGET_WORKSPACE, "target-document"),
            (OTHER_WORKSPACE, "unrelated-document"),
        ):
            connection.execute(
                """
                INSERT INTO durable_documents (
                    id, workspace_id, domain, document_key, document_json,
                    source_sha256, created_at, updated_at
                ) VALUES (?, ?, 'pantry', 'primary', ?, ?, ?, ?)
                """,
                (
                    "document:" + workspace_id,
                    workspace_id,
                    '{"marker":"%s"}' % marker,
                    hashlib.sha256(marker.encode()).hexdigest(),
                    OLD_TIME,
                    OLD_TIME,
                ),
            )
        for artifact_id, workspace_id, path in (
            ("artifact-target", TARGET_WORKSPACE, target_artifact),
            ("artifact-unrelated", OTHER_WORKSPACE, unrelated_artifact),
        ):
            connection.execute(
                """
                INSERT INTO artifacts (
                    id, workspace_id, artifact_kind, storage_backend, storage_key,
                    exact_path, content_sha256, byte_count, exclusive_owner,
                    lifecycle_state, created_at, updated_at
                ) VALUES (?, ?, 'generated_pdf', 'local', ?, ?, ?, ?, 1,
                          'active', ?, ?)
                """,
                (
                    artifact_id,
                    workspace_id,
                    str(path),
                    str(path.resolve()),
                    _file_sha256(path),
                    path.stat().st_size,
                    OLD_TIME,
                    OLD_TIME,
                ),
            )
        for workspace_id, marker in (
            (TARGET_WORKSPACE, "target-share"),
            (OTHER_WORKSPACE, "unrelated-share"),
        ):
            connection.execute(
                """
                INSERT INTO share_links (
                    token_digest, encrypted_token_json, encryption_key_id,
                    workspace_id, created_by_user_id, pdf_filename, pdf_path,
                    original_filename, created_at, expires_at, updated_at
                ) VALUES (?, '{}', 'test-key', ?, ?, 'file.pdf', '',
                          'file.pdf', ?, ?, ?)
                """,
                (
                    hashlib.sha256(marker.encode()).hexdigest(),
                    workspace_id,
                    marker,
                    OLD_TIME,
                    FUTURE_TIME,
                    OLD_TIME,
                ),
            )


@pytest.fixture
def purge_environment(monkeypatch, tmp_path):
    app_db = tmp_path / "recipe-master.sqlite3"
    jobs_db = tmp_path / "jobs.sqlite3"
    guest_root = tmp_path / "guests"
    target_workspace = guest_root / TARGET_GUEST
    other_workspace = guest_root / OTHER_GUEST
    target_workspace.mkdir(parents=True)
    other_workspace.mkdir(parents=True)
    (target_workspace / "owned.json").write_text("owned", encoding="utf-8")
    (other_workspace / "keep.json").write_text("keep", encoding="utf-8")
    target_artifact = tmp_path / "generated-target.pdf"
    other_artifact = tmp_path / "generated-unrelated.pdf"
    target_artifact.write_bytes(b"target pdf")
    other_artifact.write_bytes(b"unrelated pdf")

    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", app_db)
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", jobs_db)
    _install_recipe_tables(app_db)
    _insert_application_rows(app_db, target_artifact, other_artifact)
    job_service.create_job(
        "recipe-import", guest_session_id=TARGET_GUEST, job_id="target-job"
    )
    job_service.create_job(
        "recipe-import", guest_session_id=OTHER_GUEST, job_id="unrelated-job"
    )
    return {
        "app_db": app_db,
        "jobs_db": jobs_db,
        "guest_root": guest_root,
        "target_workspace": target_workspace,
        "other_workspace": other_workspace,
        "target_artifact": target_artifact,
        "other_artifact": other_artifact,
    }


def _apply(environment, **changes):
    arguments = {
        "dry_run": False,
        "authorized": True,
        "approval": purge.GUEST_PURGE_APPROVAL_PHRASE,
        "db_path": environment["app_db"],
        "recipe_db_path": environment["app_db"],
        "jobs_db_path": environment["jobs_db"],
        "guest_base_dir": environment["guest_root"],
        "at_time": datetime(2026, 8, 14, tzinfo=timezone.utc),
    }
    arguments.update(changes)
    return purge.purge_expired_guest(TARGET_GUEST, **arguments)


def _mark_guest_registry_covered(db_path):
    source_sha256 = hashlib.sha256(b"covered guest registry").hexdigest()
    run_id = "test-guest-registry-migration"
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        application_data.ensure_workspace(
            guest_migration.REGISTRY_WORKSPACE_ID,
            "system",
            guest_migration.REGISTRY_WORKSPACE_EXTERNAL_ID,
            connection=connection,
        )
        application_data.record_application_migration_run(
            guest_migration.SOURCE_KIND,
            "succeeded",
            run_id=run_id,
            source_sha256=source_sha256,
            summary={"record_count": 2},
            connection=connection,
        )
        application_data.upsert_source_coverage(
            guest_migration.REGISTRY_WORKSPACE_ID,
            guest_migration.MIGRATION_DOMAIN,
            guest_migration.REGISTRY_COVERAGE_SOURCE_KEY,
            source_sha256,
            migration_run_id=run_id,
            status="covered",
            summary={"record_count": 2},
            connection=connection,
        )


def _owner_count(connection, table_name, owner):
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM {_quote(table_name)} WHERE user_id = ?", (owner,)
        ).fetchone()[0]
    )


def test_dry_run_is_default_and_does_not_mutate_any_target(purge_environment):
    environment = purge_environment
    app_hash = _file_sha256(environment["app_db"])
    jobs_hash = _file_sha256(environment["jobs_db"])

    result = purge.purge_expired_guest(
        TARGET_GUEST,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["eligible"] is True
    assert result["counts"]["recipe_rows"] == len(recipe_cleanup.DELETE_ORDER)
    assert _file_sha256(environment["app_db"]) == app_hash
    assert _file_sha256(environment["jobs_db"]) == jobs_hash
    assert environment["target_workspace"].exists()
    assert environment["target_artifact"].exists()
    with pytest.raises(purge.GuestPurgeApprovalError):
        purge.purge_expired_guest(
            TARGET_GUEST,
            dry_run=False,
            db_path=environment["app_db"],
        )


def test_purge_removes_all_guest_owned_data_and_preserves_unrelated_data(
    purge_environment,
):
    environment = purge_environment

    result = _apply(environment)

    assert result["ok"] is True
    assert result["code"] == "purge_complete"
    assert not environment["target_workspace"].exists()
    assert not environment["target_artifact"].exists()
    assert (environment["other_workspace"] / "keep.json").read_text() == "keep"
    assert environment["other_artifact"].read_bytes() == b"unrelated pdf"
    assert job_service.get_job("target-job") is None
    assert job_service.get_job("unrelated-job")["guest_session_id"] == OTHER_GUEST

    with sqlite3.connect(environment["app_db"]) as connection:
        connection.row_factory = sqlite3.Row
        for table_name in recipe_cleanup.OWNER_SCOPED_TABLES:
            assert _owner_count(connection, table_name, TARGET_OWNER) == 0
            assert _owner_count(connection, table_name, OTHER_OWNER) == 1
            assert _owner_count(connection, table_name, ACCOUNT_OWNER) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM workspaces WHERE id = ?", (TARGET_WORKSPACE,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_documents WHERE workspace_id = ?",
            (TARGET_WORKSPACE,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM share_links WHERE workspace_id = ?",
            (TARGET_WORKSPACE,),
        ).fetchone()[0] == 0
        unrelated = connection.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (OTHER_GUEST,)
        ).fetchone()
        assert unrelated["workspace_id"] == OTHER_WORKSPACE
        assert unrelated["expires_at"] == FUTURE_TIME
        assert unrelated["is_active"] == 1
        assert connection.execute(
            "SELECT lifecycle_state FROM guest_tombstones WHERE guest_session_id = ?",
            (TARGET_GUEST,),
        ).fetchone()[0] == "purged"


def test_purge_persists_r2_verifiers_and_deletes_only_exact_object_version(
    monkeypatch, purge_environment
):
    environment = purge_environment
    expected_sha256 = hashlib.sha256(b"remote owned object").hexdigest()
    with sqlite3.connect(environment["app_db"]) as connection:
        connection.execute(
            """
            UPDATE artifacts
               SET storage_backend = 'r2', storage_key = ?, exact_path = '',
                   content_sha256 = ?, metadata_json = ?
             WHERE id = 'artifact-target'
            """,
            (
                "recipe-pdfs/owned.pdf",
                expected_sha256,
                json.dumps(
                    {
                        "expected_etag": "registered-etag",
                        "version_id": "registered-version",
                        "trusted_write": True,
                    }
                ),
            ),
        )
    client = _R2Client(
        {
            "ETag": '"registered-etag"',
            "VersionId": "registered-version",
            "Metadata": {"sha256": expected_sha256},
        }
    )
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)

    result = _apply(environment)

    request = {
        "Bucket": "owned-bucket",
        "Key": "recipe-pdfs/owned.pdf",
        "VersionId": "registered-version",
    }
    assert result["ok"] is True
    assert client.head_calls == [request]
    assert client.delete_calls == [request]


def test_r2_delete_crash_after_physical_delete_retries_as_absent_no_op(
    monkeypatch, purge_environment
):
    environment = purge_environment
    expected_sha256 = hashlib.sha256(b"remote owned object").hexdigest()
    with sqlite3.connect(environment["app_db"]) as connection:
        connection.execute(
            """
            UPDATE artifacts
               SET storage_backend = 'r2', storage_key = ?, exact_path = '',
                   content_sha256 = ?, metadata_json = ?
             WHERE id = 'artifact-target'
            """,
            (
                "recipe-pdfs/retry-owned.pdf",
                expected_sha256,
                json.dumps(
                    {
                        "expected_etag": "registered-etag",
                        "version_id": "registered-version",
                        "trusted_write": True,
                    }
                ),
            ),
        )

    class DeleteThenAbsentClient(_R2Client):
        def __init__(self):
            super().__init__()
            self.deleted = False

        def head_object(self, **parameters):
            self.head_calls.append(parameters)
            if self.deleted:
                raise _R2NotFoundError("already deleted")
            return {
                "ETag": '"registered-etag"',
                "VersionId": "registered-version",
                "Metadata": {"sha256": expected_sha256},
            }

        def delete_object(self, **parameters):
            self.delete_calls.append(parameters)
            self.deleted = True
            return {}

    client = DeleteThenAbsentClient()
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)
    failed_once = {"value": False}

    def crash_after_delete(stage, _context):
        if stage == "after_artifact_cleanup" and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError("simulated crash after remote delete")

    first = _apply(environment, failure_injector=crash_after_delete)
    second = _apply(environment)

    expected_request = {
        "Bucket": "owned-bucket",
        "Key": "recipe-pdfs/retry-owned.pdf",
        "VersionId": "registered-version",
    }
    assert first["ok"] is False
    assert first["code"] == "artifact_delete_failed"
    assert second["ok"] is True
    assert second["run_id"] == first["run_id"]
    assert client.head_calls == [expected_request, expected_request]
    assert client.delete_calls == [expected_request]
    with sqlite3.connect(environment["app_db"]) as connection:
        target = connection.execute(
            """
            SELECT status, attempt_count, error_code
              FROM guest_purge_targets
             WHERE purge_run_id = ? AND target_kind = 'artifact'
            """,
            (first["run_id"],),
        ).fetchone()
    assert target == ("completed", 2, "")


def test_completed_purge_rerun_is_a_safe_no_op(purge_environment):
    first = _apply(purge_environment)
    second = _apply(purge_environment)

    assert first["ok"] is True
    assert second == {
        "ok": True,
        "dry_run": False,
        "applied": True,
        "no_op": True,
        "code": "purge_already_complete",
        "run_id": first["run_id"],
        "guest_session_id": TARGET_GUEST,
        "workspace_id": TARGET_WORKSPACE,
    }
    assert job_service.get_job("unrelated-job") is not None
    assert purge_environment["other_artifact"].exists()


def test_partial_artifact_failure_persists_state_and_retry_resumes(
    purge_environment,
):
    failed_once = {"value": False}

    def inject_failure(stage, _context):
        if stage == "before_artifact_cleanup" and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError("injected artifact outage")

    first = _apply(purge_environment, failure_injector=inject_failure)

    assert first["ok"] is False
    assert first["retryable"] is True
    assert first["code"] == "artifact_delete_failed"
    assert purge_environment["target_artifact"].exists()
    assert purge_environment["target_workspace"].exists()
    with sqlite3.connect(purge_environment["app_db"]) as connection:
        run = connection.execute(
            "SELECT status, attempt_count FROM guest_purge_runs WHERE id = ?",
            (first["run_id"],),
        ).fetchone()
        target = connection.execute(
            """
            SELECT status, attempt_count, error_code
              FROM guest_purge_targets
             WHERE purge_run_id = ? AND target_kind = 'artifact'
            """,
            (first["run_id"],),
        ).fetchone()
        assert run == ("failed", 1)
        assert target == ("failed", 1, "artifact_delete_failed")

    second = _apply(purge_environment)

    assert second["ok"] is True
    assert second["run_id"] == first["run_id"]
    assert not purge_environment["target_artifact"].exists()
    assert not purge_environment["target_workspace"].exists()
    assert purge_environment["other_artifact"].exists()
    with sqlite3.connect(purge_environment["app_db"]) as connection:
        run = connection.execute(
            "SELECT status, attempt_count FROM guest_purge_runs WHERE id = ?",
            (first["run_id"],),
        ).fetchone()
        target = connection.execute(
            """
            SELECT status, attempt_count FROM guest_purge_targets
             WHERE purge_run_id = ? AND target_kind = 'artifact'
            """,
            (first["run_id"],),
        ).fetchone()
        assert run == ("succeeded", 2)
        assert target == ("completed", 2)


def test_database_failure_rolls_back_then_retry_removes_master_rows(
    purge_environment,
):
    failed_once = {"value": False}

    def inject_failure(stage, context):
        if (
            stage == "after_delete"
            and context.get("table") == "ingredients"
            and not failed_once["value"]
        ):
            failed_once["value"] = True
            raise RuntimeError("injected database failure")

    first = _apply(purge_environment, failure_injector=inject_failure)

    assert first["ok"] is False
    assert first["code"] == "database_cleanup_failed"
    with sqlite3.connect(purge_environment["app_db"]) as connection:
        for table_name in recipe_cleanup.OWNER_SCOPED_TABLES:
            assert _owner_count(connection, table_name, TARGET_OWNER) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM workspaces WHERE id = ?", (TARGET_WORKSPACE,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT lifecycle_state FROM guest_sessions WHERE id = ?",
            (TARGET_GUEST,),
        ).fetchone()[0] == "purging"

    second = _apply(purge_environment)

    assert second["ok"] is True
    with sqlite3.connect(purge_environment["app_db"]) as connection:
        assert _owner_count(connection, "ingredients", TARGET_OWNER) == 0
        assert _owner_count(connection, "equipment", TARGET_OWNER) == 0
        assert _owner_count(connection, "ingredients", OTHER_OWNER) == 1


def test_registry_missing_orphan_recipe_master_rows_are_purged(purge_environment):
    environment = purge_environment
    with sqlite3.connect(environment["app_db"]) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "DELETE FROM workspaces WHERE id = ?", (TARGET_WORKSPACE,)
        )

    preview = purge.preview_guest_purge(
        TARGET_GUEST,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    result = _apply(environment)

    assert preview["eligible"] is True
    assert preview["eligibility_reason"] == "orphaned"
    assert result["ok"] is True
    with sqlite3.connect(environment["app_db"]) as connection:
        assert _owner_count(connection, "ingredients", TARGET_OWNER) == 0
        assert _owner_count(connection, "equipment", TARGET_OWNER) == 0
        assert _owner_count(connection, "ingredients", OTHER_OWNER) == 1
        assert connection.execute(
            "SELECT lifecycle_state FROM guest_tombstones WHERE guest_session_id = ?",
            (TARGET_GUEST,),
        ).fetchone()[0] == "purged"


def test_registry_missing_job_and_workspace_are_still_discovered(purge_environment):
    environment = purge_environment
    recipe_result = recipe_cleanup.delete_guest_recipe_data(
        TARGET_GUEST, db_path=environment["app_db"]
    )
    assert recipe_result["ok"] is True
    with sqlite3.connect(environment["app_db"]) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "DELETE FROM workspaces WHERE id = ?", (TARGET_WORKSPACE,)
        )

    preview = purge.preview_guest_purge(
        TARGET_GUEST,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    result = _apply(environment)

    assert preview["eligible"] is True
    assert preview["eligibility_reason"] == "orphaned"
    assert preview["counts"]["recipe_rows"] == 0
    assert preview["counts"]["jobs"] == 1
    assert result["ok"] is True
    assert job_service.get_job("target-job") is None
    assert not environment["target_workspace"].exists()
    assert environment["other_workspace"].exists()


def test_committed_tombstone_fences_new_and_not_yet_started_jobs(
    purge_environment,
):
    failed_once = {"value": False}

    def stop_after_fence(stage, _context):
        if stage == "after_fence" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("simulated process interruption")

    first = _apply(purge_environment, failure_injector=stop_after_fence)

    assert first["ok"] is False
    assert purge.guest_write_is_fenced(
        TARGET_GUEST, db_path=purge_environment["app_db"]
    ) is True
    with pytest.raises(job_service.GuestJobWriteFencedError):
        job_service.create_job(
            "recipe-import",
            guest_session_id=TARGET_GUEST,
            job_id="late-target-job",
        )
    start = job_service.try_start_job("target-job")
    assert start["cancelled"] is True
    assert start["guest_session_purging"] is True
    assert job_service.get_job("unrelated-job")["status"] == "queued"

    retry = _apply(purge_environment)

    assert retry["ok"] is True
    assert retry["run_id"] == first["run_id"]


@pytest.mark.parametrize("operation", ["create", "start"])
def test_guest_job_mutation_is_ordered_before_two_connection_purge_cleanup(
    monkeypatch, purge_environment, operation
):
    environment = purge_environment
    purge_started = environment["guest_root"] / (operation + "-purge-started")
    purge_finished = environment["guest_root"] / (operation + "-purge-finished")
    process_holder = {}
    connection_count = {"value": 0}
    trigger_connection = 1 if operation == "create" else 2
    original_jobs_connection = job_service.jobs_connection
    purge_script = "\n".join(
        (
            "import sqlite3, sys",
            "from pathlib import Path",
            "app_db, jobs_db, guest, workspace, started, finished = sys.argv[1:]",
            "Path(started).write_text('started', encoding='utf-8')",
            "app = sqlite3.connect(app_db, timeout=5)",
            "app.execute('BEGIN IMMEDIATE')",
            "app.execute(\"INSERT INTO guest_tombstones (guest_session_id, workspace_id, purge_run_id, lifecycle_state, tombstoned_at) VALUES (?, ?, 'race-purge', 'purged', '2026-08-14T00:00:00Z') ON CONFLICT(guest_session_id) DO UPDATE SET lifecycle_state = 'purged'\", (guest, workspace))",
            "app.commit()",
            "app.close()",
            "jobs = sqlite3.connect(jobs_db, timeout=5)",
            "jobs.execute('DELETE FROM jobs WHERE guest_session_id = ?', (guest,))",
            "jobs.commit()",
            "jobs.close()",
            "Path(finished).write_text('finished', encoding='utf-8')",
        )
    )

    @contextmanager
    def observed_jobs_connection(db_path=None):
        connection_count["value"] += 1
        with original_jobs_connection(db_path) as connection:
            if connection_count["value"] == trigger_connection:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        purge_script,
                        str(environment["app_db"]),
                        str(environment["jobs_db"]),
                        TARGET_GUEST,
                        TARGET_WORKSPACE,
                        str(purge_started),
                        str(purge_finished),
                    ]
                )
                process_holder["process"] = process
                deadline = time.monotonic() + 2
                while not purge_started.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert purge_started.exists()
                time.sleep(0.05)
                # The independent application DB connection has begun its
                # purge attempt, but it cannot commit the tombstone while this
                # guest job mutation holds the writer reservation.
                assert process.poll() is None
                assert not purge_finished.exists()
            yield connection

    monkeypatch.setattr(job_service, "jobs_connection", observed_jobs_connection)
    if operation == "create":
        job_service.create_job(
            "recipe-import",
            guest_session_id=TARGET_GUEST,
            job_id="racing-created-job",
        )
    else:
        result = job_service.try_start_job("target-job")
        assert result["started"] is True

    process = process_holder["process"]
    assert process.wait(timeout=5) == 0
    assert purge_finished.exists()
    assert job_service.preview_guest_jobs_cleanup(
        TARGET_GUEST, db_path=environment["jobs_db"]
    )["job_count"] == 0

    # The exact guest fence never spills into another owner scope.
    unrelated = job_service.try_start_job("unrelated-job")
    assert unrelated["started"] is True
    assert unrelated["job"]["guest_session_id"] == OTHER_GUEST


def test_json_only_guest_job_creation_does_not_create_application_schema(
    monkeypatch, tmp_path
):
    application_db = tmp_path / "application-data.sqlite3"
    jobs_db = tmp_path / "jobs.sqlite3"
    monkeypatch.delenv("SHOPPING_APP_RECIPE_MASTER_DB", raising=False)
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", application_db)
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", jobs_db)

    created = job_service.create_job(
        "recipe-import", guest_session_id="json-only-guest", job_id="json-only-job"
    )

    assert created["id"] == "json-only-job"
    assert jobs_db.is_file()
    assert not application_db.exists()


def test_running_job_must_acknowledge_cancellation_before_purge_resumes(
    purge_environment,
):
    environment = purge_environment
    job_service.update_job(
        "target-job",
        status="running",
        started_at=OLD_TIME,
        worker_id="test-worker",
    )

    first = _apply(environment)

    assert first["ok"] is False
    assert first["code"] == "guest_jobs_draining"
    assert job_service.get_job("target-job")["status"] == "cancel_requested"
    assert environment["target_workspace"].exists()
    with sqlite3.connect(environment["app_db"]) as connection:
        assert _owner_count(connection, "ingredients", TARGET_OWNER) == 1

    acknowledged = job_service.cancel_job(
        "target-job", message="Worker acknowledged cancellation"
    )
    assert acknowledged["status"] == "cancelled"
    second = _apply(environment)

    assert second["ok"] is True
    assert second["run_id"] == first["run_id"]
    assert job_service.get_job("target-job") is None
    assert not environment["target_workspace"].exists()


def test_future_active_guest_is_rejected_without_fencing(purge_environment):
    environment = purge_environment
    result = purge.purge_expired_guest(
        OTHER_GUEST,
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert result["code"] == "guest_not_eligible"
    assert purge.guest_write_is_fenced(OTHER_GUEST, db_path=environment["app_db"]) is False
    assert environment["other_workspace"].exists()
    assert job_service.get_job("unrelated-job") is not None


def test_batch_preview_apply_and_rerun_are_safe_and_idempotent(purge_environment):
    environment = purge_environment
    _mark_guest_registry_covered(environment["app_db"])

    preview = purge.purge_expired_guest_batch(
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["eligible_ids"] == [TARGET_GUEST]
    assert OTHER_GUEST in preview["skipped_ids"]
    assert environment["target_workspace"].exists()

    applied = purge.purge_expired_guest_batch(
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_BATCH_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    rerun = purge.purge_expired_guest_batch(
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_BATCH_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert applied["ok"] is True
    assert applied["deleted_count"] == 1
    assert applied["guest_session_ids"] == [TARGET_GUEST]
    assert rerun["ok"] is True
    assert rerun["no_op"] is True
    assert rerun["deleted_count"] == 0
    assert environment["other_workspace"].exists()
    assert job_service.get_job("unrelated-job") is not None


def test_batch_requires_completed_guest_migration_without_deleting_legacy_data(
    purge_environment,
):
    environment = purge_environment
    before_database = _file_sha256(environment["app_db"])

    result = purge.purge_expired_guest_batch(
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_BATCH_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert result["applied"] is False
    assert result["code"] == "guest_migration_incomplete"
    assert _file_sha256(environment["app_db"]) == before_database
    assert environment["target_workspace"].exists()
    assert environment["target_artifact"].exists()


def test_batch_aggregates_retryable_failure_and_next_run_resumes(
    purge_environment,
):
    environment = purge_environment
    _mark_guest_registry_covered(environment["app_db"])
    failed_once = {"value": False}

    def inject_failure(stage, _context):
        if stage == "before_artifact_cleanup" and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError("temporary artifact outage")

    first = purge.purge_expired_guest_batch(
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_BATCH_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
        failure_injector=inject_failure,
    )

    assert first["ok"] is False
    assert first["code"] == "batch_purge_incomplete"
    assert first["deleted_count"] == 0
    assert first["retryable_failures"] == [{
        "guest_session_id": TARGET_GUEST,
        "code": "artifact_delete_failed",
        "run_id": first["retryable_failures"][0]["run_id"],
    }]
    assert first["terminal_failures"] == []
    assert environment["target_artifact"].exists()

    second = purge.purge_expired_guest_batch(
        dry_run=False,
        authorized=True,
        approval=purge.GUEST_PURGE_BATCH_APPROVAL_PHRASE,
        db_path=environment["app_db"],
        jobs_db_path=environment["jobs_db"],
        guest_base_dir=environment["guest_root"],
        at_time=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert second["ok"] is True
    assert second["deleted_count"] == 1
    assert second["guest_session_ids"] == [TARGET_GUEST]
    assert not environment["target_artifact"].exists()


def test_r2_artifact_delete_heads_and_deletes_exact_verified_version(monkeypatch):
    expected_sha256 = hashlib.sha256(b"owned object").hexdigest()
    client = _R2Client(
        {
            "ETag": '"registered-etag"',
            "VersionId": "registered-version",
            "Metadata": {"sha256": expected_sha256},
        }
    )
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)
    target = {
        "expected_sha256": expected_sha256,
        "metadata_json": _trusted_r2_metadata(
            "recipe-pdfs/owned.pdf",
            expected_etag="registered-etag",
            version_id="registered-version",
        ),
    }

    result = purge._delete_r2_artifact(target)

    expected_request = {
        "Bucket": "owned-bucket",
        "Key": "recipe-pdfs/owned.pdf",
        "VersionId": "registered-version",
    }
    assert result["ok"] is True
    assert result["verification_count"] == 3
    assert client.head_calls == [expected_request]
    assert client.delete_calls == [expected_request]


@pytest.mark.parametrize(
    ("target", "head_result", "expected_code"),
    [
        (
            {
                "metadata_json": _trusted_r2_metadata(
                    "recipe-pdfs/unverified.pdf"
                )
            },
            {"ETag": '"remote"'},
            "artifact_object_verification_missing",
        ),
        (
            {
                "metadata_json": _trusted_r2_metadata(
                    "recipe-pdfs/mismatch.pdf",
                    expected_etag="registered",
                )
            },
            {"ETag": '"different"'},
            "artifact_object_etag_mismatch",
        ),
        (
            {
                "expected_sha256": hashlib.sha256(b"registered").hexdigest(),
                "metadata_json": _trusted_r2_metadata(
                    "recipe-pdfs/checksum.pdf"
                ),
            },
            {
                "Metadata": {
                    "sha256": hashlib.sha256(b"different").hexdigest()
                }
            },
            "artifact_object_checksum_mismatch",
        ),
    ],
)
def test_r2_artifact_delete_fails_retryably_before_unverified_delete(
    monkeypatch, target, head_result, expected_code
):
    client = _R2Client(head_result)
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)

    with pytest.raises(purge.GuestPurgePhaseError) as captured:
        purge._delete_r2_artifact(target)

    assert captured.value.code == expected_code
    assert client.delete_calls == []


def test_r2_artifact_head_absence_is_retryable_and_never_deletes(monkeypatch):
    client = _R2Client(head_error=_R2NotFoundError("missing"))
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)

    with pytest.raises(purge.GuestPurgePhaseError) as captured:
        purge._delete_r2_artifact(
            {
                "metadata_json": _trusted_r2_metadata(
                    "recipe-pdfs/missing.pdf",
                    version_id="registered-version",
                )
            }
        )

    assert captured.value.code == "artifact_object_missing"
    assert client.delete_calls == []


@pytest.mark.parametrize(
    ("metadata_json", "expected_code"),
    [
        (
            purge._canonical_json(
                {
                    "storage_key": "recipe-pdfs/untrusted.pdf",
                    "version_id": "registered-version",
                    "owner_workspace_id": TARGET_WORKSPACE,
                }
            ),
            "artifact_object_untrusted",
        ),
        (
            _trusted_r2_metadata(
                "arbitrary-owner-prefix/forged.pdf",
                version_id="registered-version",
            ),
            "artifact_storage_key_untrusted",
        ),
    ],
)
def test_r2_artifact_delete_rejects_untrusted_receipts_and_arbitrary_prefixes(
    monkeypatch, metadata_json, expected_code
):
    client = _R2Client({"VersionId": "registered-version"})
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)

    with pytest.raises(purge.GuestPurgePhaseError) as captured:
        purge._delete_r2_artifact({"metadata_json": metadata_json})

    assert captured.value.code == expected_code
    assert client.head_calls == []
    assert client.delete_calls == []


def test_r2_absence_after_verification_mismatch_remains_retryable(monkeypatch):
    client = _R2Client(head_error=_R2NotFoundError("missing"))
    monkeypatch.setattr(
        cloudflare_r2_storage, "config_values", lambda: {"bucket_name": "owned-bucket"}
    )
    monkeypatch.setattr(cloudflare_r2_storage, "r2_client", lambda: client)

    with pytest.raises(purge.GuestPurgePhaseError) as captured:
        purge._delete_r2_artifact(
            {
                "status": "failed",
                "attempt_count": 1,
                "error_code": "artifact_object_etag_mismatch",
                "metadata_json": _trusted_r2_metadata(
                    "recipe-pdfs/mismatch-gone.pdf",
                    expected_etag="registered",
                ),
            }
        )

    assert captured.value.code == "artifact_object_missing"
    assert client.delete_calls == []
