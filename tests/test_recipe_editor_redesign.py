from pathlib import Path

from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def configure_recipe_editor_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *args, **kwargs: None)

    return output_dir


def test_standalone_recipe_editor_uses_app_shell_navigation():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")

    assert "app-shell-body recipe-edit-standalone-page" in template
    assert "app-sidebar recipe-edit-page-sidebar" in template
    assert "recipe-edit-page-main-shell" in template
    assert "recipe-edit-standalone-shell" in template
    assert "{% include \"sections/current_recipe_url_log.html\" %}" in template
    assert 'data-app-sidebar-collapse' in template
    assert 'class="app-global-search"' in template
    assert "organizeRecipeEditStandaloneWorkspace()" in template


def test_standalone_recipe_editor_matches_homepage_width_without_a_max_cap():
    css = read_text("PushShoppingList/static/css/app.css")
    rule_start = css.index(".recipe-edit-standalone-page .recipe-edit-standalone-shell {")
    rule_end = css.index("}", rule_start)
    shell_rule = css[rule_start:rule_end]

    assert "width: calc(100% - 48px);" in shell_rule
    assert "max-width: none;" in shell_rule
    assert "width: min(" not in shell_rule


def test_standalone_recipe_editor_has_an_independent_main_scroll_region():
    css = read_text("PushShoppingList/static/css/app.css")

    main_rule_start = css.index(".recipe-edit-page-main-shell {")
    main_rule = css[main_rule_start:css.index("}", main_rule_start)]
    page_rule_start = css.index(".recipe-edit-standalone-page {", main_rule_start)
    page_rule = css[page_rule_start:css.index("}", page_rule_start)]
    shell_rule_start = css.index(".recipe-edit-standalone-page .recipe-edit-page-shell {", page_rule_start)
    shell_rule = css[shell_rule_start:css.index("}", shell_rule_start)]
    content_rule_start = css.index(".recipe-edit-standalone-page .recipe-edit-standalone-shell {", main_rule_start)
    content_rule = css[content_rule_start:css.index("}", content_rule_start)]

    assert "height: 100vh;" in page_rule
    assert "overflow: hidden;" in page_rule
    assert "height: 100vh;" in shell_rule
    assert "min-height: 0;" in shell_rule
    assert "display: flex;" in main_rule
    assert "flex-direction: column;" in main_rule
    assert "min-height: 0;" in main_rule
    assert "overflow: hidden;" in main_rule
    assert "flex: 1 1 auto;" in content_rule
    assert "min-width: 0;" in content_rule
    assert "min-height: 0;" in content_rule
    assert "overflow-x: hidden;" in content_rule
    assert "overflow-y: auto;" in content_rule


def test_recipe_editor_redesign_preserves_core_fields_and_actions():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")

    assert "recipe-edit-breadcrumb" in template
    assert "Preview Recipe" in template
    assert "recipe-edit-layout" in template
    assert "recipe-edit-main-workspace" in template
    assert "recipeEditUtilityColumn" in template
    assert "recipe-edit-context-sidebar" in template
    assert "recipeEditBreadcrumbName" in template
    assert "recipeEditImageCardContent" in template
    assert "recipe-edit-tab-list" in template
    assert 'data-recipe-edit-tab="ingredients"' in template
    assert 'data-recipe-edit-tab="instructions"' in template
    assert 'data-recipe-edit-tab="equipment"' in template
    assert 'data-recipe-edit-tab="nutrition"' in template
    assert 'data-recipe-edit-tab="notes"' in template
    assert "recipe-edit-source-documents-card" in template
    assert "data-document-download" in template
    assert "recipe-edit-restaurant-card" in template
    assert "recipeEditIngredientGallery" in template
    assert "recipeEditHealthList" in template
    assert "recipe-edit-ai-assistant-card" in template
    assert "recipeEditAiMissingFields" in template
    assert "recipeEditAiConfidenceCard" in template
    assert "beginRecipeIngredientReorder(this)" in template
    assert "focusRecipeIngredientGrouping(this)" in template


def test_recipe_editor_header_actions_match_the_mockup_order_and_icons():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    css = read_text("PushShoppingList/static/css/app.css")
    actions = template[
        template.index('<div class="recipe-edit-header-actions">'):
        template.index('<input type="hidden" name="original_url"')
    ]

    assert actions.index("recipe-edit-preview-button") < actions.index("recipeEditPdfButton")
    assert actions.index("recipeEditPdfButton") < actions.index("recipe-edit-header-menu-wrap")
    assert actions.index("recipe-edit-header-menu-wrap") < actions.index("recipe-edit-header-cancel")
    assert actions.index("recipe-edit-header-cancel") < actions.index("recipe-edit-header-save")
    assert '{{ shell.svg_icon("eye") }}' in actions
    assert '{{ shell.svg_icon("document") }}' in actions
    assert '{{ shell.svg_icon("more") }}' in actions
    assert '{{ shell.svg_icon("check") }}' in actions
    assert 'aria-haspopup="menu"' in actions
    assert 'aria-expanded="false"' in actions
    assert "height: 42px;" in css
    assert "min-width: 138px;" in css

    javascript = read_text("PushShoppingList/static/js/app.js")
    assert 'event.key !== "Escape"' in javascript
    assert 'document.addEventListener("keydown", handleRecipeEditRowMenuEscape)' in javascript

    for field_id in [
        "recipeEditDisplayName",
        "recipeEditTitleInput",
        "recipeEditDescription",
        "recipeEditSourceUrl",
        "recipeEditSourceMenuUrl",
        "recipeEditSourcePdfPath",
        "recipeEditSourceCloudflarePdfUrl",
        "recipeEditGeneratedPdfPath",
        "recipeEditGeneratedCloudflarePdfUrl",
        "recipeEditRestaurantName",
        "recipeEditRestaurantWebsiteUrl",
        "recipeEditRestaurantPhone",
        "recipeEditRestaurantAddress",
        "recipeEditCategoryMenuSection",
        "recipeEditLevel",
        "recipeEditTotalTime",
        "recipeEditPrepTime",
        "recipeEditInactiveTime",
        "recipeEditCookTime",
        "recipeEditServings",
        "recipeEditInferOverwriteAiFields",
        "recipeEditInferPreviewOnly",
    ]:
        assert f'id="{field_id}"' in template

    assert "inferMissingRecipeDetails(this)" in template
    assert "confirmDeleteRecipeFromEditor(this, event)" in template
    assert 'type="submit" class="recipe-edit-save"' in template


def test_restaurant_source_card_uses_compact_identity_details_and_actions():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    card_start = template.index('<details class="recipe-edit-context-card recipe-edit-restaurant-card"')
    card_end = template.index("</details>", card_start)
    card = template[card_start:card_end]

    assert card.index("Restaurant Source") < card.index("recipe-edit-restaurant-edit")
    assert card.index("recipe-edit-restaurant-avatar") < card.index("recipe-edit-restaurant-rating")
    assert card.index('data-restaurant-detail-row="phone"') < card.index("recipe-edit-restaurant-actions")
    assert card.index('data-restaurant-detail="website"') < card.index("recipe-edit-restaurant-actions")
    assert card.index('data-restaurant-detail-row="address"') < card.index("recipe-edit-restaurant-actions")
    assert card.count('data-restaurant-action="') == 3
    assert card.index('data-restaurant-action="website"') < card.index('data-restaurant-action="menu"')
    assert card.index('data-restaurant-action="menu"') < card.index('data-restaurant-action="map"')
    assert card.rfind("recipe-edit-restaurant-edit") < card.index("recipe-edit-restaurant-summary")
    assert "selectedSource.restaurant_logo_url" in script
    assert "selectedSource.restaurant_rating" in script
    assert "encodeURIComponent(address)" in script
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert ".recipe-edit-standalone-page .recipe-edit-restaurant-details {" in css


def test_recipe_information_card_matches_compact_mockup_structure():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer_start = script.index("function organizeRecipeEditInformationCard()")
    organizer_end = script.index("function organizeRecipeEditAiAssistant()", organizer_start)
    organizer = script[organizer_start:organizer_end]

    assert 'primaryRow.className = "recipe-edit-primary-fields"' in organizer
    assert 'tagRow.className = "recipe-edit-tag-row"' in organizer
    assert 'metadataRow.className = "recipe-edit-metadata-strip"' in organizer
    assert 'descriptionRow.className = "recipe-edit-description-row"' in organizer
    assert "addRecipeEditMetadataIcon(servingsField, \"servings\")" in organizer
    assert 'data-recipe-metadata-icon="servings"' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("utensils")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("cooking-pot")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "data-recipe-edit-cuisine-chips" in script
    assert "renderRecipeEditCuisineChips" in script
    assert "recipe-edit-price-control" in organizer
    assert 'ratingField.classList.add("recipe-edit-header-rating")' in organizer
    assert "panelHeading.appendChild(ratingField)" in organizer
    assert "appendRecipeEditWorkspaceChildren(technicalBody, [\n        titleField," in organizer
    assert "appendRecipeEditWorkspaceChildren(grid, [primaryRow, tagRow, metadataRow, descriptionRow, technicalDetails])" in organizer
    assert "if (infoActions) infoActions.hidden = true;" in organizer
    assert "technicalDetails.open = false;" in organizer
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in css
    assert "grid-template-columns: minmax(0, 2fr) minmax(145px, .9fr);" in css
    assert ".recipe-edit-price-prefix {" in css
    assert ".recipe-edit-tag-chip {" in css
    assert ".recipe-edit-description-count {" in css
    assert "updateRecipeEditDescriptionCount" in script
    assert 'value.replace(/\\s*(people|persons?|servings?|minutes?|mins?)' in script
    assert 'valueWrap.className = "recipe-edit-metadata-value"' in script
    assert 'unitLabel.className = "recipe-edit-metadata-unit"' in script
    assert "width: 68px;" in css
    assert "position: static;" in css
    assert "if (clear) clear.hidden = normalizedRating <= 0;" in script


def test_restaurant_source_edit_uses_accessible_modal_and_save_wiring():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    route = read_text("PushShoppingList/routes/recipe_routes.py")

    for field in (
        "restaurant_name", "restaurant_logo_url", "restaurant_rating", "restaurant_phone",
        "restaurant_website_url", "source_menu_url", "menu_item_url", "restaurant_street_address",
        "restaurant_city", "restaurant_state", "restaurant_postal_code", "restaurant_country",
        "restaurant_hours_text", "restaurant_current_status", "restaurant_promotions",
        "restaurant_online_payment_available", "restaurant_delivery_available",
    ):
        assert f'data-restaurant-edit-field="{field}"' in template
    assert "data-restaurant-edit-form" in template
    assert '<form class="recipe-edit-restaurant-form"' not in template
    assert '<div class="recipe-edit-restaurant-form" data-restaurant-edit-form role="form"' in template
    assert 'onclick="return editRecipeRestaurantSource(this, event)"' in template
    assert 'type="button" class="primary" data-restaurant-edit-save' in template
    assert "data-restaurant-edit-modal" in template
    assert 'role="dialog"' in template
    assert 'aria-modal="true"' in template
    assert "Edit Restaurant Source" in template
    assert "Save Changes" in template
    assert "Upload Image" in template
    assert "Use Image URL" in template
    assert "Clear Rating" in template
    assert template.count('data-restaurant-rating-value=') == 1
    assert "Restaurant's main website." in template
    assert "Page containing the full restaurant menu." in template
    assert "Direct source page or deep link for this recipe or menu item." in template
    assert "Advanced Restaurant Details" in template
    assert "Advanced Raw Data" in template
    assert 'data-restaurant-hours-day="{{ day }}"' in template
    assert "Optional rewards programs, discounts, or active promotions." in template
    assert "Temporarily Closed" in template
    assert "Permanently Closed" in template
    assert template.count('<option value="">Unknown</option>') >= 2
    assert "cancelRecipeRestaurantSourceEdit" in template
    assert "async function saveRecipeRestaurantSource(form)" in script
    assert "function editRecipeRestaurantSource(button, event = null)" in script
    assert "event.stopPropagation();" in script
    assert 'form.querySelector("input:invalid")' in script
    assert 'fetch("/api/recipe/restaurant-source"' in script
    assert 'save.textContent = "Saving..."' in script
    assert "recipeRestaurantEditSnapshot" in script
    assert "function recipeRestaurantModalFocusableElements()" in script
    assert "function currentRecipeRestaurantSourceOption()" in script
    assert "function chooseRecipeRestaurantLogoUpload(button)" in script
    assert "function setRecipeRestaurantRating(button, rating)" in script
    assert "function handleRecipeRestaurantRatingKeydown(button, event)" in script
    assert "function updateRecipeRestaurantStructuredHours(control)" in script
    assert "function toggleRecipeRestaurantSplitHours(button)" in script
    assert 'const restaurantId = recipeEditInputValue("recipeEditRestaurantId")' in script
    assert 'const selected = currentRecipeRestaurantSourceOption();' in script
    assert 'event.key === "Escape"' in script
    assert 'event.key !== "Tab"' in script
    assert "Discard unsaved restaurant changes?" in script
    assert 'document.body.classList.add("restaurant-source-modal-open")' in script
    assert "document.body.appendChild(modal);" in script
    assert ".map(element => ({ element, wasInert: Boolean(element.inert) }))" in script
    assert "item.element.inert = true" in script
    assert "item.element.inert = item.wasInert" in script
    assert 'trigger?.focus({ preventScroll: true })' in script
    assert '@recipe_bp.route("/api/recipe/restaurant-source", methods=["POST"])' in route
    assert ".recipe-edit-standalone-page .recipe-edit-restaurant-form {" in css
    assert ".recipe-edit-restaurant-modal-backdrop {" in css
    assert ".recipe-edit-restaurant-modal-body {" in css
    assert "width: min(1400px, calc(100vw - 48px));" in css
    assert "height: min(900px, calc(100vh - 32px));" in css
    assert "grid-template-columns: minmax(0, 48fr) minmax(0, 52fr);" in css
    assert "recipe-edit-restaurant-primary-column" in template
    assert "recipe-edit-restaurant-operational-column" in template
    assert "recipe-edit-restaurant-availability-row" in template
    assert "grid-template-columns: 64px 72px minmax(82px, 1fr) minmax(82px, 1fr) 72px;" in css
    assert "syncRecipeRestaurantHoursRow(row)" in script
    assert "flex: 1 1 auto;" in css
    assert "overflow-y: auto;" in css
    assert "overflow-x: hidden;" in css

    card_start = template.index('<details class="recipe-edit-context-card recipe-edit-restaurant-card"')
    card_end = template.index("</details>", card_start)
    assert "data-restaurant-edit-field" not in template[card_start:card_end]
    assert template.index("data-restaurant-edit-modal") > card_end


def test_source_documents_card_uses_compact_rows_and_edit_modal():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    card_start = template.index('<section class="recipe-edit-context-card recipe-edit-source-documents-card"')
    card_end = template.index('<div class="recipe-edit-source-documents-modal-backdrop"', card_start)
    card = template[card_start:card_end]
    expected_labels = (
        "Source URL",
        "Source Menu URL",
        "Source PDF",
        "Cloudflare Source PDF",
        "Generated PDF",
        "Cloudflare Generated PDF",
    )

    assert "recipe-edit-source-documents-help" in card
    assert "recipeEditSourceDocumentsHelp" in card
    assert 'role="dialog"' in card
    assert "Original webpage the recipe was imported from." in card
    assert "Use Open to view a document." in card
    assert "recipe-edit-context-chevron" not in card
    assert "<summary>" not in card
    assert "recipe-edit-source-documents-toggle" not in card
    assert 'class="recipe-edit-source-documents-edit"' in card
    assert "toggleRecipeSourceDocumentsCard" not in script
    assert 'onclick="return editRecipeSourceDocuments(this, event)"' in card
    assert card.count("data-recipe-edit-document-row") == len(expected_labels)
    assert card.count("recipe-edit-document-icon") == len(expected_labels)
    assert card.count("recipe-edit-document-identity") == len(expected_labels)
    assert "recipe-edit-document-more" not in card
    assert card.count("data-document-open hidden") == len(expected_labels)
    assert card.count("recipe-edit-document-secondary") == 6
    assert card.count('shell.svg_icon("link")') == 2
    assert card.count('data-document-external title=') == 2
    assert card.count('shell.svg_icon("external-link")') == 4
    assert 'aria-label="Open source URL in new tab"' in card
    assert 'aria-label="Open source menu URL in new tab"' in card
    assert 'external.href = externalHref || "#";' in script
    assert card.count('shell.svg_icon("document")') == 4
    assert card.count('shell.svg_icon("external-link")') == 4
    assert card.count('shell.svg_icon("download")') == 1
    assert card.count('shell.svg_icon("cloud-upload")') == 1
    assert all(label in card for label in expected_labels)
    assert 'row.hidden = !hasValue;' in script
    assert 'status.title = `${sourceValue} (click to copy)`;' in script
    assert 'open.setAttribute("aria-disabled", canOpen ? "false" : "true");' in script
    assert ".recipe-edit-standalone-page .recipe-edit-document-row {" in css
    assert "grid-template-columns: 32px minmax(0, 1fr) auto 28px;" in css
    assert "text-overflow: ellipsis;" in css
    assert ".recipe-edit-standalone-page .recipe-edit-document-secondary {" in css
    assert 'data-document-input-id="recipeEditGeneratedPdfPath"] { order: 4; }' in css
    assert "function recipeEditDocumentSlug(value, fallback = \"document\")" in script
    assert "function toggleRecipeSourceDocumentsHelp" in script
    assert "function editRecipeSourceDocuments(button, event = null)" in script
    assert "Edit Source &amp; Documents" in template
    assert 'data-source-documents-edit-modal' in template
    assert 'aria-modal="true"' in template
    assert 'fetch("/api/recipe/source-documents"' in script
    assert "Advanced Document Management" in template
    assert "Regenerate PDF" in template
    assert "Refresh Upload" in template
    assert "function uploadRecipeSourcePdfToCloudflare" in script
    assert 'kind: "webpage_backup"' in script

def test_recipe_editor_keeps_five_tabs_and_table_overflow_inside_the_workspace():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    tab_list_start = template.index('<div class="recipe-edit-tab-list"')
    tab_list_end = template.index('<div class="recipe-edit-tab-panels">', tab_list_start)
    tab_list = template[tab_list_start:tab_list_end]
    expected_tabs = ["ingredients", "instructions", "equipment", "nutrition", "notes"]

    assert tab_list.count('data-recipe-edit-tab="') == len(expected_tabs)
    assert [tab_list.index(f'data-recipe-edit-tab="{tab}"') for tab in expected_tabs] == sorted(
        tab_list.index(f'data-recipe-edit-tab="{tab}"') for tab in expected_tabs
    )
    assert tab_list.count('aria-selected="true"') == 1
    assert 'data-recipe-edit-tab="ingredients"' in tab_list[:tab_list.index('aria-selected="false"')]

    v4_css = css[css.index("/* Recipe workspace v4: homepage alignment and compact tab editors. */"):]
    tab_rule_start = v4_css.index(".recipe-edit-standalone-page .recipe-edit-tab-list {")
    tab_rule_end = v4_css.index("}", tab_rule_start)
    tab_rule = v4_css[tab_rule_start:tab_rule_end]
    panel_rule_start = v4_css.index(".recipe-edit-standalone-page .recipe-edit-tab-panels {")
    panel_rule_end = v4_css.index("}", panel_rule_start)
    panel_rule = v4_css[panel_rule_start:panel_rule_end]
    table_rule_start = v4_css.index(".recipe-edit-standalone-page .recipe-edit-ingredient-table-scroll {")
    table_rule_end = v4_css.index("}", table_rule_start)
    table_rule = v4_css[table_rule_start:table_rule_end]

    assert "justify-content: flex-start;" in tab_rule
    assert "width: 100%;" in tab_rule
    assert "max-width: 100%;" in tab_rule
    assert "overflow-x: hidden;" in tab_rule
    assert "overflow-x: hidden;" in panel_rule
    assert "overflow-x: auto;" in table_rule
    assert "overscroll-behavior-inline: contain;" in table_rule
    assert "min-width: 680px;" in v4_css

    tools_start = script.index("function organizeRecipeEditIngredientTools()")
    tools_end = script.index("function organizeRecipeEditEquipmentTools()", tools_start)
    tools_block = script[tools_start:tools_end]
    assert 'tableScroll.className = "recipe-edit-ingredient-table-scroll";' in tools_block
    assert "tableScroll.appendChild(tableHead);" in tools_block
    assert "tableScroll.appendChild(ingredientList);" in tools_block


def test_recipe_editor_compact_rows_keep_headers_actions_and_tool_organization():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    for class_name, labels in (
        ("recipe-edit-equipment-header", ("Image", "Equipment", "Options", "Edit", "Delete")),
        ("recipe-edit-instructions-header", ("Step", "Instruction", "Options", "Edit", "Delete")),
        ("recipe-edit-nutrition-header", ("Nutrient", "Value", "Options", "Edit", "Delete")),
    ):
        header_start = template.index(f'class="{class_name}"')
        header_end = template.index("</div>", header_start)
        header = template[header_start:header_end]
        positions = [header.index(f"<span>{label}</span>") for label in labels]
        assert positions == sorted(positions)

    compact_actions_start = script.index("function organizeRecipeEditCompactRowActions")
    compact_actions_end = script.index("function focusRecipeEditCompactRow", compact_actions_start)
    compact_actions = script[compact_actions_start:compact_actions_end]
    assert 'class="recipe-edit-compact-row-edit"' in compact_actions
    assert 'class="recipe-edit-compact-row-delete"' in compact_actions
    assert 'onclick="return focusRecipeEditCompactRow(this)"' in compact_actions
    assert 'onclick="return removeRecipeEditRow(this)"' in compact_actions
    for call in (
        'organizeRecipeEditCompactRowActions(row, \'[data-field="ingredient"]\', "ingredient");',
        'organizeRecipeEditCompactRowActions(row, \'[data-field="text"]\', "equipment");',
        'organizeRecipeEditCompactRowActions(row, \'[data-field="text"]\', "step");',
        'organizeRecipeEditCompactRowActions(row, \'[data-field="key"]\', "nutrition row");',
    ):
        assert call in script

    ingredient_tools = script[
        script.index("function organizeRecipeEditIngredientTools()"):script.index(
            "function organizeRecipeEditEquipmentTools()"
        )
    ]
    equipment_tools = script[
        script.index("function organizeRecipeEditEquipmentTools()"):script.index(
            "function organizeRecipeEditIngredientRow(row)"
        )
    ]
    assert 'viewSection.innerHTML = \'<div class="overflow-menu-section-title">Table View</div>\';' in ingredient_tools
    assert "viewSection.appendChild(collapseToggle);" in ingredient_tools
    assert 'viewSection.innerHTML = \'<div class="overflow-menu-section-title">Table View</div>\';' in equipment_tools
    assert "viewSection.appendChild(collapseToggle);" in equipment_tools

    v4_css = css[css.index("/* Recipe workspace v4: homepage alignment and compact tab editors. */"):]
    assert ".recipe-edit-standalone-page .recipe-edit-compact-row-actions {" in v4_css
    assert "display: contents;" in v4_css
    assert ".recipe-edit-standalone-page .recipe-edit-equipment-header," in v4_css
    assert ".recipe-edit-standalone-page .recipe-edit-instructions-header," in v4_css
    assert ".recipe-edit-standalone-page .recipe-edit-nutrition-header," in v4_css
    assert ".recipe-edit-standalone-page #recipeEditRecipeNotes > .recipe-edit-note-section-row," in v4_css
    assert "min-height: 0;" in v4_css
    assert "height: 30px;" in v4_css


def test_recipe_editor_redesign_javascript_wiring():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function initRecipeEditTabs()" in script
    assert "function organizeRecipeEditStandaloneWorkspace()" in script
    assert "function organizeRecipeEditInformationCard()" in script
    assert "function organizeRecipeEditIngredientTools()" in script
    assert "function organizeRecipeEditIngredientRow(row)" in script
    assert "function organizeRecipeEditHeaderActions()" in script
    assert "function setRecipeEditActiveTab(tabKey, options = {})" in script
    assert "function syncRecipeEditDocumentRows()" in script
    assert "function updateRecipeEditRestaurantCard()" in script
    assert "function updateRecipeEditIngredientGallery()" in script
    assert "function updateRecipeEditorHealth()" in script
    assert "function recipeEditHealthChecks()" in script
    assert "row.hidden = !hasValue;" in script
    assert "function toggleRecipeEditIngredientGallery" in script
    assert "function beginRecipeIngredientReorder" in script
    assert "function focusRecipeIngredientGrouping" in script
    assert "function previewRecipeFromEditor()" in script
    assert "function replaceRecipeIngredientWithSubstitution(button)" in script
    assert 'setValue("recipeEditDescription", recipe.description || "")' in script
    assert 'description: document.getElementById("recipeEditDescription")' in script
    assert "data-recipe-edit-health-item" in script
    assert "data-health-status" in script
    assert "data-document-download" in script
    assert "recipeBreadcrumbName.textContent" in script
    assert "[\"initRecipeEditTabs\", initRecipeEditTabs]" in script
    assert "[\"initRecipeEditContextPanels\", initRecipeEditContextPanels]" in script
    assert 'data-field="section"' in script
    assert "Replace ingredient with this option" in script
    assert script.count("setRecipeIngredientsCollapsed(!recipeEditorStandalonePageIsActive());") == 2


def test_recipe_editor_redesign_css_uses_app_tokens_and_mobile_breakpoints():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "Recipe workspace v3: target mockup structure with the homepage dark system" in css
    assert ".recipe-edit-standalone-page .recipe-edit-layout {" in css
    assert "grid-template-columns: minmax(0, 1.95fr) minmax(250px, 1fr) minmax(240px, .9fr);" in css
    assert ".recipe-edit-context-sidebar {" in css
    assert ".recipe-edit-tab-list {" in css
    assert ".recipe-edit-ingredient-table-head," in css
    assert ".recipe-edit-ingredient-advanced-details" in css
    assert ".recipe-edit-document-row {" in css
    assert ".recipe-edit-health-row" in css
    assert ".recipe-edit-ai-assistant-card {" in css
    assert ".recipe-edit-image-card .recipe-edit-cover-field {" in css
    assert ".recipe-edit-ai-assistant-card :is(" in css
    assert "--app-bg: #101415;" in css
    assert ".recipe-edit-ingredient-row label.recipe-edit-section-label" in css
    assert ".recipe-edit-substitution-row-menu:not([hidden])" in css
    assert "@media (max-width: 1499px)" in css
    assert "@media (max-width: 767px)" in css


def test_recipe_editor_description_loads_and_saves_existing_field(monkeypatch, tmp_path):
    configure_recipe_editor_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/description-soup"

    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Description Soup",
        "description": "A bright soup with herbs.",
        "ingredients": [{"ingredient": "tomato", "quantity": "2", "unit": "cups"}],
        "instructions": [{"instruction": "Simmer until warm."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    assert loaded["description"] == "A bright soup with herbs."

    result = recipe_edit_service.save_editable_recipe(url, {
        "source_url": url,
        "display_name": "Description Soup",
        "recipe_title": "Description Soup",
        "description": "A saved soup description.",
        "quantity": 1,
        "servings": "4",
        "level": "Easy",
        "total_time": "30 minutes",
        "prep_time": "10 minutes",
        "inactive_time": "",
        "cook_time": "20 minutes",
        "scaling": {},
        "ingredients": [{"ingredient": "tomato", "quantity": "2", "unit": "cups"}],
        "equipment": [],
        "instructions": [{"instruction": "Simmer until warm."}],
        "nutrition": [],
        "recipe_notes": [],
        "reflection_notes": [],
    })

    assert result["recipe"]["description"] == "A saved soup description."
    assert recipe_edit_service.load_recipe_output(url)["description"] == "A saved soup description."
