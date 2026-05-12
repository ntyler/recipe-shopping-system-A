import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ITEM_STATE_FILE = BASE_DIR / "recipe-extractor" / "data" / "shopping_item_state.json"

ITEM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_item_state():
    if not ITEM_STATE_FILE.exists():
        return {}

    try:
        data = json.loads(ITEM_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

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


def reset_item_stores():
    state = load_item_state()

    for item in state.values():
        if isinstance(item, dict):
            item.pop("store", None)

    save_item_state(state)
    return state


def save_item_state(state):
    ITEM_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
