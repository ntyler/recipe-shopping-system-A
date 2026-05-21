from datetime import datetime

from PushShoppingList.services.product_selection_service import clean_text
from PushShoppingList.scripts.test_grab_aldi_eggs import test_grab_products


def run_test_grab_aldi(home_address, search_term, job_id=None):
    search_term = clean_text(search_term)
    if not search_term:
        return {
            "ok": False,
            "search_term": "",
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "searched_store": {},
            "best_product": {},
            "alternatives": [],
            "rejected_products": [],
            "errors": ["Ingredient is required."],
        }

    result = test_grab_products(
        job_id=job_id,
        ingredient=search_term,
        home_address_override=home_address,
    )
    result = result if isinstance(result, dict) else {}

    return {
        "ok": bool(result.get("ok")),
        "search_term": result.get("search_item") or search_term,
        "timestamp": result.get("timestamp") or datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "searched_store": result.get("searched_store") or {},
        "best_product": result.get("best_product") or {},
        "alternatives": result.get("alternatives") or [],
        "rejected_products": result.get("rejected_products") or [],
        "errors": result.get("errors") or [],
        "result_path": result.get("result_path", ""),
        "results": result.get("results") or [],
        "count": result.get("count", 0),
        "selected_count": result.get("selected_count", 0),
        "download_count": result.get("download_count", 0),
        "max_workers": result.get("max_workers", 1),
    }
