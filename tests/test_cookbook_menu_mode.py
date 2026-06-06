from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from PushShoppingList.services import cookbook_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_cookbook_menu_mode_static_hooks_are_present():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/main_routes.py")
    service = read_text("PushShoppingList/services/cookbook_service.py")

    for label in (
        "📖 Cookbook Menu",
        "Browse your cookbook like a restaurant menu.",
        "Sort Cookbook By",
        "🍽️ Restaurant Menu",
        "🌎 Cuisine",
        "🥩 Main Ingredient",
        "🍳 Meal Type",
        "🔥 Cooking Method",
        "🎉 Occasion",
        "🥗 Dietary Preference",
        "⏱️ Prep Time",
        "🔤 Alphabetical",
        "⭐ Custom Categories",
    ):
        assert label in template or label in service

    assert "data-cookbook-menu-view" in template
    assert "data-cookbook-menu-section" in template
    assert "No recipes found in this category yet." in template
    assert "Add Ingredients to Shopping List" in template
    assert "cookbookCategoryEditorModal" in template
    assert "/api/cookbooks/<cookbook_id>/recipe_categories" in routes
    assert "function openCookbookCategoryEditor" in script
    assert "function saveCookbookCategories" in script
    assert "cookbook_category_overwrite" in script
    assert "data-cookbook-search-text" in template
    assert ".cookbook-menu-recipe-card" in css
    assert ".cookbook-category-grid" in css


def test_cookbook_menu_metadata_uses_saved_values_without_render_inference():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        recipe_rows = [{
            "name": "Chicken Alfredo",
            "url": "https://example.com/chicken-alfredo",
            "description": "Creamy pasta dinner with chicken.",
            "prep_time": "20 min",
            "cook_time": "25 min",
            "base_servings": "4 servings",
            "instruction_items": ["Cook the fettuccine and simmer the chicken in a skillet."],
            "sections": {
                "MISC": [
                    {"name": "chicken breast", "display_name": "chicken breast"},
                    {"name": "fettuccine pasta", "display_name": "fettuccine pasta"},
                    {"name": "parmesan cheese", "display_name": "parmesan cheese"},
                ],
            },
        }]

        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/chicken-alfredo"],
            recipe_rows,
        )

        stored_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]
        assert stored_recipe["meal_type"] == ""
        assert stored_recipe["category_metadata_user_set"] is False

        view = cookbook_service.cookbook_view([])
        dinner = view["cookbooks"][0]
        recipe = dinner["recipes"][0]

        assert recipe["main_ingredient"] == ""
        assert recipe["cuisine"] == ""
        assert recipe["meal_type"] == ""
        assert recipe["restaurant_menu_category"] == ""
        assert recipe["prep_time_group"] == ""
        assert recipe["category_metadata_source"] == "Blank"
        assert recipe["category_metadata_sources"]["main_ingredient"] == "blank"
        assert "🇮🇹 Italian" not in recipe["menu_tags"]
        assert "fettuccine pasta" in recipe["menu_search_text"]

        restaurant_fallback_section = next(
            section
            for section in dinner["menu_sections"]["restaurant_menu"]
            if section["label"] == "🍽️ Other Recipes"
        )
        assert restaurant_fallback_section["recipes"][0]["name"] == "Chicken Alfredo"


def test_cookbook_category_update_requires_confirmation_before_overwriting_manual_values():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.create_cookbook("Dinner")
        cookbook_service.move_recipes_to_cookbook(
            "dinner",
            ["https://example.com/margarita"],
            [{"name": "Margarita", "url": "https://example.com/margarita"}],
        )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/margarita",
            {
                "meal_type": "🍹 Drink",
                "cuisine": "🇲🇽 Mexican",
                "custom_categories": "☀️ Summer BBQ",
            },
        )

        with pytest.raises(cookbook_service.CookbookCategoryOverwriteConflict):
            cookbook_service.update_cookbook_recipe_categories(
                "dinner",
                "https://example.com/margarita",
                {
                    "meal_type": "🍹 Drink",
                    "cuisine": "🌍 Other / Fusion",
                    "custom_categories": "🧪 Things We Want To Try",
                },
            )

        cookbook_service.update_cookbook_recipe_categories(
            "dinner",
            "https://example.com/margarita",
            {
                "meal_type": "🍹 Drink",
                "cuisine": "🌍 Other / Fusion",
                "custom_categories": "🧪 Things We Want To Try",
            },
            confirm_overwrite=True,
        )

        saved_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]
        assert saved_recipe["category_metadata_user_set"] is True
        assert saved_recipe["cuisine"] == "🌍 Other / Fusion"
        assert saved_recipe["custom_categories"] == ["🧪 Things We Want To Try"]
        assert saved_recipe["category_metadata_sources"]["cuisine"] == "user_selected"
        assert saved_recipe["category_metadata_sources"]["custom_categories"] == "user_selected"
