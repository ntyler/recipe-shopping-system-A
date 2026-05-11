"""
update_store_websites_from_results.py

Uses PushShoppingList/shopping_stores_Results.json as the source of truth.
Opens each selected store website and tries to set the store's home/pickup location
before product searches are run by store_product_scraper.py.

Examples:
    py -3.11 update_store_websites_from_results.py --headed
    py -3.11 update_store_websites_from_results.py --headed --stores meijer aldi walmart
    py -3.11 update_store_websites_from_results.py --headed --force
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_FILE_CANDIDATES = [
    SCRIPT_DIR / "PushShoppingList" / "shopping_stores_Results.json",
]

DEFAULT_WAIT = 3.0
CHROME_VERSION_MAIN = 147


def find_results_file() -> Path:
    for path in RESULTS_FILE_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Could not find shopping_stores_Results.json. Expected it in script folder or PushShoppingList/."
    )


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_zip(address: str | None) -> str | None:
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", address or "")
    return match.group(0) if match else None


def base_url_from_website_or_search(store: dict[str, Any]) -> str:
    for key in ["website", "search_url_template"]:
        url = clean_text(store.get(key))
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
    return ""


def store_number_from_url(url: str | None) -> str | None:
    url = url or ""
    patterns = [
        r"/store/(\d+)",
        r"/store-locator/(\d+)\.html",
        r"/sl/[^/]+/(\d+)",
        r"/(\d{3,5})[-_.]",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def build_store_context(store_key: str, store: dict[str, Any], home: dict[str, Any]) -> dict[str, Any]:
    exact_address = clean_text(store.get("exact_address"))
    selected_name = clean_text(store.get("selected_name") or store.get("store_name") or store_key)
    pickup_zip = extract_zip(exact_address) or clean_text(home.get("zip"))
    website = clean_text(store.get("website"))
    base_url = base_url_from_website_or_search(store)

    return {
        "store_key": store_key,
        "store_name": clean_text(store.get("store_name") or store_key.title()),
        "selected_name": selected_name,
        "exact_address": exact_address,
        "pickup_zip": pickup_zip,
        "website": website,
        "base_url": base_url,
        "store_number": store_number_from_url(website),
        "search_values": [
            value
            for value in [
                pickup_zip,
                exact_address,
                selected_name,
                store_number_from_url(website),
            ]
            if value
        ],
    }


def build_driver(headless: bool):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        return uc.Chrome(
            options=options,
            headless=headless,
            use_subprocess=True,
            version_main=CHROME_VERSION_MAIN,
        )
    except Exception:
        return uc.Chrome(options=options, headless=headless, use_subprocess=True)


def click_visible(driver, xpaths: list[str], wait: float = DEFAULT_WAIT) -> bool:
    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.3)
                    element.click()
                    time.sleep(wait)
                    return True
            except Exception:
                continue
    return False


def type_visible_input(driver, values: list[str], wait: float = DEFAULT_WAIT) -> bool:
    input_xpaths = [
        "//input[not(@type='hidden')]",
        "//*[@contenteditable='true']",
        "//textarea",
    ]

    for value in values:
        for xpath in input_xpaths:
            try:
                inputs = driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue

            for box in inputs:
                try:
                    if box.is_displayed() and box.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
                        time.sleep(0.2)
                        box.click()
                        try:
                            box.clear()
                        except Exception:
                            pass
                        box.send_keys(value)
                        time.sleep(0.5)
                        box.send_keys(Keys.ENTER)
                        time.sleep(wait)
                        return True
                except Exception:
                    continue
    return False


def page_contains(driver, needles: list[str]) -> bool:
    try:
        text = clean_text(driver.page_source).lower()
    except Exception:
        return False
    return any(clean_text(needle).lower() in text for needle in needles if needle)


def common_location_clicks(store_key: str) -> list[str]:
    phrases = [
        "change store", "select store", "choose store", "my store", "store", "pickup",
        "delivery", "location", "change location", "find a store", "store locator",
        "warehouse", "find a warehouse", "change warehouse", "how do you want your items",
    ]
    xpaths = []
    for phrase in phrases:
        lowered = phrase.lower()
        xpaths.extend([
            f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//*[contains(@aria-label, '{phrase}')]",
            f"//*[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
        ])
    return xpaths


def final_selection_clicks(context: dict[str, Any]) -> list[str]:
    selected = clean_text(context.get("selected_name")).lower()
    address_part = clean_text(context.get("exact_address")).split(",")[0].lower()
    store_number = clean_text(context.get("store_number"))

    phrases = [
        "set store", "make this my store", "select store", "shop this store",
        "start shopping", "save", "update location", "make it my store",
        "set as my warehouse", "select", "use this store", "choose this store",
    ]

    if selected:
        phrases.insert(0, selected)
    if address_part:
        phrases.insert(0, address_part)
    if store_number:
        phrases.insert(0, store_number)

    xpaths = []
    for phrase in phrases:
        lowered = phrase.lower()
        xpaths.extend([
            f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
        ])
    return xpaths


def update_one_store(driver, context: dict[str, Any], wait: float) -> dict[str, Any]:
    store_key = context["store_key"]
    base_url = context["base_url"]
    website = context["website"]

    if not base_url:
        return {"attempted": True, "ok": False, "message": "No base URL found.", **context}

    start_url = website or base_url
    print(f"\n🏬 {store_key}: opening {start_url}")

    try:
        driver.get(start_url)
        time.sleep(wait)

        # Some store-specific direct pages already set/store context better than homepage.
        if page_contains(driver, [context.get("selected_name"), context.get("exact_address"), context.get("pickup_zip")]):
            maybe_ok = True
        else:
            maybe_ok = False

        clicked_location = click_visible(driver, common_location_clicks(store_key), wait=wait)
        typed_location = type_visible_input(driver, context["search_values"], wait=wait)
        clicked_final = click_visible(driver, final_selection_clicks(context), wait=wait)

        time.sleep(wait)

        confirmed = page_contains(
            driver,
            [
                context.get("selected_name"),
                context.get("exact_address"),
                context.get("pickup_zip"),
                context.get("store_number"),
            ],
        )

        ok = bool(confirmed or clicked_final or maybe_ok)

        return {
            "attempted": True,
            "ok": ok,
            "message": "Attempted website home-store update." if ok else "Could not confirm store was selected on website.",
            "clicked_location": clicked_location,
            "typed_location": typed_location,
            "clicked_final": clicked_final,
            **context,
        }

    except Exception as exc:
        return {"attempted": True, "ok": False, "message": str(exc), **context}


def main() -> int:
    parser = argparse.ArgumentParser(description="Set home/pickup stores on store websites from shopping_stores_Results.json.")
    parser.add_argument("--stores", nargs="*", help="Optional store keys to update, like meijer aldi walmart.")
    parser.add_argument("--headed", action="store_true", help="Show Chrome windows.")
    parser.add_argument("--force", action="store_true", help="Redo stores even if prior website_home_store_update ok=true.")
    parser.add_argument("--wait", type=float, default=4.0, help="Seconds to wait between page actions.")
    args = parser.parse_args()

    results_file = find_results_file()
    data = json.loads(results_file.read_text(encoding="utf-8"))
    home = data.get("home_address", {})
    stores = data.get("stores", {})

    requested = {s.lower() for s in args.stores or []}
    headless = not args.headed

    headless = False
    driver = build_driver(headless=headless)

    try:
        for store_key, store_data in stores.items():
            key = str(store_key).lower()
            if requested and key not in requested:
                continue

            existing = store_data.get("website_home_store_update") or {}
            if existing.get("ok") and not args.force:
                print(f"✅ Skipping {key}; already marked ok. Use --force to redo.")
                continue

            context = build_store_context(key, store_data, home)
            result = update_one_store(driver, context, wait=args.wait)
            stores[store_key]["website_home_store_update"] = result

            status = "✅" if result.get("ok") else "⚠️"
            print(f"{status} {key}: {result.get('message')}")

            results_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"\n✅ Saved updates to: {results_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
