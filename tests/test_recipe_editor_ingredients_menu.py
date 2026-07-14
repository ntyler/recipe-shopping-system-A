from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


ROOT = Path(__file__).resolve().parents[1]


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
    assert "Show or Hide Images" in ingredient_section
    assert "Thumbnail Size" in ingredient_section
    assert ingredient_section.index("Generate Images") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Regenerate Ingredients") < ingredient_section.index("Food Rules")
    assert ingredient_section.index("Food Rules") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Sort Ingredients") < ingredient_section.index("Show or Hide Images")
    assert ingredient_section.index("Show or Hide Images") < ingredient_section.index("Thumbnail Size")
    assert "generateRecipeImagesFromEditor(this, { imageScope: 'ingredients' })" in ingredient_section
    assert "generateRecipeImagesFromEditor(this, { missingOnly: true, imageScope: 'ingredients' })" in ingredient_section
    assert "regenerateRecipeIngredientsSection(this)" in ingredient_section
    assert "autoSortRecipeIngredients('ingredient')" in ingredient_section
    assert "autoSortRecipeIngredients('store_section')" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'ingredients' })" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'ingredients' })" in ingredient_section
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
    assert "data-ingredient-warning-message" in script
    assert "recipeIngredientFoodReviewPayload(row)" in script
    assert "Accept Fix" in script
    assert "ignoreFoodReviewIssue" in script
    assert "editFoodReviewManually" in script


def test_recipe_editor_ingredient_substitutions_are_wired():
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
    assert "function recipeIngredientSubstitutionOptionRowHtml(option = {}, index = 0)" in script
    assert "recipe-edit-ingredient-substitutions" in row_block
    assert "recipe-edit-substitution-option-row recipe-edit-ingredient-row" in script
    assert "data-ingredient-substitution-list" in row_block
    assert "data-ingredient-substitution-title" in row_block
    assert "Add substitution" in row_block
    assert "Add substitution option" in row_block
    assert 'data-field="substitutions_text"' not in row_block
    assert "bindRecipeIngredientSubstitutionRows(row);" in row_block
    assert "data-ingredient-substitution-count" in row_block
    assert 'badges.push([`${substitutionCount} ${substitutionCount === 1 ? "option" : "alternatives"}`, "substitution"]);' in script
    assert "function recipeEditIngredientRows()" in script
    assert "function collectRecipeIngredientSubstitutionRows(row)" in script
    assert "item.substitutions = collectRecipeIngredientSubstitutionRows(row);" in collect_block
    assert "delete item.substitutions_text;" in collect_block
    assert "const optionRow = input.closest(\"[data-substitution-option-row]\");" in script
    assert ".recipe-edit-ingredient-substitutions" in css
    assert ".recipe-edit-substitution-list" in css
    substitution_grid_start = css.index(".recipe-edit-ingredient-row .recipe-edit-ingredient-substitutions,")
    substitution_grid_end = css.index(".recipe-edit-ingredient-row .recipe-ingredient-image-panel.recipe-edit-row-image-panel", substitution_grid_start)
    substitution_grid_css = css[substitution_grid_start:substitution_grid_end]
    assert "grid-column: 1 / -1;" in substitution_grid_css
    assert "padding-left: calc(28px + 14px + 54px + 14px);" in substitution_grid_css
    parent_thumbnail_option_start = css.index(
        ".recipe-edit-ingredient-row:has(> .recipe-edit-ingredient-name-label > .recipe-ingredient-image-panel"
    )
    parent_thumbnail_option_end = css.index(".recipe-edit-ingredient-row .recipe-ingredient-image-panel,", parent_thumbnail_option_start)
    parent_thumbnail_option_css = css[parent_thumbnail_option_start:parent_thumbnail_option_end]
    assert ".recipe-edit-substitution-option-row.recipe-edit-ingredient-row" in parent_thumbnail_option_css
    assert "grid-template-columns: 28px 54px var(--recipe-edit-thumbnail-slot, 66px) minmax(260px, 1.5fr) minmax(74px, 0.42fr) minmax(100px, 0.52fr) minmax(160px, 0.8fr) minmax(190px, 0.95fr) 94px 40px;" in parent_thumbnail_option_css
    assert ".recipe-edit-ingredient-title-line" in parent_thumbnail_option_css
    assert "grid-column: 4 / 10;" in parent_thumbnail_option_css
    assert "label.recipe-edit-qty-label" in parent_thumbnail_option_css
    assert "grid-column: 5 / 6;" in parent_thumbnail_option_css
    assert "label.recipe-edit-store-section-label" in parent_thumbnail_option_css
    assert "grid-column: 8 / 9;" in parent_thumbnail_option_css
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
    assert 'badges.push([`${substitutionCount} ${substitutionCount === 1 ? "option" : "alternatives"}`, "substitution"]);' in badges

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
        assert label in details

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
    assert "recipeIngredientMatchDetailsHtml(matchItem)" in summary

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


def test_recipe_editor_hide_all_images_keeps_title_image_visible():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    function_start = script.index("function setRecipeEditorImagesVisibleFromMenu")
    function_end = script.index("function recipeEditorImagePanelSelector", function_start)
    function_block = script[function_start:function_end]

    assert "const scope = options.imageScope || options.scope || \"all\";" in function_block
    assert "modal.querySelectorAll(recipeEditorImagePanelSelector(options))" in function_block
    assert "if (!visible && scope === \"all\")" in function_block
    assert "keepRecipeCoverImagesVisible(modal);" in function_block


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


def test_recipe_editor_ingredient_row_menu_is_grouped():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_block = script[row_start:row_end]

    assert 'class="recipe-edit-row-menu recipe-edit-ingredient-row-menu"' in row_block
    assert row_block.count('class="recipe-edit-menu-group"') == 4
    assert 'class="recipe-edit-menu-group recipe-edit-menu-group-danger"' in row_block
    for label in ("Review", "Images", "Row", "Move"):
        assert f'<div class="recipe-edit-menu-group-label">{label}</div>' in row_block
    assert ".recipe-edit-row-menu.recipe-edit-ingredient-row-menu" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group-label" in css
    assert ".recipe-edit-row-menu .recipe-edit-menu-group-danger button.delete" in css


def test_recipe_editor_ingredient_rows_use_compact_table_and_secondary_details():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    tools_start = script.index("function organizeRecipeEditIngredientTools()")
    tools_end = script.index("function organizeRecipeEditEquipmentTools()", tools_start)
    tools = script[tools_start:tools_end]
    assert 'tableScroll.setAttribute("role", "table");' in tools
    assert 'ingredientList.setAttribute("role", "rowgroup");' in tools
    assert tools.count('role="columnheader"') == 11
    assert '<span role="columnheader">Ingredient</span>' in tools
    assert '<span role="columnheader">Match / Status</span>' in tools
    assert '<span role="columnheader">Amount</span>' in tools
    assert '<span role="columnheader">Buy As</span>' in tools
    assert '<span role="columnheader">Store Section</span>' in tools
    assert '<span role="columnheader">Substitutions</span>' in tools
    assert '<span role="columnheader">Actions</span>' in tools
    assert '<span class="sr-only">Drag</span>' in tools
    assert '<span class="sr-only">Image</span>' in tools
    assert "<span>Edit</span>" not in tools
    assert "<span>Delete</span>" not in tools

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'matchStatus.classList.add("recipe-edit-ingredient-match-status");' in organize
    assert 'matchStatus.setAttribute("role", "cell");' in organize
    assert 'primary.className = "recipe-edit-ingredient-primary-fields";' in organize
    assert 'row.querySelector(".recipe-edit-size-inline")' in organize
    assert 'row.querySelector(".recipe-edit-notes-inline")' in organize
    assert 'row.querySelector(".recipe-edit-preparation-inline")' in organize
    assert 'row.querySelector(":scope > .recipe-edit-buy-as-label")' in organize
    assert 'row.querySelector(".recipe-edit-optional-label")' in organize
    assert 'row.querySelector(".recipe-edit-original-text-label")' in organize
    assert 'details.id = `recipeEditIngredientDetails${recipeEditIngredientDetailsId}`;' in organize
    assert 'details.addEventListener("toggle", () => updateRecipeEditIngredientDetailsState(row));' in organize
    assert 'matchDetails.dataset.ingredientMatchDetails = "";' in organize
    assert "recipeIngredientMatchDetailsHtml(recipeIngredientMatchItemFromRow(row))" in organize

    row_start = script.index("function addRecipeIngredientRow")
    row_end = script.index("function bindRecipeIngredientSummaryUpdates", row_start)
    row_markup = script[row_start:row_end]
    assert '<span>Amount</span>' in row_markup
    assert '<span>Store Section</span>' in row_markup
    assert '<textarea data-field="original_text" rows="2" readonly>' in row_markup
    assert 'recipeIngredientBadgesHtml(item, { maxVisible: 2 })' in row_markup
    assert 'data-recipe-edit-ingredient-details-toggle' in script
    assert 'aria-expanded="false"' in script
    assert 'const label = expanded ? "Hide details" : "More details";' in script
    assert 'optionsButton.classList.toggle("is-empty", optionRows.length === 0);' in script

    v5 = css[css.index("/* Ingredient editor v5:"):]
    assert "min-width: 1052px;" in v5
    assert "--recipe-edit-ingredient-grid:" in v5
    assert "minmax(180px, 1.8fr)" in v5
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in v5
    assert "min-height: 64px !important;" in v5
    assert "position: static;" in v5
    assert ".recipe-edit-ingredient-match-status" in v5
    assert "grid-column: 10;" in v5
    assert "grid-column: 3 / 11;" in v5
    assert ".recipe-edit-ingredient-primary-fields" in v5
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in v5
    assert ".recipe-edit-ingredient-options-button.is-empty" in v5
    assert ".recipe-edit-compact-row-details.is-expanded" in v5
    assert "@media (min-width: 761px) and (max-width: 1399px)" in v5
    assert "@media (max-width: 760px)" in v5
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in v5
    assert "grid-column: 1 / -1;" in v5


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

    assert 'label.textContent = optionRows.length ? optionLabel : "No substitutions";' in script
    assert '`${optionRows.length} substitution${optionRows.length === 1 ? "" : "s"}`' in script
    assert "document.body.appendChild(menu);" in script


def test_recipe_editor_substitutions_use_accessible_mini_table_without_losing_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    polish = css[css.index("/* Ingredient editor v6:"):]

    substitution_start = script.index("function organizeRecipeEditSubstitutionOptionRow")
    substitution_end = script.index("function organizeRecipeEditIngredientRow", substitution_start)
    substitution = script[substitution_start:substitution_end]
    details_start = substitution.index("const detailFields = [")
    details_end = substitution.index("].filter(Boolean);", details_start)
    detail_fields = substitution[details_start:details_end]
    assert 'optionRow.setAttribute("role", "row");' in substitution
    assert 'cell.setAttribute("role", "cell")' in substitution
    for first_class_field in (
        "recipe-edit-qty-label",
        "recipe-edit-unit-label",
        "recipe-edit-buy-as-label",
        "recipe-edit-store-section-label",
    ):
        assert first_class_field in substitution
        assert first_class_field not in detail_fields
    assert "preparation," in detail_fields
    assert "optional," in detail_fields
    for secondary_field in (
        "recipe-edit-size-inline",
        "recipe-edit-notes-inline",
        "recipe-edit-original-text-label",
    ):
        assert secondary_field in detail_fields

    organizer_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organizer_end = script.index("function organizeRecipeEditCompactRowActions", organizer_start)
    organizer = script[organizer_start:organizer_end]
    assert 'substitutionTable.setAttribute("role", "table");' in organizer
    assert 'substitutionList.setAttribute("role", "rowgroup");' in organizer
    header_labels = ["Alternative", "Ingredient", "Amount", "Unit", "Buy As", "Store Section", "Actions"]
    header_indexes = [organizer.index(f'<span role="columnheader">{label}</span>') for label in header_labels]
    assert header_indexes == sorted(header_indexes)

    assert "width: min(1080px, calc(100vw - 32px));" in polish
    assert "--recipe-edit-substitution-grid:" in polish
    assert "grid-template-columns: var(--recipe-edit-substitution-grid) !important;" in polish
    assert ".recipe-edit-substitution-view-all" in polish
    assert "border-top: 1px solid var(--app-border-strong);" in polish
    assert "min-width: 1000px;" in polish
    v9 = css[css.index("/* Ingredient editor v9:"):]
    assert "min-width: 1180px;" in v9
    assert ".recipe-edit-ingredient-options-panel .recipe-edit-ingredient-name-label" in v9
    assert ".recipe-edit-ingredient-options-panel .recipe-edit-qty-label { grid-column: 4 !important; grid-row: 1 !important; }" in v9
    assert ".recipe-edit-ingredient-options-panel .recipe-edit-unit-label { grid-column: 5 !important; grid-row: 1 !important; }" in v9
    assert ".recipe-edit-substitution-details[hidden]" in v9
    assert 'label.textContent = optionRows.length ? optionLabel : "No substitutions";' in script
    assert '`${optionRows.length} substitution${optionRows.length === 1 ? "" : "s"}`' in script


def test_recipe_editor_v9_matches_accepted_inline_alternatives_table():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    polish = css[css.index("/* Ingredient editor v9:"):]

    expected_grid = """--recipe-edit-ingredient-grid:
        28px
        52px
        minmax(220px, 1.3fr)
        155px
        72px
        96px
        minmax(150px, 1fr)
        170px
        110px
        150px
        88px;"""
    assert expected_grid in polish
    assert "min-width: 1444px;" in polish
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in polish
    for column in range(5, 10):
        assert f"grid-column: {column} !important;" in polish
    assert "grid-column: 10 !important;" in polish
    assert "grid-column: 11 !important;" in polish
    assert "overflow-x: auto;" in polish

    assert "function toggleRecipeIngredientSubstitutions(button, event = null)" in script
    assert 'otherContainer.hidden = true;' in script
    assert 'button.setAttribute("aria-expanded", String(shouldOpen));' in script
    assert 'row.classList.toggle("recipe-edit-substitutions-open", shouldOpen);' in script
    assert 'const isIngredientRow = label === "ingredient";' in script
    assert 'actions.appendChild(menuWrap);' in script
    assert 'class="recipe-edit-compact-row-delete"' in script
    assert '${isIngredientRow ? "" : `<button type="button"' in script


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
    assert 'recipeEditSvgIcon("basket")' in row
    assert 'data-field="ingredient_image_url"' in row
    assert "recipeIngredientStoreSectionIconName" not in row

    polish = css[css.index("/* Ingredient editor v7:"):]
    assert ".recipe-edit-substitution-thumbnail img" in polish
    assert "object-fit: cover;" in polish
    assert ".recipe-edit-substitution-image-fallback[hidden]" in polish


def test_recipe_editor_substitution_primary_fields_stay_inline_with_wide_ingredient_column():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    assert css.index("/* Ingredient editor v8:") > css.index("/* Ingredient editor v7:")
    polish = css[css.index("/* Ingredient editor v8:"):]

    assert "minmax(320px, 1.9fr)" in polish
    assert "min-width: 1220px;" in polish
    assert "--recipe-edit-substitution-gap: 12px;" in polish
    assert "grid-template-rows: 64px auto;" in polish
    assert "align-items: start;" in polish

    name_start = polish.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-options-panel .recipe-edit-ingredient-name-label {"
    )
    name_end = polish.index("}", name_start)
    name_rule = polish[name_start:name_end]
    assert "grid-column: 2 !important;" in name_rule
    assert "grid-row: 1 !important;" in name_rule
    assert "min-width: 320px;" in name_rule
    assert "justify-self: stretch;" in name_rule

    textarea_start = polish.index(
        'body.recipe-edit-standalone-page .recipe-edit-ingredient-options-panel textarea[data-field="ingredient"] {'
    )
    textarea_end = polish.index("}", textarea_start)
    textarea_rule = polish[textarea_start:textarea_end]
    for rule in (
        "width: 100% !important;",
        "min-width: 0 !important;",
        "height: 40px !important;",
        "overflow-x: auto;",
        "overflow-y: hidden;",
        "white-space: nowrap;",
    ):
        assert rule in textarea_rule

    inline_cells = (
        ".recipe-edit-substitution-match-cell",
        ".recipe-edit-preparation-inline",
        ".recipe-edit-buy-as-label",
        ".recipe-edit-store-section-label",
        ".recipe-edit-optional-label",
        ".recipe-edit-substitution-list .recipe-edit-row-menu-wrap",
    )
    for selector in inline_cells:
        rule_start = polish.index(selector)
        rule_end = polish.index("}", rule_start)
        assert "grid-row: 1 !important;" in polish[rule_start:rule_end]

    organizer_start = script.index("function organizeRecipeEditSubstitutionOptionRow")
    organizer_end = script.index("function organizeRecipeEditIngredientRow", organizer_start)
    organizer = script[organizer_start:organizer_end]
    assert "optionRow.appendChild(details);" in organizer
    assert "name.appendChild(details);" not in organizer

    details_start = polish.index(
        ".recipe-edit-ingredient-options-panel .recipe-edit-substitution-details {"
    )
    details_end = polish.index("}", details_start)
    details_rule = polish[details_start:details_end]
    assert "grid-column: 2 / 9 !important;" in details_rule
    assert "grid-row: 2 !important;" in details_rule
    assert "justify-self: stretch;" in details_rule

    assert "minmax(280px, 1.4fr);" in polish
    assert ".recipe-edit-substitution-detail-fields > *" in polish


def test_recipe_editor_advanced_fields_pair_preparation_and_buy_as():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    polish = css[css.index("/* Ingredient editor v6:"):]

    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in polish
    assert ".recipe-edit-preparation-inline { grid-column: 3; grid-row: 1; }" in polish
    assert ".recipe-edit-buy-as-label { grid-column: 4; grid-row: 1; }" in polish
    assert ".recipe-edit-original-text-label { grid-column: 1 / 4; grid-row: 2; }" in polish
    assert ".recipe-edit-optional-label { grid-column: 4; grid-row: 2; }" in polish
    assert "transition: max-height 180ms ease" in polish
    assert "max-height: 900px;" in polish
    assert "animation: recipe-edit-details-reveal 140ms ease-out;" in polish
    assert "@media (prefers-reduced-motion: reduce)" in polish


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
    assert "function bindRecipeIngredientStoreSectionControls(scope)" in script
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
    assert ".recipe-edit-store-section-icon.is-fish" in css
    assert ".recipe-edit-store-section-icon.is-paw" in css


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
    assert 'addRecipeIngredientRow({}, { expanded: true })' in template
    assert 'data-recipe-equipment-collapse-toggle' in template
    assert "toggleRecipeEquipmentCollapsed(this)" in template
    assert "addRecipeEquipmentRow('', { expanded: true })" in template
    assert "function setRecipeIngredientsCollapsed" in script
    assert "function setRecipeEquipmentCollapsed" in script
    assert "function toggleRecipeEquipmentRowCollapsed" in script
    assert "function isRecipeEquipmentRowCollapsed" in script
    assert script.count("setRecipeIngredientsCollapsed(!recipeEditorStandalonePageIsActive());") == 2
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
    assert "recipe_bp.edit_recipe_page_route" in current_recipes
    assert "recipe_bp.edit_recipe_page_route" in recipe_view
    assert "recipe_bp.edit_recipe_page_route" in cookbooks
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
            query_string={"url": "https://example.com/soup"},
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
