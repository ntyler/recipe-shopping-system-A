import importlib.metadata
import importlib.util
import os
import threading
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from PushShoppingList.services.job_service import fail_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import import_payload_is_menu
from PushShoppingList.services.job_service import update_job


DEFAULT_REDIS_URL = "redis://localhost:6379/0"
REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
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
_STARTUP_DIAGNOSTICS_LOGGED = False
_REDIS_NOT_CONFIGURED_LOGGED = False
_ACTIVE_THREAD_JOBS_LOCK = threading.RLock()
_ACTIVE_THREAD_JOB_IDS = set()


class JobQueueUnavailable(RuntimeError):
    def __init__(self, reason, message, original_exception=None):
        super().__init__(message)
        self.reason = str(reason or "job_queue_unavailable")
        self.original_exception = original_exception


def redis_url():
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL).strip() or DEFAULT_REDIS_URL


def redis_url_configured():
    return bool(os.getenv("REDIS_URL", "").strip())


def redis_url_source():
    return "REDIS_URL" if redis_url_configured() else "default"


def redacted_redis_url(value=None):
    value = str(value or redis_url() or "").strip()
    if not value:
        return ""

    try:
        parsed = urlsplit(value)
    except Exception:
        return "<invalid Redis URL>"

    if not parsed.scheme:
        return "<invalid Redis URL>"

    username = parsed.username or ""
    hostname = parsed.hostname or ""
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
    port = f":{parsed_port}" if parsed_port else ""
    auth = ""
    if username:
        auth = f"{username}:***@"
    elif parsed.password:
        auth = "***@"

    netloc = f"{auth}{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


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


def _bool_for_log(value):
    return "true" if bool(value) else "false"


def _package_installed(module_name):
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _package_version(distribution_name):
    try:
        return importlib.metadata.version(distribution_name)
    except Exception:
        return ""


def _redis_connection_from_class(Redis):
    return Redis.from_url(
        redis_url(),
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
    )


def log_redis_not_configured_once():
    global _REDIS_NOT_CONFIGURED_LOGGED
    if _REDIS_NOT_CONFIGURED_LOGGED:
        return
    _REDIS_NOT_CONFIGURED_LOGGED = True
    print("[Job Queue] Redis not configured. Using local thread fallback for development.")


def _missing_dependency_error(module_name, package_name, install_name):
    return JobQueueUnavailable(
        f"missing_{module_name}_package",
        (
            f"The {package_name} Python package is not installed. "
            f"Run: C:\\Python39\\python.exe -m pip install -r requirements.txt "
            f"(missing dependency: {install_name})"
        ),
    )


def redis_queue_connection():
    try:
        from redis import Redis
    except ImportError as exc:
        raise _missing_dependency_error("redis", "Redis", "redis") from exc

    try:
        from rq import Queue
    except ImportError as exc:
        raise _missing_dependency_error("rq", "RQ", "rq") from exc

    try:
        connection = _redis_connection_from_class(Redis)
        connection.ping()
        return connection, Queue
    except ValueError as exc:
        raise JobQueueUnavailable(
            "invalid_redis_url",
            f"REDIS_URL is invalid ({redacted_redis_url()}): {exc}",
            exc,
        ) from exc
    except Exception as exc:
        source_label = "REDIS_URL" if redis_url_configured() else "the default local Redis URL"
        raise JobQueueUnavailable(
            "redis_connection_failed",
            f"Redis connection failed using {source_label} ({redacted_redis_url()}): {exc}",
            exc,
        ) from exc


def redis_queue_readiness(check_connection=True):
    redis_installed = _package_installed("redis")
    rq_installed = _package_installed("rq")
    readiness = {
        "redis_package_installed": redis_installed,
        "redis_package_version": _package_version("redis") if redis_installed else "",
        "rq_package_installed": rq_installed,
        "rq_package_version": _package_version("rq") if rq_installed else "",
        "redis_url_configured": redis_url_configured(),
        "redis_url_source": redis_url_source(),
        "redis_url": redacted_redis_url(),
        "redis_connection_checked": bool(check_connection),
        "redis_connection_succeeded": False,
        "redis_connection_error": "",
        "redis_connection_error_type": "",
        "thread_fallback_enabled": thread_fallback_enabled(),
        "inline_jobs_enabled": inline_jobs_enabled(),
        "mode": "unknown",
        "reason": "",
        "menu_queue": QUEUE_AI_PANTRY_MENU,
        "worker_queues": worker_queue_names(),
    }

    if not redis_installed:
        readiness["reason"] = "missing_redis_package"
    elif not redis_url_configured():
        readiness["reason"] = "redis_not_configured"
        readiness["redis_connection_checked"] = False
    elif check_connection:
        try:
            from redis import Redis

            connection = _redis_connection_from_class(Redis)
            connection.ping()
            readiness["redis_connection_succeeded"] = True
        except ValueError as exc:
            readiness["reason"] = "invalid_redis_url"
            readiness["redis_connection_error"] = str(exc)
            readiness["redis_connection_error_type"] = type(exc).__name__
        except Exception as exc:
            readiness["reason"] = "redis_connection_failed"
            readiness["redis_connection_error"] = str(exc)
            readiness["redis_connection_error_type"] = type(exc).__name__
    else:
        readiness["reason"] = "not_checked"

    if redis_installed and not rq_installed:
        readiness["reason"] = "missing_rq_package"

    if readiness["inline_jobs_enabled"]:
        readiness["mode"] = "inline"
        readiness["fallback_intent"] = "JOB_QUEUE_MODE requests inline execution"
    elif (
        readiness["redis_package_installed"]
        and readiness["rq_package_installed"]
        and readiness["redis_connection_succeeded"]
    ):
        readiness["mode"] = "redis/rq"
        readiness["reason"] = "redis_connected"
        readiness["fallback_intent"] = ""
    elif readiness["thread_fallback_enabled"]:
        readiness["mode"] = "local/thread"
        if not readiness["redis_url_configured"]:
            readiness["fallback_intent"] = "development fallback allowed because REDIS_URL is not configured"
        else:
            readiness["fallback_intent"] = "JOB_QUEUE_THREAD_FALLBACK allows local thread fallback"
    else:
        readiness["mode"] = "unavailable"
        readiness["fallback_intent"] = "JOB_QUEUE_THREAD_FALLBACK is disabled"

    return readiness


def log_job_queue_startup_diagnostics(force=False):
    global _STARTUP_DIAGNOSTICS_LOGGED
    if _STARTUP_DIAGNOSTICS_LOGGED and not force:
        return redis_queue_readiness(check_connection=False)

    _STARTUP_DIAGNOSTICS_LOGGED = True
    readiness = redis_queue_readiness(check_connection=True)
    print(
        "[Job Queue] action=startup_diagnostics "
        f"redis_package_installed={_bool_for_log(readiness['redis_package_installed'])} "
        f"redis_package_version={readiness['redis_package_version'] or 'none'} "
        f"rq_package_installed={_bool_for_log(readiness['rq_package_installed'])} "
        f"rq_package_version={readiness['rq_package_version'] or 'none'} "
        f"redis_url_configured={_bool_for_log(readiness['redis_url_configured'])} "
        f"redis_url_source={readiness['redis_url_source']} "
        f"redis_url={readiness['redis_url']} "
        f"redis_connection_succeeded={_bool_for_log(readiness['redis_connection_succeeded'])} "
        f"redis_connection_error_type={readiness['redis_connection_error_type'] or 'none'} "
        f"mode={readiness['mode']} "
        f"thread_fallback_enabled={_bool_for_log(readiness['thread_fallback_enabled'])} "
        f"reason={readiness['reason'] or 'none'} "
        f"fallback_intent={readiness.get('fallback_intent') or 'none'}"
    )
    if readiness.get("redis_connection_error"):
        level = "warning" if readiness["thread_fallback_enabled"] else "error"
        print(
            "[Job Queue] action=redis_readiness_error "
            f"level={level} "
            f"redis_url_configured={_bool_for_log(readiness['redis_url_configured'])} "
            f"redis_url={readiness['redis_url']} "
            f"reason={readiness['reason']} "
            f"error={readiness['redis_connection_error']}"
        )
    elif readiness.get("reason") == "redis_not_configured" and readiness.get("thread_fallback_enabled"):
        log_redis_not_configured_once()
    return readiness


def _log_queue_unavailable(action, unavailable, job_id="", queue_name_value=""):
    level = "warning" if thread_fallback_enabled() else "error"
    job_part = f" job_id={job_id}" if job_id else ""
    queue_part = f" queue={queue_name_value}" if queue_name_value else ""
    print(
        f"[Job Queue] action={action} level={level}{job_part}{queue_part} "
        f"reason={unavailable.reason} "
        f"redis_url_configured={_bool_for_log(redis_url_configured())} "
        f"redis_url={redacted_redis_url()} "
        f"thread_fallback_enabled={_bool_for_log(thread_fallback_enabled())} "
        f"error={unavailable}"
    )


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
    if job_type == "menu-deferred-heavy-tasks":
        return QUEUE_AI_PANTRY_LIGHT
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


def _start_thread_fallback(job_id, target_queue_name, reason="", detail=""):
    with _ACTIVE_THREAD_JOBS_LOCK:
        if job_id in _ACTIVE_THREAD_JOB_IDS:
            print(
                f"[Job Queue] action=thread_fallback_already_running job_id={job_id} "
                f"queue={target_queue_name} reason={reason or 'already_running'}"
            )
            return {
                "ok": True,
                "mode": "thread",
                "queue_name": target_queue_name,
                "already_running": True,
                "reason": reason or "already_running",
            }
        _ACTIVE_THREAD_JOB_IDS.add(job_id)

    thread = threading.Thread(
        target=_run_job_thread,
        args=(job_id,),
        name=f"job-worker-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    print(
        f"[Job Queue] action=thread_fallback_started job_id={job_id} "
        f"queue={target_queue_name} thread_name={thread.name} "
        f"reason={reason or 'thread_fallback'} detail={detail or 'none'}"
    )
    return {
        "ok": True,
        "mode": "thread",
        "queue_name": target_queue_name,
        "warning": "Redis/RQ was unavailable; running in a local background thread.",
        "reason": reason or "thread_fallback",
    }


def enqueue_job(job_id, queue_name_override=""):
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"ok": False, "error": "Job id is required."}

    target_queue_name = queue_name_for_existing_job(job_id, queue_name_override)
    update_job(job_id, queue_name=target_queue_name)
    print(f"[Job Queue] action=enqueue_requested job_id={job_id} queue={target_queue_name}")

    if inline_jobs_enabled():
        from PushShoppingList.workers.job_worker import run_job

        print(f"[Job Queue] action=inline_start job_id={job_id} queue={target_queue_name}")
        run_job(job_id)
        print(f"[Job Queue] action=inline_done job_id={job_id} queue={target_queue_name}")
        return {"ok": True, "mode": "inline", "queue_name": target_queue_name}

    if not redis_url_configured():
        if thread_fallback_enabled():
            log_redis_not_configured_once()
            return _start_thread_fallback(
                job_id,
                target_queue_name,
                reason="redis_not_configured",
                detail="REDIS_URL is not configured",
            )
        fail_job(
            job_id,
            QUEUE_UNAVAILABLE_MESSAGE,
            current_step="Queue unavailable",
        )
        return {
            "ok": False,
            "error": QUEUE_UNAVAILABLE_MESSAGE,
            "details": "REDIS_URL is not configured and local thread fallback is disabled.",
            "reason": "redis_not_configured",
            "queue_name": target_queue_name,
        }

    queue_unavailable = None
    try:
        connection, Queue = redis_queue_connection()
        queue = Queue(target_queue_name, connection=connection)
        rq_job = queue.enqueue(
            "PushShoppingList.workers.job_worker.run_job",
            job_id,
            job_timeout=os.getenv("RQ_JOB_TIMEOUT", "30m"),
            result_ttl=int(os.getenv("RQ_RESULT_TTL_SECONDS", "86400")),
            failure_ttl=int(os.getenv("RQ_FAILURE_TTL_SECONDS", "86400")),
        )
        update_job(job_id, rq_job_id=rq_job.id, queue_name=target_queue_name)
        print(f"[Job Queue] action=rq_enqueued job_id={job_id} queue={target_queue_name} rq_job_id={rq_job.id}")
        return {"ok": True, "mode": "rq", "rq_job_id": rq_job.id, "queue_name": target_queue_name}
    except JobQueueUnavailable as exc:
        queue_unavailable = exc
    except Exception as exc:
        queue_unavailable = JobQueueUnavailable(
            "rq_enqueue_failed",
            f"RQ enqueue failed for queue {target_queue_name}: {exc}",
            exc,
        )

    if queue_unavailable:
        _log_queue_unavailable(
            "enqueue_unavailable",
            queue_unavailable,
            job_id=job_id,
            queue_name_value=target_queue_name,
        )
        if not thread_fallback_enabled():
            print(
                f"[Job Queue] action=enqueue_failed job_id={job_id} queue={target_queue_name} "
                f"thread_fallback=false reason={queue_unavailable.reason} error={queue_unavailable}"
            )
            fail_job(
                job_id,
                QUEUE_UNAVAILABLE_MESSAGE,
                current_step="Queue unavailable",
            )
            return {
                "ok": False,
                "error": QUEUE_UNAVAILABLE_MESSAGE,
                "details": str(queue_unavailable),
                "reason": queue_unavailable.reason,
                "queue_name": target_queue_name,
            }

        return _start_thread_fallback(
            job_id,
            target_queue_name,
            reason=queue_unavailable.reason,
            detail=str(queue_unavailable),
        )


def _run_job_thread(job_id):
    from PushShoppingList.workers.job_worker import run_job

    try:
        run_job(job_id)
    finally:
        with _ACTIVE_THREAD_JOBS_LOCK:
            _ACTIVE_THREAD_JOB_IDS.discard(str(job_id or "").strip())


def cancel_queued_rq_job(rq_job_id):
    rq_job_id = str(rq_job_id or "").strip()
    if not rq_job_id:
        return False

    stopped = False
    try:
        connection, _Queue = redis_queue_connection()
        from rq.command import send_stop_job_command
        from rq.job import Job

        try:
            send_stop_job_command(connection, rq_job_id)
            stopped = True
        except Exception:
            stopped = False

        job = Job.fetch(rq_job_id, connection=connection)
        job.cancel()
        return True
    except JobQueueUnavailable as exc:
        _log_queue_unavailable("cancel_rq_unavailable", exc)
        return stopped
    except Exception:
        return stopped
