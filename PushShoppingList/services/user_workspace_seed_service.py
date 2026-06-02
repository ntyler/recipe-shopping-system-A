import json

from PushShoppingList.services.food_rules_service import DEFAULT_FOOD_RULES
from PushShoppingList.services.food_rules_service import normalize_food_rules
from PushShoppingList.services.home_address_service import DEFAULT_HOME_ADDRESS
from PushShoppingList.services.rules_display_service import DEFAULT_RULES_DISPLAY
from PushShoppingList.services.rules_display_service import deepcopy_rules_display
from PushShoppingList.services.rules_display_service import normalize_rules_section
from PushShoppingList.services.store_settings_service import DEFAULT_ENABLED_STORES
from PushShoppingList.services.store_settings_service import DEFAULT_STORES
from PushShoppingList.services.store_settings_service import clean_store_settings
from PushShoppingList.services.store_settings_service import deepcopy_stores
from PushShoppingList.services.storage_service import LEGACY_EXTRACTOR_DIR
from PushShoppingList.services.storage_service import extractor_root


def seed_new_user_rule_workspace(user_id):
    """Copy base rule/config defaults into a new user's isolated workspace."""
    try:
        target_data_dir = extractor_root(user_id) / "data"
        target_data_dir.mkdir(parents=True, exist_ok=True)

        seed_json_file(
            target_data_dir / "food_rules.json",
            normalized_base_food_rules(),
        )
        seed_json_file(
            target_data_dir / "rules_display.json",
            normalized_base_rules_display(),
        )
        seed_json_file(
            target_data_dir / "home_address.json",
            normalized_base_home_address(),
        )
        seed_json_file(
            target_data_dir / "store_settings.json",
            normalized_base_store_settings(),
        )
    except Exception as exc:
        return {
            "ok": False,
            "errors": [f"Unable to initialize account rules: {exc}"],
        }

    return {"ok": True}


def seed_json_file(path, payload):
    if path.exists():
        return

    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalized_base_food_rules():
    return normalize_food_rules(
        read_legacy_json("food_rules.json", DEFAULT_FOOD_RULES)
    )


def normalized_base_rules_display():
    return save_rules_display_payload(
        read_legacy_json("rules_display.json", DEFAULT_RULES_DISPLAY)
    )


def normalized_base_home_address():
    saved = read_legacy_json("home_address.json", DEFAULT_HOME_ADDRESS)
    saved = saved if isinstance(saved, dict) else {}

    return {
        key: str(saved.get(key, DEFAULT_HOME_ADDRESS[key]) or "").strip()
        for key in DEFAULT_HOME_ADDRESS
    }


def normalized_base_store_settings():
    saved = read_legacy_json(
        "store_settings.json",
        {
            "stores": deepcopy_stores(DEFAULT_STORES),
            "enabled_stores": list(DEFAULT_ENABLED_STORES),
        },
    )

    return clean_store_settings(saved if isinstance(saved, dict) else {})


def read_legacy_json(filename, fallback):
    path = LEGACY_EXTRACTOR_DIR / "data" / filename

    if not path.exists():
        return json_copy(fallback)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json_copy(fallback)

    return payload if isinstance(payload, dict) else json_copy(fallback)


def save_rules_display_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    normalized = {}

    for section_key, fallback in DEFAULT_RULES_DISPLAY.items():
        section = payload.get(section_key)
        normalized[section_key] = normalize_rules_section(section, fallback)

    return deepcopy_rules_display(normalized)


def json_copy(value):
    return json.loads(json.dumps(value))
