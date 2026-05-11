# grab_best_products.py
# ---------------------------------------------------------
# Isolated Grab Best Products worker for PushShoppingList.
#
# app.py should handle:
#   - Flask routes
#   - UI popup / polling
#   - job dictionary updates
#
# This file handles:
#   - finding selected-store ingredients
#   - building scraper URL lists BEFORE scraping
#   - calling store_product_scraper.py with a list of URLs
#   - normalizing product results
# ---------------------------------------------------------

from pathlib import Path
import json
import sys
import requests
import traceback

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

for import_path in [BASE_DIR, PROJECT_ROOT]:
    import_path_text = str(import_path)
    if import_path_text not in sys.path:
        sys.path.insert(0, import_path_text)

try:
    from store_product_scraper import run_scraper
except Exception as import_error:
    run_scraper = None
    print(f"Could not import run_scraper from store_product_scraper.py: {import_error}")


SHOPPING_LIST_FILE = BASE_DIR / "shopping_list.txt"
ITEM_SOURCES_FILE = BASE_DIR / "shopping_item_sources.json"
ITEM_STATE_FILE = BASE_DIR / "shopping_item_state.json"
STORE_SETTINGS_FILE = BASE_DIR / "shopping_store_settings.json"
STORES_FILE = BASE_DIR / "shopping_stores.json"
PRODUCT_CHOICES_FILE = BASE_DIR / "shopping_product_choices.json"

DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k="
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query="
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q="
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text="
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm="
    }
}


def normalize(text):
    return " ".join(str(text or "").strip().lower().split())


def normalize_store_key(text):
    text = str(text or "").strip().lower()
    allowed = []

    for char in text:
        if char.isalnum():
            allowed.append(char)
        elif char in [" ", "-", "_"]:
            allowed.append("_")

    key = "".join(allowed)

    while "__" in key:
        key = key.replace("__", "_")

    return key.strip("_")


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def read_json(path, default):
    if not path.exists():
        return default

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default


def write_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def load_items():
    if not SHOPPING_LIST_FILE.exists():
        return []

    return [
        line.strip()
        for line in SHOPPING_LIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not is_section_header(line)
    ]


def load_item_state():
    data = read_json(ITEM_STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def load_item_sources():
    data = read_json(ITEM_SOURCES_FILE, {})
    return data if isinstance(data, dict) else {}


def save_item_sources(data):
    write_json(ITEM_SOURCES_FILE, data if isinstance(data, dict) else {})


def load_product_choices():
    data = read_json(PRODUCT_CHOICES_FILE, {})
    return data if isinstance(data, dict) else {}


def save_product_choices(data):
    write_json(PRODUCT_CHOICES_FILE, data if isinstance(data, dict) else {})


def load_all_stores():
    data = read_json(STORES_FILE, None)

    if not isinstance(data, dict) or not data:
        return DEFAULT_STORES.copy()

    cleaned = {}

    for raw_key, raw_store in data.items():
        key = normalize_store_key(raw_key)

        if not key or not isinstance(raw_store, dict):
            continue

        label = str(raw_store.get("label") or key.title()).strip()
        url = str(raw_store.get("url") or "").strip()

        if label and url:
            cleaned[key] = {"label": label, "url": url}

    return cleaned or DEFAULT_STORES.copy()


def get_source_list_for_item(item, item_sources=None):
    item_sources = item_sources or load_item_sources()
    item_key = normalize(item)
    sources = item_sources.get(item_key, [])

    if isinstance(sources, str):
        sources = [{"url": sources}]

    if isinstance(sources, dict):
        sources = [sources]

    return sources if isinstance(sources, list) else []


def item_has_selected_product(item, item_sources=None):
    for source in get_source_list_for_item(item, item_sources):
        if isinstance(source, dict) and (
            source.get("source_type") == "product"
            or source.get("product_url")
        ):
            return True

    return False


def get_selected_store_for_item(item, item_state=None):
    item_state = item_state or load_item_state()
    item_key = normalize(item)
    state = item_state.get(item_key, {})

    if not isinstance(state, dict):
        return None

    selected_store = state.get("store")
    stores = load_all_stores()

    if selected_store in stores:
        return selected_store

    return None


def get_grabbable_product_items(skip_existing=True):
    items = load_items()
    item_state = load_item_state()
    item_sources = load_item_sources()
    grabbable = []

    for item in items:
        selected_store = get_selected_store_for_item(item, item_state)

        if not selected_store:
            continue

        if skip_existing and item_has_selected_product(item, item_sources):
            continue

        grabbable.append(item)

    return grabbable


def build_store_search_details(item, selected_store=None):
    selected_store = selected_store or get_selected_store_for_item(item)

    if not selected_store:
        return None, None

    stores = load_all_stores()
    store_info = stores.get(selected_store, {})
    base_url = store_info.get("url", "")
    store_label = store_info.get("label", selected_store.title())

    if not base_url:
        return None, f"{store_label} → {item}"

    return base_url + requests.utils.quote(str(item)), f"{store_label} → {item}"


def build_scraper_url_for_item(item, selected_store=None):
    search_url, _label = build_store_search_details(item, selected_store)
    return search_url


def build_scraper_urls_for_items(items):
    """
    Builds the exact URL list BEFORE calling store_product_scraper.py.

    Returns:
        urls: list[str]
        url_to_item: dict[url] = item
        item_to_url: dict[item] = url
    """
    urls = []
    url_to_item = {}
    item_to_url = {}

    for item in items:
        selected_store = get_selected_store_for_item(item)

        if not selected_store:
            continue

        url = build_scraper_url_for_item(item, selected_store)

        if not url:
            continue

        urls.append(url)
        url_to_item[url] = item
        item_to_url[item] = url

    return urls, url_to_item, item_to_url


def normalize_scraper_product(product, selected_store=None):
    if not isinstance(product, dict):
        return None

    cleaned = dict(product)

    if not cleaned.get("product_name"):
        cleaned["product_name"] = cleaned.get("name") or cleaned.get("title")

    if not cleaned.get("product_url"):
        cleaned["product_url"] = (
            cleaned.get("url")
            or cleaned.get("href")
            or cleaned.get("link")
        )

    if not cleaned.get("product_cost"):
        cleaned["product_cost"] = cleaned.get("price") or cleaned.get("cost")

    if selected_store and not cleaned.get("store"):
        cleaned["store"] = selected_store

    if selected_store and not cleaned.get("product_location"):
        cleaned["product_location"] = (
            load_all_stores()
            .get(selected_store, {})
            .get("label", selected_store.title())
        )

    if cleaned.get("product_name") or cleaned.get("product_url"):
        return cleaned

    return None


def flatten_products_from_run_scraper(scrape_result, selected_store=None):
    raw_products = []

    if isinstance(scrape_result, list):
        for entry in scrape_result:
            if isinstance(entry, dict) and isinstance(entry.get("results"), list):
                raw_products.extend(entry.get("results") or [])
            elif isinstance(entry, dict) and isinstance(entry.get("products"), list):
                raw_products.extend(entry.get("products") or [])
            elif isinstance(entry, dict):
                raw_products.append(entry)

    elif isinstance(scrape_result, dict):
        for key in ["results", "products", "items"]:
            if isinstance(scrape_result.get(key), list):
                raw_products.extend(scrape_result.get(key) or [])

        for key in ["stores", "urls", "data"]:
            if isinstance(scrape_result.get(key), list):
                for entry in scrape_result.get(key) or []:
                    if isinstance(entry, dict) and isinstance(entry.get("results"), list):
                        raw_products.extend(entry.get("results") or [])
                    elif isinstance(entry, dict) and isinstance(entry.get("products"), list):
                        raw_products.extend(entry.get("products") or [])

    products = []
    seen = set()

    for raw_product in raw_products:
        product = normalize_scraper_product(raw_product, selected_store)

        if not product:
            continue

        identity = product.get("product_url") or normalize(product.get("product_name", ""))

        if not identity or identity in seen:
            continue

        seen.add(identity)
        products.append(product)

    return sorted(
        products,
        key=lambda product: product.get("score", 0) or 0,
        reverse=True
    )


def append_selected_product_to_item_sources(item, product):
    item_key = normalize(item)
    sources = load_item_sources()

    source_list = sources.get(item_key, [])

    if isinstance(source_list, str):
        source_list = [{"url": source_list}]

    if isinstance(source_list, dict):
        source_list = [source_list]

    if not isinstance(source_list, list):
        source_list = []

    product_url = product.get("product_url")
    product_store = product.get("store")
    product_location = product.get("product_location")

    cleaned_sources = []

    for source in source_list:
        if not isinstance(source, dict):
            cleaned_sources.append(source)
            continue

        is_product = source.get("source_type") == "product" or source.get("product_url")

        if is_product:
            same_url = product_url and source.get("product_url") == product_url
            same_store = (
                (product_store and source.get("store") == product_store)
                or (product_location and source.get("product_location") == product_location)
            )

            if same_url or same_store:
                continue

        cleaned_sources.append(source)

    cleaned_sources.append({
        "source_type": "product",
        "url": None,
        "product_name": product.get("product_name"),
        "product_url": product.get("product_url"),
        "product_location": product.get("product_location"),
        "product_cost": product.get("product_cost"),
        "store": product.get("store"),
        "is_organic": product.get("is_organic"),
        "score": product.get("score"),
    })

    sources[item_key] = cleaned_sources
    save_item_sources(sources)


def save_product_choices_for_item(item, products, best_product, scrape_result=None, search_url=None):
    choices = load_product_choices()
    item_key = normalize(item)

    choices[item_key] = {
        "item": item,
        "products": products,
        "selected_product": best_product,
        "selected_product_url": best_product.get("product_url") if best_product else None,
        "raw_result": scrape_result,
        "selected_store": get_selected_store_for_item(item),
        "search_url": search_url,
    }

    save_product_choices(choices)


def grab_products_from_urls(urls):
    """
    The only function that calls store_product_scraper.py.
    """
    if run_scraper is None:
        raise RuntimeError("store_product_scraper.run_scraper could not be imported.")

    print("\n==============================")
    print("URL LIST GOING INTO store_product_scraper.py")
    for index, url in enumerate(urls, start=1):
        print(f"{index}. {url}")
    print("==============================\n")

    try:
        return run_scraper(urls)
    except TypeError:
        return run_scraper(urls=urls)


def grab_best_products_for_items(items):
    """
    Main isolated workflow.

    Returns a result dict that app.py can put directly into the bulk job state.
    """
    urls, url_to_item, item_to_url = build_scraper_urls_for_items(items)

    result = {
        "ok": True,
        "urls": urls,
        "url_to_item": url_to_item,
        "item_to_url": item_to_url,
        "items": [],
        "added": 0,
        "skipped": 0,
        "failed": 0,
        "raw_result": None,
    }

    if not urls:
        result["ok"] = False
        result["error"] = "No scraper URLs were built. Select stores for ingredients first."
        return result

    try:
        scrape_result = grab_products_from_urls(urls)
        result["raw_result"] = scrape_result
    except Exception as error:
        traceback.print_exc()
        result["ok"] = False
        result["error"] = str(error)
        result["failed"] = len(items)
        return result

    # If your scraper returns one combined result list, use the same products for review.
    # If it returns per-URL results, this still flattens what it can.
    for item in items:
        selected_store = get_selected_store_for_item(item)
        search_url = item_to_url.get(item)
        products = flatten_products_from_run_scraper(result["raw_result"], selected_store)

        if products:
            best_product = products[0]
            append_selected_product_to_item_sources(item, best_product)
            save_product_choices_for_item(
                item=item,
                products=products,
                best_product=best_product,
                scrape_result=result["raw_result"],
                search_url=search_url,
            )

            result["items"].append({
                "item": item,
                "status": "done",
                "search_url": search_url,
                "scraper_urls": [search_url] if search_url else [],
                "selected_store": selected_store,
                "selected_store_label": load_all_stores().get(selected_store, {}).get("label", ""),
                "product_name": best_product.get("product_name"),
                "product_cost": best_product.get("product_cost"),
                "selected_product_url": best_product.get("product_url"),
                "selected_product": best_product,
                "products": products,
                "skip_reason": None,
                "error": None,
            })
            result["added"] += 1
        else:
            result["items"].append({
                "item": item,
                "status": "skipped",
                "search_url": search_url,
                "scraper_urls": [search_url] if search_url else [],
                "selected_store": selected_store,
                "selected_store_label": load_all_stores().get(selected_store, {}).get("label", ""),
                "product_name": None,
                "product_cost": None,
                "selected_product_url": None,
                "selected_product": None,
                "products": [],
                "skip_reason": "No matching product candidates were found.",
                "error": None,
            })
            result["skipped"] += 1

    return result


if __name__ == "__main__":
    items = get_grabbable_product_items(skip_existing=True)
    result = grab_best_products_for_items(items)
    print(json.dumps(result, indent=2, ensure_ascii=False))
