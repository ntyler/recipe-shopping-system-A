import json
from datetime import datetime
from pathlib import Path

from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.store_settings_service import load_store_settings


PACKAGE_DIR = Path(__file__).resolve().parents[1]
NEAREST_STORE_RESULTS_FILE = PACKAGE_DIR / "shopping_stores_Results.json"


def load_nearest_store_results():
    if not NEAREST_STORE_RESULTS_FILE.exists():
        return {
            "ok": False,
            "home_address": "",
            "home_location": None,
            "enabled_stores": [],
            "store_locations": {},
            "updated_at": "",
        }

    try:
        data = json.loads(NEAREST_STORE_RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ok": False,
            "home_address": "",
            "home_location": None,
            "enabled_stores": [],
            "store_locations": {},
            "updated_at": "",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "home_address": "",
            "home_location": None,
            "enabled_stores": [],
            "store_locations": {},
            "updated_at": "",
        }

    data.setdefault("store_locations", {})
    data.setdefault("enabled_stores", [])
    return data


def save_nearest_store_results(data):
    NEAREST_STORE_RESULTS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def resolve_nearest_stores_for_home_address(home_address=None, store_settings=None):
    from PushShoppingList.services.product_selection_service import find_nearest_store_location
    from PushShoppingList.services.product_selection_service import geocode_home_address

    home_address = home_address or load_home_address()
    store_settings = store_settings or load_store_settings()
    stores = store_settings.get("stores", {})
    enabled_stores = [
        store_key
        for store_key in store_settings.get("enabled_stores", [])
        if store_key in stores
    ]
    full_address = str(home_address.get("full_address", "") or "").strip()
    home_location = geocode_home_address(full_address)

    if not full_address:
        return {
            "ok": False,
            "saved": False,
            "home_address": full_address,
            "home_location": None,
            "enabled_stores": enabled_stores,
            "store_locations": load_nearest_store_results().get("store_locations", {}),
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "error": "Full Address is missing.",
        }

    if not home_location:
        return {
            "ok": False,
            "saved": False,
            "home_address": full_address,
            "home_location": None,
            "enabled_stores": enabled_stores,
            "store_locations": load_nearest_store_results().get("store_locations", {}),
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "error": "Full Address could not be geocoded.",
        }

    store_locations = {}

    for store_key in enabled_stores:
        store_locations[store_key] = find_nearest_store_location(
            store_key,
            stores[store_key],
            full_address,
            home_location,
        )

    result = {
        "ok": True,
        "saved": True,
        "home_address": full_address,
        "home_location": home_location,
        "enabled_stores": enabled_stores,
        "store_locations": store_locations,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    return save_nearest_store_results(result)
