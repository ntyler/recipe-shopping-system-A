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
    assert 'class="ai-pantry-inventory-select"' not in template
    assert "pantryBulkDeleteForm" in template
    assert "Delete Selected" in template
    assert "data-pantry-inventory-select-visible" in template
    assert "data-pantry-receipt-filter" in template
    assert "Receipt Items" in template
    assert "data-pantry-image-filter" in template
    assert "Image Taken" in template
    assert "Receipt PDFs" in template
    assert "Uploaded Images" in template
    assert "data-pantry-source-detail-filter" in template
    assert 'data-pantry-source-detail-type="receipt-pdf"' in template
    assert 'data-pantry-source-detail-type="receipt-image"' in template
    assert 'data-pantry-source-detail-type="pantry-item-images"' in template
    assert "togglePantryInventorySourceFilter(this)" in template
    assert "data-pantry-store-section" in template
    assert "data-pantry-receipt-source" in template
    assert "data-pantry-receipt-id" in template
    assert "data-pantry-receipt-file-kind" in template
    assert "data-pantry-image-source" in template
    assert "data-pantry-item-image-source" in template
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
    assert 'size="1"' in template
    assert "ai-pantry-location-remove-btn" in template
    assert "data-pantry-location-remove-selected" in template
    location_controls_index = template.index('class="ai-pantry-location-control-stack"')
    save_updates_index = template.index('aria-label="Save pantry location updates"', location_controls_index)
    add_location_form_index = template.index('class="ai-pantry-location-form"', location_controls_index)
    assert location_controls_index < save_updates_index < add_location_form_index
    assert 'role="checkbox"' in template
    assert 'aria-checked="false"' in template
    assert 'name="store_section"' in template
    assert "Store Section" in template
    assert "ai-pantry-inventory-store-section-label" in template
    assert "ai-pantry-inventory-source-link" in template
    assert "ai-pantry-inventory-source-actions" in template
    assert "ai-pantry-inventory-source-filter-btn" in template
    assert "view_pantry_receipt_file_route" in template
    assert "View Receipt PDF" in template
    assert "Filter This Receipt" in template
    assert "Filter Image Set" in template
    assert 'data-pantry-source-detail-id="{{ item.source_receipt.receipt_id }}"' in template
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
        "    grid-template-columns: 24px 44px minmax(0, 1fr) 42px;"
    ) in css
    assert (
        "#aiPantrySection.user-ai-pantry-panel .ai-pantry-inventory-name {\n"
        "    grid-column: 3 / 4;\n"
        "    grid-row: 1;"
    ) in css
    assert ".ai-pantry-inventory-row-collapsed {" in css
    assert ".ai-pantry-inventory-details-toggle" in css
    assert ".ai-pantry-inventory-details-icon" in css
    assert ".ai-pantry-inventory-row-collapsed .ai-pantry-inventory-notes-preview" in css
    assert ".ai-pantry-inventory-bulk-actions" in css
    assert ".ai-pantry-inventory-filter-actions" in css
    assert ".ai-pantry-inventory-filter-btn" in css
    assert '.ai-pantry-inventory-filter-btn[aria-pressed="true"]' in css
    assert ".ai-pantry-source-filter-groups" in css
    assert ".ai-pantry-source-filter-chip" in css
    assert '.ai-pantry-source-filter-chip[aria-pressed="true"]' in css
    assert ".ai-pantry-location-manager" in css
    assert 'grid-template-areas: "locations controls";' in css
    assert ".ai-pantry-location-form" in css
    assert ".ai-pantry-location-control-stack" in css
    assert "justify-self: end;" in css
    assert "grid-area: controls;" in css
    assert ".ai-pantry-location-choice" in css
    assert ".ai-pantry-location-choice-check" in css
    assert "opacity: 0;" in css
    assert ".ai-pantry-location-choice:has(.ai-pantry-location-choice-check:checked)" in css
    assert ".ai-pantry-location-edit-input" in css
    assert "--pantry-location-input-ch" in css
    assert "width: calc(var(--pantry-location-input-ch, 6) * 1ch);" in css
    assert "min-width: 38px;" in css
    assert "flex: 0 1 auto;" in css
    assert ".ai-pantry-location-save-btn" in css
    assert ".ai-pantry-location-remove-btn" in css
    assert ".ai-pantry-inventory-number:hover" in css
    assert ".ai-pantry-inventory-number:has([data-pantry-inventory-checkbox]:checked)" in css
    assert "min-width: 44px;" in css
    assert ".ai-pantry-meta-store-section select" not in css
    assert ".ai-pantry-delete-selected-btn" in css
    assert ".ai-pantry-inventory-row [data-pantry-inventory-details][hidden]" in css
    assert ".ai-pantry-inventory-row .ai-pantry-inventory-source-link" in css
    assert "grid-column: span 2;" in css
    assert ".ai-pantry-inventory-source-actions" in css
    assert ".ai-pantry-inventory-source-link a" in css
    assert ".ai-pantry-inventory-source-filter-btn" in css
    assert '.ai-pantry-inventory-source-filter-btn[aria-pressed="true"]' in css
    assert ".ai-pantry-inventory-row .ai-pantry-inventory-notes-label" in css
    assert ".ai-pantry-inventory-handle {\n    grid-column: 1 / 2;\n    grid-row: 1;\n    align-self: start;" in css
    assert ".ai-pantry-inventory-number {\n    grid-column: 2 / 3;\n    grid-row: 1;\n    align-self: start;" in css
    assert ".ai-pantry-inventory-menu-wrap {\n    grid-column: 5 / 6;\n    grid-row: 1;\n    align-self: start;" in css
    assert "grid-column: 1 / -1;" in css
    assert ".ai-pantry-inventory-row .ai-pantry-inline-form textarea" in css
    assert "min-height: 58px;" in css
    assert ".recipe-step-image-actions [hidden]" in css
    assert "display: none !important;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 120px), 1fr));" in css
    assert "@media (max-width: 980px)" in css
    assert ".ai-pantry-card {\n    border: 0;" in css
    assert "background: transparent;" in css
    assert "function togglePantryInventorySourceFilter" in js
    assert "function activePantryInventoryDetailFilters" in js
    assert "function setMatchingPantrySourceDetailFiltersActive" in js
    assert "function pantryItemMatchesInventoryDetailFilter" in js
    assert "function pantryItemMatchesInventorySourceFilters" in js
    assert "function pantryItemMatchesReceiptFilter" in js
    assert "function pantryItemMatchesImageFilter" in js
    assert 'item.dataset.pantryReceiptSource === "1"' in js
    assert 'item.dataset.pantryImageSource === "1"' in js
    assert 'row.dataset.pantryImageSource = "1";' in js
    assert 'row.dataset.pantryItemImageSource = "1";' in js
    assert 'image.removeAttribute("hidden");' in js
    assert 'download.hidden = !imageUrl;' in js
    assert "status.hidden = Boolean(imageUrl);" in js
    assert 'image.removeAttribute("data-deferred-src");' in js
    assert 'filter.type === "receipt-pdf"' in js
    assert 'filter.type === "receipt-image"' in js
    assert 'filter.type === "pantry-item-images"' in js
    assert "setMatchingPantrySourceDetailFiltersActive(button, nextActive);" in js
    assert 'activeFilters.has("receipt")' in js
    assert 'activeFilters.has("image")' in js
    assert "function togglePantryInventoryDetails" in js
    assert '"#aiPantryInventory": "aiPantry"' in js
    assert '"#aiPantryLocations": "aiPantry"' in js
    assert 'aiPantryInventory: "pantry"' in js
    assert 'aiPantryLocations: "pantry"' in js
    assert "function submitPantryInventoryUpdate" in js
    assert "form.requestSubmit();" in js
    assert "onclick=\"return submitPantryInventoryUpdate(this)\"" in template
    assert "function resizePantryLocationEditInput" in js
    assert "resizePantryLocationEditInput(input);" in js
    assert 'input.addEventListener("input", event => {' in js
    assert 'input.addEventListener("change", event => {' in js
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
    assert "data-pantry-receipt-filter" in html
    assert "Receipt Items" in html
    assert "data-pantry-image-filter" in html
    assert "Image Taken" in html
    assert "Receipt PDFs" in html
    assert "Uploaded Images" in html
    assert "Pantry" in html
    assert "Fridge" in html
    assert "Freezer" in html
    assert "Counter" in html
