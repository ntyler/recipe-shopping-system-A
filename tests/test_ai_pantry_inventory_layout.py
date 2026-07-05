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
    assert "pantry_storage_locations" in template
    assert "pantry_storage_location_values" in template
    assert "pantry_has_removable_storage_locations" in template
    assert "ai-pantry-location-manager" in template
    assert "aiPantryLocations" in template
    assert "add_pantry_storage_location_route" in template
    assert "delete_pantry_storage_locations_route" in template
    assert "update_pantry_storage_location_route" in template
    assert "pantryLocationDeleteForm" in template
    assert "ai-pantry-location-choice" in template
    assert "ai-pantry-location-choice-check" in template
    assert "data-pantry-location-choice" in template
    assert "data-pantry-location-checkbox" in template
    assert "data-pantry-location-edit-input" in template
    assert "ai-pantry-location-remove-btn" in template
    assert "data-pantry-location-remove-selected" in template
    assert 'role="checkbox"' in template
    assert 'aria-checked="false"' in template
    assert 'name="store_section"' in template
    assert "Store Section" in template
    assert "ai-pantry-inventory-store-section-label" in template
    assert "ai-pantry-inventory-source-link" in template
    assert "view_pantry_receipt_file_route" in template
    assert "View Receipt PDF" in template
    frozen_on_index = template.index("<span>Frozen On</span>")
    store_section_index = template.index("ai-pantry-inventory-store-section-label")
    notes_index = template.index("ai-pantry-inventory-notes-label")
    source_link_index = template.index("ai-pantry-inventory-source-link")
    assert frozen_on_index < store_section_index < source_link_index < notes_index
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
    assert (
        "#aiPantrySection.user-ai-pantry-panel .ai-pantry-inventory-row {\n"
        "    grid-template-columns: 24px 44px 44px minmax(0, 1fr) 42px;"
    ) in css
    assert (
        "#aiPantrySection.user-ai-pantry-panel .ai-pantry-inventory-select {\n"
        "    grid-column: 3 / 4;\n"
        "    grid-row: 1;\n"
        "}"
    ) in css
    assert (
        "#aiPantrySection.user-ai-pantry-panel .ai-pantry-inventory-name {\n"
        "    grid-column: 4 / 5;\n"
        "    grid-row: 1;"
    ) in css
    assert ".ai-pantry-inventory-row-collapsed {" in css
    assert ".ai-pantry-inventory-details-toggle" in css
    assert ".ai-pantry-inventory-details-icon" in css
    assert ".ai-pantry-inventory-row-collapsed .ai-pantry-inventory-notes-preview" in css
    assert ".ai-pantry-inventory-bulk-actions" in css
    assert ".ai-pantry-location-manager" in css
    assert ".ai-pantry-location-form" in css
    assert ".ai-pantry-location-choice" in css
    assert ".ai-pantry-location-choice-check" in css
    assert "opacity: 0;" in css
    assert ".ai-pantry-location-choice:has(.ai-pantry-location-choice-check:checked)" in css
    assert ".ai-pantry-location-edit-input" in css
    assert ".ai-pantry-location-save-btn" in css
    assert ".ai-pantry-location-remove-btn" in css
    assert ".ai-pantry-inventory-select" in css
    assert ".ai-pantry-inventory-select:hover" in css
    assert "min-width: 44px;" in css
    assert ".ai-pantry-meta-store-section select" not in css
    assert ".ai-pantry-delete-selected-btn" in css
    assert ".ai-pantry-inventory-row [data-pantry-inventory-details][hidden]" in css
    assert ".ai-pantry-inventory-row .ai-pantry-inventory-source-link" in css
    assert ".ai-pantry-inventory-source-link a" in css
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
    assert "function bindPantryLocationChoices" in js
    assert "function bindPantryInventoryDetails" in js
    assert "function bindPantryInventoryBulkDelete" in js
    assert "function confirmDeleteSelectedPantryItems" in js
    assert "bindPantryLocationChoices(options.root || document);" in js
    assert "bindPantryInventoryDetails(options.root || document);" in js
    assert "bindPantryInventoryBulkDelete(options.root || document);" in js
    assert '["bindPantryLocationChoices", bindPantryLocationChoices]' in js
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
    assert "ai-pantry-location-manager" in html
    assert "Pantry" in html
    assert "Fridge" in html
    assert "Freezer" in html
    assert "Counter" in html
