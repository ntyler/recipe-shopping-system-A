import contextlib
import contextvars


_JOB_CONTEXT = contextvars.ContextVar("shopping_app_job_context", default={})


def current_job_context():
    context = _JOB_CONTEXT.get({})
    return context if isinstance(context, dict) else {}


def set_job_context(**values):
    clean_values = {
        key: value
        for key, value in values.items()
        if value not in (None, "")
    }
    return _JOB_CONTEXT.set(clean_values)


def reset_job_context(token):
    if token is not None:
        _JOB_CONTEXT.reset(token)


@contextlib.contextmanager
def job_context(**values):
    token = set_job_context(**values)
    try:
        yield current_job_context()
    finally:
        reset_job_context(token)


def current_job_id():
    return str(current_job_context().get("job_id") or "").strip()


def current_job_queue_name():
    return str(current_job_context().get("queue_name") or "").strip()


def model_snapshot_for_env(env_var):
    env_var = str(env_var or "").strip()
    context = current_job_context()
    if not env_var or str(context.get("model_env_var_used") or "").strip() != env_var:
        return None

    model = str(context.get("model_used") or "").strip()
    if not model:
        return None

    return {
        "model": model,
        "source": str(context.get("model_source") or f"job-snapshot:{env_var}").strip(),
        "env_var": env_var,
    }


def model_value_for_env(env_var, default_model="", default_source=""):
    snapshot = model_snapshot_for_env(env_var)
    if snapshot:
        return snapshot["model"], snapshot["source"]
    return str(default_model or "").strip(), str(default_source or "").strip()
