"""Reviewed, scoped shopping requirements for saved meals and prep batches.

The contribution ledger keeps meal instances separate from recipe editing and
from other shopping entries. A batch is a single cooking event even when its
portions are scheduled in several weeks.
"""

import hashlib
import json
import math
import threading
import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

from PushShoppingList.services import durable_document_runtime_service as durable_runtime
from PushShoppingList.services import meal_plan_service as plans
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services.ingredient_option_service import ingredient_name, resolve_ingredient_requirements
from PushShoppingList.services.item_state_service import load_item_state
from PushShoppingList.services.pantry_service import load_pantry_inventory, normalize_ingredient_name, pantry_item_lifecycle_status
from PushShoppingList.services.purchase_mapping_service import normalize_item_key, purchase_mapping_for_recipe_ingredient
from PushShoppingList.services.recipe_quantity_service import (
    format_quantity_display, load_saved_recipe_output, recipe_base_servings, scale_quantity,
)
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.storage_service import scoped_package_path


SHOPPING_PLAN_FILE = scoped_package_path("meal_plan_shopping.json")
SHOPPING_PLAN_LOCK = threading.RLock()


class ShoppingPlanError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def load_shopping_plans():
    def legacy_loader():
        if not SHOPPING_PLAN_FILE.exists():
            return {"lists": []}
        # Do not turn unreadable shopping data into an empty list on a write.
        return json.loads(SHOPPING_PLAN_FILE.read_text(encoding="utf-8-sig"))
    payload = durable_runtime.load_json_document(
        legacy_loader, domain="shopping", document_key="meal_plan_lists",
        source_key="meal_plan_shopping", source_ref="meal_plan_shopping.json",
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("lists"), list):
        raise ShoppingPlanError("Saved shopping lists could not be read.", 500)
    return payload


def _save(payload):
    return durable_runtime.save_json_document(
        payload, lambda value: durable_runtime.atomic_write_json(SHOPPING_PLAN_FILE, value),
        domain="shopping", document_key="meal_plan_lists", source_key="meal_plan_shopping",
        source_ref="meal_plan_shopping.json",
    )


def _id_list(value, label):
    if not isinstance(value, list) or len(value) > 500 or any(not isinstance(item, str) or not item.strip() or len(item) > 100 for item in value):
        raise ShoppingPlanError(f"Provide valid {label} IDs.")
    return list(dict.fromkeys(item.strip() for item in value))


def _selection(selection, plan):
    if not isinstance(selection, dict) or not selection or set(selection) - {"week_start", "meal_ids", "batch_ids"}:
        raise ShoppingPlanError("Choose a week, meals, or preparation batches to shop.")
    meals = {meal["id"]: meal for meal in plan["meals"]}
    batches = {batch["id"]: batch for batch in plan["batches"]}
    week = None
    if "week_start" in selection:
        if set(selection) != {"week_start"} or not isinstance(selection["week_start"], str):
            raise ShoppingPlanError("Choose a week or explicit meals and batches.")
        selected_date = plans.parse_date(selection["week_start"])
        if not selected_date:
            raise ShoppingPlanError("Choose a valid week.")
        week = plans.week_start(selected_date.isoformat())
        meal_ids = [meal["id"] for meal in meals.values() if week.isoformat() <= meal["date"] <= (week + timedelta(days=6)).isoformat()]
        batch_ids = []
        normalized = {"week_start": week.isoformat()}
    else:
        meal_ids = _id_list(selection.get("meal_ids", []), "meal")
        batch_ids = _id_list(selection.get("batch_ids", []), "batch")
        if any(item not in meals for item in meal_ids) or any(item not in batches for item in batch_ids):
            raise ShoppingPlanError("A selected meal or prep batch is no longer available in this workspace.", 404)
        normalized = {"meal_ids": sorted(meal_ids), "batch_ids": sorted(batch_ids)}
    for meal_id in meal_ids:
        batch_id = meals[meal_id].get("batch_id")
        if batch_id:
            if batch_id not in batches:
                raise ShoppingPlanError("A selected meal has a missing prep batch. Review the meal plan first.")
            batch_ids.append(batch_id)
    selected = []
    for batch_id in sorted(set(batch_ids)):
        allocated = [meal for meal in meals.values() if meal.get("batch_id") == batch_id]
        if not allocated:
            raise ShoppingPlanError("This prep batch has no scheduled meals to shop.")
        selected.append(("batch", batches[batch_id], allocated))
    selected.extend(("meal", meals[meal_id], [meals[meal_id]]) for meal_id in sorted(set(meal_ids)) if not meals[meal_id].get("batch_id"))
    if not selected:
        raise ShoppingPlanError("There are no planned meals in this selection.")
    return normalized, selected, week


def _quantity_sum(values):
    # Keep incompatible units separate; never invent a volume/weight conversion.
    from PushShoppingList.services.product_selection_service import parse_display_quantity, sum_quantity_values
    values = [str(value).strip() for value in values if str(value or "").strip()]
    values = [part for value in values
              for part in (value.split(" + ") if all(parse_display_quantity(part) is not None for part in value.split(" + ")) else [value])]
    return (sum_quantity_values(values) or " + ".join(values)) if values else ""


def _aggregate(contributions):
    items = {}
    for contribution in contributions:
        for row in contribution.get("items", []):
            item = items.setdefault(row["id"], {"id": row["id"], "name": row["name"], "sources": []})
            item["sources"].append({
                "id": contribution["id"], "recipe_name": contribution["recipe_name"],
                "recipe_url": contribution["recipe_url"], "servings": contribution["servings"],
                "quantity": row["quantity"], "amount_unspecified": row.get("amount_unspecified", False),
            })
    for item in items.values():
        quantities = [source["quantity"] for source in item["sources"] if source["quantity"]]
        item["amount_unspecified"] = any(source["amount_unspecified"] for source in item["sources"])
        item["quantity"] = _quantity_sum(quantities)
        if item["amount_unspecified"]:
            item["quantity"] = (item["quantity"] + " + unspecified amount") if item["quantity"] else "Amount not specified"
    return sorted(items.values(), key=lambda item: item["name"].casefold())


def _source_requirements(kind, record, meals, state):
    url = record["recipe_url"]
    recipe = load_saved_recipe_output(url)
    if not recipe:
        raise ShoppingPlanError(f"Save or restore {record['recipe_name']} before shopping for it.")
    live_yield = plans.planned_servings_from_yield(recipe_base_servings(recipe))
    groups = {}
    for meal in meals:
        if meal.get("ingredient_selection_needed") or meal.get("unresolved_ingredient_requirement_ids"):
            raise ShoppingPlanError(f"Choose ingredient bundles for {record['recipe_name']} before shopping.")
        ingredients = meal.get("ingredients")
        if ingredients is None:
            resolution = resolve_ingredient_requirements(recipe, meal.get("ingredient_option_selections"), require_all=True)
            ingredients = plans.meal_ingredient_snapshot(recipe, resolution["items"])["ingredients"]
        if not ingredients:
            raise ShoppingPlanError(f"Add ingredients to {record['recipe_name']} before shopping.")
        portions = plans.normalize_positive_servings(meal.get("planned_servings"), "Scheduled servings")
        yield_amount = meal.get("ingredient_base_servings") or live_yield
        if not yield_amount:
            raise ShoppingPlanError(f"Set a valid recipe yield for {record['recipe_name']} before shopping.")
        signature = _digest({"ingredients": ingredients, "yield": yield_amount})
        group = groups.setdefault(signature, {"ingredients": ingredients, "yield": yield_amount, "servings": Decimal(0)})
        group["servings"] += Decimal(str(portions))
    allocated = sum((group["servings"] for group in groups.values()), Decimal(0))
    total = Decimal(str(record["batch_servings"])) if kind == "batch" else allocated
    if total < allocated:
        raise ShoppingPlanError("This prep batch has more scheduled portions than its yield. Review the plan first.")
    if total > allocated and len(groups) > 1:
        raise ShoppingPlanError("This batch has different ingredient bundles and unallocated portions. Allocate the remaining portions before shopping.")
    if len(groups) == 1:
        next(iter(groups.values()))["servings"] = total
    rows = {}
    for group in groups.values():
        multiplier = group["servings"] / Decimal(str(group["yield"]))
        for ingredient in group["ingredients"]:
            mapping = purchase_mapping_for_recipe_ingredient({**ingredient, "ingredient": ingredient_name(ingredient)}, item_state=state)
            name = mapping["purchase_group"]
            if not name:
                continue
            item_id = _digest(mapping["purchase_group_key"])[:24]
            row = rows.setdefault(item_id, {"id": item_id, "name": name, "quantities": [], "amount_unspecified": False})
            # Snapshots are normalized on capture. Older records can carry an
            # explicit base amount, but must never inherit a newer live scale.
            quantity = ingredient.get("base_quantity") if ingredient.get("base_quantity") not in (None, "") else ingredient.get("quantity")
            unit = ingredient.get("base_unit") if ingredient.get("base_unit") not in (None, "") else ingredient.get("unit")
            display = format_quantity_display(scale_quantity(quantity, multiplier), unit)
            if display:
                row["quantities"].append(display)
            else:
                row["amount_unspecified"] = True
    return {
        "id": f"{kind}:{record['id']}", "kind": kind, "record_id": record["id"],
        "recipe_name": record["recipe_name"], "recipe_url": url,
        "servings": plans.servings_number(total), "meal_ids": sorted(meal["id"] for meal in meals),
        "date_from": min(meal["date"] for meal in meals), "date_to": max(meal["date"] for meal in meals),
        "items": [{"id": row["id"], "name": row["name"], "quantity": _quantity_sum(row["quantities"]),
                   "amount_unspecified": row["amount_unspecified"]} for row in rows.values()],
    }


def review_meal_plan_shopping(selection):
    normalized, selected, week = _selection(selection, plans.load_meal_plan())
    state = load_item_state()
    contributions, blockers, blocked_sources = [], [], []
    for kind, record, meals in selected:
        try:
            contributions.append(_source_requirements(kind, record, meals, state))
        except ValueError as exc:
            blockers.append(str(exc))
            blocked_sources.append({
                "id": f"{kind}:{record['id']}", "kind": kind, "record_id": record["id"],
                "recipe_name": record["recipe_name"], "recipe_url": record["recipe_url"],
                "servings": record.get("batch_servings") if kind == "batch" else record.get("planned_servings"),
                "meal_ids": sorted(meal["id"] for meal in meals),
                "date_from": min(meal["date"] for meal in meals), "date_to": max(meal["date"] for meal in meals),
                "error": str(exc),
            })
    pantry_items = load_pantry_inventory().get("items", [])
    items = _aggregate(contributions)
    for item in items:
        name_key = normalize_ingredient_name(item["name"])
        item["pantry_matches"] = [{"id": row["id"], "name": row.get("ingredient_name") or row.get("product_name"),
                                  "quantity": row.get("quantity"), "unit": row.get("unit", ""), "status": row.get("status", "available"),
                                  "expiration_date": row.get("expiration_date", ""),
                                  "condition": pantry_item_lifecycle_status(row)["label"]}
                                 for row in pantry_items if row.get("status") != "used" and _positive_stock(row.get("quantity"))
                                 and normalize_ingredient_name(row.get("normalized_name") or row.get("ingredient_name") or row.get("product_name")) == name_key]
        item["included"] = True
    warnings = []
    if week and any(source["kind"] == "batch" and (source["date_from"] < week.isoformat() or source["date_to"] > (week + timedelta(days=6)).isoformat()) for source in contributions):
        warnings.append("Selected prep batches include their full cooking yield, including portions scheduled in other weeks.")
    if any(item["pantry_matches"] for item in items):
        warnings.append("Pantry matches are suggestions. Check amounts and exclude items you already have; pantry inventory is not changed.")
    if any(item["amount_unspecified"] for item in items):
        warnings.append("Some ingredients have no stated amount. Check these before shopping.")
    sources = [{key: value for key, value in source.items() if key != "items"} for source in contributions] + blocked_sources
    token = _digest({"selection": normalized, "contributions": contributions, "items": items, "blockers": blockers})
    return {"ok": True, "selection": normalized, "review_token": token, "sources": sources, "items": items,
            "warnings": warnings, "blockers": blockers, "can_add": not blockers and bool(items),
            "lists": list_shopping_plans(), "_contributions": contributions}


def _positive_stock(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def _list_detail(record):
    items = _aggregate(record.get("contributions", []))
    checked = record.get("checked", {})
    for item in items:
        item["checked"] = checked.get(item["id"]) is True
        item["pantry_matches"] = []
    return {"id": record["id"], "name": record["name"], "items": items, "item_count": len(items)}


def list_shopping_plans():
    records = load_shopping_plans()["lists"]
    return [{"id": "current", "name": "Current shopping list", "item_count": len(shopping.load_items())}] + [
        {key: value for key, value in _list_detail(record).items() if key != "items"}
        for record in records if record["id"] != "current"
    ]


def shopping_plan_detail(list_id):
    # The current list uses its existing full editor, including non-planner items.
    record = next((row for row in load_shopping_plans()["lists"] if row["id"] == list_id), None)
    if record is None:
        raise ShoppingPlanError("That saved shopping list was not found.", 404)
    return _list_detail(record)


def add_meal_plan_shopping(payload):
    if not isinstance(payload, dict) or set(payload) - {"selection", "review_token", "excluded_item_ids", "list_id", "new_list_name"}:
        raise ShoppingPlanError("Provide a reviewed meal-plan selection and shopping-list destination.")
    excluded = _id_list(payload.get("excluded_item_ids", []), "excluded ingredient")
    if ("list_id" in payload) == ("new_list_name" in payload):
        raise ShoppingPlanError("Choose an existing shopping list or name a new one.")
    name = payload.get("new_list_name")
    if name is not None and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 100):
        raise ShoppingPlanError("Enter a shopping-list name of 100 characters or fewer.")
    list_id = payload.get("list_id")
    if list_id is not None and (not isinstance(list_id, str) or not list_id.strip()):
        raise ShoppingPlanError("Choose a shopping list.")
    with shopping.SHOPPING_LIST_LOCK, SHOPPING_PLAN_LOCK:
        review = review_meal_plan_shopping(payload.get("selection"))
        if review["blockers"]:
            raise ShoppingPlanError("Resolve or deselect meals with ingredient or serving issues before adding them.")
        if payload.get("review_token") != review["review_token"]:
            raise ShoppingPlanError("The plan or pantry changed. Review the ingredients again before adding them.", 409)
        if set(excluded) - {row["id"] for row in review["items"]}:
            raise ShoppingPlanError("An excluded ingredient is not part of this review.")
        included = [row for row in review["items"] if row["id"] not in excluded]
        if not included:
            raise ShoppingPlanError("Select at least one ingredient to add.")
        stored = deepcopy(load_shopping_plans())
        if name is not None:
            if name.strip().casefold() == "current shopping list" or any(row["name"].casefold() == name.strip().casefold() for row in stored["lists"]):
                raise ShoppingPlanError("A shopping list with that name already exists. Choose it from the existing lists.")
            destination = {"id": uuid.uuid4().hex, "name": name.strip(), "contributions": [], "checked": {}}
            stored["lists"].append(destination)
        else:
            destination = next((row for row in stored["lists"] if row["id"] == list_id), None)
            if destination is None and list_id == "current":
                destination = {"id": "current", "name": "Current shopping list", "contributions": [], "checked": {}}
                stored["lists"].append(destination)
            if destination is None:
                raise ShoppingPlanError("That shopping list was not found in this workspace.", 404)
        old_quantities = {item["id"]: item["quantity"] for item in _list_detail(destination)["items"]}
        source_ids = {source["id"] for source in review["_contributions"]}
        destination["contributions"] = [source for source in destination.get("contributions", []) if source["id"] not in source_ids]
        for source in review["_contributions"]:
            source = deepcopy(source)
            source["items"] = [row for row in source["items"] if row["id"] not in excluded]
            if source["items"]:
                destination["contributions"].append(source)
        for item in _list_detail(destination)["items"]:
            if old_quantities.get(item["id"]) != item["quantity"]:
                destination.setdefault("checked", {})[item["id"]] = False
        detail = _list_detail(destination)
        names = [item["name"] for item in included]
        previous_names = shopping.load_items() if destination["id"] == "current" else None
        added = names
        try:
            if previous_names is not None:
                from PushShoppingList.services.product_selection_service import load_item_quantity_context
                from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_item
                state = load_item_state()
                previous_context = load_item_quantity_context(previous_names)
                added = shopping.add_items(names)["added"]
                owned = set(destination.get("owned_item_keys", []))
                owned.update(purchase_mapping_for_item(name, state)["purchase_group_key"] for name in added)
                kept_keys = {normalize_item_key(item["name"]) for item in detail["items"]}
                removable = owned - kept_keys
                removable = {key for key in removable if not any(not source.get("meal_plan_source_id") for source in previous_context.get(key, {}).get("sources", []))}
                final_names = [name for name in shopping.load_items() if purchase_mapping_for_item(name, state)["purchase_group_key"] not in removable]
                shopping.save_items(final_names, preserve_plan_contributions=True)
                destination["owned_item_keys"] = sorted(owned - removable)
            _save(stored)
        except Exception:
            if previous_names is not None:
                shopping.save_items(previous_names, preserve_plan_contributions=True)
            raise
        return {"ok": True, "list": detail, "added": added, "excluded_count": len(excluded)}


def set_shopping_plan_item_checked(list_id, item_id, checked):
    if not isinstance(checked, bool):
        raise ShoppingPlanError("Checked must be true or false.")
    if list_id == "current":
        raise ShoppingPlanError("Use the current shopping list to update its items.")
    with SHOPPING_PLAN_LOCK:
        stored = load_shopping_plans()
        record = next((row for row in stored["lists"] if row["id"] == list_id), None)
        if record is None or item_id not in {item["id"] for item in _list_detail(record)["items"]}:
            raise ShoppingPlanError("That shopping-list item was not found.", 404)
        record.setdefault("checked", {})[item_id] = checked
        _save(stored)
        return _list_detail(record)


def current_shopping_quantity_sources(items):
    from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_item
    state = load_item_state()
    keys = {purchase_mapping_for_item(item, state)["purchase_group_key"] for item in items}
    record = next((row for row in load_shopping_plans()["lists"] if row["id"] == "current"), {})
    result = {}
    for contribution in record.get("contributions", []):
        for row in contribution.get("items", []):
            key = normalize_item_key(row["name"])
            if key not in keys:
                continue
            quantity = row["quantity"]
            if row.get("amount_unspecified"):
                quantity = (quantity + " + unspecified amount") if quantity else "Amount not specified"
            result.setdefault(key, []).append({
                "label": f"Meal plan: {contribution['recipe_name']}", "ingredient": row["name"],
                "recipe_ingredient": row["name"], "item_key": key, "purchasable_item": row["name"],
                "purchase_group": row["name"], "purchase_group_key": key, "quantity": quantity,
                "amount_unspecified": row.get("amount_unspecified", False),
                "url": contribution["recipe_url"], "meal_plan_source_id": contribution["id"],
            })
    return result


def merge_plan_quantity_sources(quantity_sources, planner_sources):
    """Replace only the same recipe's baseline, retaining unrelated/manual demand."""
    result = deepcopy(quantity_sources)
    for key, additions in planner_sources.items():
        urls = {normalize_recipe_url_key(source["url"]) for source in additions}
        for existing_key, sources in result.items():
            result[existing_key] = [source for source in sources if source.get("manual") or not (
                normalize_item_key(source.get("purchase_group_key") or existing_key) == key
                and normalize_recipe_url_key(source.get("url")) in urls
            )]
        result.setdefault(key, []).extend(additions)
    return result


def prune_current_shopping_contributions(items):
    """A removed line must not regain its previous plan amount when re-added."""
    from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_item
    state = load_item_state()
    keys = {purchase_mapping_for_item(item, state)["purchase_group_key"] for item in items}
    with SHOPPING_PLAN_LOCK:
        stored = load_shopping_plans()
        record = next((row for row in stored["lists"] if row["id"] == "current"), None)
        if record is None:
            return
        for source in record.get("contributions", []):
            source["items"] = [row for row in source["items"] if normalize_item_key(row["name"]) in keys]
        record["contributions"] = [source for source in record.get("contributions", []) if source["items"]]
        record["owned_item_keys"] = [key for key in record.get("owned_item_keys", []) if key in keys]
        _save(stored)
