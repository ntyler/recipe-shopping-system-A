from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ingredients_header_has_image_overflow_menu():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(
        encoding="utf-8",
    )
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    ingredient_section_start = template.index("recipe-edit-ingredients-section")
    equipment_section_start = template.index("recipe-edit-equipment-section")
    ingredient_section = template[ingredient_section_start:equipment_section_start]

    assert "recipe-edit-ingredients-menu-wrap" in ingredient_section
    assert "recipe-edit-ingredients-image-menu" in ingredient_section
    assert "Generate Images" in ingredient_section
    assert "Show or Hide Images" in ingredient_section
    assert "generateRecipeImagesFromEditor(this)" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, true)" in ingredient_section
    assert "setRecipeEditorImagesVisibleFromMenu(this, false)" in ingredient_section
    assert ".recipe-edit-ingredients-image-menu" in css
