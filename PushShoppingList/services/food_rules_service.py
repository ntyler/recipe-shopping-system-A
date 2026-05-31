import json
import os
import re
from pathlib import Path

from openai import OpenAI

from PushShoppingList.services.storage_service import scoped_extractor_data_path


BASE_DIR = Path(__file__).resolve().parent
FOOD_RULES_FILE = scoped_extractor_data_path("food_rules.json")
MODEL = os.getenv("OPENAI_FOOD_RULES_MODEL", os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"))
client = None

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
        {
            "label": "no chocolate liquor",
            "terms": ["chocolate liquor"],
        },
    ],
}

FOOD_RULES_FILE.parent.mkdir(parents=True, exist_ok=True)


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=30)

    return client


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

    return normalize_food_rules(data)


def save_food_rules(rules):
    normalized = normalize_food_rules(rules)
    FOOD_RULES_FILE.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return normalized


def update_food_rules(rules):
    return save_food_rules(rules)


def suggest_food_rules_from_prompt(prompt, current_rules=None, section=None):
    prompt = str(prompt or "").strip()
    section = normalize_rule_section(section)

    if not prompt:
        return {
            "ok": False,
            "error": "Enter a food restriction prompt.",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    current_rules = normalize_food_rules(current_rules) if current_rules is not None else load_food_rules()

    try:
        response = get_openai_client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You convert food preference text into grocery product restriction rules. "
                        "Return only valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": build_food_rule_prompt(prompt, current_rules, section),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Unable to add food restrictions with ChatGPT API: {exc}",
        }

    additions = normalize_food_rules(data)

    if not additions["require"] and not additions["avoid"]:
        existing_rule = find_existing_food_rule_for_prompt(prompt, current_rules, section)

        if existing_rule:
            change = food_rule_change("matched_existing", existing_rule["section"], existing_rule["rule"])
            return {
                "ok": True,
                "food_rules": current_rules,
                "added": additions,
                "changes": [change],
                "message": food_rule_suggestion_message([change], prompt, section),
            }

        return {
            "ok": True,
            "food_rules": current_rules,
            "added": additions,
            "changes": [],
            "message": "ChatGPT did not add or update any food restriction rules.",
        }

    merged, changes = merge_food_rules_with_changes(current_rules, additions)
    saved = save_food_rules(merged)

    return {
        "ok": True,
        "food_rules": saved,
        "added": additions,
        "changes": changes,
        "message": food_rule_suggestion_message(changes, prompt, section),
    }


def build_food_rule_prompt(prompt, current_rules, section=None):
    section = normalize_rule_section(section)
    section_instruction = ""

    if section == "require":
        section_instruction = (
            "\nTarget list: require. Treat the request as something products must have. "
            "Return require rules unless the user clearly asks to avoid something.\n"
        )
    elif section == "avoid":
        section_instruction = (
            "\nTarget list: avoid. Treat the request as something products must not contain. "
            "Return avoid rules unless the user clearly asks for a required quality.\n"
        )

    return f"""
Add food restriction rules from this user request:
{prompt}
{section_instruction}

Existing rules:
{json.dumps(current_rules, ensure_ascii=False)}

Use this meaning:
- require: product qualities that must be present, such as organic or gluten free.
- avoid: ingredients, additives, or wording that should reject a product.

Rules:
- Create short labels, for example "no carrageenan" or "must be organic".
- Terms must be lowercase product-label search terms.
- Include common label variants and synonyms only when they are directly relevant.
- If an existing rule already covers the request, return that existing rule with any useful missing terms.
- Do not create duplicate rules with different labels for the same terms.
- Return ONLY valid JSON.

Output shape:
{{
  "require": [
    {{"label": "must be ...", "terms": ["..."]}}
  ],
  "avoid": [
    {{"label": "no ...", "terms": ["...", "..."]}}
  ]
}}
"""


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
        terms = normalize_rule_terms(rule.get("terms", []))

        if label and terms:
            normalized.append({"label": label, "terms": terms})

    return normalized


def normalize_food_rules(rules):
    rules = rules if isinstance(rules, dict) else {}
    require_rules = rules.get("require", rules.get("required", rules.get("must_have")))
    avoid_rules = rules.get("avoid", rules.get("avoids", rules.get("avoid_rules")))

    return {
        "require": normalize_rule_list(require_rules),
        "avoid": normalize_rule_list(avoid_rules),
    }


def merge_food_rules(current_rules, additions):
    merged, _changes = merge_food_rules_with_changes(current_rules, additions)
    return merged


def merge_food_rules_with_changes(current_rules, additions):
    merged = normalize_food_rules(current_rules)
    additions = normalize_food_rules(additions)
    changes = []

    for section in ("require", "avoid"):
        for rule in additions[section]:
            change = merge_food_rule(merged[section], rule, section)

            if change:
                changes.append(change)

    return merged, changes


def merge_food_rule(existing_rules, incoming_rule, section=None):
    incoming_label = normalize_rule_label(incoming_rule.get("label"))
    incoming_terms = normalize_rule_terms(incoming_rule.get("terms"))

    if not incoming_label or not incoming_terms:
        return None

    for rule in existing_rules:
        existing_label = normalize_rule_label(rule.get("label"))
        existing_terms = set(normalize_rule_terms(rule.get("terms")))

        if existing_label == incoming_label or existing_terms == set(incoming_terms):
            added_terms = sorted(set(incoming_terms) - existing_terms)
            rule["terms"] = sorted(existing_terms | set(incoming_terms))
            action = "updated_existing" if added_terms else "matched_existing"
            return food_rule_change(action, section, rule, added_terms)

    new_rule = {
        "label": incoming_rule["label"],
        "terms": incoming_terms,
    }
    existing_rules.append(new_rule)
    return food_rule_change("added", section, new_rule)


def food_rule_change(action, section, rule, added_terms=None):
    return {
        "action": action,
        "section": normalize_rule_section(section) or section or "",
        "label": str(rule.get("label", "") or "").strip(),
        "terms": normalize_rule_terms(rule.get("terms", [])),
        "added_terms": normalize_rule_terms(added_terms or []),
    }


def food_rule_suggestion_message(changes, prompt="", section=None):
    changes = relevant_food_rule_changes(changes, prompt, section)

    if not changes:
        return "ChatGPT did not add or update any food restriction rules."

    if len(changes) == 1:
        change = changes[0]
        section_label = food_rule_section_label(change.get("section"))
        label = change.get("label") or "unnamed rule"

        if change.get("action") == "added":
            return f"ChatGPT added a new {section_label} rule: {label}."

        if change.get("action") == "updated_existing":
            added_terms = change.get("added_terms") or []
            terms_text = f" Added terms: {', '.join(added_terms)}." if added_terms else ""
            return f"ChatGPT found the existing {section_label} rule '{label}' and updated it.{terms_text}"

        return f"ChatGPT found the existing {section_label} rule '{label}' already meets this requirement."

    added = [change for change in changes if change.get("action") == "added"]
    updated = [change for change in changes if change.get("action") == "updated_existing"]
    matched = [change for change in changes if change.get("action") == "matched_existing"]

    if matched and not added and not updated:
        return "ChatGPT found existing rules that already meet this: " + food_rule_label_list(matched) + "."

    parts = []
    if added:
        parts.append(f"added {len(added)} new")
    if updated:
        parts.append(f"updated {len(updated)} existing")
    if matched:
        parts.append(f"found {len(matched)} already covered")

    return "ChatGPT " + ", ".join(parts) + " food restriction rules: " + food_rule_label_list(changes) + "."


def relevant_food_rule_changes(changes, prompt="", section=None):
    changes = [change for change in changes if isinstance(change, dict)]
    target_section = normalize_rule_section(section)

    if target_section:
        changes = [
            change for change in changes
            if normalize_rule_section(change.get("section")) == target_section
        ]

    if len(changes) <= 1:
        return changes

    prompt_text = normalize_rule_label(prompt)
    matching = [
        change for change in changes
        if food_rule_change_matches_prompt(change, prompt_text)
    ]

    return matching or changes


def food_rule_change_matches_prompt(change, prompt_text):
    if not prompt_text:
        return False

    label = normalize_rule_label(change.get("label"))

    if label and (label in prompt_text or prompt_text in label):
        return True

    for term in normalize_rule_terms(change.get("terms")):
        if len(term) >= 3 and term in prompt_text:
            return True

    return False


def food_rule_label_list(changes):
    labels = [change.get("label") or "unnamed rule" for change in changes[:4]]

    if len(changes) > 4:
        labels.append(f"{len(changes) - 4} more")

    return ", ".join(labels)


def food_rule_section_label(section):
    return "Required" if normalize_rule_section(section) == "require" else "Avoid"


def find_existing_food_rule_for_prompt(prompt, current_rules, section=None):
    prompt_text = normalize_rule_label(prompt)

    if not prompt_text:
        return None

    rules = normalize_food_rules(current_rules)
    sections = [normalize_rule_section(section)] if normalize_rule_section(section) else ["require", "avoid"]

    for rule_section in sections:
        for rule in rules.get(rule_section, []):
            change = food_rule_change("matched_existing", rule_section, rule)

            if food_rule_change_matches_prompt(change, prompt_text):
                return {
                    "section": rule_section,
                    "rule": rule,
                }

    return None


def normalize_rule_label(value):
    return " ".join(str(value or "").strip().lower().split())


def normalize_rule_section(value):
    section = str(value or "").strip().lower()

    if section in {"require", "required", "must_have", "must-have", "must have"}:
        return "require"

    if section in {"avoid", "avoids", "avoid_rules", "avoid-rules"}:
        return "avoid"

    return None


def normalize_rule_terms(value):
    if isinstance(value, str):
        parts = re.split(r"[,;\n]+", value)
    elif isinstance(value, list):
        parts = value
    else:
        parts = []

    terms = []
    seen = set()
    for part in parts:
        term = " ".join(str(part or "").strip().lower().split())
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    return terms


def clean_json_response(text):
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    return value


def deepcopy_rules(rules):
    return {
        "require": [dict(rule, terms=list(rule["terms"])) for rule in rules["require"]],
        "avoid": [dict(rule, terms=list(rule["terms"])) for rule in rules["avoid"]],
    }
