"""Removing a prep batch affects its schedule, not recipes or shopping history."""

from copy import deepcopy
import json

import pytest

from PushShoppingList.services import item_state_service
from PushShoppingList.services import meal_plan_service as plans
from PushShoppingList.services import meal_plan_shopping_service as shopping_plans
from PushShoppingList.services import recipe_quantity_service
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services import shopping_trip_service as trips
from test_meal_plan_shopping import RECIPE, isolated_shopping, add_review
from test_meal_prep_batches import isolated_plan, scoped_client, sign_in, batch_input, allocations
from test_shopping_trip_planner import isolated_trips


def seed_same_recipe_schedules():
    batch, meals = plans.add_meal_prep_batch(batch_input(), allocations(), {
        "ingredients": deepcopy(RECIPE["ingredients"]), "ingredient_base_servings": 4,
    })
    plans.update_meal_prep_step(batch["id"], batch["prep_steps"][0]["id"], True)
    other_batch, other_meals = plans.add_meal_prep_batch({
        "recipe_url": "recipe://soup", "recipe_name": "Soup", "batch_servings": 4,
        "prep_notes": "Keep this different batch",
        "prep_steps": [{"date": "2026-10-07", "instruction": "Prepare another batch"}],
    }, [{"date": "2026-10-08", "meal_type": "dinner", "planned_servings": 4}], {
        "ingredients": deepcopy(RECIPE["ingredients"]), "ingredient_base_servings": 4,
    })
    standalone = plans.add_meal({
        "date": "2026-09-29", "meal_type": "breakfast", "recipe_url": "recipe://soup",
        "recipe_name": "Soup", "planned_servings": 1, "prep_notes": "Keep this standalone meal",
        "ingredients": deepcopy(RECIPE["ingredients"]), "ingredient_base_servings": 4,
    })
    return batch, meals, other_batch, other_meals, standalone


def test_delete_entire_batch_keeps_recipe_other_schedules_lists_checks_and_trips(isolated_trips, monkeypatch):
    output = isolated_trips / "recipe-extractor" / "data" / "output"
    output.mkdir(parents=True)
    recipe_path = output / "soup.json"
    recipe_path.write_text(json.dumps({**RECIPE, "source_url": "recipe://soup", "notes": "Permanent recipe notes"}), encoding="utf-8")
    monkeypatch.setattr(recipe_quantity_service, "OUTPUT_FOLDER", output)
    monkeypatch.setattr(item_state_service, "ITEM_STATE_FILE", isolated_trips / "shopping_item_state.json")
    batch, meals, other_batch, other_meals, standalone = seed_same_recipe_schedules()
    member = plans.add_meal_plan_member("Nate")
    group = plans.add_meal_plan_group("Tyler")
    plans.update_meal_plan_member(member["id"], group_ids=[group["id"]])
    selection = {"batch_ids": [batch["id"], other_batch["id"]], "meal_ids": [standalone["id"]]}
    review = shopping_plans.review_meal_plan_shopping(selection)
    named = add_review(review, new_list_name="Planned groceries")["list"]
    add_review(review, list_id="current")
    named = shopping_plans.set_shopping_plan_item_checked(named["id"], named["items"][0]["id"], True)
    item_state_service.save_item_state({"flour": {"checked": True, "store": "aldi", "manual_qty": "1 bag"}})
    current_trip = trips.add_shopping_trip({"date": "2026-09-27", "list_id": "current", "source_ids": ["batch:" + batch["id"]]})
    named_trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": named["id"], "status": "completed", "source_ids": ["batch:" + batch["id"]]})

    protected_paths = [recipe_path, shopping.SHOPPING_LIST_FILE, shopping_plans.SHOPPING_PLAN_FILE,
                       item_state_service.ITEM_STATE_FILE, trips.SHOPPING_TRIPS_FILE]
    protected_bytes = [(path, path.read_bytes()) for path in protected_paths]
    plan_before = plans.load_meal_plan()
    assert len(plans.meal_prep_batch_detail(batch["id"])["meals"]) == 3
    assert trips.planning_week("2026-10-05")["prep_steps_by_day"]["2026-10-05"]

    assert plans.delete_meal_prep_batch(batch["id"]) is True

    after = plans.load_meal_plan()
    assert after["batches"] == [row for row in plan_before["batches"] if row["id"] == other_batch["id"]]
    assert after["meals"] == [row for row in plan_before["meals"] if row["id"] in {standalone["id"], other_meals[0]["id"]}]
    assert after["members"] == plan_before["members"]
    assert after["groups"] == plan_before["groups"]
    assert plans.meal_prep_batch_detail(batch["id"]) is None
    for date in ("2026-09-21", "2026-09-28", "2026-10-05"):
        week = trips.planning_week(date)
        assert not ({row["id"] for row in week["meals"]} & {meal["id"] for meal in meals})
        assert all(step["batch_id"] != batch["id"] for steps in week["prep_steps_by_day"].values() for step in steps)
    assert trips.planning_week("2026-10-05")["prep_steps_by_day"]["2026-10-07"][0]["batch_id"] == other_batch["id"]
    for path, before in protected_bytes:
        assert path.read_bytes() == before
    assert recipe_quantity_service.load_saved_recipe_output("recipe://soup")["notes"] == "Permanent recipe notes"
    assert shopping_plans.shopping_plan_detail(named["id"]) == named
    assert named["items"][0]["checked"] is True
    assert item_state_service.load_item_state()["flour"]["checked"] is True
    assert trips.shopping_trip_detail(current_trip["id"]) == current_trip
    assert trips.shopping_trip_detail(named_trip["id"]) == named_trip
    assert set(current_trip["sources"][0]["meal_ids"]) == {meal["id"] for meal in meals}
    # A historical trip remains editable even though its prep batch is gone.
    updated = trips.update_shopping_trip(current_trip["id"], {"status": "in_progress", "source_ids": current_trip["source_ids"]})
    assert updated["sources"] == current_trip["sources"]


def test_missing_batch_delete_and_failed_write_do_not_remove_partial_schedule(isolated_plan, monkeypatch):
    batch, _, _, _, _ = seed_same_recipe_schedules()
    before = isolated_plan.read_bytes()
    assert plans.delete_meal_prep_batch("not-present") is False
    assert isolated_plan.read_bytes() == before
    monkeypatch.setattr(plans, "save_meal_plan", lambda value: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        plans.delete_meal_prep_batch(batch["id"])
    assert isolated_plan.read_bytes() == before


def test_batch_delete_api_scopes_complete_cross_week_removal(scoped_client):
    client = scoped_client
    base = "/api/meal-plan/batches"
    assert client.delete(base + "/unknown").status_code == 403
    sign_in(client, "owner")
    result = client.post(base, json={**batch_input(), "allocations": allocations()})
    assert result.status_code == 201
    batch = result.get_json()["batch"]
    meal_ids = [meal["id"] for meal in result.get_json()["meals"]]
    endpoint = base + "/" + batch["id"]
    original = client.get(endpoint).get_json()
    assert len(original["meals"]) == 3
    assert min(row["date"] for row in original["meals"]) == "2026-09-28"
    assert max(row["date"] for row in original["meals"]) == "2026-10-05"
    assert len(original["batch"]["prep_steps"]) == 3
    assert client.delete(endpoint + "?viewer_user_id=other").status_code == 403
    assert client.get(endpoint).get_json() == original
    for identity, guest in (("other", False), ("guest-remove", True)):
        sign_in(client, identity, guest=guest)
        assert client.delete(endpoint).status_code == 404
        own = client.post(base, json={**batch_input(), "allocations": allocations()}).get_json()["batch"]
        assert client.delete(base + "/" + own["id"]).get_json() == {"ok": True}
    sign_in(client, "owner")
    assert client.get(endpoint).get_json() == original
    assert client.delete(endpoint).get_json() == {"ok": True}
    assert client.get(endpoint).status_code == 404
    assert client.delete(endpoint).status_code == 404
    assert all(client.get("/api/meal-plan/" + meal_id).status_code == 404 for meal_id in meal_ids)
    assert client.get("/api/meal-plan?recipe_url=recipe://soup").get_json() == {"ok": True, "meals": [], "batches": []}
