from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PushShoppingList.services import cookbook_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_recipe_editor_includes_inline_category_controls_above_ingredients():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")

    assert "recipeEditCategoriesSection" in template
    assert "Edit Recipe Categories" in template
    assert "recipeEditCategoryMealType" in template
    assert "recipeEditCategoryCuisine" in template
    assert "recipeEditCategoryMainIngredient" in template
    assert "recipeEditCategoryCookingMethod" in template
    assert "recipeEditCategoryOccasion" in template
    assert "recipeEditCategoryDietaryPreference" in template
    assert "recipeEditCategoryPrepTimeGroup" in template
    assert "recipeEditCategoryCustomCategories" in template
    assert template.index("recipeEditCategoriesSection") < template.index("recipeEditIngredientsTitle")

    assert "function populateRecipeEditCategories" in script
    assert "function saveRecipeEditorCategories" in script
    assert "saveRecipeEditorCategories(sourceUrl, payload.original_url)" in script
    assert "cookbook_category_overwrite" in script


def test_recipe_editor_category_metadata_uses_saved_values_and_live_inference_context():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/enchiladas"],
            [{"name": "Enchiladas Verde", "url": "https://example.com/enchiladas"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/enchiladas",
            {
                "meal_type": choices["meal_type"][1],
                "cuisine": choices["cuisine"][1],
                "custom_categories": "Sophia's Favorites, Weeknight Dinners",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor(
            "https://example.com/enchiladas",
            {
                "recipe_title": "Enchiladas Verde with Jackfruit and White Beans",
                "prep_time": "20 min",
                "ingredients": [
                    {"ingredient": "young green jackfruit"},
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake the filled tortillas until hot."},
                ],
            },
            {"name": "Enchiladas Verde"},
        )

        assert metadata["meal_type"]
        assert metadata["cuisine"]
        assert metadata["main_ingredient"]
        assert metadata["cooking_method"]
        assert metadata["prep_time_group"]
        assert metadata["custom_categories"] == ["Sophia's Favorites", "Weeknight Dinners"]
        assert metadata["category_metadata_source"] == "Saved"
