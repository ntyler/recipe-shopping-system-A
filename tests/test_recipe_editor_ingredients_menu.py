from pathlib import Path


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
    assert "Sort Ingredients" in ingredient_section
    assert "By Ingredient Name" in ingredient_section
    assert "By Store Section" in ingredient_section
    assert "Show or Hide Images" in ingredient_section
    assert ingredient_section.index("Generate Images") < ingredient_section.index("Sort Ingredients")
    assert ingredient_section.index("Sort Ingredients") < ingredient_section.index("Show or Hide Images")
    assert "generateRecipeImagesFromEditor(this)" in ingredient_section
    assert "autoSortRecipeIngredients('ingredient')" in ingredient_section
    assert "autoSortRecipeIngredients('store_section')" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, true)" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, false)" in ingredient_section
    assert "Auto Sort" not in toolbar_markup
    assert ".recipe-edit-ingredients-image-menu" in css
    assert "function autoSortRecipeIngredients(mode = \"ingredient\")" in script
    assert "const sortMode = mode === \"store_section\" ? \"store_section\" : \"ingredient\";" in script
    assert "function recipeIngredientSortKey(value)" in script
    assert "closeRecipeEditRowMenus();" in script


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


def test_recipe_menu_edit_opens_editor_after_closing_menu():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    current_recipes = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    recipe_view = (ROOT / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    cookbooks = (ROOT / "PushShoppingList/templates/sections/cookbooks.html").read_text(encoding="utf-8")

    assert "function openRecipeEditorFromMenu(button, options = {})" in script
    assert 'const recipeUrl = button ? button.dataset.recipeUrl || "" : "";' in script
    assert "openRecipeEditor({ dataset: { recipeUrl } }, options);" in script
    assert "await waitForNextPaint();" in script
    assert "scheduleRecipeImageProgressPoll(750);" in script
    assert "onclick=\"return openRecipeEditorFromMenu(this)\"" in current_recipes
    assert "onclick=\"return openRecipeEditorFromMenu(this)\"" in recipe_view
    assert "onclick=\"return openRecipeEditorFromMenu(this)\"" in cookbooks
