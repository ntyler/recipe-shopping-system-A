from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_restaurant_selector_is_searchable_accessible_and_header_scoped():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")

    header_start = template.index('<header class="recipe-edit-restaurant-modal-header">')
    header_end = template.index("</header>", header_start)
    header = template[header_start:header_end]

    assert header.index("recipeEditRestaurantModalTitle") < header.index("data-restaurant-selector")
    assert header.index("data-restaurant-selector") < header.index("recipe-edit-restaurant-modal-close")
    assert 'role="combobox"' in header
    assert 'aria-autocomplete="list"' in header
    assert 'aria-controls="recipeEditRestaurantSelectorList"' in header
    assert 'role="listbox"' in header
    assert 'data-restaurant-selector-status aria-live="polite"' in header
    assert ".recipe-edit-restaurant-modal-header {" in css
    assert "grid-template-columns: max-content minmax(320px, 560px) 38px;" in css
    assert 'grid-template-areas:' in css
    assert '"selector selector"' in css


def test_restaurant_selector_switch_create_and_recipe_specific_url_behavior():
    script = read_text("PushShoppingList/static/js/app.js")

    assert 'fetch(`/api/recipe/restaurants?q=' in script
    assert 'fetch(`/api/recipe/restaurants/${encodeURIComponent(id)}`)' in script
    assert "No restaurants found" in script
    assert "+ Create New Restaurant" in script
    assert "function handleRecipeRestaurantSelectorKeydown(input, event)" in script
    selector_keydown = script[
        script.index("function handleRecipeRestaurantSelectorKeydown(input, event)"):
        script.index("function currentRecipeRestaurantSourceOption()")
    ]
    escape_branch = selector_keydown[
        selector_keydown.index('if (event.key === "Escape")'):
        selector_keydown.index('if (event.key === "Tab")')
    ]
    assert "const selectorList = recipeRestaurantSelectorElements().list;" in escape_branch
    assert "if (!selectorList || selectorList.hidden) return true;" in escape_branch
    assert "event.stopPropagation();" in escape_branch
    assert "closeRecipeRestaurantSelector({ restoreValue: true });" in escape_branch
    assert "function beginCreateRecipeRestaurant(button, options = {})" in script
    assert 'window.confirm("You have unsaved restaurant changes. Discard them and switch restaurants?")' in script
    assert 'save.textContent = recipeRestaurantEditCreateMode ? "Create Restaurant" : "Save Changes";' in script
    assert 'action: recipeRestaurantEditCreateMode ? "create" : "update"' in script
    assert "assign_restaurant: true" in script
    assert "create_anyway: Boolean(options.createAnyway)" in script
    assert 'field === "menu_item_url"' in script
    assert "recipeRestaurantOriginalMenuItemUrl" in script
    assert "loadRecipeRestaurantUsage(recipeRestaurantRecordId(record))" in script
    assert "function recipeRestaurantMenuIdForSave(selected)" in script
    assert "selectedRestaurantId === recipeRestaurantOriginalRestaurantId ? recipeRestaurantOriginalMenuId" in script
    assert "function syncRecipeRestaurantMenuSourceSelection(savedRestaurant)" in script
    assert "recipeEditMenuSourceOptions.unshift(normalizedOption)" in script
    assert 'document.getElementById("recipeEditMenuSourceSelect")' in script
    assert "setRecipeMenuRelationFields({" in script
    assert 'menu_section_id: relationshipChanged ? ""' in script
    assert 'menu_item_id: relationshipChanged ? ""' in script


def test_duplicate_create_response_offers_explicit_resolution_actions():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")

    assert "A similar restaurant already exists." in template
    assert "Select Existing Restaurant" in template
    assert "Create Anyway" in template
    assert 'response.status === 409 && data.duplicate_detected' in script
    assert "showRecipeRestaurantDuplicatePanel(data.duplicates)" in script
    assert "switchRecipeRestaurantSelection(recipeRestaurantRecordId(duplicate), { skipConfirm: true })" in script


def test_restaurant_editor_opens_without_an_existing_normalized_source():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function recipeRestaurantFallbackFromEditor()" in script
    assert 'recipeEditInputValue("recipeEditMenuItemUrl")' in script
    assert 'recipeEditInputValue("recipeEditDocumentSourceUrl")' in script
    assert 'recipeEditInputValue("recipeEditSourceUrl")' in script
    assert "const selected = linkedSource || recipeRestaurantFallbackFromEditor();" in script
    assert "const hasNormalizedRestaurant = Boolean(recipeRestaurantRecordId(selected));" in script
    assert "if (!modal || !form) return false;" in script
    assert "if (!modal || !form || !selected) return false;" not in script
    assert "recipeRestaurantEditCreateMode = !hasNormalizedRestaurant;" in script
    assert 'save.textContent = hasNormalizedRestaurant ? "Save Changes" : "Create Restaurant";' in script
    assert "else setRecipeRestaurantUsageEmpty();" in script
    assert "editButton.hidden =" not in script
    assert "canNormalizeFallback" in script
