from pathlib import Path

from PushShoppingList.routes import main_routes


ROOT = Path(__file__).resolve().parents[1]


def test_recipe_view_page_bounds_batches_and_preserves_global_offsets():
    recipes = [
        {"url": f"https://example.test/recipe-{index}", "name": f"Recipe {index}"}
        for index in range(1, 19)
    ]

    first = main_routes.recipe_view_page(recipes, "not-a-number")
    middle = main_routes.recipe_view_page(recipes, 2)
    last = main_routes.recipe_view_page(recipes, 999)

    assert first["page"] == 1
    assert first["recipe_urls"] == recipes[:8]
    assert first["has_more"] is True
    assert middle["start"] == 8
    assert middle["end"] == 16
    assert middle["recipe_urls"] == recipes[8:16]
    assert last["page"] == 3
    assert last["recipe_urls"] == recipes[16:]
    assert last["has_more"] is False


def test_initial_recipe_view_batch_keeps_all_recipe_shopping_quantities(monkeypatch):
    recipes = [
        {"url": f"https://example.test/recipe-{index}", "name": f"Recipe {index}"}
        for index in range(1, 11)
    ]
    calls = {
        "reconciled_urls": [],
        "rich_urls": [],
        "quantity_urls": [],
        "quantity_input": [],
    }

    monkeypatch.setattr(main_routes, "load_items", lambda: [])
    monkeypatch.setattr(main_routes, "load_item_state", lambda: {})
    monkeypatch.setattr(
        main_routes,
        "load_store_settings",
        lambda: {"stores": {}, "enabled_stores": []},
    )
    monkeypatch.setattr(main_routes, "product_choices_by_item", lambda: {})
    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: recipes)
    monkeypatch.setattr(main_routes, "purchase_mapping_lookup_for_items", lambda items, state: {})
    monkeypatch.setattr(main_routes, "build_store_view", lambda *args: [])
    monkeypatch.setattr(main_routes, "url_for", lambda endpoint, **values: f"/sections/recipe-view?page={values['page']}&batch=1")
    monkeypatch.setattr(
        main_routes,
        "ensure_unclassified_cookbook_for_recipes",
        lambda rows: calls["reconciled_urls"].append([recipe["url"] for recipe in rows]),
    )

    def batch_context(page_urls):
        calls["rich_urls"].append([recipe["url"] for recipe in page_urls])
        return {
            "recipe_urls": page_urls,
            "food_rules": [],
            "recipe_view_rows": [
                {"number": index, "url": recipe["url"], "sections": {}}
                for index, recipe in enumerate(page_urls, start=1)
            ],
            "cookbook_view": {"cookbooks": []},
            "cookbook_count": 0,
            "cookbook_recipe_count": 0,
            "cookbook_assignments": {},
        }

    def quantity_rows(all_urls):
        calls["quantity_urls"].append([recipe["url"] for recipe in all_urls])
        return [
            {"number": index, "url": recipe["url"], "sections": {}}
            for index, recipe in enumerate(all_urls, start=1)
        ]

    def quantity_lookup(rows):
        calls["quantity_input"].append([row["url"] for row in rows])
        return {"all-recipes-count": str(len(rows))}

    monkeypatch.setattr(main_routes, "recipe_view_batch_context", batch_context)
    monkeypatch.setattr(main_routes, "recipe_quantity_rows", quantity_rows)
    monkeypatch.setattr(main_routes, "recipe_quantity_lookup", quantity_lookup)
    monkeypatch.setattr(main_routes, "recipe_quantity_sources_lookup", lambda rows: {})
    monkeypatch.setattr(main_routes, "apply_manual_item_quantities", lambda quantities, state: quantities)

    context = main_routes.shopping_views_context(recipe_page=1)

    assert calls["reconciled_urls"] == [[recipe["url"] for recipe in recipes]]
    assert calls["rich_urls"] == [[recipe["url"] for recipe in recipes[:8]]]
    assert calls["quantity_urls"] == [[recipe["url"] for recipe in recipes]]
    assert calls["quantity_input"] == [[recipe["url"] for recipe in recipes]]
    assert context["recipe_item_quantities"] == {"all-recipes-count": "10"}
    assert context["recipe_view_pagination"]["next_url"] == "/sections/recipe-view?page=2&batch=1"
    assert [row["number"] for row in context["recipe_view_rows"]] == list(range(1, 9))


def test_followup_recipe_batch_skips_rebuilding_global_quantity_projection(monkeypatch):
    recipes = [
        {"url": f"https://example.test/recipe-{index}", "name": f"Recipe {index}"}
        for index in range(1, 11)
    ]
    global_reconciliation_called = False
    quantity_projection_called = False
    quantity_input = []

    monkeypatch.setattr(main_routes, "load_items", lambda: [])
    monkeypatch.setattr(main_routes, "load_item_state", lambda: {})
    monkeypatch.setattr(
        main_routes,
        "load_store_settings",
        lambda: {"stores": {}, "enabled_stores": []},
    )
    monkeypatch.setattr(main_routes, "product_choices_by_item", lambda: {})
    monkeypatch.setattr(main_routes, "recipe_url_rows", lambda: recipes)
    monkeypatch.setattr(main_routes, "purchase_mapping_lookup_for_items", lambda items, state: {})
    monkeypatch.setattr(main_routes, "build_store_view", lambda *args: [])

    def unexpected_global_reconciliation(_recipes):
        nonlocal global_reconciliation_called
        global_reconciliation_called = True

    monkeypatch.setattr(
        main_routes,
        "ensure_unclassified_cookbook_for_recipes",
        unexpected_global_reconciliation,
    )

    def batch_context(page_urls):
        return {
            "recipe_urls": page_urls,
            "food_rules": [],
            "recipe_view_rows": [
                {"number": index, "url": recipe["url"], "sections": {}}
                for index, recipe in enumerate(page_urls, start=1)
            ],
            "cookbook_view": {"cookbooks": []},
            "cookbook_count": 0,
            "cookbook_recipe_count": 0,
            "cookbook_assignments": {},
        }

    def unexpected_quantity_projection(_recipes):
        nonlocal quantity_projection_called
        quantity_projection_called = True
        return []

    def quantity_lookup(rows):
        quantity_input.extend(row["url"] for row in rows)
        return {}

    monkeypatch.setattr(main_routes, "recipe_view_batch_context", batch_context)
    monkeypatch.setattr(main_routes, "recipe_quantity_rows", unexpected_quantity_projection)
    monkeypatch.setattr(main_routes, "recipe_quantity_lookup", quantity_lookup)
    monkeypatch.setattr(main_routes, "recipe_quantity_sources_lookup", lambda rows: {})
    monkeypatch.setattr(main_routes, "apply_manual_item_quantities", lambda quantities, state: quantities)

    context = main_routes.shopping_views_context(recipe_page=2, recipe_batch_only=True)

    assert global_reconciliation_called is False
    assert quantity_projection_called is False
    assert quantity_input == []
    assert [row["number"] for row in context["recipe_view_rows"]] == [9, 10]
    assert context["recipe_view_pagination"]["has_more"] is False


def test_quantity_projection_explicitly_skips_ingredient_image_variants(monkeypatch):
    recipe_url = "https://example.test/recipe-1"
    include_images = []

    monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(
        main_routes,
        "load_saved_recipe_output",
        lambda url: {"ingredients": [{"ingredient": "Flour", "quantity": 1, "unit": "cup"}]},
    )

    def build_sections(*args, **kwargs):
        include_images.append(kwargs.get("include_images"))
        return {"PANTRY": [{"display_name": "Flour", "quantity_display": "1 cup"}]}

    monkeypatch.setattr(main_routes, "build_recipe_sections", build_sections)

    rows = main_routes.recipe_quantity_rows([
        {"url": recipe_url, "name": "Recipe 1", "quantity": 1},
    ])

    assert include_images == [False]
    assert rows[0]["sections"]["PANTRY"][0]["quantity_display"] == "1 cup"


def test_recipe_view_pagination_loads_targets_and_blocks_partial_reorders():
    template = (ROOT / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert 'data-recipe-view-page="{{ recipe_pagination.page if recipe_pagination else 1 }}"' in template
    assert "data-recipe-view-load-more" in template
    assert "data-recipe-order-control" in template
    assert "Load all recipes to reorder" in template
    assert "async function loadMoreRecipeViewPage" in script
    assert "async function loadRecipeViewUntilRecipeAvailable" in script
    assert "await loadRecipeViewUntilRecipeAvailable(state.recipeUrl);" in script
    assert "!recipeViewOrderIsComplete(list)" in script
    assert "itemStateRoots: nextCards" in script
    assert "scheduleImagePoll: false" in script


def test_dynamic_item_check_initialization_is_scoped_and_idempotent():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    initializer = script[
        script.index("function restoreItemCheckState"):
        script.index("function syncItemCheckedState")
    ]

    assert "function restoreItemCheckState(root = document)" in initializer
    assert 'scope.querySelectorAll(".row[data-key]")' in initializer
    assert 'checkbox.dataset.itemCheckStateBound !== "1"' in initializer
    assert 'checkbox.dataset.itemCheckStateBound = "1"' in initializer
    assert initializer.index('checkbox.dataset.itemCheckStateBound !== "1"') < initializer.index(
        'checkbox.addEventListener("change"'
    )
