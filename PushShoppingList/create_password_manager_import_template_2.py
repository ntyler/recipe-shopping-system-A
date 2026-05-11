from pathlib import Path
import csv

CSV_FILE = Path(
    r"D:\GitHub\recipe-shopping-system\PushShoppingList\password_manager_import_template.csv"
)

rows = [
    {
        "name": "Aldi",
        "url": "https://www.aldi.us/",
        "username": "YOUR_ALDI_EMAIL",
        "password": "YOUR_ALDI_PASSWORD",
    },
    {
        "name": "Kroger",
        "url": "https://www.kroger.com/",
        "username": "YOUR_KROGER_EMAIL",
        "password": "YOUR_KROGER_PASSWORD",
    },
    {
        "name": "Walmart",
        "url": "https://www.walmart.com/",
        "username": "YOUR_WALMART_EMAIL",
        "password": "YOUR_WALMART_PASSWORD",
    },
    {
        "name": "Meijer",
        "url": "https://www.meijer.com/",
        "username": "YOUR_MEIJER_EMAIL",
        "password": "YOUR_MEIJER_PASSWORD",
    },
]

with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["name", "url", "username", "password"],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Chrome password CSV written:\n{CSV_FILE}")
