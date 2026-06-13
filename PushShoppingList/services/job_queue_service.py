import os
import threading

from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import update_job


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_QUEUE_NAME = "ai-pantry"


def redis_url():
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL


def queue_name():
    return os.getenv("RQ_QUEUE_NAME", DEFAULT_QUEUE_NAME).strip() or DEFAULT_QUEUE_NAME


def thread_fallback_enabled():
    return os.getenv("JOB_QUEUE_THREAD_FALLBACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def inline_jobs_enabled():
    return os.getenv("JOB_QUEUE_MODE", "").strip().lower() in {"inline", "sync"}


def enqueue_job(job_id):
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"ok": False, "error": "Job id is required."}

    if inline_jobs_enabled():
        from PushShoppingList.workers.job_worker import run_job

        run_job(job_id)
        return {"ok": True, "mode": "inline"}

    try:
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(redis_url())
        connection.ping()
        queue = Queue(queue_name(), connection=connection)
        rq_job = queue.enqueue(
            "PushShoppingList.workers.job_worker.run_job",
            job_id,
            job_timeout=os.getenv("RQ_JOB_TIMEOUT", "30m"),
            result_ttl=int(os.getenv("RQ_RESULT_TTL_SECONDS", "86400")),
            failure_ttl=int(os.getenv("RQ_FAILURE_TTL_SECONDS", "86400")),
        )
        update_job(job_id, rq_job_id=rq_job.id)
        return {"ok": True, "mode": "rq", "rq_job_id": rq_job.id}
    except Exception as exc:
        if not thread_fallback_enabled():
            fail_job(
                job_id,
                "Job queue is unavailable. Check REDIS_URL and the RQ worker.",
                current_step="Queue unavailable",
            )
            return {
                "ok": False,
                "error": "Job queue is unavailable. Check REDIS_URL and the RQ worker.",
                "details": str(exc),
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
            "warning": "Redis/RQ was unavailable; running in a local background thread.",
        }


def _run_job_thread(job_id):
    from PushShoppingList.workers.job_worker import run_job

    run_job(job_id)


def cancel_queued_rq_job(rq_job_id):
    rq_job_id = str(rq_job_id or "").strip()
    if not rq_job_id:
        return False

    try:
        from redis import Redis
        from rq.job import Job

        connection = Redis.from_url(redis_url())
        job = Job.fetch(rq_job_id, connection=connection)
        job.cancel()
        return True
    except Exception:
        return False
