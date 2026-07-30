import json
from pathlib import Path

import pytest

from PushShoppingList.services import meal_plan_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services.ingredient_option_service import (
    IngredientOptionSelectionRequired,
    ingredient_requirement,
    migrate_ingredient_requirement,
    resolve_ingredient_requirements,
)


ROOT = Path(__file__).resolve().parents[1]


def buttermilk_requirement():
    return {
        "id": "ingredient-buttermilk",
        "ingredient": "Buttermilk",
        "quantity": "1",
        "unit": "cup",
        "original_text": "1 cup buttermilk",
        "substitutions": [
            {
                "alternative_id": "milk-lemon",
                "alternative_label": "Milk + lemon juice",
                "alternative_order": 2,
                "ingredients": [
                    {
                        "ingredient": "Milk",
                        "quantity": "1",
                        "unit": "cup",
                    },
                    {
                        "ingredient": "Lemon juice",
                        "quantity": "1",
                        "unit": "tablespoon",
                    },
                ],
            }
        ],
    }


def test_requirement_without_alternatives_preserves_current_single_item_behavior():
    ingredient = {
        "id": "ingredient-flour",
        "ingredient": "Flour",
        "quantity": "2",
        "unit": "cups",
    }

    requirement = ingredient_requirement(ingredient)
    resolution = resolve_ingredient_requirements([ingredient], require_all=True)

    assert requirement["selection_required"] is False
    assert requirement["default_option_id"] is None
    assert [option["option_type"] for option in requirement["options"]] == ["original"]
    assert [item["ingredient"] for item in resolution["items"]] == ["Flour"]


def test_recipe_authored_fresh_or_frozen_choice_is_explicit_and_pdf_safe():
    ingredient = {
        "id": "ingredient-corn",
        "ingredient": "Corn",
        "preparation": "fresh",
        "original_text": "fresh or frozen corn",
        "substitutions": [
            {
                "alternative_id": "inline-form-frozen-corn",
                "ingredient": "Corn",
                "preparation": "frozen",
                "inferred": False,
            }
        ],
    }

    requirement = ingredient_requirement(ingredient)
    pdf_html = recipe_extract_service.format_video_recipe_ingredients_for_pdf([ingredient])

    assert requirement["selection_required"] is True
    assert requirement["source_text"] == "fresh or frozen corn"
    assert requirement["options"][1]["option_type"] == "recipe_choice"
    assert (
        '<td class="amount-cell">1</td><td>Corn</td><td>fresh or frozen</td>'
        in pdf_html
    )
    assert "Alternative:" not in pdf_html


@pytest.mark.parametrize(
    "ingredient, option_id, expected",
    [
        (
            {
                "id": "ingredient-butter",
                "ingredient": "Butter",
                "substitutions": [
                    {
                        "alternative_id": "margarine",
                        "ingredient": "Margarine",
                    }
                ],
            },
            "margarine",
            ["Margarine"],
        ),
        (buttermilk_requirement(), "milk-lemon", ["Milk", "Lemon juice"]),
        (
            {
                "id": "ingredient-egg",
                "ingredient": "Egg",
                "substitutions": [
                    {
                        "alternative_id": "flax-egg",
                        "ingredients": [
                            {"ingredient": "Ground flax"},
                            {"ingredient": "Water"},
                            {"ingredient": "Baking powder"},
                        ],
                    }
                ],
            },
            "flax-egg",
            ["Ground flax", "Water", "Baking powder"],
        ),
    ],
)
def test_selected_replacement_option_resolves_as_one_atomic_group(
    ingredient,
    option_id,
    expected,
):
    requirement = ingredient_requirement(ingredient)

    with pytest.raises(IngredientOptionSelectionRequired):
        resolve_ingredient_requirements([ingredient], require_all=True)

    resolution = resolve_ingredient_requirements(
        [ingredient],
        {requirement["id"]: option_id},
        require_all=True,
    )

    assert [item["ingredient"] for item in resolution["items"]] == expected
    assert resolution["selected_options"] == {requirement["id"]: option_id}
    assert resolution["selection_needed"] is False


def test_migration_keeps_existing_flat_rows_and_adds_stable_group_metadata():
    migrated = migrate_ingredient_requirement(buttermilk_requirement())

    assert migrated["recipe_ingredient_id"] == "ingredient-buttermilk"
    assert migrated["selection_required"] is True
    assert len(migrated["substitutions"]) == 2
    assert {row["alternative_id"] for row in migrated["substitutions"]} == {"milk-lemon"}
    assert [row["alternative_order"] for row in migrated["substitutions"]] == [2, 2]
    assert [row["alternative_component_order"] for row in migrated["substitutions"]] == [0, 1]


def test_pdf_keeps_one_for_one_and_one_for_many_alternatives_grouped():
    html = recipe_extract_service.format_video_recipe_ingredients_for_pdf(
        [
            {
                "ingredient": "Butter",
                "substitutions": [
                    {"alternative_id": "margarine", "ingredient": "Margarine"}
                ],
            },
            buttermilk_requirement(),
        ]
    )

    assert html.count('class="alternative-row"') == 2
    assert "Margarine" in html
    assert "1 cup Milk + 1 tablespoon Lemon juice" in html


def test_shopping_list_requires_resolution_then_persists_instance_selection(
    monkeypatch,
    tmp_path,
):
    list_file = tmp_path / "shopping_list.txt"
    selections_file = tmp_path / "shopping_list_recipe_selections.json"
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_FILE", list_file)
    monkeypatch.setattr(
        shopping_list_service,
        "SHOPPING_LIST_SELECTIONS_FILE",
        selections_file,
    )
    recipe = {"ingredients": [buttermilk_requirement()]}
    requirement = ingredient_requirement(recipe["ingredients"][0])

    skipped = shopping_list_service.add_items(recipe["ingredients"])
    assert skipped["selection_needed"] is True
    assert shopping_list_service.load_items() == []

    result = shopping_list_service.finalize_recipe_items(
        "recipe://biscuits",
        recipe,
        {requirement["id"]: "milk-lemon"},
    )

    assert result["added"] == ["Milk", "Lemon juice"]
    assert shopping_list_service.load_items() == ["Milk", "Lemon juice"]
    saved = json.loads(selections_file.read_text(encoding="utf-8"))
    assert saved["recipes"]["recipe://biscuits"] == {
        requirement["id"]: "milk-lemon"
    }


def test_meal_selection_is_saved_only_on_the_meal_instance(monkeypatch, tmp_path):
    target = tmp_path / "meal_plan.json"
    monkeypatch.setattr(meal_plan_service, "MEAL_PLAN_FILE", target)
    master_recipe = {"ingredients": [buttermilk_requirement()]}
    requirement = ingredient_requirement(master_recipe["ingredients"][0])
    original_recipe = json.loads(json.dumps(master_recipe))

    meal = meal_plan_service.add_meal(
        {
            "date": "2026-07-29",
            "meal_type": "dinner",
            "recipe_url": "recipe://biscuits",
            "recipe_name": "Biscuits",
            "unresolved_ingredient_requirement_ids": [requirement["id"]],
            "ingredient_selection_needed": True,
        }
    )
    assert meal["ingredient_selection_needed"] is True

    updated = meal_plan_service.update_meal_ingredient_option_selections(
        meal["id"],
        {requirement["id"]: "milk-lemon"},
        [],
    )

    assert updated["ingredient_option_selections"] == {
        requirement["id"]: "milk-lemon"
    }
    assert updated["ingredient_selection_needed"] is False
    assert master_recipe == original_recipe


def test_editor_uses_inline_option_detail_instead_of_an_alternative_dialog():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organizer = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index(
            "function organizeRecipeEditCompactRowActions",
            script.index("function organizeRecipeEditIngredientRow(row)"),
        )
    ]

    assert 'substitutions.classList.add("recipe-edit-ingredient-options-panel");' in organizer
    assert "row.appendChild(substitutions);" in organizer
    assert 'setAttribute("aria-haspopup", "dialog")' not in organizer
    assert "recipe-edit-ingredient-choice-overview" in script
    assert "Add ingredient to this option" in script
    assert "Add another option" in script
    assert "function moveRecipeIngredientAlternative(control, direction)" in script
    assert "function moveRecipeIngredientAlternativeComponent(control, direction)" in script
    assert "function setRecipeIngredientDefaultOption" in script
    assert 'marker.type = "radio";' in script
    assert "grid-column: 1 / -1 !important;" in css
