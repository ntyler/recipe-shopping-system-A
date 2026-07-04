import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from PushShoppingList.services.storage_service import GUEST_DATA_DIR
from PushShoppingList.services.storage_service import PACKAGE_DIR
from PushShoppingList.services.storage_service import USER_DATA_DIR
from PushShoppingList.services.storage_service import safe_user_id
from PushShoppingList.services.user_account_service import display_datetime
from PushShoppingList.services.user_account_service import load_users
from PushShoppingList.services.user_account_service import user_display_name


DEVICE_STATUS_EVENTS_FILE = "device_status_events.json"
DEVICE_STATUS_MAX_EVENTS = 500


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def clamp_string(value, limit=500):
    return str(value or "").strip()[:limit]


def clamp_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if number < 0:
        return 0.0

    return round(number, 2)


def device_status_events_path(user_id="", guest_session_id=""):
    safe_id = safe_user_id(user_id)
    if safe_id:
        return USER_DATA_DIR / safe_id / DEVICE_STATUS_EVENTS_FILE

    safe_guest_id = safe_user_id(guest_session_id)
    if safe_guest_id:
        return GUEST_DATA_DIR / safe_guest_id / DEVICE_STATUS_EVENTS_FILE

    return Path(os.getenv(
        "SHOPPING_APP_DEVICE_STATUS_EVENTS_FILE",
        PACKAGE_DIR / DEVICE_STATUS_EVENTS_FILE,
    ))


def load_device_status_events(user_id="", guest_session_id=""):
    path = device_status_events_path(user_id=user_id, guest_session_id=guest_session_id)
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = payload.get("entries", []) if isinstance(payload, dict) else payload
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("device_id")
    ]


def save_device_status_events(entries, user_id="", guest_session_id=""):
    path = device_status_events_path(user_id=user_id, guest_session_id=guest_session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"entries": entries[-DEVICE_STATUS_MAX_EVENTS:]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize_device_status_event(payload, request_user_agent="", session_user_id="", guest_session_id=""):
    payload = payload if isinstance(payload, dict) else {}
    user_id = clamp_string(session_user_id or payload.get("user_id"), 120)
    device_id = clamp_string(payload.get("device_id"), 120) or uuid.uuid4().hex
    timestamp = clamp_string(payload.get("timestamp"), 80) or now_iso()
    user_agent = clamp_string(payload.get("user_agent") or request_user_agent, 500)

    return {
        "event_id": uuid.uuid4().hex,
        "user_id": user_id,
        "guest_session_id": clamp_string(guest_session_id, 120),
        "device_id": device_id,
        "route": clamp_string(payload.get("route"), 300),
        "stale_reason": clamp_string(payload.get("stale_reason"), 120),
        "is_stale": bool(payload.get("is_stale", True)),
        "timestamp": timestamp,
        "last_active_at": clamp_string(payload.get("last_active_at"), 80),
        "created_at": now_iso(),
        "minutes_inactive": clamp_float(payload.get("minutes_inactive")),
        "minutes_hidden": clamp_float(payload.get("minutes_hidden")),
        "user_agent": user_agent,
    }


def record_device_stale_event(payload, request_user_agent="", session_user_id="", guest_session_id=""):
    event = normalize_device_status_event(
        payload,
        request_user_agent=request_user_agent,
        session_user_id=session_user_id,
        guest_session_id=guest_session_id,
    )
    entries = load_device_status_events(
        user_id=event.get("user_id"),
        guest_session_id=event.get("guest_session_id"),
    )
    entries.append(event)
    save_device_status_events(
        entries,
        user_id=event.get("user_id"),
        guest_session_id=event.get("guest_session_id"),
    )
    return event


def device_label_from_user_agent(user_agent):
    ua = str(user_agent or "")
    browser = "Browser"
    platform = "Device"

    browser_patterns = [
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Chrome/", "Chrome"),
        ("Firefox/", "Firefox"),
        ("Safari/", "Safari"),
    ]
    platform_patterns = [
        ("Windows", "Windows"),
        ("Android", "Android"),
        ("iPhone", "iPhone"),
        ("iPad", "iPad"),
        ("Mac OS X", "Mac"),
        ("Linux", "Linux"),
    ]

    for needle, label in browser_patterns:
        if needle in ua:
            browser = label
            break

    for needle, label in platform_patterns:
        if needle in ua:
            platform = label
            break

    return f"{browser} on {platform}"


def account_identity_lookup():
    lookup = {}
    for user in load_users().get("users", []):
        user_id = str(user.get("user_id") or "").strip()
        if not user_id:
            continue

        lookup[user_id] = {
            "account_email": str(user.get("email") or "").strip(),
            "account_display_name": user_display_name(user),
        }

    return lookup


def short_device_identity(value):
    text = str(value or "").strip()
    if len(text) <= 16:
        return text

    return f"{text[:12]}..."


def device_status_filter_key(event):
    user_id = str(event.get("user_id") or "").strip()
    guest_session_id = str(event.get("guest_session_id") or "").strip()

    if event.get("account_email") and user_id:
        return f"account:{user_id}"

    if user_id:
        return f"user:{user_id}"

    if guest_session_id:
        return f"guest:{guest_session_id}"

    return "anonymous"


def device_status_filter_label(event):
    if event.get("account_email"):
        display = str(event.get("account_display_name") or event.get("account_email") or "").strip()
        email = str(event.get("account_email") or "").strip()
        if display and display != email:
            return f"{display} - {email}"

        return email

    user_id = str(event.get("user_id") or "").strip()
    if user_id:
        return f"User {short_device_identity(user_id)}"

    guest_session_id = str(event.get("guest_session_id") or "").strip()
    if guest_session_id:
        return f"Guest {short_device_identity(guest_session_id)}"

    return "Anonymous"


def device_status_filter_options(events):
    options = []
    seen = set()

    for event in events if isinstance(events, list) else []:
        key = str(event.get("device_filter_key") or device_status_filter_key(event))
        if not key or key in seen:
            continue

        seen.add(key)
        options.append({
            "key": key,
            "label": str(event.get("device_filter_label") or device_status_filter_label(event)),
        })

    return sorted(options, key=lambda option: option.get("label", "").lower())


def device_status_event_for_render(entry, account_lookup=None):
    timestamp = str(entry.get("timestamp") or entry.get("created_at") or "")
    last_active_at = str(entry.get("last_active_at") or "")
    user_id = str(entry.get("user_id") or "")
    account = (account_lookup or {}).get(user_id, {})
    event = {
        "event_id": str(entry.get("event_id") or ""),
        "user_id": user_id,
        "guest_session_id": str(entry.get("guest_session_id") or ""),
        "device_id": str(entry.get("device_id") or ""),
        "route": str(entry.get("route") or ""),
        "stale_reason": str(entry.get("stale_reason") or "stale"),
        "is_stale": bool(entry.get("is_stale")),
        "account_email": str(account.get("account_email") or ""),
        "account_display_name": str(account.get("account_display_name") or ""),
        "timestamp": timestamp,
        "timestamp_label": display_datetime(timestamp) or timestamp,
        "last_active_at": last_active_at,
        "last_active_label": display_datetime(last_active_at) or last_active_at or "Unknown",
        "minutes_inactive": entry.get("minutes_inactive", 0),
        "minutes_hidden": entry.get("minutes_hidden", 0),
        "user_agent": str(entry.get("user_agent") or ""),
        "device_label": device_label_from_user_agent(entry.get("user_agent")),
    }
    event["device_filter_key"] = device_status_filter_key(event)
    event["device_filter_label"] = device_status_filter_label(event)
    return event


def iter_status_event_files():
    roots = [
        (USER_DATA_DIR, "user"),
        (GUEST_DATA_DIR, "guest"),
    ]

    for root, scope in roots:
        if not root.exists():
            continue

        try:
            paths = root.glob(f"*/{DEVICE_STATUS_EVENTS_FILE}")
        except OSError:
            continue

        for path in paths:
            yield path, scope

    fallback = device_status_events_path()
    if fallback.exists():
        yield fallback, "anonymous"


def load_events_from_file(path, scope):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    entries = payload.get("entries", []) if isinstance(payload, dict) else payload
    rendered = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        event = dict(entry)
        event["storage_scope"] = scope
        if scope == "user" and not event.get("user_id"):
            event["user_id"] = path.parent.name
        if scope == "guest" and not event.get("guest_session_id"):
            event["guest_session_id"] = path.parent.name
        rendered.append(event)

    return rendered


def recent_device_status_events(limit=20, account_lookup=None):
    events = []
    for path, scope in iter_status_event_files():
        events.extend(load_events_from_file(path, scope))

    events = sorted(
        events,
        key=lambda entry: str(entry.get("timestamp") or entry.get("created_at") or ""),
        reverse=True,
    )
    return [
        device_status_event_for_render(entry, account_lookup=account_lookup)
        for entry in events[:limit]
    ]


def device_status_summary(limit=20):
    latest_by_device = {}
    account_lookup = account_identity_lookup()

    for event in recent_device_status_events(
        limit=DEVICE_STATUS_MAX_EVENTS,
        account_lookup=account_lookup,
    ):
        device_key = "|".join([
            event.get("user_id") or event.get("guest_session_id") or "anonymous",
            event.get("device_id") or "",
        ])
        if device_key not in latest_by_device:
            latest_by_device[device_key] = event

    return list(latest_by_device.values())[:limit]
