from __future__ import annotations

from typing import Any

from . import aldi_store, costco_store, kroger_store, meijer_store, target_store, walmart_store
from . import generic_store

STORE_MODULES = {
    "aldi": aldi_store,
    "costco": costco_store,
    "kroger": kroger_store,
    "meijer": meijer_store,
    "target": target_store,
    "walmart": walmart_store,
}


def route_update_home_store(
    driver,
    store: str,
    context: dict[str, Any],
    start_url: str | None,
    helpers: dict[str, Any],
    worker_id: int = 0,
    wait_seconds: float = 4.0,
) -> dict[str, Any]:
    store = str(store or "").lower().strip()

    if not start_url:
        return {
            "attempted": True,
            "ok": False,
            "store_key": store,
            "message": "No store website/base URL found.",
            **context,
        }

    print(f"[Worker {worker_id}] 🏬 First time seeing {store}; setting home store on website")
    print(f"[Worker {worker_id}] 🌐 Opening: {start_url}")

    try:
        driver.get(start_url)
        import time
        time.sleep(wait_seconds)

        module = STORE_MODULES.get(store, generic_store)
        result = module.update_home_store(
            driver=driver,
            context=context,
            helpers=helpers,
            worker_id=worker_id,
            wait_seconds=wait_seconds,
        )

        print(f"[Worker {worker_id}] {'✅' if result.get('ok') else '⚠️'} {store}: {result.get('message')}")
        return result

    except Exception as exc:
        message = f"Home store update failed, continuing ingredient search: {exc}"
        print(f"[Worker {worker_id}] ⚠️ {store}: {message}")
        return {
            "attempted": True,
            "ok": False,
            "message": message,
            **context,
        }
