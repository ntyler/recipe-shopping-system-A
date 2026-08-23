import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from PushShoppingList.app import create_app
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


ROOT = Path(__file__).resolve().parents[1]


def javascript_function_source(script, function_name):
    """Extract one top-level JavaScript function for a focused Node harness."""
    marker = f"function {function_name}("
    start = script.index(marker)
    parameter_start = script.index("(", start)
    parameter_depth = 0
    parameter_quote = None
    parameter_escaped = False
    parameter_end = None
    for index in range(parameter_start, len(script)):
        character = script[index]
        if parameter_quote:
            if parameter_escaped:
                parameter_escaped = False
            elif character == "\\":
                parameter_escaped = True
            elif character == parameter_quote:
                parameter_quote = None
            continue
        if character in "'\"`":
            parameter_quote = character
        elif character == "(":
            parameter_depth += 1
        elif character == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                parameter_end = index
                break
    if parameter_end is None:
        raise AssertionError(f"Could not parse parameters for JavaScript function {function_name}")
    body_start = script.index("{", parameter_end)
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    index = body_start
    while index < len(script):
        character = script[index]
        following = script[index + 1] if index + 1 < len(script) else ""
        if line_comment:
            if character in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if character == "*" and following == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if character == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        if character == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        if character in "'\"`":
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return script[start:index + 1]
        index += 1
    raise AssertionError(f"Could not extract JavaScript function {function_name}")


def test_ingredients_header_has_image_overflow_menu():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    ingredient_section_start = template.index("recipe-edit-ingredients-section")
    equipment_section_start = template.index("recipe-edit-equipment-section")
    ingredient_section = template[ingredient_section_start:equipment_section_start]
    actions_start = ingredient_section.index("recipe-edit-ingredient-actions")
    menu_start = ingredient_section.index("recipe-edit-ingredients-menu-wrap")
    toolbar_markup = ingredient_section[actions_start:menu_start]

    assert "recipe-edit-ingredients-menu-wrap" in ingredient_section
    assert "recipe-edit-ingredients-image-menu" in ingredient_section
    assert "Generate Images" in ingredient_section
    assert "Regenerate Ingredients" in ingredient_section
    assert "Sort Ingredients" in ingredient_section
    assert "By Ingredient Name" in ingredient_section
    assert "By Store Section" in ingredient_section
    assert "Show or Hide Images" not in ingredient_section
    assert "Show ingredient images" not in ingredient_section
    assert "Hide ingredient images" not in ingredient_section
    assert "Thumbnail Size" in ingredient_section
    assert ingredient_section.index("Generate Images") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Regenerate Ingredients") < ingredient_section.index("Food Rules")
    assert ingredient_section.index("Food Rules") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Sort Ingredients") < ingredient_section.index("Thumbnail Size")
    assert "generateRecipeImagesFromEditor(this, { imageScope: 'ingredients' })" in ingredient_section
    assert "generateRecipeImagesFromEditor(this, { missingOnly: true, imageScope: 'ingredients' })" in ingredient_section
    assert "regenerateRecipeIngredientsSection(this)" in ingredient_section
    assert "autoSortRecipeIngredients('ingredient')" in ingredient_section
    assert "autoSortRecipeIngredients('store_section')" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'ingredients' })" not in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'ingredients' })" not in ingredient_section
    assert "data-recipe-thumbnail-size-decrease" in ingredient_section
    assert "changeRecipeImageThumbnailSize(this, -1)" in ingredient_section
    assert "data-recipe-thumbnail-size-value" in ingredient_section
    assert "changeRecipeImageThumbnailSize(this, 1)" in ingredient_section
    assert "resetRecipeImageThumbnailSize(this)" in ingredient_section
    assert "Auto Sort" not in toolbar_markup
    assert ".recipe-edit-ingredients-image-menu" in css
    assert ".recipe-edit-thumbnail-size-controls" in css
    assert "function autoSortRecipeIngredients(mode = \"ingredient\")" in script
    assert "async function regenerateRecipeIngredientsSection(button)" in script
    assert "\"/api/recipe/regenerate_ingredients\"" in script
    assert "replaceRecipeEditorIngredients(data.ingredients" in script
    assert "const sortMode = mode === \"store_section\" ? \"store_section\" : \"ingredient\";" in script
    assert "function recipeIngredientSortKey(value)" in script
    assert "closeRecipeEditRowMenus();" in script
    assert "recipe-edit-extraction-warning" in script
    assert 'data-field="parsed_name"' in script
    assert 'data-field="normalized_name"' in script
    assert 'data-field="confidence"' in script
    assert 'data-field="inferred"' in script
    assert 'data-field="warning"' in script
    assert "Use this section for all future occurrences" in script
    assert 'data-field="store_section_source"' in script
    assert 'data-field="store_section_confidence"' in script
    assert 'data-field="store_section_user_confirmed"' in script
    assert 'data-field="classifier_version"' in script
    assert "function useRecipeIngredientStoreSectionForFuture(button)" in script
    assert "data-ingredient-warning-message" in script
    assert "recipeIngredientFoodReviewPayload(row)" in script
    assert "Accept Fix" in script
    assert "ignoreFoodReviewIssue" in script
    assert "editFoodReviewManually" in script


def test_recipe_editor_header_omits_global_image_visibility_but_keeps_section_controls():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    menu_start = template.index("recipe-edit-header-image-menu")
    menu_end = template.index(
        '<button type="button" class="recipe-edit-cancel recipe-edit-header-cancel"',
        menu_start,
    )
    header_menu = template[menu_start:menu_end]

    assert "Show or Hide Images" not in header_menu
    assert "Show all recipe images by default" not in header_menu
    assert "Show all recipe images" not in header_menu
    assert "Hide all recipe images" not in header_menu
    assert "setRecipeEditorImagesVisibleFromMenu" not in header_menu

    assert "setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'equipment' })" in template
    assert "setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'equipment' })" in template
    assert "setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'instructions' })" in template
    assert "setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'instructions' })" in template


def test_recipe_editor_ingredient_alternatives_are_wired_without_changing_collection_shape():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]
    collect_start = script.index("function collectRecipeIngredientRows")
    collect_end = script.index("function collectRecipeNutritionRows", collect_start)
    collect_block = script[collect_start:collect_end]

    assert "function recipeIngredientSubstitutionRows(item = {})" in script
    assert "function recipeIngredientSubstitutions(item = {})" in script
    assert "function recipeIngredientSubstitutionOptionRowHtml(option = {}, index = 0, group = {})" in script
    assert "recipe-edit-ingredient-substitutions" in row_block
    assert "recipe-edit-substitution-option-row recipe-edit-ingredient-row" in script
    assert "data-ingredient-substitution-list" in row_block
    assert "data-ingredient-substitution-title" in row_block
    assert "Alternatives" in row_block
    assert "Add another option" in row_block
    assert "Add alternative" in row_block
    assert ">Substitutions<" not in row_block
    assert 'data-field="substitutions_text"' not in row_block
    assert "bindRecipeIngredientSubstitutionRows(row);" in row_block
    assert "data-ingredient-substitution-count" in row_block
    assert 'badges.push([`${substitutionCount} alternative group${substitutionCount === 1 ? "" : "s"}`, "substitution"]);' in script
    assert "function recipeEditIngredientRows()" in script
    assert "function collectRecipeIngredientSubstitutionRows(row)" in script
    assert "item.substitutions = collectRecipeIngredientSubstitutionRows(row);" in collect_block
    assert "delete item.substitutions_text;" in collect_block
    assert "const optionRow = input.closest(\"[data-substitution-option-row]\");" in script
    assert ".recipe-edit-ingredient-substitutions" in css
    assert ".recipe-edit-substitution-list" in css
    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-alternative-card" in v10
    assert ".recipe-edit-alternative-component" in v10
    assert ".recipe-edit-substitution-table-head" in v10
    assert "display: none !important;" in v10
    assert ".recipe-edit-ingredient-badge.substitution" in css
    assert ".recipe-edit-row-collapsed .recipe-edit-ingredient-substitutions" in css


def test_recipe_editor_match_column_only_surfaces_attention_states():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    badges_start = script.index("function recipeIngredientBadgesHtml")
    badges_end = script.index("function recipeIngredientStoreSectionIconName", badges_start)
    badges = script[badges_start:badges_end]
    assert 'badges.push(["Best Match", "best"]);' not in badges
    assert "const match = recipeIngredientMatchDetails(item);" in badges
    for status in (
        "Review Match",
        "Low Confidence",
        "Multiple Matches",
        "Unmatched",
        "Pantry Staple",
        "Optional",
    ):
        assert status in badges
    assert 'badges.push([`${substitutionCount} alternative group${substitutionCount === 1 ? "" : "s"}`, "substitution"]);' in badges

    details_start = script.index("function recipeIngredientMatchDetails(item = {})")
    details_end = script.index("function recipeIngredientBadgesHtml", details_start)
    details = script[details_start:details_end]
    assert "confidence.percent < 60" in details
    assert "confidence.percent < 80" in details
    assert "ingredient && !hasMasterMatch" in details
    assert "!hasExplicitBestStatus" in details
    assert 'attentionStatus = "Multiple Matches";' in details
    assert 'attentionStatus = "Unmatched";' in details
    assert "isBestAvailable" in details
    for label in (
        "Selected matched ingredient",
        "Match confidence",
        "Best available match",
        "Alternative matches",
        "Source / matching reason",
    ):
        assert label.lower() in details.lower()

    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]
    assert "row.dataset.ingredientMatchDetails = JSON.stringify(recipeIngredientMatchSnapshot(item));" in row_block
    assert "hidden>Review Match</span>" in row_block

    summary_start = script.index("function updateRecipeIngredientSummary")
    summary_end = script.index("function recipeEditIngredientRows", summary_start)
    summary = script[summary_start:summary_end]
    assert "const matchItem = recipeIngredientMatchItemFromRow(row, values);" in summary
    assert "recipeIngredientBadgesHtml(matchItem, { maxVisible: 2 })" in summary
    assert "recipeIngredientMatchDetailsHtml(modalMatchItem)" in summary
    assert 'row.querySelector(":scope > [data-recipe-ingredient-edit-panel]")' in summary
    assert (
        'editPanel.querySelector(".recipe-edit-ingredient-match-details[data-ingredient-match-details]")'
        in summary
    )
    assert 'row ? row.querySelector("[data-ingredient-match-details]")' not in summary

    assert "recipeIngredientBadgesHtml(option, { includeMatchStatus: false })" in script
    assert "recipeIngredientBadgesHtml(fieldValuesFromRow(optionRow), { includeMatchStatus: false })" in script

    marker_start = script.index("function updateRecipeIngredientFoodRuleWarning")
    marker_end = script.index("function ingredientChoiceReviewFromRow", marker_start)
    marker = script[marker_start:marker_end]
    assert 'marker.textContent = "Food Review";' not in marker
    assert '? "Multiple Matches"' in marker
    assert ': "Review Match";' in marker
    assert 'marker.hidden = true;' in marker

    for selector in (
        ".recipe-edit-ingredient-badge.review",
        ".recipe-edit-ingredient-badge.multiple",
        ".recipe-edit-ingredient-badge.low-confidence",
        ".recipe-edit-ingredient-badge.unmatched",
        ".recipe-edit-ingredient-match-details-grid",
    ):
        assert selector in css


def test_recipe_editor_hide_all_images_keeps_title_and_ingredient_images_visible():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    function_start = script.index("function setRecipeEditorImagesVisibleFromMenu")
    function_end = script.index("function recipeEditorImagePanelSelector", function_start)
    function_block = script[function_start:function_end]

    assert "const scope = options.imageScope || options.scope || \"all\";" in function_block
    assert "modal.querySelectorAll(recipeEditorImagePanelSelector(options))" in function_block
    assert "keepRecipeEditorIngredientImagesVisible(modal);" in function_block
    assert "if (!visible && scope === \"all\")" in function_block
    assert "keepRecipeCoverImagesVisible(modal);" in function_block

    defaults_start = script.index("function applyRecipeImageDefaultVisibility")
    defaults_end = script.index("function recipeImageContainersForCard", defaults_start)
    defaults_block = script[defaults_start:defaults_end]
    assert "keepRecipeEditorIngredientImagesVisible(scope);" in defaults_block
    assert "function keepRecipeEditorIngredientImagesVisible(scope = document)" in defaults_block
    assert 'editor.querySelectorAll("[data-ingredient-image-panel]")' in defaults_block
    assert "true" in defaults_block


def test_recipe_editor_ingredient_images_use_thumbnail_previews():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]

    assert 'recipeImageVariantUrl(ingredientImageUrl, "thumb")' in row_block
    assert 'sizes="120px"' in row_block
    assert "data-recipe-edit-row-image-tools-show" in row_block
    assert "setRecipeEditRowImageToolsVisibleFromMenu(this, true)" in row_block
    assert "data-recipe-edit-row-image-tools-hide" in row_block
    assert "setRecipeEditRowImageToolsVisibleFromMenu(this, false)" in row_block
    assert "data-recipe-edit-row-image-show" not in row_block
    assert "data-recipe-edit-row-image-hide" not in row_block
    assert "Show ingredient image" not in row_block
    assert "Hide ingredient image" not in row_block
    visibility_start = script.index("function setRecipeEditRowImageVisible(row, visible)")
    visibility_end = script.index("function updateRecipeEditRowImageMenu", visibility_start)
    visibility_block = script[visibility_start:visibility_end]
    assert 'row.classList.contains("recipe-edit-ingredient-row") || visible' in visibility_block
    assert "setRecipeImageContainersVisible([panel], shouldShow);" in visibility_block
    assert ".recipe-edit-ingredient-row .recipe-ingredient-image-panel .recipe-ingredient-image" in css
    assert "width: 120px;" in css
    assert "height: 120px;" in css
    assert ".recipe-edit-ingredient-row .recipe-ingredient-image-panel:not(.recipe-image-tools-visible)" in css
    assert ".recipe-edit-ingredient-row .recipe-ingredient-image-panel.recipe-image-empty:not(.recipe-image-tools-visible)" in css


def test_recipe_editor_equipment_images_use_thumbnail_previews():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeEquipmentRow")
    row_end = script.index("function recipeEquipmentHeaderHtml", row_start)
    row_block = script[row_start:row_end]
    tools_start = script.index("function setRecipeEditRowImageToolsVisible")
    tools_end = script.index("function setRecipeEditRowImageVisible", tools_start)
    tools_block = script[tools_start:tools_end]

    assert 'recipeImageVariantUrl(equipmentImageUrl, "thumb")' in row_block
    assert 'sizes="120px"' in row_block
    assert 'recipe-equipment-image-panel${equipmentImageUrl ? "" : " recipe-image-empty"}' in row_block
    assert "data-recipe-edit-row-image-tools-show" in row_block
    assert "setRecipeEditRowImageToolsVisibleFromMenu(this, true)" in row_block
    assert "data-recipe-edit-row-image-tools-hide" in row_block
    assert "setRecipeEditRowImageToolsVisibleFromMenu(this, false)" in row_block
    assert 'row.querySelector("[data-equipment-image-panel], [data-ingredient-image-panel], [data-step-image-panel]")' in tools_block
    assert ".recipe-edit-equipment-row .recipe-equipment-image-panel .recipe-equipment-image" in css
    assert ".recipe-edit-equipment-row .recipe-equipment-image-panel:not(.recipe-image-tools-visible)" in css
    assert ".recipe-edit-equipment-row .recipe-equipment-image-panel.recipe-image-empty:not(.recipe-image-tools-visible)" in css
    assert ".recipe-edit-equipment.recipe-edit-equipment-collapsed .recipe-edit-equipment-row:not(.recipe-edit-row-expanded):not(:has([data-equipment-image-panel]:not(.recipe-image-empty):not(.recipe-image-visibility-hidden)))" in css
    assert ".recipe-edit-equipment-row.recipe-edit-row-collapsed:not(:has([data-equipment-image-panel]:not(.recipe-image-empty):not(.recipe-image-visibility-hidden)))" in css


def test_recipe_editor_ingredient_thumbnail_uses_consistent_inline_slot():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]
    name_column_start = row_block.index('<div class="recipe-edit-ingredient-name-label">')
    name_column_end = row_block.index('<label class="recipe-edit-qty-label">', name_column_start)
    name_column = row_block[name_column_start:name_column_end]
    base_selector = ".recipe-edit-ingredient-row .recipe-ingredient-image-panel.recipe-edit-row-image-panel"
    rule_start = css.index(f"\n{base_selector} {{\n    flex: 0 0 auto;") + 1
    rule_end = css.index("\n}", rule_start)
    rule = css[rule_start:rule_end]
    desktop_start = css.index(
        ".recipe-edit-ingredient-row:has(.recipe-ingredient-image-panel:not(.recipe-image-tools-visible)"
    )
    desktop_end = css.index(".recipe-edit-ingredient-row .recipe-ingredient-image-panel,", desktop_start)
    desktop_rule = css[desktop_start:desktop_end]

    assert "recipe-ingredient-image-panel" in row_block[:name_column_start]
    assert name_column.index("recipe-edit-original-text-label") < name_column.index("${ingredientImagePanelHtml}")
    assert "flex: 0 0 auto;" in rule
    assert "margin: 8px 0 0;" in rule
    assert "grid-column:" not in rule
    assert "grid-row:" not in rule
    assert ".recipe-ingredient-image-panel.recipe-edit-row-image-panel" in desktop_rule
    assert "grid-column: 3 / 4;" in desktop_rule
    assert "grid-row: 1;" in desktop_rule
    assert "width: var(--recipe-edit-thumbnail-size, 64px);" in desktop_rule
    assert "height: var(--recipe-edit-thumbnail-size, 64px);" in desktop_rule
    assert "grid-column: 4 / 10;" in desktop_rule


def test_recipe_editor_equipment_thumbnail_uses_ingredient_like_inline_slot():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    equipment_start = css.index(
        ".recipe-edit-equipment-row .recipe-equipment-image-panel.recipe-edit-row-image-panel"
    )
    equipment_end = css.index(
        ".recipe-edit-ingredient-row:has(.recipe-ingredient-image-panel:not(.recipe-image-tools-visible)",
        equipment_start,
    )
    equipment_css = css[equipment_start:equipment_end]

    assert "width: 120px;" in equipment_css
    assert "height: 120px;" in equipment_css
    assert ".recipe-equipment-image-panel:not(.recipe-image-tools-visible) .recipe-step-image-actions" in equipment_css
    assert "grid-template-columns: 26px 54px var(--recipe-edit-thumbnail-slot, 66px) minmax(0, 1fr) 44px;" in equipment_css
    assert "gap: 10px 14px;" in equipment_css
    assert "min-height: 0;" in equipment_css
    assert "padding: 10px 18px;" in equipment_css
    assert "grid-template-columns: 28px 54px var(--recipe-edit-thumbnail-slot, 66px) minmax(260px, 1fr) 40px;" in equipment_css
    assert "> .recipe-edit-row-handle" in equipment_css
    assert "> .recipe-edit-row-number" in equipment_css
    assert "grid-row: 1;" in equipment_css
    assert "align-self: center;" in equipment_css
    assert "grid-column: 3 / 4;" in equipment_css
    assert "width: var(--recipe-edit-thumbnail-size, 64px);" in equipment_css
    assert "height: var(--recipe-edit-thumbnail-size, 64px);" in equipment_css
    assert "grid-column: 4 / 5;" in equipment_css
    assert "grid-column: 5 / 6;" in equipment_css


def test_recipe_editor_thumbnail_size_controls_are_wired():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert template.count("data-recipe-thumbnail-size-controls") >= 3
    assert template.count("data-recipe-thumbnail-size-decrease") >= 3
    assert template.count("data-recipe-thumbnail-size-increase") >= 3
    assert template.count("data-recipe-thumbnail-size-value") >= 3
    assert template.count("data-recipe-thumbnail-size-value>64px") >= 3
    assert "changeRecipeImageThumbnailSize(this, -1)" in template
    assert "changeRecipeImageThumbnailSize(this, 1)" in template
    assert "resetRecipeImageThumbnailSize(this)" in template

    assert 'RECIPE_IMAGE_THUMBNAIL_SIZE_STORAGE_KEY = "recipe-image-thumbnail-size"' in script
    assert "RECIPE_IMAGE_THUMBNAIL_DEFAULT_SIZE = 64" in script
    assert "RECIPE_IMAGE_THUMBNAIL_MIN_SIZE = 32" in script
    assert "RECIPE_IMAGE_THUMBNAIL_MAX_SIZE = 80" in script
    assert "function normalizeRecipeImageThumbnailSize" in script
    assert "function applyRecipeImageThumbnailSize" in script
    assert 'document.documentElement.style.setProperty("--recipe-edit-thumbnail-size"' in script
    assert 'document.documentElement.style.setProperty("--recipe-edit-thumbnail-slot"' in script
    assert '["initRecipeImageThumbnailSizeControls", initRecipeImageThumbnailSizeControls]' in script

    assert "--recipe-edit-thumbnail-size: 64px;" in css
    assert "--recipe-edit-thumbnail-slot: 66px;" in css
    assert "var(--recipe-edit-thumbnail-size, 64px)" in css
    assert "var(--recipe-edit-thumbnail-slot, 66px)" in css


def test_active_standalone_desktop_ingredient_thumbnails_use_size_variables():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    v10_start = css.index("/* Ingredient editor v10:")
    panel_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients > "
        ".recipe-edit-ingredient-row > .recipe-ingredient-image-panel {"
    )
    panel_start = css.index(panel_selector, v10_start)
    panel_end = css.index("\n}", panel_start)
    panel_rule = css[panel_start:panel_end]

    for property_name in ("width", "min-width", "max-width", "height", "min-height"):
        assert f"{property_name}: var(--recipe-edit-thumbnail-size" in panel_rule
    assert "48px" not in panel_rule

    v75_start = css.index("/* Ingredient editor v75:")
    v75_end = css.index("/* Ingredient editor v76:", v75_start)
    desktop_grid_rules = css[v75_start:v75_end]
    assert desktop_grid_rules.count("var(--recipe-edit-thumbnail-slot, 66px)") == 2

    option_image_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-alternative-component-summary\n"
        "    > .recipe-edit-alternative-component-image-cell {"
    )
    v51_start = css.index("/* Ingredient editor v51:")
    option_image_start = css.index(option_image_selector, v51_start)
    option_image_end = css.index("\n}", option_image_start)
    option_image_rule = css[option_image_start:option_image_end]

    for property_name in ("width", "min-width", "max-width", "height", "min-height"):
        assert f"{property_name}: var(--recipe-edit-thumbnail-size, 64px) !important;" in option_image_rule
    assert "48px" not in option_image_rule


def test_recipe_editor_row_image_tools_toggle_is_wired():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    menu_start = script.index("function updateRecipeEditRowImageMenu")
    menu_end = script.index("async function generateAllRecipeInstructionImagesFromMenu", menu_start)
    menu_block = script[menu_start:menu_end]
    generate_start = script.index("async function generateRecipeEditRowImageFromMenu")
    generate_end = script.index("async function generateRecipeImagesFromEditor", generate_start)
    generate_block = script[generate_start:generate_end]

    assert "function setRecipeEditRowImageToolsVisibleFromMenu" in script
    assert "function setRecipeEditRowImageToolsVisible" in script
    assert 'panel.classList.toggle("recipe-image-tools-visible", Boolean(visible));' in script
    assert "const showToolsButton = row ? row.querySelector(\"[data-recipe-edit-row-image-tools-show]\") : null;" in menu_block
    assert "const hideToolsButton = row ? row.querySelector(\"[data-recipe-edit-row-image-tools-hide]\") : null;" in menu_block
    assert "showToolsButton.hidden = !panel || isHidden || toolsVisible;" in menu_block
    assert "hideToolsButton.hidden = !panel || isHidden || !toolsVisible;" in menu_block
    tools_call = "setRecipeEditRowImageToolsVisible(row, true);"
    tools_call_index = generate_block.index(tools_call)
    ingredient_guard_index = generate_block.rfind(
        'imageButton.matches("[data-ingredient-image-generate]")',
        0,
        tools_call_index,
    )
    assert ingredient_guard_index != -1


def test_recipe_editor_image_empty_state_tracks_generated_and_removed_images():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    generating_start = script.index("function setRecipeImagePanelGenerating")
    complete_start = script.index("function setRecipeImagePanelComplete")
    removed_start = script.index("function setRecipeImagePanelRemoved")
    failed_start = script.index("function setRecipeImagePanelFailed")
    complete_block = script[complete_start:removed_start]
    removed_block = script[removed_start:failed_start]
    image_state_block = script[generating_start:script.index("function setRecipeImagePanelHiddenValue", failed_start)]

    assert 'panel.classList.remove("recipe-image-empty");' in image_state_block
    assert 'panel.classList.toggle("recipe-image-empty", !imageUrl);' in complete_block
    assert 'panel.classList.add("recipe-image-empty");' in removed_block
    assert 'panel.classList.toggle("recipe-image-empty", !imageUrl);' not in removed_block
    assert 'if (kind === "ingredient") {' in complete_block
    assert "updateRecipeEditIngredientGallery();" in complete_block
    assert 'if (normalizedKind === "ingredient") {' in removed_block
    assert "updateRecipeEditIngredientGallery();" in removed_block


def test_recipe_editor_ingredient_row_menu_is_grouped():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]

    assert 'class="recipe-edit-row-menu recipe-edit-ingredient-row-menu"' in row_block
    assert row_block.count('class="recipe-edit-menu-group"') == 5
    assert 'class="recipe-edit-menu-group recipe-edit-menu-group-danger"' in row_block
    for label in ("Review", "Store Section", "Images", "Row", "Move"):
        assert f'<div class="recipe-edit-menu-group-label">{label}</div>' in row_block
    assert "Use this section for all future occurrences" in row_block
    row_menu = row_block[
        row_block.index('<div class="recipe-edit-menu-group-label">Row</div>'):
        row_block.index('<div class="recipe-edit-menu-group-label">Move</div>')
    ]
    assert 'onclick="return focusRecipeEditCompactRow(this)">Edit ingredient</button>' in row_menu
    assert row_menu.index("Edit ingredient") < row_menu.index("Add alternative")
    assert ".recipe-edit-row-menu.recipe-edit-ingredient-row-menu" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group-label" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group-danger button.delete" in css


def test_recipe_editor_ingredient_rows_use_read_first_table_and_on_demand_editing():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    tools_start = script.index("function organizeRecipeEditIngredientTools()")
    tools_end = script.index("function organizeRecipeEditEquipmentTools()", tools_start)
    tools = script[tools_start:tools_end]
    assert 'tableScroll.setAttribute("role", "table");' in tools
    assert 'ingredientList.setAttribute("role", "rowgroup");' in tools
    headers = (
        "Drag / Image",
        "Ingredient",
        "Status",
        "Quantity",
        "Unit",
        "Size",
        "Store Section",
        "Type",
        "Alternatives",
    )
    assert tools.count('role="columnheader"') == len(headers) + 1
    positions = [tools.index(f">{header}</span>") for header in headers]
    assert positions == sorted(positions)
    assert 'class="recipe-edit-ingredient-actions-header"' in tools
    assert ">ACTIONS</span>" in tools
    for removed_header in ("Match / Status", "Amount", "Preparation", "Buy As", "Substitutions"):
        assert f">{removed_header}</span>" not in tools

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    shared_cells = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function appendRecipeIngredientInlineSummaryControl")
    ]
    assert 'row.classList.add("recipe-edit-read-first-row");' in organize
    assert "const readCell = createRecipeIngredientReadCell();" in organize
    assert "const statusSummary = createRecipeIngredientStatusSummary();" in organize
    assert '"recipe-edit-ingredient-read-cell"' in shared_cells
    assert '"recipe-edit-ingredient-status-summary"' in shared_cells
    assert "data-ingredient-read-name" in shared_cells
    assert "status.dataset.ingredientReadStatus" in shared_cells
    assert "data-ingredient-read-buy-as" in shared_cells
    assert "data-ingredient-read-optional" in shared_cells
    assert organize.index("row.appendChild(readCell);") < organize.index("row.appendChild(statusSummary);")
    assert organize.index("row.appendChild(statusSummary);") < organize.index("const summaryDefinitions = [")
    for summary_class in (
        "recipe-edit-ingredient-quantity-summary",
        "recipe-edit-ingredient-unit-summary",
        "recipe-edit-ingredient-size-summary",
        "recipe-edit-ingredient-store-summary",
        "recipe-edit-ingredient-type-summary",
    ):
        assert summary_class in organize
    assert 'substitutions.setAttribute("role", "region");' in organize
    assert 'substitutions.removeAttribute("aria-colspan");' in organize

    workspace = css[css.index("/* Ingredient editor v14:"):]
    grid_rule = workspace[workspace.index(".recipe-edit-ingredient-table-scroll {"):]
    grid_rule = grid_rule[:grid_rule.index("}")]
    assert "minmax(240px, 2.5fr)\n        minmax(90px, .8fr)" in grid_rule
    assert "min-width: 1040px;" in workspace
    assert ".recipe-edit-ingredient-table-head > :nth-child(3) { grid-column: 4; }" in workspace
    assert ".recipe-edit-ingredient-row > .recipe-edit-ingredient-status-summary { grid-column: 4 !important; }" in workspace
    assert ".recipe-edit-ingredient-table-head > :nth-child(4) { grid-column: 5; }" in workspace
    assert ".recipe-edit-ingredient-row > .recipe-edit-ingredient-quantity-summary { grid-column: 5 !important; }" in workspace
    mobile = workspace[workspace.index("@media (max-width: 767px)"):]
    assert "grid-template-rows: minmax(54px, auto) repeat(4, auto) !important;" in mobile
    assert ".recipe-edit-ingredient-status-summary { grid-column: 2 / 5 !important; grid-row: 2 !important; }" in mobile
    assert '.recipe-edit-ingredient-status-summary::before { content: "Status"; }' in mobile

    assert 'const editPanel = document.createElement("dialog");' in organize
    assert 'editPanel.className = "recipe-edit-ingredient-edit-panel";' in organize
    assert 'editPanel.setAttribute("role", "dialog");' in organize
    assert 'editPanel.setAttribute("aria-modal", "true");' in organize
    assert 'editPanel.setAttribute("aria-labelledby", modalTitleId);' in organize
    assert 'editPanel.setAttribute("aria-describedby", modalSubtitleId);' in organize
    assert "editPanel.hidden = true;" in organize
    for class_name in (
        "recipe-edit-ingredient-modal-shell",
        "recipe-edit-ingredient-modal-header",
        "recipe-edit-ingredient-modal-body",
        "recipe-edit-ingredient-modal-content",
        "recipe-edit-ingredient-modal-footer",
    ):
        assert class_name in organize


    section_labels = (
        ">Identity</h3>",
        ">Quantity &amp; Details</h3>",
        ">Usage</h3>",
        ">Notes</h3>",
        "AI Analysis &amp; Source Details",
    )
    positions = [organize.index(label) for label in section_labels]
    assert positions == sorted(positions)
    assert "Edit Ingredient" in organize
    assert 'aria-label="Close Edit Ingredient"' in organize
    assert 'data-recipe-ingredient-edit-subtitle' in organize
    assert 'imageSlot.dataset.recipeIngredientModalImageSlot = "";' in organize
    assert 'nameInput.setAttribute("aria-required", "true");' in organize
    assert 'nameLabel.textContent = "Ingredient Name";' in organize
    assert "addRecipeIngredientBuyAsTooltip(buyAs, modalId);" in organize
    assert 'typeLabel.textContent = "Type";' in organize
    assert ">Previous</button>" in organize
    assert ">Next</button>" in organize
    assert "Save Changes" in organize
    assert "Save &amp; Next" in organize
    assert organize.index(">Cancel</button>") < organize.index(">Previous</button>")
    assert organize.index(">Previous</button>") < organize.index(">Next</button>")
    assert organize.index(">Next</button>") < organize.index(">Save Changes</button>")
    assert "optional.hidden = true;" in organize
    assert 'matchDetails.className = "recipe-edit-ingredient-match-details";' in organize
    assert 'matchDetails.dataset.ingredientMatchDetails = "";' in organize
    assert 'type.classList.add("recipe-edit-ingredient-edit-field", "recipe-edit-ingredient-modal-type-field");' in organize
    assert "identityFields.appendChild(type);" in organize
    assert 'role="radiogroup" aria-label="Ingredient Type"' not in organize
    assert 'data-recipe-ingredient-requirement="required"' not in organize
    assert 'data-recipe-ingredient-requirement="optional"' not in organize
    assert ">View Details</button>" in organize
    assert "support.appendChild(originalText)" not in organize
    assert "[originalText, choiceReview, warning].filter(Boolean).forEach(field => support.appendChild(field));" in organize

    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_markup = script[row_start:row_end]
    for field in (
        "ingredient",
        "purchasable_item",
        "quantity",
        "unit",
        "size",
        "quantity_text",
        "preparation",
        "store_section",
        "section",
        "notes",
        "ingredient_image_url",
        "ingredient_image_generated_at",
        "ingredient_image_prompt",
        "unit_id",
        "unit_raw",
        "unit_review_required",
        "unit_review_value",
        "unit_custom",
        "store_section_custom",
        "parsed_name",
        "normalized_name",
        "master_normalized_name",
        "confidence",
        "match_status",
    ):
        assert f'data-field="{field}"' in row_markup
    assert 'textarea data-field="ingredient" rows="1" required aria-required="true"' in row_markup
    assert '<span>Quantity</span>' in row_markup
    assert '<span>Amount</span>' not in row_markup
    assert '<input type="hidden" data-field="quantity_text"' in row_markup
    assert '<span>Quantity Text</span>' not in row_markup
    assert 'placeholder="e.g. For sautéing onions."' in row_markup
    assert "Add preparation notes, purchasing guidance, or ingredient-specific details." in row_markup

    formatter = script[
        script.index("function formatRecipeIngredientQuantity"):
        script.index("function recipeIngredientReadStatusHtml")
    ]
    assert "values.quantity_text" in formatter
    assert "values.quantity || values.amount" in formatter
    assert "values.size" in formatter
    assert "recipeIngredientPluralUnit(unit, quantity)" in formatter
    assert '/^(?:to taste|as needed)$/i' in formatter
    pluralizer = script[
        script.index("function recipeIngredientPluralUnit"):
        script.index("function formatRecipeIngredientQuantity")
    ]
    for singular, plural in (
        ("tablespoon", "tablespoons"),
        ("teaspoon", "teaspoons"),
        ("cup", "cups"),
        ("clove", "cloves"),
        ("piece", "pieces"),
    ):
        assert f'{singular}: "{plural}"' in pluralizer
    assert "numericQuantity === 1" in pluralizer

    edit_mode = script[
        script.index("function setRecipeIngredientEditMode"):
        script.index("function organizeRecipeEditHeaderActions")
    ]
    assert 'row.classList.toggle("is-editing", Boolean(shouldEdit));' in edit_mode
    assert "recipeIngredientModalEditableFieldSnapshot(row)" in edit_mode
    assert "restoreRecipeIngredientEditableFieldSnapshot" in edit_mode
    assert 'document.body.classList.add("recipe-ingredient-modal-open");' in edit_mode
    assert 'document.body.classList.remove("recipe-ingredient-modal-open");' in edit_mode
    assert "captureRecipeIngredientModalScrollState()" in edit_mode
    assert "restoreRecipeIngredientModalScrollState();" in edit_mode
    assert "mountRecipeIngredientModalImage(row, panel);" in edit_mode
    assert "restoreRecipeIngredientModalImage(row);" in edit_mode
    assert "panel.showModal();" in edit_mode
    assert "panel.close();" in edit_mode
    assert 'focusTarget.focus({ preventScroll: true });' in edit_mode
    assert "updateRecipeIngredientSummary(row);" in edit_mode
    assert "updateRecipeEditorDirtyState" in edit_mode
    open_branch = edit_mode[
        edit_mode.index("if (shouldEdit) {"):
        edit_mode.index("} else if (options.restore && panel.dataset.editSnapshot)")
    ]
    assert "setRecipeIngredientSubstitutionsExpanded" not in open_branch
    assert "recipeIngredientSubstitutionContainer" not in open_branch
    assert ".recipe-edit-alternative-card.is-editing" not in open_branch

    modal_css = css[css.index("/* Ingredient editor v12:"):]
    assert css.index("/* Ingredient editor v12:") > css.index("/* Instruction editor v2:")
    assert "body.recipe-ingredient-modal-open" in modal_css
    assert "dialog.recipe-edit-ingredient-edit-panel" in modal_css
    assert "dialog.recipe-edit-ingredient-edit-panel[open]" in modal_css
    assert "dialog.recipe-edit-ingredient-edit-panel::backdrop" in modal_css
    edit_panel_rule = modal_css[modal_css.index("dialog.recipe-edit-ingredient-edit-panel {"):]
    edit_panel_rule = edit_panel_rule[:edit_panel_rule.index("}")]
    assert "display: none;" in edit_panel_rule


def test_recipe_editor_requested_headers_filter_and_sort_as_combined_view_only_menus():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    supported_start = script.index("const RECIPE_EDIT_INGREDIENT_VIEW_COLUMN_KEYS")
    supported_end = script.index("]);", supported_start)
    supported = script[supported_start:supported_end]
    for column_key in ("ingredient", "status", "unit", "store", "type"):
        assert f'"{column_key}"' in supported

    view_start = script.index("function recipeIngredientColumnViewDefinition")
    view_end = script.index("function clearRecipeEditIngredientColumnDropTargets", view_start)
    view = script[view_start:view_end]
    apply_view = javascript_function_source(script, "applyRecipeIngredientColumnView")
    assert '["manual", "store", "az", "za"]' in view
    assert "function recipeIngredientColumnViewOptions(columnKey)" in view
    assert "function applyRecipeIngredientColumnView(options = {})" in view
    assert "recipeEditIngredientColumnView.filterKeys.entries()" in view
    assert ".style.order" not in apply_view
    assert 'removeProperty("order")' not in apply_view
    assert "syncRecipeIngredientColumnViewSectionFragments" in view
    assert "clearRecipeIngredientColumnViewSectionFragments" in view
    assert '"is-ingredient-column-filtered"' in view
    assert 'function clearRecipeIngredientColumnView(columnKey = "", options = {})' in view
    assert "filterKeys: new Map()" in script
    assert "sorts: []" in script
    assert "function recipeIngredientColumnViewSorts()" in view
    assert "function setRecipeIngredientColumnViewSort(columnKey, requestedMode)" in view
    assert "function moveRecipeIngredientColumnViewSort(columnKey, direction)" in view
    assert "sorts.push({ columnKey, mode });" in view
    assert "groupByStoreSection: false" in script

    assert "function ensureRecipeIngredientColumnViewTrigger(header)" in view
    assert 'trigger.setAttribute("aria-haspopup", "dialog");' in view
    assert "Filter and sort ingredients by" in view
    assert "View-only controls" in view
    for label in ("Manual recipe order", "Store order", "Clear this column"):
        assert label in view

    decorate_start = script.index("function decorateRecipeEditIngredientColumnHeaders")
    decorate_end = script.index("function resetRecipeEditIngredientColumnLayout", decorate_start)
    decorate = script[decorate_start:decorate_end]
    assert "recipeIngredientColumnViewDefinition(key)" in decorate
    assert "ensureRecipeIngredientColumnViewTrigger(header);" in decorate
    assert 'event.target.closest("[data-recipe-ingredient-column-view-trigger]")' in script
    assert "[data-recipe-ingredient-column-view-trigger][aria-expanded]" in script
    summary_start = script.index("function updateRecipeIngredientSummary(row)")
    summary_end = script.index("function recipeEditIngredientRows()", summary_start)
    summary = script[summary_start:summary_end]
    assert "applyRecipeIngredientColumnView();" in summary
    assert "syncRecipeIngredientColumnViewOpenMenu({ render: true });" in summary

    assert ".recipe-edit-ingredient-column-view-trigger" in css
    assert ".recipe-edit-row-menu.recipe-edit-ingredient-column-view-menu" in css
    assert ".recipe-edit-ingredient-column-view-option" in css
    assert ".recipe-edit-ingredient-column-view-sort-badge" in css
    assert ".recipe-edit-ingredient-column-view-sort-priority" in css
    assert ".recipe-edit-ingredient-column-view-empty" in css
    assert ".recipe-edit-ingredient-row:is(" in css
    assert ".is-ingredient-column-filtered" in css
    assert '[data-recipe-ingredient-column-view-active="true"]' in css


def test_ingredient_column_menu_can_hide_empty_optional_inline_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    view_start = script.index("function recipeIngredientColumnViewDefinition")
    view_end = script.index("function clearRecipeEditIngredientColumnDropTargets", view_start)
    view = script[view_start:view_end]
    read_cell = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function createRecipeIngredientStatusSummary")
    ]

    assert "hideEmptyFields: false" in script
    assert "function syncRecipeIngredientEmptyFieldVisibility()" in view
    assert 'columnKey === "ingredient"' in view
    assert "recipeEditIngredientColumnView.hideEmptyFields" in view
    assert "data-recipe-ingredient-column-view-hide-empty-fields" in view
    assert "Hide empty fields" in view
    assert "Hides blank Preparation and Buy As inputs." in view
    assert "hideEmptyFields && empty" in view
    assert '!field.matches(":focus-within")' in view
    assert 'data-recipe-ingredient-optional-field="preparation"' in read_cell
    assert 'data-recipe-ingredient-optional-field="buy-as"' in read_cell
    assert "summary.dataset.recipeIngredientOptionalField = fieldName;" in script
    assert "syncRecipeIngredientEmptyFieldVisibility();" in script

    optional_field_css = css[css.index("/* Ingredient editor v93:"):]
    assert "[data-recipe-ingredient-optional-field][hidden]" in optional_field_css
    assert "display: none !important;" in optional_field_css


def test_ingredient_column_menu_can_hide_buy_as_matching_ingredient_name():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    view_start = script.index("function recipeIngredientColumnViewDefinition")
    view_end = script.index("function clearRecipeEditIngredientColumnDropTargets", view_start)
    view = script[view_start:view_end]

    assert "hideMatchingBuyAs: false" in script
    assert "function recipeIngredientOptionalFieldMatchesName(field, control)" in view
    assert 'fieldName !== "buy-as" && fieldName !== "purchasable_item"' in view
    assert "recipeIngredientViewNamesDifferOnlyByCount(" in view
    assert "data-recipe-ingredient-column-view-hide-matching-buy-as" in view
    assert "Hide matching Buy As" in view
    assert "Hides Buy As when it matches the Ingredient name." in view
    assert "hideMatchingBuyAs && matchingBuyAs" in view
    assert "recipeEditIngredientColumnView.hideMatchingBuyAs = false;" in view


def test_recipe_editor_store_section_menu_reconciles_direct_children_without_css_order():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    view_start = script.index("function recipeIngredientColumnViewDefinition")
    view_end = script.index("function clearRecipeEditIngredientColumnDropTargets", view_start)
    view = script[view_start:view_end]
    group_headers = javascript_function_source(
        script,
        "renderRecipeIngredientColumnViewGroupHeaders",
    )
    apply_view = javascript_function_source(script, "applyRecipeIngredientColumnView")
    fragments = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    reconcile = javascript_function_source(
        script,
        "reconcileRecipeIngredientColumnViewOrder",
    )

    assert "function clearRecipeIngredientColumnViewGroupHeaders(list)" in view
    assert "function renderRecipeIngredientColumnViewGroupHeaders(list, sortedRows)" in view
    assert "recipeIngredientColumnViewIngredientEntries" in view
    assert "return left.index - right.index;" in view
    assert 'header.dataset.recipeIngredientColumnGroupHeader = section.key || "__unassigned__";' in view
    assert "reconcileRecipeIngredientColumnViewOrder(list, orderedNodes);" in group_headers
    assert "list.insertBefore(node, cursor);" in reconcile
    assert ".style.order" not in group_headers
    assert ".style.order" not in apply_view
    assert ".style.order" not in fragments
    assert "cloneNode" not in fragments
    assert "Group rows by Store Section" in view
    assert "Sort other columns to order ingredients within each section." in view
    assert "[data-recipe-ingredient-column-view-group-store]" in view
    assert "recipeEditIngredientColumnView.groupByStoreSection = false;" in view
    assert "renderRecipeIngredientColumnViewGroupHeaders(list, sortedRows);" in view
    assert "function recipeIngredientColumnViewDescription()" in view
    assert "function compareRecipeIngredientColumnViewSort(left, right, sort, storeOrder)" in view
    assert "function recipeIngredientColumnViewCompare(left, right, storeOrder, manualStoreOrder)" in view
    assert "for (const sort of sorts)" in view
    assert 'if (sort.columnKey === "store") continue;' in view
    assert "setRecipeIngredientColumnViewSort(columnKey, mode);" in view
    assert "recipeEditIngredientColumnView.groupByStoreSection = false;" not in view[
        view.index('menu.querySelectorAll("[data-recipe-ingredient-column-view-sort]")'):
        view.index('menu.querySelector("[data-recipe-ingredient-column-view-group-store]")')
    ]
    assert 'data-recipe-ingredient-column-view-sort-legend' in view
    assert '"Sort groups"' in view
    assert '"Sort within groups"' in view
    assert "Column sorts combine in priority order." in view
    assert "data-recipe-ingredient-column-view-sort-move" in view
    assert "data-recipe-ingredient-column-view-sort-priority" in view

    assert ".recipe-edit-ingredient-column-view-group-note" in css
    assert ".recipe-edit-ingredient-column-group-header" in css
    assert "data-recipe-ingredient-column-view-menu=\"store\"" in css


def test_recipe_editor_display_toggle_preferences_persist_per_user_and_recover_safely():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helper_start = script.index("function recipeEditIngredientDisplayPreferencesStorageKey")
    helper_end = script.index("function clampRecipeEditIngredientColumnWidth", helper_start)
    helpers = script[helper_start:helper_end]
    node = shutil.which("node")

    if not node:
        pytest.skip("Node.js is not available for the recipe editor preference regression")

    harness = """
const RECIPE_EDIT_INGREDIENT_DISPLAY_PREFERENCES_STORAGE_KEY =
    "ai-pantry:recipe-editor:ingredient-display:v1";
let recipeEditIngredientColumnView = {
    filterKeys: new Map([["ingredient", new Set(["saved-filter"])]]),
    sorts: [{ columnKey: "ingredient", mode: "az" }],
    groupByStoreSection: false,
    hideEmptyFields: false,
    hideMatchingBuyAs: false,
};
class MemoryStorage {
    constructor() {
        this.values = new Map();
    }
    getItem(key) {
        return this.values.has(key) ? this.values.get(key) : null;
    }
    setItem(key, value) {
        this.values.set(key, String(value));
    }
}
const document = { body: { dataset: { userId: "" } } };
const window = { localStorage: new MemoryStorage() };
""" + helpers + """

const defaults = loadRecipeEditIngredientDisplayPreferences();

document.body.dataset.userId = "user/a";
recipeEditIngredientColumnView.groupByStoreSection = true;
recipeEditIngredientColumnView.hideEmptyFields = true;
recipeEditIngredientColumnView.hideMatchingBuyAs = true;
saveRecipeEditIngredientDisplayPreferences();
const userAKey = recipeEditIngredientDisplayPreferencesStorageKey();
const savedUserA = JSON.parse(window.localStorage.getItem(userAKey));

recipeEditIngredientColumnView.groupByStoreSection = false;
recipeEditIngredientColumnView.hideEmptyFields = false;
recipeEditIngredientColumnView.hideMatchingBuyAs = false;
const restoredUserA = restoreRecipeEditIngredientDisplayPreferences();

document.body.dataset.userId = "user/b";
const userBKey = recipeEditIngredientDisplayPreferencesStorageKey();
const initialUserB = restoreRecipeEditIngredientDisplayPreferences();
recipeEditIngredientColumnView.hideEmptyFields = true;
saveRecipeEditIngredientDisplayPreferences();
const savedUserB = JSON.parse(window.localStorage.getItem(userBKey));

document.body.dataset.userId = "user/a";
const isolatedUserA = restoreRecipeEditIngredientDisplayPreferences();

document.body.dataset.userId = "malformed-user";
const malformedKey = recipeEditIngredientDisplayPreferencesStorageKey();
window.localStorage.setItem(malformedKey, "{broken-json");
const malformed = loadRecipeEditIngredientDisplayPreferences();
window.localStorage.setItem(malformedKey, JSON.stringify({
    groupByStoreSection: true,
    hideEmptyFields: "yes",
}));
const partiallyMalformed = loadRecipeEditIngredientDisplayPreferences();

document.body.dataset.userId = "missing-user";
const missing = loadRecipeEditIngredientDisplayPreferences();

process.stdout.write(JSON.stringify({
    defaults,
    userAKey,
    userBKey,
    savedUserA,
    restoredUserA,
    initialUserB,
    savedUserB,
    isolatedUserA,
    malformed,
    partiallyMalformed,
    missing,
    filterCount: recipeEditIngredientColumnView.filterKeys.size,
    sorts: recipeEditIngredientColumnView.sorts,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    defaults = {
        "groupByStoreSection": False,
        "hideEmptyFields": False,
        "hideMatchingBuyAs": False,
    }
    assert result["defaults"] == defaults
    assert result["savedUserA"] == {
        "groupByStoreSection": True,
        "hideEmptyFields": True,
        "hideMatchingBuyAs": True,
    }
    assert result["restoredUserA"] == result["savedUserA"]
    assert result["userAKey"] != result["userBKey"]
    assert result["initialUserB"] == defaults
    assert result["savedUserB"] == {
        "groupByStoreSection": False,
        "hideEmptyFields": True,
        "hideMatchingBuyAs": False,
    }
    assert result["isolatedUserA"] == result["savedUserA"]
    assert result["malformed"] == defaults
    assert result["partiallyMalformed"] == {
        "groupByStoreSection": True,
        "hideEmptyFields": False,
        "hideMatchingBuyAs": False,
    }
    assert result["missing"] == defaults
    assert result["filterCount"] == 1
    assert result["sorts"] == [{"columnKey": "ingredient", "mode": "az"}]


def test_store_section_grouping_uses_leaf_entries_and_moves_existing_rows_without_clones():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    view_start = script.index("function recipeIngredientColumnViewSourceRow")
    view_end = script.index("function recipeIngredientColumnViewEntry(row", view_start)
    grouped_view = script[view_start:view_end]

    assert "function recipeIngredientColumnViewIngredientEntries" in grouped_view
    assert "recipeIngredientColumnViewSelectedOptionLineItems" in grouped_view
    assert "sourceRow" in grouped_view
    assert "parentRow" in grouped_view
    assert "optionId" in grouped_view
    assert "manualIndex" in grouped_view
    assert "function syncRecipeIngredientColumnViewSectionFragments" in grouped_view
    assert "function clearRecipeIngredientColumnViewSectionFragments" in grouped_view
    assert "cloneNode" not in grouped_view
    assert ".style.order" not in grouped_view
    assert "function createRecipeIngredientColumnViewGroupProjection" not in script
    assert "function syncRecipeIngredientColumnViewGroupProjection" not in script


def test_store_section_counts_use_visible_active_leaf_ingredients():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for Store Section count coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    assert "function recipeIngredientColumnViewIngredientEntries" in script
    entries_function = javascript_function_source(
        script,
        "recipeIngredientColumnViewIngredientEntries",
    )
    choice_entries_function = javascript_function_source(
        script,
        "recipeIngredientColumnViewChoiceEntries",
    )
    context_anchors_function = javascript_function_source(
        script,
        "assignRecipeIngredientColumnViewSectionContextAnchors",
    )
    option_context_key_function = javascript_function_source(
        script,
        "recipeIngredientColumnViewOptionContextKey",
    )
    stable_function = ""
    if "function recipeIngredientColumnViewEntryStableId" in script:
        stable_function = javascript_function_source(
            script,
            "recipeIngredientColumnViewEntryStableId",
        )
    harness = r"""
function classes(...names) {
    const values = new Set(names);
    return {
        contains(name) { return values.has(name); },
        toggle(name, enabled) {
            if (enabled) values.add(name);
            else values.delete(name);
        },
    };
}
function sourceRow(id, ingredient, storeSection, values = {}) {
    return {
        id,
        ingredient,
        store_section: storeSection,
        ...values,
        dataset: {},
        querySelector() { return null; },
    };
}
function selectedLineItem(source, optionId) {
    return {
        id: `display-${source.id}`,
        recipeIngredientOptionSourceRow: source,
        dataset: {
            ingredientOptionId: optionId,
            ingredientSelectedOptionId: optionId,
        },
        classList: classes(),
        querySelector() { return null; },
        closest() { return null; },
    };
}
function alternativeSummary(source) {
    return {
        id: `display-${source.id}`,
        recipeIngredientOptionSourceRow: source,
        dataset: {},
        classList: classes(),
        querySelector() { return null; },
        closest() { return null; },
    };
}
function ingredientRow(id, ingredient, storeSection, options = {}) {
    const row = sourceRow(id, ingredient, storeSection, options.values || {});
    row.classList = classes(...(options.choice ? ["has-ingredient-choice"] : []));
    row.dataset = {
        ingredientSelectedOptionId: options.optionId || "",
        ingredientOptionId: options.optionId || "",
    };
    row.lineItems = options.lineItems || [];
    row.alternativeRows = options.alternativeRows || [];
    row.expanded = false;
    row.hasAttribute = () => false;
    row.querySelectorAll = selector => selector.includes("ingredient-selected-option-line-item")
        ? row.lineItems
        : [];
    row.querySelector = selector => {
        if (selector === '[data-field="default_option_id"]') {
            return {value: options.optionId || ""};
        }
        if (selector === "[data-original-option-id]") {
            return {value: options.originalOptionId || ""};
        }
        return null;
    };
    return row;
}
function fieldValuesFromRow(row) { return row || {}; }
function recipeIngredientColumnViewSourceRow(row) {
    return row && (row.recipeIngredientOptionSourceRow || row);
}
function recipeIngredientColumnViewSelectedOptionLineItems(row) {
    return row && Array.isArray(row.lineItems) ? row.lineItems : [];
}
function recipeIngredientStoreSectionKey(value) {
    return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
}
function recipeStoreSectionDisplayLabel(value) { return String(value || ""); }
function recipeIngredientColumnViewEntry(row, columnKey) {
    const source = recipeIngredientColumnViewSourceRow(row);
    const value = columnKey === "store"
        ? String(source && (source.store_section || source.storeSection) || "").trim()
        : String(source && source.ingredient || "").trim();
    return {
        key: columnKey === "store" ? recipeIngredientStoreSectionKey(value) : value.toLowerCase(),
        label: value || "Unassigned",
        value,
    };
}
function recipeIngredientColumnViewEntryStableId(source, parent, optionId, manualIndex) {
    return String(
        source && (source.id || source.recipe_ingredient_id || source.substitution_id)
        || `${parent && parent.id || "ingredient"}:${optionId || "standard"}:${manualIndex}`
    );
}
function recipeIngredientStablePresentationId(value, prefix = "ingredient") {
    return String(value && (value.id || value.recipe_ingredient_id) || `${prefix}-legacy`);
}
function recipeIngredientColumnViewChoiceOptions(row) { return row.presentation(); }
function recipeIngredientColumnViewOptionSummary(parent, source, selected) {
    if (selected) {
        return parent.lineItems.find(item => item.recipeIngredientOptionSourceRow === source) || null;
    }
    return source.displayRow || source;
}
function recipeIngredientColumnViewOptionComponentOrder(source) {
    const order = Number(source.alternative_component_order);
    return Number.isInteger(order) ? order : Number.MAX_SAFE_INTEGER;
}
function recipeIngredientColumnViewOptionAnchor(_parent, entries) {
    return [...entries].sort((left, right) => (
        left.componentOrder - right.componentOrder
        || left.stableId.localeCompare(right.stableId)
    ))[0] || null;
}
function recipeIngredientColumnViewOptionHeader() { return null; }
function recipeIngredientColumnViewOptionAction() { return null; }
function recipeIngredientOptionTypeLabel(isDefault) {
    return isDefault ? "DEFAULT OPTION" : "ALTERNATIVE OPTION";
}
""" + stable_function + "\n" + context_anchors_function + "\n" + option_context_key_function + "\n" + choice_entries_function + "\n" + entries_function + r"""

const cannedCorn = ingredientRow("ingredient-canned-corn", "Canned cream-style corn", "CANNED");
const egg = ingredientRow("ingredient-egg", "Egg", "DAIRY & EGGS");
const sourCream = ingredientRow("ingredient-sour-cream", "Sour cream", "DAIRY & EGGS");

const cornSource = sourceRow("component-corn", "Corn", "PRODUCE", {
    alternative_id: "option-corn-default",
    alternative_component_order: 0,
});
const cuminSource = sourceRow("component-cumin", "Cumin", "SPICES & SEASONINGS", {
    alternative_id: "option-corn-default",
    alternative_component_order: 1,
});
const onionSource = sourceRow("component-onion", "Onion", "PRODUCE", {
    alternative_id: "option-corn-default",
    alternative_component_order: 2,
});
const frozenCornSource = sourceRow(
    "component-frozen-corn",
    "Frozen corn",
    "FROZEN",
    {alternative_id: "option-corn-frozen", alternative_component_order: 0},
);
const alternativeOnionSource = sourceRow(
    "component-alternative-onion",
    "Onion",
    "PRODUCE",
    {alternative_id: "option-corn-frozen", alternative_component_order: 1},
);
frozenCornSource.displayRow = alternativeSummary(frozenCornSource);
alternativeOnionSource.displayRow = alternativeSummary(alternativeOnionSource);
const corn = ingredientRow("requirement-corn", "Corn choice", "PRODUCE", {
    choice: true,
    optionId: "option-corn-default",
    lineItems: [
        selectedLineItem(cornSource, "option-corn-default"),
        selectedLineItem(cuminSource, "option-corn-default"),
        selectedLineItem(onionSource, "option-corn-default"),
    ],
    alternativeRows: [frozenCornSource, alternativeOnionSource],
});
corn.presentation = () => {
    const selectedChoice = {
        id: "option-corn-default",
        rows: [cornSource, cuminSource, onionSource],
        values: [cornSource, cuminSource, onionSource],
        isDefaultOption: true,
        isSelected: true,
        selectionLabel: "DEFAULT OPTION",
    };
    const alternative = {
        id: "option-corn-frozen",
        rows: [frozenCornSource, alternativeOnionSource],
        values: [frozenCornSource, alternativeOnionSource],
        isDefaultOption: false,
        isSelected: false,
    };
    return {
        selectedChoice,
        groups: [selectedChoice, alternative],
        expanded: corn.expanded,
        requiredUnresolved: false,
    };
};
// Reproduce the regression trigger: the parent points at its first selected row.
corn.recipeIngredientInlineSummarySourceRow = cornSource;

const unsaltedButterSource = sourceRow(
    "component-unsalted",
    "Unsalted butter",
    "DAIRY & EGGS",
    {alternative_id: "option-unsalted", alternative_component_order: 0},
);
unsaltedButterSource.displayRow = alternativeSummary(unsaltedButterSource);
const butter = ingredientRow("requirement-butter", "Butter", "DAIRY & EGGS", {
    choice: true,
    optionId: "original:requirement-butter",
    originalOptionId: "original:requirement-butter",
    alternativeRows: [unsaltedButterSource],
});
butter.lineItems = [selectedLineItem(butter, "original:requirement-butter")];
butter.presentation = () => {
    const selectedChoice = {
        id: "original:requirement-butter",
        rows: [butter],
        values: [butter],
        isDefaultOption: true,
        isSelected: true,
        selectionLabel: "DEFAULT OPTION",
    };
    const alternative = {
        id: "option-unsalted",
        rows: butter.alternativeRows,
        values: butter.alternativeRows,
        isDefaultOption: false,
        isSelected: false,
    };
    return {
        selectedChoice,
        groups: [selectedChoice, alternative],
        expanded: butter.expanded,
        requiredUnresolved: false,
    };
};

const requiredChoice = sourceRow(
    "component-required-choice",
    "Required choice",
    "PRODUCE",
    {alternative_id: "option-required", alternative_component_order: 0},
);
requiredChoice.displayRow = alternativeSummary(requiredChoice);
const unresolved = ingredientRow(
    "requirement-unresolved",
    "Selection required",
    "PRODUCE",
    {choice: true, alternativeRows: [requiredChoice]},
);
unresolved.presentation = () => ({
    selectedChoice: null,
    groups: [{
        id: "option-required",
        rows: [requiredChoice],
        values: [requiredChoice],
        isDefaultOption: false,
        isSelected: false,
    }],
    expanded: false,
    requiredUnresolved: true,
});
const rows = [cannedCorn, egg, sourCream, corn, butter, unresolved];
let recipeEditIngredientColumnView = {groupByStoreSection: false};
function snapshot({grouped, expanded}) {
    recipeEditIngredientColumnView.groupByStoreSection = grouped;
    corn.expanded = expanded;
    butter.expanded = expanded;
    corn.classList.toggle("recipe-edit-substitutions-open", expanded);
    butter.classList.toggle("recipe-edit-substitutions-open", expanded);
    const entries = recipeIngredientColumnViewIngredientEntries(rows, {
        includeAlternatives: grouped,
    });
    const activeEntries = entries.filter(entry => entry.counted !== false);
    const counts = {};
    activeEntries.forEach(entry => {
        counts[entry.store.value] = (counts[entry.store.value] || 0) + 1;
    });
    const cumin = entries.find(entry => entry.sourceRow.id === "component-cumin");
    const unresolvedEntries = entries.filter(entry => (
        entry.parentRow.id === "requirement-unresolved"
    ));
    return {
        sourceIds: activeEntries.map(entry => entry.sourceRow.id),
        visibleSourceIds: entries.map(entry => entry.sourceRow.id),
        inactiveSourceIds: entries
            .filter(entry => entry.counted === false)
            .map(entry => entry.sourceRow.id),
        keys: activeEntries.map(entry => entry.key),
        counts,
        cuminSection: cumin && cumin.store.value,
        cuminParent: cumin && cumin.parentRow.id,
        cornOptionIds: entries
            .filter(entry => entry.parentRow.id === "requirement-corn")
            .map(entry => entry.optionId),
        alternativeStores: Object.fromEntries(entries
            .filter(entry => (
                entry.selected === false
                && entry.parentRow.classList.contains("has-ingredient-choice")
            ))
            .map(entry => [entry.sourceRow.id, entry.store.value])),
        alternativeSummariesOmitStore: entries
            .filter(entry => (
                entry.selected === false
                && entry.parentRow.classList.contains("has-ingredient-choice")
            ))
            .every(entry => (
                entry.row !== entry.sourceRow
                && !entry.row.store_section
                && !entry.row.storeSection
            )),
        optionContexts: entries
            .filter(entry => entry.parentRow.classList.contains(
                "has-ingredient-choice",
            ))
            .map(entry => ({
                sourceId: entry.sourceRow.id,
                optionId: entry.optionId,
                store: entry.store.value,
                selected: entry.selected,
                anchor: entry.anchor,
                sectionContextAnchor: entry.sectionContextAnchor,
                optionLabel: entry.optionLabel,
            })),
        unresolvedCounted: unresolvedEntries.map(entry => entry.counted),
        duplicateSourceCount: entries.length - new Set(
            entries.map(entry => entry.sourceRow.id),
        ).size,
    };
}
const collapsedUngrouped = snapshot({grouped: false, expanded: false});
const collapsedGrouped = snapshot({grouped: true, expanded: false});
const expandedGrouped = snapshot({grouped: true, expanded: true});
const repeatedGrouped = snapshot({grouped: true, expanded: false});
const restoredUngrouped = snapshot({grouped: false, expanded: false});
process.stdout.write(JSON.stringify({
    collapsedUngrouped,
    collapsedGrouped,
    expandedGrouped,
    repeatedGrouped,
    restoredUngrouped,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    expected_source_ids = [
        "ingredient-canned-corn",
        "ingredient-egg",
        "ingredient-sour-cream",
        "component-corn",
        "component-cumin",
        "component-onion",
        "requirement-butter",
    ]
    expected_counts = {
        "CANNED": 1,
        "DAIRY & EGGS": 3,
        "PRODUCE": 2,
        "SPICES & SEASONINGS": 1,
    }
    baseline = result["collapsedUngrouped"]
    assert baseline["sourceIds"] == expected_source_ids
    assert baseline["counts"] == expected_counts
    assert baseline["cuminSection"] == "SPICES & SEASONINGS"
    assert baseline["cuminParent"] == "requirement-corn"
    assert baseline["cornOptionIds"] == ["option-corn-default"] * 3
    assert baseline["visibleSourceIds"] == expected_source_ids
    assert baseline["inactiveSourceIds"] == []
    assert baseline["unresolvedCounted"] == []
    assert baseline["duplicateSourceCount"] == 0
    for state in (
        "collapsedGrouped",
        "expandedGrouped",
        "repeatedGrouped",
        "restoredUngrouped",
    ):
        assert result[state]["sourceIds"] == expected_source_ids
        assert result[state]["counts"] == expected_counts
        assert result[state]["cuminSection"] == "SPICES & SEASONINGS"
        assert result[state]["cuminParent"] == "requirement-corn"
        assert result[state]["duplicateSourceCount"] == 0

    collapsed_grouped = result["collapsedGrouped"]
    assert collapsed_grouped["visibleSourceIds"] == [
        *expected_source_ids,
        "component-required-choice",
    ]
    assert collapsed_grouped["inactiveSourceIds"] == ["component-required-choice"]
    assert collapsed_grouped["unresolvedCounted"] == [False]
    assert collapsed_grouped["alternativeStores"] == {
        "component-required-choice": "PRODUCE",
    }
    assert collapsed_grouped["alternativeSummariesOmitStore"] is True
    assert collapsed_grouped["cornOptionIds"] == ["option-corn-default"] * 3
    assert collapsed_grouped["optionContexts"] == [
        {
            "sourceId": "component-corn",
            "optionId": "option-corn-default",
            "store": "PRODUCE",
            "selected": True,
            "anchor": True,
            "sectionContextAnchor": True,
            "optionLabel": "DEFAULT OPTION",
        },
        {
            "sourceId": "component-cumin",
            "optionId": "option-corn-default",
            "store": "SPICES & SEASONINGS",
            "selected": True,
            "anchor": False,
            "sectionContextAnchor": True,
            "optionLabel": "DEFAULT OPTION",
        },
        {
            "sourceId": "component-onion",
            "optionId": "option-corn-default",
            "store": "PRODUCE",
            "selected": True,
            "anchor": False,
            "sectionContextAnchor": False,
            "optionLabel": "DEFAULT OPTION",
        },
        {
            "sourceId": "requirement-butter",
            "optionId": "original:requirement-butter",
            "store": "DAIRY & EGGS",
            "selected": True,
            "anchor": True,
            "sectionContextAnchor": True,
            "optionLabel": "DEFAULT OPTION",
        },
        {
            "sourceId": "component-required-choice",
            "optionId": "option-required",
            "store": "PRODUCE",
            "selected": False,
            "anchor": True,
            "sectionContextAnchor": True,
            "optionLabel": "ALTERNATIVE OPTION",
        },
    ]
    assert result["repeatedGrouped"] == collapsed_grouped

    expanded_grouped = result["expandedGrouped"]
    assert expanded_grouped["visibleSourceIds"] == [
        "ingredient-canned-corn",
        "ingredient-egg",
        "ingredient-sour-cream",
        "component-corn",
        "component-cumin",
        "component-onion",
        "component-frozen-corn",
        "component-alternative-onion",
        "requirement-butter",
        "component-unsalted",
        "component-required-choice",
    ]
    assert expanded_grouped["inactiveSourceIds"] == [
        "component-frozen-corn",
        "component-alternative-onion",
        "component-unsalted",
        "component-required-choice",
    ]
    assert expanded_grouped["cornOptionIds"] == [
        "option-corn-default",
        "option-corn-default",
        "option-corn-default",
        "option-corn-frozen",
        "option-corn-frozen",
    ]
    assert expanded_grouped["unresolvedCounted"] == [False]
    assert expanded_grouped["alternativeStores"] == {
        "component-frozen-corn": "FROZEN",
        "component-alternative-onion": "PRODUCE",
        "component-unsalted": "DAIRY & EGGS",
        "component-required-choice": "PRODUCE",
    }
    assert expanded_grouped["alternativeSummariesOmitStore"] is True
    assert [
        context
        for context in expanded_grouped["optionContexts"]
        if context["optionId"] == "option-corn-frozen"
    ] == [
        {
            "sourceId": "component-frozen-corn",
            "optionId": "option-corn-frozen",
            "store": "FROZEN",
            "selected": False,
            "anchor": True,
            "sectionContextAnchor": True,
            "optionLabel": "ALTERNATIVE OPTION",
        },
        {
            "sourceId": "component-alternative-onion",
            "optionId": "option-corn-frozen",
            "store": "PRODUCE",
            "selected": False,
            "anchor": False,
            "sectionContextAnchor": True,
            "optionLabel": "ALTERNATIVE OPTION",
        },
    ]
    assert result["restoredUngrouped"] == baseline


def test_grouped_section_headers_precede_their_actual_ingredient_rows_and_active_counts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped Store Section order coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    reconcile = javascript_function_source(
        script,
        "reconcileRecipeIngredientColumnViewOrder",
    )
    render_headers = javascript_function_source(
        script,
        "renderRecipeIngredientColumnViewGroupHeaders",
    )
    harness = r"""
class FakeNode {
    constructor(id = "") {
        this.id = id;
        this.children = [];
        this.parentNode = null;
        this.dataset = {};
        this.attributes = {};
        this.style = {removeProperty() {}};
        this.className = "";
        this.innerHTML = "";
    }
    append(...nodes) { nodes.forEach(node => this.insertBefore(node, null)); }
    insertBefore(node, reference) {
        node.remove();
        const index = reference ? this.children.indexOf(reference) : -1;
        node.parentNode = this;
        if (index < 0) this.children.push(node);
        else this.children.splice(index, 0, node);
        return node;
    }
    remove() {
        if (!this.parentNode) return;
        const index = this.parentNode.children.indexOf(this);
        if (index >= 0) this.parentNode.children.splice(index, 1);
        this.parentNode = null;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    querySelectorAll(selector) {
        if (selector.includes("recipe-ingredient-column-management-row")) {
            return this.children.filter(child => (
                Object.hasOwn(child.dataset, "recipeIngredientColumnManagementRow")
            ));
        }
        return [];
    }
    get firstChild() { return this.children[0] || null; }
    get nextSibling() {
        if (!this.parentNode) return null;
        const index = this.parentNode.children.indexOf(this);
        return this.parentNode.children[index + 1] || null;
    }
}
const document = {
    activeElement: null,
    createElement() { return new FakeNode("section-header"); },
};
const recipeEditIngredientColumnView = {groupByStoreSection: true};
function recipeIngredientColumnViewEntry(row) { return row.store; }
function recipeIngredientColumnViewIngredientCount(row) {
    return (row.recipeIngredientColumnViewEntries || [{counted: true}])
        .filter(entry => entry.counted !== false).length;
}
function recipeIngredientStoreSectionIconHtml() { return ""; }
function escapeHtml(value) { return String(value); }
""" + reconcile + "\n" + render_headers + r"""

function ingredient(id, key, label, counted = true) {
    const row = new FakeNode(id);
    row.store = {key, label, value: label};
    row.recipeIngredientColumnViewEntries = [{counted, filtered: false}];
    return row;
}
const butter = ingredient("butter", "dairy", "Dairy & Eggs");
const egg = ingredient("egg", "dairy", "Dairy & Eggs");
const sourCream = ingredient("sour-cream", "dairy", "Dairy & Eggs");
const cannedCorn = ingredient("canned-corn", "canned", "Canned Goods");
const corn = ingredient("corn", "produce", "Produce");
const onion = ingredient("onion", "produce", "Produce");
const cumin = ingredient("cumin", "spices", "Spices");
const list = new FakeNode("ingredients");
const rows = [butter, egg, sourCream, cannedCorn, corn, onion, cumin];
list.append(...rows);
renderRecipeIngredientColumnViewGroupHeaders(
    list,
    rows.map((row, index) => ({row, index, filtered: false})),
);
process.stdout.write(JSON.stringify({
    sequence: list.children.map(item => (
        item.dataset.recipeIngredientColumnGroupHeader
            ? `header:${item.dataset.recipeIngredientColumnGroupHeader}`
            : item.id
    )),
    labels: list.children
        .filter(item => item.dataset.recipeIngredientColumnGroupHeader)
        .map(item => item.attributes["aria-label"]),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "sequence": [
            "header:dairy",
            "butter",
            "egg",
            "sour-cream",
            "header:canned",
            "canned-corn",
            "header:produce",
            "corn",
            "onion",
            "header:spices",
            "cumin",
        ],
        "labels": [
            "Dairy & Eggs, 3 ingredients",
            "Canned Goods, 1 ingredient",
            "Produce, 2 ingredients",
            "Spices, 1 ingredient",
        ],
    }


def test_grouped_option_rows_move_without_parent_summaries_and_restore_exact_nodes():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for Store Section fragment coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    sync_fragments = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    clear_fragments = javascript_function_source(
        script,
        "clearRecipeIngredientColumnViewSectionFragments",
    )
    move_node = javascript_function_source(
        script,
        "moveRecipeIngredientColumnViewNode",
    )
    source_carrier = javascript_function_source(
        script,
        "setRecipeIngredientColumnViewSourceCarrier",
    )
    display_rows = javascript_function_source(
        script,
        "recipeIngredientColumnViewDisplayRows",
    )
    ensure_option_row_id = javascript_function_source(
        script,
        "ensureRecipeIngredientColumnViewOptionRowId",
    )
    bind_option_selection = javascript_function_source(
        script,
        "bindRecipeIngredientColumnViewOptionSelection",
    )
    move_control = javascript_function_source(
        script,
        "recipeIngredientColumnViewMoveControl",
    )
    option_action = javascript_function_source(
        script,
        "recipeIngredientColumnViewOptionAction",
    )
    add_option_action = javascript_function_source(
        script,
        "recipeIngredientColumnViewAddOptionAction",
    )
    create_management_row = javascript_function_source(
        script,
        "createRecipeIngredientColumnViewManagementRow",
    )
    sync_management_rows = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewManagementRows",
    )
    sync_option_metadata = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionMetadata",
    )
    shows_option_context = javascript_function_source(
        script,
        "recipeIngredientColumnViewEntryShowsOptionContext",
    )
    sync_option_accessibility = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionAccessibility",
    )
    sync_option_context = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionContext",
    )
    harness = r"""
function classes(...initial) {
    const values = new Set(initial);
    return {
        add(...names) { names.forEach(name => values.add(name)); },
        remove(...names) { names.forEach(name => values.delete(name)); },
        contains(name) { return values.has(name); },
        toggle(name, enabled) {
            if (enabled) values.add(name);
            else values.delete(name);
        },
    };
}
class FakeStyle {
    constructor() {
        this.values = {};
        this.priorities = {};
    }
    setProperty(name, value, priority = "") {
        this.values[name] = String(value);
        this.priorities[name] = String(priority);
    }
    getPropertyValue(name) { return this.values[name] || ""; }
    getPropertyPriority(name) { return this.priorities[name] || ""; }
    removeProperty(name) {
        const value = this.getPropertyValue(name);
        delete this.values[name];
        delete this.priorities[name];
        return value;
    }
    get gridColumn() { return this.getPropertyValue("grid-column"); }
    set gridColumn(value) {
        if (value) this.setProperty("grid-column", value);
        else this.removeProperty("grid-column");
    }
}
class FakeNode {
    constructor(id = "") {
        this.id = id;
        this.children = [];
        this.dataset = {};
        this.classList = classes();
        this.attributes = {};
        this.parentNode = null;
        this.textContent = "";
        this.hidden = false;
        this.className = "";
        this.listeners = [];
        this.style = new FakeStyle();
    }
    append(...nodes) {
        nodes.filter(Boolean).forEach(node => {
            node.remove();
            node.parentNode = this;
            this.children.push(node);
        });
    }
    appendChild(node) {
        this.append(node);
        return node;
    }
    insertBefore(node, reference) {
        node.remove();
        const index = reference ? this.children.indexOf(reference) : -1;
        node.parentNode = this;
        if (index < 0) this.children.push(node);
        else this.children.splice(index, 0, node);
        return node;
    }
    remove() {
        if (!this.parentNode) return;
        const index = this.parentNode.children.indexOf(this);
        if (index >= 0) this.parentNode.children.splice(index, 1);
        this.parentNode = null;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) {
        delete this.attributes[name];
        const datasetKeys = {
            "data-recipe-ingredient-column-option-row": "recipeIngredientColumnOptionRow",
            "data-recipe-ingredient-option-member-id": "recipeIngredientOptionMemberId",
            "data-recipe-ingredient-option-id": "recipeIngredientOptionId",
            "data-recipe-ingredient-option-anchor": "recipeIngredientOptionAnchor",
            "data-recipe-ingredient-option-section-context": "recipeIngredientOptionSectionContext",
        };
        if (datasetKeys[name]) delete this.dataset[datasetKeys[name]];
    }
    hasAttribute(name) {
        if (name === "data-recipe-ingredient-column-option-row") {
            return Object.hasOwn(this.dataset, "recipeIngredientColumnOptionRow");
        }
        return Object.hasOwn(this.attributes, name);
    }
        toggleAttribute(name, enabled) {
            if (enabled) this.setAttribute(name, "");
            else this.removeAttribute(name);
        }
        addEventListener(type, listener, capture = false) {
            this.listeners.push({type, listener, capture});
        }
    replaceWith(node) {
        if (!this.parentNode) return;
        this.parentNode.insertBefore(node, this);
        this.remove();
    }
    matches() { return false; }
    get parentElement() { return this.parentNode; }
    get firstChild() { return this.children[0] || null; }
    get firstElementChild() { return this.firstChild; }
    get lastElementChild() { return this.children[this.children.length - 1] || null; }
    get nextSibling() {
        if (!this.parentNode) return null;
        const index = this.parentNode.children.indexOf(this);
        return this.parentNode.children[index + 1] || null;
    }
    querySelector(selector) {
        if (selector.includes("recipe-ingredient-grouped-selection-status")) {
            return this.sourceText?.children.find(child => (
                Object.hasOwn(child.dataset, "recipeIngredientGroupedSelectionStatus")
            )) || null;
        }
        if (selector.includes("ingredient-source-text")) {
            return this.sourceText || null;
        }
        if (selector.includes("alternative-component-option-spacer")) {
            return this.optionCell || null;
        }
        if (selector.includes("alternative-component-handle-cell")) {
            return this.handleCell || null;
        }
        if (selector.includes("alternative-component-actions")) {
            return this.actionsCell || null;
        }
        if (selector.includes("ingredient-choice-group-drag")) {
            return this.groupHandle || null;
        }
        if (selector.includes("recipe-edit-row-menu-wrap")) {
            return this.sourceMenu || null;
        }
        if (selector.includes("ingredient-option-select")) {
            return this.optionSelect || null;
        }
        if (selector.includes("recipe-edit-alternative-menu-wrap")) {
            return this.optionMenu || null;
        }
        if (
            selector.includes("ingredient-selected-option-block")
            && selector.includes("ingredient-option-actions")
        ) {
            return this.selectedBlock?.action || null;
        }
        if (selector.includes("ingredient-selected-option-block")) {
            return this.selectedBlock || null;
        }
        if (selector.includes("addRecipeIngredientSubstitutionRow")) {
            return this.addOptionAction || null;
        }
        if (selector.includes("ingredient-option-header")) {
            return this.children.find(child => (
                Object.hasOwn(child.dataset, "ingredientOptionHeader")
            )) || null;
        }
        if (selector.includes("ingredient-option-actions")) {
            return this.children.find(child => (
                Object.hasOwn(child.dataset, "ingredientOptionActions")
            )) || null;
        }
        if (selector.includes("ingredient-option-label")) {
            return this.optionLabel || null;
        }
        if (selector.includes("alternative-component-summary")) {
            return this.children.find(child => (
                Object.hasOwn(child.dataset, "alternativeComponentSummary")
            )) || null;
        }
        return null;
    }
    closest(selector) {
        if (selector.includes("recipe-edit-alternative-card")) {
            return this.alternativeCard || null;
        }
        return null;
    }
    querySelectorAll(selector) {
        if (
            selector.includes("ingredient-option-select")
            || selector.includes("set-alternative-preferred")
        ) {
            return this.children.filter(child => child.matches(selector));
        }
        if (selector.includes("ingredient-column-section-fragment")) {
            return this.children.filter(child => (
                Object.hasOwn(child.dataset, "recipeIngredientColumnSectionFragment")
            ));
        }
        if (selector.includes("ingredient-selected-option-line-item")) {
            return this.children.filter(child => (
                Object.hasOwn(child.dataset, "ingredientSelectedOptionLineItem")
            ));
        }
        if (selector.includes("recipe-ingredient-column-option-row")) {
            return this.children.filter(child => (
                Object.hasOwn(child.dataset, "recipeIngredientColumnOptionRow")
            ));
        }
        if (selector.includes("recipe-ingredient-column-management-row")) {
            return this.children.filter(child => (
                Object.hasOwn(child.dataset, "recipeIngredientColumnManagementRow")
            ));
        }
        if (selector.includes("is-recipe-ingredient-column-source-carrier")) {
            return this.children.filter(child => (
                child.classList.contains("is-recipe-ingredient-column-source-carrier")
            ));
        }
        return [];
    }
    matches(selector) {
        return Boolean(
            (selector.includes("ingredient-option-select")
                && Object.hasOwn(this.dataset, "ingredientOptionSelect"))
            || (selector.includes("set-alternative-preferred")
                && Object.hasOwn(this.dataset, "setAlternativePreferred"))
        );
    }
}
const document = {
    createElement() { return new FakeNode("generated"); },
    createComment() { return new FakeNode("comment"); },
};
function createRecipeIngredientOptionHeader({label}) {
    const header = new FakeNode("context-header");
    header.dataset.ingredientOptionHeader = "";
    header.optionLabel = {textContent: label};
    return header;
}
function renderRecipeIngredientOptionBlock(block, {header, ingredientContent, actions}) {
    [...block.children].forEach(child => child.remove());
    block.append(header, ...(ingredientContent || []), ...(actions || []).filter(Boolean));
}
function recipeIngredientColumnViewEntryStableId(source, parent) {
    return String(source && source.id || parent && parent.id || "ingredient");
}
function recipeIngredientStablePresentationId(...parts) {
    return parts.map(part => String(part || "").replace(/[^a-z0-9]+/gi, "-")).join("-");
}
function recipeIngredientSubstitutionContainer(row) { return row?.optionPanel || null; }
function organizeRecipeIngredientRowActions() {}
function fieldValuesFromRow(row) { return row?.values || {}; }
const optionSummarySyncs = [];
function updateRecipeIngredientOptionRowSummary(row, sourceRow, values, options) {
    optionSummarySyncs.push({row: row.id, sourceRow: sourceRow.id, values, options});
}
const delegatedOptionSelections = [];
function selectRecipeIngredientColumnViewOption(action, event) {
    delegatedOptionSelections.push({action, event});
}
function recipeIngredientExpansionIsOpen() { return false; }
function ensureRecipeIngredientExpansionId(row) { return `expansion-${row.id}`; }
const recipeEditExpandedIngredientIds = new Set();
const recipeEditIngredientColumnView = {groupByStoreSection: false};
""" + display_rows + "\n" + ensure_option_row_id + "\n" + move_node + "\n" + bind_option_selection + "\n" + source_carrier + "\n" + move_control + "\n" + option_action + "\n" + add_option_action + "\n" + create_management_row + "\n" + sync_management_rows + "\n" + shows_option_context + "\n" + sync_option_accessibility + "\n" + sync_option_context + "\n" + sync_option_metadata + "\n" + sync_fragments + "\n" + clear_fragments + r"""

function lineItem(id) {
    const row = new FakeNode(id);
    row.dataset.ingredientSelectedOptionLineItem = "";
    row.recipeIngredientOptionSourceRow = {id: `source-${id}`};
    row.sourceText = new FakeNode(`${id}-source-text`);
    row.optionCell = new FakeNode(`${id}-option-cell`);
    row.handleCell = new FakeNode(`${id}-handle-cell`);
    row.actionsCell = new FakeNode(`${id}-actions-cell`);
    row.append(row.handleCell, row.sourceText, row.optionCell, row.actionsCell);
    return row;
}
function selectedBlock(id, rows) {
    const block = new FakeNode(id);
    block.dataset.ingredientSelectedOptionBlock = "";
    block.recipeIngredientOptionSourceRows = rows.map(row => row.recipeIngredientOptionSourceRow);
    const header = new FakeNode("selected-header");
    header.dataset.ingredientOptionHeader = "";
    header.optionLabel = {textContent: "DEFAULT OPTION"};
    const action = new FakeNode("selected-action");
    action.dataset.ingredientOptionActions = "";
    action.textContent = "Add ingredient to this option";
    action.hidden = true;
    action.setAttribute("aria-hidden", "true");
    action.setAttribute("inert", "");
    block.append(header, ...rows, action);
    block.action = action;
    return {block, header, action};
}
function entry(
    row,
    sourceRow,
    parentRow,
    store,
    manualIndex,
    optionId,
    {
        selected = true,
        counted = true,
        anchor = false,
        sectionContextAnchor = false,
    } = {},
) {
    return {
        key: row.id,
        row,
        sourceRow,
        parentRow,
        optionId,
        store: {key: store.toLowerCase(), label: store, value: store},
        manualIndex,
        selected,
        active: selected,
        counted,
        anchor,
        sectionContextAnchor,
        stableId: sourceRow.id || row.id,
        componentOrder: manualIndex,
        optionLabel: selected ? "DEFAULT OPTION" : "ALTERNATIVE OPTION",
        expanded: !selected,
        filtered: false,
        optionHeader: sourceRow.optionHeader || null,
        optionAction: null,
        optionContextKey: optionId ? `id:${optionId}` : "",
    };
}
function ids(node) { return node.children.map(child => child.id); }
function optionRows(node) {
    return node.children.filter(child => (
        Object.hasOwn(child.dataset, "recipeIngredientColumnOptionRow")
    ));
}
function managementRows(node) {
    return node.children.filter(child => (
        Object.hasOwn(child.dataset, "recipeIngredientColumnManagementRow")
    ));
}
function allNodes(node) {
    return [node, ...node.children.flatMap(allNodes)];
}
function sourceOption(id, summaryId) {
    const source = new FakeNode(id);
    source.dataset.substitutionOptionRow = "";
    source.values = {ingredient: summaryId};
    const header = new FakeNode(`${summaryId}-header`);
    const optionSelect = new FakeNode(`${summaryId}-use-option`);
    optionSelect.dataset.ingredientOptionSelect = "";
    optionSelect.setAttribute("onclick", "return setRecipeIngredientOptionSelected(this)");
    const optionMenu = new FakeNode(`${summaryId}-option-menu`);
    optionMenu.classList.add("recipe-edit-alternative-menu-wrap");
    optionMenu.style.setProperty("grid-column", "10", "important");
    header.optionSelect = optionSelect;
    header.optionMenu = optionMenu;
    header.append(optionSelect, optionMenu);
    source.optionHeader = header;
    const summary = new FakeNode(summaryId);
    summary.dataset.alternativeComponentSummary = "";
    summary.recipeIngredientOptionSourceRow = source;
    summary.sourceText = new FakeNode(`${summaryId}-source-text`);
    summary.optionCell = new FakeNode(`${summaryId}-option-cell`);
    summary.append(summary.sourceText, summary.optionCell);
    const optionAction = new FakeNode(`${summaryId}-add-ingredient`);
    optionAction.dataset.ingredientOptionActions = "";
    optionAction.textContent = "Add ingredient to this option";
    source.append(header, summary, optionAction);
    return {source, summary, header, optionSelect, optionMenu, optionAction};
}
function optionPanel(id) {
    const panel = new FakeNode(`${id}-panel`);
    const addOptionAction = new FakeNode(`${id}-add-option`);
    addOptionAction.textContent = "Add another option";
    addOptionAction.hidden = true;
    addOptionAction.setAttribute("aria-hidden", "true");
    addOptionAction.setAttribute("inert", "");
    panel.addOptionAction = addOptionAction;
    panel.append(addOptionAction);
    return {panel, addOptionAction};
}

const corn = lineItem("corn");
const cumin = lineItem("cumin");
const onion = lineItem("onion");
const parent = new FakeNode("requirement-corn");
parent.classList.add("has-ingredient-choice", "recipe-edit-ingredient-row");
const selected = selectedBlock("selected-corn", [corn, cumin, onion]);
parent.selectedBlock = selected.block;
const frozenCorn = sourceOption("source-frozen-corn", "frozen-corn");
const alternativeOnion = sourceOption("source-alternative-onion", "alternative-onion");
const alternatives = new FakeNode("corn-alternatives");
alternatives.append(frozenCorn.source, alternativeOnion.source);
const cornOptionPanel = optionPanel("corn");
parent.optionPanel = cornOptionPanel.panel;
parent.append(selected.block, alternatives, cornOptionPanel.panel);
const butter = lineItem("butter");
const butterParent = new FakeNode("requirement-butter");
butterParent.classList.add("has-ingredient-choice", "recipe-edit-ingredient-row");
butter.recipeIngredientOptionSourceRow = butterParent;
const selectedButter = selectedBlock("selected-butter", [butter]);
butterParent.selectedBlock = selectedButter.block;
const butterGroupHeader = new FakeNode("butter-group-header");
const butterGroupHandle = new FakeNode("butter-real-drag-handle");
butterGroupHandle.listeners.push({type: "pointerdown", listener: "real-drag-listener"});
butterGroupHeader.groupHandle = butterGroupHandle;
butterGroupHeader.append(butterGroupHandle);
butterParent.groupHandle = butterGroupHandle;
const butterRowActions = new FakeNode("butter-row-actions");
const butterSourceMenu = new FakeNode("butter-real-row-menu");
butterSourceMenu.listeners.push({type: "click", listener: "real-menu-listener"});
butterRowActions.sourceMenu = butterSourceMenu;
butterRowActions.append(butterSourceMenu);
butterParent.sourceMenu = butterSourceMenu;
const unsaltedButter = sourceOption("source-unsalted-butter", "unsalted-butter");
const butterAlternatives = new FakeNode("butter-alternatives");
butterAlternatives.append(unsaltedButter.source);
const butterOptionPanel = optionPanel("butter");
butterParent.optionPanel = butterOptionPanel.panel;
butterParent.append(
    butterGroupHeader,
    selectedButter.block,
    butterRowActions,
    butterAlternatives,
    butterOptionPanel.panel,
);
const list = new FakeNode("ingredient-list");
list.append(parent, butterParent);
const selectedEntries = [
    entry(
        corn,
        corn.recipeIngredientOptionSourceRow,
        parent,
        "PRODUCE",
        0,
        "option-corn-default",
        {anchor: true, sectionContextAnchor: true},
    ),
    entry(
        cumin,
        cumin.recipeIngredientOptionSourceRow,
        parent,
        "SPICES & SEASONINGS",
        1,
        "option-corn-default",
        {sectionContextAnchor: true},
    ),
    entry(onion, onion.recipeIngredientOptionSourceRow, parent, "PRODUCE", 2, "option-corn-default"),
    entry(
        butter,
        butterParent,
        butterParent,
        "DAIRY & EGGS",
        3,
        "original:requirement-butter",
        {anchor: true, sectionContextAnchor: true},
    ),
];
const alternativeEntries = [
    entry(
        frozenCorn.summary,
        frozenCorn.source,
        parent,
        "FROZEN",
        4,
        "option-frozen-corn",
        {
            selected: false,
            counted: false,
            anchor: true,
            sectionContextAnchor: true,
        },
    ),
    entry(
        alternativeOnion.summary,
        alternativeOnion.source,
        parent,
        "PRODUCE",
        5,
        "option-frozen-corn",
        {selected: false, counted: false, sectionContextAnchor: true},
    ),
    entry(
        unsaltedButter.summary,
        unsaltedButter.source,
        butterParent,
        "DAIRY & EGGS",
        6,
        "option-unsalted-butter",
        {
            selected: false,
            counted: false,
            anchor: true,
            sectionContextAnchor: true,
        },
    ),
];
frozenCorn.source.alternativeCard = frozenCorn.source;
alternativeOnion.source.alternativeCard = frozenCorn.source;
unsaltedButter.source.alternativeCard = unsaltedButter.source;
selectedEntries.forEach(item => {
    item.optionAction = recipeIngredientColumnViewOptionAction(
        item.parentRow,
        {selected: true, sourceRow: item.sourceRow},
    );
});
alternativeEntries.forEach(item => {
    item.optionAction = recipeIngredientColumnViewOptionAction(
        item.parentRow,
        {selected: false, sourceRow: item.sourceRow},
    );
});
const originalManagementActions = [
    selected.action,
    frozenCorn.optionAction,
    cornOptionPanel.addOptionAction,
    selectedButter.action,
    unsaltedButter.optionAction,
    butterOptionPanel.addOptionAction,
];

syncRecipeIngredientColumnViewSectionFragments(
    list,
    [parent, butterParent],
    selectedEntries,
);
const groupedSelectionAction = {
    closest(selector) {
        if (selector.includes("ingredient-option-select")) return this;
        if (selector.includes("recipe-ingredient-column-option-row")) return corn;
        return null;
    },
};
list.listeners.find(item => item.type === "click").listener({
    target: groupedSelectionAction,
});
const collapsedRows = optionRows(list);
const collapsedChrome = {
    exactHandle: butter.handleCell.firstElementChild === butterGroupHandle,
    exactMenu: butter.actionsCell.firstElementChild === butterSourceMenu,
    handleStillInteractive: butterGroupHandle.listeners.length === 1,
    menuStillInteractive: butterSourceMenu.listeners.length === 1,
    sourceHandleMoved: !butterGroupHeader.children.includes(butterGroupHandle),
    sourceMenuMoved: !butterRowActions.children.includes(butterSourceMenu),
};
const collapsed = {
    directIds: collapsedRows.map(row => row.id),
    parentSummaryVisible: recipeIngredientColumnViewDisplayRows(list).includes(parent),
    butterSummaryVisible: recipeIngredientColumnViewDisplayRows(list).includes(butterParent),
    allSelectedAreOriginalNodes: [corn, cumin, onion, butter].every(row => (
        collapsedRows.includes(row)
    )),
    alternativeSourcesIntact: frozenCorn.source.children.includes(frozenCorn.summary)
        && alternativeOnion.source.children.includes(alternativeOnion.summary)
        && unsaltedButter.source.children.includes(unsaltedButter.summary),
    uniqueRows: new Set(collapsedRows).size,
    stores: Object.fromEntries(collapsedRows.map(row => [
        row.id,
        row.recipeIngredientColumnViewEntry?.store?.value || null,
    ])),
    optionIds: collapsedRows.map(row => (
        row.recipeIngredientColumnViewEntry?.optionId || null
    )),
    stableKeysAreUnique: new Set(collapsedRows.map(row => (
        row.recipeIngredientColumnViewEntry?.key || null
    ))).size === collapsedRows.length,
    stableDatasets: collapsedRows.every(row => (
        row.dataset.recipeIngredientOptionMemberId
        === row.recipeIngredientColumnViewEntry?.stableId
        && row.dataset.recipeIngredientOptionId
        === row.recipeIngredientColumnViewEntry?.optionId
        && row.dataset.recipeIngredientOptionAnchor
        === String(row.recipeIngredientColumnViewEntry?.anchor)
        && row.dataset.recipeIngredientOptionSectionContext
        === String(row.recipeIngredientColumnViewEntry?.sectionContextAnchor)
    )),
    contextLabels: Object.fromEntries(optionSummarySyncs.map(sync => [
        sync.row,
        sync.options.selectionState,
    ])),
};

clearRecipeIngredientColumnViewSectionFragments(list);
const restoredCollapsed = {
    parents: ids(list),
    selected: ids(selected.block),
    butterSelected: ids(selectedButter.block),
    directOptionRows: optionRows(list).length,
    canonicalIdentity: selected.block.children[1] === corn
        && selected.block.children[2] === cumin
        && selected.block.children[3] === onion,
    alternativesRestored: frozenCorn.source.children.includes(frozenCorn.summary)
        && alternativeOnion.source.children.includes(alternativeOnion.summary)
        && unsaltedButter.source.children.includes(unsaltedButter.summary),
};
const restoredCollapsedChrome = {
    exactHandleHome: butterGroupHeader.firstElementChild === butterGroupHandle,
    exactMenuHome: butterRowActions.firstElementChild === butterSourceMenu,
    promotedHandleCellEmpty: butter.handleCell.children.length === 0,
    promotedActionsCellEmpty: butter.actionsCell.children.length === 0,
    oneHandle: allNodes(list).filter(node => node === butterGroupHandle).length === 1,
    oneMenu: allNodes(list).filter(node => node === butterSourceMenu).length === 1,
};

syncRecipeIngredientColumnViewSectionFragments(
    list,
    [parent, butterParent],
    [...selectedEntries, ...alternativeEntries],
);
const expandedRows = optionRows(list);
const expandedChrome = {
    exactHandle: butter.handleCell.firstElementChild === butterGroupHandle,
    exactMenu: butter.actionsCell.firstElementChild === butterSourceMenu,
    oneHandle: allNodes(list).filter(node => node === butterGroupHandle).length === 1,
    oneMenu: allNodes(list).filter(node => node === butterSourceMenu).length === 1,
};
const expandedManagementRows = managementRows(list);
const expandedManagementActions = expandedManagementRows.map(row => (
    row.firstElementChild?.firstElementChild || null
));
const expanded = {
    directIds: expandedRows.map(row => row.id).sort(),
    parentSummaryVisible: recipeIngredientColumnViewDisplayRows(list).includes(parent),
    butterSummaryVisible: recipeIngredientColumnViewDisplayRows(list).includes(butterParent),
    allRowsAreOriginalNodes: [
        corn,
        cumin,
        onion,
        butter,
        frozenCorn.summary,
        alternativeOnion.summary,
        unsaltedButter.summary,
    ].every(row => expandedRows.includes(row)),
    uniqueRows: new Set(expandedRows).size,
    activeCount: [...selectedEntries, ...alternativeEntries].filter(entry => (
        entry.counted !== false
    )).length,
    frozenSourceWasMoved: !frozenCorn.source.children.includes(frozenCorn.summary),
    stores: Object.fromEntries(expandedRows.map(row => [
        row.id,
        row.recipeIngredientColumnViewEntry?.store?.value || null,
    ])),
    activeCountFromRows: expandedRows.filter(row => (
        row.recipeIngredientColumnViewEntry?.counted !== false
    )).length,
    metadataSyncCount: optionSummarySyncs.length,
    contextLabels: Object.fromEntries(optionSummarySyncs.map(sync => [
        sync.row,
        sync.options.selectionState,
    ])),
    frozenOptionControls: ids(frozenCorn.summary.optionCell),
    frozenOptionCellHasMenu: frozenCorn.summary.optionCell.classList.contains(
        "has-recipe-ingredient-grouped-option-menu",
    ),
    frozenMenuPlacementIsSafe: frozenCorn.optionMenu.style.getPropertyValue(
        "grid-column",
    ) !== "10",
    frozenSelectionDelegates: frozenCorn.optionSelect.getAttribute("onclick")
        === "return selectRecipeIngredientColumnViewOption(this, event)",
    stableDatasets: expandedRows.every(row => (
        row.dataset.recipeIngredientOptionMemberId
        === row.recipeIngredientColumnViewEntry?.stableId
        && row.dataset.recipeIngredientOptionId
        === row.recipeIngredientColumnViewEntry?.optionId
    )),
};
const expandedManagement = {
    rowKinds: expandedManagementRows.map(row => (
        row.dataset.recipeIngredientColumnManagementRow
    )),
    exactOriginalActions: expandedManagementActions.length === originalManagementActions.length
        && originalManagementActions.every(action => expandedManagementActions.includes(action)),
    uniqueActions: new Set(expandedManagementActions).size,
    eachActionRenderedOnce: originalManagementActions.every(action => (
        allNodes(list).filter(node => node === action).length === 1
    )),
    allActionsExposed: expandedManagementActions.every(action => (
        action && !action.hidden
        && action.getAttribute("aria-hidden") === null
        && !action.hasAttribute("inert")
    )),
    selectedActionMovedFromHome: !selected.block.children.includes(selected.action),
    alternativeActionMovedFromHome: !frozenCorn.source.children.includes(
        frozenCorn.optionAction,
    ),
    addOptionMovedFromHome: !cornOptionPanel.panel.children.includes(
        cornOptionPanel.addOptionAction,
    ),
};
clearRecipeIngredientColumnViewSectionFragments(list);
const restoredExpanded = {
    parents: ids(list),
    selected: ids(selected.block),
    butterSelected: ids(selectedButter.block),
    directOptionRows: optionRows(list).length,
    alternativesRestored: frozenCorn.source.children.includes(frozenCorn.summary)
        && alternativeOnion.source.children.includes(alternativeOnion.summary)
        && unsaltedButter.source.children.includes(unsaltedButter.summary),
    frozenHeaderControls: ids(frozenCorn.header),
    frozenMenuPlacement: frozenCorn.optionMenu.style.getPropertyValue("grid-column"),
    frozenMenuPlacementPriority: frozenCorn.optionMenu.style.getPropertyPriority(
        "grid-column",
    ),
    frozenSelectionOnclick: frozenCorn.optionSelect.getAttribute("onclick"),
    frozenOptionCellHasMenu: frozenCorn.summary.optionCell.classList.contains(
        "has-recipe-ingredient-grouped-option-menu",
    ),
};
const restoredManagement = {
    directManagementRows: managementRows(list).length,
    exactParents: selected.action.parentNode === selected.block
        && frozenCorn.optionAction.parentNode === frozenCorn.source
        && cornOptionPanel.addOptionAction.parentNode === cornOptionPanel.panel
        && selectedButter.action.parentNode === selectedButter.block
        && unsaltedButter.optionAction.parentNode === unsaltedButter.source
        && butterOptionPanel.addOptionAction.parentNode === butterOptionPanel.panel,
    exactOriginalOrder: ids(selected.block).at(-1) === "selected-action"
        && ids(frozenCorn.source).at(-1) === "frozen-corn-add-ingredient"
        && ids(cornOptionPanel.panel).at(-1) === "corn-add-option",
    selectedVisibilityRestored: selected.action.hidden
        && selected.action.getAttribute("aria-hidden") === "true"
        && selected.action.hasAttribute("inert"),
    alternativeVisibilityRestored: !frozenCorn.optionAction.hidden
        && frozenCorn.optionAction.getAttribute("aria-hidden") === null
        && !frozenCorn.optionAction.hasAttribute("inert"),
    addOptionVisibilityRestored: cornOptionPanel.addOptionAction.hidden
        && cornOptionPanel.addOptionAction.getAttribute("aria-hidden") === "true"
        && cornOptionPanel.addOptionAction.hasAttribute("inert"),
    oneOfEachOriginalAction: originalManagementActions.every(action => (
        allNodes(list).filter(node => node === action).length === 1
    )),
};
const restoredExpandedChrome = {
    exactHandleHome: butterGroupHeader.firstElementChild === butterGroupHandle,
    exactMenuHome: butterRowActions.firstElementChild === butterSourceMenu,
    oneHandle: allNodes(list).filter(node => node === butterGroupHandle).length === 1,
    oneMenu: allNodes(list).filter(node => node === butterSourceMenu).length === 1,
};

syncRecipeIngredientColumnViewSectionFragments(
    list,
    [parent, butterParent],
    [...selectedEntries, ...alternativeEntries],
);
const repeatedExpandedManagementCount = managementRows(list).length;
const repeatedChromeMovedOnce = butter.handleCell.children.filter(
    node => node === butterGroupHandle,
).length === 1 && butter.actionsCell.children.filter(
    node => node === butterSourceMenu,
).length === 1;
clearRecipeIngredientColumnViewSectionFragments(list);
const repeated = {
    parents: ids(list),
    selected: ids(selected.block),
    butterSelected: ids(selectedButter.block),
    directOptionRows: optionRows(list).length,
    delegatedListenerCount: list.listeners.filter(item => item.type === "click").length,
    delegatedListenerUsesCapture: list.listeners.find(item => item.type === "click")?.capture,
    delegatedSelectionCalls: delegatedOptionSelections.length,
    selectionBoundOnce: list.recipeIngredientColumnViewOptionSelectionBound === true,
    expandedManagementCount: repeatedExpandedManagementCount,
    directManagementRows: managementRows(list).length,
    exactParentsRestored: originalManagementActions.every(action => (
        allNodes(list).filter(node => node === action).length === 1
    )),
    chromeMovedOnce: repeatedChromeMovedOnce,
    chromeRestoredOnce: allNodes(list).filter(node => node === butterGroupHandle).length === 1
        && allNodes(list).filter(node => node === butterSourceMenu).length === 1
        && butterGroupHeader.firstElementChild === butterGroupHandle
        && butterRowActions.firstElementChild === butterSourceMenu,
};

process.stdout.write(JSON.stringify({
    collapsed,
    collapsedChrome,
    restoredCollapsed,
    restoredCollapsedChrome,
    expanded,
    expandedChrome,
    expandedManagement,
    restoredExpanded,
    restoredExpandedChrome,
    restoredManagement,
    repeated,
}));
"""
    completed = subprocess.run(
        [node, "-"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=harness,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    chrome_result = {
        key: result.pop(key)
        for key in (
            "collapsedChrome",
            "restoredCollapsedChrome",
            "expandedChrome",
            "restoredExpandedChrome",
        )
    }
    assert chrome_result == {
        "collapsedChrome": {
            "exactHandle": True,
            "exactMenu": True,
            "handleStillInteractive": True,
            "menuStillInteractive": True,
            "sourceHandleMoved": True,
            "sourceMenuMoved": True,
        },
        "restoredCollapsedChrome": {
            "exactHandleHome": True,
            "exactMenuHome": True,
            "promotedHandleCellEmpty": True,
            "promotedActionsCellEmpty": True,
            "oneHandle": True,
            "oneMenu": True,
        },
        "expandedChrome": {
            "exactHandle": True,
            "exactMenu": True,
            "oneHandle": True,
            "oneMenu": True,
        },
        "restoredExpandedChrome": {
            "exactHandleHome": True,
            "exactMenuHome": True,
            "oneHandle": True,
            "oneMenu": True,
        },
    }
    expanded_metadata = {
        key: result["expanded"].pop(key)
        for key in (
            "metadataSyncCount",
            "contextLabels",
            "frozenOptionControls",
            "frozenOptionCellHasMenu",
            "frozenMenuPlacementIsSafe",
            "frozenSelectionDelegates",
        )
    }
    restored_metadata = {
        key: result["restoredExpanded"].pop(key)
        for key in (
            "frozenHeaderControls",
            "frozenMenuPlacement",
            "frozenMenuPlacementPriority",
            "frozenSelectionOnclick",
            "frozenOptionCellHasMenu",
        )
    }
    expanded_management = result.pop("expandedManagement")
    restored_management = result.pop("restoredManagement")
    assert expanded_management == {
        "rowKinds": [
            "add-ingredient",
            "add-ingredient",
            "add-option",
            "add-ingredient",
            "add-ingredient",
            "add-option",
        ],
        "exactOriginalActions": True,
        "uniqueActions": 6,
        "eachActionRenderedOnce": True,
        "allActionsExposed": True,
        "selectedActionMovedFromHome": True,
        "alternativeActionMovedFromHome": True,
        "addOptionMovedFromHome": True,
    }
    assert restored_management == {
        "directManagementRows": 0,
        "exactParents": True,
        "exactOriginalOrder": True,
        "selectedVisibilityRestored": True,
        "alternativeVisibilityRestored": True,
        "addOptionVisibilityRestored": True,
        "oneOfEachOriginalAction": True,
    }
    assert expanded_metadata == {
        "metadataSyncCount": 11,
        "contextLabels": {
            "corn": "DEFAULT OPTION",
            "cumin": "DEFAULT OPTION",
            "onion": "",
            "butter": "DEFAULT OPTION",
            "frozen-corn": "ALTERNATIVE OPTION",
            "alternative-onion": "ALTERNATIVE OPTION",
            "unsalted-butter": "ALTERNATIVE OPTION",
        },
        "frozenOptionControls": [
            "frozen-corn-use-option",
            "frozen-corn-option-menu",
        ],
        "frozenOptionCellHasMenu": True,
        "frozenMenuPlacementIsSafe": True,
        "frozenSelectionDelegates": True,
    }
    assert restored_metadata == {
        "frozenHeaderControls": [
            "frozen-corn-use-option",
            "frozen-corn-option-menu",
        ],
        "frozenMenuPlacement": "10",
        "frozenMenuPlacementPriority": "important",
        "frozenSelectionOnclick": "return setRecipeIngredientOptionSelected(this)",
        "frozenOptionCellHasMenu": False,
    }
    assert result == {
        "collapsed": {
            "directIds": ["corn", "cumin", "onion", "butter"],
            "parentSummaryVisible": False,
            "butterSummaryVisible": False,
            "allSelectedAreOriginalNodes": True,
            "alternativeSourcesIntact": True,
            "uniqueRows": 4,
            "stores": {
                "corn": "PRODUCE",
                "cumin": "SPICES & SEASONINGS",
                "onion": "PRODUCE",
                "butter": "DAIRY & EGGS",
            },
            "optionIds": [
                "option-corn-default",
                "option-corn-default",
                "option-corn-default",
                "original:requirement-butter",
            ],
            "stableKeysAreUnique": True,
            "stableDatasets": True,
            "contextLabels": {
                "corn": "DEFAULT OPTION",
                "cumin": "DEFAULT OPTION",
                "onion": "",
                "butter": "DEFAULT OPTION",
            },
        },
        "restoredCollapsed": {
            "parents": ["requirement-corn", "requirement-butter"],
            "selected": [
                "selected-header",
                "corn",
                "cumin",
                "onion",
                "selected-action",
            ],
            "butterSelected": ["selected-header", "butter", "selected-action"],
            "directOptionRows": 0,
            "canonicalIdentity": True,
            "alternativesRestored": True,
        },
        "expanded": {
            "directIds": [
                "alternative-onion",
                "butter",
                "corn",
                "cumin",
                "frozen-corn",
                "onion",
                "unsalted-butter",
            ],
            "parentSummaryVisible": False,
            "butterSummaryVisible": False,
            "allRowsAreOriginalNodes": True,
            "uniqueRows": 7,
            "activeCount": 4,
            "frozenSourceWasMoved": True,
            "stores": {
                "corn": "PRODUCE",
                "cumin": "SPICES & SEASONINGS",
                "onion": "PRODUCE",
                "butter": "DAIRY & EGGS",
                "frozen-corn": "FROZEN",
                "alternative-onion": "PRODUCE",
                "unsalted-butter": "DAIRY & EGGS",
            },
            "activeCountFromRows": 4,
            "stableDatasets": True,
        },
        "restoredExpanded": {
            "parents": ["requirement-corn", "requirement-butter"],
            "selected": [
                "selected-header",
                "corn",
                "cumin",
                "onion",
                "selected-action",
            ],
            "butterSelected": ["selected-header", "butter", "selected-action"],
            "directOptionRows": 0,
            "alternativesRestored": True,
        },
        "repeated": {
            "parents": ["requirement-corn", "requirement-butter"],
            "selected": [
                "selected-header",
                "corn",
                "cumin",
                "onion",
                "selected-action",
            ],
            "butterSelected": ["selected-header", "butter", "selected-action"],
            "directOptionRows": 0,
            "delegatedListenerCount": 1,
            "delegatedListenerUsesCapture": True,
            "delegatedSelectionCalls": 1,
            "selectionBoundOnce": True,
            "expandedManagementCount": 6,
            "directManagementRows": 0,
            "exactParentsRestored": True,
            "chromeMovedOnce": True,
            "chromeRestoredOnce": True,
        },
    }


def test_grouped_action_row_resolver_routes_promoted_and_portaled_controls_to_source_parent():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped action routing coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    resolver = javascript_function_source(script, "recipeEditActionRowFromButton")
    duplicate = javascript_function_source(script, "duplicateRecipeIngredientRow")
    harness = r"""
const movableSelector = ".recipe-edit-ingredient-row:not([data-substitution-option-row])";
function recipeEditMovableRowSelector() { return movableSelector; }

const duplicateNode = {id: "duplicate-row"};
const calls = {
    sourceReads: [],
    addedValues: [],
    insertedAfter: [],
    closedMenus: 0,
    indexed: 0,
    projections: 0,
};
const sourceParent = {
    id: "source-parent",
    after(node) { calls.insertedAfter.push(node); },
};
const promotedRow = {
    id: "promoted-butter",
    recipeIngredientChoiceParentRow: sourceParent,
};
const directSourceRow = {id: "direct-row"};

const promotedButton = {
    closest(selector) {
        if (selector === movableSelector) return null;
        if (selector.includes("recipe-ingredient-column-option-row")) {
            return promotedRow;
        }
        if (selector.includes("recipe-edit-row-menu")) return null;
        return null;
    },
};
const menuAnchor = {
    closest(selector) {
        if (selector.includes("recipe-ingredient-column-option-row")) {
            return promotedRow;
        }
        if (selector === movableSelector) return null;
        return null;
    },
};
const portaledMenu = {recipeEditAnchorButton: menuAnchor};
const portaledMenuButton = {
    closest(selector) {
        if (selector === movableSelector) return null;
        if (selector.includes("recipe-ingredient-column-option-row")) return null;
        if (selector.includes("recipe-edit-row-menu")) return portaledMenu;
        return null;
    },
};
const directButton = {
    closest(selector) {
        return selector === movableSelector ? directSourceRow : null;
    },
};

function fieldValuesFromRow(row) {
    calls.sourceReads.push(row);
    return {ingredient: "Butter", sourceId: row.id};
}
function addRecipeIngredientRow(values) {
    calls.addedValues.push(values);
    return duplicateNode;
}
function closeRecipeEditRowMenus() { calls.closedMenus += 1; }
function updateRecipeIngredientRowIndexes() { calls.indexed += 1; }
function recipeIngredientColumnViewIsActive() { return true; }
function applyRecipeIngredientColumnView() { calls.projections += 1; }
""" + resolver + "\n" + duplicate + r"""

const resolved = {
    promoted: recipeEditActionRowFromButton(promotedButton),
    portaled: recipeEditActionRowFromButton(portaledMenuButton),
    direct: recipeEditActionRowFromButton(directButton),
};
const duplicateResult = duplicateRecipeIngredientRow(portaledMenuButton);
process.stdout.write(JSON.stringify({
    resolved: {
        promoted: resolved.promoted?.id || null,
        portaled: resolved.portaled?.id || null,
        direct: resolved.direct?.id || null,
    },
    duplicateResult,
    duplicate: {
        sourceIds: calls.sourceReads.map(row => row.id),
        addedValues: calls.addedValues,
        insertedIds: calls.insertedAfter.map(row => row.id),
        closedMenus: calls.closedMenus,
        indexed: calls.indexed,
        projections: calls.projections,
    },
}));
"""
    completed = subprocess.run(
        [node, "-"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=harness,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "resolved": {
            "promoted": "source-parent",
            "portaled": "source-parent",
            "direct": "direct-row",
        },
        "duplicateResult": False,
        "duplicate": {
            "sourceIds": ["source-parent"],
            "addedValues": [{"ingredient": "Butter", "sourceId": "source-parent"}],
            "insertedIds": ["duplicate-row"],
            "closedMenus": 1,
            "indexed": 1,
            "projections": 1,
        },
    }


def test_grouped_add_ingredient_handlers_refresh_and_focus_the_promoted_new_row():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped Add Ingredient coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    add_default = javascript_function_source(
        script,
        "addRecipeIngredientDefaultComponent",
    )
    add_alternative = javascript_function_source(
        script,
        "addRecipeIngredientAlternativeComponent",
    )
    harness = r"""
function classList(...initial) {
    const values = new Set(initial);
    return {
        contains(name) { return values.has(name); },
    };
}
function focusField(id) {
    return {
        id,
        focusCalls: [],
        focus(options) { this.focusCalls.push(options); },
    };
}

const defaultSourceField = focusField("default-source-field");
const defaultPromotedField = focusField("default-promoted-field");
const alternativeSourceField = focusField("alternative-source-field");
const alternativePromotedField = focusField("alternative-promoted-field");
const defaultOriginal = {
    id: "default-original",
    querySelector() { return null; },
};
const defaultNew = {
    id: "default-new",
    querySelector(selector) {
        return selector.includes("ingredient") ? defaultSourceField : null;
    },
};
const defaultPromoted = {
    id: "default-promoted",
    querySelector(selector) {
        return selector.includes("ingredient") ? defaultPromotedField : null;
    },
};
const defaultRows = [];
const defaultList = {
    insertAdjacentHTML() {
        defaultRows.splice(0, defaultRows.length, defaultOriginal, defaultNew);
    },
    querySelectorAll() { return defaultRows; },
};
const defaultCard = {
    querySelectorAll() { return defaultRows; },
};

const alternativeExisting = {
    id: "alternative-existing",
    dataset: {alternativeGroupIndex: "2"},
    querySelector(selector) {
        if (selector.includes('alternative_id')) return {value: "alternative-1"};
        return null;
    },
};
const alternativeNew = {
    id: "alternative-new",
    querySelector(selector) {
        return selector.includes("ingredient") ? alternativeSourceField : null;
    },
};
const alternativePromoted = {
    id: "alternative-promoted",
    querySelector(selector) {
        return selector.includes("ingredient") ? alternativePromotedField : null;
    },
};
let alternativeInserted = false;
const alternativeComponents = {
    insertAdjacentHTML() { alternativeInserted = true; },
    querySelectorAll() { return alternativeInserted
        ? [alternativeExisting, alternativeNew]
        : [alternativeExisting]; },
    querySelector(selector) {
        return selector.includes(":last-child") && alternativeInserted
            ? alternativeNew
            : null;
    },
};

const sourceParent = {
    id: "source-parent",
    classList: classList("is-recipe-ingredient-column-source-carrier"),
    values: {
        ingredient: "Butter",
        store_section: "DAIRY & EGGS",
        section: "main",
    },
    querySelector(selector) {
        if (selector.includes('default_option_id')) return {value: ""};
        if (selector.includes('selection_required')) return {value: "false"};
        if (selector.includes('original_is_default')) return {value: "true"};
        return null;
    },
};
const alternativeCard = {
    dataset: {alternativeId: "alternative-1"},
    closest() { return sourceParent; },
    querySelector(selector) {
        return selector.includes("recipe-edit-alternative-components")
            ? alternativeComponents
            : null;
    },
    querySelectorAll() {
        return alternativeInserted
            ? [alternativeExisting, alternativeNew]
            : [alternativeExisting];
    },
};
const defaultContainer = {
    querySelector(selector) {
        if (selector.includes("ingredient-substitution-list")) return defaultList;
        if (selector.includes("recipe-edit-alternative-card")) return defaultCard;
        return null;
    },
    querySelectorAll(selector) {
        return selector.includes("recipe-edit-alternative-card")
            ? [alternativeCard]
            : [];
    },
};
const defaultButton = {id: "add-default"};
const alternativeButton = {id: "add-alternative"};

let projectionMode = "default";
const calls = {
    projections: [],
    expanded: [],
    organized: [],
    bound: [],
    state: 0,
    summary: 0,
    editMode: 0,
    dirty: 0,
};
function recipeIngredientParentRowFromControl() { return sourceParent; }
function recipeIngredientSubstitutionContainer() { return defaultContainer; }
function recipeIngredientAlternativeCardFromControl() { return alternativeCard; }
function ensureRecipeIngredientModalOptionsExpanded(button) {
    calls.expanded.push(button.id);
}
function fieldValuesFromRow(row) { return row.values || {option_type: "custom"}; }
function nextRecipeIngredientAlternativeId() { return "generated-default"; }
function recipeIngredientIsOptional() { return false; }
function recipeIngredientSubstitutionOptionRowHtml() { return "<option-row>"; }
function organizeRecipeEditSubstitutionOptionRow(row) { calls.organized.push(row.id); }
function bindRecipeIngredientSubstitutionRow(row) { calls.bound.push(row.id); }
function updateRecipeIngredientSubstitutionState() { calls.state += 1; }
function updateRecipeIngredientSummary() { calls.summary += 1; }
function setRecipeIngredientAlternativeEditMode() { calls.editMode += 1; }
function updateRecipeEditorDirtyState() { calls.dirty += 1; }
function applyRecipeIngredientColumnView() {
    calls.projections.push(projectionMode);
    if (projectionMode === "default") {
        defaultNew.recipeIngredientColumnViewPromotedSummary = defaultPromoted;
    } else {
        alternativeNew.recipeIngredientColumnViewPromotedSummary = alternativePromoted;
    }
}
const CSS = {escape(value) { return value; }};
""" + add_default + "\n" + add_alternative + r"""

const defaultResult = addRecipeIngredientDefaultComponent(defaultButton);
projectionMode = "alternative";
const alternativeResult = addRecipeIngredientAlternativeComponent(alternativeButton);
process.stdout.write(JSON.stringify({
    defaultResult,
    alternativeResult,
    projections: calls.projections,
    expanded: calls.expanded,
    organized: calls.organized,
    bound: calls.bound,
    state: calls.state,
    summary: calls.summary,
    editMode: calls.editMode,
    dirty: calls.dirty,
    defaultFocus: defaultPromotedField.focusCalls,
    defaultSourceFocus: defaultSourceField.focusCalls,
    alternativeFocus: alternativePromotedField.focusCalls,
    alternativeSourceFocus: alternativeSourceField.focusCalls,
    defaultPromotedIdentity: defaultNew.recipeIngredientColumnViewPromotedSummary
        === defaultPromoted,
    alternativePromotedIdentity: alternativeNew.recipeIngredientColumnViewPromotedSummary
        === alternativePromoted,
}));
"""
    completed = subprocess.run(
        [node, "-"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=harness,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "defaultResult": False,
        "alternativeResult": False,
        "projections": ["default", "alternative"],
        "expanded": ["add-default", "add-alternative"],
        "organized": ["default-original", "default-new", "alternative-new"],
        "bound": ["default-original", "default-new", "alternative-new"],
        "state": 2,
        "summary": 1,
        "editMode": 2,
        "dirty": 2,
        "defaultFocus": [{"preventScroll": True}],
        "defaultSourceFocus": [],
        "alternativeFocus": [{"preventScroll": True}],
        "alternativeSourceFocus": [],
        "defaultPromotedIdentity": True,
        "alternativePromotedIdentity": True,
    }


def test_grouped_add_another_option_refreshes_and_focuses_its_promoted_row():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped Add Another coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    set_expanded = javascript_function_source(
        script,
        "setRecipeIngredientSubstitutionsExpanded",
    )
    add_option = javascript_function_source(
        script,
        "addRecipeIngredientSubstitutionRow",
    )
    harness = r"""
function classList(...initial) {
    const values = new Set(initial);
    return {
        contains(name) { return values.has(name); },
        toggle(name, enabled) {
            if (enabled) values.add(name);
            else values.delete(name);
        },
        snapshot() { return [...values].sort(); },
    };
}
const sourceField = {
    focusCalls: [],
    focus(options) { this.focusCalls.push(options); },
};
const promotedField = {
    focusCalls: [],
    focus(options) { this.focusCalls.push(options); },
};
const promotedRow = {
    id: "promoted-new-option",
    querySelector(selector) { return selector.includes("ingredient") ? promotedField : null; },
};
const existingRow = {
    id: "existing-option",
    matches() { return true; },
};
const newOption = {
    id: "new-option",
    matches(selector) { return selector.includes("substitution-option-row"); },
    querySelector(selector) { return selector.includes("ingredient") ? sourceField : null; },
};
const optionRows = [existingRow];
const list = {
    insertAdjacentHTML() { optionRows.push(newOption); },
    querySelectorAll(selector) {
        return selector.includes("substitution-option-row") ? optionRows : [];
    },
    get lastElementChild() { return optionRows.at(-1); },
};
const optionsButton = {id: "options-toggle"};
const row = {
    id: "source-parent",
    classList: classList(
        "has-ingredient-choice",
        "is-recipe-ingredient-column-source-carrier",
    ),
    querySelector(selector) {
        if (selector.includes("substitutions-toggle")) return optionsButton;
        return null;
    },
};
const container = {
    hidden: true,
    querySelector(selector) {
        return selector.includes("ingredient-substitution-list") ? list : null;
    },
    querySelectorAll() { return []; },
    closest() { return null; },
};
const addButton = {id: "add-another"};
const calls = {
    projections: 0,
    syncMenus: 0,
    closeMenus: 0,
    expandedChecks: 0,
    states: 0,
    summaries: 0,
    organized: [],
    bound: [],
    dirty: 0,
};
function recipeIngredientParentRowFromControl() { return row; }
function recipeIngredientSubstitutionContainer() { return container; }
function recipeIngredientOptionsMenuForRow() { return null; }
function ensureRecipeIngredientModalOptionsExpanded() { calls.expandedChecks += 1; }
function recipeIngredientSubstitutionDomGroups(rows) { return rows.length ? [{}] : []; }
function recipeIngredientSubstitutionOptionRowHtml() { return "<option-row>"; }
function nextRecipeIngredientAlternativeId() { return "new-option-id"; }
function fieldValuesFromRow() { return {store_section: "DAIRY & EGGS"}; }
function organizeRecipeEditSubstitutionOptionRow(optionRow) {
    calls.organized.push(optionRow.id);
}
function bindRecipeIngredientSubstitutionRow(optionRow) { calls.bound.push(optionRow.id); }
function updateRecipeIngredientSummary() { calls.summaries += 1; }
function closeRecipeEditRowMenus() { calls.closeMenus += 1; }
function updateRecipeEditorDirtyState() { calls.dirty += 1; }
function updateRecipeIngredientSubstitutionState() { calls.states += 1; }
function ensureRecipeIngredientExpansionId() { return "expansion-source-parent"; }
function setRecipeIngredientAlternativeEditMode() {}
function syncRecipeIngredientColumnViewOpenMenu() { calls.syncMenus += 1; }
function applyRecipeIngredientColumnView() {
    calls.projections += 1;
    newOption.recipeIngredientColumnViewPromotedSummary = promotedRow;
}
function positionRecipeEditPopupMenu() {}
const recipeEditIngredientColumnView = {groupByStoreSection: true};
const recipeEditExpandedIngredientIds = new Set();
""" + set_expanded + "\n" + add_option + r"""

const result = addRecipeIngredientSubstitutionRow(addButton);
process.stdout.write(JSON.stringify({
    result,
    projections: calls.projections,
    syncMenus: calls.syncMenus,
    closeMenus: calls.closeMenus,
    expandedChecks: calls.expandedChecks,
    states: calls.states,
    summaries: calls.summaries,
    organized: calls.organized,
    bound: calls.bound,
    dirty: calls.dirty,
    optionCount: optionRows.length,
    promotedIdentity: newOption.recipeIngredientColumnViewPromotedSummary === promotedRow,
    promotedFocus: promotedField.focusCalls,
    sourceFocus: sourceField.focusCalls,
    expansionOpen: row.recipeIngredientGroupedOptionsExpanded,
    expansionClass: row.classList.contains("recipe-edit-substitutions-open"),
    expansionTracked: recipeEditExpandedIngredientIds.has("expansion-source-parent"),
    containerHidden: container.hidden,
}));
"""
    completed = subprocess.run(
        [node, "-"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        input=harness,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "result": False,
        "projections": 1,
        "syncMenus": 1,
        "closeMenus": 2,
        "expandedChecks": 1,
        "states": 1,
        "summaries": 1,
        "organized": ["new-option"],
        "bound": ["new-option"],
        "dirty": 1,
        "optionCount": 2,
        "promotedIdentity": True,
        "promotedFocus": [{"preventScroll": True}],
        "sourceFocus": [],
        "expansionOpen": True,
        "expansionClass": True,
        "expansionTracked": True,
        "containerHidden": True,
    }


def test_grouped_store_section_forward_port_keeps_real_controls_and_actions():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    choice_entries = javascript_function_source(
        script,
        "recipeIngredientColumnViewChoiceEntries",
    )
    option_action = javascript_function_source(
        script,
        "recipeIngredientColumnViewOptionAction",
    )
    add_option_action = javascript_function_source(
        script,
        "recipeIngredientColumnViewAddOptionAction",
    )
    move_control = javascript_function_source(
        script,
        "recipeIngredientColumnViewMoveControl",
    )
    create_management = javascript_function_source(
        script,
        "createRecipeIngredientColumnViewManagementRow",
    )
    sync_management = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewManagementRows",
    )
    sync_metadata = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionMetadata",
    )
    sync_fragments = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    group_headers = javascript_function_source(
        script,
        "renderRecipeIngredientColumnViewGroupHeaders",
    )
    restore = javascript_function_source(
        script,
        "clearRecipeIngredientColumnViewSectionFragments",
    )

    assert "entry.optionAction = recipeIngredientColumnViewOptionAction(" in choice_entries
    assert ":scope > [data-ingredient-selected-option-block]" in option_action
    assert ":scope > [data-ingredient-choice-overview]" in option_action
    assert 'closest?.(".recipe-edit-alternative-card")' in option_action
    assert "[data-ingredient-option-actions]" in option_action
    assert "button[onclick*='addRecipeIngredientSubstitutionRow']" in add_option_action

    assert "entry.selected" in sync_metadata
    assert "entry.sourceRow === entry.parentRow" in sync_metadata
    assert "[data-ingredient-choice-group-drag]" in sync_metadata
    assert "> .recipe-edit-row-menu-wrap" in sync_metadata
    assert sync_metadata.count("recipeIngredientColumnViewMoveControl(") >= 4
    assert "{ preservePlacement: true }" in sync_metadata
    assert "organizeRecipeIngredientRowActions(row);" in sync_metadata
    assert "cloneNode" not in sync_metadata

    assert "recipeIngredientColumnViewOriginalVisibility" in move_control
    assert "if (control.style && !options.preservePlacement)" in move_control
    assert "moveRecipeIngredientColumnViewNode(control, target)" in move_control
    assert "cloneNode" not in move_control

    assert 'managementRow.dataset.recipeIngredientColumnManagementRow = kind;' in (
        create_management
    )
    assert "recipeIngredientColumnViewMoveControl(" in create_management
    assert "{ preservePlacement: true }" in create_management
    assert "action.recipeIngredientChoiceParentRow = parentRow;" in create_management
    assert "cloneNode" not in create_management

    assert "const entriesByOption = new Map();" in sync_management
    assert "const movedActions = new Set();" in sync_management
    assert "if (!action || movedActions.has(action)) return;" in sync_management
    assert '"add-ingredient"' in sync_management
    assert "recipeIngredientColumnViewAddOptionAction(parentRow)" in sync_management
    assert '"add-option"' in sync_management
    assert "cloneNode" not in sync_management
    assert "syncRecipeIngredientColumnViewManagementRows(" in sync_fragments

    assert "data-recipe-ingredient-column-management-row" in group_headers
    assert "managementRowsAfter" in group_headers
    assert "orderedNodes.push(...(managementRowsAfter.get(entry.row) || []));" in (
        group_headers
    )

    assert "const managementRows =" in restore
    assert "const home = control.recipeIngredientColumnViewHome;" in restore
    assert "home.replaceWith(control);" in restore
    assert "recipeIngredientColumnViewOriginalVisibility" in restore
    assert "managementRows.forEach(row => row.remove());" in restore
    assert "cloneNode" not in restore

    grouped_css = css[css.index(
        "/* Ingredient editor v114: grouped choices render only stable, concrete ingredient rows. */"
    ):]
    desktop_css = grouped_css[
        grouped_css.index("@media (min-width: 768px)"):
        grouped_css.index("@media (max-width: 767px)")
    ]
    mobile_css = grouped_css[grouped_css.index("@media (max-width: 767px)"):]

    assert "font-size: 9px" not in grouped_css
    assert "font-size: var(--recipe-edit-ingredient-column-font-size) !important;" in (
        grouped_css
    )
    assert "font-weight: var(--recipe-edit-ingredient-column-font-weight) !important;" in (
        grouped_css
    )
    assert "grid-template-columns: minmax(0, 1fr) 32px;" in grouped_css
    assert "width: 32px;" in grouped_css
    assert "min-width: 32px;" in grouped_css

    assert "> [data-recipe-ingredient-column-option-row]" in desktop_css
    assert "min-height: 80px;" in desktop_css
    assert "align-items: center;" in desktop_css
    assert "row-gap: 0 !important;" in desktop_css
    assert "padding: 8px 12px;" in desktop_css
    assert "> [data-recipe-ingredient-column-management-row]" in desktop_css
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid);" in desktop_css

    assert "grid-template-columns: minmax(0, 1fr) 40px;" in mobile_css
    assert "width: 40px;" in mobile_css
    assert "min-width: 40px;" in mobile_css
    assert "> [data-recipe-ingredient-column-management-row]" in mobile_css
    assert "width: 100% !important;" in mobile_css
    assert "@media (forced-colors: active)" in grouped_css


def test_expanded_grouped_source_carrier_cannot_win_as_a_grid_row():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    parsed_rules = []
    for block in css.split("}"):
        if "{" not in block:
            continue
        selector, declarations = block.rsplit("{", 1)
        parsed_rules.append((selector.strip(), declarations))

    expanded_grid_selectors = [
        selector
        for selector, declarations in parsed_rules
        if ".recipe-edit-ingredient-row" in selector
        and ".recipe-edit-substitutions-open" in selector
        and "display: grid !important;" in declarations
    ]
    source_carrier_selectors = [
        selector
        for selector, declarations in parsed_rules
        if ".is-recipe-ingredient-column-source-carrier" in selector
        and "display: contents !important;" in declarations
    ]

    assert expanded_grid_selectors
    assert source_carrier_selectors
    expanded_grid_excludes_carrier = all(
        ":not(.is-recipe-ingredient-column-source-carrier)" in selector
        for selector in expanded_grid_selectors
    )
    carrier_rule_matches_row_specificity = any(
        ".recipe-edit-ingredient-row" in selector
        and ".is-recipe-ingredient-column-source-carrier" in selector
        for selector in source_carrier_selectors
    )
    assert expanded_grid_excludes_carrier or carrier_rule_matches_row_specificity


def test_promoted_grouped_choice_rows_keep_their_mobile_card_and_disclosure_layout():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    marker = "/* Ingredient editor v114: grouped choices render only stable, concrete ingredient rows. */"
    promoted_css = css[css.index(marker):]
    mobile_start = promoted_css.index("@media (max-width: 767px)")
    mobile_end = promoted_css.index("@media (forced-colors: active)", mobile_start)
    mobile_css = promoted_css[mobile_start:mobile_end]

    assert "> [data-recipe-ingredient-column-option-row] {" in mobile_css
    assert "grid-column: 1 / -1 !important;" in mobile_css
    assert (
        "grid-template-columns: 40px minmax(0, 1fr) max-content 96px !important;"
        in mobile_css
    )
    assert ".has-visible-ingredient-selected-option-toggle" in mobile_css
    assert ".has-recipe-ingredient-grouped-option-menu" in mobile_css
    assert "grid-column: 2 / -1 !important;" in mobile_css
    assert "grid-row: 3 !important;" in mobile_css
    assert "min-height: 40px;" in mobile_css
    assert "> .recipe-edit-alternative-component-handle-cell" in mobile_css
    assert ".recipe-edit-alternative-component-quantity" in mobile_css
    assert "display: none !important;" in mobile_css


def test_store_section_column_label_remains_in_the_sticky_scrolling_header():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    ingredient_tools = javascript_function_source(
        script,
        "organizeRecipeEditIngredientTools",
    )
    header_scroll = javascript_function_source(
        script,
        "syncRecipeEditIngredientTableHeaderScroll",
    )
    sticky_start = css.index(
        "/* Ingredient editor v65: keep ingredient controls and desktop column labels visible while rows scroll. */"
    )
    sticky_end = css.index("/* Ingredient editor v66:", sticky_start)
    sticky_css = css[sticky_start:sticky_end]

    assert 'data-ingredient-column="store">Store Section</span>' in ingredient_tools
    assert 'tableHeadViewport.className = "recipe-edit-ingredient-table-head-viewport";' in ingredient_tools
    assert "tableHeadViewport.appendChild(tableHead);" in ingredient_tools
    assert 'tableBodyScroll.addEventListener(\n            "scroll"' in ingredient_tools
    assert "syncRecipeEditIngredientTableHeaderScroll(tableScroll);" in ingredient_tools
    assert "headerViewport.scrollLeft = bodyScroll.scrollLeft;" in header_scroll
    assert ".recipe-edit-ingredient-table-head-viewport" in sticky_css
    assert "position: sticky;" in sticky_css
    assert "z-index: 35;" in sticky_css
    assert "overflow: hidden;" in sticky_css


def test_grouped_choice_controls_use_one_stable_member_anchor_after_section_reordering():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped choice anchor coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    sync_toggles = javascript_function_source(
        script,
        "syncRecipeIngredientSelectedOptionToggles",
    )
    alternative_summary_ids = javascript_function_source(
        script,
        "recipeIngredientColumnViewAlternativeSummaryIds",
    )
    ensure_option_row_id = javascript_function_source(
        script,
        "ensureRecipeIngredientColumnViewOptionRowId",
    )
    stable_presentation_id = javascript_function_source(
        script,
        "recipeIngredientStablePresentationId",
    )
    harness = r"""
function classes(...initial) {
    const values = new Set(initial);
    return {
        contains(name) { return values.has(name); },
        toggle(name, enabled) {
            if (enabled) values.add(name);
            else values.delete(name);
        },
    };
}
function cell() {
    return {
        classList: classes(),
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = String(value); },
    };
}
function button() {
    const owner = cell();
    const label = {textContent: ""};
    const detail = {textContent: "", hidden: false};
    return {
        hidden: true,
        disabled: false,
        title: "",
        classList: classes(),
        attributes: {},
        owner,
        querySelector(selector) {
            if (selector.includes("ingredient-options-label")) return label;
            if (selector.includes("ingredient-options-summary")) return detail;
            return null;
        },
        closest() { return owner; },
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name] ?? null; },
        removeAttribute(name) { delete this.attributes[name]; },
    };
}
function source(id, order) {
    return {
        id,
        alternative_component_order: order,
        dataset: {ingredientExpansionId: id},
    };
}
function summary(id, sourceRow) {
    return {
        id,
        hidden: false,
        isConnected: true,
        recipeIngredientOptionSourceRow: sourceRow,
        button: button(),
    };
}
function alternativeSource(id, order) {
    const item = source(id, order);
    item.groupedSummary = summary("", item);
    return item;
}
function fieldValuesFromRow(row) { return row || {}; }
function recipeIngredientColumnViewEntryStableId(sourceRow, parentRow) {
    return String(sourceRow?.id || parentRow?.id || "ingredient");
}
function recipeIngredientColumnViewChoiceOptions(row) { return row.presentation; }
function recipeIngredientColumnViewOptionSummary(_parentRow, sourceRow) {
    return sourceRow?.groupedSummary || null;
}
let visibleOptionRows = [];
const document = {
    querySelectorAll() { return visibleOptionRows; },
};
function ensureRecipeIngredientExpansionId(row) {
    return row.dataset.ingredientExpansionId;
}
function visibleOptionRow(id, parentId) {
    return {
        id,
        dataset: {recipeIngredientChoiceParentId: parentId},
        classList: classes(),
    };
}

const sourceButtonLabel = {textContent: "2 options"};
const sourceButtonSummary = {textContent: "", hidden: true};
const sourceButton = {
    disabled: false,
    title: "Show 2 ingredient options",
    classList: classes("has-selected-option"),
    attributes: {
        "aria-controls": "corn-choice-panel",
        "aria-label": "Show 2 ingredient options",
    },
    querySelector(selector) {
        if (selector.includes("ingredient-options-label")) return sourceButtonLabel;
        if (selector.includes("ingredient-options-summary")) return sourceButtonSummary;
        return null;
    },
    getAttribute(name) { return this.attributes[name] ?? null; },
};
const cornSource = source("component-corn", 0);
const cuminSource = source("component-cumin", 1);
const onionSource = source("component-onion", 2);
const corn = summary("corn", cornSource);
const cumin = summary("cumin", cuminSource);
const onion = summary("onion", onionSource);
const frozenCornSource = alternativeSource("component-frozen-corn", 0);
const alternativeOnionSource = alternativeSource("component-alternative-onion", 1);
cornSource.groupedSummary = corn;
cuminSource.groupedSummary = cumin;
onionSource.groupedSummary = onion;
const parent = {
    id: "requirement-corn",
    dataset: {ingredientExpansionId: "requirement-corn"},
    classList: classes("is-ingredient-store-section-grouped-choice"),
    recipeIngredientColumnViewEntries: [
        {
            row: corn,
            sourceRow: cornSource,
            optionId: "option-default",
            manualIndex: 0,
            anchor: true,
        },
        {row: cumin, sourceRow: cuminSource, optionId: "option-default", manualIndex: 1},
        {row: onion, sourceRow: onionSource, optionId: "option-default", manualIndex: 2},
    ],
    presentation: {
        groups: [
            {id: "option-default", rows: [cornSource, cuminSource, onionSource], isSelected: true},
            {
                id: "option-frozen",
                rows: [frozenCornSource, alternativeOnionSource],
                isSelected: false,
            },
        ],
    },
    recipeIngredientGroupedChoiceAnchorSummary: corn,
    querySelector(selector) {
        return selector.includes("ingredient-substitutions-toggle") ? sourceButton : null;
    },
};
corn.recipeIngredientChoiceParentRow = parent;
cumin.recipeIngredientChoiceParentRow = parent;
onion.recipeIngredientChoiceParentRow = parent;
let summaries = [cumin, onion, corn];
let expanded = false;
function recipeIngredientSelectedOptionSummaries() { return summaries; }
function ensureRecipeIngredientSelectedOptionToggle(_row, item) { return item.button; }
function recipeIngredientExpansionIsOpen() { return expanded; }
function recipeIngredientDisclosureActionText(value, isExpanded) {
    const action = isExpanded ? "Collapse" : "Show";
    return String(value || "").replace(/^(?:Show|Collapse)/, action);
}
""" + stable_presentation_id + "\n" + ensure_option_row_id + "\n" + alternative_summary_ids + "\n" + sync_toggles + r"""

function state() {
    const visible = summaries.filter(item => !item.button.hidden);
    const controls = visible.map(item => item.button.getAttribute("aria-controls"));
    const controlIds = controls.flatMap(value => String(value || "")
        .split(/\s+/)
        .filter(Boolean));
    const alternativeIds = parent.presentation.groups
        .filter(group => !group.isSelected)
        .flatMap(group => group.rows.map(item => item.groupedSummary.id));
    const visibleAlternativeIds = expanded
        ? visibleOptionRows
            .filter(item => (
                item.dataset.recipeIngredientChoiceParentId
                    === parent.dataset.ingredientExpansionId
                && !item.classList.contains(
                    "is-recipe-ingredient-column-selected-option",
                )
            ))
            .map(item => item.id)
        : [];
    return {
        visibleIds: visible.map(item => item.id),
        controls,
        controlIds,
        alternativeIds,
        visibleAlternativeIds,
        controlsResolveToAlternatives: controlIds.every(id => alternativeIds.includes(id)),
        controlsResolveToVisibleAlternatives: Boolean(
            expanded
            && controlIds.length
            && controlIds.every(id => visibleAlternativeIds.includes(id)),
        ),
        usesSourcePanelFallback: controlIds.includes("corn-choice-panel"),
        expanded: visible.map(item => item.button.getAttribute("aria-expanded")),
        labels: visible.map(item => item.button.getAttribute("aria-label")),
        hiddenCells: summaries
            .filter(item => item.button.hidden)
            .every(item => item.button.owner.attributes["aria-hidden"] === "true"),
    };
}

recipeIngredientColumnViewAlternativeSummaryIds(parent);
syncRecipeIngredientSelectedOptionToggles(parent);
const collapsed = state();
summaries = [onion, corn, cumin];
parent.presentation.groups[1].rows = [alternativeOnionSource, frozenCornSource];
expanded = true;
visibleOptionRows = recipeIngredientColumnViewAlternativeSummaryIds(parent)
    .map(id => visibleOptionRow(id, parent.dataset.ingredientExpansionId));
syncRecipeIngredientSelectedOptionToggles(parent);
const expandedAfterReorder = state();
parent.presentation.groups[0].isSelected = false;
parent.presentation.groups[1].isSelected = true;
parent.recipeIngredientGroupedChoiceAnchorSummary = frozenCornSource.groupedSummary;
summaries = [
    alternativeOnionSource.groupedSummary,
    frozenCornSource.groupedSummary,
];
visibleOptionRows = recipeIngredientColumnViewAlternativeSummaryIds(parent)
    .map(id => visibleOptionRow(id, parent.dataset.ingredientExpansionId));
syncRecipeIngredientSelectedOptionToggles(parent);
const switchedOption = state();
process.stdout.write(JSON.stringify({
    collapsed,
    expandedAfterReorder,
    switchedOption,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    collapsed = result["collapsed"]
    expanded = result["expandedAfterReorder"]
    switched = result["switchedOption"]
    assert collapsed["visibleIds"] == ["corn"]
    assert collapsed["expanded"] == ["false"]
    assert collapsed["labels"] == ["Show 2 ingredient options"]
    assert collapsed["hiddenCells"] is True
    assert len(collapsed["alternativeIds"]) == 2
    assert len(set(collapsed["alternativeIds"])) == 2
    assert all(
        item.startswith("recipeIngredientGroupedOption-")
        for item in collapsed["alternativeIds"]
    )
    assert set(collapsed["controlIds"]) == set(collapsed["alternativeIds"])
    assert collapsed["controlsResolveToAlternatives"] is True
    assert collapsed["controlsResolveToVisibleAlternatives"] is False
    assert collapsed["visibleAlternativeIds"] == []
    assert collapsed["usesSourcePanelFallback"] is False

    assert expanded["visibleIds"] == ["corn"]
    assert expanded["expanded"] == ["true"]
    assert expanded["labels"] == ["Collapse 2 ingredient options"]
    assert expanded["hiddenCells"] is True
    assert set(expanded["alternativeIds"]) == set(collapsed["alternativeIds"])
    assert set(expanded["controlIds"]) == set(collapsed["alternativeIds"])
    assert expanded["controlsResolveToAlternatives"] is True
    assert expanded["controlsResolveToVisibleAlternatives"] is True
    assert expanded["usesSourcePanelFallback"] is False

    assert switched["visibleIds"] == [collapsed["alternativeIds"][0]]
    assert switched["expanded"] == ["true"]
    assert switched["labels"] == ["Collapse 2 ingredient options"]
    assert switched["hiddenCells"] is True
    assert switched["alternativeIds"] == ["corn", "cumin", "onion"]
    assert set(switched["controlIds"]) == set(switched["alternativeIds"])
    assert switched["controlsResolveToAlternatives"] is True
    assert switched["visibleAlternativeIds"] == ["corn", "cumin", "onion"]
    assert switched["controlsResolveToVisibleAlternatives"] is True
    assert switched["usesSourcePanelFallback"] is False


def test_grouped_choice_anchor_identity_supports_current_and_idless_legacy_members():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped choice identity coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helpers = "\n".join(
        javascript_function_source(script, function_name)
        for function_name in (
            "recipeIngredientColumnViewEntryStableId",
            "recipeIngredientColumnViewOptionComponentOrder",
            "recipeIngredientColumnViewOptionPrimaryIds",
            "recipeIngredientColumnViewOptionAnchor",
        )
    )
    harness = r"""
function fieldValuesFromRow(row) { return row || {}; }
function recipeIngredientStablePresentationId(...parts) {
    return parts.map(part => String(part ?? "").trim()).join("|");
}
""" + helpers + r"""

const parent = {
    recipeIngredientId: "requirement-current",
    primaryIngredientId: "member-current-primary",
};
const explicitPrimary = {
    substitutionId: "member-current-primary",
    ingredient: "Corn",
    storeSection: "Produce",
    alternativeComponentOrder: 2,
};
const explicitOther = {
    substitution_id: "member-current-other",
    ingredient: "Cumin",
    store_section: "Spices",
    alternative_component_order: 0,
};
const explicitEntries = [explicitOther, explicitPrimary].map((source, index) => ({
    sourceRow: source,
    stableId: recipeIngredientColumnViewEntryStableId(
        source,
        parent,
        "option-current",
        index,
    ),
    componentOrder: recipeIngredientColumnViewOptionComponentOrder(source),
}));

const legacyParent = {recipeIngredientId: "requirement-legacy"};
const legacyFirst = {
    ingredient: "Legacy corn",
    storeSection: "Produce",
    alternativeComponentOrder: 0,
    quantityText: "1 cup",
};
const legacySecond = {
    ingredient: "Legacy cumin",
    storeSection: "Spices",
    alternativeComponentOrder: 1,
};
function legacyEntry(source, manualIndex) {
    return {
        sourceRow: source,
        stableId: recipeIngredientColumnViewEntryStableId(
            source,
            legacyParent,
            "legacy-option",
            manualIndex,
        ),
        componentOrder: recipeIngredientColumnViewOptionComponentOrder(source),
    };
}
const legacyEntries = [legacyEntry(legacySecond, 8), legacyEntry(legacyFirst, 7)];
const result = {
    explicitIds: explicitEntries.map(entry => entry.stableId),
    explicitAnchor: recipeIngredientColumnViewOptionAnchor(
        parent,
        explicitEntries,
    )?.stableId,
    legacyStableAcrossViewOrder: legacyEntry(legacyFirst, 0).stableId
        === legacyEntry(legacyFirst, 99).stableId,
    legacyIdsUnique: new Set(legacyEntries.map(entry => entry.stableId)).size,
    legacyAnchor: recipeIngredientColumnViewOptionAnchor(
        legacyParent,
        legacyEntries,
    )?.stableId,
    legacyExpectedAnchor: legacyEntry(legacyFirst, 1).stableId,
};
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert {
        key: result[key]
        for key in (
            "explicitIds",
            "explicitAnchor",
            "legacyStableAcrossViewOrder",
            "legacyIdsUnique",
        )
    } == {
        "explicitIds": ["member-current-other", "member-current-primary"],
        "explicitAnchor": "member-current-primary",
        "legacyStableAcrossViewOrder": True,
        "legacyIdsUnique": 2,
    }
    assert result["legacyAnchor"] == result["legacyExpectedAnchor"]


def test_grouped_option_switch_round_trip_keeps_ids_unique_and_idrefs_unambiguous():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for grouped option ID coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    stable_presentation_id = javascript_function_source(
        script,
        "recipeIngredientStablePresentationId",
    )
    entry_stable_id = javascript_function_source(
        script,
        "recipeIngredientColumnViewEntryStableId",
    )
    ensure_option_row_id = javascript_function_source(
        script,
        "ensureRecipeIngredientColumnViewOptionRowId",
    )
    harness = r"""
function fieldValuesFromRow(row) { return row?.values || {}; }
""" + stable_presentation_id + "\n" + entry_stable_id + "\n" + ensure_option_row_id + r"""

const parent = {
    dataset: { ingredientExpansionId: "ingredient-group:requirement-corn" },
    values: { recipe_ingredient_id: "requirement-corn", ingredient: "corn" },
};
const replacementSource = {
    dataset: { ingredientExpansionId: "ingredient-option:replacement-corn:0" },
    values: {
        substitution_id: "replacement-corn-component",
        ingredient_id: "frozen-corn",
        ingredient: "frozen corn",
    },
};
const originalOptionId = "option-original";
const replacementOptionId = "option-replacement";
const canonicalOriginal = { id: "" };
const canonicalReplacement = { id: "" };

function assign(summary, optionId, sourceRow, role) {
    return ensureRecipeIngredientColumnViewOptionRowId(
        summary,
        parent,
        optionId,
        sourceRow,
        0,
        role,
    );
}

function disclosureState(connected, controlledIds) {
    const disclosure = {
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = String(value); },
        getAttribute(name) { return this.attributes[name] || ""; },
    };
    disclosure.setAttribute("aria-controls", controlledIds.join(" "));
    const ids = connected.map(summary => summary.id).filter(Boolean);
    const references = disclosure.getAttribute("aria-controls")
        .split(/\s+/)
        .filter(Boolean);
    return {
        ids,
        references,
        uniqueIds: new Set(ids).size === ids.length,
        referenceMatches: references.map(id => ids.filter(value => value === id).length),
    };
}

const selectedOriginalFirst = { id: "" };
const selectedOriginalFirstId = assign(
    selectedOriginalFirst,
    originalOptionId,
    parent,
    "selected",
);
const replacementAlternativeId = assign(
    canonicalReplacement,
    replacementOptionId,
    replacementSource,
    "alternative",
);
const initial = disclosureState(
    [canonicalOriginal, canonicalReplacement, selectedOriginalFirst],
    [replacementAlternativeId],
);

const originalAlternativeId = assign(
    canonicalOriginal,
    originalOptionId,
    parent,
    "alternative",
);
const selectedReplacement = { id: "" };
const selectedReplacementId = assign(
    selectedReplacement,
    replacementOptionId,
    replacementSource,
    "selected",
);
const switched = disclosureState(
    [canonicalOriginal, canonicalReplacement, selectedReplacement],
    [originalAlternativeId],
);

const selectedOriginalAgain = { id: "" };
const selectedOriginalAgainId = assign(
    selectedOriginalAgain,
    originalOptionId,
    parent,
    "selected",
);
const roundTrip = disclosureState(
    [canonicalOriginal, canonicalReplacement, selectedOriginalAgain],
    [replacementAlternativeId],
);

process.stdout.write(JSON.stringify({
    initial,
    switched,
    roundTrip,
    selectedOriginalStable: selectedOriginalFirstId === selectedOriginalAgainId,
    selectedAndSourceDiffer: selectedReplacementId !== replacementAlternativeId,
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["selectedOriginalStable"] is True
    assert result["selectedAndSourceDiffer"] is True
    for state_name in ("initial", "switched", "roundTrip"):
        state = result[state_name]
        assert state["uniqueIds"] is True
        assert state["references"]
        assert state["referenceMatches"] == [1] * len(state["references"])


def test_store_section_grouping_toggle_preserves_choice_expansion_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    handler_start = script.index(
        'menu.querySelector("[data-recipe-ingredient-column-view-group-store]")'
    )
    handler_end = script.index(
        'menu.querySelectorAll("[data-recipe-ingredient-column-view-filter]")',
        handler_start,
    )
    handler = script[handler_start:handler_end]

    assert "captureRecipeIngredientChoiceExpansionState()" in handler
    assert "applyRecipeIngredientColumnView({ announce: true });" in handler
    assert "restoreRecipeIngredientChoiceExpansionState(" in handler
    assert handler.index("captureRecipeIngredientChoiceExpansionState()") < handler.index(
        "applyRecipeIngredientColumnView({ announce: true });"
    )
    assert handler.index("applyRecipeIngredientColumnView({ announce: true });") < handler.index(
        "restoreRecipeIngredientChoiceExpansionState("
    )


def test_selected_option_block_is_atomic_and_hides_only_its_duplicate_source():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    selected_block = script[
        script.index("function ensureRecipeIngredientSelectedOptionBlock"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    source_visibility = script[
        script.index("function syncRecipeIngredientSourceOptionBlockVisibility"):
        script.index("function materializeRecipeIngredientDefaultOption")
    ]
    header = script[
        script.index("function createRecipeIngredientOptionHeader"):
        script.index("function updateRecipeIngredientOptionSelectionState")
    ]
    selection = script[
        script.index("function setRecipeIngredientOptionSelected"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]
    atomic_css = css[css.index(
        "/* Ingredient editor v112: every selected ingredient option renders as one atomic block. */"
    ):]

    assert 'block.dataset.ingredientSelectedOptionBlock = "";' in selected_block
    assert 'block.dataset.ingredientOptionBlock = "";' in selected_block
    assert "const home = row.recipeIngredientSubstitutionHome;" in selected_block
    assert "const homeIsInRow = Boolean(home?.parentNode === row);" in selected_block
    assert "const reference = homeIsInRow" in selected_block
    assert "? home" in selected_block
    assert ": (optionsPanel?.parentNode === row ? optionsPanel : null);" in selected_block
    assert "row.insertBefore(block, reference);" in selected_block
    assert "else if (homeIsInRow && block.nextSibling !== home)" in selected_block
    assert "row.insertBefore(block, home);" in selected_block
    assert "createRecipeIngredientOptionHeader({" in selected_block
    assert "selected: true," in selected_block
    assert '":scope > [data-ingredient-option-header]"' in selected_block
    assert '":scope > [data-ingredient-selected-option-line-item]"' in selected_block
    assert '":scope > [data-ingredient-option-actions]"' in selected_block
    assert "renderRecipeIngredientOptionBlock(lineItems, {" in selected_block
    assert "header," in selected_block
    assert "ingredientContent: summaries," in selected_block
    assert "actions: [action]," in selected_block
    assert "action.hidden = !expanded;" in selected_block
    assert 'action.setAttribute("aria-hidden", String(!expanded));' in selected_block
    assert "lineItems.hidden = !hasRenderedRows;" in selected_block
    assert "recipeEditIngredientColumnView.groupByStoreSection" not in selected_block

    assert 'header.dataset.ingredientOptionHeader = "";' in header
    assert 'status.dataset.ingredientOptionSelectedStatus = "";' in header
    assert 'status.setAttribute("role", "status");' in header
    assert 'status.setAttribute("aria-label", "Selected ingredient option");' in header

    assert 'block.classList.contains("is-selected-option")' in source_visibility
    assert 'block.classList.toggle("is-selected-option-source", hidesSelectedSource);' in source_visibility
    assert "block.hidden = hidesSelectedSource;" in source_visibility
    assert 'block.toggleAttribute("inert", hidesSelectedSource);' in source_visibility
    assert 'block.setAttribute("aria-hidden", "true");' in source_visibility
    assert "delete block.dataset.ingredientOptionBlock;" in source_visibility
    assert "delete header.dataset.ingredientOptionHeader;" in source_visibility

    # Selecting an alternative hides its source card immediately. Focus must be
    # handed to the equivalent visible selected block control or parent disclosure.
    assert "const selectionTriggerHadFocus = Boolean(" in selection
    assert "button === document.activeElement" in selection
    assert "option.contains(document.activeElement)" in selection
    assert "if (!modalIsActive && selectionTriggerHadFocus)" in selection
    assert '":scope > [data-ingredient-selected-option-block]"' in selection
    assert "const selectedMenuButton = selectedBlock?.querySelector(" in selection
    assert '"[data-ingredient-substitutions-toggle]"' in selection
    assert "const groupedDisclosure = ingredientRow" in selection
    assert ".recipeIngredientGroupedChoiceAnchorSummary" in selection
    assert '?.querySelector("[data-ingredient-selected-option-toggle]");' in selection
    assert "const focusTarget = groupedDisclosure || selectedMenuButton || disclosure;" in selection
    assert '!focusTarget.closest("[hidden], [inert]")' in selection
    assert "focusTarget.focus({ preventScroll: true });" in selection

    assert ".is-selected-option-source" in atomic_css
    assert "display: none !important;" in atomic_css
    assert ".has-section-placed-selected-option" not in selected_block
    assert ".has-section-placed-selected-option" not in atomic_css


def test_option_block_renderer_and_add_another_use_real_dom_order():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for ingredient option DOM-order coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    renderer = script[
        script.index("function renderRecipeIngredientOptionBlock"):
        script.index("function updateRecipeIngredientOptionSelectionState")
    ]
    harness = renderer + r"""
function node(id) { return { id }; }
function block() {
    return {
        dataset: {},
        children: [],
        replaceChildren(...children) { this.children = children; },
    };
}
const selected = block();
renderRecipeIngredientOptionBlock(selected, {
    header: node("default-header"),
    ingredientContent: [node("butter"), node("milk")],
    actions: [node("add-to-default")],
});
const alternative = block();
renderRecipeIngredientOptionBlock(alternative, {
    header: node("alternative-header"),
    ingredientContent: [node("unsalted-butter")],
    actions: [node("add-to-alternative")],
    trailing: [node("edit-footer")],
});
console.log(JSON.stringify({
    selected: selected.children.map(child => child.id),
    alternative: alternative.children.map(child => child.id),
    selectedMarked: Object.hasOwn(selected.dataset, "ingredientOptionBlock"),
    alternativeMarked: Object.hasOwn(alternative.dataset, "ingredientOptionBlock"),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "selected": ["default-header", "butter", "milk", "add-to-default"],
        "alternative": [
            "alternative-header",
            "unsalted-butter",
            "add-to-alternative",
            "edit-footer",
        ],
        "selectedMarked": True,
        "alternativeMarked": True,
    }

    row_markup = script[
        script.index("function addRecipeIngredientRow"):
        script.index("function bindRecipeIngredientSummaryUpdates")
    ]
    list_markup = '<div class="recipe-edit-substitution-list" data-ingredient-substitution-list>'
    add_another_markup = '<div class="recipe-edit-substitution-heading">'
    assert row_markup.index(list_markup) < row_markup.index(add_another_markup)

    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]
    assert 'const addAnother = container?.querySelector(' in substitution_state
    assert 'if (addAnother && container.lastElementChild !== addAnother)' in substitution_state
    assert "container.appendChild(addAnother);" in substitution_state

    heading_selector = (
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-options-panel\n"
        "    > .recipe-edit-substitution-heading {"
    )
    heading_rule = css[css.index(heading_selector):]
    heading_rule = heading_rule[:heading_rule.index("}")]
    list_selector = (
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-options-panel\n"
        "    > .recipe-edit-substitution-list {"
    )
    list_rule = css[css.index(list_selector):]
    list_rule = list_rule[:list_rule.index("}")]
    assert "order:" not in heading_rule
    assert "order:" not in list_rule
    assert (
        "> .recipe-edit-ingredient-choice-overview {\n"
        "    order:"
    ) not in css


def test_atomic_selected_option_rows_inherit_their_choice_state_badge():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    update_start = script.index("function updateRecipeIngredientOptionRowSummary")
    update_end = script.index("function updateRecipeIngredientAlternativeComponentSummary", update_start)
    update_summary = script[update_start:update_end]
    create_start = script.index("function createRecipeIngredientSelectedOptionLineItem")
    create_end = script.index("function resizeRecipeIngredientChoiceTitleInput", create_start)
    create_line_item = script[create_start:create_end]
    sync_start = script.index("function syncRecipeIngredientSelectedOptionLineItems")
    sync_end = script.index("function organizeRecipeEditSubstitutionOptionRow", sync_start)
    sync_line_items = script[sync_start:sync_end]

    assert 'summary.querySelector("[data-ingredient-source-text]")' in update_summary
    assert 'selectionStateElement.classList.toggle("is-selected-choice", Boolean(selectionState));' in update_summary
    assert "selectionStateElement.hidden = !selectionState;" in update_summary
    assert "`${selectionState}: ${selectionDetails}`" in update_summary
    assert "options = {}" in create_line_item
    assert "summary.dataset.ingredientSelectedChoiceState = selectionState;" in create_line_item
    assert "summary.dataset.ingredientSelectedChoiceDetails = selectionDetails;" in create_line_item
    assert "selectedChoice.selectionLabel" in sync_line_items
    assert "selectedChoice?.summary" in sync_line_items
    assert "recipeIngredientOptionTypeLabel(selectedChoice.isDefaultOption)" in sync_line_items
    assert "createRecipeIngredientSelectedOptionLineItem(row, sourceRow, {" in sync_line_items
    assert "selectionState," in sync_line_items
    assert "selectionDetails," in sync_line_items
    assert "renderRecipeIngredientOptionBlock(lineItems, {" in sync_line_items
    assert "ingredientContent: summaries," in sync_line_items
    assert "function syncRecipeIngredientColumnViewGroupProjection" not in script


def test_projected_replacement_move_uses_visible_store_section_siblings_and_drag_drop():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helpers = script[
        script.index("function recipeIngredientProjectedSummaryFromControl"):
        script.index("function recipeIngredientSubstitutionConfidencePercent")
    ]
    move = script[
        script.index("function moveRecipeIngredientAlternativeComponent"):
        script.index("function moveRecipeIngredientAlternative(control")
    ]

    assert "function recipeIngredientColumnViewManualRowsInSection" in helpers
    assert "style.order" not in helpers
    assert "Number.parseFloat" not in helpers
    assert 'recipeIngredientColumnViewEntry(displayRow, "store").key' in helpers
    assert 'recipeIngredientColumnViewEntry(row, "store").key === sectionKey' in helpers
    assert 'row.classList.contains("is-ingredient-column-filtered")' in helpers
    assert "visibleRows[currentIndex + offset]" in helpers
    assert "recipeIngredientTopLevelSourceRow(displayRow)" in helpers
    assert "recipeIngredientTopLevelSourceRow(targetDisplayRow)" in helpers
    assert "recipeEditCanDropOnRow(sourceParentRow, targetParentRow)" in helpers
    assert "dropRecipeEditRow(" in move
    assert "projectedMove.sourceRow" in move
    assert "projectedMove.targetRow" in move
    assert "projectedMove.insertAfter" in move
    assert "updateRecipeIngredientSummary(sourceParentRow);" in move


def test_store_section_grouping_preserves_serialized_top_level_order_without_projections():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    grouped_view = javascript_function_source(
        script,
        "prepareRecipeIngredientColumnViewDisplayRows",
    )
    collection = script[
        script.index("function collectRecipeIngredientRows"):
        script.index("function collectRecipeNutritionRows")
    ]

    assert "clearRecipeIngredientColumnViewSectionFragments" in grouped_view
    assert "syncRecipeIngredientColumnViewSectionFragments" in grouped_view
    assert "projectionAnchor" not in grouped_view
    assert 'insertAdjacentElement("afterend", projection)' not in grouped_view
    assert "cloneNode" not in grouped_view
    assert ".style.order" not in grouped_view
    assert "function createRecipeIngredientColumnViewGroupProjection" not in script
    assert "return recipeEditIngredientRows()" in collection
    assert ".map(row => {" in collection
    assert "const item = fieldValuesFromRow(row);" in collection
    assert "data-recipe-ingredient-column-section-fragment" not in collection


def test_physical_grouping_order_does_not_change_serialized_canonical_ingredient_order():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for canonical ingredient-order coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    functions = "\n".join([
        javascript_function_source(script, "recipeIngredientColumnViewCanonicalOrder"),
        javascript_function_source(script, "ensureRecipeIngredientColumnViewCanonicalOrder"),
        javascript_function_source(script, "reconcileRecipeIngredientColumnViewOrder"),
        javascript_function_source(script, "restoreRecipeIngredientColumnViewCanonicalOrder"),
        javascript_function_source(script, "recipeEditIngredientRows"),
        javascript_function_source(script, "collectRecipeIngredientRows"),
    ])
    harness = r"""
function classes(...names) {
    const values = new Set(names);
    return {contains(name) { return values.has(name); }};
}
function row(id, order) {
    return {
        id,
        ingredient: id,
        recipeIngredientColumnViewCanonicalOrder: order,
        classList: classes("recipe-edit-ingredient-row"),
        dataset: {},
        style: {removeProperty() {}},
    };
}
const first = row("first", 0);
const second = row("second", 1);
const third = row("third", 2);
const list = {
    children: [third, first, second],
    get firstChild() { return this.children[0] || null; },
    appendChild(item) {
        const index = this.children.indexOf(item);
        if (index >= 0) this.children.splice(index, 1);
        this.children.push(item);
    },
    insertBefore(item, cursor) {
        const currentIndex = this.children.indexOf(item);
        if (currentIndex >= 0) this.children.splice(currentIndex, 1);
        const cursorIndex = this.children.indexOf(cursor);
        if (cursorIndex >= 0) this.children.splice(cursorIndex, 0, item);
        else this.children.push(item);
    },
};
[first, second, third].forEach(item => Object.defineProperty(item, "nextSibling", {
    get() {
        const index = list.children.indexOf(item);
        return index >= 0 ? (list.children[index + 1] || null) : null;
    },
}));
const document = {
    activeElement: null,
    getElementById(id) { return id === "recipeEditIngredients" ? list : null; },
};
function fieldValuesFromRow(item) { return {ingredient: item.ingredient}; }
function recipeIngredientTypeValue() { return "main"; }
function recipeIngredientIsOptional() { return false; }
function recipeIngredientMatchItemFromRow() { return null; }
function recipeIngredientMatchSnapshot() { return {}; }
function recipeIngredientFoodReviewPayload() { return null; }
function collectRecipeIngredientSubstitutionRows() { return []; }
function canonicalRecipeIngredientAmountForSave(item) { return item; }
""" + functions + r"""

const groupedRows = recipeEditIngredientRows().map(item => item.id);
const groupedPayload = JSON.stringify(collectRecipeIngredientRows());
restoreRecipeIngredientColumnViewCanonicalOrder(list, [...list.children]);
const restoredRows = recipeEditIngredientRows().map(item => item.id);
const restoredPayload = JSON.stringify(collectRecipeIngredientRows());
process.stdout.write(JSON.stringify({
    groupedRows,
    restoredRows,
    groupedPayload,
    restoredPayload,
    physicalOrder: list.children.map(item => item.id),
    canonicalMarkersCleared: list.children.every(item => (
        item.recipeIngredientColumnViewCanonicalOrder === undefined
    )),
}));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["groupedRows"] == ["first", "second", "third"]
    assert result["restoredRows"] == ["first", "second", "third"]
    assert result["physicalOrder"] == ["first", "second", "third"]
    assert result["groupedPayload"] == result["restoredPayload"]
    assert result["canonicalMarkersCleared"] is True


def test_replacement_move_actions_disable_at_visible_and_component_boundaries():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    organizer = script[
        script.index("function organizeRecipeEditSubstitutionOptionRow"):
        script.index("function editRecipeIngredientSubstitutionFields")
    ]
    availability = script[
        script.index("function recipeIngredientAlternativeComponentCanMove"):
        script.index("function recipeIngredientSubstitutionConfidencePercent")
    ]
    menu_toggle = script[
        script.index("function toggleRecipeEditRowMenu"):
        script.index("function toggleRecipeEditSectionMenu")
    ]

    assert 'data-alternative-component-move="-1"' in organizer
    assert 'data-alternative-component-move="1"' in organizer
    assert "Boolean(projectedMove.sourceRow && projectedMove.targetRow)" in availability
    assert "nextIndex >= 0 && nextIndex < rows.length" in availability
    assert "button.disabled = !canMove;" in availability
    assert 'No visible ingredient ${direction < 0 ? "above" : "below"} to move past.' in availability
    assert "syncRecipeIngredientAlternativeComponentMoveActions(menu, button);" in menu_toggle


def test_expanded_replacement_option_move_keeps_component_scoped_reordering():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    move = script[
        script.index("function moveRecipeIngredientAlternativeComponent"):
        script.index("function moveRecipeIngredientAlternative(control")
    ]
    internal_move = move[move.index("const optionRow ="):]

    assert 'components.querySelectorAll(":scope > [data-substitution-option-row]")' in internal_move
    assert "const nextIndex = index + (Number(direction) < 0 ? -1 : 1);" in internal_move
    assert "nextIndex < 0 || nextIndex >= rows.length" in internal_move
    assert "dropRecipeEditRow(optionRow, rows[nextIndex], nextIndex > index);" in internal_move


def test_selected_choice_header_uses_a_compact_flat_options_control():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    header_controls = css[css.index(
        "/* Ingredient editor v67: keep grouped choice header controls compact and flat. */"
    ):css.index("/* Ingredient editor v68:")]

    assert ".recipe-edit-selected-choice-group-header" in header_controls
    assert ".recipe-edit-ingredient-options-button" in header_controls
    assert "width: auto;" in header_controls
    assert "min-height: 30px;" in header_controls
    assert "border: 0;" in header_controls
    assert "border-radius: 0;" in header_controls
    assert "background: transparent !important;" in header_controls
    assert "box-shadow: none !important;" in header_controls
    assert "border-radius: 999px;" not in header_controls
    assert "> .recipe-edit-ingredient-options-copy" in header_controls
    assert "display: inline-flex !important;" in header_controls
    assert "[data-ingredient-options-label]" in header_controls
    assert "white-space: nowrap;" in header_controls


def test_store_section_grouping_promotes_actual_rows_with_compact_section_context():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    entries = javascript_function_source(script, "recipeIngredientColumnViewIngredientEntries")
    choice_entries = javascript_function_source(
        script,
        "recipeIngredientColumnViewChoiceEntries",
    )
    display_rows = javascript_function_source(
        script,
        "recipeIngredientColumnViewDisplayRows",
    )
    fragments = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    restore = javascript_function_source(
        script,
        "clearRecipeIngredientColumnViewSectionFragments",
    )
    prepare = javascript_function_source(
        script,
        "prepareRecipeIngredientColumnViewDisplayRows",
    )
    metadata = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionMetadata",
    )
    context_anchors = javascript_function_source(
        script,
        "assignRecipeIngredientColumnViewSectionContextAnchors",
    )
    context_key = javascript_function_source(
        script,
        "recipeIngredientColumnViewOptionContextKey",
    )
    context_sync = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionContext",
    )
    visible_contexts = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewVisibleSectionContexts",
    )
    apply_view = javascript_function_source(
        script,
        "applyRecipeIngredientColumnView",
    )

    assert "recipeIngredientColumnViewChoiceEntries" in entries
    assert "options.includeAlternatives" in choice_entries
    assert "presentation.expanded || presentation.requiredUnresolved" in choice_entries
    assert "selected: false" in choice_entries
    assert "counted: false" in choice_entries
    for field in (
        "stableId",
        "sourceRow",
        "parentRow",
        "optionId",
        "optionContextKey",
        "componentOrder",
        "store",
        "manualIndex",
        "anchor",
        "sectionContextAnchor",
    ):
        assert field in choice_entries
    assert "assignRecipeIngredientColumnViewSectionContextAnchors" in choice_entries
    assert "recipeIngredientColumnViewOptionContextKey" in choice_entries
    assert "const entriesBySection = new Map();" in context_anchors
    assert "options.visibleOnly" in context_anchors
    assert "sectionContextAnchors.has(entry)" in context_anchors
    assert 'if (optionId) return `id:${optionId}`;' in context_key
    assert "optionEntries.map(entry => entry.stableId).sort" in context_key
    assert '"recipeIngredientColumnOptionContext"' in context_key
    assert 'row.hasAttribute?.("data-recipe-ingredient-column-option-row")' in display_rows
    assert '"is-recipe-ingredient-column-source-carrier"' in display_rows
    assert "cloneNode" not in fragments
    assert ".style.order" not in fragments
    assert "replaceChildren" not in fragments
    assert "moveRecipeIngredientColumnViewNode(row, list)" in fragments
    assert "createRecipeIngredientOptionHeader" not in fragments
    assert "ingredientOptionContextHeader" not in fragments
    assert "ingredientEntries" in fragments
    assert 'row.dataset.recipeIngredientColumnOptionRow = "";' in fragments
    assert "row.dataset.recipeIngredientOptionMemberId = entry.stableId;" in fragments
    assert "row.dataset.recipeIngredientOptionId = entry.optionId;" in fragments
    assert "row.dataset.recipeIngredientOptionAnchor = String(entry.anchor);" in fragments
    assert "row.dataset.recipeIngredientOptionSectionContext" in context_sync
    assert '"is-recipe-ingredient-column-option-section-context"' in context_sync
    assert 'selectionState: showsOptionContext ? entry.optionLabel : ""' in (
        context_sync
    )
    assert "row.recipeIngredientColumnViewEntry = entry;" in fragments
    assert "setRecipeIngredientColumnViewSourceCarrier(parentRow);" in fragments
    assert "recipeIngredientColumnViewIngredientEntries" in prepare
    assert "includeAlternatives: recipeEditIngredientColumnView.groupByStoreSection" in prepare
    assert "syncRecipeIngredientColumnViewSectionFragments" in prepare
    assert "home.replaceWith(row);" in restore
    assert 'row.removeAttribute("data-recipe-ingredient-column-option-row");' in restore
    assert 'row.removeAttribute("data-recipe-ingredient-option-member-id");' in restore
    assert 'row.removeAttribute("data-recipe-ingredient-option-id");' in restore
    assert 'row.removeAttribute("data-recipe-ingredient-option-anchor");' in restore
    assert (
        'row.removeAttribute("data-recipe-ingredient-option-section-context");'
        in restore
    )
    assert "recipeIngredientColumnViewEntryShowsOptionContext" in context_sync
    assert "syncRecipeIngredientColumnViewOptionContext(entry);" in metadata
    assert "if (!entry.anchor) return;" in metadata
    assert "assignRecipeIngredientColumnViewSectionContextAnchors" in visible_contexts
    assert "entry.optionContextKey" in visible_contexts
    assert "{ visibleOnly: true }" in visible_contexts
    assert "optionEntries.forEach(syncRecipeIngredientColumnViewOptionContext);" in (
        visible_contexts
    )
    assert "syncRecipeIngredientColumnViewVisibleSectionContexts" in apply_view


def test_grouped_option_context_survives_selected_and_alternative_row_refreshes():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selected_refresh = javascript_function_source(
        script,
        "syncRecipeIngredientSelectedOptionLineItems",
    )
    alternative_refresh = javascript_function_source(
        script,
        "updateRecipeIngredientAlternativeComponentSummary",
    )
    accessibility = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewOptionAccessibility",
    )

    for refresh in (selected_refresh, alternative_refresh):
        assert "recipeIngredientColumnViewEntryShowsOptionContext" in refresh
        assert "syncRecipeIngredientColumnViewOptionAccessibility" in refresh
    assert "groupedEntry" in selected_refresh
    assert "groupedEntry" in alternative_refresh
    assert "entry.anchor ? entry.optionLabel" not in selected_refresh
    assert "groupedEntry?.anchor" not in alternative_refresh
    assert 'row.setAttribute(\n        "aria-label"' in accessibility
    assert 'entry.selected ? "selected " : ""' in accessibility


def test_grouped_option_context_moves_to_a_visible_member_when_filtered():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for filtered option-context coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    assign_context = javascript_function_source(
        script,
        "assignRecipeIngredientColumnViewSectionContextAnchors",
    )
    harness = r"""
function recipeIngredientColumnViewOptionAnchor(_parentRow, entries) {
    return entries.find(entry => entry.anchor) || entries[0] || null;
}
""" + assign_context + r"""

const parent = {id: "requirement-corn"};
const corn = {
    id: "corn",
    anchor: true,
    filtered: true,
    store: {key: "produce"},
};
const onion = {
    id: "onion",
    anchor: false,
    filtered: false,
    store: {key: "produce"},
};
const cumin = {
    id: "cumin",
    anchor: false,
    filtered: false,
    store: {key: "spices"},
};
const entries = [corn, onion, cumin];
function state() {
    return Object.fromEntries(entries.map(entry => [
        entry.id,
        entry.sectionContextAnchor,
    ]));
}

assignRecipeIngredientColumnViewSectionContextAnchors(
    parent,
    entries,
    {visibleOnly: true},
);
const anchorFiltered = state();
corn.filtered = false;
assignRecipeIngredientColumnViewSectionContextAnchors(
    parent,
    entries,
    {visibleOnly: true},
);
const filterCleared = state();
corn.filtered = true;
onion.filtered = true;
assignRecipeIngredientColumnViewSectionContextAnchors(
    parent,
    entries,
    {visibleOnly: true},
);
const produceHidden = state();
process.stdout.write(JSON.stringify({
    anchorFiltered,
    filterCleared,
    produceHidden,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "anchorFiltered": {"corn": False, "onion": True, "cumin": True},
        "filterCleared": {"corn": True, "onion": False, "cumin": True},
        "produceHidden": {"corn": False, "onion": False, "cumin": True},
    }


def test_filtered_context_keeps_distinct_idless_legacy_options_isolated():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for legacy option-context coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    stable_presentation_id = javascript_function_source(
        script,
        "recipeIngredientStablePresentationId",
    )
    context_key = javascript_function_source(
        script,
        "recipeIngredientColumnViewOptionContextKey",
    )
    assign_context = javascript_function_source(
        script,
        "assignRecipeIngredientColumnViewSectionContextAnchors",
    )
    sync_visible_context = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewVisibleSectionContexts",
    )
    harness = r"""
function recipeIngredientColumnViewEntryStableId(row) {
    return row.id;
}
function recipeIngredientColumnViewOptionAnchor(_parentRow, entries) {
    return entries.find(entry => entry.anchor) || entries[0] || null;
}
const contextSyncs = [];
function syncRecipeIngredientColumnViewOptionContext(entry) {
    contextSyncs.push(entry.stableId);
}
""" + stable_presentation_id + "\n" + context_key + "\n" + assign_context + "\n" + sync_visible_context + r"""

const parent = {
    id: "requirement-legacy",
    classList: {contains(name) { return name === "has-ingredient-choice"; }},
};
function entry(stableId, section, {anchor = false, filtered = false} = {}) {
    return {
        stableId,
        parentRow: parent,
        optionId: "",
        store: {key: section},
        anchor,
        filtered,
    };
}
const firstOption = [
    entry("first-corn", "produce", {anchor: true, filtered: true}),
    entry("first-onion", "produce"),
    entry("first-cumin", "spices"),
];
const secondOption = [
    entry("second-corn", "produce", {anchor: true}),
    entry("second-onion", "produce"),
    entry("second-pepper", "spices"),
];
const firstKey = recipeIngredientColumnViewOptionContextKey(
    parent,
    {id: "", selected: false},
    firstOption,
);
const secondKey = recipeIngredientColumnViewOptionContextKey(
    parent,
    {id: "", selected: false},
    secondOption,
);
firstOption.forEach(item => { item.optionContextKey = firstKey; });
secondOption.forEach(item => { item.optionContextKey = secondKey; });
syncRecipeIngredientColumnViewVisibleSectionContexts([
    ...firstOption,
    ...secondOption,
]);
function state(entries) {
    return Object.fromEntries(entries.map(item => [
        item.stableId,
        item.sectionContextAnchor,
    ]));
}
process.stdout.write(JSON.stringify({
    distinctKeys: firstKey !== secondKey,
    first: state(firstOption),
    second: state(secondOption),
    contextSyncs,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "distinctKeys": True,
        "first": {
            "first-corn": False,
            "first-onion": True,
            "first-cumin": True,
        },
        "second": {
            "second-corn": True,
            "second-onion": False,
            "second-pepper": True,
        },
        "contextSyncs": [
            "first-corn",
            "first-onion",
            "first-cumin",
            "second-corn",
            "second-onion",
            "second-pepper",
        ],
    }


def test_ungrouped_selected_option_block_remains_the_canonical_source_after_grouping():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    grouped_view = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    selected_block = script[
        script.index("function ensureRecipeIngredientSelectedOptionBlock"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    substitution_state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    restore = javascript_function_source(
        script,
        "clearRecipeIngredientColumnViewSectionFragments",
    )

    assert "ingredientEntries" in grouped_view
    assert "optionId" in grouped_view
    assert "parentRow" in grouped_view
    assert "cloneNode" not in grouped_view
    assert "data-recipe-ingredient-column-group-projection" not in grouped_view
    assert "entriesBySection" not in grouped_view
    assert "hostEntries" not in grouped_view
    assert "createRecipeIngredientOptionHeader" not in grouped_view
    assert "moveRecipeIngredientColumnViewNode(row, list)" in grouped_view
    assert "home.replaceWith(row);" in restore
    assert "delete row.recipeIngredientSelectedOptionBlock;" in restore
    assert "selectedChoiceUsesParentIngredientRow" not in substitution_state
    assert '"has-selected-implicit-default-choice"' not in substitution_state
    assert "hidesSelectedChoiceHeaderInStoreSectionView" not in substitution_state
    assert "hidesImplicitDefaultHeaderInStoreSectionView" not in substitution_state
    assert "syncRecipeIngredientSelectedOptionLineItems(" in substitution_state

    assert 'block.dataset.ingredientSelectedOptionBlock = "";' in selected_block
    assert 'block.dataset.ingredientOptionBlock = "";' in selected_block
    assert "createRecipeIngredientOptionHeader({" in selected_block
    assert "selected: true," in selected_block
    assert "block.prepend(header);" in selected_block
    assert "if (block.firstElementChild !== header) block.prepend(header);" in selected_block
    assert "const home = row.recipeIngredientSubstitutionHome;" in selected_block
    assert "const reference = homeIsInRow" in selected_block
    assert "row.insertBefore(block, reference);" in selected_block
    assert "else if (homeIsInRow && block.nextSibling !== home)" in selected_block
    assert "row.insertBefore(block, home);" in selected_block


def test_ingredient_choice_panel_mounts_on_parent_row_after_the_home_marker():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    expansion_start = script.index("function ensureRecipeIngredientExpansionId")
    expansion_end = script.index("function bindRecipeIngredientSubstitutionRows", expansion_start)
    expansion = script[expansion_start:expansion_end]
    toggle_start = script.index("function setRecipeIngredientSubstitutionsExpanded")
    toggle_end = script.index("function recipeIngredientSubstitutionDomGroups", toggle_start)
    toggle = script[toggle_start:toggle_end]

    assert "const recipeEditExpandedIngredientIds = new Set();" in script
    assert 'fieldValue("recipe_ingredient_id")' in expansion
    assert 'fieldValue("substitution_id")' in expansion
    assert "function recipeIngredientExpansionSelectedOptionSummary" in expansion
    assert "recipeEditIngredientColumnView.groupByStoreSection" in expansion
    assert "row?.recipeIngredientGroupedOptionsExpanded !== undefined" in expansion
    assert "return Boolean(row.recipeIngredientGroupedOptionsExpanded);" in expansion
    assert "recipeIngredientSelectedOptionSummaries(row).find" not in expansion
    assert "controlledSummary.recipeIngredientChoiceParentRow === row" in expansion
    assert "controlledSummary.recipeIngredientOptionSourceRow !== row" not in expansion
    assert "summary.recipeIngredientOptionSourceRow !== row" not in expansion
    assert "The parent disclosure always controls the parent's alternatives region." in expansion
    assert "return null;" in expansion
    assert "recipeIngredientExpansionSelectedOptionSummary(" in expansion
    assert "recipeIngredientExpansionAnchorFromControl" in expansion
    assert "function recipeIngredientExpansionAnchorFromControl(row, control = null)" in expansion
    assert "return row;" in expansion
    assert '"[data-recipe-ingredient-column-group-projection]"' not in expansion
    assert '"[data-recipe-ingredient-column-section-fragment]"' not in expansion
    assert 'anchor.insertAdjacentElement("afterend", container);' in expansion
    assert "row.appendChild(container);" in expansion
    assert "if (anchor === row)" in expansion
    assert "home.after(container);" in expansion
    assert "container.dataset.ingredientExpansionFor = expansionId;" in expansion
    assert "recipeEditExpandedIngredientIds.add(expansionId);" in expansion

    # Grouped choices expose their actual ingredient summaries as direct rows.
    # Keep the alternatives source panel hidden on the parent carrier and rebuild
    # the grouped rows instead of mounting that panel beside one promoted child.
    assert "const groupedStoreSectionChoice = Boolean(" in toggle
    assert 'row.classList.contains("has-ingredient-choice")' in toggle
    assert "row.recipeIngredientGroupedOptionsExpanded = Boolean(shouldOpen);" in toggle
    assert "container.hidden = true;" in toggle
    assert "updateRecipeIngredientSubstitutionState(row, control);" in toggle
    assert "applyRecipeIngredientColumnView();" in toggle

    assert "mountRecipeIngredientExpansion(row, container, control);" in toggle
    assert "recipeIngredientExpansionIsOpen(row, button)" in toggle
    assert "setRecipeIngredientSubstitutionsExpanded(row, button, true, options);" in toggle
    assert "setRecipeIngredientSubstitutionsExpanded(row, control, false, options);" in toggle

    attached_panel = css[css.index(
        "/* Ingredient editor v70: keep each choice panel attached to its disclosure row. */"
    ):]
    assert ".recipe-edit-selected-option-line-items" in attached_panel
    assert "> .recipe-edit-ingredient-options-panel" in attached_panel
    assert "padding: 10px 12px 12px;" in attached_panel
    assert "border-left: 3px solid" not in attached_panel
    assert "box-shadow: inset 3px 0 0" in attached_panel
    assert "@media (min-width: 768px)" in attached_panel
    assert "width: calc(100% + 24px);" in attached_panel
    assert "margin-inline: -12px;" in attached_panel
    assert "background: color-mix(" in attached_panel
    assert ".is-ingredient-expansion-anchor" in attached_panel


def test_grouped_choice_disclosure_ignores_hidden_modal_preview_rows():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the ingredient disclosure regression harness.")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    summaries_start = script.index("function recipeIngredientSelectedOptionSummaries")
    summaries_end = script.index("function ensureRecipeIngredientSelectedOptionToggle", summaries_start)
    expansion_start = script.index("function recipeIngredientExpansionSelectedOptionSummary")
    expansion_end = script.index("function recipeIngredientExpansionSourceRow", expansion_start)
    harness = """
const row = { id: "parent-row" };
const otherRow = { id: "other-row" };
const modalSummary = {
    id: "modal",
    recipeIngredientChoiceParentRow: row,
    closest(selector) {
        return selector === "[data-recipe-ingredient-edit-panel]" ? {} : null;
    },
    classList: { contains() { return false; } },
};
const tableSummary = {
    id: "table",
    recipeIngredientChoiceParentRow: row,
    closest() { return null; },
    classList: { contains() { return false; } },
};
const unrelatedSummary = {
    id: "other",
    recipeIngredientChoiceParentRow: otherRow,
    closest() { return null; },
    classList: { contains() { return false; } },
};
const sourceButton = { closest() { return null; } };
const tableButton = {
    closest(selector) {
        return selector === "[data-ingredient-selected-option-line-item]"
            ? tableSummary
            : null;
    },
};
const recipeEditIngredientColumnView = { groupByStoreSection: true };
const document = {
    querySelectorAll() { return [modalSummary, tableSummary, unrelatedSummary]; },
};
""" + script[summaries_start:summaries_end] + script[expansion_start:expansion_end] + """

const summaries = recipeIngredientSelectedOptionSummaries(row);
const fallback = recipeIngredientExpansionSelectedOptionSummary(row, sourceButton);
const directTable = recipeIngredientExpansionSelectedOptionSummary(row, tableButton);
document.querySelectorAll = () => [modalSummary];
const modalOnlyFallback = recipeIngredientExpansionSelectedOptionSummary(row, sourceButton);
process.stdout.write(JSON.stringify({
    summaryIds: summaries.map(summary => summary.id),
    fallbackId: fallback ? fallback.id : null,
    directTableId: directTable ? directTable.id : null,
    modalOnlyFallbackId: modalOnlyFallback ? modalOnlyFallback.id : null,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "summaryIds": ["table"],
        "fallbackId": None,
        "directTableId": "table",
        "modalOnlyFallbackId": None,
    }


def test_ingredient_choice_disclosure_preserves_the_visible_header_viewport_position():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    anchor_start = script.index("function recipeIngredientExpansionViewportAnchor")
    anchor_end = script.index("function setRecipeIngredientSubstitutionsExpanded", anchor_start)
    anchor = script[anchor_start:anchor_end]
    toggle_start = script.index("function toggleRecipeIngredientSubstitutions")
    toggle_end = script.index("function recipeIngredientSubstitutionDomGroups", toggle_start)
    toggle = script[toggle_start:toggle_end]

    assert "window.getComputedStyle(candidate).overflowY" in anchor
    assert "candidate.scrollHeight > candidate.clientHeight" in anchor
    assert "function recipeIngredientExpansionViewportAnchor" in anchor
    assert "return recipeIngredientExpansionAnchorFromControl(row, control) || row;" in anchor
    assert "const anchor = recipeIngredientExpansionViewportAnchor(row, control);" in anchor
    assert "const previousTop = anchor.getBoundingClientRect().top;" in anchor
    assert "const result = toggleExpansion();" in anchor
    assert "const newTop = anchor.getBoundingClientRect().top;" in anchor
    assert "const delta = newTop - previousTop;" in anchor
    assert "function recipeIngredientScrollMaximum" in anchor
    assert "function recipeIngredientScrollReserveState" in anchor
    assert "function releaseRecipeIngredientScrollReserve" in anchor
    assert "const targetScrollTop = Math.max(0, scrollContainer.scrollTop + delta);" in anchor
    assert "targetScrollTop > maximumScrollTop" in anchor
    assert "state.height + Math.ceil(targetScrollTop - maximumScrollTop) + 1" in anchor
    assert "scrollContainer.scrollTop = targetScrollTop;" in anchor
    assert 'window.scrollBy({ top: delta, behavior: "instant" });' in anchor
    assert anchor.count("restoreRecipeIngredientExpansionAnchor(") >= 2
    assert anchor.count("restoreAnchorIfCurrent()") >= 3
    assert "window.cancelAnimationFrame(row.recipeIngredientAnchorFrame);" in anchor
    assert "recipe-edit-ingredient-scroll-stabilizing" in anchor
    assert "state.stabilizationToken += 1;" in anchor
    assert "function ensureRecipeIngredientGroupHeaderVisible" in anchor
    assert 'anchor.closest?.("#recipeEditIngredients")' in anchor
    assert "groupHeader.previousElementSibling" in anchor
    assert "headerRect.bottom > tableHeadRect.top" in anchor
    assert "headerRect.top < tableHeadRect.bottom" in anchor
    assert "verticalScroller.scrollTop - overlap" in anchor
    assert anchor.rindex("ensureRecipeIngredientGroupHeaderVisible(") > anchor.rindex(
        "restoreAnchorIfCurrent()"
    )
    assert script.count("clearRecipeIngredientScrollReserve(appMainScrollRegion());") >= 2

    assert "toggleRecipeIngredientExpansionWithAnchor(" in toggle
    assert "row,\n        button,\n        () => (" in toggle
    assert "container.scrollIntoView" not in toggle
    assert "returnFocus.focus({ preventScroll: true });" in toggle
    assert "resetRecipeIngredientExpansionMount(otherRow, otherContainer);" not in toggle
    attached_panel = css[css.index(
        "/* Ingredient editor v70: keep each choice panel attached to its disclosure row. */"
    ):]
    assert "overflow-anchor: none;" in attached_panel
    assert ".recipe-edit-ingredient-scroll-stabilizing" in css
    assert ".recipe-edit-ingredient-scroll-reserve" in css


def test_ingredient_choice_scroll_reserve_bridges_the_maximum_scroll_clamp():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    helpers_start = script.index("function recipeIngredientScrollMaximum")
    helpers_end = script.index(
        "function toggleRecipeIngredientExpansionWithAnchor",
        helpers_start,
    )
    helpers = script[helpers_start:helpers_end]
    node = shutil.which("node")

    if not node:
        pytest.skip("Node.js is not available for the supplemental scroll-helper regression")

    harness = """
const recipeEditIngredientScrollReserveStates = new WeakMap();
const window = {
    scrollBy() {
        throw new Error("The element-scroll scenario must not fall back to window scrolling");
    },
};
const document = {
    createElement() {
        return {
            className: "",
            dataset: {},
            parentElement: null,
            style: {
                height: "",
                removeProperty(name) {
                    if (name === "height") this.height = "";
                },
            },
            setAttribute() {},
            remove() {
                const parent = this.parentElement;
                if (!parent) return;
                if (parent.spacer === this) parent.spacer = null;
                this.parentElement = null;
            },
        };
    },
};
""" + helpers + """
const scrollContainer = {
    baseScrollHeight: 640,
    clientHeight: 480,
    _scrollTop: 160,
    spacer: null,
    isConnected: true,
    get scrollHeight() {
        return this.baseScrollHeight
            + Number.parseFloat(this.spacer?.style.height || "0");
    },
    get scrollTop() {
        return this._scrollTop;
    },
    set scrollTop(value) {
        const maximum = Math.max(0, this.scrollHeight - this.clientHeight);
        this._scrollTop = Math.min(maximum, Math.max(0, Number(value) || 0));
    },
    addEventListener() {},
    appendChild(element) {
        this.spacer = element;
        element.parentElement = this;
    },
};
const anchor = {
    isConnected: true,
    getBoundingClientRect() {
        return { top: 500 };
    },
};

// The collapsed content leaves only 160px of native scroll range, but keeping
// the anchor at its previous 280px viewport position requires scrollTop 380.
restoreRecipeIngredientExpansionAnchor(anchor, 280, scrollContainer);
const state = recipeEditIngredientScrollReserveStates.get(scrollContainer);
const afterRestore = {
    reserveHeight: state.height,
    scrollTop: scrollContainer.scrollTop,
    maximum: recipeIngredientScrollMaximum(scrollContainer),
};

// Releasing 51px of slack must shrink the reserve without allowing the
// browser-like scrollTop setter to clamp the viewport upward.
scrollContainer.scrollTop = 330;
releaseRecipeIngredientScrollReserve(scrollContainer);
const afterPartialRelease = {
    reserveHeight: state.height,
    scrollTop: scrollContainer.scrollTop,
    maximum: recipeIngredientScrollMaximum(scrollContainer),
};

// Once enough real scroll range is available, the remainder can disappear.
scrollContainer.scrollTop = 100;
releaseRecipeIngredientScrollReserve(scrollContainer);
const afterFullRelease = {
    reserveHeight: state.height,
    scrollTop: scrollContainer.scrollTop,
    maximum: recipeIngredientScrollMaximum(scrollContainer),
    spacerConnected: Boolean(state.spacer.parentElement),
};

process.stdout.write(JSON.stringify({
    afterRestore,
    afterPartialRelease,
    afterFullRelease,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["afterRestore"] == {
        "reserveHeight": 221,
        "scrollTop": 380,
        "maximum": 381,
    }
    assert result["afterPartialRelease"] == {
        "reserveHeight": 170,
        "scrollTop": 330,
        "maximum": 330,
    }
    assert result["afterFullRelease"] == {
        "reserveHeight": 0,
        "scrollTop": 100,
        "maximum": 160,
        "spacerConnected": False,
    }


def test_recipe_editor_v72_aligns_all_desktop_action_cells_to_the_shared_track():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = "/* Ingredient editor v72: align every desktop action cell to the shared column edge. */"
    assert marker in css
    assert css.index(marker) > css.index("/* Ingredient editor v71:")
    actions = css[css.index(marker):]
    selector = '[data-ingredient-column="actions"].recipe-edit-compact-row-actions {'
    assert selector in actions
    rule = actions[actions.index(selector):]
    rule = rule[:rule.index("}")]
    for declaration in (
        "display: flex !important;",
        "width: 100% !important;",
        "min-width: 0 !important;",
        "max-width: 100%;",
        "align-self: stretch;",
        "justify-self: stretch;",
        "align-items: center;",
        "justify-content: flex-end;",
        "gap: 4px;",
    ):
        assert declaration in rule


def test_recipe_editor_v73_keeps_choice_group_controls_on_one_centered_row():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = "/* Ingredient editor v73: keep choice-group controls on one centered table row. */"
    assert marker in css
    assert css.index(marker) > css.index("/* Ingredient editor v72:")
    group_row = css[css.index(marker):]
    header_selector = ".recipe-edit-selected-choice-group-header {"
    assert header_selector in group_row
    header_rule = group_row[group_row.index(header_selector):]
    header_rule = header_rule[:header_rule.index("}")]
    assert "grid-template-rows: minmax(48px, 1fr) !important;" in header_rule
    assert "min-height: 64px;" in header_rule
    assert "align-content: center;" in header_rule

    cells_selector = ".recipe-edit-selected-choice-group-header\n        > [data-ingredient-column] {"
    assert cells_selector in group_row
    cells_rule = group_row[group_row.index(cells_selector):]
    cells_rule = cells_rule[:cells_rule.index("}")]
    assert "grid-row: 1 !important;" in cells_rule
    assert "align-self: center !important;" in cells_rule


def test_recipe_editor_v74_centers_both_desktop_action_controls_in_each_row():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = "/* Ingredient editor v74: center both action controls within every desktop row. */"
    assert marker in css
    assert css.index(marker) > css.index("/* Ingredient editor v73:")
    actions = css[css.index(marker):]
    action_selector = '[data-ingredient-column="actions"].recipe-edit-compact-row-actions {'
    assert action_selector in actions
    action_rule = actions[actions.index(action_selector):]
    action_rule = action_rule[:action_rule.index("}")]
    assert "display: grid !important;" in action_rule
    assert "grid-template-columns: repeat(2, 34px);" in action_rule
    assert "grid-auto-flow: column;" in action_rule
    assert "align-items: center;" in action_rule
    assert "justify-content: end;" in action_rule

    menu_rule = actions[actions.index("> .recipe-edit-row-menu-wrap {"):]
    menu_rule = menu_rule[:menu_rule.index("}")]
    assert "height: 38px;" in menu_rule
    assert "align-self: center;" in menu_rule
    assert "align-items: center;" in menu_rule

    dots_rule = actions[actions.index("> .recipe-edit-row-menu-btn::before {"):]
    dots_rule = dots_rule[:dots_rule.index("}")]
    assert "top: 50%;" in dots_rule
    assert "transform: translate(-50%, -50%);" in dots_rule


def test_recipe_editor_v75_keeps_alternatives_in_their_column_and_two_actions_responsive():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    columns = script[
        script.index("const RECIPE_EDIT_INGREDIENT_COLUMNS"):
        script.index("const RECIPE_EDIT_INGREDIENT_VIEW_COLUMN_KEYS")
    ]
    alternatives_column = columns[
        columns.index("    alternatives: {"):
        columns.index("    actions: {")
    ]
    actions_column = columns[columns.index("    actions: {"):]
    assert "minWidth: 84" in alternatives_column
    assert 'label: "Actions"' in columns
    assert "minWidth: 80" in actions_column
    assert "maxWidth: 80" in actions_column
    assert "fallbackWidth: 80" in actions_column
    assert "optionsCell.appendChild(optionsButton);" in script
    assert "optionsCell.appendChild(optionsDisplay);" not in script
    assert "organizeRecipeIngredientRowActions(row);" in script

    organizer = script[
        script.index("function createRecipeIngredientRowActionPlaceholder"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    assert 'placeholder.setAttribute("aria-hidden", "true");' in organizer
    assert 'actions.classList.add("recipe-edit-ingredient-row-actions");' in organizer
    assert 'actions.querySelector(":scope > .recipe-edit-compact-row-collapse")?.remove();' in organizer
    assert "actions.replaceChildren(editControl, menuControl);" in organizer
    assert "alternativesControl" not in organizer
    assert 'event => event.stopPropagation()' in organizer
    assert 'menuButton.setAttribute("aria-label", "More actions");' in organizer

    marker = "/* Ingredient editor v75: keep alternatives in their column and actions compact. */"
    assert marker in css
    action_css = css[css.index(marker):]
    for declaration in (
        "--recipe-edit-ingredient-actions-column-width: 80px;",
        "grid-template-columns: repeat(2, 32px);",
        "> :nth-child(1) {",
        "grid-column: 8 !important;",
        "gap: 8px;",
        "padding: 0 8px 0 0 !important;",
        "visibility: hidden;",
        "outline: 2px solid var(--app-primary-hover) !important;",
        "minmax(84px, 1fr)",
        "--recipe-edit-ingredient-actions-column-width: 96px;",
        "grid-template-columns: repeat(2, 40px);",
    ):
        assert declaration in action_css
    assert ".recipe-edit-ingredient-alternatives-action" not in action_css
    assert "grid-template-columns: repeat(3" not in action_css


def test_selected_option_switch_hands_focus_to_a_visible_parent_control():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selection = script[
        script.index("function setRecipeIngredientOptionSelected"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]

    assert "const selectionTriggerHadFocus = Boolean(" in selection
    assert "button === document.activeElement" in selection
    assert "option.contains(document.activeElement)" in selection
    assert "applyRecipeIngredientOptionSelection(ingredientRow, optionId);" in selection
    assert "if (!modalIsActive && selectionTriggerHadFocus)" in selection
    assert 'ingredientRow.querySelector(\n            ":scope > [data-ingredient-selected-option-block]"' in selection
    assert "const selectedMenuButton = selectedBlock?.querySelector(" in selection
    assert 'ingredientRow.querySelector(\n            "[data-ingredient-substitutions-toggle]"' in selection
    assert "const groupedDisclosure = ingredientRow" in selection
    assert ".recipeIngredientGroupedChoiceAnchorSummary" in selection
    assert '?.querySelector("[data-ingredient-selected-option-toggle]");' in selection
    assert "const focusTarget = groupedDisclosure || selectedMenuButton || disclosure;" in selection
    assert "focusTarget?.isConnected" in selection
    assert '!focusTarget.closest("[hidden], [inert]")' in selection
    assert "focusTarget.focus({ preventScroll: true });" in selection


def test_portaled_selected_option_actions_resolve_source_and_restore_focus():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for selected-option portal coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    portal_lookup = script[
        script.index("function recipeIngredientSelectedOptionBlockFromControl"):
        script.index("function editRecipeIngredientSelectedOption")
    ]
    edit_selected = script[
        script.index("function editRecipeIngredientSelectedOption"):
        script.index("function duplicateRecipeIngredientSelectedOption")
    ]
    selection = script[
        script.index("function setRecipeIngredientOptionSelected"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]
    harness = portal_lookup + edit_selected + selection + r"""
const focusLog = [];
const visibleSelectedMenuButton = {
    isConnected: true,
    closest() { return null; },
    focus() { focusLog.push("selected-menu"); },
};
const disclosure = {
    isConnected: true,
    closest() { return null; },
    focus() { focusLog.push("parent-disclosure"); },
};
const selectedBlock = {
    dataset: { optionId: "alternative-2" },
    querySelector() { return visibleSelectedMenuButton; },
};
const menuAnchor = {
    closest(selector) {
        return selector === "[data-ingredient-selected-option-block]"
            ? selectedBlock
            : null;
    },
};
const portaledMenu = { recipeEditAnchorButton: menuAnchor };
const portaledAction = {
    closest(selector) {
        if (selector === ".recipe-edit-row-menu") return portaledMenu;
        return null;
    },
};
const selectedOptionRow = { id: "selected-option-row" };
const selectedSourceCard = {
    dataset: { alternativeId: "alternative-2" },
    querySelector() { return selectedOptionRow; },
};
const otherSourceCard = { dataset: { alternativeId: "alternative-1" } };
const substitutionContainer = {
    querySelectorAll() { return [otherSourceCard, selectedSourceCard]; },
};
const ingredientRow = {
    classList: { contains() { return false; } },
    querySelector(selector) {
        if (selector === ":scope > [data-recipe-ingredient-edit-panel]") return null;
        if (selector === ":scope > [data-ingredient-selected-option-block]") return selectedBlock;
        if (selector === "[data-ingredient-substitutions-toggle]") return disclosure;
        return null;
    },
};
const selectionCard = {
    dataset: { alternativeId: "alternative-2" },
    contains() { return false; },
    querySelector() { return { id: "selected-option-row" }; },
};
const document = { activeElement: portaledAction };
let appliedOptionId = null;
let alternativeModalArgs = null;
let defaultModalControl = null;
function recipeIngredientParentRowFromControl() { return ingredientRow; }
function recipeIngredientSubstitutionContainer() { return substitutionContainer; }
function recipeIngredientAlternativeCardFromControl() { return selectionCard; }
function recipeEditMenuAnchorButtonFromButton(button) {
    return button.closest(".recipe-edit-row-menu")?.recipeEditAnchorButton || null;
}
function recipeIngredientModalHasChanges() { return false; }
function applyRecipeIngredientOptionSelection(row, optionId) { appliedOptionId = optionId; }
function closeRecipeEditRowMenus() {}
function openRecipeIngredientOptionModal(control, options) {
    alternativeModalArgs = {
        controlIsAnchor: control === menuAnchor,
        triggerIsAnchor: options.trigger === menuAnchor,
        optionRowMatches: options.optionRow === selectedOptionRow,
    };
    return "alternative-modal";
}
function openRecipeIngredientDefaultOptionModal(control) {
    defaultModalControl = control;
    return "default-modal";
}
function openRecipeIngredientDefaultOptionModalWithOptions() {}
function setRecipeEditStatus() {}

const resolvedBlock = recipeIngredientSelectedOptionBlockFromControl(portaledAction);
const resolvedSource = recipeIngredientSelectedOptionSourceCard(portaledAction);
const alternativeEditResult = editRecipeIngredientSelectedOption(portaledAction);
selectedBlock.dataset.optionId = "original-default";
const defaultEditResult = editRecipeIngredientSelectedOption(portaledAction);
selectedBlock.dataset.optionId = "alternative-2";
const selectionResult = setRecipeIngredientOptionSelected(portaledAction);
process.stdout.write(JSON.stringify({
    resolvedBlock: resolvedBlock === selectedBlock,
    resolvedSource: resolvedSource === selectedSourceCard,
    alternativeEditResult,
    alternativeModalArgs,
    defaultEditResult,
    defaultControlIsAnchor: defaultModalControl === menuAnchor,
    appliedOptionId,
    focusLog,
    selectionResult,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "resolvedBlock": True,
        "resolvedSource": True,
        "alternativeEditResult": "alternative-modal",
        "alternativeModalArgs": {
            "controlIsAnchor": True,
            "triggerIsAnchor": True,
            "optionRowMatches": True,
        },
        "defaultEditResult": "default-modal",
        "defaultControlIsAnchor": True,
        "appliedOptionId": "alternative-2",
        "focusLog": ["selected-menu"],
        "selectionResult": False,
    }
    assert 'control?.closest?.(".recipe-edit-row-menu")' in portal_lookup
    assert "const anchor = menu?.recipeEditAnchorButton;" in portal_lookup
    assert 'anchor?.closest?.("[data-ingredient-selected-option-block]") || null' in portal_lookup
    assert "const trigger = recipeEditMenuAnchorButtonFromButton(button) || button;" in edit_selected
    assert "return openRecipeIngredientOptionModal(trigger, {" in edit_selected
    assert "optionRow,\n            trigger," in edit_selected
    assert "return openRecipeIngredientDefaultOptionModal(trigger);" in edit_selected
    assert "button === document.activeElement" in selection


def test_selected_option_modal_close_reresolves_action_after_block_refresh():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for selected-option return-focus coverage")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    edit_mode = script[
        script.index("function setRecipeIngredientEditMode"):
        script.index("function saveRecipeIngredientInlineEdit")
    ]
    harness = edit_mode + r"""
const focusLog = [];
const animationFrames = [];
let staleActionConnected = true;
const staleSelectedBlock = { id: "stale-selected-block" };
let row = null;
const staleAction = {
    get isConnected() { return staleActionConnected; },
    closest(selector) {
        if (selector === ".recipe-edit-ingredient-row") return row;
        if (selector === "[data-ingredient-selected-option-block]") return staleSelectedBlock;
        return null;
    },
    focus() { focusLog.push("stale-action"); },
};
const freshAction = {
    isConnected: true,
    closest() { return null; },
    focus() { focusLog.push("fresh-action"); },
};
const parentDisclosure = {
    isConnected: true,
    closest() { return null; },
    focus() { focusLog.push("parent-disclosure"); },
};
const freshSelectedBlock = {
    querySelector(selector) {
        return selector.includes(".recipe-edit-row-menu-btn") ? freshAction : null;
    },
};
const panel = {
    dataset: { editSnapshot: "snapshot" },
    hidden: false,
    open: false,
    removeAttribute() {},
};
row = {
    classList: { toggle() {} },
    querySelector(selector) {
        if (selector === "[data-recipe-ingredient-edit-panel]") return panel;
        if (selector === ":scope > [data-ingredient-selected-option-block]") {
            return freshSelectedBlock;
        }
        if (selector === "[data-ingredient-substitutions-toggle]") return parentDisclosure;
        return null;
    },
    closest() { return { id: "recipe-form" }; },
};
const document = {
    body: { classList: { remove() {} } },
    querySelectorAll() { return []; },
};
const window = {
    requestAnimationFrame(callback) { animationFrames.push(callback); },
};
let recipeEditIngredientModalActiveRow = row;
let recipeEditIngredientModalReturnView = "";
let recipeEditIngredientView = "table";
let recipeEditIngredientModalReturnFocus = staleAction;
function finishRecipeIngredientModalSelectedOptionEdits() {}
function closeRecipeEditRowMenus() {}
function hideRecipeIngredientDiscardConfirmation() {}
function restoreRecipeIngredientModalOptions() {}
function restoreRecipeIngredientModalImage() {}
function setRecipeEditRowImageToolsVisible() {}
function updateRecipeIngredientSummary() {}
function updateRecipeEditorDirtyState() {}
function restoreRecipeIngredientModalScrollState() {}
function setRecipeEditIngredientView() {}

const closeResult = setRecipeIngredientEditMode(row, false, {
    restoreScroll: false,
});
const focusBeforeRefresh = [...focusLog];
staleActionConnected = false;
animationFrames.shift()?.();
process.stdout.write(JSON.stringify({
    closeResult,
    focusBeforeRefresh,
    focusAfterRefresh: focusLog,
    queuedFrameCount: animationFrames.length,
    returnFocusCleared: recipeEditIngredientModalReturnFocus === null,
    activeRowCleared: recipeEditIngredientModalActiveRow === null,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "closeResult": False,
        "focusBeforeRefresh": ["stale-action"],
        "focusAfterRefresh": ["stale-action", "fresh-action"],
        "queuedFrameCount": 0,
        "returnFocusCleared": True,
        "activeRowCleared": True,
    }
    assert 'returnFocus?.closest?.("[data-ingredient-selected-option-block]")' in edit_mode
    assert "const restoreModalFocus = () => {" in edit_mode
    assert "!focusTarget.isConnected" in edit_mode
    assert 'focusTarget.closest("[hidden], [inert]")' in edit_mode
    assert '":scope > [data-ingredient-selected-option-block]"' in edit_mode
    assert "> .recipe-edit-row-menu-btn" in edit_mode
    assert '"[data-ingredient-substitutions-toggle]"' in edit_mode
    assert "restoreModalFocus();" in edit_mode
    assert "window.requestAnimationFrame?.(restoreModalFocus);" in edit_mode


def test_recipe_editor_ingredient_modal_requires_pencil_and_preserves_dirty_close_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organize = script[
        script.index("function organizeRecipeEditIngredientRow"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    actions = script[
        script.index("function organizeRecipeEditCompactRowActions"):
        script.index("function updateRecipeEditIngredientDetailsState")
    ]
    focus_row = script[
        script.index("function focusRecipeEditCompactRow"):
        script.index("function setRecipeIngredientEditMode")
    ]
    assert "bindRecipeIngredientModalRowOpen" not in script
    assert "bindRecipeIngredientModalRowOpen(row);" not in organize
    assert 'row.removeAttribute("tabindex");' in actions
    assert 'row.removeAttribute("aria-label");' in actions
    assert 'return setRecipeIngredientEditMode(row, true, { trigger: button });' in focus_row

    row_cursor_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients > "
        ".recipe-edit-read-first-row:not(.is-editing) :is("
    )
    row_cursor = css[css.index(row_cursor_selector):]
    row_cursor = row_cursor[:row_cursor.index("}")]
    assert "cursor: default;" in row_cursor
    assert "cursor: pointer;" not in row_cursor

    close_contract = script[
        script.index("function recipeIngredientModalHasChanges"):
        script.index("async function commitRecipeIngredientModal")
    ]
    assert "recipeIngredientModalEditableFieldSnapshot(row)" in close_contract
    assert "showRecipeIngredientDiscardConfirmation" in close_contract
    assert 'panel.dataset.saving === "true"' in close_contract
    assert "requestRecipeIngredientModalClose" in close_contract
    assert "previousRecipeIngredientModal" in close_contract
    assert "nextRecipeIngredientModal" in close_contract
    assert 'event.key === "Escape"' in close_contract
    assert 'event.key !== "Tab"' in close_contract
    assert "focusTarget.focus({ preventScroll: true })" in close_contract


def test_recipe_editor_ingredient_rows_restore_visible_pencil_action():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    actions_start = script.index("function organizeRecipeEditCompactRowActions")
    actions_end = script.index("function updateRecipeEditIngredientDetailsState", actions_start)
    actions = script[actions_start:actions_end]
    pencil_css = css[css.index("/* Ingredient editor v21:"):]

    assert 'const editButtonHtml = `' in actions
    assert 'const editButtonHtml = isIngredientRow ? "" :' not in actions
    assert 'class="recipe-edit-compact-row-edit"' in actions
    assert 'onclick="return focusRecipeEditCompactRow(this)"' in actions
    assert '${recipeEditSvgIcon("edit")}' in actions
    assert 'return setRecipeIngredientEditMode(row, true, { trigger: button });' in script
    assert "width: 76px;" in pencil_css
    assert "min-width: 76px;" in pencil_css
    assert "gap: 4px;" in pencil_css
    assert "76px;" in pencil_css

    organize = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions", script.index("function organizeRecipeEditIngredientRow(row)"))
    ]
    assert "Discard unsaved ingredient changes?" in organize
    assert 'role="alertdialog"' in organize
    assert 'editPanel.addEventListener("cancel", event =>' in organize
    assert "requestRecipeIngredientModalClose(editPanel);" in organize
    assert 'editPanel.addEventListener("click"' not in organize

    scroll = script[
        script.index("const RECIPE_INGREDIENT_MODAL_SCROLL_LOCK_CLASS"):
        script.index("function recipeIngredientModalImagePanel")
    ]
    assert '"[data-app-content]"' in scroll
    assert '".app-sidebar"' in scroll
    assert '".recipe-edit-ingredient-table-scroll"' in scroll
    assert "element.classList.add(RECIPE_INGREDIENT_MODAL_SCROLL_LOCK_CLASS);" in scroll
    assert "wasLocked" in scroll
    assert "element.classList.remove(RECIPE_INGREDIENT_MODAL_SCROLL_LOCK_CLASS);" in scroll
    assert "scrollLeft: element.scrollLeft" in scroll
    assert "scrollTop: element.scrollTop" in scroll
    assert "windowX: window.scrollX" in scroll
    assert "windowY: window.scrollY" in scroll
    assert "window.scrollTo" in scroll
    assert "window.requestAnimationFrame?.(restore);" in scroll

    modal_css = css[css.index("/* Ingredient editor v12:"):]
    scroll_lock_rule = modal_css[
        modal_css.index("body.recipe-ingredient-modal-open :is("):
        modal_css.index("body.recipe-edit-standalone-page #recipeEditIngredients", modal_css.index("body.recipe-ingredient-modal-open :is("))
    ]
    assert "[data-app-content]" in scroll_lock_rule
    assert ".app-sidebar" in scroll_lock_rule
    assert ".recipe-edit-ingredient-table-scroll" in scroll_lock_rule
    assert ").recipe-ingredient-modal-scroll-locked" in scroll_lock_rule
    assert "overflow: hidden !important;" in scroll_lock_rule
    assert "overscroll-behavior: none !important;" in scroll_lock_rule


def test_recipe_editor_ingredient_pencils_share_lightweight_collision_aware_tooltip():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    tooltip_script = script[
        script.index("const RECIPE_INGREDIENT_EDIT_TOOLTIP_ID"):
        script.index("function updateRecipeIngredientOptionRowSummary")
    ]
    assert 'button.dataset.recipeEditIngredientAction = "";' in tooltip_script
    assert 'button.setAttribute("aria-label", "Edit ingredient");' in tooltip_script
    assert 'button.removeAttribute("title");' in tooltip_script
    assert 'tooltip.setAttribute("role", "tooltip");' in tooltip_script
    assert 'tooltip.textContent = "Edit ingredient";' in tooltip_script
    assert 'document.body.appendChild(tooltip);' in tooltip_script
    assert "buttonRect.right + gap + tooltipRect.width" in tooltip_script
    assert 'tooltip.dataset.placement = fitsRight ? "right" : "left";' in tooltip_script
    assert 'document.addEventListener("pointerover"' in tooltip_script
    assert 'document.addEventListener("focusin"' in tooltip_script
    assert 'document.addEventListener("focusout"' in tooltip_script
    assert 'document.addEventListener("scroll"' in tooltip_script
    assert 'window.addEventListener("resize"' in tooltip_script

    tooltip_css = css[css.index("/* Ingredient editor v69:"):]
    assert "button.recipe-edit-compact-row-edit[data-recipe-edit-ingredient-action]" in tooltip_css
    assert "background: transparent !important;" in tooltip_css
    assert "box-shadow: none !important;" in tooltip_css
    assert "color: var(--app-primary-hover);" in tooltip_css
    assert "cursor: pointer;" in tooltip_css
    assert ".recipe-edit-ingredient-action-tooltip" in tooltip_css
    assert "position: fixed;" in tooltip_css
    assert "z-index: 10000;" in tooltip_css

    assert script.count("createRecipeIngredientEditActionButton()") >= 3
    assert "configureRecipeIngredientEditAction(editButton);" in script


def test_recipe_editor_mobile_ingredient_cards_keep_identity_and_details_readable():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert css.index("/* Ingredient editor v23:") > css.index("/* Ingredient editor v22:")
    mobile = css[css.index("/* Ingredient editor v23:"):]

    assert "@media (max-width: 767px)" in mobile
    assert ".recipe-edit-standalone-shell {\n        width: 100%;" in mobile
    assert "padding-bottom: calc(112px + env(safe-area-inset-bottom));" in mobile
    assert "overflow-x: clip;" in mobile
    assert "#recipeEditForm," in mobile
    assert ".recipe-edit-layout," in mobile
    assert ".recipe-edit-main-workspace," in mobile
    assert ".recipe-edit-tabs-card," in mobile
    assert ".recipe-edit-ingredient-table-scroll," in mobile
    assert "grid-template-columns: 46px minmax(0, 1fr) minmax(100px, .65fr) 72px !important;" in mobile
    assert "grid-template-rows: minmax(48px, auto) repeat(5, auto) !important;" in mobile
    assert ".recipe-edit-row-handle {\n        display: none !important;" in mobile
    assert "padding-right: 0;" in mobile
    assert ".recipe-edit-ingredient-read-cell {\n        grid-column: 2 / 4 !important;" in mobile
    assert ".recipe-edit-ingredient-status-summary {\n        grid-column: 1 / 5 !important;" in mobile
    assert ".recipe-edit-ingredient-store-summary {\n        grid-column: 1 / 3 !important;" in mobile
    assert ".recipe-edit-ingredient-type-summary {\n        grid-column: 3 / 5 !important;" in mobile
    assert ".recipe-edit-ingredient-unit-summary {\n        grid-column: 2 / 3 !important;\n        grid-row: 3 !important;" in mobile
    assert ".recipe-edit-ingredient-size-summary {\n        grid-column: 3 / 5 !important;\n        grid-row: 3 !important;" in mobile
    assert ".recipe-edit-ingredient-substitution-cell {\n        grid-column: 1 / 5 !important;\n        grid-row: 5 !important;" in mobile
    assert ".recipe-edit-ingredient-options-panel {\n        grid-column: 1 / -1 !important;\n        grid-row: 6 !important;" in mobile
    assert ".recipe-edit-ingredient-substitution-cell {\n        display: block;" in mobile
    assert "grid-template-columns: 72px minmax(0, 1fr);" in mobile
    assert '.recipe-edit-ingredient-quantity-summary::before {\n        content: "Quantity";' in mobile
    assert '.recipe-edit-ingredient-unit-summary::before {\n        content: "Unit";' in mobile
    assert '.recipe-edit-ingredient-size-summary::before {\n        content: "Size";' in mobile
    assert '.recipe-edit-ingredient-substitution-cell::before {\n        content: "Alternatives";' in mobile
    assert '.recipe-edit-ingredient-store-summary::before {\n        content: "Store";' in mobile
    assert ".recipe-edit-ingredient-type-summary::before {" in mobile
    assert "width: auto;" in mobile
    assert "height: auto;" in mobile
    assert "background: transparent;" in mobile
    assert 'content: "Type";' in mobile
    assert ".recipe-edit-ingredient-inline-preparation {" in mobile
    assert "color: var(--app-muted);" in mobile
    assert "font-weight: 450;" in mobile
    assert "text-overflow: ellipsis;" in mobile
    assert "white-space: nowrap;" in mobile
    assert ".recipe-edit-ingredient-options-copy > [data-ingredient-options-summary]" in mobile
    assert "display: none !important;" in mobile
    narrow = mobile[mobile.index("@media (max-width: 420px)"):]
    assert "grid-template-columns: minmax(0, 1fr) 38px minmax(0, 1fr);" in narrow
    assert ".recipe-edit-header-actions .recipe-edit-header-save {" in narrow
    assert "grid-column: 1 / -1;" in narrow
    assert "grid-row: 2;" in narrow
    assert "grid-template-columns: 44px minmax(0, 1fr) 72px !important;" in narrow
    assert "grid-template-rows: minmax(46px, auto) repeat(6, auto) !important;" in narrow
    assert ".recipe-edit-ingredient-read-cell {\n        grid-column: 2 !important;" in narrow
    assert ".recipe-edit-ingredient-status-summary {\n        grid-column: 1 / 4 !important;" in narrow
    assert ".recipe-edit-ingredient-store-summary {\n        grid-column: 1 / 4 !important;\n        grid-row: 4 !important;" in narrow
    assert ".recipe-edit-ingredient-type-summary {\n        grid-column: 1 / 4 !important;\n        grid-row: 5 !important;" in narrow
    assert ".recipe-edit-ingredient-substitution-cell {\n        grid-column: 1 / 4 !important;\n        grid-row: 6 !important;" in narrow
    assert ".recipe-edit-ingredient-options-panel {\n        grid-column: 1 / -1 !important;\n        grid-row: 7 !important;" in narrow
    assert 'onclick="moveRecipeEditRow(this, -1)">Move ingredient up</button>' in script
    assert 'onclick="moveRecipeEditRow(this, 1)">Move ingredient down</button>' in script


def test_mobile_and_desktop_recipe_editor_use_the_same_app_font_family():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    font_declaration = '--app-font-family: "Segoe UI Variable Text", Inter, "Segoe UI", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Arial, sans-serif;'
    font_declaration_start = css.index(font_declaration)
    root_start = css.rfind(":root {", 0, font_declaration_start)
    root_rule = css[root_start:css.index("}", font_declaration_start)]
    assert font_declaration in root_rule

    shell_start = css.index(".app-shell-body {")
    shell_rule = css[shell_start:css.index("}", shell_start)]
    assert "font-family: var(--app-font-family);" in shell_rule

    desktop_start = css.index("/* Desktop mockup fidelity pass:")
    desktop_shell_start = css.index(".app-shell-body {", desktop_start)
    desktop_shell_rule = css[desktop_shell_start:css.index("}", desktop_shell_start)]
    assert "font-family: var(--app-font-family);" in desktop_shell_rule
    assert 'font-family: "Segoe UI Variable Text"' not in desktop_shell_rule


def test_mobile_ingredient_status_value_stacks_beneath_its_label():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    v33_start = css.index("/* Ingredient editor v33:")
    assert v33_start > css.index("/* Ingredient editor v32:")
    v33 = css[v33_start:css.index("/* Keep expanded modal analysis", v33_start)]
    assert "@media (max-width: 767px)" in v33

    status_start = v33.index(
        "#recipeEditIngredients > .recipe-edit-ingredient-row > .recipe-edit-ingredient-status-summary {"
    )
    status_rule = v33[status_start:v33.index("}", status_start)]
    assert "grid-template-columns: minmax(0, 1fr);" in status_rule
    assert "align-items: stretch;" in status_rule
    assert "gap: 2px;" in status_rule

    label_start = v33.index(".recipe-edit-ingredient-status-summary::before {")
    label_rule = v33[label_start:v33.index("}", label_start)]
    assert "grid-column: 1;" in label_rule
    assert "grid-row: 1;" in label_rule

    value_start = v33.index(
        ".recipe-edit-ingredient-status-summary > [data-ingredient-read-status] {"
    )
    value_rule = v33[value_start:v33.index("}", value_start)]
    assert "display: block;" in value_rule
    assert "grid-column: 1;" in value_rule
    assert "grid-row: 2;" in value_rule
    assert "width: 100%;" in value_rule


def test_mobile_ingredient_metadata_stays_compact_with_read_only_status():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    status_factory = script[
        script.index("function createRecipeIngredientStatusSummary"):
        script.index("function appendRecipeIngredientInlineSummaryControl")
    ]
    assert 'status.className = "recipe-edit-ingredient-read-status";' in status_factory
    assert "status.dataset.ingredientReadStatus" in status_factory
    assert 'data-recipe-ingredient-inline-field="match_status"' not in organize
    assert "RECIPE_INGREDIENT_EDITABLE_MATCH_STATUSES" not in script
    for field_name in ("quantity", "unit", "size", "store_section", "section"):
        assert f'"{field_name}"' in organize
    assert "optionsButton.dataset.ingredientSubstitutionsToggle" in organize

    v34_start = css.index("/* Ingredient editor v34:")
    v34 = css[v34_start:css.index("/* Keep expanded modal analysis", v34_start)]
    assert "@media (max-width: 767px)" in v34
    assert ".recipe-edit-ingredient-status-control" not in v34
    assert ".recipe-edit-ingredient-inline-status" not in v34
    assert ".recipe-edit-ingredient-options-button::after" in v34
    assert '.recipe-edit-ingredient-options-button[aria-expanded="true"]::after' in v34


def test_mobile_expanded_ingredient_cards_align_status_and_alternatives_beside_one_divider():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    collapse_start = script.index("function recipeIngredientMobileAccordionIsActive")
    collapse_end = script.index("function expandRecipeIngredientRow", collapse_start)
    collapse = script[collapse_start:collapse_end]
    assert 'window.matchMedia("(max-width: 767px)").matches' in collapse
    assert "function collapseOtherRecipeIngredientRows(activeRow)" in collapse
    assert "if (row !== activeRow)" in collapse
    assert "setRecipeIngredientRowCollapsed(row, true);" in collapse
    assert "collapseOtherRecipeIngredientRows(row);" in collapse
    assert "recipeIngredientMobileAccordionIsActive()\n            ||" in collapse
    assert 'row.classList.add("recipe-edit-row-expanded");' in collapse

    expand_all_start = script.index("function setRecipeIngredientsCollapsed")
    expand_all_end = script.index("function toggleRecipeIngredientsCollapsed", expand_all_start)
    expand_all = script[expand_all_start:expand_all_end]
    assert "const expandRows = !collapsed && recipeIngredientMobileAccordionIsActive();" in expand_all
    assert 'row.classList.toggle("recipe-edit-row-expanded", expandRows);' in expand_all

    v35_start = css.index("/* Ingredient editor v35:")
    assert v35_start > css.index("/* Ingredient editor v34:")
    v35 = css[v35_start:css.index("/* Keep expanded modal analysis", v35_start)]
    assert "@media (max-width: 767px)" in v35
    assert "> .recipe-edit-ingredient-row.recipe-edit-row-expanded::before" in v35
    assert "grid-column: 1 / -1;" in v35
    assert "grid-row: 2;" in v35
    assert "border-top: 1px solid" in v35

    status_start = v35.index("> .recipe-edit-ingredient-status-summary {")
    status_end = v35.index("> .recipe-edit-ingredient-substitution-cell {", status_start)
    status = v35[status_start:status_end]
    assert "grid-column: 1 / 3 !important;" in status
    assert "grid-row: 2 !important;" in status
    assert "align-self: stretch;" in status
    assert "border-top: 0;" in status

    alternatives_start = status_end
    alternatives_end = v35.index("> .recipe-edit-ingredient-substitution-cell::before", alternatives_start)
    alternatives = v35[alternatives_start:alternatives_end]
    assert "grid-column: 3 / 5 !important;" in alternatives
    assert "grid-row: 2 !important;" in alternatives
    assert "align-self: stretch;" in alternatives
    assert "gap: 0;" in alternatives
    assert "border-top: 0;" in alternatives

    value_row_start = v35.index("> [data-ingredient-read-status],")
    value_row_end = v35.index("}", value_row_start)
    value_row = v35[value_row_start:value_row_end]
    assert "display: flex;" in value_row
    assert "align-items: center;" in value_row
    assert "height: 30px;" in value_row
    assert "min-height: 30px;" in value_row

    button_start = v35.index("> .recipe-edit-ingredient-options-button {", value_row_end)
    button_end = v35.index("}", button_start)
    button = v35[button_start:button_end]
    assert "margin-top: 0;" in button
    assert "padding-block: 0;" in button
    assert "line-height: 1.4;" in button

    assert "@media (max-width: 420px)" in v35
    assert "grid-template-columns: repeat(12, minmax(0, 1fr)) !important;" in v35
    assert "grid-column: 1 / 7 !important;" in v35
    assert "grid-column: 7 / 13 !important;" in v35


def test_mobile_optional_type_label_does_not_keep_the_desktop_dot_background():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    mobile_start = css.index("/* Ingredient editor v23: compact, readable mobile ingredient cards. */")
    selector = (
        "body.recipe-edit-standalone-page "
        ".recipe-edit-ingredient-type-summary.is-optional::before {"
    )
    rule_start = css.index(selector, mobile_start)
    rule = css[rule_start:css.index("}", rule_start)]
    assert "background: transparent;" in rule


def test_mobile_ingredient_header_surfaces_saved_alternatives_inline():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'mobileAlternativesBadge.className = "recipe-edit-ingredient-mobile-alternatives-badge";' in organize
    assert "mobileAlternativesBadge.dataset.ingredientMobileAlternativesBadge" in organize
    assert 'mobileAlternativesBadge.setAttribute("aria-controls", substitutions.id);' in organize
    assert 'mobileAlternativesBadge.setAttribute("aria-haspopup", "dialog");' not in organize
    assert "toggleRecipeIngredientSubstitutions(mobileAlternativesBadge, event)" in organize

    state_start = script.index("function updateRecipeIngredientSubstitutionState")
    state_end = script.index("function addRecipeIngredientSubstitutionRow", state_start)
    state = script[state_start:state_end]
    assert "const badgeLabel = requirementChoiceSummary.label;" in state
    assert "mobileAlternativesBadge.hidden = alternativeCount === 0;" in state
    assert "String(recipeIngredientExpansionIsOpen(row, mobileAlternativesBadge))" in state
    assert "alternativesDialogName" not in state

    open_start = script.index("function openRecipeIngredientAlternativesDialog")
    open_end = script.index("function recipeIngredientSubstitutionDomGroups", open_start)
    open_helper = script[open_start:open_end]
    assert "setRecipeIngredientSubstitutionsExpanded(row, button, true, options);" in open_helper
    assert "container.scrollIntoView" not in open_helper
    assert "function closeRecipeIngredientAlternativesDialog" in open_helper
    assert "setRecipeIngredientSubstitutionsExpanded(row, control, false, options);" in open_helper
    assert "showModal" not in open_helper

    v41_start = css.index("/* Ingredient editor v41:")
    v41 = css[v41_start:css.index("/* Ingredient editor v42:", v41_start)]
    assert ".recipe-edit-ingredient-mobile-alternatives-badge" in v41
    assert "display: none;" in v41
    assert "@media (max-width: 767px)" in v41
    assert ".recipe-edit-ingredient-mobile-alternatives-badge:not([hidden])" in v41
    assert "display: inline-flex;" in v41
    assert "border: 0;" in v41
    assert "background: transparent;" in v41
    assert "font-size: 8px;" in v41
    assert "font-weight: 650;" in v41

    v45 = css[css.index("/* Ingredient editor v45:"):]
    assert ".recipe-edit-ingredient-options-panel" in v45
    assert "grid-column: 1 / -1 !important;" in css
    assert ".recipe-edit-ingredient-choice-overview" in v45
    assert "@media (max-width: 767px)" in v45


def test_ingredient_name_and_buy_as_fields_use_the_normalized_master_data_picker():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    bind_start = script.index("function bindRecipeIngredientNameField(row)")
    bind_end = script.index("function addRecipeIngredientRow", bind_start)
    binding = script[bind_start:bind_end]
    assert 'recipeIngredientDirectField(row, "ingredient")' in binding
    assert 'recipeIngredientDirectField(row, "purchasable_item")' in binding
    assert 'data-recipe-ingredient-inline-field="ingredient"' in binding
    assert 'data-recipe-ingredient-inline-field="purchasable_item"' in binding
    assert 'field.dataset.recipeIngredientMasterField = targetField;' in binding
    assert 'field.removeAttribute("list");' in binding
    assert "bindRecipeIngredientMasterPicker(field);" in binding

    picker_start = script.index("function ensureRecipeIngredientMasterMenu")
    picker_end = script.index("function bindRecipeIngredientNameField", picker_start)
    picker = script[picker_start:picker_end]
    assert 'menu.setAttribute("role", "listbox");' in picker
    assert 'input.setAttribute("role", "combobox");' in picker
    assert 'input.setAttribute("aria-autocomplete", "list");' in picker
    assert 'const requestUrl = masterDataViewerUrl(' in picker
    assert '"/api/master-data/ingredients/options"' in picker
    assert "const response = await fetch(requestUrl" in picker
    assert "function chooseRecipeIngredientMasterOption" in picker
    assert "function recipeIngredientMasterSelectedIndex" in picker
    assert "recipeIngredientProjectedOptionSourceRow(input)" in picker
    assert "return input.recipeIngredientMasterTargetRow" in picker
    assert "function syncRecipeIngredientModalSelectedOptionMasterControls" in picker
    assert "function focusRecipeIngredientMasterSelectionInput" in picker
    assert 'targetField === "purchasable_item"' in picker
    assert 'setRowFieldValue(row, "purchasable_item", name, { dispatch: false });' in picker
    assert "syncRecipeIngredientPurchaseGroup(buyAsField);" in picker
    assert "focusRecipeIngredientMasterSelectionInput(input, row, targetField, modalPanel);" in picker
    assert 'recipeIngredientDirectField(targetRow, "ingredient_id")' in picker
    for field_name in (
        "master_normalized_name",
        "normalized_name",
        "ingredient",
        "parsed_name",
        "purchasable_item",
    ):
        assert f'"{field_name}"' in picker
    assert ".map(recipeIngredientComparableText)" in picker
    assert "ingredient.aliases" in picker
    assert "const selected = index === selectedOptionIndex;" in picker
    assert picker.index("positionRecipeEditPopupMenu(menu, input);") < picker.index(
        "setRecipeEditListboxActiveOption(menu, activeIndex >= 0 ? activeIndex : 0);"
    )
    for field_name in (
        "ingredient_id",
        "normalized_name",
        "master_normalized_name",
        "store_section",
        "ingredient_image_url",
        "match_status",
    ):
        assert f"{field_name}:" in picker
    assert 'match_source: "ingredient master data"' in picker
    assert "Manage master ingredients" in picker
    assert "ingredient.aliases" in picker
    assert "Also matches" in picker
    assert 'const RECIPE_EDIT_INGREDIENT_MASTER_VERSION_STORAGE_KEY = "ingredient-master-data-version";' in script
    assert "recipeEditIngredientMasterCache.clear();" in script

    outside_click_start = script.index("function handleRecipeEditRowMenuOutsideClick")
    outside_click_end = script.index("function handleRecipeEditRowMenuScrollOrResize", outside_click_start)
    outside_click = script[outside_click_start:outside_click_end]
    assert "[data-recipe-edit-ingredient-master-trigger]" in outside_click
    assert '[data-recipe-edit-ingredient-master-trigger][aria-expanded=\\"true\\"]' in outside_click

    v43 = css[css.index("/* Ingredient editor v43:"):css.index("/* Keep expanded modal analysis")]
    assert ".recipe-edit-row-menu.recipe-edit-ingredient-master-menu" in v43
    assert ".recipe-edit-ingredient-master-option" in v43
    assert ".recipe-edit-ingredient-master-manage" in v43
    assert "@media (max-width: 520px)" in v43


def test_compact_ingredient_controls_do_not_compress_master_data_options():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert (
        ":is(input, select, button):not(.recipe-edit-ingredient-master-option)"
        in css
    )
    assert "min-height: 52px;" in css


def test_mobile_expanded_editable_values_share_one_typography_treatment():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    v36_start = css.index("/* Ingredient editor v36:")
    v36 = css[v36_start:css.index("/* Ingredient editor v37:", v36_start)]
    assert "@media (max-width: 767px)" in v36
    for class_name in (
        ".recipe-edit-ingredient-quantity-summary",
        ".recipe-edit-ingredient-unit-summary",
        ".recipe-edit-ingredient-size-summary",
        ".recipe-edit-ingredient-store-summary",
        ".recipe-edit-ingredient-type-summary",
        ".recipe-edit-ingredient-preparation-summary",
        ".recipe-edit-ingredient-buy-as-summary",
        ".recipe-edit-ingredient-inline-control",
        ".recipe-edit-store-section-trigger",
        ".recipe-edit-type-trigger",
    ):
        assert class_name in v36
    assert "font-family: inherit;" in v36
    assert "font-size: 16px !important;" in v36
    assert "font-weight: 400;" in v36
    assert "line-height: 1.2;" in v36
    assert ".recipe-edit-ingredient-status-summary" not in v36
    assert ".recipe-edit-ingredient-substitution-cell" not in v36


def test_mobile_expanded_cards_show_editable_preparation_and_buy_as_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert '"recipe-edit-ingredient-preparation-summary"' in organize
    assert '"recipe-edit-ingredient-buy-as-summary"' in organize
    assert '"preparation", "Preparation", "Add preparation"' in organize
    assert '"purchasable_item", "Buy As", "Add buy as"' in organize
    assert 'control.dataset.recipeIngredientInlineField = fieldName;' in organize

    v37_start = css.index("/* Ingredient editor v37:")
    v37 = css[v37_start:css.index("/* Ingredient editor v38:", v37_start)]
    assert "grid-template-rows: minmax(48px, auto) repeat(5, auto) !important;" in v37
    hidden_header_start = v37.index("> .recipe-edit-ingredient-read-details {")
    hidden_header_end = v37.index("}", hidden_header_start)
    hidden_header = v37[hidden_header_start:hidden_header_end]
    assert "display: none !important;" in hidden_header
    assert ".recipe-edit-ingredient-read-buy-as" not in hidden_header
    assert "> .recipe-edit-ingredient-mobile-detail-summary {" in v37
    assert "display: grid;" in v37
    assert "grid-row: 5 !important;" in v37
    assert 'content: "Preparation";' in v37
    assert 'content: "Buy As";' in v37
    assert "height: 30px;" in v37
    assert "grid-row: 6 !important;" in v37


def test_mobile_ingredient_header_uses_one_layout_in_every_fold_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    sync_start = script.index("function syncRecipeIngredientMobileHeader(row)")
    sync_end = script.index("function initializeRecipeIngredientMobileHeaderLayout", sync_start)
    sync = script[sync_start:sync_end]
    assert 'row.querySelector(":scope > .recipe-edit-ingredient-mobile-header")' in sync
    assert 'header.className = "recipe-edit-ingredient-mobile-header";' in sync
    assert 'row.insertBefore(header, row.firstChild);' in sync
    assert '[...header.children].forEach(child => row.insertBefore(child, header));' in sync
    for selector in (
        ".recipe-edit-row-number",
        ".recipe-ingredient-image-panel",
        ".recipe-edit-ingredient-read-cell",
        ".recipe-edit-ingredient-mobile-quantity-summary",
        ".recipe-edit-compact-row-actions",
    ):
        assert f'"{selector}"' in sync

    init_start = script.index("function initializeRecipeIngredientMobileHeaderLayout()")
    init_end = script.index("function collapseOtherRecipeIngredientRows", init_start)
    initialization = script[init_start:init_end]
    assert 'window.matchMedia("(max-width: 767px)")' in initialization
    assert 'addEventListener("change", syncHeaders)' in initialization

    v39_start = css.index("/* Ingredient editor v39:")
    v39 = css[v39_start:css.index("/* Keep expanded modal analysis", v39_start)]
    header_start = v39.index("> .recipe-edit-ingredient-mobile-header {")
    header_end = v39.index("}", header_start)
    header = v39[header_start:header_end]
    assert ".recipe-edit-row-expanded" not in header
    assert "grid-template-columns: 40px minmax(0, 1fr) max-content 106px;" in header
    assert "grid-column: 1 / -1 !important;" in header
    assert "grid-row: 1 !important;" in header
    assert "height: 44px;" in header
    assert "column-gap: 6px;" in header

    for selector, column in (
        ("> .recipe-edit-row-number,", "grid-column: 1 !important;"),
        ("> .recipe-ingredient-image-panel {", "grid-column: 1 !important;"),
        ("> .recipe-edit-ingredient-read-cell {", "grid-column: 2 !important;"),
        ("> .recipe-edit-ingredient-mobile-quantity-summary {", "grid-column: 3 !important;"),
        ("> .recipe-edit-compact-row-actions {", "grid-column: 4 !important;"),
    ):
        start = v39.index(selector)
        end = v39.index("}", start)
        rule = v39[start:end]
        assert ".recipe-edit-row-expanded" not in rule
        assert column in rule
        assert "grid-row: 1 !important;" in rule

    actions_start = v39.index("> .recipe-edit-compact-row-actions {")
    actions_end = v39.index("}", actions_start)
    actions = v39[actions_start:actions_end]
    assert "display: flex !important;" in actions
    assert "align-items: center;" in actions
    assert "justify-content: flex-end;" in actions
    assert "gap: 4px;" in actions

    number_start = v39.index("> .recipe-edit-row-number {")
    number_end = v39.index("}", number_start)
    number = v39[number_start:number_end]
    assert "display: grid;" in number
    assert "place-items: center;" in number
    assert "z-index: 1;" in number
    assert "> .recipe-edit-ingredient-mobile-header:has(" in v39
    assert ".recipe-ingredient-image:not([hidden])" in v39

    image_start = v39.index("> .recipe-ingredient-image-panel {")
    image_end = v39.index("}", image_start)
    image = v39[image_start:image_end]
    assert "width: 40px !important;" in image
    assert "height: 40px !important;" in image
    assert "overflow: hidden;" in image
    assert "border: 1px solid var(--recipe-editor-border);" in image
    assert "border-radius: 8px;" in image
    assert ".recipe-edit-ingredient-status-summary" not in v39
    assert ".recipe-edit-ingredient-type-summary" not in v39


def test_mobile_preparation_and_buy_as_fields_use_full_width_rows():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    v40_start = css.index("/* Ingredient editor v40:")
    v40 = css[v40_start:css.index("/* Keep expanded modal analysis", v40_start)]
    assert "grid-template-columns: repeat(4, minmax(0, 1fr)) !important;" in v40
    assert "grid-template-rows: 44px repeat(6, auto) !important;" in v40
    assert "column-gap: 8px !important;" in v40

    for selector, row in (
        ("> .recipe-edit-ingredient-preparation-summary {", "grid-row: 5 !important;"),
        ("> .recipe-edit-ingredient-buy-as-summary {", "grid-row: 6 !important;"),
    ):
        start = v40.index(selector)
        end = v40.index("}", start)
        rule = v40[start:end]
        assert "grid-column: 1 / 5 !important;" in rule
        assert row in rule

    options_start = v40.index("> .recipe-edit-ingredient-options-panel {")
    options_end = v40.index("}", options_start)
    options = v40[options_start:options_end]
    assert "grid-row: 7 !important;" in options


def test_mobile_detail_inputs_share_quantity_quiet_and_hover_colors():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    quiet_start = css.index(
        "#recipeEditIngredients > .recipe-edit-ingredient-row .recipe-edit-ingredient-read-cell"
    )
    quiet_end = css.index(".recipe-edit-standalone-page .recipe-edit-ingredient-inline-control[aria-invalid", quiet_start)
    quiet_styles = css[quiet_start:quiet_end]
    for class_name in (
        ".recipe-edit-ingredient-quantity-summary",
        ".recipe-edit-ingredient-preparation-summary",
        ".recipe-edit-ingredient-buy-as-summary",
    ):
        assert class_name in quiet_styles
    assert "border-color: transparent;" in quiet_styles
    assert "background: transparent;" in quiet_styles
    assert "border-color: var(--app-border-strong);" in quiet_styles
    assert "background: var(--app-bg-soft);" in quiet_styles


def test_quantity_and_unit_hover_use_active_field_highlight():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    > :is(\n"
        "        .recipe-edit-ingredient-row,\n"
        "        .recipe-edit-ingredient-column-group-projection\n"
        "    )\n"
        "    :is(\n"
        "        .recipe-edit-ingredient-quantity-summary,\n"
        "        .recipe-edit-ingredient-unit-summary\n"
        "    )\n"
        "    > .recipe-edit-ingredient-inline-control:not("
    )
    rule_start = css.index(selector)
    rule = css[rule_start:css.index("\n}", rule_start)]

    assert ":disabled," in rule
    assert '[aria-invalid="true"]' in rule
    assert ':is(:hover, :focus, [aria-expanded="true"])' in rule
    assert ".recipe-edit-ingredient-column-group-projection" in rule
    assert "border-color: var(--app-primary-hover);" in rule
    assert "background: var(--app-surface);" in rule
    assert "box-shadow: 0 0 0 2px" in rule


def test_recipe_editor_ingredient_modal_navigation_and_busy_state_are_wired():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    navigation = script[
        script.index("function updateRecipeIngredientModalNavigation"):
        script.index("function hideRecipeIngredientDiscardConfirmation")
    ]
    assert "const rows = recipeEditIngredientRows();" in navigation
    assert "previousButton.disabled = index <= 0;" in navigation
    assert "forwardButton.disabled = index < 0 || index >= rows.length - 1;" in navigation
    assert 'nextButton.textContent = "Save & Next";' in navigation
    assert 'nextButton.dataset.recipeIngredientFinal = isFinal ? "true" : "false";' in navigation
    assert 'panel.toggleAttribute("aria-busy", Boolean(saving));' in navigation
    for selector in (
        "[data-recipe-ingredient-modal-save]",
        "[data-recipe-ingredient-modal-next]",
        "[data-recipe-ingredient-modal-previous]",
        "[data-recipe-ingredient-modal-forward]",
        "[data-recipe-ingredient-modal-close]",
    ):
        assert selector in navigation
    assert 'setRecipeIngredientModalStatus(panel, "saving")' in navigation

    commit = script[
        script.index("async function commitRecipeIngredientModal"):
        script.index("function updateRecipeIngredientAlternativeComponentSummary")
    ]
    assert 'panel.dataset.saving === "true"' in commit
    assert 'panel.dataset.saving = "true";' in commit
    assert "setRecipeIngredientModalSaving(panel, true);" in commit
    assert "validateRecipeIngredientModal(row, panel)" in commit
    assert "panel.dataset.editSnapshot = JSON.stringify(recipeIngredientModalEditableFieldSnapshot(row));" in commit
    assert "const nextRow = index >= 0 && index < rows.length - 1 ? rows[index + 1] : null;" in commit
    assert "switchRecipeIngredientModal(row, nextRow)" in commit
    assert "setRecipeIngredientEditMode(row, false)" in commit
    assert "Unable to save this ingredient. Please try again." in commit
    assert "delete panel.dataset.saving;" in commit
    assert "setRecipeIngredientModalSaving(panel, false);" in commit


def test_recipe_editor_ingredient_modal_keeps_image_workflow_compact_and_portals_popups_inside_dialog():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    image_contract = script[
        script.index("function recipeIngredientModalImagePanel"):
        script.index("function recipeIngredientModalFieldError")
    ]
    assert 'generateButton.textContent = "Generate Image";' in image_contract
    assert 'recipeIngredientModalHasImage(imagePanel) ? "Change Image" : "Add Image"' in image_contract
    assert 'removeButton.textContent = "Remove";' in image_contract
    assert 'viewButton.dataset.recipeIngredientImageView = "";' in image_contract
    assert 'viewButton.textContent = "View Image";' in image_contract
    assert 'viewButton.title = "View full-size ingredient image";' in image_contract
    assert "viewButton.hidden = !recipeIngredientModalHasImage(imagePanel);" in image_contract
    assert "imageOptions.insertBefore(viewButton, generateButton || imageOptions.firstChild);" in image_contract
    assert 'imagePanel.querySelector(".recipe-ingredient-image:not([hidden])")' in image_contract
    assert "if (image) openRecipeImageLightbox(image);" in image_contract
    assert 'imageOptions.querySelector("[data-recipe-ingredient-image-view]")?.remove();' in image_contract
    assert 'image.tabIndex = -1;' in image_contract
    assert 'image.title = "Open ingredient image options";' in image_contract
    assert 'image.setAttribute("aria-label", "Enlarge ingredient image");' in image_contract
    assert 'image.title = "Click to enlarge ingredient image";' in image_contract
    assert 'function recipeIngredientModalUsesImageOptionsPopup' in image_contract
    assert 'window.matchMedia("(max-width: 760px)").matches' in image_contract
    assert 'if (usesImageOptionsPopup)' in image_contract
    assert 'const imageOptionsOpen = imagePanel.classList.contains("recipe-ingredient-image-options-open");' in image_contract
    assert 'imageOptions.setAttribute("aria-hidden", imageOptionsOpen ? "false" : "true");' in image_contract
    assert 'imageOptionsTrigger.setAttribute("aria-expanded", imageOptionsOpen ? "true" : "false");' in image_contract
    assert 'function toggleRecipeIngredientModalImageOptions' in image_contract
    assert 'function closeRecipeIngredientModalImageOptionsOnEscape' in image_contract
    assert 'imagePanel.classList.toggle("recipe-ingredient-image-options-open", shouldOpen);' in image_contract
    assert 'imageOptions.setAttribute("role", "dialog");' in image_contract
    assert 'heading.textContent = "Image options";' in image_contract
    assert 'slot.appendChild(imagePanel);' in image_contract
    assert "recipeIngredientModalPlaceholder" in image_contract
    assert '"recipe-ingredient-image-prompt-requested"' in image_contract

    organizer = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions", script.index("function organizeRecipeEditIngredientRow(row)"))
    ]
    assert 'imagePanel.classList.add("recipe-ingredient-image-prompt-requested");' in organizer
    assert 'data-ingredient-image-generate' in organizer
    assert 'data-recipe-ingredient-modal-preview-media' in organizer
    assert 'aria-haspopup="dialog"' in organizer
    assert 'aria-label="Open ingredient image options"' in organizer
    click_handler = script[
        script.index("function handleRecipeCoverImageClick"):
        script.index("function handleRecipeCoverImageKeydown")
    ]
    assert 'event.target.closest("[data-recipe-ingredient-modal-preview-media]")' in click_handler
    assert 'event.target.closest("[data-recipe-ingredient-image-options]")' in click_handler
    assert 'event.target.closest("[data-recipe-ingredient-image-options-trigger]")' in click_handler
    assert "focusFirst: event.detail === 0" in click_handler
    assert "toggleRecipeIngredientModalImageOptions(previewMedia," in click_handler
    assert "closeRecipeIngredientModalImageOptions();" in click_handler
    assert 'document.addEventListener("keydown", closeRecipeIngredientModalImageOptionsOnEscape, true);' in script

    portal = script[
        script.index("function portalRecipeEditPopupMenu"):
        script.index("function restoreRecipeEditPopupMenu")
    ]
    assert 'button.closest("[data-recipe-ingredient-edit-panel][open]")' in portal
    assert "const portalHost = ingredientDialog || document.body;" in portal
    assert "portalHost.appendChild(menu);" in portal

    modal_css = css[css.index("/* Ingredient editor v12:"):]
    assert "width: 112px !important;" in modal_css
    assert "height: 112px !important;" in modal_css
    assert ".recipe-step-image-download" in modal_css
    assert "display: none !important;" in modal_css
    assert ".recipe-image-prompt" in modal_css
    assert ".recipe-ingredient-image-prompt-requested .recipe-image-prompt:not([hidden])" in modal_css
    assert ".recipe-edit-ingredient-image-options-title" in modal_css
    assert ".recipe-edit-ingredient-image-options-trigger" in modal_css
    assert ".recipe-ingredient-image-options-open > .recipe-step-image-actions" in modal_css
    assert "visibility: hidden;" in modal_css
    assert "visibility: visible;" in modal_css
    desktop_image_actions = modal_css[modal_css.index("@media (min-width: 761px)"):]
    desktop_image_actions = desktop_image_actions[:desktop_image_actions.index("@media (max-width: 1240px)")]
    assert ".recipe-edit-ingredient-image-options-trigger" in desktop_image_actions
    assert "display: none;" in desktop_image_actions
    assert "pointer-events: auto;" in desktop_image_actions
    assert "cursor: zoom-in;" in desktop_image_actions
    assert "bottom: 6px;" in desktop_image_actions
    assert "display: flex !important;" in desktop_image_actions
    assert "visibility: visible;" in desktop_image_actions
    assert ".recipe-edit-ingredient-modal-preview-media:hover .recipe-step-image-actions" in desktop_image_actions
    assert "min-height: 28px !important;" in desktop_image_actions
    assert "dialog.recipe-edit-ingredient-edit-panel > .recipe-edit-floating-menu" in modal_css
    assert "z-index: 40 !important;" in modal_css


def test_selected_ingredient_option_modal_uses_the_clicked_component_identity():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    option_markup = script[
        script.index("function recipeIngredientSubstitutionOptionRowHtml"):
        script.index("function recipeIngredientSubstitutionOptionsHtml")
    ]
    image_contract = script[
        script.index("function mountRecipeIngredientModalImage"):
        script.index("function restoreRecipeIngredientModalImage")
    ]
    option_modal = script[
        script.index("function openRecipeIngredientOptionModal"):
        script.index("function switchRecipeIngredientOptionModal")
    ]
    match_details = script[
        script.index("function recipeIngredientMatchDetails(item = {})"):
        script.index("function recipeIngredientMatchDetailsHtml")
    ]

    assert "JSON.stringify(recipeIngredientMatchSnapshot(option))" in option_markup
    assert 'data-ingredient-match-details="${escapeAttribute(matchDetails)}"' in option_markup
    assert "const optionRow = panel.recipeIngredientOptionSourceRow;" in image_contract
    assert "fieldValuesFromRow(optionRow)" in image_contract
    assert 'optionImagePanel.dataset.recipeIngredientModalOptionImage = "";' in image_contract
    assert "slot.replaceChildren(optionImagePanel);" in image_contract
    assert "imageOptionsTrigger.hidden = true;" in image_contract
    assert "imageOptionsTrigger.dataset.recipeIngredientOptionPreview" in image_contract
    assert "recipeIngredientMatchItemFromRow(optionRow, fieldValuesFromRow(optionRow))" in option_modal
    assert "row.dataset.ingredientMatchDetails = JSON.stringify(recipeIngredientMatchSnapshot(optionMatch));" in option_modal
    assert "item.master_normalized_name" in match_details
    assert "item.normalized_name" in match_details
    assert (
        ".recipe-edit-ingredient-image-options-trigger[data-recipe-ingredient-option-preview]"
        in css
    )


def test_recipe_editor_ingredient_image_lightbox_stays_above_the_modal_and_restores_focus():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    lightbox = script[
        script.index("function ensureRecipeImageLightbox"):
        script.index("function buildAddressSummaryFromForm")
    ]
    assert 'const dialogHost = image.closest("dialog[open]");' in lightbox
    assert "const lightboxHost = dialogHost || document.body;" in lightbox
    assert "lightboxHost.appendChild(lightbox);" in lightbox
    assert "lightbox.recipeImageLightboxTrigger = image;" in lightbox
    assert "lightbox.parentNode !== document.body" in lightbox
    assert "document.body.appendChild(lightbox);" in lightbox
    assert "trigger.focus({ preventScroll: true });" in lightbox
    assert "event.stopImmediatePropagation();" in lightbox
    assert 'data-recipe-image-lightbox-action="generate"' in lightbox
    assert 'data-recipe-image-lightbox-action="remove"' in lightbox
    assert 'data-recipe-image-lightbox-action="change"' in lightbox
    assert "function recipeImageLightboxIngredientActionTargets" in lightbox
    assert 'image.closest("[data-ingredient-image-panel]")' in lightbox
    assert "function syncRecipeImageLightboxActions" in lightbox
    assert "syncRecipeImageLightboxActions(lightbox, image);" in lightbox
    assert "function runRecipeImageLightboxAction" in lightbox
    assert "closeRecipeImageLightbox({ restoreFocus: false });" in lightbox
    assert "target.click();" in lightbox

    assert ".recipe-image-lightbox-actions {" in css
    assert ".recipe-image-lightbox-media:hover .recipe-image-lightbox-actions" in css
    assert ".recipe-image-lightbox-content:focus-within .recipe-image-lightbox-actions" in css
    assert "@media (hover: none), (max-width: 760px)" in css
    assert ".recipe-image-lightbox-actions button.is-remove" in css
    lightbox_image = css[css.index(".recipe-image-lightbox img {"):]
    lightbox_image = lightbox_image[:lightbox_image.index("}")]
    assert "max-width: calc(100vw - 32px);" in lightbox_image
    assert "max-height: calc(100dvh - 32px);" in lightbox_image

    modal_lightbox = css[css.index(
        "dialog.recipe-edit-ingredient-edit-panel > .recipe-image-lightbox"
    ):]
    modal_lightbox = modal_lightbox[:modal_lightbox.index("}")]
    assert "position: fixed;" in modal_lightbox
    assert "inset: 0;" in modal_lightbox
    assert "z-index: 20000;" in modal_lightbox


def test_recipe_editor_ingredient_modal_v13_is_compact_readable_and_responsive():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    compact = css[css.index("/* Ingredient editor v13:"):]

    dialog_rule = compact[compact.index("dialog.recipe-edit-ingredient-edit-panel {"):]
    dialog_rule = dialog_rule[:dialog_rule.index("}")]
    for declaration in (
        "width: calc(100vw - 80px);",
        "max-width: 1220px;",
        "height: min(88dvh, 820px);",
        "max-height: 88dvh;",
    ):
        assert declaration in dialog_rule

    assert "width: min(100%, 1040px);" in compact
    assert "padding: 24px 28px 28px;" in compact
    assert ".recipe-edit-ingredient-modal-section-surface" in compact
    assert "border-radius: 16px;" in compact
    assert "grid-template-columns: 180px minmax(0, 1fr);" in compact
    assert 'grid-template-areas: "image fields";' in compact
    assert ".recipe-edit-ingredient-modal-identity-fields" in compact
    assert "grid-area: fields !important;" in compact
    modal_image_slot_selector = "body.recipe-edit-standalone-page .recipe-edit-ingredient-modal-image-slot {"
    modal_image_slot = compact[
        compact.index(modal_image_slot_selector):
        compact.index("}", compact.index(modal_image_slot_selector))
    ]
    assert "grid-template-columns: minmax(0, 1fr);" in modal_image_slot
    modal_image_panel = compact[
        compact.index("dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-image-panel {"):
        compact.index("}", compact.index("dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-image-panel {"))
    ]
    assert "grid-column: 1 !important;" in modal_image_panel
    assert "grid-row: auto !important;" in modal_image_panel
    assert "justify-self: stretch !important;" in modal_image_panel
    assert "flex-direction: column;" in compact
    assert "gap: 16px;" in compact
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in compact
    assert "grid-template-columns: minmax(0, 2.1fr) minmax(240px, 1fr);" in compact
    assert "height: 40px;" in compact
    assert "font-size: 14px;" in compact
    assert "min-height: 96px;" in compact
    assert ".recipe-edit-ingredient-requirement-control" in compact
    assert ".recipe-edit-ingredient-requirement-control button.is-selected" in compact
    assert ".recipe-edit-ingredient-analysis-heading" in compact
    assert '.recipe-edit-ingredient-modal-status[data-state="dirty"]' in compact
    assert '.recipe-edit-ingredient-modal-status[data-state="saved"]' in compact
    assert '.recipe-edit-ingredient-modal-status[data-state="error"]' in compact
    assert "@media (max-width: 860px)" in compact
    assert "@media (max-width: 760px)" in compact
    assert "@media (max-width: 620px)" in compact
    modal_name_field = compact[
        compact.index("dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-name-field {"):
        compact.index("}", compact.index("dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-name-field {"))
    ]
    assert "display: grid !important;" in modal_name_field
    assert "grid-template-columns: minmax(0, 1fr);" in modal_name_field
    assert "display: flex !important;" not in modal_name_field
    modal_name_title = compact[
        compact.index(".recipe-edit-ingredient-modal-name-field .recipe-edit-ingredient-title-line {"):
        compact.index("}", compact.index(".recipe-edit-ingredient-modal-name-field .recipe-edit-ingredient-title-line {"))
    ]
    assert "grid-column: auto !important;" in modal_name_title
    assert "grid-row: auto !important;" in modal_name_title
    assert "width: 100% !important;" in modal_name_title
    identity_reset = compact[
        compact.index(".recipe-edit-ingredient-modal-field-grid > * {"):
        compact.index("}", compact.index(".recipe-edit-ingredient-modal-field-grid > * {"))
    ]
    assert "identity-grid" not in identity_reset
    assert '"image"\n            "fields";' in compact

    status = script[
        script.index("function setRecipeIngredientModalStatus"):
        script.index("const RECIPE_INGREDIENT_MODAL_SCROLL_LOCK_CLASS")
    ]
    for text in ("Unsaved changes", "Saving\\u2026", "Saved"):
        assert text in status
    assert "recipeIngredientModalHasChanges(row) ? \"dirty\" : \"\"" in status

    assert "Ingredient ${Math.max(ingredientIndex, 0) + 1} of ${Math.max(rows.length, 1)}" in script
    assert 'identityFields.className = "recipe-edit-ingredient-modal-identity-fields";' in script
    assert script.index("identityFields.appendChild(name);") < script.index("identityFields.appendChild(buyAs);")
    identity_repair = script[
        script.index("function ensureRecipeIngredientModalIdentityStack"):
        script.index("function organizeRecipeEditIngredientRow")
    ]
    assert ':scope > .recipe-edit-ingredient-modal-name-field' in identity_repair
    assert ':scope > .recipe-edit-ingredient-modal-buy-as-field' in identity_repair
    assert ':scope > .recipe-edit-ingredient-modal-type-field' in identity_repair
    assert identity_repair.index("identityFields.appendChild(name);") < identity_repair.index("identityFields.appendChild(buyAs);")
    assert identity_repair.index("identityFields.appendChild(buyAs);") < identity_repair.index("identityFields.appendChild(type);")
    assert "syncRecipeIngredientModalIdentityWidths(editPanel, identityFields);" in identity_repair
    mobile_width_sync = script[
        script.index("function setRecipeIngredientModalMobileFullWidth"):
        script.index("function ensureRecipeIngredientModalIdentityStack")
    ]
    assert 'window.matchMedia("(max-width: 760px)").matches' in mobile_width_sync
    assert '"grid-template-columns": "minmax(0, 1fr)"' in mobile_width_sync
    assert '"grid-column": "1 / -1"' in mobile_width_sync
    assert 'width: "100%"' in mobile_width_sync
    assert 'element.style.setProperty(property, value, "important");' in mobile_width_sync
    assert "[name, buyAs].forEach" in mobile_width_sync
    modal_open = script[
        script.index("function setRecipeIngredientEditMode"):
        script.index("function saveRecipeIngredientInlineEdit")
    ]
    assert "ensureRecipeIngredientModalIdentityStack(panel);" in modal_open
    assert 'window.addEventListener("resize", syncRecipeIngredientModalIdentityWidthsForViewport);' in script
    assert ".recipe-edit-ingredient-modal-identity-grid > .recipe-edit-ingredient-modal-name-field" in compact
    assert ".recipe-edit-ingredient-modal-identity-grid > .recipe-edit-ingredient-modal-buy-as-field" in compact
    assert "grid-row: 2 !important;" in compact
    modal_type_order = compact[
        compact.index("dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-type-field {"):
    ]
    modal_type_order = modal_type_order[:modal_type_order.index("}")]
    assert "order: 3;" in modal_type_order


def test_recipe_editor_ingredient_modal_v14_matches_workspace_reference_without_changing_handlers():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    workspace = css[css.index("/* Ingredient editor v14:"):]
    organize = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions", script.index("function organizeRecipeEditIngredientRow(row)"))
    ]
    buy_as_tooltip = script[
        script.index("function addRecipeIngredientBuyAsTooltip"):
        script.index("function organizeRecipeEditIngredientRow(row)")
    ]

    for label in ("Overview", "Quantity &amp; Details", "Usage", "Notes", "AI Analysis"):
        assert f"<span>{label}</span>" in organize
    for section in ("overview", "quantity", "usage", "notes", "analysis"):
        assert f'data-recipe-ingredient-modal-nav="{section}"' in organize
        assert f'data-recipe-ingredient-modal-section="{section}"' in organize
    assert 'class="recipe-edit-ingredient-modal-sidebar"' in organize
    assert 'class="recipe-edit-ingredient-modal-scroll"' in organize
    assert 'data-recipe-ingredient-modal-preview-media' in organize
    assert 'data-recipe-ingredient-modal-preview-name' in organize
    assert 'data-recipe-ingredient-modal-preview-buy-as' in organize
    assert 'data-recipe-ingredient-modal-preview-store' in organize
    assert 'class="recipe-edit-ingredient-modal-bottom-grid"' in organize
    assert 'class="recipe-edit-ingredient-analysis-summary"' in organize
    assert 'onclick="return toggleRecipeIngredientModalAnalysis(this)"' in organize
    assert 'onclick="return removeRecipeIngredientFromModal(this)"' in organize
    assert 'class="recipe-edit-ingredient-modal-delete"' in organize
    assert 'aria-label="Delete Ingredient"' in organize
    assert 'class="recipe-edit-ingredient-modal-delete-label-desktop">Delete Ingredient</span>' in organize
    assert 'class="recipe-edit-ingredient-modal-delete-label-mobile" aria-hidden="true">Delete</span>' in organize

    assert 'onclick="return cancelRecipeIngredientInlineEdit(this)"' in organize
    assert 'onclick="return previousRecipeIngredientModal(this)"' in organize
    assert 'onclick="return nextRecipeIngredientModal(this)"' in organize
    assert 'onclick="return saveRecipeIngredientInlineEdit(this)"' in organize
    assert 'onclick="return saveRecipeIngredientAndNext(this)"' in organize
    assert 'typeLabel.textContent = "Type";' in organize
    assert "identityFields.appendChild(type);" in organize
    assert "identityFields.appendChild(requirementField);" not in organize
    assert "addRecipeIngredientBuyAsTooltip(buyAs, modalId);" in organize
    assert 'helper.textContent = "The grocery item that should be added to the shopping list.";' not in organize
    assert 'field.querySelector(\':scope > input[data-field="purchasable_item"]\')' in buy_as_tooltip
    assert 'heading.className = "recipe-edit-ingredient-field-heading recipe-edit-metadata-heading";' in buy_as_tooltip
    assert 'if (!control.id) control.id = `${modalId}BuyAs`;' in buy_as_tooltip
    assert "addRecipeEditMetadataTooltip(" in buy_as_tooltip
    assert '"The grocery item that should be added to the shopping list."' in buy_as_tooltip
    assert 'if (trigger) trigger.textContent = "i";' in buy_as_tooltip
    assert "previewMedia?.appendChild(imageSlot);" in organize
    assert "analysisSummary?.appendChild(matchDetails);" in organize
    assert "[originalText, choiceReview, warning].filter(Boolean).forEach(field => support.appendChild(field));" in organize

    body_rule = workspace[workspace.index(".recipe-edit-ingredient-modal-body {"):]
    body_rule = body_rule[:body_rule.index("}")]
    assert "grid-template-columns: 292px minmax(0, 1fr);" in body_rule
    assert "overflow: hidden;" in body_rule
    scroll_rule = workspace[workspace.index(".recipe-edit-ingredient-modal-scroll {"):]
    scroll_rule = scroll_rule[:scroll_rule.index("}")]
    assert "overflow-y: auto;" in scroll_rule
    assert "overflow-x: hidden;" in scroll_rule
    scrollbar_button_rule = workspace[
        workspace.index(
            ":is(\n    .recipe-edit-ingredient-modal-body,\n"
            "    .recipe-edit-ingredient-modal-scroll\n)::-webkit-scrollbar-button {"
        ):
    ]
    scrollbar_button_rule = scrollbar_button_rule[:scrollbar_button_rule.index("}")]
    for declaration in ("display: none;", "width: 0;", "height: 0;"):
        assert declaration in scrollbar_button_rule
    locked_scrollbar_button_selector = (
        "body.recipe-ingredient-modal-open :is(\n"
        "    [data-app-content],\n"
        "    .app-sidebar,\n"
        "    .recipe-edit-ingredient-table-scroll\n"
        ").recipe-ingredient-modal-scroll-locked::-webkit-scrollbar-button {"
    )
    locked_scrollbar_button_rule = css[css.index(locked_scrollbar_button_selector):]
    locked_scrollbar_button_rule = locked_scrollbar_button_rule[
        :locked_scrollbar_button_rule.index("}")
    ]
    for declaration in (
        "-webkit-appearance: none;",
        "display: none !important;",
        "width: 0 !important;",
        "height: 0 !important;",
    ):
        assert declaration in locked_scrollbar_button_rule
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in workspace
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1.08fr);" in workspace
    bottom_grid_rule = workspace[workspace.index(".recipe-edit-ingredient-modal-bottom-grid {"):]
    bottom_grid_rule = bottom_grid_rule[:bottom_grid_rule.index("}")]
    assert "align-items: start;" in bottom_grid_rule
    assert "align-items: stretch;" not in bottom_grid_rule
    bottom_card_rule = workspace[
        workspace.index(
            ".recipe-edit-ingredient-modal-bottom-grid > .recipe-edit-ingredient-modal-section {"
        ):
    ]
    bottom_card_rule = bottom_card_rule[:bottom_card_rule.index("}")]
    assert "align-self: start;" in bottom_card_rule
    assert "height: fit-content;" in bottom_card_rule
    bottom_surface_rule = workspace[
        workspace.index(
            ".recipe-edit-ingredient-modal-bottom-grid .recipe-edit-ingredient-modal-section-surface {"
        ):
    ]
    bottom_surface_rule = bottom_surface_rule[:bottom_surface_rule.index("}")]
    assert "min-height: 0;" in bottom_surface_rule
    assert "height: fit-content;" in bottom_surface_rule
    assert "min-height: 100%;" not in bottom_surface_rule
    assert "padding: 24px 28px;" in workspace
    assert "gap: 20px;" in workspace
    identity_fields_rule = workspace[
        workspace.index(
            "dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-identity-fields {"
        ):
    ]
    identity_fields_rule = identity_fields_rule[:identity_fields_rule.index("}")]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in identity_fields_rule
    identity_width_rule = workspace[
        workspace.index(
            "dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-identity-fields > :is("
        ):
    ]
    identity_width_rule = identity_width_rule[:identity_width_rule.index("}")]
    assert ".recipe-edit-ingredient-modal-name-field" in identity_width_rule
    assert ".recipe-edit-ingredient-modal-buy-as-field" in identity_width_rule
    assert "width: 100% !important;" in identity_width_rule
    assert "max-width: none !important;" in identity_width_rule
    assert "align-self: start !important;" in identity_width_rule
    name_control_width_rule = workspace[
        workspace.index(
            "dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-name-field :is("
        ):
    ]
    name_control_width_rule = name_control_width_rule[:name_control_width_rule.index("}")]
    assert 'textarea[data-field="ingredient"]' in name_control_width_rule
    assert "box-sizing: border-box;" in name_control_width_rule
    assert "width: 100% !important;" in name_control_width_rule
    assert "max-width: none !important;" in name_control_width_rule
    assert ".recipe-edit-ingredient-modal-nav button.is-active" in workspace
    assert ".recipe-edit-ingredient-analysis-toggle" in workspace
    assert ".recipe-edit-ingredient-match-details-grid > div" in workspace
    assert "border-bottom:" in workspace
    assert ".recipe-edit-ingredient-modal-footer" in workspace
    assert ".recipe-edit-ingredient-modal-delete" in workspace
    assert "@media (max-width: 980px)" in workspace
    assert "@media (max-width: 760px)" in workspace
    mobile = workspace[workspace.index("@media (max-width: 760px)"):]
    assert ".recipe-edit-ingredient-modal-nav" in mobile
    assert "display: flex;" in mobile
    assert "grid-template-columns: minmax(0, 1fr);" in mobile
    mobile_footer_selector = ".recipe-edit-ingredient-modal-footer {"
    mobile_footer = mobile[mobile.index(mobile_footer_selector):]
    mobile_footer = mobile_footer[:mobile_footer.index("}")]
    for declaration in (
        "grid-template-columns: repeat(6, minmax(0, 1fr));",
        "min-height: 0;",
        "gap: 6px;",
        "padding: 8px 12px max(8px, env(safe-area-inset-bottom));",
    ):
        assert declaration in mobile_footer
    mobile_cancel_selector = (
        ".recipe-edit-ingredient-modal-footer-actions .recipe-edit-ingredient-edit-cancel {"
    )
    mobile_cancel = mobile[mobile.index(mobile_cancel_selector):]
    mobile_cancel = mobile_cancel[:mobile_cancel.index("}")]
    assert "display: none;" in mobile_cancel
    for selector, placement in (
        (".recipe-edit-ingredient-modal-delete {", "grid-column: 1 / span 2;"),
        (".recipe-edit-ingredient-modal-previous {", "grid-column: 3 / span 2;"),
        (".recipe-edit-ingredient-modal-forward {", "grid-column: 5 / span 2;"),
        (".recipe-edit-ingredient-edit-save {", "grid-column: 1 / span 3;"),
        (
            ".recipe-edit-ingredient-modal-footer-actions .recipe-edit-ingredient-modal-next {",
            "grid-column: 4 / span 3;",
        ),
    ):
        rule = mobile[mobile.index(selector):]
        rule = rule[:rule.index("}")]
        assert placement in rule
    mobile_delete = mobile[mobile.index(".recipe-edit-ingredient-modal-delete {"):]
    mobile_delete = mobile_delete[:mobile_delete.index("}")]
    assert "height: 30px;" in mobile_delete
    assert "min-height: 30px !important;" in mobile_delete
    mobile_delete_label = mobile[
        mobile.index(".recipe-edit-ingredient-modal-delete-label-mobile {"):
    ]
    mobile_delete_label = mobile_delete_label[:mobile_delete_label.index("}")]
    assert "display: inline;" in mobile_delete_label
    mobile_identity_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-modal-identity-fields {"
    )
    mobile_identity = mobile[mobile.index(mobile_identity_selector):]
    mobile_identity = mobile_identity[:mobile_identity.index("}")]
    for declaration in (
        "display: grid !important;",
        "grid-template-columns: minmax(0, 1fr) !important;",
        "width: 100% !important;",
        "align-items: start;",
    ):
        assert declaration in mobile_identity
    assert "display: flex !important;" not in mobile_identity
    mobile_dialog = mobile[
        mobile.index("dialog.recipe-edit-ingredient-edit-panel {"):
    ]
    mobile_dialog = mobile_dialog[:mobile_dialog.index("}")]
    assert 'font-family: "Segoe UI Variable", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif;' in mobile_dialog
    mobile_identity_children_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-modal-identity-fields > * {"
    )
    mobile_identity_children = mobile[mobile.index(mobile_identity_children_selector):]
    mobile_identity_children = mobile_identity_children[:mobile_identity_children.index("}")]
    assert "grid-column: 1 !important;" in mobile_identity_children
    assert "width: 100% !important;" in mobile_identity_children
    assert "max-width: none !important;" in mobile_identity_children
    mobile_identity_width_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-modal-identity-fields > :is("
    )
    mobile_identity_width = mobile[mobile.index(mobile_identity_width_selector):]
    mobile_identity_width = mobile_identity_width[:mobile_identity_width.index("}")]
    assert ".recipe-edit-ingredient-modal-name-field" in mobile_identity_width
    assert ".recipe-edit-ingredient-modal-buy-as-field" in mobile_identity_width
    for declaration in (
        "grid-column: 1 / -1 !important;",
        "justify-self: stretch;",
        "box-sizing: border-box;",
        "width: 100% !important;",
        "max-width: none !important;",
        "margin-inline: 0 !important;",
        "align-items: stretch !important;",
        "text-align: left;",
    ):
        assert declaration in mobile_identity_width
    mobile_name_control_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-modal-name-field textarea[data-field=\"ingredient\"] {"
    )
    mobile_name_control_start = mobile.index(mobile_name_control_selector)
    mobile_name_control = mobile[mobile_name_control_start:]
    mobile_name_control = mobile_name_control[:mobile_name_control.index("}")]
    for declaration in (
        "box-sizing: border-box;",
        "width: 100% !important;",
        "max-width: none !important;",
        "margin-inline: 0 !important;",
        "align-self: stretch !important;",
    ):
        assert declaration in mobile_name_control

    mobile_field_type_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select) {"
    )
    mobile_field_type = mobile[mobile.index(mobile_field_type_selector):]
    mobile_field_type = mobile_field_type[:mobile_field_type.index("}")]
    assert "font-size: 16px;" in mobile_field_type
    assert "font-weight: 500;" in mobile_field_type
    assert "line-height: 1.25;" in mobile_field_type
    mobile_name_type_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-modal-name-field textarea[data-field=\"ingredient\"] {"
    )
    mobile_name_type_start = mobile.index(mobile_name_type_selector, mobile_name_control_start + len(mobile_name_control))
    mobile_name_type = mobile[mobile_name_type_start:]
    mobile_name_type = mobile_name_type[:mobile_name_type.index("}")]
    assert "font-size: 16px !important;" in mobile_name_type
    assert ".recipe-edit-ingredient-modal-section-surface > h3" in mobile
    assert "font-weight: 700;" in mobile
    assert ".recipe-edit-ingredient-field-heading" in workspace
    assert "display: flex;" in workspace
    assert ".recipe-edit-ingredient-field-heading" in mobile
    assert ".recipe-edit-ingredient-field-helper" not in workspace

    shared_quiet_field_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select):not([aria-invalid=\"true\"]),"
    )
    shared_quiet_field = workspace[workspace.index(shared_quiet_field_selector):]
    shared_quiet_field = shared_quiet_field[:shared_quiet_field.index("}")]
    assert workspace.index(shared_quiet_field_selector) < workspace.index("@media (max-width: 760px)")
    assert ".recipe-edit-store-section-trigger" in shared_quiet_field
    assert ".recipe-edit-type-trigger" in shared_quiet_field
    assert "border-color: transparent;" in shared_quiet_field
    assert "background: color-mix(in srgb, var(--app-bg) 68%, var(--app-surface-soft));" in shared_quiet_field
    assert "box-shadow: none;" in shared_quiet_field

    shared_hover_field_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select):not([aria-invalid=\"true\"]):hover,"
    )
    shared_hover_field = workspace[workspace.index(shared_hover_field_selector):]
    shared_hover_field = shared_hover_field[:shared_hover_field.index("}")]
    assert workspace.index(shared_quiet_field_selector) < workspace.index(shared_hover_field_selector)
    assert ".recipe-edit-store-section-trigger" in shared_hover_field
    assert ".recipe-edit-type-trigger" in shared_hover_field
    assert "border-color: color-mix(in srgb, var(--app-primary-hover) 72%, var(--app-border-strong));" in shared_hover_field
    assert "box-shadow: 0 0 0 1px" in shared_hover_field

    shared_active_field_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select):focus,"
    )
    shared_active_field = workspace[workspace.index(shared_active_field_selector):]
    shared_active_field = shared_active_field[:shared_active_field.index("}")]
    assert workspace.index(shared_hover_field_selector) < workspace.index(shared_active_field_selector)
    assert ':is(:focus-visible, [aria-expanded="true"])' in shared_active_field
    assert "border-color: var(--app-primary-hover);" in shared_active_field
    assert "box-shadow: 0 0 0 2px" in shared_active_field

    shared_invalid_field_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select)[aria-invalid=\"true\"],"
    )
    shared_invalid_field = workspace[workspace.index(shared_invalid_field_selector):]
    shared_invalid_field = shared_invalid_field[:shared_invalid_field.index("}")]
    assert ".recipe-edit-store-section-trigger" in shared_invalid_field
    assert "border-color: var(--app-danger, #ef4444);" in shared_invalid_field
    assert "box-shadow: 0 0 0 2px" in shared_invalid_field

    mobile_image_actions_selector = (
        ".recipe-edit-ingredient-modal-preview-media "
        ".recipe-edit-ingredient-modal-image-panel > .recipe-step-image-actions {"
    )
    mobile_image_actions = mobile[mobile.index(mobile_image_actions_selector):]
    mobile_image_actions = mobile_image_actions[:mobile_image_actions.index("}")]
    for declaration in (
        "left: 0;",
        "width: min(220px, calc(100vw - 52px));",
        "transform: translateY(-5px);",
    ):
        assert declaration in mobile_image_actions
    assert "display: none !important;" not in mobile_image_actions
    assert ".recipe-ingredient-image-options-open > .recipe-step-image-actions" in mobile
    assert "transform: translateY(0);" in mobile

    match_details = script[
        script.index("function recipeIngredientMatchDetailsHtml"):
        script.index("function recipeIngredientBadgesHtml", script.index("function recipeIngredientMatchDetailsHtml"))
    ]
    match_labels = (
        "Status",
        "Match Confidence",
        "Best Available Match",
        "Selected Matched Ingredient",
        "Alternative Matches",
        "Source / Matching Reason",
    )
    match_positions = [match_details.index(label) for label in match_labels]
    assert match_positions == sorted(match_positions)


def test_recipe_editor_ingredient_polish_uses_professional_grid_and_command_bar():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    polish = css[css.index("/* Ingredient editor v6:"):]

    assert 'class="recipe-edit-add-ingredient-button"' in template
    assert ".recipe-edit-add-ingredient-button" in polish
    assert "min-height: 40px;" in polish
    assert "minmax(144px, 1.25fr)" in polish
    for width in ("80px", "120px", "170px", "128px"):
        assert width in polish
    assert "min-width: 1152px;" in polish
    assert "min-height: 60px !important;" in polish
    assert "line-height: 14px;" in polish
    assert "white-space: pre-wrap;" in polish
    assert "box-shadow: inset 3px 0 0 var(--app-primary);" in polish
    assert ".recipe-edit-ingredient-row.recipe-edit-menu-open" in polish
    assert "width: 40px;" in polish
    assert "height: 40px;" in polish
    assert "text-transform: uppercase;" in polish
    assert "white-space: nowrap;" in polish

    action_start = script.index("function organizeRecipeEditCompactRowActions")
    action_end = script.index("function updateRecipeEditIngredientDetailsState", action_start)
    action_block = script[action_start:action_end]
    assert action_block.index("recipe-edit-compact-row-details") < action_block.index("recipe-edit-compact-row-edit")
    assert action_block.index("recipe-edit-compact-row-edit") < action_block.index("recipe-edit-compact-row-delete")
    assert 'title="More details"' in action_block
    assert 'title="Edit ${escapeAttribute(label)}"' in action_block
    assert 'title="Delete ${escapeAttribute(label)}"' in action_block


def test_recipe_editor_expanded_analysis_fields_ignore_collapsed_row_visibility():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    override = css[css.index("/* Keep expanded modal analysis fields visible") :]
    assert "#recipeEditIngredients" in override
    assert "> dialog.recipe-edit-ingredient-edit-panel" in override
    assert ".recipe-edit-ingredient-edit-field" in override
    assert "display: grid !important;" in override
    assert ".recipe-edit-ingredient-analysis:not([hidden])" in override
    assert ".recipe-edit-original-text-label" in override
    assert ".recipe-edit-choice-review:not([hidden])" in override
    assert ".recipe-edit-extraction-warning:not([hidden])" in override
    assert "display: grid;" in override
    assert "display: inline-flex;" in override


def test_recipe_editor_v7_separates_toolbar_options_actions_and_popover():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    polish = css[css.index("/* Ingredient editor v7:"):]

    assert 'class="recipe-edit-section-header ingredients-toolbar"' in template
    assert "recipe-edit-ingredient-actions ingredients-toolbar-actions" in template
    assert ".recipe-edit-ingredients-section > .ingredients-toolbar" in polish
    assert "position: relative;" in polish
    assert "justify-content: space-between;" in polish
    assert "min-height: 48px;" in polish
    assert "padding: 8px 16px;" in polish
    assert ".ingredients-toolbar > .ingredients-toolbar-actions" in polish
    assert "gap: 12px;" in polish

    desktop_grid = """--recipe-edit-ingredient-grid:
        28px
        48px
        minmax(180px, 1.35fr)
        110px
        72px
        110px
        160px
        110px
        160px
        88px;"""
    assert desktop_grid in polish
    assert "--recipe-edit-ingredient-column-gap: 12px;" in polish
    assert "overflow-x: auto;" in polish
    assert "min-width: 1206px;" in polish
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in polish

    options_start = polish.index(
        ".recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-ingredient-options-button {"
    )
    options_end = polish.index("}", options_start)
    options = polish[options_start:options_end]
    for rule in (
        "display: flex;", "align-items: center;", "width: 100%;", "min-width: 150px;",
        "max-width: 165px;", "height: 38px;", "padding: 0 12px 0 13px;", "flex: 1 1 auto;",
        "justify-content: space-between;", "gap: 8px;", "overflow: visible;",
        "text-indent: 0;", "white-space: nowrap;", "aspect-ratio: auto;",
    ):
        assert rule in options
    assert "width: 32px;" not in options
    assert "max-width: 40px;" not in options
    assert "overflow: hidden;" not in options

    options_label_start = polish.index("[data-ingredient-options-label]")
    options_label_end = polish.index("}", options_label_start)
    options_label = polish[options_label_start:options_label_end]
    assert "overflow: visible;" in options_label
    assert "text-overflow: clip;" in options_label

    actions_start = polish.index(
        ".recipe-edit-standalone-page #recipeEditIngredients > .recipe-edit-ingredient-row > .recipe-edit-compact-row-actions {"
    )
    actions_end = polish.index("}", actions_start)
    actions = polish[actions_start:actions_end]
    assert "width: 88px;" in actions
    assert "min-width: 88px;" in actions

    assert "minmax(160px, 1.35fr)" in polish
    assert "min-width: 1186px;" in polish
    assert "min-width: 1166px;" in polish
    assert "min-width: 1152px;" in polish

    assert "width: min(1080px, calc(100vw - 32px));" in polish
    assert "min-width: min(760px, calc(100vw - 32px));" in polish
    assert "minmax(170px, 1.5fr)" in polish
    assert ".recipe-edit-buy-as-label" in polish
    assert "min-width: 160px;" in polish
    assert "overflow-wrap: break-word;" in polish
    assert "word-break: normal;" in polish
    assert "white-space: normal;" in polish
    assert "hyphens: none;" in polish

    position_start = script.index("function positionRecipeEditPopupMenu")
    position_end = script.index("function portalRecipeEditPopupMenu", position_start)
    position = script[position_start:position_end]
    assert 'menu.classList.contains("recipe-edit-ingredient-row-menu")' in position
    assert "const margin = isIngredientOptionsMenu ? 16 : 8;" in position
    assert "const gap = isIngredientOptionsMenu ? 10 : 6;" in position
    assert 'button.closest(".recipe-edit-tabs-card")' in position
    assert "const availableWidth = Math.max(0, horizontalRightLimit - horizontalLeftLimit);" in position
    assert "const popupWidth = Math.min(1080, availableWidth);" in position
    assert "buttonRect.left + menuWidth <= rightLimit" in position
    assert 'menu.matches(".recipe-edit-unit-menu, .recipe-edit-type-menu")' in position
    assert "let left = alignMenuToAnchorStart ? buttonRect.left : buttonRect.right - menuWidth;" in position
    assert "left = Math.max(horizontalLeftLimit, Math.min(left, rightLimit - menuWidth));" in position

    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in script
    assert "recipeIngredientCompactChoiceSummary" in script
    assert "summary.textContent = alternativeCount ? compactSummary.summary : \"\";" in script
    assert "document.body.appendChild(menu);" in script


def test_recipe_editor_ingredient_columns_can_be_reordered_resized_hidden_and_reset():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8"
    )

    assert 'const RECIPE_EDIT_INGREDIENT_COLUMN_STORAGE_KEY = "recipeEditIngredientColumnsV2";' in script
    assert 'const RECIPE_EDIT_INGREDIENT_COLUMN_ORDER = [' in script
    for column in (
        "media", "ingredient", "status", "quantity", "unit",
        "size", "store", "type", "alternatives", "actions",
    ):
        assert f'data-ingredient-column="{column}"' in script

    interaction_start = script.index("function recipeEditIngredientColumnStorageKey()")
    interaction_end = script.index("function organizeRecipeEditEquipmentTools()", interaction_start)
    interaction = script[interaction_start:interaction_end]
    for behavior in (
        "loadRecipeEditIngredientColumnLayout",
        "saveRecipeEditIngredientColumnLayout",
        "moveRecipeEditIngredientColumn",
        "beginRecipeEditIngredientColumnMove",
        "updateRecipeEditIngredientColumnMove",
        "finishRecipeEditIngredientColumnMove",
        "showRecipeEditIngredientColumnResizeGuide",
        "hideRecipeEditIngredientColumnResizeGuide",
        "bindRecipeEditIngredientColumnResizeTracking",
        "unbindRecipeEditIngredientColumnResizeTracking",
        "beginRecipeEditIngredientColumnResize",
        "updateRecipeEditIngredientColumnResize",
        "autoFitRecipeEditIngredientColumns",
        "setRecipeEditIngredientColumnVisibility",
        "showAllRecipeEditIngredientColumns",
        "syncRecipeEditIngredientColumnVisibilityMenu",
        "applyRecipeEditIngredientColumnVisibility",
        "handleRecipeEditIngredientColumnKeydown",
        "resetRecipeEditIngredientColumnLayout",
    ):
        assert f"function {behavior}" in interaction
    assert 'header.addEventListener("pointerdown"' in interaction
    assert 'header.addEventListener("pointermove"' in interaction
    assert 'header.addEventListener("pointerup"' in interaction
    assert 'header.addEventListener("pointercancel"' in interaction
    assert 'resizeHandle.addEventListener("pointerdown"' in interaction
    assert 'resizeHandle.addEventListener("dblclick"' in interaction
    assert 'handle.setPointerCapture(event.pointerId)' in interaction
    assert "currentOrder.every((key, index) => key === order[index])" in interaction
    assert 'window.addEventListener("pointermove", updateRecipeEditIngredientColumnResize, true);' in interaction
    assert 'window.addEventListener("mousemove", updateRecipeEditIngredientColumnResize, true);' in interaction
    assert 'window.addEventListener("mouseup", finishRecipeEditIngredientColumnResize, true);' in interaction
    assert 'window.removeEventListener("pointermove", updateRecipeEditIngredientColumnResize, true);' in interaction
    assert 'window.removeEventListener("mousemove", updateRecipeEditIngredientColumnResize, true);' in interaction
    assert 'window.removeEventListener("mouseup", finishRecipeEditIngredientColumnResize, true);' in interaction
    assert 'state.header.getBoundingClientRect().right' in interaction
    resize_update = interaction[
        interaction.index("function updateRecipeEditIngredientColumnResize"):
        interaction.index("function beginRecipeEditIngredientColumnResize")
    ]
    assert "const layout = ensureRecipeEditIngredientColumnLayout();" in resize_update
    assert "layout.widths[state.key] = clampRecipeEditIngredientColumnWidth(" in resize_update
    assert "state.layout" not in resize_update
    assert 'window.localStorage.setItem(' in interaction
    assert 'window.localStorage.removeItem(' in interaction
    assert "const requestedHidden = Array.isArray(value?.hidden) ? value.hidden : [];" in interaction
    assert "return { order, widths, hidden };" in interaction
    assert 'checkbox.type = "checkbox";' in interaction
    assert "checkbox.checked = !hidden.has(key);" in interaction
    assert "checkbox.disabled = checkbox.checked && visibleCount === 1;" in interaction
    assert 'cell.dataset.recipeEditIngredientColumnHidden = "true";' in interaction
    assert 'header.dataset.recipeEditIngredientColumnHidden = "true";' in interaction
    visibility = interaction[
        interaction.index("function applyRecipeEditIngredientColumnVisibility"):
        interaction.index("function clearRecipeEditIngredientColumnLayoutStyles")
    ]
    assert "Object.entries(RECIPE_EDIT_INGREDIENT_COLUMNS)" in visibility
    assert "hidden.has(key)" in visibility
    refresh = interaction[
        interaction.index("function refreshRecipeEditIngredientColumnLayout"):
        interaction.index("function moveRecipeEditIngredientColumn")
    ]
    assert refresh.index("clearRecipeEditIngredientColumnLayoutStyles();") < refresh.index(
        "applyRecipeEditIngredientColumnVisibility(recipeEditIngredientColumnLayout);"
    )
    assert 'tableScroll.setAttribute("aria-colcount", String(visibleOrder.length));' in interaction
    assert 'autoFitColumns.textContent = "Auto-fit column widths";' in interaction
    assert 'resetColumns.textContent = "Restore default columns";' in interaction
    assert 'window.matchMedia("(min-width: 768px)")' in interaction
    assert "table.clientWidth > 859" in interaction
    assert 'class="recipe-edit-ingredient-columns-button"' in template
    assert "Choose which columns are visible." in template
    assert "data-recipe-edit-ingredient-column-visibility" in template
    assert "Show all columns" in template
    assert "Auto-fit column widths" in template
    assert "Restore default columns" in template
    assert "Drag a vertical boundary to resize it" in template
    assert "double-click the boundary to auto-fit" in template

    column_css = css[css.index("/* Ingredient editor v22:"):]
    assert ".recipe-edit-ingredient-column-menu" in column_css
    assert ".recipe-edit-ingredient-column-visibility" in column_css
    assert ".recipe-edit-ingredient-column-option" in column_css
    assert '[data-recipe-edit-ingredient-column-hidden="true"]' in column_css
    assert ".recipe-edit-ingredient-column-move" in column_css
    assert ".recipe-edit-ingredient-column-resize" in column_css
    assert ".recipe-edit-ingredient-column-resize-guide" in column_css
    assert "inset-block: -12px;" in column_css
    assert "width: 18px;" in column_css
    assert "cursor: col-resize;" in column_css
    assert ".is-column-drop-before" in column_css
    assert ".is-column-drop-after" in column_css
    assert '[data-recipe-edit-ingredient-column-layout-enabled="true"]' in column_css
    mobile = column_css[column_css.index("@media (max-width: 767px)"):]
    assert "display: none !important;" in mobile


def test_recipe_editor_auto_fit_keeps_visible_columns_inside_the_table_width():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    definitions = script[
        script.index("const RECIPE_EDIT_INGREDIENT_COLUMNS = {"):
        script.index("const RECIPE_EDIT_PDF_FIELD_ALIASES")
    ]
    keys = (
        "media", "ingredient", "status", "quantity", "unit",
        "size", "store", "type", "alternatives", "actions",
    )
    minimum_widths = []
    for index, key in enumerate(keys):
        next_key = keys[index + 1] if index + 1 < len(keys) else None
        start = definitions.index(f"    {key}: {{")
        end = definitions.index(f"    {next_key}: {{", start) if next_key else len(definitions)
        block = definitions[start:end]
        minimum_line = next(line for line in block.splitlines() if "minWidth:" in line)
        minimum_widths.append(int(minimum_line.split(":", 1)[1].strip(" ,")))
    assert sum(minimum_widths) + (10 * (len(keys) - 1)) + 24 + 2 <= 860

    alternatives = definitions[
        definitions.index("    alternatives: {"):
        definitions.index("    actions: {")
    ]
    assert "minWidth: 84" in alternatives
    assert "maxWidth: 180" in alternatives
    assert "fallbackWidth: 132" in alternatives

    auto_fit = script[
        script.index("function fitRecipeEditIngredientColumnWidthsToBudget"):
        script.index("function recipeEditIngredientColumnLayoutIsAvailable")
    ]
    assert "const target = Math.max(minimumTotal" in auto_fit
    assert 'const visibleKeys = recipeEditIngredientVisibleColumnOrder(layout);' in auto_fit
    assert "recipeEditIngredientColumnWidthBudget(tableScroll, visibleKeys.length, gap)" in auto_fit
    assert "Object.assign(layout.widths, fittedWidths);" in auto_fit
    assert 'tableScroll.clientWidth' in auto_fit
    assert 'Visible ingredient columns fitted to their content within the table width.' in auto_fit
    assert "if (total > target)" in auto_fit
    assert 'const shrinkTiers = [' in auto_fit
    assert '["ingredient", "alternatives"]' in auto_fit
    assert '["store", "type"]' in auto_fit
    assert auto_fit.index('["ingredient", "alternatives"]') < auto_fit.index('["store", "type"]')
    assert "if (total < target)" not in auto_fit
    assert "const growthOrder" not in auto_fit
    assert "Preserve content-fitted widths when the visible columns already fit." in auto_fit
    assert 'function recipeEditIngredientColumnCellText(cell, key = "")' in script
    assert 'cell.querySelectorAll("[data-type-trigger-label]")' in script
    assert '"value" in label ? label.value : label.textContent' in script
    assert 'const contentAllowances = { store: 64, type: 46 };' in script
    assert 'const contentAllowance = contentAllowances[key] || 30;' in script
    assert "recipeEditIngredientColumnCellText(cell, key)" in script
    assert "text) + contentAllowance" in script

    alternatives_css = css[css.index("@media (min-width: 768px) {", css.index("/* Ingredient editor v20:")):]
    assert ".recipe-edit-ingredient-options-button" in alternatives_css
    assert ".recipe-edit-ingredient-options-copy" in alternatives_css
    assert "overflow: hidden;" in alternatives_css
    assert "text-overflow: ellipsis;" in alternatives_css


def test_recipe_editor_size_column_follows_unit_and_matches_quantity_formatting():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    order = script[
        script.index("const RECIPE_EDIT_INGREDIENT_COLUMN_ORDER = ["):
        script.index("const RECIPE_EDIT_INGREDIENT_COLUMNS = {")
    ]
    assert order.index('"unit"') < order.index('"size"') < order.index('"store"')

    quantity_definition = script[
        script.index("    quantity: {"):
        script.index("    unit: {")
    ]
    size_definition = script[
        script.index("    size: {"):
        script.index("    store: {")
    ]
    for formatting in ("minWidth: 52", "maxWidth: 240", "fallbackWidth: 72"):
        assert formatting in quantity_definition
        assert formatting in size_definition

    headers = script[
        script.index('data-ingredient-column="quantity"'):
        script.index('data-ingredient-column="actions"')
    ]
    assert headers.index('data-ingredient-column="unit"') < headers.index(
        'data-ingredient-column="size"'
    ) < headers.index('data-ingredient-column="store"')

    row = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    assert row.index('"ingredientUnitSummary", "unit", "input"') < row.index(
        '"ingredientSizeSummary", "size", "input"'
    ) < row.index('"ingredientStoreSummary", "store_section", "display"')
    inline_control_factory = script[
        script.index("function appendRecipeIngredientInlineSummaryControl"):
        script.index("function createRecipeIngredientOptionRowSummary")
    ]
    assert 'size: "Size"' in inline_control_factory
    assert 'substitutions.setAttribute("role", "region");' in row
    assert 'substitutions.removeAttribute("aria-colspan");' in row

    normalize = script[
        script.index("function normalizeRecipeEditIngredientColumnLayout"):
        script.index("function loadRecipeEditIngredientColumnLayout")
    ]
    assert 'if (!rawOrder.includes("size")) {' in normalize
    assert 'order.splice(order.indexOf("unit") + 1, 0, "size");' in normalize

    assert '[data-ingredient-column="unit"] { grid-column: 6; }' in css
    assert '[data-ingredient-column="size"] { grid-column: 7; }' in css
    assert '.recipe-edit-ingredient-size-summary::before {' in css
    assert 'content: "Size";' in css


def test_recipe_editor_ingredient_modal_ignores_table_column_visibility_filters():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    helper_start = script.index("function clearRecipeIngredientModalColumnVisibility")
    helper_end = script.index("function clearRecipeEditIngredientColumnLayoutStyles", helper_start)
    helper = script[helper_start:helper_end]
    assert 'panel.querySelectorAll("[data-recipe-edit-ingredient-column-hidden]")' in helper
    assert "delete field.dataset.recipeEditIngredientColumnHidden;" in helper

    organize_start = script.index("function organizeRecipeEditIngredientRow")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert organize.index("row.appendChild(editPanel);") < organize.index(
        "clearRecipeIngredientModalColumnVisibility(editPanel);"
    )

    edit_mode_start = script.index("function setRecipeIngredientEditMode")
    edit_mode_end = script.index("function saveRecipeIngredientInlineEdit", edit_mode_start)
    edit_mode = script[edit_mode_start:edit_mode_end]
    assert edit_mode.index("clearRecipeIngredientModalColumnVisibility(panel);") < edit_mode.index(
        "panel.hidden = false;"
    )

    column_css = css[css.index("/* Ingredient editor v22:"):]
    visibility_start = column_css.index(
        'body.recipe-edit-standalone-page .recipe-edit-ingredient-table-head'
    )
    visibility_end = column_css.index("}", visibility_start)
    visibility_rule = column_css[visibility_start:visibility_end]
    assert "> [data-recipe-edit-ingredient-column-hidden=\"true\"]" in visibility_rule
    assert "> .recipe-edit-ingredient-row" in visibility_rule
    assert "recipe-edit-ingredient-edit-panel" not in visibility_rule


def test_recipe_editor_alternatives_use_nested_table_rows_without_losing_edit_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    substitution_start = script.index("function organizeRecipeEditSubstitutionOptionRow")
    substitution_end = script.index("function organizeRecipeEditIngredientRow", substitution_start)
    substitution = script[substitution_start:substitution_end]
    summary_start = script.index("function createRecipeIngredientOptionRowSummary(")
    summary_end = script.index("function updateRecipeIngredientOptionRowSummary", summary_start)
    summary = script[summary_start:summary_end]
    shared_cells = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function appendRecipeIngredientInlineSummaryControl")
    ]
    assert 'optionRow.classList.add("recipe-edit-alternative-component");' in substitution
    assert "const summary = createRecipeIngredientOptionRowSummary();" in substitution
    assert '"recipe-edit-alternative-component-summary"' in summary
    assert "data-alternative-component-name" in shared_cells
    assert "createRecipeIngredientReadCell(" in summary
    assert "createRecipeIngredientStatusSummary(" in summary
    assert '"recipe-edit-alternative-component-quantity recipe-edit-ingredient-quantity-summary"' in summary
    assert '"recipe-edit-alternative-component-unit recipe-edit-ingredient-unit-summary"' in summary
    assert '"recipe-edit-alternative-component-size recipe-edit-ingredient-size-summary"' in summary
    for field_name, data_name in (
        ("quantity", "alternativeComponentQuantity"),
        ("unit", "alternativeComponentUnit"),
        ("size", "alternativeComponentSize"),
        ("store_section", "alternativeComponentStore"),
        ("section", "alternativeComponentType"),
    ):
        selector_name = {
            "store_section": "store",
            "section": "type",
        }.get(field_name, field_name)
        assert (
            f'["{field_name}", ".recipe-edit-alternative-component-{selector_name}", '
            f'"{data_name}"'
        ) in summary
    assert "appendRecipeIngredientInlineSummaryControl(" in summary
    assert "alternativeComponentStore" in summary
    assert "alternativeComponentStatus" in shared_cells
    assert '"alternativeComponentSize"' in summary
    assert "alternativeComponentType" in summary
    assert "data-alternative-component-metadata" in summary
    assert "data-alternative-component-buy-as" in shared_cells
    assert 'data-ingredient-column="media"' in summary
    assert 'ingredientCell.dataset.ingredientColumn = "ingredient";' in summary
    assert 'data-ingredient-column="actions"' in summary
    assert 'editGrid.className = "recipe-edit-alternative-component-edit-grid";' in substitution
    assert 'identity.className = "recipe-edit-alternative-edit-field field-ingredient";' in substitution
    assert 'compactMetadata.className = "recipe-edit-alternative-metadata-inputs";' in substitution
    assert "[preparation, size, optional]" in substitution
    assert "quantityText" not in substitution
    assert 'sourceDetails.className = "recipe-edit-alternative-source-details";' in substitution
    assert "<span>More details</span>" in substitution
    assert "Purchasing, preparation, optional, and source" in substitution
    assert 'buyAsLabel.textContent = "Purchasing name (if different)";' in substitution
    assert 'ingredientLabel.className = "sr-only";' in substitution
    assert 'ingredientLabel.textContent = "Ingredient";' in substitution
    assert "sourceGrid.appendChild(buyAs);" in substitution
    assert "sourceGrid.appendChild(compactMetadata);" in substitution
    assert "identity.appendChild(buyAs);" not in substitution
    assert "identity.appendChild(compactMetadata);" not in substitution
    assert '["Match source",' in substitution
    assert '["Match confidence",' in substitution
    assert '["AI reasoning",' in substitution
    assert "optional.hidden = true;" not in substitution
    assert "removeComponent" not in substitution
    assert "openRecipeIngredientOptionModal(this)" in substitution
    assert "createRecipeIngredientEditActionButton()" in substitution
    assert (
        "editButton.addEventListener(\"click\", () => "
        "openRecipeIngredientOptionModal(editButton));"
        in substitution
    )
    assert "duplicateRecipeIngredientAlternativeComponent(this)" in substitution
    assert ">Edit details</button>" in substitution
    assert ">Duplicate replacement ingredient</button>" in substitution
    assert ">Remove replacement ingredient</button>" in substitution
    assert "data-alternative-component-remove" in substitution
    assert "updateRecipeIngredientAlternativeComponentSummary(optionRow);" in substitution

    alternative_markup = script[
        script.index("function recipeIngredientSubstitutionOptionRowHtml"):
        script.index("function recipeIngredientSubstitutionOptionsHtml")
    ]
    assert 'data-field="ingredient_image_url"' in alternative_markup
    assert 'data-field="ingredient_image_generated_at"' in alternative_markup
    assert 'data-field="ingredient_image_prompt"' in alternative_markup
    assert '<textarea data-field="ingredient" rows="1" aria-label="Ingredient">' in alternative_markup
    assert '<span>Quantity</span>' in alternative_markup
    assert '<span>Amount</span>' not in alternative_markup
    assert '<input type="hidden" data-field="quantity_text"' in alternative_markup
    assert '<span>Quantity Text</span>' not in alternative_markup
    assert 'data-field="confidence_score"' in alternative_markup
    assert 'data-field="match_confidence"' in alternative_markup
    assert 'data-field="reason"' in alternative_markup
    assert '<select data-field="section" hidden>' in alternative_markup
    assert "bindRecipeEditDragAndDrop(optionRow);" in script

    card_logic = script[
        script.index("function updateRecipeIngredientAlternativeCard"):
        script.index("function createRecipeIngredientAlternativeCard")
    ]
    assert 'card.classList.toggle("is-single-alternative", singleIngredient);' in card_logic
    assert 'card.classList.toggle("is-multi-alternative", !singleIngredient);' in card_logic

    card_markup = script[
        script.index("function createRecipeIngredientAlternativeCard"):
        script.index("function ensureRecipeIngredientAlternativeCards")
    ]
    shared_header = script[
        script.index("function recipeIngredientOptionHeaderMenuHtml"):
        script.index("function renderRecipeIngredientOptionBlock")
    ]
    assert 'card.className = "recipe-edit-alternative-card";' in card_markup
    assert 'card.dataset.ingredientOptionBlock = "";' in card_markup
    assert "const header = createRecipeIngredientOptionHeader({" in card_markup
    assert 'label: "ALTERNATIVE OPTION",' in card_markup
    assert 'menuKind: "alternative",' in card_markup
    assert "renderRecipeIngredientOptionBlock(card, {" in card_markup
    assert "header," in card_markup
    assert "ingredientContent: [editor]," in card_markup
    assert "trailing: [footer]," in card_markup
    assert "recipe-edit-ingredient-option-divider" in shared_header
    assert 'label.dataset.ingredientOptionDividerLabel = "";' in shared_header
    assert "recipe-edit-alternative-components" in card_markup
    assert "Add ingredient to this option" in card_markup
    assert "Add another replacement ingredient" not in card_markup
    assert "Edit option" in shared_header
    assert "Duplicate option" in shared_header
    assert "Move option up" in shared_header
    assert "Use this option" in shared_header
    assert "Remove option" in shared_header
    assert "Save option" in card_markup
    assert ">Cancel</button>" in card_markup
    assert "recipe-edit-alternative-relationship" not in card_markup
    assert "recipe-edit-alternative-equivalency" not in card_markup
    assert "recipe-edit-alternative-explanation-block" not in card_markup

    v45 = css[css.index("/* Ingredient editor v45:"):]
    assert ".recipe-edit-ingredient-option-divider" in v45
    assert ".recipe-edit-alternative-component-summary" in v45
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid);" in v45
    assert ".recipe-edit-alternative-component-status" in v45
    assert ".recipe-edit-alternative-component-size" in v45
    assert ".recipe-edit-alternative-component-actions" in v45
    assert ".recipe-edit-ingredient-option-group::before" in v45
    assert ".recipe-edit-alternative-relationship" in v45
    assert "display: none !important;" in v45
    assert "@media (max-width: 767px)" in v45


def test_recipe_editor_v46_aligns_expanded_options_to_the_shared_table_grid():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    v46 = css[css.index("/* Ingredient editor v46:"):]

    assert css.index("/* Ingredient editor v46:") > css.index("/* Ingredient editor v45:")
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in v46
    assert ".recipe-edit-ingredient-option-divider," in v46
    assert ".recipe-edit-alternative-component-summary," in v46
    assert ".recipe-edit-alternative-component-edit-grid," in v46
    assert "width: 100%;" in v46
    assert "min-width: 0;" in v46
    assert "max-width: 100%;" in v46
    assert "overflow-x: visible;" in v46
    assert "transform: none;" in v46
    assert "padding-left: 14px;" in v46
    assert "text-overflow: ellipsis;" in v46
    assert "grid-column: 11;" in v46
    assert "grid-column: 8 !important;" in v46
    assert "@container recipe-ingredient-table (max-width: 859px)" in v46
    assert "margin-left:" not in v46

    assert 'data-ingredient-grid-column="ingredient"' in script
    assert 'data-ingredient-grid-column="actions"' in script
    assert 'identity.dataset.ingredientGridColumn = "ingredient";' in script
    assert 'field.dataset.ingredientGridColumn = column;' in script
    assert 'sourceDetails.dataset.ingredientGridColumn = "ingredient";' in script
    assert "fitRecipeEditIngredientColumnWidthsToBudget(" in script
    assert "recipeEditIngredientColumnWidthBudget(tableScroll" in script
    assert "recipeEditIngredientColumnGrid(renderedLayout, gap)" in script


def test_recipe_editor_v10_prioritizes_six_readable_groups_and_overflow_menu():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    assert css.index("/* Ingredient editor v10:") > css.index("/* Ingredient editor v9:")
    v10_start = css.index("/* Ingredient editor v10:")
    polish = css[v10_start:css.index("/* Ingredient editor v11:", v10_start)]

    assert "--recipe-edit-ingredient-grid:" in polish
    for priority in (
        "minmax(220px, 1.9fr)",
        "minmax(126px, .85fr)",
        "126px",
        "40px",
    ):
        assert priority in polish
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in polish
    assert "overflow-x: auto;" in polish
    assert ".recipe-edit-ingredient-read-cell" in polish
    assert ".recipe-edit-ingredient-quantity-summary" in polish
    assert ".recipe-edit-ingredient-store-summary" in polish
    assert ".recipe-edit-ingredient-type-summary" in polish
    assert ".recipe-edit-ingredient-substitution-cell" in polish
    assert ".recipe-edit-compact-row-actions" in polish
    assert "min-width: 826px;" in polish
    assert "min-height: 68px !important;" in polish
    assert "container-name: recipe-ingredient-table;" in polish
    assert "@container recipe-ingredient-table (max-width: 859px)" in polish
    assert "position: sticky" not in polish

    assert "function toggleRecipeIngredientSubstitutions(button, event = null)" in script
    assert "function setRecipeIngredientSubstitutionsExpanded(row, control, shouldOpen, options = {})" in script
    assert "String(recipeIngredientExpansionIsOpen(row, optionsButton))" in script
    assert 'row.classList.toggle("recipe-edit-substitutions-open", anchor === row);' in script
    assert 'const isIngredientRow = label === "ingredient";' in script
    assert 'const editButtonHtml = `' in script
    assert 'const editButtonHtml = isIngredientRow ? "" :' not in script
    assert 'row.removeAttribute("tabindex");' in script
    assert 'row.removeAttribute("aria-label");' in script
    assert 'editButton.setAttribute("aria-label", `Edit ${accessibleName}`);' in script
    assert 'actions.appendChild(menuWrap);' in script
    assert 'class="recipe-edit-compact-row-delete"' in script
    assert '${menuInActions ? "" : `<button type="button"' in script


def test_recipe_editor_replacement_rows_edit_and_duplicate_without_new_save_plumbing():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    card_lookup = script[
        script.index("function recipeIngredientAlternativeCardFromControl"):
        script.index("function recipeIngredientAlternativeComponentFromControl")
    ]
    assert "recipeIngredientAlternativeComponentFromControl(control)" in card_lookup
    assert 'optionRow.closest(".recipe-edit-alternative-card")' in card_lookup

    component_lookup = script[
        script.index("function recipeIngredientAlternativeComponentFromControl"):
        script.index("function recipeIngredientSubstitutionConfidencePercent")
    ]
    assert 'control.closest("[data-substitution-option-row]")' in component_lookup
    assert "menu.recipeEditAnchorButton" in component_lookup
    assert 'anchor.closest("[data-substitution-option-row]")' in component_lookup

    edit_mode = script[
        script.index("function setRecipeIngredientAlternativeEditMode"):
        script.index("function replaceRecipeIngredientWithAlternativeCard")
    ]
    assert "options.activeComponent" in edit_mode
    assert 'optionRow.classList.toggle("is-component-editing"' in edit_mode
    assert 'editGrid.hidden = !shouldEdit || !editGrid.closest(".is-component-editing");' in edit_mode
    assert 'if (secondaryDetails && !shouldEdit) secondaryDetails.open = false;' in edit_mode
    assert "card.dataset.editSnapshot = JSON.stringify(snapshots);" in edit_mode

    component_edit = script[
        script.index("function editRecipeIngredientAlternativeComponent"):
        script.index("function editRecipeIngredientAlternativeNotes")
    ]
    assert "recipeIngredientAlternativeComponentFromControl(button)" in component_edit
    assert "{ activeComponent: optionRow }" in component_edit

    notes_edit = script[
        script.index("function editRecipeIngredientAlternativeNotes"):
        script.index("function setRecipeIngredientAlternativePreferred")
    ]
    assert 'notes.closest(".recipe-edit-alternative-source-details")' in notes_edit
    assert "secondaryDetails.open = true;" in notes_edit

    duplicate = script[
        script.index("function duplicateRecipeIngredientAlternativeComponent"):
        script.index("function addRecipeIngredientAlternativeComponent")
    ]
    assert 'id: ""' in duplicate
    assert 'substitution_id: ""' in duplicate
    assert "recipeIngredientAlternativeComponentFromControl(button)" in duplicate
    assert "alternative_id: alternativeId" in duplicate
    assert "recipeIngredientSubstitutionOptionRowHtml(" in duplicate
    assert "updateRecipeIngredientSubstitutionState(ingredientRow);" in duplicate
    assert "setRecipeIngredientAlternativeEditMode(updatedCard, true, { activeComponent: updatedDuplicate });" in duplicate
    assert "/api/" not in duplicate

    for start_marker, end_marker in (
        (
            "function removeRecipeIngredientAlternativeComponent(button)",
            "function moveRecipeIngredientAlternativeComponent(control, direction)",
        ),
        (
            "function moveRecipeIngredientAlternativeComponent(control, direction)",
            "function moveRecipeIngredientAlternative(control, direction)",
        ),
    ):
        action = script[
            script.index(start_marker):
            script.index(end_marker)
        ]
        assert "recipeIngredientAlternativeCardFromControl" in action
        assert "recipeIngredientAlternativeComponentFromControl" in action

    remove_component = script[
        script.index("function removeRecipeIngredientAlternativeComponent"):
        script.index("function moveRecipeIngredientAlternativeComponent")
    ]
    assert remove_component.index("closeRecipeEditRowMenus();") < (
        remove_component.index("optionRow.remove();")
    )


def test_recipe_editor_alternative_disclosure_opens_populated_and_empty_rows_inline():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organizer = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions", script.index("function organizeRecipeEditIngredientRow(row)"))
    ]
    toggle = script[
        script.index("function setRecipeIngredientSubstitutionsExpanded"):
        script.index("function updateRecipeIngredientSubstitutionState")
    ]
    state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert 'optionsButton.type = "button";' in organizer
    assert 'optionsButton.setAttribute("aria-expanded", "false");' in organizer
    assert 'optionsButton.setAttribute("aria-controls", substitutions.id);' in organizer
    assert 'optionsButton.setAttribute("aria-haspopup", "dialog");' not in organizer
    assert 'optionsButton.addEventListener("click"' in organizer
    assert 'substitutions.setAttribute("role", "region");' in organizer
    assert "row.appendChild(substitutions);" in organizer
    assert 'alternativesDialog = document.createElement("dialog")' not in organizer
    assert "<span data-ingredient-options-label>None</span>" in organizer
    options_button_markup = organizer[
        organizer.index("optionsButton.innerHTML"):
        organizer.index('optionsButton.addEventListener("click"')
    ]
    assert 'recipeEditSvgIcon("chevron-down")' in options_button_markup

    assert "!optionCount" not in toggle
    assert "resetRecipeIngredientExpansionMount(otherRow, otherContainer);" not in toggle
    assert "mountRecipeIngredientExpansion(row, container, control);" in toggle
    assert "container.hidden = false;" in toggle
    assert "resetRecipeIngredientExpansionMount(row, container);" in toggle
    assert 'row.classList.toggle("recipe-edit-substitutions-open", anchor === row);' in script
    assert "event.preventDefault();" in toggle
    assert "event.stopPropagation();" in toggle
    assert "function openRecipeIngredientAlternativesDialog" in toggle
    assert "container.scrollIntoView" not in toggle
    assert "function closeRecipeIngredientAlternativesDialog" in toggle
    assert "showModal" not in toggle

    assert "optionsButton.disabled = false;" in state
    assert '`${action} alternative groups for ${ingredientName}${tooltip}`' in state
    assert 'empty.hidden = optionRows.length !== 0;' in state
    assert 'addLabel.textContent = "Add another option to this ingredient group";' in state
    assert "No alternatives have been added." in script
    assert "Add a single replacement ingredient or a replacement made from multiple ingredients." in script
    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in state
    assert "const compactSummary = requirementChoiceSummary;" in state
    assert 'optionsButton.querySelector("[data-ingredient-options-summary]")' in state
    assert "recipeIngredientAlternativeRecommendation" in state
    assert "recipeIngredientSubstitutionConfidencePercent" in state
    assert "summary.hidden = !alternativeCount || !compactSummary.summary;" in state
    assert 'label.textContent += " · Selected";' not in state
    assert "label.textContent = selectedLabel;" not in state
    assert "ensureRecipeIngredientAlternativeCards(container)" in state
    assert "viewAll.hidden = true;" in state

    choice_overview = script[
        script.index("function ensureRecipeIngredientChoiceOverview"):
        script.index("function materializeRecipeIngredientDefaultOption")
    ]
    assert "alternativeGroups.length" in choice_overview
    assert 'row.classList.contains("is-editing")' in choice_overview
    assert "recipeIngredientExpansionIsOpen(row)" in choice_overview

    visible_count_css = css[css.index("/* Ingredient editor v61:"):]
    assert "@media (min-width: 768px)" in visible_count_css
    assert "> .recipe-edit-ingredient-options-copy" in visible_count_css
    assert "display: block !important;" in visible_count_css
    assert "[data-ingredient-options-summary]" in visible_count_css
    assert "display: none !important;" in visible_count_css

    editable_title = script[
        script.index("function resizeRecipeIngredientChoiceTitleInput"):
        script.index("function syncRecipeIngredientSelectedOptionLineItems")
    ]
    assert 'aria-label="Ingredient choice wording"' in editable_title
    assert 'recipeIngredientDirectField(row, "source_text")' in editable_title
    assert 'input.addEventListener("input"' in editable_title
    assert 'input.addEventListener("keydown"' in editable_title
    assert 'input.addEventListener("blur"' in editable_title
    assert "updateRecipeEditorDirtyState();" in editable_title
    assert "updateRecipeIngredientSubstitutionState(row, input);" in editable_title

    v44 = css[css.index("/* Ingredient editor v44:"):]
    assert ".recipe-edit-ingredient-options-panel:not([hidden])" in v44
    open_rule = v44[v44.index(".recipe-edit-ingredient-options-panel:not([hidden])"):]
    open_rule = open_rule[:open_rule.index("}")]
    assert "display: grid !important;" in open_rule
    assert "grid-column: 1 / -1 !important;" in v44
    assert ".recipe-edit-substitution-empty[hidden]" in css
    assert ".recipe-edit-ingredient-options-button:focus-visible" in css


def test_recipe_editor_renders_and_serializes_multi_ingredient_alternative_groups():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    rows = script[
        script.index("function recipeIngredientSubstitutionRows"):
        script.index("function recipeIngredientSubstitutionsText")
    ]
    row_html = script[
        script.index("function recipeIngredientSubstitutionOptionRowHtml"):
        script.index("function resizeRecipeIngredientNameField")
    ]
    collect = script[
        script.index("function collectRecipeIngredientSubstitutionRows"):
        script.index("function collectRecipeIngredientRows")
    ]

    assert "option.ingredients, option.components, option.replacements" in rows
    assert "alternative_id:" in rows
    assert "alternative_component_order:" in rows
    assert 'data-field="alternative_id"' in row_html
    assert 'data-field="alternative_order"' in row_html
    assert 'data-field="alternative_component_order"' in row_html
    assert "recipeIngredientSubstitutionGroups" in row_html
    assert "componentIndex" in row_html
    assert "recipeIngredientSubstitutionDomGroups(optionRows)" in collect
    assert "option.inferred = recipeIngredientInferredValue(option) === \"true\";" in collect

    groups = script[
        script.index("function recipeIngredientSubstitutionGroups"):
        script.index("function nextRecipeIngredientAlternativeId")
    ]
    assert 'const key = alternativeId ? `id:${alternativeId}` : `legacy:${rowIndex}`;' in groups


def test_recipe_editor_substitution_thumbnails_reuse_image_resolution_and_fallbacks():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    resolver_start = script.index("function recipeIngredientImageCandidateUrl")
    resolver_end = script.index("function recipeIngredientSubstitutionOptionRowHtml", resolver_start)
    resolver = script[resolver_start:resolver_end]
    assert "function recipeIngredientImageUrl(item = {})" in resolver
    for field in (
        "ingredient_image_url", "image_url", "thumbnail_url", "thumb_url",
        "matched_ingredient", "master_ingredient", "matched_master_ingredient",
    ):
        assert field in resolver
    assert "cookbookRecipeImageUrlFromRecord" in resolver

    row_start = script.index("function recipeIngredientSubstitutionOptionRowHtml")
    row_end = script.index("function recipeIngredientSubstitutionOptionsHtml", row_start)
    row = script[row_start:row_end]
    assert "recipeIngredientImageUrl(option)" in row
    assert 'recipeImageVariantUrl(optionImageUrl, "thumb")' in row
    assert "data-deferred-src" in row
    assert 'sizes="44px"' in row
    assert 'alt="${escapeAttribute(optionIngredientName)} ingredient"' in row
    assert 'onerror="handleRecipeIngredientThumbnailError(this)"' in row
    assert "data-substitution-image-fallback" in row
    assert 'recipeEditSvgIcon("image")' in row
    assert 'data-field="ingredient_image_url"' in row
    assert "recipeIngredientStoreSectionIconName" not in row

    polish = css[css.index("/* Ingredient editor v7:"):]
    assert ".recipe-edit-substitution-thumbnail img" in polish
    assert "object-fit: cover;" in polish
    assert ".recipe-edit-substitution-image-fallback[hidden]" in polish


def test_recipe_editor_alternative_editing_is_scoped_to_one_group_and_serializable():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    editing = script[
        script.index("function setRecipeIngredientAlternativeEditMode"):
        script.index("function updateRecipeIngredientSubstitutionState")
    ]
    assert 'card.closest("[data-ingredient-substitutions]")' in editing
    assert '.querySelectorAll(".recipe-edit-alternative-card.is-editing")' in editing
    assert ".map(optionRow => fieldValuesFromRow(optionRow))" in editing
    assert "components.querySelectorAll(\"[data-substitution-option-row]\").forEach(optionRow => optionRow.remove())" in editing
    assert "snapshots.forEach((values, componentIndex)" in editing
    assert "recipeIngredientSubstitutionOptionRowHtml(values, componentIndex" in editing
    assert 'card.classList.toggle("is-editing", Boolean(shouldEdit));' in editing
    assert "canonicalizeRecipeIngredientUnitControl(input, { allowCustom: true })" in editing
    assert "updateRecipeEditorDirtyState" in editing
    assert "alternativeId = nextRecipeIngredientAlternativeId();" in editing
    assert "existingRows.forEach(optionRow" in editing
    assert "alternative_id: alternativeId" in editing
    assert "componentIndex: existingRows.length" in editing
    assert "function editRecipeIngredientAlternativeComponent(button)" in editing
    assert "function setRecipeIngredientAlternativePreferred(button)" in editing
    assert "function duplicateRecipeIngredientAlternative(button)" in editing
    assert 'id: ""' in editing
    assert 'substitution_id: ""' in editing
    assert "card.after(template.content);" in editing
    assert "preferred: false" in editing
    assert 'window.confirm("Delete this replacement group and all of its ingredients?")' in editing
    assert 'card.querySelectorAll("[data-substitution-option-row]").forEach(optionRow => optionRow.remove());' in editing

    add_group = script[
        script.index("function addRecipeIngredientSubstitutionRow"):
        script.index("function removeRecipeIngredientSubstitutionRow")
    ]
    assert 'list.lastElementChild?.matches("[data-substitution-option-row]")' in add_group
    assert 'list.querySelector("[data-substitution-option-row]:last-child")' not in add_group

    collect = script[
        script.index("function collectRecipeIngredientSubstitutionRows"):
        script.index("function collectRecipeIngredientRows")
    ]
    assert "recipeIngredientSubstitutionDomGroups(optionRows)" in collect
    assert "alternative_id" in collect
    assert "alternative_order" in collect
    assert "alternative_component_order" in collect
    assert "preferred" in script
    assert "match_status" in script
    assert "quantity_text" in script

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-alternative-card:not(.is-editing)" in v10
    assert ".recipe-edit-alternative-card.is-editing" in v10
    assert ".recipe-edit-alternative-component-edit-grid" in v10
    assert ".recipe-edit-alternative-edit-footer" in v10
    assert ".recipe-edit-alternative-add-component" in v10

    v16 = css[css.index("/* Ingredient editor v16:"):]
    assert ".recipe-edit-alternative-card-type" in v16
    assert ".recipe-edit-alternative-component-actions" in v16
    assert ".recipe-edit-alternative-card-footer" in v16
    assert 'content: "+";' in v16
    assert "grid-template-columns: minmax(0, 1fr);" in v16
    assert "@media (max-width: 760px)" in v16


def test_recipe_editor_visible_ingredient_columns_are_inline_editors_with_read_status():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    status = script[
        script.index("function recipeIngredientReadStatusHtml"):
        script.index("function recipeIngredientEditableFieldSnapshot")
    ]
    assert "const statusLabels = {" in status
    assert '(pantryStaple ? "Pantry staple" : "Good match")' in status
    assert "recipe-edit-ingredient-read-match" in status
    assert "recipe-edit-ingredient-read-preparation" not in status
    assert "recipeIngredientBadgesHtml" not in status

    type_helpers = script[
        script.index("function recipeIngredientTypeValue"):
        script.index("function recipeIngredientPluralUnit")
    ]
    assert 'return "optional";' in type_helpers
    assert "if (!explicitType && optional)" in type_helpers
    assert 'recipeIngredientTypeKey(recipeIngredientTypeValue(values)) === "optional"' in type_helpers
    assert 'return builtIn ? builtIn.value : explicitType || "main";' in type_helpers
    assert 'return builtIn ? builtIn.label : value;' in type_helpers

    summary = script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    organize = script[
        script.index("function organizeRecipeEditIngredientRow"):
        script.index("function organizeRecipeEditCompactRowActions")
    ]
    binding = script[
        script.index("function bindRecipeIngredientInlineEditor"):
        script.index("function organizeRecipeEditIngredientRow")
    ]
    store_trigger_sync = script[
        script.index("function syncRecipeIngredientStoreSectionTrigger"):
        script.index("function createRecipeIngredientStoreSectionTrigger")
    ]
    inline_control_factory = script[
        script.index("function appendRecipeIngredientInlineSummaryControl"):
        script.index("function createRecipeIngredientOptionRowSummary")
    ]
    shared_visible_cells = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function appendRecipeIngredientInlineSummaryControl")
    ]
    for field_name in ("ingredient", "preparation", "purchasable_item", "quantity", "unit", "store_section", "section"):
        assert f'data-recipe-ingredient-inline-field="{field_name}"' in shared_visible_cells or (
            f'control.dataset.recipeIngredientInlineField = fieldName' in organize
            and f'"{field_name}"' in organize
        )
    for label in ("Ingredient", "Preparation", "Buy As", "Quantity", "Unit", "Store Section", "Type"):
        assert (
            f'aria-label="{label}"' in shared_visible_cells
            or f'"{label}"' in organize
            or f'"{label}"' in inline_control_factory
        )
    assert 'class="recipe-edit-ingredient-read-details"' in shared_visible_cells
    assert 'class="recipe-edit-ingredient-inline-control recipe-edit-ingredient-inline-preparation"' in shared_visible_cells
    assert 'class="recipe-edit-ingredient-inline-control recipe-edit-ingredient-inline-buy-as"' in shared_visible_cells
    assert 'placeholder="Add preparation"' in shared_visible_cells
    assert 'placeholder="Add buy as"' in shared_visible_cells
    assert "appendRecipeIngredientInlineSummaryControl(summary, fieldName, tagName);" in organize
    assert 'control.className = "recipe-edit-ingredient-inline-control";' in inline_control_factory
    assert "control.dataset.recipeIngredientInlineField = fieldName;" in inline_control_factory
    assert 'control.setAttribute("list", "recipeIngredientUnitOptions");' in inline_control_factory
    assert '"recipe-edit-unit-chevron recipe-edit-inline-picker-chevron"' in inline_control_factory
    assert "function recipeIngredientInlineEditorSourceRow(control, fallbackRow)" in script
    assert 'control?.closest("[data-substitution-option-row]")' in script
    assert "recipeIngredientProjectedOptionSourceRow(control)" in script
    assert "fallbackRow?.recipeIngredientInlineSummarySourceRow" in script
    assert "const sourceRow = recipeIngredientInlineEditorSourceRow(control, row);" in binding
    assert "const source = recipeIngredientDirectField(sourceRow, fieldName);" in binding
    assert 'source.dispatchEvent(new Event(eventName, { bubbles: true }));' in binding
    assert 'control.tagName === "SELECT"' in binding
    assert 'control.replaceChildren(...[...source.options].map(option => option.cloneNode(true)));' in script
    assert 'bindRecipeIngredientUnitPickerTrigger(control);' in binding
    assert "function bindRecipeIngredientUnitPickerTrigger(input)" in script
    assert 'input.removeAttribute("list");' in script
    assert 'openRecipeIngredientUnitPicker(input, { showAll: true })' in script
    assert "const source = trigger.recipeEditStoreSectionSelect;" in store_trigger_sync
    assert "trigger.disabled = Boolean(source?.disabled);" in store_trigger_sync
    assert '"aria-invalid", "data-recipe-edit-validation-invalid"' in store_trigger_sync
    assert "trigger.removeAttribute(attribute);" in store_trigger_sync
    assert "syncRecipeIngredientInlineEditor(row)" in summary
    assert "readStatus.innerHTML = recipeIngredientReadStatusHtml(matchItem)" in summary
    assert 'const buyAsValue = String(values.purchasable_item || values.buy_as || "").trim();' in summary
    assert "meaningfulBuyAs = recipeIngredientMeaningfulBuyAs(values)" in summary
    assert 'readBuyAs.closest(".recipe-edit-ingredient-read-buy-as")' in summary
    assert "readBuyAsField.hidden = !meaningfulBuyAs;" in summary
    assert 'readCell.querySelector(":scope > [data-ingredient-read-optional]")' in summary
    assert "readOptional.hidden = !recipeIngredientIsOptional(values);" in summary
    assert "readBuyAs.value = buyAsValue;" in summary
    assert 'readBuyAs.title = meaningfulBuyAs ? `Buy as: ${meaningfulBuyAs}` : "Buy As matches Ingredient Name";' in summary
    assert "previewBuyAs.hidden = !modalBuyAs;" in summary
    assert "quantitySummary.textContent" not in summary
    assert "unitSummary.textContent" not in summary
    assert "preparationSummary" not in summary
    assert "buyAsSummary" not in summary
    assert "const typeLabel = recipeIngredientTypeLabel(values)" in summary
    assert "typeSummary.textContent = typeLabel" not in summary

    v10 = css[css.index("/* Ingredient editor v10:"):]
    hidden_status_start = v10.index(".recipe-edit-ingredient-role-summary")
    hidden_status_end = v10.index("}", hidden_status_start)
    assert ".recipe-edit-ingredient-badges" in v10[hidden_status_start:hidden_status_end]
    assert "display: none !important;" in v10[hidden_status_start:hidden_status_end]
    assert ".recipe-edit-ingredient-edit-support > .recipe-edit-ingredient-legacy-optional" in v10
    assert ".recipe-edit-ingredient-type-summary.is-optional" in v10
    v20 = css[css.index("/* Ingredient editor v20:"):]
    assert ".recipe-edit-ingredient-inline-control" in v20
    assert ".recipe-edit-ingredient-inline-control:focus" in v20
    inline_control_rule = v20[
        v20.index(
            "body.recipe-edit-standalone-page .recipe-edit-ingredient-inline-control {"
        ):
    ]
    inline_control_rule = inline_control_rule[:inline_control_rule.index("}")]
    assert "border: 1px solid transparent;" in inline_control_rule
    assert "background: transparent;" in inline_control_rule
    assert (
        "#recipeEditIngredients > .recipe-edit-ingredient-row:hover "
        ".recipe-edit-ingredient-inline-control"
    ) not in v20
    store_trigger_rule = v20[
        v20.index(
            "body.recipe-edit-standalone-page #recipeEditIngredients\n"
            "    .recipe-edit-ingredient-store-summary\n"
            "    > .recipe-edit-store-section-trigger {"
        ):
    ]
    store_trigger_rule = store_trigger_rule[:store_trigger_rule.index("}")]
    assert "#recipeEditIngredients" in store_trigger_rule
    assert ".recipe-edit-ingredient-store-summary" in store_trigger_rule
    assert "> .recipe-edit-ingredient-row" not in store_trigger_rule
    assert "border: 1px solid transparent;" in store_trigger_rule
    assert "background: transparent;" in store_trigger_rule
    assert "box-shadow: none;" in store_trigger_rule
    assert "transition: border-color 120ms ease" in store_trigger_rule
    store_trigger_hover = v20[
        v20.index(
            "body.recipe-edit-standalone-page #recipeEditIngredients\n"
            "    .recipe-edit-ingredient-store-summary\n"
            "    > .recipe-edit-store-section-trigger:not("
        ):
    ]
    store_trigger_hover = store_trigger_hover[:store_trigger_hover.index("}")]
    assert '[aria-expanded="true"]' in store_trigger_hover
    assert '[aria-invalid="true"]' in store_trigger_hover
    assert "border-color: var(--app-border-strong);" in store_trigger_hover
    assert "background-color: var(--app-bg-soft);" in store_trigger_hover
    assert "box-shadow: none;" in store_trigger_hover
    store_trigger_active_start = v20.index(
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-ingredient-store-summary\n"
        "    > .recipe-edit-store-section-trigger:not(",
        v20.index(
            "body.recipe-edit-standalone-page #recipeEditIngredients\n"
            "    .recipe-edit-ingredient-store-summary\n"
            "    > .recipe-edit-store-section-trigger:not("
        ) + 1,
    )
    store_trigger_active = v20[store_trigger_active_start:]
    store_trigger_active = store_trigger_active[:store_trigger_active.index("}")]
    assert ':is(:focus-visible, [aria-expanded="true"])' in store_trigger_active
    assert ":focus," not in store_trigger_active
    assert "border-color: var(--app-primary-hover);" in store_trigger_active
    assert "background-color: var(--app-surface);" in store_trigger_active
    assert "color-mix(in srgb, var(--app-primary-hover) 22%" in store_trigger_active
    store_trigger_invalid_start = v20.index(
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-ingredient-store-summary\n"
        "    > .recipe-edit-store-section-trigger:is("
    )
    store_trigger_invalid = v20[store_trigger_invalid_start:]
    store_trigger_invalid = store_trigger_invalid[:store_trigger_invalid.index("}")]
    assert '[aria-invalid="true"]' in store_trigger_invalid
    assert "border-color: var(--app-danger, #ef4444);" in store_trigger_invalid
    assert "background" not in store_trigger_invalid
    assert "box-shadow" not in store_trigger_invalid
    read_cell_rule = v20[v20.index("body.recipe-edit-standalone-page .recipe-edit-ingredient-read-cell {"):]
    read_cell_rule = read_cell_rule[:read_cell_rule.index("}")]
    assert "gap: 0;" in read_cell_rule
    preparation_rule = v20[v20.index("body.recipe-edit-standalone-page .recipe-edit-ingredient-inline-preparation {"):]
    preparation_rule = preparation_rule[:preparation_rule.index("}")]
    assert "padding: 0 7px;" in preparation_rule
    buy_as_rule = v20[v20.index("body.recipe-edit-standalone-page .recipe-edit-ingredient-read-buy-as {"):]
    buy_as_rule = buy_as_rule[:buy_as_rule.index("}")]
    assert "box-sizing: border-box;" in buy_as_rule
    assert "width: 100%;" in buy_as_rule
    assert "padding-inline: 7px;" in buy_as_rule
    compact_buy_as = css[css.index("/* Ingredient editor v25:"):]
    assert css.index("/* Ingredient editor v25:") > css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-inline-control:focus"
    )
    compact_buy_as_input = compact_buy_as[
        compact_buy_as.index(
            ".recipe-edit-ingredient-read-buy-as > .recipe-edit-ingredient-inline-buy-as {"
        ):
    ]
    compact_buy_as_input = compact_buy_as_input[:compact_buy_as_input.index("}")]
    compact_buy_as_layout = compact_buy_as[
        compact_buy_as.index("body.recipe-edit-standalone-page .recipe-edit-ingredient-read-buy-as {"):
    ]
    compact_buy_as_layout = compact_buy_as_layout[:compact_buy_as_layout.index("}")]
    assert "display: grid !important;" in compact_buy_as_layout
    assert "grid-template-columns: max-content minmax(0, 1fr);" in compact_buy_as_layout
    compact_buy_as_hidden = compact_buy_as[
        compact_buy_as.index(
            "body.recipe-edit-standalone-page .recipe-edit-ingredient-read-buy-as[hidden] {"
        ):
    ]
    compact_buy_as_hidden = compact_buy_as_hidden[:compact_buy_as_hidden.index("}")]
    assert "display: none !important;" in compact_buy_as_hidden
    compact_buy_as_label = compact_buy_as[
        compact_buy_as.index(".recipe-edit-ingredient-read-buy-as > span {"):
    ]
    compact_buy_as_label = compact_buy_as_label[:compact_buy_as_label.index("}")]
    assert "grid-column: 1;" in compact_buy_as_label
    assert "grid-row: 1;" in compact_buy_as_label
    assert "height: 16px !important;" in compact_buy_as_input
    assert "grid-column: 2 !important;" in compact_buy_as_input
    assert "grid-row: 1 !important;" in compact_buy_as_input
    assert "width: 100% !important;" in compact_buy_as_input
    assert "width: 0 !important;" not in compact_buy_as_input
    assert "border: 0 !important;" in compact_buy_as_input
    assert "background: transparent !important;" in compact_buy_as_input
    assert "color: var(--app-muted);" in compact_buy_as_input
    assert "font-size: 10px !important;" in compact_buy_as_input
    alternatives_cell_rule = v20[v20.index(
        "body.recipe-edit-standalone-page #recipeEditIngredients > .recipe-edit-ingredient-row > "
        ".recipe-edit-ingredient-substitution-cell {"
    ):]
    alternatives_cell_rule = alternatives_cell_rule[:alternatives_cell_rule.index("}")]
    assert "display: flex;" in alternatives_cell_rule
    assert "height: 32px;" in alternatives_cell_rule
    assert "align-items: center;" in alternatives_cell_rule
    assert "align-self: center;" in alternatives_cell_rule
    assert "min-height: 32px;" in alternatives_cell_rule
    assert "margin: 0;" in alternatives_cell_rule
    alternatives_button_rule = v20[v20.index(
        "body.recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-ingredient-options-button {"
    ):]
    alternatives_button_rule = alternatives_button_rule[:alternatives_button_rule.index("}")]
    assert "box-sizing: border-box;" in alternatives_button_rule
    assert "align-items: center;" in alternatives_button_rule
    assert "height: 32px;" in alternatives_button_rule
    assert "min-height: 32px;" in alternatives_button_rule
    assert "margin: 0;" in alternatives_button_rule
    for summary_class in (
        "recipe-edit-ingredient-quantity-summary",
        "recipe-edit-ingredient-unit-summary",
        "recipe-edit-ingredient-size-summary",
    ):
        idle_selector = f"#recipeEditIngredients > .recipe-edit-ingredient-row .{summary_class} > .recipe-edit-ingredient-inline-control:not(:hover):not(:focus)"
        idle_rule = v20[v20.index(idle_selector):]
        idle_rule = idle_rule[:idle_rule.index("}")]
        assert ':not([aria-expanded="true"])' in idle_rule
        assert ':not([aria-invalid="true"])' in idle_rule
        assert "border-color: transparent;" in idle_rule
        assert "background: transparent;" in idle_rule
        hover_selector = f"#recipeEditIngredients > .recipe-edit-ingredient-row .{summary_class} > .recipe-edit-ingredient-inline-control:hover"
        hover_rule = v20[v20.index(hover_selector):]
        hover_rule = hover_rule[:hover_rule.index("}")]
        assert "border-color: var(--app-border-strong);" in hover_rule
        assert "background: var(--app-bg-soft);" in hover_rule
    ingredient_idle_selector = ".recipe-edit-ingredient-read-cell > .recipe-edit-ingredient-inline-name:not(:hover):not(:focus)"
    ingredient_idle_rule = v20[v20.index(ingredient_idle_selector):]
    ingredient_idle_rule = ingredient_idle_rule[:ingredient_idle_rule.index("}")]
    assert ':not([aria-invalid="true"])' in ingredient_idle_rule
    assert "border-color: transparent;" in ingredient_idle_rule
    assert "background: transparent;" in ingredient_idle_rule
    ingredient_hover_selector = ".recipe-edit-ingredient-read-cell > .recipe-edit-ingredient-inline-name:hover"
    ingredient_hover_rule = v20[v20.index(ingredient_hover_selector):]
    ingredient_hover_rule = ingredient_hover_rule[:ingredient_hover_rule.index("}")]
    assert "border-color: var(--app-border-strong);" in ingredient_hover_rule
    assert "background: var(--app-bg-soft);" in ingredient_hover_rule
    preparation_idle_selector = ".recipe-edit-ingredient-read-details > .recipe-edit-ingredient-inline-preparation:not(:hover):not(:focus)"
    preparation_idle_rule = v20[v20.index(preparation_idle_selector):]
    preparation_idle_rule = preparation_idle_rule[:preparation_idle_rule.index("}")]
    assert ':not([aria-invalid="true"])' in preparation_idle_rule
    assert "border-color: transparent;" in preparation_idle_rule
    assert "background: transparent;" in preparation_idle_rule
    preparation_hover_selector = ".recipe-edit-ingredient-read-details > .recipe-edit-ingredient-inline-preparation:hover"
    preparation_hover_rule = v20[v20.index(preparation_hover_selector):]
    preparation_hover_rule = preparation_hover_rule[:preparation_hover_rule.index("}")]
    assert "border-color: var(--app-border-strong);" in preparation_hover_rule
    assert "background: var(--app-bg-soft);" in preparation_hover_rule
    assert "width: 100%;" in v20


def test_recipe_editor_secondary_metadata_normalizes_buy_as_for_summaries():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    comparison = script[
        script.index("function recipeIngredientComparableText"):
        script.index("function recipeIngredientReadStatusHtml")
    ]
    assert '.normalize("NFKD")' in comparison
    assert ".toLowerCase()" in comparison
    assert ".replace(/[^a-z0-9]+/g, \" \")" in comparison
    assert "recipeIngredientComparableText(ingredient) === recipeIngredientComparableText(buyAs)" in comparison
    assert "recipeIngredientViewNamesDifferOnlyByCount(ingredient, buyAs)" in comparison
    assert 'return "";' in comparison

    summary = script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    assert 'previewBuyAs.textContent = modalBuyAs ? `Buy as: ${modalBuyAs}` : "";' in summary
    assert "previewBuyAs.hidden = !modalBuyAs;" in summary
    assert "readBuyAsField.hidden = !meaningfulBuyAs;" in summary
    assert 'data-recipe-ingredient-inline-field="purchasable_item"' in script
    assert "recipeIngredientReadStatusHtml(matchItem)" in summary

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-ingredient-read-buy-as > .recipe-edit-ingredient-inline-buy-as" in v10
    assert ".recipe-edit-ingredient-read-separator" in v10


def test_mobile_compact_ingredient_summaries_show_preparation_and_hide_redundant_buy_as():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    summary = script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    option_summary = script[
        script.index("function updateRecipeIngredientOptionRowSummary"):
        script.index("function updateRecipeIngredientAlternativeComponentSummary")
    ]
    mobile_preparation = css[css.index("/* Ingredient editor v90:"):]

    assert ":scope > .recipe-edit-ingredient-mobile-header > .recipe-edit-ingredient-read-cell" in summary
    assert 'readDetails.classList.toggle("has-preparation", Boolean(preparationValue));' in summary
    assert 'preparationDetails.classList.toggle("has-preparation", Boolean(preparation));' in option_summary
    assert ".recipe-edit-ingredient-read-details.has-preparation" in mobile_preparation
    assert ".recipe-edit-selected-option-line-item" in mobile_preparation
    assert "display: flex !important;" in mobile_preparation
    assert 'content: "\\00b7";' in mobile_preparation


def test_recipe_editor_compact_alternative_cards_keep_inline_adds_out_of_expanded_mode():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    editing = script[
        script.index("function setRecipeIngredientAlternativeEditMode"):
        script.index("function replaceRecipeIngredientWithAlternativeCard")
    ]
    state = script[
        script.index("function updateRecipeIngredientSubstitutionState"):
        script.index("function addRecipeIngredientSubstitutionRow")
    ]

    assert "dataset.newAlternative" not in script
    assert 'card.querySelectorAll("[data-substitution-option-row]").forEach(optionRow => optionRow.remove());' not in editing
    assert 'list.hidden = optionRows.length === 0;' in state
    assert 'addLabel.textContent = "Add another option to this ingredient group";' in state
    assert "viewAll.hidden = true;" in state

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-alternative-card.is-single-alternative:not(.is-editing)" in v10
    assert "min-height: 74px;" in v10
    assert ".recipe-edit-substitution-list[hidden]" in v10


def test_recipe_editor_alternative_cancel_preserves_false_normalization_flags():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    option_markup = script[
        script.index("function recipeIngredientSubstitutionOptionRowHtml"):
        script.index("function recipeIngredientSubstitutionOptionsHtml")
    ]
    ingredient_markup = script[
        script.index("function addRecipeIngredientRow"):
        script.index("function bindRecipeIngredientSummaryUpdates")
    ]

    for scope, value_name in ((option_markup, "option"), (ingredient_markup, "item")):
        for field in ("unit_review_required", "unit_custom", "store_section_custom"):
            assert f"recipeIngredientMatchFlag({value_name}.{field})" in scope
            assert f"{value_name}.{field} ? \"true\" : \"false\"" not in scope


def test_recipe_editor_multi_ingredient_alternative_uses_one_preferred_control():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    card = script[
        script.index("function updateRecipeIngredientAlternativeCard"):
        script.index("function createRecipeIngredientAlternativeCard")
    ]
    markup = script[
        script.index("function createRecipeIngredientAlternativeCard"):
        script.index("function ensureRecipeIngredientAlternativeCards")
    ]
    binding = script[
        script.index("function bindRecipeIngredientSubstitutionRow"):
        script.index("function recipeIngredientOptionsMenuForRow")
    ]

    assert "const preferredInputs = rows" in card
    assert 'labelElement.hidden = index > 0;' in card
    assert 'input.dataset.alternativePreferredBound' not in card
    assert 'input.dataset.field === "preferred"' in binding
    assert 'card?.querySelectorAll(\'[data-field="preferred"]\')' in binding
    assert "preferredInput.checked = input.checked;" in binding
    assert binding.index('input.dataset.field === "preferred"') < binding.index("updateRecipeIngredientSubstitutionRowSummary(optionRow)")
    assert "Add another replacement ingredient" not in markup
    assert ">Add ingredient to this option</span>" in markup


def test_recipe_editor_compact_table_responsive_priority_keeps_critical_columns():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    v10 = css[css.index("/* Ingredient editor v10:"):]
    narrow = v10[v10.index("@container recipe-ingredient-table (max-width: 859px)"):]
    narrow = narrow[:narrow.index("@media (max-width: 760px)")]

    assert ".recipe-edit-ingredient-store-summary" in narrow
    assert "display: none !important;" in narrow
    for critical in (
        ".recipe-edit-ingredient-type-summary",
        ".recipe-edit-ingredient-substitution-cell",
        ".recipe-edit-compact-row-actions",
    ):
        assert critical in narrow
    assert ".recipe-edit-ingredient-read-cell" not in narrow
    assert ".recipe-edit-ingredient-quantity-summary" not in narrow
    assert "box-sizing: border-box;" in v10
    assert "grid-template-rows: minmax(52px, auto) auto auto;" in v10
    assert "row-gap: 0 !important;" in v10
    assert "padding-inline: 14px;" in v10
    assert ".recipe-edit-alternative-component-edit-grid > .recipe-edit-alternative-edit-field" in v10
    assert ".recipe-edit-alternative-component-edit-grid > .recipe-edit-alternative-component-remove" in v10
    mobile = v10[v10.index("@media (max-width: 760px)"):]
    assert "grid-template-rows: repeat(6, auto);" in mobile
    assert ".recipe-ingredient-image-panel.recipe-image-tools-visible" in mobile
    assert "grid-row: 6 !important;" in mobile
    assert ".recipe-edit-alternative-card.is-single-alternative:not(.is-editing)" in mobile

    modal = css[css.index("/* Ingredient editor v12:"):]
    dialog_rule = modal[modal.index("dialog.recipe-edit-ingredient-edit-panel {"):]
    dialog_rule = dialog_rule[:dialog_rule.index("}")]
    assert "width: 90vw;" in dialog_rule
    assert "max-width: 90vw;" in dialog_rule
    assert "height: min(90dvh, 860px);" in dialog_rule
    assert "max-height: 90dvh;" in dialog_rule
    assert "overflow: hidden;" in dialog_rule
    assert ".recipe-edit-ingredient-modal-body" in modal
    assert "overflow: auto;" in modal
    assert ".recipe-edit-ingredient-modal-header" in modal
    assert ".recipe-edit-ingredient-modal-footer" in modal
    assert modal.count("position: sticky;") >= 2
    assert "grid-template-columns: minmax(260px, 1.35fr) minmax(260px, 1fr) minmax(164px, 190px);" in modal
    assert "grid-template-columns: repeat(2, minmax(260px, 1fr));" in modal
    assert "min-width: 240px !important;" in modal

    tablet = modal[modal.index("@media (max-width: 860px)"):modal.index("@media (max-width: 760px)")]
    assert ".recipe-edit-ingredient-modal-identity-grid" in tablet
    assert ".recipe-edit-ingredient-modal-field-grid" in tablet
    assert "grid-template-columns: minmax(0, 1fr);" in tablet
    assert "min-width: 0 !important;" in tablet

    modal_mobile = modal[modal.index("@media (max-width: 760px)"):]
    for dimension in ("width: 100vw;", "max-width: 100vw;", "height: 100dvh;", "max-height: 100dvh;"):
        assert dimension in modal_mobile
    assert "border-radius: 0;" in modal_mobile
    assert "overflow-x: hidden;" in modal_mobile
    assert "grid-template-columns: minmax(0, 1fr);" in modal_mobile
    assert "min-height: 44px;" in modal_mobile

    assert css.index("/* Ingredient editor v12:") > css.index("/* Instruction editor v2:")


def test_recipe_editor_store_section_picker_shows_icons_and_preserves_select_value():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "function ensureRecipeIngredientStoreSectionMenu()" in script
    assert 'menu.id = "recipeIngredientStoreSectionMenu";' in script
    assert 'menu.setAttribute("role", "listbox");' in script
    assert 'class="recipe-edit-store-section-option${selected ? " is-selected" : ""}"' in script
    assert "${recipeIngredientStoreSectionIconHtml(value)}" in script
    assert 'role="option"' in script
    assert "function chooseRecipeIngredientStoreSection(button)" in script
    assert 'select.value = button.dataset.storeSectionValue || "";' in script
    assert 'select.dispatchEvent(new Event("change", { bubbles: true }));' in script
    store_section_open = script[
        script.index("function openRecipeIngredientStoreSectionMenu(trigger)"):
        script.index("function chooseRecipeIngredientStoreSection(button)")
    ]
    assert store_section_open.index("positionRecipeEditPopupMenu(menu, trigger);") < (
        store_section_open.index(
            "setRecipeEditListboxActiveOption(menu, Number(menu.dataset.activeIndex || 0));"
        )
    )
    assert "const configured = recipeEditStoreSectionDetails.get(" in script
    assert "if (configured && !recipeIngredientMatchFlag(configured.is_builtin))" in script
    assert 'const RECIPE_INGREDIENT_CUSTOM_STORE_SECTIONS_KEY = "recipeIngredientCustomStoreSections";' in script
    assert "function saveRecipeIngredientCustomStoreSectionName(value)" in script
    assert "function addRecipeIngredientCustomStoreSection(button)" in script
    assert "function editRecipeIngredientCustomStoreSection(button)" in script
    assert "function deleteRecipeIngredientCustomStoreSection(button)" in script
    assert "const values = customNames.map(value => ({ value, custom: true }));" in script
    assert 'data-field="store_section_custom"' in script
    assert "recipe-edit-store-section-menu-list" in script
    assert "recipe-edit-store-section-menu-footer" in script
    assert "Add custom section…" in script
    assert "Manage Store Sections…" in script
    assert 'masterDataViewerUrl("/admin/master-data/store-sections")' in script
    assert 'href="/admin/master-data/store-sections"' not in script
    assert 'target="_blank"' in script
    assert 'rel="noopener"' in script
    assert 'aria-label="Manage Store Sections in a new tab"' in script
    assert "if (!custom)" in script
    assert "function bindRecipeIngredientStoreSectionControls(scope)" in script
    assert "function createRecipeIngredientStoreSectionTrigger(select)" in script
    assert "function ensureRecipeIngredientInlineStoreSectionTrigger(control, source)" in script
    assert "trigger.recipeEditStoreSectionSelect = select;" in script
    assert "trigger && trigger.recipeEditStoreSectionSelect" in script
    assert "trigger.dataset.recipeIngredientInlineStoreSectionTrigger" in script
    assert "control.hidden = true;" in script
    assert 'trigger.setAttribute("role", "combobox");' in script
    assert 'select.hidden = true;' in script
    assert 'bindRecipeIngredientStoreSectionControls(row);' in script
    assert 'bindRecipeIngredientStoreSectionControls(optionRow);' in script
    assert "[data-recipe-edit-store-section-trigger]" in script
    for icon_name in (
        "fish", "snowflake", "package", "wheat", "sauce", "cookie",
        "cup", "bread", "sandwich", "home", "heart", "paw",
    ):
        assert f'{icon_name}:' in script

    assert ".recipe-edit-store-section-trigger" in css
    assert ".recipe-edit-row-menu.recipe-edit-store-section-menu" in css
    assert ".recipe-edit-store-section-option.is-selected" in css
    assert ".recipe-edit-store-section-option.is-active" in css
    assert ".recipe-edit-store-section-custom-row" in css
    assert ".recipe-edit-store-section-edit-button" in css
    assert ".recipe-edit-store-section-delete-button" in css
    assert ".recipe-edit-store-section-menu-footer" in css
    assert ".recipe-edit-store-section-manage-option" in css
    assert ".recipe-edit-ingredient-store-summary > .recipe-edit-store-section-trigger" in css
    assert ".recipe-edit-store-section-menu-list {\n    flex: 1 1 auto;" in css
    assert ".recipe-edit-store-section-icon.is-fish" in css
    assert ".recipe-edit-store-section-icon.is-paw" in css
    hidden_menu_start = css.index(".recipe-edit-row-menu[hidden] {")
    hidden_menu_rule = css[hidden_menu_start:css.index("}", hidden_menu_start)]
    assert "display: none !important;" in hidden_menu_rule

    chevron_start = css.index(
        ".recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-store-section-chevron {"
    )
    chevron_rule = css[chevron_start:css.index("}", chevron_start)]
    assert "opacity: 0;" in chevron_rule
    assert "transition: opacity 120ms ease;" in chevron_rule
    assert '.recipe-edit-store-section-trigger:is(:hover, :focus-visible, [aria-expanded="true"])' in css
    active_chevron_start = css.index(
        '.recipe-edit-store-section-trigger:is(:hover, :focus-visible, [aria-expanded="true"])'
    )
    active_chevron_rule = css[active_chevron_start:css.index("}", active_chevron_start)]
    assert "> .recipe-edit-store-section-chevron" in active_chevron_rule
    assert "opacity: 1;" in active_chevron_rule

    matching_type = css[css.index("/* Ingredient editor v30:"):]
    assert ".recipe-edit-ingredient-store-summary > .recipe-edit-store-section-trigger" in matching_type
    assert ".recipe-edit-ingredient-type-summary > .recipe-edit-type-trigger" in matching_type
    table_font_rule = matching_type[:matching_type.index("}")]
    assert "font: inherit;" in table_font_rule
    assert "line-height: 1.2;" in table_font_rule
    assert "letter-spacing: inherit;" in table_font_rule

    store_trigger_start = css.index(
        ".recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-store-section-trigger {"
    )
    store_trigger_rule = css[store_trigger_start:css.index("}", store_trigger_start)]
    assert "font: inherit;" in store_trigger_rule
    assert "font-size:" not in store_trigger_rule
    assert "font-weight:" not in store_trigger_rule

    mobile_store_start = css.index(
        "body.recipe-edit-standalone-page dialog.recipe-edit-ingredient-edit-panel .recipe-edit-store-section-trigger {",
        css.index("/* Use a calmer mobile type hierarchy and keep editable text phone-friendly. */"),
    )
    mobile_store_rule = css[mobile_store_start:css.index("}", mobile_store_start)]
    assert "font-size: 16px;" in mobile_store_rule
    assert "font-weight: 500;" in mobile_store_rule
    assert "line-height: 1.25;" in mobile_store_rule


def test_store_section_summary_icon_stays_inside_its_table_cell():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    broad_positioning_selector = (
        ".recipe-edit-standalone-page #recipeEditIngredients "
        ".recipe-edit-store-section-icon {"
    )
    edit_field_selector = (
        ".recipe-edit-standalone-page #recipeEditIngredients > .recipe-edit-ingredient-row > "
        ".recipe-edit-store-section-label .recipe-edit-store-section-icon {"
    )

    assert broad_positioning_selector not in css
    assert edit_field_selector in css
    assert "body.recipe-edit-standalone-page .recipe-edit-ingredient-store-summary .recipe-edit-store-section-icon {" in css

    summary_icon_size_start = css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-store-summary "
        ":is(.recipe-edit-inline-icon, svg) {"
    )
    summary_icon_size_end = css.index("\n}", summary_icon_size_start)
    summary_icon_size_rule = css[summary_icon_size_start:summary_icon_size_end]

    # The SVG must inherit the category color from its is-* icon wrapper.
    assert "color:" not in summary_icon_size_rule
    projected_icon_size_start = css.index(
        "body.recipe-edit-standalone-page .recipe-edit-alternative-component-store "
        ":is(.recipe-edit-inline-icon, svg) {",
    )
    projected_icon_size_end = css.index("\n}", projected_icon_size_start)
    projected_icon_size_rule = css[
        projected_icon_size_start:projected_icon_size_end
    ]
    assert "color:" not in projected_icon_size_rule
    for color_rule in (
        ".recipe-edit-store-section-icon.is-leaf { color: #4ade80; }",
        ".recipe-edit-store-section-icon.is-dairy { color: #60a5fa; }",
        ".recipe-edit-store-section-icon.is-can { color: #fb923c; }",
        ".recipe-edit-store-section-icon.is-jar { color: #f87171; }",
        ".recipe-edit-store-section-icon.is-oil { color: #fbbf24; }",
    ):
        assert color_rule in css

    badge_icon_start = css.index(
        ".store-section-badge > .recipe-edit-store-section-icon {",
    )
    badge_icon_end = css.index("\n}", badge_icon_start)
    badge_icon_rule = css[badge_icon_start:badge_icon_end]
    assert "--store-section-color: inherit !important;" in badge_icon_rule


def test_store_section_display_and_editor_keep_icon_and_label_aligned():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    display_component = (
        ROOT / "PushShoppingList/static/js/store-sections/StoreSectionDisplay.js"
    ).read_text(encoding="utf-8")

    badge_start = css.index(".store-section-badge {")
    badge_rule = css[badge_start:css.index("\n}", badge_start)]
    assert "gap: 8px;" in badge_rule

    display_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-ingredient-store-summary\n"
        "    > .store-section-display {"
    )
    display_start = css.index(display_selector)
    display_rule = css[display_start:css.index("\n}", display_start)]
    assert "> .recipe-edit-ingredient-row" not in display_rule
    assert "padding-inline: 3px;" in display_rule

    editor_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-ingredient-store-summary\n"
        "    > .store-section-editor-control {"
    )
    editor_start = css.index(editor_selector)
    editor_rule = css[editor_start:css.index("\n}", editor_start)]
    assert "> .recipe-edit-ingredient-row" not in editor_rule
    assert "gap: 8px;" in editor_rule
    assert "padding-inline: 3px;" in editor_rule
    assert "border-color: var(--app-primary-hover);" in editor_rule

    display_base_start = css.index(".store-section-display {")
    display_base_rule = css[display_base_start:css.index("\n}", display_base_start)]
    assert "border: 1px solid transparent;" in display_base_rule
    assert "border-radius: 6px;" in display_base_rule
    assert "opacity 120ms ease" not in display_base_rule
    hover_start = css.index(
        '.store-section-display:is(:hover, :focus-visible, [aria-expanded="true"]) {'
    )
    hover_rule = css[hover_start:css.index("\n}", hover_start)]
    assert "border-color: var(--app-primary-hover);" in hover_rule
    assert "background: var(--app-surface);" in hover_rule
    assert "box-shadow: 0 0 0 2px" in hover_rule

    editing_start = css.index(".is-store-section-editing > .store-section-display {")
    editing_rule = css[editing_start:css.index("\n}", editing_start)]
    assert "opacity: 0;" in editing_rule
    assert "transition: none;" in editing_rule

    entering_start = css.index(".store-section-editor-control.is-entering {")
    entering_rule = css[entering_start:css.index("\n}", entering_start)]
    assert "opacity: 1;" in entering_rule

    shared_label_selector = (
        "body.recipe-edit-standalone-page #recipeEditIngredients\n"
        "    .recipe-edit-ingredient-store-summary\n"
        "    :is(.store-section-badge-label, [data-store-section-trigger-label]) {"
    )
    shared_label_start = css.index(shared_label_selector)
    shared_label_rule = css[shared_label_start:css.index("\n}", shared_label_start)]
    assert "font: inherit;" in shared_label_rule
    assert "line-height: inherit;" in shared_label_rule
    assert "letter-spacing: inherit;" in shared_label_rule

    display_factory = script[
        script.index("function createRecipeIngredientStoreSectionDisplay(source = null)"):
        script.index("function recipeIngredientStoreSectionDisplaySource")
    ]
    assert 'indicatorHtml: recipeEditSvgIcon("chevron-down"),' in display_factory
    assert 'indicatorHtml: recipeEditSvgIcon("edit"),' not in display_factory
    assert 'display.dataset.recipeEditStoreSectionTrigger = "true";' in display_factory
    assert 'display.setAttribute("role", "combobox");' in display_factory
    assert 'display.setAttribute("aria-expanded", "false");' in display_factory
    assert "handleRecipeIngredientStoreSectionKeydown(event, display)" in display_factory

    inline_open = script[
        script.index("function startRecipeIngredientStoreSectionInlineEdit(display)"):
        script.index("function ensureRecipeIngredientInlineStoreSectionTrigger")
    ]
    assert "return openRecipeIngredientStoreSectionMenu(display);" in inline_open
    assert "StoreSectionEditor.mount" not in inline_open
    assert "createRecipeIngredientStoreSectionTrigger" not in inline_open
    assert 'class="store-section-display-chevron"' in display_component
    assert "store-section-display-edit-indicator" not in display_component


def test_compact_store_section_display_rebinds_when_the_selected_choice_changes():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    source_resolution = script[
        script.index("function recipeIngredientStoreSectionDisplaySource"):
        script.index("function syncRecipeIngredientStoreSectionDisplay")
    ]
    inline_sync = script[
        script.index("function syncRecipeIngredientInlineEditor"):
        script.index("function bindRecipeIngredientInlineEditor")
    ]
    inline_binding = script[
        script.index("function bindRecipeIngredientInlineEditor"):
        script.index("function bindRecipeIngredientNameField")
    ]

    dynamic_source = (
        'const sourceRow = recipeIngredientInlineEditorSourceRow(display, fallbackRow);'
    )
    cached_source = "if (display?.recipeEditStoreSectionSelect)"
    assert dynamic_source in source_resolution
    assert source_resolution.index(dynamic_source) < source_resolution.index(cached_source)
    assert "function bindRecipeIngredientStoreSectionDisplaySource" in source_resolution
    assert 'previousSource.removeEventListener("change", previousHandler);' in source_resolution
    assert 'source.addEventListener("change", syncDisplay);' in source_resolution
    assert "bindRecipeIngredientStoreSectionDisplaySource(display, source);" in inline_sync
    assert "bindRecipeIngredientStoreSectionDisplaySource(display, source);" in inline_binding


def test_master_ingredient_selection_batches_field_updates_before_one_summary_refresh():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    setter = script[
        script.index("function setRowFieldValue"):
        script.index("function recipeEditSvgIcon")
    ]
    selection = script[
        script.index("function chooseRecipeIngredientMasterOption"):
        script.index("function handleRecipeIngredientMasterKeydown")
    ]

    assert "function setRowFieldValue(row, field, value, options = {})" in setter
    assert "if (options.dispatch !== false)" in setter
    assert "const masterFieldValues = {" in selection
    assert "Object.entries(masterFieldValues).forEach" in selection
    assert "setRowFieldValue(row, field, value, { dispatch: false });" in selection
    assert 'setRowFieldValue(row, "purchasable_item", name, { dispatch: false });' in selection
    assert selection.count("updateRecipeIngredientSummary(") == 4


def test_recipe_editor_type_picker_uses_workspace_registry_and_drives_optional_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'RECIPE_INGREDIENT_CUSTOM_TYPES_KEY = "recipeIngredientCustomTypes"' in script
    assert "const RECIPE_INGREDIENT_BUILT_IN_TYPES = [" in script
    for value in ("main", "optional", "garnish", "topping", "sauce", "substitute"):
        assert f'{{ value: "{value}"' in script
    assert "function recipeIngredientTypeRegistry()" in script
    assert 'document.getElementById("ingredientTypeConfig")' in script
    assert "function recipeIngredientCustomTypeNames()" in script
    assert "async function saveRecipeIngredientCustomTypeName(value)" in script
    assert 'masterDataViewerUrl("/api/master-data/types")' in script
    assert "function refreshRecipeIngredientTypeRegistryFromServer()" in script
    assert 'window.addEventListener("focus"' in script
    assert "function refreshRecipeIngredientTypeSelectOptions(scope = document)" in script
    assert 'data-custom="${type.custom ? "true" : "false"}"' in script

    assert "function ensureRecipeIngredientTypeMenu()" in script
    assert 'menu.id = "recipeIngredientTypeMenu";' in script
    assert 'menu.setAttribute("role", "listbox");' in script
    assert "function renderRecipeIngredientTypeMenu(menu, select)" in script
    assert 'class="recipe-edit-store-section-option recipe-edit-type-option${selected ? " is-selected" : ""}"' in script
    assert "function recipeIngredientTypeDotClassModifier(value)" in script
    assert 'return " is-custom";' in script
    assert 'return builtIn.value === "optional" ? " is-optional" : "";' in script
    assert 'class="recipe-edit-type-option-dot${recipeIngredientTypeDotClassModifier(value)}"' in script
    assert 'data-type-trigger-dot' not in script
    assert 'trigger.querySelector("[data-type-trigger-dot]")' not in script
    assert 'data-type-action="add-custom"' in script
    assert "Add custom type…" in script
    assert "Manage Types…" in script
    assert 'href="${escapeAttribute(masterDataViewerUrl("/admin/master-data/types"))}"' in script
    assert 'target="_blank"' in script
    assert 'rel="noopener"' in script
    assert 'aria-label="Manage Types in a new tab"' in script
    assert "async function addRecipeIngredientCustomType(button)" in script
    assert "function ensureRecipeIngredientTypeManager()" not in script

    assert "function bindRecipeIngredientTypeControls(scope)" in script
    assert "function createRecipeIngredientTypeTrigger(select, options = {})" in script
    assert "function ensureRecipeIngredientInlineTypeTrigger(control, source)" in script
    create_start = script.index("function createRecipeIngredientTypeTrigger(select, options = {})")
    create_end = script.index("function syncRecipeIngredientTypeControl(select)", create_start)
    create_trigger = script[create_start:create_end]
    assert 'document.createElement("input")' in create_trigger
    assert 'document.createElement("button")' not in create_trigger
    assert 'trigger.type = "text";' in create_trigger
    assert "trigger.readOnly = true;" in create_trigger
    assert '"recipe-edit-ingredient-inline-control recipe-edit-type-trigger"' in create_trigger
    assert 'trigger.dataset.typeTriggerLabel = "";' in create_trigger
    assert "trigger.innerHTML" not in create_trigger
    assert "event.preventDefault();" not in create_trigger
    assert 'trigger.matches("[data-type-trigger-label]")' in script
    assert '"value" in triggerLabel' in script
    assert "trigger.recipeEditTypeSelect = select;" in script
    assert "trigger && trigger.recipeEditTypeSelect" in script
    assert "trigger.dataset.recipeIngredientInlineTypeTrigger" in script
    assert "menu.recipeEditTypeInline" in script
    assert 'trigger.dataset.recipeEditTypeTrigger = "true";' in script
    assert 'trigger.setAttribute("role", "combobox");' in script
    assert 'trigger.setAttribute("aria-controls", "recipeIngredientTypeMenu");' in script
    assert "select.hidden = true;" in script
    bind_start = script.index("function bindRecipeIngredientTypeControls(scope)")
    bind_end = script.index("let recipeIngredientUnitRegistryCache", bind_start)
    bind_type = script[bind_start:bind_end]
    assert 'chevron.className = "recipe-edit-unit-chevron recipe-edit-type-chevron";' in bind_type
    assert 'trigger.insertAdjacentElement("afterend", chevron);' in bind_type
    summary_start = script.index("const summaryDefinitions = [")
    summary_end = script.index("const mobileQuantitySummary", summary_start)
    summary_controls = script[summary_start:summary_end]
    inline_control_factory = script[
        script.index("function appendRecipeIngredientInlineSummaryControl"):
        script.index("function createRecipeIngredientOptionRowSummary")
    ]
    assert 'if (fieldName === "unit" || fieldName === "section")' in inline_control_factory
    assert '"recipe-edit-unit-chevron recipe-edit-type-chevron recipe-edit-inline-picker-chevron"' in inline_control_factory
    assert '"recipe-edit-unit-chevron recipe-edit-inline-picker-chevron"' in inline_control_factory
    assert 'chevron.innerHTML = recipeEditSvgIcon("chevron-down");' in inline_control_factory
    assert "bindRecipeIngredientStoreSectionControls(row);\n    bindRecipeIngredientTypeControls(row);" in script
    assert 'optionalInput.checked = recipeIngredientIsOptional({ section: typeSelect.value });' in script
    assert 'item.optional = recipeIngredientIsOptional(item);' in script
    assert 'syncRecipeIngredientTypeControl(input);' in script
    assert "/* Ingredient editor v11: managed custom Type picker. */" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot.is-optional" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot.is-custom" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-manage-option" in css
    assert ".recipe-edit-ingredient-type-summary" in css
    assert ".recipe-edit-ingredient-type-summary > .recipe-edit-type-trigger" in css
    assert 'border: 1px solid transparent;' in css

    trigger_rule_start = css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-type-summary > .recipe-edit-type-trigger {"
    )
    trigger_rule = css[trigger_rule_start:css.index("}", trigger_rule_start)]
    assert "display: block;" in trigger_rule
    assert "grid-template-columns:" not in trigger_rule
    assert "font: inherit;" in trigger_rule
    assert "cursor: pointer;" in trigger_rule

    quiet_type = css[css.index("/* Ingredient editor v28:"):]
    assert "@media (min-width: 768px)" in quiet_type
    assert "#recipeEditIngredients .recipe-edit-ingredient-type-summary:has(> [data-recipe-ingredient-inline-type-trigger])" in quiet_type
    assert "display: block;" in quiet_type
    assert "width: 100%;" in quiet_type
    assert "max-width: none;" in quiet_type
    assert "padding: 0 7px;" in quiet_type
    assert "font: inherit;" in quiet_type
    assert "text-align: left;" in quiet_type
    assert "transition: border-color 120ms ease, background-color 120ms ease, box-shadow 120ms ease;" in quiet_type

    modal_type = css[css.index("/* Ingredient editor v29:"):]
    assert ".recipe-edit-ingredient-modal-type-field > .recipe-edit-type-trigger" in modal_type
    assert "padding: 9px 40px 9px 12px;" in modal_type
    assert "cursor: pointer;" in modal_type
    assert "[data-recipe-edit-unit-trigger]:is(:hover, :focus-visible, [aria-expanded=\"true\"])" in modal_type
    assert "[data-recipe-edit-type-trigger]:is(:hover, :focus-visible, [aria-expanded=\"true\"])" in modal_type
    assert "~ .recipe-edit-unit-chevron" in modal_type
    assert "~ .recipe-edit-type-chevron" in modal_type
    assert "opacity: 1;" in modal_type

    separate_chevron = css[css.index("/* Ingredient editor v31:"):]
    aligned_field_rule = separate_chevron[:separate_chevron.index("}")]
    assert ".recipe-edit-ingredient-unit-summary > .recipe-edit-ingredient-inline-control" in aligned_field_rule
    assert ".recipe-edit-ingredient-type-summary > .recipe-edit-type-trigger" in aligned_field_rule
    assert "width: 100%;" in aligned_field_rule
    assert "padding-right: 22px;" in aligned_field_rule
    separate_icon_start = separate_chevron.index(".recipe-edit-inline-picker-chevron")
    separate_icon_rule = separate_chevron[separate_icon_start:separate_chevron.index("}", separate_icon_start)]
    assert "right: 9px;" in separate_icon_rule

    unit_chevron_start = css.index(
        ".recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-unit-chevron {"
    )
    unit_chevron_rule = css[unit_chevron_start:css.index("}", unit_chevron_start)]
    assert "opacity: 0;" in unit_chevron_rule
    assert "transition: opacity 120ms ease;" in unit_chevron_rule

    mobile_type_start = css.index(
        "body.recipe-edit-standalone-page dialog.recipe-edit-ingredient-edit-panel .recipe-edit-type-trigger {",
        css.index("/* Use a calmer mobile type hierarchy and keep editable text phone-friendly. */"),
    )
    mobile_type = css[mobile_type_start:css.index("}", mobile_type_start)]
    assert "font-size: 16px;" in mobile_type
    assert "font-weight: 500;" in mobile_type
    assert "line-height: 1.25;" in mobile_type


def test_recipe_editor_type_is_authoritative_for_saved_optional_state():
    rows = recipe_edit_service.sanitize_ingredients([
        {"ingredient": "Required salt", "section": "main", "optional": True},
        {"ingredient": "Optional parsley", "section": "optional", "optional": False},
        {"ingredient": "Garnish", "section": "garnish", "optional": True},
        {"ingredient": "Legacy optional", "optional": True},
    ])

    assert [(row["section"], row["optional"]) for row in rows] == [
        ("main", False),
        ("optional", True),
        ("garnish", False),
        ("optional", True),
    ]


def test_recipe_editor_dropdowns_support_shared_keyboard_typeahead_search():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "const RECIPE_EDIT_LISTBOX_TYPEAHEAD_RESET_MS = 700;" in script
    assert "function recipeEditListboxTypeaheadText(value)" in script
    assert '.normalize("NFKD")' in script
    assert "function recipeEditListboxTypeaheadKey(event)" in script
    assert "!event.isComposing" in script
    assert "!event.ctrlKey" in script
    assert "!event.metaKey" in script
    assert "!event.altKey" in script
    assert "function recipeEditListboxOptionTypeaheadText(option)" in script
    assert "option.dataset.unitValue" in script
    assert "option.dataset.typeValue" in script
    assert "option.dataset.storeSectionValue" in script

    matcher_start = script.index("function recipeEditListboxMatch(menu, value, startIndex = 0)")
    helper_start = script.index("function moveRecipeEditListboxToTypeaheadMatch(event, menu)")
    helper_end = script.index("function renderRecipeIngredientUnitMenu", helper_start)
    matcher = script[matcher_start:helper_start]
    helper = script[helper_start:helper_end]
    assert "candidate.text.startsWith(searchQuery)" in matcher
    assert "word.startsWith(searchQuery)" in matcher
    assert "candidate.text.includes(searchQuery)" in matcher
    assert 'option.matches("[data-unit-action], [data-type-action], [data-store-section-action]")' in matcher
    assert "event.preventDefault();" in helper
    assert 'menu.dataset.typeaheadBuffer || ""' in helper
    assert "previousBuffer" in helper
    assert "repeatedKey" in helper
    assert "recipeEditListboxMatch(menu, query" in helper
    assert "setRecipeEditListboxActiveOption(menu, match.index);" in helper

    handlers = (
        ("function handleRecipeIngredientStoreSectionKeydown", "function bindRecipeIngredientStoreSectionControls", "openRecipeIngredientStoreSectionMenu(trigger);"),
        ("function handleRecipeIngredientTypeKeydown", "function bindRecipeIngredientTypeControls", "openRecipeIngredientTypeMenu(trigger);"),
    )
    for start_marker, end_marker, open_call in handlers:
        start = script.index(start_marker)
        handler = script[start:script.index(end_marker, start)]
        assert "recipeEditListboxTypeaheadKey(event)" in handler
        assert open_call in handler
        assert "moveRecipeEditListboxToTypeaheadMatch(event, menu);" in handler

    unit_handler_start = script.index("function handleRecipeIngredientUnitKeydown")
    unit_handler = script[unit_handler_start:script.index("function bindRecipeIngredientUnitPickerTrigger", unit_handler_start)]
    assert "recipeEditListboxTypeaheadKey(event)" not in unit_handler
    assert "moveRecipeEditListboxToTypeaheadMatch(event, menu);" not in unit_handler

    unit_bind_start = script.index("function bindRecipeIngredientUnitPickerTrigger(input)")
    unit_bind = script[unit_bind_start:script.index("function bindRecipeIngredientUnitControls", unit_bind_start)]
    assert "input.select();" in unit_bind
    assert 'input.addEventListener("input", event =>' in unit_bind
    assert "if (!isOpen && event.isTrusted)" in unit_bind
    assert "openRecipeIngredientUnitPicker(input, { showAll: true });" in unit_bind
    assert "renderRecipeIngredientUnitMenu(menu, input, { showAll: true });" in unit_bind
    assert "if (!menu || menu.hidden || menu.recipeEditAnchorButton !== input)" in unit_bind
    assert "const match = recipeEditListboxMatch(menu, input.value);" in unit_bind
    assert "setRecipeEditListboxActiveOption(menu, match.index);" in unit_bind

    close_start = script.index("function closeRecipeEditRowMenus()")
    close_end = script.index("function closeRecipeViewGenerateSubmenus", close_start)
    close_handler = script[close_start:close_end]
    assert "delete menu.dataset.typeaheadBuffer;" in close_handler
    assert "delete menu.recipeEditTypeaheadAt;" in close_handler


def test_bulk_image_generation_menus_include_title_image_scope():
    recipe_view = (ROOT / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    current_log = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(encoding="utf-8")
    view_behavior = (ROOT / "PushShoppingList/templates/sections/view_behavior.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "generateRecipeImagesFromMenu(this, { imageScope: 'title' })" in recipe_view
    assert "generateRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'title' })" in recipe_view
    assert "generateCurrentRecipeImagesFromMenu(this, { imageScope: 'title' })" in current_log
    assert "generateCurrentRecipeImagesFromMenu(this, { missingOnly: true, imageScope: 'title' })" in current_log
    assert "generateRecipeImagesFromEditor(this, { imageScope: 'title' })" in current_log
    assert "generateRecipeImagesFromEditor(this, { missingOnly: true, imageScope: 'title' })" in current_log
    assert "generateAllRecipeImagesFromViewBehavior(this, { imageScope: 'title' })" in view_behavior
    assert "generateAllRecipeImagesFromViewBehavior(this, { missingOnly: true, imageScope: 'title' })" in view_behavior
    assert 'return "[data-recipe-edit-title-image-panel]";' in script
    assert "async function generateRecipeTitleImageForCard" in script
    assert "requestRecipeCoverImageGeneration" in script
    assert "await generateRecipeTitleImageForCard(card, options);" in script
    assert 'if (scope === "title") {' in script


def test_recipe_editor_image_menu_allows_standalone_editor_page():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    surface_start = script.index("function recipeEditorSurfaceIsActive")
    surface_end = script.index("function recipeEditPageUrl", surface_start)
    surface_block = script[surface_start:surface_end]
    generate_start = script.index("async function generateRecipeImagesFromEditor")
    generate_end = script.index("function setRecipeEditorImagesVisibleFromMenu", generate_start)
    generate_block = script[generate_start:generate_end]
    toggle_start = script.index("function setRecipeEditorImagesVisibleFromMenu")
    toggle_end = script.index("function recipeEditorImagePanelSelector", toggle_start)
    toggle_block = script[toggle_start:toggle_end]

    assert "modal.classList.contains(\"open\")" in surface_block
    assert "recipeEditorStandalonePageIsActive()" in surface_block
    assert "if (!recipeEditorSurfaceIsActive(modal))" in generate_block
    assert "if (!recipeEditorSurfaceIsActive(modal))" in toggle_block


def test_recipe_editor_row_delete_uses_portaled_menu_anchor():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    remove_start = script.index("function removeRecipeEditRow")
    remove_end = script.index("function recipeHasGeneratedCloudflarePdf", remove_start)
    remove_block = script[remove_start:remove_end]
    nutrition_start = script.index("function addRecipeNutritionRow")
    nutrition_end = script.index("function recipeNutritionHeaderHtml", nutrition_start)
    nutrition_block = script[nutrition_start:nutrition_end]

    assert 'Delete nutrition row' in nutrition_block
    assert 'onclick="removeRecipeEditRow(this)"' in nutrition_block
    assert "const row = recipeEditActionRowFromButton(button);" in remove_block
    assert "button.closest(recipeEditMovableRowSelector())" not in remove_block
    assert remove_block.index("closeRecipeEditRowMenus();") < remove_block.index("row.remove();")
    assert "return false;" in remove_block


def test_collapsed_ingredient_rows_use_compact_one_line_layout():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    final_surface_start = css.index("/* Keep ingredient rows visually aligned with the Equipment row surface. */")
    shared_surface_end = css.index("@media (min-width: 761px)", final_surface_start)
    shared_surface_css = css[final_surface_start:shared_surface_end]
    compact_start = css.index(
        ".recipe-edit-ingredients.recipe-edit-ingredients-collapsed > .recipe-edit-ingredient-row:not(.recipe-edit-row-expanded),",
        final_surface_start,
    )
    compact_end = css.index(".recipe-edit-equipment.recipe-edit-equipment-collapsed", compact_start)
    compact_css = css[compact_start:compact_end]

    assert ".recipe-edit-equipment-row {" in shared_surface_css
    assert "border: 0;" in shared_surface_css
    assert "border-bottom: 1px solid #263447;" in shared_surface_css
    assert "grid-template-columns: 22px 40px minmax(0, 1fr) 38px;" in compact_css
    assert "min-height: 0;" in compact_css
    assert "padding: 10px 14px;" in compact_css
    assert "@media (min-width: 761px)" in compact_css
    assert "grid-template-columns: 28px 54px minmax(0, 1fr) 40px;" in compact_css
    assert "padding: 10px 18px;" in compact_css
    assert "width: 44px;" in compact_css
    assert "height: 44px;" in compact_css
    assert "@media (min-width: 761px) and (max-width: 1500px)" in compact_css
    assert "grid-template-columns: 26px 54px minmax(0, 1fr) 44px;" in compact_css
    assert "grid-row: 1;" in compact_css
    assert "display: flex;" in compact_css
    assert "width: 34px;" in compact_css
    assert "height: 34px;" in compact_css
    assert "min-height: 20px;" in compact_css
    assert "border: 0;" in compact_css
    assert "border-bottom: 1px solid #263447;" in compact_css


def test_collapsed_ingredient_rows_put_thumbnail_between_number_and_name():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    compact_start = css.index(
        ".recipe-edit-ingredients.recipe-edit-ingredients-collapsed "
        "> .recipe-edit-ingredient-row:not(.recipe-edit-row-expanded):has("
        ".recipe-ingredient-image-panel:not(.recipe-image-visibility-hidden) "
        ".recipe-ingredient-image:not([hidden]))"
    )
    compact_end = css.index("@media (max-width: 760px)", compact_start)
    compact_css = css[compact_start:compact_end]

    assert "grid-template-columns: 22px 40px var(--recipe-edit-thumbnail-slot, 66px) minmax(0, 1fr) 38px;" in compact_css
    assert "display: contents;" in compact_css
    assert "grid-column: 3 / 4;" in compact_css
    assert "width: var(--recipe-edit-thumbnail-size, 64px);" in compact_css
    assert "height: var(--recipe-edit-thumbnail-size, 64px);" in compact_css
    assert "grid-column: 4 / 5;" in compact_css
    assert "grid-column: 5 / 6;" in compact_css
    assert "@media (min-width: 1181px)" in compact_css
    assert "grid-template-columns: 28px 54px var(--recipe-edit-thumbnail-slot, 66px) minmax(0, 1fr) 40px;" in compact_css
    assert "padding-right: 18px;" in compact_css
    assert "padding-left: 18px;" in compact_css


def test_recipe_editor_equipment_uses_same_compact_expand_controls_as_ingredients():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'data-recipe-ingredients-collapse-toggle' in template
    assert 'addRecipeIngredientFromCurrentView()' in template
    assert 'data-recipe-equipment-collapse-toggle' in template
    assert "toggleRecipeEquipmentCollapsed(this)" in template
    assert "addRecipeEquipmentRow('', { expanded: true })" in template
    assert "function setRecipeIngredientsCollapsed" in script
    assert "function setRecipeEquipmentCollapsed" in script
    assert "function toggleRecipeEquipmentRowCollapsed" in script
    assert "function isRecipeEquipmentRowCollapsed" in script
    assert script.count("setRecipeIngredientsCollapsed(recipeIngredientsShouldStartCollapsed());") == 2
    assert "setRecipeEquipmentCollapsed(true);" in script
    assert "addRecipeIngredientRow({}, { expanded: true });" in script
    assert 'addRecipeEquipmentRow("", { expanded: false });' in script
    assert "expandRecipeEquipmentRow(row);" in script
    assert "recipe-edit-equipment-collapsed" in script
    assert "Expand equipment" in script
    assert "Collapse equipment" in script
    assert ".recipe-edit-equipment.recipe-edit-equipment-collapsed .recipe-edit-equipment-row:not(.recipe-edit-row-expanded):has(" in css
    assert ".recipe-edit-equipment-row.recipe-edit-row-collapsed:has(" in css
    compact_equipment_start = css.index(
        ".recipe-edit-equipment.recipe-edit-equipment-collapsed .recipe-edit-equipment-row:not(.recipe-edit-row-expanded),"
    )
    compact_equipment_end = css.index(
        ".recipe-edit-equipment.recipe-edit-equipment-collapsed .recipe-edit-equipment-row:not(.recipe-edit-row-expanded):not(:has",
        compact_equipment_start,
    )
    compact_equipment_css = css[compact_equipment_start:compact_equipment_end]
    assert "border: 0;" in compact_equipment_css
    assert "border-bottom: 1px solid #263447;" in compact_equipment_css
    assert "border-radius: 8px;" in compact_equipment_css
    assert "linear-gradient(145deg, rgba(19, 30, 45, 0.9), rgba(10, 16, 25, 0.96))" in compact_equipment_css


def test_mobile_ingredient_cards_expose_and_honor_the_compact_collapse_controls():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="recipe-edit-mobile-ingredients-collapse-toggle"' in template
    assert template.count("data-recipe-ingredients-collapse-toggle") >= 2
    assert "data-recipe-edit-ingredient-collapse-toggle" in script
    assert 'mobileQuantitySummary.className = "recipe-edit-ingredient-mobile-quantity-summary";' in script
    assert 'mobileQuantitySummary.setAttribute("aria-label", "Quantity Unit");' in script
    assert "const quantitySummaryText = formatRecipeIngredientQuantityUnit(values);" in script
    assert 'mobileQuantityValue.textContent = quantitySummaryText;' in script
    quantity_unit_formatter = script[
        script.index("function formatRecipeIngredientQuantityUnit"):
        script.index("function formatRecipeIngredientQuantityColumn")
    ]
    assert "values.size" not in quantity_unit_formatter
    assert "recipeIngredientPluralUnit(" in quantity_unit_formatter
    assert "{ includePieces: true }" in quantity_unit_formatter
    assert 'document.querySelectorAll("[data-recipe-ingredients-collapse-toggle]")' in script
    assert 'compactButton.setAttribute("aria-expanded", String(!collapsed));' in script
    assert "function recipeIngredientsShouldStartCollapsed()" in script
    assert 'window.matchMedia("(max-width: 767px)").matches' in script
    assert 'document.body.classList.contains("screen-preview-mobile-frame")' in script
    assert script.count("setRecipeIngredientsCollapsed(recipeIngredientsShouldStartCollapsed());") == 2
    mobile_header_setup = script[
        script.index("function initializeRecipeIngredientMobileHeaderLayout"):
        script.index("function collapseOtherRecipeIngredientRows")
    ]
    assert "const syncHeaders = event => {" in mobile_header_setup
    assert "const choiceExpansionState = event && typeof event.matches" in mobile_header_setup
    assert "captureRecipeIngredientChoiceExpansionState()" in mobile_header_setup
    assert "const shouldCollapse = recipeIngredientsShouldStartCollapsed();" in mobile_header_setup
    assert "setRecipeIngredientsCollapsed(shouldCollapse);" in mobile_header_setup
    assert "restoreRecipeIngredientChoiceExpansionState(choiceExpansionState);" in mobile_header_setup

    mobile_start = css.index("/* Ingredient editor v24: real mobile folding for the current card-based layout. */")
    mobile_css = css[mobile_start:]
    mobile_media_start = mobile_css.index("@media (max-width: 767px)")
    desktop_only_rule = mobile_css[:mobile_media_start]
    assert (
        "body.recipe-edit-standalone-page .ingredients-toolbar "
        ".recipe-edit-mobile-ingredients-collapse-toggle {"
    ) in desktop_only_rule
    assert "display: none;" in desktop_only_rule
    mobile_media = mobile_css[mobile_media_start:]
    assert "display: inline-flex;" in mobile_media
    assert "grid-template-columns: 40px minmax(0, 1fr) max-content 106px !important;" in mobile_css
    assert "grid-template-rows: 44px !important;" in mobile_css
    assert "min-height: 62px !important;" in mobile_css
    assert ".recipe-edit-ingredient-status-summary," in mobile_css
    assert ".recipe-edit-ingredient-quantity-summary," in mobile_css
    assert ".recipe-edit-ingredient-unit-summary," in mobile_css
    assert ".recipe-edit-ingredient-size-summary," in mobile_css
    assert ".recipe-edit-ingredient-substitution-cell," in mobile_css
    assert ".recipe-edit-ingredient-mobile-quantity-summary" in mobile_css
    assert "display: none !important;" in mobile_css
    collapsed_detail_selector = mobile_css[
        mobile_css.index(
            "#recipeEditIngredients.recipe-edit-ingredients-collapsed > "
            ".recipe-edit-ingredient-row:not(.recipe-edit-row-expanded) "
            ".recipe-edit-ingredient-read-details"
        ):
    ]
    collapsed_detail_selector = collapsed_detail_selector[:collapsed_detail_selector.index("{")]
    assert ".recipe-edit-ingredient-read-details" in collapsed_detail_selector
    assert ".recipe-edit-ingredient-read-buy-as" not in collapsed_detail_selector
    collapsed_buy_as = mobile_css[
        mobile_css.index(
            "#recipeEditIngredients.recipe-edit-ingredients-collapsed > "
            ".recipe-edit-ingredient-row:not(.recipe-edit-row-expanded) "
            ".recipe-edit-ingredient-read-buy-as:not([hidden])"
        ):
    ]
    collapsed_buy_as = collapsed_buy_as[:collapsed_buy_as.index("}")]
    assert "display: grid !important;" in collapsed_buy_as
    assert ".recipe-edit-compact-row-edit" in mobile_css
    assert ".recipe-edit-compact-row-actions > .recipe-edit-compact-row-edit" in mobile_css
    assert ".recipe-edit-compact-row-actions > .recipe-edit-compact-row-collapse" in mobile_css
    assert ".recipe-edit-compact-row-actions > .recipe-edit-row-menu-wrap" in mobile_css
    collapse_order = mobile_css[
        mobile_css.index(".recipe-edit-compact-row-actions > .recipe-edit-compact-row-collapse {"):
    ]
    collapse_order = collapse_order[:collapse_order.index("}")]
    edit_order = mobile_css[
        mobile_css.index(".recipe-edit-compact-row-actions > .recipe-edit-compact-row-edit {"):
    ]
    edit_order = edit_order[:edit_order.index("}")]
    assert "order: 1;" in collapse_order
    assert "order: 2;" in edit_order
    assert mobile_css.count("order: 3;") >= 1
    collapsed_edit = mobile_css[
        mobile_css.index(
            "#recipeEditIngredients.recipe-edit-ingredients-collapsed > "
            ".recipe-edit-ingredient-row:not(.recipe-edit-row-expanded) "
            ".recipe-edit-compact-row-edit"
        ):
    ]
    collapsed_edit = collapsed_edit[:collapsed_edit.index("}")]
    assert "display: inline-flex !important;" in collapsed_edit
    assert "display: none !important;" not in collapsed_edit


def test_mobile_ingredient_quantity_formatter_uses_plain_slash_fractions_and_keeps_units():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    formatter = script[
        script.index("function formatRecipeIngredientQuantityUnit"):
        script.index("function formatRecipeIngredientQuantityColumn")
    ]
    normalizer = script[
        script.index("function normalizeQuantityFractionText"):
        script.index("function formatQuantityFraction")
    ]

    assert "const quantityText = normalizeQuantityFractionText(values.quantity_text);" in formatter
    assert "const quantity = normalizeQuantityFractionText(values.quantity || values.amount);" in formatter
    assert "const quantityTextNumber = recipeIngredientViewQuantityNumber(quantityText);" in formatter
    assert "const quantityNumber = recipeIngredientViewQuantityNumber(quantity);" in formatter
    assert "quantityText && quantityTextNumber === null" in formatter
    assert "!/\\d/.test(quantity) && quantityNumber === null" in formatter
    assert "const displayQuantity = quantityTextNumber !== null ? quantityText : quantity;" in formatter
    assert "quantityForPluralization !== null && quantityForPluralization <= 1" in formatter
    assert "quantityForPluralization !== null ? String(quantityForPluralization) : quantity" in formatter
    for character, replacement in (("½", "1/2"), ("¾", "3/4"), ("⅓", "1/3"), ("⅔", "2/3")):
        assert f'["{character}", "{replacement}"]' in normalizer
    assert '.replace(new RegExp(`(\\\\d)\\\\s*${character}`, "g"), `$1 ${replacement}`)' in normalizer


def test_ingredients_toolbar_places_equal_height_columns_view_add_and_overflow_in_order():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    soup = BeautifulSoup(template, "html.parser")
    toolbar = soup.select_one("#recipeEditPanelIngredients > .ingredients-toolbar")
    actions = toolbar.select_one(":scope > .ingredients-toolbar-actions")
    children = [child for child in actions.children if getattr(child, "name", None)]
    columns = actions.select_one(":scope > .recipe-edit-ingredient-column-menu-wrap")
    view = actions.select_one(":scope > .recipe-edit-ingredient-view-menu-wrap")
    add = actions.select_one(":scope > .recipe-edit-add-ingredient-button")
    overflow = actions.select_one(":scope > .recipe-edit-ingredients-menu-wrap")

    assert children[:4] == [columns, view, add, overflow]

    desktop_start = css.index("@media (min-width: 768px)")
    desktop_css = css[desktop_start:]
    shared_height_start = desktop_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredients-section :is("
    )
    shared_height_end = desktop_css.index("}", shared_height_start)
    shared_height = desktop_css[shared_height_start:shared_height_end]
    assert ".recipe-edit-add-ingredient-button," in shared_height
    assert ".recipe-edit-ingredient-columns-button" in shared_height
    assert ".recipe-edit-ingredient-view-button" in shared_height
    assert "min-height: 34px;" in shared_height
    assert "height: 34px;" in shared_height


def test_ingredient_view_menu_replaces_upper_switcher_and_stays_inside_ingredients_toolbar():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    soup = BeautifulSoup(template, "html.parser")
    tab_bar = soup.select_one(".recipe-edit-tab-bar")
    assert tab_bar is not None
    section_tablist = tab_bar.select_one(".recipe-edit-tab-list")
    ingredient_toolbar = soup.select_one("#recipeEditPanelIngredients > .ingredients-toolbar")
    ingredient_view_trigger = ingredient_toolbar.select_one("[data-recipe-ingredient-view-trigger]")
    ingredient_view_menu = ingredient_toolbar.select_one("[data-recipe-ingredient-view-menu]")

    assert section_tablist is not None
    assert ingredient_toolbar is not None
    assert section_tablist.parent is tab_bar
    assert section_tablist.get("role") == "tablist"
    assert [tab.get_text(strip=True) for tab in section_tablist.select('[role="tab"]')] == [
        "Ingredients",
        "Instructions",
        "Equipment",
        "Nutrition",
        "Notes",
    ]
    assert tab_bar.select_one(".recipe-edit-ingredient-view-switcher") is None
    assert ingredient_view_trigger is not None
    assert ingredient_view_trigger.get("aria-haspopup") == "menu"
    assert ingredient_view_trigger.get("aria-expanded") == "false"
    assert ingredient_view_menu.get("role") == "menu"
    assert ingredient_view_menu.get("aria-label") == "Ingredient view"
    options = ingredient_view_menu.select('[role="menuitemradio"]')
    assert [option.get_text(strip=True).replace("✓", "") for option in options] == [
        "Recipe",
        "Smart",
        "Table",
    ]
    assert [option.get("aria-checked") for option in options] == ["false", "false", "true"]

    tab_bar_start = template.index('class="recipe-edit-tab-bar"')
    tab_list_start = template.index('class="recipe-edit-tab-list"', tab_bar_start)
    tab_list_end = template.index("</div>", tab_list_start)
    panels_index = template.index('class="recipe-edit-tab-panels"', tab_list_end)
    panel_start = template.index('id="recipeEditPanelIngredients"')
    panel_end = template.index('id="recipeEditPanelEquipment"', panel_start)
    ingredient_section = template[panel_start:panel_end]
    title_index = ingredient_section.index('id="recipeEditIngredientsTitle"')
    actions_index = ingredient_section.index(
        'class="recipe-edit-section-actions recipe-edit-ingredient-actions ingredients-toolbar-actions"'
    )
    table_panel_index = ingredient_section.index('id="recipeEditIngredientViewTable"')

    assert tab_bar_start < tab_list_start < tab_list_end < panels_index
    assert "recipe-edit-ingredient-view-switcher" not in template
    assert title_index < actions_index < table_panel_index
    toolbar = ingredient_section[:table_panel_index]
    assert toolbar.index('id="recipeEditIngredientsTitle"') < toolbar.index(
        "recipe-edit-ingredient-column-menu-wrap"
    )
    assert toolbar.index("recipe-edit-ingredient-column-menu-wrap") < toolbar.index(
        "recipe-edit-ingredient-view-menu-wrap"
    )
    assert toolbar.index("recipe-edit-ingredient-view-menu-wrap") < toolbar.index(
        "recipe-edit-add-ingredient-button"
    )
    assert toolbar.index("recipe-edit-add-ingredient-button") < toolbar.index(
        "recipe-edit-ingredients-menu-wrap"
    )
    table_panel_end = ingredient_section.index(
        'id="recipeEditIngredientViewRecipe"', table_panel_index
    )
    table_panel = ingredient_section[table_panel_index:table_panel_end]
    assert table_panel.index('id="recipeEditIngredients"') < table_panel.index(
        "data-recipe-ingredient-table-add"
    )
    assert "recipe-edit-ingredient-recipe-add" in table_panel
    assert "addRecipeIngredientFromCurrentView()" in table_panel
    menu_css = css[css.index("/* Ingredient editor v80:"):]
    assert ".recipe-edit-ingredient-view-menu > [role=\"menuitemradio\"]" in menu_css
    assert '[role="menuitemradio"]:focus-visible' in menu_css
    assert '[role="menuitemradio"][aria-checked="true"]' in menu_css
    assert ".recipe-edit-ingredient-view-switcher" not in menu_css
    assert 'tabsRoot.querySelector("[data-recipe-ingredient-view-switcher]")' not in script


def test_recipe_editor_section_tabs_and_view_menu_keep_keyboard_focus_and_visibility_behavior():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the recipe editor tab regression harness.")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    section_tabs_start = script.index("function recipeEditTabKey(value)")
    section_tabs_end = script.index("function initRecipeEditTabs()", section_tabs_start)
    ingredient_menu_start = script.index("function recipeEditIngredientViewMenuItems(menu)")
    ingredient_menu_end = script.index("function initRecipeEditIngredientViews()", ingredient_menu_start)
    harness = """
function makeClassList() {
    const values = new Set();
    return {
        toggle(name, enabled) {
            if (enabled) values.add(name);
            else values.delete(name);
        },
        contains(name) { return values.has(name); },
    };
}
function makeSectionTab(key) {
    return {
        dataset: { recipeEditTab: key },
        classList: makeClassList(),
        attributes: {},
        tabIndex: -1,
        focused: false,
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; },
    };
}
const sectionTabs = ["ingredients", "instructions", "equipment", "nutrition", "notes"].map(makeSectionTab);
const sectionPanels = sectionTabs.map(tab => ({
    dataset: { recipeEditTabPanel: tab.dataset.recipeEditTab },
    hidden: false,
}));
const tabsRoot = {
    querySelectorAll(selector) {
        if (selector === "[data-recipe-edit-tab]") return sectionTabs;
        if (selector === "[data-recipe-edit-tab-panel]") return sectionPanels;
        return [];
    },
};
let viewTrigger = null;
const document = {
    querySelector(selector) {
        if (selector === "[data-recipe-edit-tabs]") return tabsRoot;
        if (selector === "[data-recipe-ingredient-view-trigger]") return viewTrigger;
        return null;
    },
};
function clearRecipeIngredientScrollReserve() {}
function appMainScrollRegion() { return null; }
function updateRecipeEditStickyOffsets() {}
""" + script[section_tabs_start:section_tabs_end] + """

setRecipeEditActiveTab("instructions", { focus: true });
const instructionsState = {
    viewVisible: !sectionPanels[0].hidden,
    selected: sectionTabs.filter(tab => tab.attributes["aria-selected"] === "true").map(tab => tab.dataset.recipeEditTab),
    visiblePanels: sectionPanels.filter(panel => !panel.hidden).map(panel => panel.dataset.recipeEditTabPanel),
    focused: sectionTabs.filter(tab => tab.focused).map(tab => tab.dataset.recipeEditTab),
};
setRecipeEditActiveTab("ingredients");
const ingredientsState = {
    viewVisible: !sectionPanels[0].hidden,
    selected: sectionTabs.filter(tab => tab.attributes["aria-selected"] === "true").map(tab => tab.dataset.recipeEditTab),
    visiblePanels: sectionPanels.filter(panel => !panel.hidden).map(panel => panel.dataset.recipeEditTabPanel),
};

function makeViewItem(view, checked = false) {
    return {
        dataset: { recipeIngredientViewOption: view },
        attributes: { "aria-checked": checked ? "true" : "false" },
        focused: false,
        getAttribute(name) { return this.attributes[name]; },
        setAttribute(name, value) { this.attributes[name] = value; },
        closest(selector) {
            return selector === "[data-recipe-ingredient-view-menu]" ? ingredientMenu : null;
        },
        focus() {
            ingredientItems.forEach(item => { item.focused = false; });
            this.focused = true;
        },
    };
}
const ingredientItems = [
    makeViewItem("recipe"),
    makeViewItem("smart"),
    makeViewItem("table", true),
];
const viewWrap = {
    querySelector(selector) {
        return selector === "[data-recipe-ingredient-view-menu]" ? ingredientMenu : null;
    },
};
viewTrigger = {
    attributes: { "aria-expanded": "false" },
    focused: false,
    closest(selector) { return selector === ".recipe-edit-ingredient-view-menu-wrap" ? viewWrap : null; },
    setAttribute(name, value) { this.attributes[name] = value; },
    focus() { this.focused = true; },
};
const ingredientMenu = {
    hidden: true,
    dataset: {},
    recipeEditAnchorButton: viewTrigger,
    querySelectorAll(selector) {
        return selector === "[data-recipe-ingredient-view-option]" ? ingredientItems : [];
    },
};
const ingredientViewCalls = [];
function toggleRecipeEditSectionMenu(button, event) {
    ingredientMenu.hidden = !ingredientMenu.hidden;
    button.setAttribute("aria-expanded", String(!ingredientMenu.hidden));
}
function closeRecipeEditRowMenus() {
    ingredientMenu.hidden = true;
    viewTrigger.setAttribute("aria-expanded", "false");
}
function setRecipeEditIngredientView(view) {
    ingredientViewCalls.push(view);
    ingredientItems.forEach(item => item.setAttribute(
        "aria-checked",
        String(item.dataset.recipeIngredientViewOption === view),
    ));
}
""" + script[ingredient_menu_start:ingredient_menu_end] + """

function keyEvent(currentTarget, key) {
    return {
        currentTarget,
        key,
        altKey: false,
        ctrlKey: false,
        metaKey: false,
        prevented: false,
        stopped: false,
        preventDefault() { this.prevented = true; },
        stopPropagation() { this.stopped = true; },
    };
}

const enterOpen = keyEvent(viewTrigger, "Enter");
handleRecipeEditIngredientViewButtonKeydown(enterOpen);
const enterState = {
    open: !ingredientMenu.hidden,
    expanded: viewTrigger.attributes["aria-expanded"],
    focused: ingredientItems.filter(item => item.focused).map(item => item.dataset.recipeIngredientViewOption),
    prevented: enterOpen.prevented,
};
closeRecipeEditRowMenus();
const spaceOpen = keyEvent(viewTrigger, " ");
handleRecipeEditIngredientViewButtonKeydown(spaceOpen);
const spaceState = { open: !ingredientMenu.hidden, prevented: spaceOpen.prevented };
const down = keyEvent(ingredientItems[2], "ArrowDown");
handleRecipeEditIngredientViewMenuKeydown(down);
const afterDown = ingredientItems.find(item => item.focused).dataset.recipeIngredientViewOption;
const up = keyEvent(ingredientItems[0], "ArrowUp");
handleRecipeEditIngredientViewMenuKeydown(up);
const afterUp = ingredientItems.find(item => item.focused).dataset.recipeIngredientViewOption;
viewTrigger.focused = false;
const escape = keyEvent(ingredientItems[2], "Escape");
handleRecipeEditIngredientViewMenuKeydown(escape);
const escapeState = {
    open: !ingredientMenu.hidden,
    triggerFocused: viewTrigger.focused,
    prevented: escape.prevented,
    stopped: escape.stopped,
};
ingredientMenu.hidden = false;
viewTrigger.focused = false;
const chooseSmart = keyEvent(ingredientItems[1], "Enter");
handleRecipeEditIngredientViewMenuKeydown(chooseSmart);
const chooseState = {
    calls: ingredientViewCalls,
    checked: ingredientItems.filter(item => item.attributes["aria-checked"] === "true")
        .map(item => item.dataset.recipeIngredientViewOption),
    open: !ingredientMenu.hidden,
    triggerFocused: viewTrigger.focused,
};

process.stdout.write(JSON.stringify({
    instructionsState,
    ingredientsState,
    enterState,
    spaceState,
    afterDown,
    afterUp,
    escapeState,
    chooseState,
}));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["instructionsState"] == {
        "viewVisible": False,
        "selected": ["instructions"],
        "visiblePanels": ["instructions"],
        "focused": ["instructions"],
    }
    assert result["ingredientsState"] == {
        "viewVisible": True,
        "selected": ["ingredients"],
        "visiblePanels": ["ingredients"],
    }
    assert result["enterState"] == {
        "open": True,
        "expanded": "true",
        "focused": ["table"],
        "prevented": True,
    }
    assert result["spaceState"] == {"open": True, "prevented": True}
    assert result["afterDown"] == "recipe"
    assert result["afterUp"] == "table"
    assert result["escapeState"] == {
        "open": False,
        "triggerFocused": True,
        "prevented": True,
        "stopped": True,
    }
    assert result["chooseState"] == {
        "calls": ["smart"],
        "checked": ["smart"],
        "open": False,
        "triggerFocused": True,
    }


def test_mobile_ingredients_toolbar_shows_icon_only_columns_and_view_controls_with_labels():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="recipe-edit-ingredient-columns-label">Columns</span>' in template
    assert 'class="recipe-edit-ingredient-columns-desktop-action"' in template
    assert '{{ shell.svg_icon("columns") }}' in template
    assert 'class="recipe-edit-ingredient-view-label">View</span>' in template
    assert '{{ shell.svg_icon("eye") }}' in template
    assert 'aria-label="Choose ingredient view"' in template
    assert 'title="Choose ingredient view"' in template

    mobile_start = css.index("/* Ingredient editor v24: real mobile folding for the current card-based layout. */")
    mobile_css = css[mobile_start:]
    mobile_css = mobile_css[mobile_css.index("@media (max-width: 767px)"):]
    assert ".recipe-edit-ingredient-column-menu-wrap {" in mobile_css
    assert "display: block;" in mobile_css
    assert ".recipe-edit-ingredient-columns-button .recipe-edit-button-icon .app-icon-svg" in mobile_css
    assert "width: 16px;" in mobile_css
    assert "visibility: visible;" in mobile_css
    assert ".recipe-edit-ingredient-columns-label," in mobile_css
    assert ".recipe-edit-columns-chevron" in mobile_css
    assert ".recipe-edit-ingredient-view-button" in mobile_css
    assert ".recipe-edit-ingredient-view-label," in mobile_css
    assert ".recipe-edit-view-chevron" in mobile_css
    assert ".recipe-edit-ingredient-columns-desktop-action" in mobile_css

    visibility_start = script.index("function setRecipeEditIngredientColumnVisibility")
    visibility_end = script.index("function showAllRecipeEditIngredientColumns", visibility_start)
    visibility = script[visibility_start:visibility_end]
    assert "refreshRecipeEditIngredientColumnLayout();" in visibility
    assert "applyRecipeEditIngredientColumnLayout();" not in visibility

    show_all_start = visibility_end
    show_all_end = script.index("function recipeEditIngredientColumnCellText", show_all_start)
    show_all = script[show_all_start:show_all_end]
    assert "refreshRecipeEditIngredientColumnLayout();" in show_all
    assert "applyRecipeEditIngredientColumnLayout();" not in show_all


def test_mobile_store_and_type_fields_stack_beneath_their_labels():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    mobile_fields = css[
        css.index(
            "/* Ingredient editor v32: stack mobile Store and Type fields beneath their labels. */"
        ):
    ]
    assert "@media (max-width: 767px)" in mobile_fields
    assert ".recipe-edit-ingredient-store-summary," in mobile_fields
    assert ".recipe-edit-ingredient-type-summary" in mobile_fields
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_fields
    assert "align-items: stretch;" in mobile_fields
    assert "grid-row: 1;" in mobile_fields
    assert ".recipe-edit-store-section-trigger," in mobile_fields
    assert ".recipe-edit-type-trigger" in mobile_fields
    assert "grid-row: 2;" in mobile_fields
    assert "justify-self: stretch;" in mobile_fields
    assert "width: 100%;" in mobile_fields
    assert "min-width: 0;" in mobile_fields


def test_ingredient_rows_label_optional_items_beneath_buy_as_on_desktop_and_mobile():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    read_factory = script[
        script.index("function createRecipeIngredientReadCell"):
        script.index("function createRecipeIngredientStatusSummary")
    ]
    optional_badge = read_factory.index('class="recipe-edit-ingredient-read-optional"')
    buy_as = read_factory.index('class="recipe-edit-ingredient-read-buy-as"')
    assert buy_as < optional_badge
    assert "data-ingredient-read-optional" in read_factory
    assert 'aria-label="Optional ingredient"' in read_factory
    assert "hidden>Optional</span>" in read_factory

    summary_start = script.index("function updateRecipeIngredientSummary(row)")
    summary_end = script.index("function recipeEditIngredientRows()", summary_start)
    summary = script[summary_start:summary_end]
    assert 'readCell.querySelector(":scope > [data-ingredient-read-optional]")' in summary
    assert "readOptional.hidden = !recipeIngredientIsOptional(values);" in summary
    optional_css = css[css.index("/* Ingredient editor v26:"):]
    assert "@media (max-width: 767px)" in optional_css
    assert ".recipe-edit-ingredient-read-optional:not([hidden])" in optional_css
    assert ":has(.recipe-edit-ingredient-read-optional:not([hidden]))" in optional_css
    assert "grid-template-rows: 56px !important;" in optional_css
    assert "min-height: 74px !important;" in optional_css
    assert "display: inline-flex;" in optional_css
    assert "text-transform: uppercase;" in optional_css
    desktop_badge = optional_css[
        optional_css.index(
            "body.recipe-edit-standalone-page .recipe-edit-ingredient-read-optional:not([hidden]) {"
        ):
        optional_css.index("@media (max-width: 767px)")
    ]
    assert "display: inline-flex;" in desktop_badge
    assert "text-transform: uppercase;" in desktop_badge
    assert "@media (min-width: 768px)" in desktop_badge
    assert "margin-left: 7px;" in desktop_badge


def test_ingredient_modal_labels_follow_the_focused_record_not_the_selected_projection():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    summary = script[
        script.index("function updateRecipeIngredientSummary(row)"):
        script.index("function recipeEditIngredientRows()")
    ]

    assert "const rowValues = row ? fieldValuesFromRow(row) : {};" in summary
    assert "const parentValues = recipeIngredientChoiceParentValues(row);" in summary
    assert "const modalValues = editPanel?.recipeIngredientOptionSourceRow" in summary
    assert "...rowValues," in summary
    assert "recipeIngredientMatchDetailsHtml(modalMatchItem)" in summary
    assert "recipeIngredientSentenceCase(modalIngredientName)" in summary
    assert "recipeIngredientMeaningfulBuyAs(modalValues)" in summary
    assert "recipeStoreSectionDisplayLabel(modalValues.store_section" in summary
    assert "readCell.querySelector(\":scope > [data-ingredient-read-optional]\")" in summary
    assert 'row.querySelector("[data-ingredient-read-optional]")' not in summary


def test_wide_desktop_ingredient_overview_uses_one_page_compact_grid():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    compact = css[css.index("/* Ingredient editor v27:"):]
    assert "@media (min-width: 1440px) and (min-height: 800px)" in compact
    content = compact[compact.index(".recipe-edit-ingredient-modal-content {"):]
    content = content[:content.index("}")]
    assert "grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr);" in content
    assert "align-content: start;" in content
    assert "gap: 16px;" in content

    identity_fields = compact[
        compact.index(
            "dialog.recipe-edit-ingredient-edit-panel .recipe-edit-ingredient-modal-identity-fields {"
        ):
    ]
    identity_fields = identity_fields[:identity_fields.index("}")]
    assert (
        "grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr) minmax(164px, .9fr);"
        in identity_fields
    )
    assert "gap: 16px;" in identity_fields

    wide_desktop = compact[:compact.index("/* Ingredient editor v28:")]
    assert ".recipe-edit-ingredient-modal-type-field .recipe-edit-type-trigger" not in wide_desktop

    placements = {
        ".recipe-edit-ingredient-modal-section.is-identity {": ("grid-column: 1;", "grid-row: 1;"),
        ".recipe-edit-ingredient-modal-section.is-quantity {": ("grid-column: 2;", "grid-row: 1;"),
        ".recipe-edit-ingredient-modal-section.is-usage {": ("grid-column: 1 / -1;", "grid-row: 2;"),
        ".recipe-edit-ingredient-modal-bottom-grid {": ("grid-column: 1 / -1;", "grid-row: 3;"),
    }
    for selector, declarations in placements.items():
        rule = compact[compact.index(selector):]
        rule = rule[:rule.index("}")]
        for declaration in declarations:
            assert declaration in rule


def test_desktop_ingredient_modal_has_a_full_workspace_fit_mode():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    compact = css[
        css.index("/* Ingredient editor v85:"):
        css.index("/* Ingredient modal options v86:")
    ]
    assert "@media (min-width: 1280px) and (min-height: 760px)" in compact
    assert "grid-template-rows: 62px minmax(0, 1fr) 62px;" in compact
    assert "grid-template-columns: 230px minmax(0, 1fr);" in compact
    assert "grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr);" in compact
    assert "gap: 10px;" in compact
    assert "min-height: 70px;" in compact
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in compact
    assert ".recipe-edit-alternative-component-summary {" not in compact
    assert ".recipe-edit-ingredient-option-divider {" not in compact
    assert ".recipe-edit-alternative-add-component {" not in compact


def test_recipe_menu_edit_links_to_standalone_editor_page():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    current_recipes = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    recipe_view = (ROOT / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    cookbooks = (ROOT / "PushShoppingList/templates/sections/cookbooks.html").read_text(encoding="utf-8")
    standalone_page = (ROOT / "PushShoppingList/templates/recipe_edit_page.html").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert '@recipe_bp.route("/recipe/edit", methods=["GET"])' in routes
    assert "recipe_edit_only = true" in standalone_page
    assert "data-recipe-edit-page=\"true\"" in standalone_page
    assert "data-recipe-edit-url=\"{{ recipe_url }}\"" in standalone_page
    assert "consumeRecipeEditPendingAction(recipeUrl)" in standalone_page
    assert "openRecipeEditor({ dataset: { recipeUrl } }, pendingOptions);" in standalone_page
    assert "await waitForNextPaint();" in script
    assert "scheduleRecipeImageProgressPoll(750);" in script
    assert "document.body.dataset.recipeEditPage" in script
    assert "recipe_edit_page_url" in current_recipes
    assert "recipe_edit_page_url" in recipe_view
    assert "recipe_edit_page_url" in cookbooks
    assert 'target="_blank"' in current_recipes
    assert 'target="_blank"' in recipe_view
    assert 'target="_blank"' in cookbooks


def test_standalone_recipe_edit_page_renders_editor(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [{
            "user_id": "edit-page-user",
            "first_name": "Nathaniel",
            "last_name": "Tyler",
            "email": "ntylerbert@gmail.com",
            "username": "ntylerbert",
            "picture": "https://example.com/nathaniel-avatar.jpg",
            "account_status": "active",
        }],
    })

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "edit-page-user"

        home_response = client.get("/")
        response = client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "edit-page-user",
                "url": "https://example.com/soup",
            },
        )

    home_html = home_response.get_data(as_text=True)
    html = response.get_data(as_text=True)
    home_account_start = home_html.index('<span class="app-account-avatar"')
    home_account_end = home_html.index("</button>", home_account_start)
    edit_account_start = html.index('<span class="app-account-avatar"')
    edit_account_end = html.index("</button>", edit_account_start)
    home_account = home_html[home_account_start:home_account_end]
    edit_account = html[edit_account_start:edit_account_end]

    assert response.status_code == 200
    assert 'data-recipe-edit-page="true"' in html
    assert 'data-recipe-edit-url="https://example.com/soup"' in html
    assert html.count('data-app-header') == 1
    assert html.count('aria-label="Primary navigation"') == 1
    assert html.count('id="appContent"') == 1
    assert html.count('class="app-mobile-bottom-nav"') == 1
    assert 'id="recipeEditModal"' in html
    assert 'id="currentRecipeUrlLogCard"' not in html
    assert home_response.status_code == 200
    assert home_account == edit_account
    assert "Nathaniel Tyler" in edit_account
    assert "Pro Plan" in edit_account
    assert "ntylerbert@gmail.com" not in edit_account
    assert 'src="https://example.com/nathaniel-avatar.jpg"' in edit_account


def test_recipe_edit_page_canonicalizes_and_enforces_session_user_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    user_account_service.save_users({
        "users": [
            {
                "user_id": "owner-user",
                "username": "owner-user",
                "email": "owner@example.com",
                "account_status": "active",
            },
            {
                "user_id": "other-user",
                "username": "other-user",
                "email": "other@example.com",
                "account_status": "active",
            },
        ],
    })
    app = create_app()
    app.config.update(TESTING=True)
    source_url = "https://example.com/soup?size=2&next=/menu?q=hot#recipe"

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner-user"

        canonicalized = client.get(
            "/recipe/edit",
            query_string={
                "url": source_url,
                "screen_preview_width": "1440",
            },
        )
        location = canonicalized.headers["Location"]
        location_query = parse_qs(urlsplit(location).query)

        assert canonicalized.status_code == 302
        assert canonicalized.headers["Cache-Control"] == "private, no-store"
        assert location_query == {
            "viewer_user_id": ["owner-user"],
            "url": [source_url],
            "screen_preview_width": ["1440"],
        }
        matching = client.get(location)
        assert matching.status_code == 200
        assert matching.headers["Cache-Control"] == "private, no-store"

        blank_scope = client.get(
            "/recipe/edit",
            query_string={"viewer_user_id": "   ", "url": source_url},
        )
        assert blank_scope.status_code == 302
        assert parse_qs(urlsplit(blank_scope.headers["Location"]).query)["viewer_user_id"] == [
            "owner-user"
        ]

        legacy = client.get(
            "/recipe/edit",
            query_string={"user_id": "owner-user", "url": source_url},
        )
        assert legacy.status_code == 302
        legacy_query = parse_qs(urlsplit(legacy.headers["Location"]).query)
        assert legacy_query == {
            "viewer_user_id": ["owner-user"],
            "url": [source_url],
        }
        assert client.get(legacy.headers["Location"]).status_code == 200

        mismatch = client.get(
            "/recipe/edit",
            query_string={"viewer_user_id": "other-user", "url": source_url},
        )
        duplicate_scope = client.get(
            "/recipe/edit",
            query_string=[
                ("viewer_user_id", "owner-user"),
                ("viewer_user_id", "other-user"),
                ("url", source_url),
            ],
        )
        duplicate_legacy_scope = client.get(
            "/recipe/edit",
            query_string=[
                ("user_id", "owner-user"),
                ("user_id", "owner-user"),
                ("url", source_url),
            ],
        )
        conflicting_scope = client.get(
            "/recipe/edit",
            query_string={
                "viewer_user_id": "owner-user",
                "user_id": "other-user",
                "url": source_url,
            },
        )
        missing_url = client.get(
            "/recipe/edit",
            query_string={"viewer_user_id": "owner-user"},
        )

        assert mismatch.status_code == 403
        assert mismatch.headers["Cache-Control"] == "private, no-store"
        assert "owner-user" not in mismatch.get_data(as_text=True)
        assert "other-user" not in mismatch.get_data(as_text=True)
        assert duplicate_scope.status_code == 400
        assert duplicate_scope.headers["Cache-Control"] == "private, no-store"
        assert duplicate_legacy_scope.status_code == 400
        assert conflicting_scope.status_code == 400
        assert missing_url.status_code == 400
        assert missing_url.headers["Cache-Control"] == "private, no-store"

        with client.session_transaction() as session:
            session.clear()
        anonymous = client.get(
            "/recipe/edit",
            query_string={"viewer_user_id": "owner-user", "url": source_url},
        )

    assert anonymous.status_code == 302
    assert anonymous.headers["Location"].endswith("/#userAccountSection")


def test_recipe_edit_page_url_builder_retains_user_scope_after_navigation_and_save():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    editor_page = (ROOT / "PushShoppingList/templates/recipe_edit_page.html").read_text(
        encoding="utf-8",
    )
    helper = script[
        script.index("function recipeEditPageUrl"):
        script.index("function recipeEditPendingActionFromOptions")
    ]
    save_identity = script[
        script.index("function updateRecipeEditorSavedIdentity"):
        script.index("function normalizeRecipeEditorCoverImage")
    ]

    assert "withCanonicalViewerUserId" in helper
    assert "removeLegacyUserId: true" in helper
    assert 'url.searchParams.set("url", normalizedUrl);' in helper
    assert "dataset.userId" not in helper
    assert 'data-viewer-user-id="{{ current_user.user_id if current_user else \'\' }}"' in editor_page
    assert "recipeEditPageUrl(savedSourceUrl)" in save_identity
    assert script.count("/recipe/edit?url=") == 0


def test_recipe_editor_has_store_section_review_controls():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert "Store Sections" in template
    assert "Preview Store Sections" in template
    assert "Apply Store Sections" in template
    assert "reviewRecipeStoreSections(this, { apply: false })" in template
    assert "reviewRecipeStoreSections(this, { apply: true })" in template
    assert "function reviewRecipeStoreSections" in script
    assert "function applyRecipeStoreSectionReviewToEditor" in script
    assert 'fetch("/api/recipe/review_store_sections"' in script
    assert '@recipe_bp.route("/api/recipe/review_store_sections", methods=["POST"])' in routes


def test_recipe_editor_view_defaults_to_table_and_restores_and_saves_the_existing_preference():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the ingredient view preference regression harness.")

    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    preference_start = script.index("function normalizeRecipeEditIngredientView(value)")
    preference_end = script.index("function addEmptyRecipeIngredientRow()", preference_start)
    harness = r"""
const RECIPE_EDIT_INGREDIENT_VIEW_STORAGE_KEY = "ai-pantry-ingredient-view";
const RECIPE_EDIT_INGREDIENT_VIEWS = new Set(["recipe", "smart", "table"]);
let storedValue = null;
const writes = [];
const window = {
    localStorage: {
        getItem(key) {
            if (key !== RECIPE_EDIT_INGREDIENT_VIEW_STORAGE_KEY) throw new Error("unexpected key");
            return storedValue;
        },
        setItem(key, value) {
            writes.push([key, value]);
            storedValue = value;
        },
    },
};
""" + script[preference_start:preference_end] + r"""
const defaultView = loadRecipeEditIngredientView();
storedValue = "smart";
const savedView = loadRecipeEditIngredientView();
storedValue = "unsupported";
const invalidView = loadRecipeEditIngredientView();
saveRecipeEditIngredientView("recipe");
process.stdout.write(JSON.stringify({ defaultView, savedView, invalidView, storedValue, writes }));
"""
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "defaultView": "table",
        "savedView": "smart",
        "invalidView": "table",
        "storedValue": "recipe",
        "writes": [["ai-pantry-ingredient-view", "recipe"]],
    }


def test_recipe_editor_ingredient_views_share_the_existing_table_and_phase_two_recipe_projection():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    ingredient_start = template.index('id="recipeEditPanelIngredients"')
    ingredient_end = template.index('id="recipeEditPanelEquipment"', ingredient_start)
    ingredient_section = template[ingredient_start:ingredient_end]
    tab_bar_start = template.index('class="recipe-edit-tab-bar"')
    tab_bar_end = template.index('class="recipe-edit-tab-panels"', tab_bar_start)
    tab_bar = template[tab_bar_start:tab_bar_end]
    switch_start = script.index("function setRecipeEditIngredientView(value, options = {})")
    switch_end = script.index("function recipeEditIngredientViewMenuItems", switch_start)
    switch_function = script[switch_start:switch_end]
    collect_start = script.index("function collectRecipeIngredientRows()")
    collect_end = script.index("function collectRecipeNutritionRows()", collect_start)
    collect_function = script[collect_start:collect_end]

    assert 'role="tablist"' in tab_bar
    assert 'aria-label="Ingredient view"' not in tab_bar
    assert "recipe-edit-ingredient-view-switcher" not in tab_bar
    assert 'data-recipe-ingredient-view-trigger' in ingredient_section
    assert 'aria-haspopup="menu"' in ingredient_section
    assert 'data-recipe-ingredient-view-menu' in ingredient_section
    assert 'role="menu"' in ingredient_section
    for view in ("recipe", "smart", "table"):
        assert f'data-recipe-ingredient-view-option="{view}"' in ingredient_section
        assert f'data-recipe-ingredient-view-panel="{view}"' in ingredient_section
        assert f'aria-label="{view.title()} ingredient view"' in ingredient_section
    assert ingredient_section.count('role="menuitemradio"') == 3
    assert ingredient_section.count('aria-checked="true"') == 1
    assert ingredient_section.count('id="recipeEditIngredients"') == 1
    assert "Recipe View will be implemented in Phase 2." not in ingredient_section
    assert "Smart View will be implemented in Phase 3." not in ingredient_section
    assert 'id="recipeEditIngredientRecipeList"' in ingredient_section
    assert "data-recipe-ingredient-recipe-empty" in ingredient_section
    assert 'id="recipeEditIngredientSmartGrid"' in ingredient_section
    assert "data-recipe-ingredient-smart-empty" in ingredient_section
    assert "No ingredients yet." in ingredient_section
    assert ingredient_section.count("data-recipe-ingredient-recipe-add") == 1
    assert ingredient_section.count("data-recipe-ingredient-smart-add") == 1
    assert "data-recipe-ingredient-table-action" in ingredient_section
    assert ingredient_section.count("addRecipeIngredientFromCurrentView()") == 6

    assert 'const RECIPE_EDIT_INGREDIENT_VIEW_STORAGE_KEY = "ai-pantry-ingredient-view";' in script
    assert 'new Set(["recipe", "smart", "table"])' in script
    assert 'let recipeEditIngredientView = "table";' in script
    assert "function initRecipeEditIngredientViews()" in script
    assert "function addEmptyRecipeIngredientRow()" in script
    assert script.count("addEmptyRecipeIngredientRow();") == 2
    assert 'if (recipeEditIngredientView === "table")' in script
    assert "addRecipeIngredientRow({}, { expanded: false });" in script
    assert 'menu.querySelectorAll("[data-recipe-ingredient-view-option]")' in switch_function
    assert 'option.setAttribute("aria-checked", selected ? "true" : "false");' in switch_function
    assert 'panel.hidden = panel.dataset.recipeIngredientViewPanel !== view;' in switch_function
    assert "syncRecipeEditIngredientViewActions(section, view);" in switch_function
    assert 'view === "smart"' in switch_function
    assert "renderRecipeIngredientSmartView();" in switch_function
    assert "populateRecipeEditor" not in switch_function
    assert "fetch(" not in switch_function
    assert ".innerHTML" not in switch_function

    assert "return recipeEditIngredientRows()" in collect_function
    assert 'document.getElementById("recipeEditIngredients")' in script
    assert ".recipe-edit-ingredient-view-menu" in css
    assert '[role="menuitemradio"]:focus-visible' in css
    assert "[data-recipe-ingredient-table-action][hidden]" in css


def test_recipe_editor_phase_two_recipe_view_reuses_shared_rows_handlers_and_option_groups():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    render_start = script.index("function renderRecipeIngredientRecipeView()")
    render_end = script.index("function toggleRecipeIngredientRecipeView", render_start)
    render = script[render_start:render_end]
    item_start = script.index("function renderRecipeIngredientRecipeViewItem(")
    item_end = script.index("function renderRecipeIngredientRecipeView()", item_start)
    item = script[item_start:item_end]
    groups_start = script.index("function recipeIngredientRecipeViewChoiceGroups")
    groups_end = script.index("function createRecipeIngredientRecipeViewItem", groups_start)
    groups = script[groups_start:groups_end]
    model_start = script.index("function recipeIngredientPresentationModel")
    model_end = script.index("function recipeIngredientRecipeViewChoiceGroups", model_start)
    model = script[model_start:model_end]
    toggle_start = script.index("function toggleRecipeIngredientRecipeView")
    toggle_end = script.index("function editRecipeIngredientFromRecipeView", toggle_start)
    toggle = script[toggle_start:toggle_end]
    edit_start = toggle_end
    edit_end = script.index("function setRecipeEditIngredientView", edit_start)
    edit = script[edit_start:edit_end]

    assert "recipeEditIngredientRows().map(row =>" in render
    assert "fieldValuesFromRow(row)" in render
    assert "recipeIngredientSubstitutionDomGroups(" in render
    assert "ensureRecipeIngredientExpansionId(row)" in render
    assert "existingItems.get(key)" in render
    assert "list.appendChild(item)" in render
    assert "fetch(" not in render
    assert "recipeViewIngredients" not in script

    assert "recipeIngredientViewAmount(values)" in item
    assert "recipeIngredientViewName(values, hasChoices)" in item
    assert "recipeIngredientRecipeViewStatus(row, values)" in script
    assert "recipeIngredientMeaningfulBuyAs(values)" in script
    assert "StoreSectionBadge.create" in script
    assert 'edit.setAttribute("aria-label", `Edit ${name || "ingredient"}`);' in item
    assert 'disclosure.setAttribute("aria-expanded", String(expanded));' in item
    assert 'disclosure.setAttribute("aria-controls", choices?.id || "");' in item

    assert "recipeIngredientPresentationModel(" in groups
    assert "groups: presentation.groups" in groups
    assert "selectedChoice: presentation.selectedChoice" in groups
    assert "recipeIngredientCompactChoiceSummary(parentValues, alternativeGroups)" in model
    assert "recipeIngredientSelectedChoice(" in model
    assert "group.rows.map(fieldValuesFromRow)" in model
    assert "group.values.forEach(values =>" in script
    assert "label.textContent = recipeIngredientOptionTypeLabel(group.isDefaultOption);" in script
    assert "recipeIngredientChoiceItemSummary(" in script
    assert "recipeEditExpandedRecipeViewIngredientIds" in toggle
    assert "scrollIntoView" not in toggle
    assert "scrollTop" not in toggle
    assert "setRecipeIngredientEditMode(row, true, { trigger: button })" in edit
    assert 'setRecipeEditIngredientView("table", { persist: false });' in edit
    assert "function addRecipeIngredientFromCurrentView()" in edit
    assert "return addRecipeIngredientRow({}, { expanded: true });" in edit
    modal_start = script.index("function setRecipeIngredientEditMode")
    modal_end = script.index("function saveRecipeIngredientInlineEdit", modal_start)
    modal = script[modal_start:modal_end]
    assert "const returnView = recipeEditIngredientModalReturnView;" in modal
    assert "setRecipeEditIngredientView(returnView, { persist: false });" in modal

    assert "renderRecipeIngredientRecipeView();" in script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    assert "renderRecipeIngredientRecipeView();" in script[
        script.index("function updateRecipeIngredientRowIndexes"):
        script.index("function toggleRecipeEditRowMenu")
    ]
    assert "Ingredient editor v81: compact recipe-style ingredient list." in css
    assert "Ingredient editor v83: align Recipe view metadata into orderly desktop columns." in css


def test_edit_ingredient_modal_exposes_the_shared_option_group():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    modal_start = script.index("function organizeRecipeEditIngredientRow")
    modal_end = script.index("function setRecipeIngredientEditMode", modal_start)
    modal = script[modal_start:modal_end]
    sync_start = script.index("function recipeIngredientChoiceParentValues")
    sync_end = script.index("function setActiveRecipeIngredientModalSection", sync_start)
    sync = script[sync_start:sync_end]
    add_start = script.index("function addRecipeIngredientSubstitutionRow")
    add_end = script.index("function removeRecipeIngredientSubstitutionRow", add_start)
    add = script[add_start:add_end]
    inline_start = script.index("function recipeIngredientInlineEditorSourceRow")
    inline_end = script.index("function syncRecipeIngredientInlineEditor", inline_start)
    inline = script[inline_start:inline_end]

    assert 'data-recipe-ingredient-modal-nav="options"' in modal
    assert "Options <span data-recipe-ingredient-modal-options-count>(0)</span>" in modal
    assert modal.index('data-recipe-ingredient-modal-nav="options"') < modal.index(
        'data-recipe-ingredient-modal-nav="quantity"'
    )
    assert 'data-recipe-ingredient-modal-section="options"' in modal
    assert "Choose one option for this ingredient." in modal
    assert "data-recipe-ingredient-modal-options-toggle" in modal
    assert 'aria-expanded="false"' in modal
    assert 'aria-controls="${modalOptionsBodyId}"' in modal
    assert "data-recipe-ingredient-modal-options-summary" in modal
    assert "data-recipe-ingredient-modal-selected-option" in modal
    assert 'aria-label="Selected option editor"' in modal
    assert "data-recipe-ingredient-modal-options-body" in modal
    assert "data-recipe-ingredient-modal-options-slot" in modal

    assert "function recipeIngredientModalOptionsSummary(row)" in sync
    assert "function recipeIngredientModalOptionSelection(row, summary)" in sync
    assert "function renderRecipeIngredientModalOptionSelection(summaryElement, selection)" in sync
    assert "function recipeIngredientModalSelectedOptionSummary(valuesList = [])" in sync
    assert "function createRecipeIngredientModalSelectedOptionRow(" in sync
    assert "function renderRecipeIngredientModalSelectedOptionPreview(panel, selection, optionCount)" in sync
    assert "function setRecipeIngredientModalOptionsExpanded(panel, expanded, options = {})" in sync
    assert "function toggleRecipeIngredientModalOptions(button)" in sync
    assert "body.hidden = !shouldExpand;" in sync
    assert 'toggle.setAttribute("aria-expanded", String(shouldExpand));' in sync
    assert "selection.needsAttention || recipeEditIngredientModalOptionsExpanded" in sync
    assert 'label: `Selected option ingredients: ${ingredients.join(" + ")}`' in sync
    assert "values: selectedChoice.values || []" in sync
    assert "rows: selectedRows" in sync
    assert "optionLabel: selectedChoice.selectionLabel" in sync
    assert "groupTitle," in sync
    assert "const item = createRecipeIngredientOptionRowSummary(" in sync
    assert '"recipe-edit-selected-option-line-item recipe-edit-ingredient-modal-selected-option-row"' in sync
    assert "updateRecipeIngredientOptionRowSummary(item, targetRow, values" in sync
    assert 'label.textContent = String(selection.optionLabel || selection.prefix || "Selected option");' in sync
    assert 'summary.textContent = String(selection.groupTitle || "").trim()' in sync
    assert 'list.setAttribute("aria-label", `${label.textContent} ingredients`);' in sync
    assert "function createRecipeIngredientModalSelectedOptionColumns()" in sync
    assert 'columns.className = "recipe-edit-ingredient-modal-selected-option-columns recipe-edit-ingredient-table-grid";' in sync
    assert "function ensureRecipeIngredientModalOptionsTableHeader(container)" in sync
    assert 'header.className = "recipe-edit-ingredient-modal-options-table-header recipe-edit-ingredient-table-grid";' in sync
    assert 'header.dataset.recipeIngredientModalOptionsTableHeader = "";' in sync
    assert "decorateRecipeEditIngredientColumnHeaders(" not in sync
    assert "recipe-edit-ingredient-table-head" not in sync
    assert "ensureRecipeIngredientModalOptionsTableHeader(summary.container);" in sync
    assert ".recipe-edit-ingredient-modal-options-table-header > [data-ingredient-column]" in script
    assert "syncRecipeIngredientModalDefaultOptionControls(row, panel, summary.container);\n    applyRecipeEditIngredientColumnLayout();" in sync
    for column_key, column_name in (
        ("media", "Drag / Image"),
        ("ingredient", "Ingredient"),
        ("status", "Status"),
        ("quantity", "Quantity"),
        ("unit", "Unit"),
        ("size", "Size"),
        ("store", "Store Section"),
        ("type", "Type"),
        ("alternatives", "Alternatives"),
        ("actions", "Actions"),
    ):
        assert f'["{column_key}", "{column_name}"' in sync
    assert "function createRecipeIngredientModalSelectedOptionControl(" in sync
    assert "function bindRecipeIngredientModalSelectedOptionPicker(control, fieldName)" in sync
    assert "bindRecipeIngredientUnitPickerTrigger(control);" in sync
    assert "ensureRecipeIngredientInlineStoreSectionTrigger(control, control)" in sync
    assert "ensureRecipeIngredientInlineTypeTrigger(control, control)" in sync
    assert 'trigger.classList.add("recipe-edit-ingredient-modal-selected-option-picker");' in sync
    assert 'bindRecipeIngredientModalSelectedOptionPicker(unitControl, "unit");' in sync
    assert 'bindRecipeIngredientModalSelectedOptionPicker(storeControl, "store_section");' in sync
    assert 'bindRecipeIngredientModalSelectedOptionPicker(typeControl, "section");' in sync
    assert 'select[data-recipe-ingredient-modal-selected-option-field="store_section"]' in script
    assert 'select[data-recipe-ingredient-modal-selected-option-field="section"]' in script
    assert "recipeIngredientModalSelectedOptionTargetRow(" in sync
    assert "control.dataset.recipeIngredientModalSelectedOptionField = fieldName;" in sync
    assert "control.recipeIngredientMasterTargetRow = targetRow;" in sync
    assert '["ingredient", "purchasable_item"].includes(fieldName)' in sync
    assert "control.dataset.recipeIngredientMasterField = fieldName;" in sync
    assert "bindRecipeIngredientMasterPicker(control);" in sync
    for field_name in (
        "ingredient",
        "preparation",
        "purchasable_item",
        "quantity",
        "unit",
        "size",
        "store_section",
        "section",
    ):
        assert f'"{field_name}"' in sync
    assert "valuesList.forEach((values, index) =>" in sync
    assert "valuesList.slice(0, 3)" not in sync
    assert '${options.optionCount || 1} option${options.optionCount === 1 ? "" : "s"}' in sync
    assert 'class="recipe-edit-ingredient-options-chevron"' in sync
    assert "heading.appendChild(headingCopy);" in sync
    assert 'preview.hidden = shouldExpand || preview.dataset.hasContent !== "true";' in sync
    assert "hasChoiceGroup: optionCount > 1" in sync
    assert "isAvailable: optionCount > 0" in sync
    assert "const optionCount = groups.length + (hasExplicitDefault ? 0 : 1);" in sync
    assert "function restoreRecipeIngredientModalOptions(panel)" in sync
    assert "slot.appendChild(summary.container);" in sync
    assert 'summary.container.classList.add("recipe-edit-ingredient-modal-options-panel")' in sync
    assert "syncRecipeIngredientModalDefaultOptionControls(row, panel, summary.container);" in sync
    assert 'control?.closest("[data-ingredient-choice-overview]")' in inline
    assert "if (panel?.recipeIngredientOptionSourceRow)" in inline
    assert "return null;" in inline
    assert "return fallbackRow;" in inline

    assert 'container.closest("[data-recipe-ingredient-modal-options-slot]")' in add
    assert "setRecipeIngredientSubstitutionsExpanded(row, optionsButton || button, true);" in add
    assert "function openRecipeIngredientDefaultOptionModal(control)" in script
    assert "function openRecipeIngredientOptionModal(control, options = {})" in script
    assert 'data-recipe-ingredient-default-edit onclick="return openRecipeIngredientDefaultOptionModal(this)"' in script
    assert 'editPanel.querySelector(".recipe-edit-ingredient-match-details[data-ingredient-match-details]")' in script
    assert 'alternativeGroups.length || row.classList.contains("is-editing")' in script

    modal_css = css[css.index("/* Ingredient editor v84:"):]
    assert ".recipe-edit-ingredient-modal-section.is-options" in modal_css
    assert ".recipe-edit-ingredient-modal-options-panel" in modal_css
    assert ".recipe-edit-ingredient-choice-overview.is-editing-another-option" in modal_css
    assert ".recipe-edit-ingredient-modal-options-toggle" in css
    assert ".recipe-edit-ingredient-modal-options-summary.is-warning" in css
    assert ".recipe-edit-ingredient-modal-selected-option-heading" in css
    assert ".recipe-edit-ingredient-modal-selected-option-row" in css
    assert ".recipe-edit-ingredient-modal-selected-option-columns" in css
    assert ".recipe-edit-ingredient-modal-selected-option-column-amount" in css
    assert ".recipe-edit-ingredient-modal-options-table-header" in css
    assert ".recipe-edit-ingredient-modal-selected-option-image" in css
    assert ".recipe-edit-ingredient-modal-selected-option-store" in css
    assert "Ingredient modal options v95: mirror the saved option-group hierarchy while keeping fields editable." in css
    assert "Ingredient modal options v96: expose Ingredient Master Data as a searchable dropdown." in css
    assert "Ingredient modal options v97: use the recipe table's columns, controls, and actions." in css
    assert "Ingredient modal options v99: modal labels follow column layout without table controls." in css
    assert "[data-recipe-edit-ingredient-master-trigger]" in css
    assert ".recipe-edit-ingredient-modal-selected-option-control" in css
    assert '.recipe-edit-ingredient-modal-selected-option-control[aria-invalid="true"]' in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "border: 1px solid transparent;" in css
    assert ".recipe-edit-ingredient-modal-section.is-options.is-collapsed" in css
    assert ".recipe-edit-ingredient-modal-options-body[hidden]" in css
    assert "@media (max-width: 760px)" in modal_css
    assert ".recipe-edit-ingredient-recipe-item" in css
    inline_css = css[css.index("Ingredient editor v83:"):]
    assert "grid-template-columns:" in inline_css
    assert "text-overflow: ellipsis;" in inline_css
    assert ".recipe-edit-ingredient-recipe-secondary" in inline_css
    assert "grid-column: 3;" in inline_css
    assert "grid-column: 5;" in inline_css
    assert "grid-column: 7;" in inline_css
    assert "overflow-x: clip;" in css
    assert ".recipe-edit-ingredient-recipe-disclosure:focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_edit_ingredient_modal_selected_option_edits_are_transactional():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    snapshots = script[
        script.index("function recipeIngredientModalHasChanges"):
        script.index("function setRecipeIngredientModalStatus")
    ]
    validation = script[
        script.index("function validateRecipeIngredientModal"):
        script.index("function recipeIngredientModalPersistedIndex")
    ]
    commit = script[
        script.index("async function commitRecipeIngredientModal"):
        script.index("const RECIPE_EDIT_INGREDIENT_GRID_CELL_ORDER")
    ]
    option_close = script[
        script.index("function closeRecipeIngredientOptionModal"):
        script.index("function openRecipeIngredientDefaultOptionModal")
    ]
    edit_mode = script[
        script.index("function setRecipeIngredientEditMode"):
        script.index("function saveRecipeIngredientInlineEdit")
    ]

    assert "recipeIngredientModalSelectedOptionHasChanges(panel)" in snapshots
    assert "function ensureRecipeIngredientModalSelectedOptionSnapshot" in snapshots
    assert "panel.recipeIngredientModalSelectedOptionSnapshots = new Map();" in snapshots
    assert "function finishRecipeIngredientModalSelectedOptionEdits" in snapshots
    assert "restoreRecipeIngredientEditableFieldSnapshot(sourceRow, snapshot);" in snapshots
    assert '[data-recipe-ingredient-modal-selected-option-field="ingredient"]' in validation
    assert '[data-recipe-ingredient-modal-selected-option-field="unit"]' in validation
    assert "finishRecipeIngredientModalSelectedOptionEdits(panel);" in commit
    assert "restore: !options.commit" in option_close
    assert "delete panel.recipeIngredientModalSelectedOptionSnapshots;" in edit_mode
    assert "restore: Boolean(options.restore)" in edit_mode


def test_edit_ingredient_modal_options_open_for_navigation_edits_and_errors():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    navigation_start = script.index("function navigateRecipeIngredientModalSection")
    navigation_end = script.index("function toggleRecipeIngredientModalAnalysis", navigation_start)
    navigation = script[navigation_start:navigation_end]
    errors_start = script.index("function applyRecipeIngredientModalServerErrors")
    errors_end = script.index("function applySavedRecipeIngredientToModalRow", errors_start)
    errors = script[errors_start:errors_end]

    assert 'button.dataset.recipeIngredientModalNav === "options"' in navigation
    assert "setRecipeIngredientModalOptionsExpanded(panel, true" in navigation
    assert "remember: true" in navigation
    assert "scroll: true" in navigation
    assert '/option|alternative|substitution|selection/i.test(String(path || ""))' in errors
    assert "if (hasOptionsError)" in errors
    assert "setRecipeIngredientModalOptionsExpanded(panel, true" in errors

    for function_name in (
        "openRecipeIngredientDefaultOptionModal",
        "openRecipeIngredientOptionModal",
        "setRecipeIngredientAlternativeEditMode",
        "addRecipeIngredientAlternativeComponent",
        "addRecipeIngredientDefaultComponent",
        "addRecipeIngredientSubstitutionRow",
    ):
        start = script.index(f"function {function_name}")
        next_function = script.find("\nfunction ", start + 10)
        function_source = script[start:next_function if next_function >= 0 else None]
        assert "ensureRecipeIngredientModalOptionsExpanded(" in function_source


def test_mobile_saved_multi_ingredient_choice_rows_do_not_share_grid_cells_or_hide_images():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    mobile_choice_css = css[css.index("/* Ingredient editor v88:"):]
    option_summary = script[
        script.index("function createRecipeIngredientOptionRowSummary"):
        script.index("const RECIPE_INGREDIENT_EDIT_TOOLTIP_ID")
    ]
    update_summary = script[
        script.index("function updateRecipeIngredientOptionRowSummary"):
        script.index("function updateRecipeIngredientAlternativeComponentSummary")
    ]

    assert "@media (max-width: 767px)" in mobile_choice_css
    assert ".recipe-edit-selected-option-line-item.recipe-edit-ingredient-table-grid" in mobile_choice_css
    assert "display: grid !important;" in mobile_choice_css
    assert "grid-auto-rows: auto;" in mobile_choice_css
    assert "> .recipe-edit-ingredient-substitution-cell::before" in mobile_choice_css
    assert "content: none !important;" in mobile_choice_css
    assert "grid-template-columns: 40px minmax(0, 1fr) max-content 96px !important;" in mobile_choice_css
    assert "gap: 5px 6px !important;" in mobile_choice_css
    assert "width: calc(100% + 20px);" in mobile_choice_css
    assert "max-width: none !important;" in mobile_choice_css
    assert "margin-inline: -10px;" in mobile_choice_css
    image_rule = mobile_choice_css[
        mobile_choice_css.index("> .recipe-edit-alternative-component-image-cell {"):
        mobile_choice_css.index("> .recipe-edit-alternative-component-status {")
    ]
    assert "display: flex !important;" in image_rule
    assert "grid-column: 1 !important;" in image_rule
    assert "width: 40px !important;" in image_rule
    assert "height: 40px !important;" in image_rule
    actions_rule = mobile_choice_css[
        mobile_choice_css.index("> .recipe-edit-alternative-component-actions.recipe-edit-compact-row-actions {"):
        mobile_choice_css.rindex("> :is(")
    ]
    assert "grid-column: 4 !important;" in actions_rule
    assert "width: 96px !important;" in actions_rule
    hidden_cells = mobile_choice_css[mobile_choice_css.rindex("> :is("):]
    assert ".recipe-edit-alternative-component-image-cell" not in hidden_cells
    assert 'class="recipe-edit-selected-option-mobile-amount"' in option_summary
    assert "data-selected-option-mobile-amount" in option_summary
    assert 'formatRecipeIngredientQuantityUnit(values)' in update_summary
    assert 'mobileAmountElement.hidden = !hasMobileAmount;' in update_summary
    mobile_amount_rule = mobile_choice_css[
        mobile_choice_css.index("> .recipe-edit-selected-option-mobile-amount:not([hidden]) {"):
        mobile_choice_css.index("> .recipe-edit-alternative-component-actions.recipe-edit-compact-row-actions {")
    ]
    assert "display: block;" in mobile_amount_rule
    assert "grid-column: 3 !important;" in mobile_amount_rule
    assert "white-space: nowrap;" in mobile_amount_rule


def test_mobile_selected_option_block_keeps_header_and_rows_visible_when_collapsed():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    selected_block = script[
        script.index("function ensureRecipeIngredientSelectedOptionBlock"):
        script.index("function organizeRecipeEditSubstitutionOptionRow")
    ]
    atomic_css = css[css.index(
        "/* Ingredient editor v112: every selected ingredient option renders as one atomic block. */"
    ):]

    assert "const activeRows = recipeIngredientSelectedOptionActiveRows(row, selectedChoice);" in selected_block
    assert "const renderedRows = activeRows;" in selected_block
    assert "groupByStoreSection\n        ? projectedRows" not in selected_block
    assert 'block.dataset.ingredientSelectedOptionBlock = "";' in selected_block
    assert 'block.dataset.ingredientOptionBlock = "";' in selected_block
    assert "block.prepend(header);" in selected_block
    assert "ingredientContent: summaries," in selected_block
    assert "actions: [action]," in selected_block
    assert "action.hidden = !expanded;" in selected_block
    assert 'menu.toggleAttribute("inert", !expanded);' in selected_block
    assert "lineItems.hidden = !hasRenderedRows;" in selected_block
    assert "expandedAtSelectedLineItem" not in selected_block
    assert "keepsGroupedSelectedRowsVisible" not in selected_block
    assert '"has-mobile-implicit-default-line-item"' not in selected_block

    assert ".recipe-edit-selected-option-line-items" in atomic_css
    assert "> [data-ingredient-option-header]" in atomic_css
    assert "> [data-ingredient-option-actions][hidden]" in atomic_css
    assert "display: none !important;" in atomic_css
    assert "@media (max-width: 767px)" in atomic_css
    assert "grid-template-rows: auto auto auto auto auto !important;" in atomic_css
    assert "> .recipe-edit-ingredient-mobile-header" in atomic_css
    assert "> .recipe-edit-selected-option-line-items" in atomic_css
    assert "> .recipe-edit-ingredient-options-panel" in atomic_css
    assert "> .recipe-edit-ingredient-preparation-summary" in atomic_css
    assert "> .recipe-edit-ingredient-buy-as-summary" in atomic_css
    for grid_row in range(1, 6):
        assert f"grid-row: {grid_row} !important;" in atomic_css


def test_grouping_toggle_restores_one_canonical_selected_option_block_without_duplicates():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    selected_block = javascript_function_source(
        script,
        "ensureRecipeIngredientSelectedOptionBlock",
    )
    fragments = javascript_function_source(
        script,
        "syncRecipeIngredientColumnViewSectionFragments",
    )
    restore = javascript_function_source(
        script,
        "clearRecipeIngredientColumnViewSectionFragments",
    )
    handler_start = script.index(
        'menu.querySelector("[data-recipe-ingredient-column-view-group-store]")'
    )
    handler_end = script.index(
        'menu.querySelectorAll("[data-recipe-ingredient-column-view-filter]")',
        handler_start,
    )
    handler = script[handler_start:handler_end]

    assert 'block.dataset.ingredientSelectedOptionBlock = "";' in selected_block
    assert 'block.dataset.ingredientOptionBlock = "";' in selected_block
    assert 'block.querySelector(":scope > [data-ingredient-option-header]")' in selected_block
    assert "row.insertBefore(block" in selected_block
    assert "ingredientEntries" in fragments
    assert "cloneNode" not in fragments
    assert "replaceChildren" not in fragments
    assert "home.replaceWith(row);" in restore
    assert "row.recipeIngredientOptionSourceRow" in restore
    assert "recipeIngredientColumnViewPromotedSummary" in restore
    assert "parentRow.recipeIngredientColumnViewCarrierState" in restore
    assert "delete row.recipeIngredientColumnViewHome;" in restore
    assert "captureRecipeIngredientChoiceExpansionState()" in handler
    assert "applyRecipeIngredientColumnView({ announce: true });" in handler
    assert "restoreRecipeIngredientChoiceExpansionState(" in handler
    assert "function createRecipeIngredientColumnViewGroupProjection" not in script
    assert "function syncRecipeIngredientColumnViewGroupProjection" not in script


def test_ingredient_modal_selected_option_header_stays_above_shared_summary_rows():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    placement = css[css.index(
        "/* Ingredient modal options v98: keep preview headers ahead of inherited summary rows. */"
    ):]

    header_rule = placement[placement.index(
        "> .recipe-edit-ingredient-modal-selected-option-columns {"
    ):]
    header_rule = header_rule[:header_rule.index("}")]
    assert "grid-column: 1 / -1 !important;" in header_rule
    assert "grid-row: 1 !important;" in header_rule

    row_rule = placement[placement.index(
        "> .recipe-edit-ingredient-modal-selected-option-row.recipe-edit-ingredient-table-grid {"
    ):]
    row_rule = row_rule[:row_rule.index("}")]
    assert "grid-column: 1 / -1 !important;" in row_rule
    assert "grid-row: auto !important;" in row_rule


def test_ingredient_modal_selected_option_edit_action_is_centered_and_boxed():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    action_css = css[css.index(
        "/* Ingredient modal options v100: center the edit action with the row values. */"
    ):]

    cell_rule = action_css[action_css.index(
        "> .recipe-edit-alternative-component-actions.recipe-edit-compact-row-actions {"
    ):]
    cell_rule = cell_rule[:cell_rule.index("}")]
    assert "height: 32px !important;" in cell_rule
    assert "min-height: 32px !important;" in cell_rule
    assert "align-self: center !important;" in cell_rule
    assert "align-items: center !important;" in cell_rule
    assert "justify-content: center !important;" in cell_rule

    button_rule = action_css[action_css.index(
        "> .recipe-edit-compact-row-edit {"
    ):]
    button_rule = button_rule[:button_rule.index("}")]
    assert "width: 32px !important;" in button_rule
    assert "height: 32px !important;" in button_rule
    assert "border: 1px solid" in button_rule
    assert "background: color-mix(" in button_rule


def test_nested_ingredient_hover_highlights_only_the_visual_row():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = "/* Ingredient editor v104: highlight one visual ingredient row, not its choice group. */"
    hover_css = css[css.index(marker):]
    selected_line_item = script[
        script.index("function createRecipeIngredientSelectedOptionLineItem"):
        script.index("function resizeRecipeIngredientChoiceTitleInput")
    ]

    assert css.index(marker) > css.index("/* Ingredient editor v103:")
    assert '"recipe-edit-selected-option-line-item"' in selected_line_item
    assert 'summary.dataset.ingredientSelectedOptionLineItem = "";' in selected_line_item
    assert 'summary.recipeIngredientChoiceParentRow = row;' in selected_line_item

    parent_start = hover_css.index("> .recipe-edit-ingredient-row:has(")
    parent_rule = hover_css[parent_start:hover_css.index("}", parent_start)]
    assert "> .recipe-edit-selected-option-line-items" in parent_rule
    assert ".recipe-edit-selected-option-line-item:is(:hover, :focus-within)" in parent_rule
    assert "> [data-ingredient-substitutions]" in parent_rule
    assert ".recipe-edit-alternative-component-summary:is(:hover, :focus-within)" in parent_rule
    assert "background: var(--app-surface) !important;" in parent_rule
    assert "box-shadow: none !important;" in parent_rule

    leaf_start = hover_css.index(":is(\n        .recipe-edit-selected-option-line-item,")
    leaf_rule = hover_css[leaf_start:hover_css.index("}", leaf_start)]
    assert ".recipe-edit-alternative-component-summary" in leaf_rule
    assert "):is(:hover, :focus-within)" in leaf_rule
    assert (
        "background: color-mix(in srgb, var(--app-surface-soft) 80%, transparent) !important;"
        in leaf_rule
    )
    assert (
        "box-shadow: inset 3px 0 0 color-mix(in srgb, var(--app-primary) 44%, transparent) !important;"
        in leaf_rule
    )

    single_choice_marker = (
        "/* Ingredient editor v106: selected single-component choices keep the standard active-row strip. */"
    )
    assert css.index(single_choice_marker) > css.index(marker)
    single_choice_css = css[css.index(single_choice_marker):]
    single_choice_start = single_choice_css.index(
        "> .recipe-edit-ingredient-row.has-selected-ingredient-choice:is(:hover, :focus-within) {"
    )
    single_choice_rule = single_choice_css[
        single_choice_start:single_choice_css.index("}", single_choice_start)
    ]
    assert "box-shadow: inset 3px 0 0" in single_choice_rule


def test_ingredient_drag_handles_share_muted_rest_color_across_visual_row_types():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = (
        "/* Ingredient editor v107: every ingredient drag handle shares one row-scoped color contract. */"
    )
    assert css.index(marker) > css.index("/* Ingredient editor v106:")
    handle_css = css[css.index(marker):]
    rest_rule_start = handle_css.index(
        "body.recipe-edit-standalone-page #recipeEditIngredients .recipe-edit-row-handle {"
    )
    rest_rule = handle_css[rest_rule_start:handle_css.index("}", rest_rule_start)]

    assert "color: var(--app-muted) !important;" in rest_rule
    assert "> .recipe-edit-ingredient-row:is(:hover, :focus-within):not(:has(" in handle_css
    assert ".recipe-edit-selected-choice-group-header:is(:hover, :focus-within)" in handle_css
    assert ".recipe-edit-alternative-component-summary:is(:hover, :focus-within)" in handle_css
    assert "> .recipe-edit-alternative-component-handle-cell" in handle_css
    assert "> .recipe-edit-row-handle:not([aria-disabled=\"true\"])" in handle_css


def test_ingredient_drag_handle_brightening_is_local_active_and_disabled_safe():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    marker = (
        "/* Ingredient editor v107: every ingredient drag handle shares one row-scoped color contract. */"
    )
    handle_css = css[
        css.index(marker):
        css.index("/* Edit Recipe hierarchy, borderless cooking summary", css.index(marker))
    ]
    drag_binding = script[
        script.index("function bindRecipeEditDragAndDrop"):
        script.index("function startRecipeEditPointerDrag")
    ]
    pointer_drag = script[
        script.index("function startRecipeEditPointerDrag"):
        script.index("function moveRecipeEditPointerDrag")
    ]
    clear_drag = script[
        script.index("function clearRecipeEditDragState"):
        script.index("function dropRecipeEditRow")
    ]

    assert '> .recipe-edit-selected-option-line-items:is(:hover, :focus-within)' in handle_css
    assert '> [data-ingredient-substitutions]:is(:hover, :focus-within)' in handle_css
    assert ".recipe-edit-drag-handle-active:not([aria-disabled=\"true\"])" in handle_css
    assert "color: var(--app-text-strong) !important;" in handle_css
    assert 'handle.classList.add("recipe-edit-drag-handle-active");' in drag_binding
    assert 'handle.classList.add("recipe-edit-drag-handle-active");' in pointer_drag
    assert 'handle.classList.remove("recipe-edit-drag-handle-active");' in clear_drag

    disabled_start = handle_css.index(
        '.recipe-edit-row-handle[aria-disabled="true"] {'
    )
    disabled_rule = handle_css[disabled_start:handle_css.index("}", disabled_start)]
    assert "color: var(--app-muted) !important;" in disabled_rule
    assert "opacity: .34;" in disabled_rule
    assert "cursor: not-allowed;" in disabled_rule
    assert "background:" not in handle_css
    assert "box-shadow:" not in handle_css


def test_ingredients_table_uses_quiet_logical_group_boundaries():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    marker = "/* Ingredient editor v108: one quiet boundary per complete ingredient group. */"

    assert css.index(marker) > css.index("/* Ingredient editor v107:")
    hierarchy_css = css[css.index(marker):]

    tab_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-tab-bar {"
    )
    tab_rule = hierarchy_css[tab_start:hierarchy_css.index("}", tab_start)]
    assert "border-bottom-color: color-mix(" in tab_rule
    assert "var(--recipe-editor-border-soft) 58%" in tab_rule

    table_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-table-scroll {"
    )
    table_rule = hierarchy_css[table_start:hierarchy_css.index("}", table_start)]
    for declaration in (
        "border: 0;",
        "border-radius: 0;",
        "background: transparent;",
        "box-shadow: none;",
    ):
        assert declaration in table_rule

    viewport_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-table-head-viewport {"
    )
    viewport_rule = hierarchy_css[
        viewport_start:hierarchy_css.index("}", viewport_start)
    ]
    assert "box-shadow: none;" in viewport_rule

    header_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-table-head {"
    )
    header_rule = hierarchy_css[header_start:hierarchy_css.index("}", header_start)]
    assert "border-top: 0;" in header_rule
    assert "border-right: 0;" in header_rule
    assert "border-bottom: 1px solid color-mix(" in header_rule
    assert "var(--recipe-editor-border) 68%" in header_rule
    assert "border-left: 0;" in header_rule

    resize_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-column-resize::before {"
    )
    resize_rule = hierarchy_css[resize_start:hierarchy_css.index("}", resize_start)]
    assert "background: transparent;" in resize_rule
    assert "box-shadow: none;" in resize_rule
    assert "> [data-ingredient-column]:hover" in hierarchy_css
    assert ".recipe-edit-ingredient-column-resize.is-resizing::before" in hierarchy_css
    assert "background: var(--app-primary-hover);" in hierarchy_css

    group_start = hierarchy_css.index(
        "/* Each direct row/projection owns its complete collapsed or expanded logical group. */"
    )
    group_rule_start = hierarchy_css.index("> :is(", group_start)
    group_rule = hierarchy_css[
        group_rule_start:hierarchy_css.index("}", group_rule_start)
    ]
    assert ".recipe-edit-ingredient-row" in group_rule
    assert ".recipe-edit-ingredient-column-group-projection" in group_rule
    assert "border-top: 0 !important;" in group_rule
    assert "border-right: 0 !important;" in group_rule
    assert "border-bottom: 1px solid color-mix(" in group_rule
    assert "var(--recipe-editor-border-soft) 22%" in group_rule
    assert "border-left: 0 !important;" in group_rule
    assert "padding:" not in group_rule
    assert "grid-template" not in group_rule
    assert ":nth-child" not in hierarchy_css
    assert "> .recipe-edit-ingredient-row:is(.is-editing, .recipe-edit-substitutions-open)" in hierarchy_css
    assert "border-left: 2px solid var(--app-primary-hover) !important;" in hierarchy_css

    assert "> .recipe-edit-ingredient-row:hover {" in hierarchy_css
    assert "var(--app-primary-soft) 18%" in hierarchy_css
    assert ".recipe-edit-selected-choice-group-header," in hierarchy_css
    assert ".recipe-edit-selected-option-line-item," in hierarchy_css
    assert ".recipe-edit-ingredient-option-divider," in hierarchy_css
    assert ".recipe-edit-default-option-summary," in hierarchy_css
    assert ".recipe-edit-alternative-component-summary," in hierarchy_css
    assert ".recipe-edit-alternative-edit-footer {" in hierarchy_css
    assert "border-block: 0 !important;" in hierarchy_css
    assert "> .recipe-edit-ingredient-options-panel::before" in hierarchy_css
    assert ".recipe-edit-ingredient-option-group::before" in hierarchy_css
    assert "> .recipe-edit-alternative-card::before" in hierarchy_css
    assert "display: none !important;" in hierarchy_css
    assert "content: none !important;" in hierarchy_css

    assert "@media (forced-colors: active)" in hierarchy_css
    assert "border-bottom-color: CanvasText;" in hierarchy_css
    assert "border-bottom-color: CanvasText !important;" in hierarchy_css
    assert "background: Highlight;" in hierarchy_css
