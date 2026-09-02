"""AI-assisted meal nutrition estimates prepared for human review.

This module deliberately does not persist meals or media.  Callers resolve a
workspace-scoped staged photo through ``nutrition_photo_service`` and pass the
private path here.  Every successful estimate is returned as editable food
items, and every provider/format failure becomes an empty manual-entry review
instead of invented nutrition.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Mapping

from PushShoppingList.services.nutrition_tracking_service import MAX_DESCRIPTION_LENGTH
from PushShoppingList.services.nutrition_tracking_service import MAX_FOOD_ITEMS
from PushShoppingList.services.nutrition_tracking_service import NUTRIENT_FIELDS
from PushShoppingList.services.nutrition_tracking_service import NUTRIENT_LABELS
from PushShoppingList.services.nutrition_tracking_service import NUTRIENT_UNITS
from PushShoppingList.services.nutrition_tracking_service import NutritionValidationError
from PushShoppingList.services.nutrition_tracking_service import normalize_nutrition
from PushShoppingList.services.openai_model_service import model_value_for_env
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.recipe_extract_service import build_openai_chat_payload
from PushShoppingList.services.recipe_extract_service import call_openai_vision_image
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import get_openai_client


ANALYSIS_ACTION = "nutrition-meal-analysis"
ESTIMATE_LABEL = "AI estimate — review and edit before saving."
MANUAL_LABEL = "Nutrition has not been entered yet."
MANUAL_MESSAGE = (
    "Nutrition analysis is unavailable right now. Add the foods and nutrition "
    "manually, then review them before saving."
)


def _safe_env_int(name, default, *, minimum, maximum):
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, min(maximum, value))


MAX_ANALYSIS_ITEMS = _safe_env_int(
    "SHOPPING_APP_NUTRITION_AI_MAX_ITEMS",
    30,
    minimum=1,
    maximum=MAX_FOOD_ITEMS,
)


def _nutrition_status(nutrition):
    return {
        nutrient: "complete" if nutrient in nutrition else "missing"
        for nutrient in NUTRIENT_FIELDS
    }


def _source_kind(description, photo_path):
    if description and photo_path:
        return "photo_and_description"
    if photo_path:
        return "photo"
    if description:
        return "description"
    return "none"


def manual_entry_review(
    *,
    source_kind="none",
    error_code="analysis_unavailable",
    message=MANUAL_MESSAGE,
    model_used="",
    model_source="",
):
    """Return the stable, non-fabricated review shape used on AI failure."""

    return {
        "ok": True,
        "analysis_available": False,
        "analysis_status": "manual_entry",
        "source_kind": str(source_kind or "none"),
        "is_estimate": False,
        "estimate_label": MANUAL_LABEL,
        "requires_review": True,
        "manual_entry_available": True,
        "food_items": [],
        "nutrition": {},
        "nutrition_units": dict(NUTRIENT_UNITS),
        "nutrition_status": _nutrition_status({}),
        "confidence": None,
        "model_used": str(model_used or ""),
        "model_source": str(model_source or ""),
        "error_code": str(error_code or "analysis_unavailable"),
        "warning": str(message or MANUAL_MESSAGE),
    }


def _clean_description(value):
    description = str(value or "").strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise NutritionValidationError(
            f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.",
            field="description",
        )
    return description


def _number(value, *, field, minimum=0.0, maximum=None, allow_zero=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite.")
    if number < minimum or (number == minimum and not allow_zero):
        raise ValueError(f"{field} is out of range.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} is out of range.")
    rounded = round(number, 3)
    return int(rounded) if rounded.is_integer() else rounded


def _confidence(value):
    if value in (None, ""):
        return None
    return _number(
        value,
        field="Confidence",
        minimum=0,
        maximum=1,
        allow_zero=True,
    )


def _portion_parts(item):
    portion = item.get("portion") if isinstance(item.get("portion"), Mapping) else {}
    quantity = (
        item.get("quantity")
        if item.get("quantity") not in (None, "")
        else item.get("serving_amount")
    )
    if quantity in (None, ""):
        quantity = portion.get("quantity", portion.get("amount"))
    unit = str(
        item.get("unit")
        or item.get("serving_unit")
        or portion.get("unit")
        or ""
    ).strip()
    if not unit or len(unit) > 50:
        raise ValueError("Food portion unit is invalid.")
    quantity = _number(quantity, field="Food quantity", maximum=10_000)
    return quantity, unit


def _food_nutrition(item):
    candidate = item.get("nutrition")
    if not isinstance(candidate, (dict, list)):
        candidate = {
            nutrient: item.get(nutrient, item.get("carbs") if nutrient == "carbohydrates" else None)
            for nutrient in NUTRIENT_FIELDS
        }
    nutrition = normalize_nutrition(candidate, allow_display_values=True)
    missing = [nutrient for nutrient in NUTRIENT_FIELDS if nutrient not in nutrition]
    if missing:
        labels = ", ".join(NUTRIENT_LABELS[nutrient] for nutrient in missing)
        raise ValueError(f"Food nutrition is missing: {labels}.")
    return nutrition


def _normalize_food_item(item):
    if not isinstance(item, Mapping):
        raise ValueError("Each food item must be an object.")
    name = str(item.get("name") or item.get("food") or "").strip()
    if not name or len(name) > 120:
        raise ValueError("Food name is missing or too long.")
    quantity, unit = _portion_parts(item)
    nutrition = _food_nutrition(item)
    per_unit = {
        nutrient: round(amount / quantity, 6)
        for nutrient, amount in nutrition.items()
    }
    portion_label = f"{quantity:g} {unit}" if isinstance(quantity, float) else f"{quantity} {unit}"
    normalized = {
        "id": uuid.uuid4().hex,
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "portion": portion_label,
        "nutrition_per_unit": per_unit,
        "nutrition": nutrition,
        "confidence": _confidence(item.get("confidence")),
        "is_estimate": True,
    }
    return normalized


def _response_payload(value):
    if not isinstance(value, Mapping):
        raise ValueError("Analysis response must be an object.")
    nested = value.get("meal")
    return nested if isinstance(nested, Mapping) else value


def normalize_analysis_response(value, *, source_kind, model_used="", model_source=""):
    """Validate provider JSON and create the editable review contract."""

    payload = _response_payload(value)
    foods = payload.get("food_items")
    if foods is None:
        foods = payload.get("foods")
    if not isinstance(foods, list) or not foods or len(foods) > MAX_ANALYSIS_ITEMS:
        raise ValueError("Analysis did not return a usable food list.")
    food_items = [_normalize_food_item(item) for item in foods]

    totals = {nutrient: 0.0 for nutrient in NUTRIENT_FIELDS}
    for item in food_items:
        for nutrient, amount in item["nutrition"].items():
            totals[nutrient] += amount
    nutrition = {
        nutrient: int(round(value)) if round(value, 3).is_integer() else round(value, 3)
        for nutrient, value in totals.items()
    }

    confidence = _confidence(payload.get("confidence"))
    if confidence is None:
        item_confidences = [
            item["confidence"] for item in food_items if item["confidence"] is not None
        ]
        if item_confidences:
            confidence = round(sum(item_confidences) / len(item_confidences), 3)

    return {
        "ok": True,
        "analysis_available": True,
        "analysis_status": "estimated",
        "source_kind": source_kind,
        "is_estimate": True,
        "estimate_label": ESTIMATE_LABEL,
        "requires_review": True,
        "manual_entry_available": True,
        "food_items": food_items,
        "nutrition": nutrition,
        "nutrition_units": dict(NUTRIENT_UNITS),
        "nutrition_status": _nutrition_status(nutrition),
        "confidence": confidence,
        "model_used": str(model_used or ""),
        "model_source": str(model_source or ""),
        "error_code": "",
        "warning": "",
    }


def build_meal_analysis_prompt(description="", *, includes_photo=False):
    evidence = []
    if includes_photo:
        evidence.append("the attached meal photo")
    if description:
        evidence.append(f"this user description: {json.dumps(description, ensure_ascii=False)}")
    evidence_text = " and ".join(evidence)
    return f"""
Estimate the foods, edible portions, and nutrition visible or stated in {evidence_text}.
This is an estimate for human review, not a medical determination. Do not infer a food
that is not reasonably supported by the evidence. If the evidence is inadequate,
return an empty food_items array.

Return only one JSON object with this exact shape:
{{
  "food_items": [
    {{
      "name": "food name",
      "quantity": 1,
      "unit": "cup",
      "nutrition": {{
        "calories": 0,
        "protein": 0,
        "carbohydrates": 0,
        "fat": 0,
        "fiber": 0,
        "sugar": 0,
        "sodium": 0
      }},
      "confidence": 0.0
    }}
  ],
  "confidence": 0.0
}}

Use kcal for calories, grams for protein/carbohydrates/fat/fiber/sugar, and milligrams
for sodium. Nutrition for each item must cover that item's full stated quantity.
Use numeric values only and confidence from 0 to 1. Keep food names and units concise.
""".strip()


def _content_from_response(response):
    try:
        return str(response.choices[0].message.content or "")
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("OpenAI returned an unexpected response.") from exc


def _description_analysis(description):
    model, model_source = model_value_for_env("OPENAI_NUTRITION_MODEL")
    payload, _temperature_included, resolved_model = build_openai_chat_payload(
        model,
        ANALYSIS_ACTION,
        [
            {
                "role": "system",
                "content": (
                    "You estimate meal foods and nutrition for an editable human review. "
                    "Return only valid JSON and never present estimates as exact facts."
                ),
            },
            {
                "role": "user",
                "content": build_meal_analysis_prompt(description),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    response = throttled_chat_completion(
        get_openai_client(),
        payload,
        action_name=ANALYSIS_ACTION,
        model=resolved_model,
    )
    record_openai_usage(
        response,
        ANALYSIS_ACTION,
        model=resolved_model,
        metadata={"source_kind": "description"},
    )
    return _content_from_response(response), resolved_model, model_source


def _photo_analysis(description, photo_path):
    result = call_openai_vision_image(
        image_path=photo_path,
        prompt=build_meal_analysis_prompt(description, includes_photo=True),
        action_name=ANALYSIS_ACTION,
    )
    if not result.ok:
        return None, result.model_used, result.model_source, result.error_code
    return result.text, result.model_used, result.model_source, ""


def analyze_meal(description="", photo_path=None):
    """Analyze a description and/or resolved private photo for editable review.

    ``photo_path`` is an internal path returned by ``resolve_staged_photo``; it
    is never included in the result.  AI/provider failures are represented by a
    valid manual-entry review object so the logging workflow can continue.
    """

    description = _clean_description(description)
    private_photo = Path(photo_path) if photo_path else None
    source_kind = _source_kind(description, private_photo)
    if source_kind == "none":
        return manual_entry_review(
            source_kind=source_kind,
            error_code="meal_source_required",
            message="Add a meal description or choose a meal photo before analyzing.",
        )
    if private_photo is not None and not private_photo.is_file():
        return manual_entry_review(
            source_kind=source_kind,
            error_code="staged_photo_unavailable",
            message="The staged meal photo is no longer available. Replace it or enter nutrition manually.",
        )
    if not str(os.getenv("OPENAI_API_KEY") or "").strip():
        return manual_entry_review(
            source_kind=source_kind,
            error_code="analysis_unavailable",
        )

    model_used = ""
    model_source = ""
    try:
        if private_photo is not None:
            text, model_used, model_source, error_code = _photo_analysis(
                description,
                private_photo,
            )
            if text is None:
                return manual_entry_review(
                    source_kind=source_kind,
                    error_code=error_code or "analysis_unavailable",
                    model_used=model_used,
                    model_source=model_source,
                )
        else:
            text, model_used, model_source = _description_analysis(description)
        parsed = json.loads(clean_json_response(text))
        return normalize_analysis_response(
            parsed,
            source_kind=source_kind,
            model_used=model_used,
            model_source=model_source,
        )
    except (json.JSONDecodeError, TypeError, ValueError, NutritionValidationError):
        return manual_entry_review(
            source_kind=source_kind,
            error_code="analysis_response_invalid",
            message=(
                "We could not turn the nutrition estimate into editable food items. "
                "Enter the foods and nutrition manually."
            ),
            model_used=model_used,
            model_source=model_source,
        )
    except Exception:
        return manual_entry_review(
            source_kind=source_kind,
            error_code="analysis_unavailable",
            model_used=model_used,
            model_source=model_source,
        )


def analyze_staged_meal(description="", photo_token=""):
    """Safely resolve an opaque staged-photo token and analyze its meal.

    This is the preferred route-facing entry point.  Token resolution is bound
    to the active workspace; neither the token nor its path is echoed in the
    returned review object.
    """

    description = _clean_description(description)
    token = str(photo_token or "").strip()
    if not token:
        return analyze_meal(description=description)
    try:
        from PushShoppingList.services.nutrition_photo_service import (
            NutritionPhotoError,
            resolve_staged_photo,
        )

        private_photo = resolve_staged_photo(token)
    except NutritionPhotoError:
        return manual_entry_review(
            source_kind="photo_and_description" if description else "photo",
            error_code="staged_photo_unavailable",
            message=(
                "The staged meal photo is no longer available. Replace it or "
                "enter nutrition manually."
            ),
        )
    return analyze_meal(description=description, photo_path=private_photo)


__all__ = [
    "ANALYSIS_ACTION",
    "ESTIMATE_LABEL",
    "MANUAL_LABEL",
    "analyze_meal",
    "analyze_staged_meal",
    "build_meal_analysis_prompt",
    "manual_entry_review",
    "normalize_analysis_response",
]
