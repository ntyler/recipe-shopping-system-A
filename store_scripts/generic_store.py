from __future__ import annotations

import time
from typing import Any


def update_home_store(driver, context: dict[str, Any], helpers: dict[str, Any], worker_id: int = 0, wait_seconds: float = 4.0) -> dict[str, Any]:
    """Generic store-location flow used by non-customized stores."""
    accept_cookies_if_present = helpers["accept_cookies_if_present"]
    page_contains_any = helpers["page_contains_any"]
    click_visible_xpath = helpers["click_visible_xpath"]
    common_location_xpaths = helpers["common_location_xpaths"]
    type_visible_location_input = helpers["type_visible_location_input"]
    click_store_card_that_matches_context = helpers["click_store_card_that_matches_context"]
    click_continue_shopping = helpers["click_continue_shopping"]
    final_home_store_xpaths = helpers["final_home_store_xpaths"]
    correct_home_store_selected = helpers["correct_home_store_selected"]

    accept_cookies_if_present(driver, wait=0.75)

    already_visible = page_contains_any(
        driver,
        [
            context.get("selected_name"),
            context.get("exact_address"),
            context.get("pickup_zip"),
            context.get("store_number"),
        ],
    )

    clicked_location = click_visible_xpath(driver, common_location_xpaths(), wait=wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    typed_location = type_visible_location_input(driver, context.get("search_values", []), wait=wait_seconds)
    accept_cookies_if_present(driver, wait=0.75)

    clicked_store_card = click_store_card_that_matches_context(
        driver=driver,
        context=context,
        wait=wait_seconds,
    )

    clicked_continue = click_continue_shopping(driver, wait=wait_seconds)

    clicked_final = False
    if not clicked_continue:
        clicked_final = click_visible_xpath(driver, final_home_store_xpaths(context), wait=wait_seconds)

    time.sleep(wait_seconds)
    confirmed = correct_home_store_selected(driver, context)
    ok = bool(confirmed)

    if not ok:
        print(f"[Worker {worker_id}] ⚠️ {context.get('store_key')}: correct address was NOT confirmed")

    return {
        "attempted": True,
        "ok": ok,
        "message": "Home store confirmed." if ok else "Could not confirm home store, but continuing ingredient search in same browser.",
        "already_visible": already_visible,
        "clicked_location": clicked_location,
        "typed_location": typed_location,
        "clicked_store_card": clicked_store_card,
        "clicked_continue": clicked_continue,
        "clicked_final": clicked_final,
        **context,
    }
