from __future__ import annotations

import time
from typing import Any


def get_start_url(context: dict[str, Any]) -> str:
    return (
        context.get("urlStoreSelector")
        or context.get("website")
        or context.get("base_url")
        or "https://www.meijer.com/"
    )


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

    clicked_location = False
    typed_location = False
    clicked_store_card = False
    clicked_continue = False
    clicked_final = False

    start_url = get_start_url(context)

    print(f"[Worker {worker_id}] 🌐 Meijer opening: {start_url}")
    driver.get(start_url)
    time.sleep(wait_seconds)

    accept_cookies_if_present(driver, wait=0.75)

    print(f"[Worker {worker_id}] 🛒 Meijer: opening store/location selector")
    clicked_location = click_visible_xpath(
        driver,
        common_location_xpaths(),
        wait=wait_seconds,
    )

    accept_cookies_if_present(driver, wait=0.75)

    print(f"[Worker {worker_id}] 🛒 Meijer: entering home ZIP/address")
    typed_location = type_visible_location_input(
        driver,
        context.get("search_values", []),
        wait=wait_seconds,
    )

    accept_cookies_if_present(driver, wait=0.75)
    time.sleep(1)

    print(f"[Worker {worker_id}] 🛒 Meijer: clicking matching saved store card/radio")
    clicked_store_card = click_store_card_that_matches_context(
        driver=driver,
        context=context,
        wait=wait_seconds,
    )

    print(f"[Worker {worker_id}] 🛒 Meijer: clicking Continue shopping")
    clicked_continue = click_continue_shopping(
        driver,
        wait=wait_seconds,
    )

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
            "Meijer home store confirmed."
            if confirmed
            else "Meijer home store was not confirmed. Retrying if attempts remain."
        ),
        "clicked_location": clicked_location,
        "typed_location": typed_location,
        "clicked_store_card": clicked_store_card,
        "clicked_continue": clicked_continue,
        "clicked_final": clicked_final,
        **context,
    }
