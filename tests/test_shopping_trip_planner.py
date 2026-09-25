"""One scoped calendar for prep work and live shopping-list links."""

from copy import deepcopy
import json

import pytest

from PushShoppingList.services import meal_plan_service as plans
from PushShoppingList.services import meal_plan_shopping_service as shopping_plans
from PushShoppingList.services import shopping_list_service as shopping
from PushShoppingList.services import shopping_trip_service as trips
from PushShoppingList.services import storage_service
from test_meal_plan_shopping import isolated_shopping, seed_batch, add_review
from test_meal_prep_batches import scoped_client, sign_in


STORE_SETTINGS = {
    "stores": {"aldi": {"label": "Aldi", "password": "private"}, "kroger": {"label": "Kroger"}},
    "enabled_stores": ["aldi"],
}


@pytest.fixture
def isolated_trips(isolated_shopping, monkeypatch):
    monkeypatch.setattr(trips, "SHOPPING_TRIPS_FILE", isolated_shopping / "shopping_trips.json")
    monkeypatch.setattr(trips, "load_store_settings", lambda: deepcopy(STORE_SETTINGS))
    return isolated_shopping


def saved_batch_list(name="This week's groceries"):
    batch, meals = seed_batch()
    review = shopping_plans.review_meal_plan_shopping({"batch_ids": [batch["id"]]})
    result = add_review(review, new_list_name=name)
    return batch, meals, result["list"]


def test_options_live_lists_provenance_enabled_stores_without_sensitive_fields(isolated_trips):
    batch, meals, saved = saved_batch_list()
    shopping.add_items(["coffee"])
    options = trips.shopping_trip_options()
    assert options["lists"][0] == {
        "id": "current", "name": "Current shopping list", "item_count": 1, "is_current": True, "sources": [],
    }
    linked = options["lists"][1]
    assert linked["id"] == saved["id"]
    assert linked["item_count"] == 2
    assert linked["is_current"] is False
    source = linked["sources"][0]
    assert source["id"] == f"batch:{batch['id']}"
    assert source["servings"] == 12
    assert set(source["meal_ids"]) == {meal["id"] for meal in meals}
    assert (source["date_from"], source["date_to"]) == ("2026-09-28", "2026-10-05")
    assert "items" not in source
    assert options["stores"] == [{"key": "aldi", "label": "Aldi"}]
    assert [row["value"] for row in options["statuses"]] == ["planned", "in_progress", "completed"]
    assert not trips.SHOPPING_TRIPS_FILE.exists()


def test_crud_retains_ids_link_and_coverage_without_copying_or_deleting_lists(isolated_trips):
    batch, meals, saved = saved_batch_list()
    before_plan = plans.MEAL_PLAN_FILE.read_bytes()
    before_list = shopping_plans.SHOPPING_PLAN_FILE.read_bytes()
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": saved["id"], "store_key": "aldi"})
    assert trip["status"] == "planned"
    assert trip["source_ids"] == [f"batch:{batch['id']}"]
    assert trip["list_name"] == saved["name"]
    assert trip["store_label"] == "Aldi"
    assert trip["list_available"] is True
    assert "items" not in json.loads(trips.SHOPPING_TRIPS_FILE.read_text())["trips"][0]
    reread = trips.shopping_trip_detail(trip["id"])
    assert reread == trip
    moved = trips.update_shopping_trip(trip["id"], {"date": "2026-10-05", "status": "in_progress"})
    assert moved["id"] == trip["id"]
    assert moved["created_at"] == trip["created_at"]
    assert moved["sources"] == trip["sources"]
    assert trips.planning_week("2026-09-28")["shopping_trips"] == []
    assert trips.planning_week("2026-10-05")["shopping_trips_by_day"]["2026-10-05"] == [moved]
    completed = trips.update_shopping_trip(trip["id"], {"status": "completed", "store_key": ""})
    assert completed["status"] == "completed"
    assert completed["store_key"] == completed["store_label"] == ""
    assert trips.delete_shopping_trip(trip["id"]) == trip["id"]
    assert trips.load_shopping_trips() == {"trips": []}
    assert plans.MEAL_PLAN_FILE.read_bytes() == before_plan
    assert shopping_plans.SHOPPING_PLAN_FILE.read_bytes() == before_list
    with pytest.raises(trips.ShoppingTripError) as missing:
        trips.shopping_trip_detail(trip["id"])
    assert missing.value.status == 404


def test_current_list_is_live_and_can_have_no_meal_provenance(isolated_trips):
    shopping.add_items(["coffee"])
    trip = trips.add_shopping_trip({"date": "2026-09-29", "list_id": "current", "source_ids": []})
    assert trip["sources"] == []
    assert trip["is_current"] is True
    shopping.add_items(["tea"])
    assert trips.shopping_trip_options()["lists"][0]["item_count"] == 2
    trips.delete_shopping_trip(trip["id"])
    assert shopping.load_items() == ["coffee", "tea"]


def test_validated_subset_and_historical_sources_survive_list_and_meal_changes(isolated_trips, monkeypatch):
    batch, _, saved = saved_batch_list()
    selection = {"batch_ids": [batch["id"]]}
    add_review(shopping_plans.review_meal_plan_shopping(selection), list_id="current")
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": "current", "source_ids": [f"batch:{batch['id']}"]})
    shopping.save_items([])
    plan = plans.load_meal_plan()
    plan["meals"] = []
    plan["batches"] = []
    plans.save_meal_plan(plan)
    assert trips.shopping_trip_options()["lists"][0]["sources"] == []
    monkeypatch.setattr(trips, "load_store_settings", lambda: {"stores": {}, "enabled_stores": []})
    changed = trips.update_shopping_trip(trip["id"], {"status": "completed", "source_ids": trip["source_ids"]})
    assert changed["sources"] == trip["sources"]
    assert changed["source_ids"] == trip["source_ids"]
    assert trips.planning_week("2026-09-28")["shopping_trips"][0]["sources"] == trip["sources"]
    cleared = trips.update_shopping_trip(trip["id"], {"source_ids": []})
    assert cleared["sources"] == []
    with pytest.raises(trips.ShoppingTripError, match="belong"):
        trips.update_shopping_trip(trip["id"], {"source_ids": trip["source_ids"]})


def test_same_list_resubmitted_source_id_preserves_original_portions(isolated_trips):
    batch, _, saved = saved_batch_list()
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": saved["id"]})
    document = shopping_plans.load_shopping_plans()
    document["lists"][0]["contributions"][0]["servings"] = 24
    shopping_plans._save(document)
    changed = trips.update_shopping_trip(trip["id"], {"list_id": saved["id"], "source_ids": trip["source_ids"]})
    assert changed["sources"][0]["servings"] == 12
    assert trips.shopping_trip_options()["lists"][1]["sources"][0]["servings"] == 24


def test_list_change_resets_coverage_and_rejects_historical_ids_not_on_new_list(isolated_trips):
    batch, _, saved = saved_batch_list()
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": saved["id"]})
    before = trips.SHOPPING_TRIPS_FILE.read_bytes()
    with pytest.raises(trips.ShoppingTripError, match="belong"):
        trips.update_shopping_trip(trip["id"], {"list_id": "current", "source_ids": trip["source_ids"]})
    assert trips.SHOPPING_TRIPS_FILE.read_bytes() == before
    moved = trips.update_shopping_trip(trip["id"], {"list_id": "current"})
    assert moved["source_ids"] == moved["sources"] == []
    moved_back = trips.update_shopping_trip(trip["id"], {"list_id": saved["id"]})
    assert moved_back["source_ids"] == [f"batch:{batch['id']}"]


def test_disabled_store_and_unavailable_list_do_not_block_historical_trip_edit(isolated_trips, monkeypatch):
    _, _, saved = saved_batch_list()
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": saved["id"], "store_key": "aldi"})
    shopping_plans._save({"lists": []})
    monkeypatch.setattr(trips, "load_store_settings", lambda: {"stores": {}, "enabled_stores": []})
    result = trips.update_shopping_trip(trip["id"], {"status": "completed", "list_id": saved["id"], "store_key": "aldi", "source_ids": trip["source_ids"]})
    assert result["list_available"] is False
    assert result["list_name"] == saved["name"]
    assert result["store_label"] == "Aldi"
    with pytest.raises(trips.ShoppingTripError) as missing:
        trips.add_shopping_trip({"date": "2026-09-28", "list_id": saved["id"]})
    assert missing.value.status == 404


def test_week_prep_uses_actual_task_dates_and_unscheduled_only_without_any_tasks(isolated_trips):
    scheduled, allocations = plans.add_meal_prep_batch({
        "recipe_url": "recipe://rice", "recipe_name": "Rice", "batch_servings": 4,
        "prep_steps": [{"date": "2026-09-29", "instruction": "Cook rice"}, {"date": "2026-10-05", "instruction": "Thaw"}],
    }, [{"date": "2026-10-06", "meal_type": "lunch", "planned_servings": 4}])
    outside, _ = plans.add_meal_prep_batch({
        "recipe_url": "recipe://stew", "recipe_name": "Stew", "batch_servings": 2,
        "prep_steps": [{"date": "2026-09-27", "instruction": "Cook stew"}],
    }, [{"date": "2026-09-30", "meal_type": "dinner", "planned_servings": 2}])
    unscheduled, meals = seed_batch()
    before = plans.MEAL_PLAN_FILE.read_bytes()
    calendar = trips.planning_week("2026-09-30", reference_date="2026-09-30")
    assert calendar["week_start"] == "2026-09-28"
    assert calendar["week_end"] == "2026-10-04"
    assert calendar["previous_week"] == "2026-09-21"
    assert calendar["next_week"] == "2026-10-05"
    assert len(calendar["days"]) == 7
    assert calendar["days"][2]["is_today"] is True
    task = calendar["prep_steps_by_day"]["2026-09-29"][0]
    assert task["batch_id"] == scheduled["id"]
    assert task["meal_id"] == allocations[0]["id"]
    assert task["instruction"] == "Cook rice"
    assert sum(map(len, calendar["prep_steps_by_day"].values())) == 1
    assert [row["id"] for row in calendar["unscheduled_prep_batches"]] == [unscheduled["id"]]
    summary = calendar["unscheduled_prep_batches"][0]
    assert summary["batch_id"] == unscheduled["id"]
    assert summary["meal_id"] in {meal["id"] for meal in meals}
    assert len(summary["allocations"]) == 3
    assert summary["allocated_servings"] == 12
    assert "meals_by_slot" not in calendar
    assert plans.MEAL_PLAN_FILE.read_bytes() == before
    json.dumps(calendar, allow_nan=False)


@pytest.mark.parametrize("payload", [
    None, [], {}, {"date": "2026-09-28"}, {"list_id": "current"},
    {"date": None, "list_id": "current"}, {"date": True, "list_id": "current"},
    {"date": "2026-02-30", "list_id": "current"}, {"date": "2026-09-28 ", "list_id": "current"},
    {"date": "2026-09-28", "list_id": None}, {"date": "2026-09-28", "list_id": "unknown"},
    {"date": "2026-09-28", "list_id": "current", "status": "done"},
    {"date": "2026-09-28", "list_id": "current", "status": []},
    {"date": "2026-09-28", "list_id": "current", "store_key": "kroger"},
    {"date": "2026-09-28", "list_id": "current", "source_ids": "meal:a"},
    {"date": "2026-09-28", "list_id": "current", "source_ids": [None]},
    {"date": "2026-09-28", "list_id": "current", "source_ids": ["batch:foreign"]},
    {"date": "2026-09-28", "list_id": "current", "list_name": "Spoofed"},
])
def test_malformed_create_never_persists_partial_trip(isolated_trips, payload):
    with pytest.raises(trips.ShoppingTripError):
        trips.add_shopping_trip(payload)
    assert not trips.SHOPPING_TRIPS_FILE.exists()


@pytest.mark.parametrize("payload", [None, {}, [], {"status": False}, {"date": "not a date"}, {"id": "changed"}, {"source_ids": [{}]}, {"store_key": 3}])
def test_malformed_patch_keeps_original_bytes(isolated_trips, payload):
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": "current"})
    before = trips.SHOPPING_TRIPS_FILE.read_bytes()
    with pytest.raises(trips.ShoppingTripError):
        trips.update_shopping_trip(trip["id"], payload)
    assert trips.SHOPPING_TRIPS_FILE.read_bytes() == before


def test_atomic_write_failure_and_corrupt_documents_not_replaced(isolated_trips, monkeypatch):
    trip = trips.add_shopping_trip({"date": "2026-09-28", "list_id": "current"})
    before = trips.SHOPPING_TRIPS_FILE.read_bytes()
    monkeypatch.setattr(trips, "_save", lambda value: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        trips.update_shopping_trip(trip["id"], {"status": "completed"})
    assert trips.SHOPPING_TRIPS_FILE.read_bytes() == before
    trips.SHOPPING_TRIPS_FILE.write_text('{"trips": "broken"}')
    with pytest.raises(trips.ShoppingTripError) as broken:
        trips.add_shopping_trip({"date": "2026-09-28", "list_id": "current"})
    assert broken.value.status == 500
    assert trips.SHOPPING_TRIPS_FILE.read_text() == '{"trips": "broken"}'


@pytest.fixture
def trip_client(scoped_client, monkeypatch):
    monkeypatch.setattr(trips, "SHOPPING_TRIPS_FILE", storage_service.scoped_package_path("shopping_trips.json"))
    monkeypatch.setattr(shopping_plans, "SHOPPING_PLAN_FILE", storage_service.scoped_package_path("meal_plan_shopping.json"))
    monkeypatch.setattr(shopping, "SHOPPING_LIST_FILE", storage_service.scoped_package_path("shopping_list.txt"))
    monkeypatch.setattr(trips, "load_store_settings", lambda: deepcopy(STORE_SETTINGS))
    return scoped_client


def test_api_crud_auth_scope_guest_week_and_viewer_protection(trip_client):
    client = trip_client
    endpoints = ["/api/planning/week", "/api/shopping-trips/options", "/api/shopping-trips/anything"]
    for endpoint in endpoints:
        assert client.get(endpoint).status_code == 403
    assert client.post("/api/shopping-trips", json={}).status_code == 403
    assert client.patch("/api/shopping-trips/a", json={}).status_code == 403
    assert client.delete("/api/shopping-trips/a").status_code == 403
    sign_in(client, "owner")
    options = client.get("/api/shopping-trips/options").get_json()
    assert options["ok"] is True
    assert options["lists"][0]["id"] == "current"
    result = client.post("/api/shopping-trips", json={"date": "2026-12-31", "list_id": "current", "store_key": "aldi"})
    assert result.status_code == 201
    trip = result.get_json()["trip"]
    url = "/api/shopping-trips/" + trip["id"]
    assert client.get(url).get_json()["trip"] == trip
    assert client.patch(url, json={"status": "in_progress"}).get_json()["trip"]["status"] == "in_progress"
    week = client.get("/api/planning/week?week_start=2027-01-01").get_json()
    assert week["week_start"] == "2026-12-28"
    assert week["week_end"] == "2027-01-03"
    assert week["shopping_trips_by_day"]["2026-12-31"][0]["id"] == trip["id"]
    for endpoint in endpoints + [url]:
        assert client.get(endpoint + "?viewer_user_id=other").status_code == 403
    assert client.post("/api/shopping-trips?viewer_user_id=other", json={"date": "2026-09-28", "list_id": "current"}).status_code == 403
    assert client.patch(url + "?viewer_user_id=other", json={"status": "completed"}).status_code == 403
    assert client.delete(url + "?viewer_user_id=other").status_code == 403
    assert client.get("/api/planning/week?week_start=invalid").status_code == 400
    assert client.post("/api/shopping-trips", json=[]).status_code == 400
    assert client.patch(url, json={"date": None}).status_code == 400

    for identity, guest in [("other", False), ("guest-workspace", True)]:
        sign_in(client, identity, guest=guest)
        assert client.get("/api/planning/week?week_start=2026-12-28").get_json()["shopping_trips"] == []
        assert client.get(url).status_code == 404
        assert client.patch(url, json={"status": "completed"}).status_code == 404
        assert client.delete(url).status_code == 404
    assert client.post("/api/shopping-trips", json={"date": "2026-09-28", "list_id": "current"}).status_code == 201
    assert len(client.get("/api/planning/week?week_start=2026-09-28").get_json()["shopping_trips"]) == 1
    assert client.get("/api/shopping-trips/options?viewer_user_id=owner").status_code == 403
    sign_in(client, "owner")
    assert client.delete(url).get_json() == {"ok": True, "removed_id": trip["id"]}
    assert client.get(url).status_code == 404


def test_api_named_lists_and_source_ids_are_workspace_scoped(trip_client):
    client = trip_client
    sign_in(client, "owner")
    with client.application.test_request_context():
        from flask import g
        g.session_identity_validated = True
        g.authenticated_user_id = "owner"
        g.authenticated_guest_session_id = ""
        shopping_plans._save({"lists": [{"id": "owners-list", "name": "Owner list", "contributions": [{
            "id": "batch:owners-batch", "kind": "batch", "record_id": "owners-batch", "recipe_name": "Soup",
            "recipe_url": "recipe://soup", "servings": 12, "meal_ids": ["owner-meal"], "items": [],
        }], "checked": {}}]})
    result = client.post("/api/shopping-trips", json={"date": "2026-09-28", "list_id": "owners-list"})
    assert result.status_code == 201
    assert result.get_json()["trip"]["source_ids"] == ["batch:owners-batch"]
    sign_in(client, "other")
    assert [row["id"] for row in client.get("/api/shopping-trips/options").get_json()["lists"]] == ["current"]
    assert client.post("/api/shopping-trips", json={"date": "2026-09-28", "list_id": "owners-list"}).status_code == 404
    assert client.post("/api/shopping-trips", json={"date": "2026-09-28", "list_id": "current", "source_ids": ["batch:owners-batch"]}).status_code == 400
