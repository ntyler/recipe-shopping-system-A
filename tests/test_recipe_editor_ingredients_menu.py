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
    assert "openRecipeEditor({ dataset: { recipeUrl } });" in standalone_page
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
