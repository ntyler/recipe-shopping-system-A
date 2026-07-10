from datetime import date
from pathlib import Path

import pytest

from PushShoppingList.services import meal_plan_service
from PushShoppingList.services.user_account_service import load_users


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


@pytest.fixture
def isolated_meal_plan(monkeypatch, tmp_path):
    target = tmp_path / "meal_plan.json"
    monkeypatch.setattr(meal_plan_service, "MEAL_PLAN_FILE", target)
    return target


def test_meal_plan_week_context_and_persistence(isolated_meal_plan):
    context = meal_plan_service.meal_plan_for_week("2026-07-10")

    assert context["week_start"] == "2026-07-06"
    assert context["previous_week"] == "2026-06-29"
    assert context["next_week"] == "2026-07-13"
    assert len(context["days"]) == 7
    assert context["meal_count"] == 0

    meal = meal_plan_service.add_meal({
        "date": "2026-07-10",
        "meal_type": "dinner",
        "recipe_url": "recipe://pasta",
        "recipe_name": "Friday Pasta",
    })

    updated = meal_plan_service.meal_plan_for_week("2026-07-10")
    assert updated["meal_count"] == 1
    assert updated["unique_recipe_count"] == 1
    assert updated["meals_by_day"]["2026-07-10"]["dinner"][0]["id"] == meal["id"]
    assert meal_plan_service.delete_meal(meal["id"]) is True
    assert meal_plan_service.meal_plan_for_week("2026-07-10")["meal_count"] == 0


def test_meal_plan_rejects_invalid_and_duplicate_entries(isolated_meal_plan):
    with pytest.raises(ValueError, match="valid date"):
        meal_plan_service.add_meal({"date": "bad", "meal_type": "dinner"})

    payload = {
        "date": date(2026, 7, 10).isoformat(),
        "meal_type": "lunch",
        "recipe_url": "recipe://salad",
        "recipe_name": "Salad",
    }
    meal_plan_service.add_meal(payload)
    with pytest.raises(ValueError, match="already planned"):
        meal_plan_service.add_meal(payload)


def test_meal_plan_routes_create_and_delete_real_entries(monkeypatch, isolated_meal_plan):
    from PushShoppingList.app import create_app
    from PushShoppingList.routes import main_routes

    users = load_users().get("users", [])
    assert users
    user_id = users[0]["user_id"]
    monkeypatch.setattr(
        main_routes,
        "recipe_url_rows",
        lambda: [{"url": "recipe://soup", "name": "Weeknight Soup"}],
    )

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = user_id

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://soup",
        })
        assert response.status_code == 201
        meal_id = response.get_json()["meal"]["id"]

        response = client.delete(f"/api/meal-plan/{meal_id}")
        assert response.status_code == 200
        assert response.get_json() == {"ok": True}


def test_desktop_workspace_wires_meal_planner_and_sidebar_controls():
    workspaces = read_text("PushShoppingList/templates/sections/app_workspaces.html")
    index = read_text("PushShoppingList/templates/index.html")
    script = read_text("PushShoppingList/static/js/app.js")

    assert 'id="mealPlannerPage"' in workspaces
    assert 'id="mealPlannerDialog"' in workspaces
    assert 'id="mealPlannerDeleteDialog"' in workspaces
    assert 'onclick="return openMealPlannerDialog()"' in workspaces
    assert 'onsubmit="return submitMealPlannerForm(event)"' in workspaces
    assert 'onsubmit="return confirmMealPlannerDelete(event)"' in workspaces
    assert 'data-app-page-target="mealPlannerPage"' in index
    assert "data-app-sidebar-collapse" in index
    assert 'mealPlannerPage: "mealPlannerPage"' in script
    assert "function setAppSidebarCollapsed" in script
    assert "async function submitMealPlannerForm" in script
    assert "async function confirmMealPlannerDelete" in script


def test_guest_pantry_fragment_uses_expected_lazy_root():
    template = read_text("PushShoppingList/templates/sections/guest_ai_pantry.html")
    assert 'id="aiPantrySection"' in template
    assert "data-ai-pantry-panel" in template


def test_desktop_workspace_does_not_present_mock_only_controls_as_buttons():
    workspaces = read_text("PushShoppingList/templates/sections/app_workspaces.html")

    for mock_only_button in (
        '<button type="button" class="is-active" aria-pressed="true">All Recipes',
        '<button type="button" class="is-active">All Cookbooks',
        '<button type="button" class="is-active" aria-pressed="true">Current List',
        'aria-label="Grid view"',
        '<th>Favorite</th>',
        '<span>3 unread</span>',
    ):
        assert mock_only_button not in workspaces

    assert '<h3>Use Soon</h3>' in workspaces
    assert "pantry_use_soon_items" in workspaces
    assert "cookbook.recipe_count" in workspaces


def test_desktop_action_inventory_covers_new_write_paths():
    inventory = read_text("docs/desktop-redesign-action-inventory.md")

    assert "POST /api/meal-plan" in inventory
    assert "DELETE /api/meal-plan/<id>" in inventory
    assert "confirmation modal" in inventory
    assert "Controls intentionally represented as labels" in inventory
