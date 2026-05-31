import json
import threading
import time
from pathlib import Path

from PushShoppingList.services.storage_service import scoped_extractor_data_path


BASE_DIR = Path(__file__).resolve().parent
PROGRESS_FILE = scoped_extractor_data_path("recipe_image_progress.json")
PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)

PROGRESS_LOCK = threading.RLock()
RUNNING_STALE_SECONDS = 15 * 60
RECENT_RESULT_SECONDS = 2 * 60


def normalize_image_progress_kind(kind):
    return "equipment" if str(kind or "").strip().lower() == "equipment" else "step"


def normalize_image_progress_target(target):
    value = str(target or "").strip()

    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return value

    return str(number)


def image_progress_key(kind, url, target):
    return "|".join([
        normalize_image_progress_kind(kind),
        str(url or "").strip(),
        normalize_image_progress_target(target),
    ])


def default_recipe_image_progress():
    return {
        "active": False,
        "items": [],
        "updated_at": time.time(),
    }


def load_recipe_image_progress_file():
    if not PROGRESS_FILE.exists():
        return default_recipe_image_progress()

    try:
        progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_recipe_image_progress()

    return progress if isinstance(progress, dict) else default_recipe_image_progress()


def save_recipe_image_progress(progress):
    progress = progress if isinstance(progress, dict) else default_recipe_image_progress()
    progress["updated_at"] = time.time()
    progress["active"] = any(
        item.get("state") == "running"
        for item in progress.get("items", [])
        if isinstance(item, dict)
    )
    PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return progress


def compact_recipe_image_progress(progress, now=None):
    now = now or time.time()
    compacted = []

    for item in progress.get("items", []):
        if not isinstance(item, dict):
            continue

        try:
            item_updated = float(item.get("updated_at") or item.get("started_at") or now)
        except (TypeError, ValueError):
            item_updated = now
        state = item.get("state") or "idle"
        age = now - item_updated

        if state == "running" and age > RUNNING_STALE_SECONDS:
            item = {
                **item,
                "state": "failed",
                "message": "Image generation took too long. Please try again.",
                "updated_at": now,
            }
            compacted.append(item)
            continue

        if state == "running" or age <= RECENT_RESULT_SECONDS:
            compacted.append(item)

    progress["items"] = compacted
    progress["active"] = any(item.get("state") == "running" for item in compacted)
    return progress


def load_recipe_image_progress(url=None):
    with PROGRESS_LOCK:
        progress = compact_recipe_image_progress(load_recipe_image_progress_file())

        if PROGRESS_FILE.exists() or progress.get("items"):
            save_recipe_image_progress(progress)

    if url:
        recipe_url = str(url or "").strip()
        progress = {
            **progress,
            "items": [
                item for item in progress.get("items", [])
                if str(item.get("url") or "").strip() == recipe_url
            ],
        }
        progress["active"] = any(item.get("state") == "running" for item in progress["items"])

    return progress


def image_progress_record(kind, url, target, state, **values):
    normalized_kind = normalize_image_progress_kind(kind)
    normalized_target = normalize_image_progress_target(target)
    now = time.time()
    record = {
        "key": image_progress_key(normalized_kind, url, normalized_target),
        "kind": normalized_kind,
        "url": str(url or "").strip(),
        "target": normalized_target,
        "state": state,
        "message": values.get("message") or default_image_progress_message(normalized_kind, state),
        "image_url": values.get("image_url") or "",
        "generated_at": values.get("generated_at") or "",
        "started_at": values.get("started_at") or now,
        "updated_at": now,
    }

    if normalized_kind == "equipment":
        record["equipment_index"] = normalized_target
    else:
        record["step_number"] = normalized_target

    return record


def default_image_progress_message(kind, state):
    if state == "running":
        return (
            "Generating equipment image..."
            if kind == "equipment"
            else "Generating step image..."
        )

    if state == "done":
        return "Image generated."

    if state == "failed":
        return "Image generation failed. Please try again."

    return ""


def upsert_recipe_image_progress_item(progress, item):
    item_key = item.get("key") or image_progress_key(
        item.get("kind"),
        item.get("url"),
        item.get("target"),
    )
    next_items = [
        current for current in progress.get("items", [])
        if isinstance(current, dict) and current.get("key") != item_key
    ]
    next_items.append(item)
    progress["items"] = next_items
    return progress


def start_recipe_image_progress(kind, url, target, message=None):
    with PROGRESS_LOCK:
        progress = compact_recipe_image_progress(load_recipe_image_progress_file())
        item = image_progress_record(
            kind,
            url,
            target,
            "running",
            message=message,
        )
        upsert_recipe_image_progress_item(progress, item)
        return save_recipe_image_progress(progress)


def finish_recipe_image_progress(kind, url, target, ok=True, image_url="", generated_at="", error=""):
    state = "done" if ok else "failed"
    message = "" if ok else (error or "Image generation failed. Please try again.")

    with PROGRESS_LOCK:
        progress = compact_recipe_image_progress(load_recipe_image_progress_file())
        existing = next((
            item for item in progress.get("items", [])
            if isinstance(item, dict)
            and item.get("key") == image_progress_key(kind, url, target)
        ), {})
        item = image_progress_record(
            kind,
            url,
            target,
            state,
            message=message,
            image_url=image_url,
            generated_at=generated_at,
            started_at=existing.get("started_at"),
        )
        upsert_recipe_image_progress_item(progress, item)
        return save_recipe_image_progress(progress)
