from __future__ import annotations

import re
import time
from typing import Any

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


def clean_store_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_zip_from_text(value: Any) -> str:
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", str(value or ""))
    return match.group(0) if match else ""


def store_number_from_url(url: Any) -> str:
    url = str(url or "")
    for pattern in [
        r"/store/(\d+)",
        r"/store-locator/(\d+)\.html",
        r"/sl/[^/]+/(\d+)",
        r"/([a-z]?\d{2,6})/?$",
        r"/([a-z]?\d{2,6})(?:[?#]|$)",
    ]:
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def store_address_hints(address: Any) -> list[str]:
    text = clean_store_text(address)
    if not text:
        return []

    parts = [clean_store_text(part) for part in text.split(",") if clean_store_text(part)]
    hints: list[str] = []

    def add(value: Any) -> None:
        value = clean_store_text(value)
        if value and value.lower() not in {hint.lower() for hint in hints}:
            hints.append(value)

    add(text)

    first_with_digit = ""
    for index, part in enumerate(parts):
        if re.search(r"\d", part):
            if (
                re.fullmatch(r"\d{2,6}", part)
                and index + 1 < len(parts)
                and not re.search(r"\d{5}", parts[index + 1])
            ):
                first_with_digit = f"{part} {parts[index + 1]}"
            else:
                first_with_digit = part
            break

    if first_with_digit:
        add(first_with_digit)
        add(shorten_street_words(first_with_digit))
        add(expand_street_words(first_with_digit))

    street_number = re.search(r"\b\d{2,6}\b", text)
    if street_number:
        add(street_number.group(0))

    zip_code = extract_zip_from_text(text)
    if zip_code:
        add(zip_code)

    return hints


def shorten_street_words(value: Any) -> str:
    text = clean_store_text(value)
    replacements = {
        r"\bSouth\b": "S",
        r"\bNorth\b": "N",
        r"\bEast\b": "E",
        r"\bWest\b": "W",
        r"\bAvenue\b": "Ave",
        r"\bRoad\b": "Rd",
        r"\bStreet\b": "St",
        r"\bDrive\b": "Dr",
        r"\bBoulevard\b": "Blvd",
        r"\bLane\b": "Ln",
        r"\bCourt\b": "Ct",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return clean_store_text(text)


def expand_street_words(value: Any) -> str:
    text = clean_store_text(value)
    replacements = {
        r"\bS\b": "South",
        r"\bN\b": "North",
        r"\bE\b": "East",
        r"\bW\b": "West",
        r"\bAve\b": "Avenue",
        r"\bRd\b": "Road",
        r"\bSt\b": "Street",
        r"\bDr\b": "Drive",
        r"\bBlvd\b": "Boulevard",
        r"\bLn\b": "Lane",
        r"\bCt\b": "Court",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return clean_store_text(text)


def build_store_context(
    store_key: str,
    store: dict[str, Any] | None,
    full_address: str,
    store_location: dict[str, Any] | None = None,
    start_url: str = "",
) -> dict[str, Any]:
    store = store or {}
    store_location = store_location or {}
    store_key = clean_store_text(store_key).lower()
    store_name = clean_store_text(store.get("label") or store_location.get("name") or store_key.title())
    exact_address = clean_store_text(
        store_location.get("exact_address")
        or store_location.get("address")
        or store.get("exact_address")
        or store.get("location")
    )
    selected_name = clean_store_text(
        store_location.get("selected_name")
        or store_location.get("name")
        or store.get("selected_name")
        or store.get("pickup_store_name")
        or store_name
    )
    website = clean_store_text(
        store.get("urlStoreSelector")
        or store_location.get("website")
        or store.get("base_url")
        or store.get("url")
    )
    pickup_zip = (
        clean_store_text(store.get("pickup_zip"))
        or extract_zip_from_text(exact_address)
        or extract_zip_from_text(full_address)
    )
    store_number = (
        clean_store_text(store_location.get("store_id"))
        or clean_store_text(store.get("store_id"))
        or store_number_from_url(store_location.get("website"))
        or store_number_from_url(website)
    )

    search_values: list[str] = []
    for value in [
        full_address,
        extract_zip_from_text(full_address),
        pickup_zip,
        exact_address,
        *store_address_hints(exact_address),
        selected_name,
        store_number,
    ]:
        value = clean_store_text(value)
        if value and value.lower() not in {existing.lower() for existing in search_values}:
            search_values.append(value)

    return {
        "store_key": store_key,
        "store_name": store_name,
        "selected_name": selected_name,
        "exact_address": exact_address,
        "address_hints": store_address_hints(exact_address),
        "pickup_zip": pickup_zip,
        "urlStoreSelector": clean_store_text(store.get("urlStoreSelector")),
        "website": website,
        "base_url": clean_store_text(store.get("base_url")),
        "store_session_url": clean_store_text(start_url),
        "store_number": store_number,
        "home_address": clean_store_text(full_address),
        "home_zip": extract_zip_from_text(full_address),
        "username": clean_store_text(store.get("username")),
        "password": clean_store_text(store.get("password")),
        "search_values": search_values,
        "store_location": store_location,
    }


def page_contains_any(driver, needles: list[Any]) -> bool:
    try:
        text = clean_store_text(driver.page_source).lower()
    except Exception:
        return False
    return any(clean_store_text(needle).lower() in text for needle in needles if clean_store_text(needle))


def click_visible_xpath(driver, xpaths: list[str], wait: float = 1.5) -> bool:
    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                    time.sleep(0.2)
                    element.click()
                    time.sleep(wait)
                    return True
            except Exception:
                continue
    return False


def type_visible_location_input(driver, values: list[Any], wait: float = 1.5) -> bool:
    input_xpaths = [
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'near')]",
        "//input[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'near')]",
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'address')]",
        "//input[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'address')]",
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'zip')]",
        "//input[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'zip')]",
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'location')]",
        "//input[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'location')]",
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'city')]",
        "//input[contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'search')]",
        "//input[not(@type='hidden')]",
        "//*[@contenteditable='true']",
        "//textarea",
    ]
    for value in values or []:
        value = clean_store_text(value)
        if not value:
            continue
        for xpath in input_xpaths:
            try:
                boxes = driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            for box in boxes:
                try:
                    if box.is_displayed() and box.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
                        time.sleep(0.2)
                        box.click()
                        try:
                            box.clear()
                        except Exception:
                            pass
                        try:
                            box.send_keys(Keys.CONTROL, "a")
                            box.send_keys(Keys.BACKSPACE)
                        except Exception:
                            pass
                        box.send_keys(value)
                        time.sleep(0.4)
                        box.send_keys(Keys.ENTER)
                        time.sleep(wait)
                        return True
                except Exception:
                    continue
    return False


def common_location_xpaths() -> list[str]:
    phrases = [
        "change store",
        "select store",
        "choose store",
        "my store",
        "pickup",
        "delivery",
        "location",
        "change location",
        "find a store",
        "store locator",
        "warehouse",
        "how do you want your items",
    ]
    xpaths: list[str] = []
    for phrase in phrases:
        lowered = phrase.lower()
        xpaths.extend([
            f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//*[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
        ])
    return xpaths


def final_home_store_xpaths(context: dict[str, Any]) -> list[str]:
    phrases = [
        *context.get("address_hints", []),
        context.get("selected_name"),
        context.get("store_number"),
        "set store",
        "make this my store",
        "select store",
        "shop this store",
        "start shopping",
        "save",
        "update location",
        "set as my warehouse",
        "use this store",
        "choose this store",
        "confirm",
        "continue",
    ]
    xpaths: list[str] = []
    for phrase in phrases:
        lowered = clean_store_text(phrase).lower()
        if not lowered:
            continue
        xpaths.extend([
            f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
        ])
    return xpaths


def click_text_button(driver, phrases: list[str], wait: float = 1.0) -> bool:
    for phrase in phrases:
        phrase = clean_store_text(phrase)
        if not phrase:
            continue
        lowered = phrase.lower()
        xpaths = [
            f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
            f"//*[@role='button' and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{lowered}')]",
        ]
        if click_visible_xpath(driver, xpaths, wait=wait):
            return True
    return False


def js_click(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", element)
        time.sleep(0.2)
        driver.execute_script("arguments[0].click();", element)
        time.sleep(0.75)
        return True
    except Exception:
        try:
            ActionChains(driver).move_to_element(element).pause(0.2).click().perform()
            time.sleep(0.75)
            return True
        except Exception:
            return False


def xpath_literal(value: str) -> str:
    value = str(value or "")
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


def click_store_card_that_matches_context(driver, context: dict[str, Any], wait: float = 2.0) -> bool:
    target_texts: list[str] = []
    for value in [
        *context.get("address_hints", []),
        context.get("store_number"),
        context.get("selected_name"),
        context.get("pickup_zip"),
    ]:
        value = clean_store_text(value)
        if value and value.lower() not in {existing.lower() for existing in target_texts}:
            target_texts.append(value)

    for target in target_texts:
        text_nodes = []
        for xpath in [
            f"//*[contains(normalize-space(.), {xpath_literal(target)})]",
            f"//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), {xpath_literal(target.lower())})]",
        ]:
            try:
                text_nodes.extend(driver.find_elements(By.XPATH, xpath))
            except Exception:
                continue

        visible_nodes = []
        for element in text_nodes:
            try:
                if not element.is_displayed():
                    continue
                rect = element.rect or {}
                area = float(rect.get("width", 0) or 0) * float(rect.get("height", 0) or 0)
                if area > 0:
                    visible_nodes.append((area, element))
            except Exception:
                continue

        for _, text_element in sorted(visible_nodes, key=lambda item: item[0]):
            card = text_element
            for _ in range(8):
                try:
                    parent = card.find_element(By.XPATH, "..")
                    parent_text = clean_store_text(parent.text)
                    radios = parent.find_elements(By.XPATH, ".//input[@type='radio'] | .//*[@role='radio']")
                    buttons = parent.find_elements(By.XPATH, ".//button | .//*[@role='button']")
                    rect = parent.rect or {}
                    area = float(rect.get("width", 0) or 0) * float(rect.get("height", 0) or 0)
                except Exception:
                    break
                if target.lower() in parent_text.lower() and (radios or buttons or area < 350000):
                    card = parent
                    break
                card = parent

            click_targets = []
            for xpath in [
                ".//input[@type='radio']",
                ".//*[@role='radio']",
                ".//button[contains(@aria-label, 'Select') or contains(@aria-label, 'select')]",
                ".//button",
            ]:
                try:
                    click_targets.extend(card.find_elements(By.XPATH, xpath))
                except Exception:
                    pass
            click_targets.extend([card, text_element])

            for target_element in click_targets:
                try:
                    if target_element.is_displayed() and js_click(driver, target_element):
                        time.sleep(wait)
                        return True
                except Exception:
                    continue
    return False


def click_continue_shopping(driver, wait: float = 2.0) -> bool:
    return click_text_button(
        driver,
        [
            "Continue shopping",
            "Start shopping",
            "Shop this store",
            "Use this store",
            "Select store",
            "Confirm",
            "Save",
            "Done",
        ],
        wait=wait,
    )


def accept_cookies_if_present(driver, wait: float = 0.75) -> bool:
    return click_text_button(driver, ["Accept all", "I accept", "Accept", "Agree", "Got it"], wait=wait)


def correct_home_store_selected(driver, context: dict[str, Any]) -> bool:
    try:
        page_text = clean_store_text(driver.page_source).lower()
    except Exception:
        return False

    def contains(value: Any) -> bool:
        value = clean_store_text(value).lower()
        return bool(value and value in page_text)

    strong_hints = [
        hint
        for hint in context.get("address_hints", [])
        if re.search(r"\d", clean_store_text(hint)) and len(clean_store_text(hint)) >= 4
    ]
    if any(contains(hint) for hint in strong_hints):
        return True
    if contains(context.get("store_number")):
        return True
    if contains(context.get("pickup_zip")) and contains(context.get("selected_name")):
        return True
    return False


def build_store_helpers() -> dict[str, Any]:
    return {
        "accept_cookies_if_present": accept_cookies_if_present,
        "click_text_button": click_text_button,
        "click_visible_xpath": click_visible_xpath,
        "type_visible_location_input": type_visible_location_input,
        "click_store_card_that_matches_context": click_store_card_that_matches_context,
        "click_continue_shopping": click_continue_shopping,
        "final_home_store_xpaths": final_home_store_xpaths,
        "correct_home_store_selected": correct_home_store_selected,
        "page_contains_any": page_contains_any,
        "common_location_xpaths": common_location_xpaths,
        "clean_store_text": clean_store_text,
    }

