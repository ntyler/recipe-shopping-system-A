import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from PushShoppingList.services.email_service import send_admin_support_access_email
from PushShoppingList.services.guest_session_service import expired_guest_session_count
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import guest_purge_service
from PushShoppingList.services.storage_service import USER_DATA_DIR
from PushShoppingList.services.storage_service import safe_user_id
from PushShoppingList.services.user_account_service import display_datetime
from PushShoppingList.services.user_account_service import can_manage_admin_access
from PushShoppingList.services.user_account_service import get_public_support_identity
from PushShoppingList.services.user_account_service import is_admin_user
from PushShoppingList.services.user_account_service import is_owner_admin_user
from PushShoppingList.services.user_account_service import load_users
from PushShoppingList.services.user_account_service import public_user
from PushShoppingList.services.user_account_service import save_users
from PushShoppingList.services import durable_document_runtime_service as durable_runtime


PACKAGE_DIR = Path(__file__).resolve().parent.parent
ADMIN_SUPPORT_AUDIT_FILE = Path(
    os.getenv("SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE", PACKAGE_DIR / "admin_support_audit.json")
)
AUDIT_ACTION = "view_account_support_record"
ADMIN_ACCESS_AUDIT_ACTION = "update_admin_access"
GUEST_DEMO_CLEANUP_AUDIT_ACTION = "delete_expired_guest_demo_sessions"


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_audit_entries():
    def legacy_loader():
        if not ADMIN_SUPPORT_AUDIT_FILE.exists():
            return []
        try:
            return json.loads(ADMIN_SUPPORT_AUDIT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    payload = durable_runtime.load_json_document(
        legacy_loader,
        domain="audit",
        document_key="admin_support",
        source_key="admin_audit",
        source_ref="admin_audit",
        workspace_id=durable_runtime.GLOBAL_WORKSPACE_ID,
        workspace_type=durable_runtime.GLOBAL_WORKSPACE_TYPE,
        subject_id=durable_runtime.GLOBAL_SUBJECT_ID,
    )

    entries = payload.get("entries", []) if isinstance(payload, dict) else payload

    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("audit_id")
    ]


def save_audit_entries(entries):
    return durable_runtime.save_json_document(
        {"entries": entries},
        lambda value: durable_runtime.atomic_write_json(
            ADMIN_SUPPORT_AUDIT_FILE, value
        ),
        domain="audit",
        document_key="admin_support",
        source_key="admin_audit",
        source_ref="admin_audit",
        workspace_id=durable_runtime.GLOBAL_WORKSPACE_ID,
        workspace_type=durable_runtime.GLOBAL_WORKSPACE_TYPE,
        subject_id=durable_runtime.GLOBAL_SUBJECT_ID,
    )


def recent_support_audit_entries(limit=20):
    entries = sorted(
        [
            (index, entry)
            for index, entry in enumerate(load_audit_entries())
            if str(entry.get("action") or "") == AUDIT_ACTION
        ],
        key=lambda item: (str(item[1].get("timestamp") or ""), item[0]),
        reverse=True,
    )
    return [audit_entry_for_render(entry) for _index, entry in entries[:limit]]


def recent_admin_access_audit_entries(limit=20):
    entries = sorted(
        [
            (index, entry)
            for index, entry in enumerate(load_audit_entries())
            if str(entry.get("action") or "") == ADMIN_ACCESS_AUDIT_ACTION
        ],
        key=lambda item: (str(item[1].get("timestamp") or ""), item[0]),
        reverse=True,
    )
    return [admin_access_audit_entry_for_render(entry) for _index, entry in entries[:limit]]


def support_access_notices_for_user(user, limit=2):
    user_id = str((user or {}).get("user_id") or "").strip()
    email = str((user or {}).get("email") or "").strip().lower()

    if not user_id and not email:
        return []

    notices = []
    for index, entry in enumerate(load_audit_entries()):
        if str(entry.get("action") or "") != AUDIT_ACTION:
            continue

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


def admin_access_audit_entry_for_render(entry):
    rendered = audit_entry_for_render(entry)
    enabled = bool(entry.get("admin_access_enabled"))
    rendered.update({
        "admin_access_enabled": enabled,
        "admin_access_action": "Granted" if enabled else "Revoked",
    })
    return rendered


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
    admin_access_enabled = bool(public.get("admin_access_enabled"))
    admin_access_locked = bool(public.get("admin_access_locked"))
    return {
        "user_id": str(public.get("user_id") or ""),
        "display_name": str(public.get("display_name") or ""),
        "username": str(public.get("username") or ""),
        "email": str(public.get("email") or ""),
        "auth_provider": str(public.get("auth_provider") or ""),
        "provider_label": str(public.get("provider_label") or public.get("provider") or ""),
        "role": str(public.get("role") or "User"),
        "is_admin": bool(public.get("is_admin")),
        "admin_access_enabled": admin_access_enabled,
        "admin_access_locked": admin_access_locked,
        "admin_access_label": admin_access_label(public),
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


def admin_access_label(user):
    if bool((user or {}).get("admin_access_locked")):
        return "Main admin"

    if bool((user or {}).get("admin_access_enabled")):
        return "Granted admin"

    if bool((user or {}).get("is_admin")):
        return "Configured admin"

    return "User"


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


def record_admin_access_change(admin_user, target_user, enabled):
    actor_private_email = str((admin_user or {}).get("email") or "")
    created_at = now_iso()
    target_user_email = str((target_user or {}).get("email") or "")
    entry = {
        "audit_id": uuid.uuid4().hex,
        "action": ADMIN_ACCESS_AUDIT_ACTION,
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
        "admin_access_enabled": bool(enabled),
        "reason": "Granted admin access" if enabled else "Revoked admin access",
    }
    entries = load_audit_entries()
    entries.append(entry)
    save_audit_entries(entries[-500:])
    return entry


def record_expired_guest_demo_cleanup(admin_user, cleanup_result):
    actor_private_email = str((admin_user or {}).get("email") or "")
    created_at = now_iso()
    deleted_count = int((cleanup_result or {}).get("deleted_count") or 0)
    guest_session_ids = [
        str(guest_id)
        for guest_id in (cleanup_result or {}).get("guest_session_ids", [])
        if str(guest_id)
    ]
    entry = {
        "audit_id": uuid.uuid4().hex,
        "action": GUEST_DEMO_CLEANUP_AUDIT_ACTION,
        "timestamp": created_at,
        "createdAt": created_at,
        "actorUid": str((admin_user or {}).get("user_id") or ""),
        "actorPrivateEmail": actor_private_email,
        "actorPublicEmail": get_public_support_identity(actor_private_email),
        "admin_user_id": str((admin_user or {}).get("user_id") or ""),
        "admin_email": actor_private_email,
        "target_user_id": "",
        "target_email": "",
        "targetUserEmail": "",
        "deleted_count": deleted_count,
        "guest_session_ids": guest_session_ids,
        "reason": f"Deleted {deleted_count} expired guest demo session{'s' if deleted_count != 1 else ''}.",
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


def update_account_admin_access(admin_user, target_user_id, enabled):
    if not can_manage_admin_access(admin_user):
        return {
            "ok": False,
            "errors": ["Only the main admin can manage admin access."],
        }

    target_user_id = str(target_user_id or "").strip()
    if not target_user_id:
        return {
            "ok": False,
            "errors": ["Choose a user account before changing admin access."],
        }

    payload = load_users()
    target_user = next(
        (
            user
            for user in payload.get("users", [])
            if str(user.get("user_id") or "").strip() == target_user_id
        ),
        None,
    )
    if not target_user:
        return {
            "ok": False,
            "errors": ["Choose a valid user account before changing admin access."],
        }

    if is_owner_admin_user(target_user):
        return {
            "ok": False,
            "errors": ["Main admin access is built in and cannot be changed here."],
            "selected_user": safe_account_detail(target_user),
        }

    previous_enabled = bool(target_user.get("admin_access_enabled"))
    target_user["admin_access_enabled"] = bool(enabled)
    target_user["admin_access_updated_at"] = now_iso()
    target_user["admin_access_updated_by"] = str((admin_user or {}).get("user_id") or "")
    target_user["admin_access_updated_by_email"] = str((admin_user or {}).get("email") or "")
    save_users(payload)

    audit_entry = record_admin_access_change(admin_user, target_user, enabled)
    action = "granted" if enabled else "revoked"
    return {
        "ok": True,
        "changed": previous_enabled != bool(enabled),
        "selected_user": safe_account_detail(target_user),
        "audit_entry": admin_access_audit_entry_for_render(audit_entry),
        "message": f"Admin access {action} for {target_user.get('email') or 'that account'}.",
    }


def delete_expired_guest_demo_sessions_for_admin(
    admin_user,
    *,
    dry_run=True,
    authorized=False,
    approval="",
    db_path=None,
    recipe_db_path=None,
    jobs_db_path=None,
    guest_base_dir=None,
    at_time=None,
    artifact_deleters=None,
    rq_canceller=None,
    failure_injector=None,
):
    if not is_admin_user(admin_user):
        return {
            "ok": False,
            "errors": ["Admin access is required."],
        }

    try:
        result = guest_purge_service.purge_expired_guest_batch(
            dry_run=bool(dry_run),
            authorized=bool(authorized),
            approval=approval,
            db_path=db_path,
            recipe_db_path=recipe_db_path,
            jobs_db_path=jobs_db_path,
            guest_base_dir=guest_base_dir,
            at_time=at_time,
            artifact_deleters=artifact_deleters,
            rq_canceller=rq_canceller,
            failure_injector=failure_injector,
        )
    except guest_purge_service.GuestPurgeApprovalError:
        return {
            "ok": False,
            "dry_run": False,
            "applied": False,
            "code": "approval_required",
            "errors": ["Type the exact guest purge approval phrase."],
        }

    if dry_run:
        if not result.get("ok"):
            return {
                **result,
                "errors": [
                    "Guest cleanup is unavailable until the database schema and guest migration are complete."
                ],
            }
        eligible_count = int(result.get("eligible_count") or 0)
        return {
            **result,
            "deleted_count": 0,
            "guest_session_ids": [],
            "message": (
                f"Previewed {eligible_count} expired or orphaned guest session"
                f"{'s' if eligible_count != 1 else ''}; no data was deleted."
            ),
        }

    audit_entry = (
        record_expired_guest_demo_cleanup(admin_user, result)
        if result.get("applied")
        else None
    )
    deleted_count = int(result.get("deleted_count") or 0)
    if not result.get("ok"):
        retryable_count = len(result.get("retryable_failures") or [])
        return {
            **result,
            "deleted_count": deleted_count,
            "guest_session_ids": result.get("guest_session_ids", []),
            "audit_entry": audit_entry_for_render(audit_entry) if audit_entry else None,
            "errors": [
                (
                    f"Guest cleanup is incomplete; {retryable_count} purge"
                    f"{'s' if retryable_count != 1 else ''} can be retried."
                )
                if retryable_count
                else "Guest cleanup failed safely without using legacy deletion."
            ],
        }
    return {
        "ok": True,
        "dry_run": False,
        "applied": True,
        "deleted_count": deleted_count,
        "guest_session_ids": result.get("guest_session_ids", []),
        "audit_entry": audit_entry_for_render(audit_entry) if audit_entry else None,
        "message": f"Deleted {deleted_count} expired guest demo session{'s' if deleted_count != 1 else ''}.",
    }


def expired_guest_purge_candidate_count_for_admin():
    """Include retryable/orphan candidates after the database becomes authoritative."""

    try:
        legacy_count = expired_guest_session_count()
    except Exception:
        legacy_count = 0
    try:
        if guest_session_service.guest_session_backend_mode() not in {
            "db_preferred",
            "db_only",
        }:
            return legacy_count
        database = guest_session_service.guest_session_db_path()
        preview = guest_purge_service.preview_expired_guest_purge_batch(
            db_path=database,
            recipe_db_path=database,
        )
        if preview.get("ok"):
            return int(preview.get("eligible_count") or 0)
    except Exception:
        pass
    return legacy_count


def admin_support_dashboard_for_user(admin_user, selected_user=None, errors=None, reason=""):
    is_admin = is_admin_user(admin_user)
    can_manage_access = can_manage_admin_access(admin_user)
    return {
        "is_admin": is_admin,
        "can_manage_admin_access": can_manage_access,
        "users": support_users() if is_admin else [],
        "selected_user": selected_user if is_admin and isinstance(selected_user, dict) else None,
        "errors": errors if is_admin and isinstance(errors, list) else [],
        "reason": normalize_reason(reason) if is_admin else "",
        "recent_audit": recent_support_audit_entries() if is_admin else [],
        "recent_admin_access": recent_admin_access_audit_entries() if can_manage_access else [],
        "expired_guest_demo_count": (
            expired_guest_purge_candidate_count_for_admin() if is_admin else 0
        ),
        "guest_purge_approval_phrase": (
            guest_purge_service.GUEST_PURGE_BATCH_APPROVAL_PHRASE if is_admin else ""
        ),
    }
