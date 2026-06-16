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


def test_recipe_editor_infer_missing_details_runs_full_ai_followups():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "async function estimateRecipeNutrition(button, options = {})" in script
    assert "async function decideRecipeEditCategoriesWithChatGPT(button, mode = \"missing\", options = {})" in script
    assert "async function runRecipeEditorInferenceFollowups()" in script
    assert "await estimateRecipeNutrition(null, {" in script
    assert "await decideRecipeEditCategoriesWithChatGPT(null, \"all\", {" in script
    assert "const followupResult = previewOnly ? null : await runRecipeEditorInferenceFollowups();" in script
    assert "Save Recipe to keep nutrition/categories." in script


def test_recipe_editor_category_metadata_preserves_saved_values_without_live_inference():
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

        assert metadata["meal_type"] == choices["meal_type"][1]
        assert metadata["cuisine"] == choices["cuisine"][1]
        assert metadata["main_ingredient"] == ""
        assert metadata["cooking_method"] == ""
        assert metadata["prep_time_group"] == ""
        assert metadata["custom_categories"] == ["Sophia's Favorites", "Weeknight Dinners"]
        assert metadata["category_metadata_source"] == "Saved"
        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "blank"


def test_recipe_category_metadata_preserves_ai_inferred_sources():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        choices = cookbook_service.cookbook_category_choices()
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/beans"],
            [{"name": "Bean Enchiladas", "url": "https://example.com/beans"}],
        )
        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/beans",
            {
                "meal_type": choices["meal_type"][2],
                "main_ingredient": next(item for item in choices["main_ingredient"] if "Beans" in item),
            },
            category_sources={
                "meal_type": "user_selected",
                "main_ingredient": "ai_inferred",
            },
        )

        metadata = cookbook_service.recipe_category_metadata_for_editor("https://example.com/beans")

        assert metadata["category_metadata_sources"]["meal_type"] == "user_selected"
        assert metadata["category_metadata_sources"]["main_ingredient"] == "ai_inferred"
        assert metadata["category_metadata_sources"]["cuisine"] == "blank"


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


def test_recipe_category_inference_uses_total_time_and_keeps_vegan_out_of_main_ingredient():
    categories = cookbook_service.infer_recipe_categories({
        "name": "Vegan Enchiladas Verde with Jackfruit and White Beans",
        "prep_time": "20 min",
        "total_time": "45 min",
        "sections": {
            "INGREDIENTS": [
                {"name": "young green jackfruit"},
                {"name": "white beans"},
                {"name": "green enchilada sauce"},
            ],
        },
        "instruction_items": ["Bake the filled tortillas until hot."],
    })

    assert "Vegan" not in categories["main_ingredient"]
    assert categories["main_ingredient"] == next(
        item for item in cookbook_service.cookbook_category_choices()["main_ingredient"] if "Beans" in item
    )
    assert categories["dietary_preference"] == next(
        item for item in cookbook_service.cookbook_category_choices()["dietary_preference"] if "Vegan" in item
    )
    assert categories["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )


def test_chatgpt_category_decision_logs_and_sanitizes_vegan_and_total_time(capsys):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({
                        "meal_type": "Dinner",
                        "cuisine": "Mexican",
                        "main_ingredient": "Vegan",
                        "cooking_method": "Oven Baked",
                        "occasion": "Family Dinner",
                        "dietary_preference": "Vegan",
                        "prep_time_group": "15-30 Minutes",
                        "custom_categories": ["Comfort Food"],
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
        result = recipe_edit_service.decide_recipe_categories_with_chatgpt(
            {
                "source_url": "manual://recipe/test-vegan-enchiladas",
                "recipe_title": "Vegan Enchiladas Verde with White Beans",
                "prep_time": "20 min",
                "total_time": "45 min",
                "ingredients": [
                    {"ingredient": "white beans"},
                    {"ingredient": "green enchilada sauce"},
                ],
                "instructions": [
                    {"instruction": "Bake until hot."},
                ],
            },
            mode="missing",
            trigger_source="recipe_editor:missing",
            current_categories={"meal_type": "🍽️ Dinner"},
        )

    assert result["ok"] is True
    assert "Vegan" not in result["categories"]["main_ingredient"]
    assert result["categories"]["prep_time_group"] == next(
        item for item in cookbook_service.cookbook_category_choices()["prep_time_group"] if "30" in item and "60" in item
    )

    log_output = capsys.readouterr().out
    assert "[recipe_category_inference]" in log_output
    assert "manual://recipe/test-vegan-enchiladas" in log_output
    assert "recipe_editor:missing" in log_output
    assert '"meal_type"' not in log_output.split('"fields_changed":', 1)[1]
