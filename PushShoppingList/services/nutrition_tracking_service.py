"""Workspace-scoped nutrition, saved-meal, and water persistence.

Nutrition history is intentionally stored as a single versioned durable
document.  Keeping a meal and its reviewed food items in the same atomic write
prevents partial history, while persisted date indexes keep the dashboard and
weekly views inexpensive.  The active Flask workspace selects the backing file;
callers never provide an owner id.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from typing import Mapping

from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services.file_lock_service import workspace_write_lock
from PushShoppingList.services.storage_service import scoped_package_path


SCHEMA_VERSION = 1
NUTRITION_FILE = scoped_package_path("nutrition_tracking.json")
NUTRITION_LOCK = threading.RLock()

DOCUMENT_DOMAIN = "nutrition"
DOCUMENT_KEY = "tracking"
SOURCE_KEY = "nutrition_tracking"
SOURCE_REF = "nutrition_tracking.json"

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
MEAL_TYPE_LABELS = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snack",
}
MEAL_FILTER_LABELS = {
    "all": "All Meals",
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "snack": "Snacks",
}

NUTRIENT_FIELDS = (
    "calories",
    "protein",
    "carbohydrates",
    "fat",
    "fiber",
    "sugar",
    "sodium",
)
NUTRIENT_LABELS = {
    "calories": "Calories",
    "protein": "Protein",
    "carbohydrates": "Carbohydrates",
    "fat": "Fat",
    "fiber": "Fiber",
    "sugar": "Sugar",
    "sodium": "Sodium",
}
NUTRIENT_UNITS = {
    "calories": "kcal",
    "protein": "g",
    "carbohydrates": "g",
    "fat": "g",
    "fiber": "g",
    "sugar": "g",
    "sodium": "mg",
}
NUTRIENT_MAXIMUMS = {
    "calories": 100_000,
    "protein": 10_000,
    "carbohydrates": 10_000,
    "fat": 10_000,
    "fiber": 10_000,
    "sugar": 10_000,
    "sodium": 10_000_000,
}
NUTRIENT_ALIASES = {
    "calories": ("calories", "calorie", "energy", "calories_per_serving"),
    "protein": ("protein", "protein_content"),
    "carbohydrates": (
        "carbohydrates",
        "carbohydrate",
        "carbs",
        "carbohydrate_content",
    ),
    "fat": ("fat", "total_fat", "fat_content"),
    "fiber": ("fiber", "fibre", "fiber_content"),
    "sugar": ("sugar", "sugars", "sugar_content"),
    "sodium": ("sodium", "sodium_content"),
}

WATER_UNITS = ("ml", "fl_oz")
WATER_UNIT_LABELS = {"ml": "mL", "fl_oz": "fl oz"}
ML_PER_FLUID_OUNCE = 29.5735
MAX_WATER_ENTRY_ML = 10_000
MAX_WATER_GOAL_ML = 20_000

MAX_DESCRIPTION_LENGTH = 200
MAX_MEAL_NAME_LENGTH = 120
MAX_SAVED_MEAL_NAME_LENGTH = 120
MAX_FOOD_ITEMS = 100
MAX_ITEM_QUANTITY = 10_000
MAX_SERVINGS = 10_000
MAX_IDEMPOTENCY_RECORDS = 500

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TIMEZONE_RE = re.compile(r"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*$")
_LOCAL_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_STRICT_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_DISPLAY_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


class NutritionValidationError(ValueError):
    """Input was syntactically valid JSON but invalid Nutrition data."""

    def __init__(self, message, *, field="", field_errors=None):
        super().__init__(message)
        errors = dict(field_errors or {})
        if field and field not in errors:
            errors[field] = message
        self.field = field
        self.field_errors = errors


class NutritionNotFoundError(LookupError):
    """A record does not exist in the active workspace."""


class NutritionConflictError(NutritionValidationError):
    """An idempotency key was reused for a different operation."""


class NutritionSchemaError(RuntimeError):
    """The durable document was written by an unsupported newer schema."""


def _clean_text(value):
    return str(value or "").strip()


def _compact_number(value, *, digits=3):
    rounded = round(float(value), digits)
    if rounded == 0:
        rounded = 0.0
    if rounded.is_integer():
        return int(rounded)
    return rounded


def _utc_timestamp(value=None):
    moment = value or datetime.now(timezone.utc)
    if not isinstance(moment, datetime):
        raise TypeError("now must be a datetime value.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value, *, field, fallback=None):
    text = _clean_text(value)
    if not text:
        return _utc_timestamp(fallback)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NutritionValidationError(
            f"{field.replace('_', ' ').title()} must be a valid date and time.",
            field=field,
        ) from exc
    if parsed.tzinfo is None:
        raise NutritionValidationError(
            f"{field.replace('_', ' ').title()} must include a timezone.",
            field=field,
        )
    return _utc_timestamp(parsed)


def normalize_local_date(value, *, reference_date=None, allow_future=False):
    text = _clean_text(value)
    try:
        selected = date.fromisoformat(text)
    except ValueError as exc:
        raise NutritionValidationError(
            "Choose a valid date.", field="date"
        ) from exc

    if not allow_future:
        if reference_date is None:
            today = date.today()
        elif isinstance(reference_date, datetime):
            today = reference_date.date()
        elif isinstance(reference_date, date):
            today = reference_date
        else:
            try:
                today = date.fromisoformat(_clean_text(reference_date))
            except ValueError as exc:
                raise NutritionValidationError(
                    "The reference date is invalid.", field="date"
                ) from exc
        if selected > today:
            raise NutritionValidationError(
                "Future dates are not available for Nutrition tracking.", field="date"
            )
    return selected.isoformat()


def normalize_meal_type(value):
    meal_type = _clean_text(value).lower()
    if meal_type == "snacks":
        meal_type = "snack"
    if meal_type not in MEAL_TYPES:
        raise NutritionValidationError(
            "Choose Breakfast, Lunch, Dinner, or Snack.", field="meal_type"
        )
    return meal_type


def normalize_meal_filter(value):
    meal_filter = _clean_text(value).lower().replace(" ", "_") or "all"
    if meal_filter in {"all", "all_meals"}:
        return "all"
    return normalize_meal_type(meal_filter)


def normalize_description(value):
    description = _clean_text(value)
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise NutritionValidationError(
            f"Description must be {MAX_DESCRIPTION_LENGTH} characters or fewer.",
            field="description",
        )
    return description


def _normalize_positive_number(
    value,
    *,
    field,
    minimum=0,
    maximum=None,
    allow_zero=False,
):
    if isinstance(value, bool) or value is None:
        raise NutritionValidationError(f"{field} must be a number.", field=field)
    if isinstance(value, str):
        text = value.strip()
        if not _STRICT_NUMBER_RE.fullmatch(text):
            raise NutritionValidationError(f"{field} must be a number.", field=field)
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NutritionValidationError(f"{field} must be a number.", field=field) from exc
    if not math.isfinite(number):
        raise NutritionValidationError(f"{field} must be a finite number.", field=field)
    if number < minimum or (number == minimum and not allow_zero):
        qualifier = "zero or more" if allow_zero and minimum == 0 else f"more than {minimum:g}"
        raise NutritionValidationError(f"{field} must be {qualifier}.", field=field)
    if maximum is not None and number > maximum:
        raise NutritionValidationError(
            f"{field} must not exceed {maximum:g}.", field=field
        )
    return _compact_number(number, digits=6)


def _normalized_key(value):
    return re.sub(r"[^a-z0-9]+", "_", _clean_text(value).lower()).strip("_")


def _nutrition_mapping(value):
    if isinstance(value, Mapping):
        return {_normalized_key(key): item for key, item in value.items()}
    if isinstance(value, list):
        mapped = {}
        for row in value:
            if not isinstance(row, Mapping):
                continue
            key = row.get("key") or row.get("name") or row.get("label")
            if key:
                mapped[_normalized_key(key)] = row.get("value")
        return mapped
    if value in (None, ""):
        return {}
    raise NutritionValidationError("Nutrition must be an object.", field="nutrition")


def _nutrition_number(value, nutrient, *, allow_display_values):
    unit_text = ""
    if isinstance(value, bool) or value is None:
        raise NutritionValidationError(
            f"{NUTRIENT_LABELS[nutrient]} must be a number.", field=nutrient
        )
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if allow_display_values:
            match = _DISPLAY_NUMBER_RE.search(text)
            if not match:
                raise NutritionValidationError(
                    f"{NUTRIENT_LABELS[nutrient]} must be a number.", field=nutrient
                )
            value = match.group(0)
            unit_text = text.lower()
        elif not _STRICT_NUMBER_RE.fullmatch(text):
            raise NutritionValidationError(
                f"{NUTRIENT_LABELS[nutrient]} must be a number.", field=nutrient
            )
        else:
            value = text
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NutritionValidationError(
            f"{NUTRIENT_LABELS[nutrient]} must be a number.", field=nutrient
        ) from exc
    if allow_display_values and unit_text:
        if nutrient == "calories" and re.search(r"\bkj\b", unit_text):
            number /= 4.184
        elif nutrient == "sodium":
            if re.search(r"(?:\b|\d)(?:mcg|ug|µg)\b", unit_text):
                number /= 1000
            elif re.search(r"(?:\b|\d)g\b", unit_text) and not re.search(
                r"(?:\b|\d)mg\b", unit_text
            ):
                number *= 1000
        elif nutrient != "calories":
            if re.search(r"(?:\b|\d)(?:mcg|ug|µg)\b", unit_text):
                number /= 1_000_000
            elif re.search(r"(?:\b|\d)mg\b", unit_text):
                number /= 1000
    if not math.isfinite(number) or number < 0:
        raise NutritionValidationError(
            f"{NUTRIENT_LABELS[nutrient]} must be zero or more.", field=nutrient
        )
    maximum = NUTRIENT_MAXIMUMS[nutrient]
    if number > maximum:
        raise NutritionValidationError(
            f"{NUTRIENT_LABELS[nutrient]} must not exceed {maximum:g} {NUTRIENT_UNITS[nutrient]}.",
            field=nutrient,
        )
    return _compact_number(number, digits=6)


def normalize_nutrition(value, *, allow_display_values=False):
    """Return only nutrients with real values, preserving missing versus zero."""

    mapped = _nutrition_mapping(value)
    normalized = {}
    for nutrient in NUTRIENT_FIELDS:
        raw = None
        present = False
        for alias in NUTRIENT_ALIASES[nutrient]:
            if alias in mapped and mapped[alias] not in (None, ""):
                raw = mapped[alias]
                present = True
                break
        if present:
            normalized[nutrient] = _nutrition_number(
                raw, nutrient, allow_display_values=allow_display_values
            )
    return normalized


def complete_nutrition(value):
    normalized = normalize_nutrition(value)
    return {nutrient: normalized.get(nutrient) for nutrient in NUTRIENT_FIELDS}


def scale_nutrition(value, multiplier):
    factor = _normalize_positive_number(
        multiplier, field="Servings", maximum=MAX_SERVINGS
    )
    nutrition = normalize_nutrition(value)
    return normalize_nutrition({
        nutrient: _compact_number(amount * factor, digits=3)
        for nutrient, amount in nutrition.items()
    })


def _aggregate_nutrition(records, *, nutrition_key="nutrition", status_key="nutrition_status"):
    records = list(records)
    totals = {nutrient: 0.0 for nutrient in NUTRIENT_FIELDS}
    present_counts = {nutrient: 0 for nutrient in NUTRIENT_FIELDS}
    partial_flags = {nutrient: False for nutrient in NUTRIENT_FIELDS}
    for record in records:
        nutrition = normalize_nutrition(record.get(nutrition_key) or {})
        statuses = record.get(status_key) if isinstance(record.get(status_key), Mapping) else {}
        for nutrient in NUTRIENT_FIELDS:
            if nutrient in nutrition:
                totals[nutrient] += nutrition[nutrient]
                present_counts[nutrient] += 1
            if statuses.get(nutrient) == "partial":
                partial_flags[nutrient] = True

    values = {}
    status = {}
    for nutrient in NUTRIENT_FIELDS:
        count = present_counts[nutrient]
        values[nutrient] = _compact_number(totals[nutrient], digits=3) if count else None
        if count == 0:
            status[nutrient] = "missing"
        elif count == len(records) and not partial_flags[nutrient]:
            status[nutrient] = "complete"
        else:
            status[nutrient] = "partial"
    return values, status


def _normalize_identifier(value, *, field, required=False):
    identifier = _clean_text(value)
    if not identifier and not required:
        return ""
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise NutritionValidationError(f"{field} is invalid.", field=field)
    return identifier


def _new_identifier():
    return uuid.uuid4().hex


def _normalize_timezone_metadata(payload):
    result = {}
    timezone_name = _clean_text(
        payload.get("timezone") if isinstance(payload, Mapping) else ""
    )
    if timezone_name:
        timezone_parts = timezone_name.split("/")
        if (
            len(timezone_name) > 100
            or not _TIMEZONE_RE.fullmatch(timezone_name)
            or any(part in {"", ".", ".."} for part in timezone_parts)
            or ".." in timezone_name
        ):
            raise NutritionValidationError(
                "Timezone must be a valid IANA timezone name.", field="timezone"
            )
        result["timezone"] = timezone_name

    offset = payload.get("timezone_offset_minutes") if isinstance(payload, Mapping) else None
    if offset not in (None, ""):
        if isinstance(offset, bool):
            raise NutritionValidationError(
                "Timezone offset must be a whole number of minutes.",
                field="timezone_offset_minutes",
            )
        try:
            parsed = int(offset)
        except (TypeError, ValueError) as exc:
            raise NutritionValidationError(
                "Timezone offset must be a whole number of minutes.",
                field="timezone_offset_minutes",
            ) from exc
        if str(offset).strip() not in {str(parsed), f"+{parsed}"} and not isinstance(offset, int):
            raise NutritionValidationError(
                "Timezone offset must be a whole number of minutes.",
                field="timezone_offset_minutes",
            )
        if parsed < -840 or parsed > 840:
            raise NutritionValidationError(
                "Timezone offset must be between -840 and 840 minutes.",
                field="timezone_offset_minutes",
            )
        result["timezone_offset_minutes"] = parsed
    return result


def _normalize_local_time(value, *, fallback=""):
    local_time = _clean_text(value) or fallback
    if local_time and not _LOCAL_TIME_RE.fullmatch(local_time):
        raise NutritionValidationError(
            "Time must use a 24-hour HH:MM value.", field="local_time"
        )
    return local_time


def _normalize_food_item(item):
    if not isinstance(item, Mapping):
        raise NutritionValidationError("Each food item must be an object.", field="food_items")
    name = _clean_text(item.get("name"))
    if not name:
        raise NutritionValidationError("Enter a food name.", field="food_items")
    if len(name) > MAX_MEAL_NAME_LENGTH:
        raise NutritionValidationError(
            f"Food names must be {MAX_MEAL_NAME_LENGTH} characters or fewer.",
            field="food_items",
        )
    quantity_value = item.get("quantity")
    if quantity_value in (None, ""):
        quantity_value = item.get("serving_amount", item.get("amount", 1))
    quantity = _normalize_positive_number(
        quantity_value,
        field="Food quantity",
        maximum=MAX_ITEM_QUANTITY,
    )
    unit = _clean_text(item.get("unit") or item.get("serving_unit"))
    if len(unit) > 50:
        raise NutritionValidationError(
            "Food units must be 50 characters or fewer.", field="food_items"
        )

    per_unit_source = item.get("nutrition_per_unit")
    if per_unit_source is None:
        per_unit_source = item.get("nutrition_per_serving")
    if isinstance(per_unit_source, (Mapping, list)):
        per_unit = normalize_nutrition(per_unit_source)
        if not per_unit and isinstance(item.get("nutrition"), (Mapping, list)):
            total = normalize_nutrition(item.get("nutrition") or {})
            per_unit = {
                nutrient: _compact_number(amount / quantity, digits=6)
                for nutrient, amount in total.items()
            }
    else:
        total = normalize_nutrition(item.get("nutrition") or {})
        per_unit = {
            nutrient: _compact_number(amount / quantity, digits=6)
            for nutrient, amount in total.items()
        }
    nutrition = normalize_nutrition({
        nutrient: _compact_number(amount * quantity, digits=3)
        for nutrient, amount in per_unit.items()
    })
    normalized = {
        "id": _normalize_identifier(item.get("id"), field="Food item id") or _new_identifier(),
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "nutrition_per_unit": per_unit,
        "nutrition": nutrition,
    }
    confidence = item.get("confidence")
    if confidence not in (None, ""):
        normalized["confidence"] = _normalize_positive_number(
            confidence,
            field="Food confidence",
            minimum=0,
            maximum=1,
            allow_zero=True,
        )
    return normalized


def normalize_food_items(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise NutritionValidationError("Food items must be a list.", field="food_items")
    if len(value) > MAX_FOOD_ITEMS:
        raise NutritionValidationError(
            f"A meal may contain at most {MAX_FOOD_ITEMS} food items.", field="food_items"
        )
    return [_normalize_food_item(item) for item in value]


def _nutrition_from_food_items(items):
    values, status = _aggregate_nutrition(items)
    return (
        normalize_nutrition(
            {nutrient: value for nutrient, value in values.items() if value is not None}
        ),
        status,
    )


def _parse_serving_count(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return _normalize_positive_number(
                value, field="Servings", maximum=MAX_SERVINGS
            )
        except NutritionValidationError:
            return None
    text = _clean_text(value)
    mixed = re.search(r"(?<!\d)(\d+)\s+(\d+)/(\d+)(?!\d)", text)
    fraction = re.search(r"(?<![\d/])(\d+)/(\d+)(?![\d/])", text)
    decimal = re.search(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", text)
    try:
        if mixed:
            whole, numerator, denominator = mixed.groups()
            return _normalize_positive_number(
                float(Fraction(int(whole), 1) + Fraction(int(numerator), int(denominator))),
                field="Servings",
                maximum=MAX_SERVINGS,
            )
        if fraction:
            numerator, denominator = fraction.groups()
            return _normalize_positive_number(
                float(Fraction(int(numerator), int(denominator))),
                field="Servings",
                maximum=MAX_SERVINGS,
            )
        if decimal:
            return _normalize_positive_number(
                decimal.group(0), field="Servings", maximum=MAX_SERVINGS
            )
    except (NutritionValidationError, ZeroDivisionError):
        return None
    return None


def build_recipe_nutrition_snapshot(
    recipe,
    selected_servings,
    *,
    recipe_url="",
    recipe_name="",
    base_servings=None,
):
    """Create a scaled, immutable recipe snapshot for one historical meal."""

    if not isinstance(recipe, Mapping):
        raise NutritionValidationError("Recipe data is invalid.", field="recipe")
    selected = _normalize_positive_number(
        selected_servings, field="Servings", maximum=MAX_SERVINGS
    )
    resolved_url = _clean_text(recipe_url or recipe.get("url") or recipe.get("recipe_url"))
    if not resolved_url or len(resolved_url) > 2048 or any(ord(char) < 32 for char in resolved_url):
        raise NutritionValidationError("Choose a valid AI Pantry recipe.", field="recipe_url")
    resolved_name = _clean_text(
        recipe_name or recipe.get("name") or recipe.get("title") or recipe.get("recipe_name")
    )
    if not resolved_name:
        raise NutritionValidationError("Recipe name is required.", field="recipe_url")
    if len(resolved_name) > MAX_MEAL_NAME_LENGTH:
        raise NutritionValidationError(
            f"Recipe names must be {MAX_MEAL_NAME_LENGTH} characters or fewer.",
            field="recipe_url",
        )

    nutrition_source = recipe.get("nutrition")
    if nutrition_source is None:
        nutrition_source = recipe.get("nutrition_data") or {}
    source_nutrition = normalize_nutrition(
        nutrition_source, allow_display_values=True
    )
    nutrition_mapping = _nutrition_mapping(nutrition_source)
    basis_text = _clean_text(
        nutrition_mapping.get("serving_basis")
        or recipe.get("nutrition_serving_basis")
        or "per serving"
    ).lower()
    whole_recipe_basis = any(token in basis_text for token in ("whole", "full", "entire", "total recipe"))
    basis = "whole_recipe" if whole_recipe_basis else "per_serving"

    resolved_base = _parse_serving_count(base_servings)
    if resolved_base is None:
        scaling = recipe.get("scaling") if isinstance(recipe.get("scaling"), Mapping) else {}
        resolved_base = _parse_serving_count(scaling.get("base_servings"))
    if resolved_base is None:
        resolved_base = _parse_serving_count(
            recipe.get("servings") or recipe.get("yield") or recipe.get("recipeYield")
        )
    if resolved_base is None:
        resolved_base = 1

    multiplier = selected / resolved_base if basis == "whole_recipe" else selected
    scaled = normalize_nutrition({
        nutrient: _compact_number(amount * multiplier, digits=3)
        for nutrient, amount in source_nutrition.items()
    })
    return {
        "recipe_url": resolved_url,
        "recipe_name": resolved_name,
        "selected_servings": selected,
        "base_servings": resolved_base,
        "nutrition_basis": basis,
        "source_nutrition": source_nutrition,
        "nutrition": scaled,
    }


def _normalize_recipe_snapshot(value):
    if value in (None, ""):
        return None
    if not isinstance(value, Mapping):
        raise NutritionValidationError("Recipe snapshot is invalid.", field="recipe_snapshot")
    recipe_url = _clean_text(value.get("recipe_url"))
    recipe_name = _clean_text(value.get("recipe_name"))
    if not recipe_url or len(recipe_url) > 2048 or any(ord(char) < 32 for char in recipe_url):
        raise NutritionValidationError("Recipe snapshot is invalid.", field="recipe_snapshot")
    if not recipe_name or len(recipe_name) > MAX_MEAL_NAME_LENGTH:
        raise NutritionValidationError("Recipe snapshot is invalid.", field="recipe_snapshot")
    selected = _normalize_positive_number(
        value.get("selected_servings", 1), field="Servings", maximum=MAX_SERVINGS
    )
    base = _normalize_positive_number(
        value.get("base_servings", 1), field="Base servings", maximum=MAX_SERVINGS
    )
    basis = _clean_text(value.get("nutrition_basis")) or "per_serving"
    if basis not in {"per_serving", "whole_recipe"}:
        raise NutritionValidationError("Recipe nutrition basis is invalid.", field="recipe_snapshot")
    return {
        "recipe_url": recipe_url,
        "recipe_name": recipe_name,
        "selected_servings": selected,
        "base_servings": base,
        "nutrition_basis": basis,
        "source_nutrition": normalize_nutrition(value.get("source_nutrition") or {}),
        "nutrition": normalize_nutrition(value.get("nutrition") or {}),
    }


def _normalize_saved_meal_snapshot(value):
    if value in (None, ""):
        return None
    if not isinstance(value, Mapping):
        raise NutritionValidationError(
            "Saved meal snapshot is invalid.", field="saved_meal_id"
        )
    saved_id = _normalize_identifier(
        value.get("saved_meal_id") or value.get("id"),
        field="Saved meal id",
        required=True,
    )
    name = _clean_text(value.get("name"))
    if not name or len(name) > MAX_SAVED_MEAL_NAME_LENGTH:
        raise NutritionValidationError(
            "Saved meal snapshot is invalid.", field="saved_meal_id"
        )
    snapshot = {
        "saved_meal_id": saved_id,
        "name": name,
        "base_servings": _normalize_positive_number(
            value.get("base_servings", 1), field="Base servings", maximum=MAX_SERVINGS
        ),
        "selected_servings": _normalize_positive_number(
            value.get("selected_servings", 1), field="Servings", maximum=MAX_SERVINGS
        ),
        "nutrition": normalize_nutrition(value.get("nutrition") or {}),
        "food_items": normalize_food_items(value.get("food_items") or []),
    }
    template_updated_at = _clean_text(value.get("template_updated_at"))
    if template_updated_at:
        snapshot["template_updated_at"] = template_updated_at
    return snapshot


def _meal_source_types(payload, description, recipe_snapshot, saved_snapshot):
    photo_id = _normalize_identifier(payload.get("photo_id"), field="Meal photo id")
    types = []
    if photo_id:
        types.append("photo")
    if description:
        types.append("description")
    if recipe_snapshot:
        types.append("recipe")
    if saved_snapshot:
        types.append("saved_meal")
    if not types:
        raise NutritionValidationError(
            "Add a meal photo, description, AI Pantry recipe, or saved meal.",
            field="meal_source",
        )
    return photo_id, types


def _meal_name(payload, meal_type, description, recipe_snapshot, saved_snapshot):
    name = _clean_text(payload.get("name") or payload.get("meal_name"))
    if not name and saved_snapshot:
        name = saved_snapshot["name"]
    if not name and recipe_snapshot:
        name = recipe_snapshot["recipe_name"]
    if not name and description:
        name = description.splitlines()[0][:MAX_MEAL_NAME_LENGTH].strip()
    if not name:
        name = MEAL_TYPE_LABELS[meal_type]
    if len(name) > MAX_MEAL_NAME_LENGTH:
        raise NutritionValidationError(
            f"Meal name must be {MAX_MEAL_NAME_LENGTH} characters or fewer.",
            field="name",
        )
    return name


def _normalize_meal_payload(
    payload,
    *,
    record_id=None,
    created_at=None,
    now=None,
    reference_date=None,
    allow_future=False,
):
    if not isinstance(payload, Mapping):
        raise NutritionValidationError("Meal data is invalid.")
    local_date = normalize_local_date(
        payload.get("local_date") or payload.get("date"),
        reference_date=reference_date,
        allow_future=allow_future,
    )
    meal_type = normalize_meal_type(payload.get("meal_type"))
    description = normalize_description(payload.get("description"))
    recipe_snapshot = _normalize_recipe_snapshot(payload.get("recipe_snapshot"))
    saved_snapshot = _normalize_saved_meal_snapshot(payload.get("saved_meal_snapshot"))
    photo_id, source_types = _meal_source_types(
        payload, description, recipe_snapshot, saved_snapshot
    )
    food_items = normalize_food_items(payload.get("food_items") or [])
    if food_items:
        nutrition, nutrition_status = _nutrition_from_food_items(food_items)
    else:
        fallback_nutrition = payload.get("nutrition")
        if fallback_nutrition is None and recipe_snapshot:
            fallback_nutrition = recipe_snapshot.get("nutrition")
        if fallback_nutrition is None and saved_snapshot:
            fallback_nutrition = saved_snapshot.get("nutrition")
        nutrition = normalize_nutrition(fallback_nutrition or {})
        nutrition_status = {
            nutrient: "complete" if nutrient in nutrition else "missing"
            for nutrient in NUTRIENT_FIELDS
        }

    moment = now or datetime.now(timezone.utc)
    logged_at = _parse_timestamp(
        payload.get("logged_at"), field="logged_at", fallback=moment
    )
    parsed_logged = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
    local_time = _normalize_local_time(
        payload.get("local_time"), fallback=parsed_logged.strftime("%H:%M")
    )
    normalized = {
        "id": _normalize_identifier(record_id or payload.get("id"), field="Meal id")
        or _new_identifier(),
        "local_date": local_date,
        "meal_type": meal_type,
        "name": _meal_name(payload, meal_type, description, recipe_snapshot, saved_snapshot),
        "description": description,
        "source_types": source_types,
        "food_items": food_items,
        "nutrition": nutrition,
        "nutrition_status": nutrition_status,
        "servings": _normalize_positive_number(
            payload.get("servings", 1), field="Servings", maximum=MAX_SERVINGS
        ),
        "local_time": local_time,
        "logged_at": logged_at,
        "created_at": created_at or _utc_timestamp(moment),
        "updated_at": _utc_timestamp(moment),
    }
    if photo_id:
        normalized["photo_id"] = photo_id
    if recipe_snapshot:
        normalized["recipe_snapshot"] = recipe_snapshot
    if saved_snapshot:
        normalized["saved_meal_snapshot"] = saved_snapshot
        normalized["saved_meal_id"] = saved_snapshot["saved_meal_id"]
    normalized.update(_normalize_timezone_metadata(payload))
    token = _normalize_identifier(
        payload.get("client_request_id"), field="Client request id"
    )
    if token:
        normalized["client_request_id"] = token
    return normalized


def _normalize_saved_meal_payload(payload, *, record_id=None, created_at=None, now=None):
    if not isinstance(payload, Mapping):
        raise NutritionValidationError("Saved meal data is invalid.")
    name = _clean_text(payload.get("name"))
    if not name:
        raise NutritionValidationError("Enter a saved meal name.", field="name")
    if len(name) > MAX_SAVED_MEAL_NAME_LENGTH:
        raise NutritionValidationError(
            f"Saved meal name must be {MAX_SAVED_MEAL_NAME_LENGTH} characters or fewer.",
            field="name",
        )
    default_meal_type = payload.get("default_meal_type") or payload.get("meal_type")
    normalized_type = normalize_meal_type(default_meal_type) if default_meal_type else None
    food_items = normalize_food_items(payload.get("food_items") or [])
    if food_items:
        nutrition, nutrition_status = _nutrition_from_food_items(food_items)
    else:
        nutrition = normalize_nutrition(payload.get("nutrition") or {})
        nutrition_status = {
            nutrient: "complete" if nutrient in nutrition else "missing"
            for nutrient in NUTRIENT_FIELDS
        }
    moment = now or datetime.now(timezone.utc)
    normalized = {
        "id": _normalize_identifier(record_id or payload.get("id"), field="Saved meal id")
        or _new_identifier(),
        "name": name,
        "default_meal_type": normalized_type,
        "base_servings": _normalize_positive_number(
            payload.get("base_servings", 1), field="Base servings", maximum=MAX_SERVINGS
        ),
        "food_items": food_items,
        "nutrition": nutrition,
        "nutrition_status": nutrition_status,
        "created_at": created_at or _utc_timestamp(moment),
        "updated_at": _utc_timestamp(moment),
    }
    recipe_snapshot = _normalize_recipe_snapshot(payload.get("recipe_snapshot"))
    if recipe_snapshot:
        normalized["recipe_snapshot"] = recipe_snapshot
    return normalized


def normalize_water_unit(value):
    normalized = _normalized_key(value)
    aliases = {
        "ml": "ml",
        "milliliter": "ml",
        "milliliters": "ml",
        "millilitre": "ml",
        "millilitres": "ml",
        "fl_oz": "fl_oz",
        "floz": "fl_oz",
        "fluid_ounce": "fl_oz",
        "fluid_ounces": "fl_oz",
        "ounce": "fl_oz",
        "ounces": "fl_oz",
        "oz": "fl_oz",
    }
    unit = aliases.get(normalized)
    if not unit:
        raise NutritionValidationError("Choose mL or fl oz.", field="unit")
    return unit


def water_amount_to_ml(amount, unit):
    normalized_unit = normalize_water_unit(unit)
    numeric = _normalize_positive_number(
        amount, field="Water amount", maximum=MAX_WATER_ENTRY_ML
    )
    amount_ml = numeric if normalized_unit == "ml" else numeric * ML_PER_FLUID_OUNCE
    if amount_ml > MAX_WATER_ENTRY_ML:
        raise NutritionValidationError(
            f"Water amount must not exceed {MAX_WATER_ENTRY_ML:g} mL.",
            field="amount",
        )
    return _compact_number(amount_ml, digits=3)


def water_amount_from_ml(amount_ml, unit):
    normalized_unit = normalize_water_unit(unit)
    numeric = _normalize_positive_number(
        amount_ml,
        field="Water amount",
    )
    converted = numeric if normalized_unit == "ml" else numeric / ML_PER_FLUID_OUNCE
    return _compact_number(converted, digits=2)


def _normalize_water_payload(
    payload,
    *,
    record_id=None,
    created_at=None,
    now=None,
    reference_date=None,
    allow_future=False,
):
    if not isinstance(payload, Mapping):
        raise NutritionValidationError("Water entry data is invalid.")
    local_date = normalize_local_date(
        payload.get("local_date") or payload.get("date"),
        reference_date=reference_date,
        allow_future=allow_future,
    )
    unit = normalize_water_unit(payload.get("unit"))
    amount = _normalize_positive_number(
        payload.get("amount"), field="Water amount", maximum=MAX_WATER_ENTRY_ML
    )
    amount_ml = water_amount_to_ml(amount, unit)
    moment = now or datetime.now(timezone.utc)
    occurred_at_input = payload.get("occurred_at")
    occurred_at = _parse_timestamp(
        occurred_at_input, field="occurred_at", fallback=moment
    )
    if occurred_at_input:
        original = datetime.fromisoformat(
            _clean_text(occurred_at_input).replace("Z", "+00:00")
        )
        fallback_time = original.strftime("%H:%M")
    else:
        fallback_time = moment.strftime("%H:%M")
    local_time = _normalize_local_time(payload.get("local_time"), fallback=fallback_time)
    source = _clean_text(payload.get("source")) or "manual"
    if len(source) > 80 or any(ord(char) < 32 for char in source):
        raise NutritionValidationError(
            "Water source must be 80 characters or fewer.", field="source"
        )
    normalized = {
        "id": _normalize_identifier(record_id or payload.get("id"), field="Water entry id")
        or _new_identifier(),
        "local_date": local_date,
        "amount": amount,
        "unit": unit,
        "unit_label": WATER_UNIT_LABELS[unit],
        "amount_ml": amount_ml,
        "local_time": local_time,
        "occurred_at": occurred_at,
        "source": source,
        "created_at": created_at or _utc_timestamp(moment),
        "updated_at": _utc_timestamp(moment),
    }
    normalized.update(_normalize_timezone_metadata(payload))
    token = _normalize_identifier(
        payload.get("client_request_id"), field="Client request id"
    )
    if token:
        normalized["client_request_id"] = token
    return normalized


def _default_settings():
    return {
        "preferred_water_unit": None,
        "water_goal_ml": None,
        "nutrition_goals": {},
    }


def _normalize_settings(value, *, strict=False):
    source = value if isinstance(value, Mapping) else {}
    result = _default_settings()
    preferred = source.get("preferred_water_unit")
    if preferred not in (None, ""):
        try:
            result["preferred_water_unit"] = normalize_water_unit(preferred)
        except NutritionValidationError:
            if strict:
                raise
    water_goal = source.get("water_goal_ml")
    if water_goal not in (None, ""):
        try:
            result["water_goal_ml"] = _normalize_positive_number(
                water_goal,
                field="Water goal",
                maximum=MAX_WATER_GOAL_ML,
            )
        except NutritionValidationError:
            if strict:
                raise
    goals_source = source.get("nutrition_goals")
    if isinstance(goals_source, Mapping):
        for nutrient in NUTRIENT_FIELDS:
            raw = goals_source.get(nutrient)
            if raw in (None, ""):
                continue
            try:
                goal = _nutrition_number(raw, nutrient, allow_display_values=False)
                if goal <= 0:
                    raise NutritionValidationError(
                        f"{NUTRIENT_LABELS[nutrient]} goal must be more than zero.",
                        field=nutrient,
                    )
                result["nutrition_goals"][nutrient] = goal
            except NutritionValidationError:
                if strict:
                    raise
    return result


def _default_document():
    return {
        "schema_version": SCHEMA_VERSION,
        "meals": {},
        "meal_ids_by_date": {},
        "saved_meals": {},
        "water_entries": {},
        "water_entry_ids_by_date": {},
        "idempotency": {
            "meal_create": {},
            "saved_meal_create": {},
            "water_create": {},
        },
        "settings": _default_settings(),
        "updated_at": None,
    }


def _records(value):
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def _safe_normalize(callback, value):
    try:
        return callback(value)
    except (NutritionValidationError, TypeError, ValueError):
        return None


def _normalize_document(payload):
    document = _default_document()
    source = payload if isinstance(payload, Mapping) else {}
    source_version = source.get("schema_version")
    if source_version not in (None, ""):
        try:
            parsed_version = int(source_version)
        except (TypeError, ValueError) as exc:
            raise NutritionSchemaError(
                "Nutrition data has an invalid schema version."
            ) from exc
        if parsed_version > SCHEMA_VERSION:
            raise NutritionSchemaError(
                "Nutrition data requires a newer application version."
            )
    for meal in _records(source.get("meals")):
        if not isinstance(meal, Mapping):
            continue
        normalized = _safe_normalize(
            lambda value: _normalize_meal_payload(
                value,
                record_id=value.get("id"),
                created_at=_clean_text(value.get("created_at")) or None,
                allow_future=True,
            ),
            meal,
        )
        if normalized:
            normalized["updated_at"] = _clean_text(meal.get("updated_at")) or normalized["updated_at"]
            document["meals"][normalized["id"]] = normalized

    for template in _records(source.get("saved_meals")):
        if not isinstance(template, Mapping):
            continue
        normalized = _safe_normalize(
            lambda value: _normalize_saved_meal_payload(
                value,
                record_id=value.get("id"),
                created_at=_clean_text(value.get("created_at")) or None,
            ),
            template,
        )
        if normalized:
            normalized["updated_at"] = _clean_text(template.get("updated_at")) or normalized["updated_at"]
            document["saved_meals"][normalized["id"]] = normalized

    for entry in _records(source.get("water_entries")):
        if not isinstance(entry, Mapping):
            continue
        normalized = _safe_normalize(
            lambda value: _normalize_water_payload(
                value,
                record_id=value.get("id"),
                created_at=_clean_text(value.get("created_at")) or None,
                allow_future=True,
            ),
            entry,
        )
        if normalized:
            normalized["updated_at"] = _clean_text(entry.get("updated_at")) or normalized["updated_at"]
            document["water_entries"][normalized["id"]] = normalized

    idempotency = source.get("idempotency") if isinstance(source.get("idempotency"), Mapping) else {}
    for namespace in document["idempotency"]:
        namespace_records = idempotency.get(namespace)
        if not isinstance(namespace_records, Mapping):
            continue
        for token, value in namespace_records.items():
            if not isinstance(value, Mapping):
                continue
            try:
                safe_token = _normalize_identifier(token, field="Client request id", required=True)
                entity_id = _normalize_identifier(
                    value.get("entity_id"), field="Entity id", required=True
                )
            except NutritionValidationError:
                continue
            document["idempotency"][namespace][safe_token] = {
                "entity_id": entity_id,
                "fingerprint": _clean_text(value.get("fingerprint")),
                "created_at": _clean_text(value.get("created_at")),
            }

    document["settings"] = _normalize_settings(source.get("settings"))
    document["updated_at"] = _clean_text(source.get("updated_at")) or None
    _rebuild_date_indexes(document)
    return document


def _rebuild_date_indexes(document):
    meal_index = {}
    for meal_id, meal in document["meals"].items():
        meal_index.setdefault(meal["local_date"], []).append(meal_id)
    for day, ids in meal_index.items():
        ids.sort(
            key=lambda item: (
                document["meals"][item].get("local_time") or "",
                document["meals"][item].get("logged_at") or "",
                item,
            )
        )
    document["meal_ids_by_date"] = dict(sorted(meal_index.items()))

    water_index = {}
    for entry_id, entry in document["water_entries"].items():
        water_index.setdefault(entry["local_date"], []).append(entry_id)
    for day, ids in water_index.items():
        ids.sort(
            key=lambda item: (
                document["water_entries"][item].get("local_time") or "",
                document["water_entries"][item].get("occurred_at") or "",
                item,
            )
        )
    document["water_entry_ids_by_date"] = dict(sorted(water_index.items()))


def _legacy_loader():
    if not NUTRITION_FILE.exists():
        return _default_document()
    try:
        return json.loads(NUTRITION_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return _default_document()


def _load_document_unlocked():
    payload = durable_runtime.load_json_document(
        _legacy_loader,
        domain=DOCUMENT_DOMAIN,
        document_key=DOCUMENT_KEY,
        source_key=SOURCE_KEY,
        source_ref=SOURCE_REF,
    )
    return _normalize_document(payload)


def load_nutrition_tracking():
    with NUTRITION_LOCK:
        return deepcopy(_load_document_unlocked())


def _save_document_unlocked(document, *, now=None):
    normalized = _normalize_document(document)
    normalized["schema_version"] = SCHEMA_VERSION
    normalized["updated_at"] = _utc_timestamp(now)
    _rebuild_date_indexes(normalized)
    durable_runtime.save_json_document(
        normalized,
        lambda value: durable_runtime.atomic_write_json(NUTRITION_FILE, value),
        domain=DOCUMENT_DOMAIN,
        document_key=DOCUMENT_KEY,
        source_key=SOURCE_KEY,
        source_ref=SOURCE_REF,
    )
    document.clear()
    document.update(deepcopy(normalized))
    return normalized


def _mutation_document():
    return workspace_write_lock("nutrition")


def _payload_fingerprint(payload):
    if not isinstance(payload, Mapping):
        raise NutritionValidationError("Request data is invalid.")
    cleaned = deepcopy(dict(payload or {}))
    cleaned.pop("client_request_id", None)
    try:
        text = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise NutritionValidationError("Request data is invalid.") from exc
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _idempotent_existing(document, namespace, token, fingerprint, collection):
    if not token:
        return None
    record = document["idempotency"][namespace].get(token)
    if not record:
        return None
    if record.get("fingerprint") != fingerprint:
        raise NutritionConflictError(
            "That request id was already used for different data.",
            field="client_request_id",
        )
    existing = document[collection].get(record.get("entity_id"))
    if existing is None:
        raise NutritionConflictError(
            "That request was already completed and the record is no longer available.",
            field="client_request_id",
        )
    return deepcopy(existing)


def _remember_idempotency(document, namespace, token, fingerprint, entity_id, *, now=None):
    if not token:
        return
    records = document["idempotency"][namespace]
    records[token] = {
        "entity_id": entity_id,
        "fingerprint": fingerprint,
        "created_at": _utc_timestamp(now),
    }
    if len(records) > MAX_IDEMPOTENCY_RECORDS:
        ordered = sorted(
            records,
            key=lambda key: (records[key].get("created_at") or "", key),
        )
        for key in ordered[: len(records) - MAX_IDEMPOTENCY_RECORDS]:
            records.pop(key, None)


def _create_meal_in_document(
    document,
    payload,
    *,
    now=None,
    reference_date=None,
    allow_future=False,
    fingerprint_override="",
):
    token = _normalize_identifier(
        payload.get("client_request_id") if isinstance(payload, Mapping) else "",
        field="Client request id",
    )
    fingerprint = fingerprint_override or _payload_fingerprint(payload)
    existing = _idempotent_existing(
        document, "meal_create", token, fingerprint, "meals"
    )
    if existing:
        return existing, False
    meal = _normalize_meal_payload(
        payload,
        now=now,
        reference_date=reference_date,
        allow_future=allow_future,
    )
    document["meals"][meal["id"]] = meal
    _remember_idempotency(
        document, "meal_create", token, fingerprint, meal["id"], now=now
    )
    return deepcopy(meal), True


def create_meal(payload, *, now=None, reference_date=None, allow_future=False):
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            meal, created = _create_meal_in_document(
                document,
                payload,
                now=now,
                reference_date=reference_date,
                allow_future=allow_future,
            )
            if created:
                _save_document_unlocked(document, now=now)
            return meal


def create_recipe_meal(
    recipe,
    *,
    local_date,
    meal_type,
    selected_servings,
    recipe_url="",
    recipe_name="",
    base_servings=None,
    client_request_id="",
    now=None,
    reference_date=None,
    **meal_values,
):
    snapshot = build_recipe_nutrition_snapshot(
        recipe,
        selected_servings,
        recipe_url=recipe_url,
        recipe_name=recipe_name,
        base_servings=base_servings,
    )
    payload = {
        **meal_values,
        "local_date": local_date,
        "meal_type": meal_type,
        "name": meal_values.get("name") or snapshot["recipe_name"],
        "servings": snapshot["selected_servings"],
        "recipe_snapshot": snapshot,
        "nutrition": snapshot["nutrition"],
        "client_request_id": client_request_id,
    }
    return create_meal(
        payload, now=now, reference_date=reference_date
    )


def get_meal(meal_id):
    identifier = _normalize_identifier(meal_id, field="Meal id", required=True)
    meal = load_nutrition_tracking()["meals"].get(identifier)
    return deepcopy(meal) if meal else None


def list_meals(local_date=None, meal_type=None):
    document = load_nutrition_tracking()
    meal_filter = normalize_meal_filter(meal_type)
    if local_date is None:
        ids = [
            meal_id
            for day in sorted(document["meal_ids_by_date"])
            for meal_id in document["meal_ids_by_date"][day]
        ]
    else:
        day = normalize_local_date(local_date, allow_future=True)
        ids = document["meal_ids_by_date"].get(day, [])
    meals = [document["meals"][meal_id] for meal_id in ids]
    if meal_filter != "all":
        meals = [meal for meal in meals if meal["meal_type"] == meal_filter]
    return deepcopy(meals)


def update_meal(
    meal_id,
    changes,
    *,
    now=None,
    reference_date=None,
    allow_future=False,
):
    identifier = _normalize_identifier(meal_id, field="Meal id", required=True)
    if not isinstance(changes, Mapping):
        raise NutritionValidationError("Meal changes are invalid.")
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            current = document["meals"].get(identifier)
            if current is None:
                raise NutritionNotFoundError("Meal not found.")
            merged = deepcopy(current)
            merged.update(deepcopy(dict(changes)))
            if "date" in changes and "local_date" not in changes:
                merged["local_date"] = changes.get("date")
            if "meal_name" in changes and "name" not in changes:
                merged["name"] = changes.get("meal_name")
            merged["id"] = identifier
            merged["client_request_id"] = current.get("client_request_id", "")
            updated = _normalize_meal_payload(
                merged,
                record_id=identifier,
                created_at=current["created_at"],
                now=now,
                reference_date=reference_date,
                allow_future=allow_future,
            )
            document["meals"][identifier] = updated
            _save_document_unlocked(document, now=now)
            return deepcopy(updated)


def delete_meal(meal_id, *, now=None):
    identifier = _normalize_identifier(meal_id, field="Meal id", required=True)
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            if document["meals"].pop(identifier, None) is None:
                return False
            _save_document_unlocked(document, now=now)
            return True


def _create_saved_meal_in_document(document, payload, *, now=None):
    token = _normalize_identifier(
        payload.get("client_request_id") if isinstance(payload, Mapping) else "",
        field="Client request id",
    )
    fingerprint = _payload_fingerprint(payload)
    existing = _idempotent_existing(
        document, "saved_meal_create", token, fingerprint, "saved_meals"
    )
    if existing:
        return existing, False
    template = _normalize_saved_meal_payload(payload, now=now)
    document["saved_meals"][template["id"]] = template
    _remember_idempotency(
        document,
        "saved_meal_create",
        token,
        fingerprint,
        template["id"],
        now=now,
    )
    return deepcopy(template), True


def create_saved_meal(payload, *, now=None):
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            template, created = _create_saved_meal_in_document(document, payload, now=now)
            if created:
                _save_document_unlocked(document, now=now)
            return template


def create_saved_meal_from_meal(
    meal_id,
    name,
    *,
    default_meal_type=None,
    base_servings=None,
    client_request_id="",
    now=None,
):
    identifier = _normalize_identifier(meal_id, field="Meal id", required=True)
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            meal = document["meals"].get(identifier)
            if meal is None:
                raise NutritionNotFoundError("Meal not found.")
            payload = {
                "name": name,
                "default_meal_type": default_meal_type or meal["meal_type"],
                "base_servings": (
                    meal.get("servings") or 1
                    if base_servings in (None, "")
                    else base_servings
                ),
                "food_items": deepcopy(meal["food_items"]),
                "nutrition": deepcopy(meal["nutrition"]),
                "recipe_snapshot": deepcopy(meal.get("recipe_snapshot")),
                "client_request_id": client_request_id,
            }
            template, created = _create_saved_meal_in_document(document, payload, now=now)
            if created:
                _save_document_unlocked(document, now=now)
            return template


def get_saved_meal(saved_meal_id):
    identifier = _normalize_identifier(
        saved_meal_id, field="Saved meal id", required=True
    )
    template = load_nutrition_tracking()["saved_meals"].get(identifier)
    return deepcopy(template) if template else None


def list_saved_meals():
    templates = list(load_nutrition_tracking()["saved_meals"].values())
    templates.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    return deepcopy(templates)


def update_saved_meal(saved_meal_id, changes, *, now=None):
    identifier = _normalize_identifier(
        saved_meal_id, field="Saved meal id", required=True
    )
    if not isinstance(changes, Mapping):
        raise NutritionValidationError("Saved meal changes are invalid.")
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            current = document["saved_meals"].get(identifier)
            if current is None:
                raise NutritionNotFoundError("Saved meal not found.")
            merged = deepcopy(current)
            merged.update(deepcopy(dict(changes)))
            if "meal_type" in changes and "default_meal_type" not in changes:
                merged["default_meal_type"] = changes.get("meal_type")
            merged["id"] = identifier
            updated = _normalize_saved_meal_payload(
                merged,
                record_id=identifier,
                created_at=current["created_at"],
                now=now,
            )
            document["saved_meals"][identifier] = updated
            _save_document_unlocked(document, now=now)
            return deepcopy(updated)


def delete_saved_meal(saved_meal_id, *, now=None):
    identifier = _normalize_identifier(
        saved_meal_id, field="Saved meal id", required=True
    )
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            if document["saved_meals"].pop(identifier, None) is None:
                return False
            _save_document_unlocked(document, now=now)
            return True


def _scaled_food_items(items, multiplier):
    scaled = []
    for item in items:
        copy = deepcopy(item)
        copy["id"] = _new_identifier()
        copy["quantity"] = _compact_number(copy["quantity"] * multiplier, digits=6)
        copy["nutrition"] = {
            nutrient: _compact_number(amount * copy["quantity"], digits=3)
            for nutrient, amount in copy["nutrition_per_unit"].items()
        }
        scaled.append(copy)
    return scaled


def reuse_saved_meal(
    saved_meal_id,
    *,
    local_date,
    meal_type,
    servings=1,
    client_request_id="",
    now=None,
    reference_date=None,
    **meal_values,
):
    identifier = _normalize_identifier(
        saved_meal_id, field="Saved meal id", required=True
    )
    selected = _normalize_positive_number(
        servings, field="Servings", maximum=MAX_SERVINGS
    )
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            template = document["saved_meals"].get(identifier)
            if template is None:
                raise NutritionNotFoundError("Saved meal not found.")
            multiplier = selected / template["base_servings"]
            food_items = _scaled_food_items(template["food_items"], multiplier)
            scaled_nutrition = {
                nutrient: _compact_number(amount * multiplier, digits=3)
                for nutrient, amount in template["nutrition"].items()
            }
            snapshot = {
                "saved_meal_id": identifier,
                "name": template["name"],
                "base_servings": template["base_servings"],
                "selected_servings": selected,
                "template_updated_at": template["updated_at"],
                "food_items": deepcopy(food_items),
                "nutrition": deepcopy(scaled_nutrition),
            }
            recipe_snapshot = deepcopy(template.get("recipe_snapshot"))
            if recipe_snapshot:
                recipe_snapshot["selected_servings"] = _compact_number(
                    recipe_snapshot["selected_servings"] * multiplier,
                    digits=6,
                )
                recipe_snapshot["nutrition"] = {
                    nutrient: _compact_number(amount * multiplier, digits=3)
                    for nutrient, amount in recipe_snapshot["nutrition"].items()
                }
            payload = {
                **meal_values,
                "local_date": local_date,
                "meal_type": meal_type,
                "name": meal_values.get("name") or template["name"],
                "servings": selected,
                "food_items": food_items,
                "nutrition": scaled_nutrition,
                "saved_meal_snapshot": snapshot,
                "client_request_id": client_request_id,
            }
            if recipe_snapshot:
                payload["recipe_snapshot"] = recipe_snapshot
            stable_fingerprint = _payload_fingerprint(
                {
                    **meal_values,
                    "saved_meal_id": identifier,
                    "local_date": local_date,
                    "meal_type": meal_type,
                    "servings": selected,
                }
            )
            meal, created = _create_meal_in_document(
                document,
                payload,
                now=now,
                reference_date=reference_date,
                fingerprint_override=stable_fingerprint,
            )
            if created:
                _save_document_unlocked(document, now=now)
            return meal


def _create_water_in_document(
    document,
    payload,
    *,
    now=None,
    reference_date=None,
    allow_future=False,
):
    token = _normalize_identifier(
        payload.get("client_request_id") if isinstance(payload, Mapping) else "",
        field="Client request id",
    )
    fingerprint = _payload_fingerprint(payload)
    existing = _idempotent_existing(
        document, "water_create", token, fingerprint, "water_entries"
    )
    if existing:
        return existing, False
    entry = _normalize_water_payload(
        payload,
        now=now,
        reference_date=reference_date,
        allow_future=allow_future,
    )
    document["water_entries"][entry["id"]] = entry
    _remember_idempotency(
        document, "water_create", token, fingerprint, entry["id"], now=now
    )
    return deepcopy(entry), True


def create_water_entry(payload, *, now=None, reference_date=None, allow_future=False):
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            entry, created = _create_water_in_document(
                document,
                payload,
                now=now,
                reference_date=reference_date,
                allow_future=allow_future,
            )
            if created:
                _save_document_unlocked(document, now=now)
            return entry


def get_water_entry(entry_id):
    identifier = _normalize_identifier(
        entry_id, field="Water entry id", required=True
    )
    entry = load_nutrition_tracking()["water_entries"].get(identifier)
    return deepcopy(entry) if entry else None


def list_water_entries(local_date=None):
    document = load_nutrition_tracking()
    if local_date is None:
        ids = [
            entry_id
            for day in sorted(document["water_entry_ids_by_date"])
            for entry_id in document["water_entry_ids_by_date"][day]
        ]
    else:
        day = normalize_local_date(local_date, allow_future=True)
        ids = document["water_entry_ids_by_date"].get(day, [])
    return deepcopy([document["water_entries"][entry_id] for entry_id in ids])


def update_water_entry(
    entry_id,
    changes,
    *,
    now=None,
    reference_date=None,
    allow_future=False,
):
    identifier = _normalize_identifier(
        entry_id, field="Water entry id", required=True
    )
    if not isinstance(changes, Mapping):
        raise NutritionValidationError("Water entry changes are invalid.")
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            current = document["water_entries"].get(identifier)
            if current is None:
                raise NutritionNotFoundError("Water entry not found.")
            merged = deepcopy(current)
            merged.update(deepcopy(dict(changes)))
            if "date" in changes and "local_date" not in changes:
                merged["local_date"] = changes.get("date")
            merged["id"] = identifier
            merged["client_request_id"] = current.get("client_request_id", "")
            updated = _normalize_water_payload(
                merged,
                record_id=identifier,
                created_at=current["created_at"],
                now=now,
                reference_date=reference_date,
                allow_future=allow_future,
            )
            document["water_entries"][identifier] = updated
            _save_document_unlocked(document, now=now)
            return deepcopy(updated)


def delete_water_entry(entry_id, *, now=None):
    identifier = _normalize_identifier(
        entry_id, field="Water entry id", required=True
    )
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            if document["water_entries"].pop(identifier, None) is None:
                return False
            _save_document_unlocked(document, now=now)
            return True


def get_settings():
    return deepcopy(load_nutrition_tracking()["settings"])


def update_settings(changes, *, now=None):
    if not isinstance(changes, Mapping):
        raise NutritionValidationError("Nutrition settings are invalid.")
    with NUTRITION_LOCK:
        with _mutation_document():
            document = _load_document_unlocked()
            merged = deepcopy(document["settings"])
            if "preferred_water_unit" in changes:
                merged["preferred_water_unit"] = changes.get("preferred_water_unit")
            if "water_goal_ml" in changes:
                merged["water_goal_ml"] = changes.get("water_goal_ml")
            if "water_goal" in changes:
                goal = changes.get("water_goal")
                if goal in (None, ""):
                    merged["water_goal_ml"] = None
                elif isinstance(goal, Mapping):
                    goal_unit = normalize_water_unit(goal.get("unit"))
                    goal_amount = _normalize_positive_number(
                        goal.get("amount"),
                        field="Water goal",
                        maximum=MAX_WATER_GOAL_ML,
                    )
                    converted_goal = (
                        goal_amount
                        if goal_unit == "ml"
                        else goal_amount * ML_PER_FLUID_OUNCE
                    )
                    if converted_goal > MAX_WATER_GOAL_ML:
                        raise NutritionValidationError(
                            f"Water goal must not exceed {MAX_WATER_GOAL_ML:g} mL.",
                            field="water_goal",
                        )
                    merged["water_goal_ml"] = _compact_number(
                        converted_goal, digits=3
                    )
                else:
                    raise NutritionValidationError(
                        "Water goal is invalid.", field="water_goal"
                    )
            if "nutrition_goals" in changes:
                goals = changes.get("nutrition_goals")
                if goals in (None, ""):
                    merged["nutrition_goals"] = {}
                elif isinstance(goals, Mapping):
                    merged["nutrition_goals"] = {
                        **merged.get("nutrition_goals", {}),
                        **dict(goals),
                    }
                else:
                    raise NutritionValidationError(
                        "Nutrition goals are invalid.", field="nutrition_goals"
                    )
            settings = _normalize_settings(merged, strict=True)
            document["settings"] = settings
            _save_document_unlocked(document, now=now)
            return deepcopy(settings)


def _water_summary(document, local_date):
    ids = document["water_entry_ids_by_date"].get(local_date, [])
    entries = [document["water_entries"][entry_id] for entry_id in ids]
    total_ml = _compact_number(sum(entry["amount_ml"] for entry in entries), digits=3)
    settings = document["settings"]
    preferred_unit = settings.get("preferred_water_unit") or "fl_oz"
    goal_ml = settings.get("water_goal_ml")
    return {
        "total_ml": total_ml,
        "display_amount": (
            water_amount_from_ml(total_ml, preferred_unit) if total_ml > 0 else 0
        ),
        "display_unit": preferred_unit,
        "display_unit_label": WATER_UNIT_LABELS[preferred_unit],
        "entry_count": len(entries),
        "goal_ml": goal_ml,
        "goal_progress_percent": (
            _compact_number(total_ml / goal_ml * 100, digits=1) if goal_ml else None
        ),
    }


def _daily_summary_from_document(document, local_date, meal_filter="all", *, include_records=True):
    ids = document["meal_ids_by_date"].get(local_date, [])
    meals = [document["meals"][meal_id] for meal_id in ids]
    if meal_filter != "all":
        meals = [meal for meal in meals if meal["meal_type"] == meal_filter]
    nutrition, status = _aggregate_nutrition(meals)
    result = {
        "local_date": local_date,
        "meal_filter": meal_filter,
        "meal_filter_label": MEAL_FILTER_LABELS[meal_filter],
        "meal_count": len(meals),
        "food_item_count": sum(len(meal["food_items"]) for meal in meals),
        "nutrition": nutrition,
        "nutrition_status": status,
        "water": _water_summary(document, local_date),
    }
    if include_records:
        result["meals"] = deepcopy(meals)
    return result


def daily_summary(local_date, meal_type=None):
    day = normalize_local_date(local_date, allow_future=True)
    meal_filter = normalize_meal_filter(meal_type)
    document = load_nutrition_tracking()
    return _daily_summary_from_document(document, day, meal_filter)


def weekly_summary(selected_date, meal_type=None, *, days=7):
    end = date.fromisoformat(normalize_local_date(selected_date, allow_future=True))
    meal_filter = normalize_meal_filter(meal_type)
    if isinstance(days, bool):
        raise NutritionValidationError("Weekly range is invalid.")
    try:
        count = int(days)
    except (TypeError, ValueError) as exc:
        raise NutritionValidationError("Weekly range is invalid.") from exc
    if count < 1 or count > 31:
        raise NutritionValidationError("Weekly range must contain 1 to 31 days.")
    start = end - timedelta(days=count - 1)
    document = load_nutrition_tracking()
    rows = [
        _daily_summary_from_document(
            document,
            (start + timedelta(days=offset)).isoformat(),
            meal_filter,
            include_records=False,
        )
        for offset in range(count)
    ]
    aggregate_records = [
        document["meals"][meal_id]
        for row in rows
        for meal_id in document["meal_ids_by_date"].get(row["local_date"], [])
        if meal_filter == "all"
        or document["meals"][meal_id]["meal_type"] == meal_filter
    ]
    nutrition, status = _aggregate_nutrition(aggregate_records)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "meal_filter": meal_filter,
        "meal_filter_label": MEAL_FILTER_LABELS[meal_filter],
        "days": rows,
        "meal_count": len(aggregate_records),
        "nutrition": nutrition,
        "nutrition_status": status,
        "water_total_ml": _compact_number(
            sum(row["water"]["total_ml"] for row in rows), digits=3
        ),
        "water_goal_ml": document["settings"].get("water_goal_ml"),
    }


__all__ = [
    "DOCUMENT_DOMAIN",
    "DOCUMENT_KEY",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_WATER_ENTRY_ML",
    "MEAL_FILTER_LABELS",
    "MEAL_TYPES",
    "MEAL_TYPE_LABELS",
    "ML_PER_FLUID_OUNCE",
    "NUTRIENT_FIELDS",
    "NUTRIENT_LABELS",
    "NUTRIENT_UNITS",
    "NutritionConflictError",
    "NutritionNotFoundError",
    "NutritionSchemaError",
    "NutritionValidationError",
    "SCHEMA_VERSION",
    "WATER_UNITS",
    "WATER_UNIT_LABELS",
    "build_recipe_nutrition_snapshot",
    "complete_nutrition",
    "create_meal",
    "create_recipe_meal",
    "create_saved_meal",
    "create_saved_meal_from_meal",
    "create_water_entry",
    "daily_summary",
    "delete_meal",
    "delete_saved_meal",
    "delete_water_entry",
    "get_meal",
    "get_saved_meal",
    "get_settings",
    "get_water_entry",
    "list_meals",
    "list_saved_meals",
    "list_water_entries",
    "load_nutrition_tracking",
    "normalize_description",
    "normalize_food_items",
    "normalize_local_date",
    "normalize_meal_filter",
    "normalize_meal_type",
    "normalize_nutrition",
    "normalize_water_unit",
    "reuse_saved_meal",
    "scale_nutrition",
    "update_meal",
    "update_saved_meal",
    "update_settings",
    "update_water_entry",
    "water_amount_from_ml",
    "water_amount_to_ml",
    "weekly_summary",
]
