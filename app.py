import os
import sys
from pathlib import Path

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

    print(f"[startup] Re-executing app with required Python: {required_python}")
    os.execv(str(required_python), [str(required_python), str(Path(__file__).resolve())])


enforce_required_python_runtime()
apply_openai_model_overrides()

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


def env_truthy(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def app_host():
    return os.getenv("SHOPPING_APP_HOST", "0.0.0.0")


def app_port():
    return int(os.getenv("SHOPPING_APP_PORT", "5000"))


def run_flask_dev_server():
    print("[startup] Serving with Flask development server.")
    app.run(
        host=app_host(),
        port=app_port(),
        debug=False,
        use_reloader=False,
        threaded=True,
        ssl_context=ssl_context_from_env(),
    )


def run_waitress_server():
    ssl_context = ssl_context_from_env()

    if ssl_context:
        raise SystemExit(
            "Waitress serves HTTP only. Remove SHOPPING_APP_SSL_ADHOC / "
            "SHOPPING_APP_SSL_CERT / SHOPPING_APP_SSL_KEY and use Tailscale Funnel, "
            "Cloudflare Tunnel, or another HTTPS proxy; or set SHOPPING_APP_SERVER=flask-dev "
            "for local self-signed SSL testing."
        )

    try:
        from waitress import serve
    except ImportError as exc:
        raise SystemExit(
            "Waitress is not installed. Run: "
            "C:\\Python39\\python.exe -m pip install -r requirements.txt"
        ) from exc

    threads = int(os.getenv("SHOPPING_APP_WAITRESS_THREADS", "8"))
    host = app_host()
    port = app_port()

    print(f"[startup] Serving with Waitress on http://{host}:{port}")
    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        ident="Recipe Shopping System",
    )


if __name__ == "__main__":
    server = os.getenv("SHOPPING_APP_SERVER", "waitress").strip().lower()

    if server in {"flask", "flask-dev", "development"} or env_truthy("SHOPPING_APP_USE_FLASK_DEV_SERVER"):
        run_flask_dev_server()
    else:
        run_waitress_server()
