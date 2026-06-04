import json
import hashlib
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path

from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import scoped_extractor_data_path


BASE_DIR = Path(__file__).resolve().parent
HOME_ADDRESS_FILE = scoped_extractor_data_path("home_address.json")
HOME_ADDRESS_HISTORY_FILE = scoped_extractor_data_path("home_address_history.json")
MAX_HOME_ADDRESS_HISTORY = 25

DEFAULT_HOME_ADDRESS = {
    "label": "",
    "street": "5905 Arlo Drive",
    "apartment": "Apt 2213",
    "city": "Indianapolis",
    "county": "Marion County",
    "state": "IN",
    "zip": "46237",
    "country": "United States",
}
EMPTY_HOME_ADDRESS = {
    "label": "",
    "street": "",
    "apartment": "",
    "city": "",
    "county": "",
    "state": "",
    "zip": "",
    "country": "",
}

HOME_ADDRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_home_address():
    data = (EMPTY_HOME_ADDRESS if active_user_id() else DEFAULT_HOME_ADDRESS).copy()

    if HOME_ADDRESS_FILE.exists():
        try:
            saved = json.loads(HOME_ADDRESS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update({
                    key: str(saved.get(key, data[key]) or "").strip()
                    for key in DEFAULT_HOME_ADDRESS
                })
        except Exception:
            pass

    data["full_address"] = build_full_address(data)
    return data


def save_home_address(form_data):
    data = {
        "label": str(form_data.get("address_label", "") or "").strip(),
        "street": str(form_data.get("address_street", "") or "").strip(),
        "apartment": str(form_data.get("address_apartment", "") or "").strip(),
        "city": str(form_data.get("address_city", "") or "").strip(),
        "county": str(form_data.get("address_county", "") or "").strip(),
        "state": str(form_data.get("address_state", "") or "").strip(),
        "zip": str(form_data.get("address_zip", "") or "").strip(),
        "country": str(form_data.get("address_country", "") or "").strip(),
    }

    HOME_ADDRESS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    data["full_address"] = build_full_address(data)
    save_home_address_history_entry(data)
    return data


def load_home_address_history(limit=10):
    payload = read_home_address_history_payload()
    entries = payload.get("history", []) if isinstance(payload, dict) else []
    history = []

    for entry in entries:
        normalized = normalize_home_address_history_entry(entry)

        if normalized:
            history.append(normalized)

    if limit is None:
        return history

    return history[:limit]


def save_home_address_history_entry(address):
    full_address = str(address.get("full_address") or build_full_address(address) or "").strip()

    if not full_address:
        return load_home_address_history()

    existing_entry = next(
        (
            existing
            for existing in load_home_address_history(limit=None)
            if existing.get("full_address") == full_address
        ),
        {},
    )
    label = str(address.get("label") or "").strip() or existing_entry.get("label", "")
    entry = {
        key: str(address.get(key, "") or "").strip()
        for key in EMPTY_HOME_ADDRESS
    }
    entry["id"] = existing_entry.get("id") or uuid.uuid4().hex
    entry["label"] = label
    entry["full_address"] = full_address
    entry["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    history = [
        existing
        for existing in load_home_address_history(limit=None)
        if existing.get("full_address") != full_address
    ]
    save_home_address_history([entry] + history)
    return load_home_address_history()


def read_home_address_history_payload():
    if not HOME_ADDRESS_HISTORY_FILE.exists():
        return {"history": []}

    try:
        saved = json.loads(HOME_ADDRESS_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"history": []}

    if isinstance(saved, list):
        return {"history": saved}

    if not isinstance(saved, dict):
        return {"history": []}

    return saved


def save_home_address_history(history):
    cleaned = []

    for entry in history[:MAX_HOME_ADDRESS_HISTORY]:
        normalized = normalize_home_address_history_entry(entry)

        if not normalized:
            continue

        cleaned.append({
            key: normalized.get(key, "")
            for key in ["id", *EMPTY_HOME_ADDRESS.keys(), "full_address", "saved_at"]
        })

    HOME_ADDRESS_HISTORY_FILE.write_text(
        json.dumps({"history": cleaned}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def normalize_home_address_history_entry(entry):
    if not isinstance(entry, dict):
        return None

    normalized = {
        key: str(entry.get(key, "") or "").strip()
        for key in EMPTY_HOME_ADDRESS
    }
    full_address = str(entry.get("full_address") or build_full_address(normalized) or "").strip()

    if not full_address:
        return None

    normalized["id"] = str(entry.get("id") or home_address_history_id(entry, full_address)).strip()
    normalized["label"] = str(entry.get("label") or entry.get("title") or "").strip()
    saved_at = str(entry.get("saved_at") or entry.get("timestamp") or "").strip()
    normalized["full_address"] = full_address
    normalized["saved_at"] = saved_at
    normalized["saved_at_display"] = format_home_address_history_timestamp(saved_at)
    return normalized


def home_address_history_id(entry, full_address):
    seed = "|".join([
        str(full_address or ""),
        str(entry.get("saved_at") or entry.get("timestamp") or ""),
    ])
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def update_home_address_history_label(entry_id, label):
    entry_id = str(entry_id or "").strip()
    label = str(label or "").strip()
    history = load_home_address_history(limit=None)
    updated = False

    for entry in history:
        if entry.get("id") == entry_id:
            entry["label"] = label
            updated = True
            break

    if not updated:
        return {
            "ok": False,
            "error": "Saved address was not found.",
            "home_address_history": history,
        }

    save_home_address_history(history)
    return {
        "ok": True,
        "home_address_history": load_home_address_history(),
    }


def delete_home_address_history_entry(entry_id):
    entry_id = str(entry_id or "").strip()
    history = load_home_address_history(limit=None)
    next_history = [
        entry
        for entry in history
        if entry.get("id") != entry_id
    ]

    if len(next_history) == len(history):
        return {
            "ok": False,
            "error": "Saved address was not found.",
            "home_address_history": history,
        }

    save_home_address_history(next_history)
    return {
        "ok": True,
        "home_address_history": load_home_address_history(),
    }


def format_home_address_history_timestamp(saved_at):
    if not saved_at:
        return "Saved"

    try:
        parsed = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
    except ValueError:
        return saved_at

    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y-%m-%d %H:%M UTC")

    return parsed.strftime("%Y-%m-%d %H:%M")


def build_full_address(data):
    street_line = " ".join(
        part
        for part in [data.get("street", ""), data.get("apartment", "")]
        if str(part or "").strip()
    )
    city_line = ", ".join(
        part
        for part in [
            str(data.get("city", "") or "").strip(),
            str(data.get("county", "") or "").strip(),
            " ".join(
                part
                for part in [
                    str(data.get("state", "") or "").strip(),
                    str(data.get("zip", "") or "").strip(),
                ]
                if part
            ),
        ]
        if part
    )

    return ", ".join(
        part
        for part in [
            street_line,
            city_line,
            str(data.get("country", "") or "").strip(),
        ]
        if part
    )
