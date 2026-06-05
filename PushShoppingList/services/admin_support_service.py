import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from PushShoppingList.services.email_service import send_admin_support_access_email
from PushShoppingList.services.storage_service import USER_DATA_DIR
from PushShoppingList.services.storage_service import safe_user_id
from PushShoppingList.services.user_account_service import display_datetime
from PushShoppingList.services.user_account_service import get_public_support_identity
from PushShoppingList.services.user_account_service import is_admin_user
from PushShoppingList.services.user_account_service import load_users
from PushShoppingList.services.user_account_service import public_user


PACKAGE_DIR = Path(__file__).resolve().parent.parent
ADMIN_SUPPORT_AUDIT_FILE = Path(
    os.getenv("SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE", PACKAGE_DIR / "admin_support_audit.json")
)
AUDIT_ACTION = "view_account_support_record"


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_audit_entries():
    if not ADMIN_SUPPORT_AUDIT_FILE.exists():
        return []

    try:
        payload = json.loads(ADMIN_SUPPORT_AUDIT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = payload.get("entries", []) if isinstance(payload, dict) else payload

    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("audit_id")
    ]


def save_audit_entries(entries):
    ADMIN_SUPPORT_AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_SUPPORT_AUDIT_FILE.write_text(
        json.dumps({"entries": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def recent_support_audit_entries(limit=20):
    entries = sorted(
        load_audit_entries(),
        key=lambda entry: str(entry.get("timestamp") or ""),
        reverse=True,
    )
    return [audit_entry_for_render(entry) for entry in entries[:limit]]


def support_access_notices_for_user(user, limit=2):
    user_id = str((user or {}).get("user_id") or "").strip()
    email = str((user or {}).get("email") or "").strip().lower()

    if not user_id and not email:
        return []

    notices = []
    for index, entry in enumerate(load_audit_entries()):
        target_user_id = str(entry.get("target_user_id") or "").strip()
        target_email = str(entry.get("target_email") or "").strip().lower()
        if (user_id and target_user_id == user_id) or (email and target_email == email):
            notices.append((index, audit_entry_for_render(entry)))

    sorted_notices = sorted(
        notices,
        key=lambda item: (str(item[1].get("timestamp") or ""), item[0]),
        reverse=True,
    )
    if limit is None:
        return [notice for _index, notice in sorted_notices]

    return [notice for _index, notice in sorted_notices[:limit]]


def audit_entry_for_render(entry):
    actor_uid = str(entry.get("actorUid") or entry.get("admin_user_id") or "")
    actor_private_email = str(
        entry.get("actorPrivateEmail")
        or entry.get("actorEmail")
        or entry.get("admin_email")
        or ""
    )
    actor_public_email = str(
        entry.get("actorPublicEmail")
        or get_public_support_identity(actor_private_email)
    )
    created_at = str(entry.get("createdAt") or entry.get("timestamp") or "")
    target_user_email = str(entry.get("targetUserEmail") or entry.get("target_email") or "")

    return {
        "audit_id": str(entry.get("audit_id") or ""),
        "action": str(entry.get("action") or ""),
        "timestamp": created_at,
        "timestamp_label": display_datetime(created_at) or created_at,
        "createdAt": created_at,
        "actorUid": actor_uid,
        "actorPrivateEmail": actor_private_email,
        "actorPublicEmail": actor_public_email,
        "admin_user_id": actor_uid,
        "admin_email": actor_private_email,
        "admin_public_email": actor_public_email,
        "target_user_id": str(entry.get("target_user_id") or ""),
        "target_email": target_user_email,
        "targetUserEmail": target_user_email,
        "reason": str(entry.get("reason") or ""),
    }


def support_users():
    rows = [
        safe_account_summary(user)
        for user in load_users().get("users", [])
    ]
    rows = [row for row in rows if row.get("user_id")]
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("email") or "").lower(),
            str(row.get("display_name") or "").lower(),
        ),
    )


def find_support_target(target_user_id):
    target_user_id = str(target_user_id or "").strip()

    if not target_user_id:
        return None

    for user in load_users().get("users", []):
        if str(user.get("user_id") or "").strip() == target_user_id:
            return user

    return None


def safe_account_summary(user):
    public = public_user(user) or {}
    return {
        "user_id": str(public.get("user_id") or ""),
        "display_name": str(public.get("display_name") or ""),
        "username": str(public.get("username") or ""),
        "email": str(public.get("email") or ""),
        "auth_provider": str(public.get("auth_provider") or ""),
        "provider_label": str(public.get("provider_label") or public.get("provider") or ""),
        "role": str(public.get("role") or "User"),
        "is_admin": bool(public.get("is_admin")),
        "account_status": str(public.get("account_status") or "active"),
        "email_verified": bool(public.get("email_verified")),
        "phone_verified": bool(public.get("phone_verified")),
        "notifications_enabled": bool(public.get("notifications_enabled")),
        "two_factor_enabled": bool(public.get("two_factor_enabled")),
        "two_factor_backup_codes_remaining": int(public.get("two_factor_backup_codes_remaining") or 0),
        "created_at": str(public.get("created_at") or ""),
        "created_at_label": str(public.get("created_at_label") or public.get("created_at") or ""),
        "last_sign_in_at": str(public.get("last_sign_in_at") or ""),
        "last_sign_in_at_label": str(public.get("last_sign_in_at_label") or public.get("last_sign_in_at") or ""),
    }


def support_workspace_summary(user_id):
    user_id = safe_user_id(user_id)

    if not user_id:
        return {
            "workspace_exists": False,
            "saved_recipe_files": 0,
            "uploaded_files": 0,
        }

    root = USER_DATA_DIR / user_id
    data_root = root / "recipe-extractor" / "data"

    return {
        "workspace_exists": root.exists(),
        "saved_recipe_files": count_files(data_root / "output", "*.json"),
        "uploaded_files": count_files(data_root / "uploads", "*"),
    }


def count_files(root, pattern):
    if not root.exists():
        return 0

    try:
        return sum(1 for path in root.glob(pattern) if path.is_file())
    except OSError:
        return 0


def safe_account_detail(user):
    detail = safe_account_summary(user)
    detail["workspace"] = support_workspace_summary(user.get("user_id"))
    return detail


def record_support_access(admin_user, target_user, reason):
    actor_private_email = str((admin_user or {}).get("email") or "")
    created_at = now_iso()
    target_user_email = str((target_user or {}).get("email") or "")
    entry = {
        "audit_id": uuid.uuid4().hex,
        "action": AUDIT_ACTION,
        "timestamp": created_at,
        "createdAt": created_at,
        "actorUid": str((admin_user or {}).get("user_id") or ""),
        "actorPrivateEmail": actor_private_email,
        "actorPublicEmail": get_public_support_identity(actor_private_email),
        "admin_user_id": str((admin_user or {}).get("user_id") or ""),
        "admin_email": actor_private_email,
        "target_user_id": str((target_user or {}).get("user_id") or ""),
        "target_email": target_user_email,
        "targetUserEmail": target_user_email,
        "reason": normalize_reason(reason),
    }
    entries = load_audit_entries()
    entries.append(entry)
    save_audit_entries(entries[-500:])
    return entry


def normalize_reason(reason):
    return str(reason or "").strip()[:300]


def open_admin_support_record(admin_user, target_user_id, reason):
    if not is_admin_user(admin_user):
        return {
            "ok": False,
            "errors": ["Admin access is required."],
        }

    reason = normalize_reason(reason)
    if not reason:
        return {
            "ok": False,
            "errors": ["Enter a support reason before opening a user account record."],
        }

    target_user = find_support_target(target_user_id)
    if not target_user:
        return {
            "ok": False,
            "errors": ["Choose a user account to review."],
        }

    audit_entry = record_support_access(admin_user, target_user, reason)
    rendered_audit_entry = audit_entry_for_render(audit_entry)
    email_notice = send_admin_support_access_email(
        target_user,
        admin_user,
        rendered_audit_entry,
    )
    return {
        "ok": True,
        "selected_user": safe_account_detail(target_user),
        "audit_entry": rendered_audit_entry,
        "email_notice": email_notice,
    }


def admin_support_dashboard_for_user(admin_user, selected_user=None, errors=None, reason=""):
    is_admin = is_admin_user(admin_user)
    return {
        "is_admin": is_admin,
        "users": support_users() if is_admin else [],
        "selected_user": selected_user if is_admin and isinstance(selected_user, dict) else None,
        "errors": errors if is_admin and isinstance(errors, list) else [],
        "reason": normalize_reason(reason) if is_admin else "",
        "recent_audit": recent_support_audit_entries() if is_admin else [],
    }
