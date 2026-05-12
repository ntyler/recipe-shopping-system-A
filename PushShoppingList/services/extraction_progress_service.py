import json
import os
import time
import uuid
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
PROGRESS_FILE = PROJECT_DIR / "recipe-extractor" / "data" / "extract_progress.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nathaniel-shopping-list-12345")

PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def new_job_id():
    return uuid.uuid4().hex


def default_progress():
    return {
        "active": False,
        "job_id": None,
        "status": "idle",
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
    progress["active"] = True
    progress["status"] = "running"
    progress["current_index"] = index
    progress["summary"] = "Fetching recipe page and extracting ingredients."
    progress["percent"] = progress_percent(index, progress["total"])

    if 0 <= index < len(progress["urls"]):
        progress["urls"][index]["state"] = "running"
        progress["urls"][index]["message"] = "extracting - Running recipe extractor..."

    return save_progress(progress)


def mark_url_done(job_id, urls, index, ingredients_count):
    progress = ensure_job(job_id, urls)

    if 0 <= index < len(progress["urls"]):
        progress["urls"][index]["state"] = "done"
        progress["urls"][index]["message"] = f"done - {ingredients_count} ingredients extracted"
        progress["urls"][index]["ingredients_count"] = ingredients_count

    progress["percent"] = progress_percent(index + 1, progress["total"])
    return save_progress(progress)


def mark_url_failed(job_id, urls, index, error):
    progress = ensure_job(job_id, urls)

    if 0 <= index < len(progress["urls"]):
        progress["urls"][index]["state"] = "failed"
        progress["urls"][index]["message"] = f"failed - {error or 'unknown error'}"

    progress["percent"] = progress_percent(index + 1, progress["total"])
    return save_progress(progress)


def finish_progress(job_id, ok=True):
    progress = load_progress()

    if job_id and progress.get("job_id") != job_id:
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
        progress = start_progress(urls, job_id=job_id)

    return progress


def progress_percent(done_count, total):
    if not total:
        return 0

    return max(10, min(100, round((done_count / total) * 100)))


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
