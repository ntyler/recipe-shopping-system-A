from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from flask import current_app
from flask import has_request_context
from flask import request
from flask import session
from itsdangerous import BadSignature
from itsdangerous import URLSafeSerializer

from PushShoppingList.services.storage_service import PACKAGE_DIR
from PushShoppingList.services.storage_service import safe_user_id


GUEST_COOKIE_NAME = "guest_demo_session"
GUEST_SESSION_TTL = timedelta(hours=24)
GUEST_COOKIE_MAX_AGE = int(GUEST_SESSION_TTL.total_seconds())
GUEST_SESSIONS_FILE = Path(os.getenv("SHOPPING_APP_GUEST_SESSIONS_FILE", PACKAGE_DIR / "guest_sessions.json"))
GUEST_DATA_DIR = Path(os.getenv("SHOPPING_APP_GUEST_DATA_DIR", PACKAGE_DIR / "user_data" / "guests"))
GUEST_SESSIONS_LOCK = threading.RLock()
GUEST_SESSION_BACKEND_ENV = "SHOPPING_APP_GUEST_SESSION_BACKEND"
GUEST_SESSION_BACKEND_MODES = frozenset(
    {"legacy", "json", "shadow", "db_preferred", "db_only"}
)
GUEST_SESSION_DB_PATH = None
GUEST_SESSION_LOCK_TIMEOUT_SECONDS = 30
_GUEST_WRITE_LOCK_STATE = threading.local()


class GuestSessionStorageError(RuntimeError):
    """Raised when the session registry cannot be read without losing data."""


def _try_lock_file(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_file(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _guest_registry_write_lock():
    """Serialize a complete JSON read-modify-write across threads and processes."""

    with GUEST_SESSIONS_LOCK:
        depth = int(getattr(_GUEST_WRITE_LOCK_STATE, "depth", 0) or 0)
        if depth:
            _GUEST_WRITE_LOCK_STATE.depth = depth + 1
            try:
                yield
            finally:
                _GUEST_WRITE_LOCK_STATE.depth = depth
            return

        lock_path = GUEST_SESSIONS_FILE.with_name(
            ".%s.lock" % GUEST_SESSIONS_FILE.name
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        acquired = False
        try:
            if lock_path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + GUEST_SESSION_LOCK_TIMEOUT_SECONDS
            while not acquired:
                acquired = _try_lock_file(handle)
                if acquired:
                    break
                if time.monotonic() >= deadline:
                    raise GuestSessionStorageError(
                        "Guest-session registry write lock timed out."
                    )
                time.sleep(0.05)
            _GUEST_WRITE_LOCK_STATE.depth = 1
            yield
        finally:
            _GUEST_WRITE_LOCK_STATE.depth = 0
            if acquired:
                try:
                    _unlock_file(handle)
                except OSError:
                    pass
            handle.close()


def guest_session_backend_mode(environment=None):
    """Return the explicitly configured backend, defaulting to legacy JSON."""

    environment = environment if environment is not None else os.environ
    mode = str(environment.get(GUEST_SESSION_BACKEND_ENV, "json") or "json").strip().lower()
    if mode not in GUEST_SESSION_BACKEND_MODES:
        raise GuestSessionStorageError("Guest-session backend mode is invalid.")
    return mode


def guest_session_db_path():
    """Resolve the durable database lazily without creating or installing it."""

    if GUEST_SESSION_DB_PATH is not None:
        return Path(GUEST_SESSION_DB_PATH)
    from PushShoppingList.services.application_data_service import application_data_db_path

    return Path(application_data_db_path())


def _application_data_service():
    from PushShoppingList.services import application_data_service

    return application_data_service


def _guest_purge_fenced(guest_session_id):
    """Fail closed when the persisted purge saga has fenced this identity."""

    try:
        from PushShoppingList.services.guest_purge_service import guest_write_is_fenced

        return bool(
            guest_write_is_fenced(
                str(guest_session_id or ""),
                db_path=guest_session_db_path(),
            )
        )
    except Exception:
        return True


def _database_authority(mode):
    """Return whether SQLite is authoritative, or fail closed on ambiguity."""

    if mode not in {"db_preferred", "db_only"}:
        return False
    try:
        application_data = _application_data_service()
        status = application_data.application_schema_status(guest_session_db_path())
        missing_tables = set(status.get("missing_tables") or ())
        wholly_uninitialized = (
            status.get("current_version") is None
            and missing_tables == set(application_data.REQUIRED_APPLICATION_TABLES)
            and not status.get("issues")
        )
        if not status.get("available"):
            if mode == "db_preferred" and wholly_uninitialized:
                return False
            raise GuestSessionStorageError("Guest-session database schema is unavailable.")

        from PushShoppingList.services.guest_session_migration_service import (
            database_coverage_status,
        )

        coverage = database_coverage_status(guest_session_db_path())
        if coverage is None:
            if mode == "db_preferred":
                return False
            raise GuestSessionStorageError("Guest-session database migration is incomplete.")
        if coverage.get("status") != "covered":
            raise GuestSessionStorageError("Guest-session database migration is incomplete.")
        return True
    except GuestSessionStorageError:
        raise
    except Exception as exc:
        raise GuestSessionStorageError(
            "Guest-session database authority could not be verified."
        ) from exc


def _require_shadow_database():
    try:
        application_data = _application_data_service()
        status = application_data.application_schema_status(guest_session_db_path())
        if not status.get("available"):
            raise GuestSessionStorageError("Guest-session shadow database is unavailable.")
    except GuestSessionStorageError:
        raise
    except Exception as exc:
        raise GuestSessionStorageError(
            "Guest-session shadow database could not be verified."
        ) from exc


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso():
    return now_utc().isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        without_z = text[:-1]
        text = without_z if without_z.endswith("+00:00") else without_z + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_utc_datetime(value):
    value = value or now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_json_guest_sessions_unlocked():
    if not GUEST_SESSIONS_FILE.exists():
        return {"guest_sessions": []}

    try:
        payload = json.loads(GUEST_SESSIONS_FILE.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise GuestSessionStorageError(
            "Guest session registry is unreadable; refusing to treat it as empty."
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("guest_sessions"), list):
        raise GuestSessionStorageError(
            "Guest session registry must contain a guest_sessions list."
        )
    return payload


def _normalize_guest_sessions_payload(payload):
    payload = payload if isinstance(payload, dict) else {"guest_sessions": []}
    payload.setdefault("guest_sessions", [])
    if not isinstance(payload.get("guest_sessions"), list):
        raise GuestSessionStorageError("guest_sessions must be a list.")
    return payload


def _atomic_write_bytes_unlocked(destination, raw):
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(destination))
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _save_json_guest_sessions_unlocked(payload):
    payload = _normalize_guest_sessions_payload(payload)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes_unlocked(GUEST_SESSIONS_FILE, serialized.encode("utf-8"))
    return payload


def _legacy_record_from_database(record):
    converted = {
        "id": str(record.get("id") or ""),
        "session_id": str(record.get("session_id") or ""),
        "created_at": str(record.get("created_at") or ""),
        "expires_at": str(record.get("expires_at") or ""),
        "used_at": str(record.get("used_at") or ""),
        "is_active": bool(record.get("is_active")),
        "lifecycle_state": str(record.get("lifecycle_state") or ""),
        "temporary_data_json": deepcopy(record.get("temporary_data") or {}),
    }
    if record.get("ended_at"):
        converted["ended_at"] = str(record["ended_at"])
    if record.get("updated_at"):
        converted["updated_at"] = str(record["updated_at"])
    if record.get("source_version"):
        converted["source_version"] = str(record["source_version"])
    return converted


def _legacy_record_sha256(record):
    try:
        canonical = json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise GuestSessionStorageError(
            "Guest-session record is not portable JSON."
        ) from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_database_guest_sessions(connection=None):
    application_data = _application_data_service()
    records = application_data.list_guest_sessions(
        connection=connection,
        db_path=None if connection is not None else guest_session_db_path(),
    )
    return {"guest_sessions": [_legacy_record_from_database(record) for record in records]}


def load_guest_sessions():
    with GUEST_SESSIONS_LOCK:
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            try:
                return _load_database_guest_sessions()
            except Exception as exc:
                if isinstance(exc, GuestSessionStorageError):
                    raise
                raise GuestSessionStorageError(
                    "Guest-session database records could not be read."
                ) from exc
        if mode == "shadow":
            _require_shadow_database()
        return _load_json_guest_sessions_unlocked()


def save_guest_sessions(payload):
    """Compatibility replacement for JSON modes; database cutovers use scoped writes."""

    with _guest_registry_write_lock():
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            raise GuestSessionStorageError(
                "Bulk guest-session replacement is disabled for an authoritative database."
            )
        if mode == "shadow":
            _require_shadow_database()
            return _save_shadow_payload_unlocked(payload)
        return _save_json_guest_sessions_unlocked(payload)


def _database_guest_fence(connection, guest_session_id):
    """Return the durable row plus any purge/tombstone write fence."""

    guest_session_id = str(guest_session_id or "")
    if not guest_session_id:
        return None, False
    application_data = _application_data_service()
    record = application_data.get_guest_session(
        guest_session_id,
        connection=connection,
    )
    tombstoned = connection.execute(
        "SELECT 1 FROM guest_tombstones WHERE guest_session_id = ?",
        (guest_session_id,),
    ).fetchone() is not None
    workspace_state = ""
    if record is not None:
        workspace = connection.execute(
            "SELECT lifecycle_state FROM workspaces WHERE id = ?",
            (record.get("workspace_id"),),
        ).fetchone()
        workspace_state = str(workspace[0] or "") if workspace else ""
    lifecycle_state = str((record or {}).get("lifecycle_state") or "")
    fenced = bool(
        tombstoned
        or lifecycle_state in {"purging", "purged", "failed"}
        or workspace_state in {"purging", "purged"}
    )
    return record, fenced


def _database_record_from_legacy(record, connection):
    """Insert or safely advance one shadow record inside a caller transaction."""

    if not isinstance(record, dict):
        raise GuestSessionStorageError("Guest-session records must be objects.")
    guest_session_id = str(record.get("id") or "")
    session_id = str(record.get("session_id") or guest_session_id)
    if not guest_session_id or not session_id:
        raise GuestSessionStorageError("Guest-session identities cannot be empty.")
    application_data = _application_data_service()
    existing, fenced = _database_guest_fence(connection, guest_session_id)
    if fenced:
        # A purge owns this durable identity now.  Shadow writes must neither
        # resurrect nor delay it, but may continue mirroring unrelated rows.
        return existing

    is_active = record.get("is_active", False)
    if not isinstance(is_active, bool):
        raise GuestSessionStorageError("Guest-session activity must be boolean.")
    lifecycle_state = str(
        record.get("lifecycle_state") or ("active" if is_active else "inactive")
    )
    temporary_data = record.get("temporary_data_json", {})
    if not isinstance(temporary_data, dict):
        raise GuestSessionStorageError("Guest-session temporary data must be an object.")

    if existing is None:
        return application_data.insert_guest_session(
            guest_session_id=guest_session_id,
            session_id=session_id,
            workspace_id="guest:%s" % guest_session_id,
            created_at=str(record.get("created_at") or ""),
            expires_at=str(record.get("expires_at") or ""),
            used_at=str(record.get("used_at") or ""),
            ended_at=str(record.get("ended_at") or ""),
            updated_at=str(record.get("updated_at") or record.get("used_at") or ""),
            is_active=is_active,
            lifecycle_state=lifecycle_state,
            temporary_data=temporary_data,
            source_version=str(record.get("source_version") or "1"),
            source_sha256=_legacy_record_sha256(record),
            connection=connection,
        )

    if (
        existing.get("lifecycle_state") != "active"
        and is_active
        and lifecycle_state == "active"
    ):
        # Shadow JSON may lag a durable logout/deactivation.  Never use it to
        # resurrect an inactive durable identity.
        return existing

    immutable = {
        "session_id": session_id,
        "workspace_id": "guest:%s" % guest_session_id,
        "created_at": str(record.get("created_at") or ""),
    }
    if any(existing.get(name) != value for name, value in immutable.items()):
        raise GuestSessionStorageError(
            "Guest-session shadow data conflicts with a durable identity."
        )
    current_used_at = parse_iso_datetime(existing.get("used_at"))
    requested_used_at = parse_iso_datetime(record.get("used_at"))
    if not requested_used_at or (current_used_at and requested_used_at < current_used_at):
        raise GuestSessionStorageError(
            "Guest-session shadow data would regress durable activity state."
        )
    return application_data.update_guest_session(
        guest_session_id,
        used_at=str(record.get("used_at") or ""),
        expires_at=str(record.get("expires_at") or ""),
        ended_at=str(record.get("ended_at") or ""),
        is_active=is_active,
        lifecycle_state=lifecycle_state,
        temporary_data=temporary_data,
        source_sha256=_legacy_record_sha256(record),
        expected_row_version=int(existing.get("row_version") or 0),
        connection=connection,
    )


def _restore_json_snapshot_unlocked(existed, raw):
    try:
        if existed:
            _atomic_write_bytes_unlocked(GUEST_SESSIONS_FILE, raw)
        else:
            GUEST_SESSIONS_FILE.unlink(missing_ok=True)
    except Exception as exc:
        raise GuestSessionStorageError(
            "Guest-session JSON rollback could not be completed."
        ) from exc


def _shadow_mutation_unlocked(mutator, payload=None):
    """Run a JSON/SQLite shadow mutation with one lock and one DB transaction."""

    normalized = (
        deepcopy(_normalize_guest_sessions_payload(payload))
        if payload is not None
        else _load_json_guest_sessions_unlocked()
    )
    existed = GUEST_SESSIONS_FILE.is_file()
    try:
        original = GUEST_SESSIONS_FILE.read_bytes() if existed else b""
    except OSError as exc:
        raise GuestSessionStorageError(
            "Guest session registry is unreadable; refusing a shadow write."
        ) from exc

    json_replaced = False
    application_data = _application_data_service()
    try:
        with application_data.application_data_write_connection(
            guest_session_db_path()
        ) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result, changed = mutator(normalized, connection)
            if changed:
                for record in normalized["guest_sessions"]:
                    _database_record_from_legacy(record, connection)
                _save_json_guest_sessions_unlocked(normalized)
                json_replaced = True
        return result, normalized
    except BaseException as exc:
        if json_replaced:
            _restore_json_snapshot_unlocked(existed, original)
        if isinstance(exc, GuestSessionStorageError):
            raise
        raise GuestSessionStorageError("Guest-session shadow write failed.") from exc


def _save_shadow_payload_unlocked(payload):
    """Mirror a complete JSON payload using the shadow transaction boundary."""

    def replace(_stored, _connection):
        return None, True

    _result, normalized = _shadow_mutation_unlocked(replace, payload=payload)
    return normalized


def _database_write(operation):
    application_data = _application_data_service()
    try:
        with application_data.application_data_write_connection(
            guest_session_db_path()
        ) as connection:
            connection.execute("BEGIN IMMEDIATE")
            return operation(connection)
    except GuestSessionStorageError:
        raise
    except Exception as exc:
        raise GuestSessionStorageError("Guest-session database write failed.") from exc


def _sync_caller_payload(caller_payload, stored_payload):
    if isinstance(caller_payload, dict):
        caller_payload.clear()
        caller_payload.update(deepcopy(stored_payload))


def _json_payload_for_mutation(caller_payload=None):
    if GUEST_SESSIONS_FILE.exists():
        return _load_json_guest_sessions_unlocked()
    if isinstance(caller_payload, dict):
        return deepcopy(_normalize_guest_sessions_payload(caller_payload))
    return {"guest_sessions": []}


def _database_record_for_read_unlocked(guest_session_id):
    application_data = _application_data_service()
    try:
        with application_data.existing_application_read_connection(
            guest_session_db_path()
        ) as connection:
            if connection is None:
                raise GuestSessionStorageError("Guest-session database is unavailable.")
            record, fenced = _database_guest_fence(connection, guest_session_id)
            if record is None:
                return None
            converted = _legacy_record_from_database(record)
            if fenced:
                converted["is_active"] = False
                converted["lifecycle_state"] = "purging"
            return converted
    except GuestSessionStorageError:
        raise
    except Exception as exc:
        raise GuestSessionStorageError(
            "Guest-session database record could not be read."
        ) from exc


def _shadow_record_for_read_unlocked(payload, guest_session_id):
    record = find_guest_session(payload, guest_session_id)
    if record is None:
        return None
    application_data = _application_data_service()
    try:
        with application_data.existing_application_read_connection(
            guest_session_db_path()
        ) as connection:
            if connection is None:
                raise GuestSessionStorageError("Guest-session shadow database is unavailable.")
            durable, fenced = _database_guest_fence(connection, guest_session_id)
            converted = deepcopy(record)
            if fenced:
                converted["is_active"] = False
                converted["lifecycle_state"] = "purging"
                return converted
            if durable is not None:
                if (
                    durable.get("lifecycle_state") != "active"
                    and record.get("is_active", False)
                ):
                    converted["is_active"] = False
                    converted["lifecycle_state"] = str(
                        durable.get("lifecycle_state") or "inactive"
                    )
                    return converted
                comparable = {
                    "session_id": str(record.get("session_id") or record.get("id") or ""),
                    "created_at": str(record.get("created_at") or ""),
                    "expires_at": str(record.get("expires_at") or ""),
                    "is_active": bool(record.get("is_active")),
                    "lifecycle_state": str(
                        record.get("lifecycle_state")
                        or ("active" if record.get("is_active") else "inactive")
                    ),
                }
                if any(durable.get(name) != value for name, value in comparable.items()):
                    raise GuestSessionStorageError(
                        "Guest-session shadow read found divergent durable state."
                    )
            return converted
    except GuestSessionStorageError:
        raise
    except Exception as exc:
        raise GuestSessionStorageError(
            "Guest-session shadow fence could not be read."
        ) from exc


def _lookup_guest_session_unlocked(guest_session_id, mode):
    if _database_authority(mode):
        return _database_record_for_read_unlocked(guest_session_id)
    payload = _load_json_guest_sessions_unlocked()
    if mode == "shadow":
        _require_shadow_database()
        return _shadow_record_for_read_unlocked(payload, guest_session_id)
    record = find_guest_session(payload, guest_session_id)
    if record is not None and _guest_purge_fenced(guest_session_id):
        record = deepcopy(record)
        record["is_active"] = False
        record["lifecycle_state"] = "purging"
    return record


def guest_workspace_root(guest_session_id=None):
    if guest_session_id:
        session_id = safe_user_id(guest_session_id)
    elif has_request_context():
        session_id = safe_user_id(session.get("guest_session_id"))
    else:
        session_id = ""
    root = GUEST_DATA_DIR / session_id if session_id else GUEST_DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def guest_session_serializer():
    return URLSafeSerializer(current_app.secret_key, salt="guest-demo-session")


def sign_guest_session_id(guest_session_id):
    return guest_session_serializer().dumps(str(guest_session_id or ""))


def decode_guest_cookie(value):
    if not value:
        return ""

    try:
        return str(guest_session_serializer().loads(value) or "").strip()
    except BadSignature:
        return ""


def find_guest_session(payload, guest_session_id):
    guest_session_id = str(guest_session_id or "").strip()
    if not guest_session_id:
        return None

    for item in payload.get("guest_sessions", []):
        if isinstance(item, dict) and str(item.get("id") or "") == guest_session_id:
            return item

    return None


def guest_session_is_valid(record, at_time=None):
    if not isinstance(record, dict) or not record.get("is_active", False):
        return False

    if str(record.get("lifecycle_state") or "active").strip().lower() not in {"", "active"}:
        return False

    expires_at = parse_iso_datetime(record.get("expires_at"))
    if not expires_at:
        return False

    return expires_at > normalize_utc_datetime(at_time)


def guest_session_is_expired(record, at_time=None):
    if not isinstance(record, dict):
        return False
    expires_at = parse_iso_datetime(record.get("expires_at"))
    return expires_at is None or expires_at <= normalize_utc_datetime(at_time)


def clear_guest_session_flags():
    if not has_request_context():
        return

    session.pop("is_guest", None)
    session.pop("guest_session_id", None)


def activate_guest_session(record):
    session.permanent = True
    session.pop("user_id", None)
    session.pop("firebase_uid", None)
    session.pop("email", None)
    session.pop("display_name", None)
    session.pop("picture", None)
    session.pop("provider", None)
    session.pop("is_admin", None)
    session["is_guest"] = True
    session["guest_session_id"] = record["id"]


def _new_guest_session_record():
    created_at = now_utc()
    guest_session_id = uuid.uuid4().hex
    timestamp = created_at.isoformat().replace("+00:00", "Z")
    return {
        "id": guest_session_id,
        "session_id": guest_session_id,
        "created_at": timestamp,
        "expires_at": (created_at + GUEST_SESSION_TTL).isoformat().replace("+00:00", "Z"),
        "used_at": timestamp,
        "is_active": True,
        "lifecycle_state": "active",
        "temporary_data_json": {},
    }


def create_guest_session(payload=None):
    with _guest_registry_write_lock():
        record = _new_guest_session_record()
        guest_session_id = record["id"]
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            def insert(connection):
                stored = _database_record_from_legacy(record, connection)
                return _legacy_record_from_database(stored)

            result = _database_write(insert)
            stored_payload = _load_database_guest_sessions()
        else:
            if mode == "shadow":
                _require_shadow_database()
            stored_payload = _json_payload_for_mutation(payload)
            stored_payload["guest_sessions"].append(record)
            if mode == "shadow":
                _save_shadow_payload_unlocked(stored_payload)
            else:
                _save_json_guest_sessions_unlocked(stored_payload)
            result = record
        _sync_caller_payload(payload, stored_payload)
        guest_workspace_root(guest_session_id)
        return result


def update_guest_used_at(record, payload=None):
    if not isinstance(record, dict):
        return None
    guest_session_id = str(record.get("id") or "").strip()
    if not guest_session_id:
        return None

    with _guest_registry_write_lock():
        used_at = now_iso()
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            def update(connection):
                application_data = _application_data_service()
                existing, fenced = _database_guest_fence(connection, guest_session_id)
                if fenced:
                    raise GuestSessionStorageError(
                        "Guest-session activity update was rejected by a purge fence."
                    )
                if existing is None:
                    return None
                changed = application_data.update_guest_session(
                    guest_session_id,
                    used_at=used_at,
                    expected_row_version=int(existing.get("row_version") or 0),
                    connection=connection,
                )
                return _legacy_record_from_database(changed) if changed else None

            return _database_write(update)

        if mode == "shadow":
            _require_shadow_database()
            def update_shadow(stored_payload, connection):
                stored = find_guest_session(stored_payload, guest_session_id)
                durable, fenced = _database_guest_fence(connection, guest_session_id)
                if stored is None or fenced:
                    return None, False
                if durable is not None and durable.get("lifecycle_state") != "active":
                    return None, False
                stored["used_at"] = used_at
                return stored, True

            stored, stored_payload = _shadow_mutation_unlocked(update_shadow)
            _sync_caller_payload(payload, stored_payload)
            return stored

        stored_payload = _json_payload_for_mutation(payload)
        stored = find_guest_session(stored_payload, guest_session_id)
        if not stored:
            return None
        stored["used_at"] = used_at
        _save_json_guest_sessions_unlocked(stored_payload)
        _sync_caller_payload(payload, stored_payload)
        return stored


def delete_guest_temporary_data(guest_session_id):
    """Reject the former partial file/job cleanup path.

    Guest deletion must go through ``guest_purge_service`` so recipe rows,
    application rows, jobs, artifacts, and the workspace are handled by one
    durable, retryable saga. Keeping this compatibility name fail-closed also
    prevents an out-of-tree legacy caller from recreating orphan data.
    """

    del guest_session_id
    raise GuestSessionStorageError(
        "Partial guest cleanup is disabled; use the transactional guest purge workflow."
    )


def cleanup_expired_guest_sessions(at_time=None):
    """Expire access only; physical deletion is owned by the purge command."""
    at_time = normalize_utc_datetime(at_time)
    with _guest_registry_write_lock():
        ended_at = now_iso()
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            def expire(connection):
                application_data = _application_data_service()
                for stored in application_data.list_guest_sessions(connection=connection):
                    record = _legacy_record_from_database(stored)
                    if not guest_session_is_expired(record, at_time=at_time):
                        continue
                    if not stored.get("is_active", False):
                        continue
                    _current, fenced = _database_guest_fence(connection, stored["id"])
                    if fenced:
                        continue
                    application_data.deactivate_guest_session(
                        stored["id"],
                        ended_at=ended_at,
                        expected_row_version=int(stored.get("row_version") or 0),
                        connection=connection,
                    )
                return _load_database_guest_sessions(connection)

            return _database_write(expire)

        if mode == "shadow":
            _require_shadow_database()
        payload = _json_payload_for_mutation()
        changed = False
        for record in payload.get("guest_sessions", []):
            if not isinstance(record, dict):
                continue
            if not guest_session_is_expired(record, at_time=at_time):
                continue
            if record.get("is_active", False):
                record["is_active"] = False
                record["lifecycle_state"] = "inactive"
                record["ended_at"] = ended_at
                changed = True

        if changed:
            if mode == "shadow":
                _save_shadow_payload_unlocked(payload)
            else:
                _save_json_guest_sessions_unlocked(payload)
        return payload


def expired_guest_session_count(at_time=None):
    at_time = normalize_utc_datetime(at_time)
    payload = load_guest_sessions()
    return sum(
        1
        for record in payload.get("guest_sessions", [])
        if isinstance(record, dict) and guest_session_is_expired(record, at_time=at_time)
    )


def delete_expired_guest_sessions(at_time=None):
    """Deprecated fail-closed shim; physical deletion belongs to the purge saga.

    This legacy API intentionally does not read, rewrite, or delete the JSON
    registry, workspaces, jobs, recipe rows, or artifacts in any backend mode.
    Callers must use the dry-run-first guest purge service with its explicit
    approval gate after the database migration is complete.
    """

    normalize_utc_datetime(at_time)
    return {
        "ok": False,
        "applied": False,
        "deleted_count": 0,
        "guest_session_ids": [],
        "code": "transactional_guest_purge_required",
        "deprecated": True,
    }


def deactivate_guest_session(guest_session_id, delete_data=True):
    guest_session_id = str(guest_session_id or "").strip()
    if not guest_session_id:
        return False
    with _guest_registry_write_lock():
        ended_at = now_iso()
        mode = guest_session_backend_mode()
        if _database_authority(mode):
            def deactivate(connection):
                application_data = _application_data_service()
                existing, fenced = _database_guest_fence(connection, guest_session_id)
                if existing is None or fenced:
                    return False
                application_data.deactivate_guest_session(
                    guest_session_id,
                    ended_at=ended_at,
                    expected_row_version=int(existing.get("row_version") or 0),
                    connection=connection,
                )
                return True

            changed = _database_write(deactivate)
        else:
            if mode == "shadow":
                _require_shadow_database()
            payload = _json_payload_for_mutation()
            record = find_guest_session(payload, guest_session_id)
            if not record:
                return False
            record["is_active"] = False
            record["lifecycle_state"] = "inactive"
            record["ended_at"] = ended_at
            if mode == "shadow":
                _save_shadow_payload_unlocked(payload)
            else:
                _save_json_guest_sessions_unlocked(payload)
            changed = True

    # Revocation is deliberately access-only. Physical deletion is deferred
    # to the approval-gated purge saga at the session's expiration boundary.
    # ``delete_data`` remains accepted for API compatibility but cannot invoke
    # the former partial file/job deletion path.
    return bool(changed)


def delete_current_guest_session():
    if not has_request_context():
        return False

    guest_session_id = str(session.get("guest_session_id") or "").strip()
    deleted = deactivate_guest_session(guest_session_id, delete_data=False) if guest_session_id else False
    clear_guest_session_flags()
    return deleted


def get_current_guest_session():
    if not has_request_context() or not session.get("is_guest"):
        return None

    with GUEST_SESSIONS_LOCK:
        mode = guest_session_backend_mode()
        record = _lookup_guest_session_unlocked(
            str(session.get("guest_session_id") or ""),
            mode,
        )
    if guest_session_is_valid(record):
        return record

    clear_guest_session_flags()
    return None


def is_guest_session():
    return get_current_guest_session() is not None


def guest_session_can_accept_writes(guest_session_id, at_time=None):
    """Return whether an exact guest identity may create or update owned data."""
    guest_session_id = str(guest_session_id or "").strip()
    if not guest_session_id:
        return False
    if _guest_purge_fenced(guest_session_id):
        return False
    with GUEST_SESSIONS_LOCK:
        mode = guest_session_backend_mode()
        record = _lookup_guest_session_unlocked(guest_session_id, mode)
        return guest_session_is_valid(record, at_time=at_time)


def start_or_restore_guest_session(cookie_value=""):
    remembered_session_id = decode_guest_cookie(cookie_value)
    with _guest_registry_write_lock():
        mode = guest_session_backend_mode()
        used_at = now_iso()
        if _database_authority(mode):
            def start(connection):
                application_data = _application_data_service()
                durable, fenced = _database_guest_fence(connection, remembered_session_id)
                if durable is not None and not fenced:
                    candidate = _legacy_record_from_database(durable)
                else:
                    candidate = None
                if guest_session_is_valid(candidate):
                    stored = application_data.update_guest_session(
                        durable["id"],
                        used_at=used_at,
                        expected_row_version=int(durable.get("row_version") or 0),
                        connection=connection,
                    )
                    return _legacy_record_from_database(stored)
                created = _new_guest_session_record()
                return _legacy_record_from_database(
                    _database_record_from_legacy(created, connection)
                )

            record = _database_write(start)
        elif mode == "shadow":
            _require_shadow_database()

            def start_shadow(payload, connection):
                candidate = find_guest_session(payload, remembered_session_id)
                durable, fenced = _database_guest_fence(connection, remembered_session_id)
                durable_valid = durable is None or guest_session_is_valid(
                    _legacy_record_from_database(durable)
                )
                if guest_session_is_valid(candidate) and not fenced and durable_valid:
                    candidate["used_at"] = used_at
                    return candidate, True
                created = _new_guest_session_record()
                payload["guest_sessions"].append(created)
                return created, True

            record, _payload = _shadow_mutation_unlocked(start_shadow)
        else:
            payload = _load_json_guest_sessions_unlocked()
            record = find_guest_session(payload, remembered_session_id)
            if guest_session_is_valid(record) and not _guest_purge_fenced(
                remembered_session_id
            ):
                record["used_at"] = used_at
            else:
                record = _new_guest_session_record()
                payload["guest_sessions"].append(record)
            _save_json_guest_sessions_unlocked(payload)
        guest_workspace_root(record["id"])
    activate_guest_session(record)
    return record


def restore_guest_session_from_cookie(cookie_value=""):
    remembered_session_id = decode_guest_cookie(cookie_value)
    with _guest_registry_write_lock():
        mode = guest_session_backend_mode()
        used_at = now_iso()
        if _database_authority(mode):
            def restore(connection):
                application_data = _application_data_service()
                durable, fenced = _database_guest_fence(connection, remembered_session_id)
                candidate = (
                    _legacy_record_from_database(durable)
                    if durable is not None and not fenced
                    else None
                )
                if not guest_session_is_valid(candidate):
                    return None
                stored = application_data.update_guest_session(
                    remembered_session_id,
                    used_at=used_at,
                    expected_row_version=int(durable.get("row_version") or 0),
                    connection=connection,
                )
                return _legacy_record_from_database(stored)

            record = _database_write(restore)
        elif mode == "shadow":
            _require_shadow_database()

            def restore_shadow(payload, connection):
                candidate = find_guest_session(payload, remembered_session_id)
                durable, fenced = _database_guest_fence(connection, remembered_session_id)
                durable_valid = durable is None or guest_session_is_valid(
                    _legacy_record_from_database(durable)
                )
                if not guest_session_is_valid(candidate) or fenced or not durable_valid:
                    return None, False
                candidate["used_at"] = used_at
                return candidate, True

            record, _payload = _shadow_mutation_unlocked(restore_shadow)
        else:
            payload = _load_json_guest_sessions_unlocked()
            record = find_guest_session(payload, remembered_session_id)
            if guest_session_is_valid(record) and not _guest_purge_fenced(
                remembered_session_id
            ):
                record["used_at"] = used_at
                _save_json_guest_sessions_unlocked(payload)
            else:
                record = None

    if record is None:
        clear_guest_session_flags()
        return None
    activate_guest_session(record)
    return record


def remembered_guest_cookie_status(cookie_value=""):
    if not cookie_value:
        return "missing"

    guest_session_id = decode_guest_cookie(cookie_value)
    if not guest_session_id:
        return "invalid"

    with GUEST_SESSIONS_LOCK:
        mode = guest_session_backend_mode()
        record = _lookup_guest_session_unlocked(guest_session_id, mode)
    if not record:
        return "invalid"

    if guest_session_is_valid(record):
        return "valid"

    return "expired"


def cookie_should_be_secure():
    if not has_request_context():
        return False

    env = str(os.getenv("FLASK_ENV") or os.getenv("SHOPPING_APP_ENV") or "").strip().lower()
    return request.is_secure or env in {"production", "prod"}


def set_guest_cookie(response, guest_session_id):
    response.set_cookie(
        GUEST_COOKIE_NAME,
        sign_guest_session_id(guest_session_id),
        max_age=GUEST_COOKIE_MAX_AGE,
        httponly=True,
        secure=cookie_should_be_secure(),
        samesite="Lax",
    )
    return response


def clear_guest_cookie(response):
    response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
    return response


def guest_banner_context():
    record = get_current_guest_session()
    if not record:
        return None

    expires_at = parse_iso_datetime(record.get("expires_at"))
    remaining_seconds = 0
    if expires_at:
        remaining_seconds = max(0, int((expires_at - now_utc()).total_seconds()))

    hours = remaining_seconds // 3600
    minutes = (remaining_seconds % 3600) // 60
    return {
        "session_id": record.get("id", ""),
        "expires_at": record.get("expires_at", ""),
        "remaining_label": f"{hours:02d}:{minutes:02d}",
    }
