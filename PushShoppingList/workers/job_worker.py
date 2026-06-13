import traceback

from flask import session

from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_cancelled
from PushShoppingList.services.job_service import start_job


def run_job(job_id):
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "Job not found."}

    if job_cancelled(job_id):
        return {"ok": False, "cancelled": True}

    start_job(job_id, "Starting")

    try:
        from PushShoppingList.app import create_app
        from PushShoppingList.services.job_tasks import run_job_task

        app = create_app()
        with app.test_request_context("/__job_worker__"):
            if job.get("guest_session_id"):
                session["is_guest"] = True
                session["guest_session_id"] = job.get("guest_session_id")
            elif job.get("user_id"):
                session["user_id"] = job.get("user_id")

            return run_job_task(job_id)
    except Exception as exc:
        print(f"[job_worker] job_id={job_id} failed: {exc}")
        traceback.print_exc()
        fail_job(job_id, "The job failed. Check server logs for details.")
        return {"ok": False, "error": "The job failed. Check server logs for details."}
