import os
import sys
from pathlib import Path

from redis import Redis
from rq import Queue
from rq import Worker

from PushShoppingList.services.job_queue_service import redis_url
from PushShoppingList.services.job_queue_service import worker_queue_names
from PushShoppingList.services.openai_model_service import apply_openai_model_overrides


def enforce_required_python_runtime():
    required_python = Path(os.getenv("SHOPPING_APP_PYTHON_EXE", r"C:\Python39\python.exe"))
    allow_any_python = os.getenv("SHOPPING_APP_ALLOW_ANY_PYTHON", "").strip().lower() in {"1", "true", "yes"}

    if allow_any_python:
        return

    try:
        current_python = Path(sys.executable).resolve()
        required_python = required_python.resolve()
    except OSError:
        current_python = Path(sys.executable)

    if current_python == required_python:
        return

    if not required_python.is_file():
        raise SystemExit(f"Required Python executable not found: {required_python}")

    print(f"[worker] Re-executing worker with required Python: {required_python}")
    os.execv(str(required_python), [str(required_python), str(Path(__file__).resolve())])


def main():
    enforce_required_python_runtime()
    apply_openai_model_overrides()
    connection = Redis.from_url(redis_url())
    queue_names = worker_queue_names()
    print(f"[worker] Listening on queues: {', '.join(queue_names)}")
    worker = Worker([Queue(name, connection=connection) for name in queue_names], connection=connection)
    worker.work(with_scheduler=os.getenv("RQ_WITH_SCHEDULER", "0").strip() == "1")


if __name__ == "__main__":
    main()
