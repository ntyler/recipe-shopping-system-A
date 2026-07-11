from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
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

    same_recipe_another_slot = dict(payload, meal_type="dinner")
    same_recipe_another_day = dict(payload, date="2026-07-11")
    assert meal_plan_service.add_meal(same_recipe_another_slot)["meal_type"] == "dinner"
    assert meal_plan_service.add_meal(same_recipe_another_day)["date"] == "2026-07-11"


def test_meal_plan_appends_multiple_recipes_and_removes_only_one(isolated_meal_plan):
    recipes = [
        ("recipe://papa", "Papa a la Huancaina"),
        ("recipe://yuca", "Yuca la Huancaina"),
        ("recipe://fruit", "Fruit Salad"),
    ]
    added = [
        meal_plan_service.add_meal({
            "date": "2026-07-06",
            "meal_type": "breakfast",
            "recipe_url": recipe_url,
            "recipe_name": recipe_name,
        })
        for recipe_url, recipe_name in recipes
    ]

    context = meal_plan_service.meal_plan_for_week("2026-07-06")
    slot = context["meals_by_day"]["2026-07-06"]["breakfast"]
    assert [meal["id"] for meal in slot] == [meal["id"] for meal in added]
    assert [meal["recipe_name"] for meal in slot] == [name for _, name in recipes]
    assert len(json.loads(isolated_meal_plan.read_text(encoding="utf-8"))["meals"]) == 3

    assert meal_plan_service.delete_meal(added[1]["id"]) is True
    remaining = meal_plan_service.meal_plan_for_week("2026-07-06")["meals_by_day"]["2026-07-06"]["breakfast"]
    assert [meal["id"] for meal in remaining] == [added[0]["id"], added[2]["id"]]


def test_meal_plan_home_preview_groups_slots_and_caps_visible_recipes(isolated_meal_plan):
    for suffix in ("papa", "yuca", "fruit"):
        meal_plan_service.add_meal({
            "date": "2026-07-06",
            "meal_type": "breakfast",
            "recipe_url": f"recipe://{suffix}",
            "recipe_name": suffix.title(),
        })
    meal_plan_service.add_meal({
        "date": "2026-07-06",
        "meal_type": "lunch",
        "recipe_url": "recipe://soup",
        "recipe_name": "Soup",
    })
    meal_plan_service.add_meal({
        "date": "2026-07-07",
        "meal_type": "dinner",
        "recipe_url": "recipe://pasta",
        "recipe_name": "Pasta",
    })

    preview = meal_plan_service.meal_plan_home_preview(
        meal_plan_service.meal_plan_for_week("2026-07-06"),
        max_slots=2,
        max_recipes_per_slot=2,
        max_recipes=3,
    )

    assert [(slot["date"], slot["meal_type"]) for slot in preview["slots"]] == [
        ("2026-07-06", "breakfast"),
        ("2026-07-06", "lunch"),
    ]
    assert [meal["recipe_name"] for meal in preview["slots"][0]["meals"]] == ["Papa", "Yuca"]
    assert preview["slots"][0]["remaining_count"] == 1
    assert preview["slots"][1]["remaining_count"] == 0
    assert preview["hidden_slot_count"] == 1
    assert preview["hidden_meal_count"] == 1


def test_meal_plan_atomic_adds_preserve_concurrent_assignments(isolated_meal_plan):
    def add_recipe(index):
        return meal_plan_service.add_meal({
            "date": "2026-07-06",
            "meal_type": "snack",
            "recipe_url": f"recipe://snack-{index}",
            "recipe_name": f"Snack {index}",
        })

    with ThreadPoolExecutor(max_workers=6) as executor:
        added = list(executor.map(add_recipe, range(6)))

    slot = meal_plan_service.meal_plan_for_week("2026-07-06")["meals_by_day"]["2026-07-06"]["snack"]
    assert {meal["id"] for meal in slot} == {meal["id"] for meal in added}
    assert len(slot) == 6


def test_legacy_single_recipe_record_remains_readable(isolated_meal_plan):
    isolated_meal_plan.write_text(json.dumps({
        "meals": [{
            "date": "2026-07-06",
            "meal_type": "breakfast",
            "recipe_url": "recipe://legacy",
            "recipe_name": "Legacy Breakfast",
        }],
    }), encoding="utf-8")

    slot = meal_plan_service.meal_plan_for_week("2026-07-06")["meals_by_day"]["2026-07-06"]["breakfast"]
    assert len(slot) == 1
    assert slot[0]["recipe_name"] == "Legacy Breakfast"
    assert slot[0]["id"]


def test_meal_plan_routes_create_and_delete_real_entries(monkeypatch, isolated_meal_plan):
    from PushShoppingList.app import create_app
    from PushShoppingList.routes import main_routes

    users = load_users().get("users", [])
    assert users
    user_id = users[0]["user_id"]
    recipe_rows = [
        {"url": f"recipe://filler-{index}", "name": f"Filler {index}"}
        for index in range(8)
    ] + [
        {"url": "recipe://soup", "name": "Weeknight Soup"},
        {"url": "recipe://salad", "name": "Side Salad"},
    ]
    preview_batches = []

    def fake_recipe_url_log_rows(rows, *args, **kwargs):
        rows = list(rows)
        preview_batches.append([row["url"] for row in rows])
        return [
            {
                **row,
                "cover_image": {
                    "src": f"/static/test/{row['name'].lower().replace(' ', '-')}.jpg",
                },
            }
            for row in rows
        ]

    monkeypatch.setattr(
        main_routes,
        "recipe_url_rows",
        lambda: recipe_rows,
    )
    monkeypatch.setattr(main_routes, "recipe_url_log_rows", fake_recipe_url_log_rows)

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
        soup_id = response.get_json()["meal"]["id"]

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://salad",
        })
        assert response.status_code == 201
        salad_id = response.get_json()["meal"]["id"]

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://soup",
        })
        assert response.status_code == 400
        assert "already planned" in response.get_json()["error"]

        planned = meal_plan_service.meal_plan_for_week("2026-07-10")["meals_by_day"]["2026-07-10"]["dinner"]
        assert [meal["id"] for meal in planned] == [soup_id, salad_id]

        page = client.get("/?meal_week=2026-07-10")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        preview_start = html.index('aria-label="Upcoming meal plan"')
        preview_end = html.index("</section>", preview_start)
        preview_html = html[preview_start:preview_end]
        assert preview_html.count('class="app-home-meal-slot"') == 1
        assert "Weeknight Soup" in preview_html
        assert "Side Salad" in preview_html
        assert "/static/test/weeknight-soup.jpg" in preview_html
        assert "/static/test/side-salad.jpg" in preview_html
        assert preview_batches[0] == [f"recipe://filler-{index}" for index in range(8)]
        assert preview_batches[1] == ["recipe://soup", "recipe://salad"]

        response = client.delete(f"/api/meal-plan/{soup_id}")
        assert response.status_code == 200
        assert response.get_json() == {"ok": True}
        remaining = meal_plan_service.meal_plan_for_week("2026-07-10")["meals_by_day"]["2026-07-10"]["dinner"]
        assert [meal["id"] for meal in remaining] == [salad_id]


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
    assert 'class="app-meal-slot-recipes"' in workspaces
    assert 'class="app-meal-add-slot{% if planned_meals %} has-meals{% endif %}"' in workspaces
    assert '<span class="app-meal-add-slot-label">Add recipe</span>' in workspaces
    card_loop = workspaces.index("{% for meal in planned_meals %}")
    add_action = workspaces.index('class="app-meal-add-slot', card_loop)
    assert workspaces.index("{% endfor %}", card_loop) < add_action
    assert 'data-app-page-target="mealPlannerPage"' in index
    assert "{% for slot in home_meal_plan.slots %}" in index
    assert "{% for meal in slot.meals %}" in index
    assert "slot.remaining_count" in index
    assert 'class="app-home-meal-recipe"' in index
    assert 'onclick="return openHomeMealPlanSlot(this, event)"' in index
    assert "data-app-sidebar-collapse" in index
    assert 'mealPlannerPage: "mealPlannerPage"' in script
    assert "function setAppSidebarCollapsed" in script
    assert "async function submitMealPlannerForm" in script
    assert "async function confirmMealPlannerDelete" in script
    assert "function openHomeMealPlanSlot" in script
    assert "function handleHomeMealPlanSlotKeydown" in script


def test_meal_plan_styles_compact_multiple_items_and_keep_mobile_contained():
    css = read_text("PushShoppingList/static/css/app.css")
    route = read_text("PushShoppingList/routes/main_routes.py")

    assert ".app-meal-slot-recipes {\n    display: grid;\n    gap: 6px;" in css
    assert ".app-meal-planner-cell .app-meal-card {" in css
    assert "height: auto;" in css
    assert ".app-meal-planner-cell .app-meal-add-slot {" in css
    assert ".app-home-meal-list > .app-home-meal-slot {" in css
    assert ".app-home-meal-recipes {\n    display: grid;" in css
    assert "grid-template-columns: minmax(0, 1fr) 46px;" in css
    assert "max-width: 100%;" in css
    assert "overflow-x: auto;" in css
    assert "planned_recipe_rows = [" in route
    assert "planned_preview_rows = (" in route
    assert "recipe_url_log_rows(" in route
    assert '"home_meal_plan": home_meal_plan' in route


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
