import json

import pytest
from flask import Flask, g, session

from PushShoppingList.routes import main_routes
from PushShoppingList.services import meal_plan_service as service
from PushShoppingList.services import storage_service


@pytest.fixture
def isolated_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    path = tmp_path / "meal_plan.json"
    monkeypatch.setattr(service, "MEAL_PLAN_FILE", path)
    return path


def batch_input():
    return {
        "recipe_url": "recipe://soup",
        "recipe_name": "Soup",
        "batch_servings": 12,
        "prep_notes": "Cool and portion the batch",
        "prep_steps": [
            {"date": "2026-09-27", "instruction": "Chop vegetables"},
            {"date": "2026-09-28", "instruction": "Cook and portion"},
            {"date": "2026-10-05", "instruction": "Thaw remaining portions"},
        ],
    }


def allocations():
    return [
        {"date": "2026-09-28", "meal_type": "lunch", "planned_servings": 4, "prep_notes": "Reheat gently"},
        {"date": "2026-09-30", "meal_type": "dinner", "planned_servings": 3},
        {"date": "2026-10-05", "meal_type": "lunch", "planned_servings": 4},
    ]


def test_batch_persists_linked_allocations_steps_and_separate_notes(isolated_plan):
    batch, meals = service.add_meal_prep_batch(batch_input(), allocations(), {
        "ingredient_option_selections": {"requirement-1": "option-2"},
        "ingredients": [{"name": "carrot", "quantity": 2}],
    })
    stored = service.load_meal_plan()
    assert len(stored["batches"]) == 1
    assert batch["allocated_servings"] == 11
    assert batch["remaining_servings"] == 1
    assert all(meal["batch_id"] == batch["id"] for meal in stored["meals"])
    assert stored["meals"][0]["prep_notes"] == "Reheat gently"
    assert stored["meals"][1]["prep_notes"] == ""
    assert stored["batches"][0]["prep_notes"] == "Cool and portion the batch"
    assert stored["meals"][0]["ingredients"][0]["name"] == "carrot"
    assert stored["meals"][0]["ingredient_option_selections"] == {"requirement-1": "option-2"}
    assert all("recipe_notes" not in row for row in stored["meals"] + stored["batches"])
    assert len({step["id"] for step in batch["prep_steps"]}) == 3
    assert all(step["completed"] is False for step in batch["prep_steps"])
    assert [meal["id"] for meal in batch["allocations"]] == [meal["id"] for meal in meals]


def test_fractional_allocations_use_exact_portion_totals(isolated_plan):
    portions = [{**meal, "planned_servings": 1.1} for meal in allocations()]
    batch, meals = service.add_meal_prep_batch({**batch_input(), "batch_servings": 3.3}, portions)
    assert batch["allocated_servings"] == 3.3
    assert batch["remaining_servings"] == 0
    service.delete_meal(meals[0]["id"])
    stored = service.load_meal_plan()
    updated = service.meal_prep_batch_summary(stored["batches"][0], stored["meals"])
    assert updated["allocated_servings"] == 2.2
    assert updated["remaining_servings"] == 1.1


@pytest.mark.parametrize("field,value", [
    ("batch_servings", 0), ("batch_servings", True), ("batch_servings", float("inf")),
    ("batch_servings", 10 ** 400),
    ("batch_servings", float("nan")), ("prep_steps", "Chop"),
    ("prep_steps", [{"date": "not-a-date", "instruction": "Chop"}]),
    ("prep_steps", [{"date": "2026-09-27", "instruction": " "}]),
])
def test_invalid_batch_is_atomic(isolated_plan, field, value):
    service.add_meal({"date": "2026-09-28", "meal_type": "breakfast", "recipe_url": "recipe://toast", "recipe_name": "Toast"})
    before = isolated_plan.read_bytes()
    candidate = batch_input()
    candidate[field] = value
    with pytest.raises(ValueError):
        service.add_meal_prep_batch(candidate, allocations())
    assert isolated_plan.read_bytes() == before


@pytest.mark.parametrize("candidate", [
    [], None, "invalid", [None],
    [{"date": "2026-09-28", "meal_type": "lunch", "planned_servings": 13}],
    [{"date": "2026-09-28", "meal_type": "lunch", "planned_servings": float("nan")}],
    [{"date": "2026-09-28", "meal_type": "lunch", "planned_servings": 10 ** 400}],
    [{"date": "bad", "meal_type": "lunch", "planned_servings": 4}],
    [{"date": "2026-09-28", "meal_type": "invalid", "planned_servings": 4}],
    [allocations()[0], allocations()[0]],
    [allocations()[0], {"date": "bad", "meal_type": "dinner", "planned_servings": 4}],
])
def test_invalid_allocation_never_saves_partial_batch(isolated_plan, candidate):
    with pytest.raises(ValueError):
        service.add_meal_prep_batch(batch_input(), candidate)
    assert not isolated_plan.exists()
    assert service.load_meal_plan() == {"meals": [], "batches": []}


def test_existing_slot_conflict_is_atomic_but_other_recipes_can_share_slot(isolated_plan):
    service.add_meal({**allocations()[1], "recipe_url": "recipe://soup", "recipe_name": "Soup"})
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="already planned"):
        service.add_meal_prep_batch(batch_input(), allocations())
    assert isolated_plan.read_bytes() == before
    other = {**batch_input(), "recipe_url": "recipe://stew", "recipe_name": "Stew"}
    assert service.add_meal_prep_batch(other, allocations())[0]["allocated_servings"] == 11


def test_existing_mutations_preserve_batch_and_recalculate_remaining(isolated_plan, monkeypatch):
    batch, meals = service.add_meal_prep_batch(batch_input(), allocations())
    step_id = batch["prep_steps"][0]["id"]
    service.update_meal_prep_step(batch["id"], step_id, True)
    service.update_meal_ingredient_option_selections(meals[0]["id"], {})
    monkeypatch.setattr(service, "recipe_data_with_sql_requirements", lambda url, data: data)
    service.sync_meal_recipe_ingredients("recipe://soup", {"ingredients": [{"name": "onion"}]})
    service.delete_meal(meals[0]["id"])
    service.add_meal({"date": "2026-09-28", "meal_type": "breakfast", "recipe_url": "recipe://toast", "recipe_name": "Toast"})
    stored = service.load_meal_plan()
    saved_batch = stored["batches"][0]
    assert saved_batch["prep_steps"][0]["completed"] is True
    assert saved_batch["prep_notes"] == batch["prep_notes"]
    assert service.meal_prep_batch_summary(saved_batch, stored["meals"])["remaining_servings"] == 5
    assert all(meal.get("batch_id") == batch["id"] for meal in stored["meals"] if meal["recipe_url"] == "recipe://soup")
    assert service.delete_meal_prep_batch(batch["id"]) is True
    assert service.delete_meal_prep_batch(batch["id"]) is False
    assert service.load_meal_plan()["batches"] == []
    assert [meal["recipe_name"] for meal in service.load_meal_plan()["meals"]] == ["Toast"]


def test_preparation_timeline_filters_each_week_without_counting_steps_as_meals(isolated_plan):
    batch, _ = service.add_meal_prep_batch(batch_input(), allocations())
    service.update_meal_prep_step(batch["id"], batch["prep_steps"][0]["id"], True)
    previous = service.meal_plan_for_week("2026-09-27")
    current = service.meal_plan_for_week("2026-09-28")
    next_week = service.meal_plan_for_week("2026-10-05")
    assert previous["meal_count"] == 0
    assert previous["prep_steps_by_day"]["2026-09-27"][0]["completed"] is True
    assert current["meal_count"] == 2
    assert current["unique_recipe_count"] == 1
    assert sum(map(len, current["prep_steps_by_day"].values())) == 1
    assert current["prep_steps_by_day"]["2026-09-28"][0]["recipe_name"] == "Soup"
    assert next_week["meal_count"] == 1
    assert next_week["prep_steps_by_day"]["2026-10-05"][0]["batch_id"] == batch["id"]


def test_legacy_document_stays_readable_and_survives_new_batch(isolated_plan):
    legacy = {"id": "old", "date": "2026-09-26", "meal_type": "dinner", "recipe_url": "recipe://toast", "recipe_name": "Toast"}
    isolated_plan.write_text(json.dumps({"meals": [legacy]}), encoding="utf-8")
    assert service.load_meal_plan()["batches"] == []
    service.add_meal_prep_batch(batch_input(), allocations())
    assert service.load_meal_plan()["meals"][0]["id"] == "old"


@pytest.fixture
def scoped_client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(service, "MEAL_PLAN_FILE", storage_service.scoped_package_path("meal_plan.json"))
    monkeypatch.setattr(main_routes, "current_public_user", lambda: {"user_id": g.authenticated_user_id} if g.authenticated_user_id else None)
    monkeypatch.setattr(main_routes, "is_guest_session", lambda: bool(g.authenticated_guest_session_id))
    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: [])
    monkeypatch.setattr(main_routes, "meal_plan_recipe_option_rows", lambda rows: [{"url": "recipe://soup", "name": "Soup", "default_servings": 12}])
    monkeypatch.setattr(main_routes, "load_recipe_output", lambda url: {"ingredients": [{"name": "carrot"}]})
    app = Flask(__name__)
    app.secret_key = "test-only-meal-prep"
    app.register_blueprint(main_routes.main_bp)

    @app.before_request
    def identity():
        g.session_identity_validated = True
        g.authenticated_user_id = session.get("user_id", "")
        g.authenticated_guest_session_id = session.get("guest_id", "")

    return app.test_client()


def sign_in(client, identity, guest=False):
    with client.session_transaction() as current:
        current.clear()
        current["guest_id" if guest else "user_id"] = identity


def test_batch_routes_auth_collection_checks_and_workspace_isolation(scoped_client):
    client = scoped_client
    payload = {**batch_input(), "allocations": allocations()}
    assert client.post("/api/meal-plan/batches", json=payload).status_code == 403
    assert client.patch("/api/meal-plan/batches/missing/prep-steps/missing", json={"completed": True}).status_code == 403
    assert client.delete("/api/meal-plan/batches/missing").status_code == 403
    sign_in(client, "alice")
    assert client.post("/api/meal-plan/batches", json=[]).status_code == 400
    assert client.post("/api/meal-plan/batches", json={**payload, "recipe_url": "recipe://other-user"}).status_code == 400
    response = client.post("/api/meal-plan/batches", json=payload)
    assert response.status_code == 201
    batch = response.json["batch"]
    batch_id = batch["id"]
    step_id = batch["prep_steps"][0]["id"]
    endpoint = f"/api/meal-plan/batches/{batch_id}/prep-steps/{step_id}"
    assert client.patch(endpoint, json={"completed": "true"}).status_code == 400
    assert client.patch(endpoint, json={"completed": True}).json["step"]["completed"] is True
    read = client.get("/api/meal-plan?recipe_url=recipe://soup").json
    assert read["batches"][0]["allocated_servings"] == 11
    assert read["batches"][0]["prep_steps"][0]["completed"] is True
    assert len(read["batches"][0]["allocations"]) == 3
    assert all(meal["batch_id"] == batch_id for meal in read["meals"])
    for user, guest in (("bob", False), ("guest-test", True)):
        sign_in(client, user, guest)
        assert client.get("/api/meal-plan?recipe_url=recipe://soup").json["batches"] == []
        assert client.patch(endpoint, json={"completed": False}).status_code == 404
        assert client.delete(f"/api/meal-plan/batches/{batch_id}").status_code == 404
        own_batch = client.post("/api/meal-plan/batches", json=payload).json["batch"]
        assert own_batch["id"] != batch_id
    sign_in(client, "alice")
    first_meal = read["meals"][0]["id"]
    assert client.delete(f"/api/meal-plan/{first_meal}").status_code == 200
    read = client.get("/api/meal-plan?recipe_url=recipe://soup").json
    assert read["batches"][0]["remaining_servings"] == 5
    assert client.delete(f"/api/meal-plan/batches/{batch_id}").status_code == 200
    assert client.get("/api/meal-plan?recipe_url=recipe://soup").json == {"ok": True, "meals": [], "batches": []}
