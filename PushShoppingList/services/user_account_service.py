import json
import os
import re
import secrets
import uuid
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from flask import has_request_context
from flask import session
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from PushShoppingList.services.two_factor_service import ISSUER_NAME
from PushShoppingList.services.two_factor_service import backup_codes_remaining
from PushShoppingList.services.two_factor_service import generate_backup_codes
from PushShoppingList.services.two_factor_service import generate_totp_secret
from PushShoppingList.services.two_factor_service import hash_backup_codes
from PushShoppingList.services.two_factor_service import totp_qr_data_uri
from PushShoppingList.services.two_factor_service import totp_uri
from PushShoppingList.services.two_factor_service import verify_backup_code
from PushShoppingList.services.two_factor_service import verify_totp_code
from PushShoppingList.services.user_workspace_seed_service import seed_new_user_rule_workspace


PACKAGE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = Path(os.getenv("SHOPPING_APP_USERS_FILE", PACKAGE_DIR / "users.json"))
AVATAR_UPLOAD_DIR = Path(os.getenv("SHOPPING_APP_AVATAR_UPLOAD_DIR", PACKAGE_DIR / "static" / "uploads" / "avatars"))
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGITS_PATTERN = re.compile(r"\d+")
ADMIN_EMAIL = os.getenv("SHOPPING_APP_ADMIN_EMAIL", "ntylerbert@gmail.com").strip().lower()
PASSWORD_RESET_TTL_HOURS = 1
TWO_FACTOR_TRUST_DAYS = 30
TWO_FACTOR_RECOVERY_TTL_MINUTES = 30
NTFY_TOPIC_PREFIX = os.getenv("SHOPPING_APP_NTFY_TOPIC_PREFIX", "shopping-user").strip() or "shopping-user"


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None


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


def normalize_ntfy_topic(topic):
    return re.sub(r"[^a-zA-Z0-9_-]+", "", str(topic or "").strip())[:200]


def generate_ntfy_topic():
    prefix = normalize_ntfy_topic(NTFY_TOPIC_PREFIX) or "shopping-user"
    return normalize_ntfy_topic(f"{prefix}-{secrets.token_urlsafe(24)}")


def ntfy_subscription_url(topic):
    topic = normalize_ntfy_topic(topic)

    if not topic:
        return ""

    return f"https://ntfy.sh/{topic}"


def ensure_user_ntfy_topic(user_id):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return None

    topic = normalize_ntfy_topic(user.get("ntfy_topic"))

    if not topic or topic != str(user.get("ntfy_topic") or ""):
        user["ntfy_topic"] = topic or generate_ntfy_topic()
        user["ntfy_topic_created_at"] = user.get("ntfy_topic_created_at") or now_iso()
        user["updated_at"] = now_iso()
        save_users(payload)

    return user


def public_user(user):
    if not isinstance(user, dict):
        return None
    two_factor = user.get("two_factor") if isinstance(user.get("two_factor"), dict) else {}
    ntfy_topic = normalize_ntfy_topic(user.get("ntfy_topic"))

    return {
        "user_id": user.get("user_id", ""),
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "ntfy_topic": ntfy_topic,
        "ntfy_url": ntfy_subscription_url(ntfy_topic),
        "avatar_path": user.get("avatar_path", ""),
        "created_at": user.get("created_at", ""),
        "updated_at": user.get("updated_at", ""),
        "is_admin": is_admin_user(user),
        "two_factor_enabled": bool(two_factor.get("enabled")),
        "two_factor_backup_codes_remaining": backup_codes_remaining(two_factor) if two_factor.get("enabled") else 0,
    }


def is_admin_user(user):
    email = str((user or {}).get("email") or "").strip().lower()
    return bool(ADMIN_EMAIL and email == ADMIN_EMAIL)


def current_user():
    if not has_request_context():
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    user = find_user_by_id(user_id)

    stored_ntfy_topic = str((user or {}).get("ntfy_topic") or "")
    normalized_ntfy_topic = normalize_ntfy_topic(stored_ntfy_topic)

    if user and (not normalized_ntfy_topic or normalized_ntfy_topic != stored_ntfy_topic):
        user = ensure_user_ntfy_topic(user_id) or user

    return user


def current_public_user():
    return public_user(current_user())


def find_user_by_id(user_id):
    user_id = str(user_id or "")
    return next(
        (user for user in load_users().get("users", []) if str(user.get("user_id")) == user_id),
        None,
    )


def find_user_by_identity(identity):
    return find_user_by_identity_in_payload(load_users(), identity)


def find_user_by_identity_in_payload(payload, identity):
    identity_key = normalize_identity(identity)

    if not identity_key:
        return None

    for user in payload.get("users", []):
        if (
            normalize_identity(user.get("username")) == identity_key
            or normalize_identity(user.get("email")) == identity_key
        ):
            return user

    return None


def find_user_by_phone_in_payload(payload, phone):
    phone_keys = phone_lookup_candidates(phone)

    if not phone_keys:
        return None

    for user in payload.get("users", []):
        if phone_lookup_candidates(user.get("phone")) & phone_keys:
            return user

    return None


def normalize_identity(value):
    return str(value or "").strip().lower()


def normalize_phone_lookup(value):
    return "".join(PHONE_DIGITS_PATTERN.findall(str(value or "")))


def phone_lookup_candidates(value):
    digits = normalize_phone_lookup(value)

    if not digits:
        return set()

    candidates = {digits}

    if len(digits) == 10:
        candidates.add(f"1{digits}")
    elif len(digits) == 11 and digits.startswith("1"):
        candidates.add(digits[1:])

    return candidates


def normalize_phone_for_storage(phone):
    phone = str(phone or "").strip()
    digits = normalize_phone_lookup(phone)

    if not digits:
        return ""

    if phone.startswith("+"):
        return f"+{digits}"

    if len(digits) == 10:
        return f"+1{digits}"

    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    if len(digits) > 10:
        return f"+{digits}"

    return digits


def validate_phone(phone):
    phone = str(phone or "").strip()

    if not phone:
        return ""

    digits = normalize_phone_lookup(phone)

    if len(digits) < 7:
        return "Enter a valid phone number."

    return ""


def validate_account_fields(username, email, password=None, confirm_password=None, require_password=True, phone=""):
    errors = []
    username = str(username or "").strip()
    email = str(email or "").strip()
    phone = str(phone or "").strip()
    password = str(password or "")
    confirm_password = str(confirm_password or "")

    if not username:
        errors.append("Username is required.")

    if not email:
        errors.append("Email is required.")
    elif not EMAIL_PATTERN.match(email):
        errors.append("Enter a valid email address.")

    phone_error = validate_phone(phone)
    if phone_error:
        errors.append(phone_error)

    if require_password and not password:
        errors.append("Password is required.")

    if password or confirm_password:
        if password != confirm_password:
            errors.append("Password and confirm password must match.")

    return errors


def create_user(username, email, password, confirm_password, avatar_file=None, phone=""):
    errors = validate_account_fields(username, email, password, confirm_password, require_password=True, phone=phone)
    username = str(username or "").strip()
    email = str(email or "").strip()
    phone = normalize_phone_for_storage(phone)
    phone_keys = phone_lookup_candidates(phone)
    payload = load_users()

    if username and any(normalize_identity(user.get("username")) == normalize_identity(username) for user in payload["users"]):
        errors.append("That username is already in use.")

    if email and any(normalize_identity(user.get("email")) == normalize_identity(email) for user in payload["users"]):
        errors.append("That email is already in use.")

    if phone_keys and any(phone_lookup_candidates(user.get("phone")) & phone_keys for user in payload["users"]):
        errors.append("That phone number is already in use.")

    if errors:
        return {"ok": False, "errors": errors}

    user_id = uuid.uuid4().hex
    timestamp = now_iso()
    user = {
        "user_id": user_id,
        "username": username,
        "email": email,
        "phone": phone,
        "ntfy_topic": generate_ntfy_topic(),
        "ntfy_topic_created_at": timestamp,
        "password_hash": generate_password_hash(password),
        "avatar_path": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    avatar_result = save_avatar_upload(avatar_file, user_id)

    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["avatar_path"] = avatar_result.get("avatar_path", "")
    seed_result = seed_new_user_rule_workspace(user_id)

    if not seed_result.get("ok"):
        return {"ok": False, "errors": seed_result.get("errors", ["Unable to initialize account rules."])}

    payload["users"].append(user)
    save_users(payload)
    session["user_id"] = user_id
    return {"ok": True, "user": public_user(user)}


def authenticate_user(identity, password, trusted_device_token=""):
    identity = str(identity or "").strip()
    password = str(password or "")

    if not identity or not password:
        return {"ok": False, "errors": ["Enter your username or email and password."]}

    user = find_user_by_identity(identity)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        return {"ok": False, "errors": ["We could not sign you in with those details."]}

    if two_factor_enabled(user):
        if verify_trusted_two_factor_device(user, trusted_device_token):
            session["user_id"] = user["user_id"]
            session.pop("pending_2fa_user_id", None)
            return {"ok": True, "user": public_user(user)}

        session.pop("user_id", None)
        session["pending_2fa_user_id"] = user["user_id"]
        return {"ok": True, "requires_2fa": True, "user": public_user(user)}

    session["user_id"] = user["user_id"]
    session.pop("pending_2fa_user_id", None)
    return {"ok": True, "user": public_user(user)}


def request_password_reset(identity, delivery_method="email"):
    identity = str(identity or "").strip()
    delivery_method = str(delivery_method or "email").strip().lower()

    if delivery_method not in {"email", "phone"}:
        delivery_method = "email"

    if not identity:
        return {
            "ok": False,
            "errors": [
                "Enter your phone number to reset your password."
                if delivery_method == "phone"
                else "Enter your username or email to reset your password."
            ],
        }

    payload = load_users()
    user = (
        find_user_by_phone_in_payload(payload, identity)
        if delivery_method == "phone"
        else find_user_by_identity_in_payload(payload, identity)
    )

    if not user:
        return {"ok": True, "sent": False}

    token = secrets.token_urlsafe(32)
    timestamp = now_iso()
    user["password_reset"] = {
        # Store only a hash of the one-time token, never the reset token itself.
        "token_hash": generate_password_hash(token),
        "created_at": timestamp,
        "expires_at": (
            datetime.utcnow().replace(microsecond=0)
            + timedelta(hours=PASSWORD_RESET_TTL_HOURS)
        ).isoformat() + "Z",
    }
    save_users(payload)
    return {"ok": True, "sent": True, "token": token, "user": public_user(user), "delivery_method": delivery_method}


def reset_password_with_token(token, password, confirm_password):
    token = str(token or "").strip()
    password = str(password or "")
    confirm_password = str(confirm_password or "")
    errors = []

    if not token:
        errors.append("Password reset link is missing. Request a new one.")

    if not password:
        errors.append("New password is required.")

    if password or confirm_password:
        if password != confirm_password:
            errors.append("Password and confirm password must match.")

    if errors:
        return {"ok": False, "errors": errors}

    payload = load_users()
    user = find_user_by_reset_token(payload, token)

    if not user:
        return {
            "ok": False,
            "errors": ["That reset link is invalid or expired. Request a new password reset link."],
        }

    user["password_hash"] = generate_password_hash(password)
    user.pop("password_reset", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    session.pop("user_id", None)
    return {"ok": True, "user": public_user(user)}


def find_user_by_reset_token(payload, token):
    for user in payload.get("users", []):
        reset = user.get("password_reset") if isinstance(user, dict) else None

        if not isinstance(reset, dict):
            continue

        expires_at = parse_iso_datetime(reset.get("expires_at"))
        if not expires_at or expires_at < datetime.utcnow():
            continue

        token_hash = str(reset.get("token_hash") or "")
        if token_hash and check_password_hash(token_hash, token):
            return user

    return None


def request_two_factor_recovery(user_id):
    """Create an email recovery token only after the password sign-in step succeeds."""
    user_id = str(user_id or "").strip()

    if not user_id:
        return {"ok": False, "errors": ["Sign in with your password before requesting two-factor recovery."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in with your password before requesting two-factor recovery."]}

    if not two_factor_enabled(user):
        return {"ok": False, "errors": ["Two-factor authentication is not enabled for this account."]}

    token = secrets.token_urlsafe(32)
    timestamp = now_iso()
    user["two_factor_recovery"] = {
        # Store only a hash of the one-time recovery token.
        "token_hash": generate_password_hash(token),
        "created_at": timestamp,
        "expires_at": (
            datetime.utcnow().replace(microsecond=0)
            + timedelta(minutes=TWO_FACTOR_RECOVERY_TTL_MINUTES)
        ).isoformat() + "Z",
    }
    user["updated_at"] = timestamp
    save_users(payload)
    return {"ok": True, "sent": True, "token": token, "user": public_user(user)}


def recover_two_factor_with_token(token, password):
    token = str(token or "").strip()
    password = str(password or "")
    errors = []

    if not token:
        errors.append("Two-factor recovery link is missing. Request a new recovery email.")
    if not password:
        errors.append("Current password is required to recover two-factor access.")

    if errors:
        return {"ok": False, "errors": errors}

    payload = load_users()
    user = find_user_by_two_factor_recovery_token(payload, token)

    if not user:
        return {
            "ok": False,
            "errors": ["That two-factor recovery link is invalid or expired. Request a new recovery email."],
        }

    if not check_password_hash(str(user.get("password_hash") or ""), password):
        return {"ok": False, "errors": ["Enter the current password for this account to recover two-factor access."]}

    user.pop("two_factor", None)
    user.pop("two_factor_setup", None)
    user.pop("two_factor_recovery", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    session.pop("user_id", None)
    session.pop("pending_2fa_user_id", None)
    return {"ok": True, "user": public_user(user)}


def find_user_by_two_factor_recovery_token(payload, token):
    for user in payload.get("users", []):
        recovery = user.get("two_factor_recovery") if isinstance(user, dict) else None

        if not isinstance(recovery, dict):
            continue

        expires_at = parse_iso_datetime(recovery.get("expires_at"))
        if not expires_at or expires_at < datetime.utcnow():
            continue

        token_hash = str(recovery.get("token_hash") or "")
        if token_hash and check_password_hash(token_hash, token):
            return user

    return None


def two_factor_enabled(user):
    two_factor = user.get("two_factor") if isinstance(user, dict) else None
    return isinstance(two_factor, dict) and bool(two_factor.get("enabled"))


def pending_two_factor_setup(user_id):
    user = find_user_by_id(user_id)
    setup = user.get("two_factor_setup") if isinstance(user, dict) else None

    if not isinstance(setup, dict) or not setup.get("secret"):
        return None

    otpauth_uri = totp_uri(setup.get("secret", ""), user.get("username") or user.get("email"), ISSUER_NAME)

    return {
        "secret": setup.get("secret", ""),
        "otpauth_uri": otpauth_uri,
        "qr_data_uri": totp_qr_data_uri(otpauth_uri),
        "issuer": ISSUER_NAME,
        "account_name": user.get("username") or user.get("email") or "account",
    }


def start_two_factor_setup(user_id):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before setting up two-factor authentication."]}

    if two_factor_enabled(user):
        return {"ok": False, "errors": ["Two-factor authentication is already enabled."]}

    secret = generate_totp_secret()
    user["two_factor_setup"] = {
        "secret": secret,
        "created_at": now_iso(),
    }
    user["updated_at"] = now_iso()
    save_users(payload)

    return {
        "ok": True,
        "setup": pending_two_factor_setup(user_id),
    }


def enable_two_factor(user_id, code):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)
    setup = user.get("two_factor_setup") if isinstance(user, dict) else None

    if not user:
        return {"ok": False, "errors": ["Sign in again before enabling two-factor authentication."]}

    if two_factor_enabled(user):
        return {"ok": False, "errors": ["Two-factor authentication is already enabled."]}

    if not isinstance(setup, dict) or not setup.get("secret"):
        return {"ok": False, "errors": ["Start two-factor setup before entering a verification code."]}

    if not verify_totp_code(setup["secret"], code):
        return {"ok": False, "errors": ["That authenticator code did not match. Try the current 6-digit code."]}

    backup_codes = generate_backup_codes()
    user["two_factor"] = {
        "enabled": True,
        "secret": setup["secret"],
        "enabled_at": now_iso(),
        "backup_codes": hash_backup_codes(backup_codes),
        "trusted_devices": [],
    }
    user.pop("two_factor_setup", None)
    user["updated_at"] = now_iso()
    save_users(payload)

    return {"ok": True, "backup_codes": backup_codes, "user": public_user(user)}


def cancel_two_factor_setup(user_id):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before changing two-factor authentication."]}

    user.pop("two_factor_setup", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True}


def complete_two_factor_sign_in(code, remember_device=False):
    user_id = session.get("pending_2fa_user_id")

    if not user_id:
        return {"ok": False, "errors": ["Sign in with your password before entering a two-factor code."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user or not two_factor_enabled(user):
        session.pop("pending_2fa_user_id", None)
        return {"ok": False, "errors": ["Two-factor verification is no longer available. Sign in again."]}

    verified = verify_user_two_factor_code(user, code)

    if not verified:
        save_users(payload)
        return {"ok": False, "errors": ["That two-factor code did not match."]}

    trust_token = ""
    if remember_device:
        trust_token = add_trusted_two_factor_device(user)

    user["updated_at"] = now_iso()
    save_users(payload)
    session["user_id"] = user["user_id"]
    session.pop("pending_2fa_user_id", None)
    return {"ok": True, "user": public_user(user), "trust_token": trust_token}


def cancel_two_factor_sign_in():
    session.pop("pending_2fa_user_id", None)
    return {"ok": True}


def disable_two_factor(user_id, password, code):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before disabling two-factor authentication."]}

    if not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
        return {"ok": False, "errors": ["Enter your current password to disable two-factor authentication."]}

    if not two_factor_enabled(user):
        user.pop("two_factor_setup", None)
        save_users(payload)
        return {"ok": True, "user": public_user(user)}

    if not verify_user_two_factor_code(user, code):
        save_users(payload)
        return {"ok": False, "errors": ["Enter a valid authenticator or backup code to disable two-factor authentication."]}

    user.pop("two_factor", None)
    user.pop("two_factor_setup", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True, "user": public_user(user)}


def regenerate_two_factor_backup_codes(user_id, password, code):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before regenerating backup codes."]}

    if not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
        return {"ok": False, "errors": ["Enter your current password to regenerate backup codes."]}

    if not two_factor_enabled(user):
        return {"ok": False, "errors": ["Enable two-factor authentication before generating backup codes."]}

    if not verify_user_two_factor_code(user, code):
        save_users(payload)
        return {"ok": False, "errors": ["Enter a valid authenticator or backup code to regenerate backup codes."]}

    backup_codes = generate_backup_codes()
    user["two_factor"]["backup_codes"] = hash_backup_codes(backup_codes)
    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True, "backup_codes": backup_codes, "user": public_user(user)}


def verify_user_two_factor_code(user, code):
    two_factor = user.get("two_factor") if isinstance(user, dict) else None

    if not isinstance(two_factor, dict) or not two_factor.get("enabled"):
        return False

    if verify_totp_code(two_factor.get("secret", ""), code):
        return True

    return verify_backup_code(two_factor, code, now_iso())


def add_trusted_two_factor_device(user):
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.utcnow().replace(microsecond=0)
        + timedelta(days=TWO_FACTOR_TRUST_DAYS)
    ).isoformat() + "Z"

    two_factor = user.setdefault("two_factor", {})
    devices = purge_expired_trusted_devices(two_factor.get("trusted_devices", []))
    devices.append({
        "token_hash": generate_password_hash(token),
        "created_at": now_iso(),
        "expires_at": expires_at,
    })
    two_factor["trusted_devices"] = devices[-10:]
    return f"{user.get('user_id', '')}:{token}"


def verify_trusted_two_factor_device(user, trusted_device_token):
    if not trusted_device_token or not two_factor_enabled(user):
        return False

    user_id, sep, token = str(trusted_device_token or "").partition(":")

    if sep != ":" or user_id != str(user.get("user_id") or "") or not token:
        return False

    two_factor = user.get("two_factor", {})
    devices = purge_expired_trusted_devices(two_factor.get("trusted_devices", []))
    changed = len(devices) != len(two_factor.get("trusted_devices", []))
    matched = False

    for device in devices:
        token_hash = str(device.get("token_hash") or "")
        if token_hash and check_password_hash(token_hash, token):
            matched = True
            break

    if changed:
        payload = load_users()
        stored_user = find_user_by_id_in_payload(payload, user.get("user_id"))
        if stored_user and two_factor_enabled(stored_user):
            stored_user["two_factor"]["trusted_devices"] = devices
            save_users(payload)

    return matched


def purge_expired_trusted_devices(devices):
    now = datetime.utcnow()
    kept = []

    for device in devices if isinstance(devices, list) else []:
        expires_at = parse_iso_datetime(device.get("expires_at"))
        if expires_at and expires_at >= now:
            kept.append(device)

    return kept


def find_user_by_id_in_payload(payload, user_id):
    user_id = str(user_id or "")
    return next(
        (user for user in payload.get("users", []) if str(user.get("user_id")) == user_id),
        None,
    )


def sign_out_user():
    session.pop("user_id", None)
    session.pop("pending_2fa_user_id", None)
    session.pop("two_factor_recovery_link", None)


def update_user_profile(user_id, username, email, password="", confirm_password="", avatar_file=None, phone=""):
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
        phone=phone,
    )
    username = str(username or "").strip()
    email = str(email or "").strip()
    phone = normalize_phone_for_storage(phone)
    phone_keys = phone_lookup_candidates(phone)

    for existing in payload["users"]:
        if existing.get("user_id") == user_id:
            continue
        if normalize_identity(existing.get("username")) == normalize_identity(username):
            errors.append("That username is already in use.")
        if normalize_identity(existing.get("email")) == normalize_identity(email):
            errors.append("That email is already in use.")
        if phone_keys and phone_lookup_candidates(existing.get("phone")) & phone_keys:
            errors.append("That phone number is already in use.")

    if errors:
        return {"ok": False, "errors": errors}

    avatar_result = save_avatar_upload(avatar_file, user_id)
    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["username"] = username
    user["email"] = email
    user["phone"] = phone
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
