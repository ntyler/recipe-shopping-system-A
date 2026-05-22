from __future__ import annotations

import time
from typing import Any

from selenium.webdriver.common.keys import Keys


def get_start_url(context: dict[str, Any]) -> str:
    return (
        context.get("store_session_url")
        or context.get("start_url")
        or context.get("website")
        or context.get("urlStoreSelector")
        or context.get("base_url")
        or "https://www.aldi.us/store/aldi"
    )


def open_aldi_store_selector_page(
    driver,
    context: dict[str, Any],
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    click_visible_xpath = helpers["click_visible_xpath"]
    start_url = get_start_url(context)

    print(f"[Worker {worker_id}] Aldi opening: {start_url}")
    driver.get(start_url)
    time.sleep(wait_seconds)

    clicked_top_store = click_visible_xpath(
        driver,
        [
            "//*[contains(text(), 'Shopping at ALDI')]",
            "//*[contains(text(), 'Delivery')]",
            "//*[contains(text(), 'Pickup')]",
            "//button[contains(., 'Shopping at ALDI')]",
            "//button[contains(., 'Delivery')]",
            "//button[contains(., 'Pickup')]",
            "//button[contains(., 'How would you like to shop')]",
        ],
        wait=wait_seconds,
    )
    time.sleep(1)

    clicked_change_store = click_visible_xpath(
        driver,
        [
            "(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'change store')])[last()]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'choose an in-store location')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'find stores')]",
        ],
        wait=wait_seconds,
    )

    if clicked_change_store:
        return True

    if clicked_top_store:
        clicked_change_store = click_visible_xpath(
            driver,
            [
                "(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'change store')])[last()]",
                "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'choose an in-store location')]",
            ],
            wait=wait_seconds,
        )
        if clicked_change_store:
            return True

    raise RuntimeError("Aldi Change store button was not clicked. Cannot enter address yet.")


def click_aldi_near_button(
    driver,
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    click_visible_xpath = helpers["click_visible_xpath"]
    clicked_near_box = click_visible_xpath(
        driver,
        [
            "//button[contains(., 'Near')]",
            "//button[contains(., '60602')]",
            "//button[@aria-haspopup='dialog' and contains(., 'Near')]",
            "//button[@type='button' and contains(., 'Near')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'near')]",
        ],
        wait=wait_seconds,
    )
    if not clicked_near_box:
        raise RuntimeError("Aldi Near location button was not clicked.")
    time.sleep(1)
    return True


def click_aldi_shop_this_store(
    driver,
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    click_visible_xpath = helpers["click_visible_xpath"]

    try:
        clicked_direct = driver.execute_script(
            """
            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const style = window.getComputedStyle(node);
                    if (node.hidden || style.display === "none" || style.visibility === "hidden") {
                        return false;
                    }
                    node = node.parentElement;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && !el.disabled;
            }

            const controls = Array.from(document.querySelectorAll("button, [role='button'], input[type='submit']"));
            const button = controls.find(el => {
                const text = String(el.innerText || el.value || el.getAttribute("aria-label") || "")
                    .replace(/\\s+/g, " ")
                    .trim();
                return visible(el) && /^shop this store$/i.test(text);
            });
            if (!button) {
                return false;
            }
            button.scrollIntoView({ block: "center", inline: "center" });
            button.click();
            return true;
            """
        )
    except Exception:
        clicked_direct = False

    if clicked_direct:
        time.sleep(wait_seconds)
        return True

    clicked_shop = click_visible_xpath(
        driver,
        [
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'shop this store')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'shop this store')]",
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'select store')]",
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'set as my store')]",
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'use this store')]",
        ],
        wait=wait_seconds,
    )
    time.sleep(1)
    return bool(clicked_shop)


def clean_aldi_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def aldi_location_search_values(context: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        value = clean_aldi_text(value)
        if value and value.lower() not in {existing.lower() for existing in values}:
            values.append(value)

    add(context.get("pickup_zip"))
    add(context.get("home_zip"))
    add(context.get("exact_address"))
    add(context.get("home_address"))
    for value in context.get("search_values", []):
        add(value)
    return values


def find_aldi_location_input(driver):
    try:
        return driver.execute_script(
            """
            function visible(el) {
                if (!el || el.disabled || el.readOnly) return false;
                let node = el;
                while (node && node.nodeType === 1) {
                    const style = window.getComputedStyle(node);
                    if (
                        node.hidden ||
                        node.getAttribute("aria-hidden") === "true" ||
                        style.display === "none" ||
                        style.visibility === "hidden" ||
                        Number(style.opacity || "1") === 0
                    ) {
                        return false;
                    }
                    node = node.parentElement;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            const dialogs = Array.from(document.querySelectorAll(
                '[role="dialog"], [aria-modal="true"], [data-dialog="true"]'
            )).filter(visible);
            const roots = dialogs.length ? dialogs : [document.body || document.documentElement];
            const fields = [];
            for (const root of roots) {
                fields.push(...Array.from(root.querySelectorAll(
                    'input:not([type="hidden"]), textarea, [contenteditable="true"]'
                )));
            }

            function fieldText(el) {
                const parts = [
                    el.getAttribute("placeholder"),
                    el.getAttribute("aria-label"),
                    el.getAttribute("name"),
                    el.getAttribute("id"),
                    el.getAttribute("autocomplete"),
                    el.getAttribute("data-testid")
                ];
                if (el.id && window.CSS && CSS.escape) {
                    document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach(label => {
                        parts.push(label.innerText);
                    });
                }
                const label = el.closest("label");
                if (label) parts.push(label.innerText);
                return parts.filter(Boolean).join(" ").replace(/\\s+/g, " ").toLowerCase();
            }

            const blocked = /(product|item|recipe|weekly|department|cart|sign in|email|password)/i;
            const preferred = /(address|zip|postal|city|state|location|near|store)/i;

            const visibleFields = fields.filter(el => {
                if (!visible(el)) return false;
                const text = fieldText(el);
                if (/hidden-input-for-ios-virtual-keyboard/i.test(text)) return false;
                if (blocked.test(text) && !preferred.test(text)) return false;
                if (dialogs.length) return true;
                return preferred.test(text);
            });

            visibleFields.sort((a, b) => {
                const aPreferred = preferred.test(fieldText(a)) ? 0 : 1;
                const bPreferred = preferred.test(fieldText(b)) ? 0 : 1;
                return aPreferred - bPreferred;
            });
            return visibleFields[0] || null;
            """
        )
    except Exception:
        return None


def type_aldi_location_input(driver, values: list[Any], wait: float = 1.5) -> bool:
    for value in values or []:
        value = clean_aldi_text(value)
        if not value:
            continue

        box = None
        deadline = time.monotonic() + max(1.0, wait)
        while time.monotonic() < deadline:
            box = find_aldi_location_input(driver)
            if box is not None:
                break
            time.sleep(0.2)
        if box is None:
            return False

        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", box)
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
            time.sleep(0.5)
            box.send_keys(Keys.ENTER)
            time.sleep(wait)
            return True
        except Exception:
            continue
    return False


def wait_for_aldi_storefront(driver, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        try:
            current_url = str(driver.current_url or "")
        except Exception:
            current_url = ""
        if "/store/aldi/storefront" in current_url:
            return True
        time.sleep(0.4)
    return False


def update_home_store(
    driver,
    context: dict[str, Any],
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    accept_cookies_if_present = helpers["accept_cookies_if_present"]
    click_first_address_suggestion = helpers["click_first_address_suggestion"]
    click_save_address_button = helpers["click_save_address_button"]
    click_first_store_location_card = helpers["click_first_store_location_card"]
    click_store_card_that_matches_context = helpers["click_store_card_that_matches_context"]
    click_continue_shopping = helpers["click_continue_shopping"]
    click_visible_xpath = helpers["click_visible_xpath"]
    final_home_store_xpaths = helpers["final_home_store_xpaths"]
    correct_home_store_selected = helpers["correct_home_store_selected"]

    clicked_location = False
    clicked_near_box = False
    typed_location = False
    clicked_address_suggestion = False
    clicked_save_address = False
    clicked_first_store_card = False
    clicked_store_card = False
    clicked_shop_this_store = False
    reached_storefront = False
    clicked_continue = False
    clicked_final = False

    accept_cookies_if_present(driver, wait=0.75)
    if correct_home_store_selected(driver, context):
        return {
            "attempted": False,
            "ok": True,
            "message": "Aldi home store was already confirmed.",
            "already_selected": True,
            "clicked_location": clicked_location,
            "clicked_near_box": clicked_near_box,
            "typed_location": typed_location,
            "clicked_address_suggestion": clicked_address_suggestion,
            "clicked_save_address": clicked_save_address,
            "clicked_first_store_card": clicked_first_store_card,
            "clicked_store_card": clicked_store_card,
            "clicked_shop_this_store": clicked_shop_this_store,
            "reached_storefront": reached_storefront,
            "storefront_url": str(getattr(driver, "current_url", "") or ""),
            "clicked_continue": clicked_continue,
            "clicked_final": clicked_final,
            **context,
        }

    clicked_location = open_aldi_store_selector_page(
        driver=driver,
        context=context,
        helpers=helpers,
        worker_id=worker_id,
        wait_seconds=wait_seconds,
    )
    accept_cookies_if_present(driver, wait=0.75)

    try:
        clicked_near_box = click_aldi_near_button(
            driver=driver,
            helpers=helpers,
            worker_id=worker_id,
            wait_seconds=wait_seconds,
        )
    except Exception:
        clicked_near_box = False

    typed_location = type_aldi_location_input(driver, aldi_location_search_values(context), wait=wait_seconds)
    clicked_address_suggestion = click_first_address_suggestion(driver, context, wait=wait_seconds)
    if typed_location or clicked_address_suggestion:
        clicked_save_address = click_save_address_button(driver, wait=wait_seconds)
    time.sleep(wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    clicked_store_card = click_store_card_that_matches_context(driver=driver, context=context, wait=wait_seconds)
    if not clicked_store_card:
        clicked_first_store_card = click_first_store_location_card(driver, wait=wait_seconds)
        clicked_store_card = bool(clicked_first_store_card)
    time.sleep(1)
    accept_cookies_if_present(driver, wait=0.75)

    if not clicked_store_card:
        clicked_store_card = click_store_card_that_matches_context(driver=driver, context=context, wait=wait_seconds)
        time.sleep(1)

    clicked_shop_this_store = click_aldi_shop_this_store(
        driver=driver,
        helpers=helpers,
        worker_id=worker_id,
        wait_seconds=wait_seconds,
    )
    if clicked_shop_this_store:
        reached_storefront = wait_for_aldi_storefront(driver, timeout_seconds=wait_seconds + 8)

    clicked_continue = False if reached_storefront else click_continue_shopping(driver, wait=wait_seconds)

    if not reached_storefront and not clicked_continue:
        clicked_final = click_visible_xpath(driver, final_home_store_xpaths(context), wait=wait_seconds)

    time.sleep(wait_seconds)
    confirmed = correct_home_store_selected(driver, context)
    ok = bool(confirmed or (clicked_shop_this_store and reached_storefront))

    return {
        "attempted": True,
        "ok": ok,
        "message": "Aldi home store confirmed." if ok else "Aldi home store was not confirmed.",
        "clicked_location": clicked_location,
        "clicked_near_box": clicked_near_box,
        "typed_location": typed_location,
        "clicked_address_suggestion": clicked_address_suggestion,
        "clicked_save_address": clicked_save_address,
        "clicked_first_store_card": clicked_first_store_card,
        "clicked_store_card": clicked_store_card,
        "clicked_shop_this_store": clicked_shop_this_store,
        "reached_storefront": reached_storefront,
        "storefront_url": str(getattr(driver, "current_url", "") or ""),
        "clicked_continue": clicked_continue,
        "clicked_final": clicked_final,
        **context,
    }
