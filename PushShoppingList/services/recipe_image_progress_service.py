import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PushShoppingList.services.storage_service import scoped_extractor_data_path


PROGRESS_FILE = scoped_extractor_data_path("recipe_image_progress.json")

PROGRESS_LOCK = threading.RLock()
RUNNING_STALE_SECONDS = 15 * 60
RECENT_RESULT_SECONDS = 2 * 60
STALE_TRANSITION_CACHE_MAX_ENTRIES = 256
_STALE_TRANSITION_CACHE = OrderedDict()


def _now():
    return time.time()


def _resolved_progress_path():
    return Path(os.path.abspath(os.fspath(PROGRESS_FILE))).resolve(strict=False)


def _progress_scope_key(progress_path):
    return os.path.normcase(str(progress_path))


def _invalidate_stale_transitions(progress_scope):
    for cache_key in list(_STALE_TRANSITION_CACHE):
        if cache_key[0] == progress_scope:
            del _STALE_TRANSITION_CACHE[cache_key]


def _prune_superseded_stale_transitions(progress_scope, source_fingerprint):
    for cache_key in list(_STALE_TRANSITION_CACHE):
        if cache_key[0] == progress_scope and cache_key[1] != source_fingerprint:
            del _STALE_TRANSITION_CACHE[cache_key]


def _enforce_stale_transition_cache_bound():
    while len(_STALE_TRANSITION_CACHE) > STALE_TRANSITION_CACHE_MAX_ENTRIES:
        _STALE_TRANSITION_CACHE.popitem(last=False)


def _progress_item_identity(item, item_index):
    identity = [
        item_index,
        str(item.get("key") or ""),
        normalize_image_progress_kind(item.get("kind")),
        str(item.get("url") or "").strip(),
        normalize_image_progress_target(item.get("target")),
    ]
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_image_progress_kind(kind):
    normalized = str(kind or "").strip().lower()
    if normalized in {"equipment", "ingredient"}:
        return normalized
    return "step"


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
        "updated_at": _now(),
    }


def _load_recipe_image_progress_snapshot():
    progress_path = _resolved_progress_path()
    progress_scope = _progress_scope_key(progress_path)

    if not progress_path.exists():
        _invalidate_stale_transitions(progress_scope)
        return default_recipe_image_progress(), progress_path, progress_scope, None

    try:
        source_bytes = progress_path.read_bytes()
    except Exception:
        _invalidate_stale_transitions(progress_scope)
        return default_recipe_image_progress(), progress_path, progress_scope, None

    source_fingerprint = hashlib.sha256(source_bytes).hexdigest()
    _prune_superseded_stale_transitions(progress_scope, source_fingerprint)

    try:
        progress = json.loads(source_bytes.decode("utf-8"))
    except Exception:
        progress = default_recipe_image_progress()

    if not isinstance(progress, dict):
        progress = default_recipe_image_progress()

    return progress, progress_path, progress_scope, source_fingerprint


def load_recipe_image_progress_file():
    with PROGRESS_LOCK:
        progress, _, _, _ = _load_recipe_image_progress_snapshot()
        return progress


def save_recipe_image_progress(progress, progress_path=None):
    with PROGRESS_LOCK:
        progress_path = progress_path or _resolved_progress_path()
        progress_scope = _progress_scope_key(progress_path)
        progress = progress if isinstance(progress, dict) else default_recipe_image_progress()
        progress["updated_at"] = _now()
        progress["active"] = any(
            item.get("state") == "running"
            for item in progress.get("items", [])
            if isinstance(item, dict)
        )
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _invalidate_stale_transitions(progress_scope)
        return progress


def compact_recipe_image_progress(
    progress,
    now=None,
    progress_scope=None,
    source_fingerprint=None,
):
    with PROGRESS_LOCK:
        now = _now() if now is None else now
        compacted = []
        use_transition_cache = (
            progress_scope is not None and source_fingerprint is not None
        )

        for item_index, item in enumerate(progress.get("items", [])):
            if not isinstance(item, dict):
                continue

            try:
                item_updated = float(item.get("updated_at") or item.get("started_at") or now)
            except (TypeError, ValueError):
                item_updated = now
            state = item.get("state") or "idle"
            age = now - item_updated

            if state == "running" and age > RUNNING_STALE_SECONDS:
                transition_at = now
                cache_key = None

                if use_transition_cache:
                    cache_key = (
                        progress_scope,
                        source_fingerprint,
                        _progress_item_identity(item, item_index),
                    )
                    if cache_key in _STALE_TRANSITION_CACHE:
                        transition_at = _STALE_TRANSITION_CACHE[cache_key]
                        _STALE_TRANSITION_CACHE.move_to_end(cache_key)
                    else:
                        _STALE_TRANSITION_CACHE[cache_key] = transition_at
                        _enforce_stale_transition_cache_bound()

                if transition_at is None:
                    continue

                if now - transition_at > RECENT_RESULT_SECONDS:
                    if cache_key is not None:
                        _STALE_TRANSITION_CACHE[cache_key] = None
                        _STALE_TRANSITION_CACHE.move_to_end(cache_key)
                    continue

                item = {
                    **item,
                    "state": "failed",
                    "message": "Image generation took too long. Please try again.",
                    "updated_at": transition_at,
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
        progress, _, progress_scope, source_fingerprint = (
            _load_recipe_image_progress_snapshot()
        )
        progress = compact_recipe_image_progress(
            progress,
            progress_scope=progress_scope,
            source_fingerprint=source_fingerprint,
        )

        if source_fingerprint is not None or progress.get("items"):
            # Preserve the response's prior freshness semantics without turning
            # a read into a filesystem write.
            progress["updated_at"] = _now()

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
    now = _now()
    record = {
        "key": image_progress_key(normalized_kind, url, normalized_target),
        "kind": normalized_kind,
        "url": str(url or "").strip(),
        "target": normalized_target,
        "state": state,
        "message": values.get("message") or default_image_progress_message(normalized_kind, state),
        "image_url": values.get("image_url") or "",
        "generated_at": values.get("generated_at") or "",
        "image_prompt": values.get("image_prompt") or "",
        "started_at": values.get("started_at") or now,
        "updated_at": now,
    }

    if normalized_kind == "equipment":
        record["equipment_index"] = normalized_target
    elif normalized_kind == "ingredient":
        record["ingredient_index"] = normalized_target
    else:
        record["step_number"] = normalized_target

    return record


def default_image_progress_message(kind, state):
    if state == "running":
        if kind == "equipment":
            return "Generating equipment image..."
        if kind == "ingredient":
            return "Generating ingredient image..."
        return "Generating step image..."

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


def start_recipe_image_progress(kind, url, target, message=None, image_prompt=""):
    with PROGRESS_LOCK:
        progress, progress_path, progress_scope, source_fingerprint = (
            _load_recipe_image_progress_snapshot()
        )
        progress = compact_recipe_image_progress(
            progress,
            progress_scope=progress_scope,
            source_fingerprint=source_fingerprint,
        )
        item = image_progress_record(
            kind,
            url,
            target,
            "running",
            message=message,
            image_prompt=image_prompt,
        )
        upsert_recipe_image_progress_item(progress, item)
        return save_recipe_image_progress(progress, progress_path=progress_path)


def finish_recipe_image_progress(
    kind,
    url,
    target,
    ok=True,
    image_url="",
    generated_at="",
    error="",
    image_prompt="",
):
    state = "done" if ok else "failed"
    message = "" if ok else (error or "Image generation failed. Please try again.")

    with PROGRESS_LOCK:
        progress, progress_path, progress_scope, source_fingerprint = (
            _load_recipe_image_progress_snapshot()
        )
        item_key = image_progress_key(kind, url, target)
        existing = next((
            item for item in progress.get("items", [])
            if isinstance(item, dict) and item.get("key") == item_key
        ), {})
        progress = compact_recipe_image_progress(
            progress,
            progress_scope=progress_scope,
            source_fingerprint=source_fingerprint,
        )
        item = image_progress_record(
            kind,
            url,
            target,
            state,
            message=message,
            image_url=image_url,
            generated_at=generated_at,
            image_prompt=image_prompt or existing.get("image_prompt") or "",
            started_at=existing.get("started_at"),
        )
        upsert_recipe_image_progress_item(progress, item)
        return save_recipe_image_progress(progress, progress_path=progress_path)
