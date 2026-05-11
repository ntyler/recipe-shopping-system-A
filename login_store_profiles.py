from __future__ import annotations

import json
import time
from pathlib import Path

import undetected_chromedriver as uc


# =========================================================
# PATHS
# =========================================================

THIS_FILE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_FILE_DIR.parent

STORES_JSON = PROJECT_ROOT / "PushShoppingList" / "shopping_stores.json"

PROFILE_ROOT = PROJECT_ROOT / "chrome_worker_profiles"

STORE_RESULTS_CANDIDATES = [
    PROJECT_ROOT / "shopping_stores_Results.json",
    PROJECT_ROOT / "PushShoppingList" / "shopping_stores_Results.json",
]


# =========================================================
# LOAD STORES
# =========================================================

with STORES_JSON.open("r", encoding="utf-8") as f:
    STORES = json.load(f)


# =========================================================
# CHROME
# =========================================================

def build_driver(profile_name: str):
    profile_dir = PROFILE_ROOT / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"🧠 Using browser profile: {profile_dir}")

    options = uc.ChromeOptions()

    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={profile_dir}")

    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = uc.Chrome(
        options=options,
        use_subprocess=True,
    )

    driver.set_page_load_timeout(60)

    return driver


def build_driver(profile_name: str):
    profile_dir = PROFILE_ROOT / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"🧠 Using browser profile: {profile_dir}")

    options = uc.ChromeOptions()

    options.add_argument("--start-maximized")

    # PERSISTENT PROFILE
    options.add_argument(f"--user-data-dir={profile_dir}")

    # USE NORMAL CHROME PROFILE
    options.add_argument("--profile-directory=Default")

    # REDUCE AUTOMATION DETECTION
    options.add_argument("--disable-blink-features=AutomationControlled")

    # KEEP NORMAL CHROME FEATURES
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")

    # IMPORTANT:
    # DO NOT DISABLE PASSWORD FEATURES
    # DO NOT USE GUEST MODE
    # DO NOT USE INCOGNITO

    driver = uc.Chrome(
        options=options,
        use_subprocess=True,
    )

    driver.set_page_load_timeout(60)

    return driver


# =========================================================
# HELPERS
# =========================================================

def click_xpath(driver, xpaths, wait=2):
    for xpath in xpaths:
        try:
            elements = driver.find_elements("xpath", xpath)
        except Exception:
            continue

        for element in elements:
            try:
                if not element.is_displayed():
                    continue

                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    element,
                )

                time.sleep(0.3)

                driver.execute_script(
                    "arguments[0].click();",
                    element,
                )

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

    time.sleep(0.3)

    element.send_keys("\ue009" + "a")
    time.sleep(0.2)

    element.send_keys("\ue003")
    time.sleep(0.2)

    try:
        element.clear()
    except Exception:
        pass

    time.sleep(0.2)

    element.send_keys(value)

    time.sleep(1)


def page_text(driver) -> str:
    try:
        return driver.find_element("tag name", "body").text.lower()
    except Exception:
        return ""


def already_logged_in(driver) -> bool:
    text = page_text(driver)

    return (
        "sign out" in text
        or "my account" in text
        or "account settings" in text
        or "hi," in text
    )
