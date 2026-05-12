import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
STORE_SETTINGS_FILE = PROJECT_DIR / "recipe-extractor" / "data" / "store_settings.json"

DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "urlStoreSelector": "https://info.aldi.us/stores",
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "urlStoreSelector": "https://www.kroger.com/stores/search",
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "urlStoreSelector": "https://www.walmart.com/",
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "urlStoreSelector": "https://www.meijer.com/",
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "urlStoreSelector": "https://www.target.com/store-locator/find-stores",
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "urlStoreSelector": "https://www.costco.com/s?keyword=&openFMW=true",
    },
}
DEFAULT_ENABLED_STORES = ["meijer", "aldi"]

STORE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_store_settings():
    data = {
        "stores": deepcopy_stores(DEFAULT_STORES),
        "enabled_stores": list(DEFAULT_ENABLED_STORES),
    }

    if STORE_SETTINGS_FILE.exists():
        try:
            saved = json.loads(STORE_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                stores = saved.get("stores")
                enabled = saved.get("enabled_stores")

                if isinstance(stores, dict):
                    data["stores"] = stores
                if isinstance(enabled, list):
                    data["enabled_stores"] = [
                        key
                        for key in enabled
                        if key in data["stores"]
                    ]
        except Exception:
            pass

    return data


def save_enabled_stores(enabled_stores):
    settings = load_store_settings()
    settings["enabled_stores"] = [
        key
        for key in enabled_stores
        if key in settings["stores"]
    ]
    save_store_settings(settings)
    return settings


def add_store(form_data):
    settings = load_store_settings()
    label = str(form_data.get("store_label", "") or "").strip()
    homepage_url = str(form_data.get("homepage_url", "") or "").strip()
    search_url = str(form_data.get("store_url", "") or "").strip()
    selector_url = str(form_data.get("urlStoreSelector", "") or "").strip()
    username = str(form_data.get("store_username", "") or "").strip()
    password = str(form_data.get("store_password", "") or "").strip()

    if not label:
        return settings

    key = unique_store_key(label, settings["stores"])
    settings["stores"][key] = {
        "label": label,
        "url": search_url or guess_search_url(homepage_url),
        "urlStoreSelector": selector_url,
        "username": username,
        "password": password,
    }

    if key not in settings["enabled_stores"]:
        settings["enabled_stores"].append(key)

    save_store_settings(settings)
    return settings


def update_store(store_key, form_data):
    settings = load_store_settings()
    store = settings["stores"].get(store_key)

    if not store:
        return settings

    store["label"] = str(form_data.get("store_label", store.get("label", "")) or "").strip()
    store["url"] = str(form_data.get("store_url", store.get("url", "")) or "").strip()
    store["urlStoreSelector"] = str(
        form_data.get("urlStoreSelector", store.get("urlStoreSelector", "")) or ""
    ).strip()
    store["username"] = str(
        form_data.get("store_username", store.get("username", "")) or ""
    ).strip()
    store["password"] = str(
        form_data.get("store_password", store.get("password", "")) or ""
    ).strip()
    save_store_settings(settings)
    return settings


def delete_store(store_key):
    settings = load_store_settings()
    settings["stores"].pop(store_key, None)
    settings["enabled_stores"] = [
        key
        for key in settings["enabled_stores"]
        if key != store_key
    ]
    save_store_settings(settings)
    return settings


def save_store_settings(settings):
    STORE_SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def unique_store_key(label, stores):
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "store"
    key = base
    counter = 2

    while key in stores:
        key = f"{base}_{counter}"
        counter += 1

    return key


def guess_search_url(homepage_url):
    homepage_url = homepage_url.rstrip("/")

    if not homepage_url:
        return ""

    return f"{homepage_url}/search?q="


def deepcopy_stores(stores):
    return {
        key: dict(value)
        for key, value in stores.items()
    }
