"""Scoped shopping dates linked to live lists and their saved meal provenance."""

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import meal_plan_service as plans
from PushShoppingList.services import meal_plan_shopping_service as shopping_plans
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services.storage_service import scoped_package_path
from PushShoppingList.services.store_settings_service import load_store_settings


SHOPPING_TRIPS_FILE = scoped_package_path("shopping_trips.json")
SHOPPING_TRIPS_LOCK = threading.RLock()
STATUSES = (
    {"value": "planned", "label": "Planned"},
    {"value": "in_progress", "label": "In progress"},
    {"value": "completed", "label": "Completed"},
)
SOURCE_FIELDS = ("id", "kind", "record_id", "recipe_name", "recipe_url", "servings", "meal_ids", "date_from", "date_to")


class ShoppingTripError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def load_shopping_trips():
    def legacy_loader():
        if not SHOPPING_TRIPS_FILE.exists():
            return {"trips": []}
        try:
            return json.loads(SHOPPING_TRIPS_FILE.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ShoppingTripError("Saved shopping trips could not be read.", 500) from exc

    with SHOPPING_TRIPS_LOCK:
        payload = durable_runtime.load_json_document(
            legacy_loader, domain="shopping", document_key="trips",
            source_key="shopping_trips", source_ref="shopping_trips.json",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("trips"), list) or any(
            not isinstance(row, dict) or not row.get("id") for row in payload["trips"]
        ):
            raise ShoppingTripError("Saved shopping trips could not be read.", 500)
        return payload


def _save(payload):
    return durable_runtime.save_json_document(
        payload, lambda value: durable_runtime.atomic_write_json(SHOPPING_TRIPS_FILE, value),
        domain="shopping", document_key="trips", source_key="shopping_trips",
        source_ref="shopping_trips.json",
    )


def _date(value):
    parsed = plans.parse_date(value) if isinstance(value, str) else None
    if not parsed or parsed.isoformat() != value:
        raise ShoppingTripError("Choose a valid shopping date (YYYY-MM-DD).")
    return parsed.isoformat()


def _text_id(value, label, *, blank=False):
    if not isinstance(value, str) or len(value) > 100 or (not blank and not value.strip()):
        raise ShoppingTripError(f"Choose a valid {label}.")
    return value.strip()


def _sources(record):
    return [
        {key: deepcopy(source[key]) for key in SOURCE_FIELDS if key in source}
        for source in record.get("contributions", [])
    ]


def _list_options():
    # The current list may contain only manually entered items and no ledger.
    records = {record["id"]: record for record in shopping_plans.load_shopping_plans()["lists"]}
    return [
        {**row, "is_current": row["id"] == "current", "sources": _sources(records.get(row["id"], {}))}
        for row in shopping_plans.list_shopping_plans()
    ]


def _store_options():
    settings = load_store_settings()
    return [
        {"key": key, "label": settings["stores"][key].get("label") or key}
        for key in settings.get("enabled_stores", [])
        if isinstance(settings.get("stores", {}).get(key), dict)
    ]


def shopping_trip_options():
    # Match the existing add/remove-list writer lock order.
    with shopping.SHOPPING_LIST_LOCK, shopping_plans.SHOPPING_PLAN_LOCK:
        return {"lists": _list_options(), "stores": _store_options(), "statuses": list(STATUSES)}


def _find(payload, trip_id):
    record = next((row for row in payload["trips"] if row["id"] == trip_id), None)
    if record is None:
        raise ShoppingTripError("That shopping trip was not found.", 404)
    return record


def _view(record, list_options=None, store_options=None):
    if list_options is None or store_options is None:
        options = shopping_trip_options()
        list_options = options["lists"] if list_options is None else list_options
        store_options = options["stores"] if store_options is None else store_options
    linked_list = next((row for row in list_options if row["id"] == record["list_id"]), None)
    store = next((row for row in store_options if row["key"] == record.get("store_key")), None)
    return {
        **deepcopy(record),
        "list_name": linked_list["name"] if linked_list else record["list_name"],
        "is_current": record["list_id"] == "current",
        "list_available": linked_list is not None,
        "store_label": store["label"] if store else record.get("store_label", ""),
    }


def shopping_trip_detail(trip_id):
    return _view(_find(load_shopping_trips(), trip_id))


def _updated_record(payload, existing=None):
    allowed = {"date", "list_id", "store_key", "status", "source_ids"}
    if not isinstance(payload, dict) or not payload or set(payload) - allowed:
        raise ShoppingTripError("Provide a shopping date, list, store, status, or covered meals.")
    if existing is None and not {"date", "list_id"}.issubset(payload):
        raise ShoppingTripError("Choose a shopping date and shopping list.")
    result = deepcopy(existing) if existing else {}
    if "date" in payload:
        result["date"] = _date(payload["date"])
    if "status" in payload:
        if not isinstance(payload["status"], str) or payload["status"] not in {item["value"] for item in STATUSES}:
            raise ShoppingTripError("Choose Planned, In progress, or Completed.")
        result["status"] = payload["status"]
    result.setdefault("status", "planned")

    options = shopping_trip_options()
    if "store_key" in payload or existing is None:
        key = _text_id(payload.get("store_key", ""), "store", blank=True)
        store = next((row for row in options["stores"] if row["key"] == key), None)
        if key and store is None and (not existing or key != existing.get("store_key")):
            raise ShoppingTripError("Choose an enabled store.")
        result["store_key"] = key
        result["store_label"] = store["label"] if store else (existing.get("store_label", "") if key and existing else "")

    list_id = _text_id(payload.get("list_id", result.get("list_id")), "shopping list")
    linked_list = next((row for row in options["lists"] if row["id"] == list_id), None)
    same_list = existing is not None and list_id == existing["list_id"]
    # Keep a historical trip editable if its list is no longer available, but
    # never let a new trip claim a list belonging to another workspace.
    if linked_list is None and not same_list:
        raise ShoppingTripError("That shopping list was not found in this workspace.", 404)
    result["list_id"] = list_id
    result["list_name"] = linked_list["name"] if linked_list else existing["list_name"]
    if not same_list or "source_ids" in payload:
        current_sources = linked_list["sources"] if linked_list else []
        available = {source["id"]: source for source in current_sources}
        # Existing verified coverage can be retained after a current list is
        # cleared or edited; fresh IDs must come from the chosen list's ledger.
        if same_list:
            available = {**available, **{source["id"]: source for source in existing.get("sources", [])}}
        ids = payload.get("source_ids", [source["id"] for source in current_sources])
        if not isinstance(ids, list) or len(ids) > 500:
            raise ShoppingTripError("Choose valid covered meals or prep batches.")
        ids = list(dict.fromkeys(_text_id(value, "meal or prep batch") for value in ids))
        if set(ids) - set(available):
            raise ShoppingTripError("Covered meals and prep batches must belong to the selected shopping list.")
        result["source_ids"] = ids
        result["sources"] = [deepcopy(available[value]) for value in ids]
    timestamp = datetime.now(timezone.utc).isoformat()
    result.setdefault("id", uuid.uuid4().hex)
    result.setdefault("created_at", timestamp)
    result["updated_at"] = timestamp
    return result


def add_shopping_trip(payload):
    with shopping.SHOPPING_LIST_LOCK, shopping_plans.SHOPPING_PLAN_LOCK, SHOPPING_TRIPS_LOCK:
        stored = deepcopy(load_shopping_trips())
        record = _updated_record(payload)
        stored["trips"].append(record)
        result = _view(record)
        _save(stored)
        return result


def update_shopping_trip(trip_id, payload):
    with shopping.SHOPPING_LIST_LOCK, shopping_plans.SHOPPING_PLAN_LOCK, SHOPPING_TRIPS_LOCK:
        stored = deepcopy(load_shopping_trips())
        existing = _find(stored, trip_id)
        updated = _updated_record(payload, existing)
        stored["trips"][stored["trips"].index(existing)] = updated
        result = _view(updated)
        _save(stored)
        return result


def delete_shopping_trip(trip_id):
    with SHOPPING_TRIPS_LOCK:
        stored = deepcopy(load_shopping_trips())
        record = _find(stored, trip_id)
        stored["trips"].remove(record)
        _save(stored)
    return trip_id


def planning_week(value=None, reference_date=None):
    if value is not None:
        _date(value)
    try:
        with plans.MEAL_PLAN_LOCK:
            calendar = plans.meal_plan_for_week(value, reference_date=reference_date)
            plan = plans.load_meal_plan()
    except OverflowError as exc:
        raise ShoppingTripError("Choose a week within the supported calendar range.") from exc
    # Existing template helpers use tuple keys, which cannot be JSON keys.
    calendar.pop("meals_by_slot", None)
    days = {day["date"] for day in calendar["days"]}
    calendar["week_end"] = calendar["days"][-1]["date"]
    batch_meals = {}
    for meal in plan["meals"]:
        if meal.get("batch_id"):
            batch_meals.setdefault(meal["batch_id"], []).append(meal)
    for steps in calendar["prep_steps_by_day"].values():
        for step in steps:
            allocations = batch_meals.get(step["batch_id"], [])
            step["meal_id"] = allocations[0]["id"] if allocations else ""
    unscheduled = []
    for batch in plan["batches"]:
        allocations = batch_meals.get(batch["id"], [])
        in_week = [meal for meal in allocations if meal["date"] in days]
        if not batch["prep_steps"] and in_week:
            unscheduled.append({
                **plans.meal_prep_batch_summary(batch, allocations),
                "batch_id": batch["id"], "meal_id": in_week[0]["id"],
            })
    unscheduled.sort(key=lambda row: (row["allocations"][0]["date"], row["recipe_name"], row["id"]))
    options = shopping_trip_options()
    trips = sorted(
        (_view(row, options["lists"], options["stores"]) for row in load_shopping_trips()["trips"] if row["date"] in days),
        key=lambda row: (row["date"], row["created_at"], row["id"]),
    )
    return {
        **calendar, "unscheduled_prep_batches": unscheduled, "shopping_trips": trips,
        "shopping_trips_by_day": {day["date"]: [row for row in trips if row["date"] == day["date"]] for day in calendar["days"]},
    }
