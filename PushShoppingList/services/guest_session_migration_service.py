"""Strict, approval-gated migration of legacy guest sessions into SQLite.

Preview is payload-free and never opens the application database. Apply keeps
the legacy registry unchanged, verifies an optional caller-created backup,
rechecks the source under a ``BEGIN IMMEDIATE`` transaction, and validates the
stored rows before commit. Guest IDs and timestamp text are treated as opaque
data and are never regenerated or normalized.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import guest_session_service


APPLY_APPROVAL_PHRASE = "APPLY GUEST SESSION MIGRATION"
SOURCE_KIND = "legacy_guest_sessions_json"
MIGRATION_DOMAIN = "guest_sessions"
SOURCE_VERSION = "1"
MIGRATION_SCHEMA_VERSION = 2
MAX_SOURCE_BYTES = 16 * 1024 * 1024
REGISTRY_WORKSPACE_ID = "system:guest-session-registry"
REGISTRY_WORKSPACE_EXTERNAL_ID = "guest-session-registry"
REGISTRY_COVERAGE_SOURCE_KEY = "guest_sessions.json"

_GUEST_LIFECYCLE_STATES = frozenset(
    {"active", "inactive", "purging", "purged", "failed"}
)
_REQUIRED_RECORD_FIELDS = frozenset(
    {
        "id",
        "session_id",
        "created_at",
        "expires_at",
        "used_at",
        "is_active",
        "temporary_data_json",
    }
)
_OPTIONAL_RECORD_FIELDS = frozenset(
    {"ended_at", "updated_at", "lifecycle_state", "source_version"}
)
_KNOWN_RECORD_FIELDS = _REQUIRED_RECORD_FIELDS | _OPTIONAL_RECORD_FIELDS


class GuestSessionMigrationError(RuntimeError):
    """Base class for guest-session migration failures."""


class GuestSessionMigrationApprovalError(GuestSessionMigrationError):
    """Raised when apply lacks the exact approval phrase."""


class GuestSessionMigrationSourceError(GuestSessionMigrationError):
    """Raised when the legacy registry cannot be migrated safely."""


class StaleGuestSessionMigrationPreviewError(GuestSessionMigrationSourceError):
    """Raised when the source no longer matches the reviewed preview."""


class GuestSessionMigrationCollisionError(GuestSessionMigrationError):
    """Raised when a source identity conflicts with durable application data."""


class GuestSessionMigrationBackupError(GuestSessionMigrationError):
    """Raised when a requested pre-apply backup cannot be verified."""


class GuestSessionMigrationIntegrityError(GuestSessionMigrationError):
    """Raised when pre-commit row or SQLite integrity validation fails."""


class _DuplicateJsonKeyError(ValueError):
    pass


class _GuestShapeError(ValueError):
    pass


@dataclass(frozen=True)
class GuestSessionMigrationPreview:
    """Payload-free source inventory safe for operator review and logs."""

    created_at: str
    status: str
    source_sha256: Optional[str]
    byte_count: int
    session_count: int
    active_count: int
    inactive_count: int
    expired_count: int
    active_unexpired_count: int
    active_unexpired_sha256: Optional[str]
    record_set_sha256: Optional[str]
    error_code: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> Dict[str, object]:
        result = asdict(self)
        result["ready"] = self.ready
        return result


@dataclass(frozen=True)
class GuestSessionMigrationApplyResult:
    """Redacted result of one approved transactional apply."""

    applied_at: str
    source_sha256: str
    migration_run_id: Optional[str]
    session_count: int
    inserted_sessions: int
    unchanged_sessions: int
    preserved_newer_used_at: int
    coverage_rows: int
    active_unexpired_count: int
    active_unexpired_sha256: str
    backup: Mapping[str, object]
    no_op: bool
    validation: Mapping[str, object]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _PreparedGuestSession:
    guest_session_id: str
    session_id: str
    workspace_id: str
    created_at: str
    expires_at: str
    used_at: str
    ended_at: str
    updated_at: str
    is_active: bool
    lifecycle_state: str
    temporary_data: Mapping[str, object]
    source_version: str
    source_sha256: str
    created_value: datetime
    expires_value: datetime
    used_value: datetime


@dataclass(frozen=True)
class _VerifiedBackup:
    requested: bool
    path: Optional[Path]
    source_sha256: str
    byte_count: int

    def redacted(self) -> Dict[str, object]:
        return {
            "requested": self.requested,
            "verified": bool(self.requested and self.path is not None),
            "source_sha256": self.source_sha256 if self.requested else "",
            "byte_count": self.byte_count if self.requested else 0,
        }


def guest_sessions_source_path(source_path=None) -> Path:
    """Resolve the legacy source lazily so tests and operators can override it."""

    if source_path is not None:
        return Path(source_path)
    return Path(guest_session_service.GUEST_SESSIONS_FILE)


def guest_session_migration_db_path(db_path=None) -> Path:
    """Resolve the application database lazily through its owning repository."""

    if db_path is not None:
        return Path(db_path)
    return Path(application_data.application_data_db_path())


def database_coverage_status(db_path=None) -> Optional[Dict[str, object]]:
    """Return redacted cutover coverage, ``None`` only for a pristine DB domain.

    Once any guest-session row, tombstone, or per-guest coverage exists, a
    missing registry marker is treated as incomplete rather than as permission
    to fall back to JSON.  This prevents a partial shadow/backfill failure from
    silently selecting stale legacy state.
    """

    resolved_db = guest_session_migration_db_path(db_path)
    status = application_data.application_schema_status(resolved_db)
    if not status.get("available"):
        raise GuestSessionMigrationIntegrityError(
            "Guest-session database coverage requires the installed application schema."
        )
    with application_data.existing_application_read_connection(resolved_db) as connection:
        if connection is None:
            raise GuestSessionMigrationIntegrityError(
                "Guest-session database coverage could not be opened."
            )
        coverage = application_data.get_source_coverage(
            REGISTRY_WORKSPACE_ID,
            MIGRATION_DOMAIN,
            REGISTRY_COVERAGE_SOURCE_KEY,
            connection=connection,
        )
        if coverage is None:
            evidence_count = sum(
                int(connection.execute(sql, parameters).fetchone()[0])
                for sql, parameters in (
                    ("SELECT COUNT(*) FROM guest_sessions", ()),
                    ("SELECT COUNT(*) FROM guest_tombstones", ()),
                    (
                        """SELECT COUNT(*) FROM application_source_coverage
                           WHERE domain = ? AND source_key = ?""",
                        (MIGRATION_DOMAIN, SOURCE_KIND),
                    ),
                    (
                        "SELECT COUNT(*) FROM workspaces WHERE id = ?",
                        (REGISTRY_WORKSPACE_ID,),
                    ),
                )
            )
            if evidence_count == 0:
                return None
            return {
                "status": "incomplete",
                "source_sha256": "",
                "record_count": 0,
                "migration_run_valid": False,
            }

        run_id = str(coverage.get("migration_run_id") or "")
        run = connection.execute(
            """SELECT migration_kind, status, source_sha256
               FROM migration_runs WHERE id = ?""",
            (run_id,),
        ).fetchone() if run_id else None
        run_valid = bool(
            run is not None
            and run["migration_kind"] == SOURCE_KIND
            and run["status"] == "succeeded"
            and run["source_sha256"] == coverage.get("source_sha256")
        )
        summary = coverage.get("summary")
        record_count = summary.get("record_count") if isinstance(summary, Mapping) else None
        identity_refs = summary.get("identity_refs") if isinstance(summary, Mapping) else None
        summary_valid = (
            isinstance(record_count, int)
            and not isinstance(record_count, bool)
            and record_count >= 0
            and summary.get("schema_version") == MIGRATION_SCHEMA_VERSION
            and isinstance(identity_refs, list)
            and len(identity_refs) == record_count
            and len(set(identity_refs)) == record_count
            and all(
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in identity_refs
            )
        )
        identities_valid = False
        if summary_valid:
            expected_refs = set(identity_refs)
            accounted_refs = set()
            session_rows = connection.execute(
                "SELECT id, workspace_id, source_sha256 FROM guest_sessions"
            ).fetchall()
            for session_row in session_rows:
                identity_ref = _identity_ref(str(session_row["id"]))
                if identity_ref not in expected_refs:
                    continue
                item_coverage = application_data.get_source_coverage(
                    str(session_row["workspace_id"]),
                    MIGRATION_DOMAIN,
                    SOURCE_KIND,
                    connection=connection,
                )
                if (
                    isinstance(item_coverage, Mapping)
                    and item_coverage.get("status") == "covered"
                    and item_coverage.get("source_sha256")
                    == str(session_row["source_sha256"] or "")
                ):
                    accounted_refs.add(identity_ref)
            for tombstone in connection.execute(
                "SELECT guest_session_id FROM guest_tombstones"
            ).fetchall():
                identity_ref = _identity_ref(str(tombstone["guest_session_id"]))
                if identity_ref in expected_refs:
                    accounted_refs.add(identity_ref)
            identities_valid = accounted_refs == expected_refs
        covered = bool(
            coverage.get("status") == "covered"
            and run_valid
            and summary_valid
            and identities_valid
        )
        return {
            "status": "covered" if covered else "incomplete",
            "source_sha256": str(coverage.get("source_sha256") or "") if covered else "",
            "record_count": int(record_count) if summary_valid else 0,
            "migration_run_valid": run_valid,
        }


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _identity_ref(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _identity_refs(prepared) -> list:
    return sorted(_identity_ref(item.guest_session_id) for item in prepared)


def _timestamp(clock: Optional[Callable[[], datetime]]) -> str:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError("clock must return a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_opaque_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise _GuestShapeError("invalid_%s" % field_name)
    return value


def _validate_timestamp_text(
    value: object,
    field_name: str,
    *,
    optional: bool = False,
) -> Tuple[str, Optional[datetime]]:
    if optional and value == "":
        return "", None
    if not isinstance(value, str) or value == "" or "\x00" in value:
        raise _GuestShapeError("invalid_%s" % field_name)
    parsed_text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parsed_text)
    except (TypeError, ValueError) as exc:
        raise _GuestShapeError("invalid_%s" % field_name) from exc
    if parsed.tzinfo is None:
        raise _GuestShapeError("invalid_%s" % field_name)
    return value, parsed.astimezone(timezone.utc)


def _timestamp_value(value: str, field_name: str) -> datetime:
    _text, parsed = _validate_timestamp_text(value, field_name)
    if parsed is None:  # pragma: no cover - non-optional validation guarantees it
        raise _GuestShapeError("invalid_%s" % field_name)
    return parsed


def _strict_json_loads(raw: bytes) -> object:
    text = raw.decode("utf-8-sig", errors="strict")

    def object_pairs(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non_finite_json_number")

    return json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _read_source(source_path: Path) -> Tuple[bytes, object]:
    if not source_path.is_file():
        raise FileNotFoundError("legacy guest-session source is missing")
    if source_path.stat().st_size > MAX_SOURCE_BYTES:
        raise _GuestShapeError("source_too_large")
    raw = source_path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise _GuestShapeError("source_too_large")
    return raw, _strict_json_loads(raw)


def _hash_values(values) -> str:
    return hashlib.sha256(
        canonical_json(sorted(values)).encode("utf-8")
    ).hexdigest()


def _prepare_guest_sessions(value: object) -> Tuple[_PreparedGuestSession, ...]:
    if not isinstance(value, dict) or set(value) != {"guest_sessions"}:
        raise _GuestShapeError("expected_guest_sessions_object")
    records = value.get("guest_sessions")
    if not isinstance(records, list):
        raise _GuestShapeError("guest_sessions_not_array")

    prepared = []
    seen_ids = set()
    seen_session_ids = set()
    identity_owners: Dict[str, int] = {}
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict):
            raise _GuestShapeError("guest_session_not_object")
        fields = set(raw_record)
        if not _REQUIRED_RECORD_FIELDS.issubset(fields):
            raise _GuestShapeError("missing_guest_session_field")
        if fields.difference(_KNOWN_RECORD_FIELDS):
            raise _GuestShapeError("unknown_guest_session_field")

        guest_session_id = _validate_opaque_text(raw_record["id"], "guest_id")
        session_id = _validate_opaque_text(raw_record["session_id"], "session_id")
        if guest_session_id in seen_ids:
            raise _GuestShapeError("duplicate_guest_id")
        if session_id in seen_session_ids:
            raise _GuestShapeError("duplicate_session_id")
        seen_ids.add(guest_session_id)
        seen_session_ids.add(session_id)
        for identity in {guest_session_id, session_id}:
            owner = identity_owners.get(identity)
            if owner is not None and owner != index:
                raise _GuestShapeError("duplicate_guest_identity")
            identity_owners[identity] = index

        created_at, created_value = _validate_timestamp_text(
            raw_record["created_at"], "created_at"
        )
        expires_at, expires_value = _validate_timestamp_text(
            raw_record["expires_at"], "expires_at"
        )
        used_at, used_value = _validate_timestamp_text(
            raw_record["used_at"], "used_at"
        )
        ended_at, _ended_value = _validate_timestamp_text(
            raw_record.get("ended_at", ""),
            "ended_at",
            optional=True,
        )
        updated_at, _updated_value = _validate_timestamp_text(
            raw_record.get("updated_at", used_at),
            "updated_at",
        )
        if expires_value is None or created_value is None or used_value is None:
            raise _GuestShapeError("invalid_guest_timestamp")
        if expires_value <= created_value:
            raise _GuestShapeError("invalid_expiration_order")

        is_active = raw_record["is_active"]
        if not isinstance(is_active, bool):
            raise _GuestShapeError("invalid_is_active")
        lifecycle_state = raw_record.get(
            "lifecycle_state",
            "active" if is_active else "inactive",
        )
        if not isinstance(lifecycle_state, str) or (
            lifecycle_state not in _GUEST_LIFECYCLE_STATES
        ):
            raise _GuestShapeError("invalid_lifecycle_state")
        if is_active != (lifecycle_state == "active"):
            raise _GuestShapeError("inconsistent_guest_lifecycle")

        temporary_data = raw_record["temporary_data_json"]
        if not isinstance(temporary_data, dict):
            raise _GuestShapeError("invalid_temporary_data")
        # Re-serialization catches values outside portable JSON even when a
        # custom caller supplies an already-decoded object to internal tests.
        canonical_json(temporary_data)

        source_version = raw_record.get("source_version", SOURCE_VERSION)
        source_version = _validate_opaque_text(
            source_version,
            "source_version",
        )
        source_record_json = canonical_json(raw_record)
        prepared.append(
            _PreparedGuestSession(
                guest_session_id=guest_session_id,
                session_id=session_id,
                workspace_id="guest:%s" % guest_session_id,
                created_at=created_at,
                expires_at=expires_at,
                used_at=used_at,
                ended_at=ended_at,
                updated_at=updated_at,
                is_active=is_active,
                lifecycle_state=lifecycle_state,
                temporary_data=deepcopy(temporary_data),
                source_version=source_version,
                source_sha256=hashlib.sha256(
                    source_record_json.encode("utf-8")
                ).hexdigest(),
                created_value=created_value,
                expires_value=expires_value,
                used_value=used_value,
            )
        )
    return tuple(prepared)


def _active_unexpired_ids(
    prepared: Tuple[_PreparedGuestSession, ...],
    evaluated_at: datetime,
):
    return [
        item.guest_session_id
        for item in prepared
        if item.is_active
        and item.lifecycle_state == "active"
        and item.expires_value > evaluated_at
    ]


def _preview_from_prepared(
    raw: bytes,
    prepared: Tuple[_PreparedGuestSession, ...],
    *,
    created_at: str,
) -> GuestSessionMigrationPreview:
    evaluated_at = _timestamp_value(created_at, "preview_created_at")
    active_ids = _active_unexpired_ids(prepared, evaluated_at)
    active_count = sum(1 for item in prepared if item.is_active)
    expired_count = sum(
        1 for item in prepared if item.expires_value <= evaluated_at
    )
    return GuestSessionMigrationPreview(
        created_at=created_at,
        status="ready",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        session_count=len(prepared),
        active_count=active_count,
        inactive_count=len(prepared) - active_count,
        expired_count=expired_count,
        active_unexpired_count=len(active_ids),
        active_unexpired_sha256=_hash_values(active_ids),
        record_set_sha256=_hash_values(
            item.source_sha256 for item in prepared
        ),
    )


def _scan_source(
    source_path: Path,
    *,
    clock: Optional[Callable[[], datetime]] = None,
    created_at: str = "",
) -> Tuple[GuestSessionMigrationPreview, Tuple[_PreparedGuestSession, ...]]:
    raw, value = _read_source(source_path)
    prepared = _prepare_guest_sessions(value)
    preview_time = created_at or _timestamp(clock)
    return (
        _preview_from_prepared(raw, prepared, created_at=preview_time),
        prepared,
    )


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "source_missing"
    if isinstance(exc, _DuplicateJsonKeyError):
        return "duplicate_json_key"
    if isinstance(exc, UnicodeError):
        return "invalid_utf8"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, OSError):
        return "source_io_error"
    if isinstance(exc, _GuestShapeError):
        code = str(exc)
        if code.replace("_", "").isalnum():
            return code
        return "invalid_guest_source"
    if isinstance(exc, (TypeError, ValueError)):
        return "invalid_json_value"
    return "invalid_guest_source"


def preview_guest_session_migration(
    source_path=None,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> GuestSessionMigrationPreview:
    """Strictly inventory the legacy registry without opening SQLite."""

    try:
        preview, _prepared = _scan_source(
            guest_sessions_source_path(source_path),
            clock=clock,
        )
        return preview
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return GuestSessionMigrationPreview(
            created_at=_timestamp(clock),
            status="invalid",
            source_sha256=None,
            byte_count=0,
            session_count=0,
            active_count=0,
            inactive_count=0,
            expired_count=0,
            active_unexpired_count=0,
            active_unexpired_sha256=None,
            record_set_sha256=None,
            error_code=_safe_error_code(exc),
        )


def _preview_signature(preview: GuestSessionMigrationPreview) -> Tuple[object, ...]:
    return (
        preview.created_at,
        preview.status,
        preview.source_sha256,
        preview.byte_count,
        preview.session_count,
        preview.active_count,
        preview.inactive_count,
        preview.expired_count,
        preview.active_unexpired_count,
        preview.active_unexpired_sha256,
        preview.record_set_sha256,
        preview.error_code,
    )


def _assert_preview_current(
    expected: GuestSessionMigrationPreview,
    current: GuestSessionMigrationPreview,
) -> None:
    if _preview_signature(expected) != _preview_signature(current):
        raise StaleGuestSessionMigrationPreviewError(
            "The legacy guest-session source changed after preview."
        )


def _scan_unchanged_source(
    preview: GuestSessionMigrationPreview,
    source_path: Path,
    *,
    clock: Optional[Callable[[], datetime]],
) -> Tuple[_PreparedGuestSession, ...]:
    try:
        current, prepared = _scan_source(
            source_path,
            clock=clock,
            created_at=preview.created_at,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise StaleGuestSessionMigrationPreviewError(
            "The legacy guest-session source is no longer review-equivalent."
        ) from exc
    _assert_preview_current(preview, current)
    return prepared


def _verify_optional_backup(
    backup_callback,
    source_path: Path,
    preview: GuestSessionMigrationPreview,
) -> _VerifiedBackup:
    if backup_callback is None:
        return _VerifiedBackup(False, None, "", 0)
    if not callable(backup_callback):
        raise GuestSessionMigrationBackupError(
            "The guest-session backup callback is not callable."
        )
    try:
        value = backup_callback(source_path, preview.source_sha256 or "")
    except BaseException as exc:
        raise GuestSessionMigrationBackupError(
            "The guest-session source backup could not be created."
        ) from exc

    claimed_hash = ""
    claimed_bytes = None
    if isinstance(value, Mapping):
        if "verified" in value and value.get("verified") is not True:
            raise GuestSessionMigrationBackupError(
                "The guest-session source backup was not verified."
            )
        backup_value = value.get("backup_path")
        claimed_hash = str(value.get("source_sha256") or "")
        claimed_bytes = value.get("byte_count")
    else:
        backup_value = value
    if not isinstance(backup_value, (str, Path)) or not str(backup_value):
        raise GuestSessionMigrationBackupError(
            "The guest-session backup callback did not return a backup file."
        )
    backup_path = Path(backup_value)
    if not backup_path.is_absolute():
        backup_path = source_path.parent / backup_path
    try:
        if backup_path.resolve() == source_path.resolve():
            raise GuestSessionMigrationBackupError(
                "The guest-session backup must be separate from its source."
            )
        if not backup_path.is_file() or backup_path.stat().st_size > MAX_SOURCE_BYTES:
            raise GuestSessionMigrationBackupError(
                "The guest-session backup file is missing or too large."
            )
        raw = backup_path.read_bytes()
    except GuestSessionMigrationBackupError:
        raise
    except OSError as exc:
        raise GuestSessionMigrationBackupError(
            "The guest-session backup file could not be verified."
        ) from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != preview.source_sha256 or len(raw) != preview.byte_count:
        raise GuestSessionMigrationBackupError(
            "The guest-session backup does not match the reviewed source."
        )
    if claimed_hash and claimed_hash != digest:
        raise GuestSessionMigrationBackupError(
            "The guest-session backup manifest hash does not match."
        )
    if claimed_bytes is not None and claimed_bytes != len(raw):
        raise GuestSessionMigrationBackupError(
            "The guest-session backup manifest byte count does not match."
        )
    return _VerifiedBackup(True, backup_path, digest, len(raw))


def _assert_backup_current(backup: _VerifiedBackup) -> None:
    if not backup.requested or backup.path is None:
        return
    try:
        if backup.path.stat().st_size != backup.byte_count:
            raise GuestSessionMigrationBackupError(
                "The verified guest-session backup changed before commit."
            )
        raw = backup.path.read_bytes()
    except GuestSessionMigrationBackupError:
        raise
    except OSError as exc:
        raise GuestSessionMigrationBackupError(
            "The verified guest-session backup is no longer readable."
        ) from exc
    if (
        len(raw) != backup.byte_count
        or hashlib.sha256(raw).hexdigest() != backup.source_sha256
    ):
        raise GuestSessionMigrationBackupError(
            "The verified guest-session backup changed before commit."
        )


def _install_schema(db_path: Path) -> None:
    result = application_data.install_application_schema(
        db_path=db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    if isinstance(result, Mapping) and result.get("ok") is False:
        raise GuestSessionMigrationError(
            "The application-data schema could not be installed."
        )


def _action_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        action = value.get("action")
        if isinstance(action, str):
            return action
    return "applied"


def _is_repository_collision(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if isinstance(
        exc,
        (
            application_data.ApplicationDataCollisionError,
            application_data.ApplicationDataLifecycleError,
        ),
    ):
        return True
    return "collision" in type(exc).__name__.lower()


def _existing_guest_match(
    existing: Mapping[str, object],
    expected: _PreparedGuestSession,
) -> str:
    exact_fields = {
        "id": expected.guest_session_id,
        "session_id": expected.session_id,
        "workspace_id": expected.workspace_id,
        "created_at": expected.created_at,
        "expires_at": expected.expires_at,
        "ended_at": expected.ended_at,
        "is_active": expected.is_active,
        "lifecycle_state": expected.lifecycle_state,
        "source_version": expected.source_version,
        "source_sha256": expected.source_sha256,
    }
    if any(existing.get(name) != value for name, value in exact_fields.items()):
        return "collision"
    if existing.get("temporary_data") != expected.temporary_data:
        return "collision"
    if (
        existing.get("used_at") == expected.used_at
        and existing.get("updated_at") == expected.updated_at
    ):
        return "exact"
    try:
        stored_used = _timestamp_value(str(existing.get("used_at") or ""), "stored_used_at")
        stored_updated = _timestamp_value(
            str(existing.get("updated_at") or ""),
            "stored_updated_at",
        )
        expected_updated = _timestamp_value(expected.updated_at, "expected_updated_at")
    except _GuestShapeError:
        return "collision"
    if stored_used > expected.used_value:
        return "newer_used_at"
    if stored_used == expected.used_value and stored_updated >= expected_updated:
        # Shadow writes preserve the exact legacy used_at value but the DB
        # repository may advance its transaction timestamp independently.
        return "exact"
    return "collision"


def _coverage_is_current(connection, item: _PreparedGuestSession) -> bool:
    coverage = application_data.get_source_coverage(
        item.workspace_id,
        MIGRATION_DOMAIN,
        SOURCE_KIND,
        connection=connection,
    )
    return bool(
        isinstance(coverage, Mapping)
        and coverage.get("source_sha256") == item.source_sha256
        and coverage.get("status") == "covered"
    )


def _registry_coverage_is_current(
    connection,
    preview: GuestSessionMigrationPreview,
    prepared,
) -> bool:
    coverage = application_data.get_source_coverage(
        REGISTRY_WORKSPACE_ID,
        MIGRATION_DOMAIN,
        REGISTRY_COVERAGE_SOURCE_KEY,
        connection=connection,
    )
    if not isinstance(coverage, Mapping) or coverage.get("status") != "covered":
        return False
    summary = coverage.get("summary")
    if not isinstance(summary, Mapping):
        return False
    if (
        coverage.get("source_sha256") != preview.source_sha256
        or summary.get("record_count") != preview.session_count
        or summary.get("active_count") != preview.active_count
        or summary.get("active_unexpired_count") != preview.active_unexpired_count
        or summary.get("active_unexpired_sha256") != preview.active_unexpired_sha256
        or summary.get("identity_refs") != _identity_refs(prepared)
        or summary.get("schema_version") != MIGRATION_SCHEMA_VERSION
    ):
        return False
    run_id = str(coverage.get("migration_run_id") or "")
    if not run_id:
        return False
    run = connection.execute(
        """SELECT migration_kind, status, source_sha256
           FROM migration_runs WHERE id = ?""",
        (run_id,),
    ).fetchone()
    return bool(
        run is not None
        and run["migration_kind"] == SOURCE_KIND
        and run["status"] == "succeeded"
        and run["source_sha256"] == preview.source_sha256
    )


def _assert_database_identity_compatible(
    connection,
    item: _PreparedGuestSession,
) -> None:
    if connection.execute(
        "SELECT 1 FROM guest_tombstones WHERE guest_session_id = ?",
        (item.guest_session_id,),
    ).fetchone():
        raise GuestSessionMigrationCollisionError(
            "A guest-session tombstone forbids legacy resurrection."
        )

    rows = connection.execute(
        """
        SELECT id, session_id
        FROM guest_sessions
        WHERE id IN (?, ?) OR session_id IN (?, ?)
        """,
        (
            item.guest_session_id,
            item.session_id,
            item.guest_session_id,
            item.session_id,
        ),
    ).fetchall()
    if any(
        row["id"] != item.guest_session_id
        or row["session_id"] != item.session_id
        for row in rows
    ):
        raise GuestSessionMigrationCollisionError(
            "A guest-session identity is cross-mapped in application data."
        )

    workspaces = connection.execute(
        """
        SELECT id, workspace_type, external_id
        FROM workspaces
        WHERE id = ? OR (workspace_type = 'guest' AND external_id = ?)
        """,
        (item.workspace_id, item.guest_session_id),
    ).fetchall()
    if any(
        row["id"] != item.workspace_id
        or row["workspace_type"] != "guest"
        or row["external_id"] != item.guest_session_id
        for row in workspaces
    ):
        raise GuestSessionMigrationCollisionError(
            "A guest workspace identity is cross-mapped in application data."
        )


def _run_failure_injector(failure_injector, stage: str, **context) -> None:
    if callable(failure_injector):
        failure_injector(stage, dict(context))


def _stored_active_unexpired_ids(
    stored_rows,
    evaluated_at: datetime,
):
    active_ids = []
    for row in stored_rows:
        expires_at = _timestamp_value(
            str(row.get("expires_at") or ""),
            "stored_expires_at",
        )
        if (
            row.get("is_active") is True
            and row.get("lifecycle_state") == "active"
            and expires_at > evaluated_at
        ):
            active_ids.append(str(row.get("id") or ""))
    return active_ids


def _validate_transaction(
    connection,
    prepared: Tuple[_PreparedGuestSession, ...],
    preview: GuestSessionMigrationPreview,
) -> Dict[str, object]:
    stored_rows = []
    preserved_newer = 0
    for item in prepared:
        stored = application_data.get_guest_session(
            item.guest_session_id,
            connection=connection,
        )
        if not isinstance(stored, Mapping):
            raise GuestSessionMigrationIntegrityError(
                "Guest-session validation found a missing durable row."
            )
        match = _existing_guest_match(stored, item)
        if match == "collision":
            raise GuestSessionMigrationIntegrityError(
                "Guest-session validation found divergent durable data."
            )
        if match == "newer_used_at":
            preserved_newer += 1
        if not _coverage_is_current(connection, item):
            raise GuestSessionMigrationIntegrityError(
                "Guest-session source coverage validation failed."
            )
        stored_rows.append(stored)

    evaluated_at = _timestamp_value(preview.created_at, "preview_created_at")
    active_ids = _stored_active_unexpired_ids(stored_rows, evaluated_at)
    active_hash = _hash_values(active_ids)
    if (
        len(active_ids) != preview.active_unexpired_count
        or active_hash != preview.active_unexpired_sha256
    ):
        raise GuestSessionMigrationIntegrityError(
            "Active guest-session validation did not match the reviewed source."
        )
    if not _registry_coverage_is_current(connection, preview, prepared):
        raise GuestSessionMigrationIntegrityError(
            "Guest-session registry coverage validation failed."
        )

    foreign_key_violations = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if foreign_key_violations:
        raise GuestSessionMigrationIntegrityError(
            "SQLite foreign-key validation failed before commit."
        )
    quick_check = [row[0] for row in connection.execute("PRAGMA quick_check")]
    if quick_check != ["ok"]:
        raise GuestSessionMigrationIntegrityError(
            "SQLite quick-check validation failed before commit."
        )
    return {
        "stored_rows": len(stored_rows),
        "coverage_rows": len(prepared),
        "registry_coverage_rows": 1,
        "preserved_newer_used_at": preserved_newer,
        "active_unexpired_count": len(active_ids),
        "active_unexpired_sha256": active_hash,
        "record_set_sha256": preview.record_set_sha256 or "",
        "foreign_key_violations": 0,
        "quick_check": "ok",
    }


def apply_guest_session_migration(
    preview: GuestSessionMigrationPreview,
    *,
    approval: str,
    source_path=None,
    db_path=None,
    backup_callback=None,
    clock: Optional[Callable[[], datetime]] = None,
    failure_injector=None,
) -> GuestSessionMigrationApplyResult:
    """Apply an unchanged reviewed source without modifying the legacy file."""

    if approval != APPLY_APPROVAL_PHRASE:
        raise GuestSessionMigrationApprovalError(
            "The exact guest-session migration approval phrase is required."
        )
    if not isinstance(preview, GuestSessionMigrationPreview) or not preview.ready:
        raise GuestSessionMigrationSourceError(
            "A ready guest-session migration preview is required."
        )

    resolved_source = guest_sessions_source_path(source_path)
    prepared = _scan_unchanged_source(
        preview,
        resolved_source,
        clock=clock,
    )
    resolved_db_path = guest_session_migration_db_path(db_path)
    if resolved_db_path.resolve() == resolved_source.resolve():
        raise GuestSessionMigrationSourceError(
            "The guest-session source and application database must be separate."
        )
    verified_backup = _verify_optional_backup(
        backup_callback,
        resolved_source,
        preview,
    )
    if (
        verified_backup.path is not None
        and verified_backup.path.resolve() == resolved_db_path.resolve()
    ):
        raise GuestSessionMigrationBackupError(
            "The guest-session backup and application database must be separate."
        )
    # A backup callback is external code and may race with the source. Recheck
    # before even installing the additive application schema.
    prepared = _scan_unchanged_source(
        preview,
        resolved_source,
        clock=clock,
    )

    _install_schema(resolved_db_path)

    applied_at = _timestamp(clock)
    migration_run_id: Optional[str] = None
    inserted_sessions = 0
    unchanged_sessions = 0
    preserved_newer_used_at = 0
    coverage_updates = []
    validation: Mapping[str, object] = {}

    with application_data.application_data_write_connection(
        db_path=resolved_db_path
    ) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _run_failure_injector(failure_injector, "after_begin")
            prepared = _scan_unchanged_source(
                preview,
                resolved_source,
                clock=clock,
            )

            for index, item in enumerate(prepared):
                _assert_database_identity_compatible(connection, item)
                existing = application_data.get_guest_session(
                    item.guest_session_id,
                    connection=connection,
                )
                if existing is not None:
                    match = _existing_guest_match(existing, item)
                    if match == "collision":
                        raise GuestSessionMigrationCollisionError(
                            "An existing guest session differs from the legacy source."
                        )
                    if match == "newer_used_at":
                        preserved_newer_used_at += 1
                    else:
                        unchanged_sessions += 1
                else:
                    try:
                        result = application_data.insert_guest_session(
                            guest_session_id=item.guest_session_id,
                            session_id=item.session_id,
                            workspace_id=item.workspace_id,
                            created_at=item.created_at,
                            expires_at=item.expires_at,
                            used_at=item.used_at,
                            ended_at=item.ended_at,
                            updated_at=item.updated_at,
                            is_active=item.is_active,
                            lifecycle_state=item.lifecycle_state,
                            temporary_data=item.temporary_data,
                            source_version=item.source_version,
                            source_sha256=item.source_sha256,
                            connection=connection,
                        )
                    except BaseException as exc:
                        if _is_repository_collision(exc):
                            raise GuestSessionMigrationCollisionError(
                                "A guest-session identity collides with application data."
                            ) from exc
                        raise
                    if _action_name(result) != "inserted":
                        raise GuestSessionMigrationCollisionError(
                            "A new guest session was not inserted exactly once."
                        )
                    inserted_sessions += 1

                if not _coverage_is_current(connection, item):
                    coverage_updates.append(item)
                _run_failure_injector(
                    failure_injector,
                    "after_session",
                    session_index=index,
                )

            registry_coverage_current = _registry_coverage_is_current(
                connection,
                preview,
                prepared,
            )
            changed = bool(
                inserted_sessions
                or coverage_updates
                or not registry_coverage_current
            )
            if changed:
                application_data.ensure_workspace(
                    REGISTRY_WORKSPACE_ID,
                    "system",
                    REGISTRY_WORKSPACE_EXTERNAL_ID,
                    lifecycle_state="active",
                    source_sha256=preview.source_sha256 or "",
                    created_at=applied_at,
                    updated_at=applied_at,
                    connection=connection,
                )
                migration_run_id = uuid.uuid4().hex
                run_result = application_data.record_application_migration_run(
                    SOURCE_KIND,
                    "succeeded",
                    run_id=migration_run_id,
                    source_sha256=preview.source_sha256 or "",
                    summary={
                        "record_count": len(prepared),
                        "identity_refs": _identity_refs(prepared),
                        "active_count": preview.active_count,
                        "active_unexpired_count": (
                            preview.active_unexpired_count
                        ),
                        "coverage_updates": len(coverage_updates),
                        "registry_coverage_update": not registry_coverage_current,
                        "schema_version": MIGRATION_SCHEMA_VERSION,
                    },
                    started_at=applied_at,
                    finished_at=applied_at,
                    connection=connection,
                )
                if isinstance(run_result, Mapping) and run_result.get("id"):
                    migration_run_id = str(run_result["id"])

                for item in coverage_updates:
                    application_data.upsert_source_coverage(
                        item.workspace_id,
                        MIGRATION_DOMAIN,
                        SOURCE_KIND,
                        item.source_sha256,
                        migration_run_id=migration_run_id,
                        status="covered",
                        summary={
                            "active": item.is_active,
                            "schema_version": MIGRATION_SCHEMA_VERSION,
                        },
                        covered_at=applied_at,
                        connection=connection,
                    )

                application_data.upsert_source_coverage(
                    REGISTRY_WORKSPACE_ID,
                    MIGRATION_DOMAIN,
                    REGISTRY_COVERAGE_SOURCE_KEY,
                    preview.source_sha256 or "",
                    migration_run_id=migration_run_id,
                    status="covered",
                    summary={
                        "record_count": preview.session_count,
                        "identity_refs": _identity_refs(prepared),
                        "active_count": preview.active_count,
                        "active_unexpired_count": preview.active_unexpired_count,
                        "active_unexpired_sha256": (
                            preview.active_unexpired_sha256 or ""
                        ),
                        "schema_version": MIGRATION_SCHEMA_VERSION,
                    },
                    covered_at=applied_at,
                    connection=connection,
                )

            _run_failure_injector(failure_injector, "before_validation")
            validation = _validate_transaction(
                connection,
                prepared,
                preview,
            )
            _run_failure_injector(failure_injector, "before_commit")
            _assert_backup_current(verified_backup)
            _scan_unchanged_source(
                preview,
                resolved_source,
                clock=clock,
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

    return GuestSessionMigrationApplyResult(
        applied_at=applied_at,
        source_sha256=preview.source_sha256 or "",
        migration_run_id=migration_run_id,
        session_count=len(prepared),
        inserted_sessions=inserted_sessions,
        unchanged_sessions=unchanged_sessions,
        preserved_newer_used_at=preserved_newer_used_at,
        coverage_rows=int(validation.get("coverage_rows", 0)),
        active_unexpired_count=int(
            validation.get("active_unexpired_count", 0)
        ),
        active_unexpired_sha256=str(
            validation.get("active_unexpired_sha256", "")
        ),
        backup=verified_backup.redacted(),
        no_op=not bool(
            inserted_sessions
            or coverage_updates
            or not registry_coverage_current
        ),
        validation=validation,
    )


__all__ = [
    "APPLY_APPROVAL_PHRASE",
    "REGISTRY_COVERAGE_SOURCE_KEY",
    "REGISTRY_WORKSPACE_ID",
    "GuestSessionMigrationApplyResult",
    "GuestSessionMigrationApprovalError",
    "GuestSessionMigrationBackupError",
    "GuestSessionMigrationCollisionError",
    "GuestSessionMigrationError",
    "GuestSessionMigrationIntegrityError",
    "GuestSessionMigrationPreview",
    "GuestSessionMigrationSourceError",
    "StaleGuestSessionMigrationPreviewError",
    "apply_guest_session_migration",
    "canonical_json",
    "database_coverage_status",
    "guest_session_migration_db_path",
    "guest_sessions_source_path",
    "preview_guest_session_migration",
]
