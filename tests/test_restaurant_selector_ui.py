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
    assert 'recipe-edit-restaurant-combobox-icon' not in header
    assert 'shell.svg_icon("search")' not in header
    assert 'shell.svg_icon("chevron-down")' in header
    assert ".recipe-edit-restaurant-combobox-icon" not in css
    assert "padding: 8px 44px 8px 12px;" in css
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


def test_restaurant_details_fetch_is_backend_only_and_reviewed_before_form_changes():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert "Fetch Restaurant Details" in template
    assert 'data-restaurant-fetch-button' in template
    assert 'data-restaurant-fetch-review' in template
    assert "Apply Selected" in template
    assert "Apply All" in template
    assert 'aria-labelledby="recipeEditRestaurantFetchReviewTitle"' in template
    assert 'fetch(`/api/recipe/restaurants/${encodeURIComponent(restaurantId)}/fetch-details`' in script
    assert 'method: "POST"' in script
    assert "Fetching details…" in script
    assert "renderRecipeRestaurantFetchReview(data)" in script
    assert 'found && !conflict ? "checked"' in script
    assert "Differs from current value" in script
    assert "Not found" in script
    assert "applyRecipeRestaurantFetchedDetails" in script
    assert "updateRecipeRestaurantEditState(form);" in script
    assert 'fetch-details", methods=["POST"]' in routes


def test_restaurant_details_fetch_review_is_responsive_and_does_not_replace_save():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "recipe-edit-restaurant-fetch-review-list" in template
    assert "Save Changes" in template
    assert ".recipe-edit-restaurant-fetch-review {" in css
    assert "position: absolute;" in css
    assert "overflow-y: auto;" in css
    assert ".recipe-edit-restaurant-fetch-row.has-conflict" in css
    assert ".recipe-edit-restaurant-fetch-review[hidden]" in css
    assert "display: none !important;" in css
