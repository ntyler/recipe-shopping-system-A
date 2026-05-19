import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import quote_plus
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.item_state_service import save_item_store
from PushShoppingList.services.rules_display_service import load_rules_display
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.store_settings_service import load_store_settings


BASE_DIR = Path(__file__).resolve().parent
PRODUCT_CHOICES_FILE = BASE_DIR / "recipe-extractor" / "data" / "product_choices.json"
PRODUCT_PROGRESS_FILE = BASE_DIR / "recipe-extractor" / "data" / "product_progress.json"
PRODUCT_CHOICES_FILE.parent.mkdir(parents=True, exist_ok=True)

REQUEST_HEADERS = {
    "User-Agent": "PushShoppingList/1.0 local product finder",
    "Accept-Language": "en-US,en;q=0.9",
}
PRICE_PATTERN = re.compile(r"\$\s*\d+(?:,\d{3})*(?:\.\d{2})?")
PRODUCT_PROGRESS_LOCK = threading.RLock()
PRODUCT_FINAL_STATES = {"done", "failed", "skipped", "cancelled"}
PRODUCT_BROWSER_FETCH_LOCK = threading.BoundedSemaphore(1)
PACKAGE_SIZE_PATTERN = re.compile(
    r"(?<![\w.])(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?))?\s*"
    r"(?:fl\s*oz|fluid\s*ounces?|ounces?|oz|pounds?|lbs?|lb|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
    r"count|ct|pack|pk|each|ea)\b",
    re.IGNORECASE,
)
UNIT_PRICE_PATTERN = re.compile(
    r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:/|per)\s*"
    r"(fl\s*oz|fluid\s*ounce|ounce|oz|pound|lb|gram|g|kg|count|ct|each|ea|piece|pc)\b",
    re.IGNORECASE,
)
INGREDIENT_ALTERNATIVE_PATTERN = re.compile(r"\s+(?:and\s*/\s*or|and/or|or)\s+", re.IGNORECASE)
GROCERY_QUERY_REPLACEMENTS = [
    (re.compile(r"\byoghurt\b", re.IGNORECASE), "yogurt"),
    (re.compile(r"\bself[-\s]+raising\b", re.IGNORECASE), "self rising"),
]
QUALIFIER_TOKENS = {
    "fat",
    "free",
    "light",
    "lite",
    "low",
    "lower",
    "reduced",
    "regular",
    "nonfat",
    "non",
    "unsalted",
    "salted",
    "whole",
    "skim",
    "sugar",
    "zero",
}
TOKEN_ALIASES = {
    "yoghurt": "yogurt",
}
DETAIL_REQUIRED = os.getenv("PRODUCT_REQUIRE_DETAIL_PAGE", "1") != "0"
BROWSER_SEARCH_MODE = os.getenv("PRODUCT_SEARCH_BROWSER_MODE", "always").strip().lower()
PRODUCT_ANALYSIS_MODEL = os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL", os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"))
PRODUCT_ANALYSIS_CLIENT = None
PRODUCT_AI_ANALYSIS_LOCK = threading.BoundedSemaphore(2)


def product_candidate_limit():
    try:
        configured = int(os.getenv("PRODUCT_CANDIDATE_LIMIT_PER_STORE", "48"))
    except (TypeError, ValueError):
        configured = 48

    return max(8, min(96, configured))


def product_browser_wait_seconds():
    try:
        configured = float(os.getenv("PRODUCT_BROWSER_WAIT_SECONDS", "14"))
    except (TypeError, ValueError):
        configured = 14

    return max(4, min(45, configured))


def product_search_browser_enabled():
    if os.getenv("DISABLE_BROWSER_PRODUCT_SEARCH") == "1":
        return False

    return BROWSER_SEARCH_MODE not in {"0", "off", "false", "disabled"}


def should_open_store_search_page(has_request_candidates):
    if not product_search_browser_enabled():
        return False

    if BROWSER_SEARCH_MODE in {"fallback", "if-needed", "if_needed"}:
        return not has_request_candidates

    return True


def product_worker_count(total_downloads=None):
    try:
        configured = int(os.getenv("PRODUCT_SEARCH_WORKERS", "6"))
    except (TypeError, ValueError):
        configured = 6

    configured = max(1, min(16, configured))

    if total_downloads:
        return max(1, min(configured, int(total_downloads)))

    return configured


def product_detail_limit():
    try:
        configured = int(os.getenv("PRODUCT_DETAIL_LIMIT_PER_STORE", "8"))
    except (TypeError, ValueError):
        configured = 8

    return max(1, min(16, configured))


def product_ai_analysis_limit():
    try:
        configured = int(os.getenv("PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE", "1"))
    except (TypeError, ValueError):
        configured = 1

    return max(0, min(4, configured))


def product_ai_html_chars():
    try:
        configured = int(os.getenv("PRODUCT_AI_HTML_CHARS", "45000"))
    except (TypeError, ValueError):
        configured = 45000

    return max(8000, min(100000, configured))


def product_ai_text_chars():
    try:
        configured = int(os.getenv("PRODUCT_AI_TEXT_CHARS", "20000"))
    except (TypeError, ValueError):
        configured = 20000

    return max(4000, min(50000, configured))


def product_ai_analysis_enabled():
    if os.getenv("DISABLE_PRODUCT_CHATGPT_ANALYSIS") == "1":
        return False

    return bool(os.getenv("OPENAI_API_KEY"))


def get_product_analysis_client():
    global PRODUCT_ANALYSIS_CLIENT

    if not product_ai_analysis_enabled():
        return None

    if PRODUCT_ANALYSIS_CLIENT is None:
        PRODUCT_ANALYSIS_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)

    return PRODUCT_ANALYSIS_CLIENT


def new_product_job_id():
    return uuid.uuid4().hex


def default_product_progress():
    return {
        "active": False,
        "job_id": None,
        "status": "idle",
        "summary": "No product search is running.",
        "home_address": "",
        "enabled_stores": [],
        "max_workers": product_worker_count(),
        "total": 0,
        "completed": 0,
        "percent": 0,
        "downloads": [],
        "updated_at": time.time(),
    }


def load_product_progress():
    with PRODUCT_PROGRESS_LOCK:
        if not PRODUCT_PROGRESS_FILE.exists():
            return default_product_progress()

        try:
            progress = json.loads(PRODUCT_PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return default_product_progress()

        if not isinstance(progress, dict):
            return default_product_progress()

        progress.setdefault("downloads", [])
        progress.setdefault("completed", completed_product_download_count(progress))
        progress.setdefault("percent", product_progress_percent(progress.get("completed", 0), progress.get("total", 0)))
        return progress


def save_product_progress(progress):
    with PRODUCT_PROGRESS_LOCK:
        progress = progress if isinstance(progress, dict) else default_product_progress()
        progress["updated_at"] = time.time()
        progress["completed"] = completed_product_download_count(progress)
        if progress.get("total"):
            progress["percent"] = product_progress_percent(progress.get("completed", 0), progress.get("total", 0))
        else:
            progress["percent"] = 100 if progress.get("status") in {"complete", "failed"} else 0
        PRODUCT_PROGRESS_FILE.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return progress


def start_product_progress(downloads, job_id=None, home_address="", enabled_stores=None, max_workers=None):
    with PRODUCT_PROGRESS_LOCK:
        job_id = job_id or new_product_job_id()
        downloads = [dict(item) for item in downloads]
        progress = {
            "active": bool(downloads),
            "job_id": job_id,
            "status": "running" if downloads else "complete",
            "summary": "Preparing product downloads." if downloads else "No product downloads were needed.",
            "home_address": home_address or "",
            "enabled_stores": enabled_stores or [],
            "max_workers": max_workers or product_worker_count(len(downloads)),
            "total": len(downloads),
            "completed": 0,
            "percent": 3 if downloads else 100,
            "downloads": downloads,
        }
        return save_product_progress(progress)


def update_product_progress_summary(job_id, summary, status=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        progress["active"] = True
        progress["status"] = status or progress.get("status") or "running"
        progress["summary"] = summary
        return save_product_progress(progress)


def mark_product_download(job_id, index, state, message, candidates_count=None, selected_name=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        downloads = progress.setdefault("downloads", [])
        if 0 <= index < len(downloads):
            item = downloads[index]
            item["state"] = state
            item["message"] = message
            item["updated_at"] = time.time()

            if state == "running" and not item.get("started_at"):
                item["started_at"] = time.time()

            if state in PRODUCT_FINAL_STATES:
                item["finished_at"] = time.time()

            if candidates_count is not None:
                item["candidates_count"] = candidates_count

            if selected_name:
                item["selected_name"] = selected_name

        progress["active"] = state == "running" or any(
            item.get("state") in {"waiting", "running"}
            for item in downloads
        )
        progress["status"] = "running" if progress["active"] else progress.get("status", "running")
        return save_product_progress(progress)


def finish_product_progress(job_id, ok=True, summary=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        has_failed = any(
            item.get("state") == "failed"
            for item in progress.get("downloads", [])
        )
        ok = bool(ok) and not has_failed

        progress["active"] = False
        progress["status"] = "complete" if ok else "failed"
        progress["summary"] = summary or (
            "Product search complete. Refreshing shopping list..."
            if ok
            else "Product search finished with errors."
        )
        progress["percent"] = 100
        return save_product_progress(progress)


def completed_product_download_count(progress):
    return sum(
        1
        for item in progress.get("downloads", [])
        if item.get("state") in PRODUCT_FINAL_STATES
    )


def product_progress_percent(done_count, total):
    if not total:
        return 100 if done_count else 0

    return max(3, min(100, round((done_count / total) * 100)))


def load_product_choices():
    if not PRODUCT_CHOICES_FILE.exists():
        return {"items": {}}

    try:
        data = json.loads(PRODUCT_CHOICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}

    if not isinstance(data, dict):
        return {"items": {}}

    data.setdefault("items", {})
    return data


def save_product_choices(data):
    data = data if isinstance(data, dict) else {"items": {}}
    data.setdefault("items", {})
    PRODUCT_CHOICES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def clear_product_choices():
    return save_product_choices({"items": {}})


def product_choices_by_item():
    return load_product_choices().get("items", {})


def product_choice_for_item(item_key, store_key=None):
    choice = product_choices_by_item().get(normalize_item_key(item_key), {})

    if store_key and choice:
        return product_choice_for_store(choice, store_key)

    return choice


def product_choice_for_store(choice, store_key):
    store_key = str(store_key or "").strip()
    filtered = dict(choice)
    candidates = [
        candidate
        for candidate in choice.get("candidates", [])
        if candidate.get("store_key") == store_key
    ]
    store_result = find_store_result(choice, store_key)
    selected = (store_result or {}).get("best_product")
    if not selected and (choice.get("selected_product") or {}).get("store_key") == store_key:
        selected = choice.get("selected_product")

    filtered["filtered_store_key"] = store_key
    filtered["filtered_store_name"] = (store_result or {}).get("store_name", "") or (selected or {}).get("store_name", "")
    filtered["store_result"] = store_result or {}
    filtered["candidates"] = candidates
    filtered["selected_product"] = selected
    filtered["selected_product_id"] = (store_result or {}).get("best_product_id") or (selected or {}).get("id", "")
    filtered["skip_reasons"] = (
        [(store_result or {}).get("reason_skipped")]
        if (store_result or {}).get("reason_skipped")
        else filtered.get("skip_reasons", [])
    )
    return filtered


def find_store_result(choice, store_key):
    store_results = choice.get("store_results", {})
    if isinstance(store_results, dict) and store_key in store_results:
        return store_results.get(store_key)

    for result in choice.get("store_results_list", []):
        if result.get("store_key") == store_key:
            return result

    return None


def grab_best_products(items=None, job_id=None):
    shopping_items = items if items is not None else load_items()
    ingredients = [
        str(item or "").strip()
        for item in shopping_items
        if str(item or "").strip() and not is_section_header(item)
    ]
    store_settings = load_store_settings()
    stores = store_settings.get("stores", {})
    enabled_stores = [
        key
        for key in store_settings.get("enabled_stores", [])
        if key in stores
    ]
    home_address = load_home_address()
    full_address = home_address.get("full_address", "")
    downloads = build_product_download_plan(ingredients, enabled_stores, stores)
    max_workers = product_worker_count(len(downloads))

    if job_id:
        start_product_progress(
            downloads,
            job_id=job_id,
            home_address=full_address,
            enabled_stores=enabled_stores,
            max_workers=max_workers,
        )

    if not ingredients:
        if job_id:
            finish_product_progress(job_id, ok=True, summary="No ingredients were available to search.")

        return {
            "ok": True,
            "home_address": full_address,
            "home_location": None,
            "enabled_stores": enabled_stores,
            "download_count": 0,
            "max_workers": max_workers,
            "count": 0,
            "selected_count": 0,
            "results": [],
        }

    if job_id:
        update_product_progress_summary(job_id, "Finding the nearest enabled store locations from the saved Full Address.")

    home_location = geocode_home_address(full_address)
    store_locations = {
        store_key: find_nearest_store_location(
            store_key,
            stores[store_key],
            full_address,
            home_location,
        )
        for store_key in enabled_stores
    }
    store_results_by_ingredient = {
        ingredient: []
        for ingredient in ingredients
    }

    if downloads:
        if job_id:
            update_product_progress_summary(
                job_id,
                f"Downloading product search pages with up to {max_workers} searches running at once.",
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    search_store_products_for_download,
                    download,
                    stores,
                    full_address,
                    home_location,
                    store_locations,
                    job_id,
                ): download
                for download in downloads
            }

            for future in as_completed(futures):
                download = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    message = f"{download.get('store_name')}: product search failed: {exc}"
                    if job_id:
                        mark_product_download(
                            job_id,
                            download.get("index", 0),
                            "failed",
                            message,
                            candidates_count=0,
                        )
                    result = {
                        "index": download.get("index", 0),
                        "ingredient": download.get("ingredient", ""),
                        "store_key": download.get("store_key", ""),
                        "store_name": download.get("store_name", ""),
                        "search_url": download.get("search_url", ""),
                        "candidates": [],
                        "skip_reasons": [message],
                    }
                ingredient = result.get("ingredient", "")
                store_results_by_ingredient.setdefault(ingredient, []).append(result)
    elif job_id:
        update_product_progress_summary(job_id, "No enabled store search URLs are configured.")

    state = load_product_choices()
    item_records = state.setdefault("items", {})
    results = []

    for ingredient in ingredients:
        record = build_product_choice_record_from_results(
            ingredient,
            store_results_by_ingredient.get(ingredient, []),
            full_address,
        )
        item_records[record["item_key"]] = record
        selected = record.get("selected_product")

        if selected and selected.get("source") != "search-page-fallback":
            save_item_store(record["item_key"], selected.get("store_key") or "")

        results.append(record)

    save_product_choices(state)

    if job_id:
        finish_product_progress(
            job_id,
            ok=True,
            summary=f"Product search complete. Saved {sum(1 for item in results if item.get('selected_product'))} best product pick(s).",
        )

    return {
        "ok": True,
        "home_address": full_address,
        "home_location": home_location,
        "enabled_stores": enabled_stores,
        "download_count": len(downloads),
        "max_workers": max_workers,
        "count": len(results),
        "selected_count": sum(1 for item in results if item.get("selected_product")),
        "results": results,
    }


def build_product_download_plan(ingredients, enabled_stores, stores):
    downloads = []

    for ingredient in ingredients:
        for search_term in ingredient_search_terms(ingredient):
            for store_key in enabled_stores:
                store = stores.get(store_key, {})
                store_name = store.get("label") or store_key.title()
                search_url = build_product_search_url(store, search_term)
                downloads.append({
                    "index": len(downloads),
                    "ingredient": ingredient,
                    "search_term": search_term,
                    "store_key": store_key,
                    "store_name": store_name,
                    "search_url": search_url,
                    "state": "waiting",
                    "message": "Queued.",
                    "candidates_count": None,
                })

    return downloads


def search_store_products_for_download(
    download,
    stores,
    full_address,
    home_location,
    store_locations,
    job_id=None,
):
    index = download.get("index", 0)
    ingredient = download.get("ingredient", "")
    store_key = download.get("store_key", "")
    store = stores.get(store_key, {})
    store_name = download.get("store_name") or store.get("label") or store_key.title()
    search_url = download.get("search_url", "")
    search_term = download.get("search_term") or ingredient
    search_label = search_term if normalize_match_text(search_term) != normalize_match_text(ingredient) else ingredient

    if not search_url:
        message = f"{store_name}: no product search URL is configured."
        if job_id:
            mark_product_download(job_id, index, "skipped", message, candidates_count=0)
        return {
            "index": index,
            "ingredient": ingredient,
            "store_key": store_key,
            "store_name": store_name,
            "search_url": search_url,
            "store_location": store_locations.get(store_key, {}),
            "candidates": [],
            "skip_reasons": [message],
        }

    if job_id:
        mark_product_download(
            job_id,
            index,
            "running",
            f"Downloading {store_name} search results for {search_label}...",
        )

    try:
        candidates, skip_reasons = search_store_products(
            ingredient,
            store_key,
            store,
            full_address,
            home_location,
            store_locations.get(store_key, {}),
            search_term=search_term,
            search_url=search_url,
        )
    except Exception as exc:
        candidates = []
        skip_reasons = [f"{store_name}: product search failed: {exc}"]

    if candidates:
        candidates = prioritize_candidates_for_detail(ingredient, candidates)
        candidates = enrich_product_candidates_from_pages(
            candidates,
            ingredient,
            store_name,
            job_id=job_id,
            progress_index=index,
        )

    raw_direct_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
    )
    direct_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback" and candidate.get("detail_evaluated")
    )
    detail_failed_count = max(0, raw_direct_count - direct_count)
    failed = any("product search failed" in str(reason).lower() for reason in skip_reasons)

    if direct_count:
        state = "done"
        message = f"Opened and evaluated {direct_count} full product page(s) from {store_name}."
    elif detail_failed_count:
        state = "failed"
        message = f"Found {detail_failed_count} product link(s), but no full product page could be evaluated."
    elif failed:
        state = "failed"
        message = skip_reasons[0] if skip_reasons else f"{store_name}: product search failed."
    else:
        state = "done"
        message = skip_reasons[0] if skip_reasons else f"{store_name}: no product candidates were found."

    if job_id:
        mark_product_download(
            job_id,
            index,
            state,
            message,
            candidates_count=direct_count,
        )

    return {
        "index": index,
        "ingredient": ingredient,
        "store_key": store_key,
        "store_name": store_name,
        "search_url": search_url,
        "search_term": search_term,
        "store_location": store_locations.get(store_key, {}),
        "store_location_name": (store_locations.get(store_key, {}) or {}).get("name", ""),
        "store_location_address": (store_locations.get(store_key, {}) or {}).get("address", ""),
        "store_location_distance_miles": (store_locations.get(store_key, {}) or {}).get("distance_miles"),
        "candidates": candidates,
        "skip_reasons": skip_reasons,
    }


def build_product_choice_record_from_results(ingredient, store_results, full_address):
    candidates = []
    skip_reasons = []
    store_results = sorted(
        [
            result
            for result in store_results
            if isinstance(result, dict)
        ],
        key=lambda item: item.get("index", 0),
    )

    for result in store_results:
        candidates.extend(result.get("candidates", []))
        skip_reasons.extend(result.get("skip_reasons", []))

    candidates = rank_product_candidates(ingredient, candidates)
    store_product_results_list = build_store_product_results(
        ingredient,
        store_results,
        candidates,
    )
    store_product_results = {
        result.get("store_key"): result
        for result in store_product_results_list
        if result.get("store_key")
    }
    viable_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("viable")
    ]
    selected = viable_candidates[0] if viable_candidates else None

    if not selected and not skip_reasons:
        skip_reasons.append("No valid product candidates were found for the enabled stores.")

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    return {
        "item_key": normalize_item_key(ingredient),
        "ingredient": ingredient,
        "home_address": full_address,
        "selected_product_id": selected.get("id") if selected else "",
        "selected_product": selected,
        "manual_override": False,
        "store_results": store_product_results,
        "store_results_list": store_product_results_list,
        "candidates": candidates,
        "skip_reasons": unique_texts(skip_reasons),
        "updated_at": now,
    }


def build_store_product_results(ingredient, raw_store_results, ranked_candidates):
    records = []

    for raw in group_raw_store_results_by_store(raw_store_results):
        store_key = raw.get("store_key", "")
        store_name = raw.get("store_name") or store_key.title()
        raw_ids = {
            candidate.get("id")
            for candidate in raw.get("candidates", [])
            if candidate.get("id")
        }
        store_candidates = [
            candidate
            for candidate in ranked_candidates
            if (
                candidate.get("store_key") == store_key
                and (not raw_ids or candidate.get("id") in raw_ids)
            )
        ]
        viable_candidates = [
            candidate
            for candidate in store_candidates
            if candidate.get("viable")
        ]
        best = viable_candidates[0] if viable_candidates else None

        if best:
            best["reason_selected"] = product_selection_reason(best, store_name)
            best["selected_reason"] = best["reason_selected"]
            skip_reason = ""
        else:
            skip_reason = store_skip_reason(store_name, raw, store_candidates)

        record = {
            "store_key": store_key,
            "store_name": store_name,
            "ingredient": ingredient,
            "search_url": raw.get("search_url", ""),
            "search_urls": raw.get("search_urls", []),
            "search_terms": raw.get("search_terms", []),
            "store_location": raw.get("store_location", {}),
            "store_location_name": raw.get("store_location_name", ""),
            "store_location_address": raw.get("store_location_address", ""),
            "store_location_distance_miles": raw.get("store_location_distance_miles"),
            "best_product_id": best.get("id") if best else "",
            "best_product": best,
            "best_product_match": best.get("product_name") if best else "",
            "price": best.get("price") if best else "",
            "size": product_size(best) if best else "",
            "unit_price": best.get("unit_price", "") if best else "",
            "product_url": best.get("product_url", "") if best else "",
            "image_url": best.get("image_url", "") if best else "",
            "reason_selected": best.get("reason_selected", "") if best else "",
            "reason_skipped": skip_reason,
            "skip_reason": skip_reason,
            "candidate_count": len(store_candidates),
            "valid_candidate_count": len(viable_candidates),
            "alternative_products": store_candidates,
            "alternatives": store_candidates,
            "skip_reasons": unique_texts(raw.get("skip_reasons", [])),
        }
        records.append(record)

    return records


def group_raw_store_results_by_store(raw_store_results):
    grouped = {}
    order = []

    for raw in raw_store_results:
        if not isinstance(raw, dict):
            continue

        store_key = raw.get("store_key", "")
        key = store_key or f"__raw_{len(order)}"

        if key not in grouped:
            grouped[key] = {
                "index": raw.get("index", len(order)),
                "ingredient": raw.get("ingredient", ""),
                "store_key": store_key,
                "store_name": raw.get("store_name", ""),
                "search_url": raw.get("search_url", ""),
                "search_urls": [],
                "search_terms": [],
                "store_location": raw.get("store_location", {}),
                "store_location_name": raw.get("store_location_name", ""),
                "store_location_address": raw.get("store_location_address", ""),
                "store_location_distance_miles": raw.get("store_location_distance_miles"),
                "candidates": [],
                "skip_reasons": [],
            }
            order.append(key)

        record = grouped[key]
        record["index"] = min(record.get("index", raw.get("index", 0)), raw.get("index", record.get("index", 0)))
        record["candidates"].extend(raw.get("candidates", []))
        record["skip_reasons"] = unique_texts(record.get("skip_reasons", []) + raw.get("skip_reasons", []))

        if raw.get("search_url"):
            record["search_urls"] = unique_texts(record.get("search_urls", []) + [raw.get("search_url")])
            record["search_url"] = record.get("search_url") or raw.get("search_url", "")

        if raw.get("search_term"):
            record["search_terms"] = unique_texts(record.get("search_terms", []) + [raw.get("search_term")])

        for key_name in [
            "store_location",
            "store_location_name",
            "store_location_address",
            "store_location_distance_miles",
        ]:
            if not record.get(key_name) and raw.get(key_name):
                record[key_name] = raw.get(key_name)

    return sorted(grouped.values(), key=lambda item: item.get("index", 0))


def product_selection_reason(candidate, store_name=""):
    reasons = [
        reason
        for reason in candidate.get("ranking_reasons", [])
        if reason
    ][:4]

    if reasons:
        return "Selected as the best {store} match because {reasons}.".format(
            store=store_name or "store",
            reasons="; ".join(reasons),
        )

    return "Selected as the highest-ranked valid product match for this store."


def store_skip_reason(store_name, raw_result, candidates):
    reasons = []
    reasons.extend(raw_result.get("skip_reasons", []))

    for candidate in candidates:
        reasons.extend(candidate.get("skip_reasons", []))

    reason = unique_texts(reasons)
    if reason:
        text = reason[0]
    elif candidates:
        text = "Product cards were found, but none passed matching, availability, price, detail, or food-rule checks."
    else:
        text = "No visible product cards or direct product links were found."

    if text.lower().startswith((store_name or "").lower()):
        return text

    return f"{store_name}: {text}" if store_name else text


def product_size(candidate):
    if not candidate:
        return ""

    return candidate.get("size") or candidate.get("package_size") or ""


def build_product_choice_record(
    ingredient,
    enabled_stores,
    stores,
    full_address,
    home_location,
    store_locations,
):
    candidates = []
    skip_reasons = []

    for store_key in enabled_stores:
        store = stores.get(store_key, {})
        store_location = store_locations.get(store_key, {})
        store_candidates, store_skips = search_store_products(
            ingredient,
            store_key,
            store,
            full_address,
            home_location,
            store_location,
        )
        store_candidates = enrich_product_candidates_from_pages(
            store_candidates,
            ingredient,
            store.get("label") or store_key.title(),
        )
        candidates.extend(store_candidates)
        skip_reasons.extend(store_skips)

    return build_product_choice_record_from_results(
        ingredient,
        [{
            "candidates": candidates,
            "skip_reasons": skip_reasons,
        }],
        full_address,
    )


def prioritize_candidates_for_detail(ingredient, candidates):
    return sorted(
        candidates,
        key=lambda candidate: pre_detail_candidate_score(ingredient, candidate),
        reverse=True,
    )


def pre_detail_candidate_score(ingredient, candidate):
    name = candidate.get("product_name", "")
    text = " ".join([
        name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("card_text_excerpt", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    match_candidate = dict(candidate)
    match_candidate["description"] = text
    match = best_ingredient_candidate_match(ingredient, match_candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    text_tokens = set(tokenize(text))
    name_tokens = set(tokenize(name))
    normalized_ingredient = normalize_match_text(match.get("ingredient", ingredient))
    normalized_name = normalize_match_text(name)
    score = 0

    if normalized_ingredient and normalized_ingredient == normalized_name:
        score += 80
    elif normalized_ingredient and normalized_ingredient in normalized_name:
        score += 55

    score += len(ingredient_tokens & name_tokens) * 22
    score += len(ingredient_tokens & text_tokens) * 10

    if candidate.get("price"):
        score += 8
    if candidate.get("image_url"):
        score += 3
    if candidate_needs_product_detail(candidate):
        score += 5
    if "organic" in text.lower():
        score += 4

    return score


def enrich_product_candidates_from_pages(
    candidates,
    ingredient,
    store_name,
    job_id=None,
    progress_index=None,
):
    enriched = []
    detail_candidates = [
        candidate
        for candidate in candidates
        if candidate_needs_product_detail(candidate)
    ]
    limit = product_detail_limit()
    detail_ids = {
        candidate.get("id")
        for candidate in detail_candidates[:limit]
    }
    analysis_ids = {
        candidate.get("id")
        for candidate in detail_candidates[:product_ai_analysis_limit()]
    }
    total = min(len(detail_candidates), limit)
    evaluated = 0

    for candidate in candidates:
        if not candidate_needs_product_detail(candidate):
            enriched.append(mark_detail_skipped(candidate, "No direct product page URL was available."))
            continue

        if candidate.get("id") not in detail_ids:
            enriched.append(mark_detail_skipped(
                candidate,
                f"Full product page was not evaluated because the per-store detail limit is {limit}.",
            ))
            continue

        evaluated += 1
        use_chatgpt_analysis = candidate.get("id") in analysis_ids
        if job_id and progress_index is not None:
            action = (
                "Opening fully loaded page for ChatGPT analysis"
                if use_chatgpt_analysis
                else "Opening full product page"
            )
            mark_product_download(
                job_id,
                progress_index,
                "running",
                f"{action} from {store_name} {evaluated} of {total}: {candidate.get('product_name', ingredient)}",
            )

        enriched.append(enrich_product_candidate_from_page(
            candidate,
            ingredient,
            use_chatgpt_analysis=use_chatgpt_analysis,
        ))

    return enriched


def candidate_needs_product_detail(candidate):
    if candidate.get("source") == "search-page-fallback":
        return False

    product_url = str(candidate.get("product_url") or "").strip()
    search_url = str(candidate.get("search_url") or "").strip()

    return product_url.startswith(("http://", "https://")) and product_url != search_url


def mark_detail_skipped(candidate, reason):
    candidate["detail_evaluated"] = False
    candidate["detail_fetch"] = {
        "status": "skipped",
        "method": "",
        "url": candidate.get("product_url", ""),
        "reason": reason,
    }
    candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + [reason])
    return candidate


def enrich_product_candidate_from_page(candidate, ingredient, use_chatgpt_analysis=False):
    product_url = candidate.get("product_url", "")
    fetch = fetch_product_page_html(
        product_url,
        candidate.get("product_name", ""),
        candidate.get("home_address", ""),
        candidate.get("home_location"),
        prefer_browser=use_chatgpt_analysis,
    )

    candidate["detail_fetch"] = {
        key: value
        for key, value in fetch.items()
        if key != "html"
    }

    html_text = fetch.get("html") or ""
    if not html_text:
        candidate["detail_evaluated"] = False
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + [f"Full product page could not be evaluated: {fetch.get('error') or 'empty page content'}"]
        )
        return candidate

    details = extract_product_details_from_html(html_text, fetch.get("final_url") or product_url, candidate)
    apply_product_details_to_candidate(candidate, details, fetch, ingredient)

    if use_chatgpt_analysis:
        apply_chatgpt_product_page_analysis(candidate, html_text, ingredient)

    return candidate


def fetch_product_page_html(product_url, expected_name="", full_address="", home_location=None, prefer_browser=False):
    result = {
        "status": "failed",
        "method": "requests",
        "url": product_url,
        "final_url": product_url,
        "html": "",
        "error": "",
    }
    browser_result = {}

    if prefer_browser and os.getenv("DISABLE_BROWSER_PRODUCT_FETCH") != "1":
        browser_result = fetch_product_page_html_with_browser(
            product_url,
            expected_name,
            full_address=full_address,
            home_location=home_location,
        )
        if browser_result.get("html"):
            return browser_result

    try:
        response = requests.get(
            product_url,
            headers=REQUEST_HEADERS,
            timeout=(5, 12),
        )
        response.raise_for_status()
        result["final_url"] = response.url or product_url
        result["html"] = response.text or ""
        result["status"] = "done"
    except Exception as exc:
        result["error"] = str(exc)

    if (
        result.get("html")
        and product_page_html_looks_useful(result["html"], expected_name)
    ):
        result["text_length"] = len(BeautifulSoup(result["html"], "html.parser").get_text(" ", strip=True))
        return result

    if os.getenv("DISABLE_BROWSER_PRODUCT_FETCH") == "1":
        if not result.get("html"):
            return result

        result["status"] = "done"
        result["method"] = "requests"
        result["warning"] = (
            "Browser full-page fetch is disabled."
            if prefer_browser
            else "Page content looked sparse, and browser product fetch is disabled."
        )
        return result

    if not prefer_browser:
        browser_result = fetch_product_page_html_with_browser(
            product_url,
            expected_name,
            full_address=full_address,
            home_location=home_location,
        )
        if browser_result.get("html"):
            return browser_result

    if result.get("html"):
        result["status"] = "done"
        result["warning"] = browser_result.get("error") or "Browser fallback did not return page content."
        return result

    result["error"] = result.get("error") or browser_result.get("error") or "No page content was returned."
    return result


def fetch_product_page_html_with_browser(product_url, expected_name="", full_address="", home_location=None):
    result = {
        "status": "failed",
        "method": "browser",
        "url": product_url,
        "final_url": product_url,
        "html": "",
        "error": "",
    }

    with PRODUCT_BROWSER_FETCH_LOCK:
        driver = None
        try:
            from PushShoppingList.services.recipe_extract_service import create_headless_chrome_driver
            from PushShoppingList.services.recipe_extract_service import wait_for_browser_document

            driver = create_headless_chrome_driver(
                window_size="1365,1000",
                prefer_undetected=True,
                page_load_strategy="eager",
            )
            driver.set_page_load_timeout(product_browser_wait_seconds() + 8)
            configure_browser_home_location(driver, product_url, home_location)

            try:
                driver.get(product_url)
            except Exception:
                if len(driver.page_source or "") < 800:
                    raise

            wait_for_browser_document(driver, timeout_seconds=14)
            handle_browser_popups_and_location(driver, full_address)

            try:
                driver.execute_script(
                    """
                    window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.35));
                    setTimeout(() => window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.7)), 350);
                    setTimeout(() => window.scrollTo(0, 0), 700);
                    """
                )
                time.sleep(1.2)
            except Exception:
                pass

            html_text = driver.page_source or ""
            result["final_url"] = driver.current_url or product_url
            result["html"] = html_text
            result["status"] = "done" if html_text else "failed"
            result["text_length"] = len(BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True))

            if html_text and not product_page_html_looks_useful(html_text, expected_name):
                result["warning"] = "Browser-loaded page content looked sparse."
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    return result


def product_page_html_looks_useful(html_text, expected_name=""):
    soup = BeautifulSoup(html_text or "", "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))

    if len(page_text) < 300:
        return False

    lowered = page_text.lower()
    expected_tokens = set(tokenize(expected_name))
    matching_tokens = [
        token
        for token in expected_tokens
        if token in lowered
    ]

    if expected_tokens and len(matching_tokens) >= max(1, min(2, len(expected_tokens))):
        return True

    return any(term in lowered for term in ["price", "ingredients", "nutrition", "in stock", "pickup", "product"])


def extract_product_details_from_html(html_text, page_url, seed_candidate):
    soup = BeautifulSoup(html_text or "", "html.parser")
    mapping = best_product_mapping_for_candidate(soup, seed_candidate)
    visible_text = clean_text(soup.get_text(" ", strip=True))
    meta_description = meta_content(soup, "description", "og:description", "twitter:description")
    meta_title = meta_content(soup, "og:title", "twitter:title")
    title = clean_text(meta_title or (soup.title.get_text(" ", strip=True) if soup.title else ""))
    mapped_name = clean_text(
        mapping.get("name")
        or mapping.get("title")
        or mapping.get("productName")
        or mapping.get("product_name")
    ) if mapping else ""
    mapped_description = clean_text(
        mapping.get("description")
        or mapping.get("shortDescription")
        or mapping.get("longDescription")
    ) if mapping else ""
    brand = extract_brand_from_mapping(mapping) if mapping else ""
    price = extract_price_from_mapping(mapping) if mapping else ""
    image_url = extract_image_url_from_mapping(mapping) if mapping else ""
    canonical_url = canonical_product_url(soup, mapping, page_url)
    detail_text = clean_text(" ".join([
        mapped_name,
        title,
        brand,
        mapped_description,
        meta_description,
        visible_text[:2500],
    ]))
    ingredients_text = extract_ingredients_text(visible_text)
    package_size = extract_package_size(" ".join([mapped_name, title, visible_text[:1500]]))
    unit_price = extract_unit_price(" ".join([visible_text[:2500], mapped_description]))
    availability = extract_availability(mapping, visible_text)

    if not price:
        price_match = PRICE_PATTERN.search(visible_text)
        if price_match:
            price = price_match.group(0).replace(" ", "")

    return {
        "name": best_detail_name(mapped_name, title, seed_candidate.get("product_name", "")),
        "brand": brand,
        "description": mapped_description or meta_description,
        "ingredients_text": ingredients_text,
        "category": clean_text(mapping.get("category")) if mapping else "",
        "sku": clean_text(mapping.get("sku")) if mapping else "",
        "gtin": clean_text(
            mapping.get("gtin")
            or mapping.get("gtin12")
            or mapping.get("gtin13")
            or mapping.get("gtin14")
        ) if mapping else "",
        "price": price,
        "package_size": package_size,
        "size": package_size,
        "unit_price": unit_price.get("display", ""),
        "unit_price_value": unit_price.get("value"),
        "unit_price_unit": unit_price.get("unit", ""),
        "image_url": urljoin(page_url, image_url) if image_url else "",
        "availability": availability.get("text", ""),
        "in_stock": availability.get("in_stock"),
        "product_url": canonical_url,
        "detail_text_excerpt": detail_text[:2200],
        "is_organic": "organic" in detail_text.lower(),
    }


def apply_product_details_to_candidate(candidate, details, fetch, ingredient):
    candidate["detail_evaluated"] = True
    candidate["detail_source"] = fetch.get("method", "")

    for key in [
        "brand",
        "description",
        "ingredients_text",
        "category",
        "sku",
        "gtin",
        "size",
        "package_size",
        "unit_price",
        "unit_price_value",
        "unit_price_unit",
        "image_url",
        "availability",
        "in_stock",
        "detail_text_excerpt",
        "is_organic",
    ]:
        value = details.get(key)
        if value not in (None, ""):
            candidate[key] = value

    if details.get("name"):
        candidate["product_name"] = details["name"]

    if details.get("price"):
        candidate["price"] = details["price"]

    if details.get("product_url"):
        candidate["product_url"] = details["product_url"]

    if candidate.get("package_size") and not candidate.get("size"):
        candidate["size"] = candidate["package_size"]

    candidate["id"] = product_candidate_id(
        candidate.get("store_key"),
        candidate.get("product_url"),
        candidate.get("product_name"),
        candidate.get("price"),
    )
    candidate["ranking_reasons"] = unique_texts(
        candidate.get("ranking_reasons", [])
        + [f"Full product page evaluated with {fetch.get('method', 'requests')}."]
    )

    rule_text = " ".join([
        candidate.get("product_name", ""),
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
        "organic" if candidate.get("is_organic") else "",
    ])
    annotated = annotate_product_food_rules({
        "name": candidate.get("product_name", ""),
        "description": rule_text,
    })
    candidate["food_rule_status"] = annotated.get("food_rule_status", {})

    if not product_matches_ingredient(ingredient, candidate):
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + ["Full product page content did not confirm a strong ingredient match."]
        )


def apply_chatgpt_product_page_analysis(candidate, html_text, ingredient):
    analysis = analyze_product_page_with_chatgpt(candidate, html_text, ingredient)
    candidate["chatgpt_analysis"] = analysis

    if analysis.get("status") != "done":
        candidate["ranking_reasons"] = unique_texts(
            candidate.get("ranking_reasons", [])
            + [analysis.get("message") or "ChatGPT product page analysis was skipped."]
        )
        return candidate

    for key in [
        "brand",
        "description",
        "ingredients_text",
        "category",
        "size",
        "package_size",
        "unit_price",
        "image_url",
        "availability",
    ]:
        value = analysis.get(key)
        if value not in (None, ""):
            candidate[key] = value

    if analysis.get("product_name"):
        candidate["product_name"] = analysis["product_name"]

    if analysis.get("price"):
        candidate["price"] = analysis["price"]

    if analysis.get("unit_price_value") is not None:
        candidate["unit_price_value"] = analysis["unit_price_value"]

    if analysis.get("unit_price_unit"):
        candidate["unit_price_unit"] = analysis["unit_price_unit"]

    if analysis.get("in_stock") is not None:
        candidate["in_stock"] = analysis["in_stock"]

    if analysis.get("is_organic") is not None:
        candidate["is_organic"] = analysis["is_organic"]

    if candidate.get("package_size") and not candidate.get("size"):
        candidate["size"] = candidate["package_size"]

    candidate["chatgpt_confidence"] = analysis.get("confidence")
    candidate["chatgpt_ingredient_match_confidence"] = analysis.get("ingredient_match_confidence")
    candidate["chatgpt_food_rules_ok"] = analysis.get("food_rules_ok")
    candidate["chatgpt_is_correct_product"] = analysis.get("is_correct_product")
    candidate["ranking_reasons"] = unique_texts(
        candidate.get("ranking_reasons", [])
        + [analysis.get("reason") or "ChatGPT analyzed the fully loaded product page against the saved rules."]
    )

    missing_required = analysis.get("missing_required", [])
    blocked_by = analysis.get("blocked_by", [])
    food_rules_ok = analysis.get("food_rules_ok")

    if food_rules_ok is False and not missing_required and not blocked_by:
        missing_required = ["ChatGPT could not confirm the required food preferences."]

    if food_rules_ok is not None:
        candidate["food_rule_status"] = {
            "ok": bool(food_rules_ok) and not missing_required and not blocked_by,
            "needs_review": bool(missing_required or blocked_by or not food_rules_ok),
            "missing_required": missing_required,
            "blocked_by": blocked_by,
            "marker": food_rule_marker_text(missing_required, blocked_by),
        }

    if analysis.get("is_correct_product") is False:
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + ["ChatGPT analysis says the fully loaded product page does not match this shopping item."]
        )

    candidate["id"] = product_candidate_id(
        candidate.get("store_key"),
        candidate.get("product_url"),
        candidate.get("product_name"),
        candidate.get("price"),
    )
    return candidate


def analyze_product_page_with_chatgpt(candidate, html_text, ingredient):
    client = get_product_analysis_client()

    if not client:
        return {
            "status": "skipped",
            "message": "ChatGPT product analysis skipped because OPENAI_API_KEY is not set.",
        }

    page_payload = product_page_ai_payload(html_text)
    rules_payload = product_analysis_rules_payload()

    try:
        with PRODUCT_AI_ANALYSIS_LOCK:
            response = client.chat.completions.create(
                model=PRODUCT_ANALYSIS_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You analyze grocery product pages for a shopping-list app. "
                            "Use the user's saved rules strictly. Return only valid JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": build_product_page_analysis_prompt(
                            ingredient,
                            candidate,
                            rules_payload,
                            page_payload,
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"ChatGPT product analysis failed: {exc}",
        }

    analysis = normalize_chatgpt_product_analysis(data)
    analysis["status"] = "done"
    analysis["model"] = PRODUCT_ANALYSIS_MODEL
    analysis["html_chars_sent"] = len(page_payload.get("html", ""))
    analysis["visible_text_chars_sent"] = len(page_payload.get("visible_text", ""))
    analysis["html_truncated"] = page_payload.get("html_truncated", False)
    analysis["visible_text_truncated"] = page_payload.get("visible_text_truncated", False)
    return analysis


def product_page_ai_payload(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    visible_text = clean_text(soup.get_text(" ", strip=True))
    compact_html = re.sub(r"\s+", " ", str(soup)).strip()
    max_html = product_ai_html_chars()
    max_text = product_ai_text_chars()

    return {
        "visible_text": visible_text[:max_text],
        "visible_text_truncated": len(visible_text) > max_text,
        "html": compact_html[:max_html],
        "html_truncated": len(compact_html) > max_html,
    }


def product_analysis_rules_payload():
    try:
        food_rules = load_food_rules()
    except Exception:
        food_rules = {"require": [], "avoid": []}

    try:
        rules_display = load_rules_display()
        ranking_rules = rules_display.get("best_product_ranking", {}).get("rows", [])
    except Exception:
        ranking_rules = []

    return {
        "food_rules": food_rules,
        "best_product_ranking": ranking_rules,
    }


def build_product_page_analysis_prompt(ingredient, candidate, rules_payload, page_payload):
    extracted = {
        "store": candidate.get("store_name", ""),
        "candidate_name": candidate.get("product_name", ""),
        "candidate_price": candidate.get("price", ""),
        "candidate_size": product_size(candidate),
        "candidate_url": candidate.get("product_url", ""),
        "search_url": candidate.get("search_url", ""),
        "local_food_rule_status": candidate.get("food_rule_status", {}),
    }

    return f"""
Analyze this grocery product page for the shopping item:
{ingredient}

Candidate already extracted by the app:
{json.dumps(extracted, ensure_ascii=False)}

Saved food rules:
{json.dumps(rules_payload.get("food_rules", {}), ensure_ascii=False)}

Saved best-product ranking guidance:
{json.dumps(rules_payload.get("best_product_ranking", []), ensure_ascii=False)}

Rules for your analysis:
- Decide whether this is a specific purchasable grocery product that matches the shopping item. If the shopping item contains OR/and-or alternatives, matching any one alternative is acceptable.
- Apply required food rules strictly. If the fully loaded product page does not confirm a required trait, include that rule under missing_required.
- Apply avoid rules strictly. If the product page ingredients, title, labels, or description include an avoided term, include that rule under blocked_by.
- Do not call a product food_rules_ok if required rules are missing or avoid rules are present.
- Prefer evidence from product name, labels, ingredients, nutrition, availability, and price. Do not use unrelated recommendations, ads, or footer text.

Fully loaded product page visible text:
{page_payload.get("visible_text", "")}

Fully loaded product page HTML excerpt:
{page_payload.get("html", "")}

Return only JSON with this shape:
{{
  "is_product_page": true,
  "is_correct_product": true,
  "ingredient_match_confidence": 0.0,
  "food_rules_ok": true,
  "missing_required": [],
  "blocked_by": [],
  "product_name": "",
  "brand": "",
  "description": "",
  "ingredients_text": "",
  "category": "",
  "price": "",
  "size": "",
  "package_size": "",
  "unit_price": "",
  "unit_price_value": null,
  "unit_price_unit": "",
  "availability": "",
  "in_stock": null,
  "is_organic": null,
  "confidence": 0.0,
  "reason": "",
  "evidence": []
}}
"""


def normalize_chatgpt_product_analysis(data):
    data = data if isinstance(data, dict) else {}

    return {
        "is_product_page": bool_or_none(data.get("is_product_page")),
        "is_correct_product": bool_or_none(data.get("is_correct_product")),
        "ingredient_match_confidence": bounded_confidence(data.get("ingredient_match_confidence")),
        "food_rules_ok": bool_or_none(data.get("food_rules_ok")),
        "missing_required": clean_text_list(data.get("missing_required")),
        "blocked_by": clean_text_list(data.get("blocked_by")),
        "product_name": clean_text(data.get("product_name")),
        "brand": clean_text(data.get("brand")),
        "description": clean_text(data.get("description")),
        "ingredients_text": clean_text(data.get("ingredients_text")),
        "category": clean_text(data.get("category")),
        "price": clean_text(data.get("price")),
        "size": clean_text(data.get("size")),
        "package_size": clean_text(data.get("package_size")),
        "unit_price": clean_text(data.get("unit_price")),
        "unit_price_value": safe_float(data.get("unit_price_value")),
        "unit_price_unit": clean_text(data.get("unit_price_unit")),
        "availability": clean_text(data.get("availability")),
        "in_stock": bool_or_none(data.get("in_stock")),
        "is_organic": bool_or_none(data.get("is_organic")),
        "confidence": bounded_confidence(data.get("confidence")),
        "reason": clean_text(data.get("reason")),
        "evidence": clean_text_list(data.get("evidence")),
    }


def clean_json_response(text):
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    return value


def bool_or_none(value):
    if isinstance(value, bool):
        return value

    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False

    return None


def bounded_confidence(value):
    number = safe_float(value)
    if number is None:
        return None

    return round(max(0.0, min(1.0, number)), 3)


def clean_text_list(value):
    if isinstance(value, str):
        parts = re.split(r"[,;\n]+", value)
    elif isinstance(value, list):
        parts = value
    else:
        parts = []

    return unique_texts(parts)


def food_rule_marker_text(missing_required, blocked_by):
    issues = []
    issues.extend(missing_required or [])
    issues.extend(blocked_by or [])

    return "Food rule review: " + "; ".join(issues) if issues else ""


def best_product_mapping_for_candidate(soup, candidate):
    mappings = []
    mappings.extend(extract_json_ld_products(soup))
    mappings.extend(extract_embedded_product_mappings(soup))

    if not mappings:
        return {}

    candidate_name = str(candidate.get("product_name") or "").lower()
    candidate_tokens = set(tokenize(candidate_name))

    def mapping_score(mapping):
        name = clean_text(
            mapping.get("name")
            or mapping.get("title")
            or mapping.get("productName")
            or mapping.get("product_name")
        ).lower()
        tokens = set(tokenize(name))
        score = len(candidate_tokens & tokens) * 5

        if candidate_name and candidate_name in name:
            score += 20

        if has_price_value(mapping):
            score += 4

        if mapping.get("description"):
            score += 3

        return score

    return max(mappings, key=mapping_score)


def meta_content(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    return ""


def canonical_product_url(soup, mapping, page_url):
    mapped_url = extract_product_url_from_mapping(mapping or {})
    if mapped_url:
        return urljoin(page_url, str(mapped_url))

    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        return urljoin(page_url, canonical.get("href"))

    return page_url


def best_detail_name(mapped_name, title, fallback):
    for value in [mapped_name, title, fallback]:
        text = clean_text(value)
        if text and len(text) <= 180:
            return text

    return clean_text(fallback)


def extract_brand_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    brand = mapping.get("brand") or mapping.get("manufacturer")

    if isinstance(brand, dict):
        return clean_text(brand.get("name") or brand.get("brandName"))

    if isinstance(brand, list):
        names = [
            extract_brand_from_mapping({"brand": item})
            for item in brand
        ]
        return clean_text(" ".join(name for name in names if name))

    return clean_text(brand)


def extract_ingredients_text(visible_text):
    match = re.search(
        r"\bingredients?\b[:\s]+(.{20,900}?)(?:\bcontains\b|\bnutrition\b|\bdirections\b|\bwarnings\b|\babout\b|$)",
        visible_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return clean_text(match.group(1))[:800]


def extract_package_size(text):
    match = PACKAGE_SIZE_PATTERN.search(str(text or ""))
    return clean_text(match.group(0)) if match else ""


def extract_unit_price(text):
    match = UNIT_PRICE_PATTERN.search(str(text or ""))

    if not match:
        return {}

    value = safe_float(match.group(1))
    unit = normalize_unit(match.group(2))

    return {
        "display": f"${value:.2f}/{unit}" if value is not None and unit else clean_text(match.group(0)),
        "value": value,
        "unit": unit,
    }


def extract_availability(mapping, visible_text):
    text_parts = []

    if isinstance(mapping, dict):
        offers = mapping.get("offers") or mapping.get("offer")
        if isinstance(offers, dict):
            text_parts.append(str(offers.get("availability") or ""))
            text_parts.append(str(offers.get("inventoryLevel") or ""))
        elif isinstance(offers, list):
            for offer in offers[:4]:
                if isinstance(offer, dict):
                    text_parts.append(str(offer.get("availability") or ""))
                    text_parts.append(str(offer.get("inventoryLevel") or ""))

    text_parts.append(str(visible_text or "")[:2500])
    haystack = clean_text(" ".join(text_parts)).lower()

    out_terms = [
        "out of stock",
        "currently unavailable",
        "not available",
        "unavailable",
        "sold out",
    ]
    in_terms = [
        "in stock",
        "pickup available",
        "available for pickup",
        "available today",
        "delivery available",
        "add to cart",
    ]

    if any(term in haystack for term in out_terms):
        return {"text": "Out of stock or unavailable", "in_stock": False}

    if any(term in haystack for term in in_terms):
        return {"text": "Available", "in_stock": True}

    return {"text": "", "in_stock": None}


def product_matches_ingredient(ingredient, candidate):
    match = best_ingredient_candidate_match(ingredient, candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    if not ingredient_tokens:
        return True

    overlap = match.get("overlap", 0)

    return overlap >= max(1, min(len(ingredient_tokens), 2))


def search_store_products(
    ingredient,
    store_key,
    store,
    full_address,
    home_location,
    store_location,
    search_term=None,
    search_url=None,
):
    store_name = store.get("label") or store_key.title()
    search_term = search_term or ingredient
    search_url = search_url or build_product_search_url(store, search_term)
    skip_reasons = []

    if not search_url:
        return [], [f"{store_name}: no product search URL is configured."]

    request_candidates = []
    request_skip_reasons = []

    try:
        response = requests.get(
            search_url,
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
    except Exception as exc:
        request_skip_reasons.append(f"{store_name}: product search request failed: {exc}")
        response = None
    else:
        request_candidates = parse_product_candidates_from_html(
            response.text,
            response.url,
            ingredient,
            store_key,
            store_name,
            search_url,
            full_address,
            home_location,
            store_location,
        )

        if not request_candidates:
            request_skip_reasons.append(f"{store_name}: no parseable product cards were found in the initial HTML.")

    if should_open_store_search_page(bool(request_candidates)):
        browser_candidates, browser_skip_reasons = search_store_products_with_browser_agent(
            ingredient,
            store_key,
            store,
            search_url,
            full_address,
            home_location,
            store_location,
        )

        if browser_candidates:
            skip_reasons.extend(browser_skip_reasons)
            return browser_candidates, unique_texts(skip_reasons)

        skip_reasons.extend(browser_skip_reasons)

    if request_candidates:
        if skip_reasons:
            for candidate in request_candidates:
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Used initial HTML product data because rendered-page extraction did not return visible cards."]
                )
        return request_candidates, unique_texts(skip_reasons)

    skip_reasons.extend(request_skip_reasons)

    fallback = build_search_page_candidate(
        ingredient,
        store_key,
        store_name,
        (response.url if response else "") or search_url,
        full_address,
        store_location,
        "No product cards with prices could be parsed from this store page.",
    )
    return [fallback], unique_texts(skip_reasons + [f"{store_name}: no parseable product cards were found."])


def search_store_products_with_browser_agent(
    ingredient,
    store_key,
    store,
    search_url,
    full_address,
    home_location,
    store_location,
):
    store_name = store.get("label") or store_key.title()

    with PRODUCT_BROWSER_FETCH_LOCK:
        driver = None

        try:
            from PushShoppingList.services.recipe_extract_service import create_headless_chrome_driver
            from PushShoppingList.services.recipe_extract_service import wait_for_browser_document

            driver = create_headless_chrome_driver(
                window_size="1440,1100",
                prefer_undetected=True,
                page_load_strategy="normal",
            )
            driver.set_page_load_timeout(product_browser_wait_seconds() + 8)
            configure_browser_home_location(driver, search_url, home_location)

            try:
                driver.get(search_url)
            except Exception:
                if len(driver.page_source or "") < 800:
                    raise

            wait_for_browser_document(driver, timeout_seconds=product_browser_wait_seconds())
            handle_browser_popups_and_location(driver, full_address)
            for _ in range(3):
                wait_for_rendered_product_cards(
                    driver,
                    timeout_seconds=max(3, product_browser_wait_seconds() / 3),
                )
                scroll_rendered_product_page(driver)
                wait_for_browser_text_to_settle(driver, timeout_seconds=2)
            handle_browser_popups_and_location(driver, full_address)

            final_url = driver.current_url or search_url
            visible_cards = extract_visible_product_cards_from_browser(driver)
            visible_candidates = product_candidates_from_visible_cards(
                visible_cards,
                ingredient,
                store_key,
                store_name,
                final_url,
                search_url,
                full_address,
                home_location,
                store_location,
            )
            rendered_html = driver.page_source or ""
            rendered_candidates = parse_product_candidates_from_html(
                rendered_html,
                final_url,
                ingredient,
                store_key,
                store_name,
                search_url,
                full_address,
                home_location,
                store_location,
            )

            candidates = dedupe_candidates(visible_candidates + rendered_candidates)
            if candidates:
                for candidate in candidates:
                    candidate["ranking_reasons"] = unique_texts(
                        candidate.get("ranking_reasons", [])
                        + ["Store search page was opened in a browser using the saved home address context."]
                    )
                return candidates[:product_candidate_limit()], []

            return [], [f"{store_name}: browser agent found no visible product cards on the rendered search page."]
        except Exception as exc:
            return [], [f"{store_name}: browser agent could not inspect rendered search page: {exc}"]
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass


def configure_browser_home_location(driver, target_url, home_location):
    if not home_location:
        return

    try:
        parsed = urlparse(target_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": origin,
                "permissions": ["geolocation"],
            },
        )
        driver.execute_cdp_cmd(
            "Emulation.setGeolocationOverride",
            {
                "latitude": float(home_location.get("latitude")),
                "longitude": float(home_location.get("longitude")),
                "accuracy": 60,
            },
        )
    except Exception:
        pass


def handle_browser_popups_and_location(driver, full_address):
    for _ in range(3):
        try:
            clicked = driver.execute_script(
                """
                const patterns = [
                    /accept all/i, /accept/i, /agree/i, /allow/i,
                    /use current location/i, /use my location/i,
                    /continue/i, /got it/i, /no thanks/i, /not now/i,
                    /dismiss/i, /^close$/i
                ];
                const blocked = [/add to cart/i, /checkout/i, /sign in/i, /log in/i, /create account/i];

                function visible(el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                }

                const controls = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input[type="button"], input[type="submit"]'
                ));

                for (const control of controls) {
                    if (!visible(control)) {
                        continue;
                    }

                    const text = [
                        control.innerText,
                        control.value,
                        control.getAttribute("aria-label"),
                        control.getAttribute("title")
                    ].filter(Boolean).join(" ").trim();

                    if (!text || blocked.some(pattern => pattern.test(text))) {
                        continue;
                    }

                    if (patterns.some(pattern => pattern.test(text))) {
                        control.click();
                        return text;
                    }
                }

                return "";
                """
            )
        except Exception:
            clicked = ""

        if clicked:
            time.sleep(0.45)

    fill_location_inputs(driver, full_address)


def fill_location_inputs(driver, full_address):
    zip_code = extract_zip_code(full_address)
    if not full_address and not zip_code:
        return

    try:
        driver.execute_script(
            """
            const zipCode = arguments[0] || "";
            const fullAddress = arguments[1] || "";
            const addressValue = zipCode || fullAddress;
            const fullValue = fullAddress || zipCode;

            function visible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    !el.disabled &&
                    !el.readOnly &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function attrs(el) {
                return [
                    el.getAttribute("name"),
                    el.getAttribute("id"),
                    el.getAttribute("placeholder"),
                    el.getAttribute("aria-label"),
                    el.getAttribute("autocomplete")
                ].filter(Boolean).join(" ").toLowerCase();
            }

            const inputs = Array.from(document.querySelectorAll('input, textarea'));
            for (const input of inputs) {
                if (!visible(input)) {
                    continue;
                }

                const attrText = attrs(input);
                const looksLocation = /(zip|postal|postcode|address|location|store)/i.test(attrText);
                const looksSearch = /(search|query|keyword|product|item)/i.test(attrText);

                if (!looksLocation || looksSearch) {
                    continue;
                }

                input.focus();
                input.value = /(address|location|store)/i.test(attrText) ? fullValue : addressValue;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));

                const form = input.closest("form");
                const submit = form
                    ? form.querySelector('button[type="submit"], input[type="submit"], button')
                    : null;

                if (submit && visible(submit)) {
                    submit.click();
                } else {
                    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
                }

                return true;
            }

            return false;
            """,
            zip_code,
            full_address,
        )
        time.sleep(0.8)
    except Exception:
        pass


def wait_for_browser_text_to_settle(driver, timeout_seconds=3):
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_length = -1
    stable_seen = 0

    while time.monotonic() < deadline:
        try:
            text_length = driver.execute_script(
                "return (document.body && document.body.innerText || '').length"
            )
        except Exception:
            text_length = 0

        if text_length == last_length and text_length > 0:
            stable_seen += 1
            if stable_seen >= 2:
                return
        else:
            stable_seen = 0
            last_length = text_length

        time.sleep(0.4)


def wait_for_rendered_product_cards(driver, timeout_seconds=8):
    deadline = time.monotonic() + max(2, timeout_seconds)

    while time.monotonic() < deadline:
        try:
            count = driver.execute_script(
                """
                const pricePattern = /\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?/;
                const selectors = [
                    '[data-testid*="product" i]',
                    '[data-test*="product" i]',
                    '[data-qa*="product" i]',
                    '[class*="product" i]',
                    'article',
                    'li'
                ].join(',');
                return Array.from(document.querySelectorAll(selectors))
                    .filter(el => pricePattern.test(el.innerText || el.textContent || ''))
                    .length;
                """
            )
        except Exception:
            count = 0

        if count:
            return

        time.sleep(0.5)


def scroll_rendered_product_page(driver):
    try:
        for ratio in [0, 0.28, 0.58, 0.9, 1, 0]:
            driver.execute_script(
                "window.scrollTo(0, Math.floor((document.body.scrollHeight || 0) * arguments[0]));",
                ratio,
            )
            time.sleep(0.35)
    except Exception:
        pass


def extract_visible_product_cards_from_browser(driver):
    try:
        cards = driver.execute_script(
            """
            const limit = arguments[0] || 48;
            const pricePattern = /\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?/g;
            const badLinePattern = /^(add|add to cart|sponsored|sale|save|pickup|delivery|shipping|in stock|out of stock|rating|stars?|reviews?|view details|quick view)$/i;

            function visible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style &&
                    style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    parseFloat(style.opacity || "1") > 0.02 &&
                    rect.width >= 60 &&
                    rect.height >= 35;
            }

            function textOf(el) {
                return String(el.innerText || el.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            function priceMatches(text) {
                return String(text || "").match(pricePattern) || [];
            }

            function usefulNameLine(line) {
                const value = String(line || "").replace(/\\s+/g, " ").trim();
                if (!value || value.length < 3 || value.length > 180) {
                    return "";
                }
                if (pricePattern.test(value)) {
                    pricePattern.lastIndex = 0;
                    return "";
                }
                pricePattern.lastIndex = 0;
                if (badLinePattern.test(value)) {
                    return "";
                }
                if (/^\\d+(?:\\.\\d+)?\\s*(ct|oz|lb|lbs|g|kg|ml|l|each|ea)$/i.test(value)) {
                    return "";
                }
                return value;
            }

            function bestName(root) {
                const targets = Array.from(root.querySelectorAll(
                    '[data-testid*="title" i], [data-test*="title" i], [class*="title" i], [class*="name" i], a[href], img[alt]'
                ));
                const values = [];

                for (const target of targets) {
                    values.push(target.getAttribute("aria-label"));
                    values.push(target.getAttribute("title"));
                    values.push(target.getAttribute("alt"));
                    values.push(target.innerText);
                }

                values.push(...String(root.innerText || "").split(/\\n+/));

                for (const value of values) {
                    const cleaned = usefulNameLine(value);
                    if (cleaned) {
                        return cleaned;
                    }
                }

                return "";
            }

            function bestLink(root) {
                const links = Array.from(root.querySelectorAll("a[href]"));
                const preferred = links.find(link => {
                    const text = textOf(link);
                    const href = link.getAttribute("href") || "";
                    return text.length > 2 || /product|p\\//i.test(href);
                }) || links[0];
                return preferred ? preferred.href : "";
            }

            function bestImage(root) {
                const image = Array.from(root.querySelectorAll("img"))
                    .find(img => visible(img) && (img.currentSrc || img.src || img.getAttribute("data-src")));
                return image ? (image.currentSrc || image.src || image.getAttribute("data-src") || "") : "";
            }

            const selector = [
                'article',
                'li',
                '[itemtype*="Product" i]',
                '[data-testid*="product" i]',
                '[data-test*="product" i]',
                '[data-qa*="product" i]',
                '[class*="product" i]',
                '[class*="Product"]',
                'section',
                'div'
            ].join(',');
            const potential = Array.from(document.querySelectorAll(selector))
                .filter(el => {
                    if (!visible(el)) {
                        return false;
                    }
                    const text = textOf(el);
                    const prices = priceMatches(text);
                    return text.length >= 15 &&
                        text.length <= 1400 &&
                        prices.length >= 1 &&
                        prices.length <= 5 &&
                        (el.querySelector("a[href]") || el.querySelector("img"));
                })
                .sort((a, b) => textOf(a).length - textOf(b).length);

            const roots = [];
            for (const el of potential) {
                if (roots.some(root => root.contains(el) || el.contains(root))) {
                    continue;
                }
                roots.push(el);
                if (roots.length >= limit) {
                    break;
                }
            }

            return roots.map(root => {
                const rawText = String(root.innerText || root.textContent || "");
                const text = textOf(root);
                const prices = priceMatches(text);
                return {
                    name: bestName(root),
                    price: prices[0] || "",
                    product_url: bestLink(root),
                    image_url: bestImage(root),
                    text: rawText.slice(0, 1600)
                };
            }).filter(card => card.name || card.product_url || card.price);
            """,
            product_candidate_limit(),
        )
    except Exception:
        cards = []

    return cards if isinstance(cards, list) else []


def product_candidates_from_visible_cards(
    cards,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
):
    candidates = []

    for card in cards:
        if not isinstance(card, dict):
            continue

        name = clean_text(card.get("name"))
        price = normalize_price(card.get("price"))
        product_url = clean_text(card.get("product_url"))
        image_url = clean_text(card.get("image_url"))
        raw_card_text = str(card.get("text") or "")
        card_text = clean_text(raw_card_text)

        ingredient_tokens = set(tokenize(ingredient))
        name_tokens = set(tokenize(name))
        needs_better_name = (
            not name
            or len(name) > 100
            or PRICE_PATTERN.search(name)
            or (ingredient_tokens and not (ingredient_tokens & name_tokens))
        )

        if needs_better_name:
            better_name = best_visible_card_name(ingredient, raw_card_text)
            if better_name:
                name = better_name

        if not name:
            continue

        candidate = build_candidate(
            ingredient,
            store_key,
            store_name,
            name,
            price,
            urljoin(page_url, product_url) if product_url else page_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="browser-visible-card",
            image_url=urljoin(page_url, image_url) if image_url else "",
        )
        package_size = extract_package_size(" ".join([name, card_text]))
        unit_price = extract_unit_price(card_text)
        if package_size:
            candidate["package_size"] = package_size
            candidate["size"] = package_size
        if unit_price:
            candidate["unit_price"] = unit_price.get("display", "")
            candidate["unit_price_value"] = unit_price.get("value")
            candidate["unit_price_unit"] = unit_price.get("unit", "")
        if card_text:
            candidate["card_text_excerpt"] = card_text[:900]
            candidate["detail_text_excerpt"] = card_text[:900]

        candidate["ranking_reasons"].append("Visible product card was extracted from the rendered store page.")
        candidates.append(candidate)

    return dedupe_candidates(candidates)[:product_candidate_limit()]


def best_visible_card_name(ingredient, card_text):
    ingredient_tokens = set(tokenize(ingredient))
    text = str(card_text or "")
    text = re.sub(
        r"\bcurrent\s+price\s*:\s*\$\s*\d+(?:,\d{3})*(?:\.\d{2})?",
        " | ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\$\s*\d+\s+\d{2}\b", " | ", text)
    text = re.sub(r"\$\s*\d+(?:,\d{3})*(?:\.\d{2})?", " | ", text)
    text = PACKAGE_SIZE_PATTERN.sub(" | ", text)
    text = re.sub(
        r"\b(?:many in stock|in stock|out of stock|add|best seller|store choice|sponsored)\b",
        " | ",
        text,
        flags=re.IGNORECASE,
    )
    lines = [
        clean_text(line)
        for line in re.split(r"[\n|]+", text)
        if clean_text(line)
    ]
    candidates = []

    for line in lines:
        if len(line) > 180 or PRICE_PATTERN.search(line):
            continue

        for value in unique_texts([strip_leading_product_badges(line), line]):
            lowered = value.lower()
            if any(term in lowered for term in ["add to cart", "pickup", "delivery", "rating", "reviews"]):
                continue

            line_tokens = set(tokenize(value))
            overlap = len(ingredient_tokens & line_tokens)
            candidates.append((overlap, len(line_tokens), value))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def strip_leading_product_badges(value):
    text = clean_text(value)
    badge_pattern = re.compile(
        r"^(?:(?:\d+%|organic|whole|low fat|fat free|skim|dairy free|vegan|vegetarian|"
        r"gluten free|low carb|best seller|store choice|sponsored)\s+)+(.+)$",
        re.IGNORECASE,
    )
    match = badge_pattern.match(text)

    if not match:
        return text

    stripped = clean_text(match.group(1))

    if len(tokenize(stripped)) >= 3:
        return stripped

    return text


def parse_product_candidates_from_html(
    html_text,
    page_url,
    ingredient,
    store_key,
    store_name,
    search_url,
    full_address,
    home_location,
    store_location,
):
    soup = BeautifulSoup(html_text or "", "html.parser")
    candidates = []
    limit = product_candidate_limit()

    for product in extract_json_ld_products(soup):
        candidate = product_candidate_from_mapping(
            product,
            ingredient,
            store_key,
            store_name,
            page_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="json-ld",
        )
        if candidate:
            candidates.append(candidate)

    if len(candidates) < limit:
        for product in extract_embedded_product_mappings(soup):
            candidate = product_candidate_from_mapping(
                product,
                ingredient,
                store_key,
                store_name,
                page_url,
                search_url,
                full_address,
                home_location,
                store_location,
                source="embedded-json",
            )
            if candidate:
                candidates.append(candidate)
                if len(candidates) >= limit:
                    break

    if len(candidates) < limit:
        candidates.extend(extract_anchor_product_candidates(
            soup,
            ingredient,
            store_key,
            store_name,
            page_url,
            search_url,
            full_address,
            home_location,
            store_location,
        ))

    return dedupe_candidates(candidates)[:limit]


def extract_json_ld_products(soup):
    products = []

    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text("", strip=True)
        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=True))

    return products


def extract_embedded_product_mappings(soup):
    products = []
    limit = product_candidate_limit()

    for script in soup.find_all("script"):
        text = script.string or script.get_text("", strip=True)

        if not text or len(text) > 1_500_000:
            continue

        lowered = text.lower()
        if "price" not in lowered or ("product" not in lowered and "name" not in lowered):
            continue

        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=False))

        if len(products) >= limit:
            break

    return products


def parse_json_payloads(text):
    payloads = []
    text = str(text or "").strip()

    if not text:
        return payloads

    try:
        payloads.append(json.loads(text))
        return payloads
    except Exception:
        pass

    for match in re.finditer(r"({.*?})", text):
        snippet = match.group(1)
        if len(snippet) > 200_000:
            continue
        try:
            payloads.append(json.loads(snippet))
        except Exception:
            continue

        if len(payloads) >= 5:
            break

    return payloads


def find_product_mappings(value, require_product_type=False):
    found = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return

        if not isinstance(node, dict):
            return

        node_type = node.get("@type") or node.get("type") or ""
        type_text = " ".join(node_type) if isinstance(node_type, list) else str(node_type)
        looks_like_product = (
            "product" in type_text.lower()
            or node.get("productName")
            or node.get("product_name")
            or (node.get("name") and has_price_value(node))
        )

        if looks_like_product and (not require_product_type or "product" in type_text.lower()):
            found.append(node)

        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value)

    walk(value)
    return found


def has_price_value(value):
    return bool(extract_price_from_mapping(value))


def product_candidate_from_mapping(
    product,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
    source,
):
    name = clean_text(
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or product.get("product_name")
    )
    price = extract_price_from_mapping(product)
    product_url = extract_product_url_from_mapping(product)
    product_url = urljoin(page_url, str(product_url or page_url))
    image_url = extract_image_url_from_mapping(product)
    image_url = urljoin(page_url, str(image_url)) if image_url else ""

    if not name or len(name) > 180:
        return None

    return build_candidate(
        ingredient,
        store_key,
        store_name,
        name,
        price,
        product_url,
        search_url,
        full_address,
        home_location,
        store_location,
        source,
        image_url=image_url,
    )


def extract_product_url_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    product_url = mapping.get("url") or mapping.get("canonicalUrl") or mapping.get("productUrl")

    if isinstance(product_url, dict):
        product_url = product_url.get("@id") or product_url.get("url")

    if product_url:
        return product_url

    offers = mapping.get("offers") or mapping.get("offer")
    if isinstance(offers, list):
        for offer in offers:
            product_url = extract_product_url_from_mapping(offer)
            if product_url:
                return product_url
    elif isinstance(offers, dict):
        return extract_product_url_from_mapping(offers)

    return ""


def extract_image_url_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    image = mapping.get("image") or mapping.get("images") or mapping.get("thumbnail") or mapping.get("thumbnailUrl")

    if isinstance(image, str):
        return image

    if isinstance(image, dict):
        return (
            image.get("url")
            or image.get("contentUrl")
            or image.get("@id")
            or ""
        )

    if isinstance(image, list):
        for item in image:
            image_url = extract_image_url_from_mapping({"image": item})
            if image_url:
                return image_url

    media = mapping.get("media") or mapping.get("primaryImage")
    if isinstance(media, (dict, list, str)):
        return extract_image_url_from_mapping({"image": media})

    return ""


def extract_price_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    for key in ["price", "salePrice", "regularPrice", "currentPrice", "finalPrice"]:
        value = mapping.get(key)
        price = normalize_price(value)
        if price:
            return price

    offers = mapping.get("offers") or mapping.get("offer")
    if isinstance(offers, list):
        for offer in offers:
            price = extract_price_from_mapping(offer)
            if price:
                return price
    elif isinstance(offers, dict):
        price = extract_price_from_mapping(offers)
        if price:
            return price

    prices = mapping.get("prices")
    if isinstance(prices, dict):
        return extract_price_from_mapping(prices)

    return ""


def normalize_price(value):
    if value in (None, ""):
        return ""

    if isinstance(value, dict):
        for key in ["value", "amount", "price", "formatted", "display"]:
            price = normalize_price(value.get(key))
            if price:
                return price
        return ""

    if isinstance(value, (int, float)):
        return f"${float(value):.2f}"

    text = clean_text(value)
    match = PRICE_PATTERN.search(text)
    if match:
        return match.group(0).replace(" ", "")

    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return f"${float(text):.2f}"

    return text if "$" in text else ""


def extract_anchor_product_candidates(
    soup,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
):
    candidates = []
    ingredient_tokens = set(tokenize(ingredient))
    limit = product_candidate_limit()

    for anchor in soup.find_all("a", href=True):
        name = clean_text(anchor.get_text(" ", strip=True))

        if not name or len(name) > 140:
            continue

        name_tokens = set(tokenize(name))
        overlap = len(ingredient_tokens & name_tokens)
        if ingredient_tokens and overlap == 0:
            continue

        parent_text = clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else name)
        price = ""
        price_match = PRICE_PATTERN.search(parent_text)
        if price_match:
            price = price_match.group(0).replace(" ", "")

        candidates.append(build_candidate(
            ingredient,
            store_key,
            store_name,
            name,
            price,
            urljoin(page_url, anchor.get("href")),
            search_url,
            full_address,
            home_location,
            store_location,
            source="html-anchor",
        ))

        if len(candidates) >= limit:
            break

    return candidates


def build_search_page_candidate(
    ingredient,
    store_key,
    store_name,
    search_url,
    full_address,
    store_location,
    reason,
):
    candidate = build_candidate(
        ingredient,
        store_key,
        store_name,
        f"{ingredient} search results",
        "",
        search_url,
        search_url,
        full_address,
        None,
        store_location,
        source="search-page-fallback",
    )
    candidate["viable"] = True
    candidate["skip_reasons"].append(reason)
    candidate["ranking_reasons"].append("Fallback search page saved because product cards were not parseable.")
    candidate["confidence"] = 0.2
    return candidate


def build_candidate(
    ingredient,
    store_key,
    store_name,
    product_name,
    price,
    product_url,
    search_url,
    full_address,
    home_location,
    store_location,
    source,
    image_url="",
):
    store_location = store_location or {}
    candidate = {
        "id": product_candidate_id(store_key, product_url, product_name, price),
        "ingredient": ingredient,
        "store_key": store_key,
        "store_name": store_name,
        "store_location_name": store_location.get("name", ""),
        "store_location_address": store_location.get("address", ""),
        "store_location_distance_miles": store_location.get("distance_miles"),
        "store_locator_url": store_location.get("locator_url", ""),
        "home_address": full_address,
        "home_location": home_location,
        "product_name": product_name,
        "price": price,
        "size": "",
        "package_size": "",
        "unit_price": "",
        "image_url": image_url,
        "product_url": product_url,
        "search_url": search_url,
        "source": source,
        "score": 0,
        "confidence": 0,
        "viable": True,
        "ranking_reasons": [],
        "skip_reasons": [],
    }
    annotated = annotate_product_food_rules({
        "name": product_name,
        "description": product_name,
    })
    candidate["food_rule_status"] = annotated.get("food_rule_status", {})
    return candidate


def rank_product_candidates(ingredient, candidates):
    ranked = []
    seen = set()

    for candidate in candidates:
        key = candidate.get("id")
        if not key or key in seen:
            continue

        seen.add(key)
        score, reasons, skip_reasons, viable = score_candidate(ingredient, candidate)
        candidate["score"] = round(score, 2)
        candidate["confidence"] = round(max(0.05, min(0.98, score / 100)), 2)
        candidate["ranking_reasons"] = unique_texts(candidate.get("ranking_reasons", []) + reasons)
        candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + skip_reasons)
        candidate["viable"] = bool(viable)
        ranked.append(candidate)

    ranked = apply_relative_candidate_preferences(ranked)
    return sorted(ranked, key=lambda item: item.get("score", 0), reverse=True)


def score_candidate(ingredient, candidate):
    score = 20.0
    reasons = []
    skip_reasons = []
    viable = True

    if candidate.get("source") == "search-page-fallback":
        return (
            1.0,
            ["Saved store search page as a reference."],
            ["No direct product card, price, or product URL was available."],
            False,
        )

    product_name = candidate.get("product_name", "")
    detail_text = " ".join([
        product_name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    match = best_ingredient_candidate_match(ingredient, candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    overlap = match.get("overlap", 0)
    token_ratio = match.get("token_ratio", 0)
    name_overlap = match.get("name_overlap", 0)
    name_token_ratio = match.get("name_token_ratio", 0)
    exact_name_match = match.get("exact_name_match", False)
    exact_phrase_match = match.get("exact_phrase_match", False)
    matched_ingredient = match.get("ingredient", ingredient)

    metadata = {
        "exact_name_match": exact_name_match,
        "exact_phrase_match": exact_phrase_match,
        "matched_ingredient": matched_ingredient,
        "ingredient_token_ratio": round(token_ratio, 3),
        "name_token_ratio": round(name_token_ratio, 3),
        "detail_evaluated": bool(candidate.get("detail_evaluated")),
        "organic": bool(candidate.get("is_organic")),
        "unit_price_value": candidate.get("unit_price_value"),
        "unit_price_unit": candidate.get("unit_price_unit", ""),
        "package_size": candidate.get("package_size", ""),
        "in_stock": candidate.get("in_stock"),
        "chatgpt_analysis_status": (candidate.get("chatgpt_analysis") or {}).get("status", ""),
        "chatgpt_confidence": candidate.get("chatgpt_confidence"),
        "chatgpt_ingredient_match_confidence": candidate.get("chatgpt_ingredient_match_confidence"),
    }
    candidate["ranking_metadata"] = metadata

    if DETAIL_REQUIRED and not candidate.get("detail_evaluated"):
        score -= 45
        viable = False
        skip_reasons.append("Full product page was not successfully evaluated.")
    elif candidate.get("detail_evaluated"):
        score += 15
        reasons.append("Full product page was opened and evaluated.")

    if exact_name_match:
        score += 38
        reasons.append("Exact product name match.")
    elif exact_phrase_match:
        score += 28
        reasons.append("Product name contains the exact ingredient phrase.")
    elif name_token_ratio >= 0.8:
        score += 22
        reasons.append("Product name matches most ingredient terms.")

    score += token_ratio * 25
    if token_ratio:
        if normalize_match_text(matched_ingredient) != normalize_match_text(ingredient):
            reasons.append(f"Matches {overlap} term(s) from alternative '{matched_ingredient}'.")
        else:
            reasons.append(f"Matches {overlap} ingredient term(s).")
    else:
        score -= 25
        skip_reasons.append("Product name does not clearly match the ingredient.")

    if ingredient_tokens and not exact_phrase_match and token_ratio < 0.5:
        score -= 20
        viable = False
        skip_reasons.append("Full product details do not confirm enough ingredient terms.")

    ai_analysis = candidate.get("chatgpt_analysis") or {}
    if ai_analysis.get("status") == "done":
        if ai_analysis.get("is_product_page") is False:
            score -= 60
            viable = False
            skip_reasons.append("ChatGPT analysis says the loaded page is not a product page.")

        if ai_analysis.get("is_correct_product") is False:
            score -= 120
            viable = False
            skip_reasons.append("ChatGPT analysis says the loaded page does not match the shopping item.")
        elif ai_analysis.get("is_correct_product") is True:
            score += 24
            reasons.append("ChatGPT confirmed the fully loaded page matches the shopping item.")

        match_confidence = safe_float(ai_analysis.get("ingredient_match_confidence"))
        if match_confidence is not None:
            score += match_confidence * 16
            reasons.append(f"ChatGPT ingredient-match confidence: {match_confidence:.2f}.")

        analysis_confidence = safe_float(ai_analysis.get("confidence"))
        if analysis_confidence is not None:
            score += analysis_confidence * 10
            reasons.append(f"ChatGPT page-analysis confidence: {analysis_confidence:.2f}.")
    elif ai_analysis.get("status") == "failed":
        skip_reasons.append(ai_analysis.get("message") or "ChatGPT product analysis failed.")
    elif ai_analysis.get("status") == "skipped":
        skip_reasons.append(ai_analysis.get("message") or "ChatGPT product analysis was skipped.")

    food_status = candidate.get("food_rule_status") or {}
    if food_status.get("blocked_by"):
        score -= 100
        viable = False
        skip_reasons.append("Blocked by food rules: " + "; ".join(food_status.get("blocked_by", [])))
    if food_status.get("missing_required"):
        score -= 100
        viable = False
        skip_reasons.append("Missing required food preference: " + "; ".join(food_status.get("missing_required", [])))
    elif not food_status.get("blocked_by"):
        score += 20
        reasons.append("Matches required food preferences.")

    if candidate.get("is_organic"):
        score += 18
        reasons.append("Organic option.")

    if candidate.get("price"):
        score += 10
        reasons.append("Has a visible price.")
    else:
        score -= 8
        skip_reasons.append("Price was not visible in the parsed store page.")

    if candidate.get("unit_price_value") is not None:
        score += 8
        reasons.append(f"Has unit value: {candidate.get('unit_price')}.")
    else:
        score -= 4
        skip_reasons.append("Unit value was not available from the product page.")

    if candidate.get("package_size"):
        score += 6
        reasons.append(f"Package size found: {candidate.get('package_size')}.")
    else:
        score -= 3
        skip_reasons.append("Package size was not clear from the product page.")

    if candidate.get("in_stock") is True:
        score += 12
        reasons.append("Nearby store page indicates availability.")
    elif candidate.get("in_stock") is False:
        score -= 60
        viable = False
        skip_reasons.append("Product page indicates the product is unavailable or out of stock.")
    else:
        skip_reasons.append("Nearby store inventory was not confirmed on the product page.")

    if candidate.get("product_url") and candidate.get("product_url") != candidate.get("search_url"):
        score += 8
        reasons.append("Has a direct product URL.")
    else:
        score -= 4
        skip_reasons.append("Only the store search URL was available.")

    distance = candidate.get("store_location_distance_miles")
    if isinstance(distance, (int, float)):
        score += max(0, 12 - min(distance, 12))
        reasons.append(f"Nearest {candidate.get('store_name')} is about {distance:.1f} mi away.")
    else:
        skip_reasons.append("Nearest store distance was not available.")

    if score < 5:
        viable = False

    return score, reasons, skip_reasons, viable


def select_product_choice(item_key, product_id, store_key=""):
    item_key = normalize_item_key(item_key)
    product_id = str(product_id or "").strip()
    store_key = str(store_key or "").strip()
    state = load_product_choices()
    record = state.get("items", {}).get(item_key)

    if not record:
        return {
            "ok": False,
            "error": "No product choices were saved for that ingredient.",
        }

    selected = next(
        (
            candidate
            for candidate in record.get("candidates", [])
            if candidate.get("id") == product_id
            and (not store_key or candidate.get("store_key") == store_key)
        ),
        None,
    )

    if not selected:
        return {
            "ok": False,
            "error": "That product choice was not found.",
        }

    if selected.get("viable") is False:
        return {
            "ok": False,
            "error": "That product choice is saved as a reference, but it is not selectable.",
        }

    selected["reason_selected"] = selected.get("reason_selected") or product_selection_reason(
        selected,
        selected.get("store_name", ""),
    )

    if store_key:
        store_results = record.setdefault("store_results", {})
        store_result = find_store_result(record, store_key) or {
            "store_key": store_key,
            "store_name": selected.get("store_name", ""),
            "ingredient": record.get("ingredient", item_key),
            "alternatives": [
                candidate
                for candidate in record.get("candidates", [])
                if candidate.get("store_key") == store_key
            ],
            "alternative_products": [
                candidate
                for candidate in record.get("candidates", [])
                if candidate.get("store_key") == store_key
            ],
        }
        store_result.update({
            "best_product_id": product_id,
            "best_product": selected,
            "best_product_match": selected.get("product_name", ""),
            "price": selected.get("price", ""),
            "size": product_size(selected),
            "unit_price": selected.get("unit_price", ""),
            "product_url": selected.get("product_url", ""),
            "image_url": selected.get("image_url", ""),
            "reason_selected": selected.get("reason_selected", ""),
            "reason_skipped": "",
            "skip_reason": "",
        })
        store_results[store_key] = store_result
        record["store_results_list"] = upsert_store_result_list(
            record.get("store_results_list", []),
            store_result,
        )

    record["selected_product_id"] = product_id
    record["selected_product"] = selected
    record["manual_override"] = True
    record["manual_override_store_key"] = store_key
    record["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    save_product_choices(state)
    save_item_store(item_key, selected.get("store_key") or "")

    return {
        "ok": True,
        "item_key": item_key,
        "choice": product_choice_for_store(record, store_key) if store_key else record,
    }


def upsert_store_result_list(store_results_list, store_result):
    output = []
    replaced = False
    store_key = store_result.get("store_key")

    for item in store_results_list if isinstance(store_results_list, list) else []:
        if item.get("store_key") == store_key:
            output.append(store_result)
            replaced = True
        else:
            output.append(item)

    if not replaced:
        output.append(store_result)

    return output


def build_product_search_url(store, ingredient):
    base_url = str(store.get("url") or "").strip()

    if not base_url:
        return ""

    encoded = quote_plus(str(ingredient or "").strip())

    if "{query}" in base_url:
        return base_url.replace("{query}", encoded)

    if base_url.endswith(("=", "/", "?")):
        return base_url + encoded

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}q={encoded}"


def geocode_home_address(full_address):
    full_address = str(full_address or "").strip()

    if not full_address:
        return None

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "jsonv2",
                "q": full_address,
                "limit": 1,
                "countrycodes": "us",
            },
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    try:
        return {
            "latitude": float(data[0].get("lat")),
            "longitude": float(data[0].get("lon")),
            "display_name": data[0].get("display_name", ""),
        }
    except (TypeError, ValueError):
        return None


def find_nearest_store_location(store_key, store, full_address, home_location):
    store_name = store.get("label") or store_key.title()
    locator_url = build_store_locator_url(store, full_address)
    fallback = {
        "name": store_name,
        "address": "",
        "distance_miles": None,
        "locator_url": locator_url,
        "source": "configured-store-locator",
    }

    if not home_location:
        fallback["skip_reason"] = "Home address could not be geocoded."
        return fallback

    lat = home_location["latitude"]
    lon = home_location["longitude"]
    delta = 0.45

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "jsonv2",
                "q": store_name,
                "limit": 8,
                "countrycodes": "us",
                "bounded": 1,
                "viewbox": f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}",
                "addressdetails": 1,
            },
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        fallback["skip_reason"] = f"Nearest store lookup failed: {exc}"
        return fallback

    locations = []
    for item in data if isinstance(data, list) else []:
        try:
            item_lat = float(item.get("lat"))
            item_lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue

        display_name = clean_text(item.get("display_name"))
        distance = haversine_miles(lat, lon, item_lat, item_lon)
        locations.append({
            "name": store_name,
            "address": display_name,
            "latitude": item_lat,
            "longitude": item_lon,
            "distance_miles": round(distance, 2),
            "locator_url": locator_url,
            "source": "nominatim",
        })

    if not locations:
        fallback["skip_reason"] = "No nearby store location was found."
        return fallback

    return min(locations, key=lambda item: item["distance_miles"])


def build_store_locator_url(store, full_address):
    url = str(store.get("urlStoreSelector") or "").strip()

    if not url:
        return ""

    try:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("q", full_address)
        return urlunparse(parsed._replace(query=urlencode(query)))
    except Exception:
        return url


def haversine_miles(lat1, lon1, lat2, lon2):
    radius_miles = 3958.8
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def apply_relative_candidate_preferences(candidates):
    groups = {}

    for candidate in candidates:
        if not candidate.get("viable"):
            continue

        unit = normalize_unit(candidate.get("unit_price_unit", ""))
        value = candidate.get("unit_price_value")

        if value is None or not unit:
            continue

        groups.setdefault(unit, []).append(candidate)

    for unit_candidates in groups.values():
        if len(unit_candidates) < 2:
            continue

        values = [
            candidate.get("unit_price_value")
            for candidate in unit_candidates
            if isinstance(candidate.get("unit_price_value"), (int, float))
        ]

        if not values:
            continue

        best = min(values)
        worst = max(values)
        spread = max(0.01, worst - best)

        for candidate in unit_candidates:
            value = candidate.get("unit_price_value")
            if not isinstance(value, (int, float)):
                continue

            if value == best:
                candidate["score"] = round(candidate.get("score", 0) + 14, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Best unit value among comparable products."]
                )
            else:
                value_score = max(0, 10 * ((worst - value) / spread))
                candidate["score"] = round(candidate.get("score", 0) + value_score, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Unit value compared with alternatives."]
                )

    for candidate in candidates:
        candidate["confidence"] = round(max(0.05, min(0.98, candidate.get("score", 0) / 120)), 2)

    return candidates


def dedupe_candidates(candidates):
    deduped = []
    seen = set()

    for candidate in candidates:
        key = (
            normalize_item_key(candidate.get("store_key")),
            normalize_item_key(candidate.get("product_name")),
            candidate.get("price") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    return deduped


def product_candidate_id(store_key, product_url, product_name, price):
    raw = "|".join(str(value or "") for value in [store_key, product_url, product_name, price])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def safe_float(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_unit(value):
    text = clean_text(value).lower().replace(".", "")
    text = re.sub(r"\s+", " ", text)
    aliases = {
        "ounces": "oz",
        "ounce": "oz",
        "fluid ounce": "fl oz",
        "fluid ounces": "fl oz",
        "pounds": "lb",
        "pound": "lb",
        "lbs": "lb",
        "grams": "g",
        "gram": "g",
        "kilogram": "kg",
        "kilograms": "kg",
        "count": "ct",
        "each": "ea",
        "piece": "ea",
        "pc": "ea",
    }
    return aliases.get(text, text)


def ingredient_search_terms(ingredient):
    variants = ingredient_match_variants(ingredient)
    terms = []
    seen = set()

    for variant in variants:
        term = clean_ingredient_search_text(variant)
        key = normalize_match_text(term)

        if term and key not in seen:
            seen.add(key)
            terms.append(term)

    fallback = clean_ingredient_search_text(ingredient)
    if fallback and not terms:
        terms.append(fallback)

    return terms[:4] or [clean_text(ingredient)]


def ingredient_match_variants(ingredient):
    text = clean_ingredient_search_text(ingredient)
    if not text:
        return []

    parts = [
        clean_ingredient_search_text(part)
        for part in INGREDIENT_ALTERNATIVE_PATTERN.split(text)
        if clean_ingredient_search_text(part)
    ]

    if len(parts) <= 1:
        return [text]

    return unique_texts(expand_alternative_parts(parts))


def expand_alternative_parts(parts):
    if len(parts) != 2:
        return parts

    left, right = parts
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)

    if 0 < len(left_tokens) <= 2 and len(right_tokens) > len(left_tokens):
        suffix_tokens = list(right_tokens)

        while suffix_tokens and suffix_tokens[0] in QUALIFIER_TOKENS:
            suffix_tokens.pop(0)

        if suffix_tokens and not set(suffix_tokens) & set(left_tokens):
            return [
                " ".join(left_tokens + suffix_tokens),
                right,
            ]

    return parts


def clean_ingredient_search_text(value):
    text = clean_text(value).replace("*", "")
    text = re.sub(r"\s+", " ", text).strip(" ,;")

    for pattern, replacement in GROCERY_QUERY_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    return clean_text(text)


def best_ingredient_candidate_match(ingredient, candidate):
    product_name = candidate.get("product_name", "")
    detail_text = " ".join([
        product_name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    normalized_name = normalize_match_text(product_name)
    product_tokens = set(tokenize(detail_text))
    name_tokens = set(tokenize(product_name))
    best = None

    for option in ingredient_match_variants(ingredient):
        ingredient_tokens = set(tokenize(option))
        normalized_ingredient = normalize_match_text(option)
        overlap = len(ingredient_tokens & product_tokens)
        name_overlap = len(ingredient_tokens & name_tokens)
        token_ratio = overlap / max(1, len(ingredient_tokens))
        name_token_ratio = name_overlap / max(1, len(ingredient_tokens))
        exact_name_match = bool(normalized_ingredient and normalized_ingredient == normalized_name)
        exact_phrase_match = bool(normalized_ingredient and normalized_ingredient in normalized_name)
        rank = (
            int(exact_name_match),
            int(exact_phrase_match),
            round(name_token_ratio, 4),
            round(token_ratio, 4),
            name_overlap,
            overlap,
        )
        current = {
            "ingredient": option,
            "ingredient_tokens": ingredient_tokens,
            "overlap": overlap,
            "token_ratio": token_ratio,
            "name_overlap": name_overlap,
            "name_token_ratio": name_token_ratio,
            "exact_name_match": exact_name_match,
            "exact_phrase_match": exact_phrase_match,
            "rank": rank,
        }

        if best is None or current["rank"] > best["rank"]:
            best = current

    if best:
        return best

    return {
        "ingredient": ingredient,
        "ingredient_tokens": set(tokenize(ingredient)),
        "overlap": 0,
        "token_ratio": 0,
        "name_overlap": 0,
        "name_token_ratio": 0,
        "exact_name_match": False,
        "exact_phrase_match": False,
        "rank": (0, 0, 0, 0, 0, 0),
    }


def normalize_match_text(value):
    return " ".join(tokenize(value))


def tokenize(text):
    return [
        TOKEN_ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) > 1 and token not in {"and", "or", "the", "with", "fresh", "whole"}
    ]


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def extract_zip_code(value):
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", str(value or ""))
    return match.group(0) if match else ""


def normalize_item_key(text):
    return " ".join(str(text or "").strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def unique_texts(values):
    seen = set()
    output = []

    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            output.append(text)
            seen.add(text)

    return output
