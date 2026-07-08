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
    assert ingredient_section.index("Generate Images") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Regenerate Ingredients") < ingredient_section.index("Food Rules")
    assert ingredient_section.index("Food Rules") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Sort Ingredients") < ingredient_section.index("Show or Hide Images")
    assert "generateRecipeImagesFromEditor(this, { imageScope: 'ingredients' })" in ingredient_section
    assert "generateRecipeImagesFromEditor(this, { missingOnly: true, imageScope: 'ingredients' })" in ingredient_section
    assert "regenerateRecipeIngredientsSection(this)" in ingredient_section
    assert "autoSortRecipeIngredients('ingredient')" in ingredient_section
    assert "autoSortRecipeIngredients('store_section')" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, true, { imageScope: 'ingredients' })" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, false, { imageScope: 'ingredients' })" in ingredient_section
    assert "Auto Sort" not in toolbar_markup
    assert ".recipe-edit-ingredients-image-menu" in css
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
    assert "setRecipeEditRowImageToolsVisible(row, true);" in generate_block


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
    compact_start = css.index(
        ".recipe-edit-ingredients.recipe-edit-ingredients-collapsed .recipe-edit-ingredient-row:not(.recipe-edit-row-expanded),",
        final_surface_start,
    )
    compact_end = css.index(".recipe-edit-equipment-row:not(:has", compact_start)
    compact_css = css[compact_start:compact_end]

    assert "grid-template-columns: 22px 40px minmax(0, 1fr) 38px;" in compact_css
    assert "min-height: 0;" in compact_css
    assert "padding: 10px 14px;" in compact_css
    assert "grid-row: 1;" in compact_css
    assert "display: flex;" in compact_css
    assert "width: 34px;" in compact_css
    assert "height: 34px;" in compact_css
    assert "min-height: 20px;" in compact_css


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
            "email": "editor@example.com",
            "username": "editor",
            "account_status": "active",
        }],
    })

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "edit-page-user"

        response = client.get(
            "/recipe/edit",
            query_string={"url": "https://example.com/soup"},
        )

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-recipe-edit-page="true"' in html
    assert 'data-recipe-edit-url="https://example.com/soup"' in html
    assert 'id="recipeEditModal"' in html
    assert 'id="currentRecipeUrlLogCard"' not in html
