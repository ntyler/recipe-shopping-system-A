import json
import os
import shutil
import uuid
from datetime import datetime
from datetime import timedelta
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


def now_utc():
    return datetime.utcnow().replace(microsecond=0)


def now_iso():
    return now_utc().isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None


def load_guest_sessions():
    if not GUEST_SESSIONS_FILE.exists():
        return {"guest_sessions": []}

    try:
        payload = json.loads(GUEST_SESSIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"guest_sessions": []}

    if not isinstance(payload, dict):
        return {"guest_sessions": []}

    sessions = payload.get("guest_sessions")
    if not isinstance(sessions, list):
        payload["guest_sessions"] = []

    return payload


def save_guest_sessions(payload):
    payload = payload if isinstance(payload, dict) else {"guest_sessions": []}
    payload.setdefault("guest_sessions", [])
    GUEST_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GUEST_SESSIONS_FILE.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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

    expires_at = parse_iso_datetime(record.get("expires_at"))
    if not expires_at:
        return False

    return expires_at > (at_time or now_utc())


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


def create_guest_session(payload=None):
    payload = payload or load_guest_sessions()
    created_at = now_utc()
    guest_session_id = uuid.uuid4().hex
    record = {
        "id": guest_session_id,
        "session_id": guest_session_id,
        "created_at": created_at.isoformat() + "Z",
        "expires_at": (created_at + GUEST_SESSION_TTL).isoformat() + "Z",
        "used_at": created_at.isoformat() + "Z",
        "is_active": True,
        "temporary_data_json": {},
    }
    payload.setdefault("guest_sessions", []).append(record)
    save_guest_sessions(payload)
    guest_workspace_root(guest_session_id)
    return record


def update_guest_used_at(record, payload=None):
    if not isinstance(record, dict):
        return None

    payload = payload or load_guest_sessions()
    stored = find_guest_session(payload, record.get("id"))
    if not stored:
        return None

    stored["used_at"] = now_iso()
    save_guest_sessions(payload)
    return stored


def delete_guest_temporary_data(guest_session_id):
    safe_id = safe_user_id(guest_session_id)
    if not safe_id:
        return

    root = GUEST_DATA_DIR / safe_id
    try:
        resolved_root = root.resolve()
        resolved_base = GUEST_DATA_DIR.resolve()
    except OSError:
        return

    if resolved_root == resolved_base or resolved_base not in resolved_root.parents:
        return

    shutil.rmtree(resolved_root, ignore_errors=True)


def cleanup_expired_guest_sessions(at_time=None):
    at_time = at_time or now_utc()
    payload = load_guest_sessions()
    changed = False

    for record in payload.get("guest_sessions", []):
        if not isinstance(record, dict):
            continue

        expires_at = parse_iso_datetime(record.get("expires_at"))
        should_cleanup = not record.get("is_active", False) or (expires_at and expires_at <= at_time)
        if not should_cleanup:
            continue

        if record.get("is_active", False):
            record["is_active"] = False
            changed = True

        delete_guest_temporary_data(record.get("id"))

    if changed:
        save_guest_sessions(payload)

    return payload


def get_current_guest_session():
    if not has_request_context() or not session.get("is_guest"):
        return None

    payload = load_guest_sessions()
    record = find_guest_session(payload, session.get("guest_session_id"))
    if guest_session_is_valid(record):
        return record

    clear_guest_session_flags()
    return None


def is_guest_session():
    return get_current_guest_session() is not None


def start_or_restore_guest_session(cookie_value=""):
    cleanup_expired_guest_sessions()
    payload = load_guest_sessions()
    remembered_session_id = decode_guest_cookie(cookie_value)
    record = find_guest_session(payload, remembered_session_id)

    if guest_session_is_valid(record):
        record = update_guest_used_at(record, payload) or record
    else:
        record = create_guest_session(payload)

    activate_guest_session(record)
    return record


def restore_guest_session_from_cookie(cookie_value=""):
    payload = cleanup_expired_guest_sessions()
    remembered_session_id = decode_guest_cookie(cookie_value)
    record = find_guest_session(payload, remembered_session_id)

    if not guest_session_is_valid(record):
        clear_guest_session_flags()
        return None

    record = update_guest_used_at(record, payload) or record
    activate_guest_session(record)
    return record


def remembered_guest_cookie_status(cookie_value=""):
    if not cookie_value:
        return "missing"

    guest_session_id = decode_guest_cookie(cookie_value)
    if not guest_session_id:
        return "invalid"

    record = find_guest_session(load_guest_sessions(), guest_session_id)
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
