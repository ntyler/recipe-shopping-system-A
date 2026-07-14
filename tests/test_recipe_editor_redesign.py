from pathlib import Path

from jinja2 import Environment
from jinja2 import FileSystemLoader

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


def test_restaurant_rating_macro_renders_exactly_five_toggleable_stars_without_clear_button():
    environment = Environment(loader=FileSystemLoader(ROOT / "PushShoppingList" / "templates"))
    template = environment.from_string(
        '{% import "includes/app_shell_macros.html" as shell %}'
        '{{ shell.rating_control("restaurantRating", "Restaurant rating", mode="restaurant") }}'
    )
    rendered = template.render()

    assert rendered.count('class="recipe-edit-rating-star"') == 5
    assert rendered.count('data-rating-value=') == 5
    assert rendered.count("&#9734;") == 5
    assert 'data-rating-toggle-selected="true"' in rendered
    assert 'role="radiogroup"' in rendered
    assert rendered.count('role="radio"') == 5
    assert rendered.count("click again to clear") == 5
    assert rendered.count("previewSharedRating") == 5
    assert "recipe-edit-rating-clear" not in rendered

    recipe_rendered = environment.from_string(
        '{% import "includes/app_shell_macros.html" as shell %}'
        '{{ shell.rating_control("recipeRating", "Recipe rating", mode="recipe") }}'
    ).render()
    assert 'data-rating-toggle-selected="true"' in recipe_rendered
    assert recipe_rendered.count("click again to clear") == 5
    assert "recipe-edit-rating-clear" not in recipe_rendered


def test_standalone_recipe_editor_uses_app_shell_navigation():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")
    header = read_text("PushShoppingList/templates/includes/app_header.html")
    sidebar = read_text("PushShoppingList/templates/includes/app_sidebar.html")

    assert '{% extends "layouts/app_layout.html" %}' in template
    assert '{% set app_body_class = "recipe-edit-standalone-page" %}' in template
    assert '{% set app_content_class = "recipe-edit-standalone-shell" %}' in template
    assert "app_sidebar_class" not in template
    assert "app_main_shell_class" not in template
    assert "app_shell_class" not in template
    assert "{% include \"sections/current_recipe_url_log.html\" %}" in template
    assert '{% include "includes/app_sidebar.html" %}' in layout
    assert '{% include "includes/app_header.html" %}' in layout
    assert 'data-app-sidebar-collapse' in sidebar
    assert 'data-app-header' in header
    assert 'app_search_id = "recipeEditGlobalSearch"' in template
    assert 'onsubmit="return submitGlobalAppSearch(this)"' in header
    assert "submitRecipeEditGlobalSearch" not in template
    assert "organizeRecipeEditStandaloneWorkspace()" in template


def test_standalone_recipe_editor_matches_homepage_width_without_a_max_cap():
    css = read_text("PushShoppingList/static/css/app.css")
    rule_start = css.index(
        ".recipe-edit-standalone-page .recipe-edit-standalone-shell {",
        css.index(".recipe-edit-standalone-page .recipe-edit-standalone-shell {") + 1,
    )
    rule_end = css.index("}", rule_start)
    shell_rule = css[rule_start:rule_end]

    assert "width: 100%;" in shell_rule
    assert "max-width: none;" in shell_rule
    assert "width: min(" not in shell_rule
    assert "100vw" not in shell_rule


def test_standalone_recipe_editor_has_an_independent_main_scroll_region():
    css = read_text("PushShoppingList/static/css/app.css")
    body_start = css.index(".app-shell-body {")
    body_rule = css[body_start:css.index("}", body_start)]
    main_start = css.index(".app-main-shell {")
    main_rule = css[main_start:css.index("}", main_start)]
    content_start = css.index(".app-content {")
    content_rule = css[content_start:css.index("}", content_start)]

    assert "height: 100dvh;" in body_rule
    assert "overflow: hidden;" in body_rule
    assert "display: grid;" in main_rule
    assert "grid-template-rows: var(--app-toolbar-height) minmax(0, 1fr);" in main_rule
    assert "min-height: 0;" in main_rule
    assert "overflow: hidden;" in main_rule
    assert "min-width: 0;" in content_rule
    assert "min-height: 0;" in content_rule
    assert "overflow-x: hidden;" in content_rule
    assert "overflow-y: auto;" in content_rule
    assert ".recipe-edit-page-main-shell" not in css
    assert ".recipe-edit-page-shell" not in css


def test_recipe_editor_redesign_preserves_core_fields_and_actions():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")

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
    organizer = script[
        script.index("function organizeRecipeEditStandaloneWorkspace()"):
        script.index("function syncRecipeEditDocumentRows()")
    ]
    assert 'const restaurantCard = document.querySelector(".recipe-edit-restaurant-card");' in organizer
    assert 'restaurantCard.insertAdjacentElement("afterend", sourceCard);' in organizer
    assert "appendRecipeEditWorkspaceChildren(utility, [aiCard]);" in organizer
    assert "appendRecipeEditWorkspaceChildren(utility, [sourceCard, aiCard]);" not in organizer
    assert "recipeEditIngredientGallery" in template
    assert "recipeEditHealthList" in template
    assert "recipe-edit-ai-assistant-card" in template
    assert "recipeEditAiMissingFields" in template
    assert "recipeEditAiConfidenceCard" in template
    assert "beginRecipeIngredientReorder(this)" in template
    assert "focusRecipeIngredientGrouping(this)" in template


def test_recipe_image_card_matches_dark_mockup_without_changing_image_workflows():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    cover_start = template.index('<div class="recipe-edit-cover-field" id="recipeEditCoverField">')
    cover_end = template.index('<div class="recipe-edit-rating-field', cover_start)
    cover = template[cover_start:cover_end]

    assert '{{ shell.svg_icon("image-copy") }}' in cover
    assert '{{ shell.svg_icon("trash") }}' in cover
    assert '<span>Remove</span>' in cover
    assert 'aria-expanded="false"' in cover
    assert "Upload Image" in cover
    assert "AI Regenerate" in cover
    assert "data-recipe-image-change-menu-template" in cover
    assert '<template data-recipe-image-change-menu-template>' in cover
    assert 'onclick="return toggleRecipeImageChangeActions(this)"' in cover
    assert 'onclick="return removeRecipeCoverImage(this)"' in cover
    assert 'onclick="return generateRecipeCoverImage(this)"' in cover
    assert '? "Change Image"' in script
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "background: var(--app-surface);" in css
    assert "position: absolute;" in css
    assert "bottom: calc(100% + 8px);" in css
    assert "function closeRecipeImageChangeActions(options = {})" in script
    assert 'event.key === "Escape"' in script
    assert "closeRecipeImageChangeActions();" in script
    assert "template?.content.firstElementChild?.cloneNode(true)" in script
    assert "if (actions) actions.remove();" in script
    assert 'if (upload) upload.setAttribute("aria-expanded", "false");' in script


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
    assert "height: 46px;" in css
    assert "min-width: 150px;" in css
    assert "background: #f5f6f8;" in css
    assert "background: #07913e;" in css
    assert "outline: 3px solid rgba(46, 182, 111, .4);" in css

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
    assert 'id="recipeEditSaveButton"' in template
    assert 'data-recipe-edit-save' in template


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
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    organizer_start = script.index("function organizeRecipeEditInformationCard()")
    organizer_end = script.index("function organizeRecipeEditAiAssistant()", organizer_start)
    organizer = script[organizer_start:organizer_end]

    assert 'primaryRow.className = "recipe-edit-primary-fields"' in organizer
    assert 'tagRow.className = "recipe-edit-tag-row"' in organizer
    assert 'metadataRow.className = "recipe-edit-metadata-strip"' in organizer
    assert 'descriptionRow.className = "recipe-edit-description-row"' in organizer
    assert "addRecipeEditMetadataIcon(servingsField, \"servings\")" in organizer
    assert "[servingsField, totalField, prepField, cookField, inactiveField].forEach(organizeRecipeEditMetadataField)" in organizer
    assert 'heading.className = "recipe-edit-metadata-heading"' in script
    assert 'data-recipe-metadata-icon="servings"' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("utensils")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("cooking-pot")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "data-recipe-edit-cuisine-chips" in script
    assert "renderRecipeEditCuisineChips" in script
    assert "recipe-edit-price-control" in organizer
    assert 'ratingField.classList.add("recipe-edit-header-rating")' in organizer
    assert "panelHeading.appendChild(ratingField)" in organizer
    assert 'class="recipe-edit-rating-label">Rating</span>' in template
    assert 'shell.rating_control("recipeEditRatingStars", "Recipe rating", mode="recipe")' in template
    assert 'shell.rating_control("recipeEditRestaurantRatingStars", "Restaurant rating", mode="restaurant")' in template
    assert 'data-rating-toggle-selected="true"' in macros
    assert 'class="recipe-edit-rating-clear"' not in macros
    assert "appendRecipeEditWorkspaceChildren(technicalBody, [\n        titleField," in organizer
    assert "appendRecipeEditWorkspaceChildren(grid, [primaryRow, tagRow, metadataRow, descriptionRow, technicalDetails])" in organizer
    assert "if (infoActions) infoActions.hidden = true;" in organizer
    assert "technicalDetails.open = false;" in organizer
    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in css
    assert ".recipe-edit-info-panel-organized .recipe-edit-metadata-heading {" in css
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
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    route = read_text("PushShoppingList/routes/recipe_routes.py")

    for field in (
        "restaurant_name", "restaurant_logo_url", "restaurant_rating", "restaurant_phone",
        "restaurant_website_url", "source_menu_url", "menu_item_url", "restaurant_street_address",
        "restaurant_city", "restaurant_state", "restaurant_postal_code", "restaurant_country",
        "restaurant_raw_hours_data", "restaurant_current_status", "restaurant_rewards_program",
        "restaurant_active_promotions", "restaurant_note_text", "restaurant_social_links",
        "restaurant_latitude", "restaurant_longitude",
        "restaurant_online_payment_available", "restaurant_online_ordering_available",
        "restaurant_pickup_available", "restaurant_delivery_available",
        "restaurant_reservation_available", "restaurant_allergy_information_note",
        "restaurant_ordering_links",
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
    assert 'shell.rating_control("recipeEditRestaurantRatingStars", "Restaurant rating", mode="restaurant")' in template
    assert "Click the selected star again to clear the rating." in macros
    assert 'data-rating-toggle-selected="true"' in macros
    assert 'class="recipe-edit-rating-clear"' not in macros
    assert macros.count('data-rating-value="{{ rating_value }}"') == 1
    assert "Restaurant's main website." in template
    assert "Page containing the full restaurant menu." in template
    assert "Direct source page or deep link for this recipe or menu item." in template
    assert "Advanced Restaurant Details" in template
    assert "Advanced Raw Data" in template
    assert 'data-restaurant-hours-day="{{ day }}"' in template
    assert '<option value="open_24_hours">Open 24 hours</option>' in template
    assert "Optional loyalty or rewards program details." in template
    assert "Current discounts or promotions, one per line." in template
    assert "Temporarily Closed" in template
    assert "Permanently Closed" in template
    assert template.count('<option value="">Unknown</option>') >= 2
    assert "cancelRecipeRestaurantSourceEdit" in template
    assert "async function saveRecipeRestaurantSource(form, options = {})" in script
    assert "function editRecipeRestaurantSource(button, event = null)" in script
    assert "event.stopPropagation();" in script
    assert 'form.querySelector("input:invalid")' in script
    assert 'fetch("/api/recipe/restaurant-source"' in script
    assert 'save.textContent = "Saving..."' in script
    assert "recipeRestaurantEditSnapshot" in script
    assert "function recipeRestaurantModalFocusableElements()" in script
    assert "function currentRecipeRestaurantSourceOption()" in script
    assert "function chooseRecipeRestaurantLogoUpload(button)" in script
    assert "function setSharedRatingFromButton(button, rating, options = {})" in script
    assert 'control?.dataset.ratingToggleSelected === "true"' in script
    assert "function previewSharedRating(button, rating)" in script
    assert "function clearSharedRatingPreview(button)" in script
    assert "function updateSharedRatingControl(source, rating, options = {})" in script
    assert "{ allowToggle: false }" in script
    assert "color: #fbbf24;" in css
    assert "color: #9ca3af;" in css
    assert ".recipe-edit-restaurant-rating-editor .recipe-edit-rating-star.active" in css
    assert '.recipe-edit-restaurant-rating-editor .recipe-edit-rating-star[aria-checked="true"]' in css
    assert "border-radius: 7px;" in css
    assert ':is(.recipe-edit-header-rating, .recipe-edit-restaurant-rating-editor) .recipe-edit-rating-star' in css
    assert '.recipe-edit-rating-star[aria-checked="true"]' in css
    assert "function handleSharedRatingKeydown(button, event)" in script
    assert "function updateRecipeRestaurantStructuredHours(control)" in script
    assert "function toggleRecipeRestaurantSplitHours(button)" in script
    assert 'const restaurantId = recipeEditInputValue("recipeEditRestaurantId")' in script
    assert 'const linkedSource = currentRecipeRestaurantSourceOption();' in script
    assert 'const selected = linkedSource || recipeRestaurantFallbackFromEditor();' in script
    assert 'event.key === "Escape"' in script
    assert 'event.key !== "Tab"' in script
    assert "Discard unsaved restaurant changes?" in script
    assert 'document.body.classList.add("restaurant-source-modal-open")' in script
    assert "document.body.appendChild(modal);" in script
    assert "function closeRecipeRestaurantModalBackgroundPopovers()" in script
    assert 'document.querySelectorAll("[data-profile-menu]")' in script
    assert 'document.querySelectorAll("[data-global-search-form]")' in script
    assert "function captureRecipeRestaurantModalScrollState()" in script
    assert "function restoreRecipeRestaurantModalScrollState()" in script
    assert ".map(element => ({ element, wasInert: Boolean(element.inert) }))" in script
    assert "item.element.inert = true" in script
    assert "item.element.inert = item.wasInert" in script
    assert 'trigger?.focus({ preventScroll: true })' in script
    assert '@recipe_bp.route("/api/recipe/restaurant-source", methods=["POST"])' in route
    assert ".recipe-edit-standalone-page .recipe-edit-restaurant-form {" in css
    assert ".recipe-edit-restaurant-modal-backdrop {" in css
    assert ".recipe-edit-restaurant-modal-body {" in css
    assert "--app-layer-sticky-shell: 18500;" in css
    assert "--app-layer-floating: 19000;" in css
    assert "--app-layer-modal-backdrop: 20000;" in css
    assert "--app-layer-modal-panel: 20010;" in css
    assert "z-index: var(--app-layer-modal-backdrop);" in css
    assert "width: 100vw;" in css
    assert "height: 100dvh;" in css
    assert "width: min(1440px, 100%);" in css
    assert "height: min(900px, 100%);" in css
    assert "max-width: calc(100vw - 32px);" in css
    assert "max-height: calc(100dvh - 32px);" in css
    assert "grid-template-columns: minmax(0, 48fr) minmax(0, 52fr);" in css
    assert "recipe-edit-restaurant-primary-column" in template
    assert "recipe-edit-restaurant-operational-column" in template
    assert "recipe-edit-restaurant-availability-row" in template
    assert "grid-template-columns: 92px 92px minmax(120px, 1fr) minmax(120px, 1fr) 102px;" in css
    assert "font-size: 18px;" in css
    assert "font-size: 14px;" in css
    assert "min-height: 40px;" in css
    assert "width: 36px;" in css
    assert "width: 20px;" in css
    assert "background: #1a201e;" in css
    assert "syncRecipeRestaurantHoursRow(row)" in script
    assert "Restaurant Usage" in template
    assert "data-restaurant-usage-view" in template
    assert "data-restaurant-usage-panel" in template
    assert "function loadRecipeRestaurantUsage(restaurantId, options = {})" in script
    assert "function handleRecipeRestaurantUsageAction(button)" in script
    assert 'fetch(`/api/recipe/restaurant-usage?${params.toString()}`)' in script
    assert 'per_page: "50"' in script
    assert "recipeRestaurantUsageTotal <= 20" in script
    assert "Review Unlinked Recipes" in template
    assert "Link Clear Matches" in template
    assert "function loadMoreRecipeRestaurantUsage(button)" in script
    assert "function backfillUnlinkedRecipeRestaurants(button)" in script
    assert "migration_status" in script
    assert 'loading="lazy"' in script
    assert 'decoding="async"' in script
    assert "handleRecipeRestaurantUsageThumbnailError" in script
    assert "recipe.total_time" in script
    assert "recipe.calories_per_serving" in script
    assert "recipe.category_label" in script
    assert ".recipe-edit-restaurant-usage-thumbnail {" in css
    assert "grid-template-columns: 64px minmax(0, 1fr);" in css
    assert "width: 64px;" in css
    assert "height: 64px;" in css
    assert "text-overflow: ellipsis;" in css
    usage_render = script[
        script.index("function renderRecipeRestaurantUsageList"):
        script.index("function applyRecipeRestaurantUsageResponse")
    ]
    assert "recipe.cookbook_name" not in usage_render
    assert "recipe.last_modified" not in usage_render
    assert 'metadata.length ?' in usage_render
    assert 'category ?' in usage_render
    assert '@recipe_bp.route("/api/recipe/restaurant-usage", methods=["GET"])' in route
    assert '@recipe_bp.route("/api/recipe/restaurant-usage/backfill", methods=["POST"])' in route
    assert ".recipe-edit-restaurant-usage-panel {" in css
    assert "Loading usage…" in template
    assert "Usage data unavailable." in script
    assert "Not currently used by any recipes." in script
    assert 'data-restaurant-usage-mode="retry"' in css
    assert "flex: 1 1 auto;" in css
    assert "overflow-y: auto;" in css
    assert "overflow-x: hidden;" in css

    card_start = template.index('<details class="recipe-edit-context-card recipe-edit-restaurant-card"')
    card_end = template.index("</details>", card_start)
    assert "data-restaurant-edit-field" not in template[card_start:card_end]
    assert template.index("data-restaurant-edit-modal") > card_end


def test_restaurant_selected_rating_star_has_no_persistent_gold_frame():
    css = read_text("PushShoppingList/static/css/app.css")
    selector = (
        '.recipe-edit-standalone-page .recipe-edit-restaurant-rating-editor '
        '.recipe-edit-rating-star[aria-checked="true"] {'
    )
    rule_start = css.index(selector)
    selected_rule = css[rule_start:css.index("}", rule_start)]

    assert "border-color: transparent;" in selected_rule
    assert "background: transparent;" in selected_rule
    assert "box-shadow: none;" in selected_rule
    assert "251, 191, 36" not in selected_rule

    focus_selector = (
        ".recipe-edit-standalone-page .recipe-edit-restaurant-rating-editor "
        ".recipe-edit-rating-star:focus-visible {"
    )
    focus_start = css.index(focus_selector)
    focus_rule = css[focus_start:css.index("}", focus_start)]
    assert "156, 163, 175" in focus_rule
    assert "251, 191, 36" not in focus_rule


def test_restaurant_rating_stars_start_directly_below_rating_label():
    css = read_text("PushShoppingList/static/css/app.css")
    editor_selector = ".recipe-edit-restaurant-rating-editor {"
    editor_start = css.index(editor_selector, css.index(".recipe-edit-restaurant-form-logo"))
    editor_rule = css[editor_start:css.index("}", editor_start)]
    assert "display: block;" in editor_rule

    stars_selector = (
        ".recipe-edit-standalone-page .recipe-edit-restaurant-rating-editor "
        ".recipe-edit-rating-stars {"
    )
    stars_start = css.rindex(stars_selector)
    stars_rule = css[stars_start:css.index("}", stars_start)]
    assert "justify-content: flex-start;" in stars_rule
    assert "margin-left: 0;" in stars_rule


def test_restaurant_usage_duplicate_review_is_explicit_accessible_and_transactional():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")
    service = read_text("PushShoppingList/services/restaurant_recipe_duplicate_service.py")

    assert 'data-restaurant-duplicate-review' in template
    assert 'aria-modal="true"' in template
    assert "Keep Both" in template
    assert "Ignore Match" in template
    assert "Delete Duplicate" in template
    assert "Merge" in template
    assert "data-restaurant-duplicate-primary" in script
    assert "data-restaurant-duplicate-selected" in script
    assert "Exact duplicate" in script
    assert "Open Recipe" in script
    assert "Confirm Merge" in script
    assert "Confirm Delete Duplicate" in script
    assert "closeRecipeRestaurantDuplicateReview" in script
    assert "duplicateReview && !duplicateReview.hidden" in script
    assert ".recipe-edit-restaurant-duplicate-badge" in css
    assert "background: rgba(245, 158, 11, .1);" in css
    assert ".recipe-edit-restaurant-duplicate-review" in css
    assert '@recipe_bp.route("/api/recipe/restaurant-duplicates/<group_id>", methods=["GET"])' in routes
    assert '/disposition", methods=["POST"]' in routes
    assert '/merge", methods=["POST"]' in routes
    assert '/delete", methods=["POST"]' in routes
    assert 'data.get("confirm_merge") is not True' in routes
    assert 'data.get("confirm_delete") is not True' in routes
    assert 'confirm_merge: true' in script
    assert 'confirm_delete: true' in script
    assert 'with workspace_write_lock("restaurant-recipe-duplicates"), DUPLICATE_LOCK:' in service
    assert '_restore_paths(snapshot)' in service
    assert '"action": action' in service
    assert '"user_id": _clean(active_user_id())' in service


def test_infer_missing_details_uses_filled_three_sparkle_mockup_icon():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    css = read_text("PushShoppingList/static/css/app.css")
    button_start = template.index('class="recipe-edit-ai-infer"')
    button_end = template.index("</button>", button_start)
    button = template[button_start:button_end]

    assert '{{ shell.svg_icon("infer-sparkles") }}' in button
    assert "recipe-edit-infer-sparkles" in button
    assert '>?</span>' not in button
    assert "Infer Missing Details" in button
    assert ".recipe-edit-ai-infer .recipe-edit-button-icon .app-icon-svg" in css
    infer_icon_start = macros.index('{% elif name == "infer-sparkles" %}')
    infer_icon_end = macros.index("{% else %}", infer_icon_start)
    infer_icon = macros[infer_icon_start:infer_icon_end]
    assert infer_icon.count('class="app-infer-sparkle-fill"') == 3
    assert ".app-infer-sparkle-fill" in css


def test_restaurant_usage_review_toggle_is_accessible_server_filtered_and_paginated():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")
    service = read_text("PushShoppingList/services/recipe_edit_service.py")

    toolbar_start = template.index('<footer class="recipe-edit-restaurant-usage-panel-actions">')
    toolbar_end = template.index("</footer>", toolbar_start)
    toolbar = template[toolbar_start:toolbar_end]
    assert 'role="switch"' in toolbar
    assert 'data-restaurant-usage-review-only' in toolbar
    assert 'aria-label="Show review items only"' in toolbar
    assert toolbar.index("Review Items Only") < toolbar.index("Load More")
    assert "function toggleRecipeRestaurantUsageReviewOnly(input)" in script
    assert 'params.set("review_only", "1")' in script
    assert "query: recipeRestaurantUsageQuery" in script
    assert "page: 1" in script
    assert "No recipes need review" in script
    assert "No review items match your search" in script
    assert "review_reason_labels" in script
    assert ".recipe-edit-restaurant-review-toggle" in css
    assert "input:checked + .recipe-edit-restaurant-review-toggle-track" in css
    assert 'request.args.get("review_only"' in routes
    assert "review_recipe_count" in service
    assert '"review_reason_codes"' in service


def test_source_documents_card_uses_compact_rows_and_edit_modal():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    card_start = template.index('<details class="recipe-edit-context-card recipe-edit-source-documents-card"')
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
    assert '<summary class="recipe-edit-source-documents-header">' in card
    assert 'ontoggle="if (!this.open) closeRecipeSourceDocumentsHelp()"' in card
    assert "open>" in card
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

    modal_start = template.index('<div class="recipe-edit-source-documents-modal-backdrop"')
    modal_end = template.index('<details class="recipe-edit-context-card recipe-edit-restaurant-card"', modal_start)
    modal = template[modal_start:modal_end]
    record_loop_start = modal.index('{% for record in')
    record_loop_end = modal.index('{% endfor %}', record_loop_start)
    record_loop = modal[record_loop_start:record_loop_end]
    assert 'data-source-document-modal-actions' in record_loop
    assert record_loop.index('data-source-document-modal-open') < record_loop.index('data-source-document-modal-download')
    assert record_loop.index('data-source-document-modal-download') < record_loop.index('Regenerate PDF')
    assert 'class="action-management" onclick="return createRecipeEditorPdf(this)"' in record_loop
    assert 'class="action-management" onclick="return uploadRecipeSourcePdfToCloudflare(this)"' in modal
    assert 'class="secondary" onclick="return closeRecipeSourceDocumentsModal' in modal
    assert modal.index('data-source-documents-edit-save') < modal.index('>Cancel</button>')
    assert 'actions.hidden = !Array.from(actions.querySelectorAll("a, button")).some(action => !action.hidden);' in script
    assert 'grid-template-columns: 72px 96px 130px;' in css
    assert 'min-height: 38px;' in css
    assert 'white-space: nowrap;' in css
    assert '.recipe-edit-source-documents-modal-footer .secondary {' in css
    assert '.recipe-edit-source-documents-modal-footer .primary {' in css
    assert 'grid-row: 2;' in css

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
    assert "min-width: 920px;" in v4_css

    tools_start = script.index("function organizeRecipeEditIngredientTools()")
    tools_end = script.index("function organizeRecipeEditEquipmentTools()", tools_start)
    tools_block = script[tools_start:tools_end]
    assert 'tableScroll.className = "recipe-edit-ingredient-table-scroll";' in tools_block
    assert "tableScroll.appendChild(tableHead);" in tools_block
    assert "tableScroll.appendChild(ingredientList);" in tools_block


def test_recipe_editor_ingredient_options_use_compact_anchored_menu():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'substitutions.classList.add("recipe-edit-ingredient-options-panel")' in organize
    assert "rowMenu.insertBefore(substitutions, rowMenu.firstChild);" in organize
    assert 'optionsButton.classList.add("recipe-edit-ingredient-options-button")' in organize
    assert "More ingredient actions" in organize
    assert "organizeRecipeEditSubstitutionOptionRow" in script
    assert 'label.textContent = optionRows.length ? optionLabel : "No substitutions";' in script

    v4_css = css[css.index("/* Recipe workspace v4: homepage alignment and compact tab editors. */"):]
    assert "grid-template-columns: 18px 40px minmax(210px, 1fr) 68px 104px 148px 88px 96px 30px 30px !important;" in v4_css
    assert ".recipe-edit-ingredient-options-button" in v4_css
    assert ".recipe-edit-ingredient-options-panel" in v4_css
    assert "width: min(520px, calc(100vw - 24px));" in v4_css


def test_recipe_editor_ingredient_table_uses_mockup_icons_and_compact_controls():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert '{{ shell.svg_icon("plus") }}' in template
    assert '{{ shell.svg_icon("sort") }}' in template
    assert '{{ shell.svg_icon("folder") }}' in template
    assert '{{ shell.svg_icon("chevron-down") }}' in template
    for icon_name in ("drag", "leaf", "dairy", "can", "jar", "oil", "edit", "trash", "chevron-down"):
        assert f"{icon_name}:" in script or f'"{icon_name}":' in script
    assert "function recipeIngredientStoreSectionIconName" in script
    assert "function recipeStoreSectionDisplayLabel" in script
    assert '"CANNED": "Canned Goods"' in script
    assert "function syncRecipeIngredientStoreSectionControl" in script
    assert "function recipeIngredientTypeOptions" in script
    assert '<select data-field="section">${recipeIngredientTypeOptions' in script
    assert 'class="recipe-edit-store-section-icon' in script
    assert ".recipe-edit-store-section-icon.is-leaf" in css
    assert ".recipe-edit-store-section-icon.is-dairy" in css
    assert ".recipe-edit-store-section-icon.is-can" in css
    assert ".recipe-edit-store-section-icon.is-jar" in css
    assert ".recipe-edit-store-section-icon.is-oil" in css
    assert 'value.includes("OIL") || value.includes("VINEGAR")' in script
    assert "Edit ${accessibleName}" in script
    assert "Delete ${accessibleName}" in script


def test_recipe_editor_substitution_popover_uses_mockup_summary_hierarchy():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "Substitutions for ${ingredientName}" in script
    assert 'class="recipe-edit-substitution-thumbnail"' in script
    assert 'class="recipe-edit-substitution-ratio"' in script
    assert 'class="recipe-edit-substitution-quality' in script
    assert "Best match" in script
    assert "Acceptable" in script
    assert 'data-ingredient-substitution-view-all' in script
    assert "optionRows.length === 0" in script
    assert ".recipe-edit-substitution-option-row:nth-child(n + 4)" in css
    assert ".recipe-edit-substitution-view-all" in css


def test_recipe_editor_compact_rows_keep_headers_actions_and_tool_organization():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    for class_name, labels in (
        ("recipe-edit-equipment-header", ("Image", "Equipment", "Options", "Edit", "Delete")),
        ("recipe-edit-instructions-header", ("Step", "Image", "Instruction", "Options", "Actions")),
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


def test_recipe_editor_instructions_use_compact_step_grid_and_preserve_handlers():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    instructions_css = css[css.index("/* Instruction editor v1:"):]

    assert 'class="recipe-edit-section-header instructions-toolbar"' in template
    assert "recipe-edit-instructions-actions instructions-toolbar-actions" in template
    assert 'id="recipeEditInstructionCount"' in template
    assert 'class="recipe-edit-add-instruction-button"' in template
    assert "data-recipe-instruction-reorder-toggle" in template
    assert 'aria-pressed="false"' in template

    for column in (
        "28px", "52px", "72px", "minmax(320px, 1fr)", "96px", "116px",
    ):
        assert column in instructions_css
    assert "grid-template-columns: var(--recipe-edit-instruction-grid) !important;" in instructions_css
    assert "min-height: 84px;" in instructions_css
    assert "position: sticky;" in instructions_css
    assert "min-height: 48px;" in instructions_css
    assert "max-height: 72px;" in instructions_css
    assert "width: 60px;" in instructions_css
    assert "min-width: 88px;" in instructions_css
    assert "width: 36px;" in instructions_css
    assert "recipe-edit-instruction-expanded" in instructions_css
    assert "recipe-edit-instruction-reorder-mode" in instructions_css
    assert "recipe-edit-row-dragging" in instructions_css
    assert "@media (max-width: 760px)" in instructions_css
    assert "grid-template-columns: 28px 52px 64px minmax(0, 1fr) !important;" in instructions_css

    row_start = script.index("function addRecipeInstructionRow")
    row_end = script.index("function addRecipeNutritionRow", row_start)
    row_code = script[row_start:row_end]
    for preserved_field in (
        'data-field="text"',
        'data-field="step_number"',
        'data-field="step_image_url"',
        'data-field="step_image_generated_at"',
    ):
        assert preserved_field in row_code
    assert "organizeRecipeEditInstructionRow(row);" in row_code
    assert "bindRecipeEditDragAndDrop(row);" in row_code
    assert "function resizeRecipeEditInstructionTextarea" in row_code
    assert "function toggleRecipeEditInstructionDetails" in row_code
    assert 'optionsButton.innerHTML = `<span>Options</span>${recipeEditSvgIcon("chevron-down")}`;' in row_code
    assert 'detailsButton.setAttribute("aria-expanded", "false");' in row_code
    assert 'detailsButton.setAttribute("onclick", "return toggleRecipeEditInstructionDetails(this)");' in row_code
    assert 'count.textContent = `${rows.length} ${rows.length === 1 ? "step" : "steps"}`;' in row_code

    reorder_start = script.index("function beginRecipeInstructionReorder")
    reorder_end = script.index("function recipeEditMetadataFields", reorder_start)
    reorder_code = script[reorder_start:reorder_end]
    assert 'list.classList.toggle("recipe-edit-instruction-reorder-mode", active);' in reorder_code
    assert 'label.textContent = active ? "Done Reordering" : "Reorder";' in reorder_code
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false");' in reorder_code

    image_tools_start = script.index("function setRecipeEditRowImageToolsVisible(row, visible)")
    image_tools_end = script.index("function setRecipeEditRowImageVisible", image_tools_start)
    image_tools = script[image_tools_start:image_tools_end]
    assert "[data-step-image-panel]" in image_tools
    assert "updateRecipeEditInstructionDetailsState(row);" in image_tools


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


def test_recipe_health_dashboard_is_compact_and_separate_from_ai_confidence():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    health_start = template.index('class="recipe-edit-context-card recipe-edit-health-card"')
    confidence_start = template.index('id="recipeEditAiConfidenceCard"')
    assert health_start < confidence_start
    assert 'id="recipeEditHealthRing"' in template
    assert 'role="progressbar"' in template
    assert 'id="recipeEditHealthLabel"' in template
    assert '<span>Complete</span>' not in template
    assert 'id="recipeEditAiConfidenceTrack"' in template
    assert "Confidence is calculated from source quality, extraction reliability, AI certainty, and user verification." in template
    assert 'aria-controls="recipeEditAiAnalysisPanel"' in template
    assert 'role="dialog"' in template
    assert 'const visibleChecks = checks.filter(([label]) => label !== "Description");' in script
    assert 'percent >= 90 ? "Excellent"' in script
    assert 'percent >= 75 ? "Good"' in script
    assert 'percent >= 50 ? "Fair"' in script
    assert 'return { label: "AI Inferred", className: "inferred", icon: "warning" };' in script
    assert 'return { label: "Missing", className: "missing", icon: "x" };' in script
    assert '.recipe-edit-health-dashboard {' in css
    assert '.recipe-edit-health-ring-progress {' in css
    assert '@media (prefers-reduced-motion: reduce)' in css


def test_ai_analysis_uses_saved_confidence_evidence_without_health_completeness():
    script = read_text("PushShoppingList/static/js/app.js")
    model_start = script.index("function recipeEditAiConfidenceModel(source = {})")
    model_end = script.index("function updateRecipeEditAiConfidenceCard", model_start)
    model = script[model_start:model_end]

    for label in (
        "Source Quality",
        "Confidence by section",
        "AI generated fields",
        "User verified fields",
        "Estimated fields",
        "Nutrition confidence",
        "Ingredient normalization confidence",
        "Duplicate detection confidence",
        "Warnings",
        "Recommended actions",
    ):
        assert label in model
    assert "recipeEditHealthChecks" not in model
    assert "recipeEditNumericConfidence(source)" in model
    assert "source_quality_score" in model
    assert "extraction_confidence_score" in model
    assert "user_verification_confidence" in model
    assert "function closeRecipeEditAiAnalysis(options = {})" in script
    assert 'event.key === "Escape"' in script


def test_recipe_editor_redesign_css_uses_app_tokens_and_mobile_breakpoints():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "Recipe workspace v3: editor content uses its dark tokens without restyling AppLayout chrome" in css
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


def test_recipe_editor_ingredients_workspace_spans_both_desktop_editing_columns():
    css = read_text("PushShoppingList/static/css/app.css")

    wide_workspace_start = css.index("/* Wide recipe workspace:")
    wide_workspace_end = css.index("\n}\n", wide_workspace_start) + 3
    wide_workspace = css[wide_workspace_start:wide_workspace_end]

    assert "@media (min-width: 1500px)" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-main-workspace {\n        display: contents;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-info-panel {\n        grid-column: 1;\n        grid-row: 1;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-utility-column {\n        grid-column: 2;\n        grid-row: 1;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-tabs-card {\n        grid-column: 1 / 3;\n        grid-row: 2;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-context-sidebar {\n        grid-column: 3;\n        grid-row: 1 / 3;" in wide_workspace


def test_recipe_editor_wide_ingredients_workspace_grows_without_sticky_headers():
    css = read_text("PushShoppingList/static/css/app.css")

    wide_workspace_start = css.index("/* Wide recipe workspace:")
    wide_workspace = css[wide_workspace_start:]

    assert ".recipe-edit-standalone-page .recipe-edit-backdrop.open {\n        display: flex;\n        min-height: 100%;" in wide_workspace
    assert "grid-template-rows: auto minmax(360px, 1fr);" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-tab-list {\n        position: static;" in wide_workspace
    assert ".recipe-edit-ingredients-section > .recipe-edit-section-header {\n        position: static;" in wide_workspace
    assert ".recipe-edit-ingredients-section:not([hidden]) {\n        display: flex;" in wide_workspace
    assert ".recipe-edit-ingredients-section .recipe-edit-ingredient-table-scroll {" in wide_workspace
    assert "flex: 1 1 auto;\n        overflow: auto;" in wide_workspace
    ingredient_polish = wide_workspace[wide_workspace.index("/* Ingredient editor v7:"):]
    assert ".recipe-edit-standalone-page .recipe-edit-tab-list," in ingredient_polish
    assert ".recipe-edit-standalone-page .recipe-edit-ingredient-table-head {\n    position: static;" in ingredient_polish
    assert "top: auto;" in ingredient_polish
    assert "z-index: auto;" in ingredient_polish


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


def test_recipe_description_ai_action_is_reviewed_before_it_changes_the_form():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    advanced_start = template.index('<details class="recipe-edit-ai-advanced">')
    advanced_end = template.index("</details>", advanced_start)
    advanced_markup = template[advanced_start:advanced_end]
    assert "More AI Actions" in advanced_markup
    assert "data-recipe-description-ai-action" in advanced_markup
    assert "data-recipe-description-ai-label" in advanced_markup
    assert "Regenerate Description" in advanced_markup
    assert "Review Description" in template
    assert "Current description" in template
    assert "Proposed description" in template
    assert "Replace Description" in template

    generate_start = script.index("async function regenerateRecipeDescription(button)")
    generate_end = script.index("function replaceRecipeDescriptionProposal", generate_start)
    generate_function = script[generate_start:generate_end]
    assert 'fetch("/api/recipe/regenerate_description"' in generate_function
    assert "collectRecipeEditorPayload()" in generate_function
    assert "openRecipeDescriptionReview" in generate_function
    assert ".value =" not in generate_function
    assert "recipeEditDescriptionRequestPending" in generate_function

    replace_start = script.index("function replaceRecipeDescriptionProposal")
    replace_end = script.index("async function regenerateRecipeIngredientsSection", replace_start)
    replace_function = script[replace_start:replace_end]
    assert "description.value = recipeEditDescriptionProposal" in replace_function
    assert 'new Event("input", { bubbles: true })' in replace_function
    assert "Save Recipe to keep this change" in replace_function
    assert 'hasDescription ? "Regenerate Description" : "Generate Description"' in script

    assert '@recipe_bp.route("/api/recipe/regenerate_description", methods=["POST"])' in routes
    assert "regenerate_recipe_description_for_recipe" in routes
    assert ".recipe-edit-description-comparison" in css
    assert ".recipe-edit-description-review-dialog" in css
