import json
import os
import sys
from datetime import datetime
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.product_selection_service import agent_stage
from PushShoppingList.services.product_selection_service import build_product_choice_record_from_results
from PushShoppingList.services.product_selection_service import build_product_search_url
from PushShoppingList.services.product_selection_service import clean_product_card_html
from PushShoppingList.services.product_selection_service import clean_text
from PushShoppingList.services.product_selection_service import clean_text_list
from PushShoppingList.services.product_selection_service import compact_product_value_for_storage
from PushShoppingList.services.product_selection_service import final_product_candidate_payload
from PushShoppingList.services.product_selection_service import find_nearest_store_location
from PushShoppingList.services.product_selection_service import finish_product_progress
from PushShoppingList.services.product_selection_service import first_present_value
from PushShoppingList.services.product_selection_service import first_store_localization
from PushShoppingList.services.product_selection_service import geocode_home_address
from PushShoppingList.services.product_selection_service import localized_inventory_blocking_failure
from PushShoppingList.services.product_selection_service import normalize_item_key
from PushShoppingList.services.product_selection_service import normalize_match_text
from PushShoppingList.services.product_selection_service import normalize_price
from PushShoppingList.services.product_selection_service import search_store_products_for_download
from PushShoppingList.services.product_selection_service import start_product_progress
from PushShoppingList.services.product_selection_service import unique_texts
from PushShoppingList.services.product_selection_service import update_product_progress_picks
from PushShoppingList.services.product_selection_service import update_product_progress_summary
from PushShoppingList.services.store_settings_service import load_store_settings


BASE_DIR = Path(__file__).resolve().parents[1] / "services"
TEST_GRAB_RESULTS_FILE = BASE_DIR / "recipe-extractor" / "data" / "test_grab_result.json"
TEST_GRAB_TARGET_STORE_KEY = "aldi"
TEST_GRAB_TARGET_STORE_NAME = "Aldi"
TEST_GRAB_TARGET_PRODUCT = "Edible grocery eggs"
TEST_GRAB_SEARCH_TERM = "eggs"


def test_grab_products(job_id=None):
    ingredient = TEST_GRAB_SEARCH_TERM
    home_address = load_home_address()
    full_address = home_address.get("full_address", "")
    store_settings = load_store_settings()
    stores = store_settings.get("stores", {})
    store = stores.get(TEST_GRAB_TARGET_STORE_KEY)

    if not store:
        result = test_grab_failure_payload(
            full_address,
            errors=[f"{TEST_GRAB_TARGET_STORE_NAME}: store is not configured."],
            job_id=job_id,
        )
        save_test_grab_result(result)
        return result

    stores = {TEST_GRAB_TARGET_STORE_KEY: store}
    search_url = build_product_search_url(store, TEST_GRAB_SEARCH_TERM)
    download = {
        "index": 0,
        "item_key": normalize_item_key(ingredient),
        "ingredient": ingredient,
        "search_term": TEST_GRAB_SEARCH_TERM,
        "store_key": TEST_GRAB_TARGET_STORE_KEY,
        "store_name": store.get("label") or TEST_GRAB_TARGET_STORE_NAME,
        "search_url": search_url,
        "quantity": "",
        "quantity_context": {},
        "state": "waiting",
        "message": "Queued isolated Test Grab.",
        "candidates_count": None,
        "test_grab": True,
    }

    if job_id:
        start_product_progress(
            [download],
            job_id=job_id,
            home_address=full_address,
            enabled_stores=[TEST_GRAB_TARGET_STORE_KEY],
            max_workers=1,
        )
        update_product_progress_summary(
            job_id,
            "Test Grab: resolving the nearest ALDI from the saved current Full Address.",
        )

    home_location = geocode_home_address(full_address)
    store_location = find_nearest_store_location(
        TEST_GRAB_TARGET_STORE_KEY,
        store,
        full_address,
        home_location,
    )
    store_locations = {TEST_GRAB_TARGET_STORE_KEY: store_location}
    store_resolution_stage = agent_stage(
        "Store Resolution Agent",
        message="Resolved nearest ALDI location for isolated Test Grab.",
        metadata={
            "home_address": full_address,
            "home_location": home_location,
            "store_location": store_location,
        },
    )

    if job_id:
        update_product_progress_summary(
            job_id,
            "Test Grab: loading localized ALDI inventory with Selenium and searching eggs.",
        )

    result = search_store_products_for_download(
        download,
        stores,
        full_address,
        home_location,
        store_locations,
        job_id=job_id,
        product_agent_prompt_builder=build_test_grab_eggs_aldi_prompt,
        browser_visible=test_grab_browser_visible(),
        browser_visual_pause_seconds=test_grab_visual_pause_seconds(),
        browser_visual_hold_seconds=test_grab_visual_hold_seconds(),
    )
    for candidate in result.get("candidates", []):
        candidate["test_grab"] = True
        candidate["allow_edible_egg_products"] = True
        candidate["ranking_reasons"] = unique_texts(
            candidate.get("ranking_reasons", [])
            + ["Isolated Test Grab accepts edible egg products as alternatives while ranking shell cartons first."]
        )

    record = build_product_choice_record_from_results(
        ingredient,
        [result],
        full_address,
        quantity_context={},
    )
    record["test_grab"] = True
    record["target_product"] = TEST_GRAB_TARGET_PRODUCT
    record["target_store"] = TEST_GRAB_TARGET_STORE_NAME
    record["agent_stages"] = [store_resolution_stage] + record.get("agent_stages", [])
    record = compact_product_value_for_storage(record)

    if job_id:
        update_product_progress_picks(job_id, ingredient, record)

    payload = build_test_grab_response_payload(
        record,
        result,
        full_address,
        home_location,
        store_location,
        job_id=job_id,
    )
    save_test_grab_result(payload)

    if job_id:
        finish_product_progress(
            job_id,
            ok=not payload.get("errors"),
            summary=(
                "Test Grab complete. ALDI eggs were ranked from verified localized inventory."
                if payload.get("best_product")
                else "Test Grab finished without a verified best product."
            ),
        )

    return payload


def test_grab_browser_visible():
    return env_truthy(os.getenv("TEST_GRAB_VISIBLE", ""))


def env_truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def test_grab_visual_pause_seconds():
    return bounded_env_float("TEST_GRAB_VISUAL_PAUSE_SECONDS", 1.25, 0, 10)


def test_grab_visual_hold_seconds():
    return bounded_env_float("TEST_GRAB_VISUAL_HOLD_SECONDS", 12, 0, 120)


def bounded_env_float(name, default, minimum, maximum):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def save_test_grab_result(payload):
    payload = payload if isinstance(payload, dict) else {}
    TEST_GRAB_RESULTS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def load_test_grab_result():
    if not TEST_GRAB_RESULTS_FILE.exists():
        return {}

    try:
        data = json.loads(TEST_GRAB_RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def test_grab_choice_from_result(payload=None):
    payload = payload if isinstance(payload, dict) else load_test_grab_result()
    record = first_test_grab_record(payload)
    candidates = record.get("candidates", []) if isinstance(record.get("candidates"), list) else []
    selected = record.get("selected_product") if isinstance(record.get("selected_product"), dict) else {}
    selected_id = record.get("selected_product_id") or selected.get("id", "")
    store_result = first_store_result(record)

    return {
        "test_grab": True,
        "item_key": record.get("item_key") or normalize_item_key(TEST_GRAB_SEARCH_TERM),
        "ingredient": record.get("ingredient") or TEST_GRAB_SEARCH_TERM,
        "filtered_store_key": TEST_GRAB_TARGET_STORE_KEY,
        "filtered_store_name": TEST_GRAB_TARGET_STORE_NAME,
        "store_result": store_result,
        "selected_product": selected,
        "selected_product_id": selected_id,
        "candidates": candidates,
        "valid_alternatives": [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("viable") is not False
        ],
        "rejected_products": [
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("viable") is False
        ],
        "skip_reasons": payload.get("errors", []),
        "result_path": str(TEST_GRAB_RESULTS_FILE),
    }


def select_test_grab_product(product_id):
    product_id = str(product_id or "").strip()
    payload = load_test_grab_result()
    record = first_test_grab_record(payload)

    if not payload or not record:
        return {
            "ok": False,
            "error": "No Test Grab result is available yet.",
        }

    candidates = record.get("candidates", []) if isinstance(record.get("candidates"), list) else []
    selected = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("id") == product_id
        ),
        None,
    )

    if not selected:
        return {
            "ok": False,
            "error": "That Test Grab product was not found.",
        }

    if selected.get("viable") is False:
        return {
            "ok": False,
            "error": "That Test Grab product is rejected and cannot be selected.",
        }

    selected_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    selected["selected_by_user"] = True
    selected["selected_at"] = selected_at
    selected["reason_selected"] = selected.get("reason_selected") or "Selected manually from Test Grab alternatives."

    record["selected_product_id"] = product_id
    record["selected_product"] = selected
    record["manual_override"] = True
    record["selected_by_user"] = True
    record["selected_at"] = selected_at
    record["updated_at"] = selected_at
    update_test_grab_store_result(record, selected)

    payload["best_product"] = final_product_candidate_payload(selected)
    payload["selected_count"] = 1
    payload["selected_by_user"] = True
    payload["selected_at"] = selected_at
    payload["alternatives"] = [
        final_product_candidate_payload(candidate)
        for candidate in candidates
        if isinstance(candidate, dict)
        and candidate.get("viable") is not False
        and candidate.get("id") != product_id
    ]
    payload["results"] = [record]
    save_test_grab_result(payload)

    return {
        "ok": True,
        "choice": test_grab_choice_from_result(payload),
        "result": payload,
    }


def first_test_grab_record(payload):
    results = payload.get("results", []) if isinstance(payload, dict) else []
    for record in results if isinstance(results, list) else []:
        if isinstance(record, dict):
            return record
    return {}


def update_test_grab_store_result(record, selected):
    store_result = first_store_result(record)
    if not store_result:
        return

    store_result["best_product_id"] = selected.get("id", "")
    store_result["best_product"] = selected
    store_result["best_product_match"] = selected.get("product_name", "")
    store_result["price"] = selected.get("price", "")
    store_result["size"] = selected.get("size") or selected.get("package_size", "")
    store_result["unit_price"] = selected.get("unit_price", "")
    store_result["product_url"] = selected.get("product_url", "")
    store_result["image_url"] = selected.get("image_url", "")
    store_result["reason_selected"] = selected.get("reason_selected", "")
    store_result["reason_skipped"] = ""
    store_result["skip_reason"] = ""
    store_result["selected_by_user"] = True
    store_result["selected_at"] = selected.get("selected_at", "")


def test_grab_failure_payload(full_address, errors=None, job_id=None):
    if job_id:
        start_product_progress(
            [],
            job_id=job_id,
            home_address=full_address,
            enabled_stores=[TEST_GRAB_TARGET_STORE_KEY],
            max_workers=1,
        )
        finish_product_progress(job_id, ok=False, summary=(errors or ["Test Grab failed."])[0])

    return {
        "ok": False,
        "test_grab": True,
        "job_id": job_id,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "home_address": full_address,
        "target_product": TEST_GRAB_TARGET_PRODUCT,
        "target_store": TEST_GRAB_TARGET_STORE_NAME,
        "searched_store": {},
        "best_product": {},
        "best_value_pick": {},
        "best_premium_pick": {},
        "alternatives": [],
        "rejected_products": [],
        "errors": clean_text_list(errors),
        "results": [],
        "count": 0,
        "selected_count": 0,
        "download_count": 0,
        "max_workers": 1,
        "result_path": str(TEST_GRAB_RESULTS_FILE),
    }


def build_test_grab_response_payload(record, raw_result, full_address, home_location, store_location, job_id=None):
    record = record if isinstance(record, dict) else {}
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    candidates = record.get("candidates", []) if isinstance(record.get("candidates"), list) else []
    valid_products = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("viable") is not False
    ]
    rejected_products = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("viable") is False
    ]
    selected = record.get("selected_product") if isinstance(record.get("selected_product"), dict) else {}
    selected_id = selected.get("id", "") if selected else ""
    best_value = best_value_egg_pick(valid_products)
    best_premium = best_premium_egg_pick(valid_products)
    alternatives = [
        candidate
        for candidate in valid_products
        if candidate.get("id") != selected_id
    ]
    store_result = first_store_result(record)
    localization = store_result.get("store_localization") or first_store_localization(candidates)
    searched_store = test_grab_searched_store_payload(
        store_result,
        localization,
        store_location,
    )
    errors = clean_text_list(
        raw_result.get("skip_reasons", [])
        + record.get("skip_reasons", [])
        + (localization.get("errors", []) if isinstance(localization, dict) else [])
    )
    errors = [] if selected and searched_store.get("proof_of_store_selection") else errors

    payload = {
        "ok": bool(selected and searched_store.get("proof_of_store_selection") and not localized_inventory_blocking_failure(errors)),
        "test_grab": True,
        "job_id": job_id,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "home_address": full_address,
        "home_location": home_location,
        "target_product": TEST_GRAB_TARGET_PRODUCT,
        "search_item": TEST_GRAB_SEARCH_TERM,
        "target_store": TEST_GRAB_TARGET_STORE_NAME,
        "searched_store": searched_store,
        "best_product": final_product_candidate_payload(selected) if selected else {},
        "best_value_pick": final_product_candidate_payload(best_value) if best_value else {},
        "best_premium_pick": final_product_candidate_payload(best_premium) if best_premium else {},
        "alternatives": [final_product_candidate_payload(candidate) for candidate in alternatives],
        "rejected_products": [final_product_candidate_payload(candidate) for candidate in rejected_products],
        "errors": errors,
        "results": [record],
        "count": 1,
        "selected_count": 1 if selected else 0,
        "download_count": 1,
        "max_workers": 1,
        "result_path": str(TEST_GRAB_RESULTS_FILE),
    }
    if not payload["ok"] and not payload["errors"]:
        payload["errors"] = ["Test Grab did not produce a verified localized best product."]
    return payload


def first_store_result(record):
    store_results = record.get("store_results_list", []) if isinstance(record, dict) else []
    for store_result in store_results if isinstance(store_results, list) else []:
        if isinstance(store_result, dict):
            return store_result
    return {}


def test_grab_searched_store_payload(store_result, localization, store_location):
    store_result = store_result if isinstance(store_result, dict) else {}
    localization = localization if isinstance(localization, dict) else {}
    store_location = store_location if isinstance(store_location, dict) else {}
    return {
        "store_name": (
            localization.get("store_name")
            or store_result.get("store_name")
            or store_location.get("name")
            or TEST_GRAB_TARGET_STORE_NAME
        ),
        "store_address": (
            localization.get("store_address")
            or store_result.get("store_location_address")
            or store_location.get("address", "")
        ),
        "distance_miles": (
            localization.get("distance_miles")
            if localization.get("distance_miles") is not None
            else store_result.get("store_location_distance_miles", store_location.get("distance_miles"))
        ),
        "store_id": localization.get("store_id", ""),
        "pickup_supported": first_present_value(
            localization.get("pickup_supported"),
            store_location.get("pickup_enabled"),
            True,
        ),
        "proof_of_store_selection": localization.get("proof_of_store_selection", []),
    }


def best_value_egg_pick(candidates):
    candidates = [candidate for candidate in candidates or [] if isinstance(candidate, dict)]
    priced = [
        candidate
        for candidate in candidates
        if isinstance(candidate.get("price_per_egg_value"), (int, float))
    ]
    if priced:
        return min(priced, key=lambda candidate: candidate.get("price_per_egg_value"))

    unit_priced = [
        candidate
        for candidate in candidates
        if isinstance(candidate.get("unit_price_value"), (int, float))
    ]
    if unit_priced:
        return min(unit_priced, key=lambda candidate: candidate.get("unit_price_value"))

    return candidates[0] if candidates else {}


def best_premium_egg_pick(candidates):
    premium_terms = {
        "organic",
        "cage free",
        "free range",
        "pasture",
        "pasture raised",
        "brown",
        "large",
        "extra large",
    }
    premium = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        text = normalize_match_text(" ".join([
            candidate.get("product_name", ""),
            candidate.get("brand", ""),
            candidate.get("product_category", ""),
            candidate.get("card_text_excerpt", ""),
        ]))
        if any(term in text for term in premium_terms):
            premium.append(candidate)

    if premium:
        return max(premium, key=lambda candidate: candidate.get("score", 0))

    return candidates[0] if candidates else {}


def build_test_grab_eggs_aldi_prompt(
    ingredient,
    store_name,
    full_address,
    store_location,
    rendered_page,
    visible_cards,
):
    store_location = store_location or {}
    rendered_page = rendered_page or {}
    localization = rendered_page.get("localization", {}) if isinstance(rendered_page.get("localization"), dict) else {}
    product_blocks = [
        {
            "product_index": index,
            "name_hint": clean_text(card.get("name")) if isinstance(card, dict) else "",
            "price_hint": normalize_price(card.get("price")) if isinstance(card, dict) else "",
            "product_url_hint": clean_text(card.get("product_url")) if isinstance(card, dict) else "",
            "image_url_hint": clean_text(card.get("image_url")) if isinstance(card, dict) else "",
            "text": clean_text(card.get("text"))[:1400] if isinstance(card, dict) else "",
            "html": clean_product_card_html((card or {}).get("raw_product_html_snippet") if isinstance(card, dict) else ""),
        }
        for index, card in enumerate(visible_cards or [], start=1)
        if isinstance(card, dict)
    ]

    return f"""
You are a grocery product collection and product ranking agent.

You specialize in:
- localized grocery inventory searches
- nearest grocery store resolution
- edible food filtering
- grocery product ranking
- live localized inventory extraction
- product alternative analysis

The generic browser automation layer has already opened the grocery website, selected/attempted the nearest store, fully rendered the page, scrolled lazy-loaded content, cleaned the DOM, and extracted product-card blocks. You must reason only from the supplied rendered content.

CORE BEHAVIOR RULES:
- You MUST search ONLY localized grocery inventory.
- You MUST verify the active store session BEFORE scraping.
- You MUST use the user's exact address as the home point.
- You MUST prioritize nearby stores.
- You MUST return ONLY edible grocery products.
- You MUST rank products using value and quality rules.
- You MUST NEVER use generic national catalog results.
- You MUST NEVER hallucinate inventory.
- You MUST NEVER use cached/unverified product pages.
- You MUST NEVER use default/unlocalized store sessions.
- You MUST NEVER include decorative/non-food products.
- You MUST NEVER claim a store was searched unless localization is verified.
- If localized inventory cannot be verified: STOP and report failure.
- Do not browse, fetch, or infer from outside websites.

USER LOCATION:
{full_address}

TARGET PRODUCT:
Edible grocery eggs

STORE WORKFLOW:
1. Detect the nearest ALDI store to the home address.
2. Open the store selector flow.
3. Select the nearest valid store.
4. Verify the localized store session is active.
5. Confirm store name, full address, store ID if visible, distance from home, and pickup/delivery support if visible.
6. ONLY AFTER localization: search for "eggs".

VERIFIED STORE INFO FROM BROWSER AUTOMATION:
{json.dumps({
    "verified": localization.get("verified"),
    "store_name": localization.get("store_name") or store_name,
    "store_address": localization.get("store_address") or store_location.get("address", ""),
    "distance_miles": localization.get("distance_miles", store_location.get("distance_miles")),
    "store_id": localization.get("store_id", ""),
    "pickup_supported": localization.get("pickup_supported", store_location.get("pickup_enabled")),
    "delivery_supported": localization.get("delivery_supported"),
    "proof_of_store_selection": localization.get("proof_of_store_selection", []),
    "errors": localization.get("errors", []),
}, ensure_ascii=False)}

Nearest ALDI metadata resolved from the exact home address:
{json.dumps(store_location, ensure_ascii=False)}

Rendered page metadata:
{json.dumps({
    "url": rendered_page.get("url", ""),
    "html_path": rendered_page.get("path", ""),
    "visible_text_path": rendered_page.get("visible_text_path", ""),
    "prompt_preview_path": rendered_page.get("prompt_preview_path", ""),
    "product_related_html_path": rendered_page.get("product_related_html_path", ""),
    "html_length": rendered_page.get("html_length", 0),
    "visible_text_length": rendered_page.get("visible_text_length", 0),
    "product_related_html_length": rendered_page.get("product_related_html_length", 0),
    "prompt_html_length": rendered_page.get("prompt_html_length", 0),
}, ensure_ascii=False)}

LOCALIZATION VERIFICATION REQUIREMENTS:
- You MUST provide proof the store session was active BEFORE scraping.
- Valid proof includes selected store banner text, active pickup location, localized inventory indicator, store address shown on page, session/store ID, store selector confirmation, or pickup/delivery availability tied to that location.
- If proof_of_store_selection is empty or verified is false, DO NOT continue. Return empty product objects/arrays and include a failure in errors.

ONLY INCLUDE EDIBLE RESULTS:
ONLY include edible grocery egg products such as chicken eggs, duck eggs, quail eggs, brown eggs, white eggs, cage free eggs, free range eggs, pasture raised eggs, organic eggs, grocery egg cartons, liquid eggs, egg whites, packaged hard boiled eggs, and refrigerated edible egg products.

STRICTLY EXCLUDE Easter eggs, chocolate eggs, candy eggs, decorative eggs, plastic eggs, ceramic eggs, toy eggs, beauty products, slime eggs, pet toys, surprise eggs, bath bombs, seasonal novelty items, and non-food products. If a result is not edible food, reject it.

FOR EVERY PRODUCT FOUND, EXTRACT WHEN VISIBLE:
- store name
- selected store address
- product name
- brand
- egg type
- package count
- package size
- price
- price per egg if available
- stock status
- pickup availability if visible
- product URL
- image URL
- product ID/SKU if visible

PRODUCT RANKING RULES:
1. Best value per egg.
2. In-stock products first.
3. Larger count/value packs preferred.
4. Cage free preferred over conventional when value difference is reasonable.
5. Organic preferred only when competitively priced.
6. Avoid overpriced specialty products unless clearly premium.
7. Prefer pickup-eligible products.
8. Prefer reputable grocery brands.

RETURN REQUIREMENTS:
Return verified store info, best overall product, best value pick, best premium pick, all other edible alternatives, and rejected products with rejection_reason.

Visible product blocks extracted generically:
{json.dumps(product_blocks, ensure_ascii=False)}

Cleaned rendered product HTML/content:
{rendered_page.get("prompt_html", "")}

Return clean structured JSON only:
{{
  "timestamp": "",
  "home_address": "{full_address}",
  "searched_store": {{
    "store_name": "",
    "store_address": "",
    "distance_miles": "",
    "store_id": "",
    "pickup_supported": true,
    "proof_of_store_selection": []
  }},
  "best_product": {{}},
  "best_value_pick": {{}},
  "best_premium_pick": {{}},
  "alternatives": [],
  "rejected_products": [],
  "errors": [],
  "results": [
    {{
      "product_index": 1,
      "ranking_status": "best|alternative|rejected",
      "rejection_reason": "",
      "confidence_score": 0,
      "reason": "",
      "product_name": "",
      "brand": "",
      "product_category": "",
      "egg_type": "",
      "package_count": "",
      "size": "",
      "price": "",
      "price_per_egg": "",
      "unit_price": "",
      "stock_status": "",
      "in_stock": true,
      "pickup_available": true,
      "product_url": "",
      "image_url": "",
      "product_id": ""
    }}
  ]
}}
"""


def main():
    result = test_grab_products(job_id=os.getenv("TEST_GRAB_JOB_ID") or None)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
