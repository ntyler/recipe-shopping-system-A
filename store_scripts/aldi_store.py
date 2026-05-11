from __future__ import annotations

import time
from typing import Any


def get_start_url(context: dict[str, Any]) -> str:
    return (
        context.get("urlStoreSelector")
        or context.get("website")
        or context.get("base_url")
        or "https://www.aldi.us/store/aldi/s?k="
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

    print(f"[Worker {worker_id}] 🌐 Aldi opening: {start_url}")
    driver.get(start_url)
    time.sleep(wait_seconds)

    print(f"[Worker {worker_id}] 🛒 Aldi: clicking current store box")

    clicked_top_store = click_visible_xpath(
        driver,
        [
            "//*[contains(text(), 'Shopping at ALDI')]",
            "//*[contains(text(), 'Delivery')]",
            "//*[contains(text(), 'Pickup')]",
            "//button[contains(., 'Shopping at ALDI')]",
            "//button[contains(., 'Delivery')]",
        ],
        wait=wait_seconds,
    )

    print(f"[Worker {worker_id}] Aldi current store box clicked: {clicked_top_store}")
    time.sleep(2)

    print(f"[Worker {worker_id}] 🛒 Aldi: clicking In-Store Change store")

    clicked_change_store = click_visible_xpath(
        driver,
        [
            "(//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'change store')])[last()]",
        ],
        wait=wait_seconds,
    )

    print(f"[Worker {worker_id}] Aldi In-Store Change store clicked: {clicked_change_store}")

    if not clicked_change_store:
        raise RuntimeError("Aldi Change store button was not clicked. Cannot enter address yet.")

    time.sleep(2)

    return True


def click_aldi_near_button(
    driver,
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    click_visible_xpath = helpers["click_visible_xpath"]

    print(f"[Worker {worker_id}] 🛒 Aldi: clicking Near location button")

    clicked_near_box = click_visible_xpath(
        driver,
        [
            "//button[contains(., 'Near')]",
            "//button[contains(., '60602')]",
            "//button[@aria-haspopup='dialog' and contains(., 'Near')]",
            "//button[@type='button' and contains(., 'Near')]",
        ],
        wait=wait_seconds,
    )

    print(f"[Worker {worker_id}] Aldi Near location button clicked: {clicked_near_box}")

    if not clicked_near_box:
        raise RuntimeError("Aldi Near location button was not clicked.")

    time.sleep(2)

    return True


def click_aldi_shop_this_store(
    driver,
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> bool:
    click_visible_xpath = helpers["click_visible_xpath"]

    print(f"[Worker {worker_id}] 🛒 Aldi: clicking Shop this store if visible")

    clicked_shop = click_visible_xpath(
        driver,
        [
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'shop this store')]",
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'shop this store')]",
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'select store')]",
            "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'set as my store')]",
        ],
        wait=wait_seconds,
    )

    print(f"[Worker {worker_id}] Aldi Shop this store clicked: {clicked_shop}")
    time.sleep(2)

    return bool(clicked_shop)


def update_home_store(
    driver,
    context: dict[str, Any],
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    accept_cookies_if_present = helpers["accept_cookies_if_present"]
    type_visible_location_input = helpers["type_visible_location_input"]
    click_store_card_that_matches_context = helpers["click_store_card_that_matches_context"]
    click_continue_shopping = helpers["click_continue_shopping"]
    click_visible_xpath = helpers["click_visible_xpath"]
    final_home_store_xpaths = helpers["final_home_store_xpaths"]
    correct_home_store_selected = helpers["correct_home_store_selected"]

    clicked_location = False
    clicked_near_box = False
    typed_location = False
    clicked_store_card = False
    clicked_shop_this_store = False
    clicked_continue = False
    clicked_final = False

    accept_cookies_if_present(driver, wait=0.75)

    clicked_location = open_aldi_store_selector_page(
        driver=driver,
        context=context,
        helpers=helpers,
        worker_id=worker_id,
        wait_seconds=wait_seconds,
    )

    accept_cookies_if_present(driver, wait=0.75)

    clicked_near_box = click_aldi_near_button(
        driver=driver,
        helpers=helpers,
        worker_id=worker_id,
        wait_seconds=wait_seconds,
    )

    print(f"[Worker {worker_id}] 🛒 Aldi: entering home address/ZIP")

    typed_location = type_visible_location_input(
        driver,
        context.get("search_values", []),
        wait=wait_seconds,
    )

    time.sleep(3)

    print(f"[Worker {worker_id}] 🔄 Aldi: refreshing after address entry")
    driver.refresh()
    time.sleep(wait_seconds)

    accept_cookies_if_present(driver, wait=0.75)

    print(f"[Worker {worker_id}] 🛒 Aldi: selecting closest in-store location after refresh")

    clicked_store_card = click_store_card_that_matches_context(
        driver=driver,
        context=context,
        wait=wait_seconds,
    )

    time.sleep(3)
    accept_cookies_if_present(driver, wait=0.75)

    print(f"[Worker {worker_id}] 🛒 Aldi: selecting closest saved store")

    clicked_store_card = click_store_card_that_matches_context(
        driver=driver,
        context=context,
        wait=wait_seconds,
    )

    time.sleep(2)

    clicked_shop_this_store = click_aldi_shop_this_store(
        driver=driver,
        helpers=helpers,
        worker_id=worker_id,
        wait_seconds=wait_seconds,
    )

    clicked_continue = click_continue_shopping(driver, wait=wait_seconds)

    if not clicked_continue:
        clicked_final = click_visible_xpath(
            driver,
            final_home_store_xpaths(context),
            wait=wait_seconds,
        )

    time.sleep(wait_seconds)

    confirmed = correct_home_store_selected(driver, context)

    return {
        "attempted": True,
        "ok": bool(confirmed),
        "message": (
            "Aldi home store confirmed."
            if confirmed
            else "Aldi home store was not confirmed. Retrying if attempts remain."
        ),
        "clicked_location": clicked_location,
        "clicked_near_box": clicked_near_box,
        "typed_location": typed_location,
        "clicked_store_card": clicked_store_card,
        "clicked_shop_this_store": clicked_shop_this_store,
        "clicked_continue": clicked_continue,
        "clicked_final": clicked_final,
        **context,
    }
