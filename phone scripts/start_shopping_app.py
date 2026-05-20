import time
from urllib.parse import quote

import keychain
import paramiko
import requests

from objc_util import UIApplication, NSURL


SSH_HOSTS = [
    "100.112.145.109",
    "desktop-in7s09s.tail906b20.ts.net",
    "desktop-in7s09s",
]
SSH_PORT = 22
SSH_TIMEOUT = 8
USERNAME = "Tyler"
PASSWORD = keychain.get_password("windows_ssh", "Tyler")

REPO_DIR = r"D:\GitHub\recipe-shopping-system-A"
BAT_FILE = rf"{REPO_DIR}\start_app.bat"

APP_URL = "https://desktop-in7s09s.tail906b20.ts.net/"
LOCAL_APP_PORT = 5058
ENSURE_FUNNEL = True
OPEN_TAILSCALE_FIRST = True

# Create this iOS Shortcut with Tailscale's built-in "Connect" action.
# If you leave this blank, the script will just open the Tailscale app.
TAILSCALE_CONNECT_SHORTCUT = "Connect Tailscale"


if not PASSWORD:
    raise Exception("Password not found in keychain")


def open_in_safari(url):
    nsurl = NSURL.URLWithString_(url)
    UIApplication.sharedApplication().openURL_(nsurl)


def open_ios_url(url):
    nsurl = NSURL.URLWithString_(url)
    UIApplication.sharedApplication().openURL_(nsurl)


def open_tailscale_connect():
    if TAILSCALE_CONNECT_SHORTCUT:
        shortcut_url = (
            "shortcuts://run-shortcut?name="
            + quote(TAILSCALE_CONNECT_SHORTCUT)
        )
        print(f"Running Shortcut: {TAILSCALE_CONNECT_SHORTCUT}")
        open_ios_url(shortcut_url)
    else:
        print("Opening Tailscale app...")
        open_ios_url("tailscale://")

    print("Make sure Tailscale says Connected, then return to Pythonista.")
    input("Press Enter here after Tailscale is connected...")


def wait_for_app(url, seconds=30):
    print("Waiting for shopping app...")

    for _ in range(seconds):
        try:
            response = requests.get(url, timeout=3)

            if response.status_code < 500:
                print("Shopping app is online")
                return True

        except Exception as exc:
            print(f"Still waiting: {exc}")

        time.sleep(1)

    print("Shopping app did not respond in time")
    return False


def app_is_online(url):
    try:
        response = requests.get(url, timeout=3)
        return response.status_code < 500
    except Exception:
        return False


def run_ssh_command(ssh, command):
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()

    if output:
        print(output)

    if error:
        print(error)

    return exit_code


def connect_ssh():
    last_error = None

    for host in SSH_HOSTS:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            print(f"Trying SSH host: {host}")
            ssh_client.connect(
                host,
                port=SSH_PORT,
                username=USERNAME,
                password=PASSWORD,
                timeout=SSH_TIMEOUT,
                banner_timeout=SSH_TIMEOUT,
                auth_timeout=SSH_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
            )
            print(f"SSH connected: {host}")
            return ssh_client
        except Exception as exc:
            last_error = exc
            print(f"SSH failed for {host}: {exc}")
            try:
                ssh_client.close()
            except Exception:
                pass

    raise Exception(f"Could not connect to Windows SSH. Last error: {last_error}")


ssh = None

try:
    if app_is_online(APP_URL):
        print("Shopping app is already online")
        print(f"Opening Safari: {APP_URL}")
        open_in_safari(APP_URL)
        raise SystemExit

    if OPEN_TAILSCALE_FIRST:
        open_tailscale_connect()

    print("Connecting to Windows PC over Tailscale...")
    ssh = connect_ssh()
    print("Launching Flask app...")

    launch_command = f'cmd /c start "" /D "{REPO_DIR}" "{BAT_FILE}"'
    run_ssh_command(ssh, launch_command)

    if ENSURE_FUNNEL:
        print("Ensuring Tailscale Funnel is on...")
        run_ssh_command(
            ssh,
            f"tailscale funnel --bg --yes http://127.0.0.1:{LOCAL_APP_PORT}",
        )

    if wait_for_app(APP_URL):
        print(f"Opening Safari: {APP_URL}")
        open_in_safari(APP_URL)

except Exception as exc:
    print(f"EXCEPTION: {exc}")

finally:
    if ssh:
        try:
            ssh.close()
        except Exception:
            pass

    print("SSH closed")
