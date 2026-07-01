import json
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import requests
from flask import has_request_context
from flask import session
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from PushShoppingList.services.firebase_auth_service import delete_firebase_auth_user
from PushShoppingList.services.two_factor_service import ISSUER_NAME
from PushShoppingList.services.two_factor_service import backup_codes_remaining
from PushShoppingList.services.two_factor_service import generate_backup_codes
from PushShoppingList.services.two_factor_service import generate_totp_secret
from PushShoppingList.services.two_factor_service import hash_backup_codes
from PushShoppingList.services.two_factor_service import totp_qr_data_uri
from PushShoppingList.services.two_factor_service import totp_uri
from PushShoppingList.services.two_factor_service import verify_backup_code
from PushShoppingList.services.two_factor_service import verify_totp_code
from PushShoppingList.services.storage_service import USER_DATA_DIR
from PushShoppingList.services.storage_service import safe_user_id
from PushShoppingList.services.user_workspace_seed_service import seed_new_user_rule_workspace


PACKAGE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = Path(os.getenv("SHOPPING_APP_USERS_FILE", PACKAGE_DIR / "users.json"))
AVATAR_UPLOAD_DIR = Path(os.getenv("SHOPPING_APP_AVATAR_UPLOAD_DIR", PACKAGE_DIR / "static" / "uploads" / "avatars"))
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGITS_PATTERN = re.compile(r"\d+")


def configured_email(name, default):
    return str(os.getenv(name, default) or default).strip().lower()


def configured_email_tuple(name, default):
    raw_value = str(os.getenv(name, default) or default)
    return tuple(
        email.strip().lower()
        for email in re.split(r"[,;]", raw_value)
        if email.strip()
    )


ADMIN_EMAIL = configured_email("SHOPPING_APP_ADMIN_EMAIL", "admin@example.com")
SUPPORT_EMAIL = str(
    os.getenv("SHOPPING_APP_SUPPORT_EMAIL", "support@recipeshoppinglist.com")
    or "support@recipeshoppinglist.com"
).strip()
SUPPORT_ADMIN_EMAILS = configured_email_tuple("SHOPPING_APP_SUPPORT_ADMIN_EMAILS", ADMIN_EMAIL)
PASSWORD_RESET_TTL_HOURS = 1
ACCOUNT_DELETE_TTL_HOURS = 1
ACCOUNT_VERIFICATION_TTL_HOURS = 24
PHONE_VERIFICATION_TTL_MINUTES = 10
TWO_FACTOR_TRUST_DAYS = 30
TWO_FACTOR_RECOVERY_TTL_MINUTES = 30
NTFY_TOPIC_PREFIX = os.getenv("SHOPPING_APP_NTFY_TOPIC_PREFIX", "shopping-user").strip() or "shopping-user"
WEB_PUSH_PUBLIC_KEY = os.getenv("SHOPPING_APP_WEB_PUSH_PUBLIC_KEY", os.getenv("VAPID_PUBLIC_KEY", "")).strip()
NOTIFICATION_PREFERENCE_OPTIONS = (
    ("recipe_import_complete", "Recipe Import Complete"),
    ("recipe_pdf_generated", "Recipe PDF Generated"),
    ("cloudflare_upload_complete", "Cloudflare Upload Complete"),
    ("store_search_complete", "Store Search Complete"),
    ("shopping_list_updated", "Shopping List Updated"),
    ("feedback_response", "Feedback Response"),
    ("security_alerts", "Security Alerts"),
)
DEFAULT_NOTIFICATION_PREFERENCES = {
    key: True
    for key, _label in NOTIFICATION_PREFERENCE_OPTIONS
}
SUPPORTED_NOTIFICATION_DEVICES = (
    {"key": "browser", "name": "Browser"},
    {"key": "iphone", "name": "iPhone"},
    {"key": "android", "name": "Android"},
)


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None


def display_datetime(value):
    parsed = parse_iso_datetime(value)

    if not parsed:
        return ""

    return parsed.strftime("%b %-d, %Y %-I:%M %p UTC") if os.name != "nt" else parsed.strftime("%b %#d, %Y %#I:%M %p UTC")


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


def notification_topic(user):
    if not isinstance(user, dict):
        return ""

    return normalize_ntfy_topic(user.get("notification_topic") or user.get("ntfy_topic"))


def ensure_user_notification_topic_fields(user):
    if not isinstance(user, dict):
        return ""

    topic = notification_topic(user) or generate_ntfy_topic()
    user["notification_topic"] = topic
    user["ntfy_topic"] = topic
    user["ntfy_topic_created_at"] = user.get("ntfy_topic_created_at") or now_iso()
    user["notification_topic_created_at"] = user.get("notification_topic_created_at") or user["ntfy_topic_created_at"]
    return topic


def ntfy_subscription_url(topic):
    topic = normalize_ntfy_topic(topic)

    if not topic:
        return ""

    return f"https://ntfy.sh/{topic}"


def ntfy_deep_link(topic):
    topic = normalize_ntfy_topic(topic)

    if not topic:
        return ""

    return f"ntfy://subscribe/{topic}"


def normalize_notification_preferences(preferences):
    normalized = DEFAULT_NOTIFICATION_PREFERENCES.copy()

    if isinstance(preferences, dict):
        for key in normalized:
            if key in preferences:
                normalized[key] = bool(preferences.get(key))

    return normalized


def normalize_notification_device_key(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")

    aliases = {
        "windows_pc": "browser",
        "desktop": "browser",
        "chrome": "browser",
        "edge": "browser",
        "phone": "iphone",
        "ios": "iphone",
    }
    return aliases.get(value, value)


def normalize_notification_device_status(status):
    status = str(status or "").strip().lower()

    if status in {"connected", "registered", "subscribed", "enabled"}:
        return "Connected"

    if status in {"pending", "requested", "opened", "waiting"}:
        return "Pending"

    return "Not Connected"


def normalize_notification_devices(devices):
    normalized = []
    seen = set()

    for device in devices if isinstance(devices, list) else []:
        if isinstance(device, str):
            name = device.strip()
            if name:
                key = normalize_notification_device_key(name)
                normalized.append({"key": key, "name": name, "status": "Connected"})
                seen.add(key)
            continue

        if not isinstance(device, dict):
            continue

        name = str(device.get("name") or "").strip()
        if not name:
            continue

        key = normalize_notification_device_key(device.get("key") or name)
        if key in seen:
            continue

        normalized.append({
            "key": key,
            "name": name,
            "status": normalize_notification_device_status(device.get("status")),
            "last_seen_at": str(device.get("last_seen_at") or "").strip(),
            "last_seen_at_label": display_datetime(device.get("last_seen_at")),
        })
        seen.add(key)

    return normalized


def upsert_notification_device(user, key, name, status, timestamp=None):
    if not isinstance(user, dict):
        return

    key = normalize_notification_device_key(key)
    status = normalize_notification_device_status(status)
    timestamp = timestamp or now_iso()
    devices = normalize_notification_devices(user.get("notification_devices"))

    for device in devices:
        if normalize_notification_device_key(device.get("key") or device.get("name")) == key:
            device["name"] = name or device.get("name") or key.title()
            device["status"] = status
            device["last_seen_at"] = timestamp
            device["last_seen_at_label"] = display_datetime(timestamp)
            user["notification_devices"] = devices
            return

    devices.append({
        "key": key,
        "name": name or key.title(),
        "status": status,
        "last_seen_at": timestamp,
        "last_seen_at_label": display_datetime(timestamp),
    })
    user["notification_devices"] = devices


def notification_device_statuses(user):
    devices = {
        normalize_notification_device_key(device.get("key") or device.get("name")): device
        for device in normalize_notification_devices((user or {}).get("notification_devices"))
    }
    enabled = notifications_enabled(user)
    browser_subscription = (user or {}).get("browser_push_subscription")
    browser_connected = isinstance(browser_subscription, dict) and bool(browser_subscription.get("endpoint"))
    permission = str((user or {}).get("browser_notification_permission") or "").strip().lower()
    result = []

    for supported in SUPPORTED_NOTIFICATION_DEVICES:
        key = supported["key"]
        name = supported["name"]
        stored = devices.get(key, {})
        status = normalize_notification_device_status(stored.get("status"))

        if not enabled:
            status = "Not Connected"
        elif key == "browser":
            if browser_connected:
                status = "Connected"
            elif permission == "denied":
                status = "Not Connected"
            else:
                status = status if stored else "Pending"
        else:
            status = status if stored else "Pending"

        result.append({
            "key": key,
            "name": name,
            "status": status,
            "status_class": status.lower().replace(" ", "-"),
            "last_seen_at": str(stored.get("last_seen_at") or "").strip(),
            "last_seen_at_label": display_datetime(stored.get("last_seen_at")),
        })

    return result


def notifications_enabled(user):
    if not isinstance(user, dict):
        return False

    value = user.get("notifications_enabled")

    if isinstance(value, bool):
        return value

    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off", "disabled"}:
        return False

    return bool(notification_topic(user))


def notification_preference_enabled(user, preference_key=""):
    if not notifications_enabled(user):
        return False

    preference_key = str(preference_key or "").strip()

    if not preference_key:
        return True

    preferences = normalize_notification_preferences(
        (user or {}).get("notification_preferences")
    )
    return bool(preferences.get(preference_key, True))


def ensure_user_ntfy_topic(user_id):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return None

    topic = notification_topic(user)

    if not topic or topic != str(user.get("notification_topic") or "") or topic != str(user.get("ntfy_topic") or ""):
        ensure_user_notification_topic_fields(user)
        user["updated_at"] = now_iso()
        save_users(payload)

    return user


def public_user(user):
    if not isinstance(user, dict):
        return None
    two_factor = user.get("two_factor") if isinstance(user.get("two_factor"), dict) else {}
    ntfy_topic = notification_topic(user)
    is_firebase = str(user.get("auth_provider") or "").strip().lower() == "firebase"
    email_verified = bool(user.get("firebase_email_verified")) if is_firebase else account_email_verified(user)
    last_sign_in_at = user.get("firebase_last_login_at") or user.get("last_login_at") or ""
    notification_preferences = normalize_notification_preferences(user.get("notification_preferences"))

    return {
        "user_id": user.get("user_id", ""),
        "first_name": user.get("first_name", ""),
        "last_name": user.get("last_name", ""),
        "display_name": user_display_name(user),
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "auth_provider": user.get("auth_provider", "local"),
        "provider": provider_label(user),
        "provider_label": provider_label(user),
        "firebase_uid": user.get("firebase_uid", ""),
        "picture": user.get("picture", ""),
        "email_verified_at": user.get("email_verified_at", ""),
        "email_verified": email_verified,
        "email_verified_label": "Email verified" if email_verified else "Email not verified",
        "account_status": account_status(user),
        "phone": user.get("phone", ""),
        "phone_verified_at": user.get("phone_verified_at", ""),
        "phone_verified": bool(user.get("phone") and user.get("phone_verified_at")),
        "notification_topic": ntfy_topic,
        "ntfy_topic": ntfy_topic,
        "ntfy_url": ntfy_subscription_url(ntfy_topic),
        "ntfy_deep_link": ntfy_deep_link(ntfy_topic),
        "notifications_enabled": notifications_enabled(user),
        "notification_preferences": notification_preferences,
        "notification_preference_options": [
            {
                "key": key,
                "label": label,
                "enabled": bool(notification_preferences.get(key, True)),
            }
            for key, label in NOTIFICATION_PREFERENCE_OPTIONS
        ],
        "notification_devices": notification_device_statuses(user),
        "supported_notification_devices": list(SUPPORTED_NOTIFICATION_DEVICES),
        "browser_push_connected": bool(
            isinstance(user.get("browser_push_subscription"), dict)
            and user.get("browser_push_subscription", {}).get("endpoint")
        ),
        "web_push_public_key": WEB_PUSH_PUBLIC_KEY,
        "last_notification_sent": user.get("last_notification_sent", ""),
        "last_notification_sent_label": display_datetime(user.get("last_notification_sent")),
        "last_notification_received": user.get("last_notification_received", ""),
        "last_notification_received_label": display_datetime(user.get("last_notification_received")),
        "last_test_notification": user.get("last_test_notification", ""),
        "last_test_notification_label": display_datetime(user.get("last_test_notification")),
        "avatar_path": user.get("avatar_path", ""),
        "created_at": user.get("created_at", ""),
        "created_at_label": display_datetime(user.get("created_at")),
        "last_sign_in_at": last_sign_in_at,
        "last_sign_in_at_label": display_datetime(last_sign_in_at),
        "updated_at": user.get("updated_at", ""),
        "is_admin": is_admin_user(user),
        "role": "Admin" if is_admin_user(user) else "User",
        "two_factor_enabled": bool(two_factor.get("enabled")),
        "two_factor_backup_codes_remaining": backup_codes_remaining(two_factor) if two_factor.get("enabled") else 0,
    }


def normalize_email_key(email):
    return str(email or "").strip().lower()


def is_support_admin_email(email):
    return normalize_email_key(email) in SUPPORT_ADMIN_EMAILS


def get_public_support_identity(email):
    email = str(email or "").strip()

    if is_support_admin_email(email):
        return SUPPORT_EMAIL

    return email


def is_admin_email(email):
    email_key = normalize_email_key(email)
    return email_key == normalize_email_key(ADMIN_EMAIL) or email_key in SUPPORT_ADMIN_EMAILS


def is_admin_user(user):
    return is_admin_email((user or {}).get("email"))


def provider_label(user):
    provider = str((user or {}).get("auth_provider") or "local").strip().lower()

    if provider == "firebase":
        return "Firebase Authentication"

    return "Local Account"


def firebase_provider_ids(firebase_user, sign_in_provider=""):
    providers = set()
    sign_in_provider = str(sign_in_provider or "").strip()

    if sign_in_provider:
        providers.add(sign_in_provider)

    provider_info = firebase_user.get("providerUserInfo", [])
    if isinstance(provider_info, list):
        for provider in provider_info:
            if isinstance(provider, dict) and str(provider.get("providerId") or "").strip():
                providers.add(str(provider.get("providerId")).strip())

    firebase_claims = firebase_user.get("firebase")
    identities = firebase_claims.get("identities") if isinstance(firebase_claims, dict) else {}
    if isinstance(identities, dict):
        for provider_id in identities.keys():
            if str(provider_id or "").strip():
                providers.add(str(provider_id).strip())

    return sorted(providers)


def user_display_name(user):
    first_name = str((user or {}).get("first_name") or "").strip()
    last_name = str((user or {}).get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    return full_name or str((user or {}).get("username") or (user or {}).get("email") or "").strip()


def account_status(user):
    return str((user or {}).get("account_status") or "active").strip() or "active"


def account_email_verified(user):
    return account_status(user) != "pending_email_verification"


def current_user():
    if not has_request_context():
        return None

    user_id = session.get("user_id")
    if not user_id:
        return None

    user = find_user_by_id(user_id)

    topic = notification_topic(user or {})

    if user and (
        not topic
        or topic != str((user or {}).get("notification_topic") or "")
        or topic != str((user or {}).get("ntfy_topic") or "")
    ):
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


def save_current_user_record(user):
    user_id = str((user or {}).get("user_id") or "").strip()

    if not user_id:
        return False

    payload = load_users()
    stored_user = find_user_by_id_in_payload(payload, user_id)

    if not stored_user:
        return False

    stored_user.update(user)
    save_users(payload)
    return True


def find_user_by_identity(identity):
    return find_user_by_identity_in_payload(load_users(), identity)


def find_user_by_firebase_uid_in_payload(payload, firebase_uid):
    firebase_uid = str(firebase_uid or "").strip()

    if not firebase_uid:
        return None

    return next(
        (
            user
            for user in payload.get("users", [])
            if str(user.get("firebase_uid") or "").strip() == firebase_uid
        ),
        None,
    )


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


def name_parts_from_display_name(display_name):
    parts = str(display_name or "").strip().split()

    if not parts:
        return "", ""

    if len(parts) == 1:
        return parts[0], ""

    return parts[0], " ".join(parts[1:])


def set_signed_in_session(user):
    session.permanent = True
    session["user_id"] = user["user_id"]
    session.pop("is_guest", None)
    session.pop("guest_session_id", None)

    if str((user or {}).get("auth_provider") or "").strip().lower() == "firebase":
        session["firebase_uid"] = user.get("firebase_uid", "")
        session["email"] = user.get("email", "")
        session["display_name"] = user_display_name(user)
        session["picture"] = user.get("picture", "")
        session["provider"] = "Firebase Authentication"

    session["is_admin"] = is_admin_user(user)
    session.pop("pending_2fa_user_id", None)
    session.pop("pending_2fa_provider", None)
    session.pop("pending_2fa_context", None)


def sign_in_firebase_user(firebase_user, profile=None, trusted_device_token=""):
    profile = profile if isinstance(profile, dict) else {}
    firebase_claims = firebase_user.get("firebase") if isinstance(firebase_user.get("firebase"), dict) else {}
    sign_in_provider = str(
        firebase_claims.get("sign_in_provider")
        or profile.get("provider")
        or profile.get("provider_id")
        or ""
    ).strip()
    firebase_uid = str(firebase_user.get("uid") or firebase_user.get("localId") or "").strip()
    email = str(firebase_user.get("email") or profile.get("email") or "").strip()
    display_name = str(
        firebase_user.get("name")
        or firebase_user.get("displayName")
        or profile.get("display_name")
        or profile.get("displayName")
        or ""
    ).strip()
    picture = str(
        firebase_user.get("picture")
        or firebase_user.get("photoUrl")
        or profile.get("picture")
        or profile.get("photoURL")
        or ""
    ).strip()
    first_name = str(profile.get("first_name") or "").strip()
    last_name = str(profile.get("last_name") or "").strip()
    username = str(profile.get("username") or email or display_name or firebase_uid).strip()

    if not firebase_uid:
        return {"ok": False, "errors": ["Firebase user id is missing."]}

    if not first_name and not last_name:
        first_name, last_name = name_parts_from_display_name(display_name)

    payload = load_users()
    user = find_user_by_firebase_uid_in_payload(payload, firebase_uid)

    if not user and email:
        user = find_user_by_identity_in_payload(payload, email)

    timestamp = now_iso()
    created = False

    if not user:
        user_id = uuid.uuid4().hex
        user = {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "email": email,
            "auth_provider": "firebase",
            "firebase_uid": firebase_uid,
            "picture": picture,
            "account_status": "active",
            "email_verified_at": timestamp,
            "phone": "",
            "notification_topic": generate_ntfy_topic(),
            "ntfy_topic": "",
            "ntfy_topic_created_at": timestamp,
            "notifications_enabled": True,
            "notification_preferences": DEFAULT_NOTIFICATION_PREFERENCES.copy(),
            "notification_devices": [],
            "browser_push_subscription": {},
            "browser_notification_permission": "",
            "last_notification_sent": "",
            "last_notification_received": "",
            "last_test_notification": "",
            "password_hash": "",
            "avatar_path": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        user["ntfy_topic"] = user["notification_topic"]
        user["notification_topic_created_at"] = timestamp
        seed_result = seed_new_user_rule_workspace(user_id)
        if not seed_result.get("ok"):
            return {"ok": False, "errors": seed_result.get("errors", ["Unable to initialize account rules."])}
        payload["users"].append(user)
        created = True
    else:
        if first_name:
            user["first_name"] = first_name
        if last_name:
            user["last_name"] = last_name
        if email:
            user["email"] = email
        if username:
            user["username"] = username
        user["auth_provider"] = "firebase"
        user["firebase_uid"] = firebase_uid
        if picture:
            user["picture"] = picture
        user["account_status"] = "active"
        user["email_verified_at"] = user.get("email_verified_at") or timestamp
        user.pop("account_verification", None)

    provider_ids = firebase_provider_ids(firebase_user, sign_in_provider)
    user["firebase_provider_ids"] = provider_ids
    user["firebase_sign_in_provider"] = sign_in_provider
    user["firebase_email_verified"] = bool(firebase_user.get("email_verified") or firebase_user.get("emailVerified"))
    if user["firebase_email_verified"]:
        user["email_verified_at"] = user.get("email_verified_at") or timestamp
    user["firebase_last_login_at"] = timestamp
    user["updated_at"] = timestamp
    save_users(payload)

    session.pop("account_verification_link", None)

    if signed_in_as_same_firebase_user(user, firebase_uid):
        set_signed_in_session(user)
        return {"ok": True, "created": created, "user": public_user(user)}

    if two_factor_enabled(user) and not verify_trusted_two_factor_device(user, trusted_device_token):
        session.permanent = True
        session.pop("user_id", None)
        session["pending_2fa_user_id"] = user["user_id"]
        session["pending_2fa_provider"] = "firebase"
        if two_factor_setup_confirmation_pending(user):
            session["pending_2fa_context"] = "setup_confirmation"
        else:
            session.pop("pending_2fa_context", None)
        return {"ok": True, "created": created, "requires_2fa": True, "user": public_user(user)}

    set_signed_in_session(user)
    return {"ok": True, "created": created, "user": public_user(user)}


def signed_in_as_same_firebase_user(user, firebase_uid):
    if not has_request_context():
        return False

    session_user_id = str(session.get("user_id") or "")
    session_firebase_uid = str(session.get("firebase_uid") or "")

    if not session_user_id or session_user_id != str((user or {}).get("user_id") or ""):
        return False

    return not session_firebase_uid or session_firebase_uid == str(firebase_uid or "")


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


def create_user(
    username,
    email,
    password,
    confirm_password,
    avatar_file=None,
    phone="",
    first_name="",
    last_name="",
):
    errors = validate_account_fields(username, email, password, confirm_password, require_password=True, phone=phone)
    first_name = str(first_name or "").strip()
    last_name = str(last_name or "").strip()
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
    verification_token = secrets.token_urlsafe(32)
    user = {
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "email": email,
        "account_status": "pending_email_verification",
        "account_verification": {
            "token_hash": generate_password_hash(verification_token),
            "created_at": timestamp,
            "expires_at": (
                datetime.utcnow().replace(microsecond=0)
                + timedelta(hours=ACCOUNT_VERIFICATION_TTL_HOURS)
            ).isoformat() + "Z",
        },
        "phone": phone,
        "notification_topic": generate_ntfy_topic(),
        "ntfy_topic": "",
        "ntfy_topic_created_at": timestamp,
        "notifications_enabled": True,
        "notification_preferences": DEFAULT_NOTIFICATION_PREFERENCES.copy(),
        "notification_devices": [],
        "browser_push_subscription": {},
        "browser_notification_permission": "",
        "last_notification_sent": "",
        "last_notification_received": "",
        "last_test_notification": "",
        "password_hash": generate_password_hash(password),
        "avatar_path": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    user["ntfy_topic"] = user["notification_topic"]
    user["notification_topic_created_at"] = timestamp
    avatar_result = save_avatar_upload(avatar_file, user_id)

    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["avatar_path"] = avatar_result.get("avatar_path", "")
    payload["users"].append(user)
    save_users(payload)
    return {"ok": True, "token": verification_token, "user": public_user(user)}


def authenticate_user(identity, password, trusted_device_token=""):
    identity = str(identity or "").strip()
    password = str(password or "")

    if not identity or not password:
        return {"ok": False, "errors": ["Enter your username or email and password."]}

    user = find_user_by_identity(identity)
    if not user or not check_password_hash(str(user.get("password_hash") or ""), password):
        return {"ok": False, "errors": ["We could not sign you in with those details."]}

    if not account_email_verified(user):
        return {"ok": False, "errors": ["Check your email and verify this account before signing in."]}

    if two_factor_enabled(user):
        if verify_trusted_two_factor_device(user, trusted_device_token):
            user["last_login_at"] = now_iso()
            save_current_user_record(user)
            session.permanent = True
            session["user_id"] = user["user_id"]
            session.pop("pending_2fa_user_id", None)
            session.pop("pending_2fa_context", None)
            return {"ok": True, "user": public_user(user)}

        session.pop("user_id", None)
        session["pending_2fa_user_id"] = user["user_id"]
        if two_factor_setup_confirmation_pending(user):
            session["pending_2fa_context"] = "setup_confirmation"
        else:
            session.pop("pending_2fa_context", None)
        return {"ok": True, "requires_2fa": True, "user": public_user(user)}

    user["last_login_at"] = now_iso()
    save_current_user_record(user)
    session.permanent = True
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

    if not account_email_verified(user):
        return {"ok": True, "sent": False}

    if delivery_method == "phone" and not user.get("phone_verified_at"):
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


def verify_account_creation(token):
    token = str(token or "").strip()

    if not token:
        return {"ok": False, "errors": ["Account verification link is missing. Request a new account."]}

    payload = load_users()
    user = find_user_by_account_verification_token(payload, token)

    if not user:
        return {
            "ok": False,
            "errors": ["That account verification link is invalid or expired. Create the account again."],
        }

    seed_result = seed_new_user_rule_workspace(user.get("user_id"))
    if not seed_result.get("ok"):
        return {"ok": False, "errors": seed_result.get("errors", ["Unable to initialize account rules."])}

    timestamp = now_iso()
    user["account_status"] = "active"
    user["email_verified_at"] = timestamp
    user.pop("account_verification", None)
    user["updated_at"] = timestamp
    save_users(payload)
    session.permanent = True
    session["user_id"] = user["user_id"]
    session.pop("pending_2fa_user_id", None)
    return {"ok": True, "user": public_user(user)}


def discard_pending_account(user_id):
    user_id = str(user_id or "").strip()

    if not user_id:
        return {"ok": False}

    payload = load_users()
    kept_users = []
    discarded_user = None

    for user in payload.get("users", []):
        if str(user.get("user_id") or "") == user_id and account_status(user) == "pending_email_verification":
            discarded_user = user
            continue
        kept_users.append(user)

    if not discarded_user:
        return {"ok": False}

    payload["users"] = kept_users
    save_users(payload)

    avatar_path = str(discarded_user.get("avatar_path") or "").strip()
    if avatar_path:
        try:
            avatar_file = (PACKAGE_DIR / "static" / avatar_path).resolve()
            avatar_root = AVATAR_UPLOAD_DIR.resolve()
            if avatar_file.is_file() and avatar_root in avatar_file.parents:
                avatar_file.unlink()
        except Exception:
            pass

    return {"ok": True}


def phone_verification_code():
    return f"{secrets.randbelow(1000000):06d}"


def request_phone_verification(user_id):
    user_id = str(user_id or "").strip()

    if not user_id:
        return {"ok": False, "errors": ["Sign in before verifying your phone number."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before verifying your phone number."]}

    if not str(user.get("phone") or "").strip():
        return {"ok": False, "errors": ["Add a phone number before requesting a verification code."]}

    code = phone_verification_code()
    timestamp = now_iso()
    user["phone_verification"] = {
        "code_hash": generate_password_hash(code),
        "phone": user.get("phone", ""),
        "created_at": timestamp,
        "expires_at": (
            datetime.utcnow().replace(microsecond=0)
            + timedelta(minutes=PHONE_VERIFICATION_TTL_MINUTES)
        ).isoformat() + "Z",
    }
    user["updated_at"] = timestamp
    save_users(payload)
    return {"ok": True, "code": code, "user": public_user(user)}


def verify_phone_code(user_id, code):
    user_id = str(user_id or "").strip()
    code = str(code or "").strip()

    if not user_id:
        return {"ok": False, "errors": ["Sign in before verifying your phone number."]}

    if not code:
        return {"ok": False, "errors": ["Enter the verification code from the text message."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before verifying your phone number."]}

    verification = user.get("phone_verification") if isinstance(user.get("phone_verification"), dict) else None

    if not verification:
        return {"ok": False, "errors": ["Request a new phone verification code first."]}

    expires_at = parse_iso_datetime(verification.get("expires_at"))
    if not expires_at or expires_at < datetime.utcnow():
        user.pop("phone_verification", None)
        save_users(payload)
        return {"ok": False, "errors": ["That phone verification code expired. Request a new code."]}

    if str(verification.get("phone") or "") != str(user.get("phone") or ""):
        user.pop("phone_verification", None)
        save_users(payload)
        return {"ok": False, "errors": ["The phone number changed. Request a new verification code."]}

    code_hash = str(verification.get("code_hash") or "")
    if not code_hash or not check_password_hash(code_hash, code):
        return {"ok": False, "errors": ["That phone verification code did not match."]}

    user["phone_verified_at"] = now_iso()
    user.pop("phone_verification", None)
    user["updated_at"] = now_iso()
    save_users(payload)
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


def find_user_by_account_verification_token(payload, token):
    for user in payload.get("users", []):
        verification = user.get("account_verification") if isinstance(user, dict) else None

        if not isinstance(verification, dict):
            continue

        expires_at = parse_iso_datetime(verification.get("expires_at"))
        if not expires_at or expires_at < datetime.utcnow():
            continue

        token_hash = str(verification.get("token_hash") or "")
        if token_hash and check_password_hash(token_hash, token):
            return user

    return None


def request_account_delete(user_id):
    user_id = str(user_id or "").strip()

    if not user_id:
        return {"ok": False, "errors": ["Sign in before requesting account deletion."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before requesting account deletion."]}

    token = secrets.token_urlsafe(32)
    timestamp = now_iso()
    user["account_delete"] = {
        "token_hash": generate_password_hash(token),
        "created_at": timestamp,
        "expires_at": (
            datetime.utcnow().replace(microsecond=0)
            + timedelta(hours=ACCOUNT_DELETE_TTL_HOURS)
        ).isoformat() + "Z",
    }
    user["updated_at"] = timestamp
    save_users(payload)
    return {"ok": True, "sent": True, "token": token, "user": public_user(user)}


def delete_account_with_token(token):
    token = str(token or "").strip()

    if not token:
        return {"ok": False, "errors": ["Account deletion link is missing. Request a new verification email."]}

    payload = load_users()
    user = find_user_by_account_delete_token(payload, token)

    if not user:
        return {
            "ok": False,
            "errors": ["That account deletion link is invalid or expired. Request a new verification email."],
        }

    user_id = str(user.get("user_id") or "")
    deleted_user = public_user(user)
    firebase_delete_result = delete_firebase_auth_user(user.get("firebase_uid"))
    if not firebase_delete_result.get("ok"):
        print(
            "[account_delete] Firebase Auth user deletion skipped or failed for "
            f"user_id={user_id}: {firebase_delete_result.get('code', 'unknown')}"
        )
    payload["users"] = [
        item
        for item in payload.get("users", [])
        if str(item.get("user_id") or "") != user_id
    ]
    save_users(payload)
    delete_user_avatar(user)
    delete_user_workspace(user_id)
    sign_out_user()
    return {"ok": True, "user": deleted_user}


def find_user_by_account_delete_token(payload, token):
    for user in payload.get("users", []):
        account_delete = user.get("account_delete") if isinstance(user, dict) else None

        if not isinstance(account_delete, dict):
            continue

        expires_at = parse_iso_datetime(account_delete.get("expires_at"))
        if not expires_at or expires_at < datetime.utcnow():
            continue

        token_hash = str(account_delete.get("token_hash") or "")
        if token_hash and check_password_hash(token_hash, token):
            return user

    return None


def delete_user_workspace(user_id):
    user_id = safe_user_id(user_id)

    if not user_id:
        return False

    try:
        base = USER_DATA_DIR.resolve()
        target = (USER_DATA_DIR / user_id).resolve()

        if target == base or base not in target.parents or not target.exists():
            return False

        shutil.rmtree(target)
        return True
    except Exception:
        return False


def delete_user_avatar(user):
    avatar_path = str((user or {}).get("avatar_path") or "").strip()

    if not avatar_path:
        return False

    try:
        avatar_file = (AVATAR_UPLOAD_DIR / Path(avatar_path).name).resolve()
        upload_dir = AVATAR_UPLOAD_DIR.resolve()

        if upload_dir not in avatar_file.parents or not avatar_file.exists():
            return False

        avatar_file.unlink()
        return True
    except Exception:
        return False


def request_two_factor_recovery(user_id):
    """Create an email token to verify disabling two-factor authentication."""
    user_id = str(user_id or "").strip()

    if not user_id:
        return {"ok": False, "errors": ["Sign in before requesting a two-factor disable verification link."]}

    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in before requesting a two-factor disable verification link."]}

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
        errors.append("Two-factor disable verification link is missing. Request a new verification email.")

    if errors:
        return {"ok": False, "errors": errors}

    payload = load_users()
    user = find_user_by_two_factor_recovery_token(payload, token)

    if not user:
        return {
            "ok": False,
            "errors": ["That two-factor disable verification link is invalid or expired. Request a new verification email."],
        }

    requires_local_password = str(user.get("auth_provider") or "local").strip().lower() != "firebase"
    if requires_local_password and not password:
        return {"ok": False, "errors": ["Current password is required to disable two-factor authentication."]}

    if requires_local_password and not check_password_hash(str(user.get("password_hash") or ""), password):
        return {"ok": False, "errors": ["Enter the current password for this account to disable two-factor authentication."]}

    user.pop("two_factor", None)
    user.pop("two_factor_setup", None)
    user.pop("two_factor_recovery", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    sign_out_user()
    return {"ok": True, "user": public_user(user)}


def admin_disable_two_factor_for_identity(identity, allow_non_admin=False, reason="", actor="local_admin_script"):
    """Disable two-factor authentication from a local admin-only recovery path."""
    identity = str(identity or "").strip()

    if not identity:
        return {"ok": False, "errors": ["Enter the account email or username to unlock."]}

    payload = load_users()
    user = find_user_by_identity_in_payload(payload, identity)

    if not user:
        return {"ok": False, "errors": [f"No account was found for {identity}."]}

    if not is_admin_user(user) and not allow_non_admin:
        return {
            "ok": False,
            "errors": [
                (
                    "Refusing to disable two-factor authentication for a non-admin account. "
                    "Pass --allow-non-admin only when you intentionally want to unlock that user."
                )
            ],
            "user": public_user(user),
        }

    had_two_factor_state = any(
        key in user
        for key in ("two_factor", "two_factor_setup", "two_factor_recovery")
    )

    if not had_two_factor_state:
        return {"ok": True, "changed": False, "user": public_user(user)}

    timestamp = now_iso()
    user.pop("two_factor", None)
    user.pop("two_factor_setup", None)
    user.pop("two_factor_recovery", None)
    user["two_factor_disabled_by_admin_at"] = timestamp
    user["two_factor_disabled_by_admin_actor"] = str(actor or "local_admin_script").strip() or "local_admin_script"
    user["two_factor_disabled_by_admin_reason"] = str(reason or "").strip()
    user["updated_at"] = timestamp
    save_users(payload)
    return {"ok": True, "changed": True, "user": public_user(user)}


def public_two_factor_recovery_user(token):
    token = str(token or "").strip()

    if not token:
        return None

    return public_user(find_user_by_two_factor_recovery_token(load_users(), token))


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


def two_factor_setup_confirmation_pending(user):
    two_factor = user.get("two_factor") if isinstance(user, dict) else None
    return (
        isinstance(two_factor, dict)
        and bool(two_factor.get("enabled"))
        and bool(two_factor.get("setup_confirmation_required"))
    )


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
        "setup_confirmation_required": True,
        "setup_confirmed_at": "",
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
        session.pop("pending_2fa_context", None)
        return {"ok": False, "errors": ["Two-factor verification is no longer available. Sign in again."]}

    verified = verify_user_two_factor_code(user, code)

    if not verified:
        save_users(payload)
        return {"ok": False, "errors": ["That two-factor code did not match."]}

    trust_token = ""
    if remember_device:
        trust_token = add_trusted_two_factor_device(user)

    timestamp = now_iso()
    two_factor = user.get("two_factor") if isinstance(user.get("two_factor"), dict) else {}
    if isinstance(two_factor, dict) and two_factor.get("setup_confirmation_required"):
        two_factor["setup_confirmation_required"] = False
        two_factor["setup_confirmed_at"] = timestamp
    user["last_login_at"] = timestamp
    user["updated_at"] = timestamp
    save_users(payload)
    set_signed_in_session(user)
    return {"ok": True, "user": public_user(user), "trust_token": trust_token}


def cancel_two_factor_sign_in():
    session.pop("pending_2fa_user_id", None)
    session.pop("pending_2fa_provider", None)
    session.pop("pending_2fa_context", None)
    return {"ok": True}


def disable_two_factor(user_id, password, code):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before disabling two-factor authentication."]}

    requires_local_password = str(user.get("auth_provider") or "local").strip().lower() != "firebase"
    if requires_local_password and not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
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

    requires_local_password = str(user.get("auth_provider") or "local").strip().lower() != "firebase"
    if requires_local_password and not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
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
    session.pop("is_guest", None)
    session.pop("guest_session_id", None)
    session.pop("firebase_uid", None)
    session.pop("email", None)
    session.pop("display_name", None)
    session.pop("picture", None)
    session.pop("provider", None)
    session.pop("is_admin", None)
    session.pop("pending_2fa_user_id", None)
    session.pop("pending_2fa_provider", None)
    session.pop("pending_2fa_context", None)
    session.pop("two_factor_recovery_link", None)
    session.pop("account_delete_link", None)
    session.pop("account_verification_link", None)
    session.pop("phone_verification_code", None)


def update_user_profile(
    user_id,
    username,
    email,
    password="",
    confirm_password="",
    avatar_file=None,
    phone="",
    first_name="",
    last_name="",
    remove_avatar=False,
):
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
    first_name = str(first_name or "").strip()
    last_name = str(last_name or "").strip()
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

    previous_phone = str(user.get("phone") or "")
    avatar_result = save_avatar_upload(avatar_file, user_id)
    if not avatar_result.get("ok"):
        return {"ok": False, "errors": avatar_result.get("errors", ["Avatar upload failed."])}

    user["first_name"] = first_name
    user["last_name"] = last_name
    user["username"] = username
    user["email"] = email
    user["phone"] = phone
    if password:
        user["password_hash"] = generate_password_hash(password)
    if avatar_result.get("avatar_path"):
        delete_user_avatar(user)
        user["avatar_path"] = avatar_result["avatar_path"]
    elif remove_avatar:
        delete_user_avatar(user)
        user["avatar_path"] = ""
    if phone != previous_phone:
        user.pop("phone_verified_at", None)
        user.pop("phone_verification", None)
    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True, "user": public_user(user)}


def update_notification_settings(
    user_id,
    enabled=None,
    preferences=None,
    browser_subscription=None,
    browser_permission=None,
    device_info=None,
):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before editing notification settings."]}

    if enabled is not None:
        user["notifications_enabled"] = bool(enabled)

        if user["notifications_enabled"]:
            ensure_user_notification_topic_fields(user)

    if isinstance(preferences, dict):
        user["notification_preferences"] = normalize_notification_preferences(preferences)

    timestamp = now_iso()

    if enabled is False:
        for supported in SUPPORTED_NOTIFICATION_DEVICES:
            upsert_notification_device(user, supported["key"], supported["name"], "Not Connected", timestamp)

    if browser_permission is not None:
        user["browser_notification_permission"] = str(browser_permission or "").strip().lower()

    if isinstance(browser_subscription, dict) and browser_subscription.get("endpoint"):
        user["browser_push_subscription"] = browser_subscription
        user["browser_push_subscription_updated_at"] = timestamp
        upsert_notification_device(user, "browser", "Browser", "Connected", timestamp)
    elif user.get("notifications_enabled") and str(browser_permission or "").strip().lower() == "denied":
        upsert_notification_device(user, "browser", "Browser", "Not Connected", timestamp)
    elif user.get("notifications_enabled") and browser_permission is not None:
        upsert_notification_device(user, "browser", "Browser", "Pending", timestamp)

    if isinstance(device_info, dict):
        device_key = normalize_notification_device_key(device_info.get("key") or device_info.get("type"))
        device_name = str(device_info.get("name") or "").strip()
        if device_key:
            upsert_notification_device(
                user,
                device_key,
                device_name or device_key.title(),
                device_info.get("status") or "Pending",
                timestamp,
            )

    user["updated_at"] = now_iso()
    save_users(payload)
    return {"ok": True, "user": public_user(user)}


def start_device_notification_subscription(user_id, device_type):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before connecting notifications."]}

    topic = ensure_user_notification_topic_fields(user)
    user["notifications_enabled"] = True
    device_key = normalize_notification_device_key(device_type)
    device_name = {
        "iphone": "iPhone",
        "android": "Android",
        "browser": "Browser",
    }.get(device_key, "Device")

    if device_key:
        upsert_notification_device(user, device_key, device_name, "Pending", now_iso())

    user["updated_at"] = now_iso()
    save_users(payload)
    return {
        "ok": True,
        "user": public_user(user),
        "topic": topic,
        "deep_link": ntfy_deep_link(topic),
        "history_url": ntfy_subscription_url(topic),
    }


def record_notification_sent(user_id, timestamp=None):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return

    timestamp = timestamp or now_iso()
    user["last_notification_sent"] = timestamp
    user["updated_at"] = timestamp
    save_users(payload)


def send_test_notification(user_id):
    payload = load_users()
    user = find_user_by_id_in_payload(payload, user_id)

    if not user:
        return {"ok": False, "errors": ["Sign in again before testing push notifications."]}

    if not notifications_enabled(user):
        return {"ok": False, "errors": ["Enable push notifications before sending a test notification."]}

    topic = notification_topic(user)

    if not topic:
        topic = ensure_user_notification_topic_fields(user)

    try:
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=b"Test notification from Recipe Shopping List",
            headers={"Title": "Recipe Shopping List"},
            timeout=5,
        )
        response.raise_for_status()
    except Exception:
        return {"ok": False, "errors": ["The test notification could not be sent. Try again in a moment."]}

    timestamp = now_iso()
    user["last_test_notification"] = timestamp
    user["last_notification_sent"] = timestamp
    user["updated_at"] = timestamp
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
