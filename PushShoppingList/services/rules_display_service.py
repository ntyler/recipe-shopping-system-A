import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RULES_DISPLAY_FILE = BASE_DIR / "recipe-extractor" / "data" / "rules_display.json"

DEFAULT_RULES_DISPLAY = {
    "home_stores": {
        "rows": [
            {
                "key": "nearby_store_lookup",
                "label": "Nearby store lookup",
                "value": "Grab Best Products uses the Full Address to find the nearest available location for each enabled store.",
            },
            {
                "key": "search_scope",
                "label": "Search scope",
                "value": "Only enabled store websites are searched for product candidates.",
            },
        ],
    },
    "best_product_ranking": {
        "rows": [
            {
                "key": "ingredient_match",
                "label": "Ingredient match",
                "value": "Products score higher when their names match more ingredient terms.",
            },
            {
                "key": "food_restrictions",
                "label": "Food restrictions",
                "value": "Avoid rules block a product. Required rules must be present for a product to be selectable.",
            },
            {
                "key": "price",
                "label": "Price",
                "value": "Visible prices are preferred. Missing prices lower confidence and are saved with a skip reason.",
            },
            {
                "key": "direct_product_url",
                "label": "Direct product URL",
                "value": "Direct product pages are preferred over store search-result pages.",
            },
            {
                "key": "distance",
                "label": "Distance",
                "value": "Closer nearest-store locations improve ranking when distance is available.",
            },
        ],
    },
    "saved_product_choices": {
        "rows": [
            {
                "key": "best_product",
                "label": "Best product",
                "value": "The top viable candidate is saved as the selected product for the ingredient.",
            },
            {
                "key": "alternatives",
                "label": "Alternatives",
                "value": "All viable candidates are preserved so the Alternatives button can switch the selected product.",
            },
            {
                "key": "manual_override",
                "label": "Manual override",
                "value": "Manual alternative selections persist across refreshes and sync through the backend JSON state.",
            },
            {
                "key": "fallback_search_pages",
                "label": "Fallback search pages",
                "value": "Search-result fallback pages are kept as references, but they are not selectable as best products.",
            },
            {
                "key": "no_valid_product",
                "label": "No valid product",
                "value": "When no viable candidate is found, skip reasons are saved and shown instead of a product pick.",
            },
        ],
    },
}

EDITABLE_RULE_SECTIONS = {"home_stores", "best_product_ranking", "saved_product_choices"}

RULES_DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_rules_display():
    data = deepcopy_rules_display(DEFAULT_RULES_DISPLAY)

    if RULES_DISPLAY_FILE.exists():
        try:
            saved = json.loads(RULES_DISPLAY_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved = {}

        if isinstance(saved, dict):
            for section_key in EDITABLE_RULE_SECTIONS:
                saved_section = saved.get(section_key)
                if isinstance(saved_section, dict):
                    data[section_key] = normalize_rules_section(
                        saved_section,
                        data.get(section_key, {"rows": []}),
                    )

    return data


def save_rules_display(data):
    normalized = {}
    current = load_rules_display()

    for section_key in EDITABLE_RULE_SECTIONS:
        normalized[section_key] = normalize_rules_section(
            data.get(section_key),
            current.get(section_key, DEFAULT_RULES_DISPLAY[section_key]),
        )

    RULES_DISPLAY_FILE.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return normalized


def save_rules_display_section(section_key, rows):
    if section_key not in EDITABLE_RULE_SECTIONS:
        return {
            "ok": False,
            "error": "Unknown rules section.",
        }

    data = load_rules_display()
    data[section_key] = {
        "rows": normalize_rule_rows(rows),
    }
    saved = save_rules_display(data)

    return {
        "ok": True,
        "rules_display": saved,
        "section": saved[section_key],
    }


def save_home_store_rule_text(rows):
    data = load_rules_display()
    existing_rows = {
        row["key"]: row
        for row in data["home_stores"]["rows"]
    }

    for row in normalize_rule_rows(rows):
        if row["key"] in {"nearby_store_lookup", "search_scope"}:
            existing_rows[row["key"]] = row

    data["home_stores"]["rows"] = [
        existing_rows.get("nearby_store_lookup", DEFAULT_RULES_DISPLAY["home_stores"]["rows"][0]),
        existing_rows.get("search_scope", DEFAULT_RULES_DISPLAY["home_stores"]["rows"][1]),
    ]
    saved = save_rules_display(data)
    return saved["home_stores"]


def normalize_rules_section(section, fallback):
    fallback = fallback if isinstance(fallback, dict) else {"rows": []}
    section = section if isinstance(section, dict) else {}
    rows = normalize_rule_rows(section.get("rows"))

    return {
        "rows": rows if rows else normalize_rule_rows(fallback.get("rows")),
    }


def normalize_rule_rows(rows):
    if not isinstance(rows, list):
        return []

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()

        if not label and not value:
            continue

        normalized.append({
            "key": rule_row_key(row.get("key") or label or value),
            "label": label or "Rule",
            "value": value,
        })

    return normalized


def rule_row_key(value):
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return key or "rule"


def deepcopy_rules_display(data):
    return {
        section_key: {
            "rows": [dict(row) for row in section.get("rows", [])],
        }
        for section_key, section in data.items()
    }
