import json
import os
import re

from openai import OpenAI

from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import term_matches
from PushShoppingList.services.openai_model_service import supports_custom_temperature
from PushShoppingList.services.openai_usage_service import record_openai_usage


MODEL = os.getenv("OPENAI_FOOD_REVIEW_MODEL", os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"))
client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=30)

    return client


def suggest_food_review_alternatives(payload):
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    ingredient = str(payload.get("ingredient") or "").strip()
    original_text = str(payload.get("original_text") or "").strip()

    if not ingredient and not original_text:
        return {
            "ok": False,
            "error": "Ingredient is required.",
        }

    review = build_food_review_context(payload)
    prompt = build_alternative_prompt(review)

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You suggest practical recipe ingredient alternatives that satisfy food rules. "
                    "Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        request_payload = {
            "model": MODEL,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if supports_custom_temperature(MODEL):
            request_payload["temperature"] = 0.2

        response = get_openai_client().chat.completions.create(
            **request_payload
        )
        record_openai_usage(response, "food-review-alternatives", model=MODEL)
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Unable to get alternatives from ChatGPT API: {exc}",
        }

    alternatives = normalize_alternatives(data.get("alternatives", []), review["avoid_rules"])

    return {
        "ok": True,
        "review": review,
        "alternatives": alternatives,
    }


def build_food_review_context(payload):
    rules = load_food_rules()
    ingredient = str(payload.get("ingredient") or "").strip()
    original_text = str(payload.get("original_text") or "").strip()
    quantity = str(payload.get("quantity") or "").strip()
    unit = str(payload.get("unit") or "").strip()
    preparation = str(payload.get("preparation") or "").strip()
    section = str(payload.get("section") or "").strip()
    store_section = str(payload.get("store_section") or "").strip()
    text = " ".join([ingredient, original_text, preparation]).lower()
    blocked_by = [
        rule["label"]
        for rule in rules["avoid"]
        if any(term_matches(text, term) for term in rule["terms"])
    ]

    return {
        "ingredient": ingredient,
        "original_text": original_text,
        "quantity": quantity,
        "unit": unit,
        "preparation": preparation,
        "section": section,
        "store_section": store_section,
        "blocked_by": blocked_by,
        "avoid_rules": rules["avoid"],
        "require_rules": rules["require"],
    }


def build_alternative_prompt(review):
    return f"""
Suggest 4 practical alternatives for this recipe ingredient.

Ingredient needing review:
{json.dumps({
    "ingredient": review["ingredient"],
    "original_text": review["original_text"],
    "quantity": review["quantity"],
    "unit": review["unit"],
    "preparation": review["preparation"],
    "section": review["section"],
    "store_section": review["store_section"],
}, ensure_ascii=False)}

Food rule issues:
{json.dumps(review["blocked_by"], ensure_ascii=False)}

Food rules to avoid:
{json.dumps(review["avoid_rules"], ensure_ascii=False)}

Required food preferences:
{json.dumps(review["require_rules"], ensure_ascii=False)}

Rules:
- Favor common grocery-store ingredients.
- Avoid all listed avoid-rule terms and obvious derivatives.
- Preserve the recipe's role for sweetness, texture, moisture, acidity, leavening, binder, fat, or seasoning.
- Keep amounts compatible with the original quantity when possible.
- Do not suggest artificial sweeteners when the rules say no sweeteners.
- If the best alternative needs recipe adjustment, explain it briefly.
- Return ONLY valid JSON.

Output shape:
{{
  "alternatives": [
    {{
      "ingredient": "replacement ingredient name",
      "quantity": "suggested quantity or original quantity",
      "unit": "suggested unit or original unit",
      "reason": "why this works",
      "adjustment": "brief use note",
      "confidence": "high, medium, or low"
    }}
  ]
}}
"""


def normalize_alternatives(value, avoid_rules=None):
    if not isinstance(value, list):
        return []

    avoid_rules = avoid_rules or []
    alternatives = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue

        ingredient = str(item.get("ingredient") or "").strip()
        if not ingredient:
            continue

        if violates_avoid_rules(ingredient, avoid_rules):
            continue

        confidence = str(item.get("confidence") or "medium").strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"

        alternatives.append({
            "ingredient": ingredient,
            "quantity": str(item.get("quantity") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
            "adjustment": str(item.get("adjustment") or "").strip(),
            "confidence": confidence,
        })

    return alternatives


def violates_avoid_rules(text, avoid_rules):
    value = str(text or "").lower()

    return any(
        any(term_matches(value, term) for term in rule.get("terms", []))
        for rule in avoid_rules
    )


def clean_json_response(text):
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    return value
