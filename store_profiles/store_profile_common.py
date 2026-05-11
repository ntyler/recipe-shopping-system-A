# store_profile_common.py

from __future__ import annotations

import json
import time
from pathlib import Path

import undetected_chromedriver as uc


# =========================================================
# PATHS
# =========================================================

THIS_FILE_DIR = Path(__file__).resolve().parent

if (THIS_FILE_DIR / "PushShoppingList" / "shopping_stores.json").exists():
    PROJECT_ROOT = THIS_FILE_DIR
else:
    PROJECT_ROOT = THIS_FILE_DIR.parent

STORES_JSON = PROJECT_ROOT / "PushShoppingList" / "shopping_stores.json"
PROFILE_ROOT = PROJECT_ROOT / "chrome_worker_profiles"

STORE_RESULTS_CANDIDATES = [
    PROJECT_ROOT / "shopping_stores_Results.json",
    PROJECT_ROOT / "PushShoppingList" / "shopping_stores_Results.json",
]


def load_stores() -> dict:
    if not STORES_JSON.exists():
        print(f"❌ Missing stores JSON: {STORES_JSON}")
        return {}

    try:
        return json.loads(STORES_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"❌ Could not read {STORES_JSON}: {exc}")
        return {}


STORES = load_stores()


# =========================================================
# CHROME
# =========================================================

##def build_driver(profile_name: str):
##    profile_dir = PROFILE_ROOT / profile_name
##    profile_dir.mkdir(parents=True, exist_ok=True)
##
##    print(f"🧠 Saving browser profile to: {profile_dir}")
##
##    options = uc.ChromeOptions()
##    options.add_argument("--start-maximized")
##    options.add_argument(f"--user-data-dir={profile_dir}")
##    options.add_argument("--disable-popup-blocking")
##    options.add_argument("--disable-notifications")
##    options.add_argument("--no-first-run")
##    options.add_argument("--no-default-browser-check")
##    options.add_argument("--disable-blink-features=AutomationControlled")
##
##    driver = uc.Chrome(
##        options=options,
##        use_subprocess=True,
##    )
##
##    driver.set_page_load_timeout(60)
##    return driver


def build_driver(profile_name: str = "profile_stores_common"):
    profile_dir = PROFILE_ROOT / "profile_stores_common"
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"🧠 Using shared browser profile: {profile_dir}")

    options = uc.ChromeOptions()

    options.add_argument("--start-maximized")

    # SHARED PERSISTENT PROFILE
    options.add_argument(f"--user-data-dir={profile_dir}")

    # USE DEFAULT CHROME PROFILE
    options.add_argument("--profile-directory=Default")

    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = uc.Chrome(
        options=options,
        use_subprocess=True,
    )

    driver.set_page_load_timeout(60)

    return driver


# =========================================================
# SELENIUM HELPERS
# =========================================================

def click_xpath(driver, xpaths, wait=2):
    for xpath in xpaths:
        try:
            elements = driver.find_elements("xpath", xpath)
        except Exception:
            continue

        visible = []

        for element in elements:
            try:
                if not element.is_displayed() or not element.is_enabled():
                    continue

                rect = element.rect or {}
                area = float(rect.get("width", 0) or 0) * float(rect.get("height", 0) or 0)
                visible.append((area, element))
            except Exception:
                continue

        for _, element in sorted(visible, key=lambda item: item[0]):
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    element,
                )
                time.sleep(0.25)
                driver.execute_script("arguments[0].click();", element)
                time.sleep(wait)
                return True
            except Exception:
                continue

    return False


def find_css(driver, selectors):
    for selector in selectors:
        try:
            elements = driver.find_elements("css selector", selector)
        except Exception:
            continue

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                continue

    return None


def type_box(element, value: str):
    element.click()
    time.sleep(0.4)

    # CTRL + A
    element.send_keys("\ue009" + "a")
    time.sleep(0.25)

    # BACKSPACE
    element.send_keys("\ue003")
    time.sleep(0.25)

    try:
        element.clear()
    except Exception:
        pass

    time.sleep(0.25)
    element.send_keys(value)
    time.sleep(1)


def page_text(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text.lower()
    except Exception:
        return ""


def xpath_literal(value: str) -> str:
    value = str(value or "")

    if "'" not in value:
        return f"'{value}'"

    if '"' not in value:
        return f'"{value}"'

    parts = value.split("'")
    return "concat(" + ', "\\\'", '.join(f"'{part}'" for part in parts) + ")"


# =========================================================
# STORE RESULTS HELPERS
# =========================================================

def find_store_results_file() -> Path | None:
    for path in STORE_RESULTS_CANDIDATES:
        if path.exists():
            return path
    return None


def load_store_results() -> dict:
    path = find_store_results_file()

    if not path:
        print("⚠️ shopping_stores_Results.json not found")
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠️ Could not read {path}: {exc}")
        return {}


def get_home_address(results: dict) -> str:
    home = results.get("home_address") or {}

    full_address = str(home.get("full_address") or "").strip()
    if full_address:
        return full_address

    street_line = " ".join(
        str(part or "").strip()
        for part in [
            home.get("street"),
            home.get("apartment"),
        ]
        if str(part or "").strip()
    )

    city_state_zip = " ".join(
        str(part or "").strip()
        for part in [
            home.get("city"),
            home.get("state"),
            home.get("zip"),
        ]
        if str(part or "").strip()
    )

    return ", ".join(part for part in [street_line, city_state_zip] if part)


def get_store_result(results: dict, store_key: str) -> dict:
    stores = results.get("stores") or {}
    return stores.get(store_key) or {}


def print_profile_result(store_key: str, ok: bool):
    print("")
    if ok:
        print(f"✅ {store_key.upper()} browser profile is now saved/authenticated here:")
    else:
        print(f"⚠️ {store_key.upper()} did not fully complete, but profile is still saved here:")
    print(PROFILE_ROOT / f"profile_{store_key}")
    print("")


def run_store_script(store_key: str, login_func=None, update_address_func=None, pause_before_close=True):
    store = STORES.get(store_key)

    if not store:
        print(f"❌ No {store_key} config found in shopping_stores.json")
        return

    driver = build_driver(f"profile_{store_key}")

    ok = True

    try:
        if login_func:
            ok = bool(login_func(driver, store))

        if ok and update_address_func:
            update_address_func(driver)

        print_profile_result(store_key, ok)

        if pause_before_close:
            input("Press ENTER to close browser...")

    finally:
        driver.quit()
