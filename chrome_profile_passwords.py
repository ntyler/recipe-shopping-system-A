from __future__ import annotations

"""
chrome_profile_passwords.py

Best-effort Windows helper that injects saved logins from
PushShoppingList/shopping_stores.json into a temporary Chrome profile BEFORE
Chrome is opened by Selenium.

IMPORTANT:
- This is intended for Windows.
- Requires: pip install pywin32
- Chrome must NOT already be using this profile directory.
- This writes plaintext-origin metadata and DPAPI-encrypted password blobs into
  the Chrome Login Data SQLite DB for the temp profile.
"""

import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import win32crypt
except Exception as exc:  # pragma: no cover
    win32crypt = None
    WIN32CRYPT_IMPORT_ERROR = exc
else:
    WIN32CRYPT_IMPORT_ERROR = None


def chrome_time_now() -> int:
    """Chrome timestamp: microseconds since 1601-01-01 UTC."""
    return int((time.time() + 11644473600) * 1_000_000)


def site_origin(url: str) -> str:
    parsed = urlparse(str(url or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f"{parsed.scheme}://{parsed.netloc}"


def encrypt_password(password: str) -> bytes:
    if win32crypt is None:
        raise RuntimeError(
            "pywin32/win32crypt is required on Windows. Run: pip install pywin32"
        ) from WIN32CRYPT_IMPORT_ERROR

    encrypted = win32crypt.CryptProtectData(
        str(password).encode('utf-8'),
        None,
        None,
        None,
        None,
        0,
    )
    return encrypted


def ensure_login_data_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Chrome schema changes over time. This table includes the core columns
    # Chrome needs plus common modern columns. Unknown/new columns are not needed
    # for a new temp profile.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logins (
        origin_url VARCHAR NOT NULL,
        action_url VARCHAR,
        username_element VARCHAR,
        username_value VARCHAR,
        password_element VARCHAR,
        password_value BLOB,
        submit_element VARCHAR,
        signon_realm VARCHAR NOT NULL,
        date_created INTEGER NOT NULL,
        blacklisted_by_user INTEGER NOT NULL,
        scheme INTEGER NOT NULL,
        password_type INTEGER DEFAULT 0,
        times_used INTEGER DEFAULT 0,
        form_data BLOB,
        display_name VARCHAR,
        icon_url VARCHAR,
        federation_url VARCHAR,
        skip_zero_click INTEGER DEFAULT 0,
        generation_upload_status INTEGER DEFAULT 0,
        possible_username_pairs BLOB,
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date_last_used INTEGER DEFAULT 0,
        moving_blocked_for BLOB,
        date_password_modified INTEGER DEFAULT 0,
        sender_email VARCHAR,
        sender_name VARCHAR,
        date_received INTEGER DEFAULT 0,
        sharing_notification_displayed INTEGER DEFAULT 0,
        keychain_identifier BLOB,
        sender_profile_image_url VARCHAR
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS meta (
        key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY,
        value LONGVARCHAR
    )
    """)
    cur.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('version', '39')")
    cur.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('last_compatible_version', '39')")
    conn.commit()


def load_password_rows(stores_json: str | Path) -> list[dict[str, str]]:
    stores_json = Path(stores_json)
    stores = json.loads(stores_json.read_text(encoding='utf-8'))

    rows: list[dict[str, str]] = []

    if not isinstance(stores, dict):
        return rows

    for store_id, store in stores.items():
        if not isinstance(store, dict):
            continue

        username = str(store.get('username') or '').strip()
        password = str(store.get('password') or '').strip()

        if not username or not password:
            continue

        urls = []
        for key in ['urlStoreSelector', 'url', 'website']:
            value = str(store.get(key) or '').strip()
            origin = site_origin(value)
            if origin and origin not in urls:
                urls.append(origin)

        # Meijer auth can be on id.meijer.com after clicking Sign in.
        if str(store_id).lower() == 'meijer':
            for origin in ['https://www.meijer.com', 'https://id.meijer.com']:
                if origin not in urls:
                    urls.append(origin)

        for origin in urls:
            rows.append({
                'store_id': str(store_id),
                'origin_url': origin,
                'action_url': origin,
                'signon_realm': origin,
                'username': username,
                'password': password,
            })

    return rows


def inject_passwords_into_chrome_profile(profile_dir: str | Path, stores_json: str | Path) -> int:
    profile_dir = Path(profile_dir)
    default_dir = profile_dir / 'Default'
    default_dir.mkdir(parents=True, exist_ok=True)

    login_db = default_dir / 'Login Data'
    rows = load_password_rows(stores_json)

    if not rows:
        print('🔐 No store credentials found to inject.')
        return 0

    conn = sqlite3.connect(str(login_db))
    try:
        ensure_login_data_schema(conn)
        cur = conn.cursor()
        now = chrome_time_now()
        count = 0

        for row in rows:
            encrypted = encrypt_password(row['password'])

            cur.execute(
                "DELETE FROM logins WHERE origin_url=? AND username_value=?",
                (row['origin_url'], row['username']),
            )

            cur.execute("""
            INSERT INTO logins (
                origin_url,
                action_url,
                username_element,
                username_value,
                password_element,
                password_value,
                submit_element,
                signon_realm,
                date_created,
                blacklisted_by_user,
                scheme,
                password_type,
                times_used,
                form_data,
                display_name,
                icon_url,
                federation_url,
                skip_zero_click,
                generation_upload_status,
                possible_username_pairs,
                date_last_used,
                moving_blocked_for,
                date_password_modified
            )
            VALUES (?, ?, '', ?, '', ?, '', ?, ?, 0, 0, 0, 0, NULL, '', '', '', 0, 0, NULL, ?, NULL, ?)
            """, (
                row['origin_url'],
                row['action_url'],
                row['username'],
                encrypted,
                row['signon_realm'],
                now,
                now,
                now,
            ))
            count += 1
            print(f"🔐 Injected password for {row['store_id']}: {row['origin_url']}")

        conn.commit()
        return count
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inject shopping store passwords into a Chrome profile.')
    parser.add_argument('--profile-dir', required=True)
    parser.add_argument('--stores-json', default='PushShoppingList/shopping_stores.json')
    args = parser.parse_args()
    total = inject_passwords_into_chrome_profile(args.profile_dir, args.stores_json)
    print(f'✅ Injected {total} password entries.')
