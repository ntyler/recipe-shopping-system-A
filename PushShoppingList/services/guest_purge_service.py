"""Persisted, retryable purge saga for one expired guest.

The recipe-master and application-owned rows share one SQLite database and are
deleted in one ``BEGIN IMMEDIATE`` transaction.  Jobs, local files, and object
storage cannot join that transaction, so they are represented by durable
``guest_purge_targets`` and completed idempotently.  Missing local targets are
safe no-ops; object-storage deletion additionally requires a fresh immutable
identity check and fails safely for operator reconciliation when it cannot be
verified.

The public entry point is dry-run first.  Applying a purge requires both an
authorization boolean and the exact approval phrase below.  This module never
installs schema and never creates a missing application database.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import guest_file_cleanup_service
from PushShoppingList.services import guest_recipe_cleanup_service
from PushShoppingList.services import maintenance_log_service
from PushShoppingList.services import recipe_master_data_service


GUEST_PURGE_APPROVAL_PHRASE = "PURGE EXPIRED GUEST DATA"
GUEST_PURGE_BATCH_APPROVAL_PHRASE = "PURGE ALL EXPIRED GUEST DATA"
GUEST_PURGE_LEASE_SECONDS = 300

RUN_RUNNING = "running"
RUN_FAILED = "failed"
RUN_SUCCEEDED = "succeeded"

TARGET_PENDING = "pending"
TARGET_RUNNING = "running"
TARGET_FAILED = "failed"
TARGET_COMPLETED = "completed"


class GuestPurgeError(RuntimeError):
    """Base guest-purge error with a stable, non-sensitive error code."""

    code = "guest_purge_failed"


class GuestPurgeApprovalError(GuestPurgeError):
    code = "approval_required"


class GuestPurgeBusyError(GuestPurgeError):
    code = "purge_already_claimed"


class GuestPurgeEligibilityError(GuestPurgeError):
    code = "guest_not_eligible"


class GuestPurgePhaseError(GuestPurgeError):
    def __init__(self, code, message="Guest purge phase failed."):
        super().__init__(message)
        self.code = str(code or "guest_purge_phase_failed")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_timestamp(value: Optional[datetime] = None) -> str:
    value = value or _utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: object) -> Optional[datetime]:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_guest_session_id(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("guest_session_id must be a non-empty opaque string.")
    if value != value.strip():
        raise ValueError("guest_session_id must be exact and cannot contain edge whitespace.")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_mapping(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _stable_target_id(run_id: str, target_kind: str, target_key: str) -> str:
    material = "\x1f".join((run_id, target_kind, target_key)).encode("utf-8")
    return "purge-target:" + hashlib.sha256(material).hexdigest()


def _lease_name(guest_session_id: str) -> str:
    digest = hashlib.sha256(guest_session_id.encode("utf-8")).hexdigest()
    return "guest-purge:" + digest


def _resolved_app_path(db_path=None) -> Path:
    return application_data.application_data_db_path(db_path)


def _resolved_recipe_path(recipe_db_path=None, db_path=None) -> Path:
    if recipe_db_path is not None:
        return Path(recipe_db_path)
    return _resolved_app_path(db_path)


def _resolved_jobs_path(jobs_db_path=None) -> Path:
    if jobs_db_path is not None:
        return Path(jobs_db_path)
    from PushShoppingList.services import job_service

    return Path(job_service.JOBS_DB_PATH)


def guest_write_is_fenced(guest_session_id, *, db_path=None) -> bool:
    """Return whether a durable tombstone forbids new guest-owned writes.

    This is intentionally read-only and returns ``False`` when the database or
    tombstone table has not been installed.  Once the table exists, database
    errors fail closed so cleanup cannot race new job creation.
    """

    try:
        guest_session_id = _validate_guest_session_id(guest_session_id)
    except ValueError:
        return True
    path = _resolved_app_path(db_path)
    if not path.is_file():
        return False
    connection = None
    try:
        uri = "%s?mode=ro" % path.resolve().as_uri()
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'guest_tombstones'"
        ).fetchone()
        if table is None:
            return False
        row = connection.execute(
            "SELECT lifecycle_state FROM guest_tombstones WHERE guest_session_id = ?",
            (guest_session_id,),
        ).fetchone()
        return bool(row and str(row[0] or "") in {"purging", "purged"})
    except sqlite3.Error:
        return True
    finally:
        if connection is not None:
            connection.close()


def _latest_run(connection, guest_session_id: str):
    return connection.execute(
        """
        SELECT *
          FROM guest_purge_runs
         WHERE guest_session_id = ? AND dry_run = 0
         ORDER BY started_at DESC, id DESC
         LIMIT 1
        """,
        (guest_session_id,),
    ).fetchone()


def _workspace_for_guest(connection, guest_session_id: str):
    session_row = connection.execute(
        "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
    ).fetchone()
    if session_row is not None:
        workspace = connection.execute(
            "SELECT * FROM workspaces WHERE id = ?", (session_row["workspace_id"],)
        ).fetchone()
        if (
            workspace is None
            or str(workspace["workspace_type"]) != "guest"
            or str(workspace["external_id"]) != guest_session_id
        ):
            raise GuestPurgeEligibilityError(
                "Guest session workspace ownership is missing or inconsistent."
            )
        return session_row, workspace, str(session_row["workspace_id"])

    workspace = connection.execute(
        """
        SELECT * FROM workspaces
         WHERE workspace_type = 'guest' AND external_id = ?
        """,
        (guest_session_id,),
    ).fetchone()
    if workspace is not None:
        return None, workspace, str(workspace["id"])

    fallback_id = "guest:%s" % guest_session_id
    collision = connection.execute(
        "SELECT workspace_type, external_id FROM workspaces WHERE id = ?",
        (fallback_id,),
    ).fetchone()
    if collision is not None:
        raise GuestPurgeEligibilityError(
            "The fallback guest workspace identity belongs to another subject."
        )
    return None, None, fallback_id


def _application_counts(connection, guest_session_id: str, workspace_id: str) -> dict:
    queries = {
        "guest_sessions": (
            "SELECT COUNT(*) FROM guest_sessions WHERE id = ? OR workspace_id = ?",
            (guest_session_id, workspace_id),
        ),
        "durable_documents": (
            "SELECT COUNT(*) FROM durable_documents WHERE workspace_id = ?",
            (workspace_id,),
        ),
        "source_coverage": (
            "SELECT COUNT(*) FROM application_source_coverage WHERE workspace_id = ?",
            (workspace_id,),
        ),
        "artifacts": (
            "SELECT COUNT(*) FROM artifacts WHERE workspace_id = ?",
            (workspace_id,),
        ),
        "share_links": (
            "SELECT COUNT(*) FROM share_links WHERE workspace_id = ?",
            (workspace_id,),
        ),
        "accounts": (
            "SELECT COUNT(*) FROM accounts WHERE workspace_id = ?",
            (workspace_id,),
        ),
        "workspaces": (
            "SELECT COUNT(*) FROM workspaces WHERE id = ?",
            (workspace_id,),
        ),
    }
    return {
        name: int(connection.execute(sql, parameters).fetchone()[0] or 0)
        for name, (sql, parameters) in queries.items()
    }


def _artifact_rows(connection, workspace_id: str) -> list:
    rows = connection.execute(
        """
        SELECT id, artifact_kind, storage_backend, storage_key, exact_path,
               content_sha256, byte_count, exclusive_owner, lifecycle_state,
               metadata_json
          FROM artifacts
         WHERE workspace_id = ?
         ORDER BY id
        """,
        (workspace_id,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "artifact_kind": str(row["artifact_kind"]),
            "storage_backend": str(row["storage_backend"]),
            "storage_key": str(row["storage_key"]),
            "exact_path": str(row["exact_path"] or ""),
            "expected_sha256": str(row["content_sha256"] or ""),
            "byte_count": int(row["byte_count"] or 0),
            "exclusive_owner": bool(row["exclusive_owner"]),
            "lifecycle_state": str(row["lifecycle_state"] or ""),
            "metadata": _json_mapping(row["metadata_json"]),
        }
        for row in rows
    ]


def _eligibility(
    session_row,
    workspace_row,
    recipe_rows,
    artifact_count,
    external_owned_data,
    tombstone_row,
    latest_run,
    now,
):
    if latest_run is not None:
        if latest_run["status"] == RUN_SUCCEEDED:
            return True, "already_purged"
        return True, "retry"
    if tombstone_row is not None and tombstone_row["lifecycle_state"] == "purging":
        return True, "retry_tombstone"
    if session_row is not None:
        expiration = _parse_timestamp(session_row["expires_at"])
        if expiration is None:
            return False, "invalid_expiration"
        if expiration > now:
            return False, "active_or_unexpired"
        return True, "expired"
    if (
        workspace_row is not None
        or recipe_rows > 0
        or artifact_count > 0
        or external_owned_data
    ):
        return True, "orphaned"
    return False, "guest_not_found"


def preview_guest_purge(
    guest_session_id,
    *,
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    guest_base_dir=None,
    at_time: Optional[datetime] = None,
) -> dict:
    """Build a read-only purge manifest without creating files or schema."""

    try:
        guest_session_id = _validate_guest_session_id(guest_session_id)
    except ValueError as exc:
        return {
            "ok": False,
            "dry_run": True,
            "applied": False,
            "code": "invalid_guest_session_id",
            "error": str(exc),
        }

    app_path = _resolved_app_path(db_path)
    recipe_path = _resolved_recipe_path(recipe_db_path, db_path)
    now = at_time or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    try:
        with application_data.existing_application_read_connection(app_path) as connection:
            if connection is None or not application_data.application_schema_available(
                connection=connection
            ):
                return {
                    "ok": False,
                    "dry_run": True,
                    "applied": False,
                    "code": "application_schema_unavailable",
                }
            session_row, workspace_row, workspace_id = _workspace_for_guest(
                connection, guest_session_id
            )
            latest_run = _latest_run(connection, guest_session_id)
            tombstone_row = connection.execute(
                "SELECT * FROM guest_tombstones WHERE guest_session_id = ?",
                (guest_session_id,),
            ).fetchone()
            if latest_run is not None and session_row is None and workspace_row is None:
                # Once the atomic database phase deletes the workspace, the
                # persisted run remains the authority for retries.  This also
                # preserves custom migrated workspace UUIDs rather than
                # replacing them with the legacy ``guest:<id>`` fallback.
                workspace_id = str(latest_run["workspace_id"])
            artifacts = _artifact_rows(connection, workspace_id)
            application_counts = _application_counts(
                connection, guest_session_id, workspace_id
            )
            session_snapshot = dict(session_row) if session_row is not None else None
            run_snapshot = dict(latest_run) if latest_run is not None else None
    except (sqlite3.Error, GuestPurgeError) as exc:
        return {
            "ok": False,
            "dry_run": True,
            "applied": False,
            "code": getattr(exc, "code", "database_error"),
        }

    recipe_preview = guest_recipe_cleanup_service.preview_guest_recipe_cleanup(
        guest_session_id,
        db_path=recipe_path,
    )
    if not recipe_preview.get("ok"):
        return {
            "ok": False,
            "dry_run": True,
            "applied": False,
            "code": "recipe_%s" % recipe_preview.get("code", "preview_failed"),
            "recipe": recipe_preview,
        }

    from PushShoppingList.services import job_service

    jobs_preview = job_service.preview_guest_jobs_cleanup(
        guest_session_id,
        db_path=_resolved_jobs_path(jobs_db_path),
    )
    workspace_preview = guest_file_cleanup_service.preview_guest_workspace_cleanup(
        guest_session_id,
        base_dir=guest_base_dir,
    )
    eligible, eligibility_reason = _eligibility(
        session_snapshot,
        workspace_row,
        int(recipe_preview.get("total_rows") or 0),
        len(artifacts),
        bool(
            int(jobs_preview.get("job_count") or 0)
            or workspace_preview.get("exists")
        ),
        tombstone_row,
        run_snapshot,
        now,
    )
    counts = {
        "recipe_rows": int(recipe_preview.get("total_rows") or 0),
        "application_rows": sum(application_counts.values()),
        "artifact_records": len(artifacts),
        "exclusive_artifacts": sum(1 for item in artifacts if item["exclusive_owner"]),
        "jobs": int(jobs_preview.get("job_count") or 0),
        "active_jobs": int(jobs_preview.get("active_job_count") or 0),
        "workspace_files": int(workspace_preview.get("file_count") or 0),
        "workspace_bytes": int(workspace_preview.get("size_bytes") or 0),
    }
    manifest_material = {
        "guest_session_id": guest_session_id,
        "workspace_id": workspace_id,
        "application_counts": application_counts,
        "recipe_counts": recipe_preview.get("counts", {}),
        "jobs": jobs_preview,
        "workspace": {
            key: workspace_preview.get(key)
            for key in (
                "ok",
                "exists",
                "workspace_relative_path",
                "file_count",
                "directory_count",
                "size_bytes",
            )
        },
        "artifacts": artifacts,
    }
    manifest_sha256 = hashlib.sha256(
        _canonical_json(manifest_material).encode("utf-8")
    ).hexdigest()
    result = {
        "ok": True,
        "dry_run": True,
        "applied": False,
        "code": "preview_complete",
        "eligible": eligible,
        "eligibility_reason": eligibility_reason,
        "guest_session_id": guest_session_id,
        "workspace_id": workspace_id,
        "application_database_path": str(app_path),
        "recipe_database_path": str(recipe_path),
        "jobs_database_path": str(_resolved_jobs_path(jobs_db_path)),
        "manifest_sha256": manifest_sha256,
        "counts": counts,
        "application_counts": application_counts,
        "recipe": recipe_preview,
        "jobs": jobs_preview,
        "workspace": workspace_preview,
        "artifacts": artifacts,
        "existing_run": run_snapshot,
    }
    maintenance_log_service.emit_maintenance_event(
        event="guest_purge",
        run_id=(run_snapshot or {}).get("id", "preview:" + manifest_sha256[:16]),
        phase="preview",
        mode="dry_run",
        outcome="preview",
        counts=counts,
        workspace_id=workspace_id,
        source_sha256=manifest_sha256,
    )
    return result


def _acquire_lease(connection, guest_session_id: str, claim_token: str, now: datetime):
    name = _lease_name(guest_session_id)
    row = connection.execute(
        "SELECT * FROM leases WHERE lease_name = ?", (name,)
    ).fetchone()
    if row is not None:
        expires = _parse_timestamp(row["expires_at"])
        if row["holder_id"] != claim_token and expires is not None and expires > now:
            raise GuestPurgeBusyError("Another process holds the guest purge lease.")
        connection.execute(
            """
            UPDATE leases
               SET holder_id = ?, acquired_at = ?, heartbeat_at = ?, expires_at = ?,
                   row_version = row_version + 1
             WHERE lease_name = ?
            """,
            (
                claim_token,
                _utc_timestamp(now),
                _utc_timestamp(now),
                _utc_timestamp(now + timedelta(seconds=GUEST_PURGE_LEASE_SECONDS)),
                name,
            ),
        )
    else:
        connection.execute(
            """
            INSERT INTO leases (
                lease_name, holder_id, acquired_at, heartbeat_at, expires_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                claim_token,
                _utc_timestamp(now),
                _utc_timestamp(now),
                _utc_timestamp(now + timedelta(seconds=GUEST_PURGE_LEASE_SECONDS)),
            ),
        )
    return name


def _release_lease(db_path, lease_name: str, claim_token: str):
    if not lease_name:
        return
    try:
        with application_data.application_data_write_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM leases WHERE lease_name = ? AND holder_id = ?",
                (lease_name, claim_token),
            )
    except Exception:
        # The lease has a bounded expiry and can be recovered after a crash or
        # database outage.  Cleanup results must not be hidden by release errors.
        return


def _renew_lease(db_path, guest_session_id: str, claim_token: str):
    """Heartbeat the cross-process lease and verify the run claim is current."""

    name = _lease_name(guest_session_id)
    now = _utc_now()
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        lease = connection.execute(
            "SELECT holder_id FROM leases WHERE lease_name = ?", (name,)
        ).fetchone()
        if lease is None or str(lease["holder_id"]) != claim_token:
            raise GuestPurgeBusyError("Guest purge lease changed or expired.")
        claimed_run = connection.execute(
            """
            SELECT 1 FROM guest_purge_runs
             WHERE guest_session_id = ? AND claim_token = ? AND status = 'running'
            """,
            (guest_session_id, claim_token),
        ).fetchone()
        if claimed_run is None:
            raise GuestPurgeBusyError("Guest purge claim changed.")
        connection.execute(
            """
            UPDATE leases
               SET heartbeat_at = ?, expires_at = ?, row_version = row_version + 1
             WHERE lease_name = ? AND holder_id = ?
            """,
            (
                _utc_timestamp(now),
                _utc_timestamp(now + timedelta(seconds=GUEST_PURGE_LEASE_SECONDS)),
                name,
                claim_token,
            ),
        )


def _insert_target(
    connection,
    *,
    run_id: str,
    guest_session_id: str,
    target_kind: str,
    target_key: str,
    exact_path: str = "",
    expected_sha256: str = "",
    metadata: Optional[Mapping] = None,
):
    connection.execute(
        """
        INSERT OR IGNORE INTO guest_purge_targets (
            id, purge_run_id, guest_session_id, target_kind, target_key,
            exact_path, expected_sha256, status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            _stable_target_id(run_id, target_kind, target_key),
            run_id,
            guest_session_id,
            target_kind,
            target_key,
            exact_path,
            expected_sha256,
            _canonical_json(dict(metadata or {})),
        ),
    )


def _fence_guest(preview: dict, claim_token: str, at_time: datetime):
    guest_session_id = preview["guest_session_id"]
    workspace_id = preview["workspace_id"]
    db_path = Path(preview["application_database_path"])
    now_text = _utc_timestamp(at_time)
    with recipe_master_data_service.RECIPE_MASTER_DB_LOCK:
        with application_data.application_data_write_connection(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            lease_name = _acquire_lease(connection, guest_session_id, claim_token, at_time)
            run = _latest_run(connection, guest_session_id)
            if run is not None and run["status"] == RUN_SUCCEEDED:
                return dict(run), lease_name, True

            session_row, workspace_row, locked_workspace_id = _workspace_for_guest(
                connection, guest_session_id
            )
            if run is not None and session_row is None and workspace_row is None:
                locked_workspace_id = str(run["workspace_id"])
            if locked_workspace_id != workspace_id:
                raise GuestPurgeEligibilityError(
                    "Guest workspace ownership changed after preview."
                )
            if session_row is not None:
                expiration = _parse_timestamp(session_row["expires_at"])
                if expiration is None or expiration > at_time:
                    raise GuestPurgeEligibilityError(
                        "An active or unexpired guest cannot be purged."
                    )

            run_id = str(run["id"]) if run is not None else uuid.uuid4().hex
            summary = _json_mapping(run["summary_json"]) if run is not None else {}
            artifacts = _artifact_rows(connection, workspace_id)
            manifest_material = {
                "preview_sha256": preview["manifest_sha256"],
                "artifact_ids": [item["id"] for item in artifacts],
                "workspace_id": workspace_id,
            }
            manifest_sha256 = hashlib.sha256(
                _canonical_json(manifest_material).encode("utf-8")
            ).hexdigest()
            if run is None:
                connection.execute(
                    """
                    INSERT INTO guest_purge_runs (
                        id, guest_session_id, workspace_id, status, phase, dry_run,
                        attempt_count, claim_token, claimed_at, started_at, updated_at,
                        manifest_sha256, summary_json
                    ) VALUES (?, ?, ?, 'running', 'fence', 0, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        guest_session_id,
                        workspace_id,
                        claim_token,
                        now_text,
                        now_text,
                        now_text,
                        manifest_sha256,
                        _canonical_json(summary),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE guest_purge_runs
                       SET status = 'running', phase = 'fence',
                           attempt_count = attempt_count + 1,
                           claim_token = ?, claimed_at = ?, updated_at = ?,
                           completed_at = '', error_code = '',
                           row_version = row_version + 1
                     WHERE id = ?
                    """,
                    (claim_token, now_text, now_text, run_id),
                )

            tombstone = connection.execute(
                "SELECT lifecycle_state FROM guest_tombstones WHERE guest_session_id = ?",
                (guest_session_id,),
            ).fetchone()
            if tombstone is not None and tombstone["lifecycle_state"] == "purged":
                raise GuestPurgeEligibilityError(
                    "A completed tombstone cannot be returned to purging state."
                )
            connection.execute(
                """
                INSERT INTO guest_tombstones (
                    guest_session_id, workspace_id, purge_run_id, lifecycle_state,
                    tombstoned_at, reason_code, source_sha256
                ) VALUES (?, ?, ?, 'purging', ?, 'expired_guest', ?)
                ON CONFLICT(guest_session_id) DO UPDATE SET
                    workspace_id = excluded.workspace_id,
                    purge_run_id = excluded.purge_run_id,
                    reason_code = excluded.reason_code
                """,
                (
                    guest_session_id,
                    workspace_id,
                    run_id,
                    now_text,
                    str(run["manifest_sha256"]) if run is not None else manifest_sha256,
                ),
            )
            if session_row is not None:
                connection.execute(
                    """
                    UPDATE guest_sessions
                       SET is_active = 0, lifecycle_state = 'purging',
                           ended_at = CASE WHEN ended_at = '' THEN ? ELSE ended_at END,
                           updated_at = ?, row_version = row_version + 1
                     WHERE id = ?
                    """,
                    (now_text, now_text, guest_session_id),
                )
            if workspace_row is not None:
                connection.execute(
                    """
                    UPDATE workspaces
                       SET lifecycle_state = 'purging', updated_at = ?,
                           row_version = row_version + 1
                     WHERE id = ?
                    """,
                    (now_text, workspace_id),
                )

            _insert_target(
                connection,
                run_id=run_id,
                guest_session_id=guest_session_id,
                target_kind="jobs",
                target_key=guest_session_id,
                metadata={"database_path": preview["jobs_database_path"]},
            )
            _insert_target(
                connection,
                run_id=run_id,
                guest_session_id=guest_session_id,
                target_kind="workspace",
                target_key=guest_session_id,
                metadata={
                    "workspace_relative_path": preview.get("workspace", {}).get(
                        "workspace_relative_path", ""
                    )
                },
            )
            for artifact in artifacts:
                artifact_metadata = artifact.get("metadata") or {}
                _insert_target(
                    connection,
                    run_id=run_id,
                    guest_session_id=guest_session_id,
                    target_kind="artifact",
                    target_key=artifact["id"],
                    exact_path=artifact["exact_path"],
                    expected_sha256=artifact["expected_sha256"],
                    metadata={
                        "artifact_kind": artifact["artifact_kind"],
                        "storage_backend": artifact["storage_backend"],
                        "storage_key": artifact["storage_key"],
                        "exclusive_owner": artifact["exclusive_owner"],
                        "expected_etag": str(
                            artifact_metadata.get("expected_etag") or ""
                        ).strip().strip('"'),
                        "version_id": str(
                            artifact_metadata.get("version_id") or ""
                        ).strip(),
                        # Only a creation-path receipt may authorize physical
                        # deletion from object storage. Document-derived
                        # references and legacy backfill rows remain metadata
                        # only even if they contain a syntactically valid key.
                        "trusted_write": artifact_metadata.get("trusted_write")
                        is True,
                        "owner_workspace_id": workspace_id,
                    },
                )
            connection.execute(
                """
                UPDATE guest_purge_runs
                   SET phase = 'fenced', updated_at = ?, row_version = row_version + 1
                 WHERE id = ? AND claim_token = ?
                """,
                (now_text, run_id, claim_token),
            )
            persisted = connection.execute(
                "SELECT * FROM guest_purge_runs WHERE id = ?", (run_id,)
            ).fetchone()
            return dict(persisted), lease_name, False


def _load_run(db_path, run_id: str) -> Optional[dict]:
    with application_data.existing_application_read_connection(db_path) as connection:
        if connection is None:
            return None
        row = connection.execute(
            "SELECT * FROM guest_purge_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row is not None else None


def _load_targets(db_path, run_id: str, target_kind: str = "") -> list:
    with application_data.existing_application_read_connection(db_path) as connection:
        if connection is None:
            return []
        sql = "SELECT * FROM guest_purge_targets WHERE purge_run_id = ?"
        parameters = [run_id]
        if target_kind:
            sql += " AND target_kind = ?"
            parameters.append(target_kind)
        sql += " ORDER BY target_kind, target_key"
        return [dict(row) for row in connection.execute(sql, tuple(parameters)).fetchall()]


def _set_target_state(
    db_path,
    target_id: str,
    claim_token: str,
    status: str,
    *,
    error_code: str = "",
    increment_attempt: bool = False,
):
    now = _utc_timestamp()
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE guest_purge_targets
               SET status = ?,
                   attempt_count = attempt_count + ?,
                   last_attempt_at = CASE WHEN ? = 1 THEN ? ELSE last_attempt_at END,
                   completed_at = CASE WHEN ? = 'completed' THEN ? ELSE '' END,
                   error_code = ?
             WHERE id = ?
               AND EXISTS (
                   SELECT 1
                     FROM guest_purge_runs AS purge_run
                    WHERE purge_run.id = guest_purge_targets.purge_run_id
                      AND purge_run.claim_token = ?
                      AND purge_run.status = 'running'
               )
            """,
            (
                status,
                int(increment_attempt),
                int(increment_attempt),
                now,
                status,
                now,
                error_code,
                target_id,
                claim_token,
            ),
        )
        if cursor.rowcount != 1:
            raise GuestPurgeBusyError("Guest purge target claim changed.")


def _update_run_state(
    db_path,
    run_id: str,
    claim_token: str,
    *,
    status: str,
    phase: str,
    error_code: str = "",
    summary_changes: Optional[Mapping] = None,
    completed: bool = False,
):
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT summary_json FROM guest_purge_runs WHERE id = ? AND claim_token = ?",
            (run_id, claim_token),
        ).fetchone()
        if row is None:
            raise GuestPurgeBusyError("Guest purge claim changed.")
        summary = _json_mapping(row["summary_json"])
        summary.update(dict(summary_changes or {}))
        now = _utc_timestamp()
        connection.execute(
            """
            UPDATE guest_purge_runs
               SET status = ?, phase = ?, updated_at = ?,
                   completed_at = CASE WHEN ? = 1 THEN ? ELSE completed_at END,
                   error_code = ?, summary_json = ?, row_version = row_version + 1
             WHERE id = ? AND claim_token = ?
            """,
            (
                status,
                phase,
                now,
                int(completed),
                now,
                error_code,
                _canonical_json(summary),
                run_id,
                claim_token,
            ),
        )


def _run_failure_injector(failure_injector, stage: str, **context):
    if callable(failure_injector):
        failure_injector(stage, dict(context))


def _execute_jobs_phase(
    *,
    db_path,
    run_id: str,
    claim_token: str,
    guest_session_id: str,
    jobs_db_path,
    rq_canceller=None,
    failure_injector=None,
):
    _renew_lease(db_path, guest_session_id, claim_token)
    targets = _load_targets(db_path, run_id, "jobs")
    if not targets or targets[0]["status"] == TARGET_COMPLETED:
        return 0
    target = targets[0]
    _set_target_state(
        db_path,
        target["id"],
        claim_token,
        TARGET_RUNNING,
        increment_attempt=True,
    )
    try:
        _run_failure_injector(failure_injector, "before_jobs_cleanup")
        from PushShoppingList.services import job_service

        resolved_jobs = _resolved_jobs_path(jobs_db_path)
        if not resolved_jobs.is_file():
            deleted = 0
        else:
            cancellation = job_service.request_guest_job_cancellation(
                guest_session_id,
                db_path=resolved_jobs,
            )
            if not cancellation.get("ok"):
                raise GuestPurgePhaseError("job_cancellation_failed")
            if rq_canceller is None:
                from PushShoppingList.services.job_queue_service import cancel_queued_rq_job

                rq_canceller = cancel_queued_rq_job
            for rq_job_id in cancellation.get("rq_job_ids", []):
                if not rq_canceller(rq_job_id):
                    raise GuestPurgePhaseError("rq_job_cancellation_failed")
            if cancellation.get("running_job_ids"):
                # A running worker may already hold guest data in memory.  Keep
                # the durable fence in place and retry only after the worker has
                # acknowledged cancellation; deleting its row early would hide
                # whether the worker actually drained.
                raise GuestPurgePhaseError("guest_jobs_draining")
            deleted = int(
                job_service.delete_guest_jobs(
                    guest_session_id,
                    db_path=resolved_jobs,
                )
                or 0
            )
            remaining = job_service.preview_guest_jobs_cleanup(
                guest_session_id,
                db_path=resolved_jobs,
            )
            if not remaining.get("ok") or int(remaining.get("job_count") or 0):
                raise GuestPurgePhaseError("job_delete_incomplete")
        _run_failure_injector(
            failure_injector, "after_jobs_cleanup", deleted_count=deleted
        )
    except GuestPurgePhaseError as exc:
        _set_target_state(
            db_path, target["id"], claim_token, TARGET_FAILED, error_code=exc.code
        )
        raise
    except Exception as exc:
        _set_target_state(
            db_path,
            target["id"],
            claim_token,
            TARGET_FAILED,
            error_code="job_cleanup_failed",
        )
        raise GuestPurgePhaseError("job_cleanup_failed") from exc
    _set_target_state(db_path, target["id"], claim_token, TARGET_COMPLETED)
    _update_run_state(
        db_path,
        run_id,
        claim_token,
        status=RUN_RUNNING,
        phase="jobs",
        summary_changes={"jobs_deleted": deleted},
    )
    return deleted


def _execute_database_phase(
    *,
    db_path,
    recipe_db_path,
    run_id: str,
    claim_token: str,
    guest_session_id: str,
    workspace_id: str,
    failure_injector=None,
):
    _renew_lease(db_path, guest_session_id, claim_token)
    run = _load_run(db_path, run_id) or {}
    summary = _json_mapping(run.get("summary_json"))
    if summary.get("database_cleanup_complete"):
        return summary.get("database_counts", {})
    if Path(db_path).resolve() != Path(recipe_db_path).resolve():
        raise GuestPurgePhaseError("non_atomic_database_layout")

    try:
        with recipe_master_data_service.RECIPE_MASTER_DB_LOCK:
            with application_data.application_data_write_connection(db_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                claimed = connection.execute(
                    "SELECT 1 FROM guest_purge_runs WHERE id = ? AND claim_token = ?",
                    (run_id, claim_token),
                ).fetchone()
                if claimed is None:
                    raise GuestPurgeBusyError("Guest purge claim changed.")
                _run_failure_injector(failure_injector, "before_database_cleanup")
                application_before = _application_counts(
                    connection, guest_session_id, workspace_id
                )
                recipe_result = (
                    guest_recipe_cleanup_service.delete_guest_recipe_data_with_connection(
                        connection,
                        guest_session_id,
                        failure_injector=failure_injector,
                    )
                )
                _run_failure_injector(
                    failure_injector,
                    "after_recipe_database_cleanup",
                    deleted_count=recipe_result["total_rows"],
                )
                share_cursor = connection.execute(
                    "DELETE FROM share_links WHERE workspace_id = ?", (workspace_id,)
                )
                connection.execute(
                    "DELETE FROM guest_sessions WHERE id = ? AND workspace_id = ?",
                    (guest_session_id, workspace_id),
                )
                workspace_cursor = connection.execute(
                    "DELETE FROM workspaces WHERE id = ?", (workspace_id,)
                )
                application_after = _application_counts(
                    connection, guest_session_id, workspace_id
                )
                if any(application_after.values()):
                    raise GuestPurgePhaseError("application_rows_remain")
                database_counts = {
                    "recipe_rows": int(recipe_result["total_rows"]),
                    "share_links": max(0, int(share_cursor.rowcount or 0)),
                    "workspaces": max(0, int(workspace_cursor.rowcount or 0)),
                    "application_rows_before": sum(application_before.values()),
                }
                current = connection.execute(
                    "SELECT summary_json FROM guest_purge_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                next_summary = _json_mapping(current["summary_json"])
                next_summary.update(
                    {
                        "database_cleanup_complete": True,
                        "database_counts": database_counts,
                    }
                )
                now = _utc_timestamp()
                connection.execute(
                    """
                    UPDATE guest_purge_runs
                       SET phase = 'database', updated_at = ?, summary_json = ?,
                           row_version = row_version + 1
                     WHERE id = ? AND claim_token = ?
                    """,
                    (
                        now,
                        _canonical_json(next_summary),
                        run_id,
                        claim_token,
                    ),
                )
                _run_failure_injector(
                    failure_injector,
                    "before_database_commit",
                    deleted_count=sum(database_counts.values()),
                )
        _run_failure_injector(failure_injector, "after_database_cleanup")
        return database_counts
    except GuestPurgeError:
        raise
    except Exception as exc:
        raise GuestPurgePhaseError("database_cleanup_failed") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _delete_local_artifact(target: Mapping) -> dict:
    exact_path = str(target.get("exact_path") or "")
    path = Path(exact_path)
    if not exact_path or not path.is_absolute():
        raise GuestPurgePhaseError("artifact_path_not_absolute")
    try:
        path.lstat()
    except FileNotFoundError:
        return {"ok": True, "no_op": True}
    except OSError as exc:
        raise GuestPurgePhaseError("artifact_path_unreadable") from exc
    if path.is_symlink() or _is_reparse_point(path) or not path.is_file():
        raise GuestPurgePhaseError("artifact_path_unsafe")
    expected = str(target.get("expected_sha256") or "")
    if expected and _sha256_file(path) != expected:
        raise GuestPurgePhaseError("artifact_checksum_mismatch")
    path.unlink()
    if path.exists():
        raise GuestPurgePhaseError("artifact_delete_incomplete")
    return {"ok": True, "no_op": False}


def _delete_r2_artifact(target: Mapping) -> dict:
    metadata = _json_mapping(target.get("metadata_json"))
    object_key = str(metadata.get("storage_key") or "")
    if (
        not object_key
        or object_key != object_key.strip()
        or "\x00" in object_key
        or "\\" in object_key
        or object_key.startswith("/")
        or any(part in {".", ".."} for part in object_key.split("/"))
    ):
        raise GuestPurgePhaseError("artifact_storage_key_missing")
    if metadata.get("trusted_write") is not True or not str(
        metadata.get("owner_workspace_id") or ""
    ).strip():
        raise GuestPurgePhaseError("artifact_object_untrusted")
    expected_etag = str(metadata.get("expected_etag") or "").strip().strip('"')
    version_id = str(metadata.get("version_id") or "").strip()
    expected_sha256 = str(target.get("expected_sha256") or "").strip().lower()
    if expected_etag and ("\x00" in expected_etag or len(expected_etag) > 256):
        raise GuestPurgePhaseError("artifact_object_verification_missing")
    if version_id and ("\x00" in version_id or len(version_id) > 1024):
        raise GuestPurgePhaseError("artifact_object_verification_missing")
    if expected_sha256 and (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise GuestPurgePhaseError("artifact_object_verification_missing")
    if not (expected_etag or version_id or expected_sha256):
        # Backfilled/unverifiable R2 rows must be registered non-exclusive.
        # Refuse physical deletion if a malformed legacy row says otherwise.
        raise GuestPurgePhaseError("artifact_object_verification_missing")
    from PushShoppingList.services import cloudflare_r2_storage

    try:
        object_key = cloudflare_r2_storage.validate_pdf_object_key(object_key)
        object_key = cloudflare_r2_storage.validate_object_key(
            object_key,
            allowed_prefixes=cloudflare_r2_storage.ALLOWED_PDF_OBJECT_PREFIXES,
        )
    except cloudflare_r2_storage.CloudflareR2StorageError as exc:
        raise GuestPurgePhaseError("artifact_storage_key_untrusted") from exc

    try:
        values = cloudflare_r2_storage.config_values()
        client = cloudflare_r2_storage.r2_client()
    except Exception as exc:
        raise GuestPurgePhaseError("artifact_object_head_failed") from exc

    head_parameters = {"Bucket": values["bucket_name"], "Key": object_key}
    if version_id:
        head_parameters["VersionId"] = version_id
    try:
        head = client.head_object(**head_parameters) or {}
    except Exception as exc:
        if cloudflare_r2_storage.r2_error_is_not_found(exc):
            previous_status = str(target.get("status") or "").strip().lower()
            previous_error = str(target.get("error_code") or "").strip()
            try:
                previous_attempts = int(target.get("attempt_count") or 0)
            except (TypeError, ValueError):
                previous_attempts = 0
            delete_outcome_was_ambiguous = bool(
                previous_attempts > 0
                and (
                    (previous_status == TARGET_RUNNING and not previous_error)
                    or (
                        previous_status == TARGET_FAILED
                        and previous_error
                        in {"artifact_delete_failed", "artifact_object_delete_failed"}
                    )
                )
            )
            if delete_outcome_was_ambiguous:
                # The prior process may have successfully deleted the exact
                # verified object and crashed before persisting target
                # completion. A subsequent authoritative HEAD absence is the
                # idempotent success condition. Verification/mismatch failures
                # are deliberately excluded from this recovery path.
                return {
                    "ok": True,
                    "no_op": True,
                    "already_absent": True,
                    "object_key": object_key,
                    "versioned": bool(version_id),
                    "verification_count": 0,
                }
            raise GuestPurgePhaseError("artifact_object_missing") from exc
        raise GuestPurgePhaseError("artifact_object_head_failed") from exc
    if not isinstance(head, Mapping):
        raise GuestPurgePhaseError("artifact_object_head_failed")

    verification_count = 0
    actual_etag = str(head.get("ETag") or "").strip().strip('"')
    if expected_etag:
        if not actual_etag:
            raise GuestPurgePhaseError("artifact_object_verification_missing")
        if actual_etag != expected_etag:
            raise GuestPurgePhaseError("artifact_object_etag_mismatch")
        verification_count += 1

    if version_id:
        actual_version = str(head.get("VersionId") or "").strip()
        if actual_version and actual_version != version_id:
            raise GuestPurgePhaseError("artifact_object_version_mismatch")
        # Supplying VersionId to both HEAD and DELETE addresses the exact
        # immutable object version even when R2 omits it from HEAD responses.
        verification_count += 1

    custom_metadata = head.get("Metadata")
    custom_metadata = custom_metadata if isinstance(custom_metadata, Mapping) else {}
    actual_sha256 = str(custom_metadata.get("sha256") or "").strip().lower()
    if not actual_sha256:
        checksum_value = str(head.get("ChecksumSHA256") or "").strip()
        if checksum_value:
            if len(checksum_value) == 64 and all(
                character in "0123456789abcdefABCDEF" for character in checksum_value
            ):
                actual_sha256 = checksum_value.lower()
            else:
                try:
                    decoded_checksum = base64.b64decode(checksum_value, validate=True)
                except (ValueError, binascii.Error):
                    decoded_checksum = b""
                if len(decoded_checksum) == 32:
                    actual_sha256 = decoded_checksum.hex()
    if expected_sha256:
        if not actual_sha256:
            if not verification_count:
                raise GuestPurgePhaseError("artifact_object_verification_missing")
        elif actual_sha256 != expected_sha256:
            raise GuestPurgePhaseError("artifact_object_checksum_mismatch")
        else:
            verification_count += 1
    if not verification_count:
        raise GuestPurgePhaseError("artifact_object_verification_missing")

    delete_parameters = {"Bucket": values["bucket_name"], "Key": object_key}
    if version_id:
        delete_parameters["VersionId"] = version_id
    try:
        client.delete_object(**delete_parameters)
    except Exception as exc:
        raise GuestPurgePhaseError("artifact_object_delete_failed") from exc
    return {
        "ok": True,
        "object_key": object_key,
        "versioned": bool(version_id),
        "verification_count": verification_count,
    }


def _artifact_deleter_for(target: Mapping, artifact_deleters=None) -> Callable:
    metadata = _json_mapping(target.get("metadata_json"))
    backend = str(metadata.get("storage_backend") or "").strip().lower()
    configured = dict(artifact_deleters or {})
    if backend in configured:
        return configured[backend]
    if backend in {"local", "filesystem", "file"}:
        return _delete_local_artifact
    if backend in {"r2", "cloudflare_r2", "cloudflare-r2"}:
        return _delete_r2_artifact
    raise GuestPurgePhaseError("artifact_backend_unsupported")


def _execute_artifact_targets(
    *,
    db_path,
    run_id: str,
    claim_token: str,
    guest_session_id: str,
    artifact_deleters=None,
    failure_injector=None,
):
    completed = 0
    for target in _load_targets(db_path, run_id, "artifact"):
        if target["status"] == TARGET_COMPLETED:
            continue
        _renew_lease(db_path, guest_session_id, claim_token)
        _set_target_state(
            db_path,
            target["id"],
            claim_token,
            TARGET_RUNNING,
            increment_attempt=True,
        )
        try:
            metadata = _json_mapping(target.get("metadata_json"))
            _run_failure_injector(
                failure_injector,
                "before_artifact_cleanup",
                target_id=target["id"],
            )
            if not bool(metadata.get("exclusive_owner")):
                result = {"ok": True, "metadata_only": True}
            else:
                deleter = _artifact_deleter_for(target, artifact_deleters)
                result = deleter(target)
                if result is False or (
                    isinstance(result, Mapping) and not result.get("ok", False)
                ):
                    raise GuestPurgePhaseError("artifact_delete_failed")
            _run_failure_injector(
                failure_injector,
                "after_artifact_cleanup",
                target_id=target["id"],
            )
        except GuestPurgePhaseError as exc:
            _set_target_state(
                db_path,
                target["id"],
                claim_token,
                TARGET_FAILED,
                error_code=exc.code,
            )
            raise
        except Exception as exc:
            _set_target_state(
                db_path,
                target["id"],
                claim_token,
                TARGET_FAILED,
                error_code="artifact_delete_failed",
            )
            raise GuestPurgePhaseError("artifact_delete_failed") from exc
        _set_target_state(db_path, target["id"], claim_token, TARGET_COMPLETED)
        completed += 1
    return completed


def _execute_workspace_target(
    *,
    db_path,
    run_id: str,
    claim_token: str,
    guest_session_id: str,
    guest_base_dir=None,
    failure_injector=None,
):
    _renew_lease(db_path, guest_session_id, claim_token)
    targets = _load_targets(db_path, run_id, "workspace")
    if not targets or targets[0]["status"] == TARGET_COMPLETED:
        return 0
    target = targets[0]
    _set_target_state(
        db_path,
        target["id"],
        claim_token,
        TARGET_RUNNING,
        increment_attempt=True,
    )

    def workspace_injector(stage, context):
        _run_failure_injector(
            failure_injector,
            "workspace_%s" % stage,
            **dict(context or {}),
        )

    result = guest_file_cleanup_service.delete_guest_workspace(
        guest_session_id,
        base_dir=guest_base_dir,
        failure_injector=workspace_injector,
    )
    if not result.get("ok") or not result.get("applied"):
        code = str(result.get("code") or "workspace_delete_failed")
        _set_target_state(
            db_path, target["id"], claim_token, TARGET_FAILED, error_code=code
        )
        raise GuestPurgePhaseError(code)
    _set_target_state(db_path, target["id"], claim_token, TARGET_COMPLETED)
    return int(not result.get("no_op", False))


def _finalize_run(
    db_path,
    run_id: str,
    claim_token: str,
    guest_session_id: str,
    failure_injector=None,
):
    _renew_lease(db_path, guest_session_id, claim_token)
    _run_failure_injector(failure_injector, "before_finalize")
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        remaining = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM guest_purge_targets
                 WHERE purge_run_id = ? AND status <> 'completed'
                """,
                (run_id,),
            ).fetchone()[0]
            or 0
        )
        if remaining:
            raise GuestPurgePhaseError("purge_targets_incomplete")
        run = connection.execute(
            "SELECT * FROM guest_purge_runs WHERE id = ? AND claim_token = ?",
            (run_id, claim_token),
        ).fetchone()
        if run is None:
            raise GuestPurgeBusyError("Guest purge claim changed.")
        summary = _json_mapping(run["summary_json"])
        summary["target_count"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM guest_purge_targets WHERE purge_run_id = ?",
                (run_id,),
            ).fetchone()[0]
            or 0
        )
        now = _utc_timestamp()
        tombstone_cursor = connection.execute(
            """
            UPDATE guest_tombstones
               SET lifecycle_state = 'purged', completed_at = ?
             WHERE guest_session_id = ? AND purge_run_id = ?
            """,
            (now, run["guest_session_id"], run_id),
        )
        if tombstone_cursor.rowcount != 1:
            raise GuestPurgePhaseError("guest_tombstone_missing")
        connection.execute(
            """
            UPDATE guest_purge_runs
               SET status = 'succeeded', phase = 'completed', updated_at = ?,
                   completed_at = ?, error_code = '', summary_json = ?,
                   row_version = row_version + 1
             WHERE id = ? AND claim_token = ?
            """,
            (now, now, _canonical_json(summary), run_id, claim_token),
        )
    return _load_run(db_path, run_id)


def purge_expired_guest(
    guest_session_id,
    *,
    dry_run: bool = True,
    authorized: bool = False,
    approval: str = "",
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    guest_base_dir=None,
    at_time: Optional[datetime] = None,
    artifact_deleters=None,
    rq_canceller=None,
    failure_injector=None,
) -> dict:
    """Preview or apply an exact, retryable expired-guest purge.

    Applying never happens implicitly: callers must pass ``dry_run=False``,
    ``authorized=True``, and :data:`GUEST_PURGE_APPROVAL_PHRASE` exactly.
    """

    if dry_run:
        return preview_guest_purge(
            guest_session_id,
            db_path=db_path,
            recipe_db_path=recipe_db_path,
            jobs_db_path=jobs_db_path,
            guest_base_dir=guest_base_dir,
            at_time=at_time,
        )
    if not authorized or approval != GUEST_PURGE_APPROVAL_PHRASE:
        raise GuestPurgeApprovalError(
            "Guest purge requires explicit authorization and the exact approval phrase."
        )

    at_time = at_time or _utc_now()
    if at_time.tzinfo is None:
        at_time = at_time.replace(tzinfo=timezone.utc)
    at_time = at_time.astimezone(timezone.utc).replace(microsecond=0)
    preview = preview_guest_purge(
        guest_session_id,
        db_path=db_path,
        recipe_db_path=recipe_db_path,
        jobs_db_path=jobs_db_path,
        guest_base_dir=guest_base_dir,
        at_time=at_time,
    )
    if not preview.get("ok"):
        return {**preview, "dry_run": False}
    if Path(preview["application_database_path"]).resolve() != Path(
        preview["recipe_database_path"]
    ).resolve():
        return {
            "ok": False,
            "dry_run": False,
            "applied": False,
            "retryable": False,
            "code": "non_atomic_database_layout",
        }
    existing = preview.get("existing_run") or {}
    if existing.get("status") == RUN_SUCCEEDED:
        return {
            "ok": True,
            "dry_run": False,
            "applied": True,
            "no_op": True,
            "code": "purge_already_complete",
            "run_id": existing["id"],
            "guest_session_id": preview["guest_session_id"],
            "workspace_id": preview["workspace_id"],
        }
    if not preview.get("eligible"):
        return {
            "ok": False,
            "dry_run": False,
            "applied": False,
            "code": "guest_not_eligible",
            "eligibility_reason": preview.get("eligibility_reason"),
        }

    claim_token = uuid.uuid4().hex
    lease_name = ""
    run_id = ""
    started = _utc_now()
    try:
        run, lease_name, already_complete = _fence_guest(
            preview, claim_token, at_time
        )
        run_id = str(run["id"])
        if already_complete:
            return {
                "ok": True,
                "dry_run": False,
                "applied": True,
                "no_op": True,
                "code": "purge_already_complete",
                "run_id": run_id,
            }
        maintenance_log_service.emit_maintenance_event(
            event="guest_purge",
            run_id=run_id,
            phase="fenced",
            mode="apply",
            outcome="started",
            counts=preview["counts"],
            workspace_id=preview["workspace_id"],
            source_sha256=preview["manifest_sha256"],
        )
        _run_failure_injector(failure_injector, "after_fence")
        jobs_deleted = _execute_jobs_phase(
            db_path=preview["application_database_path"],
            run_id=run_id,
            claim_token=claim_token,
            guest_session_id=preview["guest_session_id"],
            jobs_db_path=jobs_db_path,
            rq_canceller=rq_canceller,
            failure_injector=failure_injector,
        )
        database_counts = _execute_database_phase(
            db_path=preview["application_database_path"],
            recipe_db_path=preview["recipe_database_path"],
            run_id=run_id,
            claim_token=claim_token,
            guest_session_id=preview["guest_session_id"],
            workspace_id=preview["workspace_id"],
            failure_injector=failure_injector,
        )
        artifacts_deleted = _execute_artifact_targets(
            db_path=preview["application_database_path"],
            run_id=run_id,
            claim_token=claim_token,
            guest_session_id=preview["guest_session_id"],
            artifact_deleters=artifact_deleters,
            failure_injector=failure_injector,
        )
        workspace_deleted = _execute_workspace_target(
            db_path=preview["application_database_path"],
            run_id=run_id,
            claim_token=claim_token,
            guest_session_id=preview["guest_session_id"],
            guest_base_dir=guest_base_dir,
            failure_injector=failure_injector,
        )
        final_run = _finalize_run(
            preview["application_database_path"],
            run_id,
            claim_token,
            preview["guest_session_id"],
            failure_injector=failure_injector,
        )
        duration_ms = int((_utc_now() - started).total_seconds() * 1000)
        completion_counts = {
            "jobs_deleted": jobs_deleted,
            "artifacts_completed": artifacts_deleted,
            "workspace_deleted": workspace_deleted,
            "recipe_rows_deleted": int(database_counts.get("recipe_rows") or 0),
            "application_rows_deleted": int(
                database_counts.get("application_rows_before") or 0
            ),
        }
        maintenance_log_service.emit_maintenance_event(
            event="guest_purge",
            run_id=run_id,
            phase="completed",
            mode="apply",
            outcome="complete",
            counts=completion_counts,
            duration_ms=duration_ms,
            workspace_id=preview["workspace_id"],
            source_sha256=preview["manifest_sha256"],
        )
        return {
            "ok": True,
            "dry_run": False,
            "applied": True,
            "no_op": not any(completion_counts.values()),
            "code": "purge_complete",
            "run_id": run_id,
            "guest_session_id": preview["guest_session_id"],
            "workspace_id": preview["workspace_id"],
            "counts": completion_counts,
            "run": final_run,
        }
    except Exception as exc:
        error_code = getattr(exc, "code", "guest_purge_failed")
        if run_id:
            try:
                _update_run_state(
                    preview["application_database_path"],
                    run_id,
                    claim_token,
                    status=RUN_FAILED,
                    phase="failed",
                    error_code=error_code,
                )
            except Exception:
                pass
        maintenance_log_service.emit_maintenance_event(
            event="guest_purge",
            run_id=run_id,
            phase="failed",
            mode="apply",
            outcome="failed",
            counts={},
            duration_ms=int((_utc_now() - started).total_seconds() * 1000),
            workspace_id=preview.get("workspace_id", ""),
            source_sha256=preview.get("manifest_sha256", ""),
            error_code=error_code,
        )
        return {
            "ok": False,
            "dry_run": False,
            "applied": bool(run_id),
            "retryable": True,
            "code": error_code,
            "run_id": run_id,
        }
    finally:
        _release_lease(
            preview.get("application_database_path", _resolved_app_path(db_path)),
            lease_name,
            claim_token,
        )


def _require_guest_migration_coverage(db_path) -> dict:
    """Require a completed registry backfill before batch discovery."""

    try:
        from PushShoppingList.services import guest_session_migration_service

        coverage = guest_session_migration_service.database_coverage_status(db_path)
    except Exception as exc:
        raise GuestPurgePhaseError("guest_migration_unavailable") from exc
    if not isinstance(coverage, Mapping) or coverage.get("status") != "covered":
        raise GuestPurgePhaseError("guest_migration_incomplete")
    return dict(coverage)


def _recipe_guest_owner_ids(recipe_db_path) -> set:
    path = Path(recipe_db_path)
    if not path.is_file():
        raise GuestPurgePhaseError("recipe_database_not_found")
    connection = None
    try:
        uri = "%s?mode=ro" % path.resolve().as_uri()
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        schema = guest_recipe_cleanup_service.validate_guest_recipe_cleanup_manifest(
            connection
        )
        owners = set()
        for table_name in schema.get("present_manifest_tables", []):
            if table_name not in guest_recipe_cleanup_service.OWNER_SCOPED_TABLES:
                continue
            quoted = '"' + str(table_name).replace('"', '""') + '"'
            for row in connection.execute(
                f"SELECT DISTINCT user_id FROM {quoted} WHERE user_id LIKE 'guest:%'"
            ).fetchall():
                owner = str(row["user_id"] or "")
                if owner.startswith("guest:") and len(owner) > len("guest:"):
                    owners.add(owner[len("guest:"):])
        return owners
    except guest_recipe_cleanup_service.GuestRecipeCleanupManifestError as exc:
        raise GuestPurgePhaseError("recipe_manifest_drift") from exc
    except sqlite3.Error as exc:
        raise GuestPurgePhaseError("recipe_candidate_discovery_failed") from exc
    finally:
        if connection is not None:
            connection.close()


def _job_guest_owner_ids(jobs_db_path) -> set:
    path = Path(jobs_db_path)
    if not path.is_file():
        return set()
    connection = None
    try:
        uri = "%s?mode=ro" % path.resolve().as_uri()
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone() is None:
            return set()
        return {
            str(row["guest_session_id"])
            for row in connection.execute(
                """
                SELECT DISTINCT guest_session_id FROM jobs
                 WHERE COALESCE(guest_session_id, '') <> ''
                """
            ).fetchall()
        }
    except sqlite3.Error as exc:
        raise GuestPurgePhaseError("job_candidate_discovery_failed") from exc
    finally:
        if connection is not None:
            connection.close()


def discover_guest_purge_candidates(
    *,
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    at_time: Optional[datetime] = None,
) -> dict:
    """Discover expired, retryable, and DB-proven orphan guest identities."""

    app_path = _resolved_app_path(db_path)
    recipe_path = _resolved_recipe_path(recipe_db_path, db_path)
    jobs_path = _resolved_jobs_path(jobs_db_path)
    now = at_time or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    try:
        coverage = _require_guest_migration_coverage(app_path)
        with application_data.existing_application_read_connection(app_path) as connection:
            if connection is None or not application_data.application_schema_available(
                connection=connection
            ):
                raise GuestPurgePhaseError("application_schema_unavailable")
            candidates = set()
            expired_ids = set()
            retryable_ids = set()
            tombstoned_ids = set()
            orphan_workspace_ids = set()
            for row in connection.execute(
                "SELECT id, expires_at FROM guest_sessions ORDER BY id"
            ).fetchall():
                expiration = _parse_timestamp(row["expires_at"])
                if expiration is None:
                    raise GuestPurgePhaseError("invalid_guest_expiration")
                if expiration <= now:
                    expired_ids.add(str(row["id"]))
            retryable_ids.update(
                str(row["guest_session_id"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT guest_session_id FROM guest_purge_runs
                     WHERE dry_run = 0 AND status IN ('running', 'failed')
                    """
                ).fetchall()
            )
            tombstoned_ids.update(
                str(row["guest_session_id"])
                for row in connection.execute(
                    """
                    SELECT guest_session_id FROM guest_tombstones
                     WHERE lifecycle_state = 'purging'
                    """
                ).fetchall()
            )
            orphan_workspace_ids.update(
                str(row["external_id"])
                for row in connection.execute(
                    """
                    SELECT workspace.external_id
                      FROM workspaces AS workspace
                      LEFT JOIN guest_sessions AS guest
                        ON guest.workspace_id = workspace.id
                     WHERE workspace.workspace_type = 'guest' AND guest.id IS NULL
                    """
                ).fetchall()
            )
        recipe_owner_ids = _recipe_guest_owner_ids(recipe_path)
        job_owner_ids = _job_guest_owner_ids(jobs_path)
        candidates.update(expired_ids)
        candidates.update(retryable_ids)
        candidates.update(tombstoned_ids)
        candidates.update(orphan_workspace_ids)
        candidates.update(recipe_owner_ids)
        candidates.update(job_owner_ids)
        invalid = sorted(
            value
            for value in candidates
            if not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\x00" in value
        )
        if invalid:
            raise GuestPurgePhaseError("invalid_discovered_guest_identity")
        return {
            "ok": True,
            "code": "candidate_discovery_complete",
            "candidate_ids": sorted(candidates),
            "expired_ids": sorted(expired_ids),
            "retryable_ids": sorted(retryable_ids),
            "tombstoned_ids": sorted(tombstoned_ids),
            "orphan_workspace_ids": sorted(orphan_workspace_ids),
            "orphan_recipe_owner_ids": sorted(recipe_owner_ids),
            "job_owner_ids": sorted(job_owner_ids),
            "coverage": coverage,
        }
    except GuestPurgeError as exc:
        return {
            "ok": False,
            "code": exc.code,
            "candidate_ids": [],
        }
    except Exception:
        return {
            "ok": False,
            "code": "candidate_discovery_failed",
            "candidate_ids": [],
        }


def preview_expired_guest_purge_batch(
    *,
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    guest_base_dir=None,
    at_time: Optional[datetime] = None,
) -> dict:
    """Preview every safely discoverable expired/orphan guest purge."""

    discovery = discover_guest_purge_candidates(
        db_path=db_path,
        recipe_db_path=recipe_db_path,
        jobs_db_path=jobs_db_path,
        at_time=at_time,
    )
    if not discovery.get("ok"):
        return {
            "ok": False,
            "dry_run": True,
            "applied": False,
            "code": discovery.get("code", "candidate_discovery_failed"),
            "discovery": discovery,
        }
    previews = []
    for guest_session_id in discovery["candidate_ids"]:
        item = preview_guest_purge(
            guest_session_id,
            db_path=db_path,
            recipe_db_path=recipe_db_path,
            jobs_db_path=jobs_db_path,
            guest_base_dir=guest_base_dir,
            at_time=at_time,
        )
        if not item.get("ok"):
            return {
                "ok": False,
                "dry_run": True,
                "applied": False,
                "code": "candidate_preview_failed",
                "failed_guest_session_id": guest_session_id,
                "candidate_code": item.get("code", "preview_failed"),
                "discovery": discovery,
            }
        previews.append(item)
    eligible = [item for item in previews if item.get("eligible")]
    return {
        "ok": True,
        "dry_run": True,
        "applied": False,
        "code": "batch_preview_complete",
        "candidate_count": len(previews),
        "eligible_count": len(eligible),
        "candidate_ids": [item["guest_session_id"] for item in previews],
        "eligible_ids": [item["guest_session_id"] for item in eligible],
        "skipped_ids": [
            item["guest_session_id"] for item in previews if not item.get("eligible")
        ],
        "counts": {
            "recipe_rows": sum(int(item["counts"].get("recipe_rows") or 0) for item in eligible),
            "application_rows": sum(
                int(item["counts"].get("application_rows") or 0) for item in eligible
            ),
            "jobs": sum(int(item["counts"].get("jobs") or 0) for item in eligible),
            "artifact_records": sum(
                int(item["counts"].get("artifact_records") or 0) for item in eligible
            ),
            "workspace_files": sum(
                int(item["counts"].get("workspace_files") or 0) for item in eligible
            ),
        },
        "previews": previews,
        "discovery": discovery,
    }


def purge_expired_guest_batch(
    *,
    dry_run: bool = True,
    authorized: bool = False,
    approval: str = "",
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    guest_base_dir=None,
    at_time: Optional[datetime] = None,
    artifact_deleters=None,
    rq_canceller=None,
    failure_injector=None,
) -> dict:
    """Preview or apply all eligible guest purges, aggregating failures."""

    preview = preview_expired_guest_purge_batch(
        db_path=db_path,
        recipe_db_path=recipe_db_path,
        jobs_db_path=jobs_db_path,
        guest_base_dir=guest_base_dir,
        at_time=at_time,
    )
    if dry_run or not preview.get("ok"):
        return preview if dry_run else {**preview, "dry_run": False}
    if not authorized or approval != GUEST_PURGE_BATCH_APPROVAL_PHRASE:
        raise GuestPurgeApprovalError(
            "Batch guest purge requires explicit authorization and the exact approval phrase."
        )

    succeeded = []
    already_complete = []
    retryable_failures = []
    terminal_failures = []
    for guest_session_id in preview["eligible_ids"]:
        result = purge_expired_guest(
            guest_session_id,
            dry_run=False,
            authorized=True,
            approval=GUEST_PURGE_APPROVAL_PHRASE,
            db_path=db_path,
            recipe_db_path=recipe_db_path,
            jobs_db_path=jobs_db_path,
            guest_base_dir=guest_base_dir,
            at_time=at_time,
            artifact_deleters=artifact_deleters,
            rq_canceller=rq_canceller,
            failure_injector=failure_injector,
        )
        item = {
            "guest_session_id": guest_session_id,
            "code": str(result.get("code") or "guest_purge_failed"),
            "run_id": str(result.get("run_id") or ""),
        }
        if result.get("ok"):
            if result.get("no_op"):
                already_complete.append(item)
            else:
                succeeded.append(item)
        elif result.get("retryable"):
            retryable_failures.append(item)
        else:
            terminal_failures.append(item)
    failures = retryable_failures + terminal_failures
    return {
        "ok": not failures,
        "dry_run": False,
        "applied": True,
        "no_op": not succeeded and not failures,
        "code": "batch_purge_complete" if not failures else "batch_purge_incomplete",
        "candidate_count": preview["candidate_count"],
        "eligible_count": preview["eligible_count"],
        "deleted_count": len(succeeded),
        "guest_session_ids": [item["guest_session_id"] for item in succeeded],
        "succeeded": succeeded,
        "already_complete": already_complete,
        "retryable_failures": retryable_failures,
        "terminal_failures": terminal_failures,
        "failure_count": len(failures),
    }


__all__ = [
    "GUEST_PURGE_BATCH_APPROVAL_PHRASE",
    "GUEST_PURGE_APPROVAL_PHRASE",
    "GuestPurgeApprovalError",
    "GuestPurgeBusyError",
    "GuestPurgeEligibilityError",
    "GuestPurgeError",
    "GuestPurgePhaseError",
    "guest_write_is_fenced",
    "discover_guest_purge_candidates",
    "preview_expired_guest_purge_batch",
    "preview_guest_purge",
    "purge_expired_guest",
    "purge_expired_guest_batch",
]
