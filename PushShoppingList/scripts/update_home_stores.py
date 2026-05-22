import json
import sys

from PushShoppingList.services.home_store_location_service import resolve_nearest_stores_for_home_address


def main():
    search_radius_miles = sys.argv[1] if len(sys.argv) > 1 else None
    result = resolve_nearest_stores_for_home_address(search_radius_miles=search_radius_miles)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
