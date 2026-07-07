from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from flask import render_template

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import cookbook_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_cookbook_menu_mode_static_hooks_are_present():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/main_routes.py")
    service = read_text("PushShoppingList/services/cookbook_service.py")

    for label in (
        "Cookbook View",
        "Browse saved recipes as rows or a restaurant menu.",
        "View Cookbook As",
        "Recipe View",
        "Cookbook Menu",
        "Sort Cookbook By",
        "🍽️ Restaurant Menu",
        "🌎 Cuisine",
        "🥩 Main Ingredient",
        "🍳 Meal Type",
        "🔥 Cooking Method",
        "🎉 Occasion",
        "🥗 Dietary Preference",
        "⏱️ Prep Time",
        "🔤 Alphabetical",
        "⭐ Custom Categories",
    ):
        assert label in template or label in service

    assert "data-cookbook-menu-view" in template
    assert "data-cookbook-view-mode-select" in template
    assert 'data-cookbook-view-panel="recipes"' in template
    assert 'data-cookbook-view-panel="menu"' in template
    assert "data-cookbook-menu-section" in template
    assert "No recipes found in this category yet." in template
    assert "Add Ingredients to Shopping List" in template
    assert "cookbookCategoryEditorModal" in template
    assert "/api/cookbooks/<cookbook_id>/recipe_categories" in routes
    assert "/api/cookbooks/<cookbook_id>/menu_sections/reorder" in routes
    assert "function openCookbookCategoryEditor" in script
    assert "function applyCookbookViewMode" in script
    assert "COOKBOOK_VIEW_MODE_SESSION_KEY" in script
    assert "function saveCookbookCategories" in script
    assert "function moveRecipeEditMenuSection" in script
    assert "function inferMissingCookbookRecipeDetails" in script
    assert "cookbook_category_overwrite" in script
    assert "reorder_cookbook_menu_section" in service
    assert "Infer Details for This Recipe" in template
    assert "data-cookbook-search-text" in template
    assert ".cookbook-menu-recipe-card" in css
    assert ".cookbook-recipe-log-view" in css
    assert ".cookbook-category-grid" in css
    assert ".menu-recipe-status-failed" in css
    assert "menu-recipe-status-failed" in template
    assert "menu-recipe-status-failed" in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "menu-recipe-status-failed" in read_text("PushShoppingList/templates/sections/items.html")


def test_cookbook_infer_controls_live_inside_cookbook_submenu():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")

    actions_start = template.index('<div class="cookbook-card-actions">')
    menu_wrap_start = template.index('<div class="cookbook-card-menu-wrap', actions_start)
    header_actions_block = template[actions_start:menu_wrap_start]

    menu_start = template.index('<div class="recipe-edit-row-menu cookbook-card-menu" hidden>', menu_wrap_start)
    browser_start = template.index('<div class="cookbook-menu-browser"', menu_start)
    cookbook_menu_block = template[menu_start:browser_start]

    assert "data-cookbook-infer-overwrite" not in header_actions_block
    assert "data-cookbook-infer-preview" not in header_actions_block
    assert "inferMissingCookbookDetails" not in header_actions_block
    assert cookbook_menu_block.index("Menu AI") < cookbook_menu_block.index("data-cookbook-infer-overwrite")
    assert cookbook_menu_block.index("data-cookbook-infer-overwrite") < cookbook_menu_block.index("data-cookbook-infer-preview")
    assert cookbook_menu_block.index("data-cookbook-infer-preview") < cookbook_menu_block.index("data-cookbooks-ai-inferred-toggle")
    assert cookbook_menu_block.index("data-cookbooks-ai-inferred-toggle") < cookbook_menu_block.index("inferMissingCookbookDetails")
    assert cookbook_menu_block.index("inferMissingCookbookDetails") < cookbook_menu_block.index("Sort By")
    assert cookbook_menu_block.index("Sort By") < cookbook_menu_block.index("Menu PDF Log")
    assert cookbook_menu_block.index("inferMissingCookbookDetails") < cookbook_menu_block.index("Menu PDF Log")
    assert "Hide AI-Inferred Recipe" in cookbook_menu_block
    assert "function cookbookInferOptionCheckbox" in script
    assert "function toggleCookbooksAiInferredBadges" in script
    assert "restoreCookbooksAiInferredBadgeSetting" in script
    assert 'button.closest(".recipe-edit-row-menu")' in script
    assert "menu.recipeEditAnchorButton" in script


def test_cookbook_submenu_has_bulk_recipe_image_generation_controls():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")

    menu_start = template.index('<div class="recipe-edit-row-menu cookbook-card-menu" hidden>')
    browser_start = template.index('<div class="cookbook-menu-browser"', menu_start)
    cookbook_menu_block = template[menu_start:browser_start]

    assert '<div class="overflow-menu-section cookbook-image-menu-section">' in cookbook_menu_block
    assert cookbook_menu_block.index("Food Rules") < cookbook_menu_block.index("Generate Images")
    assert cookbook_menu_block.index("Generate Images") < cookbook_menu_block.index("Regenerate images...")
    assert cookbook_menu_block.index("Regenerate images...") < cookbook_menu_block.index("Generate missing images...")
    assert cookbook_menu_block.index("Generate missing images...") < cookbook_menu_block.index("Selection")
    assert cookbook_menu_block.count("data-cookbook-image-global-btn") == 8
    assert "generateCookbookRecipeImagesFromMenu(this, { imageScope: 'all' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { imageScope: 'ingredients' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { imageScope: 'equipment' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { imageScope: 'instructions' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'all' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'ingredients' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'equipment' })" in cookbook_menu_block
    assert "generateCookbookRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'instructions' })" in cookbook_menu_block

    assert "function cookbookRecipeUrlsForImageGeneration" in script
    assert "function cookbookRecipeImageTargetsForRecipe" in script
    assert "async function generateCookbookRecipeImageTarget" in script
    assert "async function generateCookbookRecipeImagesFromMenu" in script
    assert "cookbookCardFromControl(button)" in script
    assert 'fetchRecipeEditorData(recipeUrl, { useCache: false })' in script
    assert '"/api/recipe_ingredient_image"' in script
    assert '"/api/recipe_equipment_image"' in script
    assert '"/api/recipe_step_image"' in script


def test_cookbook_submenu_has_recipe_sort_controls():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    menu_start = template.index('<div class="recipe-edit-row-menu cookbook-card-menu" hidden>')
    browser_start = template.index('<div class="cookbook-menu-browser"', menu_start)
    cookbook_menu_block = template[menu_start:browser_start]

    assert '<div class="overflow-menu-section cookbook-sort-menu-section">' in cookbook_menu_block
    assert cookbook_menu_block.index("Sort By") < cookbook_menu_block.index("Menu PDF Log")
    for sort_key, label in (
        ("menu_section", "Sort by Menu Section"),
        ("menu_price", "Sort by Menu Price"),
        ("name", "Sort by Name"),
        ("recipe_number", "Sort by Recipe #"),
    ):
        assert f'data-cookbook-sort-option="{sort_key}"' in cookbook_menu_block
        assert f"sortCookbookRecipes(this, '{sort_key}')" in cookbook_menu_block
        assert label in cookbook_menu_block

    assert 'data-cookbook-menu-section="{{ recipe.menu_section }}"' in template
    assert 'data-cookbook-menu-section-id="{{ recipe.menu_section_id }}"' in template
    assert 'data-cookbook-menu-price="{{ recipe.menu_price }}"' in template
    assert 'data-cookbook-recipe-number="{{ recipe.number or loop.index }}"' in template
    assert "const COOKBOOK_RECIPE_SORT_KEYS" in script
    assert "const COOKBOOK_RECIPE_SORT_DIRECTIONS" in script
    assert 'const DEFAULT_COOKBOOK_RECIPE_SORT_STATE = { sortKey: "menu_section", direction: "asc" };' in script
    assert 'const DEFAULT_COOKBOOK_MENU_SECTION_LABEL = "Miscellaneous";' in script
    assert "function cookbookCardFromControl(control)" in script
    assert 'menu.recipeEditAnchorButton.closest("[data-cookbook-card]")' in script
    assert "function normalizeCookbookRecipeSortState(value)" in script
    assert "function serializeCookbookRecipeSortState(sortKey, direction)" in script
    assert "function cookbookRecipeNextSortState(card, sortKey)" in script
    assert "function cookbookRecipeMenuSectionOrder(card)" in script
    assert "dataset.cookbookMenuSectionId" in script
    assert "function renderCookbookRecipeSortDecorations(card, sortKey)" in script
    assert "function renderCookbookRecipeSectionHeadings(card)" in script
    assert "function renderCookbookRecipeMenuPriceBadges(card)" in script
    assert "function updateCookbookRecipeSortDecorationVisibility(card)" in script
    assert "function sortCookbookRecipes(button, sortKey)" in script
    assert "function applyCookbookRecipeSort(card, sortKey, options = {})" in script
    assert "function compareCookbookSortNumbers(left, right)" in script
    assert "data-cookbook-sort-section-heading" in script
    assert "data-cookbook-menu-price-badge" in script
    assert "Menu Price:" in script
    assert "updateCookbookRecipeSortDecorationVisibility(card);" in script
    assert "restoreCookbookRecipeSortState();" in script
    assert "DEFAULT_COOKBOOK_RECIPE_SORT_STATE" in script
    assert ".cookbook-sort-menu-section [data-cookbook-sort-option][aria-pressed=\"true\"]" in css
    assert ".cookbook-recipe-sort-section-heading" in css
    assert ".cookbook-recipe-menu-price-badge" in css
    assert "#cookbooksCard.cookbooks-hide-ai-inferred .menu-recipe-status-generated" in css
    assert "[data-cookbook-sort-direction=\"desc\"]::before" in css
    assert "content: \"↑\";" in css
    assert "content: \"↓\";" in css
    assert "currentState.direction === \"asc\"" in script
    assert "currentState.direction === \"desc\"" in script
    assert '"menu_section_id"' in read_text("PushShoppingList/services/cookbook_service.py")
    assert 'MISCELLANEOUS_MENU_SECTION = "Miscellaneous"' in read_text("PushShoppingList/services/cookbook_service.py")
    assert "returned to default order" in script


def test_cookbook_submenu_has_selection_and_bulk_move_controls():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")

    menu_start = template.index('<div class="recipe-edit-row-menu cookbook-card-menu" hidden>')
    browser_start = template.index('<div class="cookbook-menu-browser"', menu_start)
    cookbook_menu_block = template[menu_start:browser_start]

    assert '<div class="overflow-menu-section cookbook-selection-menu-section">' in cookbook_menu_block
    assert cookbook_menu_block.index("Menu AI") < cookbook_menu_block.index("Selection")
    assert cookbook_menu_block.index("Selection") < cookbook_menu_block.index("Sort By")
    assert "Select all recipes" in cookbook_menu_block
    assert "Clear selected recipes" in cookbook_menu_block
    assert "Move Selected To" in cookbook_menu_block
    assert "setAllCookbookRecipesSelected(this, true, event)" in cookbook_menu_block
    assert "setAllCookbookRecipesSelected(this, false, event)" in cookbook_menu_block
    assert "moveSelectedCookbookRecipes(this, event)" in cookbook_menu_block
    assert 'data-target-cookbook-id="{{ target_cookbook.id }}"' in cookbook_menu_block
    assert "data-cookbook-recipe-checkbox" in template
    assert 'aria-label="Select {{ recipe.name }}"' in template
    assert "function cookbookRecipeSelectionCheckboxesForCard" in script
    assert "function setAllCookbookRecipesSelected" in script
    assert "function moveSelectedCookbookRecipes" in script
    assert 'submitCookbookApi("/api/cookbooks/move_recipes", formData)' in script
    assert "promptCookbookOverwrite(err.data.conflicts || [], targetCookbookName)" in script


def test_cookbook_submenus_have_food_rule_reapply_controls():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    editor_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    routes = read_text("PushShoppingList/routes/main_routes.py")

    menu_start = template.index('<div class="recipe-edit-row-menu cookbook-card-menu" hidden>')
    browser_start = template.index('<div class="cookbook-menu-browser"', menu_start)
    cookbook_menu_block = template[menu_start:browser_start]
    current_header_menu_start = editor_template.index(
        '<div class="recipe-edit-row-menu recipe-url-log-menu" hidden>'
    )
    current_header_menu_end = editor_template.index(
        '<div class="recipe-url-summary-cookbook-menu-label">Menu AI</div>',
        current_header_menu_start,
    )
    current_header_menu_block = editor_template[current_header_menu_start:current_header_menu_end]

    recipe_menu_start = template.index(
        '<div class="recipe-edit-row-menu overflow-menu cookbook-recipe-menu" hidden>'
    )
    danger_section_start = template.index(
        '<div class="overflow-menu-section recipe-view-menu-section recipe-view-menu-section-danger">',
        recipe_menu_start,
    )
    recipe_menu_block = template[recipe_menu_start:danger_section_start]

    assert "Food Rules" in cookbook_menu_block
    assert "Re-apply Food Rules to Cookbook" in cookbook_menu_block
    assert "reapplyFoodRulesForCookbook(this, event)" in cookbook_menu_block
    assert "Food Rules" in current_header_menu_block
    assert "Re-apply Food Rules to All Current Recipes" in current_header_menu_block
    assert "reapplyFoodRulesForCurrentRecipes(this, event)" in current_header_menu_block
    assert "Re-apply Food Rules to This Recipe" in recipe_menu_block
    assert "reapplyFoodRulesForCookbookRecipe(this, event)" in recipe_menu_block

    current_menu_start = editor_template.index(
        '<div class="recipe-edit-row-menu overflow-menu recipe-url-summary-menu" hidden>'
    )
    current_danger_section_start = editor_template.index(
        '<div class="overflow-menu-section recipe-view-menu-section recipe-view-menu-section-danger">',
        current_menu_start,
    )
    current_menu_block = editor_template[current_menu_start:current_danger_section_start]

    assert "Food Rules" in current_menu_block
    assert "Re-apply Food Rules to This Recipe" in current_menu_block
    assert "reapplyFoodRulesForCurrentRecipe(this, event)" in current_menu_block
    assert current_menu_block.index("Generate Images") < current_menu_block.index("Food Rules")
    assert current_menu_block.index("Food Rules") < current_menu_block.index(">Recipe<")
    assert "Re-apply Food Rules to Ingredients" in editor_template
    assert "reapplyFoodRulesForRecipeIngredients(this)" in editor_template
    assert "Re-apply Food Rules" in script
    assert "function reapplyFoodRulesForCookbook" in script
    assert "function reapplyFoodRulesForCookbookRecipe" in script
    assert "function reapplyFoodRulesForCurrentRecipe" in script
    assert "function reapplyFoodRulesForCurrentRecipes" in script
    assert "function reapplyFoodRulesForRecipeIngredients" in script
    assert "function reapplyFoodRulesForIngredient" in script
    assert "/api/recipes/current/reapply_food_rules" in routes
    assert "/api/cookbooks/<cookbook_id>/reapply_food_rules" in routes
    assert "/api/recipes/reapply_food_rules" in routes


def test_cookbook_recipe_submenu_has_menu_ai_controls_before_recipe_actions():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")

    recipe_menu_start = template.index(
        '<div class="recipe-edit-row-menu overflow-menu cookbook-recipe-menu" hidden>'
    )
    danger_section_start = template.index(
        '<div class="overflow-menu-section recipe-view-menu-section recipe-view-menu-section-danger">',
        recipe_menu_start,
    )
    recipe_menu_block = template[recipe_menu_start:danger_section_start]

    menu_ai_start = recipe_menu_block.index('<div class="overflow-menu-section cookbook-infer-menu-section">')
    recipe_section_start = recipe_menu_block.index(
        '<div class="overflow-menu-section recipe-view-menu-section">',
        menu_ai_start,
    )
    order_section_start = recipe_menu_block.index("Recipe Order", recipe_section_start)
    menu_ai_block = recipe_menu_block[menu_ai_start:recipe_section_start]
    recipe_section_block = recipe_menu_block[recipe_section_start:]

    assert menu_ai_block.index("Menu AI") < menu_ai_block.index("data-cookbook-infer-overwrite")
    assert menu_ai_block.index("data-cookbook-infer-overwrite") < menu_ai_block.index("data-cookbook-infer-preview")
    assert menu_ai_block.index("data-cookbook-infer-preview") < menu_ai_block.index("inferMissingCookbookRecipeDetails")
    assert menu_ai_block.index("inferMissingCookbookRecipeDetails") < menu_ai_block.index("Infer Details for This Recipe")
    assert "Add to current recipes" in recipe_section_block
    assert "Edit recipe" in recipe_section_block
    assert "Move Up" in recipe_section_block
    assert "Move Down" in recipe_section_block
    assert "moveCookbookRecipeFromMenu(this, -1)" in recipe_section_block
    assert "moveCookbookRecipeFromMenu(this, 1)" in recipe_section_block
    assert "Infer Details for This Recipe" not in recipe_section_block
    assert menu_ai_start < recipe_section_start
    assert recipe_section_start < order_section_start
    assert "function moveCookbookRecipeFromMenu" in script
    assert "insertBeforeRecipeUrl: adjacentRecipeUrl" in script
    assert "insertAfterRecipeUrl: adjacentRecipeUrl" in script


def test_cookbook_recipe_infer_button_uses_recipe_editor_inference_flow():
    script = read_text("PushShoppingList/static/js/app.js")
    block = script[
        script.index("async function inferMissingCookbookRecipeDetails"):
        script.index("function updateCookbookMoveButton")
    ]

    assert "cookbookInferOverwriteEnabled(button)" in block
    assert "cookbookInferPreviewEnabled(button)" in block
    assert "await openRecipeEditor(button, {" in block
    assert "inferMissingDetails: true" in block
    assert "cookbookId" in block
    assert "cookbookName" in block
    assert "overwriteAiFields" in block
    assert "previewOnly" in block
    assert 'fetch("/api/recipe/infer_missing_details"' not in block


def test_recipe_editor_cookbook_dropdown_updates_portaled_menu_options():
    script = read_text("PushShoppingList/static/js/app.js")
    editor_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")
    action_data_block = script[
        script.index("function recipeLogCookbookActionData"):
        script.index("async function moveRecipeUrlToCookbook")
    ]
    cookbook_setter_block = script[
        script.index("function setRecipeEditorCookbook"):
        script.index("function updateRecipeEditorPdfControls")
    ]

    assert "recipeEditMenuAnchorButtonFromButton(button)" in action_data_block
    assert 'anchorButton.closest(".recipe-url-summary-row, .recipe-view-card, .recipe-edit-cookbook-field")' in action_data_block
    assert "function recipeEditorCookbookMenus" in cookbook_setter_block
    assert '.recipe-edit-cookbook-menu[data-recipe-edit-portaled=\'1\']' in cookbook_setter_block
    assert 'menu.recipeEditAnchorButton.closest("#recipeEditCookbookField")' in cookbook_setter_block
    assert 'recipeEditorCookbookMenuButtons(field, "[data-recipe-edit-cookbook-action]")' in cookbook_setter_block
    assert 'recipeEditorCookbookMenuButtons(field, "[data-recipe-edit-cookbook-option]")' in cookbook_setter_block
    assert 'recipeEditorCookbookMenuButtons(field, "[data-recipe-edit-cookbook-delete]")' in cookbook_setter_block
    assert "data-recipe-edit-menu-section-row" in editor_template
    assert "data-recipe-edit-menu-section-move" in editor_template
    assert "moveRecipeEditMenuSection(this, -1)" in editor_template
    assert "moveRecipeEditMenuSection(this, 1)" in editor_template
    assert "function createRecipeEditorMenuSectionOptionRow" in script
    assert "function reorderRecipeEditorMenuSectionRows" in script
    assert "function updateCookbookMenuSectionOrderData" in script
    assert "function moveRecipeEditMenuSection" in script
    assert 'formData.set("menu_section", section)' in script
    assert '`/api/cookbooks/${encodeURIComponent(cookbookId)}/menu_sections/reorder`' in script
    assert "data-cookbook-menu-section-order" in read_text("PushShoppingList/templates/sections/cookbooks.html")
    assert "dataset.cookbookMenuSectionOrder" in script
    assert ".recipe-edit-menu-section-option-row" in css
    assert ".recipe-edit-menu-section-order-btn" in css


def test_cookbook_recipe_rows_match_current_recipe_summary_layout():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    css = read_text("PushShoppingList/static/css/app.css")

    recipe_card_start = template.index("data-cookbook-recipe-card")
    title_line_start = template.index(
        '<span class="recipe-url-summary-title-line">',
        recipe_card_start,
    )
    summary_body_index = template.index(
        '<div class="recipe-url-summary-body">',
        title_line_start,
    )
    meta_index = template.index(
        '<div class="recipe-url-summary-meta">',
        summary_body_index,
    )
    servings_index = template.index(
        '<div class="recipe-url-summary-servings">',
        meta_index,
    )
    title_block = template[title_line_start:summary_body_index]
    meta_block = template[meta_index:servings_index]
    status_row_index = title_block.index("recipe-url-summary-status-row cookbook-recipe-status-row")

    assert title_block.index("menu-recipe-status-stub") < title_block.index("recipe-url-summary-food-review")
    assert title_block.index("menu-recipe-status-generated") < title_block.index("recipe-url-summary-food-review")
    assert title_block.index("recipe-url-summary-food-review") < title_block.index("Generate Fast Recipe")
    assert title_block.index("Generate Fast Recipe") < title_block.index("Generate Fast Section")
    assert title_block.index("Generate Fast Section") < title_block.index("Generate Full Section")
    assert title_block.index("Generate Full Section") < title_block.index("View Mega Menu JSON")
    assert status_row_index < title_block.index("View Mega Menu JSON")
    assert "recipe-url-summary-food-review-collapsed" not in title_block
    assert "recipe-url-summary-food-review-row" not in template
    assert "cookbook-recipe-menu-status" not in template
    assert "menu-recipe-status-badge" not in meta_block
    assert ".recipe-url-summary-status-row" in css
    assert "#cookbooksCard .cookbook-recipe-card .recipe-url-summary-food-review-collapsed" not in css
    assert "recipe-url-summary-row" in template
    assert 'class="recipe-url-summary-header"' in template
    assert 'class="recipe-batch-select cookbook-restore-checkbox cookbook-recipe-restore-checkbox"' in template
    assert 'class="recipe-url-summary-actions cookbook-recipe-actions"' in template
    assert "display: grid;\n                grid-template-columns: minmax(0, 1fr) auto;" not in css
    assert "justify-content: flex-end;\n                width: 100%;\n                margin-left: auto;" not in css
    assert "#cookbooksCard .cookbook-recipe-card .recipe-url-summary-title-line" in css
    assert "#cookbooksCard .cookbook-recipe-card .recipe-url-summary-number,\n    #cookbooksCard .cookbook-recipe-card .recipe-url-summary-name" in css
    assert "#cookbooksCard .cookbook-recipe-card .recipe-url-summary-body,\n    #cookbooksCard .cookbook-recipe-card .recipe-url-summary-main,\n    #cookbooksCard .cookbook-recipe-card .recipe-url-summary-meta" in css
    assert "#cookbooksCard .cookbook-recipe-actions .recipe-url-summary-menu-wrap,\n    #cookbooksCard .cookbook-recipe-actions .cookbook-recipe-menu-wrap" in css
    cookbook_mobile_start = css.index(
        "@media (max-width: 650px)",
        css.index(".cookbook-recipe-card.recipe-url-summary-row"),
    )
    cookbook_mobile_end = css.index(".admin-support-card", cookbook_mobile_start)
    cookbook_mobile_block = css[cookbook_mobile_start:cookbook_mobile_end]

    assert "grid-template-columns: 18px 28px minmax(0, 1fr);" in cookbook_mobile_block
    assert (
        "#cookbooksCard .cookbook-recipe-card .cookbook-recipe-restore-checkbox {\n"
        "        grid-column: 1;\n"
        "        grid-row: 1;"
    ) in cookbook_mobile_block
    assert (
        "#cookbooksCard .cookbook-recipe-card .cookbook-recipe-drag-handle {\n"
        "        grid-column: 2;\n"
        "        grid-row: 1;"
    ) in cookbook_mobile_block
    assert (
        "#cookbooksCard .cookbook-recipe-summary-title {\n"
        "        grid-column: 3;\n"
        "        grid-row: 1;"
    ) in cookbook_mobile_block
    assert (
        "#cookbooksCard .cookbook-recipe-actions.recipe-url-summary-actions {\n"
        "        grid-column: 3;\n"
        "        grid-row: 1;"
    ) in cookbook_mobile_block
    assert (
        "#cookbooksCard .cookbook-recipe-actions .recipe-url-summary-menu-wrap,\n"
        "    #cookbooksCard .cookbook-recipe-actions .cookbook-recipe-menu-wrap {\n"
        "        position: absolute;\n"
        "        top: 10px;"
    ) in cookbook_mobile_block


def test_cookbook_recipe_view_renders_menu_stub_actions_above_amount():
    app = create_app()
    app.config.update(TESTING=True)

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "vel-asain-cuisine",
                    "name": "Vel Asain Cuisine",
                    "recipes": [
                        {
                            "url": "menu-item://vel-asain-cuisine/spring-roll",
                            "source_href": "https://example.com/menu#spring-roll",
                            "source_display_url": "Vel Asain Cuisine menu",
                            "name": "Spring Roll",
                            "number": 5,
                            "quantity": 1,
                            "needs_ai_recipe": True,
                            "source_type": "menu_item_stub",
                            "menu_section": "Appetizers",
                            "menu_section_id": "section-003",
                            "parent_menu_snapshot_id": "mega-menu-1",
                        },
                    ],
                },
            ],
        })
        view = main_routes.cookbook_view_for_render([])
        for cookbook in view["cookbooks"]:
            cookbook.setdefault("menu_pdf_logs", [])
            cookbook.setdefault("restaurant_menus", [])

        with app.test_request_context("/"):
            html = render_template(
                "sections/cookbooks.html",
                cookbook_view=view,
                cookbook_count=len(view["cookbooks"]),
                cookbook_recipe_count=sum(len(cookbook["recipes"]) for cookbook in view["cookbooks"]),
            )

    recipe_card_start = html.index("data-cookbook-recipe-card")
    article_start = html.rfind("<article", 0, recipe_card_start)
    article_end = html.index("</article>", recipe_card_start)
    card_html = html[article_start:article_end]
    assert 'data-recipe-url="menu-item://vel-asain-cuisine/spring-roll"' in card_html
    title_line_start = card_html.index('<span class="recipe-url-summary-title-line">')
    summary_body_index = card_html.index('<div class="recipe-url-summary-body">')
    amount_index = card_html.index('<div class="recipe-url-summary-amount">')
    cookbook_index = card_html.index('<div class="recipe-url-summary-cookbook">')
    title_block = card_html[title_line_start:summary_body_index]
    meta_before_amount_block = card_html[summary_body_index:amount_index]

    assert "Spring Roll" in title_block
    assert "recipe-url-summary-status-row cookbook-recipe-status-row" in title_block
    assert title_block.index("menu-recipe-status-stub") < title_block.index("Generate Fast Recipe")
    assert title_block.index("Generate Fast Recipe") < title_block.index("Generate Fast Section")
    assert title_block.index("Generate Fast Section") < title_block.index("Generate Full Section")
    assert title_block.index("Generate Full Section") < title_block.index("View Mega Menu JSON")
    assert "menu-recipe-status-stub" not in meta_before_amount_block
    assert summary_body_index < amount_index < cookbook_index
    assert 'data-cookbook-menu-section-id="section-003"' in card_html
    assert "Vel Asain Cuisine" in card_html[cookbook_index:]


def test_uploaded_recipe_without_archive_pdf_does_not_render_dead_source_link(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    recipe_url = "uploaded://meal.png"
    recipe_data = {
        "source_url": recipe_url,
        "recipe_title": "Photo Rice Bowl",
        "ingredients": [{"ingredient": "rice"}],
        "instructions": [{"instruction": "Serve."}],
        "nutrition": {},
    }

    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda url: recipe_data if url == recipe_url else {})
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(main_routes, "recipe_archive_pdf_exists", lambda *args, **kwargs: False)
    monkeypatch.setattr(main_routes, "recipe_pdf_public_url", lambda *args, **kwargs: "")

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [{
                "id": "unclassified",
                "name": "unclassified",
                "recipes": [{
                    "url": recipe_url,
                    "name": "Photo Rice Bowl",
                    "source_href": recipe_url,
                    "source_display_url": recipe_url,
                }],
            }],
        })

        with app.test_request_context("/"):
            recipe_rows = main_routes.recipe_view_rows([{"url": recipe_url, "name": "Photo Rice Bowl"}])
            log_rows = main_routes.recipe_url_log_rows([{"url": recipe_url, "name": "Photo Rice Bowl", "quantity": 1}])
            view = main_routes.cookbook_view_for_render([])
            html = render_template(
                "sections/cookbooks.html",
                cookbook_view=view,
                cookbook_count=len(view["cookbooks"]),
                cookbook_recipe_count=sum(len(cookbook["recipes"]) for cookbook in view["cookbooks"]),
            )

    assert main_routes.recipe_source_href(recipe_url) == ""
    assert main_routes.recipe_source_display_url(recipe_url) == "Uploaded file: meal.png"
    assert recipe_rows[0]["source_href"] == ""
    assert log_rows[0]["source_href"] == ""
    assert view["cookbooks"][0]["recipes"][0]["source_href"] == ""
    assert view["cookbooks"][0]["recipes"][0]["source_display_url"] == "Uploaded file: meal.png"
    assert 'href="uploaded://meal.png"' not in html
    assert 'class="recipe-url-summary-name recipe-url-summary-name-link"' not in html
    assert "Photo Rice Bowl" in html


def test_cookbook_view_uses_saved_metadata_cover_image_when_cookbook_row_lacks_one(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    recipe_url = (
        "https://www.velasiancuisine.com/rs/menu_home.action"
        "?resInput=RES4902&menu_item=menu-item-1-Spring_Roll"
    )
    recipe_data = {
        "source_url": recipe_url,
        "recipe_title": "Spring Roll",
        "cover_image": {},
        "ingredients": [{"ingredient": "spring roll wrappers"}],
        "instructions": [{"instruction": "Fill and fry."}],
        "nutrition": {},
    }
    metadata = {
        main_routes.normalize_recipe_url_key(recipe_url): {
            "cover_image": {
                "path": "data/uploads/recipe_covers/spring-roll.png",
                "alt": "Spring Roll",
                "source": "ai_generated_image",
                "mime_type": "image/png",
            }
        }
    }

    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda url: recipe_data if url == recipe_url else {})
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: metadata)
    monkeypatch.setattr(main_routes, "recipe_archive_pdf_exists", lambda *args, **kwargs: False)
    monkeypatch.setattr(main_routes, "recipe_pdf_public_url", lambda *args, **kwargs: "")

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [{
                "id": "vel-asian-cuisine",
                "name": "Vel Asian Cuisine",
                "recipes": [{
                    "url": recipe_url,
                    "name": "Spring Roll",
                    "source_type": "menu_item_inferred",
                    "ai_inferred": True,
                }],
            }],
        })

        with app.test_request_context("/"):
            view = main_routes.cookbook_view_for_render([], image_variants=("thumb", "card"))
            html = render_template(
                "sections/cookbooks.html",
                cookbook_view=view,
                cookbook_count=len(view["cookbooks"]),
                cookbook_recipe_count=sum(len(cookbook["recipes"]) for cookbook in view["cookbooks"]),
            )

    recipe = view["cookbooks"][0]["recipes"][0]
    assert recipe["cover_image"]["alt"] == "Spring Roll"
    assert recipe["cover_image"]["src"].startswith("/recipe_cover_image?url=")
    assert "recipe-url-summary-row-with-cover" in html
    assert 'data-deferred-src="/recipe_cover_image?url=' in html


def test_cookbook_view_generated_recipe_clears_stale_stub_state(monkeypatch):
    recipe_url = "menu-item://vel-asain-cuisine/spring-roll"
    generated_recipe = {
        "source_url": recipe_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "needs_ai_recipe": False,
        "recipe_status": "generated",
        "recipe_title": "Spring Roll",
        "servings": "2 servings",
        "ingredients": [{"ingredient": "spring roll wrappers", "quantity": "2"}],
        "instructions": [{"instruction": "Fill and fry."}],
        "nutrition": {},
    }

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "vel-asain-cuisine",
                    "name": "Vel Asain Cuisine",
                    "recipes": [
                        {
                            "url": recipe_url,
                            "name": "Spring Roll",
                            "needs_ai_recipe": True,
                            "source_type": "menu_item_stub",
                            "recipe_status": "stub",
                        },
                    ],
                },
            ],
        })
        monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda url: generated_recipe if url == recipe_url else {})
        monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: {})

        view = main_routes.cookbook_view_for_render([])

    recipe = view["cookbooks"][0]["recipes"][0]
    assert recipe["source_type"] == "menu_item_inferred"
    assert recipe["recipe_status"] == "generated"
    assert recipe["needs_ai_recipe"] is False


def test_menu_import_failure_status_reaches_recipe_and_cookbook_rows(monkeypatch):
    recipe_url = "menu-item://vel-asain-cuisine/crab-wonton"
    failed_recipe = {
        "source_url": recipe_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "recipe_status": "generated",
        "recipe_title": "Crab Wonton",
        "menu_import_failed": True,
        "menu_import_failures": [{
            "stage": "Nutrition",
            "error": "Unable to estimate serving basis.",
        }],
        "ingredients": [{"ingredient": "cream cheese"}],
        "instructions": [{"instruction": "Fill and fry."}],
        "nutrition": {},
    }
    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda url: failed_recipe if url == recipe_url else {})
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: {})

    recipe_rows = main_routes.recipe_view_rows([{"url": recipe_url, "name": "Crab Wonton"}])
    log_rows = main_routes.recipe_url_log_rows([{"url": recipe_url, "name": "Crab Wonton", "quantity": 1}])

    assert recipe_rows[0]["import_failure_status"]["failed"] is True
    assert recipe_rows[0]["import_failure_status"]["label"] == "Failed: Nutrition"
    assert "Unable to estimate serving basis." in log_rows[0]["import_failure_status"]["title"]

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [{
                "id": "vel-asain-cuisine",
                "name": "Vel Asain Cuisine",
                "recipes": [{"url": recipe_url, "name": "Crab Wonton"}],
            }],
        })
        view = main_routes.cookbook_view_for_render([])

    cookbook_recipe = view["cookbooks"][0]["recipes"][0]
    assert cookbook_recipe["import_failure_status"]["failed"] is True
    assert cookbook_recipe["import_failure_status"]["stage"] == "Nutrition"


def test_unclassified_cookbook_menu_keeps_cookbook_management_protected():
    app = create_app()
    app.config.update(TESTING=True)

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "unclassified",
                    "name": "unclassified",
                    "recipes": [{"url": "https://example.com/loose", "name": "Loose Soup"}],
                },
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [{"url": "https://example.com/chili", "name": "Chili"}],
                },
            ],
        })
        view = cookbook_service.cookbook_view([])
        for cookbook in view["cookbooks"]:
            cookbook.setdefault("menu_pdf_logs", [])
            cookbook.setdefault("restaurant_menus", [])

        with app.test_request_context("/"):
            html = render_template(
                "sections/cookbooks.html",
                cookbook_view=view,
                cookbook_count=len(view["cookbooks"]),
                cookbook_recipe_count=sum(len(cookbook["recipes"]) for cookbook in view["cookbooks"]),
            )

    def card_header(cookbook_id):
        marker = f'data-cookbook-id="{cookbook_id}"'
        marker_index = html.index(marker)
        start = html.rfind("<article", 0, marker_index)
        end = html.index('<div class="cookbook-card-body"', marker_index)
        return html[start:end]

    unclassified_header = card_header("unclassified")
    dinner_header = card_header("dinner")

    assert 'data-cookbook-unclassified="1"' in unclassified_header
    assert "Rename cookbook" not in unclassified_header
    assert "Delete cookbook, keep recipes" not in unclassified_header
    assert "Delete cookbook and purge recipes" not in unclassified_header
    assert "deleteCookbook(this)" not in unclassified_header
    assert "purgeCookbook(this)" not in unclassified_header
    assert "Remove selected recipes" in unclassified_header
    assert "Purge selected recipes" in unclassified_header
    assert "Purge all unclassified recipes" in unclassified_header

    assert 'data-cookbook-unclassified="0"' in dinner_header
    assert "Rename cookbook" in dinner_header
    assert "Delete selected recipes" in dinner_header
    assert "Delete and purge all recipes" in dinner_header
    assert "Delete cookbook, keep recipes" in dinner_header
    assert "Delete cookbook and purge recipes" in dinner_header


def test_remove_selected_cookbook_recipes_moves_them_to_unclassified():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [
                        {"url": "https://example.com/chili", "name": "Chili"},
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
                {"id": "unclassified", "name": "unclassified", "recipes": []},
            ],
        })

        removed_urls = cookbook_service.remove_recipes_from_cookbook(
            "dinner",
            ["https://example.com/soup"],
        )
        payload = cookbook_service.load_cookbooks()

    dinner = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "dinner")
    unclassified = next(
        cookbook
        for cookbook in payload["cookbooks"]
        if cookbook["name"] == "unclassified"
    )

    assert removed_urls == ["https://example.com/soup"]
    assert [recipe["url"] for recipe in dinner["recipes"]] == ["https://example.com/chili"]
    assert [recipe["url"] for recipe in unclassified["recipes"]] == ["https://example.com/soup"]


def test_purge_selected_cookbook_recipes_removes_them_from_all_cookbooks():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [
                        {"url": "https://example.com/chili", "name": "Chili"},
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
                {
                    "id": "favorites",
                    "name": "Favorites",
                    "recipes": [
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
            ],
        })

        purged_urls = cookbook_service.purge_selected_cookbook_recipe_urls(
            "dinner",
            ["https://example.com/soup"],
        )
        payload = cookbook_service.load_cookbooks()

    dinner = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "dinner")
    favorites = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "favorites")

    assert purged_urls == ["https://example.com/soup"]
    assert [recipe["url"] for recipe in dinner["recipes"]] == ["https://example.com/chili"]
    assert favorites["recipes"] == []


def test_cookbook_menu_metadata_uses_saved_values_without_render_inference():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        recipe_rows = [{
            "name": "Chicken Alfredo",
            "url": "https://example.com/chicken-alfredo",
            "description": "Creamy pasta dinner with chicken.",
            "prep_time": "20 min",
            "cook_time": "25 min",
            "base_servings": "4 servings",
            "instruction_items": ["Cook the fettuccine and simmer the chicken in a skillet."],
            "sections": {
                "MISC": [
                    {"name": "chicken breast", "display_name": "chicken breast"},
                    {"name": "fettuccine pasta", "display_name": "fettuccine pasta"},
                    {"name": "parmesan cheese", "display_name": "parmesan cheese"},
                ],
            },
        }]

        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/chicken-alfredo"],
            recipe_rows,
        )

        stored_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]
        assert stored_recipe["meal_type"] == ""
        assert stored_recipe["category_metadata_user_set"] is False

        view = cookbook_service.cookbook_view([])
        dinner = view["cookbooks"][0]
        recipe = dinner["recipes"][0]

        assert recipe["main_ingredient"] == ""
        assert recipe["cuisine"] == ""
        assert recipe["meal_type"] == ""
        assert recipe["restaurant_menu_category"] == ""
        assert recipe["prep_time_group"] == ""
        assert recipe["category_metadata_source"] == "Blank"
        assert recipe["category_metadata_sources"]["main_ingredient"] == "blank"
        assert "🇮🇹 Italian" not in recipe["menu_tags"]
        assert "fettuccine pasta" in recipe["menu_search_text"]

        restaurant_fallback_section = next(
            section
            for section in dinner["menu_sections"]["restaurant_menu"]
            if section["label"] == "🍽️ Other Recipes"
        )
        assert restaurant_fallback_section["recipes"][0]["name"] == "Chicken Alfredo"


def test_cookbook_recipe_move_can_insert_before_and_after_saved_recipes():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        recipe_rows = [
            {"name": "Alpha", "url": "https://example.com/alpha"},
            {"name": "Bravo", "url": "https://example.com/bravo"},
            {"name": "Charlie", "url": "https://example.com/charlie"},
        ]

        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            [recipe["url"] for recipe in recipe_rows],
            recipe_rows,
        )
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/charlie"],
            recipe_rows,
            overwrite_existing=True,
            insert_before_recipe_url="https://example.com/bravo",
        )
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/alpha"],
            recipe_rows,
            overwrite_existing=True,
            insert_after_recipe_url="https://example.com/bravo",
        )

        saved = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"]

    assert [recipe["url"] for recipe in saved] == [
        "https://example.com/charlie",
        "https://example.com/bravo",
        "https://example.com/alpha",
    ]


def test_cookbook_menu_section_order_can_be_saved_and_rendered():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [{
                "id": "dinner",
                "name": "Dinner",
                "recipes": [
                    {
                        "url": "https://example.com/dumpling",
                        "name": "Dumpling",
                        "menu_section": "Kitchen Appetizers",
                    },
                    {
                        "url": "https://example.com/ramen",
                        "name": "Ramen",
                        "menu_section": "Ramen",
                    },
                    {
                        "url": "https://example.com/mochi",
                        "name": "Mochi",
                        "menu_section": "Dessert",
                    },
                ],
            }],
        })

        saved = cookbook_service.load_cookbooks()
        assert saved["cookbooks"][0]["menu_section_order"] == [
            "Kitchen Appetizers",
            "Ramen",
            "Dessert",
        ]

        section_order = cookbook_service.reorder_cookbook_menu_section(
            "dinner",
            "Ramen",
            -1,
        )
        view = cookbook_service.cookbook_view([])

    dinner = view["cookbooks"][0]
    recipes_by_name = {
        recipe["name"]: recipe
        for recipe in dinner["recipes"]
    }

    assert section_order == ["Ramen", "Kitchen Appetizers", "Dessert"]
    assert dinner["menu_section_choices"] == ["Ramen", "Kitchen Appetizers", "Dessert"]
    assert recipes_by_name["Ramen"]["menu_section_order"] == 0
    assert recipes_by_name["Dumpling"]["menu_section_order"] == 1
    assert recipes_by_name["Mochi"]["menu_section_order"] == 2


def test_cookbook_menu_section_blank_falls_back_to_miscellaneous():
    sections = cookbook_service.cookbook_menu_sections([
        {
            "url": "https://example.com/chicken-alfredo",
            "name": "Chicken Alfredo",
            "menu_section": "",
        }
    ])

    menu_section = next(
        section
        for section in sections["menu_section"]
        if section["label"] == "Miscellaneous"
    )

    assert menu_section["recipes"][0]["name"] == "Chicken Alfredo"


def test_cookbook_category_update_requires_confirmation_before_overwriting_manual_values():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/margarita"],
            [{"name": "Margarita", "url": "https://example.com/margarita"}],
        )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/margarita",
            {
                "meal_type": "🍹 Drink",
                "cuisine": "🇲🇽 Mexican",
                "custom_categories": "☀️ Summer BBQ",
            },
        )

        with pytest.raises(cookbook_service.CookbookCategoryOverwriteConflict):
            cookbook_service.update_cookbook_recipe_categories(
                "dinner",
                "https://example.com/margarita",
                {
                    "meal_type": "🍹 Drink",
                    "cuisine": "🌍 Other / Fusion",
                    "custom_categories": "🧪 Things We Want To Try",
                },
            )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/margarita",
            {
                "meal_type": "🍹 Drink",
                "cuisine": "🌍 Other / Fusion",
                "custom_categories": "🧪 Things We Want To Try",
            },
            confirm_overwrite=True,
        )

        saved_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]
        assert saved_recipe["category_metadata_user_set"] is True
        assert saved_recipe["cuisine"] == "🌍 Other / Fusion"
        assert saved_recipe["custom_categories"] == ["🧪 Things We Want To Try"]
        assert saved_recipe["category_metadata_sources"]["cuisine"] == "user_selected"
        assert saved_recipe["category_metadata_sources"]["custom_categories"] == "user_selected"


def test_cookbook_category_update_can_fill_blank_categories_when_menu_section_exists():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/huancaina"],
            [{"name": "Papa a la Huancaina", "url": "https://example.com/huancaina"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/huancaina",
            {"menu_section": "Appetizers"},
        )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/huancaina",
            {
                "meal_type": "🍽️ Appetizer / Snack",
                "cuisine": "🇵🇪 Peruvian",
                "custom_categories": "Restaurant Favorites",
            },
            category_sources={
                "meal_type": cookbook_service.CATEGORY_SOURCE_AI_INFERRED,
                "cuisine": cookbook_service.CATEGORY_SOURCE_AI_INFERRED,
                "custom_categories": cookbook_service.CATEGORY_SOURCE_AI_INFERRED,
            },
        )

        saved_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]
        assert saved_recipe["menu_section"] == "Appetizers"
        assert saved_recipe["meal_type"] == "🍽️ Appetizer / Snack"
        assert saved_recipe["cuisine"] == "🇵🇪 Peruvian"
        assert saved_recipe["custom_categories"] == ["Restaurant Favorites"]
        assert saved_recipe["category_metadata_sources"]["meal_type"] == "ai_inferred"
        assert saved_recipe["category_metadata_sources"]["cuisine"] == "ai_inferred"
        assert saved_recipe["category_metadata_sources"]["custom_categories"] == "ai_inferred"
