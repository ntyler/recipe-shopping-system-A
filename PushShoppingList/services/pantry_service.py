import json
import os
import re
import uuid
from datetime import datetime
from datetime import date
from datetime import timedelta
from pathlib import Path

from werkzeug.utils import secure_filename

from PushShoppingList.services import storage_service
from PushShoppingList.services.storage_service import scoped_package_path


# AI Pantry storage is intentionally local-file based for the MVP.
PANTRY_INVENTORY_FILENAME = "pantry_inventory.json"
PANTRY_INVENTORY_FILE = scoped_package_path("pantry_inventory.json")
PANTRY_RECEIPT_HISTORY_FILE = scoped_package_path("pantry_receipt_history.json")
PANTRY_RECEIPT_UPLOAD_DIR = scoped_package_path("pantry_receipts")
PANTRY_DATE_FIELDS = (
    "purchased_date",
    "opened_date",
    "expiration_date",
    "freeze_by_date",
    "reminder_dismissed_until",
)
PANTRY_STATUS_VALUES = {"available", "opened", "frozen", "used"}
PANTRY_STORAGE_LOCATION_VALUES = {"pantry", "fridge", "freezer", "counter", "unknown"}
DEFAULT_REMINDER_OFFSETS_DAYS = [1]

DEFAULT_CONFIDENCE_BY_SOURCE = {
    "shopping_list": 0.90,
    "receipt": 0.85,
    "manual": 0.75,
    "photo": 0.60,
    "barcode": 0.95,
}

SOURCE_VALUES = set(DEFAULT_CONFIDENCE_BY_SOURCE.keys())
RECEIPT_SKIP_WORDS = {
    "total",
    "subtotal",
    "tax",
    "visa",
    "mastercard",
    "amex",
    "discover",
    "debit",
    "credit",
    "cash",
    "change",
    "balance",
    "approval",
    "auth",
    "card",
    "tender",
    "receipt",
}

BRAND_AND_STORE_WORDS = {
    "aldi",
    "kroger",
    "walmart",
    "meijer",
    "target",
    "costco",
    "great",
    "value",
    "market",
    "pantry",
    "private",
    "selection",
    "good",
    "gather",
    "simply",
    "nature",
    "organic",
}

VARIANT_NORMALIZATION = {
    "diced tomatoes": "tomato",
    "canned tomatoes": "tomato",
    "crushed tomatoes": "tomato",
    "tomatoes": "tomato",
    "whole milk": "milk",
    "jasmine rice": "rice",
    "brown rice": "rice",
    "white rice": "rice",
    "eggs": "egg",
}

SHELF_LIFE_RULES = (
    {
        "terms": ("chicken broth", "beef broth", "vegetable broth", "broth", "stock"),
        "storage_location": "fridge",
        "opened_days": 10,
        "fridge_days": 10,
        "freeze_by_days": 7,
    },
    {
        "terms": ("chicken breast", "chicken breasts", "raw chicken", "chicken"),
        "storage_location": "fridge",
        "fridge_days": 2,
        "freeze_by_days": 1,
    },
    {
        "terms": ("ground beef", "ground turkey", "ground pork", "ground meat"),
        "storage_location": "fridge",
        "fridge_days": 2,
        "freeze_by_days": 1,
    },
    {
        "terms": ("fish", "salmon", "tilapia", "cod", "shrimp", "seafood"),
        "storage_location": "fridge",
        "fridge_days": 1,
        "freeze_by_days": 1,
    },
    {
        "terms": ("beef", "pork", "steak", "roast", "meat"),
        "storage_location": "fridge",
        "fridge_days": 3,
        "freeze_by_days": 2,
    },
    {
        "terms": ("lettuce", "spinach", "greens", "leafy greens", "herbs", "cilantro", "parsley"),
        "storage_location": "fridge",
        "fridge_days": 5,
    },
    {
        "terms": ("berries", "strawberries", "blueberries", "raspberries"),
        "storage_location": "fridge",
        "fridge_days": 4,
    },
    {
        "terms": ("vegetable", "vegetables", "broccoli", "pepper", "peppers", "zucchini", "mushroom", "mushrooms"),
        "storage_location": "fridge",
        "fridge_days": 7,
    },
    {
        "terms": ("milk", "cream", "half and half"),
        "storage_location": "fridge",
        "opened_days": 7,
        "fridge_days": 7,
    },
)


def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def today_iso():
    return datetime.utcnow().date().isoformat()


def pantry_inventory_path(user_id=None, guest_session_id=None):
    user_id = storage_service.safe_user_id(user_id)
    guest_session_id = storage_service.safe_user_id(guest_session_id)

    if user_id:
        return storage_service.user_data_root(user_id) / PANTRY_INVENTORY_FILENAME
    if guest_session_id:
        return storage_service.guest_data_root(guest_session_id) / PANTRY_INVENTORY_FILENAME
    return PANTRY_INVENTORY_FILE


def load_pantry_inventory(user_id=None, guest_session_id=None):
    inventory_path = pantry_inventory_path(user_id=user_id, guest_session_id=guest_session_id)

    if not inventory_path.exists():
        return {"items": []}

    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"items": []}

    if not isinstance(payload, dict):
        return {"items": []}

    return {
        "items": [
            normalize_pantry_item(item)
            for item in payload.get("items", [])
            if isinstance(item, dict)
        ],
    }


def save_pantry_inventory(payload, user_id=None, guest_session_id=None):
    inventory_path = pantry_inventory_path(user_id=user_id, guest_session_id=guest_session_id)
    normalized = {
        "items": [
            normalize_pantry_item(item)
            for item in payload.get("items", [])
            if isinstance(item, dict)
        ],
    }
    inventory_path.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return normalized


def normalize_pantry_item(item):
    timestamp = str(item.get("date_added") or now_iso())
    source = clean_source(item.get("source"))
    ingredient_name = str(item.get("ingredient_name") or item.get("product_name") or "").strip()
    normalized_name = normalize_ingredient_name(item.get("normalized_name") or ingredient_name)
    opened_date = normalize_date_value(item.get("opened_date"))
    storage_location = clean_storage_location(item.get("storage_location"))
    status = clean_pantry_status(item.get("status") or ("opened" if opened_date else "available"))

    return {
        "id": str(item.get("id") or uuid.uuid4().hex),
        "ingredient_name": ingredient_name,
        "normalized_name": normalized_name,
        "product_name": str(item.get("product_name") or "").strip(),
        "store": str(item.get("store") or "").strip(),
        "quantity": parse_quantity(item.get("quantity"), default=1),
        "unit": str(item.get("unit") or "").strip(),
        "category": str(item.get("category") or "").strip(),
        "source": source,
        "confidence": clamp_confidence(item.get("confidence"), DEFAULT_CONFIDENCE_BY_SOURCE[source]),
        "date_added": timestamp,
        "last_updated": str(item.get("last_updated") or timestamp),
        "notes": str(item.get("notes") or "").strip(),
        "purchased_date": normalize_date_value(item.get("purchased_date")),
        "opened_date": opened_date,
        "expiration_date": normalize_date_value(item.get("expiration_date")),
        "freeze_by_date": normalize_date_value(item.get("freeze_by_date")),
        "storage_location": storage_location,
        "status": status,
        "reminder_enabled": clean_bool(item.get("reminder_enabled"), default=True),
        "reminder_offsets_days": normalize_reminder_offsets(item.get("reminder_offsets_days")),
        "reminder_dismissed_until": normalize_date_value(item.get("reminder_dismissed_until")),
        "last_reminded_at": str(item.get("last_reminded_at") or "").strip(),
        "last_reminder_key": str(item.get("last_reminder_key") or "").strip(),
    }


def clean_source(source):
    source = str(source or "manual").strip().lower()
    return source if source in SOURCE_VALUES else "manual"


def clean_storage_location(value):
    value = str(value or "").strip().lower()
    aliases = {
        "refrigerator": "fridge",
        "refrigerated": "fridge",
        "freezer-safe": "freezer",
        "cupboard": "pantry",
        "shelf": "pantry",
    }
    value = aliases.get(value, value)
    return value if value in PANTRY_STORAGE_LOCATION_VALUES else ""


def clean_pantry_status(value):
    value = str(value or "").strip().lower()
    aliases = {
        "open": "opened",
        "done": "used",
        "finished": "used",
        "gone": "used",
    }
    value = aliases.get(value, value)
    return value if value in PANTRY_STATUS_VALUES else "available"


def clean_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def normalize_reminder_offsets(value):
    if value is None or value == "":
        return list(DEFAULT_REMINDER_OFFSETS_DAYS)

    raw_values = value
    if isinstance(value, str):
        raw_values = re.split(r"[,;\s]+", value.strip())
    elif not isinstance(value, (list, tuple, set)):
        raw_values = [value]

    offsets = []
    for raw in raw_values:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= offset <= 30 and offset not in offsets:
            offsets.append(offset)

    return sorted(offsets) if offsets else list(DEFAULT_REMINDER_OFFSETS_DAYS)


def normalize_date_value(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value or "").strip()
    if not text:
        return ""

    for parser in (
        lambda raw: datetime.fromisoformat(raw.replace("Z", "")).date(),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d").date(),
        lambda raw: datetime.strptime(raw, "%m/%d/%Y").date(),
        lambda raw: datetime.strptime(raw, "%m/%d/%y").date(),
    ):
        try:
            return parser(text).isoformat()
        except (TypeError, ValueError):
            continue

    return ""


def parse_date_value(value):
    normalized = normalize_date_value(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def date_plus_days(value, days):
    parsed = parse_date_value(value)
    if not parsed:
        return ""
    return (parsed + timedelta(days=int(days or 0))).isoformat()


def parse_quantity(value, default=1):
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return default

    if quantity.is_integer():
        return int(quantity)

    return quantity


def clamp_confidence(value, default=0.0):
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default

    return max(0.0, min(1.0, round(confidence, 2)))


def normalize_ingredient_name(name):
    text = str(name or "").lower().strip()
    text = re.sub(r"[$]\d+(?:\.\d{2})?", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:x|ct|count|oz|lb|lbs|g|kg|ml|l|pk|pkg)?\b", " ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    text = " ".join(text.split())

    for phrase, replacement in sorted(VARIANT_NORMALIZATION.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in text:
            return replacement

    words = [word for word in text.split() if word not in BRAND_AND_STORE_WORDS]
    text = " ".join(words).strip()

    if text.endswith("ies") and len(text) > 4:
        text = f"{text[:-3]}y"
    elif text.endswith("es") and len(text) > 3:
        text = text[:-2]
    elif text.endswith("s") and len(text) > 3:
        text = text[:-1]

    return text


def pantry_lifecycle_rule_for_item(item):
    search_text = " ".join(
        str(item.get(key) or "")
        for key in ("ingredient_name", "product_name", "normalized_name", "category", "notes")
    ).lower()
    normalized_name = normalize_ingredient_name(item.get("normalized_name") or item.get("ingredient_name"))
    candidates = f"{search_text} {normalized_name}".strip()

    for rule in SHELF_LIFE_RULES:
        for term in rule.get("terms", ()):
            if term in candidates:
                return rule

    return {}


def apply_lifecycle_suggestions(item, reference_date=None, overwrite=False):
    suggested = normalize_pantry_item(item)
    rule = pantry_lifecycle_rule_for_item(suggested)

    if not rule:
        return suggested

    if not suggested.get("storage_location"):
        suggested["storage_location"] = rule.get("storage_location", "")

    if suggested.get("storage_location") == "freezer":
        suggested["status"] = "frozen"
        return suggested

    base_date = (
        suggested.get("opened_date")
        or suggested.get("purchased_date")
        or normalize_date_value(reference_date)
    )

    if not base_date:
        return suggested

    is_opened = suggested.get("status") == "opened" or bool(suggested.get("opened_date"))
    expiration_days = rule.get("opened_days") if is_opened else None
    if expiration_days is None and suggested.get("storage_location") in {"fridge", ""}:
        expiration_days = rule.get("fridge_days")
    if expiration_days is None and suggested.get("storage_location") == "pantry":
        expiration_days = rule.get("pantry_days")

    if expiration_days is not None and (overwrite or not suggested.get("expiration_date")):
        suggested["expiration_date"] = date_plus_days(base_date, expiration_days)

    freeze_by_days = rule.get("freeze_by_days")
    if freeze_by_days is not None and suggested.get("status") != "frozen" and (overwrite or not suggested.get("freeze_by_date")):
        suggested["freeze_by_date"] = date_plus_days(base_date, freeze_by_days)

    return suggested


def prepare_pantry_item_for_add(item, reference_date=None):
    reference = normalize_date_value(reference_date) or today_iso()
    prepared = dict(item or {})
    if not any(prepared.get(field) for field in ("purchased_date", "opened_date", "expiration_date", "freeze_by_date")):
        prepared["purchased_date"] = reference
    if prepared.get("opened_date") and not prepared.get("status"):
        prepared["status"] = "opened"
    return apply_lifecycle_suggestions(prepared, reference_date=reference)


def add_or_increment_pantry_item(item, user_id=None, guest_session_id=None, reference_date=None):
    payload = load_pantry_inventory(user_id=user_id, guest_session_id=guest_session_id)
    incoming = normalize_pantry_item({
        **prepare_pantry_item_for_add(item, reference_date=reference_date),
        "normalized_name": normalize_ingredient_name(
            item.get("normalized_name")
            or item.get("ingredient_name")
            or item.get("product_name")
        ),
    })
    timestamp = now_iso()

    for existing in payload["items"]:
        if existing.get("normalized_name") == incoming["normalized_name"]:
            existing["quantity"] = parse_quantity(existing.get("quantity"), default=0) + parse_quantity(
                incoming.get("quantity"),
                default=1,
            )
            if incoming.get("product_name"):
                existing["product_name"] = incoming["product_name"]
            if incoming.get("store"):
                existing["store"] = incoming["store"]
            if incoming.get("unit"):
                existing["unit"] = incoming["unit"]
            if incoming.get("category"):
                existing["category"] = incoming["category"]
            existing["source"] = incoming["source"]
            existing["confidence"] = max(existing.get("confidence", 0.0), incoming["confidence"])
            existing["last_updated"] = timestamp
            existing["notes"] = incoming.get("notes") or existing.get("notes", "")
            for field in PANTRY_DATE_FIELDS:
                if incoming.get(field) and not existing.get(field):
                    existing[field] = incoming[field]
            for field in ["storage_location", "status"]:
                if incoming.get(field) and not existing.get(field):
                    existing[field] = incoming[field]
            if incoming.get("reminder_offsets_days") and not existing.get("reminder_offsets_days"):
                existing["reminder_offsets_days"] = incoming["reminder_offsets_days"]
            save_pantry_inventory(payload, user_id=user_id, guest_session_id=guest_session_id)
            return {"item": existing, "created": False}

    incoming["date_added"] = timestamp
    incoming["last_updated"] = timestamp
    payload["items"].append(incoming)
    save_pantry_inventory(payload, user_id=user_id, guest_session_id=guest_session_id)
    return {"item": incoming, "created": True}


def update_pantry_item(item_id, updates, user_id=None, guest_session_id=None, suggest_dates=False):
    payload = load_pantry_inventory(user_id=user_id, guest_session_id=guest_session_id)

    for item in payload["items"]:
        if item.get("id") != item_id:
            continue

        for field in ["quantity", "unit", "category", "notes"]:
            if field in updates:
                item[field] = parse_quantity(updates[field]) if field == "quantity" else str(updates[field] or "").strip()

        for field in PANTRY_DATE_FIELDS:
            if field in updates:
                item[field] = normalize_date_value(updates[field])

        if "storage_location" in updates:
            item["storage_location"] = clean_storage_location(updates.get("storage_location"))
        if "status" in updates:
            item["status"] = clean_pantry_status(updates.get("status"))
        if item.get("opened_date") and item.get("status") == "available":
            item["status"] = "opened"
        if item.get("status") == "frozen":
            item["storage_location"] = "freezer"
        if "reminder_enabled" in updates:
            item["reminder_enabled"] = clean_bool(updates.get("reminder_enabled"), default=True)
        if "reminder_offsets_days" in updates:
            item["reminder_offsets_days"] = normalize_reminder_offsets(updates.get("reminder_offsets_days"))
        if suggest_dates:
            item.update(apply_lifecycle_suggestions(item))

        item["last_updated"] = now_iso()
        save_pantry_inventory(payload, user_id=user_id, guest_session_id=guest_session_id)
        return {"ok": True, "item": item}

    return {"ok": False, "error": "Pantry item was not found."}


def update_pantry_item_lifecycle_action(item_id, action, user_id=None, guest_session_id=None, reference_date=None):
    action = str(action or "").strip().lower()
    today = normalize_date_value(reference_date) or today_iso()

    if action == "mark_opened":
        return update_pantry_item(
            item_id,
            {
                "status": "opened",
                "opened_date": today,
                "storage_location": "fridge",
                "reminder_dismissed_until": "",
            },
            user_id=user_id,
            guest_session_id=guest_session_id,
            suggest_dates=True,
        )
    if action == "mark_frozen":
        return update_pantry_item(
            item_id,
            {
                "status": "frozen",
                "storage_location": "freezer",
                "reminder_dismissed_until": "",
            },
            user_id=user_id,
            guest_session_id=guest_session_id,
        )
    if action == "dismiss_today":
        return update_pantry_item(
            item_id,
            {"reminder_dismissed_until": today},
            user_id=user_id,
            guest_session_id=guest_session_id,
        )

    return {"ok": False, "error": "Unsupported pantry action."}


def delete_pantry_item(item_id, user_id=None, guest_session_id=None):
    payload = load_pantry_inventory(user_id=user_id, guest_session_id=guest_session_id)
    before_count = len(payload["items"])
    payload["items"] = [item for item in payload["items"] if item.get("id") != item_id]
    save_pantry_inventory(payload, user_id=user_id, guest_session_id=guest_session_id)
    return {"ok": len(payload["items"]) != before_count}


def confidence_label(confidence):
    confidence = clamp_confidence(confidence)

    if confidence >= 0.85:
        return "High"
    if confidence >= 0.60:
        return "Medium"
    return "Low"


def date_label(value):
    parsed = parse_date_value(value)
    if not parsed:
        return ""
    return parsed.strftime("%b %#d, %Y") if os.name == "nt" else parsed.strftime("%b %-d, %Y")


def pantry_target_dates(item):
    targets = []
    if item.get("freeze_by_date") and item.get("status") != "frozen":
        targets.append({
            "field": "freeze_by_date",
            "date": item.get("freeze_by_date"),
            "label": "Freeze by",
            "action": "freeze",
        })
    if item.get("expiration_date") and item.get("status") not in {"frozen", "used"}:
        targets.append({
            "field": "expiration_date",
            "date": item.get("expiration_date"),
            "label": "Use by",
            "action": "use",
        })
    return sorted(
        targets,
        key=lambda target: parse_date_value(target.get("date")) or date.max,
    )


def pantry_item_lifecycle_status(item, reference_date=None):
    today = parse_date_value(reference_date) or datetime.utcnow().date()
    status = clean_pantry_status(item.get("status"))

    if status == "used":
        return {
            "key": "used",
            "label": "Used",
            "detail": "Marked used",
            "urgency": "done",
            "sort_key": (99, ""),
        }
    if status == "frozen":
        return {
            "key": "frozen",
            "label": "Frozen",
            "detail": "Stored in freezer",
            "urgency": "safe",
            "sort_key": (90, ""),
        }

    targets = pantry_target_dates(item)
    if not targets:
        return {
            "key": "untracked",
            "label": "No date set",
            "detail": "Add an expiration or freeze-by date",
            "urgency": "neutral",
            "sort_key": (80, ""),
        }

    target = targets[0]
    target_date = parse_date_value(target.get("date"))
    days_until = (target_date - today).days if target_date else 9999
    action_text = "freeze" if target.get("action") == "freeze" else "use"

    if days_until < 0:
        label = "Expired?"
        detail = f"{target['label']} was {abs(days_until)} day{'s' if abs(days_until) != 1 else ''} ago"
        urgency = "expired"
        rank = 0
    elif days_until == 0:
        label = "Today"
        detail = f"{target['label']} today"
        urgency = "urgent"
        rank = 1
    elif days_until == 1:
        label = "Use soon"
        detail = f"{target['label']} tomorrow"
        urgency = "soon"
        rank = 2
    elif days_until <= 3:
        label = "Coming up"
        detail = f"{target['label']} in {days_until} days"
        urgency = "soon"
        rank = 3
    else:
        label = "Fresh"
        detail = f"{target['label']} in {days_until} days"
        urgency = "fresh"
        rank = 50

    return {
        "key": target.get("field", ""),
        "label": label,
        "detail": detail,
        "urgency": urgency,
        "target_field": target.get("field", ""),
        "target_date": target.get("date", ""),
        "target_label": target.get("label", ""),
        "action": action_text,
        "days_until": days_until,
        "sort_key": (rank, target.get("date", "")),
    }


def pantry_items_for_view():
    items = sorted(
        load_pantry_inventory()["items"],
        key=lambda item: (item.get("ingredient_name") or item.get("product_name") or "").lower(),
    )

    for item in items:
        item["confidence_label"] = confidence_label(item.get("confidence"))
        item["purchased_date_label"] = date_label(item.get("purchased_date"))
        item["opened_date_label"] = date_label(item.get("opened_date"))
        item["expiration_date_label"] = date_label(item.get("expiration_date"))
        item["freeze_by_date_label"] = date_label(item.get("freeze_by_date"))
        item["lifecycle_status"] = pantry_item_lifecycle_status(item)

    return items


def pantry_use_soon_items_for_view(limit=12):
    urgent_items = []
    for item in pantry_items_for_view():
        lifecycle = item.get("lifecycle_status") or {}
        if lifecycle.get("urgency") not in {"expired", "urgent", "soon"}:
            continue
        urgent_items.append(item)

    return sorted(
        urgent_items,
        key=lambda item: (item.get("lifecycle_status") or {}).get("sort_key", (99, "")),
    )[: max(1, int(limit or 12))]


def pantry_reminder_for_item(item, reference_date=None):
    item = normalize_pantry_item(item)
    today = parse_date_value(reference_date) or datetime.utcnow().date()

    if not item.get("reminder_enabled", True) or item.get("status") in {"frozen", "used"}:
        return None

    dismissed_until = parse_date_value(item.get("reminder_dismissed_until"))
    if dismissed_until and dismissed_until >= today:
        return None

    lifecycle = pantry_item_lifecycle_status(item, reference_date=today)
    target_date = parse_date_value(lifecycle.get("target_date"))
    if not target_date:
        return None

    days_until = int(lifecycle.get("days_until") or 0)
    max_offset = max(normalize_reminder_offsets(item.get("reminder_offsets_days")))
    if days_until > max_offset:
        return None

    item_name = item.get("ingredient_name") or item.get("product_name") or "Pantry item"
    action = lifecycle.get("action") or "use"
    target_label = lifecycle.get("target_label") or "Use by"
    reminder_key = f"{item.get('id')}:{lifecycle.get('target_field')}:{lifecycle.get('target_date')}"
    if item.get("last_reminder_key") == reminder_key:
        return None

    if days_until < 0:
        detail = f"{target_label} was {abs(days_until)} day{'s' if abs(days_until) != 1 else ''} ago."
    elif days_until == 0:
        detail = f"{target_label} is today."
    elif days_until == 1:
        detail = f"{target_label} is tomorrow."
    else:
        detail = f"{target_label} is in {days_until} days."

    return {
        "item_id": item.get("id", ""),
        "item_name": item_name,
        "title": f"Use soon: {item_name}",
        "message": f"{detail} Use this soon or put it in the freezer.",
        "reminder_key": reminder_key,
        "target_field": lifecycle.get("target_field", ""),
        "target_date": lifecycle.get("target_date", ""),
        "days_until": days_until,
        "action": action,
    }


def due_pantry_reminders(user_id, reference_date=None):
    return [
        reminder
        for reminder in (
            pantry_reminder_for_item(item, reference_date=reference_date)
            for item in load_pantry_inventory(user_id=user_id)["items"]
        )
        if reminder
    ]


def mark_pantry_reminder_sent(user_id, item_id, reminder_key, timestamp=None):
    payload = load_pantry_inventory(user_id=user_id)
    timestamp = timestamp or now_iso()
    changed = False

    for item in payload["items"]:
        if item.get("id") != item_id:
            continue
        item["last_reminded_at"] = timestamp
        item["last_reminder_key"] = reminder_key
        item["last_updated"] = timestamp
        changed = True
        break

    if changed:
        save_pantry_inventory(payload, user_id=user_id)

    return changed


def send_due_pantry_reminders(user_ids=None, reference_date=None, dry_run=False):
    from PushShoppingList.services.user_account_service import load_users
    from PushShoppingList.services.user_account_service import send_user_notification

    users = load_users().get("users", [])
    allowed_user_ids = {
        str(user_id or "").strip()
        for user_id in (user_ids or [])
        if str(user_id or "").strip()
    }
    sent = []
    skipped = []
    failed = []

    for user in users:
        user_id = str(user.get("user_id") or "").strip()
        if not user_id or (allowed_user_ids and user_id not in allowed_user_ids):
            continue

        for reminder in due_pantry_reminders(user_id, reference_date=reference_date):
            if dry_run:
                skipped.append({"user_id": user_id, **reminder, "reason": "dry_run"})
                continue

            result = send_user_notification(
                user_id,
                reminder["title"],
                reminder["message"],
                preference_key="pantry_expiration_reminders",
                tags="warning",
                priority="default",
            )
            if result.get("ok"):
                mark_pantry_reminder_sent(user_id, reminder["item_id"], reminder["reminder_key"])
                sent.append({"user_id": user_id, **reminder})
            elif result.get("skipped"):
                skipped.append({"user_id": user_id, **reminder, "reason": result.get("reason", "skipped")})
            else:
                failed.append({"user_id": user_id, **reminder, "error": result.get("error") or result.get("errors") or "send_failed"})

    return {
        "ok": not failed,
        "sent_count": len(sent),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


def parse_receipt_text(receipt_text):
    candidates = []

    for raw_line in str(receipt_text or "").splitlines():
        line = raw_line.strip()
        if not line or should_skip_receipt_line(line):
            continue

        product_name = clean_receipt_product_name(line)
        normalized_name = normalize_ingredient_name(product_name)

        if not normalized_name:
            continue

        candidates.append({
            "raw_line": line,
            "product_name": product_name,
            "normalized_name": normalized_name,
            "quantity": receipt_line_quantity(line),
            "confidence": receipt_line_confidence(product_name),
            "needs_review": True,
        })

    return candidates


def should_skip_receipt_line(line):
    lowered = line.lower()

    if len(re.sub(r"[^a-z]", "", lowered)) < 2:
        return True

    return any(word in lowered for word in RECEIPT_SKIP_WORDS)


def clean_receipt_product_name(line):
    text = re.sub(r"[$]\s*\d+(?:\.\d{2})?", " ", line)
    text = re.sub(r"\b\d{5,}\b", " ", text)
    text = re.sub(r"^\s*\d+\s*[xX]\s*", " ", text)
    text = re.sub(r"[^A-Za-z\s]", " ", text)
    return " ".join(text.split()).title()


def receipt_line_quantity(line):
    match = re.search(r"^\s*(\d+)\s*[xX]\b", line)
    return int(match.group(1)) if match else 1


def receipt_line_confidence(product_name):
    word_count = len(str(product_name or "").split())
    if word_count >= 2:
        return 0.85
    return 0.72


def save_receipt_upload(upload=None, pasted_text=""):
    receipt_id = uuid.uuid4().hex
    timestamp = now_iso()
    stored_path = ""
    receipt_text = str(pasted_text or "").strip()

    if upload and getattr(upload, "filename", ""):
        PANTRY_RECEIPT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(upload.filename or "")
        stored_name = f"{receipt_id}_{filename}"
        upload.save(PANTRY_RECEIPT_UPLOAD_DIR / stored_name)
        stored_path = f"pantry_receipts/{stored_name}"

        if not receipt_text:
            receipt_text = extract_receipt_text_from_file(PANTRY_RECEIPT_UPLOAD_DIR / stored_name)

    candidates = parse_receipt_text(receipt_text)
    record = {
        "receipt_id": receipt_id,
        "created_at": timestamp,
        "stored_path": stored_path,
        "pasted_text": receipt_text if not stored_path else "",
        "text_excerpt": receipt_text[:500],
        "candidate_count": len(candidates),
        "status": "pending",
    }
    append_receipt_history(record)
    return {
        "receipt_id": receipt_id,
        "receipt_text": receipt_text,
        "candidates": candidates,
        "record": record,
    }


def extract_receipt_text_from_file(path):
    path = Path(path)
    extension = path.suffix.lower()

    if extension in {".txt", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if extension == ".pdf":
        return extract_pdf_text(path)

    return ""


def extract_pdf_text(path):
    try:
        from PyPDF2 import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def load_receipt_history():
    if not PANTRY_RECEIPT_HISTORY_FILE.exists():
        return {"receipts": []}

    try:
        payload = json.loads(PANTRY_RECEIPT_HISTORY_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"receipts": []}

    if not isinstance(payload, dict):
        return {"receipts": []}

    return {
        "receipts": [
            receipt
            for receipt in payload.get("receipts", [])
            if isinstance(receipt, dict) and receipt.get("receipt_id")
        ],
    }


def append_receipt_history(record):
    payload = load_receipt_history()
    payload["receipts"].append(record)
    save_receipt_history(payload)
    return record


def update_receipt_history_status(receipt_id, status, added_count=0):
    payload = load_receipt_history()

    for receipt in payload["receipts"]:
        if receipt.get("receipt_id") == receipt_id:
            receipt["status"] = status
            receipt["added_count"] = added_count
            receipt["last_updated"] = now_iso()
            break

    save_receipt_history(payload)


def save_receipt_history(payload):
    PANTRY_RECEIPT_HISTORY_FILE.write_text(
        json.dumps({"receipts": payload.get("receipts", [])}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def receipt_history_for_view(limit=8):
    receipts = load_receipt_history()["receipts"]
    return sorted(receipts, key=lambda receipt: receipt.get("created_at", ""), reverse=True)[:limit]


def match_recipe_to_pantry(recipe, pantry_items):
    ingredients = recipe_ingredients_for_matching(recipe)
    pantry_names = {
        item.get("normalized_name") or normalize_ingredient_name(item.get("ingredient_name"))
        for item in pantry_items
    }
    pantry_names.discard("")
    matched = []
    missing = []

    for ingredient in ingredients:
        candidate_names = [
            normalize_ingredient_name(ingredient.get("name")),
            normalize_ingredient_name(ingredient.get("purchasable_item")),
            normalize_ingredient_name(ingredient.get("purchase_group")),
        ]
        is_match = any(candidate and candidate in pantry_names for candidate in candidate_names)

        if is_match:
            matched.append(ingredient)
        else:
            missing.append(ingredient)

    total = len(ingredients)
    match_percentage = round((len(matched) / total) * 100) if total else 0

    return {
        "recipe": recipe,
        "recipe_title": recipe.get("name") or "Recipe",
        "recipe_url": recipe.get("url", ""),
        "matched_ingredients": matched,
        "missing_ingredients": missing,
        "matched_count": len(matched),
        "missing_count": len(missing),
        "total_count": total,
        "match_percentage": match_percentage,
        "status": missing_status(len(missing)),
        "sort_key": pantry_recipe_sort_key(len(missing), match_percentage),
    }


def recipe_ingredients_for_matching(recipe):
    ingredients = []

    for section in recipe.get("sections", []) or []:
        for item in section.get("items", []) if isinstance(section, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("display_name") or "").strip()
            if not name:
                continue
            ingredients.append({
                "name": name,
                "display_name": item.get("display_name") or name,
                "purchasable_item": item.get("purchasable_item") or "",
                "purchase_group": item.get("purchase_group") or "",
            })

    return ingredients


def missing_status(missing_count):
    if missing_count <= 0:
        return "Can make now"
    if missing_count == 1:
        return "Missing 1 item"
    if missing_count == 2:
        return "Missing 2 items"
    return "Missing several items"


def pantry_recipe_sort_key(missing_count, match_percentage):
    if missing_count <= 0:
        rank = 0
    elif missing_count == 1:
        rank = 1
    elif missing_count == 2:
        rank = 2
    else:
        rank = 3

    return (rank, -match_percentage)


def pantry_recipe_matches_for_view(recipe_rows, pantry_items):
    matches = [
        match_recipe_to_pantry(recipe, pantry_items)
        for recipe in recipe_rows
    ]
    return sorted(matches, key=lambda match: match["sort_key"])
