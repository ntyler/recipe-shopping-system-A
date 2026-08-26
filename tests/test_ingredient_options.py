import json
import shutil
import subprocess
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


def test_camel_case_legacy_choices_survive_the_real_editor_load_boundary(monkeypatch):
    monkeypatch.setattr(recipe_edit_service, "recipe_edit_ingredient_master_lookup", lambda *args, **kwargs: {})
    fixture = {
        "recipeIngredientId": "requirement-legacy-cream",
        "ingredient": "Cream",
        "sourceText": "1 cup cream",
        "defaultOptionId": "legacy-coconut",
        "selectionRequired": True,
        "substitutions": {"components": []},
        "substitutionOptions": [{
            "alternativeId": "legacy-coconut",
            "alternativeOrder": 3,
            "alternativeLabel": "Coconut blend",
            "optionType": "substitution",
            "ingredients": [],
            "components": [
                {
                    "name": "Water",
                    "alternativeComponentOrder": 1,
                    "purchasableItem": "Filtered water",
                    "storeSection": "Beverages",
                },
                {
                    "name": "Coconut milk",
                    "alternativeComponentOrder": 0,
                    "storeSection": "International",
                    "optional": "false",
                    "inferred": "false",
                },
            ],
        }],
    }

    migrated = migrate_ingredient_requirement(fixture)
    editor_row = recipe_edit_service.normalize_edit_ingredients([fixture])[0]
    flat_option_id = migrate_ingredient_requirement({
        "ingredient": "Milk",
        "defaultOptionId": "legacy-soy",
        "alternatives": [{"optionId": "legacy-soy", "name": "Soy milk"}],
    })
    optional_choice = recipe_edit_service.normalize_edit_ingredients([{
        "ingredient": "Milk",
        "selectionRequired": False,
        "substitutionOptions": [{"alternativeId": "legacy-soy", "name": "Soy milk"}],
    }])[0]
    original_default = recipe_edit_service.normalize_edit_ingredients([{
        "recipeIngredientId": "requirement-legacy-broth",
        "ingredient": "Chicken broth",
        "originalIsDefault": True,
        "selectionRequired": True,
        "substitutionOptions": [{
            "alternativeId": "legacy-vegetable-broth",
            "name": "Vegetable broth",
        }],
    }])[0]

    assert migrated["recipe_ingredient_id"] == "requirement-legacy-cream"
    assert migrated["default_option_id"] == "legacy-coconut"
    assert migrated["selection_required"] is True
    assert editor_row["default_option_id"] == "legacy-coconut"
    assert editor_row["selection_required"] is True
    substitutions = editor_row["substitutions"]
    assert [row["ingredient"] for row in substitutions] == ["Coconut milk", "Water"]
    assert {row["alternative_id"] for row in substitutions} == {"legacy-coconut"}
    assert [row["alternative_component_order"] for row in substitutions] == [0, 1]
    assert {row["alternative_order"] for row in substitutions} == {3}
    assert {row["alternative_label"] for row in substitutions} == {"Coconut blend"}
    assert {row["option_type"] for row in substitutions} == {"substitution"}
    assert substitutions[0]["store_section"] == "International"
    assert substitutions[0]["optional"] is False
    assert substitutions[0]["inferred"] is False
    assert substitutions[1]["purchasable_item"] == "Filtered water"
    assert substitutions[1]["store_section"] == "Beverages"
    assert flat_option_id["default_option_id"] == "legacy-soy"
    assert flat_option_id["substitutions"][0]["alternative_id"] == "legacy-soy"
    assert optional_choice["selection_required"] is False
    assert original_default["original_is_default"] is True
    assert original_default["default_option_id"] == "original:requirement-legacy-broth"


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


def test_expanded_ingredient_row_preserves_collapsed_header_spacing():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    options_css = css[
        css.index("/* Ingredient editor v44:"):
        css.index("/* Ingredient editor v45:")
    ]
    rule_start = options_css.index(
        "> .recipe-edit-ingredient-row.recipe-edit-substitutions-open {"
    )
    rule = options_css[rule_start:options_css.index("}", rule_start)]

    assert "grid-template-rows: minmax(58px, auto) auto !important;" in rule
    assert "row-gap: 8px !important;" in rule
    assert "minmax(52px, auto)" not in rule


def test_editor_option_selection_is_always_visible_and_directly_changeable():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    service = (
        ROOT / "PushShoppingList/services/recipe_edit_service.py"
    ).read_text(encoding="utf-8")

    assert "function updateRecipeIngredientOptionSelectionState" in script
    assert "function setRecipeIngredientOptionSelected" in script
    assert 'control.dataset.ingredientOptionSelect = "";' in script
    assert 'status.dataset.ingredientOptionSelectedStatus = "";' in script
    assert 'status.setAttribute("role", "status");' in script
    assert 'status.setAttribute("aria-label", "Selected ingredient option");' in script
    assert 'label.textContent = isSelected ? "Selected" : "Use this option";' in script
    assert 'control.setAttribute("aria-pressed", String(isSelected));' in script
    assert 'option.classList.toggle("is-selected-option", isSelected);' in script
    assert 'defaultInput.value = isSelected ? "true" : "false";' in script
    assert 'data-original-option-id value="${escapeAttribute(originalOptionId)}"' in script
    assert 'data-field="original_is_default" value="${escapeAttribute(originalIsDefault ? "true" : "false")}"' in script
    assert 'originalDefaultField.value = originalOptionId && optionId === originalOptionId' in script
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


def test_selecting_an_option_preserves_an_open_group_after_projection_rebuild():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selection = script[
        script.index("function applyRecipeIngredientOptionSelection"):
        script.index("function setRecipeIngredientOptionSelected")
    ]

    assert "const preserveExpandedOptions = recipeIngredientExpansionIsOpen(" in selection
    assert "ingredientRow," in selection
    assert selection.index("const preserveExpandedOptions") < selection.index(
        "setRecipeIngredientDefaultOption("
    )
    assert selection.index("setRecipeIngredientDefaultOption(") < selection.index(
        "if (preserveExpandedOptions)"
    )
    assert '"[data-ingredient-substitutions-toggle]"' in selection
    assert "setRecipeIngredientSubstitutionsExpanded(" in selection
    assert "optionsButton || ingredientRow" in selection
    assert "{ restoreOtherEdits: false }" in selection


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


def test_selecting_an_option_resolves_its_parent_from_projected_store_section_rows():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selection = script[
        script.index("function setRecipeIngredientOptionSelected"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]

    assert "const ingredientRow = recipeIngredientParentRowFromControl(button);" in selection
    assert 'option.closest(".recipe-edit-ingredient-row:not([data-substitution-option-row])")' not in selection


def test_every_group_uses_one_authoritative_parent_summary_without_child_cells():
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
    add_row = script[
        script.index("function addRecipeIngredientRow"):
        script.index("function bindRecipeIngredientSummaryUpdates")
    ]
    populate = script[
        script.index("function populateRecipeEditor"):
        script.index("function replaceRecipeEditorIngredients")
    ]
    replace = script[
        script.index("function replaceRecipeEditorIngredients"):
        script.index("function replaceRecipeEditorRecipeNotes")
    ]
    header = script[
        script.index("function ensureRecipeIngredientSelectedChoiceGroupHeader"):
        script.index("function recipeIngredientSelectedOptionProjectionRows")
    ]

    assert "data-ingredient-choice-parent" not in read_cell
    assert "recipe-edit-ingredient-choice-parent" not in css
    assert "data-ingredient-selected-choice-group-label" in header
    assert "data-ingredient-selected-choice-group-title" in header
    assert "data-ingredient-selected-choice-group-helper" in header
    assert "data-ingredient-selected-choice-group-status" in header
    for child_cell in (
        "recipe-edit-ingredient-image-cell",
        "recipe-edit-ingredient-quantity-summary",
        "recipe-edit-ingredient-unit-summary",
        "recipe-edit-ingredient-size-summary",
        "recipe-edit-ingredient-store-summary",
        "recipe-edit-ingredient-type-summary",
    ):
        assert child_cell not in header
    assert "parentValues.source_text || parentValues.original_text" in state
    assert "row.classList.toggle(\"has-ingredient-choice\", alternativeCount > 0);" in state
    assert '"has-selected-ingredient-choice"' in state
    assert 'row.classList.remove("shows-ingredient-choice-summary");' in state
    assert "presentation.hasGroup" in state
    assert "groupLabel.textContent = presentation.parentLabel;" in state
    assert "groupHelper.textContent = presentation.helperText;" in state
    assert "groupStatus.textContent = presentation.statusText;" in state
    assert '"has-required-unresolved-choice"' in state
    assert 'label: `${summaries.length} option${summaries.length === 1 ? "" : "s"}`' in script
    assert 'row.addEventListener("click"' in organizer
    assert "[data-ingredient-substitutions], .recipe-edit-row-handle" in organizer
    assert "initializeRecipeIngredientRequiredChoice(row);" not in organizer
    assert 'substitutions.setAttribute("role", "region");' in organizer
    assert 'substitutions.removeAttribute("aria-colspan");' in organizer
    assert 'optionsButton.type = "button";' in organizer
    assert 'optionsButton.setAttribute("aria-expanded", "false");' in organizer
    assert 'optionsButton.setAttribute("aria-controls", substitutions.id);' in organizer
    assert "if (!options.deferChoiceInitialization)" in add_row
    assert "initializeRecipeIngredientRequiredChoice(row);" in add_row
    for bulk_population in (populate, replace):
        assert "deferChoiceInitialization: true" in bulk_population
        assert bulk_population.index("setRecipeIngredientsCollapsed(") < bulk_population.index(
            "restoreRecipeIngredientChoiceExpansionState("
        )
    assert 'header.setAttribute("role", "presentation");' in header
    assert 'header.setAttribute("role", "cell");' not in header
    assert "aria-colspan" not in header
    assert ".recipe-edit-selected-choice-group-helper" in css
    assert ".recipe-edit-selected-choice-group-status" in css
    assert "color: var(--app-warning);" in css


def test_presentation_model_normalizes_standard_optional_default_and_choice_states():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the client presentation-model contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    model = script[
        script.index("function recipeIngredientPresentationModel"):
        script.index("function recipeIngredientRecipeViewChoiceGroups")
    ]
    legacy_normalizer = script[
        script.index("function recipeIngredientStablePresentationId"):
        script.index("function recipeIngredientSubstitutionsText")
    ]
    harness = model + legacy_normalizer + r"""
function recipeIngredientCompactChoiceSummary(parentValues, groups) {
    const explicit = Boolean(parentValues.explicitOriginal);
    return {
        hasExplicitOriginalGroup: explicit,
        label: `${groups.length + (explicit ? 0 : 1)} options`,
        summary: "summary",
    };
}
function recipeIngredientSelectedChoice(row) { return row.selectedChoice; }
function recipeIngredientIsOptional(values) { return Boolean(values.optional); }
function recipeIngredientMatchFlag(value) {
    return value === true || String(value || "").toLowerCase() === "true";
}
function recipeIngredientExpansionIsOpen(row) { return Boolean(row.expanded); }
function fieldValuesFromRow(row) { return row; }
function makeRow({defaultId = "", originalId = "original:req", required = false, selectedChoice = null, expanded = false} = {}) {
    const fields = {
        '[data-field="default_option_id"]': {value: defaultId},
        '[data-field="selection_required"]': {value: required ? "true" : "false"},
        '[data-original-option-id]': {value: originalId},
    };
    return {selectedChoice, expanded, querySelector: selector => fields[selector] || null};
}
const alternative = {alternativeId: "alt", rows: [{ingredient: "Alternative", option_type: "substitution"}]};
const explicitOriginal = {alternativeId: "original-group", rows: [{ingredient: "Original", option_type: "original"}]};
const standard = recipeIngredientPresentationModel(makeRow(), {ingredient: "Flour"}, []);
const optional = recipeIngredientPresentationModel(makeRow(), {ingredient: "Salt", optional: true}, []);
const unresolved = recipeIngredientPresentationModel(
    makeRow({required: true}),
    {ingredient: "Broth"},
    [alternative],
);
const selectedDefault = recipeIngredientPresentationModel(
    makeRow({
        defaultId: "original:req",
        required: true,
        selectedChoice: {id: "original:req", rows: [], values: [{}], isDefaultOption: true},
    }),
    {ingredient: "Butter"},
    [alternative],
);
const selectedChoice = recipeIngredientPresentationModel(
    makeRow({
        defaultId: "alt",
        required: true,
        selectedChoice: {id: "alt", rows: alternative.rows, values: alternative.rows, isDefaultOption: false},
    }),
    {ingredient: "Broth"},
    [alternative],
);
const currentNormalizedChoice = recipeIngredientPresentationModel(
    makeRow({
        defaultId: "original-group",
        required: true,
        selectedChoice: {id: "original-group", rows: explicitOriginal.rows, values: explicitOriginal.rows, isDefaultOption: true},
    }),
    {ingredient: "Corn choice", explicitOriginal: true},
    [explicitOriginal, alternative],
);
const legacyRows = recipeIngredientSubstitutionRows({
    substitutions: [],
    alternatives: [{name: "Vegetable broth", group_id: "legacy-broth"}],
});
process.stdout.write(JSON.stringify({
    standard,
    optional,
    unresolved,
    selectedDefault,
    selectedChoice,
    currentNormalizedChoice,
    legacyRows,
    legacyGroupId: recipeIngredientSubstitutionAlternativeId(legacyRows[0]),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["standard"]["kind"] == "standard"
    assert result["standard"]["optionCount"] == 0
    assert result["optional"]["kind"] == "optional"
    assert result["optional"]["optionCount"] == 0
    assert result["unresolved"]["kind"] == "group-parent"
    assert result["unresolved"]["parentLabel"] == "INGREDIENT CHOICE"
    assert result["unresolved"]["optionCount"] == 2
    assert result["unresolved"]["requiredUnresolved"] is True
    assert result["unresolved"]["statusText"] == "Selection required"
    assert all(not option["isSelected"] for option in result["unresolved"]["groups"])
    assert all(not option["isDefault"] for option in result["unresolved"]["groups"])
    assert result["selectedDefault"]["parentLabel"] == "DEFAULT OPTION"
    assert result["selectedDefault"]["groups"][0]["isSelected"] is True
    assert result["selectedChoice"]["parentLabel"] == "INGREDIENT CHOICE"
    assert result["selectedChoice"]["groups"][1]["isSelected"] is True
    assert result["currentNormalizedChoice"]["optionCount"] == 2
    assert len(result["legacyRows"]) == 1
    assert result["legacyRows"][0]["ingredient"] == "Vegetable broth"
    assert result["legacyGroupId"] == "legacy-broth"


def test_legacy_camel_case_alternatives_get_stable_canonical_group_ids():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the legacy ingredient-option contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    normalizer = script[
        script.index("function recipeIngredientStablePresentationId"):
        script.index("function recipeIngredientSubstitutionsText")
    ]
    harness = normalizer + r"""
function recipeIngredientMatchFlag(value) {
    if (value === true || value === 1) return true;
    return ["1", "true", "yes", "on", "best", "best match"].includes(
        String(value || "").trim().toLowerCase(),
    );
}
const legacyRequirement = {
    recipeIngredientId: "ingredient-cream",
    ingredient: "Cream",
    sourceText: "1 cup cream",
    quantity: "1",
    unit: "cup",
    alternatives: [
        {
            alternativeId: "legacy-oat-blend",
            alternativeLabel: "Oat blend",
            alternativeOrder: 3,
            components: [
                {
                    optionId: "legacy-oats",
                    name: "Oats",
                    optionType: "substitution",
                    alternativeComponentOrder: 0,
                    recipeAuthored: true,
                    purchasableItem: "Rolled oats",
                    storeSection: "Breakfast",
                    ingredientImageUrl: "/static/oats.webp",
                    ingredientType: "optional",
                    optional: "false",
                    inferred: "false",
                },
                {
                    name: "Water",
                    optionType: "substitution",
                    alternativeComponentOrder: 1,
                },
            ],
        },
        {
            alternativeLabel: "Coconut blend",
            alternativeOrder: 4,
            components: [
                {name: "Coconut milk", alternativeComponentOrder: 0},
                {name: "Water", alternativeComponentOrder: 1},
            ],
        },
    ],
};
const first = recipeIngredientSubstitutionRows(legacyRequirement);
const repeated = recipeIngredientSubstitutionRows({...legacyRequirement});
const groups = recipeIngredientSubstitutionGroups(first);
const singleCamelContainer = recipeIngredientSubstitutionRows({
    ingredient: "Milk",
    substitutions: {},
    substitution_options: [null],
    substitutionOptions: {
        name: "Soy milk",
        optionType: "substitution",
        substitutionId: "legacy-soy-milk",
    },
});
const placeholderFallback = recipeIngredientSubstitutionRows({
    ingredient: "Broth",
    substitutions: {components: []},
    alternatives: [{name: "Vegetable broth"}],
});
const nestedComponentFallback = recipeIngredientSubstitutionRows({
    ingredient: "Milk",
    alternatives: [{
        alternativeId: "legacy-soy",
        ingredients: [],
        components: [{name: "Soy milk"}],
    }],
});
process.stdout.write(JSON.stringify({
    first,
    repeated,
    groups,
    singleCamelContainer,
    placeholderFallback,
    nestedComponentFallback,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    first = result["first"]
    repeated = result["repeated"]
    assert len(first) == 4
    assert [row["alternative_id"] for row in first] == [
        row["alternative_id"] for row in repeated
    ]
    assert all(row["alternative_id"].strip() for row in first)
    assert first[0]["alternative_id"] == "legacy-oat-blend"
    assert first[1]["alternative_id"] == "legacy-oat-blend"
    assert first[0]["id"] == "legacy-oats"
    assert first[0]["alternative_label"] == "Oat blend"
    assert first[0]["alternative_order"] == 3
    assert first[0]["alternative_component_order"] == 0
    assert first[0]["option_type"] == "substitution"
    assert first[0]["recipe_authored"] is True
    assert first[0]["purchasable_item"] == "Rolled oats"
    assert first[0]["store_section"] == "Breakfast"
    assert first[0]["ingredientImageUrl"] == "/static/oats.webp"
    assert first[0]["ingredientType"] == "optional"
    assert first[0]["optional"] is False
    assert first[0]["inferred"] is False
    synthesized_id = first[2]["alternative_id"]
    assert synthesized_id.startswith("alternative-")
    assert first[3]["alternative_id"] == synthesized_id
    assert [group["alternativeId"] for group in result["groups"]] == [
        "legacy-oat-blend",
        synthesized_id,
    ]
    assert len(result["singleCamelContainer"]) == 1
    assert result["singleCamelContainer"][0]["ingredient"] == "Soy milk"
    assert result["singleCamelContainer"][0]["alternative_id"] == "legacy-soy-milk"
    assert result["singleCamelContainer"][0]["option_type"] == "substitution"
    assert [row["ingredient"] for row in result["placeholderFallback"]] == ["Vegetable broth"]
    assert [row["ingredient"] for row in result["nestedComponentFallback"]] == ["Soy milk"]

    assert "item.ingredientImageUrl" in script
    assert "item.imageUrl" in script
    assert "values.ingredientType" in script


def test_legacy_parent_defaults_select_normalized_child_and_keep_choice_required():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the legacy ingredient-option contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    normalizer = script[
        script.index("function recipeIngredientStablePresentationId"):
        script.index("function recipeIngredientSubstitutionsText")
    ]
    add_start = script.index("function addRecipeIngredientRow")
    add_probe = (
        script[add_start:script.index("    const ingredientType =", add_start)]
        + r"""
    return {
        substitutionOptions,
        defaultOptionId,
        originalOptionId,
        selectionRequired,
    };
}
"""
    )
    selected_choice = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]
    harness = normalizer + add_probe + selected_choice + r"""
global.document = {
    getElementById: id => id === "recipeEditIngredients"
        ? {querySelectorAll: () => []}
        : null,
    createElement: () => ({}),
};
function recipeIngredientImageUrl() { return ""; }
function recipeImageVariantUrl() { return ""; }
function recipeImageVariantSrcSet() { return ""; }
function recipeIngredientExtractionWarning() { return ""; }
function recipeIngredientMatchFlag(value) {
    if (value === true || value === 1) return true;
    return ["1", "true", "yes", "on", "best", "best match"].includes(
        String(value || "").trim().toLowerCase(),
    );
}
function fieldValuesFromRow(row) { return row; }
function recipeIngredientChoiceItemSummary(value) { return value.ingredient || ""; }
function recipeIngredientOptionItemDisplay(value) { return value.ingredient || ""; }
function recipeIngredientOptionTypeLabel(isDefaultOption) {
    return isDefaultOption ? "DEFAULT OPTION" : "ALTERNATIVE OPTION";
}

const requirement = {
    ingredient: "Cream",
    sourceText: "1 cup cream",
    quantity: "1",
    unit: "cup",
    defaultOptionId: "legacy-coconut-blend",
    alternatives: [{
        alternativeId: "legacy-coconut-blend",
        alternativeLabel: "Coconut blend",
        components: [
            {name: "Coconut milk", optionType: "substitution"},
            {name: "Water", optionType: "substitution"},
        ],
    }],
};
const initialized = addRecipeIngredientRow(requirement, {persistedIndex: 0});
const repeated = addRecipeIngredientRow({...requirement}, {persistedIndex: 0});
const optedOut = addRecipeIngredientRow(
    {...requirement, selectionRequired: false},
    {persistedIndex: 0},
);
const legacyOptedOut = addRecipeIngredientRow(
    {...requirement, requiredSelection: false},
    {persistedIndex: 0},
);
const legacyOriginalDefault = addRecipeIngredientRow(
    {
        ...requirement,
        defaultOptionId: "",
        originalIsDefault: true,
    },
    {persistedIndex: 0},
);
const explicitOriginalDefault = addRecipeIngredientRow(
    {
        ...requirement,
        defaultOptionId: "",
        originalOptionId: "original:requirement-legacy-cream",
        originalIsDefault: true,
        alternatives: [{
            alternativeId: "explicit-original-cream",
            optionType: "original",
            components: [{name: "Cream"}, {name: "Water"}],
        }, {
            alternativeId: "explicit-coconut-cream",
            optionType: "recipe_choice",
            name: "Coconut cream",
        }],
    },
    {persistedIndex: 0},
);
const newStandard = addRecipeIngredientRow({
    ingredient: "New ingredient",
    original_text: "1 cup new ingredient",
    quantity: "1",
    unit: "cup",
});
const groups = recipeIngredientSubstitutionGroups(initialized.substitutionOptions);
const fields = {
    '[data-field="default_option_id"]': {value: initialized.defaultOptionId},
    '[data-original-option-id]': {value: initialized.originalOptionId},
};
const selected = recipeIngredientSelectedChoice(
    {querySelector: selector => fields[selector] || null},
    requirement,
    groups,
);
const unresolvedFields = {
    '[data-field="default_option_id"]': {value: ""},
    '[data-original-option-id]': {value: initialized.originalOptionId},
};
const unresolved = recipeIngredientSelectedChoice(
    {querySelector: selector => unresolvedFields[selector] || null},
    requirement,
    [{
        alternativeId: "unselected-option",
        rows: [{
            ingredient: "Vegetable broth",
            preferred: false,
            is_default: "false",
            option_type: "substitution",
        }],
    }],
);
process.stdout.write(JSON.stringify({
    initialized,
    repeated,
    optedOut,
    legacyOptedOut,
    legacyOriginalDefault,
    explicitOriginalDefault,
    newStandard,
    selected,
    unresolved,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    initialized = result["initialized"]
    assert initialized["selectionRequired"] is True
    assert result["optedOut"]["selectionRequired"] is False
    assert result["legacyOptedOut"]["selectionRequired"] is False
    assert result["legacyOriginalDefault"]["defaultOptionId"] == result["legacyOriginalDefault"]["originalOptionId"]
    assert result["explicitOriginalDefault"]["originalOptionId"] == "explicit-original-cream"
    assert result["explicitOriginalDefault"]["defaultOptionId"] == "explicit-original-cream"
    assert result["newStandard"]["selectionRequired"] is False
    assert result["newStandard"]["substitutionOptions"] == []
    assert result["newStandard"]["originalOptionId"].startswith("original:ingredient-")
    assert initialized["defaultOptionId"] == "legacy-coconut-blend"
    assert initialized["originalOptionId"].startswith("original:ingredient-")
    assert initialized["originalOptionId"] == result["repeated"]["originalOptionId"]
    assert initialized["originalOptionId"] != initialized["defaultOptionId"]
    assert all(not row["preferred"] for row in initialized["substitutionOptions"])
    assert result["selected"]["id"] == "legacy-coconut-blend"
    assert [value["ingredient"] for value in result["selected"]["values"]] == [
        "Coconut milk",
        "Water",
    ]
    assert result["unresolved"] is None

    card_update = script[
        script.index("function updateRecipeIngredientAlternativeCard"):
        script.index("function createRecipeIngredientAlternativeCard")
    ]
    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]
    assert "options.selected === undefined" in card_update
    assert "Boolean(options.selected)" in card_update
    assert "input.checked = preferred" not in card_update
    assert "selected: optionPresentation?.isSelected" in substitution_state


def test_removing_or_duplicating_choices_keeps_selection_metadata_consistent():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the option-removal contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helper = script[
        script.index("function reconcileRecipeIngredientSelectionAfterOptionRemoval"):
        script.index("function removeRecipeIngredientSubstitutionRow")
    ]
    duplicate = script[
        script.index("function duplicateRecipeIngredientAlternative"):
        script.index("function addRecipeIngredientAlternativeComponent")
    ]
    assert "preferred: false" in duplicate
    assert "is_default: false" in duplicate

    harness = helper + r"""
function recipeIngredientMatchFlag(value) {
    return value === true || ["1", "true", "yes", "on"].includes(
        String(value || "").trim().toLowerCase(),
    );
}
function recipeIngredientSubstitutionContainer(row) { return row.optionContainer || row; }
function recipeIngredientSubstitutionDomGroups(rows) {
    const groups = new Map();
    rows.forEach(row => {
        const id = row.querySelector('[data-field="alternative_id"]')?.value || "";
        if (!groups.has(id)) groups.set(id, {alternativeId: id, rows: []});
        groups.get(id).rows.push(row);
    });
    return [...groups.values()];
}
function option(id, {preferred = false, isDefault = false} = {}) {
    const fields = {
        alternative_id: {value: id},
        preferred: {checked: preferred},
        is_default: {value: isDefault ? "true" : "false"},
    };
    return {
        querySelector: selector => {
            const name = selector.match(/data-field="([^"]+)"/)?.[1];
            return fields[name] || null;
        },
        fields,
    };
}
function parent(options, {
    defaultId = "",
    originalId = "original:req",
    originalDefault = false,
    required = true,
} = {}) {
    const fields = {
        default_option_id: {value: defaultId},
        original_is_default: {value: originalDefault ? "true" : "false"},
        selection_required: {value: required ? "true" : "false"},
    };
    return {
        querySelectorAll: selector => selector === "[data-substitution-option-row]" ? options : [],
        querySelector: selector => {
            if (selector === "[data-original-option-id]") return {value: originalId};
            const name = selector.match(/data-field="([^"]+)"/)?.[1];
            return fields[name] || null;
        },
        fields,
    };
}

const remainingAfterSelectedDelete = option("other", {preferred: true, isDefault: true});
const selectedDeleted = parent([remainingAfterSelectedDelete], {defaultId: "selected"});
reconcileRecipeIngredientSelectionAfterOptionRemoval(selectedDeleted, "selected", true);

const finalDeleted = parent([], {defaultId: "original:req", originalDefault: true});
reconcileRecipeIngredientSelectionAfterOptionRemoval(finalDeleted, "alternative", false);

const remainingComponent = option("selected", {preferred: true, isDefault: true});
const componentDeleted = parent([remainingComponent], {defaultId: "selected"});
reconcileRecipeIngredientSelectionAfterOptionRemoval(componentDeleted, "selected", true);

const selectedKept = option("selected", {preferred: true, isDefault: true});
const unselectedDeleted = parent([selectedKept], {defaultId: "selected"});
reconcileRecipeIngredientSelectionAfterOptionRemoval(unselectedDeleted, "other", false);

const authoritativeSelected = option("selected", {preferred: true, isDefault: true});
const staleFlagDeleted = parent([authoritativeSelected], {defaultId: "selected"});
reconcileRecipeIngredientSelectionAfterOptionRemoval(staleFlagDeleted, "stale", true);

process.stdout.write(JSON.stringify({
    selectedDeleted: {
        defaultId: selectedDeleted.fields.default_option_id.value,
        originalDefault: selectedDeleted.fields.original_is_default.value,
        required: selectedDeleted.fields.selection_required.value,
        remainingPreferred: remainingAfterSelectedDelete.fields.preferred.checked,
        remainingDefault: remainingAfterSelectedDelete.fields.is_default.value,
    },
    finalDeleted: {
        defaultId: finalDeleted.fields.default_option_id.value,
        originalDefault: finalDeleted.fields.original_is_default.value,
        required: finalDeleted.fields.selection_required.value,
    },
    componentDeleted: {
        defaultId: componentDeleted.fields.default_option_id.value,
        required: componentDeleted.fields.selection_required.value,
        remainingPreferred: remainingComponent.fields.preferred.checked,
    },
    unselectedDeleted: {
        defaultId: unselectedDeleted.fields.default_option_id.value,
        required: unselectedDeleted.fields.selection_required.value,
        selectedPreferred: selectedKept.fields.preferred.checked,
    },
    staleFlagDeleted: {
        defaultId: staleFlagDeleted.fields.default_option_id.value,
        required: staleFlagDeleted.fields.selection_required.value,
        selectedPreferred: authoritativeSelected.fields.preferred.checked,
    },
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["selectedDeleted"] == {
        "defaultId": "",
        "originalDefault": "false",
        "required": "true",
        "remainingPreferred": False,
        "remainingDefault": "false",
    }
    assert result["finalDeleted"] == {
        "defaultId": "",
        "originalDefault": "false",
        "required": "false",
    }
    assert result["componentDeleted"] == {
        "defaultId": "selected",
        "required": "true",
        "remainingPreferred": True,
    }
    assert result["unselectedDeleted"] == {
        "defaultId": "selected",
        "required": "true",
        "selectedPreferred": True,
    }
    assert result["staleFlagDeleted"] == {
        "defaultId": "selected",
        "required": "true",
        "selectedPreferred": True,
    }


def test_required_unresolved_choice_auto_expands_once_without_moving_focus():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    initializer = script[
        script.index("function initializeRecipeIngredientRequiredChoice"):
        script.index("function toggleRecipeIngredientSubstitutions")
    ]

    assert 'row.dataset.ingredientRequiredChoiceInitialized === "true"' in initializer
    assert 'row.dataset.ingredientRequiredChoiceInitialized = "true";' in initializer
    assert "presentation.requiredUnresolved" in initializer
    assert "presentation.expanded" in initializer
    assert 'row.querySelector("[data-ingredient-substitutions-toggle]")' in initializer
    assert "setRecipeIngredientSubstitutionsExpanded(row, disclosure, true" in initializer
    assert "restoreOtherEdits: false" in initializer
    assert ".focus(" not in initializer
    assert ".scrollIntoView(" not in initializer

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the initial disclosure-state contract")
    harness = initializer + r"""
const originalFocus = {id: "title"};
global.document = {activeElement: originalFocus};
const disclosure = {id: "choice-toggle"};
const row = {
    dataset: {},
    querySelectorAll: () => [],
    querySelector: selector => selector === "[data-ingredient-substitutions-toggle]"
        ? disclosure
        : null,
};
const expansions = [];
function recipeIngredientPresentationModel() {
    return {hasGroup: true, requiredUnresolved: true, expanded: false};
}
function recipeIngredientChoiceParentValues() { return {}; }
function recipeIngredientSubstitutionDomGroups() { return []; }
function setRecipeIngredientSubstitutionsExpanded(targetRow, control, open, options) {
    expansions.push({targetRow: targetRow === row, control: control === disclosure, open, options});
}
const first = initializeRecipeIngredientRequiredChoice(row);
const second = initializeRecipeIngredientRequiredChoice(row);
process.stdout.write(JSON.stringify({
    first,
    second,
    expansions,
    focusUnchanged: document.activeElement === originalFocus,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result == {
        "first": True,
        "second": False,
        "expansions": [{
            "targetRow": True,
            "control": True,
            "open": True,
            "options": {"restoreOtherEdits": False},
        }],
        "focusUnchanged": True,
    }


def test_choice_expansion_state_survives_repopulation_without_reopening_collapsed_groups():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the disclosure-state restore contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    stable_id = script[
        script.index("function recipeIngredientStablePresentationId"):
        script.index("function recipeIngredientSubstitutionGroupId")
    ]
    state_helpers = script[
        script.index("function recipeIngredientChoiceExpansionStateKeys"):
        script.index("function initializeRecipeIngredientRequiredChoice")
    ]
    harness = stable_id + state_helpers + r"""
function makeRow(expansionId, {
    initialized = false,
    expanded = false,
    persistedIndex = null,
    source = "",
    hasGroup = true,
} = {}) {
    const disclosure = {id: `${expansionId}-toggle`};
    const fields = {
        source_text: {value: source},
        original_text: {value: source},
        ingredient: {value: source},
        quantity: {value: "1"},
        unit: {value: "cup"},
    };
    return {
        dataset: {
            ingredientExpansionId: expansionId,
            ...(initialized ? {ingredientRequiredChoiceInitialized: "true"} : {}),
            ...(persistedIndex == null
                ? {}
                : {recipeIngredientPersistedIndex: String(persistedIndex)}),
        },
        fields,
        panel: {hidden: !expanded},
        recipeIngredientActiveExpansionId: expanded ? expansionId : "",
        disclosure,
        classList: {
            contains: className => hasGroup && className === "has-ingredient-choice",
        },
        querySelector: selector => selector === "[data-ingredient-substitutions-toggle]"
            ? disclosure
            : null,
    };
}

const collapsedId = "ingredient-group:collapsed";
const expandedId = "ingredient-group:expanded";
let rows = [
    makeRow(collapsedId, {
        initialized: true,
        expanded: false,
        persistedIndex: 0,
        source: "Chicken broth",
    }),
    makeRow(expandedId, {
        initialized: true,
        expanded: true,
        persistedIndex: 1,
        source: "Butter",
    }),
    makeRow("ingredient-group:late-group", {
        persistedIndex: 2,
        source: "Milk",
        hasGroup: true,
    }),
];
const recipeEditExpandedIngredientIds = new Set([expandedId]);
function recipeEditIngredientRows() { return rows; }
function ensureRecipeIngredientExpansionId(row) { return row.dataset.ingredientExpansionId; }
function recipeIngredientSubstitutionContainer(row) { return row.panel; }
function recipeIngredientDirectField(row, fieldName) { return row.fields[fieldName] || null; }

const captured = captureRecipeIngredientChoiceExpansionState();
rows = [
    makeRow("ingredient-group:requirement-broth", {
        persistedIndex: 0,
        source: "Chicken broth",
    }),
    makeRow("ingredient-group:requirement-butter", {
        persistedIndex: 1,
        source: "Butter",
    }),
    makeRow("ingredient-group:requirement-milk", {
        persistedIndex: 2,
        source: "Milk",
    }),
    makeRow("ingredient-group:new", {
        persistedIndex: 3,
        source: "A genuinely new ingredient",
    }),
];
const expansionCalls = [];
const initializationCalls = [];
function setRecipeIngredientSubstitutionsExpanded(row, control, open, options) {
    expansionCalls.push({
        expansionId: row.dataset.ingredientExpansionId,
        correctControl: control === row.disclosure,
        open,
        options,
    });
}
function initializeRecipeIngredientRequiredChoice(row) {
    initializationCalls.push(row.dataset.ingredientExpansionId);
}

restoreRecipeIngredientChoiceExpansionState(captured);
process.stdout.write(JSON.stringify({
    capturedKeys: [...captured.keys()],
    restoredInitializationFlags: rows.slice(0, 3).map(
        row => row.dataset.ingredientRequiredChoiceInitialized,
    ),
    expansionCalls,
    initializationCalls,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert "ingredient-group:collapsed" in result["capturedKeys"]
    assert "ingredient-group:expanded" in result["capturedKeys"]
    assert any(
        key.startswith("ingredient-persisted-position:0:ingredient-state-")
        for key in result["capturedKeys"]
    )
    assert any(
        key.startswith("ingredient-current-position:1:ingredient-state-")
        for key in result["capturedKeys"]
    )
    assert result["restoredInitializationFlags"] == ["true", "true", "true"]
    assert result["expansionCalls"] == [{
        "expansionId": "ingredient-group:requirement-butter",
        "correctControl": True,
        "open": True,
        "options": {"restoreOtherEdits": False},
    }]
    assert result["initializationCalls"] == ["ingredient-group:new"]


def test_group_parent_drag_binds_to_top_level_row_and_keeps_option_children_contained():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    group_drag = script[
        script.index("function ensureRecipeIngredientChoiceGroupDragHandle"):
        script.index("function ensureRecipeIngredientChoiceTitleActions")
    ]
    organizer = script[
        script.index("function organizeRecipeEditIngredientRow"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    drop_guard = script[
        script.index("function recipeEditCanDropOnRow"):
        script.index("function recipeEditDropShouldInsertAfter")
    ]
    drop = script[
        script.index("function dropRecipeEditRow"):
        script.index("function updateRecipeEditRowOrder")
    ]

    assert "bindRecipeEditDragAndDrop(row, handle);" in group_drag
    assert "row.appendChild(substitutions);" in organizer
    assert "row.recipeIngredientSubstitutionPanel = substitutions;" in organizer
    assert "substitutions.recipeIngredientChoiceParentRow = row;" in organizer
    assert "sourceRow.parentElement === resolvedTarget.parentElement" in drop_guard
    assert "recipeEditMoveSelectorForRow(sourceRow) === recipeEditMoveSelectorForRow(resolvedTarget)" in drop_guard
    assert "resolvedTarget.after(sourceRow);" in drop
    assert "resolvedTarget.before(sourceRow);" in drop


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


def test_group_parent_uses_one_persistent_selected_option_source_block():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

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
    selected_block = script[
        script.index("function ensureRecipeIngredientSelectedOptionBlock"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    sync_selected_block = script[
        script.index("function syncRecipeIngredientSelectedOptionLineItems"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    option_block_renderer = script[
        script.index("function renderRecipeIngredientOptionBlock"):
        script.index("function updateRecipeIngredientOptionSelectionState")
    ]
    group_header = script[
        script.index("function ensureRecipeIngredientSelectedChoiceGroupHeader"):
        script.index("function recipeIngredientSelectedOptionProjectionRows")
    ]
    column_source = script[
        script.index("function recipeIngredientColumnViewSourceRow"):
        script.index("function recipeIngredientColumnViewDisplayRows")
    ]
    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert "defaultOptionId && group.alternativeId === defaultOptionId" in selected_choice
    assert "recipeIngredientOptionItemDisplay(value)" in selected_choice
    assert '.join(" + ");' in selected_choice
    assert "selectionLabel: recipeIngredientOptionTypeLabel(true)" in selected_choice
    assert "selectionLabel: recipeIngredientOptionTypeLabel(isDefaultOption)" in selected_choice
    assert "recipeIngredientProjectedOptionSourceRow(control)" in inline_source
    assert "fallbackRow?.recipeIngredientInlineSummarySourceRow" in inline_source
    assert "row.recipeIngredientInlineSummarySourceRow = selectedSourceRow;" in summary
    assert "...fieldValuesFromRow(selectedSourceRow)" in summary
    assert "data-ingredient-selected-group-summary" not in read_cell
    assert "const selectedSourceRow = selectedChoice?.rows[0] || null;" in summary
    assert "const displayIngredientName = ingredientName;" in summary
    assert "if (readName) readName.hidden = false;" in summary
    assert "readDetails.hidden = false;" in summary
    assert "function recipeIngredientSelectedOptionProjectionRows" in selected_line_items
    assert "const rows = Array.isArray(selectedChoice?.rows)" in selected_line_items
    assert "? selectedChoice.rows" in selected_line_items
    assert "return rows.length > 1 ? rows : [];" in selected_line_items
    assert "function recipeIngredientSelectedOptionActiveRows" in selected_line_items
    assert "? selectedChoice.rows.filter(Boolean)" in selected_line_items
    assert "if (rows.length)" in selected_line_items
    assert "return selectedChoice && values.length === 1 && row ? [row] : [];" in selected_line_items
    assert "isPrimaryOriginalComponent" not in selected_line_items
    assert "recipeIngredientSelectedOptionProjectionRows(" in selected_line_items
    assert "recipeIngredientSelectedOptionActiveRows(row, selectedChoice)" in selected_line_items
    assert "const renderedRows = activeRows;" in selected_line_items
    assert "groupByStoreSection\n        ? projectedRows" not in selected_line_items
    assert "if (!lineItems && renderedRows.length)" in selected_line_items
    assert '":scope > [data-ingredient-selected-option-block]"' in selected_block
    assert 'block.dataset.ingredientSelectedOptionBlock = "";' in selected_block
    assert 'block.dataset.ingredientOptionBlock = "";' in selected_block
    assert "const home = row.recipeIngredientSubstitutionHome;" in selected_block
    assert "const reference = homeIsInRow" in selected_block
    assert "row.insertBefore(block, reference);" in selected_block
    assert "block.nextSibling !== home" in selected_block
    assert "row.insertBefore(block, home);" in selected_block
    assert '":scope > [data-ingredient-option-header]"' in selected_block
    assert "selected: true" in selected_block
    assert 'menuKind: "selected"' in selected_block
    assert "if (block.firstElementChild !== header) block.prepend(header);" in selected_block
    assert '":scope > [data-ingredient-option-actions]"' in selected_block
    assert "action.hidden = !expanded;" in selected_block
    assert "if (block.lastElementChild !== action) block.appendChild(action);" in selected_block
    assert "renderRecipeIngredientOptionBlock(lineItems, {" in sync_selected_block
    assert "header," in sync_selected_block
    assert "ingredientContent: summaries," in sync_selected_block
    assert "actions: [action]," in sync_selected_block
    assert "lineItems.hidden = !hasRenderedRows;" in sync_selected_block
    assert "recipeEditIngredientColumnView.groupByStoreSection" not in sync_selected_block
    assert "row.insertBefore(header, row.firstChild);" in group_header
    assert "block.replaceChildren(...children);" in option_block_renderer
    assert option_block_renderer.index("options.header") < option_block_renderer.index(
        "...ingredientContent"
    )
    assert option_block_renderer.index("...ingredientContent") < option_block_renderer.index(
        "...actions"
    )
    assert "createRecipeIngredientOptionRowSummary(" in selected_line_items
    assert "summary.recipeIngredientOptionSourceRow = sourceRow;" in selected_line_items
    assert "const isImplicitOriginal = sourceRow === row;" in selected_line_items
    assert "bindRecipeEditDragAndDrop(" in selected_line_items
    assert "if (isImplicitOriginal)" in selected_line_items
    assert "handleCell.replaceChildren();" in selected_line_items
    assert 'handleCell.setAttribute("aria-hidden", "true");' in selected_line_items
    assert "actions.appendChild(editButton);" in selected_line_items
    assert "const menuWrap = sourceMenuWrap.cloneNode(true);" in selected_line_items
    assert "actions.appendChild(menuWrap);" in selected_line_items
    assert "bindRecipeIngredientMasterPicker(" in selected_line_items
    assert 'data-recipe-ingredient-inline-field="ingredient"' in selected_line_items
    assert "bindRecipeIngredientInlineEditor(row, summary);" in selected_line_items
    assert "openRecipeIngredientOptionModal(editButton)" in selected_line_items
    assert "openRecipeIngredientDefaultOptionModal(editButton)" in selected_line_items
    assert "isDefaultOption: true" in selected_choice
    assert "isDefaultOption," in selected_choice
    assert "syncRecipeIngredientSelectedOptionLineItems(" in substitution_state
    assert "function ensureRecipeIngredientSelectedChoiceGroupHeader" in script
    assert "groupLabel.textContent = presentation.parentLabel;" in substitution_state
    assert "groupTitle.value = choiceTitle;" in substitution_state
    assert "groupTitle.dataset.ingredientChoiceSourceTitle = choiceTitle;" in substitution_state
    assert "document.activeElement !== groupTitle" in substitution_state
    assert "groupHelper.textContent = presentation.helperText;" in substitution_state
    assert "groupStatus.textContent = presentation.statusText;" in substitution_state
    assert '"has-selected-choice-group-header"' in substitution_state
    assert "alternativeCount && hasSelectedChoice" in substitution_state
    assert "alternativeCount && hasSelectedChoice && !isExpanded" not in substitution_state
    assert "alternativeCount && !hasSelectedChoice" not in substitution_state
    assert "selectedChoiceUsesParentIngredientRow" not in substitution_state
    assert "const showsSelectedChoiceGroup = Boolean(presentation.hasGroup);" in substitution_state
    assert "hidesSelectedChoiceHeaderInStoreSectionView" not in substitution_state
    assert "row?.recipeIngredientInlineSummarySourceRow" in column_source
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


def test_active_option_rows_resolve_explicit_implicit_switch_and_unresolved_sources():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the collapsed active-option contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    active_rows = script[
        script.index("function recipeIngredientSelectedOptionActiveRows"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    sync = script[
        script.index("function syncRecipeIngredientSelectedOptionLineItems"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    harness = active_rows + r"""
const parent = { id: "corn-group" };
const fresh = [{id: "corn"}, {id: "cumin"}, {id: "onion"}];
const frozen = [{id: "frozen-corn"}, {id: "frozen-onion"}];
const selectedFresh = {rows: fresh, values: fresh};
const selectedFrozen = {rows: frozen, values: frozen};
const implicitOriginal = {rows: [], values: [{id: "butter"}]};

const collapsedFresh = recipeIngredientSelectedOptionActiveRows(parent, selectedFresh);
const repeatedFresh = recipeIngredientSelectedOptionActiveRows(parent, selectedFresh);
const collapsedFrozen = recipeIngredientSelectedOptionActiveRows(parent, selectedFrozen);
const implicit = recipeIngredientSelectedOptionActiveRows(parent, implicitOriginal);
const unresolved = recipeIngredientSelectedOptionActiveRows(parent, null);
process.stdout.write(JSON.stringify({
    collapsedFresh: collapsedFresh.map(row => row.id),
    repeatedFresh: repeatedFresh.map(row => row.id),
    collapsedFrozen: collapsedFrozen.map(row => row.id),
    implicit: implicit.map(row => row.id),
    unresolved,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "collapsedFresh": ["corn", "cumin", "onion"],
        "repeatedFresh": ["corn", "cumin", "onion"],
        "collapsedFrozen": ["frozen-corn", "frozen-onion"],
        "implicit": ["corn-group"],
        "unresolved": [],
    }
    assert "const activeRows = recipeIngredientSelectedOptionActiveRows(row, selectedChoice);" in sync
    assert "const renderedRows = activeRows;" in sync
    assert "groupByStoreSection\n        ? projectedRows" not in sync
    assert '":scope > [data-ingredient-selected-option-block]"' in sync
    assert "ensureRecipeIngredientSelectedOptionBlock(" in sync
    assert "lineItems.hidden = !hasRenderedRows;" in sync
    assert "recipeEditIngredientColumnView.groupByStoreSection" not in sync


def test_option_block_renderer_keeps_semantic_dom_order_without_duplicates():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the option-block DOM-order contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    renderer = script[
        script.index("function renderRecipeIngredientOptionBlock"):
        script.index("function updateRecipeIngredientOptionSelectionState")
    ]
    harness = renderer + r"""
function nodeRef(id) { return {id}; }
function blockRef() {
    return {
        dataset: {},
        children: [],
        replaceChildren(...children) { this.children = children; },
    };
}
function renderIds({grouped = false, ingredients = []} = {}) {
    const block = blockRef();
    const header = nodeRef("default-header");
    const action = nodeRef("add-selected-ingredient");
    renderRecipeIngredientOptionBlock(block, {
        header,
        ingredientContent: ingredients,
        actions: [action],
    });
    renderRecipeIngredientOptionBlock(block, {
        header,
        ingredientContent: ingredients,
        actions: [action],
    });
    return {
        ids: block.children.map(child => child.id),
        uniqueCount: new Set(block.children).size,
        blockMarker: block.dataset.ingredientOptionBlock,
        grouped,
    };
}

const butter = nodeRef("butter");
const corn = nodeRef("corn");
const cumin = nodeRef("cumin");
const onion = nodeRef("onion");
const unsalted = nodeRef("unsalted-butter");
const ungroupedSingle = renderIds({ingredients: [butter]});
const ungroupedMulti = renderIds({ingredients: [corn, cumin, onion]});
const groupedMulti = renderIds({grouped: true, ingredients: [corn, cumin, onion]});
const alternative = blockRef();
const alternativeHeader = nodeRef("alternative-header");
const alternativeAction = nodeRef("add-alternative-ingredient");
renderRecipeIngredientOptionBlock(alternative, {
    header: alternativeHeader,
    ingredientContent: [unsalted],
    actions: [alternativeAction],
});

process.stdout.write(JSON.stringify({
    ungroupedSingle,
    ungroupedMulti,
    groupedMulti,
    alternative: alternative.children.map(child => child.id),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["ungroupedSingle"] == {
        "ids": ["default-header", "butter", "add-selected-ingredient"],
        "uniqueCount": 3,
        "blockMarker": "",
        "grouped": False,
    }
    assert result["ungroupedMulti"] == {
        "ids": [
            "default-header",
            "corn",
            "cumin",
            "onion",
            "add-selected-ingredient",
        ],
        "uniqueCount": 5,
        "blockMarker": "",
        "grouped": False,
    }
    assert result["groupedMulti"]["ids"] == result["ungroupedMulti"]["ids"]
    assert result["groupedMulti"]["uniqueCount"] == 5
    assert result["groupedMulti"]["grouped"] is True
    assert result["alternative"] == [
        "alternative-header",
        "unsalted-butter",
        "add-alternative-ingredient",
    ]


def test_alternatives_panel_hides_only_its_selected_source_duplicate():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the option-block visibility contract")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    visibility = script[
        script.index("function syncRecipeIngredientSourceOptionBlockVisibility"):
        script.index("function materializeRecipeIngredientDefaultOption")
    ]
    assert "[data-ingredient-selected-option-block]" not in visibility

    harness = visibility + r"""
function classes(...initial) {
    const values = new Set(initial);
    return {
        contains(name) { return values.has(name); },
        toggle(name, force) {
            const enabled = force === undefined ? !values.has(name) : Boolean(force);
            if (enabled) values.add(name); else values.delete(name);
            return enabled;
        },
    };
}
function makeBlock(id, selected = false) {
    const label = {
        attributes: {role: "heading", "aria-level": "4"},
        setAttribute(name, value) { this.attributes[name] = String(value); },
        removeAttribute(name) { delete this.attributes[name]; },
    };
    const header = {
        dataset: {ingredientOptionHeader: ""},
        querySelector(selector) {
            return selector === "[data-ingredient-option-label]" ? label : null;
        },
    };
    return {
        id,
        hidden: false,
        inert: false,
        attributes: {},
        dataset: {ingredientOptionBlock: ""},
        classList: classes(...(selected ? ["is-selected-option"] : [])),
        querySelector(selector) {
            return selector === ":scope > .recipe-edit-ingredient-option-divider"
                ? header
                : null;
        },
        toggleAttribute(name, force) {
            this[name] = Boolean(force);
            if (force) this.attributes[name] = ""; else delete this.attributes[name];
        },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        removeAttribute(name) { delete this.attributes[name]; },
        header,
        label,
    };
}
function snapshot(block) {
    return {
        hidden: block.hidden,
        inert: block.inert,
        sourceCarrier: Object.hasOwn(block.dataset, "ingredientOptionSourceCarrier"),
        optionBlock: Object.hasOwn(block.dataset, "ingredientOptionBlock"),
        optionHeader: Object.hasOwn(block.header.dataset, "ingredientOptionHeader"),
        ariaHidden: block.attributes["aria-hidden"] || "",
        role: block.label.attributes.role || "",
    };
}

const selectedSource = makeBlock("selected-source", true);
const alternative = makeBlock("alternative", false);
const container = {
    classList: classes(),
    querySelector() { return selectedSource; },
    querySelectorAll() { return [alternative]; },
};
syncRecipeIngredientSourceOptionBlockVisibility(container);
const collapsed = {
    selectedSource: snapshot(selectedSource),
    alternative: snapshot(alternative),
};
container.classList.toggle("recipe-edit-ingredient-modal-options-panel", true);
syncRecipeIngredientSourceOptionBlockVisibility(container);
const modal = {
    selectedSource: snapshot(selectedSource),
    alternative: snapshot(alternative),
};
process.stdout.write(JSON.stringify({collapsed, modal}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["collapsed"]["selectedSource"] == {
        "hidden": True,
        "inert": True,
        "sourceCarrier": True,
        "optionBlock": False,
        "optionHeader": False,
        "ariaHidden": "true",
        "role": "",
    }
    assert result["collapsed"]["alternative"] == {
        "hidden": False,
        "inert": False,
        "sourceCarrier": False,
        "optionBlock": True,
        "optionHeader": True,
        "ariaHidden": "",
        "role": "heading",
    }
    assert result["modal"]["selectedSource"] == result["modal"]["alternative"]
    assert result["modal"]["selectedSource"]["hidden"] is False
    assert result["modal"]["selectedSource"]["optionBlock"] is True


def test_corn_fixture_collapsed_view_keeps_all_selected_components(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Corn collapse regression")

    monkeypatch.setattr(
        recipe_edit_service,
        "recipe_edit_ingredient_master_lookup",
        lambda *args, **kwargs: {},
    )

    fixture = json.loads(
        (ROOT / "tests/fixtures/corn_spoon_bread_requirements.json").read_text(
            encoding="utf-8",
        )
    )
    corn = next(
        ingredient
        for ingredient in fixture["ingredients"]
        if ingredient.get("original_text") == "1 cup fresh or frozen corn"
    )
    default_id = corn["default_option_id"]
    selected = [
        row
        for row in corn["substitutions"]
        if row["alternative_id"] == default_id
    ]
    alternatives = [
        row
        for row in corn["substitutions"]
        if row["alternative_id"] != default_id
    ]
    normalized = recipe_edit_service.normalize_edit_ingredients([corn])[0]

    assert corn["selection_required"] is True
    assert [row["ingredient"] for row in selected] == ["corn", "cumin", "onion"]
    assert [row["store_section"] for row in selected] == [
        "PRODUCE",
        "SPICES & SEASONINGS",
        "PRODUCE",
    ]
    assert [row["ingredient"] for row in alternatives] == ["corn", "onion"]
    assert normalized["default_option_id"] == default_id
    assert len(normalized["substitutions"]) == 5
    normalized_selected = [
        row
        for row in normalized["substitutions"]
        if row["alternative_id"] == default_id
    ]
    assert [
        (row["alternative_id"], row["alternative_component_order"], row["store_section"])
        for row in normalized_selected
    ] == [
        (default_id, 0, "PRODUCE"),
        (default_id, 1, "SPICES & SEASONINGS"),
        (default_id, 2, "PRODUCE"),
    ]

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selected_choice = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]
    active_rows = script[
        script.index("function recipeIngredientSelectedOptionActiveRows"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    harness = selected_choice + active_rows + f"""
function fieldValuesFromRow(row) {{ return row; }}
function recipeIngredientChoiceItemSummary(value) {{ return value.ingredient || ""; }}
function recipeIngredientOptionItemDisplay(value) {{ return value.ingredient || ""; }}
function recipeIngredientOptionTypeLabel(isDefaultOption) {{
    return isDefaultOption ? "DEFAULT OPTION" : "ALTERNATIVE OPTION";
}}
function recipeIngredientMatchFlag(value) {{
    if (value === true || value === 1) return true;
    return ["1", "true", "yes", "on"].includes(
        String(value || "").trim().toLowerCase(),
    );
}}

const substitutions = {json.dumps(corn["substitutions"])};
const defaultOptionId = {json.dumps(default_id)};
const groups = Array.from(
    substitutions.reduce((grouped, option) => {{
        const id = option.alternative_id;
        if (!grouped.has(id)) grouped.set(id, {{alternativeId: id, rows: []}});
        grouped.get(id).rows.push(option);
        return grouped;
    }}, new Map()).values(),
);
const parent = {{
    id: "corn-group",
    querySelector(selector) {{
        if (selector === '[data-field="default_option_id"]') {{
            return {{value: defaultOptionId}};
        }}
        if (selector === "[data-original-option-id]") {{
            return {{value: "original:requirement-1b9b67bcc2c17d1f"}};
        }}
        return null;
    }},
}};
const choice = recipeIngredientSelectedChoice(
    parent,
    {json.dumps({key: corn.get(key, "") for key in ("ingredient", "quantity", "unit", "preparation")})},
    groups,
);
const rows = recipeIngredientSelectedOptionActiveRows(parent, choice);
process.stdout.write(JSON.stringify({{
    selectedId: choice && choice.id,
    label: choice && choice.selectionLabel,
    names: rows.map(row => row.ingredient),
    optionCount: groups.length,
}}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "selectedId": default_id,
        "label": "DEFAULT OPTION",
        "names": ["corn", "cumin", "onion"],
        "optionCount": 2,
    }


def test_butter_fixture_grouped_view_keeps_implicit_default_as_active_row(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the Store Section choice regression")

    monkeypatch.setattr(
        recipe_edit_service,
        "recipe_edit_ingredient_master_lookup",
        lambda *args, **kwargs: {},
    )

    fixture = json.loads(
        (ROOT / "tests/fixtures/corn_spoon_bread_requirements.json").read_text(
            encoding="utf-8",
        )
    )
    butter = next(
        ingredient
        for ingredient in fixture["ingredients"]
        if ingredient.get("original_text") == "1/2 cup butter (melted)"
    )
    normalized = recipe_edit_service.normalize_edit_ingredients([butter])[0]

    assert butter["selection_required"] is True
    assert butter["default_option_id"].startswith("original:")
    assert butter["ingredient"] == "butter"
    assert butter["substitutions"][0]["ingredient"] == "unsalted butter"
    assert normalized["default_option_id"] == butter["default_option_id"]
    assert normalized["ingredient"] == "butter"

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selected_choice = script[
        script.index("function recipeIngredientSelectedChoice"):
        script.index("function setRecipeIngredientDefaultOption")
    ]
    active_rows = script[
        script.index("function recipeIngredientSelectedOptionProjectionRows"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    default_id = butter["default_option_id"]
    original_id = f"original:{butter['recipe_ingredient_id']}"
    harness = selected_choice + active_rows + f"""
function fieldValuesFromRow(row) {{ return row; }}
function recipeIngredientChoiceItemSummary(value) {{ return value.ingredient || ""; }}
function recipeIngredientOptionItemDisplay(value) {{ return value.ingredient || ""; }}
function recipeIngredientOptionTypeLabel(isDefaultOption) {{
    return isDefaultOption ? "DEFAULT OPTION" : "ALTERNATIVE OPTION";
}}
function recipeIngredientMatchFlag(value) {{
    if (value === true || value === 1) return true;
    return ["1", "true", "yes", "on"].includes(
        String(value || "").trim().toLowerCase(),
    );
}}

const parentValues = {json.dumps({key: butter.get(key, "") for key in ("ingredient", "quantity", "unit", "preparation")})};
const alternativeRows = {json.dumps(butter["substitutions"])};
const groups = [{{
    alternativeId: alternativeRows[0].alternative_id,
    rows: alternativeRows,
}}];
const parent = {{
    id: "butter-group",
    querySelector(selector) {{
        if (selector === '[data-field="default_option_id"]') {{
            return {{value: {json.dumps(default_id)}}};
        }}
        if (selector === "[data-original-option-id]") {{
            return {{value: {json.dumps(original_id)}}};
        }}
        return null;
    }},
}};
const choice = recipeIngredientSelectedChoice(parent, parentValues, groups);
const projectedRows = recipeIngredientSelectedOptionProjectionRows(choice);
const activeRows = recipeIngredientSelectedOptionActiveRows(parent, choice);
process.stdout.write(JSON.stringify({{
    selectedId: choice && choice.id,
    selectedValues: choice && choice.values.map(value => value.ingredient),
    selectedRows: choice && choice.rows.map(value => value.ingredient),
    projectedRows: projectedRows.map(row => row.id || row.ingredient),
    activeRows: activeRows.map(row => row.id || row.ingredient),
}}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "selectedId": default_id,
        "selectedValues": ["butter"],
        "selectedRows": [],
        "projectedRows": [],
        "activeRows": ["butter-group"],
    }


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


def test_collapsed_choice_removes_all_internal_component_dividers():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    collapsed_divider_css = css[css.index(
        "/* Ingredient editor v77: keep collapsed choice ingredients free of internal dividers. */"
    ):]

    line_items_rule_start = collapsed_divider_css.index(
        ".recipe-edit-selected-option-line-items {"
    )
    line_items_rule = collapsed_divider_css[
        line_items_rule_start:collapsed_divider_css.index("}", line_items_rule_start)
    ]
    assert "border-top: 0;" in line_items_rule
    assert "> .recipe-edit-selected-option-line-item {" in collapsed_divider_css
    assert "border-bottom: 0 !important;" in collapsed_divider_css


def test_collapsed_saved_choice_uses_one_complete_group_boundary():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    hierarchy_css = css[css.index(
        "/* Ingredient editor v108: one quiet boundary per complete ingredient group. */"
    ):]
    rule_start = hierarchy_css.index(
        "> :is("
    )
    rule = hierarchy_css[rule_start:hierarchy_css.index("}", rule_start)]

    assert ".recipe-edit-ingredient-row" in rule
    assert ".recipe-edit-ingredient-column-group-projection" in rule
    assert "border-top: 0 !important;" in rule
    assert "border-right: 0 !important;" in rule
    assert "border-bottom: 1px solid color-mix(" in rule
    assert "var(--recipe-editor-border-soft) 22%" in rule
    assert "border-left: 0 !important;" in rule
    assert "border-radius: 0 !important;" in rule
    assert "box-shadow:" not in rule
    assert "> .recipe-edit-ingredient-row:is(.is-editing, .recipe-edit-substitutions-open)" in hierarchy_css
    assert "border-left: 2px solid var(--app-primary-hover) !important;" in hierarchy_css
    assert ":nth-child" not in hierarchy_css


def test_standard_and_choice_rows_share_the_same_faint_group_boundary():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    hierarchy_css = css[css.index(
        "/* Ingredient editor v108: one quiet boundary per complete ingredient group. */"
    ):]
    rule_start = hierarchy_css.index(
        "> :is("
    )
    rule = hierarchy_css[rule_start:hierarchy_css.index("}", rule_start)]

    assert ".recipe-edit-ingredient-row" in rule
    assert ".has-ingredient-choice" not in rule
    assert ".has-selected-choice-group-header" not in rule
    assert "border-bottom: 1px solid color-mix(" in rule
    assert "var(--recipe-editor-border-soft) 22%" in rule
    assert "var(--app-border)" not in rule


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


def test_adding_ingredient_to_unselected_default_option_preserves_selection():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    add_default = script[
        script.index("function addRecipeIngredientDefaultComponent"):
        script.index("function updateRecipeIngredientSubstitutionState")
    ]

    assert 'const originalOption = row.querySelector("[data-original-option-id]");' in add_default
    assert "const selected = Boolean(" in add_default
    assert 'String(defaultField.value || "").trim() === originalOptionId' in add_default
    assert add_default.count("is_default: selected") == 2
    assert add_default.count("preferred: selected") == 2
    assert "if (selected && defaultField)" in add_default
    assert "applyRecipeIngredientOptionSelection" not in add_default


def test_implicit_default_option_header_has_the_option_actions_submenu():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    header_menu = script[
        script.index("function recipeIngredientOptionHeaderMenuHtml"):
        script.index("function createRecipeIngredientOptionHeader")
    ]
    option_header = script[
        script.index("function createRecipeIngredientOptionHeader"):
        script.index("function renderRecipeIngredientOptionBlock")
    ]
    overview = script[
        script.index("function ensureRecipeIngredientChoiceOverview"):
        script.index("function addRecipeIngredientDefaultComponent")
    ]
    selected_block = script[
        script.index("function ensureRecipeIngredientSelectedOptionBlock"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    alternative_card = script[
        script.index("function createRecipeIngredientAlternativeCard"):
        script.index("function ensureRecipeIngredientAlternativeCards")
    ]
    selection_state = script[
        script.index("function updateRecipeIngredientOptionSelectionState"):
        script.index("function updateRecipeIngredientAlternativeCard")
    ]

    assert 'if (kind === "default")' in header_menu
    assert "recipe-edit-alternative-menu-wrap" in header_menu
    assert 'data-ingredient-grid-column="actions"' in header_menu
    assert 'aria-label="Option actions"' in header_menu
    assert "Ingredient option" in header_menu
    assert 'onclick="return focusRecipeEditCompactRow(this)">Edit option</button>' in header_menu
    assert 'onclick="return duplicateRecipeIngredientDefaultOption(this)">Duplicate option</button>' in header_menu
    assert 'onclick="return moveRecipeIngredientDefaultOption(this, -1)">Move option up</button>' in header_menu
    assert 'onclick="return moveRecipeIngredientDefaultOption(this, 1)">Move option down</button>' in header_menu
    assert "data-set-alternative-preferred" in header_menu
    assert 'onclick="return setRecipeIngredientOptionSelected(this)"' in header_menu
    assert 'onclick="return removeRecipeIngredientDefaultOption(this)">Remove option</button>' in header_menu
    assert 'label: "DEFAULT OPTION"' in overview
    assert 'menuKind: "default"' in overview
    assert 'menuKind: "selected"' in selected_block
    assert 'card.dataset.ingredientOptionBlock = "";' in alternative_card
    assert 'label: "ALTERNATIVE OPTION"' in alternative_card
    assert 'menuKind: "alternative"' in alternative_card
    assert "renderRecipeIngredientOptionBlock(card, {" in alternative_card
    assert "header," in alternative_card
    assert "ingredientContent: [editor]," in alternative_card
    assert 'status.dataset.ingredientOptionSelectedStatus = "";' in option_header
    assert 'status.setAttribute("role", "status");' in option_header
    assert 'status.setAttribute("aria-label", "Selected ingredient option");' in option_header
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
    assert "width: var(--recipe-edit-thumbnail-size, 64px) !important;" in v51
    assert "height: var(--recipe-edit-thumbnail-size, 64px) !important;" in v51
    assert "border: 1px solid var(--recipe-editor-border);" in v51
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
    assert "setRecipeIngredientEditMode(row, true, {" in option_modal
    assert "trigger," in option_modal
    assert "restoreOtherEdits: options.restoreOtherEdits," in option_modal
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


def test_every_alternatives_value_uses_the_shared_column_typography():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    contract = css[css.index("/* Ingredient editor v103:"):]
    for token in (
        '[data-ingredient-column="alternatives"]',
        ".recipe-edit-ingredient-options-button",
        ".recipe-edit-ingredient-options-copy",
        "[data-ingredient-options-label]",
        "[data-ingredient-options-summary]",
        "font-family: var(--app-font-family) !important;",
        "font-size: var(--recipe-edit-ingredient-column-font-size) !important;",
        "font-weight: var(--recipe-edit-ingredient-column-font-weight) !important;",
        "line-height: 1.2 !important;",
        "letter-spacing: normal !important;",
    ):
        assert token in contract


def test_standard_and_alternative_rows_share_one_drag_icon_size():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    selector = (
        "body.recipe-edit-standalone-page .recipe-edit-alternative-component-summary\n"
        "    .recipe-edit-substitution-handle\n"
        "    svg {"
    )
    rule_start = css.index(selector)
    rule = css[rule_start:css.index("}", rule_start)]

    assert "width: 24px;" in rule
    assert "height: 24px;" in rule


def test_selected_choice_header_shows_option_state_without_losing_editable_source_text():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    labels = script[
        script.index("function recipeIngredientOptionTypeLabel"):
        script.index("function recipeIngredientSelectedChoice")
    ]
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

    assert 'return isDefaultOption ? "DEFAULT OPTION" : "ALTERNATIVE OPTION";' in labels
    assert "selectionLabel: recipeIngredientOptionTypeLabel(true)" in selection
    assert "selectionLabel: recipeIngredientOptionTypeLabel(isDefaultOption)" in selection
    assert "groupLabel.textContent = presentation.parentLabel;" in state
    assert "groupTitle.value = choiceTitle;" in state
    assert "groupTitle.dataset.ingredientChoiceSourceTitle = choiceTitle;" in state
    assert "parentValues.source_text || parentValues.original_text" in state
    assert "`${presentation.parentLabel}: ${choiceTitle} (${selectedDetails})`" in state
    assert "groupHelper.textContent = presentation.helperText;" in state
    assert "groupStatus.textContent = presentation.statusText;" in state
    assert "input.dataset.ingredientChoiceSourceTitle ?? input.value" in title_editor
    assert "input.value = sourceTitle;" in title_editor
    assert "input.dataset.ingredientChoiceSourceTitle = nextValue;" in title_editor


def test_group_header_remains_visible_for_selected_and_unresolved_single_ingredient_options():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert "const showsSelectedChoiceGroup = Boolean(presentation.hasGroup);" in state
    assert "hidesSelectedChoiceHeaderInStoreSectionView" not in state
    assert "&& hasSelectedChoice" not in state[
        state.index("const showsSelectedChoiceGroup = Boolean(presentation.hasGroup);"):
        state.index("const selectedChoiceGroupHeader")
    ]
    assert "selectedChoiceUsesParentIngredientRow" not in state


def test_selected_option_type_terminology_is_shared_by_every_ingredient_choice_view():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    recipe_view = script[
        script.index("function renderRecipeIngredientRecipeViewSecondary"):
        script.index("function renderRecipeIngredientRecipeViewItem")
    ]
    projected_and_mobile_rows = script[
        script.index("function syncRecipeIngredientSelectedOptionLineItems"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    compact_summary = script[
        script.index("function updateRecipeIngredientSummary(row)"):
        script.index("function recipeEditIngredientRows")
    ]
    option_switch = script[
        script.index("function setRecipeIngredientDefaultOption"):
        script.index("function createRecipeIngredientDefaultOptionSummary")
    ]

    assert "selectedChoice.selectionLabel" in recipe_view
    assert "recipeIngredientOptionTypeLabel(group.isDefaultOption)" in recipe_view
    assert "selectedChoice.selectionLabel" in projected_and_mobile_rows
    assert "recipeIngredientOptionTypeLabel(selectedChoice.isDefaultOption)" in projected_and_mobile_rows
    assert "const compactChoiceState = selectedChoiceLabel" in compact_summary
    assert "updateRecipeIngredientSubstitutionState(row);" in option_switch
    assert "updateRecipeIngredientSummary(row);" in option_switch

    forbidden_labels = (
        "Default selected",
        "Alternative selected",
        "Default option selected",
        "Alternative option selected",
        "Default Ingredient Choice",
        "Alternative Ingredient Choice",
        "Default/Alternative Ingredient Choice",
    )
    for forbidden_label in forbidden_labels:
        assert forbidden_label.casefold() not in script.casefold()


def test_compact_grouped_row_only_shows_selected_option_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    summary = script[
        script.index("function updateRecipeIngredientSummary(row)"):
        script.index("function recipeEditIngredientRows")
    ]

    assert 'const selectedChoiceLabel = String(selectedChoice?.selectionLabel || "").trim();' in summary
    assert 'const selectedChoiceDetails = String(selectedChoice?.summary || "").trim();' in summary
    assert "const compactChoiceState = selectedChoiceLabel;" in summary
    assert "sourceWording" not in summary
    assert 'sourceText.classList.toggle("is-selected-choice", Boolean(selectedChoiceLabel));' in summary
    assert "if (sourceTextLabel) sourceTextLabel.textContent = compactChoiceState;" in summary
    assert "sourceText.hidden = !selectedChoiceLabel || values.substitutions.length === 0;" in summary
    assert "`${selectedChoiceLabel}: ${selectedChoiceDetails}`" in summary
    assert ": selectedChoiceLabel;" in summary


def test_compact_choice_state_matches_the_optional_badge_anatomy():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    read_cell = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function createRecipeIngredientStatusSummary")
    ]
    badge = css[
        css.index(".recipe-edit-ingredient-source-text.is-selected-choice:not([hidden])"):
        css.index("body.recipe-edit-standalone-page .recipe-edit-ingredient-source-label")
    ]

    assert "recipe-edit-ingredient-source-status-icon" not in read_cell
    assert "display: inline-flex;" in badge
    assert "min-height: 16px;" in badge
    assert "padding: 1px 5px;" in badge
    assert "border-radius: 4px;" in badge
    assert "font-size: 8px;" in badge
    assert "letter-spacing: .04em;" in badge
    assert "text-transform: uppercase;" in badge
    assert "margin-left: 7px;" in css
