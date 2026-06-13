import os
import socket
import time
import traceback

from flask import session

from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_cancelled
from PushShoppingList.services.job_service import try_start_job


def worker_id():
    configured = str(os.getenv("WORKER_ID") or "").strip()
    if configured:
        return configured
    return f"{socket.gethostname()}:{os.getpid()}"


def current_rq_queue_name(job):
    try:
        from rq import get_current_job

        rq_job = get_current_job()
        if rq_job and getattr(rq_job, "origin", None):
            return str(rq_job.origin or "").strip()
    except Exception:
        pass
    return str((job or {}).get("queue_name") or "").strip()


def run_job(job_id):
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "Job not found."}

    if job_cancelled(job_id):
        return {"ok": False, "cancelled": True}

    try:
        from PushShoppingList.app import create_app
        from PushShoppingList.services.job_queue_service import enqueue_job
        from PushShoppingList.services.job_runtime_context import job_context
        from PushShoppingList.services.job_tasks import job_start_metadata
        from PushShoppingList.services.job_tasks import run_job_task

        app = create_app()
        with app.test_request_context("/__job_worker__"):
            if job.get("guest_session_id"):
                session["is_guest"] = True
                session["guest_session_id"] = job.get("guest_session_id")
            elif job.get("user_id"):
                session["user_id"] = job.get("user_id")

            queue_name = current_rq_queue_name(job)
            model_snapshot = job_start_metadata(job)
            start_result = try_start_job(
                job_id,
                "Starting",
                queue_name=queue_name,
                model_used=model_snapshot.get("model_used", ""),
                model_source=model_snapshot.get("model_source", ""),
                model_env_var_used=model_snapshot.get("model_env_var_used") or model_snapshot.get("model_env_var", ""),
                worker_id=worker_id(),
            )
            if start_result.get("cancelled") or start_result.get("terminal"):
                return {"ok": True, "skipped": True}
            if start_result.get("deferred"):
                delay = max(1, int(start_result.get("delay_seconds") or 5))
                time.sleep(delay)
                queue_result = enqueue_job(job_id, queue_name_override=queue_name)
                if not queue_result.get("ok"):
                    fail_job(job_id, queue_result.get("error") or "Unable to requeue limited job.")
                return {
                    "ok": bool(queue_result.get("ok")),
                    "deferred": True,
                    "delay_seconds": delay,
                    "queue": queue_result,
                }
            if not start_result.get("started"):
                return {"ok": False, "error": start_result.get("error") or "Unable to start job."}

            started_job = start_result.get("job") or get_job(job_id) or {}
            with job_context(
                job_id=job_id,
                queue_name=started_job.get("queue_name") or queue_name,
                model_used=started_job.get("model_used") or model_snapshot.get("model_used"),
                model_source=started_job.get("model_source") or model_snapshot.get("model_source"),
                model_env_var_used=started_job.get("model_env_var_used") or model_snapshot.get("model_env_var_used") or model_snapshot.get("model_env_var"),
                worker_id=started_job.get("worker_id") or worker_id(),
            ):
                return run_job_task(job_id)
    except Exception as exc:
        print(f"[job_worker] job_id={job_id} failed: {exc}")
        traceback.print_exc()
        fail_job(job_id, "The job failed. Check server logs for details.")
        return {"ok": False, "error": "The job failed. Check server logs for details."}
