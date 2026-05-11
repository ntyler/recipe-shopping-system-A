"""
find_nearest_stores.py

Finds nearest pickup stores for each store in shopping_stores.json
using undetected Chrome, then updates shopping_stores.json.

Example:

    py -3.11 find_nearest_stores.py --zip 60504 --headed

    py -3.11 find_nearest_stores.py --zip 60504 --stores meijer aldi --headed
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

address_street      = "5905 Arlo Drive"
address_appartment  = "Apt 2213"
address_county      = "Indianapolis"
address_state       = "In"
address_zip         = "46237"

full_address        = f"{address_street}, {address_appartment}, {address_county}, {address_state} {address_zip}"

print(full_address)

CHROME_VERSION_MAIN = 147

SCRIPT_DIR = Path(__file__).resolve().parent
SHOPPING_STORES_FILE = SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json"

DEFAULT_LOCATORS = {
    "meijer": "https://www.meijer.com/shopping/store-finder.html",
    "aldi": "https://info.aldi.us/stores",
    "kroger": "https://www.kroger.com/stores/search",
    "walmart": "https://www.walmart.com/store-finder",
    "target": "https://www.target.com/store-locator/find-stores",
    "costco": "https://www.costco.com/warehouse-locations",
}


def get_chrome_major_version() -> int:
    try:
        result = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True,
        ).decode(errors="ignore")

        version = re.search(r"\d+\.\d+\.\d+\.\d+", result).group(0)
        return int(version.split(".")[0])

    except Exception:
        return CHROME_VERSION_MAIN


def get_screen_size() -> tuple[int, int]:
    try:
        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return width, height
    except Exception:
        return 1600, 900


def build_driver(headless: bool = True):
    options = uc.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = uc.Chrome(
        options=options,
        headless=headless,
        use_subprocess=True,
        version_main=get_chrome_major_version(),
    )

    driver.set_page_load_timeout(45)

    if not headless:
        width, height = get_screen_size()
        driver.set_window_rect(
            x=0,
            y=0,
            width=max(900, math.floor(width * 0.7)),
            height=max(700, math.floor(height * 0.85)),
        )

    return driver


def load_stores() -> dict[str, Any]:
    if not SHOPPING_STORES_FILE.exists():
        raise FileNotFoundError(f"Could not find {SHOPPING_STORES_FILE}")

    data = json.loads(SHOPPING_STORES_FILE.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("shopping_stores.json must contain a JSON object.")

    return data


def save_stores(stores: dict[str, Any]) -> None:
    SHOPPING_STORES_FILE.write_text(
        json.dumps(stores, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def page_text(driver) -> str:
    soup = BeautifulSoup(driver.page_source, "html.parser")
    return clean_text(soup.get_text(" ", strip=True))


def click_first_matching_text(driver, text_options: list[str], wait: float = 1.5) -> bool:
    for text in text_options:
        xpath = (
            "//*[contains(translate(normalize-space(text()), "
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{text.lower()}')]"
        )

        try:
            elements = driver.find_elements("xpath", xpath)
        except Exception:
            continue

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    element.click()
                    time.sleep(wait)
                    return True
            except Exception:
                continue

    return False


def type_into_first_visible_input(driver, value: str, wait: float = 1.5) -> bool:
    try:
        inputs = driver.find_elements("xpath", "//input")
    except Exception:
        return False

    for input_box in inputs:
        try:
            if input_box.is_displayed() and input_box.is_enabled():
                input_box.clear()
                input_box.send_keys(value)
                time.sleep(wait)
                return True
        except Exception:
            continue

    return False


def press_enter_on_first_visible_input(driver, wait: float = 2.5) -> bool:
    from selenium.webdriver.common.keys import Keys

    try:
        inputs = driver.find_elements("xpath", "//input")
    except Exception:
        return False

    for input_box in inputs:
        try:
            if input_box.is_displayed() and input_box.is_enabled():
                input_box.send_keys(Keys.ENTER)
                time.sleep(wait)
                return True
        except Exception:
            continue

    return False


def extract_distance(text: str) -> str | None:
    match = re.search(r"\b\d+(?:\.\d+)?\s*(?:mi|miles)\b", text, flags=re.I)
    return match.group(0) if match else None


def extract_phone(text: str) -> str | None:
    match = re.search(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text)
    return match.group(0) if match else None


def extract_address(text: str, zip_code: str) -> str | None:
    patterns = [
        rf"\d{{1,6}}\s+[A-Za-z0-9 .#'-]+,\s*[A-Za-z .'-]+,\s*[A-Z]{{2}}\s*{zip_code}",
        r"\d{1,6}\s+[A-Za-z0-9 .#'-]+,\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}",
        r"\d{1,6}\s+[A-Za-z0-9 .#'-]+\s+[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_text(match.group(0))

    return None


def guess_store_name(store_key: str, text: str) -> str:
    store_labels = {
        "meijer": "Meijer",
        "aldi": "ALDI",
        "kroger": "Kroger",
        "walmart": "Walmart",
        "target": "Target",
        "costco": "Costco",
    }

    label = store_labels.get(store_key, store_key.title())

    if store_key == "walmart":
        match = re.search(r"(Walmart\s+(?:Supercenter|Neighborhood Market).*?)(?:\d{1,6}\s+)", text, flags=re.I)
        if match:
            return clean_text(match.group(1))

    if store_key == "costco":
        return "Costco Wholesale"

    return label


def extract_nearest_from_page(store_key: str, driver, zip_code: str) -> dict[str, Any]:
    text = page_text(driver)

    address = extract_address(text, zip_code)
    distance = extract_distance(text)
    phone = extract_phone(text)
    name = guess_store_name(store_key, text)

    return {
        "pickup_store_name": name,
        "pickup_address": address,
        "pickup_distance": distance,
        "pickup_phone": phone,
        "locator_url": driver.current_url,
    }


def search_locator(driver, store_key: str, zip_code: str, stores: dict[str, Any]) -> dict[str, Any]:
    locator_url = (
        stores.get(store_key, {}).get("locator_url")
        or DEFAULT_LOCATORS.get(store_key)
    )

    locator_search_by = (
        stores.get(store_key, {}).get("locator_search_by")
    )
    
    if not locator_url or not locator_search_by:
        return {
            "ok": False,
            "error": f"No locator URL configured for {store_key}",
        }

    if locator_search_by == "Full Address":
        locator_url_updated = f"{locator_url}{full_address}"

    else if locator_search_by == "Zip Code":
        locator_url_updated = f"{locator_url}{address_zip}"
    
    
    print(f"\n[{store_key}] Opening locator: {locator_url_updated}")
    driver.get(locator_url_updated)
    time.sleep(5)

    if store_key == "meijer":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        time.sleep(5)

    elif store_key == "aldi":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        time.sleep(5)

    elif store_key == "kroger":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        click_first_matching_text(driver, ["search", "find stores"])
        time.sleep(5)

    elif store_key == "walmart":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        click_first_matching_text(driver, ["search", "find stores"])
        time.sleep(5)

    elif store_key == "target":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        click_first_matching_text(driver, ["search", "find stores"])
        time.sleep(5)

    elif store_key == "costco":
        type_into_first_visible_input(driver, zip_code)
        press_enter_on_first_visible_input(driver)
        click_first_matching_text(driver, ["search", "find a warehouse"])
        time.sleep(5)

    nearest = extract_nearest_from_page(store_key, driver, zip_code)

    ok = bool(nearest.get("pickup_address") or nearest.get("pickup_distance"))

    return {
        "ok": ok,
        **nearest,
    }


def update_store_record(
    stores: dict[str, Any],
    store_key: str,
    nearest: dict[str, Any],
    zip_code: str,
) -> None:
    store = stores.setdefault(store_key, {})

    store["pickup_zip"] = zip_code

    if nearest.get("pickup_store_name"):
        store["pickup_store_name"] = nearest["pickup_store_name"]

    if nearest.get("pickup_address"):
        store["pickup_address"] = nearest["pickup_address"]

    if nearest.get("pickup_distance"):
        store["pickup_distance"] = nearest["pickup_distance"]

    if nearest.get("pickup_phone"):
        store["pickup_phone"] = nearest["pickup_phone"]

    if nearest.get("locator_url"):
        store["locator_url"] = nearest["locator_url"]

    store["nearest_lookup_ok"] = bool(nearest.get("ok"))
    store["nearest_lookup_error"] = nearest.get("error")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find nearest pickup stores and update shopping_stores.json."
    )

    parser.add_argument(
        "--zip",
        default="60504",
        help="ZIP code to search near.",
    )

    parser.add_argument(
        "--stores",
        nargs="*",
        help="Optional store keys to update, like meijer aldi walmart.",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chrome window.",
    )

    parser.add_argument(
        "--output",
        default=str(SHOPPING_STORES_FILE),
        help="Output JSON file. Defaults to shopping_stores.json.",
    )

    args = parser.parse_args()

    stores = load_stores()

    selected_store_keys = args.stores or list(stores.keys())
    selected_store_keys = [
        str(store).strip().lower()
        for store in selected_store_keys
        if str(store).strip().lower() in stores
    ]

    if not selected_store_keys:
        print("No matching stores found in shopping_stores.json.")
        return 1

    driver = build_driver(headless=not args.headed)

    try:
        for store_key in selected_store_keys:
            try:
                nearest = search_locator(
                    driver=driver,
                    store_key=store_key,
                    zip_code=args.zip,
                    stores=stores,
                )

                update_store_record(
                    stores=stores,
                    store_key=store_key,
                    nearest=nearest,
                    zip_code=args.zip,
                )

                status = "✅" if nearest.get("ok") else "⚠️"
                print(f"{status} {store_key}: {nearest}")

            except Exception as exc:
                print(f"❌ {store_key}: {exc}")

                update_store_record(
                    stores=stores,
                    store_key=store_key,
                    nearest={
                        "ok": False,
                        "error": str(exc),
                    },
                    zip_code=args.zip,
                )

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(stores, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nUpdated: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
