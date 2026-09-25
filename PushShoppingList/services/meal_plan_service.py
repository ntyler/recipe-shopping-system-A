import json
import math
import re
import threading
import uuid
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from PushShoppingList.services.ingredient_option_service import ingredient_name
from PushShoppingList.services.ingredient_option_service import normalize_selection_map
from PushShoppingList.services.ingredient_option_service import option_item
from PushShoppingList.services.ingredient_option_service import resolve_ingredient_requirements
from PushShoppingList.services.recipe_ingredient_requirement_service import (
    recipe_data_with_sql_requirements,
)
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.storage_service import scoped_package_path
from PushShoppingList.services import durable_document_runtime_service as durable_runtime


MEAL_PLAN_FILE = scoped_package_path("meal_plan.json")
MEAL_PLAN_LOCK = threading.RLock()
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
_UNSET = object()


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


def weekday_short_date_label(value):
    return f"{value.strftime('%a, %b')} {value.day}"


def numeric_date_label(value):
    return f"{value.month}/{value.day}"


def normalize_planned_servings(value):
    if isinstance(value, bool) or value is None or clean_text(value) == "":
        raise ValueError("Planned servings must be a number of 1 or more.")

    try:
        planned_servings = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Planned servings must be a number of 1 or more.") from exc

    if not math.isfinite(planned_servings) or planned_servings < 1:
        raise ValueError("Planned servings must be a number of 1 or more.")

    if planned_servings.is_integer():
        return int(planned_servings)
    return planned_servings


def normalize_positive_servings(value, label="Servings"):
    message = f"{label} must be a finite number greater than zero."
    if isinstance(value, bool) or value is None or clean_text(value) == "":
        raise ValueError(message)
    try:
        servings = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(servings) or servings <= 0:
        raise ValueError(message)
    return int(servings) if servings.is_integer() else servings


def servings_number(value):
    return int(value) if value == value.to_integral_value() else float(value)


def normalize_member(value):
    if not isinstance(value, dict):
        return None
    member_id = clean_text(value.get("id"))
    name = clean_text(value.get("name"))
    try:
        default_portion = normalize_positive_servings(value.get("default_portion", 1), "Default portion")
    except ValueError:
        default_portion = 1
    group_ids = value.get("group_ids") if isinstance(value.get("group_ids"), list) else []
    return {
        "id": member_id,
        "name": name,
        "first_name": value.get("first_name", "").strip() if isinstance(value.get("first_name", ""), str) else "",
        "last_name": value.get("last_name", "").strip() if isinstance(value.get("last_name", ""), str) else "",
        "default_portion": default_portion,
        "group_ids": list(dict.fromkeys(item.strip() for item in group_ids if isinstance(item, str) and item.strip())),
        "archived": value.get("archived") is True,
    } if member_id and name else None


def normalize_member_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Enter a family member name.")
    name = value.strip()
    if len(name) > 100:
        raise ValueError("Family member names must be 100 characters or fewer.")
    return name


def normalize_optional_member_name(value, label):
    if not isinstance(value, str) or len(value.strip()) > 100:
        raise ValueError(f"{label} must be text of 100 characters or fewer.")
    return value.strip()


def normalize_group(value):
    if not isinstance(value, dict):
        return None
    group_id, name = clean_text(value.get("id")), clean_text(value.get("name"))
    return {"id": group_id, "name": name, "archived": value.get("archived") is True} if group_id and name else None


def normalize_group_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise ValueError("Enter a group name of 100 characters or fewer.")
    return value.strip()


def validate_member_group_ids(value, groups, previous_ids=()):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("Group IDs must be a list of saved group IDs.")
    group_ids = list(dict.fromkeys(item.strip() for item in value))
    by_id = {group["id"]: group for group in groups}
    for group_id in group_ids:
        group = by_id.get(group_id)
        if not group:
            raise ValueError("Choose groups from your current workspace.")
        if group["archived"] and group_id not in previous_ids:
            raise ValueError("That group is archived. Restore it before assigning new members.")
    return group_ids


def normalize_member_portions(value, members=None):
    """Read snapshots tolerantly; with a member map, validate a new allocation."""
    strict = members is not None
    if not isinstance(value, list) or (strict and not value):
        if strict:
            raise ValueError("Choose at least one family member for every meal.")
        return []
    portions = []
    seen = set()
    for item in value:
        member_id = clean_text(item.get("member_id")) if isinstance(item, dict) else ""
        if not member_id or member_id in seen:
            if strict:
                raise ValueError("Each family member can appear only once per meal.")
            continue
        if strict and member_id not in members:
            raise ValueError("Choose family members from your current workspace.")
        if strict and members[member_id].get("archived"):
            raise ValueError("That family member is archived. Restore them in Family Members before assigning new meals.")
        try:
            servings = normalize_positive_servings(item.get("servings"), "Family member portions")
        except ValueError:
            if strict:
                raise
            continue
        snapshot = members[member_id]["name"] if strict else clean_text(item.get("name_snapshot") or item.get("name"))
        portions.append({"member_id": member_id, "name_snapshot": snapshot, "name": snapshot, "servings": servings})
        seen.add(member_id)
    return portions


def meal_plan_member_summary(member, meals):
    """Count scheduled meals once each, regardless of portions or batch size."""
    meal_ids = {
        meal["id"] for meal in meals
        if any(portion["member_id"] == member["id"] for portion in meal.get("member_portions") or [])
    }
    return {**member, "meal_count": len(meal_ids)}


def list_meal_plan_members(include_archived=False):
    payload = load_meal_plan()
    return [
        meal_plan_member_summary(member, payload["meals"])
        for member in payload["members"]
        if include_archived or not member["archived"]
    ]


def list_meal_plan_groups(include_archived=False):
    return [group for group in load_meal_plan()["groups"] if include_archived or not group["archived"]]


def validate_unique_group_name(name, groups, group_id=None):
    existing = next((group for group in groups if group["id"] != group_id and group["name"].casefold() == name.casefold()), None)
    if existing:
        if existing["archived"]:
            raise ValueError("An archived group with that name already exists. Restore it in Family Members.")
        raise ValueError("A group with that name already exists.")


def add_meal_plan_group(name):
    name = normalize_group_name(name)
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        validate_unique_group_name(name, payload["groups"])
        group = {"id": uuid.uuid4().hex, "name": name, "archived": False}
        payload["groups"].append(group)
        save_meal_plan(payload)
        return group


def update_meal_plan_group(group_id, name=_UNSET, *, archived=_UNSET):
    if name is _UNSET and archived is _UNSET:
        raise ValueError("Provide a group name or archived status to update.")
    if name is not _UNSET:
        name = normalize_group_name(name)
    if archived is not _UNSET and not isinstance(archived, bool):
        raise ValueError("Archived must be true or false.")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        group = next((item for item in payload["groups"] if item["id"] == clean_text(group_id)), None)
        if not group:
            return None
        if name is not _UNSET:
            validate_unique_group_name(name, payload["groups"], group["id"])
            group["name"] = name
        if archived is not _UNSET:
            group["archived"] = archived
        save_meal_plan(payload)
        return group


def validate_unique_member_name(name, members, member_id=None):
    existing = next((
        member for member in members
        if member["id"] != member_id and member["name"].casefold() == name.casefold()
    ), None)
    if existing:
        if existing["archived"]:
            raise ValueError("An archived family member with that name already exists. Restore them in Family Members.")
        raise ValueError("A family member with that name already exists.")


def add_meal_plan_member(name, *, first_name="", last_name="", default_portion=1, group_ids=_UNSET):
    name = normalize_member_name(name)
    first_name = normalize_optional_member_name(first_name, "First name")
    last_name = normalize_optional_member_name(last_name, "Last name")
    default_portion = normalize_positive_servings(default_portion, "Default portion")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        validate_unique_member_name(name, payload["members"])
        group_ids = validate_member_group_ids([] if group_ids is _UNSET else group_ids, payload["groups"])
        member = {"id": uuid.uuid4().hex, "name": name, "first_name": first_name, "last_name": last_name,
                  "default_portion": default_portion, "group_ids": group_ids, "archived": False}
        payload["members"].append(member)
        save_meal_plan(payload)
        return meal_plan_member_summary(member, payload["meals"])


def update_meal_plan_member(member_id, name=_UNSET, *, archived=_UNSET, first_name=_UNSET,
                            last_name=_UNSET, default_portion=_UNSET, group_ids=_UNSET):
    if all(value is _UNSET for value in (name, archived, first_name, last_name, default_portion, group_ids)):
        raise ValueError("Provide member details to update.")
    if name is not _UNSET:
        name = normalize_member_name(name)
    if first_name is not _UNSET:
        first_name = normalize_optional_member_name(first_name, "First name")
    if last_name is not _UNSET:
        last_name = normalize_optional_member_name(last_name, "Last name")
    if default_portion is not _UNSET:
        default_portion = normalize_positive_servings(default_portion, "Default portion")
    if archived is not _UNSET and not isinstance(archived, bool):
        raise ValueError("Archived must be true or false.")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        member = next((item for item in payload["members"] if item["id"] == clean_text(member_id)), None)
        if not member:
            return None
        if group_ids is not _UNSET:
            group_ids = validate_member_group_ids(group_ids, payload["groups"], member["group_ids"])
        if name is not _UNSET:
            validate_unique_member_name(name, payload["members"], member["id"])
            member["name"] = name
        if archived is not _UNSET:
            member["archived"] = archived
        for key, value in (("first_name", first_name), ("last_name", last_name), ("default_portion", default_portion), ("group_ids", group_ids)):
            if value is not _UNSET:
                member[key] = value
        save_meal_plan(payload)
        return meal_plan_member_summary(member, payload["meals"])


def add_meal_plan_members_bulk(members, *, group_ids=_UNSET):
    """Validate the complete paste/import before committing one scoped write."""
    if not isinstance(members, list) or not 1 <= len(members) <= 100:
        raise ValueError("Add between 1 and 100 family members at a time.")
    allowed = {"name", "first_name", "last_name", "default_portion"}
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        selected_groups = validate_member_group_ids([] if group_ids is _UNSET else group_ids, payload["groups"])
        added = []
        for row in members:
            if not isinstance(row, dict) or "name" not in row or set(row) - allowed:
                raise ValueError("Each member needs a name and supported member details.")
            name = normalize_member_name(row["name"])
            validate_unique_member_name(name, payload["members"] + added)
            added.append({
                "id": uuid.uuid4().hex, "name": name, "archived": False,
                "first_name": normalize_optional_member_name(row.get("first_name", ""), "First name"),
                "last_name": normalize_optional_member_name(row.get("last_name", ""), "Last name"),
                "default_portion": normalize_positive_servings(row.get("default_portion", 1), "Default portion"),
                "group_ids": list(selected_groups),
            })
        payload["members"].extend(added)
        save_meal_plan(payload)
        return [meal_plan_member_summary(member, payload["meals"]) for member in added]


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


def normalize_meal_ingredients(value):
    if not isinstance(value, list):
        return []
    return [
        option_item(item)
        for item in value
        if ingredient_name(item)
    ]


def meal_ingredient_snapshot(recipe_data, ingredients):
    """Keep ingredient amounts and their serving basis together for planning."""
    from PushShoppingList.services.recipe_quantity_service import recipe_base_servings, recipe_base_ingredient_quantity, recipe_base_ingredient_unit
    items = normalize_meal_ingredients(ingredients)
    for item in items:
        quantity = recipe_base_ingredient_quantity(item, recipe_data)
        unit = recipe_base_ingredient_unit(item, recipe_data)
        item.update({"quantity": quantity, "base_quantity": quantity, "unit": unit, "base_unit": unit})
    servings = planned_servings_from_yield(recipe_base_servings(recipe_data))
    return {"ingredients": items, **({"ingredient_base_servings": servings} if servings else {})}


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
        "prep_notes": clean_text(meal.get("prep_notes")),
        "created_at": clean_text(meal.get("created_at"))
        or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    if meal.get("planned_servings") not in (None, ""):
        try:
            normalized["planned_servings"] = normalize_positive_servings(meal.get("planned_servings"))
        except ValueError:
            # Keep legacy/core meal data readable even if an optional serving
            # value in an older file is malformed.
            pass
    selections = normalize_selection_map(meal.get("ingredient_option_selections"))
    unresolved_ids = [
        clean_text(value)
        for value in (
            meal.get("unresolved_ingredient_requirement_ids")
            if isinstance(meal.get("unresolved_ingredient_requirement_ids"), list)
            else []
        )
        if clean_text(value)
    ]
    if selections:
        normalized["ingredient_option_selections"] = selections
    if unresolved_ids:
        normalized["unresolved_ingredient_requirement_ids"] = unresolved_ids
    normalized["ingredient_selection_needed"] = bool(
        meal.get("ingredient_selection_needed") or unresolved_ids
    )
    if "ingredients" in meal:
        normalized["ingredients"] = normalize_meal_ingredients(meal.get("ingredients"))
    if meal.get("ingredient_base_servings") is not None:
        try:
            normalized["ingredient_base_servings"] = normalize_positive_servings(meal["ingredient_base_servings"], "Ingredient recipe yield")
        except ValueError:
            pass
    if clean_text(meal.get("batch_id")):
        normalized["batch_id"] = clean_text(meal.get("batch_id"))
    if meal.get("portion_mode") in ("household", "family"):
        normalized["portion_mode"] = meal["portion_mode"]
    if "member_portions" in meal:
        normalized["member_portions"] = normalize_member_portions(meal["member_portions"])
    return normalized


def normalize_prep_step(value):
    if not isinstance(value, dict):
        return None
    step_date = parse_date(value.get("date"))
    instruction = clean_text(value.get("instruction"))
    if not step_date or not instruction:
        return None
    return {
        "id": clean_text(value.get("id")) or uuid.uuid4().hex,
        "date": step_date.isoformat(),
        "instruction": instruction,
        "completed": value.get("completed") is True,
    }


def normalize_meal_prep_batch(value):
    if not isinstance(value, dict):
        return None
    recipe_url = clean_text(value.get("recipe_url"))
    recipe_name = clean_text(value.get("recipe_name"))
    try:
        servings = normalize_positive_servings(value.get("batch_servings"))
    except ValueError:
        return None
    if not recipe_url or not recipe_name:
        return None
    return {
        "id": clean_text(value.get("id")) or uuid.uuid4().hex,
        "recipe_url": recipe_url,
        "recipe_name": recipe_name,
        "batch_servings": servings,
        "portion_mode": "family" if value.get("portion_mode") == "family" else "household",
        "prep_notes": clean_text(value.get("prep_notes")),
        "prep_steps": [
            step
            for item in (value.get("prep_steps") if isinstance(value.get("prep_steps"), list) else [])
            for step in [normalize_prep_step(item)]
            if step
        ],
        "created_at": clean_text(value.get("created_at"))
        or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }


def meal_prep_batch_summary(batch, meals):
    allocations = sorted(
        [meal for meal in meals if meal.get("batch_id") == batch["id"]],
        key=lambda meal: (meal["date"], MEAL_TYPES.index(meal["meal_type"]), meal["id"]),
    )
    allocated = allocated_batch_servings(allocations)
    remaining = max(Decimal(0), Decimal(str(batch["batch_servings"])) - allocated)
    member_totals = {}
    for meal in allocations:
        for portion in meal.get("member_portions") or []:
            total = member_totals.setdefault(portion["member_id"], {**portion, "servings": Decimal(0)})
            total["servings"] += Decimal(str(portion["servings"]))
    return {
        **batch,
        "allocations": allocations,
        "allocated_servings": servings_number(allocated),
        "remaining_servings": servings_number(remaining),
        "member_totals": [{**member, "servings": servings_number(member["servings"])} for member in member_totals.values()],
    }


def allocated_batch_servings(meals):
    # Decimal arithmetic keeps fractional portions such as 1.1 + 1.1 + 1.1
    # equal to a 3.3-serving batch instead of slightly exceeding it.
    return sum((Decimal(str(meal.get("planned_servings") or 0)) for meal in meals), Decimal(0))


def load_meal_plan():
    with MEAL_PLAN_LOCK:
        def legacy_loader():
            if not MEAL_PLAN_FILE.exists():
                return {"meals": []}
            try:
                return json.loads(MEAL_PLAN_FILE.read_text(encoding="utf-8-sig"))
            except Exception:
                return {"meals": []}

        payload = durable_runtime.load_json_document(
            legacy_loader,
            domain="meal_plans",
            document_key="current",
            source_key="meal_plan",
            source_ref="meal_plan.json",
        )

        meals = []
        for value in payload.get("meals", []) if isinstance(payload, dict) else []:
            normalized = normalize_meal(value) if isinstance(value, dict) else None
            if normalized:
                meals.append(normalized)
        batches = [
            batch
            for value in (payload.get("batches", []) if isinstance(payload, dict) else [])
            for batch in [normalize_meal_prep_batch(value)]
            if batch
        ]
        members = [
            member for value in (payload.get("members", []) if isinstance(payload, dict) else [])
            for member in [normalize_member(value)] if member
        ]
        groups = [
            group for value in (payload.get("groups", []) if isinstance(payload, dict) else [])
            for group in [normalize_group(value)] if group
        ]
        members_by_id = {member["id"]: member for member in members}
        for meal in meals:
            for portion in meal.get("member_portions") or []:
                portion["name"] = members_by_id.get(portion["member_id"], {}).get("name") or portion["name_snapshot"]
        return {"meals": meals, "batches": batches, "members": members, "groups": groups}


def save_meal_plan(payload):
    normalized = {
        "meals": [
            normalized_meal
            for meal in payload.get("meals", [])
            if isinstance(meal, dict)
            for normalized_meal in [normalize_meal(meal)]
            if normalized_meal
        ],
        "batches": [
            batch
            for value in payload.get("batches", [])
            for batch in [normalize_meal_prep_batch(value)]
            if batch
        ],
        "members": [member for value in payload.get("members", []) for member in [normalize_member(value)] if member],
        "groups": [group for value in payload.get("groups", []) for group in [normalize_group(value)] if group],
    }
    with MEAL_PLAN_LOCK:
        return durable_runtime.save_json_document(
            normalized,
            lambda value: durable_runtime.atomic_write_json(MEAL_PLAN_FILE, value),
            domain="meal_plans",
            document_key="current",
            source_key="meal_plan",
            source_ref="meal_plan.json",
        )


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
        payload["meals"] = remaining
        save_meal_plan(payload)
    return True


def meal_plan_entry_detail(meal_id, payload=None):
    payload = load_meal_plan() if payload is None else payload
    meal = next((item for item in payload["meals"] if item["id"] == clean_text(meal_id)), None)
    if not meal:
        return None
    batch = next((item for item in payload["batches"] if item["id"] == meal.get("batch_id")), None)
    return {"meal": meal, **({"batch": meal_prep_batch_summary(batch, payload["meals"])} if batch else {})}


def meal_prep_batch_detail(batch_id, payload=None):
    payload = load_meal_plan() if payload is None else payload
    batch = next((item for item in payload["batches"] if item["id"] == clean_text(batch_id)), None)
    if not batch:
        return None
    summary = meal_prep_batch_summary(batch, payload["meals"])
    return {"batch": summary, "meals": summary["allocations"]}


def validate_meal_edit_fields(value, allowed, label):
    if not isinstance(value, dict) or not value or set(value) - allowed:
        raise ValueError(f"Provide supported {label} details to update.")
    if "prep_notes" in value and not isinstance(value["prep_notes"], str):
        raise ValueError("Meal-prep notes must be text.")


def edited_member_portions(value, members, previous):
    """Keep historical assignments, without allowing archived people on new meals."""
    prior = {item["member_id"]: item for item in previous or []}
    permitted = {key: dict(member) for key, member in members.items()}
    for member_id, portion in prior.items():
        permitted[member_id] = {**permitted.get(member_id, {"name": portion["name_snapshot"]}), "archived": False}
    if isinstance(value, list) and any(
        not isinstance(item, dict) or not isinstance(item.get("member_id"), str)
        or set(item) - {"member_id", "servings", "name", "name_snapshot"} for item in value
    ):
        raise ValueError("Provide a saved member ID and portions for each family member.")
    portions = normalize_member_portions(value, permitted)
    for portion in portions:
        if portion["member_id"] in prior:
            portion["name_snapshot"] = prior[portion["member_id"]]["name_snapshot"]
    return portions


def edited_meal(existing, patch, members, portion_mode=None):
    if "member_portions" in patch and not isinstance(patch["member_portions"], list):
        raise ValueError("Family member portions must be a list.")
    if "date" in patch and not isinstance(patch["date"], str):
        raise ValueError("Choose a valid meal date.")
    mode = portion_mode or patch.get("portion_mode") or (
        "family" if patch.get("member_portions") else existing.get("portion_mode", "household")
    )
    if mode not in ("household", "family"):
        raise ValueError("Choose household totals or family member portions.")
    if "portion_mode" in patch and patch["portion_mode"] not in ("household", "family"):
        raise ValueError("Choose household totals or family member portions.")
    if mode == "family":
        portions = edited_member_portions(patch.get("member_portions", existing.get("member_portions")), members, existing.get("member_portions"))
        total = sum((Decimal(str(item["servings"])) for item in portions), Decimal(0))
        servings = normalize_positive_servings(servings_number(total), "Meal servings")
        if "planned_servings" in patch and Decimal(str(normalize_positive_servings(patch["planned_servings"], "Meal servings"))) != total:
            raise ValueError("Meal servings must match the assigned family member portions.")
    else:
        if patch.get("member_portions"):
            raise ValueError("Choose family member portions to assign servings to members.")
        portions = []
        servings = (normalize_positive_servings(patch.get("planned_servings", existing.get("planned_servings")), "Meal servings")
                    if "planned_servings" in patch or "planned_servings" in existing else None)
    candidate = normalize_meal({**existing, **{key: patch[key] for key in ("date", "meal_type", "prep_notes") if key in patch},
                               "portion_mode": mode, "member_portions": portions, "planned_servings": servings})
    if not candidate:
        raise ValueError("Choose a valid date, meal type, and servings for every meal.")
    for portion in candidate.get("member_portions") or []:
        portion["name"] = members.get(portion["member_id"], {}).get("name") or portion["name_snapshot"]
    return candidate


def validate_edited_slots(meals, remaining):
    slots = set()
    for meal in meals:
        slot = (meal["date"], meal["meal_type"], normalize_recipe_url_key(meal["recipe_url"]))
        if slot in slots:
            raise ValueError("Each meal date and meal type can appear only once in a batch.")
        slots.add(slot)
    if any((meal["date"], meal["meal_type"], normalize_recipe_url_key(meal["recipe_url"])) in slots for meal in remaining):
        raise ValueError("That recipe is already planned for one of these meals.")


def update_meal(meal_id, patch):
    validate_meal_edit_fields(patch, {"date", "meal_type", "planned_servings", "member_portions", "portion_mode", "prep_notes"}, "meal")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        existing = next((item for item in payload["meals"] if item["id"] == clean_text(meal_id)), None)
        if not existing:
            return None
        members = {member["id"]: member for member in payload["members"]}
        meal = edited_meal(existing, patch, members)
        validate_edited_slots([meal], [item for item in payload["meals"] if item["id"] != existing["id"]])
        batch = next((item for item in payload["batches"] if item["id"] == existing.get("batch_id")), None)
        if batch:
            # Preserve spare portions while adjusting the amount to prepare.
            total = Decimal(str(batch["batch_servings"])) + Decimal(str(meal.get("planned_servings") or 0)) - Decimal(str(existing.get("planned_servings") or 0))
            batch["batch_servings"] = normalize_positive_servings(servings_number(total), "Batch servings")
        payload["meals"] = [meal if item["id"] == existing["id"] else item for item in payload["meals"]]
        save_meal_plan(payload)
        return meal_plan_entry_detail(meal["id"], payload)


def edited_prep_steps(value, previous):
    if not isinstance(value, list):
        raise ValueError("Preparation steps must be a list of dated instructions.")
    by_id = {step["id"]: step for step in previous}
    explicit_ids = [step["id"] for step in value if isinstance(step, dict) and "id" in step]
    if any(not isinstance(step_id, str) or step_id not in by_id for step_id in explicit_ids) or len(set(explicit_ids)) != len(explicit_ids):
        raise ValueError("Choose existing preparation task IDs from this plan, once each.")
    used = set()
    steps = []
    for row in value:
        if not isinstance(row, dict) or set(row) - {"id", "date", "instruction", "completed"}:
            raise ValueError("Provide a date and instruction for every preparation step.")
        prior = by_id.get(row.get("id"))
        if not prior:
            prior = next((step for step in previous if step["id"] not in used and step["id"] not in explicit_ids
                          and step["date"] == row.get("date") and step["instruction"] == clean_text(row.get("instruction"))), None)
        if "completed" in row and not isinstance(row["completed"], bool):
            raise ValueError("Completed must be true or false.")
        if "instruction" in row and not isinstance(row["instruction"], str):
            raise ValueError("Preparation instructions must be text.")
        step = normalize_prep_step({**(prior or {}), **row, "id": prior["id"] if prior else uuid.uuid4().hex})
        if not step:
            raise ValueError("Each preparation step needs a valid date and instruction.")
        used.add(step["id"])
        steps.append(step)
    return steps


def update_meal_prep_batch(batch_id, patch):
    allowed = {"recipe_url", "recipe_name", "batch_servings", "portion_mode", "prep_notes", "prep_steps", "allocations", "ingredient_option_selections"}
    validate_meal_edit_fields(patch, allowed, "meal-prep batch")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        existing = next((item for item in payload["batches"] if item["id"] == clean_text(batch_id)), None)
        if not existing:
            return None
        if "recipe_url" in patch and patch["recipe_url"] != existing["recipe_url"]:
            raise ValueError("The recipe cannot be changed when editing a meal-prep plan.")
        if "recipe_name" in patch and patch["recipe_name"] != existing["recipe_name"]:
            raise ValueError("The recipe cannot be changed when editing a meal-prep plan.")
        old_meals = [meal for meal in payload["meals"] if meal.get("batch_id") == existing["id"]]
        by_id = {meal["id"]: meal for meal in old_meals}
        ingredient_base = old_meals[0] if old_meals else {}
        if "ingredient_option_selections" in patch and not isinstance(patch["ingredient_option_selections"], dict):
            raise ValueError("Ingredient selections must be saved ingredient choices.")
        if "ingredient_option_selections" in patch and normalize_selection_map(patch["ingredient_option_selections"]) != normalize_selection_map(ingredient_base.get("ingredient_option_selections")):
            raise ValueError("Edit ingredient choices separately from the meal schedule.")
        mode = patch.get("portion_mode", existing["portion_mode"])
        if mode not in ("household", "family"):
            raise ValueError("Choose household totals or family member portions.")
        allocations = patch.get("allocations") if "allocations" in patch else old_meals
        if not isinstance(allocations, list) or not 1 <= len(allocations) <= 1000:
            raise ValueError("Add between 1 and 1000 meals for this batch.")
        explicit_ids = [row["id"] for row in allocations if isinstance(row, dict) and "id" in row]
        if any(not isinstance(meal_id, str) or meal_id not in by_id for meal_id in explicit_ids) or len(set(explicit_ids)) != len(explicit_ids):
            raise ValueError("Choose existing meal IDs from this plan, once each.")
        members = {member["id"]: member for member in payload["members"]}
        meals, used = [], set()
        for allocation in allocations:
            allocation_fields = {"id", "date", "meal_type", "planned_servings", "member_portions", "portion_mode", "prep_notes"}
            if "allocations" in patch:
                validate_meal_edit_fields(allocation, allocation_fields, "meal allocation")
            prior = by_id.get(allocation.get("id"))
            if not prior:
                prior = next((meal for meal in old_meals if meal["id"] not in used and meal["id"] not in explicit_ids
                              and meal["date"] == allocation.get("date") and meal["meal_type"] == allocation.get("meal_type")), None)
            base = prior or {**{key: ingredient_base[key] for key in ("ingredients", "ingredient_base_servings", "ingredient_option_selections", "unresolved_ingredient_requirement_ids", "ingredient_selection_needed") if key in ingredient_base},
                             "id": uuid.uuid4().hex, "recipe_url": existing["recipe_url"], "recipe_name": existing["recipe_name"], "batch_id": existing["id"]}
            meal = edited_meal(base, allocation, members, allocation.get("portion_mode", mode))
            if "planned_servings" not in meal:
                raise ValueError("Provide servings for every meal in the batch.")
            used.add(meal["id"])
            meals.append(meal)
        remaining = [meal for meal in payload["meals"] if meal.get("batch_id") != existing["id"]]
        validate_edited_slots(meals, remaining)
        batch = {**existing, "portion_mode": mode}
        if "prep_notes" in patch:
            batch["prep_notes"] = patch["prep_notes"].strip()
        if "prep_steps" in patch:
            batch["prep_steps"] = edited_prep_steps(patch["prep_steps"], existing["prep_steps"])
        allocated = allocated_batch_servings(meals)
        batch["batch_servings"] = normalize_positive_servings(patch.get("batch_servings", servings_number(allocated) if "allocations" in patch else existing["batch_servings"]), "Batch servings")
        if allocated > Decimal(str(batch["batch_servings"])):
            raise ValueError("Planned meal servings cannot exceed total batch servings.")
        payload["meals"] = remaining + meals
        payload["batches"] = [batch if item["id"] == existing["id"] else item for item in payload["batches"]]
        save_meal_plan(payload)
        return meal_prep_batch_detail(batch["id"], payload)


def add_meal_prep_batch(batch, allocations, ingredient_data=None):
    """Validate and persist one batch and all meal allocations in one write."""
    if not isinstance(batch, dict):
        raise ValueError("Choose a recipe and total batch servings.")
    batch = dict(batch)
    portion_mode = batch.get("portion_mode", "household")
    if portion_mode not in ("household", "family"):
        raise ValueError("Choose household totals or family member portions.")
    explicit_batch_servings = "batch_servings" in batch
    if explicit_batch_servings:
        batch["batch_servings"] = normalize_positive_servings(batch.get("batch_servings"), "Batch servings")
    steps = batch.get("prep_steps", [])
    if not isinstance(steps, list):
        raise ValueError("Preparation steps must be a list of dated instructions.")
    for step in steps:
        if not normalize_prep_step(step):
            raise ValueError("Each preparation step needs a valid date and instruction.")
    batch["id"] = uuid.uuid4().hex
    batch["prep_steps"] = [
        {**step, "id": uuid.uuid4().hex, "completed": False} for step in steps
    ]
    if not isinstance(allocations, list) or not allocations:
        raise ValueError("Add at least one meal date for this batch.")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        members = {member["id"]: member for member in payload["members"]}
        meals = []
        slots = set()
        for allocation in allocations:
            if not isinstance(allocation, dict):
                raise ValueError("Choose a valid date, meal type, and servings for every meal.")
            portions = []
            if portion_mode == "family":
                portions = normalize_member_portions(allocation.get("member_portions"), members)
                portion_total = sum((Decimal(str(portion["servings"])) for portion in portions), Decimal(0))
                servings = normalize_positive_servings(servings_number(portion_total), "Meal servings")
                if "planned_servings" in allocation:
                    supplied = normalize_positive_servings(allocation["planned_servings"], "Meal servings")
                    if Decimal(str(supplied)) != portion_total:
                        raise ValueError("Meal servings must match the assigned family member portions.")
            else:
                if allocation.get("member_portions"):
                    raise ValueError("Choose family member portions to assign servings to members.")
                servings = normalize_positive_servings(allocation.get("planned_servings"), "Meal servings")
            meal = normalize_meal({
                **(ingredient_data or {}),
                "id": uuid.uuid4().hex,
                "date": allocation.get("date"),
                "meal_type": allocation.get("meal_type"),
                "planned_servings": servings,
                "prep_notes": allocation.get("prep_notes"),
                "recipe_url": batch.get("recipe_url"),
                "recipe_name": batch.get("recipe_name"),
                "batch_id": batch["id"],
                "portion_mode": portion_mode,
                "member_portions": portions,
            })
            if not meal:
                raise ValueError("Choose a valid date, meal type, and servings for every meal.")
            slot = (meal["date"], meal["meal_type"])
            if slot in slots:
                raise ValueError("Each meal date and meal type can appear only once in a batch.")
            slots.add(slot)
            meals.append(meal)
        allocated = allocated_batch_servings(meals)
        if not explicit_batch_servings:
            batch["batch_servings"] = normalize_positive_servings(servings_number(allocated), "Batch servings")
        normalized = normalize_meal_prep_batch(batch)
        if not normalized:
            raise ValueError("Choose a valid recipe for the batch.")
        if allocated > Decimal(str(normalized["batch_servings"])):
            raise ValueError("Planned meal servings cannot exceed total batch servings.")
        recipe_key = normalize_recipe_url_key(normalized["recipe_url"])
        if any(
            (meal["date"], meal["meal_type"]) in slots
            and normalize_recipe_url_key(meal["recipe_url"]) == recipe_key
            for meal in payload["meals"]
        ):
            raise ValueError("That recipe is already planned for one of these meals.")
        payload["batches"].append(normalized)
        payload["meals"].extend(meals)
        save_meal_plan(payload)
    return meal_prep_batch_summary(normalized, meals), meals


def delete_meal_prep_batch(batch_id):
    batch_id = clean_text(batch_id)
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        remaining = [batch for batch in payload["batches"] if batch["id"] != batch_id]
        if len(remaining) == len(payload["batches"]):
            return False
        payload["batches"] = remaining
        payload["meals"] = [meal for meal in payload["meals"] if meal.get("batch_id") != batch_id]
        save_meal_plan(payload)
    return True


def update_meal_prep_step(batch_id, step_id, completed):
    if not isinstance(completed, bool):
        raise ValueError("Completed must be true or false.")
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        batch = next((item for item in payload["batches"] if item["id"] == clean_text(batch_id)), None)
        step = next((item for item in batch["prep_steps"] if item["id"] == clean_text(step_id)), None) if batch else None
        if not step:
            return None
        step["completed"] = completed
        save_meal_plan(payload)
        return step


def update_meal_ingredient_option_selections(
    meal_id,
    selections,
    unresolved_requirement_ids=None,
    ingredients=None,
    ingredient_base_servings=None,
):
    meal_id = clean_text(meal_id)
    selections = normalize_selection_map(selections)
    unresolved_requirement_ids = [
        clean_text(value)
        for value in (
            unresolved_requirement_ids
            if isinstance(unresolved_requirement_ids, list)
            else []
        )
        if clean_text(value)
    ]
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        target = next(
            (meal for meal in payload["meals"] if meal["id"] == meal_id),
            None,
        )
        if not target:
            return None
        target["ingredient_option_selections"] = selections
        target["unresolved_ingredient_requirement_ids"] = unresolved_requirement_ids
        target["ingredient_selection_needed"] = bool(unresolved_requirement_ids)
        if ingredients is not None:
            target["ingredients"] = normalize_meal_ingredients(ingredients)
            if ingredient_base_servings is not None:
                target["ingredient_base_servings"] = normalize_positive_servings(ingredient_base_servings, "Ingredient recipe yield")
            else:
                target.pop("ingredient_base_servings", None)
        save_meal_plan(payload)
        return normalize_meal(target)


def sync_meal_recipe_ingredients(recipe_url, recipe_data):
    recipe_key = normalize_recipe_url_key(recipe_url)
    if not recipe_key:
        return 0
    recipe_data = recipe_data_with_sql_requirements(recipe_url, recipe_data)

    updated_count = 0
    with MEAL_PLAN_LOCK:
        payload = load_meal_plan()
        for meal in payload["meals"]:
            if normalize_recipe_url_key(meal.get("recipe_url")) != recipe_key:
                continue
            resolution = resolve_ingredient_requirements(
                recipe_data,
                meal.get("ingredient_option_selections"),
            )
            meal["ingredient_option_selections"] = resolution["selected_options"]
            meal["unresolved_ingredient_requirement_ids"] = [
                requirement["id"]
                for requirement in resolution["unresolved_requirements"]
            ]
            meal["ingredient_selection_needed"] = resolution["selection_needed"]
            meal.pop("ingredient_base_servings", None)
            meal.update(meal_ingredient_snapshot(recipe_data, resolution["items"]))
            updated_count += 1

        if updated_count:
            save_meal_plan(payload)
    return updated_count


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
        days_from_reference = (planned_date - reference_day).days
        slots.append({
            "date": planned_date.isoformat(),
            "day_label": (
                "TODAY"
                if days_from_reference == 0
                else "TOMORROW"
                if days_from_reference == 1
                else planned_date.strftime("%a").upper()
            ),
            "date_label": (
                weekday_short_date_label(planned_date)
                if days_from_reference in {0, 1}
                else short_date_label(planned_date)
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
    payload = load_meal_plan()
    meals = [meal for meal in payload["meals"] if meal["date"] in day_keys]
    prep_steps_by_day = {day.isoformat(): [] for day in days}
    for batch in payload["batches"]:
        for step in batch["prep_steps"]:
            if step["date"] in day_keys:
                prep_steps_by_day[step["date"]].append({
                    **step,
                    "batch_id": batch["id"],
                    "recipe_url": batch["recipe_url"],
                    "recipe_name": batch["recipe_name"],
                })
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
        "prep_steps_by_day": prep_steps_by_day,
        "meal_count": len(meals),
        "unique_recipe_count": len({meal["recipe_url"] for meal in meals}),
    }
