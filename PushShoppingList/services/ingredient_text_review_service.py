import json
import os
import re

from openai import OpenAI

from PushShoppingList.services.openai_model_service import supports_custom_temperature
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.storage_service import active_user_id


MODEL = os.getenv(
    "OPENAI_INGREDIENT_REVIEW_MODEL",
    os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"),
)
client = None
_review_cache = {}
_CACHE_MISS = object()

MEASURED_WITH_PATTERN = re.compile(
    r"\b(?:beaten|beat|whisked|mixed|combined|stirred|blended|dissolved)\s+with\s+"
    r"(?:\d|\d+\s*/\s*\d+|one|two|three|a|an)\b",
    re.IGNORECASE,
)
WITH_MEASUREMENT_PATTERN = re.compile(
    r"\bwith\s+(?:\d|\d+\s*/\s*\d+|one|two|three|a|an)\s+"
    r"(?:teaspoons?|tsp\.?|tablespoons?|tbsp\.?|cups?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|"
    r"milliliters?|ml|liters?|l|pinch(?:es)?|dash(?:es)?)\b",
    re.IGNORECASE,
)
SECONDARY_MEASURED_WITH_PATTERN = re.compile(
    r"\bwith\s+(?P<quantity>\d+(?:\s+\d+/\d+)?|\d+/\d+|one|two|three|a|an)\s+"
    r"(?P<unit>teaspoons?|tsp\.?|tablespoons?|tbsp\.?|cups?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|"
    r"milliliters?|ml|liters?|l|pinch(?:es)?|dash(?:es)?)\s+"
    r"(?P<ingredient>[a-z][a-z\s-]*?)(?:$|[,;)]|\s+for\b|\s+until\b)",
    re.IGNORECASE,
)
PREP_SPLIT_PATTERN = re.compile(
    r"\b(?:beaten|beat|whisked|mixed|combined|stirred|blended|dissolved)\s+with\b",
    re.IGNORECASE,
)
LEADING_AMOUNT_PATTERN = re.compile(
    r"^\s*(?:\d+(?:\s+\d+/\d+)?|\d+/\d+|one|two|three|a|an)?\s*"
    r"(?:teaspoons?|tsp\.?|tablespoons?|tbsp\.?|cups?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|"
    r"milliliters?|ml|liters?|l|pinch(?:es)?|dash(?:es)?|large|small|medium)?\s+",
    re.IGNORECASE,
)


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=30)

    return client


def annotate_ingredients_for_food_review(ingredients):
    if not isinstance(ingredients, list):
        return []

    cache = food_review_cache_for_active_user()
    rows = [
        dict(item)
        for item in ingredients
        if isinstance(item, dict)
    ]
    candidates = []

    for index, item in enumerate(rows):
        key = ingredient_review_text_key(item)
        if not key or not ingredient_text_review_candidate(item):
            continue

        cached = cache.get(key, _CACHE_MISS)
        if cached is _CACHE_MISS:
            candidates.append({
                "index": index,
                "key": key,
                "item": item,
            })
        elif cached:
            rows[index]["food_review"] = dict(cached)

    if candidates:
        reviews_by_index = {}
        used_fallback = False

        if os.getenv("OPENAI_API_KEY"):
            try:
                reviews_by_index = request_chatgpt_ingredient_reviews(candidates)
            except Exception:
                used_fallback = True
        else:
            used_fallback = True

        for candidate in candidates:
            item = candidate["item"]
            review = reviews_by_index.get(candidate["index"])

            if not review and used_fallback:
                review = fallback_ingredient_text_review(item)

            normalized = normalize_ingredient_text_review(review, item)
            cache[candidate["key"]] = normalized

            if normalized:
                rows[candidate["index"]]["food_review"] = dict(normalized)

    return rows


def food_review_cache_for_active_user():
    """Keep generated food-review annotations isolated per account/session."""
    user_id = active_user_id() or "guest"
    return _review_cache.setdefault(user_id, {})


def ingredient_text_review_candidate(item):
    text = ingredient_review_source_text(item)
    lower_text = text.lower()

    if not lower_text:
        return False

    if re.search(r"\s+\bor\b\s+", lower_text):
        return False

    return bool(
        MEASURED_WITH_PATTERN.search(lower_text)
        or WITH_MEASUREMENT_PATTERN.search(lower_text)
    )


def request_chatgpt_ingredient_reviews(candidates):
    prompt_items = [
        {
            "index": candidate["index"],
            "ingredient": str(candidate["item"].get("ingredient") or ""),
            "original_text": str(candidate["item"].get("original_text") or ""),
            "quantity": str(candidate["item"].get("quantity") or ""),
            "unit": str(candidate["item"].get("unit") or ""),
            "preparation": str(candidate["item"].get("preparation") or ""),
            "purchasable_item": str(candidate["item"].get("purchasable_item") or ""),
        }
        for candidate in candidates[:12]
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You review parsed recipe ingredient text for grocery-shopping mistakes. "
                "Return only valid JSON."
            ),
        },
        {
            "role": "user",
            "content": build_ingredient_text_review_prompt(prompt_items),
        },
    ]
    request_payload = {
        "model": MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if supports_custom_temperature(MODEL):
        request_payload["temperature"] = 0

    response = get_openai_client().chat.completions.create(
        **request_payload
    )
    record_openai_usage(response, "ingredient-text-review", model=MODEL)
    data = json.loads(clean_json_response(response.choices[0].message.content))
    reviews = data.get("reviews", [])
    by_index = {}

    if not isinstance(reviews, list):
        return by_index

    candidate_items = {
        candidate["index"]: candidate["item"]
        for candidate in candidates
    }

    for review in reviews:
        if not isinstance(review, dict):
            continue

        try:
            index = int(review.get("index"))
        except (TypeError, ValueError):
            continue

        if index not in candidate_items:
            continue

        normalized = normalize_ingredient_text_review(review, candidate_items[index])
        if normalized:
            normalized["source"] = "chatgpt"
            by_index[index] = normalized

    return by_index


def build_ingredient_text_review_prompt(items):
    return f"""
Review these parsed recipe ingredient rows and flag only rows that should show Food Review before shopping.

Rows:
{json.dumps(items, ensure_ascii=False)}

Flag a row when:
- the ingredient text accidentally contains preparation plus another measured ingredient, like "large egg yolk beaten with 1 tablespoon water";
- the parsed ingredient name combines a shop item with a recipe mixture, slurry, wash, marinade, or other prep phrase;
- the user should pick or confirm the grocery item that belongs on the shopping list.

Do not flag:
- normal compound grocery names such as peanut butter, baking powder, cream cheese, macaroni and cheese, sweetened condensed milk, or tomato sauce;
- preparation that is already cleanly separated in the preparation field;
- ingredient alternatives using "or", because the app already handles those.

For each flagged row, return practical choices for the grocery item. If there is only one sensible grocery item, return that one option. Keep non-shopping liquids such as tap water out of purchasable_item unless they truly need to be bought.

Return ONLY valid JSON with this shape:
{{
  "reviews": [
    {{
      "index": 0,
      "needs_review": true,
      "reason": "short reason",
      "prompt": "Pick grocery item",
      "options": [
        {{
          "ingredient": "clean ingredient name",
          "purchasable_item": "item to buy",
          "quantity": "quantity if this option is a measured secondary ingredient, otherwise empty",
          "unit": "unit if this option is a measured secondary ingredient, otherwise empty",
          "original_text": "clean recipe text for this option when creating a separate ingredient row",
          "reason": "why this is the right grocery item"
        }}
      ]
    }}
  ]
}}
"""


def fallback_ingredient_text_review(item):
    text = ingredient_review_candidate_text(item)
    if not ingredient_text_review_candidate(item):
        return None

    first = PREP_SPLIT_PATTERN.split(text, maxsplit=1)[0]
    ingredient = clean_review_option(first)

    if not ingredient:
        ingredient = clean_review_option(item.get("ingredient") or item.get("original_text") or "")

    if not ingredient:
        return None

    purchasable = fallback_purchasable_item(ingredient)
    options = [
        {
            "ingredient": ingredient,
            "purchasable_item": purchasable,
            "reason": "Use the shopping ingredient and keep the extra measured text as preparation.",
        }
    ]
    secondary = measured_secondary_ingredient(item)
    if secondary:
        options.append({
            **secondary,
            "reason": "Create this as its own ingredient row if the measured secondary item should be tracked separately.",
        })

    return {
        "needs_review": True,
        "reason": "This ingredient appears to combine a grocery item with preparation or another measured ingredient.",
        "prompt": "Pick grocery item",
        "options": options,
        "source": "local",
    }


def normalize_ingredient_text_review(review, item=None):
    if not isinstance(review, dict) or not review.get("needs_review"):
        return None

    options = normalize_review_options(review.get("options", []), item=item)
    reason = str(review.get("reason") or "").strip()

    if not options and item:
        fallback = fallback_ingredient_text_review(item)
        options = normalize_review_options(fallback.get("options", []) if fallback else [], item=item)

    if not options:
        return None

    return {
        "needs_review": True,
        "kind": "ingredient_text",
        "reason": reason or "This ingredient text may need cleanup before shopping.",
        "prompt": str(review.get("prompt") or "Pick grocery item").strip() or "Pick grocery item",
        "options": options,
        "source": str(review.get("source") or "chatgpt").strip() or "chatgpt",
        "text_key": ingredient_review_text_key(item) if item else "",
    }


def normalize_review_options(value, item=None):
    if not isinstance(value, list):
        return []

    options = []
    seen = set()

    for raw_option in value[:4]:
        if isinstance(raw_option, str):
            ingredient = clean_review_option(raw_option)
            purchasable = fallback_purchasable_item(ingredient)
            reason = ""
            quantity = ""
            unit = ""
            original_text = ""
            preparation = ""
            store_section = ""
        elif isinstance(raw_option, dict):
            ingredient = clean_review_option(raw_option.get("ingredient") or raw_option.get("name") or "")
            purchasable = clean_review_option(
                raw_option.get("purchasable_item")
                or raw_option.get("buy_as")
                or fallback_purchasable_item(ingredient)
            )
            reason = str(raw_option.get("reason") or "").strip()
            quantity = str(raw_option.get("quantity") or "").strip()
            unit = str(raw_option.get("unit") or "").strip()
            original_text = str(raw_option.get("original_text") or "").strip()
            preparation = str(raw_option.get("preparation") or "").strip()
            store_section = str(raw_option.get("store_section") or "").strip()
        else:
            continue

        enriched = enrich_review_option(
            {
                "ingredient": ingredient,
                "purchasable_item": purchasable,
                "quantity": quantity,
                "unit": unit,
                "original_text": original_text,
                "preparation": preparation,
                "store_section": store_section,
                "reason": reason,
            },
            source_item=item,
        )
        ingredient = enriched["ingredient"]
        purchasable = enriched["purchasable_item"]
        key = normalize_text_key(ingredient)
        if not ingredient or not key or key in seen:
            continue

        seen.add(key)
        options.append(enriched)

    return options


def enrich_review_option(option, source_item=None):
    option = dict(option)
    secondary = measured_secondary_ingredient(source_item)

    if secondary and ingredient_names_match(option.get("ingredient"), secondary.get("ingredient")):
        for field in ["quantity", "unit", "original_text", "preparation", "store_section"]:
            if not option.get(field):
                option[field] = secondary.get(field, "")

    option["purchasable_item"] = option.get("purchasable_item") or fallback_purchasable_item(option.get("ingredient"))
    return option


def clean_review_option(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    previous = None

    while previous != text:
        previous = text
        text = LEADING_AMOUNT_PATTERN.sub("", text).strip(" ,;:-")

    text = re.sub(r"\b(?:beaten|beat|whisked|mixed|combined|stirred|blended|dissolved)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    return text


def fallback_purchasable_item(ingredient):
    normalized = normalize_text_key(ingredient)

    if "egg yolk" in normalized or normalized in {"yolk", "yolks"}:
        return "eggs"

    return ingredient


def measured_secondary_ingredient(item):
    text = ingredient_review_candidate_text(item)
    match = SECONDARY_MEASURED_WITH_PATTERN.search(text)

    if not match:
        return None

    quantity = normalize_quantity_word(match.group("quantity"))
    unit = normalize_review_unit(match.group("unit"))
    ingredient = clean_review_option(match.group("ingredient"))

    if not ingredient:
        return None

    return {
        "ingredient": ingredient,
        "purchasable_item": fallback_purchasable_item(ingredient),
        "quantity": quantity,
        "unit": unit,
        "original_text": " ".join(part for part in [quantity, unit, ingredient] if part).strip(),
        "preparation": "",
        "store_section": "MISC",
    }


def normalize_quantity_word(value):
    normalized = normalize_text_key(value)
    return {
        "one": "1",
        "two": "2",
        "three": "3",
        "a": "1",
        "an": "1",
    }.get(normalized, str(value or "").strip())


def normalize_review_unit(value):
    normalized = normalize_text_key(value).rstrip(".")
    return {
        "tsp": "teaspoon",
        "teaspoons": "teaspoon",
        "tbsp": "tablespoon",
        "tablespoons": "tablespoon",
        "cups": "cup",
        "ounces": "ounce",
        "oz": "ounce",
        "pounds": "pound",
        "lbs": "pound",
        "grams": "gram",
        "milliliters": "milliliter",
        "liters": "liter",
        "pinches": "pinch",
        "dashes": "dash",
    }.get(normalized, normalized)


def ingredient_names_match(left, right):
    left_key = normalize_text_key(left)
    right_key = normalize_text_key(right)

    if not left_key or not right_key:
        return False

    return left_key == right_key or left_key in right_key or right_key in left_key


def ingredient_review_source_text(item):
    if not isinstance(item, dict):
        return ""

    values = [
        item.get("ingredient"),
        item.get("original_text"),
        item.get("preparation"),
    ]
    return " ".join(
        re.sub(r"\s+", " ", str(value or "")).strip()
        for value in values
        if re.sub(r"\s+", " ", str(value or "")).strip()
    )


def ingredient_review_candidate_text(item):
    if not isinstance(item, dict):
        return ""

    for value in [item.get("ingredient"), item.get("original_text")]:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if (
            MEASURED_WITH_PATTERN.search(text)
            or WITH_MEASUREMENT_PATTERN.search(text)
        ):
            return text

    return ingredient_review_source_text(item)


def ingredient_review_text_key(item):
    return normalize_text_key(ingredient_review_source_text(item))


def normalize_text_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def clean_json_response(text):
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    return value
