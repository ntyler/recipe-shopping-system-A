import json
from pathlib import Path

import pytest

from PushShoppingList.services import meal_plan_service
from PushShoppingList.services import recipe_edit_service
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


def grouped_corn_requirement(default_option_id="corn-default"):
    return {
        "id": "ingredient-corn",
        "ingredient": "Corn choice",
        "default_option_id": default_option_id,
        "substitutions": [
            {
                "alternative_id": "corn-default",
                "alternative_order": 0,
                "alternative_component_order": 0,
                "option_type": "original",
                "ingredient": "Corn",
                "preparation": "fresh",
                "purchasable_item": "corn",
            },
            {
                "alternative_id": "corn-default",
                "alternative_order": 0,
                "alternative_component_order": 1,
                "option_type": "original",
                "ingredient": "Onion",
                "purchasable_item": "onion",
            },
            {
                "alternative_id": "corn-frozen",
                "alternative_order": 1,
                "alternative_component_order": 0,
                "option_type": "recipe_choice",
                "ingredient": "Corn",
                "preparation": "frozen",
                "purchasable_item": "corn",
            },
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
    assert all("alternative_id" not in item for item in resolution["items"])
    assert all("option_type" not in item for item in resolution["items"])
    assert all("substitutions" not in item for item in resolution["items"])


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
        ingredients=resolve_ingredient_requirements(
            master_recipe,
            {requirement["id"]: "milk-lemon"},
        )["items"],
    )

    assert updated["ingredient_option_selections"] == {
        requirement["id"]: "milk-lemon"
    }
    assert updated["ingredient_selection_needed"] is False
    assert [item["ingredient"] for item in updated["ingredients"]] == [
        "Milk",
        "Lemon juice",
    ]
    assert all("alternative_id" not in item for item in updated["ingredients"])
    assert master_recipe == original_recipe


def test_meal_selected_group_components_refresh_when_recipe_option_is_edited(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "meal_plan.json"
    monkeypatch.setattr(meal_plan_service, "MEAL_PLAN_FILE", target)
    recipe_url = "recipe://corn"
    recipe = {"ingredients": [grouped_corn_requirement()]}
    requirement = ingredient_requirement(recipe["ingredients"][0])
    initial_resolution = resolve_ingredient_requirements(recipe)
    meal = meal_plan_service.add_meal({
        "date": "2026-07-29",
        "meal_type": "dinner",
        "recipe_url": recipe_url,
        "recipe_name": "Corn",
        "ingredient_option_selections": initial_resolution["selected_options"],
        "ingredients": initial_resolution["items"],
    })

    edited_recipe = json.loads(json.dumps(recipe))
    edited_recipe["ingredients"][0]["substitutions"][1]["ingredient"] = "Shallot"
    edited_recipe["ingredients"][0]["substitutions"][1]["purchasable_item"] = "shallot"

    assert meal_plan_service.sync_meal_recipe_ingredients(
        recipe_url,
        edited_recipe,
    ) == 1

    refreshed = meal_plan_service.load_meal_plan()["meals"][0]
    assert refreshed["id"] == meal["id"]
    assert refreshed["ingredient_option_selections"] == {
        requirement["id"]: "corn-default"
    }
    assert [item["ingredient"] for item in refreshed["ingredients"]] == [
        "Corn",
        "Shallot",
    ]
    assert all("alternative_id" not in item for item in refreshed["ingredients"])


def test_switching_selected_group_replaces_stale_shopping_items(
    monkeypatch,
    tmp_path,
):
    list_file = tmp_path / "shopping_list.txt"
    list_file.write_text("corn\nonion\n", encoding="utf-8")
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_FILE", list_file)
    monkeypatch.setattr(recipe_edit_service, "add_items", shopping_list_service.add_items)
    monkeypatch.setattr(
        recipe_edit_service,
        "load_recipe_ingredients",
        lambda: {"recipe://corn": {"ingredients": ["corn"]}},
    )
    monkeypatch.setattr(recipe_edit_service, "sort_ingredients", lambda: None)
    monkeypatch.setattr(
        recipe_edit_service,
        "sync_meal_recipe_ingredients",
        lambda *_args, **_kwargs: 0,
    )
    previous_recipe = {
        "source_url": "recipe://corn",
        "ingredients": [grouped_corn_requirement()],
    }
    updated_recipe = {
        "source_url": "recipe://corn",
        "ingredients": [grouped_corn_requirement("corn-frozen")],
    }

    recipe_edit_service.sync_saved_recipe_with_shopping_list(
        updated_recipe,
        recipe_edit_service.resolved_recipe_shopping_item_names(previous_recipe),
    )

    assert shopping_list_service.load_items() == ["corn"]


def test_derived_recipe_record_contains_selected_components_not_group_container(
    monkeypatch,
):
    saved = {}
    recipe = {
        "source_url": "recipe://corn",
        "recipe_title": "Corn",
        "ingredients": [grouped_corn_requirement()],
    }
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_ingredients",
        lambda payload: saved.update(payload),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "sync_recipe_master_records",
        lambda *_args, **_kwargs: None,
    )

    recipe_edit_service.update_recipe_ingredient_record(
        "recipe://corn",
        1,
        recipe,
    )

    record = next(iter(saved.values()))
    assert record["ingredients"] == ["corn", "onion"]
    assert [
        detail["normalized_name"]
        for detail in record["ingredient_details"]
    ] == ["Corn", "Onion"]
    assert "Corn choice" not in record["ingredients"]


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
    assert "bodyScroll.scrollLeft = inlineScrollLeft;" in script
    assert "syncRecipeEditIngredientTableHeaderScroll(tableScroll);" in script
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
    assert ".recipe-edit-ingredient-choice-overview," in css
    assert ".recipe-edit-alternative-card" in css
    assert "background: color-mix(in srgb, var(--app-primary-soft) 18%, var(--app-surface));" in css
    selected_option_css = css[
        css.index(
            ":is(\n"
            "        .recipe-edit-ingredient-choice-overview,\n"
            "        .recipe-edit-alternative-card"
        ):
        css.index(
            ".recipe-edit-alternative-component-summary:not(:hover, :focus-within)"
        )
    ]
    assert "inset 3px 0 0" not in selected_option_css
    assert "inset 0 1px 0" in selected_option_css
    assert "inset 0 -1px 0" in selected_option_css
    assert ".recipe-edit-alternative-component-summary:not(:hover, :focus-within)" in css


def test_selecting_an_option_focuses_its_record_in_the_open_ingredient_modal():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selection = script[
        script.index("function setRecipeIngredientOptionSelected"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]
    option_modal = script[
        script.index("function openRecipeIngredientDefaultOptionModal"):
        script.index("function switchRecipeIngredientOptionModal")
    ]

    assert 'const selectedOptionRow = card' in selection
    assert 'card.querySelector("[data-substitution-option-row]")' in selection
    assert "panel.recipeIngredientOptionHostSnapshot.default_option_id = optionId;" in selection
    assert "openRecipeIngredientOptionModal(button, {" in selection
    assert "optionRow: selectedOptionRow" in selection
    assert "openRecipeIngredientDefaultOptionModalWithOptions(button, {" in selection
    assert "skipUnsavedCheck: !focusedOptionRow || !focusedRecordHadChanges" in selection
    assert "skipUnsavedCheck: !focusedRecordHadChanges" in selection
    assert "!options.skipUnsavedCheck && recipeIngredientModalHasChanges(row)" in option_modal


def test_group_parent_uses_authoritative_recipe_text_and_choice_only_metadata():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    read_cell = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function createRecipeIngredientStatusSummary")
    ]
    state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]
    organizer = script[
        script.index("function organizeRecipeEditIngredientRow"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    source_first_css = css[css.index("/* Ingredient editor v57:"):]

    assert "INGREDIENT CHOICE" in read_cell
    assert "Choose one option" in read_cell
    assert "data-ingredient-choice-original-text" in read_cell
    assert "data-ingredient-choice-selected-summary" in read_cell
    assert "data-ingredient-choice-option-count" in read_cell
    assert "parentValues.source_text || parentValues.original_text" in state
    assert "originalText.textContent = choiceTitle;" in state
    assert "row.classList.toggle(\"has-ingredient-choice\", alternativeCount > 0);" in state
    assert '"has-selected-ingredient-choice"' in state
    assert '"shows-ingredient-choice-summary"' in state
    assert "choiceParent.hidden = !showsChoiceSummary;" in state
    assert "Selected: ${selectedSummary}" in state
    assert "optionCount.textContent = requirementChoiceSummary.label;" in state
    assert 'label: `${summaries.length} option${summaries.length === 1 ? "" : "s"}`' in script
    assert 'row.addEventListener("click"' in organizer
    assert "[data-ingredient-substitutions], .recipe-edit-row-handle" in organizer

    assert ".recipe-edit-ingredient-row.shows-ingredient-choice-summary" in source_first_css
    assert "> :not(.recipe-edit-ingredient-choice-parent)" in source_first_css
    for column in ("status", "quantity", "unit", "size", "store", "type"):
        assert f'[data-ingredient-column="{column}"]' in source_first_css
    assert "grid-column: 3 / -3 !important;" in source_first_css
    assert "background: var(--app-surface);" in source_first_css
    assert "box-shadow: inset 3px 0 0" in source_first_css
    assert "grid-template-areas:" not in source_first_css
    assert "display: flex;" in source_first_css
    assert "text-overflow: ellipsis;" in source_first_css
    assert "background: transparent !important;" in source_first_css


def test_selected_group_summary_uses_preparation_when_it_distinguishes_options():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    summary = script[
        script.index("function recipeIngredientChoiceItemSummary"):
        script.index("function recipeIngredientAlternativeIsRecipeChoice")
    ]
    selected_choice = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]

    assert "preparationDistinguishesOption" in summary
    assert "recipeIngredientComparableText(candidate.ingredient) === ingredientKey" in summary
    assert "recipeIngredientComparableText(candidate.preparation) !== preparationKey" in summary
    assert "return `${preparation} ${ingredientAfterPreparation}`;" in summary
    assert "recipeIngredientChoiceItemSummary(" in selected_choice


def test_collapsed_selected_group_projects_each_ingredient_as_a_normal_line_item():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    selected_choice = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]
    inline_source = script[
        script.index("function recipeIngredientInlineEditorSourceRow"):
        script.index("function syncRecipeIngredientInlineEditor")
    ]
    summary = script[
        script.index("function updateRecipeIngredientSummary(row)"):
        script.index("function recipeEditIngredientRows")
    ]
    read_cell = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function createRecipeIngredientStatusSummary")
    ]
    selected_line_items = script[
        script.index("function createRecipeIngredientSelectedOptionLineItem"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert "defaultOptionId && group.alternativeId === defaultOptionId" in selected_choice
    assert "recipeIngredientOptionItemDisplay(value)" in selected_choice
    assert '.join(" + ");' in selected_choice
    assert 'selectionLabel: "Default option selected"' in selected_choice
    assert '"Alternative option selected"' in selected_choice
    assert "recipeIngredientProjectedOptionSourceRow(control)" in inline_source
    assert "fallbackRow?.recipeIngredientInlineSummarySourceRow" in inline_source
    assert "row.recipeIngredientInlineSummarySourceRow = selectedSourceRow;" in summary
    assert "...fieldValuesFromRow(selectedSourceRow)" in summary
    assert "data-ingredient-selected-group-summary" not in read_cell
    assert "const selectedSourceRow = selectedChoice?.rows[0] || null;" in summary
    assert "const displayIngredientName = ingredientName;" in summary
    assert "if (readName) readName.hidden = false;" in summary
    assert "if (readDetails) readDetails.hidden = false;" in summary
    assert "function recipeIngredientSelectedOptionProjectionRows" in selected_line_items
    assert "return Array.isArray(selectedChoice?.rows)" in selected_line_items
    assert "? selectedChoice.rows" in selected_line_items
    assert "isPrimaryOriginalComponent" not in selected_line_items
    assert "recipeIngredientSelectedOptionProjectionRows(" in selected_line_items
    assert "data-ingredient-selected-option-line-items" in selected_line_items
    assert "createRecipeIngredientOptionRowSummary(" in selected_line_items
    assert "summary.recipeIngredientOptionSourceRow = sourceRow;" in selected_line_items
    assert "bindRecipeEditDragAndDrop(" in selected_line_items
    assert "actions.appendChild(editButton);" in selected_line_items
    assert "const menuWrap = sourceMenuWrap.cloneNode(true);" in selected_line_items
    assert "actions.appendChild(menuWrap);" in selected_line_items
    assert "bindRecipeIngredientMasterPicker(" in selected_line_items
    assert 'data-recipe-ingredient-inline-field="ingredient"' in selected_line_items
    assert "bindRecipeIngredientInlineEditor(row, summary);" in selected_line_items
    assert "openRecipeIngredientOptionModal(editButton)" in selected_line_items
    assert "lineItems.hidden = expanded || !hasProjectedRows;" in selected_line_items
    assert "isDefaultOption: true" in selected_choice
    assert "isDefaultOption," in selected_choice
    assert "syncRecipeIngredientSelectedOptionLineItems(" in substitution_state
    assert "function ensureRecipeIngredientSelectedChoiceGroupHeader" in script
    assert 'groupLabel.textContent = "INGREDIENT CHOICE";' in substitution_state
    assert "groupTitle.value = selectedLabel;" in substitution_state
    assert "groupTitle.dataset.ingredientChoiceSourceTitle = choiceTitle;" in substitution_state
    assert "document.activeElement !== groupTitle" in substitution_state
    assert '"has-selected-choice-group-header"' in substitution_state
    assert "alternativeCount && !hasSelectedChoice" in substitution_state
    assert "alternativeCount && hasSelectedChoice" in substitution_state
    assert "alternativeCount && hasSelectedChoice && !isExpanded" not in substitution_state
    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in substitution_state
    assert 'label.textContent += " · Selected";' not in substitution_state
    assert "label.textContent = selectedLabel;" not in substitution_state
    assert "selectedChoice?.ingredientSummary || selectedDetails" in substitution_state
    assert "summary.textContent = selectedSummary;" in substitution_state
    assert "summary.title = alternativeCount && selectedDetails" in substitution_state
    assert (
        'optionsButton.classList.toggle(\n            "has-selected-option"'
        in substitution_state
    )
    assert "Ingredient editor v55: collapsed group rows reflect the selected option." in css
    assert ".recipe-edit-ingredient-options-button.has-selected-option" in css
    assert "Ingredient editor v58: selected option components remain normal table rows." in css
    assert ".recipe-edit-selected-option-line-items" in css
    assert ".recipe-edit-selected-option-line-item" in css
    assert "position: relative;" in css
    assert "grid-row: 2 !important;" in css
    assert "grid-row: 8 !important;" in css
    assert "Ingredient editor v59: selected choices use a shared group header." in css
    assert ".recipe-edit-selected-choice-group-header" in css
    assert ".recipe-edit-ingredient-source-text" in css
    assert "> .recipe-edit-selected-option-line-items" in css
    assert "grid-row: 3 !important;" in css
    assert "Ingredient editor v60: expansion keeps the shared selected-choice header." in css
    assert ".has-selected-choice-group-header.recipe-edit-substitutions-open" in css
    assert '[data-ingredient-column="alternatives"]' in css
    assert '[data-ingredient-column="actions"]' in css
    assert "Ingredient editor v61: keep the option count visible" in css
    assert "Ingredient editor v62: selected choice source wording is directly editable." in css
    assert "Ingredient editor v64: keep selected-choice group actions on the shared row grid." in css
    assert ".has-selected-choice-group-header.has-selected-option-line-items" in css
    assert "grid-template-rows: auto minmax(64px, auto) !important;" in css
    assert "align-items: stretch;" in css
    assert "Ingredient editor v66: stack every ingredient in the active option when collapsed." in css
    active_option_stack = css[css.index(
        "/* Ingredient editor v66: stack every ingredient in the active option when collapsed. */"
    ):]
    assert ".recipe-edit-selected-option-line-items" in active_option_stack
    assert "> .recipe-edit-selected-option-line-item" in active_option_stack
    assert "grid-row: auto !important;" in active_option_stack


def test_collapsed_choice_option_count_aligns_with_desktop_row_cells():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    alignment_css = css[css.index(
        "/* Ingredient editor v63: align the desktop option count with the row's data cells. */"
    ):]

    assert "@media (min-width: 768px)" in alignment_css
    assert "> .recipe-edit-ingredient-substitution-cell {" in alignment_css
    assert "align-self: center;" in alignment_css
    assert "[data-ingredient-options-label] {" in alignment_css
    assert "font-size: 11px;" in alignment_css
    assert "line-height: 1.4;" in alignment_css
    assert ".recipe-edit-selected-choice-group-title-editor" in css
    assert ".recipe-edit-selected-choice-group-title-input" in css


def test_collapsed_choice_keeps_dividers_only_between_component_rows():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    collapsed_divider_css = css[css.index(
        "/* Ingredient editor v77: leave dividers only between collapsed choice ingredients. */"
    ):]

    line_items_rule_start = collapsed_divider_css.index(
        ".recipe-edit-selected-option-line-items {"
    )
    line_items_rule = collapsed_divider_css[
        line_items_rule_start:collapsed_divider_css.index("}", line_items_rule_start)
    ]
    assert "border-top: 0;" in line_items_rule
    assert "> .recipe-edit-selected-option-line-item:last-child" in collapsed_divider_css
    assert "border-bottom: 0;" in collapsed_divider_css


def test_collapsed_default_choice_has_one_parent_gap_before_its_ingredient_group():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function updateRecipeIngredientSummary")
    ]
    spacing_css = css[css.index(
        "/* Ingredient editor v78: separate a collapsed default choice from its ingredient group. */"
    ):]
    rule_start = spacing_css.index(
        "> .recipe-edit-ingredient-row.has-selected-choice-group-header.has-selected-default-choice:not("
    )
    rule = spacing_css[rule_start:spacing_css.index("}", rule_start)]

    assert '"has-selected-default-choice"' in substitution_state
    assert "showsSelectedChoiceGroup && selectedChoice?.isDefaultOption" in substitution_state
    assert "@media (min-width: 768px)" in spacing_css
    assert ".recipe-edit-substitutions-open" in rule
    assert "row-gap: 8px !important;" in rule
    assert ".has-selected-option-line-items" not in rule
    assert ".recipe-edit-selected-option-line-item" not in rule


def test_choice_row_thumbnail_stays_in_the_shared_image_column():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    alignment_css = css[css.index(
        "/* Ingredient editor v79: keep every choice row on the shared table tracks. */"
    ):]

    assert '@media (min-width: 768px)' in alignment_css
    assert '.recipe-edit-alternative-component-summary' in alignment_css
    assert '[data-ingredient-column="media"][data-ingredient-media-track="0"]' in alignment_css
    assert 'grid-column: 1 !important;' in alignment_css
    assert '[data-ingredient-column="media"][data-ingredient-media-track="1"]' in alignment_css
    assert 'grid-column: 2 !important;' in alignment_css
    assert 'transform: none !important;' in alignment_css
    assert '[data-ingredient-column="ingredient"]' in alignment_css
    assert 'grid-column: 3 !important;' in alignment_css


def test_selected_choice_group_header_uses_standard_action_grid_cells():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    header = script[
        script.index("function focusRecipeIngredientChoiceTitle"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    alignment_start = css.index(
        "/* Ingredient editor v64: keep selected-choice group actions on the shared row grid. */"
    )
    alignment_css = css[alignment_start:css.index(
        "/* Ingredient editor v65:",
        alignment_start,
    )]

    assert "setRecipeIngredientSelectedChoiceGroupControls" in header
    assert "applyRecipeIngredientTableGridContract(header" in header
    assert "drag: dragHandle" in header
    assert "ingredient: header.querySelector(" in header
    assert "alternatives: optionsCell" in header
    assert "actions," in header
    assert "recipe-edit-selected-choice-group-title-icon" not in header
    assert "function ensureRecipeIngredientChoiceTitleActions" in header
    assert "function ensureRecipeIngredientChoiceGroupDragHandle" in header
    assert 'handle.dataset.ingredientChoiceGroupDrag = "";' in header
    assert "bindRecipeEditDragAndDrop(row, handle);" in header
    assert 'actions.dataset.ingredientChoiceTitleActions = "";' in header
    assert 'editButton.setAttribute("aria-label", "Edit ingredient choice title");' in header
    assert 'editButton.dataset.ingredientChoiceTitleEdit = "";' in header
    assert '"return focusRecipeIngredientChoiceTitle(this)"' in header
    assert "const menuWrap = sourceMenuWrap.cloneNode(true);" in header
    assert 'menuWrap.dataset.ingredientChoiceGroupMenu = "";' in header
    assert 'menuButton.setAttribute("aria-label", "More actions for ingredient choice");' in header
    assert "actions.appendChild(menuWrap);" in header
    assert "restoreRecipeIngredientRowActions(row, legacyHeaderActions);" in header
    assert "syncRecipeIngredientRowActionControls(row, rowActions);" in header
    assert 'editButton.setAttribute("onclick", "return focusRecipeEditCompactRow(this)");' in header
    assert "actions?.remove();" in header
    assert "row.insertBefore(optionsCell, optionsPanel || null);" in header
    assert "row.insertBefore(legacyHeaderDragHandle, row.firstChild);" in header
    assert "delete header.dataset.ingredientChoiceGridReady;" in header
    assert "dragHandle?.remove();" in header
    assert "mobileHeader.appendChild(actions);" in header
    assert 'button?.hasAttribute("data-ingredient-choice-title-edit")' in script
    assert ".recipe-edit-selected-choice-group-actions" in alignment_css
    assert '> [data-ingredient-column="ingredient"]' in alignment_css
    assert '> [data-ingredient-column="alternatives"]' in alignment_css
    assert '> [data-ingredient-column="actions"]' in alignment_css
    assert "position: absolute" not in alignment_css
    assert "margin-left" not in alignment_css


def test_selected_choice_group_header_grid_matches_parent_row_content_edges():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    header_css = css[
        css.index("/* Ingredient editor v59: selected choices use a shared group header. */"):
        css.index("/* Ingredient editor v60: expansion keeps the shared selected-choice header. */")
    ]

    assert "width: auto;" in header_css
    assert "max-width: none;" in header_css
    assert "margin-inline: -12px;" in header_css
    assert "padding: 7px 12px 8px;" in header_css


def test_idle_choice_group_chrome_does_not_look_selected():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    marker = "/* Ingredient editor v76: keep idle choice groups visually neutral. */"
    neutral_css = css[css.index(marker):]

    assert "> .recipe-edit-ingredient-row.has-ingredient-choice {" in neutral_css
    assert "box-shadow: none;" in neutral_css
    assert (
        "> .recipe-edit-ingredient-row.has-ingredient-choice.recipe-edit-substitutions-open {"
        in neutral_css
    )
    assert "background: var(--app-surface);" in neutral_css
    assert ".recipe-edit-selected-choice-group-header {" in neutral_css
    assert "border-bottom-color: var(--app-border);" in neutral_css
    assert "var(--app-text) 3%" in neutral_css
    assert "> .recipe-edit-ingredient-options-panel" in neutral_css
    assert ".is-ingredient-expansion-anchor" in neutral_css


def test_first_alternative_keeps_original_ingredient_as_the_default_choice():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    add_group = script[
        script.index("function addRecipeIngredientSubstitutionRow"):
        script.index("function removeRecipeIngredientSubstitutionRow")
    ]

    assert "if (nextAlternativeIndex === 0)" in add_group
    assert "const defaultField = row.querySelector('[data-field=\"default_option_id\"]');" in add_group
    assert "const selectionField = row.querySelector('[data-field=\"selection_required\"]');" in add_group
    assert 'const originalOption = row.querySelector("[data-original-option-id]");' in add_group
    assert "originalOptionId" in add_group
    assert 'selectionField.value = "true";' in add_group
    assert "!String(defaultField.value || \"\").trim()" in add_group
    assert "defaultField.value = originalOptionId;" in add_group
    assert add_group.index("defaultField.value = originalOptionId;") < add_group.index(
        'list.insertAdjacentHTML("beforeend"'
        )


def test_implicit_default_option_header_has_the_option_actions_submenu():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    overview = script[
        script.index("function ensureRecipeIngredientChoiceOverview"):
        script.index("function addRecipeIngredientDefaultComponent")
    ]
    selection_state = script[
        script.index("function updateRecipeIngredientOptionSelectionState"):
        script.index("function updateRecipeIngredientAlternativeCard")
    ]

    assert "recipe-edit-alternative-menu-wrap" in overview
    assert 'data-ingredient-grid-column="actions"' in overview
    assert 'aria-label="Option actions"' in overview
    assert "Ingredient option" in overview
    assert 'onclick="return focusRecipeEditCompactRow(this)">Edit option</button>' in overview
    assert 'onclick="return duplicateRecipeIngredientDefaultOption(this)">Duplicate option</button>' in overview
    assert 'onclick="return moveRecipeIngredientDefaultOption(this, -1)">Move option up</button>' in overview
    assert 'onclick="return moveRecipeIngredientDefaultOption(this, 1)">Move option down</button>' in overview
    assert "data-set-alternative-preferred" in overview
    assert 'onclick="return setRecipeIngredientOptionSelected(this)"' in overview
    assert 'onclick="return removeRecipeIngredientDefaultOption(this)">Remove option</button>' in overview
    assert 'menuAction.textContent = isSelected ? "Selected option" : "Use this option";' in selection_state
    assert "menuAction.disabled = isSelected;" in selection_state
    assert ".recipe-edit-ingredient-choice-overview\n    > .recipe-edit-ingredient-option-divider\n    > .recipe-edit-option-selection" not in css

    default_actions = script[
        script.index("function materializeRecipeIngredientDefaultOption"):
        script.index("function addRecipeIngredientDefaultComponent")
    ]
    assert "function duplicateRecipeIngredientDefaultOption" in default_actions
    assert "function moveRecipeIngredientDefaultOption" in default_actions
    assert "function removeRecipeIngredientDefaultOption" in default_actions
    assert "duplicateRecipeIngredientAlternative(card)" in default_actions
    assert "moveRecipeIngredientAlternative(card, direction)" in default_actions
    assert 'window.confirm("Delete this replacement group and all of its ingredients?")' in default_actions
    assert "removeRecipeIngredientAlternative(card, { confirm: false })" in default_actions


def test_selected_option_line_items_reorder_their_underlying_component_rows():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    drag_helpers = script[
        script.index("function recipeEditUnderlyingMoveRow"):
        script.index("function bindRecipeEditDragAndDrop")
    ]
    drag_binding = script[
        script.index("function bindRecipeEditDragAndDrop"):
        script.index("function startRecipeEditPointerDrag")
    ]
    pointer_target = script[
        script.index("function recipeEditDropTargetFromPoint"):
        script.index("function autoScrollRecipeEditDialogForDrag")
    ]
    drop_handler = script[
        script.index("function dropRecipeEditRow"):
        script.index("function updateRecipeEditRowOrder")
    ]

    assert "row?.recipeIngredientOptionSourceRow || row" in drag_helpers
    assert "resolvedTarget.recipeIngredientInlineSummarySourceRow" in drag_helpers
    assert "[data-ingredient-selected-option-line-item]" in drag_helpers
    assert "recipeEditEventDropTarget(" in drag_binding
    assert "recipeEditDraggedRow," in drag_binding
    assert "recipeEditDraggedDisplayRow" in drag_binding
    assert "[data-ingredient-selected-option-line-item]" in pointer_target
    assert "const sourceRow = recipeEditUnderlyingMoveRow(draggedRow);" in drop_handler
    assert "const resolvedTarget = recipeEditResolvedDropRow(sourceRow, targetRow);" in drop_handler
    assert "resolvedTarget.before(sourceRow);" in drop_handler
    assert "resolvedTarget.after(sourceRow);" in drop_handler
    assert "updateRecipeIngredientSummary(" in drop_handler


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

    assert "function openRecipeIngredientOptionModal(control, options = {})" in option_modal
    assert "setRecipeIngredientEditMode(row, true, { trigger });" in option_modal
    assert "function closeRecipeIngredientOptionModal(row, panel, options = {})" in option_modal
    assert "restoreRecipeIngredientEditableFieldSnapshot(" in option_modal
    assert "panel.recipeIngredientOptionSourceRow" in commit_modal
    assert "closeRecipeIngredientOptionModal(row, panel, { commit: true })" in commit_modal
    assert "createRecipeIngredientEditActionButton()" in script
    assert "openRecipeIngredientOptionModal(editButton)" in script
    assert "/* Ingredient editor v53:" in css
    assert "> span:last-child:not(.recipe-edit-inline-icon)" in css
    v53 = css[
        css.index("/* Ingredient editor v53:"):
        css.index("/* Ingredient editor v54:")
    ]
    assert "> .recipe-edit-inline-icon" in v53
    assert "display: inline-flex;" in v53
    assert "outline: 0;" not in v53


def test_standard_and_alternative_rows_share_one_column_typography_contract():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    contract = css[css.index("/* Ingredient editor v92:"):]
    for token in (
        "--recipe-edit-ingredient-name-font-size: 13px;",
        "--recipe-edit-ingredient-name-font-weight: 750;",
        "--recipe-edit-ingredient-detail-font-size: 11px;",
        "--recipe-edit-ingredient-detail-font-weight: 500;",
        "--recipe-edit-ingredient-column-font-size: 11px;",
        "--recipe-edit-ingredient-column-font-weight: 400;",
        "> .recipe-edit-ingredient-row",
        ".recipe-edit-alternative-component-summary",
        "> [data-ingredient-column=\"ingredient\"]",
        ".recipe-edit-ingredient-inline-name",
        ".recipe-edit-ingredient-inline-preparation",
        "font-family: var(--app-font-family);",
        "font: inherit;",
    ):
        assert token in contract

    for column in (
        "status",
        "quantity",
        "unit",
        "size",
        "store",
        "type",
        "alternatives",
    ):
        assert f'[data-ingredient-column="{column}"]' in contract


def test_selected_choice_header_shows_option_state_without_losing_editable_source_text():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    selection = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]
    title_editor = script[
        script.index("function bindRecipeIngredientChoiceTitleEditor"):
        script.index("function focusRecipeIngredientChoiceTitle")
    ]
    state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert 'selectionLabel: "Default option selected"' in selection
    assert '"Alternative option selected"' in selection
    assert 'groupLabel.textContent = "INGREDIENT CHOICE";' in state
    assert "groupTitle.value = selectedLabel;" in state
    assert "groupTitle.dataset.ingredientChoiceSourceTitle = choiceTitle;" in state
    assert "`${selectedLabel}: ${selectedDetails}`" in state
    assert "input.dataset.ingredientChoiceSourceTitle ?? input.value" in title_editor
    assert "input.value = sourceTitle;" in title_editor
    assert "input.dataset.ingredientChoiceSourceTitle = nextValue;" in title_editor
