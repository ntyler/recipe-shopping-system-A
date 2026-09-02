from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading

from flask import Flask, g
import pytest

from PushShoppingList.services import nutrition_tracking_service as nutrition
from PushShoppingList.services import storage_service


NOW = datetime(2026, 7, 10, 18, 30, tzinfo=timezone.utc)
TODAY = "2026-07-10"


@pytest.fixture
def isolated_nutrition(monkeypatch, tmp_path):
    target = tmp_path / "nutrition_tracking.json"
    lock = threading.RLock()
    acquisitions = []

    @contextmanager
    def isolated_workspace_lock(name="nutrition", timeout_seconds=None):
        assert name == "nutrition"
        with lock:
            acquisitions.append(name)
            yield tmp_path / ".nutrition-lock"

    monkeypatch.setattr(nutrition, "NUTRITION_FILE", target)
    monkeypatch.setattr(nutrition, "workspace_write_lock", isolated_workspace_lock)
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    return target, acquisitions


def meal_payload(**changes):
    payload = {
        "local_date": TODAY,
        "meal_type": "breakfast",
        "description": "Oatmeal and berries",
        "local_time": "08:15",
        "timezone": "America/Indiana/Indianapolis",
        "timezone_offset_minutes": 240,
        "food_items": [
            {
                "name": "Oatmeal",
                "quantity": 1,
                "unit": "bowl",
                "nutrition_per_unit": {
                    "calories": 250,
                    "protein": 8,
                    "carbohydrates": 45,
                    "fat": 4,
                    "fiber": 5,
                    "sugar": 7,
                    "sodium": 180,
                },
            }
        ],
    }
    payload.update(changes)
    return payload


def test_versioned_document_persists_date_indexes_and_uses_workspace_lock(
    isolated_nutrition,
):
    target, acquisitions = isolated_nutrition
    later = nutrition.create_meal(
        meal_payload(local_time="09:00"), now=NOW, reference_date=TODAY
    )
    earlier = nutrition.create_meal(
        meal_payload(
            description="Early toast",
            local_time="07:00",
            meal_type="snack",
        ),
        now=NOW,
        reference_date=TODAY,
    )
    water = nutrition.create_water_entry(
        {
            "local_date": TODAY,
            "amount": 8,
            "unit": "fl oz",
            "local_time": "07:30",
        },
        now=NOW,
        reference_date=TODAY,
    )

    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["schema_version"] == nutrition.SCHEMA_VERSION
    assert raw["meal_ids_by_date"][TODAY] == [earlier["id"], later["id"]]
    assert raw["water_entry_ids_by_date"][TODAY] == [water["id"]]
    assert set(raw["meals"]) == {earlier["id"], later["id"]}
    assert acquisitions == ["nutrition", "nutrition", "nutrition"]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"meal_type": ""}, "meal_type"),
        ({"local_date": "not-a-date"}, "date"),
        ({"local_date": "2026-07-11"}, "date"),
        ({"description": "", "food_items": []}, "meal_source"),
        ({"description": "x" * 201}, "description"),
        (
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "quantity": 0,
                        "nutrition_per_unit": {"calories": 100},
                    }
                ]
            },
            "Food quantity",
        ),
        (
            {
                "food_items": [
                    {
                        "name": "Toast",
                        "quantity": 1,
                        "nutrition_per_unit": {"calories": -1},
                    }
                ]
            },
            "calories",
        ),
    ],
)
def test_meal_validation_is_explicit(isolated_nutrition, changes, field):
    with pytest.raises(nutrition.NutritionValidationError) as caught:
        nutrition.create_meal(
            meal_payload(**changes), now=NOW, reference_date=TODAY
        )
    assert caught.value.field == field
    assert field in caught.value.field_errors


def test_description_accepts_exact_limit_and_never_truncates(isolated_nutrition):
    description = "x" * nutrition.MAX_DESCRIPTION_LENGTH
    meal = nutrition.create_meal(
        meal_payload(description=description, food_items=[]),
        now=NOW,
        reference_date=TODAY,
    )
    assert meal["description"] == description


def test_food_items_recalculate_totals_and_meal_crud_repairs_indexes(
    isolated_nutrition,
):
    meal = nutrition.create_meal(
        meal_payload(
            food_items=[
                {
                    "name": "Toast",
                    "quantity": 2,
                    "unit": "slice",
                    "nutrition_per_unit": {"calories": 100, "protein": 3},
                },
                {
                    "name": "Jam",
                    "quantity": 1,
                    "unit": "tbsp",
                    "nutrition": {"calories": 50, "sugar": 0},
                },
            ],
            nutrition={"calories": 9999},
        ),
        now=NOW,
        reference_date=TODAY,
    )

    assert meal["nutrition"] == {
        "calories": 250,
        "protein": 6,
        "sugar": 0,
    }
    assert meal["nutrition_status"]["calories"] == "complete"
    assert meal["nutrition_status"]["protein"] == "partial"
    assert meal["nutrition_status"]["fiber"] == "missing"

    updated = nutrition.update_meal(
        meal["id"],
        {
            "date": "2026-07-09",
            "meal_name": "Updated toast",
            "meal_type": "lunch",
            "food_items": [
                {
                    "name": "Toast",
                    "quantity": 3,
                    "unit": "slice",
                    "nutrition_per_unit": {"calories": 100, "protein": 3},
                }
            ],
        },
        now=NOW,
        reference_date=TODAY,
    )
    assert updated["nutrition"]["calories"] == 300
    assert updated["name"] == "Updated toast"
    assert nutrition.list_meals(TODAY) == []
    assert [row["id"] for row in nutrition.list_meals("2026-07-09", "lunch")] == [
        meal["id"]
    ]
    assert nutrition.delete_meal(meal["id"], now=NOW) is True
    assert nutrition.delete_meal(meal["id"], now=NOW) is False


def test_food_item_serving_aliases_scale_from_per_serving_values(isolated_nutrition):
    meal = nutrition.create_meal(
        meal_payload(
            food_items=[
                {
                    "name": "Tacos",
                    "serving_amount": 3,
                    "serving_unit": "taco",
                    "nutrition_per_serving": {"calories": 150, "protein": 6},
                }
            ]
        ),
        now=NOW,
        reference_date=TODAY,
    )
    assert meal["food_items"][0]["quantity"] == 3
    assert meal["food_items"][0]["unit"] == "taco"
    assert meal["nutrition"] == {"calories": 450, "protein": 18}


def test_create_idempotency_prevents_duplicate_and_conflicting_submissions(
    isolated_nutrition,
):
    payload = meal_payload(client_request_id="meal-request-1")
    first = nutrition.create_meal(payload, now=NOW, reference_date=TODAY)
    repeated = nutrition.create_meal(payload, now=NOW, reference_date=TODAY)

    assert repeated == first
    assert len(nutrition.list_meals(TODAY)) == 1
    with pytest.raises(nutrition.NutritionConflictError):
        nutrition.create_meal(
            {**payload, "meal_type": "dinner"}, now=NOW, reference_date=TODAY
        )


def test_concurrent_creates_are_not_lost(isolated_nutrition):
    def add(index):
        return nutrition.create_meal(
            meal_payload(
                description=f"Snack {index}",
                meal_type="snack",
                local_time=f"{10 + index:02d}:00",
                client_request_id=f"snack-{index}",
            ),
            now=NOW,
            reference_date=TODAY,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        created = list(executor.map(add, range(6)))

    stored = nutrition.list_meals(TODAY, "snacks")
    assert {meal["id"] for meal in stored} == {meal["id"] for meal in created}
    assert len(stored) == 6


def test_saved_meal_reuse_is_a_snapshot_independent_of_template_changes(
    isolated_nutrition,
):
    original = nutrition.create_meal(
        meal_payload(servings=2), now=NOW, reference_date=TODAY
    )
    template = nutrition.create_saved_meal_from_meal(
        original["id"], "Morning oats", base_servings=2, now=NOW
    )
    reused = nutrition.reuse_saved_meal(
        template["id"],
        local_date="2026-07-09",
        meal_type="snack",
        servings=4,
        client_request_id="reuse-1",
        now=NOW,
        reference_date=TODAY,
    )
    repeated = nutrition.reuse_saved_meal(
        template["id"],
        local_date="2026-07-09",
        meal_type="snack",
        servings=4,
        client_request_id="reuse-1",
        now=NOW,
        reference_date=TODAY,
    )

    assert repeated["id"] == reused["id"]
    assert reused["nutrition"]["calories"] == 500
    assert reused["food_items"][0]["quantity"] == 2
    assert reused["saved_meal_snapshot"]["nutrition"]["calories"] == 500

    nutrition.update_saved_meal(
        template["id"],
        {
            "food_items": [
                {
                    "name": "Revised oats",
                    "quantity": 1,
                    "unit": "bowl",
                    "nutrition_per_unit": {"calories": 700},
                }
            ]
        },
        now=NOW,
    )
    assert nutrition.get_meal(reused["id"])["nutrition"]["calories"] == 500
    assert nutrition.get_meal(original["id"])["nutrition"]["calories"] == 250
    assert nutrition.delete_saved_meal(template["id"], now=NOW) is True
    assert nutrition.get_meal(reused["id"])["saved_meal_snapshot"]["name"] == "Morning oats"


def test_saved_meal_rejects_an_explicit_zero_base_serving(isolated_nutrition):
    original = nutrition.create_meal(
        meal_payload(), now=NOW, reference_date=TODAY
    )
    with pytest.raises(nutrition.NutritionValidationError):
        nutrition.create_saved_meal_from_meal(
            original["id"], "Invalid template", base_servings=0, now=NOW
        )


def test_recipe_snapshot_scales_per_serving_and_whole_recipe_values(
    isolated_nutrition,
):
    recipe = {
        "url": "recipe://soup",
        "name": "Vegetable Soup",
        "servings": "4 servings",
        "nutrition": {
            "serving_basis": "Per serving",
            "calories": "250 kcal",
            "carbs": "30 g",
            "sodium": "600 mg",
        },
    }
    snapshot = nutrition.build_recipe_nutrition_snapshot(recipe, 2)
    assert snapshot["base_servings"] == 4
    assert snapshot["nutrition"] == {
        "calories": 500,
        "carbohydrates": 60,
        "sodium": 1200,
    }

    whole = nutrition.build_recipe_nutrition_snapshot(
        {
            **recipe,
            "nutrition": {
                "serving_basis": "Whole recipe",
                "calories": "1000 calories",
            },
        },
        2,
    )
    assert whole["nutrition_basis"] == "whole_recipe"
    assert whole["nutrition"]["calories"] == 500

    logged = nutrition.create_recipe_meal(
        recipe,
        local_date=TODAY,
        meal_type="dinner",
        selected_servings=2,
        client_request_id="recipe-log-1",
        now=NOW,
        reference_date=TODAY,
    )
    recipe["nutrition"]["calories"] = "9999 kcal"
    assert nutrition.get_meal(logged["id"])["recipe_snapshot"]["nutrition"]["calories"] == 500


def test_recipe_display_units_are_converted_to_canonical_nutrition(
    isolated_nutrition,
):
    snapshot = nutrition.build_recipe_nutrition_snapshot(
        {
            "url": "recipe://units",
            "name": "Unit Soup",
            "nutrition": {
                "serving_basis": "Per serving",
                "calories": "418.4 kJ",
                "protein": "500 mg",
                "sodium": "1.2 g",
            },
        },
        1,
    )
    assert snapshot["nutrition"] == {
        "calories": 100,
        "protein": 0.5,
        "sodium": 1200,
    }


@pytest.mark.parametrize(
    ("amount", "unit"),
    [
        (None, "ml"),
        ("", "ml"),
        (0, "ml"),
        (-1, "ml"),
        ("water", "ml"),
        (10_001, "ml"),
        (400, "fl oz"),
        (8, "cups"),
    ],
)
def test_water_validation_rejects_invalid_values(isolated_nutrition, amount, unit):
    with pytest.raises(nutrition.NutritionValidationError):
        nutrition.create_water_entry(
            {"local_date": TODAY, "amount": amount, "unit": unit},
            now=NOW,
            reference_date=TODAY,
        )


def test_water_conversion_crud_timezone_and_idempotency(isolated_nutrition):
    payload = {
        "local_date": TODAY,
        "amount": 8,
        "unit": "fl oz",
        "local_time": "23:30",
        "occurred_at": "2026-07-11T03:30:00Z",
        "timezone": "America/Indiana/Indianapolis",
        "timezone_offset_minutes": 240,
        "source": "quick_add",
        "client_request_id": "water-1",
    }
    first = nutrition.create_water_entry(payload, now=NOW, reference_date=TODAY)
    repeated = nutrition.create_water_entry(payload, now=NOW, reference_date=TODAY)
    assert repeated["id"] == first["id"]
    assert first["amount_ml"] == pytest.approx(236.588, abs=0.001)
    assert first["local_date"] == TODAY
    assert first["local_time"] == "23:30"

    second = nutrition.create_water_entry(
        {
            "local_date": TODAY,
            "amount": 250,
            "unit": "mL",
            "local_time": "08:00",
        },
        now=NOW,
        reference_date=TODAY,
    )
    assert [entry["id"] for entry in nutrition.list_water_entries(TODAY)] == [
        second["id"],
        first["id"],
    ]

    updated = nutrition.update_water_entry(
        first["id"],
        {
            "amount": 12,
            "unit": "fl_oz",
            "local_time": "09:00",
            "date": "2026-07-09",
        },
        now=NOW,
        reference_date=TODAY,
    )
    assert updated["amount_ml"] == pytest.approx(354.882, abs=0.001)
    assert updated["local_date"] == "2026-07-09"
    assert nutrition.list_water_entries("2026-07-09")[0]["id"] == first["id"]
    assert nutrition.delete_water_entry(second["id"], now=NOW) is True
    assert nutrition.delete_water_entry(second["id"], now=NOW) is False


@pytest.mark.parametrize(
    "metadata",
    [
        {"timezone": "../../etc/passwd"},
        {"timezone_offset_minutes": 841},
        {"timezone_offset_minutes": 1.5},
        {"local_time": "25:00"},
        {"occurred_at": "2026-07-10T12:00:00"},
    ],
)
def test_timezone_metadata_is_validated(isolated_nutrition, metadata):
    with pytest.raises(nutrition.NutritionValidationError):
        nutrition.create_water_entry(
            {
                "local_date": TODAY,
                "amount": 250,
                "unit": "ml",
                **metadata,
            },
            now=NOW,
            reference_date=TODAY,
        )


def test_daily_filters_and_weekly_totals_distinguish_zero_from_missing(
    isolated_nutrition,
):
    nutrition.create_meal(
        meal_payload(
            meal_type="breakfast",
            description="Black coffee",
            food_items=[],
            nutrition={"calories": 0, "sugar": 0},
        ),
        now=NOW,
        reference_date=TODAY,
    )
    nutrition.create_meal(
        meal_payload(
            meal_type="lunch",
            description="Lunch",
            food_items=[],
            nutrition={"calories": 500, "protein": 20},
        ),
        now=NOW,
        reference_date=TODAY,
    )

    all_meals = nutrition.daily_summary(TODAY)
    assert all_meals["nutrition"]["calories"] == 500
    assert all_meals["nutrition_status"]["calories"] == "complete"
    assert all_meals["nutrition"]["sugar"] == 0
    assert all_meals["nutrition_status"]["sugar"] == "partial"
    assert all_meals["nutrition"]["fiber"] is None
    assert all_meals["nutrition_status"]["fiber"] == "missing"

    breakfast = nutrition.daily_summary(TODAY, "breakfast")
    assert breakfast["nutrition"]["calories"] == 0
    assert breakfast["nutrition_status"]["calories"] == "complete"
    snacks = nutrition.daily_summary(TODAY, "snacks")
    assert snacks["meal_count"] == 0
    assert snacks["nutrition"]["calories"] is None

    week = nutrition.weekly_summary(TODAY)
    assert week["start_date"] == "2026-07-04"
    assert week["end_date"] == TODAY
    assert len(week["days"]) == 7
    assert week["days"][-1]["nutrition"]["calories"] == 500
    assert week["days"][0]["nutrition"]["calories"] is None
    assert week["nutrition"]["calories"] == 500


def test_optional_goals_only_appear_after_configuration(isolated_nutrition):
    assert nutrition.get_settings() == {
        "preferred_water_unit": None,
        "water_goal_ml": None,
        "nutrition_goals": {},
    }
    settings = nutrition.update_settings(
        {
            "preferred_water_unit": "ml",
            "water_goal": {"amount": 64, "unit": "fl oz"},
            "nutrition_goals": {"calories": 2000, "protein": 100},
        },
        now=NOW,
    )
    assert settings["water_goal_ml"] == pytest.approx(1892.704, abs=0.001)
    assert settings["nutrition_goals"] == {"calories": 2000, "protein": 100}

    nutrition.create_water_entry(
        {"local_date": TODAY, "amount": 946.352, "unit": "ml"},
        now=NOW,
        reference_date=TODAY,
    )
    water = nutrition.daily_summary(TODAY)["water"]
    assert water["display_unit"] == "ml"
    assert water["goal_progress_percent"] == 50

    cleared = nutrition.update_settings(
        {"water_goal_ml": None, "nutrition_goals": None}, now=NOW
    )
    assert cleared["water_goal_ml"] is None
    assert cleared["nutrition_goals"] == {}
    assert nutrition.daily_summary(TODAY)["water"]["goal_progress_percent"] is None


def test_water_goal_can_exceed_single_entry_limit_but_not_daily_goal_limit(
    isolated_nutrition,
):
    configured = nutrition.update_settings({"water_goal_ml": 15_000}, now=NOW)
    assert configured["water_goal_ml"] == 15_000
    with pytest.raises(nutrition.NutritionValidationError):
        nutrition.update_settings({"water_goal_ml": 20_001}, now=NOW)


def test_daily_water_total_can_exceed_the_single_entry_validation_limit(
    isolated_nutrition,
):
    for index in range(3):
        nutrition.create_water_entry(
            {
                "local_date": TODAY,
                "amount": 8000,
                "unit": "ml",
                "client_request_id": f"large-water-{index}",
            },
            now=NOW,
            reference_date=TODAY,
        )
    water = nutrition.daily_summary(TODAY)["water"]
    assert water["total_ml"] == 24_000
    assert water["display_amount"] == pytest.approx(811.54, abs=0.01)


def test_newer_document_schema_is_not_silently_overwritten(isolated_nutrition):
    target, _acquisitions = isolated_nutrition
    target.write_text(
        json.dumps({"schema_version": nutrition.SCHEMA_VERSION + 1, "meals": {}}),
        encoding="utf-8",
    )
    with pytest.raises(nutrition.NutritionSchemaError):
        nutrition.load_nutrition_tracking()
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == 2


def test_records_are_scoped_to_active_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOPPING_APP_DURABLE_DATA_BACKEND", "json")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(
        nutrition,
        "NUTRITION_FILE",
        storage_service.scoped_package_path("nutrition_tracking.json"),
    )
    app = Flask(__name__)
    app.secret_key = "nutrition-test"

    def activate(user_id):
        g.session_identity_validated = True
        g.authenticated_user_id = user_id
        g.authenticated_guest_session_id = ""

    with app.test_request_context("/"):
        activate("user-a")
        created = nutrition.create_meal(
            meal_payload(), now=NOW, reference_date=TODAY
        )
        assert nutrition.get_meal(created["id"]) is not None

    with app.test_request_context("/"):
        activate("user-b")
        assert nutrition.list_meals(TODAY) == []
        assert nutrition.get_meal(created["id"]) is None
        with pytest.raises(nutrition.NutritionNotFoundError):
            nutrition.update_meal(
                created["id"], {"name": "Stolen"}, now=NOW, reference_date=TODAY
            )
        assert nutrition.delete_meal(created["id"], now=NOW) is False

    with app.test_request_context("/"):
        activate("user-a")
        assert nutrition.get_meal(created["id"])["name"] == "Oatmeal and berries"
