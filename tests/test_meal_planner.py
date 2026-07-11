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
        "planned_servings": 4,
    }
    meal_plan_service.add_meal(payload)
    with pytest.raises(ValueError, match="already planned"):
        meal_plan_service.add_meal(dict(payload, planned_servings=8))
    assert meal_plan_service.load_meal_plan()["meals"][0]["planned_servings"] == 4

    same_recipe_another_slot = dict(payload, meal_type="dinner")
    same_recipe_another_day = dict(payload, date="2026-07-11")
    assert meal_plan_service.add_meal(same_recipe_another_slot)["meal_type"] == "dinner"
    assert meal_plan_service.add_meal(same_recipe_another_day)["date"] == "2026-07-11"


def test_meal_plan_persists_numeric_and_fractional_planned_servings(isolated_meal_plan):
    fractional = meal_plan_service.add_meal({
        "date": "2026-07-06",
        "meal_type": "breakfast",
        "recipe_url": "recipe://toast",
        "recipe_name": "Toast",
        "planned_servings": "2.5",
    })
    whole = meal_plan_service.add_meal({
        "date": "2026-07-06",
        "meal_type": "lunch",
        "recipe_url": "recipe://soup",
        "recipe_name": "Soup",
        "planned_servings": "4",
    })

    assert fractional["planned_servings"] == 2.5
    assert whole["planned_servings"] == 4
    raw_meals = json.loads(isolated_meal_plan.read_text(encoding="utf-8"))["meals"]
    assert [meal["planned_servings"] for meal in raw_meals] == [2.5, 4]
    reloaded = meal_plan_service.meal_plan_for_week("2026-07-06")["meals_by_day"]["2026-07-06"]
    assert reloaded["breakfast"][0]["planned_servings"] == 2.5
    assert reloaded["lunch"][0]["planned_servings"] == 4


@pytest.mark.parametrize("planned_servings", [0, -1, "", "many", True, float("nan"), float("inf")])
def test_meal_plan_rejects_invalid_explicit_planned_servings(isolated_meal_plan, planned_servings):
    with pytest.raises(ValueError, match="Planned servings must be a number of 1 or more"):
        meal_plan_service.add_meal({
            "date": "2026-07-06",
            "meal_type": "breakfast",
            "recipe_url": "recipe://toast",
            "recipe_name": "Toast",
            "planned_servings": planned_servings,
        })


@pytest.mark.parametrize(
    ("recipe_yield", "expected_count", "expected_label"),
    [
        ("8 servings", 8, "8 servings"),
        (2.5, 2.5, "2.5 servings"),
        ("Makes 1 1/2 servings", 1.5, "Makes 1 1/2 servings"),
        ("unknown", None, "unknown"),
        (None, None, ""),
    ],
)
def test_meal_plan_recipe_yield_parsing(recipe_yield, expected_count, expected_label):
    assert meal_plan_service.planned_servings_from_yield(recipe_yield) == expected_count
    assert meal_plan_service.meal_plan_yield_label(recipe_yield) == expected_label


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
        reference_date="2026-07-06",
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


def test_home_preview_formats_relative_and_exact_local_dates():
    meal_plan = {
        "meals": [
            {
                "date": planned_date,
                "meal_type": "breakfast",
                "recipe_url": f"recipe://date-{index}",
                "recipe_name": f"Date Recipe {index}",
            }
            for index, planned_date in enumerate(
                ("2026-07-11", "2026-07-12", "2026-07-13")
            )
        ],
    }

    preview = meal_plan_service.meal_plan_home_preview(
        meal_plan,
        reference_date="2026-07-11",
        max_slots=10,
        max_recipes=10,
    )

    assert [
        (slot["day_label"], slot["date_label"])
        for slot in preview["slots"]
    ] == [
        ("TODAY", "Sat, Jul 11"),
        ("TOMORROW", "Sun, Jul 12"),
        ("MON", "Jul 13"),
    ]

    shifted_preview = meal_plan_service.meal_plan_home_preview(
        meal_plan,
        reference_date="2026-07-12",
        max_slots=10,
        max_recipes=10,
    )
    assert [
        (slot["date"], slot["day_label"], slot["date_label"])
        for slot in shifted_preview["slots"]
    ] == [
        ("2026-07-12", "TODAY", "Sun, Jul 12"),
        ("2026-07-13", "TOMORROW", "Mon, Jul 13"),
    ]


def test_home_preview_filters_past_and_orders_all_upcoming_meals(isolated_meal_plan):
    stored_meals = [
        ("2026-07-11", "snack", "Future Snack"),
        ("2026-07-09", "lunch", "Lunch B"),
        ("2026-07-08", "dinner", "Past Dinner"),
        ("2026-07-09", "dinner", "Today Dinner"),
        ("2026-07-09", "breakfast", "Today Breakfast"),
        ("2026-07-10", "breakfast", "Future Breakfast"),
        ("2026-07-09", "lunch", "Lunch A"),
    ]
    for index, (planned_date, meal_type, recipe_name) in enumerate(stored_meals):
        meal_plan_service.add_meal({
            "date": planned_date,
            "meal_type": meal_type,
            "recipe_url": f"recipe://ordered-{index}",
            "recipe_name": recipe_name,
        })

    stored_before = isolated_meal_plan.read_bytes()
    preview = meal_plan_service.meal_plan_home_preview(
        reference_date="2026-07-09",
        max_slots=10,
        max_recipes_per_slot=10,
        max_recipes=20,
    )

    assert [(slot["date"], slot["meal_type"]) for slot in preview["slots"]] == [
        ("2026-07-09", "breakfast"),
        ("2026-07-09", "lunch"),
        ("2026-07-09", "dinner"),
        ("2026-07-10", "breakfast"),
        ("2026-07-11", "snack"),
    ]
    assert preview["slots"][0]["day_label"] == "TODAY"
    assert preview["slots"][0]["date_label"] == "Thu, Jul 9"
    assert preview["slots"][3]["day_label"] == "TOMORROW"
    assert preview["slots"][3]["date_label"] == "Fri, Jul 10"
    assert preview["slots"][4]["day_label"] == "SAT"
    assert preview["slots"][4]["date_label"] == "Jul 11"
    assert [meal["recipe_name"] for meal in preview["slots"][1]["meals"]] == [
        "Lunch B",
        "Lunch A",
    ]
    assert all(
        meal["recipe_name"] != "Past Dinner"
        for slot in preview["slots"]
        for meal in slot["meals"]
    )
    assert preview["hidden_meal_count"] == 0
    assert isolated_meal_plan.read_bytes() == stored_before


def test_home_preview_ignores_past_meals_in_empty_and_overflow_counts(isolated_meal_plan):
    for index in range(3):
        meal_plan_service.add_meal({
            "date": "2026-07-08",
            "meal_type": "dinner",
            "recipe_url": f"recipe://past-{index}",
            "recipe_name": f"Past {index}",
        })

    preview = meal_plan_service.meal_plan_home_preview(reference_date="2026-07-09")

    assert preview == {
        "slots": [],
        "visible_recipe_count": 0,
        "hidden_meal_count": 0,
        "hidden_slot_count": 0,
    }
    assert len(meal_plan_service.load_meal_plan()["meals"]) == 3


def test_full_week_keeps_past_meals_and_marks_local_date_states(isolated_meal_plan):
    meal_plan_service.add_meal({
        "date": "2026-07-07",
        "meal_type": "dinner",
        "recipe_url": "recipe://past-pasta",
        "recipe_name": "Past Pasta",
    })

    context = meal_plan_service.meal_plan_for_week(
        "2026-07-06",
        reference_date="2026-07-09",
    )

    assert len(context["days"]) == 7
    assert [day["is_past"] for day in context["days"]] == [
        True, True, True, False, False, False, False,
    ]
    assert [day["is_today"] for day in context["days"]] == [
        False, False, False, True, False, False, False,
    ]
    assert context["today_week"] == "2026-07-06"
    assert context["meals_by_day"]["2026-07-07"]["dinner"][0]["recipe_name"] == "Past Pasta"


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
    assert "planned_servings" not in slot[0]


def test_meal_plan_recipe_options_use_saved_default_yield(monkeypatch):
    from PushShoppingList.routes import main_routes

    saved = {
        "recipe://family": {"servings": "8 servings"},
        "recipe://fractional": {"servings": 2.5},
        "recipe://scaled": {"scaling": {"base_servings": "3 1/2 servings"}},
        "recipe://unknown": {},
    }
    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda recipe_url: saved[recipe_url])
    options = main_routes.meal_plan_recipe_option_rows([
        {"url": recipe_url, "name": recipe_url.rsplit("/", 1)[-1].title()}
        for recipe_url in saved
    ], recipe_ingredient_data={})

    assert [option["default_servings"] for option in options] == [8, 2.5, 3.5, 1]
    assert [option["yield_label"] for option in options] == [
        "8 servings",
        "2.5 servings",
        "3 1/2 servings",
        "",
    ]


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

    def fake_saved_recipe_output(recipe_url):
        if recipe_url == "recipe://soup":
            return {"servings": "8 servings"}
        if recipe_url == "recipe://salad":
            return {"servings": "2.5 servings"}
        return {}

    monkeypatch.setattr(
        main_routes,
        "recipe_url_rows",
        lambda: recipe_rows,
    )
    monkeypatch.setattr(main_routes, "recipe_url_log_rows", fake_recipe_url_log_rows)
    monkeypatch.setattr(main_routes, "load_saved_recipe_output", fake_saved_recipe_output)
    monkeypatch.setattr(main_routes, "request_local_calendar_date", lambda: date(2026, 7, 10))

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
        soup_meal = response.get_json()["meal"]
        soup_id = soup_meal["id"]
        assert soup_meal["planned_servings"] == 8

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://filler-0",
            "planned_servings": 0,
        })
        assert response.status_code == 400
        assert "Planned servings" in response.get_json()["error"]

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://salad",
            "planned_servings": "2.5",
        })
        assert response.status_code == 201
        salad_meal = response.get_json()["meal"]
        salad_id = salad_meal["id"]
        assert salad_meal["planned_servings"] == 2.5

        response = client.post("/api/meal-plan", json={
            "date": "2026-07-10",
            "meal_type": "dinner",
            "recipe_url": "recipe://soup",
            "planned_servings": 4,
        })
        assert response.status_code == 400
        assert "already planned" in response.get_json()["error"]

        meal_plan_service.add_meal({
            "date": "2026-07-09",
            "meal_type": "breakfast",
            "recipe_url": "recipe://filler-1",
            "recipe_name": "Past Filler",
        })
        meal_plan_service.add_meal({
            "date": "2026-07-13",
            "meal_type": "snack",
            "recipe_url": "recipe://filler-0",
            "recipe_name": "Future Filler",
        })

        planned = meal_plan_service.meal_plan_for_week("2026-07-10")["meals_by_day"]["2026-07-10"]["dinner"]
        assert [meal["id"] for meal in planned] == [soup_id, salad_id]
        assert [meal["planned_servings"] for meal in planned] == [8, 2.5]

        page = client.get("/?meal_week=2026-07-10")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        preview_start = html.index('aria-label="Upcoming meal plan"')
        preview_end = html.index("</section>", preview_start)
        preview_html = html[preview_start:preview_end]
        assert preview_html.count('class="app-home-meal-slot"') == 2
        assert "Weeknight Soup" in preview_html
        assert "Side Salad" in preview_html
        assert "Future Filler" in preview_html
        assert "Past Filler" not in preview_html
        assert '<span class="app-home-meal-day-primary">TODAY</span>' in preview_html
        assert '<span class="app-home-meal-date-exact">Fri, Jul 10</span>' in preview_html
        assert '<span class="app-home-meal-day-primary">MON</span>' in preview_html
        assert '<span class="app-home-meal-date-exact">Jul 13</span>' in preview_html
        assert ">View planner</a>" in preview_html
        assert "View full meal plan" in preview_html
        assert "/static/test/weeknight-soup.jpg" in preview_html
        assert "/static/test/side-salad.jpg" in preview_html
        assert 'class="app-meal-planner-day is-past"' in html
        assert 'class="app-meal-planner-day is-today" aria-current="date"' in html
        assert 'class="app-meal-planner-cell is-past"' in html
        assert 'class="app-meal-planner-cell is-today"' in html
        assert "Past Filler" in html
        assert "openMealPlannerDialog('2026-07-09', 'breakfast')" in html
        assert 'data-meal-name="Past Filler"' in html
        soup_option_start = html.index('<option value="recipe://soup"')
        salad_option_start = html.index('<option value="recipe://salad"')
        soup_option = html[soup_option_start:html.index("</option>", soup_option_start)]
        salad_option = html[salad_option_start:html.index("</option>", salad_option_start)]
        assert 'data-default-servings="8"' in soup_option
        assert 'data-yield-label="8 servings"' in soup_option
        assert 'data-default-servings="2.5"' in salad_option
        assert 'data-yield-label="2.5 servings"' in salad_option
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
    assert 'app-meal-planner-day{% if day.is_past %} is-past{% endif %}{% if day.is_today %} is-today{% endif %}' in workspaces
    assert 'app-meal-planner-cell{% if day.is_past %} is-past{% endif %}{% if day.is_today %} is-today{% endif %}' in workspaces
    assert 'aria-current="date"' in workspaces
    assert "meal_plan.previous_week" in workspaces
    assert "meal_plan.next_week" in workspaces
    assert ">Today</a>" in workspaces
    assert 'class="app-meal-add-slot{% if planned_meals %} has-meals{% endif %}"' in workspaces
    assert '<span class="app-meal-add-slot-label">Add recipe</span>' in workspaces
    card_loop = workspaces.index("{% for meal in planned_meals %}")
    add_action = workspaces.index('class="app-meal-add-slot', card_loop)
    assert workspaces.index("{% endfor %}", card_loop) < add_action
    recipe_field = workspaces.index('<select id="mealPlannerRecipe"')
    servings_field = workspaces.index("Planned Servings")
    assert recipe_field < servings_field
    assert 'data-default-servings="{{ recipe.default_servings }}"' in workspaces
    assert 'data-yield-label="{{ recipe.yield_label }}"' in workspaces
    assert 'name="planned_servings"' in workspaces
    assert 'type="number"' in workspaces
    assert 'min="1"' in workspaces
    assert 'step="any"' in workspaces
    assert 'data-step="0.5"' in workspaces
    assert 'aria-label="Decrease planned servings"' in workspaces
    assert 'aria-label="Increase planned servings"' in workspaces
    assert 'aria-describedby="mealPlannerServingsHelp"' in workspaces
    assert 'data-app-page-target="mealPlannerPage"' in index
    assert "{% for slot in home_meal_plan.slots %}" in index
    assert "{% for meal in slot.meals %}" in index
    assert "slot.remaining_count" in index
    assert 'class="app-home-meal-day-primary"' in index
    assert 'class="app-home-meal-date-exact"' in index
    assert "slot.date_label" in index
    assert 'class="app-home-meal-recipe"' in index
    assert 'onclick="return openHomeMealPlanSlot(this, event)"' in index
    assert "data-app-sidebar-collapse" in index
    assert 'mealPlannerPage: "mealPlannerPage"' in script
    assert "function setAppSidebarCollapsed" in script
    assert "async function submitMealPlannerForm" in script
    assert "async function confirmMealPlannerDelete" in script
    assert "function openHomeMealPlanSlot" in script
    assert "function handleHomeMealPlanSlotKeydown" in script
    assert "function syncMealPlannerServingsFromRecipe" in script
    assert "function adjustMealPlannerServings" in script
    assert "function updateMealPlannerServingControls" in script
    assert "Recipe yields ${yieldLabel}." in script
    assert "planned_servings: plannedServings" in script


def test_homepage_syncs_browser_local_calendar_date_without_utc_conversion():
    index = read_text("PushShoppingList/templates/index.html")

    assert 'var cookieName = "ai_pantry_local_date";' in index
    assert "now.getFullYear()" in index
    assert "now.getMonth() + 1" in index
    assert "now.getDate()" in index
    assert "toISOString()" not in index
    assert "SameSite=Lax" in index
    assert "window.location.reload();" in index


def test_request_local_calendar_date_uses_browser_cookie():
    from flask import Flask
    from PushShoppingList.routes import main_routes

    app = Flask(__name__)
    with app.test_request_context(
        "/",
        headers={"Cookie": "ai_pantry_local_date=2026-07-09"},
    ):
        assert main_routes.request_local_calendar_date() == date(2026, 7, 9)


def test_meal_plan_styles_compact_multiple_items_and_keep_mobile_contained():
    css = read_text("PushShoppingList/static/css/app.css")
    route = read_text("PushShoppingList/routes/main_routes.py")

    assert ".app-meal-slot-recipes {\n    display: grid;\n    gap: 6px;" in css
    assert ".app-meal-planner-cell .app-meal-card {" in css
    assert "height: auto;" in css
    assert ".app-meal-planner-cell .app-meal-add-slot {" in css
    assert ".app-meal-planner-day.is-past," in css
    assert ".app-meal-planner-cell.is-past {" in css
    assert ".app-meal-planner-cell.is-today {" in css
    assert ".app-meal-planner-servings-stepper {" in css
    assert ".app-dialog-helper {" in css
    assert ".app-home-meal-list > .app-home-meal-slot {" in css
    assert "grid-template-columns: 140px minmax(0, 1fr);" in css
    assert "grid-template-columns: 64px minmax(0, 1fr);" in css
    assert ".app-home-meal-slot .app-home-meal-date-exact {" in css
    assert ".app-home-meal-recipes {\n    display: grid;" in css
    assert "grid-template-columns: minmax(0, 1fr) 46px;" in css
    assert "max-width: 100%;" in css
    assert "overflow-x: auto;" in css
    assert "planned_recipe_rows = [" in route
    assert "planned_preview_rows = (" in route
    assert "recipe_url_log_rows(" in route
    assert "home_meal_plan = meal_plan_home_preview(reference_date=local_calendar_date)" in route
    assert 'for meal in [*meal_plan["meals"], *home_preview_meals]' in route
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
