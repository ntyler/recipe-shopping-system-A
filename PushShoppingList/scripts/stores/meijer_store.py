from __future__ import annotations

import time
from typing import Any


def get_start_url(context: dict[str, Any]) -> str:
    return (
        context.get("store_session_url")
        or context.get("urlStoreSelector")
        or context.get("website")
        or context.get("base_url")
        or "https://www.meijer.com/"
    )


def _text(context: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(context.get(key) or "").strip()
        if value:
            return value
    return ""


def click_visible(driver, xpaths: list[str], wait_seconds: float = 2.0) -> bool:
    for xpath in xpaths:
        try:
            elements = driver.find_elements("xpath", xpath)
        except Exception:
            continue
        visible = []
        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    rect = element.rect or {}
                    area = float(rect.get("width", 0) or 0) * float(rect.get("height", 0) or 0)
                    visible.append((area, element))
            except Exception:
                continue
        for _, element in sorted(visible, key=lambda item: item[0]):
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", element)
                time.sleep(0.25)
                driver.execute_script("arguments[0].click();", element)
                time.sleep(wait_seconds)
                return True
            except Exception:
                continue
    return False


def find_visible_css(driver, selectors: list[str]):
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


def type_into_box(element, value: str) -> bool:
    try:
        element.click()
        time.sleep(0.4)
        element.send_keys("\ue009" + "a")
        element.send_keys("\ue003")
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(value)
        time.sleep(0.8)
        return True
    except Exception:
        return False


def login_meijer_if_credentials_exist(
    driver,
    context: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    username = _text(context, "username", "userName", "email", "login_username", "store_username")
    password = _text(context, "password", "login_password", "store_password")
    if not username or not password:
        return False

    clicked_header = click_visible(
        driver,
        [
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//a[contains(normalize-space(.), 'Sign in')]",
            "//*[@role='button' and contains(normalize-space(.), 'Sign in')]",
            "//*[contains(@aria-label, 'Sign in')]",
            "//*[contains(@aria-label, 'Account')]",
        ],
        wait_seconds=wait_seconds,
    )
    if not clicked_header:
        raise RuntimeError("Meijer header Sign in was not clicked.")

    clicked_drawer = click_visible(
        driver,
        [
            "//button[normalize-space(.)='Sign in']",
            "//a[normalize-space(.)='Sign in']",
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//a[contains(normalize-space(.), 'Sign in')]",
            "//aside//button[contains(normalize-space(.), 'Sign in')]",
            "//div[contains(@class,'drawer')]//button[contains(normalize-space(.), 'Sign in')]",
        ],
        wait_seconds=wait_seconds,
    )
    if not clicked_drawer:
        raise RuntimeError("Meijer drawer Sign in was not clicked.")

    email_box = find_visible_css(
        driver,
        [
            "input[name='identifier']",
            "input[type='email']",
            "input[id*='identifier']",
            "input[id*='email']",
            "input[autocomplete='username']",
        ],
    )
    if not email_box or not type_into_box(email_box, username):
        raise RuntimeError("Meijer email could not be typed.")

    clicked_next = click_visible(
        driver,
        [
            "//input[@type='submit']",
            "//button[@type='submit']",
            "//button[contains(normalize-space(.), 'Next')]",
            "//button[contains(normalize-space(.), 'Continue')]",
        ],
        wait_seconds=wait_seconds,
    )
    if not clicked_next:
        raise RuntimeError("Meijer Next button was not clicked.")

    password_box = find_visible_css(
        driver,
        [
            "input[name='credentials.passcode']",
            "input[type='password']",
            "input[id*='password']",
            "input[name*='password']",
            "input[autocomplete='current-password']",
        ],
    )
    if not password_box or not type_into_box(password_box, password):
        raise RuntimeError("Meijer password could not be typed.")

    clicked_submit = click_visible(
        driver,
        [
            "//input[@type='submit']",
            "//button[@type='submit']",
            "//button[contains(normalize-space(.), 'Submit')]",
            "//button[contains(normalize-space(.), 'Sign In')]",
            "//button[contains(normalize-space(.), 'Sign in')]",
            "//button[contains(normalize-space(.), 'Log in')]",
        ],
        wait_seconds=wait_seconds,
    )
    if not clicked_submit:
        raise RuntimeError("Meijer Submit button was not clicked.")
    return True


def update_home_store(
    driver,
    context: dict[str, Any],
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    accept_cookies_if_present = helpers["accept_cookies_if_present"]
    click_visible_xpath = helpers["click_visible_xpath"]
    common_location_xpaths = helpers["common_location_xpaths"]
    type_visible_location_input = helpers["type_visible_location_input"]
    click_store_card_that_matches_context = helpers["click_store_card_that_matches_context"]
    click_continue_shopping = helpers["click_continue_shopping"]
    final_home_store_xpaths = helpers["final_home_store_xpaths"]
    correct_home_store_selected = helpers["correct_home_store_selected"]

    clicked_login = False
    clicked_location = False
    typed_location = False
    clicked_store_card = False
    clicked_continue = False
    clicked_final = False

    start_url = get_start_url(context)
    driver.get(start_url)
    time.sleep(wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    try:
        clicked_login = login_meijer_if_credentials_exist(driver, context, worker_id, wait_seconds)
    except Exception as exc:
        print(f"[Worker {worker_id}] Meijer login skipped/failed: {exc}")

    driver.get(start_url)
    time.sleep(wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    clicked_location = click_visible_xpath(driver, common_location_xpaths(), wait=wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    typed_location = type_visible_location_input(driver, context.get("search_values", []), wait=wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)
    time.sleep(1)

    clicked_store_card = click_store_card_that_matches_context(driver=driver, context=context, wait=wait_seconds)
    clicked_continue = click_continue_shopping(driver, wait=wait_seconds)

    if not clicked_continue:
        clicked_final = click_visible_xpath(driver, final_home_store_xpaths(context), wait=wait_seconds)

    time.sleep(wait_seconds)
    confirmed = correct_home_store_selected(driver, context)

    return {
        "attempted": True,
        "ok": bool(confirmed),
        "message": "Meijer home store confirmed." if confirmed else "Meijer home store was not confirmed.",
        "clicked_login": clicked_login,
        "clicked_location": clicked_location,
        "typed_location": typed_location,
        "clicked_store_card": clicked_store_card,
        "clicked_continue": clicked_continue,
        "clicked_final": clicked_final,
        **context,
    }

