from pathlib import Path

from PushShoppingList.routes import main_routes


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def recipes_page_markup():
    template = read_text("PushShoppingList/templates/sections/app_workspaces.html")
    start = template.index('<section id="recipesPage"')
    end = template.index('<section id="menusPage"')
    return template[start:end]


def test_recipes_page_follows_reference_layout_without_fake_pagination():
    recipes_page = recipes_page_markup()

    assert "Browse, search, and manage all your recipes." in recipes_page
    assert 'class="app-recipes-command-row"' in recipes_page
    assert '<label class="app-recipes-search">' not in recipes_page
    assert recipes_page.index("app-recipes-heading-row") < recipes_page.index('class="app-recipes-command-row"')
    assert recipes_page.index('class="app-recipes-command-row"') < recipes_page.index('class="app-recipes-grid"')
    assert recipes_page.index('class="app-recipes-results-footer"') < recipes_page.index("app-recipes-rail")
    assert recipes_page.index('class="app-recipes-suggestions-banner"') < recipes_page.index('id="currentRecipeUrlLogCard"')
    assert "Showing" in recipes_page
    assert "Manage full collection" in recipes_page
    assert "app-recipes-pagination" not in recipes_page


def test_recipes_page_preserves_real_actions_and_recipe_metadata():
    recipes_page = recipes_page_markup()

    assert 'onclick="return createNewRecipe(this)"' in recipes_page
    assert 'onclick="return jumpToRecipeViewRecipe(this, event)"' in recipes_page
    assert 'data-recipe-url="{{ recipe.url }}"' in recipes_page
    assert 'data-deferred-src="{{ recipe.cover_image.card_url or recipe.cover_image.thumb_url or recipe.cover_image.src }}"' in recipes_page
    assert 'data-app-page-target="cookbooksPage"' in recipes_page
    assert 'data-app-page-target="recipeUrlsPage"' in recipes_page
    assert 'data-app-nav-action="ai-pantry"' in recipes_page
    assert 'onclick="return toggleRecipeBrowseFilters(this)"' in recipes_page
    assert 'onclick="return cycleRecipeBrowseSort(this)"' in recipes_page
    assert 'data-recipe-browse-search' in recipes_page
    assert 'data-recipe-browse-cookbook' in recipes_page
    assert "data-recipe-favorite" in recipes_page
    assert 'aria-pressed="{% if recipe.favorite %}true{% else %}false{% endif %}"' in recipes_page
    assert 'onclick="return toggleRecipeFavorite(this, event)"' in recipes_page
    assert 'shell.svg_icon("heart")' in recipes_page
    assert "app-recipe-card-metadata" in recipes_page
    assert "recipe.card_cook_time" in recipes_page
    assert "recipe.card_calories" in recipes_page
    assert "recipe.cookbook_name and not recipe.cookbook_is_unclassified" in recipes_page
    assert "recipe.home_badge" in recipes_page
    assert "Time TBD" not in recipes_page
    assert recipes_page.index("app-recipe-card-rating") < recipes_page.index("recipe.card_cook_time")
    assert recipes_page.index("recipe.card_cook_time") < recipes_page.index("recipe.card_calories")
    assert recipes_page.index("recipe.card_calories") < recipes_page.index("recipe.cookbook_name and not recipe.cookbook_is_unclassified")
    assert recipes_page.index("recipe.cookbook_name and not recipe.cookbook_is_unclassified") < recipes_page.index("recipe.home_badge")


def test_recipe_preview_link_opens_its_visible_parent_workspace():
    script = read_text("PushShoppingList/static/js/app.js")
    function_start = script.index("function jumpToRecipeViewRecipe")
    function_end = script.index("function jumpToCurrentRecipeLog", function_start)
    jump_function = script[function_start:function_end]

    assert 'document.getElementById("shoppingListsPage")' in jump_function
    assert 'openAppPage("shoppingListsPage", {' in jump_function
    assert 'lazySection: "recipe-view"' in jump_function
    assert 'loadLazySection("recipe-view")' in jump_function


def test_recipes_page_css_locks_reference_geometry_and_responsive_fallbacks():
    css = read_text("PushShoppingList/static/css/app.css")

    assert ".app-shell-body:has(#recipesPage:not([hidden]))" in css
    assert "--app-sidebar-width: 274px;" in css
    assert "--app-toolbar-height: 72px;" in css
    assert ".app-page-workspace-recipes .app-page-layout" in css
    assert "grid-template-columns: minmax(0, 1fr) 246px;" in css
    assert ".app-page-workspace-recipes .app-recipes-grid" in css
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in css
    assert "aspect-ratio: 13 / 10;" in css
    assert ".app-recipes-suggestions-banner" in css
    assert "@media (max-width: 1040px)" in css
    assert "@media (max-width: 768px)" in css


def test_recipe_collection_breakdown_is_exclusive_and_truthful():
    recipes = [
        {"url": "manual://weeknight-pasta"},
        {"url": "https://example.test/ai-recipe"},
        {"url": "https://example.test/imported-recipe"},
    ]
    records = {
        "manual://weeknight-pasta": {"ai_inferred": True},
        "https://example.test/ai-recipe": {"source_type": "menu_item_inferred"},
        "https://example.test/imported-recipe": {"source_type": "url"},
    }

    assert main_routes.recipe_collection_breakdown(recipes, records) == {
        "created_by_you": 1,
        "ai_inferred": 1,
        "imported": 1,
    }


def test_top_ingredients_count_each_recipe_only_once():
    recipes = [
        {"url": "recipe://one"},
        {"url": "recipe://two"},
    ]
    ingredient_data = {
        "recipe://one": {"ingredients": ["garlic", "Chicken", "garlic"]},
        "recipe://two": {"ingredients": ["Garlic", "tomatoes"]},
    }

    assert main_routes.recipe_top_ingredient_rows(recipes, ingredient_data) == [
        {"name": "Garlic", "recipe_count": 2},
        {"name": "Chicken", "recipe_count": 1},
        {"name": "Tomatoes", "recipe_count": 1},
    ]


def test_recipe_preview_time_adds_units_only_when_missing():
    assert main_routes.recipe_preview_time_label({"total_time": "55"}) == "55 min"
    assert main_routes.recipe_preview_time_label({"cook_time": "1 hr 20 min"}) == "1 hr 20 min"
    assert main_routes.recipe_preview_time_label({}) == "Time TBD"
