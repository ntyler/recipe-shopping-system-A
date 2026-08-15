"""Explicit application-data schema and transactional repository helpers.

The application data lives in the dynamically resolved recipe-master SQLite
database, but its schema is never installed by import, reads, or ordinary write
connections.  Additive DDL is available only through
``install_application_schema`` with both an exact phrase and an authorization
flag.  This keeps legacy runtime databases untouched until an operator approves
the migration.

All source identities are opaque text and are preserved verbatim.  Repository
results use parsed JSON alongside scalar columns, while database storage uses
canonical JSON.  Errors intentionally avoid embedding payloads, tokens, email
addresses, or raw database values.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


APPLICATION_SCHEMA_COMPONENT = "application_data"
APPLICATION_SCHEMA_VERSION = 1
SCHEMA_INSTALL_APPROVAL_PHRASE = "INSTALL APPLICATION DATA SCHEMA"
APPLICATION_DATA_LOCK = threading.RLock()

WORKSPACE_LIFECYCLE_STATES = frozenset({"active", "inactive", "purging", "purged"})
GUEST_LIFECYCLE_STATES = frozenset({"active", "inactive", "purging", "purged", "failed"})
MIGRATION_RUN_STATES = frozenset({"planned", "running", "succeeded", "failed", "cancelled"})
TERMINAL_MIGRATION_RUN_STATES = frozenset({"succeeded", "failed", "cancelled"})

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,160}$")
_UNSET = object()


class ApplicationDataError(RuntimeError):
    """Base application-data repository error."""


class ApplicationSchemaApprovalError(ApplicationDataError):
    """Raised when additive schema installation was not explicitly approved."""


class ApplicationSchemaUnavailableError(ApplicationDataError):
    """Raised when a write is attempted before explicit schema installation."""


class ApplicationSchemaCompatibilityError(ApplicationDataError):
    """Raised when existing table names have an incompatible shape."""


class ApplicationDataValidationError(ApplicationDataError, ValueError):
    """Raised when a repository input cannot be stored without normalization."""


class ApplicationDataCollisionError(ApplicationDataError):
    """Raised when an opaque identity already belongs to different data."""


class ApplicationDataLifecycleError(ApplicationDataError):
    """Raised when an operation would resurrect or extend expired guest state."""


class ApplicationDataIntegrityError(ApplicationDataError):
    """Raised when stored canonical data is unreadable or internally inconsistent."""


_TABLE_STATEMENTS: Tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_versions (
        component TEXT PRIMARY KEY,
        version INTEGER NOT NULL CHECK (version >= 1),
        checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),
        installed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS migration_runs (
        id TEXT PRIMARY KEY,
        migration_kind TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('planned','running','succeeded','failed','cancelled')),
        source_sha256 TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL DEFAULT '',
        error_code TEXT NOT NULL DEFAULT '',
        summary_json TEXT NOT NULL DEFAULT '{}',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        workspace_type TEXT NOT NULL,
        external_id TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL DEFAULT 'active'
            CHECK (lifecycle_state IN ('active','inactive','purging','purged')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        source_sha256 TEXT NOT NULL DEFAULT '',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
        UNIQUE (workspace_type, external_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL UNIQUE
            REFERENCES workspaces(id) ON DELETE CASCADE,
        username TEXT NOT NULL DEFAULT '',
        normalized_email TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        password_hash TEXT NOT NULL DEFAULT '',
        firebase_uid TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        profile_json TEXT NOT NULL DEFAULT '{}',
        auth_metadata_json TEXT NOT NULL DEFAULT '{}',
        encrypted_secrets_json TEXT NOT NULL DEFAULT '{}',
        encryption_key_id TEXT NOT NULL DEFAULT '',
        source_sha256 TEXT NOT NULL DEFAULT '',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_sessions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE,
        workspace_id TEXT NOT NULL UNIQUE
            REFERENCES workspaces(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT NOT NULL,
        ended_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
        lifecycle_state TEXT NOT NULL DEFAULT 'active'
            CHECK (lifecycle_state IN ('active','inactive','purging','purged','failed')),
        temporary_data_json TEXT NOT NULL DEFAULT '{}',
        source_version TEXT NOT NULL DEFAULT '1',
        source_sha256 TEXT NOT NULL DEFAULT '',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
        CHECK (
            (is_active = 1 AND lifecycle_state = 'active')
            OR (is_active = 0 AND lifecycle_state <> 'active')
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS durable_documents (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        domain TEXT NOT NULL,
        document_key TEXT NOT NULL,
        document_json TEXT NOT NULL,
        source_kind TEXT NOT NULL DEFAULT '',
        source_name TEXT NOT NULL DEFAULT '',
        source_sha256 TEXT NOT NULL,
        source_version TEXT NOT NULL DEFAULT '1',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
        UNIQUE (workspace_id, domain, document_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS application_source_coverage (
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        domain TEXT NOT NULL,
        source_key TEXT NOT NULL,
        source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
        migration_run_id TEXT
            REFERENCES migration_runs(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'covered',
        covered_at TEXT NOT NULL,
        summary_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (workspace_id, domain, source_key)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL
            REFERENCES workspaces(id) ON DELETE CASCADE,
        artifact_kind TEXT NOT NULL,
        storage_backend TEXT NOT NULL,
        storage_key TEXT NOT NULL,
        exact_path TEXT NOT NULL DEFAULT '',
        content_sha256 TEXT NOT NULL DEFAULT '',
        byte_count INTEGER NOT NULL DEFAULT 0 CHECK (byte_count >= 0),
        exclusive_owner INTEGER NOT NULL DEFAULT 0 CHECK (exclusive_owner IN (0,1)),
        lifecycle_state TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
        UNIQUE (storage_backend, storage_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leases (
        lease_name TEXT PRIMARY KEY,
        holder_id TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_purge_runs (
        id TEXT PRIMARY KEY,
        guest_session_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        status TEXT NOT NULL,
        phase TEXT NOT NULL,
        dry_run INTEGER NOT NULL DEFAULT 1 CHECK (dry_run IN (0,1)),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        claim_token TEXT NOT NULL DEFAULT '',
        claimed_at TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT NOT NULL DEFAULT '',
        error_code TEXT NOT NULL DEFAULT '',
        manifest_sha256 TEXT NOT NULL DEFAULT '',
        summary_json TEXT NOT NULL DEFAULT '{}',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_purge_targets (
        id TEXT PRIMARY KEY,
        purge_run_id TEXT NOT NULL
            REFERENCES guest_purge_runs(id) ON DELETE CASCADE,
        guest_session_id TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_key TEXT NOT NULL,
        exact_path TEXT NOT NULL DEFAULT '',
        expected_sha256 TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_attempt_at TEXT NOT NULL DEFAULT '',
        completed_at TEXT NOT NULL DEFAULT '',
        error_code TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE (purge_run_id, target_kind, target_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guest_tombstones (
        guest_session_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        purge_run_id TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL
            CHECK (lifecycle_state IN ('purging','purged')),
        tombstoned_at TEXT NOT NULL,
        completed_at TEXT NOT NULL DEFAULT '',
        reason_code TEXT NOT NULL DEFAULT '',
        source_sha256 TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_links (
        token_digest TEXT PRIMARY KEY CHECK (length(token_digest) = 64),
        digest_algorithm TEXT NOT NULL DEFAULT 'sha256',
        workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
        created_by_account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
        artifact_id TEXT REFERENCES artifacts(id) ON DELETE SET NULL,
        pdf_filename TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        allow_download INTEGER NOT NULL DEFAULT 1 CHECK (allow_download IN (0,1)),
        revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0,1)),
        access_count INTEGER NOT NULL DEFAULT 0 CHECK (access_count >= 0),
        last_accessed_at TEXT NOT NULL DEFAULT '',
        source_sha256 TEXT NOT NULL DEFAULT '',
        row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1)
    )
    """,
)

_INDEX_STATEMENTS: Tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_normalized_email ON accounts(normalized_email) WHERE normalized_email <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_firebase_uid ON accounts(firebase_uid) WHERE firebase_uid <> ''",
    "CREATE INDEX IF NOT EXISTS idx_guest_sessions_expiration ON guest_sessions(lifecycle_state, is_active, expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_durable_documents_workspace_domain ON durable_documents(workspace_id, domain)",
    "CREATE INDEX IF NOT EXISTS idx_source_coverage_status ON application_source_coverage(status, covered_at)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_workspace_state ON artifacts(workspace_id, lifecycle_state)",
    "CREATE INDEX IF NOT EXISTS idx_leases_expiration ON leases(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_guest_purge_runs_state ON guest_purge_runs(status, phase, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_guest_purge_runs_guest ON guest_purge_runs(guest_session_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_guest_purge_targets_state ON guest_purge_targets(purge_run_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_share_links_expiration ON share_links(revoked, expires_at)",
)

REQUIRED_APPLICATION_TABLES = frozenset({
    "schema_versions",
    "migration_runs",
    "workspaces",
    "accounts",
    "guest_sessions",
    "durable_documents",
    "application_source_coverage",
    "artifacts",
    "leases",
    "guest_purge_runs",
    "guest_purge_targets",
    "guest_tombstones",
    "share_links",
})

_REQUIRED_COLUMNS: Mapping[str, frozenset] = {
    "schema_versions": frozenset({"component", "version", "checksum_sha256", "installed_at"}),
    "migration_runs": frozenset({"id", "migration_kind", "status", "source_sha256", "summary_json"}),
    "workspaces": frozenset({"id", "workspace_type", "external_id", "lifecycle_state", "row_version"}),
    "accounts": frozenset({
        "id", "workspace_id", "username", "normalized_email", "status",
        "password_hash", "firebase_uid", "provider", "created_at", "updated_at",
        "profile_json", "auth_metadata_json", "encrypted_secrets_json",
        "encryption_key_id", "source_sha256", "row_version",
    }),
    "guest_sessions": frozenset({
        "id", "session_id", "workspace_id", "created_at", "expires_at", "used_at",
        "ended_at", "updated_at", "is_active", "lifecycle_state", "temporary_data_json",
        "source_version", "source_sha256", "row_version",
    }),
    "durable_documents": frozenset({
        "id", "workspace_id", "domain", "document_key", "document_json",
        "source_kind", "source_name", "source_sha256", "source_version",
        "created_at", "updated_at", "row_version",
    }),
    "application_source_coverage": frozenset({
        "workspace_id", "domain", "source_key", "source_sha256",
        "migration_run_id", "status", "covered_at", "summary_json",
    }),
    "artifacts": frozenset({"id", "workspace_id", "artifact_kind", "storage_backend", "storage_key"}),
    "leases": frozenset({"lease_name", "holder_id", "expires_at", "row_version"}),
    "guest_purge_runs": frozenset({"id", "guest_session_id", "workspace_id", "status", "phase"}),
    "guest_purge_targets": frozenset({"id", "purge_run_id", "target_kind", "target_key", "status"}),
    "guest_tombstones": frozenset({"guest_session_id", "workspace_id", "lifecycle_state", "tombstoned_at"}),
    "share_links": frozenset({"token_digest", "digest_algorithm", "expires_at", "revoked"}),
}


def application_data_db_path(db_path=None) -> Path:
    """Resolve the application-data path lazily from recipe-master ownership."""

    if db_path is not None:
        return Path(db_path)
    from PushShoppingList.services import recipe_master_data_service

    return Path(recipe_master_data_service.recipe_master_db_path())


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ApplicationDataValidationError("Value is not portable JSON.") from exc


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def schema_checksum_sha256() -> str:
    material = "\n".join(statement.strip() for statement in _TABLE_STATEMENTS + _INDEX_STATEMENTS)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@contextmanager
def existing_application_read_connection(db_path=None):
    """Yield a query-only connection, or ``None`` without creating a file."""

    path = application_data_db_path(db_path)
    if not path.is_file():
        yield None
        return
    uri = "%s?mode=ro" % path.resolve().as_uri()
    with APPLICATION_DATA_LOCK:
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
        finally:
            connection.close()


@contextmanager
def application_data_write_connection(db_path=None):
    """Yield an installed-schema write connection with commit/rollback semantics."""

    path = application_data_db_path(db_path)
    if not path.is_file():
        raise ApplicationSchemaUnavailableError(
            "Application-data schema has not been explicitly installed."
        )
    with APPLICATION_DATA_LOCK:
        connection = sqlite3.connect(str(path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            _assert_application_schema(connection)
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def application_schema_status(db_path=None, *, connection=None) -> Dict[str, object]:
    """Inspect schema availability without DDL or filesystem creation."""

    if connection is not None:
        return _schema_status_from_connection(connection, exists=True)
    path = application_data_db_path(db_path)
    if not path.is_file():
        return {
            "exists": False,
            "available": False,
            "compatible": True,
            "current_version": None,
            "target_version": APPLICATION_SCHEMA_VERSION,
            "missing_tables": sorted(REQUIRED_APPLICATION_TABLES),
            "issues": [],
        }
    with existing_application_read_connection(path) as read_connection:
        if read_connection is None:
            raise ApplicationDataIntegrityError("Existing application database could not be opened.")
        return _schema_status_from_connection(read_connection, exists=True)


def application_schema_available(db_path=None, *, connection=None) -> bool:
    return bool(application_schema_status(db_path, connection=connection)["available"])


def install_application_schema(
    db_path=None,
    *,
    dry_run: bool = True,
    authorized: bool = False,
    approval: str = "",
) -> Dict[str, object]:
    """Preview or explicitly install the additive version-one schema."""

    path = application_data_db_path(db_path)
    before = application_schema_status(path)
    if dry_run:
        return {
            "action": "dry_run",
            "authorized": False,
            "would_create_database": not path.is_file(),
            "current_version": before["current_version"],
            "target_version": APPLICATION_SCHEMA_VERSION,
            "missing_tables": before["missing_tables"],
            "issues": before["issues"],
        }
    if not authorized or approval != SCHEMA_INSTALL_APPROVAL_PHRASE:
        raise ApplicationSchemaApprovalError(
            "Schema installation requires explicit authorization and the exact approval phrase."
        )
    if not before["compatible"]:
        raise ApplicationSchemaCompatibilityError(
            "Existing application table names have an incompatible shape."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    checksum = schema_checksum_sha256()
    schema_run_id = "schema:%s:v%d" % (APPLICATION_SCHEMA_COMPONENT, APPLICATION_SCHEMA_VERSION)
    with APPLICATION_DATA_LOCK:
        connection = sqlite3.connect(str(path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            for statement in _TABLE_STATEMENTS:
                connection.execute(statement)
            for statement in _INDEX_STATEMENTS:
                connection.execute(statement)
            _assert_application_schema(connection, require_version=False)
            existing_version = connection.execute(
                "SELECT version, checksum_sha256 FROM schema_versions WHERE component = ?",
                (APPLICATION_SCHEMA_COMPONENT,),
            ).fetchone()
            if existing_version and int(existing_version["version"]) > APPLICATION_SCHEMA_VERSION:
                raise ApplicationSchemaCompatibilityError(
                    "The installed application schema is newer than this service."
                )
            connection.execute(
                """
                INSERT INTO schema_versions (component, version, checksum_sha256, installed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    version = excluded.version,
                    checksum_sha256 = excluded.checksum_sha256,
                    installed_at = excluded.installed_at
                WHERE schema_versions.version <> excluded.version
                   OR schema_versions.checksum_sha256 <> excluded.checksum_sha256
                """,
                (APPLICATION_SCHEMA_COMPONENT, APPLICATION_SCHEMA_VERSION, checksum, timestamp),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO migration_runs (
                    id, migration_kind, status, source_sha256,
                    started_at, finished_at, error_code, summary_json
                ) VALUES (?, ?, 'succeeded', '', ?, ?, '', ?)
                """,
                (
                    schema_run_id,
                    "application_schema_install",
                    timestamp,
                    timestamp,
                    canonical_json({"schema_version": APPLICATION_SCHEMA_VERSION}),
                ),
            )
            _assert_application_schema(connection)
            _assert_new_table_foreign_keys(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    after = application_schema_status(path)
    return {
        "action": "installed" if before["missing_tables"] else "unchanged",
        "authorized": True,
        "current_version": after["current_version"],
        "target_version": APPLICATION_SCHEMA_VERSION,
        "missing_tables": after["missing_tables"],
        "issues": after["issues"],
    }


def _schema_status_from_connection(connection, *, exists: bool) -> Dict[str, object]:
    table_names = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(REQUIRED_APPLICATION_TABLES.difference(table_names))
    issues = []
    for table_name in sorted(REQUIRED_APPLICATION_TABLES.intersection(table_names)):
        columns = _table_columns(connection, table_name)
        missing_columns = sorted(_REQUIRED_COLUMNS[table_name].difference(columns))
        if missing_columns:
            issues.append("%s:missing_columns" % table_name)
    if "accounts" in table_names and "user_id" in _table_columns(connection, "accounts"):
        issues.append("accounts:forbidden_user_id_column")
    current_version = None
    checksum_matches = False
    if "schema_versions" in table_names:
        try:
            row = connection.execute(
                "SELECT version, checksum_sha256 FROM schema_versions WHERE component = ?",
                (APPLICATION_SCHEMA_COMPONENT,),
            ).fetchone()
            if row:
                current_version = int(row["version"])
                checksum_matches = row["checksum_sha256"] == schema_checksum_sha256()
        except (sqlite3.Error, TypeError, ValueError):
            issues.append("schema_versions:unreadable")
    available = not missing and not issues and current_version == APPLICATION_SCHEMA_VERSION
    return {
        "exists": exists,
        "available": available,
        "compatible": not issues and (current_version in (None, APPLICATION_SCHEMA_VERSION)),
        "current_version": current_version,
        "target_version": APPLICATION_SCHEMA_VERSION,
        "checksum_matches": checksum_matches,
        "missing_tables": missing,
        "issues": sorted(set(issues)),
    }


def _assert_application_schema(connection, *, require_version: bool = True) -> None:
    status = _schema_status_from_connection(connection, exists=True)
    if status["missing_tables"] or status["issues"]:
        raise ApplicationSchemaUnavailableError(
            "Application-data schema is missing or incompatible."
        )
    if require_version and status["current_version"] != APPLICATION_SCHEMA_VERSION:
        raise ApplicationSchemaUnavailableError(
            "Application-data schema version is not installed."
        )


def _assert_new_table_foreign_keys(connection) -> None:
    for table_name in (
        "accounts",
        "guest_sessions",
        "durable_documents",
        "application_source_coverage",
        "artifacts",
        "guest_purge_targets",
        "share_links",
    ):
        if connection.execute("PRAGMA foreign_key_check(%s)" % table_name).fetchone():
            raise ApplicationDataIntegrityError("Application schema foreign-key validation failed.")


def _table_columns(connection, table_name: str) -> frozenset:
    if table_name not in REQUIRED_APPLICATION_TABLES:
        raise ApplicationDataValidationError("Unknown application table requested.")
    return frozenset(str(row["name"]) for row in connection.execute(
        "PRAGMA table_info(%s)" % table_name
    ).fetchall())


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_opaque_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise ApplicationDataValidationError(
            "%s must be a non-empty opaque string." % field_name
        )
    return value


def _validate_optional_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ApplicationDataValidationError("%s must be text." % field_name)
    return value


def _validate_sha256(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ApplicationDataValidationError("%s must be a lowercase SHA-256 digest." % field_name)
    return value


def _validate_safe_code(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not _SAFE_CODE_PATTERN.fullmatch(value):
        raise ApplicationDataValidationError("%s is not a safe code." % field_name)
    return value


def _validate_source_name(value: object) -> str:
    text = _validate_optional_text(value, "source_name")
    if len(text) > 255 or "/" in text or "\\" in text or text in {".", ".."}:
        raise ApplicationDataValidationError("source_name must be a redacted basename.")
    return text


def _validate_timestamp(value: object, field_name: str, *, optional: bool = False) -> str:
    text = _validate_optional_text(value, field_name)
    if optional and text == "":
        return ""
    parsed_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parsed_text)
    except (TypeError, ValueError) as exc:
        raise ApplicationDataValidationError("%s must be an ISO timestamp." % field_name) from exc
    if parsed.tzinfo is None:
        raise ApplicationDataValidationError("%s must include a timezone." % field_name)
    return text


def _timestamp_value(value: str, field_name: str) -> datetime:
    _validate_timestamp(value, field_name)
    parsed_text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(parsed_text).astimezone(timezone.utc)


def _canonical_mapping(value: object, field_name: str) -> str:
    if value is None:
        value = {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApplicationDataValidationError("%s must be a JSON object." % field_name) from exc
    if not isinstance(value, dict):
        raise ApplicationDataValidationError("%s must be a JSON object." % field_name)
    return canonical_json(value)


def _parse_stored_json(value: object, field_name: str, *, require_mapping: bool = False) -> object:
    if not isinstance(value, str):
        raise ApplicationDataIntegrityError("Stored %s is not JSON text." % field_name)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationDataIntegrityError("Stored %s is invalid JSON." % field_name) from exc
    if require_mapping and not isinstance(parsed, dict):
        raise ApplicationDataIntegrityError("Stored %s is not a JSON object." % field_name)
    if canonical_json(parsed) != value:
        raise ApplicationDataIntegrityError("Stored %s is not canonical JSON." % field_name)
    return parsed


def _assert_safe_summary(value: object) -> None:
    forbidden = ("email", "password", "secret", "token", "payload")
    if isinstance(value, list):
        for item in value:
            _assert_safe_summary(item)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(word in normalized for word in forbidden):
                raise ApplicationDataValidationError("Summary contains a forbidden field.")
            _assert_safe_summary(child)
        return
    if isinstance(value, str):
        if "@" in value or len(value) > 512:
            raise ApplicationDataValidationError("Summary contains unsafe text.")


def _canonical_summary(value: object) -> str:
    if value is None:
        value = {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApplicationDataValidationError("summary must be a JSON object.") from exc
    if not isinstance(value, dict):
        raise ApplicationDataValidationError("summary must be a JSON object.")
    _assert_safe_summary(value)
    return canonical_json(value)


def _stable_id(namespace: str, *parts: str) -> str:
    material = "\x1f".join((namespace,) + tuple(parts))
    return "%s:%s" % (namespace, hashlib.sha256(material.encode("utf-8")).hexdigest())


@contextmanager
def _write_operation(connection=None, db_path=None):
    if connection is not None:
        yield connection
        return
    with application_data_write_connection(db_path) as owned:
        owned.execute("BEGIN IMMEDIATE")
        yield owned


@contextmanager
def _read_operation(connection=None, db_path=None):
    if connection is not None:
        yield connection
        return
    with existing_application_read_connection(db_path) as owned:
        if owned is not None and not application_schema_available(connection=owned):
            yield None
        else:
            yield owned


def _workspace_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["metadata"] = _parse_stored_json(
        result.pop("metadata_json"), "workspace metadata", require_mapping=True
    )
    result["action"] = action
    return result


def ensure_workspace(
    workspace_id: str,
    workspace_type: str,
    external_id: str,
    *,
    lifecycle_state: str = "active",
    metadata: object = None,
    source_sha256: str = "",
    created_at: str = "",
    updated_at: str = "",
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    """Create or safely advance one exact workspace identity."""

    workspace_id = _validate_opaque_text(workspace_id, "workspace_id")
    workspace_type = _validate_opaque_text(workspace_type, "workspace_type")
    external_id = _validate_opaque_text(external_id, "external_id")
    if lifecycle_state not in WORKSPACE_LIFECYCLE_STATES:
        raise ApplicationDataValidationError("Unknown workspace lifecycle state.")
    source_sha256 = _validate_sha256(source_sha256, "source_sha256", optional=True)
    if created_at:
        created_at = _validate_timestamp(created_at, "created_at")
    if updated_at:
        updated_at = _validate_timestamp(updated_at, "updated_at")
    requested_metadata = None if metadata is None else _canonical_mapping(metadata, "metadata")

    with _write_operation(connection, db_path) as database:
        row = database.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        mapped = database.execute(
            "SELECT id FROM workspaces WHERE workspace_type = ? AND external_id = ?",
            (workspace_type, external_id),
        ).fetchone()
        if mapped and mapped["id"] != workspace_id:
            raise ApplicationDataCollisionError("Workspace subject identity is already mapped.")
        if row is None:
            now = _utc_timestamp()
            created = created_at or now
            updated = updated_at or created
            database.execute(
                """
                INSERT INTO workspaces (
                    id, workspace_type, external_id, lifecycle_state,
                    created_at, updated_at, metadata_json, source_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    workspace_type,
                    external_id,
                    lifecycle_state,
                    created,
                    updated,
                    requested_metadata or "{}",
                    source_sha256,
                ),
            )
            inserted = database.execute(
                "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
            return _workspace_result(inserted, "inserted")

        if row["workspace_type"] != workspace_type or row["external_id"] != external_id:
            raise ApplicationDataCollisionError("Workspace ID belongs to another subject identity.")
        _validate_lifecycle_transition(
            row["lifecycle_state"], lifecycle_state, field_name="workspace"
        )
        metadata_json = requested_metadata if requested_metadata is not None else row["metadata_json"]
        effective_source = source_sha256 or row["source_sha256"]
        changed = (
            row["lifecycle_state"] != lifecycle_state
            or row["metadata_json"] != metadata_json
            or row["source_sha256"] != effective_source
        )
        if not changed:
            return _workspace_result(row, "unchanged")
        database.execute(
            """
            UPDATE workspaces SET
                lifecycle_state = ?, metadata_json = ?, source_sha256 = ?,
                updated_at = ?, row_version = row_version + 1
            WHERE id = ?
            """,
            (
                lifecycle_state,
                metadata_json,
                effective_source,
                updated_at or _utc_timestamp(),
                workspace_id,
            ),
        )
        changed_row = database.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        return _workspace_result(changed_row, "updated")


def _validate_lifecycle_transition(current: str, requested: str, *, field_name: str) -> None:
    if current == requested:
        return
    allowed = {
        "active": {"inactive", "purging"},
        "inactive": {"purging"},
        "purging": {"purged"},
        "purged": set(),
    }
    if requested not in allowed.get(current, set()):
        raise ApplicationDataLifecycleError(
            "%s lifecycle transition would resurrect or skip protected state." % field_name
        )


def _validate_guest_lifecycle_transition(current: str, requested: str) -> None:
    if current == requested:
        return
    allowed = {
        "active": {"inactive", "purging"},
        "inactive": {"purging"},
        "purging": {"purged", "failed"},
        "failed": {"purging", "purged"},
        "purged": set(),
    }
    if requested not in allowed.get(current, set()):
        raise ApplicationDataLifecycleError(
            "Guest session lifecycle transition would resurrect or skip protected state."
        )


def _workspace_state_for_guest(lifecycle_state: str) -> str:
    return "purging" if lifecycle_state == "failed" else lifecycle_state


def _document_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["document"] = _parse_stored_json(result.pop("document_json"), "durable document")
    result["action"] = action
    return result


def upsert_durable_document(
    workspace_id: str,
    domain: str,
    document_key: str,
    document: object,
    *,
    document_id: str = "",
    source_kind: str = "",
    source_name: str = "",
    source_sha256: str,
    source_version: str = "1",
    created_at: str = "",
    updated_at: str = "",
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    workspace_id = _validate_opaque_text(workspace_id, "workspace_id")
    domain = _validate_opaque_text(domain, "domain")
    document_key = _validate_opaque_text(document_key, "document_key")
    source_kind = _validate_optional_text(source_kind, "source_kind")
    source_name = _validate_source_name(source_name)
    source_sha256 = _validate_sha256(source_sha256, "source_sha256")
    source_version = _validate_opaque_text(source_version, "source_version")
    if created_at:
        created_at = _validate_timestamp(created_at, "created_at")
    if updated_at:
        updated_at = _validate_timestamp(updated_at, "updated_at")
    document_json = canonical_json(document)
    resolved_id = document_id or _stable_id("document", workspace_id, domain, document_key)
    _validate_opaque_text(resolved_id, "document_id")

    with _write_operation(connection, db_path) as database:
        row = database.execute(
            """
            SELECT * FROM durable_documents
            WHERE workspace_id = ? AND domain = ? AND document_key = ?
            """,
            (workspace_id, domain, document_key),
        ).fetchone()
        if row is not None and row["id"] != resolved_id:
            raise ApplicationDataCollisionError("Durable document key has another opaque ID.")
        if row is None:
            now = _utc_timestamp()
            database.execute(
                """
                INSERT INTO durable_documents (
                    id, workspace_id, domain, document_key, document_json,
                    source_kind, source_name, source_sha256, source_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    workspace_id,
                    domain,
                    document_key,
                    document_json,
                    source_kind,
                    source_name,
                    source_sha256,
                    source_version,
                    created_at or now,
                    updated_at or created_at or now,
                ),
            )
            inserted = database.execute(
                "SELECT * FROM durable_documents WHERE id = ?", (resolved_id,)
            ).fetchone()
            return _document_result(inserted, "inserted")
        comparable = (
            document_json,
            source_kind,
            source_name,
            source_sha256,
            source_version,
        )
        existing = tuple(
            row[name]
            for name in (
                "document_json", "source_kind", "source_name", "source_sha256", "source_version"
            )
        )
        if existing == comparable:
            return _document_result(row, "unchanged")
        database.execute(
            """
            UPDATE durable_documents SET
                document_json = ?, source_kind = ?, source_name = ?,
                source_sha256 = ?, source_version = ?, updated_at = ?,
                row_version = row_version + 1
            WHERE id = ?
            """,
            comparable + (updated_at or _utc_timestamp(), resolved_id),
        )
        changed = database.execute(
            "SELECT * FROM durable_documents WHERE id = ?", (resolved_id,)
        ).fetchone()
        return _document_result(changed, "updated")


def get_durable_document(
    workspace_id: str,
    domain: str,
    document_key: str,
    *,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    _validate_opaque_text(workspace_id, "workspace_id")
    _validate_opaque_text(domain, "domain")
    _validate_opaque_text(document_key, "document_key")
    with _read_operation(connection, db_path) as database:
        if database is None:
            return None
        row = database.execute(
            """
            SELECT * FROM durable_documents
            WHERE workspace_id = ? AND domain = ? AND document_key = ?
            """,
            (workspace_id, domain, document_key),
        ).fetchone()
        return _document_result(row, "read") if row else None


def _coverage_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["summary"] = _parse_stored_json(
        result.pop("summary_json"), "source coverage summary", require_mapping=True
    )
    result["action"] = action
    return result


def upsert_source_coverage(
    workspace_id: str,
    domain: str,
    source_key: str,
    source_sha256: str,
    *,
    migration_run_id: str = "",
    status: str = "covered",
    summary: object = None,
    covered_at: str = "",
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    workspace_id = _validate_opaque_text(workspace_id, "workspace_id")
    domain = _validate_opaque_text(domain, "domain")
    source_key = _validate_opaque_text(source_key, "source_key")
    source_sha256 = _validate_sha256(source_sha256, "source_sha256")
    migration_run_id = _validate_optional_text(migration_run_id, "migration_run_id")
    status = _validate_safe_code(status, "status")
    summary_json = _canonical_summary(summary)
    if covered_at:
        covered_at = _validate_timestamp(covered_at, "covered_at")
    covered_at = covered_at or _utc_timestamp()

    with _write_operation(connection, db_path) as database:
        row = database.execute(
            """
            SELECT * FROM application_source_coverage
            WHERE workspace_id = ? AND domain = ? AND source_key = ?
            """,
            (workspace_id, domain, source_key),
        ).fetchone()
        run_value = migration_run_id or None
        comparable = (source_sha256, run_value, status, summary_json)
        if row is not None:
            existing = (
                row["source_sha256"], row["migration_run_id"], row["status"], row["summary_json"]
            )
            if existing == comparable:
                return _coverage_result(row, "unchanged")
            database.execute(
                """
                UPDATE application_source_coverage SET
                    source_sha256 = ?, migration_run_id = ?, status = ?,
                    summary_json = ?, covered_at = ?
                WHERE workspace_id = ? AND domain = ? AND source_key = ?
                """,
                comparable + (covered_at, workspace_id, domain, source_key),
            )
            changed = database.execute(
                """
                SELECT * FROM application_source_coverage
                WHERE workspace_id = ? AND domain = ? AND source_key = ?
                """,
                (workspace_id, domain, source_key),
            ).fetchone()
            return _coverage_result(changed, "updated")
        database.execute(
            """
            INSERT INTO application_source_coverage (
                workspace_id, domain, source_key, source_sha256,
                migration_run_id, status, covered_at, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                domain,
                source_key,
                source_sha256,
                run_value,
                status,
                covered_at,
                summary_json,
            ),
        )
        inserted = database.execute(
            """
            SELECT * FROM application_source_coverage
            WHERE workspace_id = ? AND domain = ? AND source_key = ?
            """,
            (workspace_id, domain, source_key),
        ).fetchone()
        return _coverage_result(inserted, "inserted")


def get_source_coverage(
    workspace_id: str,
    domain: str,
    source_key: str,
    *,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    _validate_opaque_text(workspace_id, "workspace_id")
    _validate_opaque_text(domain, "domain")
    _validate_opaque_text(source_key, "source_key")
    with _read_operation(connection, db_path) as database:
        if database is None:
            return None
        row = database.execute(
            """
            SELECT * FROM application_source_coverage
            WHERE workspace_id = ? AND domain = ? AND source_key = ?
            """,
            (workspace_id, domain, source_key),
        ).fetchone()
        return _coverage_result(row, "read") if row else None


def _account_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["profile"] = _parse_stored_json(
        result.pop("profile_json"), "account profile", require_mapping=True
    )
    result["auth_metadata"] = _parse_stored_json(
        result.pop("auth_metadata_json"), "account authentication metadata", require_mapping=True
    )
    result["encrypted_secrets"] = _parse_stored_json(
        result.pop("encrypted_secrets_json"), "account encrypted secrets", require_mapping=True
    )
    result["action"] = action
    return result


def upsert_account(
    account_id: str,
    workspace_id: str,
    *,
    username: str = "",
    normalized_email: str = "",
    status: str = "active",
    password_hash: str = "",
    firebase_uid: str = "",
    provider: str = "",
    created_at: str = "",
    updated_at: str = "",
    profile: object = None,
    auth_metadata: object = None,
    encrypted_secrets: object = None,
    encryption_key_id: str = "",
    source_sha256: str = "",
    allow_update: bool = False,
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    """Insert an account or return identical; differing rows fail closed by default."""

    account_id = _validate_opaque_text(account_id, "account_id")
    workspace_id = _validate_opaque_text(workspace_id, "workspace_id")
    username = _validate_optional_text(username, "username")
    normalized_email = _validate_optional_text(normalized_email, "normalized_email")
    if normalized_email != normalized_email.strip().lower():
        raise ApplicationDataValidationError("normalized_email is not normalized.")
    status = _validate_safe_code(status, "status")
    password_hash = _validate_optional_text(password_hash, "password_hash")
    firebase_uid = _validate_optional_text(firebase_uid, "firebase_uid")
    provider = _validate_optional_text(provider, "provider")
    encryption_key_id = _validate_optional_text(encryption_key_id, "encryption_key_id")
    source_sha256 = _validate_sha256(source_sha256, "source_sha256", optional=True)
    profile_json = _canonical_mapping(profile, "profile")
    auth_metadata_json = _canonical_mapping(auth_metadata, "auth_metadata")
    encrypted_json = _canonical_mapping(encrypted_secrets, "encrypted_secrets")
    if encrypted_json != "{}" and not encryption_key_id:
        raise ApplicationDataValidationError(
            "Encrypted account secrets require an encryption key ID."
        )
    if created_at:
        created_at = _validate_timestamp(created_at, "created_at")
    if updated_at:
        updated_at = _validate_timestamp(updated_at, "updated_at")

    fields = (
        "workspace_id", "username", "normalized_email", "status", "password_hash",
        "firebase_uid", "provider", "created_at", "updated_at", "profile_json",
        "auth_metadata_json", "encrypted_secrets_json", "encryption_key_id", "source_sha256",
    )
    with _write_operation(connection, db_path) as database:
        row = database.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        now = _utc_timestamp()
        created = created_at or (row["created_at"] if row is not None else now)
        updated = updated_at or (row["updated_at"] if row is not None else created)
        values = (
            workspace_id,
            username,
            normalized_email,
            status,
            password_hash,
            firebase_uid,
            provider,
            created,
            updated,
            profile_json,
            auth_metadata_json,
            encrypted_json,
            encryption_key_id,
            source_sha256,
        )
        if row is not None:
            existing = tuple(row[field] for field in fields)
            if existing == values:
                return _account_result(row, "unchanged")
            if not allow_update:
                raise ApplicationDataCollisionError("Account ID already has different durable data.")
            assignments = ", ".join("%s = ?" % field for field in fields if field != "created_at")
            update_values = tuple(
                values[index] for index, field in enumerate(fields) if field != "created_at"
            )
            try:
                database.execute(
                    "UPDATE accounts SET %s, row_version = row_version + 1 WHERE id = ?" % assignments,
                    update_values + (account_id,),
                )
            except sqlite3.IntegrityError as exc:
                raise ApplicationDataCollisionError("Account unique identity collides.") from exc
            changed = database.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            return _account_result(changed, "updated")
        try:
            database.execute(
                """
                INSERT INTO accounts (
                    id, workspace_id, username, normalized_email, status,
                    password_hash, firebase_uid, provider, created_at, updated_at,
                    profile_json, auth_metadata_json, encrypted_secrets_json,
                    encryption_key_id, source_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id,) + values,
            )
        except sqlite3.IntegrityError as exc:
            raise ApplicationDataCollisionError("Account unique identity collides.") from exc
        inserted = database.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _account_result(inserted, "inserted")


def get_account(
    account_id: str,
    *,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    _validate_opaque_text(account_id, "account_id")
    with _read_operation(connection, db_path) as database:
        if database is None:
            return None
        row = database.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _account_result(row, "read") if row else None


def _migration_run_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["summary"] = _parse_stored_json(
        result.pop("summary_json"), "migration run summary", require_mapping=True
    )
    result["action"] = action
    return result


def record_application_migration_run(
    migration_kind: str,
    status: str,
    *,
    run_id: str = "",
    source_sha256: str = "",
    summary: object = None,
    error_code: str = "",
    started_at: str = "",
    finished_at: str = "",
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    migration_kind = _validate_safe_code(migration_kind, "migration_kind")
    if status not in MIGRATION_RUN_STATES:
        raise ApplicationDataValidationError("Unknown migration run status.")
    resolved_id = run_id or "migration:%s" % uuid.uuid4().hex
    _validate_opaque_text(resolved_id, "run_id")
    source_sha256 = _validate_sha256(source_sha256, "source_sha256", optional=True)
    error_code = _validate_safe_code(error_code, "error_code", optional=True)
    summary_json = _canonical_summary(summary)
    if started_at:
        started_at = _validate_timestamp(started_at, "started_at")
    started_at = started_at or _utc_timestamp()
    if finished_at:
        finished_at = _validate_timestamp(finished_at, "finished_at")
    if status in TERMINAL_MIGRATION_RUN_STATES and not finished_at:
        finished_at = _utc_timestamp()
    if status not in TERMINAL_MIGRATION_RUN_STATES and finished_at:
        raise ApplicationDataValidationError("Non-terminal migration runs cannot have finished_at.")

    with _write_operation(connection, db_path) as database:
        row = database.execute("SELECT * FROM migration_runs WHERE id = ?", (resolved_id,)).fetchone()
        if row is None:
            database.execute(
                """
                INSERT INTO migration_runs (
                    id, migration_kind, status, source_sha256, started_at,
                    finished_at, error_code, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved_id,
                    migration_kind,
                    status,
                    source_sha256,
                    started_at,
                    finished_at,
                    error_code,
                    summary_json,
                ),
            )
            inserted = database.execute("SELECT * FROM migration_runs WHERE id = ?", (resolved_id,)).fetchone()
            return _migration_run_result(inserted, "inserted")
        if row["migration_kind"] != migration_kind or row["source_sha256"] != source_sha256:
            raise ApplicationDataCollisionError("Migration run ID belongs to another source.")
        comparable = (status, finished_at, error_code, summary_json)
        existing = tuple(row[field] for field in ("status", "finished_at", "error_code", "summary_json"))
        if existing == comparable:
            return _migration_run_result(row, "unchanged")
        database.execute(
            """
            UPDATE migration_runs SET
                status = ?, finished_at = ?, error_code = ?, summary_json = ?,
                row_version = row_version + 1
            WHERE id = ?
            """,
            comparable + (resolved_id,),
        )
        changed = database.execute("SELECT * FROM migration_runs WHERE id = ?", (resolved_id,)).fetchone()
        return _migration_run_result(changed, "updated")


def _guest_result(row, action: str) -> Dict[str, object]:
    result = dict(row)
    result["is_active"] = bool(result["is_active"])
    result["temporary_data"] = _parse_stored_json(
        result.pop("temporary_data_json"), "guest temporary data", require_mapping=True
    )
    result["action"] = action
    return result


def insert_guest_session(
    guest_session: object = None,
    *,
    guest_session_id: str = "",
    session_id: str = "",
    workspace_id: str = "",
    created_at: str = "",
    expires_at: str = "",
    used_at: str = "",
    ended_at: str = "",
    updated_at: str = "",
    is_active: bool = True,
    lifecycle_state: str = "active",
    temporary_data: object = None,
    source_version: str = "1",
    source_sha256: str = "",
    connection=None,
    db_path=None,
) -> Dict[str, object]:
    """Insert one exact guest record, or return unchanged for an identical row.

    ``guest_session`` may be a legacy mapping or an opaque ID.  An explicit
    ``workspace_id`` is preferred; the default uses the already-established
    ``guest:<id>`` owner scope without changing the session ID itself.
    """

    if isinstance(guest_session, Mapping):
        record = guest_session
        guest_session_id = record.get("id", guest_session_id)
        session_id = record.get("session_id", session_id or guest_session_id)
        workspace_id = record.get("workspace_id", workspace_id)
        created_at = record.get("created_at", created_at)
        expires_at = record.get("expires_at", expires_at)
        used_at = record.get("used_at", used_at)
        ended_at = record.get("ended_at", ended_at)
        updated_at = record.get("updated_at", updated_at or used_at)
        is_active = record.get("is_active", is_active)
        lifecycle_state = record.get("lifecycle_state", lifecycle_state)
        temporary_data = record.get(
            "temporary_data_json",
            record.get("temporary_data", temporary_data),
        )
        source_version = record.get("source_version", source_version)
        source_sha256 = record.get("source_sha256", source_sha256)
    elif guest_session is not None:
        if guest_session_id:
            raise ApplicationDataValidationError("Guest session ID was supplied twice.")
        guest_session_id = guest_session

    guest_session_id = _validate_opaque_text(guest_session_id, "guest_session_id")
    session_id = _validate_opaque_text(session_id or guest_session_id, "session_id")
    workspace_id = _validate_opaque_text(
        workspace_id or "guest:%s" % guest_session_id,
        "workspace_id",
    )
    created_at = _validate_timestamp(created_at, "created_at")
    expires_at = _validate_timestamp(expires_at, "expires_at")
    used_at = _validate_timestamp(used_at, "used_at")
    ended_at = _validate_timestamp(ended_at, "ended_at", optional=True)
    updated_at = _validate_timestamp(updated_at or used_at, "updated_at")
    if not isinstance(is_active, bool):
        raise ApplicationDataValidationError("is_active must be boolean.")
    if lifecycle_state not in GUEST_LIFECYCLE_STATES:
        raise ApplicationDataValidationError("Unknown guest lifecycle state.")
    if is_active != (lifecycle_state == "active"):
        raise ApplicationDataValidationError("Guest activity and lifecycle state disagree.")
    source_sha256 = _validate_sha256(source_sha256, "source_sha256", optional=True)
    source_version = _validate_opaque_text(source_version, "source_version")
    temporary_json = _canonical_mapping(temporary_data, "temporary_data")

    with _write_operation(connection, db_path) as database:
        if database.execute(
            "SELECT 1 FROM guest_tombstones WHERE guest_session_id = ?",
            (guest_session_id,),
        ).fetchone():
            raise ApplicationDataLifecycleError("A guest tombstone forbids session resurrection.")
        ensure_workspace(
            workspace_id,
            "guest",
            guest_session_id,
            lifecycle_state=_workspace_state_for_guest(lifecycle_state),
            source_sha256=source_sha256,
            created_at=created_at,
            updated_at=used_at,
            connection=database,
        )
        row = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        values = (
            session_id,
            workspace_id,
            created_at,
            expires_at,
            used_at,
            ended_at,
            updated_at,
            int(is_active),
            lifecycle_state,
            temporary_json,
            source_version,
            source_sha256,
        )
        fields = (
            "session_id", "workspace_id", "created_at", "expires_at", "used_at",
            "ended_at", "updated_at", "is_active", "lifecycle_state",
            "temporary_data_json", "source_version", "source_sha256",
        )
        if row is not None:
            if tuple(row[field] for field in fields) == values:
                return _guest_result(row, "unchanged")
            raise ApplicationDataCollisionError("Guest session ID already has different durable data.")
        try:
            database.execute(
                """
                INSERT INTO guest_sessions (
                    id, session_id, workspace_id, created_at, expires_at, used_at,
                    ended_at, updated_at, is_active, lifecycle_state, temporary_data_json,
                    source_version, source_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (guest_session_id,) + values,
            )
        except sqlite3.IntegrityError as exc:
            raise ApplicationDataCollisionError("Guest session unique identity collides.") from exc
        inserted = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        return _guest_result(inserted, "inserted")


def get_guest_session(
    guest_session_id: str,
    *,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    _validate_opaque_text(guest_session_id, "guest_session_id")
    with _read_operation(connection, db_path) as database:
        if database is None:
            return None
        row = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        return _guest_result(row, "read") if row else None


def list_guest_sessions(
    *,
    lifecycle_states: Optional[Iterable[str]] = None,
    active_only: Optional[bool] = None,
    expires_at_or_before: str = "",
    connection=None,
    db_path=None,
) -> list:
    states = None
    if lifecycle_states is not None:
        states = tuple(lifecycle_states)
        if not states or any(state not in GUEST_LIFECYCLE_STATES for state in states):
            raise ApplicationDataValidationError("Unknown guest lifecycle filter.")
    if active_only is not None and not isinstance(active_only, bool):
        raise ApplicationDataValidationError("active_only must be boolean or None.")
    cutoff = None
    if expires_at_or_before:
        expires_at_or_before = _validate_timestamp(
            expires_at_or_before, "expires_at_or_before"
        )
        cutoff = _timestamp_value(expires_at_or_before, "expires_at_or_before")

    clauses = []
    parameters = []
    if states is not None:
        clauses.append("lifecycle_state IN (%s)" % ",".join("?" for _ in states))
        parameters.extend(states)
    if active_only is not None:
        clauses.append("is_active = ?")
        parameters.append(int(active_only))
    sql = "SELECT * FROM guest_sessions"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at, id"
    with _read_operation(connection, db_path) as database:
        if database is None:
            return []
        rows = database.execute(sql, tuple(parameters)).fetchall()
        results = [_guest_result(row, "read") for row in rows]
    if cutoff is not None:
        results = [
            item
            for item in results
            if _timestamp_value(item["expires_at"], "stored expires_at") <= cutoff
        ]
    return results


def update_guest_session(
    guest_session_id: str,
    changes: Optional[Mapping[str, object]] = None,
    *,
    used_at: object = _UNSET,
    expires_at: object = _UNSET,
    ended_at: object = _UNSET,
    is_active: object = _UNSET,
    lifecycle_state: object = _UNSET,
    temporary_data: object = _UNSET,
    source_sha256: object = _UNSET,
    expected_row_version: Optional[int] = None,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    """Update mutable guest fields without extending expiration or resurrecting state."""

    guest_session_id = _validate_opaque_text(guest_session_id, "guest_session_id")
    if changes is not None:
        if not isinstance(changes, Mapping):
            raise ApplicationDataValidationError("Guest changes must be a mapping.")
        allowed = {
            "used_at", "expires_at", "ended_at", "is_active", "lifecycle_state",
            "temporary_data", "temporary_data_json", "source_sha256",
        }
        if set(changes).difference(allowed):
            raise ApplicationDataValidationError("Guest changes contain an unknown field.")
        supplied = {
            "used_at": used_at,
            "expires_at": expires_at,
            "ended_at": ended_at,
            "is_active": is_active,
            "lifecycle_state": lifecycle_state,
            "temporary_data": temporary_data,
            "source_sha256": source_sha256,
        }
        mapping = dict(changes)
        if "temporary_data_json" in mapping and "temporary_data" not in mapping:
            mapping["temporary_data"] = mapping.pop("temporary_data_json")
        for name, current in supplied.items():
            if name in mapping:
                if current is not _UNSET:
                    raise ApplicationDataValidationError("Guest change was supplied twice.")
                supplied[name] = mapping[name]
        used_at = supplied["used_at"]
        expires_at = supplied["expires_at"]
        ended_at = supplied["ended_at"]
        is_active = supplied["is_active"]
        lifecycle_state = supplied["lifecycle_state"]
        temporary_data = supplied["temporary_data"]
        source_sha256 = supplied["source_sha256"]
    if expected_row_version is not None and (
        not isinstance(expected_row_version, int) or expected_row_version < 1
    ):
        raise ApplicationDataValidationError("expected_row_version must be positive.")

    with _write_operation(connection, db_path) as database:
        row = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        if row is None:
            return None
        if expected_row_version is not None and row["row_version"] != expected_row_version:
            raise ApplicationDataCollisionError("Guest session row version changed.")

        new_used = row["used_at"] if used_at is _UNSET else _validate_timestamp(used_at, "used_at")
        new_expires = (
            row["expires_at"]
            if expires_at is _UNSET
            else _validate_timestamp(expires_at, "expires_at")
        )
        if _timestamp_value(new_expires, "expires_at") > _timestamp_value(
            row["expires_at"], "stored expires_at"
        ):
            raise ApplicationDataLifecycleError("Guest expiration cannot be extended.")
        new_ended = (
            row["ended_at"]
            if ended_at is _UNSET
            else _validate_timestamp(ended_at, "ended_at", optional=True)
        )
        new_lifecycle = row["lifecycle_state"] if lifecycle_state is _UNSET else lifecycle_state
        if new_lifecycle not in GUEST_LIFECYCLE_STATES:
            raise ApplicationDataValidationError("Unknown guest lifecycle state.")
        new_active = bool(row["is_active"]) if is_active is _UNSET else is_active
        if not isinstance(new_active, bool):
            raise ApplicationDataValidationError("is_active must be boolean.")
        if lifecycle_state is not _UNSET and new_lifecycle != "active" and is_active is _UNSET:
            new_active = False
        if is_active is not _UNSET and not new_active and lifecycle_state is _UNSET:
            new_lifecycle = "inactive"
        _validate_lifecycle_transition(
            row["lifecycle_state"], new_lifecycle, field_name="guest session"
        )
        if new_active != (new_lifecycle == "active"):
            raise ApplicationDataValidationError("Guest activity and lifecycle state disagree.")
        if new_active and database.execute(
            "SELECT 1 FROM guest_tombstones WHERE guest_session_id = ?",
            (guest_session_id,),
        ).fetchone():
            raise ApplicationDataLifecycleError("A guest tombstone forbids session resurrection.")
        new_temporary = (
            row["temporary_data_json"]
            if temporary_data is _UNSET
            else _canonical_mapping(temporary_data, "temporary_data")
        )
        new_source = (
            row["source_sha256"]
            if source_sha256 is _UNSET
            else _validate_sha256(source_sha256, "source_sha256", optional=True)
        )
        values = (
            new_used,
            new_expires,
            new_ended,
            int(new_active),
            new_lifecycle,
            new_temporary,
            new_source,
        )
        fields = (
            "used_at", "expires_at", "ended_at", "is_active", "lifecycle_state",
            "temporary_data_json", "source_sha256",
        )
        if tuple(row[field] for field in fields) == values:
            return _guest_result(row, "unchanged")
        ensure_workspace(
            row["workspace_id"],
            "guest",
            guest_session_id,
            lifecycle_state=new_lifecycle,
            connection=database,
        )
        sql = """
            UPDATE guest_sessions SET
                used_at = ?, expires_at = ?, ended_at = ?, is_active = ?,
                lifecycle_state = ?, temporary_data_json = ?, source_sha256 = ?,
                row_version = row_version + 1
            WHERE id = ?
        """
        parameters = values + (guest_session_id,)
        if expected_row_version is not None:
            sql += " AND row_version = ?"
            parameters += (expected_row_version,)
        cursor = database.execute(sql, parameters)
        if cursor.rowcount != 1:
            raise ApplicationDataCollisionError("Guest session changed concurrently.")
        changed = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        return _guest_result(changed, "updated")


def deactivate_guest_session(
    guest_session_id: str,
    *,
    ended_at: str = "",
    expected_row_version: Optional[int] = None,
    connection=None,
    db_path=None,
) -> Optional[Dict[str, object]]:
    """Deactivate access while preserving the exact expiration timestamp."""

    guest_session_id = _validate_opaque_text(guest_session_id, "guest_session_id")
    with _write_operation(connection, db_path) as database:
        row = database.execute(
            "SELECT * FROM guest_sessions WHERE id = ?", (guest_session_id,)
        ).fetchone()
        if row is None:
            return None
        if row["lifecycle_state"] in {"inactive", "purging", "purged"}:
            return _guest_result(row, "unchanged")
        return update_guest_session(
            guest_session_id,
            ended_at=ended_at or _utc_timestamp(),
            is_active=False,
            lifecycle_state="inactive",
            expected_row_version=expected_row_version,
            connection=database,
        )


__all__ = [
    "APPLICATION_DATA_LOCK",
    "APPLICATION_SCHEMA_COMPONENT",
    "APPLICATION_SCHEMA_VERSION",
    "ApplicationDataCollisionError",
    "ApplicationDataError",
    "ApplicationDataIntegrityError",
    "ApplicationDataLifecycleError",
    "ApplicationDataValidationError",
    "ApplicationSchemaApprovalError",
    "ApplicationSchemaCompatibilityError",
    "ApplicationSchemaUnavailableError",
    "REQUIRED_APPLICATION_TABLES",
    "SCHEMA_INSTALL_APPROVAL_PHRASE",
    "application_data_db_path",
    "application_data_write_connection",
    "application_schema_available",
    "application_schema_status",
    "canonical_json",
    "deactivate_guest_session",
    "ensure_workspace",
    "existing_application_read_connection",
    "get_account",
    "get_durable_document",
    "get_guest_session",
    "get_source_coverage",
    "insert_guest_session",
    "install_application_schema",
    "list_guest_sessions",
    "record_application_migration_run",
    "schema_checksum_sha256",
    "sha256_json",
    "update_guest_session",
    "upsert_account",
    "upsert_durable_document",
    "upsert_source_coverage",
]
