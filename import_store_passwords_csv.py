# import_store_passwords_csv.py
from pathlib import Path
import csv
import json

SCRIPT_DIR = Path(__file__).resolve().parent
stores_path = SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json"
csv_path = SCRIPT_DIR / "chrome_password_import_NEW.csv"

stores = json.loads(stores_path.read_text(encoding="utf-8"))

rows = []

for store_id, store in stores.items():
    username = str(store.get("username") or "").strip()
    password = str(store.get("password") or "").strip()

    site = (
        store.get("urlStoreSelector")
        or store.get("url")
        or ""
    ).strip()

    if not username or not password or not site:
        continue

    rows.append({
        "url": site,
        "username": username,
        "password": password,
    })

with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["url", "username", "password"])
    writer.writeheader()
    writer.writerows(rows)

print(f"✅ Created: {csv_path}")
