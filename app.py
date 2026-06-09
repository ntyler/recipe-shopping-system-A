import os
import sys
from pathlib import Path


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

    print(f"[startup] Re-executing Flask with required Python: {required_python}")
    os.execv(str(required_python), [str(required_python), str(Path(__file__).resolve())])


if __name__ == "__main__":
    enforce_required_python_runtime()

from PushShoppingList.app import create_app

app = create_app()


def ssl_context_from_env():
    cert_file = os.getenv("SHOPPING_APP_SSL_CERT", "").strip()
    key_file = os.getenv("SHOPPING_APP_SSL_KEY", "").strip()

    if cert_file and key_file:
        return cert_file, key_file

    if os.getenv("SHOPPING_APP_SSL_ADHOC") == "1":
        return "adhoc"

    return None

if __name__ == "__main__":
    app.run(
        host=os.getenv("SHOPPING_APP_HOST", "0.0.0.0"),
        port=int(os.getenv("SHOPPING_APP_PORT", "5000")),
        debug=False,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context_from_env(),
    )
