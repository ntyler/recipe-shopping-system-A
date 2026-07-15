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
    assert 'badges.push([`${substitutionCount} ${substitutionCount === 1 ? "option" : "alternatives"}`, "substitution"]);' in script
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
        "Quantity",
        "Store Section",
        "Type",
        "Alternatives",
        "Actions",
    )
    assert tools.count('role="columnheader"') == len(headers)
    positions = [tools.index(f">{header}</span>") for header in headers]
    assert positions == sorted(positions)
    for removed_header in ("Match / Status", "Amount", "Unit", "Preparation", "Buy As", "Substitutions"):
        assert f">{removed_header}</span>" not in tools

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'row.classList.add("recipe-edit-read-first-row");' in organize
    assert 'readCell.className = "recipe-edit-ingredient-read-cell";' in organize
    assert "data-ingredient-read-name" in organize
    assert "data-ingredient-read-status" in organize
    assert "data-ingredient-read-buy-as" in organize
    for summary_class in (
        "recipe-edit-ingredient-quantity-summary",
        "recipe-edit-ingredient-store-summary",
        "recipe-edit-ingredient-type-summary",
    ):
        assert summary_class in organize

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
        ">Quantity</h3>",
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
    assert "The grocery item that should be added to the shopping list." in organize
    assert 'typeLabel.textContent = "Requirement";' in organize
    assert "Previous Ingredient" in organize
    assert "Save Changes" in organize
    assert "Save &amp; Next" in organize
    assert organize.index(">Cancel</button>") < organize.index(">Save Changes</button>")
    assert "optional.hidden = true;" in organize
    assert 'matchDetails.className = "recipe-edit-ingredient-match-details";' in organize
    assert 'matchDetails.dataset.ingredientMatchDetails = "";' in organize
    assert 'typeSelect.value = "optional";' in organize
    assert 'String(typeSelect.value || "").trim().toLowerCase() === "optional"' in organize

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
    assert 'row.classList.contains("is-editing")' in row_open
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
    assert 'event.key === "Escape"' in close_contract
    assert 'event.key !== "Tab"' in close_contract
    assert "focusTarget.focus({ preventScroll: true })" in close_contract

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


def test_recipe_editor_ingredient_modal_navigation_and_busy_state_are_wired():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    navigation = script[
        script.index("function updateRecipeIngredientModalNavigation"):
        script.index("function hideRecipeIngredientDiscardConfirmation")
    ]
    assert "const rows = recipeEditIngredientRows();" in navigation
    assert "previousButton.disabled = index <= 0;" in navigation
    assert 'nextButton.textContent = isFinal ? "Save & Close" : "Save & Next";' in navigation
    assert 'nextButton.dataset.recipeIngredientFinal = isFinal ? "true" : "false";' in navigation
    assert 'panel.toggleAttribute("aria-busy", Boolean(saving));' in navigation
    for selector in (
        "[data-recipe-ingredient-modal-save]",
        "[data-recipe-ingredient-modal-next]",
        "[data-recipe-ingredient-modal-previous]",
        "[data-recipe-ingredient-modal-close]",
    ):
        assert selector in navigation
    assert 'status.textContent = saving ? "Saving ingredient\\u2026" : "";' in navigation

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
    assert 'generateButton.textContent = "Generate with AI";' in image_contract
    assert 'recipeIngredientModalHasImage(imagePanel) ? "Replace Image" : "Add Image"' in image_contract
    assert 'removeButton.textContent = "Remove";' in image_contract
    assert 'slot.appendChild(imagePanel);' in image_contract
    assert "recipeIngredientModalPlaceholder" in image_contract
    assert '"recipe-ingredient-image-prompt-requested"' in image_contract

    organizer = script[
        script.index("function organizeRecipeEditIngredientRow(row)"):
        script.index("function organizeRecipeEditCompactRowActions", script.index("function organizeRecipeEditIngredientRow(row)"))
    ]
    assert 'imagePanel.classList.add("recipe-ingredient-image-prompt-requested");' in organizer
    assert 'data-ingredient-image-generate' in organizer

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
    assert "dialog.recipe-edit-ingredient-edit-panel > .recipe-edit-floating-menu" in modal_css
    assert "z-index: 40 !important;" in modal_css


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

    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in script
    assert '`${alternativeCount} alternative${alternativeCount === 1 ? "" : "s"}`' in script
    assert "document.body.appendChild(menu);" in script


def test_recipe_editor_alternatives_use_read_first_cards_without_losing_edit_fields():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    substitution_start = script.index("function organizeRecipeEditSubstitutionOptionRow")
    substitution_end = script.index("function organizeRecipeEditIngredientRow", substitution_start)
    substitution = script[substitution_start:substitution_end]
    assert 'optionRow.classList.add("recipe-edit-alternative-component");' in substitution
    assert 'summary.className = "recipe-edit-alternative-component-summary";' in substitution
    assert "data-alternative-component-name" in substitution
    assert "data-alternative-component-status" in substitution
    assert "data-alternative-component-facts" in substitution
    assert "data-alternative-component-buy-as" in substitution
    assert 'editGrid.className = "recipe-edit-alternative-component-edit-grid";' in substitution
    assert "[name, quantity, unit, size, quantityText, preparation, buyAs, storeSection, preferred, notes, originalText]" in substitution
    assert "optional.hidden = true;" in substitution
    assert "Remove ingredient" in substitution
    assert "updateRecipeIngredientAlternativeComponentSummary(optionRow);" in substitution

    alternative_markup = script[
        script.index("function recipeIngredientSubstitutionOptionRowHtml"):
        script.index("function recipeIngredientSubstitutionOptionsHtml")
    ]
    assert 'data-field="ingredient_image_url"' in alternative_markup
    assert 'data-field="ingredient_image_generated_at"' in alternative_markup
    assert 'data-field="ingredient_image_prompt"' in alternative_markup

    card = script[
        script.index("function updateRecipeIngredientAlternativeCard"):
        script.index("function updateRecipeIngredientSubstitutionState")
    ]
    assert 'card.className = "recipe-edit-alternative-card";' in card
    assert "recipe-edit-alternative-card-header" in card
    assert "data-alternative-card-title" in card
    assert "data-alternative-card-status" in card
    assert "data-alternative-card-preferred" in card
    assert "data-alternative-card-replaces" in card
    assert 'card.classList.toggle("is-single-alternative", singleIngredient);' in card
    assert "recipeIngredientAlternativeStatusLabel(firstValues)" in card
    assert "replaceSummary.hidden = singleIngredient;" in card
    assert "`Replaces ${parentQuantity" in card
    assert "recipe-edit-alternative-components" in card
    assert "Edit alternative" in card
    assert "Add Replacement Ingredient" in card
    assert "Save Alternative" in card
    assert ">Cancel</button>" in card
    assert "recipeIngredientSubstitutionDomGroups(optionRows)" in card
    assert "group.rows.forEach(optionRow => components.appendChild(optionRow));" in card

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-alternative-card" in v10
    assert ".recipe-edit-alternative-component-summary" in v10
    assert ".recipe-edit-alternative-card:not(.is-editing)" in v10
    assert ".recipe-edit-alternative-card.is-editing" in v10
    assert ".recipe-edit-substitution-table-head" in v10
    assert "display: none !important;" in v10
    edit_grid_rule = v10[v10.index(".recipe-edit-alternative-component-edit-grid {"):]
    edit_grid_rule = edit_grid_rule[:edit_grid_rule.index("}")]
    assert "display: none;" in edit_grid_rule


def test_recipe_editor_v10_prioritizes_seven_readable_read_first_groups():
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
        "74px",
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
    assert "min-width: 860px;" in polish
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
    assert 'actions.appendChild(menuWrap);' in script
    assert 'class="recipe-edit-compact-row-delete"' in script
    assert '${menuInActions ? "" : `<button type="button"' in script


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
    assert 'substitutions.setAttribute("aria-colspan", "8");' in organizer
    assert "<span data-ingredient-options-label>None</span>" in organizer
    assert organizer.index("organizeRecipeEditCompactRowActions") < organizer.index("if (substitutions) row.appendChild(substitutions)")

    assert "!optionCount" not in toggle
    assert 'otherContainer.hidden = true;' in toggle
    assert 'container.hidden = !shouldOpen;' in toggle
    assert 'row.classList.toggle("recipe-edit-substitutions-open", shouldOpen);' in toggle
    assert "event.preventDefault();" in toggle
    assert "event.stopPropagation();" in toggle

    assert "optionsButton.disabled = false;" in state
    assert '`${action} alternatives for ${ingredientName}`' in state
    assert 'empty.hidden = optionRows.length !== 0;' in state
    assert 'addLabel.textContent = "Add Alternative";' in state
    assert "No alternatives have been added." in script
    assert "Add a single replacement ingredient or a replacement made from multiple ingredients." in script
    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in state
    assert '`${alternativeCount} alternative${alternativeCount === 1 ? "" : "s"}`' in state
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
    assert 'window.confirm("Delete this alternative and all of its replacement ingredients?")' in editing
    assert 'card.querySelectorAll("[data-substitution-option-row]").forEach(optionRow => optionRow.remove());' in editing

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


def test_recipe_editor_read_summaries_combine_status_quantity_and_one_type_value():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    status = script[
        script.index("function recipeIngredientReadStatusHtml"):
        script.index("function recipeIngredientEditableFieldSnapshot")
    ]
    assert "const statusLabels = {" in status
    assert '(pantryStaple ? "Pantry staple" : "Good match")' in status
    assert "recipe-edit-ingredient-read-match" in status
    assert "recipe-edit-ingredient-read-preparation" in status
    assert "recipeIngredientBadgesHtml" not in status

    type_helpers = script[
        script.index("function recipeIngredientTypeValue"):
        script.index("function recipeIngredientPluralUnit")
    ]
    assert 'return "optional";' in type_helpers
    assert 'return builtIn ? builtIn.value : explicitType || "main";' in type_helpers
    assert 'return builtIn ? builtIn.label : value;' in type_helpers

    summary = script[
        script.index("function updateRecipeIngredientSummary"):
        script.index("function recipeEditIngredientRows")
    ]
    assert "readName.textContent" in summary
    assert "readStatus.innerHTML = recipeIngredientReadStatusHtml(matchItem)" in summary
    assert "meaningfulBuyAs = recipeIngredientMeaningfulBuyAs(values)" in summary
    assert "readBuyAs.hidden = !meaningfulBuyAs" in summary
    assert "quantitySummary.textContent = formatRecipeIngredientQuantity(values)" in summary
    assert "preparationSummary" not in summary
    assert "buyAsSummary" not in summary
    assert "recipeIngredientStoreSectionIconHtml(values.store_section || \"\")" in summary
    assert "const typeLabel = recipeIngredientTypeLabel(values)" in summary
    assert "typeSummary.textContent = typeLabel" in summary

    v10 = css[css.index("/* Ingredient editor v10:"):]
    hidden_status_start = v10.index(".recipe-edit-ingredient-role-summary")
    hidden_status_end = v10.index("}", hidden_status_start)
    assert ".recipe-edit-ingredient-badges" in v10[hidden_status_start:hidden_status_end]
    assert "display: none !important;" in v10[hidden_status_start:hidden_status_end]
    assert ".recipe-edit-ingredient-edit-support > .recipe-edit-ingredient-legacy-optional" in v10
    assert ".recipe-edit-ingredient-type-summary.is-optional" in v10


def test_recipe_editor_secondary_metadata_hides_redundant_buy_as_and_empty_preparation():
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
    assert '`Buy as: ${meaningfulBuyAs}`' in summary
    assert "readBuyAs.hidden = !meaningfulBuyAs" in summary
    assert "recipeIngredientReadStatusHtml(matchItem)" in summary

    v10 = css[css.index("/* Ingredient editor v10:"):]
    assert ".recipe-edit-ingredient-read-buy-as[hidden]" in v10
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
    assert 'addLabel.textContent = "Add Alternative";' in state
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
    assert "Add Replacement Ingredient" in markup
    assert ">Add replacement ingredient</button>" not in markup


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
    assert ".recipe-edit-store-section-menu-list {\n    flex: 1 1 auto;" in css
    assert ".recipe-edit-store-section-icon.is-fish" in css
    assert ".recipe-edit-store-section-icon.is-paw" in css


def test_recipe_editor_type_picker_supports_custom_type_crud_and_optional_sync():
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
    assert 'trigger.dataset.recipeEditTypeTrigger = "true";' in script
    assert 'trigger.setAttribute("role", "combobox");' in script
    assert 'trigger.setAttribute("aria-controls", "recipeIngredientTypeMenu");' in script
    assert "select.hidden = true;" in script
    assert "bindRecipeIngredientStoreSectionControls(row);\n    bindRecipeIngredientTypeControls(row);" in script
    assert 'optionalInput.checked = String(typeSelect.value || "").trim().toLowerCase() === "optional";' in script
    assert 'syncRecipeIngredientTypeControl(input);' in script
    assert 'row.querySelector("[data-recipe-edit-type-trigger]")' in script

    assert "/* Ingredient editor v11: managed custom Type picker. */" in css
    assert ".recipe-edit-type-trigger > [data-type-trigger-label]" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-option-dot" in css
    assert ".recipe-edit-type-menu .recipe-edit-type-custom-row" in css
    assert ".recipe-edit-ingredient-type-summary" in css


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
