import socket
import subprocess
import time
import webbrowser
from pathlib import Path

APP_FOLDER = Path(__file__).resolve().parent
APP_FILE = APP_FOLDER / "proxy_test.py"

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}"


def is_running():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((HOST, PORT)) == 0


if is_running():
    print("Flask already running.")
else:
    print("Starting proxy_test.py...")

    subprocess.Popen(
        [
            "py",
            "-3.11",
            str(APP_FILE)
        ],
        cwd=str(APP_FOLDER),
    )

    time.sleep(2)

print("Opening Flask UI...")
webbrowser.open(URL)
