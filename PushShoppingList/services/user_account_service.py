import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import has_request_context
from flask import session
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename


PACKAGE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = Path(os.getenv("SHOPPING_APP_USERS_FILE", PACKAGE_DIR / "users.json"))
AVATAR_UPLOAD_DIR = Path(os.getenv("SHOPPING_APP_AVATAR_UPLOAD_DIR", PACKAGE_DIR / "static" / "uploads" / "avatars"))
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_users():
    if not USERS_FILE.exists():
        return {"users": []}

    try:
        payload = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"users": []}

    if not isinstance(payload, dict):
        return {"users": []}

    users = [
        user
        for user in payload.get("users", [])
        if isinstance(user, dict) and user.get("user_id")
    ]
    return {"users": users}


def save_users(payload):
    normalized = {
        "users": [
            user
            for user in payload.get("users", [])
            if isinstance(user, dict) and user.get("user_id")
        ],
    }
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def public_user(user):
    if not isinstance(user, dict):
        return None

    return {
        "user_id": user.get("user_id", ""),
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "avatar_path": user.get("avatar_path", ""),
        "created_at": user.get("created_at", ""),
        "updated_at": user.get("updated_at", ""),
    }


def current_user():
    if not has_request_context():
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    return find_user_by_id(user_id)


def current_public_user():
    return public_user(current_user())


def find_user_by_id(user_id):
    user_id = str(user_id or "")
    return next(
        (user for user in load_users().get("users", []) if str(user.get("user_id")) == user_id),
        None,
    )


def find_user_by_identity(identity):
    identity_key = normalize_identity(identity)

    if not identity_key:
        return None

    for user in load_users().get("users", []):
        if (
            normalize_identity(user.get("username")) == identity_key
            or normalize_identity(user.get("email")) == identity_key
        ):
            return user

    return None


def normalize_identity(value):
    return str(value or "").strip().lower()


def validate_account_fields(username, email, password=None, confirm_password=None, require_password=True):
    errors = []
    username = str(username or "").strip()
    email = str(email or "").strip()
    password = str(password or "")
    confirm_password = str(confirm_password or "")

    if not username:
        errors.append("Username is required.")

    if not email:
        errors.append("Email is required.")
    elif not EMAIL_PATTERN.match(email):
        errors.append("Enter a valid email address.")

    if require_password and not password:
        errors.append("Password is required.")

    if password or confirm_password:
        if password != confirm_password:
            errors.append("Password and confirm password must match.")

    return errors


def create_user(username, email, password, confirm_password, avatar_file=None):
    errors = validate_account_fields(username, email, password, confirm_password, require_password=True)
    username = str(username or "").strip()
    email = str(email or "").strip()
    payload = load_users()

    if username and any(normalize_identity(user.get("username")) == normalize_identity(username) for user in payload["users"]):
        errors.append("That username is already in use.")

    if email and any(normalize_identity(user.get("email")) == normalize_identity(email) for user in payload["users"]):
        errors.append("That email is already in use.")

    if errors:
        return {"ok": False, "errors": errors}

    user_id = uuid.uuid4().hex
    timestamp = now_iso()
    user = {
        "user_id": user_id,
        "username": username,
        "email": email,
        "password_hash": generate_password_hash(password),
        "avatar_path": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    avatar_result = save_avatar_upload(avatar_file, user_id)

    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["avatar_path"] = avatar_result.get("avatar_path", "")
    payload["users"].append(user)
    save_users(payload)
    session["user_id"] = user_id
    return {"ok": True, "user": public_user(user)}


def authenticate_user(identity, password):
    identity = str(identity or "").strip()
    password = str(password or "")

    if not identity or not password:
        return {"ok": False, "errors": ["Enter your username or email and password."]}

    user = find_user_by_identity(identity)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        return {"ok": False, "errors": ["We could not sign you in with those details."]}

    session["user_id"] = user["user_id"]
    return {"ok": True, "user": public_user(user)}


def sign_out_user():
    session.pop("user_id", None)


def update_user_profile(user_id, username, email, password="", confirm_password="", avatar_file=None):
    payload = load_users()
    user = next((item for item in payload["users"] if item.get("user_id") == user_id), None)

    if not user:
        return {"ok": False, "errors": ["Sign in again before editing your profile."]}

    errors = validate_account_fields(
        username,
        email,
        password,
        confirm_password,
        require_password=False,
    )
    username = str(username or "").strip()
    email = str(email or "").strip()

    for existing in payload["users"]:
        if existing.get("user_id") == user_id:
            continue
        if normalize_identity(existing.get("username")) == normalize_identity(username):
            errors.append("That username is already in use.")
        if normalize_identity(existing.get("email")) == normalize_identity(email):
            errors.append("That email is already in use.")

    if errors:
        return {"ok": False, "errors": errors}

    avatar_result = save_avatar_upload(avatar_file, user_id)
    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["username"] = username
    user["email"] = email
    if password:
        user["password_hash"] = generate_password_hash(password)
    if avatar_result.get("avatar_path"):
        user["avatar_path"] = avatar_result["avatar_path"]
    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True, "user": public_user(user)}


def save_avatar_upload(upload, user_id):
    if not upload or not getattr(upload, "filename", ""):
        return {"ok": True, "avatar_path": ""}

    filename = secure_filename(upload.filename or "")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension not in ALLOWED_AVATAR_EXTENSIONS:
        return {
            "ok": False,
            "errors": ["Avatar must be a PNG, JPG, JPEG, or WEBP image."],
        }

    AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{secure_filename(str(user_id))}_{uuid.uuid4().hex[:10]}.{extension}"
    upload.save(AVATAR_UPLOAD_DIR / stored_name)
    return {
        "ok": True,
        "avatar_path": f"uploads/avatars/{stored_name}",
    }
