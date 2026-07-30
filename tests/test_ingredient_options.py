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
        "quantity": "1",
        "unit": "cup",
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
        '<td class="amount-cell">1 cup</td><td>Corn</td><td>fresh or frozen</td>'
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


def test_explicit_multi_ingredient_default_option_uses_parent_only_as_summary():
    ingredient = {
        "id": "ingredient-flour-mixture",
        "ingredient": "Flour mixture",
        "original_text": "Flour + baking powder, or self-rising flour",
        # Legacy rows may still point at the synthetic parent option.  Once an
        # explicit original group exists, that group becomes the real default.
        "default_option_id": "original:ingredient-flour-mixture",
        "substitutions": [
            {
                "alternative_id": "flour-default",
                "alternative_order": 0,
                "alternative_component_order": 0,
                "option_type": "original",
                "is_default": True,
                "ingredient": "All-purpose flour",
                "quantity": "1",
                "unit": "cup",
            },
            {
                "alternative_id": "flour-default",
                "alternative_order": 0,
                "alternative_component_order": 1,
                "option_type": "original",
                "is_default": True,
                "ingredient": "Baking powder",
                "quantity": "1 1/2",
                "unit": "teaspoons",
            },
            {
                "alternative_id": "self-rising",
                "alternative_order": 1,
                "ingredient": "Self-rising flour",
                "quantity": "1",
                "unit": "cup",
            },
        ],
    }

    requirement = ingredient_requirement(ingredient)
    migrated = migrate_ingredient_requirement(ingredient)
    resolution = resolve_ingredient_requirements([ingredient], require_all=True)

    assert [option["id"] for option in requirement["options"]] == [
        "flour-default",
        "self-rising",
    ]
    assert requirement["default_option_id"] == "flour-default"
    assert migrated["default_option_id"] == "flour-default"
    assert requirement["selection_required"] is True
    assert [item["ingredient"] for item in resolution["items"]] == [
        "All-purpose flour",
        "Baking powder",
    ]
    assert "Flour mixture" not in [item["ingredient"] for item in resolution["items"]]


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


def test_editor_uses_nested_table_rows_instead_of_cards_or_radio_choices():
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
    assert "function addRecipeIngredientDefaultComponent" in script
    assert 'marker.type = "radio";' not in script
    assert "recipe-edit-ingredient-option-divider" in script
    assert "recipe-edit-alternative-component-status" in script
    assert "recipe-edit-alternative-component-size" in script
    assert 'data-ingredient-column="store"' in script
    assert 'data-ingredient-column="type"' in script
    assert "toggleRecipeIngredientSubstitutions(optionsButton, event)" in organizer
    assert "toggleRecipeIngredientSubstitutions(mobileAlternativesBadge, event)" in organizer
    assert "tableScroll.scrollLeft = inlineScrollLeft;" in script
    assert "grid-column: 1 / -1 !important;" in css
    assert "Ingredient editor v45: nested, table-native ingredient option groups." in css
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid);" in css
    assert ".recipe-edit-ingredient-option-group::before" in css


def test_editor_option_selection_is_always_visible_and_directly_changeable():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    service = (
        ROOT / "PushShoppingList/services/recipe_edit_service.py"
    ).read_text(encoding="utf-8")

    assert "function updateRecipeIngredientOptionSelectionState" in script
    assert "function setRecipeIngredientOptionSelected" in script
    assert script.count("data-ingredient-option-select") >= 4
    assert 'label.textContent = isSelected ? "Selected" : "Use this option";' in script
    assert 'control.setAttribute("aria-pressed", String(isSelected));' in script
    assert 'option.classList.toggle("is-selected-option", isSelected);' in script
    assert 'defaultInput.value = isSelected ? "true" : "false";' in script
    assert 'data-original-option-id value="${escapeAttribute(item.original_option_id || "")}"' in script
    assert '"original_option_id": original_option_id(item, index),' in service
    assert "Ingredient editor v54: persistent, directly changeable option selection." in css
    assert ".recipe-edit-option-selection.is-selected" in css
    assert ".is-selected-option" in css


def test_editor_reuses_one_grid_contract_for_parent_and_nested_ingredient_rows():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    contract = script[
        script.index("const RECIPE_EDIT_INGREDIENT_GRID_CELL_ORDER"):
        script.index("function createRecipeIngredientOptionRowSummary")
    ]
    assert "function applyRecipeIngredientTableGridContract" in contract
    for key in (
        "drag",
        "image",
        "ingredient",
        "status",
        "quantity",
        "unit",
        "size",
        "store",
        "type",
        "alternatives",
        "actions",
    ):
        assert f'key: "{key}"' in contract
    assert 'grid.classList.add("recipe-edit-ingredient-table-grid");' in contract
    assert 'placeholder.className = "recipe-edit-ingredient-grid-placeholder";' in contract

    nested_summary = script[
        script.index("function createRecipeIngredientOptionRowSummary"):
        script.index("function updateRecipeIngredientOptionRowSummary")
    ]
    top_level_row = script[
        script.index("function organizeRecipeEditIngredientRow"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    assert "applyRecipeIngredientTableGridContract(summary" in nested_summary
    assert "applyRecipeIngredientTableGridContract(row" in top_level_row
    assert 'tableHead.classList.add("recipe-edit-ingredient-table-grid");' in script
    assert "createRecipeIngredientReadCell(" in nested_summary
    assert "createRecipeIngredientStatusSummary(" in nested_summary
    assert '"recipe-edit-alternative-component-store recipe-edit-ingredient-store-summary"' in nested_summary
    assert '"recipe-edit-alternative-component-type recipe-edit-ingredient-type-summary"' in nested_summary

    v48 = css[css.index("/* Ingredient editor v48:"):]
    assert css.index("/* Ingredient editor v48:") > css.index("/* Ingredient editor v47:")
    assert ".recipe-edit-ingredient-table-grid" in v48
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in v48
    assert "> .recipe-edit-ingredient-options-panel::before" in v48
    assert "> .recipe-edit-alternative-card::before" in v48
    assert "content: none !important;" in v48
    assert "> .recipe-edit-alternative-card.is-single-alternative:not(.is-editing)" in v48
    assert "grid-template-columns: minmax(0, 1fr) !important;" in v48
    assert ".recipe-edit-alternative-component.recipe-edit-substitution-option-row" in v48
    assert "grid-column: 1 / -1 !important;" in v48
    assert "padding: 0 !important;" in v48
    assert "transform: none !important;" in v48
    assert "white-space: nowrap;" in v48
    for column in (
        "ingredient",
        "status",
        "quantity",
        "unit",
        "size",
        "store",
        "type",
        "alternatives",
        "actions",
    ):
        assert f'[data-ingredient-column="{column}"]' in v48

    v49 = css[css.index("/* Ingredient editor v49:"):]
    assert "> .recipe-edit-ingredient-options-panel::before" in v49
    assert "display: none !important;" in v49
    assert "content: none !important;" in v49
    assert ".recipe-edit-alternative-component-quantity" in v49
    assert ".recipe-edit-alternative-component-unit" in v49
    assert ".recipe-edit-alternative-component-size" in v49
    assert "overflow: visible;" in v49
    assert "font-weight: 400;" in v49
    assert "> [data-ingredient-column]" in v49
    assert "grid-row: 1 !important;" in v49
    for column, grid_column in (("status", 4), ("quantity", 5), ("unit", 6), ("size", 7)):
        assert f'> [data-ingredient-column="{column}"]' in v49
        assert f"grid-column: {grid_column} !important;" in v49

    assert "bindRecipeIngredientInlineEditor(optionRow);" in script
    assert "function appendRecipeIngredientInlineSummaryControl" in script
    assert '"recipe-edit-alternative-component-size recipe-edit-ingredient-size-summary"' in script
    assert '"store_section", ".recipe-edit-alternative-component-store"' in script
    assert '"section", ".recipe-edit-alternative-component-type"' in script
    assert "bindRecipeEditDragAndDrop(optionRow);" in script
    v50 = css[css.index("/* Ingredient editor v50:"):]
    for class_name in (
        ".recipe-edit-alternative-component-copy",
        ".recipe-edit-alternative-component-status",
        ".recipe-edit-alternative-component-store",
        ".recipe-edit-alternative-component-type",
        ".recipe-edit-alternative-component-image-cell",
    ):
        assert class_name in v50
    assert '> [data-ingredient-column="store"]' in v50
    assert "grid-column: 8 !important;" in v50
    assert '> [data-ingredient-column="type"]' in v50
    assert "grid-column: 9 !important;" in v50

    image_factory = script[
        script.index("function createRecipeIngredientReadImageCell"):
        script.index("function appendRecipeIngredientInlineSummaryControl")
    ]
    assert '"recipe-ingredient-image-panel"' in image_factory
    assert '"recipe-edit-ingredient-image-cell"' in image_factory
    assert 'image.className = "recipe-step-image recipe-ingredient-image";' in image_factory
    assert 'image.alt = "Ingredient image";' in image_factory
    assert "imageCell.classList.toggle(\"recipe-image-empty\", !imageUrl);" in image_factory
    assert "syncRecipeIngredientReadImageCell(" in script

    name_binding = script[
        script.index("function bindRecipeIngredientNameField"):
        script.index("function addRecipeIngredientRow")
    ]
    assert 'row.querySelectorAll(\'[data-recipe-ingredient-inline-field="ingredient"]\')' in name_binding
    assert "bindRecipeIngredientMasterPicker(field);" in name_binding

    drag_binding = script[
        script.index("function bindRecipeEditDragAndDrop"):
        script.index("function startRecipeEditPointerDrag")
    ]
    assert "requestedHandle = null" in drag_binding
    assert 'handle.dataset.recipeEditDragHandleBound !== "true"' in drag_binding
    assert 'handle.setAttribute("aria-label", "Drag to reorder");' in drag_binding

    v51 = css[css.index("/* Ingredient editor v51:"):]
    assert css.index("/* Ingredient editor v51:") > css.index("/* Ingredient editor v50:")
    assert ".recipe-edit-alternative-component-handle-cell" in v51
    assert "> .recipe-edit-row-handle" in v51
    assert "width: 28px;" in v51
    assert ".recipe-edit-alternative-component-image-cell" in v51
    assert "width: 48px !important;" in v51
    assert "height: 48px !important;" in v51
    assert "border: 1px solid var(--app-border-strong);" in v51
    assert "> .recipe-ingredient-image" in v51

    choice_overview = script[
        script.index("function ensureRecipeIngredientChoiceOverview"):
        script.index("function addRecipeIngredientDefaultComponent")
    ]
    assert 'let summary = overview.querySelector(".recipe-edit-default-option-summary");' in choice_overview
    assert "bindRecipeIngredientInlineEditor(row, overview);" in choice_overview
    assert "bindRecipeIngredientNameField(row);" in choice_overview
    default_summary = script[
        script.index("function createRecipeIngredientDefaultOptionSummary"):
        script.index("function ensureRecipeIngredientChoiceOverview")
    ]
    assert "bindRecipeEditDragAndDrop(" in default_summary
    assert 'handleCell.querySelector(".recipe-edit-row-handle")' in default_summary

    image_error_handler = script[
        script.index("function handleRecipeIngredientReadImageError"):
        script.index("function syncRecipeIngredientReadImageCell")
    ]
    assert "image.dataset.deferredSrc" in image_error_handler
    assert 'image.dataset.deferredLoaded !== "1"' in image_error_handler
    assert "image.hidden = true;" in image_error_handler
    assert 'image.closest(".recipe-ingredient-image-panel")' in image_error_handler
    assert 'imageCell.classList.add("recipe-image-empty");' in image_error_handler
    assert 'image.addEventListener("error", () => handleRecipeIngredientReadImageError(image));' in script
    assert 'onerror="handleRecipeIngredientReadImageError(this)"' in script

    v52 = css[css.index("/* Ingredient editor v52:"):]
    assert css.index("/* Ingredient editor v52:") > css.index("/* Ingredient editor v51:")
    assert ".recipe-ingredient-image[hidden]" in v52
    assert "display: none !important;" in v52
    assert ".recipe-edit-alternative-component-handle-cell" in v52
    assert "> .recipe-edit-row-handle" in v52
    assert "height: auto;" in v52
    assert "min-height: 0;" in v52
    assert ".recipe-edit-alternative-component-status" in v52
    for declaration in (
        "padding: 0;",
        "border: 0;",
        "border-radius: 0;",
        "background: transparent;",
        "color: inherit;",
        "font-size: inherit;",
        "font-weight: inherit;",
        "line-height: inherit;",
    ):
        assert declaration in v52
    assert "> [data-ingredient-read-status]" in v52
    assert "white-space: nowrap;" in v52


def test_option_ingredient_pencils_use_the_standard_edit_ingredient_modal():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    option_modal = script[
        script.index("function recipeIngredientOptionModalRows"):
        script.index("function setRecipeIngredientEditMode")
    ]
    commit_modal = script[
        script.index("async function commitRecipeIngredientModal"):
        script.index("const RECIPE_EDIT_INGREDIENT_GRID_CELL_ORDER")
    ]

    assert "function openRecipeIngredientOptionModal(control)" in option_modal
    assert "setRecipeIngredientEditMode(row, true, { trigger });" in option_modal
    assert "function closeRecipeIngredientOptionModal(row, panel, options = {})" in option_modal
    assert "restoreRecipeIngredientEditableFieldSnapshot(" in option_modal
    assert "panel.recipeIngredientOptionSourceRow" in commit_modal
    assert "closeRecipeIngredientOptionModal(row, panel, { commit: true })" in commit_modal
    assert 'editButton.className = "recipe-edit-compact-row-edit";' in script
    assert "openRecipeIngredientOptionModal(editButton)" in script
    assert "/* Ingredient editor v53:" in css
    assert "> span:last-child:not(.recipe-edit-inline-icon)" in css
    v53 = css[css.index("/* Ingredient editor v53:"):]
    assert "> .recipe-edit-inline-icon" in v53
    assert "display: inline-flex;" in v53
