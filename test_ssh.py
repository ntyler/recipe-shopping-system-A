@ -1,84 +0,0 @@
import time
import paramiko
import requests

SSH_HOST = "desktop-in7s09s"  # Use direct Tailscale device hostname for SSH
USERNAME = "Tyler"
PASSWORD = "your_password_here"  # Replace with actual password

REPO_DIR = r"D:\GitHub\recipe-shopping-system-A"
BAT_FILE = rf"{REPO_DIR}\start_app.bat"

APP_URL = "https://desktop-in7s09s.tail906b20.ts.net/"
ENSURE_FUNNEL = True

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

def run_ssh_command(ssh, command):
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()

    if output:
        print(f"Output: {output}")

    if error:
        print(f"Error: {error}")

    return exit_code

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print("Connecting to Windows PC over Tailscale...")

    ssh.connect(
        SSH_HOST,
        username=USERNAME,
        password=PASSWORD,
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )

    print("SSH connected")
    print("Launching Flask app...")

    launch_command = f'cmd /c start "" /D "{REPO_DIR}" "{BAT_FILE}"'
    run_ssh_command(ssh, launch_command)

    if ENSURE_FUNNEL:
        print("Ensuring Tailscale Funnel is on...")
        run_ssh_command(
            ssh,
            "tailscale funnel --bg --yes http://127.0.0.1:5000",
        )

    if wait_for_app(APP_URL):
        print(f"App is ready at: {APP_URL}")

except Exception as exc:
    print(f"EXCEPTION: {exc}")

finally:
    ssh.close()</content>
<parameter name="filePath">d:\GitHub\recipe-shopping-system-A\test_ssh.py