import os
import threading

from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import import_payload_is_menu
from PushShoppingList.services.job_service import update_job


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
QUEUE_AI_PANTRY_MENU = "ai-pantry-menu"
QUEUE_AI_PANTRY_RECIPE = "ai-pantry-recipe"
QUEUE_AI_PANTRY_MEDIA = "ai-pantry-media"
QUEUE_AI_PANTRY_PRODUCT = "ai-pantry-product"
QUEUE_AI_PANTRY_LIGHT = "ai-pantry-light"
DEFAULT_QUEUE_NAME = QUEUE_AI_PANTRY_LIGHT
ALL_QUEUE_NAMES = (
    QUEUE_AI_PANTRY_MENU,
    QUEUE_AI_PANTRY_RECIPE,
    QUEUE_AI_PANTRY_MEDIA,
    QUEUE_AI_PANTRY_PRODUCT,
    QUEUE_AI_PANTRY_LIGHT,
)
QUEUE_UNAVAILABLE_MESSAGE = "Job queue is unavailable. Check REDIS_URL and the RQ worker."


def redis_url():
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL


def queue_name():
    return os.getenv("RQ_QUEUE_NAME", DEFAULT_QUEUE_NAME).strip() or DEFAULT_QUEUE_NAME


def app_is_production():
    values = {
        os.getenv("FLASK_ENV", ""),
        os.getenv("APP_ENV", ""),
        os.getenv("ENV", ""),
        os.getenv("SHOPPING_APP_ENV", ""),
    }
    return any(str(value or "").strip().lower() in {"prod", "production"} for value in values)


def thread_fallback_enabled():
    raw_value = os.getenv("JOB_QUEUE_THREAD_FALLBACK")
    if raw_value is None:
        return not app_is_production()
    return raw_value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def inline_jobs_enabled():
    return os.getenv("JOB_QUEUE_MODE", "").strip().lower() in {"inline", "sync"}


def worker_queue_names():
    configured = os.getenv("WORKER_QUEUES", "").strip()
    if configured:
        names = [name.strip() for name in configured.split(",") if name.strip()]
        return names or list(ALL_QUEUE_NAMES)

    legacy = os.getenv("RQ_QUEUE_NAME", "").strip()
    if legacy:
        return [legacy]

    return list(ALL_QUEUE_NAMES)


def queue_name_for_job(job_type, input_payload=None):
    job_type = str(job_type or "").strip().lower().replace("_", "-")
    payload = input_payload if isinstance(input_payload, dict) else {}

    if job_type == "menu-import":
        return QUEUE_AI_PANTRY_MENU
    if job_type == "menu-generate-recipes":
        return QUEUE_AI_PANTRY_MENU
    if job_type == "recipe-import":
        return QUEUE_AI_PANTRY_RECIPE
    if job_type == "doc-photo-import":
        return QUEUE_AI_PANTRY_MENU if import_payload_is_menu(payload) else QUEUE_AI_PANTRY_MEDIA
    if job_type == "product-matching":
        return QUEUE_AI_PANTRY_PRODUCT
    return QUEUE_AI_PANTRY_LIGHT


def queue_name_for_existing_job(job_id, requested_queue_name=""):
    requested_queue_name = str(requested_queue_name or "").strip()
    if requested_queue_name:
        return requested_queue_name

    job = get_job(job_id) or {}
    existing_queue = str(job.get("queue_name") or "").strip()
    if existing_queue:
        return existing_queue

    return queue_name_for_job(job.get("job_type"), job.get("input_payload") or {})


def enqueue_job(job_id, queue_name_override=""):
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"ok": False, "error": "Job id is required."}

    target_queue_name = queue_name_for_existing_job(job_id, queue_name_override)
    update_job(job_id, queue_name=target_queue_name)

    if inline_jobs_enabled():
        from PushShoppingList.workers.job_worker import run_job

        run_job(job_id)
        return {"ok": True, "mode": "inline", "queue_name": target_queue_name}

    try:
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(redis_url())
        connection.ping()
        queue = Queue(target_queue_name, connection=connection)
        rq_job = queue.enqueue(
            "PushShoppingList.workers.job_worker.run_job",
            job_id,
            job_timeout=os.getenv("RQ_JOB_TIMEOUT", "30m"),
            result_ttl=int(os.getenv("RQ_RESULT_TTL_SECONDS", "86400")),
            failure_ttl=int(os.getenv("RQ_FAILURE_TTL_SECONDS", "86400")),
        )
        update_job(job_id, rq_job_id=rq_job.id, queue_name=target_queue_name)
        return {"ok": True, "mode": "rq", "rq_job_id": rq_job.id, "queue_name": target_queue_name}
    except Exception as exc:
        if not thread_fallback_enabled():
            fail_job(
                job_id,
                QUEUE_UNAVAILABLE_MESSAGE,
                current_step="Queue unavailable",
            )
            return {
                "ok": False,
                "error": QUEUE_UNAVAILABLE_MESSAGE,
                "details": str(exc),
                "queue_name": target_queue_name,
            }

        thread = threading.Thread(
            target=_run_job_thread,
            args=(job_id,),
            name=f"job-worker-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return {
            "ok": True,
            "mode": "thread",
            "queue_name": target_queue_name,
            "warning": "Redis/RQ was unavailable; running in a local background thread.",
        }


def _run_job_thread(job_id):
    from PushShoppingList.workers.job_worker import run_job

    run_job(job_id)


def cancel_queued_rq_job(rq_job_id):
    rq_job_id = str(rq_job_id or "").strip()
    if not rq_job_id:
        return False

    stopped = False
    try:
        from redis import Redis
        from rq.command import send_stop_job_command
        from rq.job import Job

        connection = Redis.from_url(redis_url())
        try:
            send_stop_job_command(connection, rq_job_id)
            stopped = True
        except Exception:
            stopped = False

        job = Job.fetch(rq_job_id, connection=connection)
        job.cancel()
        return True
    except Exception:
        return stopped
