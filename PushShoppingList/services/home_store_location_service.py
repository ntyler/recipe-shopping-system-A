import json
from datetime import datetime
from pathlib import Path

from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.store_settings_service import load_store_settings


PACKAGE_DIR = Path(__file__).resolve().parents[1]
NEAREST_STORE_RESULTS_FILE = PACKAGE_DIR / "shopping_stores_Results.json"
DEFAULT_STORE_SEARCH_RADIUS_MILES = 10


def load_nearest_store_results():
    if not NEAREST_STORE_RESULTS_FILE.exists():
        return {
            "ok": False,
            "home_address": "",
            "home_location": None,
            "enabled_stores": [],
            "store_locations": {},
            "search_radius_miles": DEFAULT_STORE_SEARCH_RADIUS_MILES,
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
            "search_radius_miles": DEFAULT_STORE_SEARCH_RADIUS_MILES,
            "updated_at": "",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "home_address": "",
            "home_location": None,
            "enabled_stores": [],
            "store_locations": {},
            "search_radius_miles": DEFAULT_STORE_SEARCH_RADIUS_MILES,
            "updated_at": "",
        }

    data.setdefault("store_locations", {})
    data.setdefault("enabled_stores", [])
    data["search_radius_miles"] = normalize_store_search_radius(
        data.get("search_radius_miles", DEFAULT_STORE_SEARCH_RADIUS_MILES)
    )
    data["search_radius_display"] = format_store_search_radius(data["search_radius_miles"])
    data["store_locations"] = normalize_saved_store_locations(data.get("store_locations", {}))
    return data


def normalize_store_search_radius(value, default=DEFAULT_STORE_SEARCH_RADIUS_MILES):
    try:
        radius = float(value)
    except (TypeError, ValueError):
        radius = float(default)

    return max(1.0, min(100.0, radius))


def format_store_search_radius(radius):
    radius = normalize_store_search_radius(radius)
    if float(radius).is_integer():
        return str(int(radius))
    return f"{radius:.1f}".rstrip("0").rstrip(".")


def normalize_saved_store_locations(store_locations):
    if not isinstance(store_locations, dict):
        return {}

    normalized = {}
    for store_key, location in store_locations.items():
        if not isinstance(location, dict):
            continue

        cleaned = dict(location)
        nearby = cleaned.get("nearby_locations")
        if not isinstance(nearby, list):
            nearby = [cleaned] if cleaned.get("address") else []

        cleaned["nearby_locations"] = [
            item
            for item in nearby
            if isinstance(item, dict)
        ]
        cleaned["nearby_count"] = len(cleaned["nearby_locations"])
        if "search_radius_miles" in cleaned:
            cleaned["search_radius_display"] = format_store_search_radius(cleaned["search_radius_miles"])
        normalized[store_key] = cleaned

    return normalized


def save_nearest_store_results(data):
    NEAREST_STORE_RESULTS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def resolve_nearest_stores_for_home_address(home_address=None, store_settings=None, search_radius_miles=None):
    from PushShoppingList.services.product_selection_service import find_nearby_store_locations
    from PushShoppingList.services.product_selection_service import geocode_home_address

    home_address = home_address or load_home_address()
    store_settings = store_settings or load_store_settings()
    search_radius = normalize_store_search_radius(search_radius_miles)
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
            "search_radius_miles": search_radius,
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
            "search_radius_miles": search_radius,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "error": "Full Address could not be geocoded.",
        }

    store_locations = {}
    search_radius_display = format_store_search_radius(search_radius)

    for store_key in enabled_stores:
        nearby_locations = find_nearby_store_locations(
            store_key,
            stores[store_key],
            full_address,
            home_location,
            radius_miles=search_radius,
        )
        if nearby_locations:
            nearest = dict(nearby_locations[0])
            nearest["nearby_locations"] = nearby_locations
            nearest["nearby_count"] = len(nearby_locations)
            nearest["search_radius_miles"] = search_radius
            nearest["search_radius_display"] = search_radius_display
            store_locations[store_key] = nearest
        else:
            store_name = stores[store_key].get("label") or store_key.title()
            store_locations[store_key] = {
                "name": store_name,
                "address": "",
                "distance_miles": None,
                "locator_url": "",
                "source": "configured-store-locator",
                "pickup_enabled": True,
                "pickup_status": "Assumed pickup-capable because the store is enabled for product search.",
                "nearby_locations": [],
                "nearby_count": 0,
                "search_radius_miles": search_radius,
                "search_radius_display": search_radius_display,
                "skip_reason": f"No nearby {store_name} location was found within {search_radius_display} mi.",
            }

    result = {
        "ok": True,
        "saved": True,
        "home_address": full_address,
        "home_location": home_location,
        "enabled_stores": enabled_stores,
        "store_locations": store_locations,
        "search_radius_miles": search_radius,
        "search_radius_display": search_radius_display,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    return save_nearest_store_results(result)
