from pathlib import Path

from app import app


ROOT = Path(__file__).resolve().parents[1]


def test_ai_pantry_inventory_uses_recipe_editor_style_markup():
    template = (ROOT / "PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    js = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert '<a href="#aiPantryInventory">Inventory</a>' in template
    assert "ai-pantry-inventory-section" in template
    assert "recipe-edit-section-header ai-pantry-inventory-header" in template
    assert "recipe-edit-section-title" in template
    assert "Inventory <span class=\"ai-pantry-inventory-count\"" in template
    assert "ai-pantry-inventory-row" in template
    assert "recipe-edit-row-number ai-pantry-inventory-number" in template
    assert "data-pantry-inventory-checkbox" in template
    assert "pantryBulkDeleteForm" in template
    assert "Delete Selected" in template
    assert "data-pantry-inventory-select-visible" in template
    assert "data-pantry-store-section" in template
    assert 'name="store_section"' in template
    assert "Store Section" in template
    assert "recipe-edit-row-menu-wrap ai-pantry-inventory-menu-wrap" in template
    assert "ai-pantry-inventory-row-collapsed" in template
    assert "data-pantry-inventory-row" in template
    assert "data-pantry-inventory-details" in template
    assert "data-pantry-inventory-details-toggle" in template
    assert "ai-pantry-inventory-details-icon" in template
    assert "togglePantryInventoryDetails(this)" in template
    assert "Save inventory item" in template
    assert "Delete inventory item" in template
    assert "<textarea name=\"notes\"" in template
    assert ".ai-pantry-inventory-row" in css
    assert ".ai-pantry-inventory-header .recipe-edit-section-title h3" in css
    assert "#aiPantrySection.user-ai-pantry-panel .ai-pantry-inventory-row" in css
    assert ".ai-pantry-inventory-row-collapsed {" in css
    assert ".ai-pantry-inventory-details-toggle" in css
    assert ".ai-pantry-inventory-details-icon" in css
    assert ".ai-pantry-inventory-row-collapsed .ai-pantry-inventory-notes-preview" in css
    assert ".ai-pantry-inventory-bulk-actions" in css
    assert ".ai-pantry-inventory-select" in css
    assert ".ai-pantry-inventory-select:hover" in css
    assert "min-width: 44px;" in css
    assert ".ai-pantry-delete-selected-btn" in css
    assert ".ai-pantry-inventory-row [data-pantry-inventory-details][hidden]" in css
    assert ".ai-pantry-inventory-row .ai-pantry-inventory-notes-label" in css
    assert ".ai-pantry-inventory-handle {\n    grid-column: 1 / 2;\n    grid-row: 1;\n    align-self: start;" in css
    assert ".ai-pantry-inventory-number {\n    grid-column: 2 / 3;\n    grid-row: 1;\n    align-self: start;" in css
    assert ".ai-pantry-inventory-menu-wrap {\n    grid-column: 6 / 7;\n    grid-row: 1;\n    align-self: start;" in css
    assert "grid-column: 1 / -1;" in css
    assert ".ai-pantry-inventory-row .ai-pantry-inline-form textarea" in css
    assert "min-height: 58px;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 120px), 1fr));" in css
    assert "@media (max-width: 980px)" in css
    assert ".ai-pantry-card {\n    border: 0;" in css
    assert "background: transparent;" in css
    assert "function togglePantryInventoryDetails" in js
    assert "function bindPantryInventoryDetails" in js
    assert "function bindPantryInventoryBulkDelete" in js
    assert "function confirmDeleteSelectedPantryItems" in js
    assert "bindPantryInventoryDetails(options.root || document);" in js
    assert "bindPantryInventoryBulkDelete(options.root || document);" in js
    assert '["bindPantryInventoryDetails", bindPantryInventoryDetails]' in js
    assert '["bindPantryInventoryBulkDelete", bindPantryInventoryBulkDelete]' in js
    toggle_function_index = js.index("function togglePantryInventoryDetails")
    assert js.index("closeRecipeEditRowMenus();", toggle_function_index) < js.index(
        "setPantryInventoryDetailsCollapsed(row, !shouldExpand);",
        toggle_function_index,
    )


def test_ai_pantry_entry_forms_share_panel_layout():
    template = (ROOT / "PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="ai-pantry-add-form ai-pantry-form-surface"' in template
    assert 'class="ai-pantry-receipt-form ai-pantry-form-surface"' in template
    assert "ai-pantry-form-field-wide" in template
    assert "ai-pantry-submit-btn" in template
    assert ".ai-pantry-form-surface {" in css
    assert ".ai-pantry-form-field {" in css
    assert ".ai-pantry-submit-btn {" in css


def test_ai_pantry_inventory_renders_inventory_heading():
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = "pantry-user"

        response = client.get("/sections/pantry")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="#aiPantryInventory">Inventory</a>' in html
    assert "ai-pantry-inventory-section" in html
    assert "ai-pantry-inventory-count" in html
