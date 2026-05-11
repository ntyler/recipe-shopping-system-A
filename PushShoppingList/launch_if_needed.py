import socket
import subprocess
import time
import webbrowser
from pathlib import Path

APP_FOLDER = Path(__file__).resolve().parent
APP_FILE = APP_FOLDER / "app.py"

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


def is_running():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) == 0


if is_running():
    print("Flask already running — reusing existing app")
else:
    print("Starting Flask app...")
    subprocess.Popen(
        ["python", str(APP_FILE)],
        cwd=str(APP_FOLDER)
    )

    # Give Flask time to start
    time.sleep(2)


# 🚀 Open local browser (Windows)
print("Opening browser...")
webbrowser.open(URL)
