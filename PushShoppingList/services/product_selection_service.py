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

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.item_state_service import save_item_store
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


def product_worker_count(total_downloads=None):
    try:
        configured = int(os.getenv("PRODUCT_SEARCH_WORKERS", "6"))
    except (TypeError, ValueError):
        configured = 6

    configured = max(1, min(16, configured))

    if total_downloads:
        return max(1, min(configured, int(total_downloads)))

    return configured


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


def product_choice_for_item(item_key):
    return product_choices_by_item().get(normalize_item_key(item_key), {})


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
                        "ingredient": download.get("ingredient", ""),
                        "store_key": download.get("store_key", ""),
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
        for store_key in enabled_stores:
            store = stores.get(store_key, {})
            store_name = store.get("label") or store_key.title()
            search_url = build_product_search_url(store, ingredient)
            downloads.append({
                "index": len(downloads),
                "ingredient": ingredient,
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

    if not search_url:
        message = f"{store_name}: no product search URL is configured."
        if job_id:
            mark_product_download(job_id, index, "skipped", message, candidates_count=0)
        return {
            "ingredient": ingredient,
            "store_key": store_key,
            "candidates": [],
            "skip_reasons": [message],
        }

    if job_id:
        mark_product_download(
            job_id,
            index,
            "running",
            f"Downloading {store_name} search results for {ingredient}...",
        )

    try:
        candidates, skip_reasons = search_store_products(
            ingredient,
            store_key,
            store,
            full_address,
            home_location,
            store_locations.get(store_key, {}),
        )
    except Exception as exc:
        candidates = []
        skip_reasons = [f"{store_name}: product search failed: {exc}"]

    direct_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
    )
    failed = any("product search failed" in str(reason).lower() for reason in skip_reasons)

    if direct_count:
        state = "done"
        message = f"Downloaded {direct_count} product candidate(s) from {store_name}."
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
        "ingredient": ingredient,
        "store_key": store_key,
        "candidates": candidates,
        "skip_reasons": skip_reasons,
    }


def build_product_choice_record_from_results(ingredient, store_results, full_address):
    candidates = []
    skip_reasons = []

    for result in store_results:
        candidates.extend(result.get("candidates", []))
        skip_reasons.extend(result.get("skip_reasons", []))

    candidates = rank_product_candidates(ingredient, candidates)
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
        "candidates": candidates,
        "skip_reasons": unique_texts(skip_reasons),
        "updated_at": now,
    }


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


def search_store_products(
    ingredient,
    store_key,
    store,
    full_address,
    home_location,
    store_location,
):
    store_name = store.get("label") or store_key.title()
    search_url = build_product_search_url(store, ingredient)
    skip_reasons = []

    if not search_url:
        return [], [f"{store_name}: no product search URL is configured."]

    try:
        response = requests.get(
            search_url,
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
    except Exception as exc:
        fallback = build_search_page_candidate(
            ingredient,
            store_key,
            store_name,
            search_url,
            full_address,
            store_location,
            f"Product page could not be fetched: {exc}",
        )
        return [fallback], [f"{store_name}: product search failed: {exc}"]

    candidates = parse_product_candidates_from_html(
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

    if candidates:
        return candidates, []

    fallback = build_search_page_candidate(
        ingredient,
        store_key,
        store_name,
        response.url or search_url,
        full_address,
        store_location,
        "No product cards with prices could be parsed from this store page.",
    )
    return [fallback], [f"{store_name}: no parseable product cards were found."]


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

    if len(candidates) < 8:
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
                if len(candidates) >= 12:
                    break

    if len(candidates) < 8:
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

    return dedupe_candidates(candidates)[:12]


def extract_json_ld_products(soup):
    products = []

    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text("", strip=True)
        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=True))

    return products


def extract_embedded_product_mappings(soup):
    products = []

    for script in soup.find_all("script"):
        text = script.string or script.get_text("", strip=True)

        if not text or len(text) > 1_500_000:
            continue

        lowered = text.lower()
        if "price" not in lowered or ("product" not in lowered and "name" not in lowered):
            continue

        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=False))

        if len(products) >= 20:
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

        if len(candidates) >= 10:
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
        "product_name": product_name,
        "price": price,
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
    ingredient_tokens = set(tokenize(ingredient))
    product_tokens = set(tokenize(product_name))
    overlap = len(ingredient_tokens & product_tokens)
    token_ratio = overlap / max(1, len(ingredient_tokens))

    score += token_ratio * 35
    if token_ratio:
        reasons.append(f"Matches {overlap} ingredient term(s).")
    else:
        score -= 25
        skip_reasons.append("Product name does not clearly match the ingredient.")

    food_status = candidate.get("food_rule_status") or {}
    if food_status.get("blocked_by"):
        score -= 100
        viable = False
        skip_reasons.append("Blocked by food rules: " + "; ".join(food_status.get("blocked_by", [])))
    elif not food_status.get("missing_required"):
        score += 20
        reasons.append("Matches required food preferences.")
    else:
        score -= 12 * len(food_status.get("missing_required", []))
        skip_reasons.append("Missing preference: " + "; ".join(food_status.get("missing_required", [])))

    if candidate.get("price"):
        score += 10
        reasons.append("Has a visible price.")
    else:
        score -= 8
        skip_reasons.append("Price was not visible in the parsed store page.")

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


def select_product_choice(item_key, product_id):
    item_key = normalize_item_key(item_key)
    product_id = str(product_id or "").strip()
    state = load_product_choices()
    record = state.get("items", {}).get(item_key)

    if not record:
        return {
            "ok": False,
            "error": "No product choices were saved for that ingredient.",
        }

    selected = next(
        (candidate for candidate in record.get("candidates", []) if candidate.get("id") == product_id),
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

    record["selected_product_id"] = product_id
    record["selected_product"] = selected
    record["manual_override"] = True
    record["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    save_product_choices(state)
    save_item_store(item_key, selected.get("store_key") or "")

    return {
        "ok": True,
        "item_key": item_key,
        "choice": record,
    }


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


def tokenize(text):
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) > 1 and token not in {"and", "or", "the", "with", "fresh", "whole"}
    ]


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


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
