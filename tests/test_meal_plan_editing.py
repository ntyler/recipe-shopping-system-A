"""Meal and whole-plan edits preserve identities, history and scoped atomic writes."""

import pytest

from PushShoppingList.services import meal_plan_service as service
from test_meal_prep_batches import isolated_plan, scoped_client, sign_in, batch_input, allocations


def seed_plan():
    return service.add_meal_prep_batch(batch_input(), allocations(), {
        "ingredient_option_selections": {"butter": "unsalted"},
        "ingredients": [{"name": "carrot", "quantity": 2}],
    })


def test_detail_includes_complete_cross_week_batch_and_individual_edit_preserves_others(isolated_plan):
    batch, meals = seed_plan()
    unrelated = service.add_meal({"date": "2026-09-28", "meal_type": "breakfast", "recipe_url": "recipe://toast", "recipe_name": "Toast"})
    before = service.load_meal_plan()
    detail = service.meal_plan_entry_detail(meals[0]["id"])
    assert len(detail["batch"]["allocations"]) == 3
    assert detail["batch"]["allocations"][-1]["date"] == "2026-10-05"
    result = service.update_meal(meals[0]["id"], {"date": "2026-10-12", "meal_type": "dinner", "planned_servings": 5.5, "prep_notes": "Pack separately"})
    updated = result["meal"]
    assert updated["id"] == meals[0]["id"]
    assert updated["batch_id"] == batch["id"]
    assert updated["recipe_url"] == meals[0]["recipe_url"]
    for field in ("created_at", "ingredients", "ingredient_option_selections"):
        assert updated[field] == meals[0][field]
    after = service.load_meal_plan()
    assert [meal for meal in after["meals"] if meal["id"] != updated["id"]] == [meal for meal in before["meals"] if meal["id"] != updated["id"]]
    assert result["batch"]["allocated_servings"] == 12.5
    assert result["batch"]["batch_servings"] == 13.5
    assert result["batch"]["remaining_servings"] == 1
    assert service.meal_plan_entry_detail(unrelated["id"])["meal"] == unrelated
    assert "batch" not in service.meal_plan_entry_detail(unrelated["id"])


def test_legacy_individual_notes_edit_keeps_unknown_servings_and_has_no_batch(isolated_plan):
    meal = service.add_meal({"date": "2026-09-28", "meal_type": "breakfast", "recipe_url": "recipe://toast", "recipe_name": "Toast"})
    result = service.update_meal(meal["id"], {"prep_notes": "Toast just before eating"})
    assert result["meal"]["prep_notes"] == "Toast just before eating"
    assert "planned_servings" not in result["meal"]
    assert "batch" not in result


@pytest.mark.parametrize("patch", [
    None, [], {}, {"recipe_url": "recipe://other"}, {"id": "other"},
    {"batch_id": "other"}, {"ingredients": []}, {"planned_servings": 0},
    {"planned_servings": True}, {"planned_servings": float("nan")},
    {"planned_servings": 10 ** 400}, {"date": "bad"}, {"meal_type": "brunch"},
    {"portion_mode": "invalid"}, {"portion_mode": None}, {"prep_notes": []},
    {"member_portions": {}}, {"member_portions": None}, {"date": 20261012},
    {"member_portions": [{"member_id": "other", "servings": 1}]},
])
def test_invalid_individual_edit_is_atomic(isolated_plan, patch):
    _, meals = seed_plan()
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError):
        service.update_meal(meals[0]["id"], patch)
    assert isolated_plan.read_bytes() == before


def test_individual_slot_collision_is_atomic(isolated_plan):
    _, meals = seed_plan()
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="already planned"):
        service.update_meal(meals[0]["id"], {"date": meals[1]["date"], "meal_type": meals[1]["meal_type"]})
    assert isolated_plan.read_bytes() == before


def test_batch_edit_preserves_matching_ids_choices_task_completion_and_custom_notes(isolated_plan):
    batch, meals = seed_plan()
    service.update_meal_prep_step(batch["id"], batch["prep_steps"][0]["id"], True)
    service.update_meal_ingredient_option_selections(meals[1]["id"], {"butter": "salted"})
    untouched = service.add_meal({"date": "2026-09-28", "meal_type": "breakfast", "recipe_url": "recipe://toast", "recipe_name": "Toast"})
    result = service.update_meal_prep_batch(batch["id"], {
        "recipe_url": batch["recipe_url"], "portion_mode": "household", "prep_notes": "New shared notes",
        "allocations": [
            {"id": meals[0]["id"], "date": "2026-10-12", "meal_type": "breakfast", "planned_servings": 1.5},
            {"date": meals[1]["date"], "meal_type": meals[1]["meal_type"], "planned_servings": 2},
            {"date": "2026-10-13", "meal_type": "lunch", "planned_servings": 3},
        ],
        "prep_steps": [
            {"id": batch["prep_steps"][0]["id"], "date": "2026-10-11", "instruction": "Prep earlier"},
            {"date": batch["prep_steps"][1]["date"], "instruction": batch["prep_steps"][1]["instruction"]},
            {"date": "2026-10-12", "instruction": "Package"},
        ],
    })
    by_id = {meal["id"]: meal for meal in result["meals"]}
    assert by_id[meals[0]["id"]]["prep_notes"] == "Reheat gently"
    assert by_id[meals[1]["id"]]["ingredient_option_selections"] == {"butter": "salted"}
    assert meals[2]["id"] not in by_id
    added = next(meal for meal in result["meals"] if meal["id"] not in {row["id"] for row in meals})
    assert added["ingredient_option_selections"] == {"butter": "unsalted"}
    assert added["prep_notes"] == ""
    assert result["batch"]["batch_servings"] == result["batch"]["allocated_servings"] == 6.5
    assert result["batch"]["prep_notes"] == "New shared notes"
    assert result["batch"]["prep_steps"][0]["id"] == batch["prep_steps"][0]["id"]
    assert result["batch"]["prep_steps"][0]["completed"] is True
    assert result["batch"]["prep_steps"][1]["id"] == batch["prep_steps"][1]["id"]
    assert result["batch"]["prep_steps"][2]["id"] not in {step["id"] for step in batch["prep_steps"]}
    assert service.meal_plan_entry_detail(untouched["id"])["meal"] == untouched


def test_notes_only_batch_edit_preserves_spare_portions_steps_and_meals(isolated_plan):
    batch, _ = seed_plan()
    before = service.load_meal_plan()
    result = service.update_meal_prep_batch(batch["id"], {"prep_notes": "Only shared notes"})
    assert result["batch"]["remaining_servings"] == 1
    assert result["batch"]["prep_steps"] == batch["prep_steps"]
    assert service.load_meal_plan()["meals"] == before["meals"]
    assert result["batch"]["id"] == batch["id"]


def test_archived_existing_assignments_keep_snapshot_and_mixed_batch_modes(isolated_plan):
    nate = service.add_meal_plan_member("Nate")
    batch, meals = service.add_meal_prep_batch({**batch_input(), "portion_mode": "family"}, [
        {"date": "2026-09-28", "meal_type": "lunch", "member_portions": [{"member_id": nate["id"], "servings": 1}]},
        {"date": "2026-10-05", "meal_type": "dinner", "member_portions": [{"member_id": nate["id"], "servings": 1}]},
    ])
    service.update_meal_plan_member(nate["id"], name="Nathan", archived=True)
    detail = service.update_meal(meals[0]["id"], {"date": "2026-10-12", "member_portions": [{"member_id": nate["id"], "servings": 1.5}]})
    assert detail["meal"]["member_portions"] == [{"member_id": nate["id"], "name": "Nathan", "name_snapshot": "Nate", "servings": 1.5}]
    service.update_meal(meals[1]["id"], {"portion_mode": "household", "planned_servings": 2})
    full = service.meal_prep_batch_detail(batch["id"])
    updates = [{key: meal[key] for key in ("id", "date", "meal_type", "portion_mode", "planned_servings", "member_portions")} for meal in full["meals"]]
    result = service.update_meal_prep_batch(batch["id"], {"portion_mode": "family", "allocations": updates})
    assert {meal["portion_mode"] for meal in result["meals"]} == {"family", "household"}
    assert result["batch"]["member_totals"][0]["servings"] == 1.5
    assert result["batch"]["allocated_servings"] == 3.5
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError, match="archived"):
        service.update_meal_prep_batch(batch["id"], {"allocations": updates + [
            {"date": "2026-10-13", "meal_type": "dinner", "member_portions": [{"member_id": nate["id"], "servings": 1}]},
        ]})
    assert isolated_plan.read_bytes() == before
    with pytest.raises(ValueError, match="archived"):
        service.update_meal(meals[1]["id"], {"member_portions": [{"member_id": nate["id"], "servings": 1}]})
    assert isolated_plan.read_bytes() == before


@pytest.mark.parametrize("patch", [
    None, [], {}, {"allocations": []}, {"allocations": [None]},
    {"allocations": [{"id": "foreign", "date": "2026-09-28", "meal_type": "lunch", "planned_servings": 1}]},
    {"allocations": [{"id": [], "planned_servings": 1}]},
    {"recipe_url": "recipe://different"}, {"ingredient_option_selections": {"butter": "different"}},
    {"ingredient_option_selections": None},
    {"portion_mode": "other"}, {"batch_servings": 1}, {"batch_servings": True},
    {"prep_notes": {}}, {"prep_steps": [{}]}, {"prep_steps": "Prep"},
    {"prep_steps": [{"id": "foreign", "date": "2026-09-28", "instruction": "Prep"}]},
    {"prep_steps": [{"date": "2026-09-28", "instruction": "Prep", "completed": "true"}]},
])
def test_invalid_whole_plan_edits_are_atomic(isolated_plan, patch):
    batch, _ = seed_plan()
    before = isolated_plan.read_bytes()
    with pytest.raises(ValueError):
        service.update_meal_prep_batch(batch["id"], patch)
    assert isolated_plan.read_bytes() == before


def test_repeated_ids_slots_and_conflicts_never_save_partial_batch(isolated_plan):
    batch, meals = seed_plan()
    original = [{key: meal[key] for key in ("id", "date", "meal_type", "planned_servings")} for meal in meals]
    other_batch, other_meals = service.add_meal_prep_batch({**batch_input(), "recipe_url": "recipe://stew"}, allocations())
    blocked = service.add_meal({"date": "2026-10-12", "meal_type": "lunch", "recipe_url": "recipe://soup", "recipe_name": "Soup"})
    before = isolated_plan.read_bytes()
    for rows in ([original[0], original[0]],
                 [original[0], {**original[1], "date": original[0]["date"], "meal_type": original[0]["meal_type"]}],
                 [{**original[0], "date": blocked["date"], "meal_type": blocked["meal_type"]}],
                 [{**original[0], "id": other_meals[0]["id"]}]):
        with pytest.raises(ValueError):
            service.update_meal_prep_batch(batch["id"], {"allocations": rows})
        assert isolated_plan.read_bytes() == before
    step = batch["prep_steps"][0]
    with pytest.raises(ValueError):
        service.update_meal_prep_batch(batch["id"], {"prep_steps": [step, step]})
    assert isolated_plan.read_bytes() == before


def test_edit_routes_full_prefill_patch_scope_and_forged_viewers(scoped_client):
    client = scoped_client
    for endpoint in ("/api/meal-plan/missing", "/api/meal-plan/batches/missing"):
        assert client.get(endpoint).status_code == 403
        assert client.patch(endpoint, json={"prep_notes": "Test"}).status_code == 403
    sign_in(client, "alice")
    created = client.post("/api/meal-plan/batches", json={**batch_input(), "allocations": allocations()}).json
    batch_url = "/api/meal-plan/batches/" + created["batch"]["id"]
    meal_url = "/api/meal-plan/" + created["meals"][0]["id"]
    full = client.get(batch_url).json
    assert full["ok"] is True
    assert full["meals"] == full["batch"]["allocations"]
    assert full["meals"][-1]["date"] == "2026-10-05"
    assert client.get(meal_url).json["batch"]["id"] == created["batch"]["id"]
    assert client.patch(meal_url, json={"planned_servings": 5}).json["meal"]["planned_servings"] == 5
    assert client.patch(batch_url, json={"prep_notes": "Edited"}).json["batch"]["prep_notes"] == "Edited"
    for endpoint in (batch_url, meal_url):
        for invalid in (None, [], {}, {"unsupported": True}):
            assert client.patch(endpoint, json=invalid).status_code == 400
        assert client.get(endpoint + "?viewer_user_id=bob").status_code == 403
        assert client.patch(endpoint + "?viewer_user_id=bob", json={"prep_notes": "Hacked"}).status_code == 403
    for who, guest in (("bob", False), ("guest-other", True)):
        sign_in(client, who, guest)
        for endpoint in (batch_url, meal_url):
            assert client.get(endpoint).status_code == 404
            assert client.patch(endpoint, json={"prep_notes": "Foreign"}).status_code == 404
    sign_in(client, "alice")
    assert client.get(batch_url).json["batch"]["prep_notes"] == "Edited"
    assert client.get(meal_url).json["meal"]["planned_servings"] == 5
