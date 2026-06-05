import json
import os
import re
import uuid
import asyncio
from datetime import datetime
from pathlib import Path

from werkzeug.utils import secure_filename

from PushShoppingList.services.user_account_service import SUPPORT_EMAIL
from PushShoppingList.services.user_account_service import get_public_support_identity
from PushShoppingList.services.user_account_service import is_admin_user


PACKAGE_DIR = Path(__file__).resolve().parent.parent
FEEDBACK_FILE = Path(os.getenv("SHOPPING_APP_FEEDBACK_FILE", PACKAGE_DIR / "feedback.json"))
FEEDBACK_UPLOAD_DIR = Path(os.getenv("SHOPPING_APP_FEEDBACK_UPLOAD_DIR", PACKAGE_DIR / "static" / "uploads" / "feedback"))
FEEDBACK_TYPES = [
    "Bug Report",
    "Feature Request",
    "Product Match Issue",
    "Store Request",
    "Store Issue",
    "Recipe Issue",
    "General Feedback",
]
FEEDBACK_STATUSES = [
    "Submitted",
    "Acknowledged",
    "Investigating",
    "Waiting on User",
    "Resolved",
    "Closed",
]
LEGACY_STATUS_MAP = {
    "Under Review": "Acknowledged",
    "Planned": "Investigating",
    "In Progress": "Investigating",
    "Declined": "Closed",
}
FEEDBACK_PRIORITIES = [
    "Low",
    "Normal",
    "High",
    "Critical",
]
TIMELINE_EVENTS = [
    "Submitted",
    "Acknowledged",
    "Investigating",
    "Support Update Added",
    "User Comment Added",
    "Resolution Notes Added",
    "Resolved",
    "Reopened",
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
    priority = clean_priority(item.get("priority")) or "Normal"
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
        "priority": priority,
        "admin_notes": str(item.get("admin_notes") or "").strip(),
        "resolution_notes": str(item.get("resolution_notes") or "").strip(),
        "admin_attachments": normalize_attachments(item.get("admin_attachments")),
        "timeline": normalize_timeline(item.get("timeline"), status, timestamp),
        "notifications": normalize_notifications(item.get("notifications")),
        "comments": normalize_comments(item.get("comments")),
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

        event = clean_timeline_event(entry.get("event") or entry.get("status")) or status
        actor_private_email = str(
            entry.get("actorPrivateEmail")
            or entry.get("actorEmail")
            or entry.get("actor")
            or ""
        ).strip()
        actor_public_email = str(entry.get("actorPublicEmail") or "").strip()
        actor_type = clean_author_type(entry.get("actorType")) or infer_actor_type(actor_private_email, event)
        if actor_type == "support":
            actor_public_email = actor_public_email or public_support_email_for_private(actor_private_email)

        normalized.append({
            "event": event,
            "status": clean_status(entry.get("status")) or (event if event in FEEDBACK_STATUSES else status),
            "timestamp": str(entry.get("timestamp") or timestamp),
            "actor": str(entry.get("actor") or "").strip(),
            "actorUid": str(entry.get("actorUid") or "").strip(),
            "actorEmail": str(entry.get("actorEmail") or actor_private_email).strip(),
            "actorPrivateEmail": actor_private_email,
            "actorPublicEmail": actor_public_email,
            "actorType": actor_type,
        })

    if not normalized:
        normalized.append({
            "event": status,
            "status": status,
            "timestamp": timestamp,
            "actor": "System",
            "actorUid": "",
            "actorEmail": "",
            "actorPrivateEmail": "",
            "actorPublicEmail": "",
            "actorType": "system",
        })

    return normalized


def normalize_comments(comments):
    normalized = []

    for comment in comments if isinstance(comments, list) else []:
        if not isinstance(comment, dict):
            continue

        comment_text = str(comment.get("commentText") or comment.get("text") or "").strip()
        if not comment_text:
            continue

        author_type = clean_author_type(comment.get("authorType")) or "user"
        author_email = str(comment.get("authorEmail") or comment.get("author_email") or "").strip()
        author_private_email = str(
            comment.get("authorPrivateEmail")
            or comment.get("actorPrivateEmail")
            or author_email
        ).strip()
        author_public_email = str(comment.get("authorPublicEmail") or comment.get("actorPublicEmail") or "").strip()

        if author_type == "support":
            author_public_email = author_public_email or public_support_email_for_private(author_private_email)
        else:
            author_public_email = author_public_email or author_email

        normalized.append({
            "commentId": str(comment.get("commentId") or comment.get("comment_id") or uuid.uuid4().hex),
            "commentText": comment_text,
            "authorUid": str(comment.get("authorUid") or comment.get("author_uid") or "").strip(),
            "authorEmail": author_email,
            "authorPrivateEmail": author_private_email,
            "authorPublicEmail": author_public_email,
            "authorType": author_type,
            "createdAt": str(comment.get("createdAt") or comment.get("created_at") or now_iso()),
        })

    return sorted(normalized, key=lambda item: item.get("createdAt") or "")


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
        "feedback_priorities": list(FEEDBACK_PRIORITIES),
        "my_feedback": sorted(my_feedback, key=lambda item: item["sort_updated_at"], reverse=True),
        "admin_feedback": sorted(admin_feedback, key=lambda item: item["sort_updated_at"], reverse=True),
        "unread_count": sum(item.get("unread_notifications_count", 0) for item in my_feedback),
    }


def feedback_view(item, current_user=None, include_user=False):
    notifications = user_notifications_for_feedback(item, current_user)
    last_notification = notifications[-1] if notifications else {}
    viewer_is_admin = is_feedback_admin(current_user)
    timeline = [
        {
            **entry,
            "display_date": format_display_datetime(entry.get("timestamp")),
            "display_actor": timeline_actor_for_view(entry, include_private=include_user and viewer_is_admin),
        }
        for entry in item.get("timeline", [])
    ]
    comments = [
        {
            **comment,
            "display_created_at": format_display_datetime(comment.get("createdAt")),
            "display_author": comment_author_for_view(comment, include_private=include_user and viewer_is_admin),
            "author_type_label": "Support" if comment.get("authorType") == "support" else "You",
        }
        for comment in item.get("comments", [])
    ]
    view = {
        **item,
        "display_feedback_id": display_feedback_id(item.get("feedback_id")),
        "display_created_at": format_display_datetime(item.get("created_at")),
        "display_updated_at": format_display_datetime(item.get("updated_at")),
        "sort_updated_at": item.get("updated_at") or item.get("created_at") or "",
        "priority": clean_priority(item.get("priority")) or "Normal",
        "priority_key": (clean_priority(item.get("priority")) or "Normal").lower(),
        "support_public_email": SUPPORT_EMAIL,
        "timeline": timeline,
        "comments": comments,
        "unread_notifications_count": len([notification for notification in notifications if not notification.get("read_at")]),
        "latest_notification_message": display_notification_message(last_notification.get("message", ""), item),
        "latest_notification_at": format_display_datetime(last_notification.get("created_at")),
        "can_reopen": item.get("status") == "Resolved",
    }

    if not include_user:
        view.pop("user", None)

    return view


def display_feedback_id(feedback_id):
    feedback_id = str(feedback_id or "").strip().upper()
    if not feedback_id:
        return "RSL-FB"
    if feedback_id.startswith("RSL-"):
        return feedback_id
    return f"RSL-{feedback_id}"


def public_support_email_for_private(email):
    email = str(email or "").strip()
    public_email = get_public_support_identity(email)

    if not public_email or "@" not in public_email:
        return SUPPORT_EMAIL

    return public_email


def timeline_actor_for_view(entry, include_private=False):
    actor_type = clean_author_type(entry.get("actorType"))

    if actor_type == "support":
        if include_private:
            return (
                str(entry.get("actorPrivateEmail") or entry.get("actorEmail") or "").strip()
                or SUPPORT_EMAIL
            )
        return (
            str(entry.get("actorPublicEmail") or "").strip()
            or public_support_email_for_private(entry.get("actorPrivateEmail") or entry.get("actorEmail"))
        )

    return str(entry.get("actorEmail") or entry.get("actor") or entry.get("actorPublicEmail") or "").strip() or "System"


def comment_author_for_view(comment, include_private=False):
    if comment.get("authorType") == "support":
        if include_private:
            return str(comment.get("authorPrivateEmail") or comment.get("authorEmail") or "").strip() or SUPPORT_EMAIL
        return (
            str(comment.get("authorPublicEmail") or "").strip()
            or public_support_email_for_private(comment.get("authorPrivateEmail") or comment.get("authorEmail"))
        )

    return str(comment.get("authorEmail") or comment.get("authorPublicEmail") or "").strip() or "User"


def display_notification_message(message, item):
    message = str(message or "").strip()
    feedback_id = str((item or {}).get("feedback_id") or "").strip()

    if not message or not feedback_id:
        return message

    return re.sub(
        rf"(?<!RSL-)(?<![A-Za-z0-9-]){re.escape(feedback_id)}(?![A-Za-z0-9-])",
        display_feedback_id(feedback_id),
        message,
    )


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
        "priority": "Normal",
        "admin_notes": "",
        "resolution_notes": "",
        "admin_attachments": [],
        "timeline": [{
            "event": "Submitted",
            "status": "Submitted",
            "timestamp": timestamp,
            "actor": user.get("email") or user.get("username") or "User",
            "actorUid": user.get("user_id", ""),
            "actorEmail": user.get("email") or user.get("username") or "",
            "actorPrivateEmail": "",
            "actorPublicEmail": user.get("email") or user.get("username") or "",
            "actorType": "user",
        }],
        "notifications": [],
        "comments": [],
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
    new_priority = clean_priority(form.get("priority")) or item.get("priority") or "Normal"
    admin_notes = str(form.get("admin_notes") or "").strip()
    resolution_notes = str(form.get("resolution_notes") or "").strip()
    support_comment = str(form.get("support_comment") or "").strip()

    if new_status not in FEEDBACK_STATUSES:
        return {"ok": False, "errors": ["Choose a valid feedback status."]}

    old_status = item.get("status") or "Submitted"
    old_priority = item.get("priority") or "Normal"
    status_changed = new_status != old_status
    priority_changed = new_priority != old_priority
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
    item["priority"] = new_priority
    item["admin_notes"] = admin_notes
    item["resolution_notes"] = resolution_notes
    item["admin_attachments"].extend(attachment_result.get("attachments", []))
    timestamp = now_iso()

    if status_changed:
        append_timeline_event(item, new_status, admin_user, "support", timestamp=timestamp, status=new_status)
        append_user_notification(
            item,
            f"Your ticket {display_feedback_id(item['feedback_id'])} was updated: Status changed to {new_status}.",
            timestamp,
        )
        queue_support_notification(item, "status_changed")

        if new_status == "Resolved":
            queue_support_notification(item, "ticket_resolved")

    if notes_changed and admin_notes:
        append_timeline_event(item, "Support Update Added", admin_user, "support", timestamp=timestamp, status=new_status)
        append_user_notification(
            item,
            f"Support added an update to {display_feedback_id(item['feedback_id'])}.",
            timestamp,
        )
        queue_support_notification(item, "support_update_added")

    if resolution_changed and resolution_notes:
        append_timeline_event(item, "Resolution Notes Added", admin_user, "support", timestamp=timestamp, status=new_status)
        append_user_notification(
            item,
            f"Resolution notes were added to {display_feedback_id(item['feedback_id'])}.",
            timestamp,
        )
        queue_support_notification(item, "resolution_notes_added")

    if support_comment:
        append_feedback_comment(item, admin_user, support_comment, "support", timestamp=timestamp)
        append_timeline_event(item, "Support Update Added", admin_user, "support", timestamp=timestamp, status=new_status)
        append_user_notification(
            item,
            f"Support replied to {display_feedback_id(item['feedback_id'])}.",
            timestamp,
        )
        queue_support_notification(item, "support_update_added")

    if (
        notes_changed
        or resolution_changed
        or attachment_result.get("attachments")
        or status_changed
        or priority_changed
        or support_comment
    ):
        item["updated_at"] = timestamp

    save_feedback_payload(payload)
    return {"ok": True, "feedback": feedback_view(item, admin_user, include_user=True)}


def append_timeline_event(item, event, actor_user, actor_type, timestamp=None, status=None):
    timestamp = timestamp or now_iso()
    actor_type = clean_author_type(actor_type) or "system"
    actor_private_email = str((actor_user or {}).get("email") or "").strip()
    actor_public_email = (
        public_support_email_for_private(actor_private_email)
        if actor_type == "support"
        else actor_private_email
    )

    item.setdefault("timeline", []).append({
        "event": clean_timeline_event(event) or event,
        "status": clean_status(status) or clean_status(item.get("status")) or "Submitted",
        "timestamp": timestamp,
        "actor": actor_public_email or actor_private_email or "System",
        "actorUid": str((actor_user or {}).get("user_id") or "").strip(),
        "actorEmail": actor_private_email,
        "actorPrivateEmail": actor_private_email if actor_type == "support" else "",
        "actorPublicEmail": actor_public_email,
        "actorType": actor_type,
    })


def append_user_notification(item, message, timestamp=None):
    item.setdefault("notifications", []).append({
        "notification_id": uuid.uuid4().hex,
        "user_id": item.get("user", {}).get("user_id", ""),
        "message": str(message or "").strip(),
        "created_at": timestamp or now_iso(),
        "read_at": "",
    })


def append_feedback_comment(item, actor_user, comment_text, author_type, timestamp=None):
    author_type = clean_author_type(author_type) or "user"
    author_private_email = str((actor_user or {}).get("email") or "").strip()
    author_public_email = (
        public_support_email_for_private(author_private_email)
        if author_type == "support"
        else author_private_email
    )
    comment = {
        "commentId": uuid.uuid4().hex,
        "commentText": str(comment_text or "").strip(),
        "authorUid": str((actor_user or {}).get("user_id") or "").strip(),
        "authorEmail": author_private_email,
        "authorPrivateEmail": author_private_email if author_type == "support" else "",
        "authorPublicEmail": author_public_email,
        "authorType": author_type,
        "createdAt": timestamp or now_iso(),
    }
    item.setdefault("comments", []).append(comment)
    return comment


async def send_support_notification(ticket, event_type):
    # TODO: send email from support@recipeshoppinglist.com
    # Subject example:
    # [RSL-FB-1001] Status updated to Investigating
    return {"ok": True, "skipped": True, "event_type": event_type, "ticket_id": display_feedback_id(ticket.get("feedback_id"))}


def queue_support_notification(ticket, event_type):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(send_support_notification(ticket, event_type))
    else:
        loop.create_task(send_support_notification(ticket, event_type))


def add_feedback_comment(user, feedback_id, comment_text):
    if not user:
        return {"ok": False, "errors": ["Sign in before replying to support."]}

    comment_text = str(comment_text or "").strip()
    if not comment_text:
        return {"ok": False, "errors": ["Add a comment before replying to support."]}

    payload = load_feedback_payload()
    item = find_feedback_in_payload(payload, feedback_id)

    if not item:
        return {"ok": False, "errors": ["Feedback item was not found."]}

    user_id = str(user.get("user_id") or "")
    owner_id = str(item.get("user", {}).get("user_id") or "")
    user_is_admin = is_feedback_admin(user)

    if owner_id != user_id and not user_is_admin:
        return {"ok": False, "errors": ["Feedback item was not found."]}

    timestamp = now_iso()
    author_type = "support" if user_is_admin and owner_id != user_id else "user"
    append_feedback_comment(item, user, comment_text, author_type, timestamp=timestamp)
    append_timeline_event(
        item,
        "Support Update Added" if author_type == "support" else "User Comment Added",
        user,
        author_type,
        timestamp=timestamp,
        status=item.get("status"),
    )

    if author_type == "support":
        append_user_notification(
            item,
            f"Support replied to {display_feedback_id(item['feedback_id'])}.",
            timestamp,
        )
        queue_support_notification(item, "support_update_added")

    item["updated_at"] = timestamp
    save_feedback_payload(payload)
    return {"ok": True, "feedback": feedback_view(item, user, include_user=user_is_admin)}


def reopen_feedback_ticket(user, feedback_id):
    if not user:
        return {"ok": False, "errors": ["Sign in before reopening a ticket."]}

    payload = load_feedback_payload()
    item = find_feedback_in_payload(payload, feedback_id)
    user_id = str(user.get("user_id") or "")

    if not item or item.get("user", {}).get("user_id") != user_id:
        return {"ok": False, "errors": ["Feedback item was not found."]}

    if item.get("status") not in {"Resolved", "Closed"}:
        return {"ok": False, "errors": ["Only resolved or closed tickets can be reopened."]}

    timestamp = now_iso()
    item["status"] = "Investigating" if has_support_activity(item) else "Submitted"
    append_timeline_event(item, "Reopened", user, "user", timestamp=timestamp, status=item["status"])
    item["updated_at"] = timestamp
    queue_support_notification(item, "ticket_reopened")
    save_feedback_payload(payload)
    return {"ok": True, "feedback": feedback_view(item, user)}


def has_support_activity(item):
    if str(item.get("admin_notes") or "").strip() or str(item.get("resolution_notes") or "").strip():
        return True

    return any(
        (entry or {}).get("actorType") == "support"
        or clean_timeline_event((entry or {}).get("event") or (entry or {}).get("status")) in {
            "Acknowledged",
            "Investigating",
            "Support Update Added",
            "Resolution Notes Added",
            "Resolved",
        }
        for entry in item.get("timeline", [])
        if isinstance(entry, dict)
    )


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
    feedback_id = normalize_feedback_id_lookup(feedback_id)
    return next(
        (
            item
            for item in payload.get("feedback", [])
            if normalize_feedback_id_lookup(item.get("feedback_id")) == feedback_id
        ),
        None,
    )


def normalize_feedback_id_lookup(feedback_id):
    feedback_id = str(feedback_id or "").strip().upper()
    feedback_id = feedback_id[1:] if feedback_id.startswith("#") else feedback_id
    return feedback_id[4:] if feedback_id.startswith("RSL-") else feedback_id


def clean_feedback_type(value):
    value = str(value or "").strip()
    return value if value in FEEDBACK_TYPES else ""


def clean_status(value):
    value = str(value or "").strip()
    value = LEGACY_STATUS_MAP.get(value, value)
    return value if value in FEEDBACK_STATUSES else ""


def clean_priority(value):
    value = str(value or "").strip().title()
    return value if value in FEEDBACK_PRIORITIES else ""


def clean_timeline_event(value):
    value = str(value or "").strip()
    value = LEGACY_STATUS_MAP.get(value, value)
    if value in FEEDBACK_STATUSES or value in TIMELINE_EVENTS:
        return value
    return ""


def clean_author_type(value):
    value = str(value or "").strip().lower()
    return value if value in {"user", "support", "system"} else ""


def infer_actor_type(actor_email, event):
    actor_email = str(actor_email or "").strip()
    event = str(event or "").strip()

    if get_public_support_identity(actor_email) == SUPPORT_EMAIL or event in {
        "Acknowledged",
        "Investigating",
        "Support Update Added",
        "Resolution Notes Added",
        "Resolved",
        "Closed",
    }:
        return "support"

    return "system" if actor_email.lower() == "system" or not actor_email else "user"


def is_feedback_admin(user):
    return is_admin_user(user)


def secure_feedback_id(feedback_id):
    return re.sub(r"[^A-Za-z0-9_-]+", "", str(feedback_id or ""))[:40] or uuid.uuid4().hex


def format_display_datetime(value):
    parsed = parse_iso_datetime(value)

    if not parsed:
        return ""

    hour = parsed.strftime("%I").lstrip("0") or "0"
    minute = parsed.strftime("%M")
    meridiem = parsed.strftime("%p")
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year} {hour}:{minute} {meridiem} UTC"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None
