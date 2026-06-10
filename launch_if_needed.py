import os
import socket
import subprocess
import sys
from pathlib import Path


REQUIRED_PYTHON = Path(os.environ.get("SHOPPING_APP_PYTHON_EXE", r"C:\Python39\python.exe"))
REPO_DIR = Path(__file__).resolve().parent
HOST = os.environ.get("SHOPPING_APP_HOST_CHECK", "127.0.0.1")
PORT = int(os.environ.get("SHOPPING_APP_PORT", "5083"))


def app_is_listening(host, port):
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def running_required_python():
    try:
        return Path(sys.executable).resolve() == REQUIRED_PYTHON.resolve()
    except OSError:
        return False


def main():
    if not REQUIRED_PYTHON.is_file():
        raise SystemExit(f"Required Python executable not found: {REQUIRED_PYTHON}")

    if not running_required_python():
        os.execv(str(REQUIRED_PYTHON), [str(REQUIRED_PYTHON), str(Path(__file__).resolve())])

    if app_is_listening(HOST, PORT):
        print(f"Shopping app already listening on {HOST}:{PORT}")
        return 0

    env = os.environ.copy()
    env.setdefault("SHOPPING_APP_PORT", str(PORT))
    env.setdefault("SHOPPING_APP_PYTHON_EXE", str(REQUIRED_PYTHON))
    env.setdefault("OPENAI_RECIPE_MODEL", "gpt-4o-mini")
    env.setdefault("OPENAI_MENU_MODEL", "gpt-5.5")
    env.setdefault("OPENAI_VISION_MODEL", "gpt-5.5")
    subprocess.Popen(
        [str(REQUIRED_PYTHON), "app.py"],
        cwd=str(REPO_DIR),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    print(f"Started shopping app with {REQUIRED_PYTHON} on port {PORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
