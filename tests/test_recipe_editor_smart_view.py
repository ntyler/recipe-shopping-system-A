from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html"
SCRIPT_PATH = ROOT / "PushShoppingList/static/js/app.js"
CSS_PATH = ROOT / "PushShoppingList/static/css/app.css"


def _function(script, name, next_name):
    start = script.index(f"function {name}")
    end = script.index(f"function {next_name}", start)
    return script[start:end]


def test_smart_view_replaces_the_placeholder_and_reuses_shared_actions():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    ingredient_start = template.index('id="recipeEditPanelIngredients"')
    ingredient_end = template.index('id="recipeEditPanelEquipment"', ingredient_start)
    ingredient_section = template[ingredient_start:ingredient_end]
    render = _function(
        script,
        "renderRecipeIngredientSmartView()",
        "toggleRecipeIngredientSmartView",
    )
    edit = _function(
        script,
        "editRecipeIngredientFromSmartView(button)",
        "toggleRecipeIngredientRecipeView",
    )

    assert "Smart View will be implemented in Phase 3." not in ingredient_section
    assert 'data-recipe-ingredient-view-panel="smart"' in ingredient_section
    assert 'role="list"' in ingredient_section
    assert "data-recipe-ingredient-smart-grid" in ingredient_section
    assert "data-recipe-ingredient-smart-empty" in ingredient_section
    assert ingredient_section.count("data-recipe-ingredient-smart-add") == 1
    assert ingredient_section.count("addRecipeIngredientFromCurrentView()") == 5

    assert "recipeEditIngredientRows().map(row =>" in render
    assert "fieldValuesFromRow(row)" in render
    assert "recipeIngredientSubstitutionDomGroups(" in render
    assert "ensureRecipeIngredientExpansionId(row)" in render
    assert "existingCards.get(key)" in render
    assert "grid.appendChild(card)" in render
    assert "fetch(" not in render
    assert "smartViewIngredients" not in script

    assert "card?.recipeIngredientSourceRow" in edit
    assert 'setRecipeEditIngredientView("table", { persist: false });' in edit
    assert "setRecipeIngredientEditMode(row, true, { trigger: button })" in edit
    assert "function addRecipeIngredientFromCurrentView()" in script
    assert "return addRecipeIngredientRow({}, { expanded: true });" in script


def test_smart_cards_reuse_images_status_store_sections_and_structured_options():
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    image = _function(
        script,
        "syncRecipeIngredientSmartViewImage(imageCell, values = {})",
        "createRecipeIngredientSmartViewCard",
    )
    card = _function(
        script,
        "renderRecipeIngredientSmartViewCard(card, row, values, alternativeGroups)",
        "layoutRecipeIngredientSmartView",
    )
    options = _function(
        script,
        "renderRecipeIngredientSmartViewOptions(",
        "renderRecipeIngredientSmartViewDetails",
    )
    details = _function(
        script,
        "renderRecipeIngredientSmartViewDetails(",
        "syncRecipeIngredientSmartViewCardExpanded",
    )

    assert "recipeIngredientImageUrl(values)" in image
    assert 'recipeImageVariantUrl(imageUrl, "thumb")' in image
    assert "recipeImageVariantSrcSet(imageUrl)" in image
    assert "handleRecipeIngredientSmartViewImageError(image)" in image
    assert "handleRecipeIngredientReadImageError(image)" in script
    assert "initDeferredImages(imageCell)" in image
    assert 'image.alt = "";' in image

    assert "recipeIngredientRecipeViewChoiceGroups(row, values, alternativeGroups)" in card
    assert "recipeIngredientRecipeViewName(values, choice.groups.length > 0)" in card
    assert "recipeIngredientRecipeViewAmount(values)" in card
    assert "recipeIngredientReadStatusHtml(" in card
    assert "recipeIngredientMatchItemFromRow(row, values)" in card
    assert "renderRecipeIngredientRecipeViewStore(" in card

    assert 'const defaultGroups = choiceGroups.filter(group => group.isDefaultOption);' in options
    assert 'const alternativeChoiceGroups = choiceGroups.filter(group => !group.isDefaultOption);' in options
    assert "group.values.forEach(values =>" in script
    assert "recipeIngredientChoiceItemSummary(" in script
    assert "recipeIngredientRecipeViewAmount(values)" in script
    assert 'label: "Default"' in options
    assert 'label: `Alternatives (${alternativeChoiceGroups.length})`' in options

    assert '"Buy As"' in details
    assert "recipeIngredientMeaningfulBuyAs(values)" in details
    assert "recipeIngredientRecipeViewName(values, true)" in details
    assert "recipeIngredientComparableText(groupedParentName)" in details
    assert '"Store Section"' in details
    assert "recipeIngredientStoreSectionIconHtml(storeSection)" in details
    assert '"Preparation"' in details
    assert '"Type"' in details
    assert "recipeIngredientTypeLabel(values)" in details
    assert 'notes || "Click to add notes\\u2026"' in details


def test_smart_expansion_is_single_stable_view_only_state_and_accessible():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    toggle = _function(
        script,
        "toggleRecipeIngredientSmartView(button)",
        "editRecipeIngredientFromSmartView",
    )
    expanded = _function(
        script,
        "syncRecipeIngredientSmartViewCardExpanded(card, expanded)",
        "renderRecipeIngredientSmartViewCard",
    )
    layout = _function(
        script,
        "layoutRecipeIngredientSmartView()",
        "scheduleRecipeIngredientSmartViewLayout",
    )

    assert 'let recipeEditExpandedSmartViewIngredientId = "";' in script
    assert "recipeEditExpandedSmartViewIngredientId !== key" in toggle
    assert "syncRecipeIngredientSmartViewCardExpanded(openCard, false);" in toggle
    assert "recipeEditExpandedSmartViewIngredientId = shouldExpand ? key : \"\";" in toggle
    assert "updateRecipeEditorDirtyState" not in toggle
    assert "scrollIntoView" not in toggle
    assert "scrollTop" not in toggle

    assert 'disclosure.setAttribute("aria-expanded", String(expanded));' in expanded
    assert 'disclosure.setAttribute("aria-controls", details?.id || "");' in expanded
    assert '${expanded ? "Collapse" : "Expand"} ${name || "ingredient"} details' in expanded
    assert 'edit.setAttribute("aria-label", `Edit ${name}`);' in script

    assert "const columnCount = width >= 700 ? 2 : 1;" in layout
    assert "index % 2" in layout
    assert "card.style.gridRow = `${start} / span ${height}`;" in layout
    assert ".recipe-edit-ingredient-smart-grid" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert '.recipe-edit-ingredient-smart-grid[data-smart-columns="1"]' in css
    assert ".recipe-edit-ingredient-smart-card.is-expanded" in css
    assert ".recipe-edit-ingredient-smart-disclosure:focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_smart_projection_refreshes_with_row_edits_and_reordering():
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    summary = _function(
        script,
        "updateRecipeIngredientSummary(row)",
        "recipeEditIngredientRows",
    )
    indexes = _function(
        script,
        "updateRecipeIngredientRowIndexes()",
        "toggleRecipeEditRowMenu",
    )
    actions = _function(
        script,
        "syncRecipeEditIngredientViewActions(section, view)",
        "recipeIngredientRecipeViewAmount",
    )

    assert "renderRecipeIngredientRecipeView();" in summary
    assert "renderRecipeIngredientSmartView();" in summary
    assert "renderRecipeIngredientRecipeView();" in indexes
    assert "renderRecipeIngredientSmartView();" in indexes
    assert 'action.hidden = view !== "table";' in actions
    assert 'const tableIsActive = view === "table";' in actions
