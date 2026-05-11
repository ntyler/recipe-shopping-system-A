"""
store_product_scraper.py

Scrapes store search pages and returns product candidates for a shopping item.

Designed to be called by app.py.

What this script does:
- Opens a store search page with undetected_chromedriver
- Extracts product candidates
- Prioritizes organic products
- Returns JSON only
- Loads editable stores from PushShoppingList/stores.json when available

What this script does NOT do:
- It does not prompt the user
- It does not save directly to the shopping list
- It does not buy anything or log into accounts

Returned product fields:
- product_name
- product_url
- product_location
- product_cost
- store
- query
- is_organic
- score

Examples:

    py -3.11 store_product_scraper.py --store meijer --item "broccoli florets"

    py -3.11 store_product_scraper.py --all-stores --item "carrots"

    py -3.11 store_product_scraper.py --store aldi --item "milk" --output product_candidates.json

Install requirements:

    pip install selenium beautifulsoup4 undetected-chromedriver
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup


CHROME_VERSION_MAIN = 147

SCRIPT_DIR = Path(__file__).resolve().parent

# app.py usually lives in PushShoppingList and stores.json is beside it.
# This scraper may be located either in PushShoppingList or project root.
STORE_JSON_CANDIDATES = [
    SCRIPT_DIR / "stores.json",
    SCRIPT_DIR / "PushShoppingList" / "stores.json",
]

DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "base_url": "https://www.aldi.us",
        "location": "Aldi",
        "order": 1,
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "base_url": "https://www.costco.com",
        "location": "Costco",
        "order": 2,
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "base_url": "https://www.kroger.com",
        "location": "Kroger",
        "order": 3,
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "base_url": "https://www.meijer.com",
        "location": "Meijer",
        "order": 4,
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "base_url": "https://www.target.com",
        "location": "Target",
        "order": 5,
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "base_url": "https://www.walmart.com",
        "location": "Walmart",
        "order": 6,
    },
}

STORE_PRODUCT_URL_PATTERNS = {
    "aldi": ["/products/", "/p/"],
    "costco": ["/.product.", "/p/", "/product/"],
    "kroger": ["/p/", "/product/"],
    "meijer": ["/shopping/product/", "/product/"],
    "target": ["/p/"],
    "walmart": ["/ip/"],
}

GENERIC_PRODUCT_URL_PATTERNS = [
    "/p/",
    "/product/",
    "/products/",
    "/ip/",
    "/shopping/product/",
    "/.product.",
]


def find_stores_file() -> Path | None:
    for candidate in STORE_JSON_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def normalize_store_search_url(url: str) -> str:
    """
    app.py stores URLs as prefixes like:
        https://www.costco.com/CatalogSearch?keyword=

    The scraper internally wants:
        https://www.costco.com/CatalogSearch?keyword={query}
    """
    url = str(url or "").strip()

    if not url:
        return ""

    if "{query}" in url:
        return url

    return url + "{query}"


def base_url_from_search_url(search_url: str) -> str:
    without_token = search_url.replace("{query}", "")
    parsed = urlparse(without_token)

    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"

    return ""


def sort_stores_alpha(stores: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return dict(
        sorted(
            stores.items(),
            key=lambda item: str(item[1].get("label") or item[0]).lower(),
        )
    )


def load_available_stores() -> dict[str, dict[str, Any]]:
    stores_file = find_stores_file()

    if stores_file:
        try:
            raw_stores = json.loads(stores_file.read_text(encoding="utf-8"))
        except Exception:
            raw_stores = DEFAULT_STORES.copy()
    else:
        raw_stores = DEFAULT_STORES.copy()

    if not isinstance(raw_stores, dict):
        raw_stores = DEFAULT_STORES.copy()

    cleaned: dict[str, dict[str, Any]] = {}

    for raw_key, raw_store in raw_stores.items():
        if not isinstance(raw_store, dict):
            continue

        store_key = str(raw_key or "").strip().lower()

        if not store_key:
            continue

        label = str(raw_store.get("label") or store_key.title()).strip()
        raw_url = raw_store.get("search_url") or raw_store.get("url") or ""
        search_url = normalize_store_search_url(raw_url)

        if not search_url:
            continue

        base_url = str(raw_store.get("base_url") or "").strip()

        if not base_url:
            base_url = base_url_from_search_url(search_url)

        cleaned[store_key] = {
            "label": label,
            "search_url": search_url,
            "base_url": base_url,
            "location": raw_store.get("location") or label,
            "order": raw_store.get("order", 999),
            "manual_only": bool(raw_store.get("manual_only", False)),
        }

    return sort_stores_alpha(cleaned or DEFAULT_STORES.copy())


AVAILABLE_STORES = load_available_stores()


@dataclass
class ProductResult:
    query: str
    store: str
    product_name: str | None
    product_url: str | None
    product_location: str | None
    product_cost: str | None
    is_organic: bool
    score: int


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def money_from_text(text: str) -> str | None:
    patterns = [
        r"\$\s?\d+(?:[.,]\d{2})?",
        r"\d+(?:[.,]\d{2})?\s?USD",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            return match.group(0).replace(" ", "")

    return None


def item_keywords(item: str) -> list[str]:
    stop_words = {
        "fresh",
        "whole",
        "chopped",
        "diced",
        "sliced",
        "large",
        "small",
        "medium",
        "organic",
        "optional",
        "finely",
        "roughly",
        "cups",
        "cup",
        "tbsp",
        "tsp",
        "tablespoon",
        "teaspoon",
        "oz",
        "ounce",
        "ounces",
        "lb",
        "lbs",
        "pound",
        "pounds",
        "package",
        "bag",
        "can",
        "canned",
        "and",
        "with",
        "for",
        "the",
    }

    words = re.findall(r"[a-zA-Z0-9]+", normalize_text(item))
    return [word for word in words if len(word) > 2 and word not in stop_words]


def score_product(query: str, name: str, url: str, price: str | None) -> tuple[int, bool]:
    name_norm = normalize_text(name)
    url_norm = normalize_text(url)
    query_norm = normalize_text(query)
    organic = "organic" in name_norm or "organic" in url_norm

    score = 0

    if organic:
        score += 1000

    keywords = item_keywords(query)

    for word in keywords:
        if word in name_norm:
            score += 80
        elif word in url_norm:
            score += 25

    # Produce equivalence boosts. This helps searches like
    # "fresh broccoli florets" find "Organic Broccoli Crown".
    produce_equivalents = {
        "broccoli": ["broccoli crown", "bunch broccoli", "broccoli florets", "organic broccoli"],
        "carrot": ["carrots", "whole carrots", "baby carrots", "organic carrots"],
        "carrots": ["carrot", "whole carrots", "baby carrots", "organic carrots"],
        "leek": ["leeks", "fresh leeks"],
        "leeks": ["leek", "fresh leeks"],
        "garlic": ["fresh garlic", "garlic bulb", "garlic cloves"],
    }

    for main_word, equivalents in produce_equivalents.items():
        if main_word in query_norm and main_word in name_norm:
            score += 120

        if main_word in query_norm:
            for equivalent in equivalents:
                if equivalent in name_norm:
                    score += 80
                    break

    unrelated_terms = [
        "cake",
        "cookie",
        "cookies",
        "chips",
        "snack",
        "candy",
        "sauce",
        "dressing",
        "seasoning",
        "mix",
        "frozen meal",
        "prepared",
        "baby food",
        "dog",
        "cat",
        "pet",
    ]

    for term in unrelated_terms:
        if term in name_norm:
            score -= 120

    if price:
        score += 20

    if name_norm:
        score += 5

    return score, organic


def make_search_url(store: str, item: str) -> str:
    store_info = AVAILABLE_STORES[store]
    return store_info["search_url"].format(query=quote_plus(item))


def init_driver(headless: bool = True):
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    driver = uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(45)
    return driver


def scroll_page(driver, scrolls: int = 6, delay: float = 1.0) -> None:
    for _ in range(scrolls):
        driver.execute_script("window.scrollBy(0, Math.max(500, document.body.scrollHeight / 3));")
        time.sleep(delay)


def safe_get_page_html(url: str, headless: bool = True, wait_seconds: float = 5.0):
    driver = init_driver(headless=headless)

    start_time = time.time()

    try:
        driver.get(url)
        time.sleep(wait_seconds)
        scroll_page(driver)
        time.sleep(1)

        load_time = round(time.time() - start_time, 2)

        return driver.page_source, load_time

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def absolute_url(href: str, store: str) -> str | None:
    if not href:
        return None

    href = href.strip()

    if href.startswith("javascript:"):
        return None

    if href.startswith("#"):
        return None

    base_url = AVAILABLE_STORES.get(store, {}).get("base_url", "")
    return urljoin(base_url, href)


def looks_like_product_url(url: str | None, store: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()

    patterns = STORE_PRODUCT_URL_PATTERNS.get(store) or GENERIC_PRODUCT_URL_PATTERNS
    return any(pattern in path for pattern in patterns)


def clean_name(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()

    junk_phrases = [
        "sponsored",
        "add to cart",
        "add",
        "pickup",
        "delivery",
        "shipping",
        "in stock",
        "out of stock",
        "current price",
        "price",
        "each",
        "shop now",
    ]

    for phrase in junk_phrases:
        text = re.sub(rf"\b{re.escape(phrase)}\b", "", text, flags=re.I)

    text = re.sub(r"\s+", " ", text).strip(" -|•")
    return text


def extract_product_cards_generic(html: str, store: str, query: str) -> list[ProductResult]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[ProductResult] = []
    seen_urls: set[str] = set()

    for link in soup.find_all("a", href=True):
        product_url = absolute_url(link.get("href", ""), store)

        if not looks_like_product_url(product_url, store):
            continue

        if product_url in seen_urls:
            continue

        seen_urls.add(product_url)

        card = link

        for _ in range(6):
            if card.parent:
                card = card.parent
            else:
                break

            card_text = clean_name(card.get_text(" ", strip=True))

            if money_from_text(card_text) or len(card_text) > 40:
                break

        link_text = clean_name(link.get_text(" ", strip=True))
        card_text = clean_name(card.get_text(" ", strip=True))

        product_name = link_text

        if not product_name or len(product_name) < 3:
            product_name = guess_product_name_from_card(card_text, query)

        product_cost = money_from_text(card_text)
        score, organic = score_product(
            query,
            product_name or "",
            product_url or "",
            product_cost,
        )

        candidates.append(
            ProductResult(
                query=query,
                store=store,
                product_name=product_name or None,
                product_url=product_url,
                product_location=AVAILABLE_STORES.get(store, {}).get("location", store.title()),
                product_cost=product_cost,
                is_organic=organic,
                score=score,
            )
        )

    return dedupe_and_sort(candidates)


def guess_product_name_from_card(card_text: str, query: str) -> str | None:
    if not card_text:
        return None

    chunks = re.split(
        r"(\$\s?\d+(?:[.,]\d{2})?|add to cart|pickup|delivery|shipping|sponsored)",
        card_text,
        flags=re.I,
    )

    keywords = item_keywords(query)
    best_chunk = ""

    for chunk in chunks:
        chunk = clean_name(chunk)

        if len(chunk) < 3:
            continue

        if any(word in normalize_text(chunk) for word in keywords):
            if not best_chunk or len(chunk) < len(best_chunk):
                best_chunk = chunk

    if best_chunk:
        return best_chunk[:180]

    return clean_name(card_text[:180]) or None


def dedupe_and_sort(products: list[ProductResult]) -> list[ProductResult]:
    deduped: dict[str, ProductResult] = {}

    for product in products:
        key = product.product_url or normalize_text(product.product_name)

        if not key:
            continue

        if key not in deduped or product.score > deduped[key].score:
            deduped[key] = product

    return sorted(
        deduped.values(),
        key=lambda product: product.score,
        reverse=True,
    )


def scrape_store_product(
    store: str,
    item: str,
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_results: int = 10,
) -> dict[str, Any]:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    store = str(store or "").strip().lower()

    if store not in AVAILABLE_STORES:
        return {
            "ok": False,
            "error": f"Unknown store: {store}",
            "available_stores": list(AVAILABLE_STORES.keys()),
        }

    search_url = make_search_url(store, item)

    try:
        html, load_time = safe_get_page_html(
            search_url,
            headless=headless,
            wait_seconds=wait_seconds,
        )

        products = extract_product_cards_generic(html, store, item)
        products = products[:max_results]

        best = products[0] if products else None

        return {
            "ok": True,
            "query": item,
            "store": store,
            "search_url": search_url,
            "load_time": load_time,
            "best_match": asdict(best) if best else None,
            "results": [asdict(product) for product in products],
        }

    except Exception as exc:
        return {
            "ok": False,
            "query": item,
            "store": store,
            "search_url": search_url,
            "load_time": round(time.time() - start_time, 2),
            "error": str(exc),
        }


def scrape_all_stores(
    item: str,
    stores: list[str] | None = None,
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_results: int = 10,
) -> dict[str, Any]:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    if stores:
        stores = [str(store).strip().lower() for store in stores if str(store).strip().lower() in AVAILABLE_STORES]
    else:
        stores = sorted(
            AVAILABLE_STORES.keys(),
            key=lambda store: (
                str(AVAILABLE_STORES[store].get("label") or store).lower(),
                AVAILABLE_STORES[store].get("order", 999),
            ),
        )

    store_results = []

    for store in stores:
        result = scrape_store_product(
            store=store,
            item=item,
            headless=headless,
            wait_seconds=wait_seconds,
            max_results=max_results,
        )
        store_results.append(result)

    best_matches = [
        result.get("best_match")
        for result in store_results
        if result.get("ok") and result.get("best_match")
    ]

    best_matches = sorted(
        best_matches,
        key=lambda product: product.get("score", 0),
        reverse=True,
    )

    return {
        "ok": True,
        "query": item,
        "best_overall": best_matches[0] if best_matches else None,
        "stores": store_results,
    }


def flatten_results(scrape_result: dict[str, Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []

    if scrape_result.get("results"):
        flattened.extend(scrape_result.get("results") or [])

    for store_result in scrape_result.get("stores", []):
        flattened.extend(store_result.get("results") or [])

    seen = set()
    unique = []

    for product in flattened:
        key = product.get("product_url") or normalize_text(product.get("product_name"))

        if not key or key in seen:
            continue

        seen.add(key)
        unique.append(product)

    return sorted(
        unique,
        key=lambda product: product.get("score", 0),
        reverse=True,
    )


def update_output_file(output_file: Path, item: str, scrape_result: dict[str, Any]) -> None:
    if output_file.exists():
        try:
            data = json.loads(output_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}

    item_key = normalize_text(item)
    data[item_key] = scrape_result

    output_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run_internal_test() -> None:
##    result = scrape_store_product(
##        store="meijer",
##        item="organic carrots",
##        headless=False,
##        wait_seconds=5,
##        max_results=5,
##    )
    
    result = scrape_store_product(
        store="meijer",
        item="fresh broccoli florets",
        headless=False,
        wait_seconds=5,
        max_results=5,
    )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> int:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    parser = argparse.ArgumentParser(
        description="Scrape store search pages and return product result URLs."
    )

    parser.add_argument("--item", required=True, help="Shopping item to search for.")

    parser.add_argument(
        "--store",
        choices=list(AVAILABLE_STORES.keys()),
        help="Store to search."
    )

    parser.add_argument(
        "--all-stores",
        action="store_true",
        help="Search all supported stores."
    )

    parser.add_argument(
        "--stores",
        nargs="*",
        choices=list(AVAILABLE_STORES.keys()),
        help="Optional list of stores to search with --all-stores."
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window instead of headless mode."
    )

    parser.add_argument(
        "--wait",
        type=float,
        default=5.0,
        help="Seconds to wait after page load."
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum results returned per store."
    )

    parser.add_argument(
        "--output",
        help="Optional JSON file to update with scrape results."
    )

    args = parser.parse_args()

    if not args.store and not args.all_stores:
        parser.error("Use --store STORE or --all-stores")

    if args.all_stores:
        result = scrape_all_stores(
            item=args.item,
            stores=args.stores,
            headless=not args.headed,
            wait_seconds=args.wait,
            max_results=args.max_results,
        )
    else:
        result = scrape_store_product(
            store=args.store,
            item=args.item,
            headless=not args.headed,
            wait_seconds=args.wait,
            max_results=args.max_results,
        )

    if args.output:
        update_output_file(Path(args.output), args.item, result)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1:
        run_internal_test()
    else:
        raise SystemExit(main())
