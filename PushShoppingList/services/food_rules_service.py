import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
FOOD_RULES_FILE = BASE_DIR / "recipe-extractor" / "data" / "food_rules.json"

DEFAULT_FOOD_RULES = {
    "require": [
        {
            "label": "must be organic",
            "terms": ["organic"],
        },
    ],
    "avoid": [
        {
            "label": "no citric acid",
            "terms": ["citric acid"],
        },
        {
            "label": "no nitrates",
            "terms": ["nitrate", "nitrates", "sodium nitrate", "potassium nitrate"],
        },
        {
            "label": "no nitrites",
            "terms": ["nitrite", "nitrites", "sodium nitrite", "potassium nitrite"],
        },
        {
            "label": "no BHA",
            "terms": ["bha", "butylated hydroxyanisole"],
        },
        {
            "label": "no BHT",
            "terms": ["bht", "butylated hydroxytoluene"],
        },
        {
            "label": "no corn syrup or derivatives of corn syrup",
            "terms": [
                "corn syrup",
                "high fructose corn syrup",
                "hfcs",
                "corn syrup solids",
                "glucose syrup",
                "fructose syrup",
            ],
        },
        {
            "label": "no red dye",
            "terms": ["red dye", "red 40", "red #40", "fd&c red", "allura red"],
        },
        {
            "label": "no MSG",
            "terms": ["msg", "monosodium glutamate"],
        },
        {
            "label": "no sweeteners",
            "terms": [
                "aspartame",
                "sucralose",
                "saccharin",
                "acesulfame potassium",
                "acesulfame k",
                "neotame",
                "advantame",
                "stevia",
                "erythritol",
                "xylitol",
                "sorbitol",
                "maltitol",
                "monk fruit",
            ],
        },
        {
            "label": "no hydrogenated oils",
            "terms": ["hydrogenated oil", "hydrogenated oils", "partially hydrogenated"],
        },
        {
            "label": "no potassium bromate",
            "terms": ["potassium bromate"],
        },
        {
            "label": "no propyl paraben",
            "terms": ["propyl paraben", "propylparaben"],
        },
        {
            "label": "no titanium dioxide",
            "terms": ["titanium dioxide"],
        },
    ],
}

FOOD_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_food_rules():
    if not FOOD_RULES_FILE.exists():
        save_food_rules(DEFAULT_FOOD_RULES)
        return deepcopy_rules(DEFAULT_FOOD_RULES)

    try:
        data = json.loads(FOOD_RULES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy_rules(DEFAULT_FOOD_RULES)

    if not isinstance(data, dict):
        return deepcopy_rules(DEFAULT_FOOD_RULES)

    return {
        "require": normalize_rule_list(data.get("require")),
        "avoid": normalize_rule_list(data.get("avoid")),
    }


def save_food_rules(rules):
    FOOD_RULES_FILE.write_text(
        json.dumps(rules, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def product_matches_food_rules(product):
    text = product_search_text(product)
    rules = load_food_rules()

    missing_required = [
        rule["label"]
        for rule in rules["require"]
        if not any(term_matches(text, term) for term in rule["terms"])
    ]
    blocked_by = [
        rule["label"]
        for rule in rules["avoid"]
        if any(term_matches(text, term) for term in rule["terms"])
    ]

    return {
        "ok": not missing_required and not blocked_by,
        "missing_required": missing_required,
        "blocked_by": blocked_by,
    }


def annotate_product_food_rules(product):
    status = product_matches_food_rules(product)

    if isinstance(product, dict):
        annotated = dict(product)
    else:
        annotated = {
            "name": str(product or ""),
        }

    annotated["food_rule_status"] = {
        "ok": status["ok"],
        "needs_review": not status["ok"],
        "missing_required": status["missing_required"],
        "blocked_by": status["blocked_by"],
        "marker": food_rule_marker(status),
    }

    return annotated


def shopping_item_food_rule_status(item_name):
    text = str(item_name or "").lower()
    rules = load_food_rules()
    blocked_by = [
        rule["label"]
        for rule in rules["avoid"]
        if any(term_matches(text, term) for term in rule["terms"])
    ]
    status = {
        "ok": not blocked_by,
        "needs_review": bool(blocked_by),
        "missing_required": [],
        "blocked_by": blocked_by,
    }
    status["marker"] = food_rule_marker(status)
    return status


def food_rule_marker(status):
    issues = []

    if status.get("missing_required"):
        issues.extend(status["missing_required"])

    if status.get("blocked_by"):
        issues.extend(status["blocked_by"])

    if not issues:
        return ""

    return "Food rule review: " + "; ".join(issues)


def product_search_text(product):
    if isinstance(product, dict):
        values = [
            product.get("name"),
            product.get("title"),
            product.get("brand"),
            product.get("description"),
            product.get("ingredients"),
            product.get("ingredient_statement"),
        ]
        return " ".join(str(value or "") for value in values).lower()

    return str(product or "").lower()


def term_matches(text, term):
    term = str(term or "").strip().lower()

    if not term:
        return False

    if re.fullmatch(r"[a-z0-9]+", term):
        return re.search(rf"\b{re.escape(term)}\b", text) is not None

    return term in text


def normalize_rule_list(value):
    if not isinstance(value, list):
        return []

    normalized = []
    for rule in value:
        if not isinstance(rule, dict):
            continue

        label = str(rule.get("label", "") or "").strip()
        terms = [
            str(term).strip().lower()
            for term in rule.get("terms", [])
            if str(term).strip()
        ]

        if label and terms:
            normalized.append({"label": label, "terms": terms})

    return normalized


def deepcopy_rules(rules):
    return {
        "require": [dict(rule, terms=list(rule["terms"])) for rule in rules["require"]],
        "avoid": [dict(rule, terms=list(rule["terms"])) for rule in rules["avoid"]],
    }
