from pathlib import Path

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


def test_recipe_ingredient_store_tools_sit_under_quantity():
    root = Path(__file__).resolve().parents[1]
    items_template = (root / "PushShoppingList/templates/sections/items.html").read_text(encoding="utf-8")
    css = (root / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    recipe_ingredient_block = items_template[items_template.index("{% for recipe_item in section_items %}"):]

    assert 'class="row recipe-ingredient-row"' in recipe_ingredient_block
    assert 'class="item-row-tools recipe-ingredient-store-tools"' in recipe_ingredient_block
    assert recipe_ingredient_block.index('class="source-line item-qty-line"') < recipe_ingredient_block.index(
        'include "sections/item_store_price_grid.html"'
    )
    assert recipe_ingredient_block.index('include "sections/item_store_price_grid.html"') < recipe_ingredient_block.index(
        'include "sections/product_choice_line.html"'
    )
    assert ".recipe-ingredient-row .item-row-tools.recipe-ingredient-store-tools" in css
    assert "grid-template-columns: 30px minmax(0, 1fr) auto" in css
