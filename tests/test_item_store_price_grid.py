from pathlib import Path

from PushShoppingList.routes import main_routes
from PushShoppingList.services.product_selection_service import store_price_cells_for_item


def test_store_price_cells_flag_cheapest_and_selected_store():
    cells = store_price_cells_for_item(
        {
            "cream cheese": {
                "store_results_list": [
                    {
                        "store_key": "aldi",
                        "store_name": "Aldi",
                        "best_product": {
                            "product_name": "Aldi Cream Cheese",
                            "price": "$1.79",
                            "unit_price": "$0.22/oz",
                        },
                    },
                    {
                        "store_key": "meijer",
                        "store_name": "Meijer",
                        "best_product": {
                            "product_name": "Meijer Cream Cheese",
                            "price": "$2.49",
                            "unit_price": "$0.31/oz",
                        },
                    },
                ],
            },
        },
        "cream cheese",
        {
            "aldi": {"label": "Aldi"},
            "meijer": {"label": "Meijer"},
        },
        ["aldi", "meijer"],
        "meijer",
    )

    assert [cell["label"] for cell in cells] == ["Aldi", "Meijer"]
    assert cells[0]["display_price"] == "$1.79"
    assert cells[0]["is_cheapest"] is True
    assert cells[0]["is_selected"] is False
    assert cells[1]["is_cheapest"] is False
    assert cells[1]["is_selected"] is True


def test_store_price_cells_fall_back_to_selected_product_store():
    cells = store_price_cells_for_item(
        {
            "cilantro": {
                "selected_product": {
                    "store_key": "aldi",
                    "store_name": "Aldi",
                    "product_name": "Fresh Cilantro",
                    "price": "$0.89",
                },
            },
        },
        "cilantro",
        {
            "aldi": {"label": "Aldi"},
            "meijer": {"label": "Meijer"},
        },
        ["aldi", "meijer"],
    )

    assert cells[0]["display_price"] == "$0.89"
    assert cells[0]["is_selected"] is True
    assert cells[0]["is_cheapest"] is True
    assert cells[1]["display_price"] == "--"


def test_item_rows_use_price_grid_and_overflow_menu():
    root = Path(__file__).resolve().parents[1]
    items_template = (root / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    price_grid = (root / "PushShoppingList/templates/sections/item_store_price_grid.html").read_text(encoding="utf-8")
    action_menu = (root / "PushShoppingList/templates/sections/item_row_action_menu.html").read_text(encoding="utf-8")
    css = (root / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    app_js = (root / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "sections/item_store_price_grid.html" in items_template
    assert "sections/item_row_action_menu.html" in items_template
    assert "item-store-price-grid" in price_grid
    assert "item-store-price-header" in price_grid
    assert "selectItemStoreFromPriceHeader(this)" in price_grid
    assert "openProductAlternatives(this)" in price_grid
    assert 'data-item-key="{{ product_choice_key }}"' in price_grid
    assert "item-row-menu recipe-edit-row-menu overflow-menu" in action_menu
    assert "item-store-price-cell.cheapest" in css
    assert "item-store-price-cell.selected" in css
    assert "item-store-price-header:focus-visible" in css
    assert "item-store-price-cell:focus-visible" in css
    assert "async function selectItemStoreFromPriceHeader" in app_js
    assert "await saveItemStoreSelection(itemKey, storeKey)" in app_js


def test_shopping_views_context_exposes_stores_for_lazy_item_menu(monkeypatch):
    stores = {
        "aldi": {"label": "Aldi", "url": "https://example.test/aldi?q="},
        "meijer": {"label": "Meijer", "url": "https://example.test/meijer?q="},
    }

    monkeypatch.setattr(main_routes, "load_items", lambda: [])
    monkeypatch.setattr(main_routes, "load_item_state", lambda: {})
    monkeypatch.setattr(
        main_routes,
        "load_store_settings",
        lambda: {"stores": stores, "enabled_stores": ["aldi", "meijer"]},
    )
    monkeypatch.setattr(main_routes, "product_choices_by_item", lambda: {})
    monkeypatch.setattr(
        main_routes,
        "recipe_rows_context",
        lambda **kwargs: {"recipe_view_rows": [], "food_rules": []},
    )
    monkeypatch.setattr(main_routes, "recipe_quantity_lookup", lambda rows: {})
    monkeypatch.setattr(main_routes, "recipe_quantity_sources_lookup", lambda rows: {})
    monkeypatch.setattr(main_routes, "apply_manual_item_quantities", lambda quantities, state: {})
    monkeypatch.setattr(main_routes, "purchase_mapping_lookup_for_items", lambda items, item_state=None: {})

    context = main_routes.shopping_views_context()

    assert context["available_stores"] == stores
    assert context["enabled_stores"] == ["aldi", "meijer"]


def test_recipe_ingredient_menu_sits_with_name_and_store_tools_sit_under_quantity():
    root = Path(__file__).resolve().parents[1]
    items_template = (root / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    css = (root / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    recipe_ingredient_block = items_template[items_template.index("{% for recipe_item in section_items %}"):]
    main_line_start = recipe_ingredient_block.index('class="item-main-line"')
    quantity_start = recipe_ingredient_block.index('class="source-line item-qty-line"')
    store_tools_start = recipe_ingredient_block.index('class="item-row-tools recipe-ingredient-store-tools"')

    assert 'class="row recipe-ingredient-row"' in recipe_ingredient_block
    assert 'class="item-row-tools recipe-ingredient-store-tools"' in recipe_ingredient_block
    assert main_line_start < recipe_ingredient_block.index('include "sections/item_row_action_menu.html"') < quantity_start
    assert quantity_start < store_tools_start < recipe_ingredient_block.index('include "sections/item_store_price_grid.html"')
    assert store_tools_start < recipe_ingredient_block.index('include "sections/product_choice_line.html"')
    assert ".recipe-ingredient-row .item-row-tools.recipe-ingredient-store-tools" in css
    assert ".recipe-ingredient-row .item-main-line .item-row-menu-wrap" in css
    assert "grid-template-columns: 30px minmax(0, 1fr)" in css
    assert "grid-template-columns: 30px minmax(0, 1fr) auto" not in css
