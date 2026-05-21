from __future__ import annotations

import importlib
from typing import Any

from PushShoppingList.scripts.stores.browser_helpers import build_store_context
from PushShoppingList.scripts.stores.browser_helpers import build_store_helpers


STORE_MODULES = {
    "aldi": "PushShoppingList.scripts.stores.aldi_store",
    "meijer": "PushShoppingList.scripts.stores.meijer_store",
    "kroger": "PushShoppingList.scripts.stores.kroger_store",
    "walmart": "PushShoppingList.scripts.stores.walmart_store",
    "target": "PushShoppingList.scripts.stores.target_store",
    "costco": "PushShoppingList.scripts.stores.costco_store",
}


def load_store_module(store_key: str):
    module_path = STORE_MODULES.get(str(store_key or "").strip().lower())
    if not module_path:
        module_path = "PushShoppingList.scripts.stores.generic_store"
    try:
        return importlib.import_module(module_path)
    except Exception:
        return importlib.import_module("PushShoppingList.scripts.stores.generic_store")


def route_update_home_store(
    driver,
    store_key: str,
    store: dict[str, Any] | None,
    full_address: str,
    store_location: dict[str, Any] | None = None,
    start_url: str = "",
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    store_key = str(store_key or "").strip().lower()
    context = build_store_context(
        store_key=store_key,
        store=store or {},
        full_address=full_address,
        store_location=store_location or {},
        start_url=start_url,
    )
    module = load_store_module(store_key)
    helpers = build_store_helpers()

    try:
        return module.update_home_store(
            driver=driver,
            context=context,
            helpers=helpers,
            worker_id=worker_id,
            wait_seconds=wait_seconds,
        )
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "store_key": store_key,
            "message": f"Home store update failed: {exc}",
            "error": str(exc),
            **context,
        }

