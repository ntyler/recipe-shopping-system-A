from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.services import recipe_edit_service
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
    assert "data-ingredient-warning-message" in script
    assert "recipeIngredientFoodReviewPayload(row)" in script
    assert "Accept Fix" in script
    assert "ignoreFoodReviewIssue" in script
    assert "editFoodReviewManually" in script


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
    assert "Add Alternative" in row_block
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
    assert 'role="columnheader" aria-label="Row actions"' in tools
    assert ">Actions</span>" not in tools
    for removed_header in ("Match / Status", "Amount", "Preparation", "Buy As", "Substitutions"):
        assert f">{removed_header}</span>" not in tools

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'row.classList.add("recipe-edit-read-first-row");' in organize
    assert 'readCell.className = "recipe-edit-ingredient-read-cell";' in organize
    assert 'statusSummary.className = "recipe-edit-ingredient-status-summary";' in organize
    assert "data-ingredient-read-name" in organize
    assert "data-ingredient-read-status" in organize
    assert "data-ingredient-read-buy-as" in organize
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
    assert 'substitutions.setAttribute("aria-colspan", "10");' in organize

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
    assert 'returnFocus.focus({ preventScroll: true });' in edit_mode
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


def test_recipe_editor_ingredient_modal_guards_row_clicks_and_dirty_close_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    row_open = script[
        script.index("function bindRecipeIngredientModalRowOpen"):
        script.index("function setRecipeIngredientEditMode", script.index("function bindRecipeIngredientModalRowOpen"))
    ]
    assert 'row.addEventListener("click", event =>' in row_open
    assert 'row.addEventListener("keydown", event =>' in row_open
    assert 'row.classList.contains("is-editing")' in row_open
    assert 'event.key !== "Enter" && event.key !== " "' in row_open
    for guarded_target in (
        "button, a, input, textarea, select, label, details, summary",
        "[role=button], [role=combobox], [contenteditable=true]",
        ".recipe-edit-row-handle, .recipe-edit-row-menu",
        "[data-recipe-ingredient-edit-panel], [data-ingredient-substitutions]",
    ):
        assert guarded_target in row_open
    assert 'setRecipeIngredientEditMode(row, true, { trigger });' in row_open

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
    assert '.recipe-edit-ingredient-quantity-summary::before {\n        content: "Amount";' in mobile
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
    assert ".recipe-edit-ingredient-store-summary {\n        grid-column: 1 / 4 !important;" in narrow
    assert ".recipe-edit-ingredient-type-summary {\n        grid-column: 1 / 4 !important;" in narrow
    assert ".recipe-edit-ingredient-substitution-cell {\n        grid-column: 1 / 4 !important;" in narrow
    assert ".recipe-edit-ingredient-options-panel {\n        grid-column: 1 / -1 !important;\n        grid-row: 7 !important;" in narrow
    assert 'onclick="moveRecipeEditRow(this, -1)">Move ingredient up</button>' in script
    assert 'onclick="moveRecipeEditRow(this, 1)">Move ingredient down</button>' in script


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

    modal_lightbox = css[css.index(
        "dialog.recipe-edit-ingredient-edit-panel > .recipe-image-lightbox"
    ):]
    modal_lightbox = modal_lightbox[:modal_lightbox.index("}")]
    assert "position: absolute;" in modal_lightbox
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

    shared_active_field_selector = (
        "dialog.recipe-edit-ingredient-edit-panel "
        ".recipe-edit-ingredient-edit-field :is(input, textarea, select):focus,"
    )
    shared_active_field = workspace[workspace.index(shared_active_field_selector):]
    shared_active_field = shared_active_field[:shared_active_field.index("}")]
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

    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in script
    assert '`${alternativeCount} Alternative${alternativeCount === 1 ? "" : "s"}`' in script
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
    for formatting in ("minWidth: 58", "maxWidth: 240", "fallbackWidth: 72"):
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
    ) < row.index('"ingredientStoreSummary", "store_section", "select"')
    assert 'size: "Size"' in row
    assert 'substitutions.setAttribute("aria-colspan", "10");' in row

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


def test_recipe_editor_alternatives_use_read_first_cards_without_losing_edit_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    substitution_start = script.index("function organizeRecipeEditSubstitutionOptionRow")
    substitution_end = script.index("function organizeRecipeEditIngredientRow", substitution_start)
    substitution = script[substitution_start:substitution_end]
    assert 'optionRow.classList.add("recipe-edit-alternative-component");' in substitution
    assert 'summary.className = "recipe-edit-alternative-component-summary";' in substitution
    assert "data-alternative-component-name" in substitution
    assert "data-alternative-component-quantity" in substitution
    assert "data-alternative-component-unit" in substitution
    assert "data-alternative-component-store" in substitution
    assert "data-alternative-component-role" in substitution
    assert "data-alternative-component-metadata" in substitution
    assert "data-alternative-component-buy-as" in substitution
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
    assert "editRecipeIngredientAlternativeComponent(this)" in substitution
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

    card = script[
        script.index("function updateRecipeIngredientAlternativeCard"):
        script.index("function updateRecipeIngredientSubstitutionState")
    ]
    assert 'card.className = "recipe-edit-alternative-card";' in card
    assert "recipe-edit-alternative-card-header" in card
    assert "data-alternative-card-recommendation" in card
    assert "data-alternative-card-title" in card
    assert "data-alternative-card-confidence" in card
    assert "data-alternative-card-name" in card
    assert "data-alternative-card-type" in card
    assert "data-alternative-card-quality" in card
    assert "data-alternative-original-amount" in card
    assert "data-alternative-summary-replacement" in card
    assert "data-alternative-equivalency-original" in card
    assert "data-alternative-equivalency-replacement" in card
    assert "data-alternative-together" in card
    assert "data-alternative-explanation" in card
    assert 'card.classList.toggle("is-single-alternative", singleIngredient);' in card
    assert 'card.classList.toggle("is-multi-alternative", !singleIngredient);' in card
    assert "recipeIngredientAlternativeRecommendation(firstValues, preferred)" in card
    assert "recipeIngredientSubstitutionConfidencePercent(firstValues)" in card
    assert 'confidence.hidden = confidencePercent == null;' in card
    assert 'explanation.textContent = notes || "No substitution notes added.";' in card
    assert 'together.hidden = singleIngredient;' in card
    assert "Replacement Option" not in card
    assert "recipe-edit-alternative-components" in card
    assert ">Original</span>" in card
    assert ">Replace With</span>" in card
    assert ">Equivalent result</span>" in card
    assert ">Why It Works</span>" in card
    assert "Use all ingredients in this group together." in card
    assert "Edit Group" in card
    assert "Duplicate Group" in card
    assert 'aria-label="Edit Group"' in card
    assert 'aria-label="Duplicate Group"' in card
    assert "Delete Group" in card
    assert "Add replacement ingredient" in card
    assert "Add another replacement ingredient" not in card
    assert "editRecipeIngredientAlternativeNotes(this)" in card
    assert "Save Group" in card
    assert ">Cancel</button>" in card
    assert "setRecipeIngredientAlternativePreferred(this)" in card
    assert "duplicateRecipeIngredientAlternative(this)" in card
    assert "recipeIngredientSubstitutionDomGroups(optionRows)" in card
    assert "group.rows.forEach(optionRow => components.appendChild(optionRow));" in card
    assert '<details class="recipe-edit-alternative-explanation-block">' in card
    assert 'class="recipe-edit-alternative-remove"' in card

    v18 = css[css.index("/* Ingredient editor v18:"):]
    assert ".recipe-edit-alternative-card" in v18
    assert ".recipe-edit-alternative-relationship" in v18
    assert ".recipe-edit-alternative-editor" in v18
    assert ".recipe-edit-alternative-equivalency" in v18
    assert ".recipe-edit-alternative-explanation-block" in v18
    assert "grid-template-columns: minmax(180px, 1fr) auto minmax(240px, 1.3fr);" in v18
    assert "grid-template-columns: minmax(90px, .65fr) minmax(130px, .9fr) minmax(130px, .9fr) minmax(180px, 1.25fr);" in v18
    assert "@media (max-width: 1100px)" in v18
    assert "@media (max-width: 760px)" in v18
    v19 = css[css.rindex("/* Ingredient editor v19:"):]
    assert "--recipe-edit-alternative-grid:" in v19
    assert "minmax(240px, 2.5fr)" in v19
    assert "minmax(64px, .62fr)" in v19
    assert "minmax(78px, .72fr)" in v19
    assert ".recipe-edit-alternative-component-quantity" in v19
    assert ".recipe-edit-alternative-component-unit" in v19
    assert ".recipe-edit-alternative-component-store" in v19
    assert ".recipe-edit-alternative-component-type" in v19
    assert ".recipe-edit-alternative-component-actions" in v19
    assert "background: transparent;" in v19
    assert ".is-component-editing > .recipe-edit-alternative-component-edit-grid" in v19
    for aligned_column in (
        "grid-column: 2 !important;",
        "grid-column: 3 !important;",
        "grid-column: 4 !important;",
        "grid-column: 5 !important;",
    ):
        assert aligned_column in v19
    assert ".field-ingredient > .recipe-edit-ingredient-name-label" in v19
    assert "grid-column: 1 !important;" in v19
    assert "grid-row: auto !important;" in v19
    assert "grid-template-columns: minmax(0, 1fr) !important;" in v19
    assert "grid-template-columns: minmax(0, 1fr) auto;" in v19
    assert ".field-ingredient .recipe-edit-ingredient-markers" in v19
    assert "display: flex !important;" in v19
    assert "justify-self: end;" in v19
    assert "justify-content: flex-end;" in v19
    assert 'textarea[data-field="ingredient"]' in v19
    assert "border: 1px solid var(--app-border-strong) !important;" in v19
    assert "background: var(--app-bg-soft) !important;" in v19
    assert ".recipe-edit-alternative-details-hint" in v19
    assert "min-height: 30px;" in v19
    assert ".field-buy-as," in v19
    assert ".recipe-edit-alternative-metadata-inputs" in v19
    mobile_v19 = v19[v19.rindex("@media (max-width: 760px)"):]
    assert "grid-template-rows: minmax(44px, auto) auto auto auto !important;" in mobile_v19
    assert "grid-column: 2 / 5 !important;" in mobile_v19
    assert "grid-column: 4 / 6 !important;" in mobile_v19
    assert "max-width: 100%;" in mobile_v19
    assert ".recipe-edit-alternative-details-hint" in mobile_v19
    assert "display: none;" in mobile_v19
    v10 = css[css.index("/* Ingredient editor v10:"):]
    edit_grid_rule = v10[v10.index(".recipe-edit-alternative-component-edit-grid {"):]
    edit_grid_rule = edit_grid_rule[:edit_grid_rule.index("}")]
    assert "display: none;" in edit_grid_rule


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
    assert 'otherContainer.hidden = true;' in script
    assert 'optionsButton.setAttribute("aria-expanded", String(shouldOpen));' in script
    assert 'row.classList.toggle("recipe-edit-substitutions-open", shouldOpen);' in script
    assert 'const isIngredientRow = label === "ingredient";' in script
    assert 'const editButtonHtml = `' in script
    assert 'const editButtonHtml = isIngredientRow ? "" :' not in script
    assert 'row.setAttribute("aria-label", `Edit ${accessibleName}`);' in script
    assert 'actions.appendChild(menuWrap);' in script
    assert 'class="recipe-edit-compact-row-delete"' in script
    assert '${menuInActions ? "" : `<button type="button"' in script


def test_recipe_editor_replacement_rows_edit_and_duplicate_without_new_save_plumbing():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

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
    assert 'optionsButton.addEventListener("click"' in organizer
    assert 'substitutions.setAttribute("role", "cell");' in organizer
    assert 'substitutions.setAttribute("aria-colspan", "10");' in organizer
    assert "<span data-ingredient-options-label>None</span>" in organizer
    options_button_markup = organizer[
        organizer.index("optionsButton.innerHTML"):
        organizer.index('optionsButton.addEventListener("click"')
    ]
    assert 'recipeEditSvgIcon("chevron-down")' not in options_button_markup
    assert organizer.index("organizeRecipeEditCompactRowActions") < organizer.index("if (substitutions) row.appendChild(substitutions)")

    assert "!optionCount" not in toggle
    assert 'otherContainer.hidden = true;' in toggle
    assert 'container.hidden = !shouldOpen;' in toggle
    assert 'row.classList.toggle("recipe-edit-substitutions-open", shouldOpen);' in toggle
    assert "event.preventDefault();" in toggle
    assert "event.stopPropagation();" in toggle

    assert "optionsButton.disabled = false;" in state
    assert '`${action} alternative groups for ${ingredientName}${tooltip}`' in state
    assert 'empty.hidden = optionRows.length !== 0;' in state
    assert 'addLabel.textContent = "Add Alternative Group";' in state
    assert "No alternatives have been added." in script
    assert "Add a single replacement ingredient or a replacement made from multiple ingredients." in script
    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in state
    assert '`${alternativeCount} Alternative${alternativeCount === 1 ? "" : "s"}`' in state
    assert 'optionsButton.querySelector("[data-ingredient-options-summary]")' in state
    assert "recipeIngredientAlternativeRecommendation" in state
    assert "recipeIngredientSubstitutionConfidencePercent" in state
    assert 'summary.hidden = !replacement;' in state
    assert "ensureRecipeIngredientAlternativeCards(container)" in state
    assert "viewAll.hidden = true;" in state

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-ingredient-options-panel:not([hidden])" in v10
    open_rule = v10[v10.index(".recipe-edit-ingredient-options-panel:not([hidden])"):]
    open_rule = open_rule[:open_rule.index("}")]
    assert "display: grid !important;" in open_rule
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
    assert 'recipeEditSvgIcon("basket")' in row
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
    for field_name in ("ingredient", "preparation", "purchasable_item", "quantity", "unit", "store_section", "section"):
        assert f'data-recipe-ingredient-inline-field="{field_name}"' in organize or (
            f'control.dataset.recipeIngredientInlineField = fieldName' in organize
            and f'"{field_name}"' in organize
        )
    for label in ("Ingredient", "Preparation", "Buy As", "Quantity", "Unit", "Store Section", "Type"):
        assert f'aria-label="{label}"' in organize or f'"{label}"' in organize
    assert 'class="recipe-edit-ingredient-read-details"' in organize
    assert 'class="recipe-edit-ingredient-inline-control recipe-edit-ingredient-inline-preparation"' in organize
    assert 'class="recipe-edit-ingredient-inline-control recipe-edit-ingredient-inline-buy-as"' in organize
    assert 'placeholder="Add preparation"' in organize
    assert 'placeholder="Add buy as"' in organize
    assert 'const source = recipeIngredientDirectField(row, fieldName);' in binding
    assert 'source.dispatchEvent(new Event(eventName, { bubbles: true }));' in binding
    assert 'control.tagName === "SELECT"' in binding
    assert 'control.replaceChildren(...[...source.options].map(option => option.cloneNode(true)));' in script
    assert 'bindRecipeIngredientUnitPickerTrigger(control);' in binding
    assert "function bindRecipeIngredientUnitPickerTrigger(input)" in script
    assert 'input.removeAttribute("list");' in script
    assert 'openRecipeIngredientUnitPicker(input, { showAll: true })' in script
    assert "syncRecipeIngredientInlineEditor(row)" in summary
    assert "readStatus.innerHTML = recipeIngredientReadStatusHtml(matchItem)" in summary
    assert 'const buyAsValue = String(values.purchasable_item || values.buy_as || "").trim();' in summary
    assert "meaningfulBuyAs = recipeIngredientMeaningfulBuyAs(values)" in summary
    assert 'readBuyAs.closest(".recipe-edit-ingredient-read-buy-as")' in summary
    assert "readBuyAsField.hidden = !meaningfulBuyAs;" in summary
    assert "readBuyAs.value = buyAsValue;" in summary
    assert 'readBuyAs.title = meaningfulBuyAs ? `Buy as: ${meaningfulBuyAs}` : "Buy As matches Ingredient Name";' in summary
    assert "previewBuyAs.hidden = !meaningfulBuyAs;" in summary
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
    assert 'return "";' in comparison

    summary = script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    assert 'previewBuyAs.textContent = meaningfulBuyAs ? `Buy as: ${meaningfulBuyAs}` : "";' in summary
    assert "previewBuyAs.hidden = !meaningfulBuyAs;" in summary
    assert "readBuyAsField.hidden = !meaningfulBuyAs;" in summary
    assert 'data-recipe-ingredient-inline-field="purchasable_item"' in script
    assert "recipeIngredientReadStatusHtml(matchItem)" in summary

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-ingredient-read-buy-as > .recipe-edit-ingredient-inline-buy-as" in v10
    assert ".recipe-edit-ingredient-read-separator" in v10


def test_recipe_editor_compact_alternative_cards_cleanup_cancelled_blank_rows():
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

    assert 'options.restore && card.dataset.newAlternative === "1"' in editing
    assert 'card.querySelectorAll("[data-substitution-option-row]").forEach(optionRow => optionRow.remove());' in editing
    assert "card.remove();" in editing
    assert "updateRecipeIngredientSubstitutionState(ingredientRow);" in editing
    assert 'list.hidden = optionRows.length === 0;' in state
    assert 'addLabel.textContent = "Add Alternative Group";' in state
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
    assert ">Add replacement ingredient</span>" in markup


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
    assert ".recipe-edit-ingredient-store-summary > .recipe-edit-store-section-trigger" in css
    assert ".recipe-edit-store-section-menu-list {\n    flex: 1 1 auto;" in css
    assert ".recipe-edit-store-section-icon.is-fish" in css
    assert ".recipe-edit-store-section-icon.is-paw" in css


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
    for color_rule in (
        ".recipe-edit-store-section-icon.is-leaf { color: #4ade80; }",
        ".recipe-edit-store-section-icon.is-dairy { color: #60a5fa; }",
        ".recipe-edit-store-section-icon.is-can { color: #fb923c; }",
        ".recipe-edit-store-section-icon.is-jar { color: #f87171; }",
        ".recipe-edit-store-section-icon.is-oil { color: #fbbf24; }",
    ):
        assert color_rule in css


def test_recipe_editor_type_picker_supports_custom_type_crud_and_drives_optional_state():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'RECIPE_INGREDIENT_CUSTOM_TYPES_KEY = "recipeIngredientCustomTypes"' in script
    assert "const RECIPE_INGREDIENT_BUILT_IN_TYPES = [" in script
    for value in ("main", "optional", "garnish", "topping", "sauce", "substitute"):
        assert f'{{ value: "{value}"' in script
    assert "function recipeIngredientCustomTypeNames()" in script
    assert "function storeRecipeIngredientCustomTypeNames(values)" in script
    assert "function saveRecipeIngredientCustomTypeName(value)" in script
    assert "function replaceRecipeIngredientCustomTypeName(previousValue, nextValue)" in script
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
    assert "`recipe-edit-type-dot${recipeIngredientTypeDotClassModifier(resolvedValue)}`" in script
    assert "if (!custom)" in script
    assert 'data-type-action="add-custom"' in script
    assert 'data-type-action="edit-custom"' in script
    assert 'data-type-action="delete-custom"' in script
    assert "Add custom type…" in script
    assert 'aria-label="Edit custom type ${escapeAttribute(value)}"' in script
    assert 'aria-label="Delete custom type ${escapeAttribute(value)}"' in script
    assert "function addRecipeIngredientCustomType(button)" in script
    assert "function editRecipeIngredientCustomType(button)" in script
    assert "function deleteRecipeIngredientCustomType(button)" in script
    assert "recipeIngredientBuiltInType(currentName)" in script

    replace_start = script.index("function replaceRecipeIngredientCustomTypeName")
    replace_end = script.index("function syncRecipeIngredientTypeControl", replace_start)
    replace = script[replace_start:replace_end]
    assert "document.querySelectorAll('select[data-field=\"section\"]')" in replace
    assert 'select.dispatchEvent(new Event("change", { bubbles: true }));' in replace
    assert 'snapshot.section = replacement;' in replace
    assert 'snapshot.optional = replacement === "optional";' in replace
    assert ': storedNames.find(name => recipeIngredientTypeKey(name) === recipeIngredientTypeKey(nextName)) || "main"' in replace
    assert "Open ingredient rows using it will be changed to Main." in script

    assert "function bindRecipeIngredientTypeControls(scope)" in script
    assert "function createRecipeIngredientTypeTrigger(select, options = {})" in script
    assert "function ensureRecipeIngredientInlineTypeTrigger(control, source)" in script
    assert "trigger.recipeEditTypeSelect = select;" in script
    assert "trigger && trigger.recipeEditTypeSelect" in script
    assert "trigger.dataset.recipeIngredientInlineTypeTrigger" in script
    assert "menu.recipeEditTypeInline" in script
    assert 'trigger.dataset.recipeEditTypeTrigger = "true";' in script
    assert 'trigger.setAttribute("role", "combobox");' in script
    assert 'trigger.setAttribute("aria-controls", "recipeIngredientTypeMenu");' in script
    assert "select.hidden = true;" in script
    assert "bindRecipeIngredientStoreSectionControls(row);\n    bindRecipeIngredientTypeControls(row);" in script
    assert 'optionalInput.checked = recipeIngredientIsOptional({ section: typeSelect.value });' in script
    assert 'item.optional = recipeIngredientIsOptional(item);' in script
    assert 'syncRecipeIngredientTypeControl(input);' in script
    assert 'row.querySelector("[data-recipe-edit-type-trigger]")' in script

    assert "/* Ingredient editor v11: managed custom Type picker. */" in css
    assert ".recipe-edit-type-trigger > [data-type-trigger-label]" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot.is-optional" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot.is-custom" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-custom-row" in css
    assert ".recipe-edit-ingredient-type-summary" in css
    assert ".recipe-edit-ingredient-type-summary > .recipe-edit-type-trigger" in css
    assert 'border: 1px solid transparent;' in css


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
    assert 'mobileQuantitySummary.textContent = quantitySummaryText;' in script
    quantity_unit_formatter = script[
        script.index("function formatRecipeIngredientQuantityUnit"):
        script.index("function formatRecipeIngredientQuantityColumn")
    ]
    assert "values.size" not in quantity_unit_formatter
    assert "recipeIngredientPluralUnit(unit, quantity, { includePieces: true })" in quantity_unit_formatter
    assert 'document.querySelectorAll("[data-recipe-ingredients-collapse-toggle]")' in script
    assert 'compactButton.setAttribute("aria-expanded", String(!collapsed));' in script
    assert "function recipeIngredientsShouldStartCollapsed()" in script
    assert 'window.matchMedia("(max-width: 767px)").matches' in script
    assert 'document.body.classList.contains("screen-preview-mobile-frame")' in script
    assert script.count("setRecipeIngredientsCollapsed(recipeIngredientsShouldStartCollapsed());") == 2

    mobile_start = css.index("/* Ingredient editor v24: real mobile folding for the current card-based layout. */")
    mobile_css = css[mobile_start:]
    assert "@media (max-width: 767px)" in mobile_css
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
