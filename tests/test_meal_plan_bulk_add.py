import pytest

from PushShoppingList.routes import main_routes
from PushShoppingList.services import meal_plan_service as service
from test_meal_prep_batches import allocations, batch_input, isolated_plan, scoped_client, sign_in


def entry(url="recipe://soup"):
    return {"batch": {**batch_input(), "recipe_url": url}, "allocations": allocations(),
            "ingredient_data": {"ingredients": [{"name": url}], "ingredient_option_selections": {"choice": url}}}


def test_multiple_recipes_keep_independent_plans_in_one_write(isolated_plan, monkeypatch):
    writes = []
    save = service.save_meal_plan
    monkeypatch.setattr(service, "save_meal_plan", lambda payload: (writes.append(payload), save(payload))[1])
    batches, meals = service.add_meal_prep_batches([entry(), entry("recipe://bread")])
    assert len(writes) == 1
    assert len(batches) == 2 and len(meals) == 6
    stored = service.load_meal_plan()
    assert len(stored["meals"]) == 6
    for batch in batches:
        own = [meal for meal in stored["meals"] if meal["batch_id"] == batch["id"]]
        assert len(own) == 3
        assert all(meal["ingredient_option_selections"] == {"choice": batch["recipe_url"]} for meal in own)
        assert all(meal["ingredients"][0]["name"] == batch["recipe_url"] for meal in own)
        assert len(batch["prep_steps"]) == 3


@pytest.mark.parametrize("kind", ["duplicate", "invalid-date", "invalid-portions", "existing-slot", "archived-member"])
def test_invalid_later_recipe_never_saves_earlier_recipes(isolated_plan, kind):
    service.add_meal({"date": "2026-09-28", "meal_type": "lunch", "recipe_url": "recipe://existing", "recipe_name": "Existing"})
    second = entry("recipe://bread")
    if kind == "duplicate":
        second = entry()
    elif kind == "invalid-date":
        second["allocations"][1]["date"] = "bad"
    elif kind == "invalid-portions":
        second["allocations"][1]["planned_servings"] = 0
    elif kind == "existing-slot":
        second = entry("recipe://existing")
    else:
        person = service.add_meal_plan_member("Person")
        service.update_meal_plan_member(person["id"], archived=True)
        second["batch"]["portion_mode"] = "family"
        second["allocations"] = [{"date": "2026-09-28", "meal_type": "dinner", "member_portions": [{"member_id": person["id"], "servings": 1}]}]
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="Recipe 2"):
        service.add_meal_prep_batches([entry(), second])
    assert isolated_plan.read_bytes() == before


@pytest.mark.parametrize("value", [None, [], {}, "invalid", [None], [entry()] * 101])
def test_invalid_collection_does_not_create_a_plan(isolated_plan, value):
    with pytest.raises(ValueError):
        service.add_meal_prep_batches(value)
    assert not isolated_plan.exists()


def test_bulk_route_collection_scope_and_atomic_retry(scoped_client, monkeypatch):
    client = scoped_client
    endpoint = "/api/meal-plan/batches/bulk"
    recipes = [{"url": "recipe://soup", "name": "Soup"}, {"url": "recipe://bread", "name": "Bread"}]
    monkeypatch.setattr(main_routes, "meal_plan_recipe_option_rows", lambda rows: recipes)
    first = {**batch_input(), "allocations": allocations()}
    second = {**first, "recipe_url": "recipe://bread", "recipe_name": "Untrusted name"}
    body = {"batches": [first, second]}
    assert client.post(endpoint, json=body).status_code == 403
    sign_in(client, "alice")
    assert client.post(endpoint + "?viewer_user_id=bob", json=body).status_code == 403
    for invalid in (None, [], {}, {"batches": []}, {"batches": [first, None]},
                    {"batches": [first, {**second, "recipe_url": "recipe://foreign"}]},
                    {"batches": [first, {**second, "allocations": [{"date": "bad"}]}]}):
        assert client.post(endpoint, json=invalid).status_code == 400
        assert client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"] == []
    response = client.post(endpoint, json=body)
    assert response.status_code == 201
    assert len(response.json["meals"]) == 6
    assert [batch["recipe_name"] for batch in response.json["batches"]] == ["Soup", "Bread"]
    assert client.post(endpoint, json=body).status_code == 400
    assert len(client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"]) == 3
    for user, guest in (("bob", False), ("guest-bulk", True)):
        sign_in(client, user, guest)
        assert client.get("/api/meal-plan?recipe_url=recipe://soup").json["meals"] == []
        assert client.post(endpoint, json=body).status_code == 201
