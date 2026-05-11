import argparse
import subprocess
import sys
import webbrowser


CONTAINER_NAME = "webtop"
WEBTOP_URL = "http://127.0.0.1:3000"

DOCKER_USER = "abc"
DISPLAY = ":1"
HOME = "/config"

BROWSER_CMD = (
    f'DISPLAY={DISPLAY} '
    f'HOME={HOME} '
    f'google-chrome '
    f'--no-sandbox '
    f'--disable-sync '
    f'--disable-signin-promo '
    f'--no-first-run '
    f'--no-default-browser-check '
    f'--disable-background-networking '
    f'--disable-component-update '
    f'--disable-default-apps '
    f'--disable-extensions '
    f'--disable-session-crashed-bubble '
    f'--disable-features=Translate,AutofillServerCommunication,OptimizationHints '
    f'--password-store=basic '
    f'--use-mock-keychain '
    f'--user-data-dir=/config/google-chrome-profile'
)

STORE_URLS = {
    "aldi": "https://www.aldi.us/store/aldi/storefront",
    "meijer": "https://www.meijer.com/shopping/search.html",
    "walmart": "https://www.walmart.com",
    "kroger": "https://www.kroger.com",
    "target": "https://www.target.com",
}


def run(cmd, detached=False):
    docker_cmd = [
        "docker",
        "exec",
        "-u",
        DOCKER_USER,
    ]

    if detached:
        docker_cmd.append("-d")

    docker_cmd += [
        CONTAINER_NAME,
        "bash",
        "-lc",
        cmd,
    ]

    return subprocess.run(
        docker_cmd,
        capture_output=True,
        text=True,
    )


def docker_container_exists():
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )

    return CONTAINER_NAME in result.stdout.strip().splitlines()


def docker_container_running():
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name=^{CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )

    return CONTAINER_NAME in result.stdout.strip().splitlines()


def start_container():
    if docker_container_running():
        print("Webtop container is already running.")
        return

    if docker_container_exists():
        print("Starting existing Webtop container...")
        subprocess.run(["docker", "start", CONTAINER_NAME])
        return

    print("Creating new Webtop container...")

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            "3000:3000",
            "--shm-size=2g",
            "lscr.io/linuxserver/webtop:ubuntu-kde",
        ]
    )


def stop_container():
    subprocess.run(["docker", "stop", CONTAINER_NAME])


def restart_container():
    subprocess.run(["docker", "restart", CONTAINER_NAME])


def remove_container():
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME])


def open_webtop():
    webbrowser.open(WEBTOP_URL)
    print(f"Opened {WEBTOP_URL}")


def open_url(url):
    command = f'{BROWSER_CMD} "{url}"'

    result = run(command, detached=True)

    if result.returncode == 0:
        print(f"Sent URL to Webtop Chrome: {url}")
    else:
        print("Failed to open URL.")
        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")
        print(result.stderr)


def open_store(store):
    store = store.lower().strip()

    if store not in STORE_URLS:
        print(f"Unknown store: {store}")
        print("Available stores:", ", ".join(STORE_URLS.keys()))
        sys.exit(1)

    open_url(STORE_URLS[store])


def debug_browser(url):
    command = f'{BROWSER_CMD} "{url}"'

    result = run(command, detached=False)

    print("STDOUT:")
    print(result.stdout)

    print("STDERR:")
    print(result.stderr)

    print("Return code:")
    print(result.returncode)


def install_chrome():
    print("Installing Google Chrome inside Webtop...")

    commands = [
        "apt-get update && apt-get install -y wget ca-certificates",
        "wget -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
        "apt-get install -y /tmp/google-chrome.deb",
    ]

    for command in commands:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "root",
                CONTAINER_NAME,
                "bash",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
        )

        print(result.stdout)
        print(result.stderr)

        if result.returncode != 0:
            print("Chrome install failed.")
            sys.exit(1)

    verify = run("which google-chrome && google-chrome --version")

    print(verify.stdout)
    print(verify.stderr)


def install_tools():
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-u",
            "root",
            CONTAINER_NAME,
            "bash",
            "-lc",
            "apt-get update && apt-get install -y xdotool",
        ],
        capture_output=True,
        text=True,
    )

    print(result.stdout)
    print(result.stderr)


def type_url(url):
    install_tools()

    command = (
        f'DISPLAY={DISPLAY} '
        f'HOME={HOME} '
        f'xdotool key ctrl+l '
        f'&& xdotool type "{url}" '
        f'&& xdotool key Return'
    )

    result = run(command, detached=True)

    if result.returncode == 0:
        print(f"Typed URL into active Webtop browser: {url}")
    else:
        print("Failed to type URL.")
        print(result.stderr or result.stdout)


def main():
    parser = argparse.ArgumentParser(
        description="Control LinuxServer Webtop Docker container from Windows."
    )

    parser.add_argument(
        "action",
        choices=[
            "start",
            "stop",
            "restart",
            "remove",
            "open-webtop",
            "open-url",
            "open-store",
            "debug-browser",
            "install-chrome",
            "type-url",
        ],
    )

    parser.add_argument(
        "value",
        nargs="?",
        help="URL or store name depending on action.",
    )

    args = parser.parse_args()

    if args.action == "start":
        start_container()

    elif args.action == "stop":
        stop_container()

    elif args.action == "restart":
        restart_container()

    elif args.action == "remove":
        remove_container()

    elif args.action == "open-webtop":
        open_webtop()

    elif args.action == "install-chrome":
        install_chrome()

    elif args.action == "open-url":
        if not args.value:
            print("Missing URL.")
            sys.exit(1)

        open_url(args.value)

    elif args.action == "open-store":
        if not args.value:
            print("Missing store name.")
            sys.exit(1)

        open_store(args.value)

    elif args.action == "debug-browser":
        debug_browser(args.value or "https://www.aldi.us/")

    elif args.action == "type-url":
        if not args.value:
            print("Missing URL.")
            sys.exit(1)

        type_url(args.value)


if __name__ == "__main__":
    main()
