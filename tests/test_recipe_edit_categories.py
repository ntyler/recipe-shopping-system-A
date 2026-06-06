import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PushShoppingList.services import cookbook_service
from PushShoppingList.services import recipe_edit_service


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
    assert "recipe-edit-category-menu" in template
    assert "Have ChatGPT Decide All" in template
    assert "Have ChatGPT Decide Missing" in template
    assert template.index("recipeEditCategoriesSection") < template.index("recipeEditIngredientsTitle")

    assert "function populateRecipeEditCategories" in script
    assert "function saveRecipeEditorCategories" in script
    assert "function decideRecipeEditCategoriesWithChatGPT" in script
    assert "function applyRecipeEditCategorySuggestions" in script
    assert "ChatGPT will replace the current category selections. Continue?" in script
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


def test_chatgpt_category_decision_normalizes_to_dropdown_choices():
    choices = cookbook_service.cookbook_category_choices()
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Italian",
                        "main_ingredient": "Pasta",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "High Protein",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Weeknight Dinners", "Comfort Food"],
                    })
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response
            )
        )
    )

    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch.object(
        recipe_edit_service,
        "get_openai_client",
        return_value=client,
    ), patch.object(recipe_edit_service, "record_openai_usage"):
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt({
            "recipe_title": "Baked Stuffed Pasta",
            "prep_time": "20 min",
            "cook_time": "35 min",
            "ingredients": [
                {"ingredient": "pasta shells"},
                {"ingredient": "ricotta cheese"},
                {"ingredient": "tomato sauce"},
            ],
            "instructions": [
                {"instruction": "Stuff the pasta and bake until bubbling."},
            ],
        })

    assert result["ok"] is True
    categories = result["categories"]
    assert categories["meal_type"] == next(item for item in choices["meal_type"] if "Dinner" in item)
    assert categories["cuisine"] == next(item for item in choices["cuisine"] if "Italian" in item)
    assert categories["main_ingredient"] == next(item for item in choices["main_ingredient"] if "Pasta" in item)
    assert categories["cooking_method"] == next(item for item in choices["cooking_method"] if "Oven Baked" in item)
    assert categories["occasion"] == next(item for item in choices["occasion"] if "Family Dinner" in item)
    assert categories["dietary_preference"] == next(item for item in choices["dietary_preference"] if "High Protein" in item)
    assert categories["prep_time_group"] == next(item for item in choices["prep_time_group"] if "15" in item and "30" in item)
    assert categories["custom_categories"] == ["Weeknight Dinners", "Comfort Food"]
