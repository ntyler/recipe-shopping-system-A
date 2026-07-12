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
    assert "Substitutions / Options" in row_block
    assert "Add Option" in row_block
    assert "Add substitution option" in row_block
    assert 'data-field="substitutions_text"' not in row_block
    assert "bindRecipeIngredientSubstitutionRows(row);" in row_block
    assert "data-ingredient-substitution-count" in row_block
    assert 'badges.push([`${substitutionCount} Option${substitutionCount === 1 ? "" : "s"}`, "substitution"]);' in script
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
    assert 'row.querySelector("[data-equipment-image-panel], [data-ingredient-image-panel]")' in tools_block
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
    home_account_end = home_html.index("</a>", home_account_start)
    edit_account_start = html.index('<span class="app-account-avatar"')
    edit_account_end = html.index("</a>", edit_account_start)
    home_account = home_html[home_account_start:home_account_end]
    edit_account = html[edit_account_start:edit_account_end]

    assert response.status_code == 200
    assert 'data-recipe-edit-page="true"' in html
    assert 'data-recipe-edit-url="https://example.com/soup"' in html
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
