import json
from pathlib import Path

from PushShoppingList.services.purchase_mapping_service import clean_text
from PushShoppingList.services.purchase_mapping_service import purchase_group_for_item
from PushShoppingList.services.storage_service import scoped_extractor_data_path
from PushShoppingList.services import durable_document_runtime_service as durable_runtime


BASE_DIR = Path(__file__).resolve().parent
ITEM_STATE_FILE = scoped_extractor_data_path("shopping_item_state.json")

ITEM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_item_state():
    def legacy_loader():
        if not ITEM_STATE_FILE.exists():
            return {}
        try:
            return json.loads(ITEM_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    data = durable_runtime.load_json_document(
        legacy_loader,
        domain="shopping",
        document_key="item_state",
        source_key="shopping_item_state",
        source_ref="recipe-extractor/data/shopping_item_state.json",
    )

    return data if isinstance(data, dict) else {}


def save_item_store(item_key, store_key):
    state = load_item_state()
    item = state.setdefault(item_key, {})

    if store_key:
        item["store"] = store_key
    else:
        item.pop("store", None)

    save_item_state(state)
    return state


def save_item_manual_qty(item_key, manual_qty):
    state = load_item_state()
    item = state.setdefault(item_key, {})
    manual_qty = str(manual_qty or "").strip()

    if manual_qty:
        item["manual_qty"] = manual_qty
    else:
        item.pop("manual_qty", None)

    if not item:
        state.pop(item_key, None)

    save_item_state(state)
    return state


def save_item_purchase_mapping(item_key, purchasable_item):
    state = load_item_state()
    item_key = clean_text(item_key).lower()
    purchasable_item = clean_text(purchasable_item)

    if not item_key:
        return state

    item = state.setdefault(item_key, {})

    if purchasable_item:
        item["purchasable_item"] = purchasable_item
        item["purchase_group"] = purchase_group_for_item(purchasable_item)
    else:
        item.pop("purchasable_item", None)
        item.pop("purchase_group", None)

    if not item:
        state.pop(item_key, None)

    save_item_state(state)
    return state


def reset_item_stores():
    state = load_item_state()

    for item in state.values():
        if isinstance(item, dict):
            item.pop("store", None)

    save_item_state(state)
    return state


def save_item_state(state):
    return durable_runtime.save_json_document(
        state,
        lambda value: durable_runtime.atomic_write_json(
            ITEM_STATE_FILE, value, newline=False
        ),
        domain="shopping",
        document_key="item_state",
        source_key="shopping_item_state",
        source_ref="recipe-extractor/data/shopping_item_state.json",
    )
