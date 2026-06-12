import json
import os
import threading
import time
import uuid
from pathlib import Path

import requests

from PushShoppingList.services.storage_service import scoped_extractor_data_path
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import notification_topic
from PushShoppingList.services.user_account_service import notification_preference_enabled
from PushShoppingList.services.user_account_service import normalize_ntfy_topic
from PushShoppingList.services.user_account_service import record_notification_sent


BASE_DIR = Path(__file__).resolve().parent
PROGRESS_FILE = scoped_extractor_data_path("extract_progress.json")
FALLBACK_NTFY_TOPIC = normalize_ntfy_topic(os.getenv("NTFY_TOPIC", ""))

PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
PROGRESS_LOCK = threading.RLock()

MENU_RECIPE_CHECKLIST_KEYS = (
    "recipe_extracted",
    "recipe_information",
    "ingredients",
    "equipment",
    "instructions",
    "nutrition",
    "food_review_applied",
    "estimate_per_serving",
)


def new_job_id():
    return uuid.uuid4().hex


def menu_recipe_checklist_defaults(checked=False):
    return {key: bool(checked) for key in MENU_RECIPE_CHECKLIST_KEYS}


def normalize_menu_recipe_progress(recipe):
    recipe = recipe if isinstance(recipe, dict) else {}
    checklist = recipe.get("checklist") if isinstance(recipe.get("checklist"), dict) else {}
    running = recipe.get("running") if isinstance(recipe.get("running"), dict) else {}
    messages = recipe.get("messages") if isinstance(recipe.get("messages"), dict) else {}
    errors = recipe.get("errors") if isinstance(recipe.get("errors"), dict) else {}

    recipe_url = str(
        recipe.get("recipe_url")
        or recipe.get("url")
        or recipe.get("source_url")
        or ""
    ).strip()
    recipe_id = str(recipe.get("recipe_id") or recipe.get("id") or recipe_url).strip()

    return {
        "recipe_id": recipe_id,
        "recipe_url": recipe_url,
        "recipe_name": str(
            recipe.get("recipe_name")
            or recipe.get("name")
            or recipe.get("display_name")
            or "Menu Recipe"
        ).strip(),
        "menu_section": str(recipe.get("menu_section") or recipe.get("category") or "").strip(),
        "extracted_description": str(
            recipe.get("extracted_description")
            or recipe.get("menu_description")
            or recipe.get("description")
            or ""
        ).strip(),
        "checklist": {
            key: bool(checklist.get(key))
            for key in MENU_RECIPE_CHECKLIST_KEYS
        },
        "running": {
            key: bool(running.get(key))
            for key in MENU_RECIPE_CHECKLIST_KEYS
        },
        "messages": {
            str(key): str(value)
            for key, value in messages.items()
            if key in MENU_RECIPE_CHECKLIST_KEYS and str(value).strip()
        },
        "errors": {
            str(key): str(value)
            for key, value in errors.items()
            if key in MENU_RECIPE_CHECKLIST_KEYS and str(value).strip()
        },
    }


def normalize_menu_recipe_progress_list(menu_recipes):
    if not isinstance(menu_recipes, list):
        return []

    return [
        normalize_menu_recipe_progress(recipe)
        for recipe in menu_recipes
        if isinstance(recipe, dict)
    ]


def default_progress():
    return {
        "active": False,
        "job_id": None,
        "status": "idle",
        "cancel_requested": False,
        "summary": "No extraction running.",
        "current_index": 0,
        "total": 0,
        "percent": 0,
        "urls": [],
        "updated_at": time.time(),
    }


def load_progress():
    with PROGRESS_LOCK:
        if not PROGRESS_FILE.exists():
            return default_progress()

        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return default_progress()


def save_progress(progress):
    with PROGRESS_LOCK:
        progress["updated_at"] = time.time()
        PROGRESS_FILE.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return progress


def start_progress(urls, job_id=None, extraction_mode="recipe"):
    with PROGRESS_LOCK:
        urls = [str(url).strip() for url in urls if str(url).strip()]
        job_id = job_id or new_job_id()
        extraction_mode = str(extraction_mode or "recipe").strip().lower()
        is_menu_extract = extraction_mode in {"menu", "menu_extract", "menu-extract"}
        progress = {
            "active": True,
            "job_id": job_id,
            "extraction_mode": "menu_extract" if is_menu_extract else "recipe",
            "status": "running",
            "cancel_requested": False,
            "summary": (
                "Fetching menu page and extracting menu items."
                if is_menu_extract
                else "Fetching recipe page and extracting ingredients."
            ),
            "current_index": 0,
            "total": len(urls),
            "percent": 10 if urls else 0,
            "urls": [
                {
                    "url": url,
                    "state": "waiting",
                    "message": "waiting...",
                    "ingredients_count": None,
                    "menu_recipes": [] if is_menu_extract else [],
                }
                for url in urls
            ],
        }
        save_progress(progress)
    send_ntfy("Recipe extraction started", f"Extracting {len(urls)} recipe URL(s).")
    return progress


def mark_url_running(job_id, urls, index):
    with PROGRESS_LOCK:
        progress = ensure_job(job_id, urls)

        if progress.get("job_id") != job_id or progress.get("cancel_requested"):
            return progress

        progress["active"] = True
        progress["status"] = "running"
        progress["current_index"] = index
        is_menu_extract = progress.get("extraction_mode") == "menu_extract"
        progress["summary"] = (
            "Fetching menu page and extracting menu items."
            if is_menu_extract
            else "Fetching recipe page and extracting ingredients."
        )
        progress["percent"] = progress_percent(index, progress["total"])

        if 0 <= index < len(progress["urls"]):
            progress["urls"][index]["state"] = "running"
            progress["urls"][index]["message"] = (
                "extracting - Running menu extractor..."
                if is_menu_extract
                else "extracting - Running recipe extractor..."
            )

        return save_progress(progress)


def mark_url_message(job_id, urls, index, message, summary=None):
    with PROGRESS_LOCK:
        progress = ensure_job(job_id, urls)

        if progress.get("job_id") != job_id or progress.get("cancel_requested"):
            return progress

        progress["active"] = True
        progress["status"] = "running"
        progress["current_index"] = index

        if summary:
            progress["summary"] = summary

        if 0 <= index < len(progress["urls"]):
            progress["urls"][index]["state"] = "running"
            progress["urls"][index]["message"] = message

        return save_progress(progress)


def set_url_menu_recipes(job_id, urls, index, menu_recipes, message=None, summary=None):
    with PROGRESS_LOCK:
        progress = ensure_job(job_id, urls)

        if progress.get("job_id") != job_id or progress.get("cancel_requested"):
            return progress

        progress["active"] = True
        progress["status"] = "running"
        progress["current_index"] = index

        if summary:
            progress["summary"] = summary

        if 0 <= index < len(progress["urls"]):
            item = progress["urls"][index]
            if item.get("state") == "waiting":
                item["state"] = "running"
            if message:
                item["message"] = message
            item["menu_recipes"] = normalize_menu_recipe_progress_list(menu_recipes)

        return save_progress(progress)


def update_menu_recipe_step(
    job_id,
    recipe_id="",
    recipe_url="",
    step="",
    checked=None,
    running=None,
    message=None,
    error=None,
):
    step = str(step or "").strip()
    if step not in MENU_RECIPE_CHECKLIST_KEYS:
        return load_progress()

    recipe_id = str(recipe_id or "").strip()
    recipe_url = str(recipe_url or "").strip()

    with PROGRESS_LOCK:
        progress = load_progress()
        if job_id and progress.get("job_id") != job_id:
            return progress

        target_recipe = None
        for item in progress.get("urls", []):
            recipes = item.get("menu_recipes")
            if not isinstance(recipes, list):
                continue

            for index, recipe in enumerate(recipes):
                normalized = normalize_menu_recipe_progress(recipe)
                recipes[index] = normalized

                if recipe_id and normalized.get("recipe_id") == recipe_id:
                    target_recipe = normalized
                    break

                if recipe_url and normalized.get("recipe_url") == recipe_url:
                    target_recipe = normalized
                    break

            if target_recipe:
                break

        if not target_recipe:
            return progress

        checklist = target_recipe.setdefault("checklist", menu_recipe_checklist_defaults())
        running_map = target_recipe.setdefault("running", menu_recipe_checklist_defaults())
        messages = target_recipe.setdefault("messages", {})
        errors = target_recipe.setdefault("errors", {})

        if checked is not None:
            checklist[step] = bool(checked)
            if checked:
                running_map[step] = False
                errors.pop(step, None)

        if running is not None:
            running_map[step] = bool(running)

        if message is not None:
            message = str(message or "").strip()
            if message:
                messages[step] = message
            else:
                messages.pop(step, None)

        if error is not None:
            error = str(error or "").strip()
            if error:
                errors[step] = error
                checklist[step] = False
                running_map[step] = False
            else:
                errors.pop(step, None)

        return save_progress(progress)


def mark_url_done(job_id, urls, index, ingredients_count):
    with PROGRESS_LOCK:
        progress = ensure_job(job_id, urls)

        if progress.get("job_id") != job_id or progress.get("cancel_requested"):
            return progress

        if 0 <= index < len(progress["urls"]):
            progress["urls"][index]["state"] = "done"
            if progress.get("extraction_mode") == "menu_extract":
                progress["urls"][index]["message"] = f"done - {ingredients_count} menu item recipes created"
            else:
                progress["urls"][index]["message"] = f"done - {ingredients_count} ingredients extracted"
            progress["urls"][index]["ingredients_count"] = ingredients_count

        progress["percent"] = progress_percent(completed_count(progress), progress["total"])
        return save_progress(progress)


def mark_url_failed(job_id, urls, index, error):
    with PROGRESS_LOCK:
        progress = ensure_job(job_id, urls)

        if progress.get("job_id") != job_id or progress.get("cancel_requested"):
            return progress

        if 0 <= index < len(progress["urls"]):
            progress["urls"][index]["state"] = "failed"
            progress["urls"][index]["message"] = f"failed - {friendly_error_message(error)}"

        progress["percent"] = progress_percent(completed_count(progress), progress["total"])
        return save_progress(progress)


def friendly_error_message(error):
    text = str(error or "unknown error").strip()

    if "403 Forbidden" in text:
        if "browser fallback failed" in text:
            return "403 Forbidden. Browser fallback opened the page but could not read recipe HTML in time."
        return "403 Forbidden. The website blocked the recipe download."

    if "Timed out receiving message from renderer" in text:
        return "Chrome timed out while loading the recipe page."

    if "timeout" in text.lower() or "timed out" in text.lower():
        return "Timed out while loading the recipe page."

    if "Cannot connect to proxy" in text:
        return "Network/proxy blocked the recipe page download."

    single_line = " ".join(text.split())
    return single_line[:220]


def request_cancel(job_id=None):
    progress = load_progress()

    if job_id and progress.get("job_id") != job_id:
        return progress

    progress["active"] = False
    progress["status"] = "cancelled"
    progress["cancel_requested"] = True
    progress["summary"] = "Extraction cancelled. Use Redo Missing to run anything that did not finish."

    for item in progress.get("urls", []):
        if item.get("state") in {"waiting", "running"}:
            item["state"] = "cancelled"
            item["message"] = "cancelled"

    progress["percent"] = progress_percent(completed_count(progress), progress.get("total", 0))
    save_progress(progress)
    send_ntfy("Recipe extraction cancelled", progress["summary"])
    return progress


def finish_progress(job_id, ok=True):
    progress = load_progress()

    if job_id and progress.get("job_id") != job_id:
        return progress

    if progress.get("cancel_requested"):
        return progress

    has_failed_url = any(
        item.get("state") == "failed"
        for item in progress.get("urls", [])
    )
    ok = ok and not has_failed_url

    progress["active"] = False
    progress["status"] = "complete" if ok else "failed"
    progress["summary"] = "Extraction complete. Refreshing shopping list..." if ok else "Extraction finished with errors."
    progress["percent"] = 100
    save_progress(progress)

    title = "Recipe extraction complete" if ok else "Recipe extraction failed"
    send_ntfy(title, progress["summary"], preference_key="recipe_import_complete")
    return progress


def ensure_job(job_id, urls):
    progress = load_progress()
    urls = [str(url).strip() for url in urls if str(url).strip()]

    if progress.get("job_id") != job_id or progress.get("total") != len(urls):
        if progress.get("active") and progress.get("job_id") != job_id:
            return progress
        progress = start_progress(urls, job_id=job_id)

    return progress


def is_cancel_requested(job_id=None):
    progress = load_progress()

    if job_id and progress.get("job_id") != job_id:
        return False

    return bool(progress.get("cancel_requested"))


def is_current_job(job_id):
    return bool(job_id) and load_progress().get("job_id") == job_id


def progress_percent(done_count, total):
    if not total:
        return 0

    return max(10, min(100, round((done_count / total) * 100)))


def completed_count(progress):
    return sum(
        1
        for item in progress.get("urls", [])
        if item.get("state") in {"done", "failed", "cancelled"}
    )


def batch_is_finished(progress):
    total = progress.get("total", 0)
    return total > 0 and completed_count(progress) >= total


def batch_has_success(progress):
    return any(
        item.get("state") == "done" and ingredients_count(item) > 0
        for item in progress.get("urls", [])
    )


def ingredients_count(item):
    try:
        return int(item.get("ingredients_count") or 0)
    except (TypeError, ValueError):
        return 0


def send_ntfy(title, message, preference_key=""):
    topic = active_ntfy_topic(preference_key=preference_key)

    if not topic:
        return

    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=str(message).encode("utf-8"),
            headers={"Title": str(title)},
            timeout=5,
        )
        user = current_user()
        if user:
            record_notification_sent(user.get("user_id"))
    except Exception:
        pass


def active_ntfy_topic(preference_key=""):
    user = current_user()

    if user and not notification_preference_enabled(user, preference_key):
        return ""

    topic = notification_topic(user or {})

    if topic:
        return topic

    return FALLBACK_NTFY_TOPIC
