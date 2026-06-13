import json
import os
import sqlite3
import threading
import uuid
from urllib.parse import urlparse
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from PushShoppingList.services.storage_service import PACKAGE_DIR


JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
ACTIVE_JOB_STATUSES = {"queued", "running"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
DEFAULT_JOB_RETENTION_HOURS = 168
DEFAULT_GUEST_JOB_RETENTION_HOURS = 24
DEFAULT_JOB_TIMEOUT_MINUTES = 180

JOBS_DB_PATH = Path(
    os.getenv("SHOPPING_APP_JOBS_DB", PACKAGE_DIR / "user_data" / "jobs.sqlite3")
)
JOBS_DB_LOCK = threading.RLock()


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def now_iso():
    return utc_now().isoformat() + "Z"


def parse_iso_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", ""))
    except ValueError:
        return None


def env_int(name, default_value, minimum=1):
    try:
        value = int(os.getenv(name, str(default_value)))
    except (TypeError, ValueError):
        return default_value
    return max(minimum, value)


def job_retention_hours(guest=False):
    if guest:
        return env_int("GUEST_JOB_RETENTION_HOURS", DEFAULT_GUEST_JOB_RETENTION_HOURS)
    return env_int("JOB_RETENTION_HOURS", DEFAULT_JOB_RETENTION_HOURS)


def job_timeout_minutes():
    return env_int("JOB_TIMEOUT_MINUTES", DEFAULT_JOB_TIMEOUT_MINUTES)


def json_dumps(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def json_loads(value, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed if parsed is not None else fallback


@contextmanager
def jobs_connection():
    JOBS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOBS_DB_LOCK:
        connection = sqlite3.connect(str(JOBS_DB_PATH), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            ensure_jobs_schema(connection)
            yield connection
            connection.commit()
        finally:
            connection.close()


def ensure_jobs_schema(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            guest_session_id TEXT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step TEXT NOT NULL,
            progress_percent INTEGER NOT NULL DEFAULT 0,
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            input_payload TEXT NOT NULL DEFAULT '{}',
            result_payload TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            warning_messages TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            expires_at TEXT NOT NULL,
            rq_job_id TEXT,
            retry_of TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_user ON jobs(user_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_guest ON jobs(guest_session_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_expires_at ON jobs(expires_at)")


def normalize_job_type(job_type):
    return str(job_type or "").strip().lower().replace("_", "-")


def normalize_status(status):
    status = str(status or "").strip().lower()
    return status if status in JOB_STATUSES else "queued"


def new_job_id():
    return uuid.uuid4().hex


def row_to_job(row):
    if not row:
        return None

    job = dict(row)
    job["input_payload"] = json_loads(job.get("input_payload"), {})
    job["result_payload"] = json_loads(job.get("result_payload"), {})
    job["warning_messages"] = json_loads(job.get("warning_messages"), [])
    return job


def _first_text(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_source_label(value):
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return text
    return Path(text).name or text


def _append_source_item(items, seen, source_type, value, detail=""):
    label = _safe_source_label(value)
    if not label:
        return

    key = (source_type, label)
    if key in seen:
        return

    item = {
        "type": source_type,
        "label": label,
        "detail": str(detail or "").strip(),
    }
    if source_type == "url":
        item["url"] = str(value or "").strip()
    seen.add(key)
    items.append(item)


def job_source_items(job):
    input_payload = job.get("input_payload") if isinstance(job.get("input_payload"), dict) else {}
    items = []
    seen = set()

    urls = input_payload.get("urls")
    if isinstance(urls, str):
        urls = [line.strip() for line in urls.splitlines() if line.strip()]
    if not isinstance(urls, list):
        urls = []
    for url in urls:
        _append_source_item(items, seen, "url", url)

    for key in ("url", "recipe_url", "menu_url", "source_url"):
        _append_source_item(items, seen, "url", input_payload.get(key))

    filename = _first_text(input_payload.get("filename"), input_payload.get("original_filename"))
    if filename:
        _append_source_item(items, seen, "file", filename)

    if not filename and input_payload.get("source_path"):
        _append_source_item(items, seen, "file", Path(str(input_payload.get("source_path"))).name)

    return items


def job_model_details(job):
    input_payload = job.get("input_payload") if isinstance(job.get("input_payload"), dict) else {}
    result_payload = job.get("result_payload") if isinstance(job.get("result_payload"), dict) else {}
    return {
        "model_used": _first_text(result_payload.get("model_used"), result_payload.get("model"), input_payload.get("model_used"), input_payload.get("model")),
        "model_source": _first_text(result_payload.get("model_source"), input_payload.get("model_source")),
        "model_env_var": _first_text(result_payload.get("model_env_var"), input_payload.get("model_env_var")),
    }


def job_for_client(job, include_input=False):
    if not job:
        return None

    model_details = job_model_details(job)
    payload = {
        "id": job.get("id", ""),
        "job_id": job.get("id", ""),
        "user_id": job.get("user_id") or "",
        "guest_session_id": job.get("guest_session_id") or "",
        "job_type": job.get("job_type", ""),
        "status": job.get("status", ""),
        "current_step": job.get("current_step", ""),
        "progress_percent": int(job.get("progress_percent") or 0),
        "total_items": int(job.get("total_items") or 0),
        "completed_items": int(job.get("completed_items") or 0),
        "failed_items": int(job.get("failed_items") or 0),
        "result_payload": job.get("result_payload") or {},
        "error_message": job.get("error_message") or "",
        "warning_messages": job.get("warning_messages") or [],
        "created_at": job.get("created_at") or "",
        "started_at": job.get("started_at") or "",
        "updated_at": job.get("updated_at") or "",
        "completed_at": job.get("completed_at") or "",
        "expires_at": job.get("expires_at") or "",
        "retry_of": job.get("retry_of") or "",
        "source_items": job_source_items(job),
        **model_details,
    }

    if include_input:
        payload["input_payload"] = job.get("input_payload") or {}

    return payload


def create_job(
    job_type,
    input_payload=None,
    user_id="",
    guest_session_id="",
    total_items=0,
    retry_of="",
):
    job_type = normalize_job_type(job_type)
    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()
    created_at = now_iso()
    expires_at = (utc_now() + timedelta(hours=job_retention_hours(bool(guest_session_id)))).isoformat() + "Z"
    job_id = new_job_id()

    with jobs_connection() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, user_id, guest_session_id, job_type, status, current_step,
                progress_percent, total_items, completed_items, failed_items,
                input_payload, result_payload, error_message, warning_messages,
                created_at, started_at, updated_at, completed_at, expires_at,
                rq_job_id, retry_of
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id or None,
                guest_session_id or None,
                job_type,
                "queued",
                "Queued",
                0,
                int(total_items or 0),
                0,
                0,
                json_dumps(input_payload or {}),
                json_dumps({}),
                "",
                json_dumps([]),
                created_at,
                None,
                created_at,
                None,
                expires_at,
                None,
                str(retry_of or "").strip() or None,
            ),
        )

    return get_job(job_id)


def get_job(job_id):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None

    with jobs_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row)


def update_job(job_id, **fields):
    job_id = str(job_id or "").strip()
    if not job_id:
        return None

    allowed = {
        "status",
        "current_step",
        "progress_percent",
        "total_items",
        "completed_items",
        "failed_items",
        "input_payload",
        "result_payload",
        "error_message",
        "warning_messages",
        "started_at",
        "completed_at",
        "expires_at",
        "rq_job_id",
        "retry_of",
    }
    updates = {}

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "status":
            value = normalize_status(value)
        if key in {"input_payload", "result_payload"}:
            value = json_dumps(value or {})
        if key == "warning_messages":
            value = json_dumps(value or [])
        updates[key] = value

    updates["updated_at"] = now_iso()

    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [job_id]

    with jobs_connection() as connection:
        connection.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)

    return get_job(job_id)


def append_job_warning(job_id, message):
    message = str(message or "").strip()
    if not message:
        return get_job(job_id)

    job = get_job(job_id)
    if not job:
        return None

    warnings = job.get("warning_messages") if isinstance(job.get("warning_messages"), list) else []
    warnings.append(message)
    return update_job(job_id, warning_messages=warnings)


def start_job(job_id, current_step="Starting"):
    return update_job(
        job_id,
        status="running",
        current_step=current_step,
        started_at=now_iso(),
        progress_percent=1,
    )


def update_job_progress(
    job_id,
    current_step=None,
    progress_percent=None,
    total_items=None,
    completed_items=None,
    failed_items=None,
    warning_message=None,
    result_payload=None,
):
    fields = {}
    if current_step is not None:
        fields["current_step"] = str(current_step or "").strip() or "Running"
    if progress_percent is not None:
        fields["progress_percent"] = max(0, min(100, int(progress_percent or 0)))
    if total_items is not None:
        fields["total_items"] = max(0, int(total_items or 0))
    if completed_items is not None:
        fields["completed_items"] = max(0, int(completed_items or 0))
    if failed_items is not None:
        fields["failed_items"] = max(0, int(failed_items or 0))
    if result_payload is not None:
        current = get_job(job_id) or {}
        merged = {
            **(current.get("result_payload") if isinstance(current.get("result_payload"), dict) else {}),
            **(result_payload if isinstance(result_payload, dict) else {}),
        }
        fields["result_payload"] = merged

    job = update_job(job_id, **fields) if fields else get_job(job_id)
    if warning_message:
        job = append_job_warning(job_id, warning_message)
    return job


def complete_job(job_id, result_payload=None, current_step="Completed"):
    return update_job(
        job_id,
        status="completed",
        current_step=current_step,
        progress_percent=100,
        result_payload=result_payload or {},
        error_message="",
        completed_at=now_iso(),
    )


def fail_job(job_id, error_message, result_payload=None, current_step="Failed"):
    return update_job(
        job_id,
        status="failed",
        current_step=current_step,
        result_payload=result_payload or {},
        error_message=str(error_message or "Job failed.").strip(),
        completed_at=now_iso(),
    )


def cancel_job(job_id, message="Cancelled"):
    return update_job(
        job_id,
        status="cancelled",
        current_step=message,
        completed_at=now_iso(),
    )


def job_cancelled(job_id):
    job = get_job(job_id)
    return bool(job and job.get("status") == "cancelled")


def cleanup_expired_jobs():
    now = now_iso()
    with jobs_connection() as connection:
        connection.execute("DELETE FROM jobs WHERE expires_at <= ?", (now,))


def delete_guest_jobs(guest_session_id):
    guest_session_id = str(guest_session_id or "").strip()
    if not guest_session_id:
        return 0

    with jobs_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM jobs WHERE guest_session_id = ?",
            (guest_session_id,),
        )
        return cursor.rowcount


def mark_stuck_jobs():
    cutoff = utc_now() - timedelta(minutes=job_timeout_minutes())
    cutoff_iso = cutoff.isoformat() + "Z"
    with jobs_connection() as connection:
        connection.execute(
            """
            UPDATE jobs
               SET status = 'failed',
                   current_step = 'Timed out',
                   error_message = 'This job stopped updating and timed out.',
                   completed_at = ?,
                   updated_at = ?
             WHERE status IN ('queued', 'running')
               AND updated_at <= ?
            """,
            (now_iso(), now_iso(), cutoff_iso),
        )


def recent_jobs(user_id="", guest_session_id="", include_all=False, limit=25):
    cleanup_expired_jobs()
    mark_stuck_jobs()
    limit = max(1, min(100, int(limit or 25)))
    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()

    if include_all:
        query = "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?"
        args = (limit,)
    elif guest_session_id:
        query = "SELECT * FROM jobs WHERE guest_session_id = ? ORDER BY updated_at DESC LIMIT ?"
        args = (guest_session_id, limit)
    else:
        query = "SELECT * FROM jobs WHERE COALESCE(user_id, '') = ? ORDER BY updated_at DESC LIMIT ?"
        args = (user_id, limit)

    with jobs_connection() as connection:
        rows = connection.execute(query, args).fetchall()

    return [row_to_job(row) for row in rows]


def user_can_access_job(job, user_id="", guest_session_id="", is_admin=False):
    if not job:
        return False
    if is_admin:
        return True

    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()
    job_user_id = str(job.get("user_id") or "").strip()
    job_guest_session_id = str(job.get("guest_session_id") or "").strip()

    if guest_session_id:
        return bool(job_guest_session_id and job_guest_session_id == guest_session_id)
    return bool(job_user_id and job_user_id == user_id)


def retryable_job_type(job_type):
    return normalize_job_type(job_type) in {
        "estimate-per-serving",
        "create-recipe-pdf",
        "product-matching",
        "upload-source-pdf",
        "upload-generated-pdf",
        "recipe-category-decision",
    }


def create_retry_job(job):
    if not job or not retryable_job_type(job.get("job_type")):
        return None

    return create_job(
        job.get("job_type"),
        input_payload=job.get("input_payload") or {},
        user_id=job.get("user_id") or "",
        guest_session_id=job.get("guest_session_id") or "",
        total_items=job.get("total_items") or 0,
        retry_of=job.get("id") or "",
    )
