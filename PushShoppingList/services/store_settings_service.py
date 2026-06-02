import json
import re
from pathlib import Path

from PushShoppingList.services.storage_service import scoped_extractor_data_path


BASE_DIR = Path(__file__).resolve().parent
STORE_SETTINGS_FILE = scoped_extractor_data_path("store_settings.json")
STORE_CREDENTIALS_FILE = scoped_extractor_data_path("store_credentials.json")

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
    legacy_credentials = {}
    needs_legacy_cleanup = False

    if STORE_SETTINGS_FILE.exists():
        try:
            saved = json.loads(STORE_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                stores = saved.get("stores")
                enabled = saved.get("enabled_stores")

                if isinstance(stores, dict):
                    data["stores"] = deepcopy_stores(stores)
                if isinstance(enabled, list):
                    data["enabled_stores"] = [
                        key
                        for key in enabled
                        if key in data["stores"]
                    ]
        except Exception:
            pass

    for store_key, store in data["stores"].items():
        if not isinstance(store, dict):
            continue

        credential = store_credentials_from_store(store)
        if credential:
            legacy_credentials[store_key] = credential
            needs_legacy_cleanup = True

        strip_store_credentials(store)

    if legacy_credentials:
        merge_store_credentials(legacy_credentials)

    if needs_legacy_cleanup:
        save_store_settings(data)

    apply_store_credentials(data)
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

    if not label:
        return settings

    key = unique_store_key(label, settings["stores"])
    settings["stores"][key] = {
        "label": label,
        "url": search_url or guess_search_url(homepage_url),
        "urlStoreSelector": selector_url,
    }
    save_store_credentials_for_form(key, form_data)

    if key not in settings["enabled_stores"]:
        settings["enabled_stores"].append(key)

    save_store_settings(settings)
    return load_store_settings()


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
    save_store_credentials_for_form(store_key, form_data)
    save_store_settings(settings)
    return load_store_settings()


def delete_store(store_key):
    settings = load_store_settings()
    settings["stores"].pop(store_key, None)
    settings["enabled_stores"] = [
        key
        for key in settings["enabled_stores"]
        if key != store_key
    ]
    delete_store_credentials(store_key)
    save_store_settings(settings)
    return load_store_settings()


def save_store_settings(settings):
    cleaned_settings = clean_store_settings(settings)
    STORE_SETTINGS_FILE.write_text(
        json.dumps(cleaned_settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cleaned_settings


def clean_store_settings(settings):
    stores = {}

    for store_key, store in (settings.get("stores") or {}).items():
        if not isinstance(store, dict):
            continue

        cleaned = dict(store)
        strip_store_credentials(cleaned)
        stores[store_key] = cleaned

    return {
        "stores": stores,
        "enabled_stores": [
            key
            for key in settings.get("enabled_stores", [])
            if key in stores
        ],
    }


def load_store_credentials():
    if not STORE_CREDENTIALS_FILE.exists():
        return {"credentials": {}}

    try:
        saved = json.loads(STORE_CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"credentials": {}}

    if not isinstance(saved, dict):
        return {"credentials": {}}

    credentials = saved.get("credentials")
    if not isinstance(credentials, dict):
        return {"credentials": {}}

    return {
        "credentials": {
            str(store_key): normalize_store_credentials(credential)
            for store_key, credential in credentials.items()
            if isinstance(credential, dict)
        },
    }


def save_store_credentials(credentials_payload):
    credentials = {}

    for store_key, credential in (credentials_payload.get("credentials") or {}).items():
        normalized = normalize_store_credentials(credential)
        if normalized["username"] or normalized["password"]:
            credentials[str(store_key)] = normalized

    STORE_CREDENTIALS_FILE.write_text(
        json.dumps({"credentials": credentials}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"credentials": credentials}


def save_store_credentials_for_form(store_key, form_data):
    credentials = load_store_credentials()
    current = credentials["credentials"].get(store_key, {})
    username = str(form_data.get("store_username", current.get("username", "")) or "").strip()
    password = str(form_data.get("store_password", current.get("password", "")) or "")

    if username or password:
        credentials["credentials"][store_key] = {
            "username": username,
            "password": password,
        }
    else:
        credentials["credentials"].pop(store_key, None)

    save_store_credentials(credentials)


def merge_store_credentials(credentials_to_merge):
    credentials = load_store_credentials()

    for store_key, credential in credentials_to_merge.items():
        normalized = normalize_store_credentials(credential)
        if normalized["username"] or normalized["password"]:
            credentials["credentials"][store_key] = normalized

    save_store_credentials(credentials)


def delete_store_credentials(store_key):
    credentials = load_store_credentials()
    credentials["credentials"].pop(store_key, None)
    save_store_credentials(credentials)


def apply_store_credentials(settings):
    # Credentials are stored in the active account's scoped data directory.
    credentials = load_store_credentials().get("credentials", {})

    for store_key, store in settings.get("stores", {}).items():
        credential = credentials.get(store_key, {})
        store["username"] = str(credential.get("username") or "")
        store["password"] = str(credential.get("password") or "")


def normalize_store_credentials(credential):
    return {
        "username": str(credential.get("username") or "").strip(),
        "password": str(credential.get("password") or ""),
    }


def store_credentials_from_store(store):
    credential = normalize_store_credentials(store)
    if credential["username"] or credential["password"]:
        return credential

    return {}


def strip_store_credentials(store):
    store.pop("username", None)
    store.pop("password", None)


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
