from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from flask import render_template

from PushShoppingList.app import create_app
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
        "Cookbook View",
        "Browse saved recipes as rows or a restaurant menu.",
        "View Cookbook As",
        "Recipe View",
        "Cookbook Menu",
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
    assert "data-cookbook-view-mode-select" in template
    assert 'data-cookbook-view-panel="recipes"' in template
    assert 'data-cookbook-view-panel="menu"' in template
    assert "data-cookbook-menu-section" in template
    assert "No recipes found in this category yet." in template
    assert "Add Ingredients to Shopping List" in template
    assert "cookbookCategoryEditorModal" in template
    assert "/api/cookbooks/<cookbook_id>/recipe_categories" in routes
    assert "function openCookbookCategoryEditor" in script
    assert "function applyCookbookViewMode" in script
    assert "COOKBOOK_VIEW_MODE_SESSION_KEY" in script
    assert "function saveCookbookCategories" in script
    assert "cookbook_category_overwrite" in script
    assert "data-cookbook-search-text" in template
    assert ".cookbook-menu-recipe-card" in css
    assert ".cookbook-recipe-log-view" in css
    assert ".cookbook-category-grid" in css


def test_cookbook_recipe_rows_match_current_recipe_summary_layout():
    template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    css = read_text("PushShoppingList/static/css/app.css")

    recipe_card_start = template.index("data-cookbook-recipe-card")
    title_line_start = template.index(
        '<span class="recipe-url-summary-title-line">',
        recipe_card_start,
    )
    food_review_index = template.index(
        'class="food-rule-marker recipe-log-food-review-btn recipe-url-summary-food-review"',
        title_line_start,
    )
    summary_body_index = template.index(
        '<div class="recipe-url-summary-body">',
        title_line_start,
    )

    assert food_review_index < summary_body_index
    assert "recipe-url-summary-row" in template
    assert 'class="recipe-url-summary-header"' in template
    assert 'class="recipe-batch-select cookbook-restore-checkbox cookbook-recipe-restore-checkbox"' in template
    assert 'class="recipe-url-summary-actions cookbook-recipe-actions"' in template
    assert "display: grid;\n                grid-template-columns: minmax(0, 1fr) auto;" not in css
    assert "justify-content: flex-end;\n                width: 100%;\n                margin-left: auto;" not in css


def test_unclassified_cookbook_menu_keeps_cookbook_management_protected():
    app = create_app()
    app.config.update(TESTING=True)

    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "unclassified",
                    "name": "unclassified",
                    "recipes": [{"url": "https://example.com/loose", "name": "Loose Soup"}],
                },
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [{"url": "https://example.com/chili", "name": "Chili"}],
                },
            ],
        })
        view = cookbook_service.cookbook_view([])
        for cookbook in view["cookbooks"]:
            cookbook.setdefault("menu_pdf_logs", [])
            cookbook.setdefault("restaurant_menus", [])

        with app.test_request_context("/"):
            html = render_template(
                "sections/cookbooks.html",
                cookbook_view=view,
                cookbook_count=len(view["cookbooks"]),
                cookbook_recipe_count=sum(len(cookbook["recipes"]) for cookbook in view["cookbooks"]),
            )

    def card_header(cookbook_id):
        marker = f'data-cookbook-id="{cookbook_id}"'
        marker_index = html.index(marker)
        start = html.rfind("<article", 0, marker_index)
        end = html.index('<div class="cookbook-card-body"', marker_index)
        return html[start:end]

    unclassified_header = card_header("unclassified")
    dinner_header = card_header("dinner")

    assert 'data-cookbook-unclassified="1"' in unclassified_header
    assert "Rename cookbook" not in unclassified_header
    assert "Delete cookbook, keep recipes" not in unclassified_header
    assert "Delete cookbook and purge recipes" not in unclassified_header
    assert "deleteCookbook(this)" not in unclassified_header
    assert "purgeCookbook(this)" not in unclassified_header
    assert "Remove selected recipes" in unclassified_header
    assert "Purge selected recipes" in unclassified_header
    assert "Purge all unclassified recipes" in unclassified_header

    assert 'data-cookbook-unclassified="0"' in dinner_header
    assert "Rename cookbook" in dinner_header
    assert "Delete selected recipes" in dinner_header
    assert "Delete cookbook, keep recipes" in dinner_header
    assert "Delete cookbook and purge recipes" in dinner_header


def test_remove_selected_cookbook_recipes_moves_them_to_unclassified():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [
                        {"url": "https://example.com/chili", "name": "Chili"},
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
                {"id": "unclassified", "name": "unclassified", "recipes": []},
            ],
        })

        removed_urls = cookbook_service.remove_recipes_from_cookbook(
            "dinner",
            ["https://example.com/soup"],
        )
        payload = cookbook_service.load_cookbooks()

    dinner = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "dinner")
    unclassified = next(
        cookbook
        for cookbook in payload["cookbooks"]
        if cookbook["name"] == "unclassified"
    )

    assert removed_urls == ["https://example.com/soup"]
    assert [recipe["url"] for recipe in dinner["recipes"]] == ["https://example.com/chili"]
    assert [recipe["url"] for recipe in unclassified["recipes"]] == ["https://example.com/soup"]


def test_purge_selected_cookbook_recipes_removes_them_from_all_cookbooks():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook_service.save_cookbooks({
            "cookbooks": [
                {
                    "id": "dinner",
                    "name": "Dinner",
                    "recipes": [
                        {"url": "https://example.com/chili", "name": "Chili"},
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
                {
                    "id": "favorites",
                    "name": "Favorites",
                    "recipes": [
                        {"url": "https://example.com/soup", "name": "Soup"},
                    ],
                },
            ],
        })

        purged_urls = cookbook_service.purge_selected_cookbook_recipe_urls(
            "dinner",
            ["https://example.com/soup"],
        )
        payload = cookbook_service.load_cookbooks()

    dinner = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "dinner")
    favorites = next(cookbook for cookbook in payload["cookbooks"] if cookbook["id"] == "favorites")

    assert purged_urls == ["https://example.com/soup"]
    assert [recipe["url"] for recipe in dinner["recipes"]] == ["https://example.com/chili"]
    assert favorites["recipes"] == []


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
