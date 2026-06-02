import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename


PACKAGE_DIR = Path(__file__).resolve().parent.parent
FEEDBACK_FILE = Path(os.getenv("SHOPPING_APP_FEEDBACK_FILE", PACKAGE_DIR / "feedback.json"))
FEEDBACK_UPLOAD_DIR = Path(os.getenv("SHOPPING_APP_FEEDBACK_UPLOAD_DIR", PACKAGE_DIR / "static" / "uploads" / "feedback"))
ADMIN_EMAIL = "ntylerbert@gmail.com"
FEEDBACK_TYPES = [
    "Bug Report",
    "Feature Request",
    "Product Match Issue",
    "Store Issue",
    "Recipe Issue",
    "General Feedback",
]
FEEDBACK_STATUSES = [
    "Submitted",
    "Under Review",
    "Investigating",
    "Planned",
    "In Progress",
    "Resolved",
    "Closed",
    "Declined",
]
ALLOWED_FEEDBACK_FILE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "pdf",
    "txt",
    "md",
    "csv",
    "doc",
    "docx",
    "xls",
    "xlsx",
}


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_feedback_payload():
    if not FEEDBACK_FILE.exists():
        return {"feedback": []}

    try:
        payload = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"feedback": []}

    if not isinstance(payload, dict):
        return {"feedback": []}

    return {
        "feedback": [
            normalize_feedback_record(item)
            for item in payload.get("feedback", [])
            if isinstance(item, dict) and item.get("feedback_id")
        ],
    }


def save_feedback_payload(payload):
    normalized = {
        "feedback": [
            normalize_feedback_record(item)
            for item in payload.get("feedback", [])
            if isinstance(item, dict) and item.get("feedback_id")
        ],
    }
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_FILE.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def normalize_feedback_record(item):
    timestamp = str(item.get("created_at") or now_iso())
    status = clean_status(item.get("status")) or "Submitted"
    return {
        "feedback_id": str(item.get("feedback_id") or "").strip(),
        "user": normalize_feedback_user(item.get("user")),
        "created_at": timestamp,
        "updated_at": str(item.get("updated_at") or timestamp),
        "feedback_type": clean_feedback_type(item.get("feedback_type")) or "General Feedback",
        "subject": str(item.get("subject") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "attachments": normalize_attachments(item.get("attachments")),
        "status": status,
        "admin_notes": str(item.get("admin_notes") or "").strip(),
        "resolution_notes": str(item.get("resolution_notes") or "").strip(),
        "admin_attachments": normalize_attachments(item.get("admin_attachments")),
        "timeline": normalize_timeline(item.get("timeline"), status, timestamp),
        "notifications": normalize_notifications(item.get("notifications")),
    }


def normalize_feedback_user(user):
    user = user if isinstance(user, dict) else {}
    return {
        "user_id": str(user.get("user_id") or "").strip(),
        "username": str(user.get("username") or "").strip(),
        "email": str(user.get("email") or "").strip(),
    }


def normalize_attachments(attachments):
    normalized = []

    for attachment in attachments if isinstance(attachments, list) else []:
        if not isinstance(attachment, dict):
            continue
        stored_path = str(attachment.get("path") or "").strip()
        if not stored_path:
            continue
        normalized.append({
            "attachment_id": str(attachment.get("attachment_id") or uuid.uuid4().hex),
            "original_name": str(attachment.get("original_name") or "Attachment").strip(),
            "path": stored_path,
            "uploaded_at": str(attachment.get("uploaded_at") or now_iso()),
            "uploaded_by": str(attachment.get("uploaded_by") or "").strip(),
        })

    return normalized


def normalize_timeline(timeline, status, timestamp):
    normalized = []

    for entry in timeline if isinstance(timeline, list) else []:
        if not isinstance(entry, dict):
            continue

        normalized.append({
            "status": clean_status(entry.get("status")) or status,
            "timestamp": str(entry.get("timestamp") or timestamp),
            "actor": str(entry.get("actor") or "").strip(),
        })

    if not normalized:
        normalized.append({
            "status": status,
            "timestamp": timestamp,
            "actor": "System",
        })

    return normalized


def normalize_notifications(notifications):
    normalized = []

    for notification in notifications if isinstance(notifications, list) else []:
        if not isinstance(notification, dict):
            continue
        normalized.append({
            "notification_id": str(notification.get("notification_id") or uuid.uuid4().hex),
            "user_id": str(notification.get("user_id") or "").strip(),
            "message": str(notification.get("message") or "").strip(),
            "created_at": str(notification.get("created_at") or now_iso()),
            "read_at": str(notification.get("read_at") or "").strip(),
        })

    return normalized


def feedback_dashboard_for_user(user):
    payload = load_feedback_payload()
    user = user if isinstance(user, dict) else None
    is_admin = is_feedback_admin(user)
    user_id = str((user or {}).get("user_id") or "")
    my_feedback = [
        feedback_view(item, user)
        for item in payload["feedback"]
        if user_id and item.get("user", {}).get("user_id") == user_id
    ]
    admin_feedback = [
        feedback_view(item, user, include_user=True)
        for item in payload["feedback"]
    ] if is_admin else []

    return {
        "is_admin": is_admin,
        "feedback_types": list(FEEDBACK_TYPES),
        "feedback_statuses": list(FEEDBACK_STATUSES),
        "my_feedback": sorted(my_feedback, key=lambda item: item["sort_updated_at"], reverse=True),
        "admin_feedback": sorted(admin_feedback, key=lambda item: item["sort_updated_at"], reverse=True),
        "unread_count": sum(item.get("unread_notifications_count", 0) for item in my_feedback),
    }


def feedback_view(item, current_user=None, include_user=False):
    notifications = user_notifications_for_feedback(item, current_user)
    last_notification = notifications[-1] if notifications else {}
    timeline = [
        {
            **entry,
            "display_date": format_display_datetime(entry.get("timestamp")),
        }
        for entry in item.get("timeline", [])
    ]
    view = {
        **item,
        "display_created_at": format_display_datetime(item.get("created_at")),
        "display_updated_at": format_display_datetime(item.get("updated_at")),
        "sort_updated_at": item.get("updated_at") or item.get("created_at") or "",
        "timeline": timeline,
        "unread_notifications_count": len([notification for notification in notifications if not notification.get("read_at")]),
        "latest_notification_message": last_notification.get("message", ""),
        "latest_notification_at": format_display_datetime(last_notification.get("created_at")),
    }

    if not include_user:
        view.pop("user", None)

    return view


def user_notifications_for_feedback(item, current_user):
    user_id = str((current_user or {}).get("user_id") or "")
    if not user_id:
        return []

    return [
        notification
        for notification in item.get("notifications", [])
        if notification.get("user_id") == user_id
    ]


def create_feedback(user, form, files):
    if not user:
        return {"ok": False, "errors": ["Sign in before submitting feedback so updates can be tracked to your account."]}

    feedback_type = clean_feedback_type(form.get("feedback_type")) or ""
    subject = str(form.get("subject") or "").strip()
    description = str(form.get("description") or "").strip()
    errors = []

    if feedback_type not in FEEDBACK_TYPES:
        errors.append("Choose a feedback type.")
    if not subject:
        errors.append("Subject is required.")
    if not description:
        errors.append("Description is required.")

    if errors:
        return {"ok": False, "errors": errors}

    payload = load_feedback_payload()
    timestamp = now_iso()
    feedback_id = next_feedback_id(payload)
    attachment_result = save_feedback_uploads(
        [
            *files.getlist("screenshot"),
            *files.getlist("attachment"),
        ],
        feedback_id,
        "user",
    )

    if not attachment_result.get("ok"):
        return {"ok": False, "errors": attachment_result.get("errors", ["Attachment upload failed."])}

    record = {
        "feedback_id": feedback_id,
        "user": {
            "user_id": user.get("user_id", ""),
            "username": user.get("username", ""),
            "email": user.get("email", ""),
        },
        "created_at": timestamp,
        "updated_at": timestamp,
        "feedback_type": feedback_type,
        "subject": subject,
        "description": description,
        "attachments": attachment_result.get("attachments", []),
        "status": "Submitted",
        "admin_notes": "",
        "resolution_notes": "",
        "admin_attachments": [],
        "timeline": [{
            "status": "Submitted",
            "timestamp": timestamp,
            "actor": user.get("email") or user.get("username") or "User",
        }],
        "notifications": [],
    }
    payload["feedback"].append(record)
    save_feedback_payload(payload)
    return {"ok": True, "feedback": feedback_view(record, user), "feedback_id": feedback_id}


def update_feedback_as_admin(admin_user, feedback_id, form, files):
    if not is_feedback_admin(admin_user):
        return {"ok": False, "errors": ["Only the feedback administrator can update feedback."]}

    payload = load_feedback_payload()
    item = find_feedback_in_payload(payload, feedback_id)

    if not item:
        return {"ok": False, "errors": ["Feedback item was not found."]}

    new_status = clean_status(form.get("status"))
    admin_notes = str(form.get("admin_notes") or "").strip()
    resolution_notes = str(form.get("resolution_notes") or "").strip()

    if new_status not in FEEDBACK_STATUSES:
        return {"ok": False, "errors": ["Choose a valid feedback status."]}

    old_status = item.get("status") or "Submitted"
    status_changed = new_status != old_status
    notes_changed = admin_notes != item.get("admin_notes", "")
    resolution_changed = resolution_notes != item.get("resolution_notes", "")
    attachment_result = save_feedback_uploads(
        files.getlist("admin_attachment"),
        item["feedback_id"],
        "admin",
    )

    if not attachment_result.get("ok"):
        return {"ok": False, "errors": attachment_result.get("errors", ["Attachment upload failed."])}

    item["status"] = new_status
    item["admin_notes"] = admin_notes
    item["resolution_notes"] = resolution_notes
    item["admin_attachments"].extend(attachment_result.get("attachments", []))

    if status_changed:
        timestamp = now_iso()
        item["timeline"].append({
            "status": new_status,
            "timestamp": timestamp,
            "actor": admin_user.get("email") or "Admin",
        })
        item["notifications"].append({
            "notification_id": uuid.uuid4().hex,
            "user_id": item.get("user", {}).get("user_id", ""),
            "message": f"Your feedback {item['feedback_id']} was updated: Status changed to {new_status}.",
            "created_at": timestamp,
            "read_at": "",
        })

    if notes_changed or resolution_changed or attachment_result.get("attachments") or status_changed:
        item["updated_at"] = now_iso()

    save_feedback_payload(payload)
    return {"ok": True, "feedback": feedback_view(item, admin_user, include_user=True)}


def mark_feedback_notifications_read(user, feedback_id):
    if not user:
        return {"ok": False, "errors": ["Sign in before marking feedback updates read."]}

    payload = load_feedback_payload()
    item = find_feedback_in_payload(payload, feedback_id)
    user_id = str(user.get("user_id") or "")

    if not item or item.get("user", {}).get("user_id") != user_id:
        return {"ok": False, "errors": ["Feedback item was not found."]}

    timestamp = now_iso()
    for notification in item.get("notifications", []):
        if notification.get("user_id") == user_id and not notification.get("read_at"):
            notification["read_at"] = timestamp

    save_feedback_payload(payload)
    return {"ok": True}


def save_feedback_uploads(uploads, feedback_id, actor):
    attachments = []
    errors = []

    for upload in uploads:
        if not upload or not getattr(upload, "filename", ""):
            continue

        filename = secure_filename(upload.filename or "")
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if extension not in ALLOWED_FEEDBACK_FILE_EXTENSIONS:
            errors.append(f"{filename or 'Attachment'} is not an allowed file type.")
            continue

        feedback_slug = secure_feedback_id(feedback_id)
        target_dir = FEEDBACK_UPLOAD_DIR / feedback_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex[:12]}_{filename}"
        upload.save(target_dir / stored_name)
        attachments.append({
            "attachment_id": uuid.uuid4().hex,
            "original_name": filename,
            "path": f"uploads/feedback/{feedback_slug}/{stored_name}",
            "uploaded_at": now_iso(),
            "uploaded_by": actor,
        })

    if errors:
        return {"ok": False, "errors": errors}

    return {"ok": True, "attachments": attachments}


def next_feedback_id(payload):
    highest = 1000

    for item in payload.get("feedback", []):
        match = re.search(r"(\d+)$", str(item.get("feedback_id") or ""))
        if match:
            highest = max(highest, int(match.group(1)))

    return f"FB-{highest + 1}"


def find_feedback_in_payload(payload, feedback_id):
    feedback_id = str(feedback_id or "").strip().upper()
    return next(
        (item for item in payload.get("feedback", []) if str(item.get("feedback_id") or "").upper() == feedback_id),
        None,
    )


def clean_feedback_type(value):
    value = str(value or "").strip()
    return value if value in FEEDBACK_TYPES else ""


def clean_status(value):
    value = str(value or "").strip()
    return value if value in FEEDBACK_STATUSES else ""


def is_feedback_admin(user):
    email = str((user or {}).get("email") or "").strip().lower()
    return email == ADMIN_EMAIL


def secure_feedback_id(feedback_id):
    return re.sub(r"[^A-Za-z0-9_-]+", "", str(feedback_id or ""))[:40] or uuid.uuid4().hex


def format_display_datetime(value):
    parsed = parse_iso_datetime(value)

    if not parsed:
        return ""

    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None
