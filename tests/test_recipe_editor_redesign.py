from pathlib import Path

from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def configure_recipe_editor_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *args, **kwargs: None)

    return output_dir


def test_standalone_recipe_editor_uses_app_shell_navigation():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")

    assert "app-shell-body recipe-edit-standalone-page" in template
    assert "app-sidebar recipe-edit-page-sidebar" in template
    assert "recipe-edit-page-main-shell" in template
    assert "recipe-edit-standalone-shell" in template
    assert "{% include \"sections/current_recipe_url_log.html\" %}" in template


def test_recipe_editor_redesign_preserves_core_fields_and_actions():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")

    assert "recipe-edit-breadcrumb" in template
    assert "Preview Recipe" in template
    assert "recipe-edit-layout" in template
    assert "recipe-edit-main-workspace" in template
    assert "recipe-edit-context-sidebar" in template
    assert "recipe-edit-tab-list" in template
    assert 'data-recipe-edit-tab="ingredients"' in template
    assert 'data-recipe-edit-tab="instructions"' in template
    assert 'data-recipe-edit-tab="equipment"' in template
    assert 'data-recipe-edit-tab="nutrition"' in template
    assert 'data-recipe-edit-tab="notes"' in template
    assert "recipe-edit-source-documents-card" in template
    assert "data-document-download" in template
    assert "recipe-edit-restaurant-card" in template
    assert "recipeEditIngredientGallery" in template
    assert "recipeEditHealthList" in template
    assert "recipe-edit-ai-assistant-card" in template

    for field_id in [
        "recipeEditDisplayName",
        "recipeEditTitleInput",
        "recipeEditDescription",
        "recipeEditSourceUrl",
        "recipeEditSourceMenuUrl",
        "recipeEditSourcePdfPath",
        "recipeEditSourceCloudflarePdfUrl",
        "recipeEditGeneratedPdfPath",
        "recipeEditGeneratedCloudflarePdfUrl",
        "recipeEditRestaurantName",
        "recipeEditRestaurantWebsiteUrl",
        "recipeEditRestaurantPhone",
        "recipeEditRestaurantAddress",
        "recipeEditCategoryMenuSection",
        "recipeEditLevel",
        "recipeEditTotalTime",
        "recipeEditPrepTime",
        "recipeEditInactiveTime",
        "recipeEditCookTime",
        "recipeEditServings",
        "recipeEditInferOverwriteAiFields",
        "recipeEditInferPreviewOnly",
    ]:
        assert f'id="{field_id}"' in template

    assert "inferMissingRecipeDetails(this)" in template
    assert "confirmDeleteRecipeFromEditor(this, event)" in template
    assert 'type="submit" class="recipe-edit-save"' in template


def test_recipe_editor_redesign_javascript_wiring():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function initRecipeEditTabs()" in script
    assert "function setRecipeEditActiveTab(tabKey, options = {})" in script
    assert "function syncRecipeEditDocumentRows()" in script
    assert "function updateRecipeEditRestaurantCard()" in script
    assert "function updateRecipeEditIngredientGallery()" in script
    assert "function updateRecipeEditorHealth()" in script
    assert "function previewRecipeFromEditor()" in script
    assert "function replaceRecipeIngredientWithSubstitution(button)" in script
    assert 'setValue("recipeEditDescription", recipe.description || "")' in script
    assert 'description: document.getElementById("recipeEditDescription")' in script
    assert "data-recipe-edit-health-item" in script
    assert "data-health-status" in script
    assert "data-document-download" in script
    assert "[\"initRecipeEditTabs\", initRecipeEditTabs]" in script
    assert "[\"initRecipeEditContextPanels\", initRecipeEditContextPanels]" in script
    assert 'data-field="section"' in script
    assert "Replace ingredient with this option" in script


def test_recipe_editor_redesign_css_uses_app_tokens_and_mobile_breakpoints():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "Phase 2 recipe editor redesign using the AI Pantry shell tokens" in css
    assert ".recipe-edit-layout {" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(292px, 360px);" in css
    assert ".recipe-edit-context-sidebar {" in css
    assert ".recipe-edit-tab-list {" in css
    assert ".recipe-edit-document-row {" in css
    assert ".recipe-edit-health-row" in css
    assert ".recipe-edit-ai-assistant-card {" in css
    assert ".recipe-edit-ingredient-row label.recipe-edit-section-label" in css
    assert ".recipe-edit-substitution-row-menu:not([hidden])" in css
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 767px)" in css


def test_recipe_editor_description_loads_and_saves_existing_field(monkeypatch, tmp_path):
    configure_recipe_editor_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/description-soup"

    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Description Soup",
        "description": "A bright soup with herbs.",
        "ingredients": [{"ingredient": "tomato", "quantity": "2", "unit": "cups"}],
        "instructions": [{"instruction": "Simmer until warm."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    assert loaded["description"] == "A bright soup with herbs."

    result = recipe_edit_service.save_editable_recipe(url, {
        "source_url": url,
        "display_name": "Description Soup",
        "recipe_title": "Description Soup",
        "description": "A saved soup description.",
        "quantity": 1,
        "servings": "4",
        "level": "Easy",
        "total_time": "30 minutes",
        "prep_time": "10 minutes",
        "inactive_time": "",
        "cook_time": "20 minutes",
        "scaling": {},
        "ingredients": [{"ingredient": "tomato", "quantity": "2", "unit": "cups"}],
        "equipment": [],
        "instructions": [{"instruction": "Simmer until warm."}],
        "nutrition": [],
        "recipe_notes": [],
        "reflection_notes": [],
    })

    assert result["recipe"]["description"] == "A saved soup description."
    assert recipe_edit_service.load_recipe_output(url)["description"] == "A saved soup description."
