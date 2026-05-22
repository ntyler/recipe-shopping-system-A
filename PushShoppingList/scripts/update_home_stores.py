import json

from PushShoppingList.services.home_store_location_service import resolve_nearest_stores_for_home_address


def main():
    result = resolve_nearest_stores_for_home_address()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
