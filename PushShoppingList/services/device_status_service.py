import json
import os
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path

from PushShoppingList.services.storage_service import GUEST_DATA_DIR
from PushShoppingList.services.storage_service import PACKAGE_DIR
from PushShoppingList.services.storage_service import USER_DATA_DIR
from PushShoppingList.services.storage_service import safe_user_id
from PushShoppingList.services.guest_session_service import load_guest_sessions
from PushShoppingList.services.user_account_service import display_datetime
from PushShoppingList.services.user_account_service import load_users
from PushShoppingList.services.user_account_service import user_display_name


DEVICE_STATUS_EVENTS_FILE = "device_status_events.json"
DEVICE_STATUS_MAX_EVENTS = 500
DEVICE_STATUS_ACTIVE_MINUTES = 60


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def current_utc():
    return datetime.now(timezone.utc)


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


def parse_status_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def minutes_since_status_datetime(value, reference_time=None):
    parsed = parse_status_datetime(value)
    if not parsed:
        return None

    reference = reference_time or current_utc()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    else:
        reference = reference.astimezone(timezone.utc)

    minutes = (reference - parsed).total_seconds() / 60
    return round(max(0.0, minutes), 1)


def device_activity_key(last_active_at, is_stale=False, reference_time=None):
    inactive_minutes = minutes_since_status_datetime(
        last_active_at,
        reference_time=reference_time,
    )
    if inactive_minutes is None:
        return "inactive" if is_stale else "active"

    return "active" if inactive_minutes < DEVICE_STATUS_ACTIVE_MINUTES else "inactive"


def device_activity_label(activity_key):
    return "Recently active" if activity_key == "active" else "Inactive"


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


def record_device_status_event(payload, request_user_agent="", session_user_id="", guest_session_id=""):
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


def record_device_stale_event(payload, request_user_agent="", session_user_id="", guest_session_id=""):
    return record_device_status_event(
        payload,
        request_user_agent=request_user_agent,
        session_user_id=session_user_id,
        guest_session_id=guest_session_id,
    )


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


def guest_session_lookup():
    lookup = {}
    payload = load_guest_sessions()

    for record in payload.get("guest_sessions", []):
        if not isinstance(record, dict):
            continue

        session_id = str(record.get("id") or record.get("session_id") or "").strip()
        if not session_id:
            continue

        lookup[session_id] = record

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
        demo_status = ""
        if event.get("guest_session_expired") is True:
            demo_status = " expired"
        elif event.get("guest_session_expires_at") or event.get("guest_session_active"):
            demo_status = " Active"

        return f"Guest Demo{demo_status} {short_device_identity(guest_session_id)}"

    return "Unlinked Browser"


def device_status_group_key(event):
    if str(event.get("guest_session_id") or "").strip():
        return "group:guest-demo"

    if str(event.get("user_id") or "").strip() or str(event.get("account_email") or "").strip():
        return "group:active-account"

    return "group:unlinked-browser"


def device_status_group_keys(event):
    keys = [device_status_group_key(event)]
    if str(event.get("guest_session_id") or "").strip():
        if event.get("guest_session_expired") is True:
            keys.append("group:guest-demo-expired")
        elif event.get("guest_session_expires_at") or event.get("guest_session_active"):
            keys.append("group:guest-demo-active")

    return keys


def device_status_group_keys_value(event):
    return " ".join(device_status_group_keys(event))


def device_identity_score(event):
    event = event if isinstance(event, dict) else {}

    if event.get("account_email") and event.get("user_id"):
        return 4

    if event.get("user_id"):
        return 3

    if event.get("guest_session_id"):
        return 2

    return 0


def device_event_sort_key(event):
    return str(event.get("timestamp") or event.get("created_at") or "")


def stronger_device_identity(candidate, current):
    candidate_score = device_identity_score(candidate)
    current_score = device_identity_score(current or {})

    if candidate_score != current_score:
        return candidate_score > current_score

    return device_event_sort_key(candidate) > device_event_sort_key(current or {})


def device_identity_lookup(events):
    lookup = {}

    for event in events if isinstance(events, list) else []:
        device_id = str(event.get("device_id") or "").strip()
        if not device_id or device_identity_score(event) <= 0:
            continue

        if stronger_device_identity(event, lookup.get(device_id)):
            lookup[device_id] = event

    return lookup


def apply_device_identity_match(event, identity_event):
    if device_identity_score(event) > 0 or device_identity_score(identity_event) <= 0:
        return event

    matched = dict(event)
    matched["matched_identity_from_device"] = True
    matched["user_id"] = str(identity_event.get("user_id") or "")
    matched["guest_session_id"] = str(identity_event.get("guest_session_id") or "")
    matched["account_email"] = str(identity_event.get("account_email") or "")
    matched["account_display_name"] = str(identity_event.get("account_display_name") or "")

    for key in (
        "guest_session_expires_at",
        "guest_session_expires_label",
        "guest_session_active",
        "guest_session_expired",
        "guest_session_remaining_label",
    ):
        if key in identity_event:
            matched[key] = identity_event.get(key)

    matched["device_filter_key"] = device_status_filter_key(matched)
    matched["device_filter_label"] = device_status_filter_label(matched)
    matched["device_status_group_key"] = device_status_group_key(matched)
    matched["device_status_group_keys"] = device_status_group_keys_value(matched)
    return matched


def device_status_summary_key(event):
    device_id = str(event.get("device_id") or "").strip()
    if device_id and device_id != "guest-session":
        return device_id

    return "|".join([
        event.get("user_id") or event.get("guest_session_id") or "anonymous",
        device_id,
        event.get("route") or "",
    ])


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


def device_status_account_type_filter_options(events):
    group_labels = [
        ("group:guest-demo", "Guest Demo accounts"),
        ("group:active-account", "Active accounts"),
    ]
    group_counts = {key: 0 for key, _label in group_labels}

    for event in events if isinstance(events, list) else []:
        for group_key in set(device_status_group_keys(event)):
            if group_key in group_counts:
                group_counts[group_key] += 1

    return [
        {"key": key, "label": f"{label} ({group_counts[key]})"}
        for key, label in group_labels
        if group_counts.get(key)
    ]


def guest_expiry_context(guest_record):
    if not isinstance(guest_record, dict):
        return {}

    expires_at = str(guest_record.get("expires_at") or "").strip()
    expires_datetime = parse_status_datetime(expires_at)
    reference_time = current_utc()
    remaining_seconds = 0
    if expires_datetime:
        remaining_seconds = max(0, int((expires_datetime - reference_time).total_seconds()))

    hours = remaining_seconds // 3600
    minutes = (remaining_seconds % 3600) // 60
    active = bool(guest_record.get("is_active"))
    expired = not active or not expires_datetime or expires_datetime <= reference_time
    return {
        "guest_session_expires_at": expires_at,
        "guest_session_expires_label": display_datetime(expires_at) or expires_at,
        "guest_session_active": active,
        "guest_session_expired": expired,
        "guest_session_remaining_label": f"{hours:02d}:{minutes:02d}",
    }


def device_status_event_for_render(entry, account_lookup=None, guest_lookup=None):
    timestamp = str(entry.get("timestamp") or entry.get("created_at") or "")
    last_active_at = str(entry.get("last_active_at") or "")
    user_id = str(entry.get("user_id") or "")
    guest_session_id = str(entry.get("guest_session_id") or "")
    account = (account_lookup or {}).get(user_id, {})
    guest_context = guest_expiry_context((guest_lookup or {}).get(guest_session_id))
    is_stale = bool(entry.get("is_stale"))
    current_minutes_inactive = minutes_since_status_datetime(last_active_at)
    activity_key = device_activity_key(last_active_at, is_stale=is_stale)
    event = {
        "event_id": str(entry.get("event_id") or ""),
        "user_id": user_id,
        "guest_session_id": guest_session_id,
        "device_id": str(entry.get("device_id") or ""),
        "route": str(entry.get("route") or ""),
        "stale_reason": str(entry.get("stale_reason") or "stale"),
        "is_stale": is_stale,
        "activity_key": activity_key,
        "activity_label": device_activity_label(activity_key),
        "account_email": str(account.get("account_email") or ""),
        "account_display_name": str(account.get("account_display_name") or ""),
        "timestamp": timestamp,
        "timestamp_label": display_datetime(timestamp) or timestamp,
        "last_active_at": last_active_at,
        "last_active_label": display_datetime(last_active_at) or last_active_at or "Unknown",
        "minutes_inactive": current_minutes_inactive if current_minutes_inactive is not None else entry.get("minutes_inactive", 0),
        "minutes_hidden": entry.get("minutes_hidden", 0),
        "user_agent": str(entry.get("user_agent") or ""),
        "device_label": device_label_from_user_agent(entry.get("user_agent")),
        "matched_identity_from_device": bool(entry.get("matched_identity_from_device")),
        **guest_context,
    }
    event["device_filter_key"] = device_status_filter_key(event)
    event["device_filter_label"] = device_status_filter_label(event)
    event["device_status_group_key"] = device_status_group_key(event)
    event["device_status_group_keys"] = device_status_group_keys_value(event)
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


def recent_device_status_events(limit=20, account_lookup=None, guest_lookup=None):
    events = []
    for path, scope in iter_status_event_files():
        events.extend(load_events_from_file(path, scope))

    events = sorted(
        events,
        key=lambda entry: str(entry.get("timestamp") or entry.get("created_at") or ""),
        reverse=True,
    )
    return [
        device_status_event_for_render(
            entry,
            account_lookup=account_lookup,
            guest_lookup=guest_lookup,
        )
        for entry in events[:limit]
    ]


def guest_session_expiration_events(guest_lookup=None, represented_guest_ids=None):
    represented_guest_ids = set(represented_guest_ids or [])
    reference_time = current_utc()
    rendered = []

    for session_id, record in (guest_lookup or {}).items():
        if session_id in represented_guest_ids or not isinstance(record, dict):
            continue

        expires_at = str(record.get("expires_at") or "").strip()
        expires_datetime = parse_status_datetime(expires_at)
        is_active = bool(record.get("is_active"))
        if is_active and expires_datetime and expires_datetime > reference_time:
            continue

        timestamp = str(
            record.get("ended_at")
            or expires_at
            or record.get("used_at")
            or record.get("created_at")
            or now_iso()
        )
        last_active_at = str(record.get("used_at") or record.get("created_at") or expires_at)
        rendered.append(device_status_event_for_render(
            {
                "event_id": f"guest-expired-{session_id}",
                "guest_session_id": session_id,
                "device_id": "guest-session",
                "route": "/guest/expired",
                "stale_reason": "guest-demo-expired",
                "is_stale": True,
                "timestamp": timestamp,
                "last_active_at": last_active_at,
                "minutes_inactive": 0,
                "minutes_hidden": 0,
                "user_agent": "Guest demo session expired after 24 hours.",
            },
            guest_lookup=guest_lookup,
        ))

    return sorted(
        rendered,
        key=lambda event: str(event.get("timestamp") or event.get("created_at") or ""),
        reverse=True,
    )


def device_status_summary(limit=20):
    latest_by_device = {}
    account_lookup = account_identity_lookup()
    guests = guest_session_lookup()
    events = recent_device_status_events(
        limit=DEVICE_STATUS_MAX_EVENTS,
        account_lookup=account_lookup,
        guest_lookup=guests,
    )
    represented_guest_ids = {
        str(event.get("guest_session_id") or "").strip()
        for event in events
        if str(event.get("guest_session_id") or "").strip()
    }
    events.extend(guest_session_expiration_events(
        guest_lookup=guests,
        represented_guest_ids=represented_guest_ids,
    ))
    events = sorted(
        events,
        key=lambda event: str(event.get("timestamp") or event.get("created_at") or ""),
        reverse=True,
    )
    identity_by_device = device_identity_lookup(events)

    for event in events:
        device_id = str(event.get("device_id") or "").strip()
        event = apply_device_identity_match(event, identity_by_device.get(device_id))
        device_key = device_status_summary_key(event)
        if device_key not in latest_by_device:
            latest_by_device[device_key] = event

    return list(latest_by_device.values())[:limit]
