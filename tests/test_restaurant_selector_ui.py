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
    assert 'type="text"' in header
    assert 'type="search"' not in header
    assert 'aria-autocomplete="list"' in header
    assert 'aria-controls="recipeEditRestaurantSelectorList"' in header
    assert 'role="listbox"' in header
    assert 'data-restaurant-selector-status aria-live="polite"' in header
    assert 'recipe-edit-restaurant-combobox-icon' not in header
    assert 'shell.svg_icon("search")' not in header
    assert 'shell.svg_icon("chevron-down")' not in header
    assert 'data-restaurant-selector-clear' in header
    assert 'aria-label="Clear restaurant selection"' in header
    assert 'title="Clear restaurant selection"' not in header
    assert 'onpointerdown="event.preventDefault(); event.stopPropagation()"' in header
    assert 'onclick="openRecipeRestaurantSelector(this)"' in header
    assert 'onclick="return clearRecipeRestaurantSelector(this, event)"' in header
    assert 'shell.svg_icon("x")' in header
    assert ".recipe-edit-restaurant-combobox-icon" not in css
    assert "padding: 8px 44px 8px 12px;" in css
    assert "appearance: none;" in css
    assert "background-image: none;" in css
    assert ".recipe-edit-restaurant-selector-toggle" not in css
    assert ".recipe-edit-restaurant-selector-clear[hidden]" in css
    assert "right: 12px;" in css
    assert "width: 32px;" in css
    assert "height: 32px;" in css
    clear_css = css[
        css.index(".recipe-edit-restaurant-modal-header .recipe-edit-restaurant-selector-clear {"):
        css.index(".recipe-edit-restaurant-modal-header .recipe-edit-restaurant-selector-clear[hidden]")
    ]
    assert "margin: 0;" in clear_css
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
    assert "function clearRecipeRestaurantSelector(button, event = null)" in script
    clear_handler = script[
        script.index("function clearRecipeRestaurantSelector(button, event = null)"):
        script.index("function handleRecipeRestaurantSelectorKeydown(input, event)")
    ]
    assert "event.stopPropagation();" in clear_handler
    assert "setRecipeRestaurantSelectorExpanded(false);" in clear_handler
    assert 'input.value = "";' in clear_handler
    assert 'input.dataset.restaurantSelectorSuppressOpen = "1";' in clear_handler
    assert "updateRecipeRestaurantSelectorClearButton();" in clear_handler
    assert "const hasSelectedRestaurant = !recipeRestaurantEditCreateMode" in script
    assert "Boolean(recipeRestaurantRecordId(recipeRestaurantEditSelection))" in script
    assert "toggleRecipeRestaurantSelector" not in script
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
    assert 'loadRecipeRestaurantUsage(recipeRestaurantRecordId(record), { query: "", reviewOnly: false })' in script
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


def test_restaurant_information_scan_is_evidence_backed_and_explicitly_applied():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert "Scan Restaurant Information" in template
    assert 'data-restaurant-fetch-button' in template
    assert 'data-restaurant-fetch-review' in template
    assert 'data-restaurant-scan-metrics' in template
    assert 'data-restaurant-scan-sources' in template
    assert 'data-restaurant-scan-unresolved' in template
    assert "Apply Selected" in template
    assert "Apply All High Confidence" in template
    assert "Rescan" in template
    assert 'aria-labelledby="recipeEditRestaurantFetchReviewTitle"' in template
    assert 'fetch(`/api/recipe/restaurants/${encodeURIComponent(restaurantId)}/fetch-details`' in script
    assert 'method: "POST"' in script
    assert "Scanning restaurant information…" in script
    assert "renderRecipeRestaurantFetchReview(data)" in script
    assert "row.requires_explicit_review" in script
    assert "View source" in script
    assert "Lock existing" in script
    assert "Keep Current Logo" in script
    assert "Apply New Logo" in script
    assert "applyRecipeRestaurantInformationScan" in script
    assert "updateRecipeRestaurantEditState(form);" in script
    assert 'fetch-details", methods=["POST"]' in routes
    assert 'apply-information-scan", methods=["POST"]' in routes


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


def test_restaurant_scan_review_formats_provider_results_and_equivalent_values():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert 'ordering_providers: { label: "Ordering providers" }' in script
    assert 'allergy_information_note: { label: "Allergy information" }' in script
    assert 'restaurant_note: { label: "Restaurant note" }' in script
    assert "function recipeRestaurantFetchCandidateHtml(key, candidate)" in script
    assert 'key === "weekly_hours"' in script
    assert 'class="recipe-edit-restaurant-scan-address"' in script
    assert 'class="recipe-edit-restaurant-scan-providers"' in script
    assert 'noChange ? "No change"' in script
    assert 'label: "Possible misclassified platform URL"' in script
    assert ".recipe-edit-restaurant-scan-hours summary" in css
    assert ".recipe-edit-restaurant-scan-address" in css
    assert ".recipe-edit-restaurant-scan-providers" in css
    assert ".recipe-edit-restaurant-fetch-row.is-no-change" in css
