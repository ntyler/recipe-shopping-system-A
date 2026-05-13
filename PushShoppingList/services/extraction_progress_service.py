import json
import os
import time
import uuid
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
PROGRESS_FILE = BASE_DIR / "recipe-extractor" / "data" / "extract_progress.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nathaniel-shopping-list-12345")

PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def new_job_id():
    return uuid.uuid4().hex


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
    if not PROGRESS_FILE.exists():
        return default_progress()

    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_progress()


def save_progress(progress):
    progress["updated_at"] = time.time()
    PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return progress


def start_progress(urls, job_id=None):
    urls = [str(url).strip() for url in urls if str(url).strip()]
    job_id = job_id or new_job_id()
    progress = {
        "active": True,
        "job_id": job_id,
        "status": "running",
        "cancel_requested": False,
        "summary": "Fetching recipe page and extracting ingredients.",
        "current_index": 0,
        "total": len(urls),
        "percent": 10 if urls else 0,
        "urls": [
            {
                "url": url,
                "state": "waiting",
                "message": "waiting...",
                "ingredients_count": None,
            }
            for url in urls
        ],
    }
    save_progress(progress)
    send_ntfy("Recipe extraction started", f"Extracting {len(urls)} recipe URL(s).")
    return progress


def mark_url_running(job_id, urls, index):
    progress = ensure_job(job_id, urls)

    if progress.get("job_id") != job_id or progress.get("cancel_requested"):
        return progress

    progress["active"] = True
    progress["status"] = "running"
    progress["current_index"] = index
    progress["summary"] = "Fetching recipe page and extracting ingredients."
    progress["percent"] = progress_percent(index, progress["total"])

    if 0 <= index < len(progress["urls"]):
        progress["urls"][index]["state"] = "running"
        progress["urls"][index]["message"] = "extracting - Running recipe extractor..."

    return save_progress(progress)


def mark_url_message(job_id, urls, index, message, summary=None):
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


def mark_url_done(job_id, urls, index, ingredients_count):
    progress = ensure_job(job_id, urls)

    if progress.get("job_id") != job_id or progress.get("cancel_requested"):
        return progress

    if 0 <= index < len(progress["urls"]):
        progress["urls"][index]["state"] = "done"
        progress["urls"][index]["message"] = f"done - {ingredients_count} ingredients extracted"
        progress["urls"][index]["ingredients_count"] = ingredients_count

    progress["percent"] = progress_percent(completed_count(progress), progress["total"])
    return save_progress(progress)


def mark_url_failed(job_id, urls, index, error):
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
    send_ntfy(title, progress["summary"])
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
        item.get("state") == "done"
        for item in progress.get("urls", [])
    )


def send_ntfy(title, message):
    if not NTFY_TOPIC:
        return

    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=str(message).encode("utf-8"),
            headers={"Title": str(title)},
            timeout=5,
        )
    except Exception:
        pass
