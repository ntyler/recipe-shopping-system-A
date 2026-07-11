import json
import math
import re
import threading
import uuid
from datetime import date
from datetime import datetime
from datetime import timedelta
from fractions import Fraction

from PushShoppingList.services.storage_service import scoped_package_path


MEAL_PLAN_FILE = scoped_package_path("meal_plan.json")
MEAL_PLAN_LOCK = threading.RLock()
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


def clean_text(value):
    return str(value or "").strip()


def parse_date(value, fallback=None):
    try:
        return date.fromisoformat(clean_text(value))
    except (TypeError, ValueError):
        return fallback


def week_start(value=None):
    selected = parse_date(value, fallback=date.today())
    return selected - timedelta(days=selected.weekday())


def week_days(value=None):
    start = week_start(value)
    return [start + timedelta(days=offset) for offset in range(7)]


def short_date_label(value):
    return f"{value.strftime('%b')} {value.day}"


def numeric_date_label(value):
    return f"{value.month}/{value.day}"


def normalize_planned_servings(value):
    if isinstance(value, bool) or value is None or clean_text(value) == "":
        raise ValueError("Planned servings must be a number of 1 or more.")

    try:
        planned_servings = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Planned servings must be a number of 1 or more.") from exc

    if not math.isfinite(planned_servings) or planned_servings < 1:
        raise ValueError("Planned servings must be a number of 1 or more.")

    if planned_servings.is_integer():
        return int(planned_servings)
    return planned_servings


def planned_servings_from_yield(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return normalize_planned_servings(value)
        except ValueError:
            return None

    yield_text = clean_text(value)
    if not yield_text:
        return None

    mixed_fraction = re.search(r"(?<!\d)(\d+)\s+(\d+)/(\d+)(?!\d)", yield_text)
    fraction = re.search(r"(?<![\d/])(\d+)/(\d+)(?![\d/])", yield_text)
    decimal = re.search(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", yield_text)

    try:
        if mixed_fraction:
            whole, numerator, denominator = mixed_fraction.groups()
            parsed = Fraction(int(whole), 1) + Fraction(int(numerator), int(denominator))
            return normalize_planned_servings(float(parsed))
        if fraction:
            numerator, denominator = fraction.groups()
            return normalize_planned_servings(float(Fraction(int(numerator), int(denominator))))
        if decimal:
            return normalize_planned_servings(decimal.group(0))
    except (ValueError, ZeroDivisionError):
        return None
    return None


def meal_plan_yield_label(value):
    yield_text = clean_text(value).rstrip(".")
    if not yield_text:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", yield_text):
        try:
            return f"{normalize_planned_servings(yield_text)} servings"
        except ValueError:
            return ""
    return yield_text


def normalize_meal(meal):
    meal_date = parse_date(meal.get("date"))
    meal_type = clean_text(meal.get("meal_type")).lower()
    recipe_url = clean_text(meal.get("recipe_url"))
    recipe_name = clean_text(meal.get("recipe_name"))
    if not meal_date or meal_type not in MEAL_TYPES or not recipe_url or not recipe_name:
        return None

    normalized = {
        "id": clean_text(meal.get("id")) or uuid.uuid4().hex,
        "date": meal_date.isoformat(),
        "meal_type": meal_type,
        "recipe_url": recipe_url,
        "recipe_name": recipe_name,
        "created_at": clean_text(meal.get("created_at"))
        or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    if meal.get("planned_servings") not in (None, ""):
        try:
            normalized["planned_servings"] = normalize_planned_servings(meal.get("planned_servings"))
        except ValueError:
            # Keep legacy/core meal data readable even if an optional serving
            # value in an older file is malformed.
            pass
    return normalized


def load_meal_plan():
    with MEAL_PLAN_LOCK:
        if not MEAL_PLAN_FILE.exists():
            return {"meals": []}
        try:
            payload = json.loads(MEAL_PLAN_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            return {"meals": []}

        meals = []
        for value in payload.get("meals", []) if isinstance(payload, dict) else []:
            normalized = normalize_meal(value) if isinstance(value, dict) else None
            if normalized:
                meals.append(normalized)
        return {"meals": meals}


def save_meal_plan(payload):
    normalized = {
        "meals": [
            normalized_meal
            for meal in payload.get("meals", [])
            if isinstance(meal, dict)
            for normalized_meal in [normalize_meal(meal)]
            if normalized_meal
        ]
    }
    with MEAL_PLAN_LOCK:
        MEAL_PLAN_FILE.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return normalized


def add_meal(meal):
    meal = dict(meal or {})
    if "planned_servings" in meal:
        meal["planned_servings"] = normalize_planned_servings(meal.get("planned_servings"))
    normalized = normalize_meal(meal)
    if not normalized:
        raise ValueError("Choose a valid date, meal type, and recipe.")

    # Keep the complete read/check/append/write operation atomic. Individual
    # load/save locks are not enough when two recipes are added to one slot at
    # nearly the same time because the later write could otherwise win.
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        duplicate = next(
            (
                existing
                for existing in payload["meals"]
                if existing["date"] == normalized["date"]
                and existing["meal_type"] == normalized["meal_type"]
                and existing["recipe_url"] == normalized["recipe_url"]
            ),
            None,
        )
        if duplicate:
            raise ValueError("That recipe is already planned for this meal.")

        payload["meals"].append(normalized)
        save_meal_plan(payload)
    return normalized


def delete_meal(meal_id):
    meal_id = clean_text(meal_id)
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        remaining = [meal for meal in payload["meals"] if meal["id"] != meal_id]
        if len(remaining) == len(payload["meals"]):
            return False
        save_meal_plan({"meals": remaining})
    return True


def meal_plan_home_preview(
    meal_plan=None,
    max_slots=3,
    max_recipes_per_slot=2,
    max_recipes=4,
    reference_date=None,
):
    """Build a compact homepage view of meals on or after a calendar date."""
    try:
        max_slots = max(1, int(max_slots))
    except (TypeError, ValueError):
        max_slots = 3
    try:
        max_recipes_per_slot = max(1, int(max_recipes_per_slot))
    except (TypeError, ValueError):
        max_recipes_per_slot = 2
    try:
        max_recipes = max(1, int(max_recipes))
    except (TypeError, ValueError):
        max_recipes = 4

    meal_plan = meal_plan if isinstance(meal_plan, dict) else load_meal_plan()
    reference_day = parse_date(reference_date, fallback=date.today())
    meal_type_order = {meal_type: index for index, meal_type in enumerate(MEAL_TYPES)}
    upcoming_meals = []
    for meal in meal_plan.get("meals") or []:
        if not isinstance(meal, dict):
            continue
        planned_date = parse_date(meal.get("date"))
        meal_type = clean_text(meal.get("meal_type")).lower()
        if (
            planned_date is None
            or planned_date < reference_day
            or meal_type not in meal_type_order
        ):
            continue
        upcoming_meals.append((planned_date, meal_type_order[meal_type], meal))

    # Python's sort is stable, so recipes in the same date/type slot retain
    # their persisted order while slots are ordered by date and meal type.
    upcoming_meals.sort(key=lambda item: (item[0], item[1]))
    grouped_slots = {}
    for planned_date, _, meal in upcoming_meals:
        slot_key = (planned_date, clean_text(meal.get("meal_type")).lower())
        grouped_slots.setdefault(slot_key, []).append(meal)

    slots = []
    visible_recipe_count = 0
    hidden_meal_count = 0
    hidden_slot_count = 0

    for (planned_date, meal_type), planned_meals in grouped_slots.items():
        remaining_budget = max_recipes - visible_recipe_count
        if len(slots) >= max_slots or remaining_budget <= 0:
            hidden_slot_count += 1
            hidden_meal_count += len(planned_meals)
            continue

        visible_count = min(
            len(planned_meals),
            max_recipes_per_slot,
            remaining_budget,
        )
        visible_meals = planned_meals[:visible_count]
        visible_recipe_count += visible_count
        slots.append({
            "date": planned_date.isoformat(),
            "day_label": (
                "TODAY"
                if planned_date == reference_day
                else planned_date.strftime("%a").upper()
            ),
            "meal_type": meal_type,
            "meal_type_label": meal_type.title(),
            "meals": visible_meals,
            "remaining_count": len(planned_meals) - visible_count,
            "total_count": len(planned_meals),
        })

    return {
        "slots": slots,
        "visible_recipe_count": visible_recipe_count,
        "hidden_meal_count": hidden_meal_count,
        "hidden_slot_count": hidden_slot_count,
    }


def meal_plan_for_week(value=None, reference_date=None):
    reference_day = parse_date(reference_date, fallback=date.today())
    selected_day = parse_date(value, fallback=reference_day)
    days = week_days(selected_day)
    day_keys = {day.isoformat() for day in days}
    meals = [meal for meal in load_meal_plan()["meals"] if meal["date"] in day_keys]
    meals_by_slot = {}
    meals_by_day = {day.isoformat(): {meal_type: [] for meal_type in MEAL_TYPES} for day in days}
    for meal in meals:
        meals_by_slot.setdefault((meal["date"], meal["meal_type"]), []).append(meal)
        meals_by_day[meal["date"]][meal["meal_type"]].append(meal)

    start = days[0]
    end = days[-1]
    return {
        "week_start": start.isoformat(),
        "previous_week": (start - timedelta(days=7)).isoformat(),
        "next_week": (start + timedelta(days=7)).isoformat(),
        "today_week": week_start(reference_day).isoformat(),
        "reference_date": reference_day.isoformat(),
        "range_label": f"{short_date_label(start)} - {short_date_label(end)}, {end.year}",
        "days": [
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%a"),
                "day_label": numeric_date_label(day),
                "is_past": day < reference_day,
                "is_today": day == reference_day,
            }
            for day in days
        ],
        "meal_types": MEAL_TYPES,
        "meals": meals,
        "meals_by_slot": meals_by_slot,
        "meals_by_day": meals_by_day,
        "meal_count": len(meals),
        "unique_recipe_count": len({meal["recipe_url"] for meal in meals}),
    }
