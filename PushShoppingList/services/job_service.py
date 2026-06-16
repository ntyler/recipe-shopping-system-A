import json
import os
import sqlite3
import threading
import uuid
from urllib.parse import quote
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
DEFAULT_QUEUED_LIMIT_PER_OWNER_TYPE = 5
ACTIVE_LIMITS_BY_KEY = {
    "menu-import": 1,
    "menu-ai": 3,
    "menu-heavy": 1,
    "cookbook-routine": 1,
    "recipe-import": 2,
    "media-import": 1,
}

JOBS_DB_PATH = Path(
    os.getenv("SHOPPING_APP_JOBS_DB", PACKAGE_DIR / "user_data" / "jobs.sqlite3")
)
JOBS_DB_LOCK = threading.RLock()


JOB_SCHEMA_ADDITIONAL_COLUMNS = {
    "queue_name": "TEXT NOT NULL DEFAULT ''",
    "attempts": "INTEGER NOT NULL DEFAULT 0",
    "model_used": "TEXT NOT NULL DEFAULT ''",
    "model_source": "TEXT NOT NULL DEFAULT ''",
    "model_env_var_used": "TEXT NOT NULL DEFAULT ''",
    "worker_id": "TEXT NOT NULL DEFAULT ''",
    "finished_at": "TEXT",
}


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
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    for column_name, column_sql in JOB_SCHEMA_ADDITIONAL_COLUMNS.items():
        if column_name in existing_columns:
            continue
        connection.execute(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_sql}")

    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_user ON jobs(user_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_guest ON jobs(guest_session_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_expires_at ON jobs(expires_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_queue_status ON jobs(queue_name, status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner_type_status ON jobs(user_id, guest_session_id, job_type, status)")


def normalize_job_type(job_type):
    return str(job_type or "").strip().lower().replace("_", "-")


def normalize_status(status):
    status = str(status or "").strip().lower()
    return status if status in JOB_STATUSES else "queued"


def import_payload_is_menu(payload):
    payload = payload if isinstance(payload, dict) else {}
    mode = str(
        payload.get("import_mode")
        or payload.get("extraction_mode")
        or payload.get("mode")
        or ""
    ).strip().lower()
    return mode in {"menu", "menu_extract", "menu-extract"}


def upload_payload_is_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    upload_mode = str(payload.get("upload_mode") or "").strip().lower()
    source_type = str(payload.get("source_type") or payload.get("import_source_type") or "").strip().lower()
    content_type = str(payload.get("content_type") or "").strip().lower()
    filename = str(payload.get("filename") or "").strip().lower()
    return bool(
        upload_mode == "image"
        or source_type == "image"
        or content_type.startswith("image/")
        or filename.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"))
    )


def job_limit_key(job_type, input_payload=None):
    job_type = normalize_job_type(job_type)
    payload = input_payload if isinstance(input_payload, dict) else {}
    if job_type == "menu-import":
        return "menu-import"
    if job_type == "menu-generate-recipes":
        return "menu-ai"
    if job_type == "menu-deferred-heavy-tasks":
        return "menu-heavy"
    if job_type == "cookbook-infer-missing-details":
        return "cookbook-routine"
    if job_type == "recipe-import":
        return "recipe-import"
    if job_type == "doc-photo-import":
        return "menu-import" if import_payload_is_menu(payload) else "media-import"
    return job_type


def active_limit_for_job(job_type, input_payload=None):
    if job_limit_key(job_type, input_payload) == "menu-ai":
        return env_int("MAX_PARALLEL_MENU_AI_JOBS", ACTIVE_LIMITS_BY_KEY["menu-ai"], minimum=1)
    return ACTIVE_LIMITS_BY_KEY.get(job_limit_key(job_type, input_payload), 0)


def queued_limit_per_owner_type():
    return env_int(
        "JOB_QUEUE_MAX_QUEUED_PER_USER_TYPE",
        DEFAULT_QUEUED_LIMIT_PER_OWNER_TYPE,
        minimum=1,
    )


def owner_identity(user_id="", guest_session_id=""):
    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()
    if guest_session_id:
        return "guest", guest_session_id
    return "user", user_id


def owner_where_clause(user_id="", guest_session_id=""):
    owner_type, owner_value = owner_identity(user_id, guest_session_id)
    if owner_type == "guest":
        return "guest_session_id = ?", (owner_value,)
    return "COALESCE(user_id, '') = ?", (owner_value,)


def _row_limit_key(row):
    payload = json_loads(row["input_payload"], {}) if row else {}
    return job_limit_key(row["job_type"], payload)


def _owner_jobs_by_status(connection, user_id="", guest_session_id="", statuses=None):
    statuses = [normalize_status(status) for status in (statuses or []) if str(status or "").strip()]
    if not statuses:
        statuses = ["queued", "running"]
    owner_clause, owner_args = owner_where_clause(user_id, guest_session_id)
    placeholders = ", ".join("?" for _ in statuses)
    return connection.execute(
        f"""
        SELECT *
          FROM jobs
         WHERE {owner_clause}
           AND status IN ({placeholders})
         ORDER BY created_at ASC
        """,
        (*owner_args, *statuses),
    ).fetchall()


def owner_job_count_for_limit_key(
    user_id="",
    guest_session_id="",
    limit_key="",
    statuses=None,
    exclude_job_id="",
    connection=None,
):
    limit_key = str(limit_key or "").strip()
    exclude_job_id = str(exclude_job_id or "").strip()

    def count_rows(active_connection):
        rows = _owner_jobs_by_status(
            active_connection,
            user_id=user_id,
            guest_session_id=guest_session_id,
            statuses=statuses,
        )
        return sum(
            1
            for row in rows
            if str(row["id"] or "") != exclude_job_id and _row_limit_key(row) == limit_key
        )

    if connection is not None:
        return count_rows(connection)

    with jobs_connection() as active_connection:
        return count_rows(active_connection)


def queued_limit_status(user_id="", guest_session_id="", job_type="", input_payload=None):
    limit_key = job_limit_key(job_type, input_payload)
    queued_count = owner_job_count_for_limit_key(
        user_id=user_id,
        guest_session_id=guest_session_id,
        limit_key=limit_key,
        statuses=["queued"],
    )
    limit = queued_limit_per_owner_type()
    if queued_count >= limit:
        return {
            "ok": False,
            "limit_key": limit_key,
            "limit": limit,
            "queued_count": queued_count,
            "message": (
                "You already have several jobs queued for this import type. "
                "Let one finish or cancel an older queued job before starting another."
            ),
        }
    return {
        "ok": True,
        "limit_key": limit_key,
        "limit": limit,
        "queued_count": queued_count,
        "message": "",
    }


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


def _append_recipe_source_item(items, seen, value, detail="menu item"):
    label = _safe_source_label(value)
    if not label:
        return

    key = ("recipe", label)
    if key in seen:
        return

    seen.add(key)
    items.append({
        "type": "recipe",
        "label": label,
        "detail": str(detail or "").strip(),
        "url": f"/recipe/edit?url={quote(str(value or '').strip(), safe='')}",
        "recipe_url": str(value or "").strip(),
    })


def job_source_items(job):
    input_payload = job.get("input_payload") if isinstance(job.get("input_payload"), dict) else {}
    items = []
    seen = set()
    job_type = normalize_job_type(job.get("job_type"))

    if job_type in {"menu-generate-recipes", "menu-deferred-heavy-tasks", "cookbook-infer-missing-details"}:
        menu_recipe_urls = []
        for key in ("recipe_urls", "urls"):
            values = input_payload.get(key)
            if isinstance(values, str):
                values = [line.strip() for line in values.splitlines() if line.strip()]
            if isinstance(values, list):
                menu_recipe_urls.extend(str(value or "").strip() for value in values if str(value or "").strip())
        for key in ("recipe_url", "url", "source_url"):
            value = str(input_payload.get(key) or "").strip()
            if value:
                menu_recipe_urls.append(value)
        for recipe_url in menu_recipe_urls:
            _append_recipe_source_item(items, seen, recipe_url)
        return items

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
    model_env_var = _first_text(
        job.get("model_env_var_used"),
        result_payload.get("model_env_var_used"),
        result_payload.get("model_env_var"),
        input_payload.get("model_env_var_used"),
        input_payload.get("model_env_var"),
    )
    return {
        "model_used": _first_text(
            job.get("model_used"),
            result_payload.get("model_used"),
            result_payload.get("model"),
            input_payload.get("model_used"),
            input_payload.get("model"),
        ),
        "model_source": _first_text(
            job.get("model_source"),
            result_payload.get("model_source"),
            input_payload.get("model_source"),
        ),
        "model_env_var": model_env_var,
        "model_env_var_used": model_env_var,
    }


def queued_position(job):
    if not job or job.get("status") != "queued":
        return None

    queue_name = str(job.get("queue_name") or "").strip()
    if not queue_name:
        return None

    with jobs_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS position
              FROM jobs
             WHERE queue_name = ?
               AND status = 'queued'
               AND created_at <= ?
            """,
            (queue_name, job.get("created_at") or ""),
        ).fetchone()

    position = int(row["position"] or 0) if row else 0
    return position or None


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
        "finished_at": job.get("finished_at") or job.get("completed_at") or "",
        "expires_at": job.get("expires_at") or "",
        "queue_name": job.get("queue_name") or "",
        "rq_job_id": job.get("rq_job_id") or "",
        "attempts": int(job.get("attempts") or 0),
        "retry_count": int(job.get("attempts") or 0),
        "worker_id": job.get("worker_id") or "",
        "queued_position": queued_position(job),
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
    queue_name="",
    job_id="",
):
    job_type = normalize_job_type(job_type)
    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()
    queue_name = str(queue_name or "").strip()
    created_at = now_iso()
    expires_at = (utc_now() + timedelta(hours=job_retention_hours(bool(guest_session_id)))).isoformat() + "Z"
    job_id = str(job_id or "").strip() or new_job_id()

    with jobs_connection() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, user_id, guest_session_id, job_type, status, current_step,
                progress_percent, total_items, completed_items, failed_items,
                input_payload, result_payload, error_message, warning_messages,
                created_at, started_at, updated_at, completed_at, expires_at,
                rq_job_id, retry_of, queue_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                queue_name,
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
        "finished_at",
        "expires_at",
        "rq_job_id",
        "retry_of",
        "queue_name",
        "attempts",
        "model_used",
        "model_source",
        "model_env_var_used",
        "worker_id",
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
        if key == "attempts":
            value = max(0, int(value or 0))
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
    if job_cancelled(job_id):
        return get_job(job_id)

    job = get_job(job_id) or {}
    return update_job(
        job_id,
        status="running",
        current_step=current_step,
        started_at=job.get("started_at") or now_iso(),
        progress_percent=1,
        attempts=int(job.get("attempts") or 0) + 1,
    )


def active_limit_wait_message(limit_key):
    labels = {
        "menu-import": "menu import",
        "menu-ai": "menu recipe inference",
        "menu-heavy": "menu PDF/nutrition routine",
        "cookbook-routine": "cookbook inference routine",
        "recipe-import": "recipe import",
        "media-import": "media or vision import",
    }
    label = labels.get(limit_key, "job")
    return f"Queued behind your active {label}. This job will start automatically."


def retry_delay_for_attempts(attempts):
    attempts = max(0, int(attempts or 0))
    return min(60, 5 + (attempts * 5))


def try_start_job(
    job_id,
    current_step="Starting",
    queue_name="",
    model_used="",
    model_source="",
    model_env_var_used="",
    worker_id="",
):
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"started": False, "ok": False, "error": "Job id is required."}

    with jobs_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return {"started": False, "ok": False, "error": "Job not found."}

        if row["status"] == "cancelled":
            return {"started": False, "ok": True, "cancelled": True, "job": row_to_job(row)}
        if row["status"] in TERMINAL_JOB_STATUSES:
            return {"started": False, "ok": True, "terminal": True, "job": row_to_job(row)}
        if row["status"] == "running":
            return {"started": False, "ok": True, "already_running": True, "job": row_to_job(row)}

        payload = json_loads(row["input_payload"], {})
        limit_key = job_limit_key(row["job_type"], payload)
        active_limit = active_limit_for_job(row["job_type"], payload)
        attempts = int(row["attempts"] or 0) + 1
        now = now_iso()

        if active_limit > 0:
            running_count = owner_job_count_for_limit_key(
                user_id=row["user_id"] or "",
                guest_session_id=row["guest_session_id"] or "",
                limit_key=limit_key,
                statuses=["running"],
                exclude_job_id=job_id,
                connection=connection,
            )
            if running_count >= active_limit:
                message = active_limit_wait_message(limit_key)
                connection.execute(
                    """
                    UPDATE jobs
                       SET current_step = ?,
                           attempts = ?,
                           queue_name = COALESCE(NULLIF(?, ''), queue_name),
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (message, attempts, queue_name, now, job_id),
                )
                updated = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return {
                    "started": False,
                    "ok": True,
                    "deferred": True,
                    "limit_key": limit_key,
                    "delay_seconds": retry_delay_for_attempts(attempts),
                    "message": message,
                    "job": row_to_job(updated),
                }

        connection.execute(
            """
            UPDATE jobs
               SET status = 'running',
                   current_step = ?,
                   started_at = COALESCE(started_at, ?),
                   progress_percent = CASE WHEN progress_percent < 1 THEN 1 ELSE progress_percent END,
                   attempts = ?,
                   queue_name = COALESCE(NULLIF(?, ''), queue_name),
                   model_used = ?,
                   model_source = ?,
                   model_env_var_used = ?,
                   worker_id = ?,
                   updated_at = ?
             WHERE id = ?
               AND status = 'queued'
            """,
            (
                current_step,
                now,
                attempts,
                queue_name,
                str(model_used or "").strip(),
                str(model_source or "").strip(),
                str(model_env_var_used or "").strip(),
                str(worker_id or "").strip(),
                now,
                job_id,
            ),
        )
        updated = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    job = row_to_job(updated)
    return {
        "started": bool(job and job.get("status") == "running"),
        "ok": True,
        "job": job,
        "limit_key": job_limit_key(job.get("job_type"), job.get("input_payload") if job else {}),
    }


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
    if job_cancelled(job_id):
        return get_job(job_id)

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
    if job_cancelled(job_id):
        return get_job(job_id)

    finished_at = now_iso()
    return update_job(
        job_id,
        status="completed",
        current_step=current_step,
        progress_percent=100,
        result_payload=result_payload or {},
        error_message="",
        completed_at=finished_at,
        finished_at=finished_at,
    )


def fail_job(job_id, error_message, result_payload=None, current_step="Failed"):
    if job_cancelled(job_id):
        return get_job(job_id)

    finished_at = now_iso()
    return update_job(
        job_id,
        status="failed",
        current_step=current_step,
        result_payload=result_payload or {},
        error_message=str(error_message or "Job failed.").strip(),
        completed_at=finished_at,
        finished_at=finished_at,
    )


def cancel_job(job_id, message="Cancelled"):
    finished_at = now_iso()
    return update_job(
        job_id,
        status="cancelled",
        current_step=message,
        completed_at=finished_at,
        finished_at=finished_at,
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


def clear_recent_jobs(user_id="", guest_session_id="", include_all=False):
    cleanup_expired_jobs()
    mark_stuck_jobs()

    statuses = sorted(TERMINAL_JOB_STATUSES)
    placeholders = ", ".join("?" for _ in statuses)
    user_id = str(user_id or "").strip()
    guest_session_id = str(guest_session_id or "").strip()

    if include_all:
        query = f"DELETE FROM jobs WHERE status IN ({placeholders})"
        args = tuple(statuses)
    elif guest_session_id:
        query = f"DELETE FROM jobs WHERE guest_session_id = ? AND status IN ({placeholders})"
        args = (guest_session_id, *statuses)
    else:
        query = f"DELETE FROM jobs WHERE COALESCE(user_id, '') = ? AND status IN ({placeholders})"
        args = (user_id, *statuses)

    with jobs_connection() as connection:
        cursor = connection.execute(query, args)
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
                   finished_at = ?,
                   updated_at = ?
             WHERE status IN ('queued', 'running')
               AND updated_at <= ?
            """,
            (now_iso(), now_iso(), now_iso(), cutoff_iso),
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
        "menu-generate-recipes",
        "cookbook-infer-missing-details",
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
        queue_name=job.get("queue_name") or "",
    )
