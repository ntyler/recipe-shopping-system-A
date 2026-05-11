from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import win32crypt
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STORES_JSON = SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json"
DEFAULT_PROFILE_ROOT = SCRIPT_DIR / "chrome_worker_profiles"


CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome_exe() -> str:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return "chrome"


def chrome_time_now() -> int:
    # Chrome/WebKit timestamp: microseconds since 1601-01-01 UTC.
    return int((time.time() + 11644473600) * 1_000_000)


def clean_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def site_origins_for_store(store_id: str, store: dict) -> list[str]:
    origins: list[str] = []

    for key in ["loginUrl", "login_url", "urlStoreSelector", "website", "url"]:
        origin = origin_from_url(clean_text(store.get(key)))
        if origin and origin not in origins:
            origins.append(origin)

    # Meijer login redirects through id.meijer.com, so save both.
    if store_id.lower() == "meijer":
        for origin in ["https://id.meijer.com", "https://www.meijer.com"]:
            if origin not in origins:
                origins.append(origin)

    return origins


def initialize_chrome_profile(profile_dir: Path, chrome_path: str) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    local_state = profile_dir / "Local State"
    login_data = default_dir / "Login Data"

    if local_state.exists() and login_data.exists():
        return

    print(f"🧱 Initializing Chrome profile: {profile_dir}")

    proc = subprocess.Popen([
        chrome_path,
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "about:blank",
    ])

    time.sleep(6)

    try:
        proc.terminate()
    except Exception:
        pass

    time.sleep(3)

    if not local_state.exists():
        raise FileNotFoundError(f"Chrome did not create Local State: {local_state}")

    if not login_data.exists():
        # Chrome usually creates this automatically. If it did not, open password manager once.
        proc = subprocess.Popen([
            chrome_path,
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "chrome://password-manager/passwords",
        ])
        time.sleep(6)
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(3)

    if not login_data.exists():
        raise FileNotFoundError(f"Chrome did not create Login Data DB: {login_data}")


def get_chrome_encryption_key(profile_dir: Path) -> bytes:
    local_state = profile_dir / "Local State"
    data = json.loads(local_state.read_text(encoding="utf-8"))

    encrypted_key_b64 = data.get("os_crypt", {}).get("encrypted_key")
    if not encrypted_key_b64:
        raise RuntimeError("Could not find os_crypt.encrypted_key in Local State")

    encrypted_key = base64.b64decode(encrypted_key_b64)

    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]

    return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]


def encrypt_password_for_chrome(password: str, key: bytes) -> bytes:
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(password.encode("utf-8"))
    return b"v10" + nonce + ciphertext + tag


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def insert_login_row(
    conn: sqlite3.Connection,
    origin_url: str,
    username: str,
    password: str,
    key: bytes,
) -> None:
    columns = table_columns(conn, "logins")
    now = chrome_time_now()
    encrypted_password = encrypt_password_for_chrome(password, key)

    conn.execute(
        "DELETE FROM logins WHERE origin_url=? AND username_value=?",
        (origin_url, username),
    )

    values = {
        "origin_url": origin_url,
        "action_url": origin_url,
        "username_element": "username",
        "username_value": username,
        "password_element": "password",
        "password_value": encrypted_password,
        "submit_element": "",
        "signon_realm": origin_url,
        "date_created": now,
        "blacklisted_by_user": 0,
        "scheme": 0,
        "password_type": 0,
        "times_used": 0,
        "form_data": b"",
        "display_name": "",
        "icon_url": "",
        "federation_url": "",
        "skip_zero_click": 0,
        "generation_upload_status": 0,
        "possible_username_pairs": b"",
        "date_last_used": now,
        "moving_blocked_for": b"",
        "date_password_modified": now,
        "sender_email": "",
        "sender_name": "",
        "date_received": 0,
        "sharing_notification_displayed": 0,
    }

    insert_columns = [col for col in values if col in columns]
    placeholders = ",".join("?" for _ in insert_columns)
    sql = f"INSERT INTO logins ({','.join(insert_columns)}) VALUES ({placeholders})"
    conn.execute(sql, [values[col] for col in insert_columns])


def inject_passwords_into_profile(profile_dir: Path, stores_json: Path, chrome_path: str) -> int:
    initialize_chrome_profile(profile_dir, chrome_path)

    login_data = profile_dir / "Default" / "Login Data"
    if not login_data.exists():
        raise FileNotFoundError(f"Login Data DB not found: {login_data}")

    key = get_chrome_encryption_key(profile_dir)
    stores = json.loads(stores_json.read_text(encoding="utf-8"))

    backup_path = login_data.with_name(f"Login Data.backup.{int(time.time())}")
    shutil.copy2(login_data, backup_path)

    count = 0
    conn = sqlite3.connect(login_data)
    try:
        for store_id, store in stores.items():
            if not isinstance(store, dict):
                continue

            username = clean_text(store.get("username"))
            password = str(store.get("password") or "").strip()

            if not username or not password:
                continue

            origins = site_origins_for_store(store_id, store)
            for origin_url in origins:
                insert_login_row(
                    conn=conn,
                    origin_url=origin_url,
                    username=username,
                    password=password,
                    key=key,
                )
                print(f"✅ Injected {store_id}: {origin_url} / {username}")
                count += 1

        conn.commit()
    finally:
        conn.close()

    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject shopping store credentials into Chrome worker profiles.")
    parser.add_argument("--stores-json", default=str(DEFAULT_STORES_JSON), help="Path to PushShoppingList/shopping_stores.json")
    parser.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT), help="Folder containing worker profiles")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker_N profiles to seed")
    parser.add_argument("--chrome", default=find_chrome_exe(), help="Path to chrome.exe")
    args = parser.parse_args()

    stores_json = Path(args.stores_json).resolve()
    profile_root = Path(args.profile_root).resolve()
    chrome_path = args.chrome

    if not stores_json.exists():
        raise FileNotFoundError(f"stores JSON not found: {stores_json}")

    print(f"Stores JSON: {stores_json}")
    print(f"Profile root: {profile_root}")
    print(f"Chrome: {chrome_path}")

    total = 0
    for worker_id in range(max(1, int(args.workers))):
        profile_dir = profile_root / f"worker_{worker_id}"
        print(f"\n=== Worker profile {worker_id}: {profile_dir} ===")
        total += inject_passwords_into_profile(profile_dir, stores_json, chrome_path)

    print(f"\n✅ Done. Injected {total} saved-login rows.")
    print("Open Chrome with the same --user-data-dir profile to verify in chrome://password-manager/passwords.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
