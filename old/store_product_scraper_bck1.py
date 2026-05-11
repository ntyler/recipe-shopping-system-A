"""
store_product_scraper.py

Scrapes store search pages and product URLs.

Examples:

    py -3.11 store_product_scraper.py --store meijer --item "broccoli florets"

    py -3.11 store_product_scraper.py --all-stores --item "carrots" --headed

    py -3.11 store_product_scraper.py --all-stores --item "carrots" --parallel-stores --workers 4 --headed

    py -3.11 store_product_scraper.py --url-file product_urls.txt --workers 4 --headed --max-results 10 --output scraped_products.json
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass
from multiprocessing import cpu_count
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote_plus, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
import undetected_chromedriver as uc


CHROME_VERSION_MAIN = 147

SCRIPT_DIR = Path(__file__).resolve().parent

STORE_JSON_CANDIDATES = [
    SCRIPT_DIR / "stores.json",
    SCRIPT_DIR / "shopping_stores.json",
    SCRIPT_DIR / "PushShoppingList" / "stores.json",
    SCRIPT_DIR / "PushShoppingList" / "shopping_stores.json",
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


# =========================================================
# STORE CONFIG
# =========================================================

def find_stores_file() -> Path | None:
    for candidate in STORE_JSON_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def normalize_store_search_url(url: str) -> str:
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


# =========================================================
# DATA MODEL
# =========================================================

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


# =========================================================
# TEXT / SCORING
# =========================================================

def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


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


def money_from_text(text: str) -> str | None:
    patterns = [
        r"\$\s?\d+(?:[.,]\d{2})?",
        r"\d+(?:[.,]\d{2})?\s?USD",
    ]

    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.I)

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

    for word in item_keywords(query):
        if word in name_norm:
            score += 80
        elif word in url_norm:
            score += 25

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


# =========================================================
# CHROME HELPERS
# =========================================================

def get_chrome_major_version() -> int:
    try:
        result = subprocess.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True,
        ).decode(errors="ignore")

        version = re.search(r"\d+\.\d+\.\d+\.\d+", result).group(0)
        return int(version.split(".")[0])

    except Exception as exc:
        print(f"Could not detect Chrome version. Using fallback {CHROME_VERSION_MAIN}. Error: {exc}")
        return CHROME_VERSION_MAIN


def get_screen_size() -> tuple[int, int]:
    try:
        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return width, height
    except Exception:
        return 1600, 900


def tile_driver_window(driver, worker_id: int, num_workers: int) -> None:
    try:
        screen_width, screen_height = get_screen_size()
        screen_height -= 80

        if num_workers == 8:
            cols = 4
            rows = 2
        else:
            cols = math.ceil(math.sqrt(num_workers))
            rows = math.ceil(num_workers / cols)

        window_width = max(500, screen_width // cols)
        window_height = max(500, screen_height // rows)

        col = worker_id % cols
        row = worker_id // cols

        x = col * window_width
        y = row * window_height

        driver.set_window_rect(
            x=x,
            y=y,
            width=window_width,
            height=window_height,
        )
    except Exception as exc:
        print(f"[Worker {worker_id}] Could not tile window: {exc}")


def init_driver(
    headless: bool = True,
    worker_id: int = 0,
    num_workers: int = 1,
):
    options = uc.ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")

    chrome_version = get_chrome_major_version()

    last_error = None

    for attempt in range(1, 4):
        try:
            print(f"[Worker {worker_id}] Starting undetected Chrome attempt {attempt}/3")

            driver = uc.Chrome(
                options=options,
                headless=headless,
                use_subprocess=True,
                version_main=chrome_version or CHROME_VERSION_MAIN,
            )

            driver.set_page_load_timeout(45)

            if not headless:
                tile_driver_window(driver, worker_id, num_workers)

            print(f"[Worker {worker_id}] Chrome started successfully")
            return driver

        except Exception as exc:
            last_error = exc
            print(f"[Worker {worker_id}] Chrome failed attempt {attempt}/3: {exc}")
            time.sleep(3)

    raise RuntimeError(
        f"[Worker {worker_id}] Could not start Chrome after 3 attempts: {last_error}"
    )


def scroll_page(driver, scrolls: int = 6, delay: float = 1.0) -> None:
    for _ in range(scrolls):
        driver.execute_script(
            "window.scrollBy(0, Math.max(500, document.body.scrollHeight / 3));"
        )
        time.sleep(delay)


def safe_get_page_html(
    url: str,
    headless: bool = True,
    wait_seconds: float = 5.0,
    worker_id: int = 0,
    num_workers: int = 1,
):
    driver = init_driver(
        headless=headless,
        worker_id=worker_id,
        num_workers=num_workers,
    )

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


# =========================================================
# URL HELPERS
# =========================================================

def make_search_url(store: str, item: str) -> str:
    store_info = AVAILABLE_STORES[store]
    return store_info["search_url"].format(query=quote_plus(item))


def absolute_url(href: str, store: str) -> str | None:
    if not href:
        return None

    href = href.strip()

    if href.startswith("javascript:") or href.startswith("#"):
        return None

    base_url = AVAILABLE_STORES.get(store, {}).get("base_url", "")

    if not base_url:
        return href

    return urljoin(base_url, href)


def looks_like_product_url(url: str | None, store: str) -> bool:
    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()

    patterns = STORE_PRODUCT_URL_PATTERNS.get(store) or GENERIC_PRODUCT_URL_PATTERNS
    return any(pattern in path for pattern in patterns)


def infer_store_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()

    if "aldi" in host:
        return "aldi"
    if "costco" in host:
        return "costco"
    if "kroger" in host:
        return "kroger"
    if "meijer" in host:
        return "meijer"
    if "target" in host:
        return "target"
    if "walmart" in host:
        return "walmart"

    return "manual"


def search_query_from_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    for key in ["text", "query", "q", "searchTerm", "keyword", "k"]:
        values = params.get(key)
        if values:
            return unquote_plus(values[0]).strip()

    return url


# =========================================================
# PRODUCT EXTRACTION
# =========================================================

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


def extract_direct_product_page(
    html: str,
    url: str,
    store: str,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    title = soup.find("title")
    page_title = clean_name(title.get_text(" ", strip=True)) if title else None

    h1 = soup.find("h1")
    h1_text = clean_name(h1.get_text(" ", strip=True)) if h1 else None

    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_title_text = None

    if og_title and og_title.get("content"):
        og_title_text = clean_name(og_title.get("content"))

    text = clean_name(soup.get_text(" ", strip=True))
    price = money_from_text(text)

    product_name = h1_text or og_title_text or page_title

    return {
        "store": store,
        "product_name": product_name,
        "product_url": url,
        "product_cost": price,
    }


# =========================================================
# STORE SEARCH MODE
# =========================================================

def scrape_store_product(
    store: str,
    item: str,
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_results: int = 10,
) -> dict[str, Any]:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    start_time = time.time()
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


def scrape_store_product_with_driver(
    driver,
    store: str,
    item: str,
    wait_seconds: float = 5.0,
    max_results: int = 10,
    worker_id: int = 0,
) -> dict[str, Any]:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    start_time = time.time()
    store = str(store or "").strip().lower()

    if store not in AVAILABLE_STORES:
        return {
            "ok": False,
            "query": item,
            "store": store,
            "error": f"Unknown store: {store}",
            "available_stores": list(AVAILABLE_STORES.keys()),
            "worker": worker_id,
        }

    search_url = make_search_url(store, item)

    try:
        driver.execute_script(f"document.title = 'Worker {worker_id} - {store}'")
    except Exception:
        pass

    try:
        driver.get(search_url)
        time.sleep(wait_seconds)
        scroll_page(driver)
        time.sleep(1)

        load_time = round(time.time() - start_time, 2)

        products = extract_product_cards_generic(driver.page_source, store, item)
        products = products[:max_results]

        best = products[0] if products else None

        return {
            "ok": True,
            "worker": worker_id,
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
            "worker": worker_id,
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
        stores = [
            str(store).strip().lower()
            for store in stores
            if str(store).strip().lower() in AVAILABLE_STORES
        ]
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


# =========================================================
# URL-FILE WORKER QUEUE MODE
# =========================================================

def scrape_product_url_with_driver(
    driver,
    url: str,
    store: str = "auto",
    wait_seconds: float = 5.0,
    worker_id: int = 0,
    max_results: int = 10,
) -> dict[str, Any]:
    start_time = time.time()
    url = str(url or "").strip()

    if not store or store == "auto":
        store = infer_store_from_url(url)

    query_text = search_query_from_url(url)

    try:
        try:
            driver.execute_script(f"document.title = 'Worker {worker_id} - {store}'")
        except Exception:
            pass

        driver.get(url)
        time.sleep(wait_seconds)
        scroll_page(driver)
        time.sleep(1)

        load_time = round(time.time() - start_time, 2)
        html = driver.page_source

        products = extract_product_cards_generic(
            html=html,
            store=store,
            query=query_text,
        )

        products = products[:max_results]
        best = products[0] if products else None

        product_data = extract_direct_product_page(
            html=html,
            url=url,
            store=store,
        )

        return {
            "ok": True,
            "worker": worker_id,
            "url": url,
            "store": store,
            "query": query_text,
            "load_time": load_time,
            "best_match": asdict(best) if best else None,
            "results": [asdict(product) for product in products],
            "product_name": product_data.get("product_name"),
            "product_url": product_data.get("product_url"),
            "product_cost": product_data.get("product_cost"),
        }

    except Exception as exc:
        return {
            "ok": False,
            "worker": worker_id,
            "url": url,
            "store": store,
            "query": query_text,
            "load_time": round(time.time() - start_time, 2),
            "error": str(exc),
        }


def worker_loop(
    worker_id: int,
    num_workers: int,
    task_queue: queue.Queue,
    results: list[dict[str, Any]],
    results_lock: threading.Lock,
    headless: bool,
    wait_seconds: float,
    max_results: int,
):
    driver = None

    try:
        driver = init_driver(
            headless=headless,
            worker_id=worker_id,
            num_workers=num_workers,
        )

        print(f"[Worker {worker_id}] started")

        while True:
            job = task_queue.get()

            if job == "STOP":
                print(f"[Worker {worker_id}] stopping")
                task_queue.task_done()
                break

            mode = job.get("mode")

            try:
                if mode == "product_url":
                    url = job["url"]
                    print(f"[Worker {worker_id}] URL: {url}")

                    result = scrape_product_url_with_driver(
                        driver=driver,
                        url=url,
                        store=job.get("store", "auto"),
                        wait_seconds=wait_seconds,
                        worker_id=worker_id,
                        max_results=max_results,
                    )

                elif mode == "store_search":
                    store = job["store"]
                    item = job["item"]
                    print(f"[Worker {worker_id}] Store search: {store} | {item}")

                    result = scrape_store_product_with_driver(
                        driver=driver,
                        store=store,
                        item=item,
                        wait_seconds=wait_seconds,
                        max_results=max_results,
                        worker_id=worker_id,
                    )

                else:
                    result = {
                        "ok": False,
                        "worker": worker_id,
                        "error": f"Unknown job mode: {mode}",
                        "job": job,
                    }

            except Exception as exc:
                result = {
                    "ok": False,
                    "worker": worker_id,
                    "error": str(exc),
                    "job": job,
                }

            with results_lock:
                results.append(result)

            status = "✅" if result.get("ok") else "❌"
            print(f"{status} [Worker {worker_id}] finished")

            task_queue.task_done()

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def run_worker_queue(
    jobs: list[dict[str, Any]],
    workers: int = 4,
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_results: int = 10,
) -> dict[str, Any]:
    if not jobs:
        return {
            "ok": False,
            "mode": "worker_queue",
            "total": 0,
            "workers": 0,
            "results": [],
            "error": "No jobs to process.",
        }

    max_cpu_workers = cpu_count()
    workers = max(1, min(int(workers or 1), max_cpu_workers, len(jobs)))

    task_queue: queue.Queue = queue.Queue()
    results: list[dict[str, Any]] = []
    results_lock = threading.Lock()

    for job in jobs:
        task_queue.put(job)

    for _ in range(workers):
        task_queue.put("STOP")

    threads = []

    for worker_id in range(workers):
        thread = threading.Thread(
            target=worker_loop,
            args=(
                worker_id,
                workers,
                task_queue,
                results,
                results_lock,
                headless,
                wait_seconds,
                max_results,
            ),
            daemon=False,
        )

        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    return {
        "ok": True,
        "mode": "worker_queue",
        "total": len(jobs),
        "workers": workers,
        "results": results,
    }


def scrape_url_list_parallel(
    urls: list[str],
    store: str = "auto",
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_workers: int = 4,
    max_results: int = 10,
) -> dict[str, Any]:
    cleaned_urls = [
        str(url).strip()
        for url in urls
        if str(url or "").strip().startswith("http")
    ]

    jobs = [
        {
            "mode": "product_url",
            "url": url,
            "store": store or "auto",
        }
        for url in cleaned_urls
    ]

    result = run_worker_queue(
        jobs=jobs,
        workers=max_workers,
        headless=headless,
        wait_seconds=wait_seconds,
        max_results=max_results,
    )

    result["mode"] = "url_file_worker_queue"
    return result


def scrape_store_searches_parallel(
    item: str,
    stores: list[str],
    headless: bool = True,
    wait_seconds: float = 5.0,
    max_workers: int = 4,
    max_results: int = 10,
) -> dict[str, Any]:
    jobs = [
        {
            "mode": "store_search",
            "store": store,
            "item": item,
        }
        for store in stores
    ]

    result = run_worker_queue(
        jobs=jobs,
        workers=max_workers,
        headless=headless,
        wait_seconds=wait_seconds,
        max_results=max_results,
    )

    store_results = result.get("results", [])

    best_matches = [
        store_result.get("best_match")
        for store_result in store_results
        if store_result.get("ok") and store_result.get("best_match")
    ]

    best_matches = sorted(
        best_matches,
        key=lambda product: product.get("score", 0),
        reverse=True,
    )

    return {
        "ok": True,
        "mode": "store_search_worker_queue",
        "query": item,
        "workers": result.get("workers", 0),
        "best_overall": best_matches[0] if best_matches else None,
        "stores": store_results,
    }


# =========================================================
# OUTPUT HELPERS
# =========================================================

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


# =========================================================
# TEST / MAIN
# =========================================================

def run_internal_test() -> None:
    print("\n==============================")
    print("🚀 SEQUENTIAL WORKER TEST")
    print("==============================\n")

    test_urls = [
        "https://www.meijer.com/shopping/search.html?text=broccoli%20florets",
        "https://www.meijer.com/shopping/search.html?text=carrots",
        "https://www.meijer.com/shopping/search.html?text=garlic",
        "https://www.meijer.com/shopping/search.html?text=onion",
        "https://www.meijer.com/shopping/search.html?text=spinach",
        "https://www.meijer.com/shopping/search.html?text=zucchini",
        "https://www.meijer.com/shopping/search.html?text=leeks",
        "https://www.meijer.com/shopping/search.html?text=potatoes",
    ]

    result = scrape_url_list_parallel(
        urls=test_urls,
        store="auto",
        headless=False,
        wait_seconds=5,
        max_workers=2,
        max_results=10,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> int:
    global AVAILABLE_STORES
    AVAILABLE_STORES = load_available_stores()

    parser = argparse.ArgumentParser(
        description="Scrape store search pages and product result URLs."
    )

    parser.add_argument("--item", help="Shopping item to search for.")

    parser.add_argument(
        "--store",
        choices=list(AVAILABLE_STORES.keys()) + ["auto", "manual"],
        help="Store to search.",
    )

    parser.add_argument(
        "--all-stores",
        action="store_true",
        help="Search all supported stores.",
    )

    parser.add_argument(
        "--stores",
        nargs="*",
        choices=list(AVAILABLE_STORES.keys()),
        help="Optional list of stores to search with --all-stores.",
    )

    parser.add_argument(
        "--url-file",
        help="Text file containing one product URL per line.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of Chrome worker windows.",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser windows instead of headless mode.",
    )

    parser.add_argument(
        "--wait",
        type=float,
        default=5.0,
        help="Seconds to wait after page load.",
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum results returned per store/search URL.",
    )

    parser.add_argument(
        "--output",
        help="Optional JSON file to update/write scrape results.",
    )

    parser.add_argument(
        "--parallel-stores",
        action="store_true",
        help="Use worker queue for --all-stores store search mode.",
    )

    args = parser.parse_args()
    headless = not args.headed

    if args.url_file:
        url_file = Path(args.url_file)

        if not url_file.exists():
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"URL file not found: {url_file}",
                    },
                    indent=2,
                )
            )
            return 1

        urls = [
            line.strip()
            for line in url_file.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("http")
        ]

        result = scrape_url_list_parallel(
            urls=urls,
            store=args.store or "auto",
            headless=headless,
            wait_seconds=args.wait,
            max_workers=args.workers,
            max_results=args.max_results,
        )

        if args.output:
            Path(args.output).write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if not args.item:
        parser.error("Use --item ITEM, or use --url-file product_urls.txt")

    if not args.store and not args.all_stores:
        parser.error("Use --store STORE, --all-stores, or --url-file")

    if args.all_stores:
        if args.stores:
            stores = [
                str(store).strip().lower()
                for store in args.stores
                if str(store).strip().lower() in AVAILABLE_STORES
            ]
        else:
            stores = sorted(
                AVAILABLE_STORES.keys(),
                key=lambda store: (
                    str(AVAILABLE_STORES[store].get("label") or store).lower(),
                    AVAILABLE_STORES[store].get("order", 999),
                ),
            )

        if args.parallel_stores:
            result = scrape_store_searches_parallel(
                item=args.item,
                stores=stores,
                headless=headless,
                wait_seconds=args.wait,
                max_workers=args.workers,
                max_results=args.max_results,
            )
        else:
            result = scrape_all_stores(
                item=args.item,
                stores=stores,
                headless=headless,
                wait_seconds=args.wait,
                max_results=args.max_results,
            )

    else:
        if args.store in {"auto", "manual"}:
            parser.error("--store auto/manual is only for --url-file mode")

        result = scrape_store_product(
            store=args.store,
            item=args.item,
            headless=headless,
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
