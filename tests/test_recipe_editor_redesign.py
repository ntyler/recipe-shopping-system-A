import re
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
    editor_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
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
    assert editor_template.count("shell.rating_control(") == 2
    assert 'class="recipe-edit-rating-star"' not in editor_template
    assert macros.count('data-rating-value="{{ rating_value }}"') == 1


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
    assert "recipeEditUtilityColumn" not in template
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
    sidebar_order = organizer[organizer.index("appendRecipeEditWorkspaceChildren(sidebar"):]
    card_names = ["imageCard", "restaurantCard", "aiCard", "sourceCard", "galleryCard", "healthCard", "confidenceCard"]
    assert [sidebar_order.index(card_name) for card_name in card_names] == sorted(
        sidebar_order.index(card_name) for card_name in card_names
    )
    assert "recipeEditIngredientGallery" in template
    assert "recipeEditHealthList" in template
    assert "recipe-edit-ai-assistant-card" in template
    assert "recipeEditAiMissingFields" in template
    assert "recipeEditAiConfidenceCard" in template
    assert "beginRecipeIngredientReorder(this)" not in template
    assert "focusRecipeIngredientGrouping(this)" not in template
    assert 'class="recipe-edit-ingredient-utility-action"' not in template


def test_recipe_image_card_matches_dark_mockup_without_changing_image_workflows():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    cover_start = template.index('<div class="recipe-edit-cover-field" id="recipeEditCoverField"')
    cover_end = template.index('<div class="recipe-edit-rating-field', cover_start)
    cover = template[cover_start:cover_end]

    assert '{{ shell.svg_icon("image-copy") }}' in cover
    assert '{{ shell.svg_icon("trash") }}' in cover
    assert '{{ shell.svg_icon("heart") }}' in cover
    assert 'id="recipeEditFavoriteButton"' in cover
    assert 'class="app-recipe-favorite recipe-edit-cover-favorite"' in cover
    assert "data-recipe-favorite" in cover
    assert 'onclick="return toggleRecipeFavorite(this, event)"' in cover
    assert '<span>Remove</span>' in cover
    assert 'aria-expanded="false"' in cover
    assert cover.count('aria-haspopup="menu"') == 1
    assert template.count('aria-haspopup="menu"') >= 2
    assert 'aria-controls="recipeEditImageChangeMenu"' in cover
    assert 'aria-controls="recipeEditImageChangeMenuMobile"' in template
    assert 'aria-labelledby="recipeEditCoverReplaceButton"' in cover
    assert 'aria-labelledby="recipeEditCoverReplaceButtonMobile"' in template
    assert cover.count('class="recipe-edit-image-change-chevron"') == 1
    assert template.count('class="recipe-edit-image-change-chevron"') == 2
    assert "Upload Image" in cover
    assert "Regenerate with AI" in cover
    assert "Generate with AI" in script
    assert "recipe-edit-cover-generate-direct" not in cover
    assert "data-recipe-image-change-menu-template" in cover
    assert '<template data-recipe-image-change-menu-template>' in cover
    assert 'onclick="return toggleRecipeImageChangeActions(this)"' in cover
    assert 'onclick="return removeRecipeCoverImage(this)"' in cover
    assert 'onclick="return generateRecipeCoverImage(this)"' in cover
    assert '? "Replace Image"' in script
    assert "function syncRecipeEditorFavoriteControl" in script
    assert "syncRecipeEditorFavoriteControl(recipe, originalUrl);" in script
    assert 'Object.prototype.hasOwnProperty.call(recipe, "favorite")' in script
    assert "previousUrl === recipeUrl" in script
    assert "setRecipeFavoriteButtonState(button, favorite);" in script
    assert "function rememberRecipeFavoriteState" in script
    assert "favorite: nextFavorite," in script
    assert "applyRecipeFavoriteSyncPayload({" in script
    assert "publishRecipeFavoriteState([recipeUrl, savedRecipeUrl], savedFavorite);" in script
    assert "recipe.favorite = isFavorite;" in script
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert "background: var(--app-surface);" in css
    assert ".recipe-edit-image-card .recipe-edit-cover-favorite" in css
    assert '.recipe-edit-cover-favorite[aria-pressed="true"]' in css
    favorite_rule = css[
        css.index(".recipe-edit-standalone-page .recipe-edit-image-card .recipe-edit-cover-favorite {"):
        css.index("}", css.index(".recipe-edit-standalone-page .recipe-edit-image-card .recipe-edit-cover-favorite {"))
    ]
    for declaration in (
        "top: 8px;",
        "right: 8px;",
        "width: 30px;",
        "height: 30px;",
        "border-radius: 50%;",
        "background: rgba(22, 27, 29, .88);",
    ):
        assert declaration in favorite_rule
    assert "width: 17px;" in css
    assert "position: absolute;" in css
    assert "bottom: calc(100% + 8px);" in css
    assert "function closeRecipeImageChangeActions(options = {})" in script
    assert "function handleRecipeImageChangeMenuKeydown(event)" in script
    assert 'event.key === "Escape"' in script
    assert '["ArrowDown", "ArrowUp", "Home", "End"]' in script
    assert "closeRecipeImageChangeActions();" in script
    assert "template?.content.firstElementChild?.cloneNode(true)" in script
    assert 'actions.classList.add("recipe-edit-row-menu");' in script
    assert "positionRecipeEditPopupMenu(actions, button);" in script
    assert '".recipe-edit-unit-menu, .recipe-edit-type-menu, .recipe-edit-image-change-actions"' in script
    assert "restoreRecipeEditPopupMenu(actions);" in script
    assert "actions.remove();" in script
    assert 'button.setAttribute("aria-expanded", "false");' in script
    assert 'document.addEventListener("focusin"' in script
    assert '+ "[data-recipe-image-change-toggle], "' in script
    upload_workflow = script[
        script.index("function openRecipeCoverUpload()"):
        script.index("async function uploadRecipeCoverImage(input)")
    ]
    generate_workflow = script[
        script.index("async function generateRecipeCoverImage(button)"):
        script.index("async function removeRecipeCoverImage(button)")
    ]
    assert upload_workflow.index("closeRecipeImageChangeActions();") < upload_workflow.index("input.click();")
    assert generate_workflow.index("closeRecipeImageChangeActions();") < generate_workflow.index(
        "requestRecipeCoverImageGeneration("
    )
    floating_menu_rule_start = css.index(
        "body.recipe-edit-standalone-page > .recipe-edit-image-change-actions.recipe-edit-floating-menu {"
    )
    floating_menu_rule = css[floating_menu_rule_start:css.index("}", floating_menu_rule_start)]
    for declaration in (
        "position: fixed;",
        "z-index: var(--app-layer-floating);",
        "width: min(220px, calc(100vw - 16px));",
        "grid-template-columns: minmax(0, 1fr);",
        "box-shadow: 0 12px 28px rgba(0, 0, 0, .4);",
    ):
        assert declaration in floating_menu_rule
    assert "position: static;" not in floating_menu_rule


def test_recipe_image_actions_render_as_standalone_controls_without_group_border():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe image actions: standalone controls without a decorative group container. */"
    image_actions = css[css.index(marker):]

    assert ".recipe-edit-image-card .recipe-edit-cover-primary-actions" in image_actions
    assert ".recipe-edit-mobile-image-actions" in image_actions

    toolbar_rule = image_actions[:image_actions.index("}")]
    for declaration in (
        "display: flex;",
        "flex-wrap: wrap;",
        "gap: 8px;",
        "width: 100%;",
        "padding: 0;",
        "border: 0;",
        "border-radius: 0;",
        "background: transparent;",
        "box-shadow: none;",
    ):
        assert declaration in toolbar_rule
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" not in toolbar_rule

    button_rule_start = image_actions.index(
        ".recipe-edit-cover-primary-actions > .recipe-edit-cover-upload-button,"
    )
    button_rule = image_actions[button_rule_start:image_actions.index("}", button_rule_start)]
    for declaration in (
        "display: inline-flex;",
        "flex: 1 1 120px;",
        "width: 100%;",
        "height: 40px;",
        "align-items: center;",
        "justify-content: center;",
        "gap: 6px;",
        "border: 1px solid transparent;",
        "background: transparent;",
        "white-space: nowrap;",
    ):
        assert declaration in button_rule

    assert "> button:is(:hover, :focus-visible)" in image_actions
    assert "> .recipe-edit-cover-remove-button:is(:hover, :focus-visible)" in image_actions
    assert "background: color-mix(in srgb, var(--app-danger, #ef4444) 11%, transparent);" in image_actions
    assert "flex-basis: 100%;" in image_actions


def test_recipe_image_prompt_uses_accessible_modal_and_existing_form_state():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    modal = template[template.index('<div class="recipe-edit-image-prompt-backdrop"'):]
    modal_script = script[
        script.index("function recipeImagePromptModal()"):
        script.index("function setRecipeEditorCoverImageViewLoaded", script.index("function recipeImagePromptModal()"))
    ]

    assert template.count('onclick="return openRecipeImagePromptModal(this)"') == 2
    assert 'id="recipeEditImagePromptModal"' in modal
    assert 'role="dialog"' in modal
    assert 'aria-modal="true"' in modal
    assert 'aria-labelledby="recipeEditImagePromptTitle"' in modal
    assert 'aria-describedby="recipeEditImagePromptHelp"' in modal
    assert "AI Image Prompt" in modal
    assert "Save Prompt" in modal
    assert "Cancel" in modal
    assert "data-recipe-edit-image-prompt-draft" in modal
    assert "closeRecipeImagePromptModalFromBackdrop(event)" in modal
    modal_header = modal.index("<header>")
    modal_body = modal.index('<div class="recipe-edit-image-prompt-body">', modal_header)
    modal_footer = modal.index("<footer>", modal_body)
    assert modal_header < modal_body < modal_footer

    open_modal_script = modal_script[
        modal_script.index("function openRecipeImagePromptModal"):
        modal_script.index(
            "function closeRecipeImagePromptModal",
            modal_script.index("function openRecipeImagePromptModal"),
        )
    ]
    draft_assignment = next(
        line for line in open_modal_script.splitlines() if "draft.value =" in line
    )
    assert ".trim()" not in draft_assignment
    assert "promptText.textContent = prompt;" in modal_script
    assert 'updateRecipeEditorDirtyState(document.getElementById("recipeEditForm"))' in modal_script
    assert 'event.key === "Escape"' in modal_script
    assert 'event.key !== "Tab"' in modal_script
    assert "modal.contains(document.activeElement)" in modal_script
    assert "recipeEditImagePromptTrigger.focus({ preventScroll: true })" not in modal_script
    assert "trigger.focus({ preventScroll: true })" in modal_script
    assert 'document.body.classList.add("recipe-image-prompt-modal-open")' in modal_script
    assert 'document.body.classList.remove("recipe-image-prompt-modal-open")' in modal_script
    assert 'closeRecipeImagePromptModal({ restoreFocus: false });' in script
    assert "normalized.prompt ? normalized : {};" in script

    assert ".recipe-edit-image-prompt-backdrop {" in css
    assert ".recipe-edit-image-prompt-dialog {" in css
    assert ".recipe-edit-image-prompt-backdrop[hidden]" in css
    image_prompt_scroll_lock_css = css[
        css.index("body.recipe-image-prompt-modal-open,"):
        css.index(".recipe-edit-image-prompt-backdrop {", css.index("body.recipe-image-prompt-modal-open,"))
    ]
    assert "body.recipe-image-prompt-modal-open [data-app-content]" in image_prompt_scroll_lock_css
    assert "overflow: hidden !important;" in image_prompt_scroll_lock_css
    image_prompt_dialog_css = css[
        css.index(".recipe-edit-image-prompt-dialog {"):
        css.index(".recipe-edit-image-prompt-dialog > header", css.index(".recipe-edit-image-prompt-dialog {"))
    ]
    image_prompt_chrome_css = css[
        css.index(".recipe-edit-image-prompt-dialog > header,"):
        css.index(".recipe-edit-image-prompt-dialog > header {", css.index(".recipe-edit-image-prompt-dialog > header,"))
    ]
    image_prompt_body_css = css[
        css.index(".recipe-edit-image-prompt-body {"):
        css.index(".recipe-edit-image-prompt-body label", css.index(".recipe-edit-image-prompt-body {"))
    ]
    image_prompt_textarea_css = css[
        css.index(".recipe-edit-image-prompt-body textarea {"):
        css.index(".recipe-edit-image-prompt-body textarea:focus-visible")
    ]
    image_prompt_mobile_start = css.index(
        "@media (max-width: 640px) {",
        css.index(
            ".recipe-edit-image-prompt-dialog > footer .recipe-edit-image-prompt-save",
        ),
    )
    image_prompt_narrow_mobile_start = css.index(
        "@media (max-width: 340px) {",
        image_prompt_mobile_start,
    )
    image_prompt_mobile_css = css[
        image_prompt_mobile_start:image_prompt_narrow_mobile_start
    ]

    assert "display: flex;" in image_prompt_dialog_css
    assert "width: min(92vw, 960px);" in image_prompt_dialog_css
    assert any(
        declaration in image_prompt_dialog_css
        for declaration in ("max-height: 85vh;", "max-height: 85dvh;")
    )
    assert "overflow: hidden;" in image_prompt_dialog_css
    assert "flex-direction: column;" in image_prompt_dialog_css
    assert "flex: 0 0 auto;" in image_prompt_chrome_css
    assert "min-height: 0;" in image_prompt_body_css
    assert "overflow-y: auto;" in image_prompt_body_css
    assert "overflow-x: hidden;" in image_prompt_body_css
    assert any(
        declaration in image_prompt_textarea_css
        for declaration in (
            "height: clamp(360px, 55vh,",
            "height: clamp(360px, 55dvh,",
        )
    )
    assert "min-height: 360px;" in image_prompt_textarea_css
    assert "max-height:" in image_prompt_textarea_css
    assert "resize: vertical;" in image_prompt_textarea_css

    assert ".recipe-edit-image-prompt-backdrop" in image_prompt_mobile_css
    assert "env(safe-area-inset-top, 0px)" in image_prompt_mobile_css
    assert "env(safe-area-inset-right, 0px)" in image_prompt_mobile_css
    assert "env(safe-area-inset-bottom, 0px)" in image_prompt_mobile_css
    assert "env(safe-area-inset-left, 0px)" in image_prompt_mobile_css
    assert "box-sizing: border-box;" in css[
        css.index(".recipe-edit-image-prompt-backdrop {"):
        css.index(".recipe-edit-image-prompt-backdrop[hidden]")
    ]
    assert "width: 100%;" in image_prompt_mobile_css
    assert "max-width: 100%;" in image_prompt_mobile_css
    assert "height: 100%;" in image_prompt_mobile_css
    assert "max-height: 100%;" in image_prompt_mobile_css
    assert "flex-wrap: nowrap;" in image_prompt_mobile_css
    image_prompt_narrow_mobile_css = css[image_prompt_narrow_mobile_start:]
    assert "flex-direction: column;" in image_prompt_narrow_mobile_css
    assert "width: 100%;" in image_prompt_narrow_mobile_css


def test_recipe_image_generation_menu_is_single_flight_and_state_aware():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    organizer = script[
        script.index("function organizeRecipeEditImageCard()"):
        script.index("function organizeRecipeEditInformationCard()")
    ]
    generator = script[
        script.index("async function generateRecipeCoverImage(button)"):
        script.index("async function removeRecipeCoverImage(button)")
    ]

    assert "recipe-edit-cover-generate-direct" not in organizer
    assert "appendRecipeEditWorkspaceChildren(actions, [upload, remove])" in organizer
    assert template.count("Regenerate with AI") == 2
    assert "Generate with AI" in script
    assert 'button?.closest(".recipe-edit-cover-details, .recipe-edit-image-mobile-card")' in script
    assert 'document.querySelectorAll("[data-recipe-image-change-toggle]")' in script
    assert "if (recipeCoverImageGenerationPending) return false;" in generator
    assert "syncRecipeCoverGenerationControls(true, hasCoverImage);" in generator
    assert "syncRecipeCoverGenerationControls(false, Boolean(currentCoverImage.path || currentCoverImage.url));" in generator
    assert 'generateRecipeCoverImage(null);' in script


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


def test_restaurant_source_actions_are_borderless_until_hover_or_focus():
    css = read_text("PushShoppingList/static/css/app.css")
    base_rule = """body.recipe-edit-standalone-page .recipe-edit-restaurant-actions a {
    min-width: 0;
    min-height: 32px;
    padding: 0 6px;
    border-color: transparent;
    background: transparent;"""
    interaction_rule = """body.recipe-edit-standalone-page .recipe-edit-restaurant-actions a:is(:hover, :focus-visible) {
    border-color: color-mix(in srgb, var(--app-primary-hover) 58%, transparent);
    background: color-mix(in srgb, var(--app-primary-soft) 58%, transparent);
    color: var(--app-primary-hover);"""
    focus_rule = """body.recipe-edit-standalone-page .recipe-edit-restaurant-actions a:focus-visible {
    outline: 2px solid color-mix(in srgb, var(--app-primary-hover) 72%, transparent);
    outline-offset: 2px;"""

    assert base_rule in css
    assert interaction_rule in css
    assert focus_rule in css


def test_recipe_information_card_matches_compact_mockup_structure():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    organizer_start = script.index("function organizeRecipeEditInformationCard()")
    organizer_end = script.index("function organizeRecipeEditAiAssistant()", organizer_start)
    organizer = script[organizer_start:organizer_end]
    hierarchy_css = css[css.index("/* Edit Recipe hierarchy, borderless cooking summary, and AI Image Prompt dialog. */"):]

    assert 'primaryRow.className = "recipe-edit-primary-fields"' in organizer
    assert 'tagRow.className = "recipe-edit-tag-row"' in organizer
    assert 'metadataRow.className = "recipe-edit-metadata-strip"' in organizer
    assert 'descriptionRow.className = "recipe-edit-description-row"' in organizer
    assert "addRecipeEditMetadataIcon(servingsField, \"servings\")" in organizer
    assert "[servingsField, totalField, prepField, cookField, inactiveField, levelField, scaleField]" in organizer
    assert 'setRecipeEditFieldLabel(levelField, "Difficulty")' in organizer
    assert 'setRecipeEditFieldLabel(scaleField, "Scale")' in organizer
    assert 'setRecipeEditFieldLabel(priceField, "Menu Price (optional)")' in organizer
    assert 'setRecipeEditFieldLabel(cuisineField, "Cuisine tags")' in organizer
    assert 'heading.className = "recipe-edit-metadata-heading"' in script
    assert 'data-recipe-metadata-icon="servings"' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("utensils")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("cooking-pot")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "data-recipe-edit-cuisine-chips" in script
    assert "renderRecipeEditCuisineChips" in script
    assert "recipe-edit-price-control" in organizer
    assert template.count('class="recipe-edit-price-control"') == 1
    assert 'id="recipeEditMenuPriceCurrency"' in template
    assert 'aria-label="Menu price currency"' in template
    assert '<option value="USD" selected>USD</option>' in template
    assert 'id="recipeEditMenuPrice"' in template
    assert 'aria-label="Menu price amount"' in template
    assert 'ratingField.classList.add("recipe-edit-header-rating")' in organizer
    assert 'ratingField.classList.remove("recipe-edit-wide")' in organizer
    assert 'bindRecipeEditNameInput(nameInput)' in organizer
    assert 'appendRecipeEditWorkspaceChildren(nameLine, [nameField])' in organizer
    assert "recipe-edit-summary-name-edit" not in organizer
    assert 'recipeEditSvgIcon("edit")' not in organizer
    assert 'const mobileImageSlot = document.querySelector("[data-recipe-edit-mobile-image-slot]")' in organizer
    assert "appendRecipeEditWorkspaceChildren(identity, [nameLine, ratingField])" in organizer
    identity_rule_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-summary-identity {"
    )
    identity_rule = hierarchy_css[
        identity_rule_start:hierarchy_css.index("}", identity_rule_start)
    ]
    rating_rule_start = hierarchy_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-summary-identity .recipe-edit-header-rating {"
    )
    rating_rule = hierarchy_css[
        rating_rule_start:hierarchy_css.index("}", rating_rule_start)
    ]
    assert "grid-template-columns: minmax(0, 1fr);" in identity_rule
    assert "justify-self: start;" in rating_rule
    assert "appendRecipeEditWorkspaceChildren(selectors, [cookbookField, sectionField, priceField])" in organizer
    assert "appendRecipeEditWorkspaceChildren(primaryRow, [identity, selectors, mobileImageSlot])" in organizer
    assert "appendRecipeEditWorkspaceChildren(descriptionRow, [descriptionField])" in organizer
    assert 'class="recipe-edit-rating-label">Rating</span>' in template
    assert 'shell.rating_control("recipeEditRatingStars", "Recipe rating", mode="recipe")' in template
    assert 'shell.rating_control("recipeEditRestaurantRatingStars", "Restaurant rating", mode="restaurant")' in template
    assert 'data-rating-toggle-selected="true"' in macros
    assert 'class="recipe-edit-rating-clear"' not in macros
    assert "appendRecipeEditWorkspaceChildren(technicalBody, [\n        titleField," in organizer
    final_order = "appendRecipeEditWorkspaceChildren(grid, [primaryRow, descriptionRow, tagRow, metadataRow, technicalDetails])"
    assert final_order in organizer
    assert "if (infoActions) infoActions.hidden = true;" in organizer
    assert "technicalDetails.open = false;" in organizer
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(130px, .62fr);" in hierarchy_css
    assert ".recipe-edit-info-panel-organized .recipe-edit-metadata-heading {" in css
    assert ".recipe-edit-description-row {\n    grid-template-columns: minmax(0, 1fr);" in hierarchy_css
    assert ".recipe-edit-price-currency {" in css
    assert ".recipe-edit-price-prefix {" not in css
    price_styles = css[
        css.index(".recipe-edit-standalone-page .recipe-edit-price-control {"):
        css.index(
            ".recipe-edit-standalone-page .recipe-edit-info-panel-organized .recipe-edit-source-files-details {"
        )
    ]
    assert "grid-template-columns: max-content minmax(0, 1fr);" in price_styles
    assert "border-right" not in price_styles
    assert ".recipe-edit-tag-chip {" in css
    assert ".recipe-edit-description-count {" in css
    assert 'event.target.id === "recipeEditDescription"' in script
    assert "updateRecipeEditDescriptionCount" in script
    assert 'value.replace(/\\s*(people|persons?|servings?|minutes?|mins?)' in script
    assert 'valueWrap.className = "recipe-edit-metadata-value"' in script
    assert 'unitLabel.className = "recipe-edit-metadata-unit"' in script
    assert "width: 68px;" in css
    assert "position: static;" in css
    assert "if (clear) clear.hidden = normalizedRating <= 0;" in script
    assert "border-color: transparent;" in hierarchy_css
    assert "background-color: transparent;" in hierarchy_css
    assert ".recipe-edit-summary-selectors .recipe-edit-price-control" in hierarchy_css
    assert ".recipe-edit-summary-selectors .recipe-edit-price-control:not(:focus-within):not(:has(" in hierarchy_css


def test_recipe_summary_selectors_are_borderless_with_accessible_state_feedback():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Borderless summary controls: preserve the control box while letting it merge with the dark panel. */"
    controls = css[css.index(marker):css.index(
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized .recipe-edit-description-row {",
        css.index(marker),
    )]

    for field_id in ("#recipeEditCookbookField", "#recipeEditCategoryMenuSectionField"):
        assert field_id in controls
    assert "> .recipe-edit-cookbook-value" in controls
    assert "> .recipe-edit-cookbook-value:focus-within" in controls
    assert '> .recipe-edit-cookbook-value:has(> .recipe-edit-cookbook-select[aria-expanded="true"])' in controls
    assert "> .recipe-edit-cookbook-select:disabled" in controls
    assert ".recipe-edit-price-control:focus-within:not(:has(" in controls
    assert ".recipe-edit-price-control:has(#recipeEditMenuPrice:disabled)" in controls

    for declaration in (
        "border: 1px solid transparent;",
        "border-color: transparent;",
        "background: transparent;",
        "box-shadow: 0 0 0 2px color-mix(in srgb, var(--app-primary-hover) 34%, transparent);",
    ):
        assert declaration in controls

    for hover_declaration in (
        "border-color: color-mix(in srgb, var(--app-primary-hover) 72%, var(--app-border-strong));",
        "box-shadow: 0 0 0 1px color-mix(in srgb, var(--app-primary-hover) 18%, transparent);",
    ):
        assert controls.count(hover_declaration) == 1

    price_rule_start = controls.index(
        ".recipe-edit-summary-selectors .recipe-edit-price-control {"
    )
    price_rule = controls[price_rule_start:controls.index("}", price_rule_start)]
    for preserved_dimension in ("height: 40px;", "min-height: 40px;"):
        assert preserved_dimension in price_rule


def test_recipe_metadata_strip_uses_spacing_without_internal_separators():
    css = read_text("PushShoppingList/static/css/app.css")
    phase_two_start = css.index(
        "/* Phase 2 recipe editor redesign using the AI Pantry shell tokens. */"
    )
    strip_selector = (
        "body.recipe-edit-standalone-page "
        ".recipe-edit-info-panel-organized .recipe-edit-metadata-strip {"
    )
    strip_start = css.index(strip_selector, phase_two_start)
    strip_rule = css[strip_start : css.index("}", strip_start)]

    for declaration in (
        "display: flex;",
        "flex-wrap: wrap;",
        "align-items: flex-start;",
        "column-gap: clamp(32px, 2.5vw, 48px);",
        "row-gap: 12px;",
        "border: 0;",
        "border-radius: 0;",
        "outline: 0;",
        "background: transparent;",
        "box-shadow: none;",
    ):
        assert declaration in strip_rule

    assert "grid-template-columns" not in strip_rule

    metric_rule_start = css.index(
        f"{strip_selector[:-1]}> label,",
        strip_start,
    )
    metric_rule = css[metric_rule_start : css.index("}", metric_rule_start)]
    assert "flex: 0 0 112px;" in metric_rule
    assert "width: 112px;" in metric_rule
    assert "border: 0;" in metric_rule

    total_metric_selector = (
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized\n"
        "    .recipe-edit-metadata-strip > .recipe-edit-total-time-field {"
    )
    total_metric_start = css.index(total_metric_selector, strip_start)
    total_metric_rule = css[total_metric_start : css.index("}", total_metric_start)]
    assert "flex-basis: 160px;" in total_metric_rule
    assert "width: 160px;" in total_metric_rule
    assert ".recipe-edit-total-time-field .recipe-edit-metadata-heading" in css
    assert "gap: 3px;" in css[total_metric_start:]

    assert ".recipe-edit-metadata-strip::before" not in css
    assert ".recipe-edit-metadata-strip::after" not in css

    metric_label_rules = re.findall(
        r"([^{}]*\.recipe-edit-metadata-strip\s*>\s*label[^{}]*)\{([^{}]*)\}",
        css[phase_two_start:],
    )
    assert metric_label_rules
    for _, declarations in metric_label_rules:
        for border_side in ("border-left", "border-right", "border-top", "border-bottom"):
            assert border_side not in declarations


def test_recipe_time_breakdown_is_one_accessible_persisted_disclosure():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    control = script[
        script.index("function createRecipeEditTimeBreakdownControl()"):
        script.index("function parseRecipeEditDurationMinutes")
    ]
    disclosure = script[
        script.index("function recipeEditTimeBreakdownStorageKey()"):
        script.index("function createRecipeEditTimeBreakdownControl()")
    ]

    assert 'button.type = "button"' in control
    assert "Breakdown</span>" not in control
    assert "Details</span>" not in control
    assert 'button.setAttribute("aria-expanded", "true")' in control
    assert 'button.setAttribute("aria-controls", "recipeEditTimeBreakdown")' in control
    assert 'button.setAttribute("aria-label", "Hide time breakdown")' in control
    assert 'class="recipe-edit-time-breakdown-chevron" aria-hidden="true"' in control
    assert 'button.addEventListener("click"' in control
    assert 'timeBreakdownGroup.id = "recipeEditTimeBreakdown"' in organizer
    assert 'timeBreakdownGroup.setAttribute("role", "group")' in organizer
    assert (
        "appendRecipeEditWorkspaceChildren(timeBreakdownGroup, "
        "[prepField, cookField, inactiveField])"
    ) in organizer
    assert "recipe-edit-time-breakdown-collapsed" in disclosure
    assert 'button.setAttribute("aria-label", `${isExpanded ? "Hide" : "Show"} time breakdown`)' in disclosure
    assert "group.hidden = !isExpanded" in disclosure
    assert ".value" not in script[
        script.index("function setRecipeEditTimeBreakdownExpanded"):
        script.index("function createRecipeEditTimeBreakdownControl")
    ]

    assert '"ai-pantry:recipe-editor:time-breakdown:v1"' in script
    assert "encodeURIComponent(userId)" in disclosure
    assert '!== "collapsed"' in disclosure
    assert "window.localStorage.getItem" in disclosure
    assert "window.localStorage.setItem" in disclosure
    assert disclosure.count("catch (_error)") == 2

    assert ".recipe-edit-time-breakdown-group[hidden]" in css
    assert "display: contents;" in css
    assert ".recipe-edit-time-breakdown-toggle:focus-visible" in css
    assert 'recipe-edit-time-breakdown-toggle[aria-expanded="true"]' in css
    assert ".recipe-edit-time-breakdown-group > label" in css
    assert 'totalField?.classList.add("recipe-edit-total-time-field")' in organizer
    assert "(totalTimeHeading || totalField)?.appendChild(timeBreakdownControl)" in organizer
    assert "recipe-edit-total-time-cluster" not in organizer
    assert (
        "appendRecipeEditWorkspaceChildren(metadataRow, "
        "[servingsField, scaleField, totalField, timeBreakdownGroup, levelField])"
    ) in organizer


def test_recipe_total_time_calculation_preserves_manual_override_and_saved_components():
    script = read_text("PushShoppingList/static/js/app.js")
    calculation = script[
        script.index("function parseRecipeEditDurationMinutes"):
        script.index("function bindRecipeEditNameInput")
    ]
    population = script[
        script.index("function populateRecipeEditor("):
        script.index("function replaceRecipeEditorIngredients")
    ]
    payload = script[
        script.index("function collectRecipeEditorPayload()"):
        script.index("function recipeEditorPersistableText")
    ]

    for field_id in (
        "recipeEditPrepTime",
        "recipeEditCookTime",
        "recipeEditInactiveTime",
    ):
        assert field_id in calculation
        assert field_id in payload
    for payload_field in ("total_time", "prep_time", "cook_time", "inactive_time"):
        assert f"{payload_field}: document.getElementById" in payload

    assert "function calculateRecipeEditTimeBreakdownMinutes()" in calculation
    assert "lastCalculatedMinutes" in calculation
    assert "manualOverride" in calculation
    assert "const totalIsBlank" in calculation
    assert "stillMatchesPreviousSum" in calculation
    assert "!state.manualOverride && stillMatchesPreviousSum" in calculation
    assert "updateRecipeEditTotalTimeOverrideState" in calculation
    assert 'totalInput.addEventListener("input", updateRecipeEditTotalTimeOverrideState)' in calculation
    assert 'addEventListener("input", updateRecipeEditCalculatedTotalTime)' in calculation
    assert "dispatchEvent" not in calculation

    initialize = population.index("initializeRecipeEditTotalTimeCalculation()")
    baseline = population.index("rememberRecipeEditorSavedState(form)")
    assert initialize < baseline
    attached = script.index(
        "appendRecipeEditWorkspaceChildren(grid, [primaryRow, descriptionRow, tagRow, metadataRow, technicalDetails])"
    )
    bound = script.index("bindRecipeEditTotalTimeCalculation()", attached)
    assert attached < bound


def test_recipe_name_is_directly_editable_without_a_pencil_control():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    binder_start = script.index("function bindRecipeEditNameInput(input)")
    binder_end = script.index("function organizeRecipeEditImageCard()", binder_start)
    binder = script[binder_start:binder_end]

    display_name_start = template.index('id="recipeEditDisplayName"')
    display_name_markup = template[display_name_start - 100:display_name_start + 220]
    assert 'aria-label="Edit recipe name"' in display_name_markup
    assert "required" in display_name_markup
    assert 'input.addEventListener("pointerdown"' in binder
    assert 'input.addEventListener("focus"' in binder
    assert 'if (typeof input.select === "function") input.select();' in binder
    assert 'event.key === "Escape"' in binder
    assert 'event.key !== "Enter"' in binder
    assert 'input.setCustomValidity("Enter a recipe name.")' in binder
    assert 'input.dataset.recipeEditNameOriginalValue' in binder
    assert ".recipe-edit-summary-name-edit" not in css
    assert "#recipeEditDisplayName:focus-visible" in css


def test_recipe_header_rating_stays_five_star_and_independent_from_restaurant_rating():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "{% for rating_value in range(1, 6) %}" in macros
    assert macros.count('data-rating-value="{{ rating_value }}"') == 1
    assert template.count('id="recipeEditRating"') == 1
    assert template.count('id="recipeEditRatingStars"') == 0
    assert template.count('shell.rating_control("recipeEditRatingStars", "Recipe rating", mode="recipe")') == 1
    assert template.count('shell.rating_control("recipeEditRestaurantRatingStars", "Restaurant rating", mode="restaurant")') == 1
    assert 'control.setAttribute("aria-label", `Recipe rating: ${normalizedRating} out of 5`)' in script
    assert 'control.dataset.ratingMode === "restaurant"' in script
    assert 'control.dataset.ratingMode === "recipe"' in script
    assert "Math.max(0, Math.min(5, rating))" in script
    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert "justify-self: end;" in css
    assert "justify-self: start;" in css
    assert "align-items: flex-start;" in css[css.index("@media (max-width: 767px)", css.index("/* Edit Recipe hierarchy")):]


def test_recipe_metadata_fields_have_accessible_tooltips():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer_start = script.index("function organizeRecipeEditInformationCard()")
    organizer_end = script.index("function organizeRecipeEditAiAssistant()", organizer_start)
    organizer = script[organizer_start:organizer_end]

    expected_tooltips = {
        "Servings": "Number of people or portions the recipe makes at the selected scale.",
        "Total Time": "Total elapsed time from start to finish, typically including prep, cooking, and inactive time.",
        "Prep Time": "Hands-on preparation time.",
        "Cook Time": "Time the food is actively cooking.",
        "Inactive Time": "Hands-off waiting time, such as resting, marinating, chilling, rising, or cooling.",
        "Difficulty": "Overall complexity based on skill, steps, timing, and equipment.",
        "Scale": "Multiplier applied to the base recipe; updates servings and ingredient amounts.",
    }
    for label, help_text in expected_tooltips.items():
        assert f'"{label}", "{help_text}"' in organizer

    assert "function addRecipeEditMetadataTooltip(field, label, helpText)" in script
    assert 'trigger.setAttribute("role", "button")' in script
    assert 'trigger.setAttribute("tabindex", "0")' in script
    assert 'trigger.setAttribute("aria-describedby", tooltipId)' in script
    assert 'control.setAttribute("aria-describedby", Array.from(describedBy).join(" "))' in script
    assert 'tooltip.setAttribute("role", "tooltip")' in script
    assert 'trigger.addEventListener("pointerenter"' in script
    assert 'trigger.addEventListener("focus"' in script
    assert 'trigger.addEventListener("click"' in script
    assert 'event.key === "Enter" || event.key === " "' in script
    assert 'document.addEventListener("pointerdown"' in script
    assert ".recipe-edit-metadata-tooltip-trigger:focus-visible" in css
    assert ".recipe-edit-metadata-tooltip[hidden]" in css
    tooltip_trigger_rule = css[
        css.index("body.recipe-edit-standalone-page .recipe-edit-metadata-tooltip-trigger {"):
    ]
    tooltip_trigger_rule = tooltip_trigger_rule[:tooltip_trigger_rule.index("}")]
    for declaration in (
        "width: 16px;",
        "min-width: 16px;",
        "max-width: 16px;",
        "height: 16px;",
        "min-height: 16px;",
        "max-height: 16px;",
        "flex: 0 0 16px;",
        "aspect-ratio: 1 / 1;",
        "padding: 0;",
        "box-sizing: border-box;",
        "border-radius: 50%;",
    ):
        assert declaration in tooltip_trigger_rule
    assert "position: fixed;" in css[css.index("body.recipe-edit-standalone-page .recipe-edit-metadata-tooltip {"):]
    assert "max-width: calc(100vw - 24px);" in css


def test_recipe_editor_standard_fields_are_quiet_until_active():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe workspace: keep standard fields quiet until they are active or invalid. */"
    targeted_summary_marker = (
        "/* Borderless summary controls: preserve the control box while letting it merge with the dark panel. */"
    )
    quiet_fields = css[css.index(marker):css.index(targeted_summary_marker)]

    assert css.rindex(marker) > css.rindex("/* Ingredient editor v25:")
    assert ".recipe-edit-info-panel:not(.recipe-edit-categories-panel)" in quiet_fields
    assert ".recipe-edit-categories-panel" in quiet_fields
    for control in ("input:where(:not(", "textarea,", "select"):
        assert control in quiet_fields
    for excluded_type in (
        "hidden",
        "checkbox",
        "radio",
        "file",
        "color",
        "range",
        "button",
        "submit",
        "reset",
        "image",
    ):
        assert f'[type="{excluded_type}"]' in quiet_fields
    assert "#recipeEditDisplayName" in quiet_fields
    assert ":not([disabled]):not([readonly])" in quiet_fields
    assert ":not([aria-invalid=\"true\"]):not([data-recipe-edit-validation-invalid=\"true\"])" in quiet_fields

    resting_rule = quiet_fields[:quiet_fields.index("}")]
    assert "border-color: transparent;" in resting_rule
    assert "background-color: color-mix(in srgb, var(--app-bg) 68%, var(--app-surface-soft));" in resting_rule
    assert "box-shadow: none;" in resting_rule

    hover_rule_start = quiet_fields.index(
        '):not([disabled]):not([readonly]):not([aria-invalid="true"]):not('
        '[data-recipe-edit-validation-invalid="true"]):hover'
    )
    hover_rule = quiet_fields[hover_rule_start:quiet_fields.index("}", hover_rule_start)]
    assert "border-color: color-mix(in srgb, var(--app-primary-hover) 72%, var(--app-border-strong));" in hover_rule
    assert "background-color: color-mix(in srgb, var(--app-bg) 76%, var(--app-surface-soft));" in hover_rule
    assert "box-shadow: 0 0 0 1px color-mix(in srgb, var(--app-primary-hover) 18%, transparent);" in hover_rule

    active_rule_start = quiet_fields.index(":is(:focus, :focus-visible)")
    active_rule = quiet_fields[active_rule_start:quiet_fields.index("}", active_rule_start)]
    assert hover_rule_start < active_rule_start
    assert "border-color: var(--app-primary-hover);" in active_rule
    assert "outline: 0;" in active_rule
    assert "background-color: color-mix(in srgb, var(--app-bg) 82%, var(--app-surface-soft));" in active_rule
    assert "box-shadow: 0 0 0 2px" in active_rule

    invalid_rule_start = quiet_fields.index(
        '):not([disabled]):not([readonly]):is([aria-invalid="true"], '
        '[data-recipe-edit-validation-invalid="true"])'
    )
    invalid_rule = quiet_fields[invalid_rule_start:quiet_fields.index("}", invalid_rule_start)]
    assert "border-color: var(--app-danger, #ef4444) !important;" in invalid_rule
    assert "background-color: color-mix(in srgb, var(--app-danger, #ef4444) 9%, var(--app-bg));" in invalid_rule
    assert "box-shadow: 0 0 0 2px" in invalid_rule
    assert ".recipe-edit-cookbook-select" not in quiet_fields
    assert ".recipe-edit-price-control:not(:focus-within):not(:has(" in quiet_fields
    price_hover_start = quiet_fields.index(".recipe-edit-price-control:hover:not(:focus-within):not(:has(")
    price_hover_rule = quiet_fields[price_hover_start:quiet_fields.index("}", price_hover_start)]
    assert "border-color: transparent;" in price_hover_rule
    assert "box-shadow: none;" in price_hover_rule
    assert ".recipe-edit-price-control:focus-within" in quiet_fields
    assert ".recipe-edit-price-control:has(" in quiet_fields
    assert "#recipeEditMenuPrice:is([aria-invalid=\"true\"], [data-recipe-edit-validation-invalid=\"true\"])" in quiet_fields


def test_recipe_category_panel_uses_readable_visual_hierarchy():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe editor: full-width category card between summary and content tabs. */"
    marker_start = css.index(marker)
    category_styles = css[marker_start:css.index("/* Narrow recipe editor:", marker_start)]

    title_start = category_styles.index(
        ".recipe-edit-categories-panel .recipe-edit-panel-heading h3 {"
    )
    title_rule = category_styles[title_start:category_styles.index("}", title_start)]
    assert "font-size: 16px;" in title_rule
    assert "font-weight: 800;" in title_rule

    subtitle_start = category_styles.index(".recipe-edit-category-recipe-name {")
    subtitle_rule = category_styles[subtitle_start:category_styles.index("}", subtitle_start)]
    assert "font-size: 12px;" in subtitle_rule
    assert "font-weight: 650;" in subtitle_rule

    assert ".recipe-edit-category-source {" not in category_styles

    label_start = category_styles.index(
        ".recipe-edit-category-grid label > span:first-child,"
    )
    label_rule = category_styles[label_start:category_styles.index("}", label_start)]
    assert "font-size: 11px;" in label_rule
    assert "font-weight: 760;" in label_rule

    value_start = category_styles.index(
        ".recipe-edit-category-grid :is(input, select, .recipe-edit-cookbook-select) {"
    )
    value_rule = category_styles[value_start:category_styles.index("}", value_start)]
    assert "font-size: 14px;" in value_rule
    assert "font-weight: 650;" in value_rule


def test_mobile_recipe_category_actions_share_the_heading_row():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe editor: full-width category card between summary and content tabs. */"
    category_styles = css[css.index(marker):css.index("/* Narrow recipe editor:", css.index(marker))]
    mobile = category_styles[category_styles.index("@media (max-width: 600px)"):]

    heading_start = mobile.index(
        ".recipe-edit-categories-panel .recipe-edit-panel-heading {"
    )
    heading_rule = mobile[heading_start:mobile.index("}", heading_start)]
    assert "align-items: center;" in heading_rule
    assert "flex-direction: row;" in heading_rule
    assert "flex-wrap: nowrap;" in heading_rule

    actions_start = mobile.index(".recipe-edit-category-actions {")
    actions_rule = mobile[actions_start:mobile.index("}", actions_start)]
    assert "width: auto;" in actions_rule
    assert "max-width: none;" in actions_rule
    assert "margin-left: auto;" in actions_rule
    assert "justify-content: flex-end;" in actions_rule

    assert ".recipe-edit-category-source {" not in mobile


def test_recipe_image_has_explicit_mobile_view_below_rating_at_narrow_widths():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert template.count('data-recipe-edit-mobile-image-slot') == 1
    assert template.count('id="recipeEditImageCardContent"') == 1
    assert template.count('id="recipeEditCoverField"') == 1
    assert template.count("data-recipe-edit-cover-image") == 2
    assert 'class="recipe-edit-image-mobile-slot recipe-image-mobile-slot recipe-edit-wide"' in template
    assert 'class="recipe-edit-context-card recipe-edit-image-card recipe-edit-image-desktop-slot recipe-image-desktop-slot"' in template
    assert "No recipe image available" in template
    assert "data-recipe-edit-mobile-generate-label" not in template
    assert template.count("data-recipe-image-change-toggle") == 2
    assert template.count('onclick="return openRecipeCoverUpload()"') >= 2
    assert template.count('onclick="return generateRecipeCoverImage(this)"') >= 2
    assert template.count('onclick="return removeRecipeCoverImage(this)"') >= 2
    assert template.count('onclick="return toggleRecipeFavorite(this, event)"') >= 2
    assert template.count('onerror="return handleRecipeEditorCoverImageError(this)"') == 2
    for state_field_id in (
        "recipeEditCoverPath",
        "recipeEditCoverUrl",
        "recipeEditCoverAlt",
        "recipeEditCoverMimeType",
        "recipeEditCoverSource",
    ):
        assert template.count(f'id="{state_field_id}"') == 1
    assert "organizeRecipeEditImageCard();" in script
    assert "organizeRecipeEditInformationCard();" in script
    assert "syncRecipeEditImageCardPlacement" not in script
    assert 'const mobileImageSlot = document.querySelector("[data-recipe-edit-mobile-image-slot]")' in script
    assert "appendRecipeEditWorkspaceChildren(identity, [nameLine, ratingField])" in script
    assert "appendRecipeEditWorkspaceChildren(primaryRow, [identity, selectors, mobileImageSlot])" in script
    assert 'button?.closest(".recipe-edit-cover-details, .recipe-edit-image-mobile-card")' in script
    assert 'document.querySelectorAll("[data-recipe-edit-cover-image]")' in script
    assert 'document.querySelectorAll("[data-recipe-edit-cover-remove]")' in script
    assert "function handleRecipeEditorCoverImageError(image)" in script

    responsive_start = css.index("/* Narrow recipe editor: render the mobile Recipe Image view")
    responsive = css[responsive_start:]
    assert "@media (max-width: 1099px)" in responsive
    assert "grid-template-columns: minmax(0, 1fr);" in responsive
    assert ".recipe-image-desktop-slot" in responsive
    assert ".recipe-image-mobile-slot" in responsive
    assert "aspect-ratio: 4 / 3;" in responsive
    assert "object-fit: cover;" in responsive
    assert "flex-wrap: wrap;" in responsive
    assert "details.recipe-edit-context-card:not([open]) > :not(summary)" in css
    assert "\n    .recipe-edit-context-card:not([open]) > :not(summary)" not in css


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
    assert "border-radius: 7px;" in css
    assert css.count("[data-shared-rating-control] .recipe-edit-rating-star {") == 1
    assert '[data-shared-rating-control] .recipe-edit-rating-star[aria-checked="true"]' in css
    assert ".recipe-edit-header-rating .recipe-edit-rating-star {" not in css
    assert ".recipe-edit-restaurant-rating-editor .recipe-edit-rating-star {" not in css
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


def test_shared_selected_rating_star_has_no_persistent_gold_frame():
    css = read_text("PushShoppingList/static/css/app.css")
    selector = '[data-shared-rating-control] .recipe-edit-rating-star[aria-checked="true"] {'
    rule_start = css.index(selector)
    selected_rule = css[rule_start:css.index("}", rule_start)]

    assert "border-color: transparent;" in selected_rule
    assert "background: transparent;" in selected_rule
    assert "box-shadow: none;" in selected_rule
    assert "251, 191, 36" not in selected_rule

    focus_selector = "[data-shared-rating-control] .recipe-edit-rating-star:focus-visible {"
    focus_start = css.index(focus_selector)
    focus_rule = css[focus_start:css.index("}", focus_start)]
    assert "156, 163, 175" in focus_rule
    assert "251, 191, 36" not in focus_rule

    assert ".recipe-edit-header-rating .recipe-edit-rating-star {" not in css
    assert ".recipe-edit-restaurant-rating-editor .recipe-edit-rating-star {" not in css


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
    tab_list_end = template.index("</div>", tab_list_start)
    tab_list = template[tab_list_start:tab_list_end]
    expected_tabs = ["ingredients", "instructions", "equipment", "nutrition", "notes"]

    assert tab_list.count('data-recipe-edit-tab="') == len(expected_tabs)
    assert [tab_list.index(f'data-recipe-edit-tab="{tab}"') for tab in expected_tabs] == sorted(
        tab_list.index(f'data-recipe-edit-tab="{tab}"') for tab in expected_tabs
    )
    assert tab_list.count('aria-selected="true"') == 1
    assert 'data-recipe-edit-tab="ingredients"' in tab_list[:tab_list.index('aria-selected="false"')]
    assert "recipe-edit-ingredient-view-switcher" not in template

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
    assert "tableHeadViewport.appendChild(tableHead);" in tools_block
    assert "tableBodyScroll.appendChild(ingredientList);" in tools_block


def test_recipe_editor_ingredient_options_use_inline_nested_table_disclosure():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'substitutions.classList.add("recipe-edit-ingredient-options-panel")' in organize
    assert "row.appendChild(substitutions);" in organize
    assert 'alternativesDialog = document.createElement("dialog");' not in organize
    assert "substitutions.hidden = true;" in organize
    assert 'optionsCell.className = "recipe-edit-ingredient-substitution-cell";' in organize
    assert 'optionsCell.setAttribute("role", "cell");' in organize
    assert 'optionsButton.className = "recipe-edit-ingredient-options-button";' in organize
    assert 'optionsButton.setAttribute("aria-haspopup", "dialog");' not in organize
    assert 'optionsButton.setAttribute("aria-controls", substitutions.id);' in organize
    assert "toggleRecipeIngredientSubstitutions(optionsButton, event)" in organize
    assert "organizeRecipeEditSubstitutionOptionRow" in script
    assert 'label.textContent = alternativeCount ? optionLabel : "None";' in script

    nested_css = css[css.index("/* Ingredient editor v45:"):]
    assert "> .recipe-edit-ingredient-options-panel" in nested_css
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid);" in nested_css
    assert ".recipe-edit-ingredient-option-divider" in nested_css
    assert ".recipe-edit-alternative-component-summary" in nested_css
    assert ".recipe-edit-ingredient-option-group::before" in nested_css


def test_recipe_editor_ingredient_table_uses_mockup_icons_and_compact_controls():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert '{{ shell.svg_icon("plus") }}' in template
    assert '{{ shell.svg_icon("sort") }}' in template
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


def test_recipe_editor_substitution_groups_use_mockup_table_hierarchy():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "DEFAULT OPTION" in script
    assert "ALTERNATIVE OPTION" in script
    assert "Add ingredient to this option" in script
    assert "Add another option to this ingredient group" in script
    assert 'class="recipe-edit-substitution-thumbnail"' in script
    assert 'data-ingredient-column="status"' in script
    assert 'data-ingredient-column="quantity"' in script
    assert 'data-ingredient-column="unit"' in script
    assert 'data-ingredient-column="size"' in script
    assert 'data-ingredient-column="store"' in script
    assert 'data-ingredient-column="type"' in script
    assert 'marker.type = "radio";' not in script
    assert ".recipe-edit-alternative-component-status" in css
    assert ".recipe-edit-alternative-component-size" in css
    assert ".recipe-edit-alternative-component-actions" in css


def test_new_recipe_ingredient_alternative_is_organized_before_controls_are_bound():
    script = read_text("PushShoppingList/static/js/app.js")
    add_start = script.index("function addRecipeIngredientSubstitutionRow(button)")
    add_end = script.index(
        "function removeRecipeIngredientSubstitutionRow",
        add_start,
    )
    add_alternative = script[add_start:add_end]

    organize_call = "organizeRecipeEditSubstitutionOptionRow(optionRow);"
    bind_call = "bindRecipeIngredientSubstitutionRow(optionRow);"
    assert organize_call in add_alternative
    assert bind_call in add_alternative
    assert add_alternative.index(organize_call) < add_alternative.index(bind_call)


def test_new_recipe_ingredient_alternative_opens_as_a_standard_inline_row():
    script = read_text("PushShoppingList/static/js/app.js")
    add_start = script.index("function addRecipeIngredientSubstitutionRow(button)")
    add_end = script.index(
        "function removeRecipeIngredientSubstitutionRow",
        add_start,
    )
    add_alternative = script[add_start:add_end]

    assert "setRecipeIngredientAlternativeEditMode" not in add_alternative
    assert "dataset.newAlternative" not in add_alternative
    assert (
        "optionRow.querySelector("
        "'[data-recipe-ingredient-inline-field=\"ingredient\"]'"
        ")"
        in add_alternative
    )
    assert "field.focus({ preventScroll: true });" in add_alternative


def test_add_ingredient_to_option_opens_standard_inline_component_rows():
    script = read_text("PushShoppingList/static/js/app.js")
    default_start = script.index("function addRecipeIngredientDefaultComponent(button)")
    default_end = script.index(
        "function updateRecipeIngredientSubstitutionState",
        default_start,
    )
    default_component = script[default_start:default_end]
    alternative_start = script.index("function addRecipeIngredientAlternativeComponent(button)")
    alternative_end = script.index(
        "function removeRecipeIngredientAlternativeComponent",
        alternative_start,
    )
    alternative_component = script[alternative_start:alternative_end]

    for add_component in (default_component, alternative_component):
        assert "setRecipeIngredientAlternativeEditMode" in add_component
        assert ", true" not in add_component
        assert ", false" in add_component
        assert (
            "'[data-recipe-ingredient-inline-field=\"ingredient\"]'"
            in add_component
        )
        assert "field.focus({ preventScroll: true });" in add_component


def test_recipe_editor_expanded_option_rows_share_the_parent_table_grid_without_offsets():
    css = read_text("PushShoppingList/static/css/app.css")
    expanded_grid_css = css[css.index("/* Ingredient editor v46:"):]

    assert (
        ".recipe-edit-standalone-page .recipe-edit-ingredient-table-head,\n"
        ".recipe-edit-standalone-page #recipeEditIngredients > .recipe-edit-ingredient-row {\n"
        "    grid-template-columns: var(--recipe-edit-ingredient-grid)"
    ) in css
    assert ".recipe-edit-ingredient-option-divider," in expanded_grid_css
    assert ".recipe-edit-alternative-component-summary," in expanded_grid_css
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in expanded_grid_css
    for declaration in (
        "box-sizing: border-box;",
        "width: 100%;",
        "min-width: 0;",
        "max-width: 100%;",
    ):
        assert declaration in expanded_grid_css

    assert ".recipe-edit-alternative-component-summary > *" in expanded_grid_css
    assert ".recipe-edit-alternative-component-handle-cell," in expanded_grid_css
    assert ".recipe-edit-alternative-component-image-cell" in expanded_grid_css
    assert "transform: none;" in expanded_grid_css
    assert "transform: translateX" not in expanded_grid_css
    assert "width: max-content" not in expanded_grid_css
    assert "min-height: 58px;" in expanded_grid_css


def test_recipe_editor_expanded_option_dividers_and_add_rows_are_compact_grid_rows():
    css = read_text("PushShoppingList/static/css/app.css")
    expanded_grid_css = css[css.index("/* Ingredient editor v46:"):]

    divider_start = expanded_grid_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-option-divider {"
    )
    divider_rule = expanded_grid_css[
        divider_start:expanded_grid_css.index("}", divider_start)
    ]
    assert "display: grid;" in divider_rule
    assert "min-height: 30px;" in divider_rule
    assert "padding: 3px 0;" in divider_rule

    assert '> [data-ingredient-grid-column="ingredient"]' in expanded_grid_css
    assert "grid-column: 3;" in expanded_grid_css
    assert ".recipe-edit-alternative-add-component," in expanded_grid_css
    assert "display: grid !important;" in expanded_grid_css
    assert "min-height: 34px;" in expanded_grid_css
    assert "margin: 0;" in expanded_grid_css
    assert "padding: 2px 0;" in expanded_grid_css
    assert ".recipe-edit-substitution-heading" in expanded_grid_css
    assert "grid-column: 1 / -1;" in expanded_grid_css

    # Hierarchy is carried by the ingredient-cell inset, not by shifting the row.
    assert "padding-left: 14px;" in expanded_grid_css
    assert "border-left: 1px solid" in expanded_grid_css
    assert ".recipe-edit-ingredient-option-group::before" in expanded_grid_css
    assert "content: none;" in expanded_grid_css


def test_recipe_editor_nested_rows_keep_complete_columns_and_actions_at_the_far_right():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    summary_builder_start = script.index("function createRecipeIngredientOptionRowSummary(")
    summary_builder_end = script.index(
        "function updateRecipeIngredientOptionRowSummary",
        summary_builder_start,
    )
    summary_markup = script[summary_builder_start:summary_builder_end]
    organize_start = script.index("function organizeRecipeEditSubstitutionOptionRow(optionRow)")
    organize_end = script.index(
        "function editRecipeIngredientSubstitutionFields",
        organize_start,
    )
    organize = script[organize_start:organize_end]

    expected_columns = (
        "media",
        "ingredient",
        "status",
        "quantity",
        "unit",
        "size",
        "store",
        "type",
        "alternatives",
        "actions",
    )
    assert all(f'data-ingredient-column="{column}"' in summary_markup for column in expected_columns)
    assert summary_markup.index('data-ingredient-column="ingredient"') < summary_markup.index(
        'data-ingredient-column="status"'
    )
    assert summary_markup.index('data-ingredient-column="store"') < summary_markup.index(
        'data-ingredient-column="type"'
    )
    assert summary_markup.index('data-ingredient-column="type"') < summary_markup.index(
        'data-ingredient-column="actions"'
    )
    assert "trash" not in summary_markup
    assert 'editButton.setAttribute("aria-label", "Edit ingredient");' in organize
    assert 'menuButton.setAttribute("aria-label", "Replacement ingredient actions");' in organize
    assert "actions?.append(editButton, menuWrap);" in organize
    assert "Remove replacement ingredient" in organize
    assert "const summary = createRecipeIngredientOptionRowSummary();" in organize
    assert 'editButton.setAttribute("aria-label", `Edit ${name}`);' in script
    assert 'editButton.title = `Edit ${name}`;' in script

    default_start = script.index("function createRecipeIngredientDefaultOptionSummary(row)")
    default_end = script.index("function ensureRecipeIngredientChoiceOverview", default_start)
    default_summary = script[default_start:default_end]
    assert (
        'createRecipeIngredientOptionRowSummary("recipe-edit-default-option-summary")'
        in default_summary
    )
    assert 'class="recipe-edit-compact-row-edit"' in default_summary
    assert 'aria-expanded="false"' in default_summary
    assert 'class="recipe-edit-row-menu-btn"' in default_summary
    assert 'aria-expanded="false"' in default_summary
    assert 'recipeEditSvgIcon("trash")' not in default_summary
    assert 'recipeEditSvgIcon("basket")' not in default_summary

    card_start = script.index("function createRecipeIngredientAlternativeCard(group, groupIndex)")
    card_end = script.index("function ensureRecipeIngredientAlternativeCards", card_start)
    card = script[card_start:card_end]
    assert "group.rows.forEach(optionRow => components.appendChild(optionRow));" in card

    v47_css = css[css.index("/* Ingredient editor v47:"):]
    summary_rule_start = v47_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-alternative-component-summary {"
    )
    summary_rule = v47_css[
        summary_rule_start:v47_css.index("}", summary_rule_start)
    ]
    # This must beat the legacy display:contents rule; otherwise nested cells
    # become implicit items in the option wrapper and collapse to the right.
    assert "display: grid !important;" in summary_rule
    assert "min-height: 64px;" in summary_rule
    assert "grid-template-columns: var(--recipe-edit-ingredient-grid) !important;" in v47_css


def test_recipe_editor_selected_choice_actions_follow_custom_column_positions():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    mobile_header_selector = (
        '".recipe-edit-ingredient-mobile-header > [data-ingredient-column], "'
    )
    selected_choice_selector = (
        '".recipe-edit-selected-choice-group-header > [data-ingredient-column], "'
    )
    option_row_selector = (
        '".recipe-edit-alternative-component-summary > [data-ingredient-column]"'
    )

    visibility_start = script.index("function applyRecipeEditIngredientColumnVisibility")
    visibility_end = script.index("function clearRecipeIngredientModalColumnVisibility", visibility_start)
    visibility = script[visibility_start:visibility_end]
    assert mobile_header_selector in visibility
    assert selected_choice_selector in visibility
    assert option_row_selector in visibility

    clear_start = script.index("function clearRecipeEditIngredientColumnLayoutStyles")
    clear_end = script.index("function applyRecipeEditIngredientColumnLayoutToRow", clear_start)
    clear = script[clear_start:clear_end]
    assert mobile_header_selector in clear
    assert selected_choice_selector in clear
    assert option_row_selector in clear

    apply_start = script.index("function applyRecipeEditIngredientColumnLayoutToRow")
    apply_end = script.index("function applyRecipeEditIngredientColumnLayout()", apply_start)
    apply = script[apply_start:apply_end]
    assert mobile_header_selector in apply
    assert selected_choice_selector in apply
    assert option_row_selector in apply
    assert 'cell.style.setProperty(\n            "grid-column",' in apply
    assert 'cell.dataset.recipeEditIngredientColumnHidden = "true";' in apply

    mobile_release = css[css.index("/* Ingredient editor v71:"):]
    assert css.index("/* Ingredient editor v71:") > css.index("/* Ingredient editor v48:")
    assert "> .recipe-edit-ingredient-row.recipe-edit-ingredient-table-grid {" in mobile_release
    assert "grid-template-columns: 40px minmax(0, 1fr) max-content 106px !important;" in mobile_release
    assert "> .recipe-edit-ingredient-mobile-header {" in mobile_release
    assert "width: 100%;" in mobile_release
    assert "max-width: 100%;" in mobile_release


def test_recipe_editor_expanded_groups_preserve_disclosure_and_option_heading_accessibility():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    organize_start = script.index("function organizeRecipeEditIngredientRow(row)")
    organize_end = script.index("function organizeRecipeEditCompactRowActions", organize_start)
    organize = script[organize_start:organize_end]
    assert 'optionsButton.setAttribute("aria-controls", substitutions.id);' in organize

    expanded_start = script.index("function setRecipeIngredientSubstitutionsExpanded(")
    expanded_end = script.index("function toggleRecipeIngredientSubstitutions", expanded_start)
    expanded = script[expanded_start:expanded_end]
    assert 'otherButton.setAttribute("aria-expanded", "false");' not in expanded
    assert "recipeIngredientExpansionIsOpen(row, optionsButton)" in expanded

    default_start = script.index("function ensureRecipeIngredientChoiceOverview(")
    default_end = script.index("function addRecipeIngredientDefaultComponent", default_start)
    default_option = script[default_start:default_end]
    alternative_start = script.index("function createRecipeIngredientAlternativeCard(")
    alternative_end = script.index("function ensureRecipeIngredientAlternativeCards", alternative_start)
    alternative_option = script[alternative_start:alternative_end]
    for option_markup in (default_option, alternative_option):
        assert 'role="heading"' in option_markup
        assert 'aria-level="4"' in option_markup

    nested_css = css[css.index("/* Ingredient editor v45:"):]
    assert ".recipe-edit-alternative-component-edit:is(:hover, :focus-visible)" in nested_css
    assert ".recipe-edit-alternative-add-component:is(:hover, :focus-visible)" in nested_css
    assert "/* Ingredient editor v53:" in nested_css
    assert (
        ".recipe-edit-alternative-component-actions.recipe-edit-compact-row-actions"
        in nested_css
    )


def test_recipe_editor_compact_rows_keep_headers_actions_and_tool_organization():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    for class_name, labels in (
        ("recipe-edit-equipment-header", ("Image", "Equipment", "Options", "Edit", "Delete")),
        ("recipe-edit-instructions-header", ("Step", "Image", "Instruction", "Actions")),
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


def test_recipe_editor_instructions_use_read_first_step_grid_and_preserve_handlers():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    instructions_css = css[css.index("/* Instruction editor v2:"):]

    assert 'class="recipe-edit-section-header instructions-toolbar"' in template
    assert "recipe-edit-instructions-actions instructions-toolbar-actions" in template
    assert 'id="recipeEditInstructionCount"' in template
    assert 'class="recipe-edit-add-instruction-button"' in template
    assert "data-recipe-instruction-reorder-toggle" in template
    assert 'aria-pressed="false"' in template
    template_header_start = template.index('class="recipe-edit-instructions-header"')
    template_header_end = template.index("</div>", template_header_start)
    template_header = template[template_header_start:template_header_end]
    assert template_header.count("<span") == 5
    assert "<span>Options</span>" not in template_header

    assert """--recipe-edit-instruction-grid:
        28px
        48px
        64px
        minmax(320px, 1fr)
        116px;""" in instructions_css
    assert "grid-template-columns: var(--recipe-edit-instruction-grid) !important;" in instructions_css
    assert "body.recipe-edit-standalone-page .recipe-edit-instructions-header," in instructions_css
    assert "body.recipe-edit-standalone-page #recipeEditInstructions > .recipe-edit-instruction-row {" in instructions_css
    assert "display: block;" in instructions_css
    assert "flex: 0 0 auto;" in instructions_css
    assert "align-content: start;" in instructions_css
    assert "overflow-x: auto;" in instructions_css
    assert "overflow-y: visible;" in instructions_css
    assert "position: static;" in instructions_css
    assert "min-height: 72px;" in instructions_css
    assert "width: 52px;" in instructions_css
    assert "width: 36px;" in instructions_css
    assert ".recipe-edit-instruction-read-text" in instructions_css
    assert ".recipe-edit-instruction-row.is-editing > .recipe-edit-instruction-read-text" in instructions_css
    assert ".recipe-edit-instruction-edit-panel[hidden]" in instructions_css
    assert "display: none !important;" in instructions_css
    assert "min-height: 88px;" in instructions_css
    assert "max-height: 180px;" in instructions_css
    assert "@media (max-width: 760px)" in instructions_css
    assert "grid-template-columns: 28px 42px 56px minmax(0, 1fr) !important;" in instructions_css
    assert "grid-column: 2 / 5;" in instructions_css
    assert "-webkit-line-clamp: 3;" in instructions_css

    medium_start = instructions_css.index("@media (min-width: 761px) and (max-width: 1100px)")
    medium_end = instructions_css.index("@media (max-width: 760px)", medium_start)
    medium_css = instructions_css[medium_start:medium_end]
    medium_step_start = medium_css.index(
        "body.recipe-edit-standalone-page #recipeEditInstructions > "
        ".recipe-edit-instruction-row > .recipe-edit-step-number {"
    )
    medium_step_end = medium_css.index("}", medium_step_start)
    medium_step_rule = medium_css[medium_step_start:medium_step_end]
    assert "width: 44px;" in medium_step_rule
    assert "min-width: 44px;" in medium_step_rule

    mobile_start = instructions_css.index("@media (max-width: 760px)")
    mobile_end = instructions_css.index("@media (max-width: 360px)", mobile_start)
    mobile_css = instructions_css[mobile_start:mobile_end]
    mobile_header_start = mobile_css.index(
        "body.recipe-edit-standalone-page .recipe-edit-instructions-header {"
    )
    mobile_header_end = mobile_css.index("}", mobile_header_start)
    assert "display: none;" in mobile_css[mobile_header_start:mobile_header_end]

    mobile_edit_start = mobile_css.index(
        "body.recipe-edit-standalone-page #recipeEditInstructions > "
        ".recipe-edit-instruction-row > .recipe-edit-instruction-edit-panel {"
    )
    mobile_edit_end = mobile_css.index("}", mobile_edit_start)
    mobile_edit_rule = mobile_css[mobile_edit_start:mobile_edit_end]
    assert "grid-row: 2;" in mobile_edit_rule

    mobile_image_start = mobile_css.index(
        "body.recipe-edit-standalone-page #recipeEditInstructions > "
        ".recipe-edit-instruction-row > .recipe-step-image-panel.recipe-image-tools-visible {"
    )
    mobile_image_end = mobile_css.index("}", mobile_image_start)
    mobile_image_rule = mobile_css[mobile_image_start:mobile_image_end]
    assert "grid-row: 3;" in mobile_image_rule
    assert "grid-row: 2;" not in mobile_image_rule

    row_start = script.index("function addRecipeInstructionRow")
    row_end = script.index("function addRecipeNutritionRow", row_start)
    row_code = script[row_start:row_end]
    assert 'const isNewBlankRow = arguments.length === 0 && !String(instruction || "").trim();' in row_code
    assert 'row.dataset.recipeInstructionNew = "true";' in row_code
    for preserved_field in (
        'data-field="text"',
        'data-field="step_number"',
        'data-field="step_image_url"',
        'data-field="step_image_generated_at"',
        'data-field="step_image_prompt"',
        'data-field="id"',
        'data-field="instruction_id"',
        'data-field="step_id"',
        'data-field="row_id"',
    ):
        assert preserved_field in row_code
    assert "data-instruction-row-number" in row_code
    assert "number.textContent = value;" in row_code
    assert "panel.dataset.stepNumber = value;" in row_code
    assert "organizeRecipeEditInstructionRow(row);" in row_code
    assert "bindRecipeEditDragAndDrop(row);" in row_code
    assert "function resizeRecipeEditInstructionTextarea" in row_code
    assert "function toggleRecipeEditInstructionDetails" in row_code
    assert 'row.classList.add("recipe-edit-read-first-instruction");' in row_code
    assert 'optionsButton.setAttribute("aria-label", "Step actions");' in row_code
    assert 'readText.className = "recipe-edit-instruction-read-text";' in row_code
    assert 'readText.dataset.recipeEditInstructionReadText = "";' in row_code
    assert 'summary.textContent = text || "Add instruction text";' in row_code
    assert 'summary.classList.toggle("is-empty", !text);' in row_code
    assert 'editPanel.className = "recipe-edit-instruction-edit-panel";' in row_code
    assert "editPanel.hidden = true;" in row_code
    assert "editBody.appendChild(textField);" in row_code
    assert 'onclick="return cancelRecipeInstructionInlineEdit(this)"' in row_code
    assert 'onclick="return saveRecipeInstructionInlineEdit(this)"' in row_code
    assert "Save Step" in row_code
    assert 'document.querySelectorAll("#recipeEditInstructions > .recipe-edit-instruction-row.is-editing")' in row_code
    assert 'editPanel.dataset.editSnapshot = JSON.stringify({ text: textarea.value });' in row_code
    assert 'setRecipeInstructionEditMode(otherRow, false, { restore: restoreOtherEdits });' in row_code
    assert 'row.classList.toggle("is-editing", Boolean(shouldEdit));' in row_code
    assert "editPanel.hidden = !shouldEdit;" in row_code
    assert 'setRecipeInstructionEditMode(row, false, { restore: true })' in row_code
    assert 'textarea.setCustomValidity("Enter instruction text.");' in row_code
    assert "updateRecipeInstructionReadSummary(row);" in row_code
    assert 'updateRecipeEditorDirtyState(row.closest("#recipeEditForm"));' in row_code
    assert "setRecipeEditRowImageToolsVisible(row, false);" in row_code
    assert 'detailsButton.setAttribute("aria-expanded", "false");' in row_code
    assert 'detailsButton.setAttribute("onclick", "return toggleRecipeEditInstructionDetails(this)");' in row_code
    assert 'count.textContent = `${rows.length} ${rows.length === 1 ? "step" : "steps"}`;' in row_code

    edit_mode_start = row_code.index("function setRecipeInstructionEditMode")
    edit_mode_end = row_code.index("function saveRecipeInstructionInlineEdit", edit_mode_start)
    edit_mode = row_code[edit_mode_start:edit_mode_end]
    assert "const restoreOtherEdits = options.restoreOtherEdits === true;" in edit_mode
    assert 'if (!shouldEdit && row.dataset.recipeInstructionNew === "true")' in edit_mode
    assert 'if (!String(textarea.value || "").trim())' in edit_mode
    assert "row.remove();" in edit_mode
    assert "updateRecipeInstructionStepNumbers();" in edit_mode
    assert "updateRecipeEditContextPanels();" in edit_mode
    assert 'updateRecipeEditorDirtyState(document.getElementById("recipeEditForm"));' in edit_mode
    assert "delete row.dataset.recipeInstructionNew;" in edit_mode

    step_numbers_start = row_code.index("function updateRecipeInstructionStepNumbers")
    step_numbers = row_code[step_numbers_start:]
    assert 'const editStep = row.querySelector("[data-recipe-instruction-edit-step]");' in step_numbers
    assert "editStep.textContent = value;" in step_numbers

    header_start = row_code.index("function recipeInstructionsHeaderHtml")
    header_end = row_code.index("function resizeRecipeEditInstructionTextarea", header_start)
    runtime_header = row_code[header_start:header_end]
    assert runtime_header.count("<span") == 5
    assert "<span>Options</span>" not in runtime_header

    compact_actions_start = script.index("function organizeRecipeEditCompactRowActions")
    compact_actions_end = script.index("function updateRecipeEditIngredientDetailsState", compact_actions_start)
    compact_actions = script[compact_actions_start:compact_actions_end]
    assert 'const isInstructionRow = label === "step";' in compact_actions
    assert "const menuInActions = isIngredientRow || isInstructionRow;" in compact_actions
    assert '${menuInActions ? "" : `<button type="button"' in compact_actions
    assert "if (menuInActions)" in compact_actions
    assert "actions.appendChild(menuWrap);" in compact_actions

    focus_start = script.index("function focusRecipeEditCompactRow")
    focus_end = script.index("function setRecipeIngredientEditMode", focus_start)
    focus_code = script[focus_start:focus_end]
    assert 'row.classList.contains("recipe-edit-read-first-instruction")' in focus_code
    assert "return setRecipeInstructionEditMode(row, true);" in focus_code

    reorder_start = script.index("function beginRecipeInstructionReorder")
    reorder_end = script.index("function recipeEditMetadataFields", reorder_start)
    reorder_code = script[reorder_start:reorder_end]
    assert 'list.classList.toggle("recipe-edit-instruction-reorder-mode", active);' in reorder_code
    assert 'label.textContent = active ? "Done Reordering" : "Reorder";' in reorder_code
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false");' in reorder_code
    assert 'setRecipeInstructionEditMode(row, false);' in reorder_code
    assert 'setRecipeEditRowImageToolsVisible(row, false);' in reorder_code

    assert "recipe-edit-instruction-expanded" in css
    assert "recipe-edit-instruction-reorder-mode" in css
    assert "recipe-edit-row-dragging" in css

    image_tools_start = script.index("function setRecipeEditRowImageToolsVisible(row, visible)")
    image_tools_end = script.index("function setRecipeEditRowImageVisible", image_tools_start)
    image_tools = script[image_tools_start:image_tools_end]
    assert "[data-step-image-panel]" in image_tools
    assert "updateRecipeEditInstructionDetailsState(row);" in image_tools

    assert (
        "#recipeEditInstructions > .recipe-edit-instruction-row > "
        ".recipe-step-image-panel:has(.recipe-step-image:not([hidden]))"
    ) not in css
    assert (
        "#recipeEditInstructions > .recipe-edit-instruction-row > "
        ".recipe-step-image-panel:not(:has(.recipe-step-image:not([hidden])))"
    ) not in css


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
    assert "function beginRecipeIngredientReorder" not in script
    assert "function focusRecipeIngredientGrouping" not in script
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
    assert "Replace ingredient with this alternative" in script
    assert script.count("setRecipeIngredientsCollapsed(recipeIngredientsShouldStartCollapsed());") == 2


def test_recipe_health_dashboard_is_compact_and_separate_from_ai_confidence():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    health_start = template.index('class="recipe-edit-context-card recipe-edit-health-card"')
    confidence_start = template.index('id="recipeEditAiConfidenceCard"')
    assert health_start < confidence_start
    organizer = script[
        script.index("function organizeRecipeEditStandaloneWorkspace()"):
        script.index("function syncRecipeEditDocumentRows()")
    ]
    sidebar_order = organizer[organizer.index("appendRecipeEditWorkspaceChildren(sidebar"):]
    assert sidebar_order.index("healthCard") < sidebar_order.index("confidenceCard")
    assert "healthCard.appendChild(confidenceCard)" not in organizer
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
    assert "grid-template-columns: minmax(0, 3fr) minmax(300px, 1fr);" in css
    assert "recipe-edit-utility-column" not in css
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


def test_recipe_editor_is_readable_at_native_desktop_zoom():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe workspace v16: native-zoom readability and container-aware context rail. */"
    readable = css[css.index(marker):]

    assert "container: recipe-editor-workspace / inline-size;" in readable
    assert "grid-template-columns: minmax(0, 1fr) minmax(300px, 320px);" in readable
    assert "@container recipe-editor-workspace (max-width: 1450px)" in readable
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in readable
    assert "@container recipe-editor-workspace (max-width: 900px)" in readable
    assert "overflow-x: auto;" in readable
    assert "@container recipe-editor-workspace (max-width: 760px)" in readable

    desktop = readable[readable.index("@media (min-width: 768px)"):]
    for declaration in (
        "--recipe-edit-ingredient-name-font-size: 14px;",
        "--recipe-edit-ingredient-detail-font-size: 12px;",
        "--recipe-edit-ingredient-column-font-size: 13px;",
        "--recipe-edit-ingredient-column-font-weight: 500;",
        "min-height: 80px !important;",
    ):
        assert declaration in desktop

    assert ".recipe-edit-ingredient-table-head > [role=\"columnheader\"]" in desktop
    assert ".recipe-edit-document-row :is(strong, span)" in desktop
    assert ".recipe-edit-confidence-body p" in desktop
    assert ".recipe-edit-health-attention" in desktop
    assert desktop.count("font-size: 12px;") >= 8
    assert "font-size: 14px;" in desktop


def test_recipe_editor_wide_workspace_preserves_exactly_two_content_columns():
    css = read_text("PushShoppingList/static/css/app.css")

    wide_workspace_start = css.index("/* Wide recipe workspace:")
    wide_workspace_end = css.index("\n}\n", wide_workspace_start) + 3
    wide_workspace = css[wide_workspace_start:wide_workspace_end]

    assert "@media (min-width: 1500px)" in wide_workspace
    assert "grid-template-columns: minmax(0, 3fr) minmax(300px, 1fr);" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-main-workspace {\n        display: block;\n        grid-column: 1;\n        grid-row: 1;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-context-sidebar {\n        grid-column: 2;\n        grid-row: 1;" in wide_workspace
    assert "recipe-edit-utility-column" not in wide_workspace


def test_recipe_editor_wide_ingredients_workspace_keeps_header_stack_sticky():
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")

    wide_workspace_start = css.index("/* Wide recipe workspace:")
    wide_workspace = css[wide_workspace_start:]

    assert ".recipe-edit-standalone-page .recipe-edit-backdrop.open {\n        display: flex;\n        min-height: 100%;" in wide_workspace
    assert "grid-template-rows: none;" in wide_workspace
    assert ".recipe-edit-standalone-page .recipe-edit-tab-list {\n        position: static;" in wide_workspace
    assert ".recipe-edit-ingredients-section > .recipe-edit-section-header {\n        position: static;" in wide_workspace
    assert ".recipe-edit-ingredients-section:not([hidden]) {\n        display: block;" in wide_workspace
    assert ".recipe-edit-ingredients-section .recipe-edit-ingredient-table-scroll {" in wide_workspace
    assert "overflow-x: auto;\n        overflow-y: visible;" in wide_workspace
    wide_table_start = wide_workspace.index(
        ".recipe-edit-standalone-page .recipe-edit-ingredients-section .recipe-edit-ingredient-table-scroll {"
    )
    wide_table_end = wide_workspace.index("}", wide_table_start)
    wide_table_rule = wide_workspace[wide_table_start:wide_table_end]
    assert "overscroll-behavior-inline: contain;" in wide_table_rule
    assert "overscroll-behavior-block: auto;" in wide_table_rule
    assert "overscroll-behavior: contain;" not in wide_table_rule
    ingredient_polish = wide_workspace[wide_workspace.index("/* Ingredient editor v7:"):]
    assert ".recipe-edit-standalone-page .recipe-edit-tab-list," in ingredient_polish
    assert ".recipe-edit-standalone-page .recipe-edit-ingredient-table-head {\n    position: static;" in ingredient_polish
    assert "top: auto;" in ingredient_polish
    assert "z-index: auto;" in ingredient_polish
    sticky_headers = wide_workspace[wide_workspace.index("/* Ingredient editor v65:"):]
    assert "#recipeEditPanelIngredients\n    > .ingredients-toolbar {" in sticky_headers
    assert "position: sticky;" in sticky_headers
    assert "z-index: 36;" in sticky_headers
    assert "top: var(--recipe-edit-ingredients-toolbar-sticky-top, 66px);" in sticky_headers
    assert "margin-bottom: 0;" in sticky_headers
    assert "border-bottom: 0;" in sticky_headers
    assert "background: var(--recipe-editor-surface);" in sticky_headers
    assert "box-shadow: none;" in sticky_headers
    assert (
        "body.recipe-edit-standalone-page\n"
        "    .recipe-edit-ingredients-section\n"
        "    .recipe-edit-ingredient-table-scroll {\n"
        "    overflow: visible;"
    ) in sticky_headers
    assert (
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-table-body-scroll {"
        in sticky_headers
    )
    assert "overflow-x: auto;" in sticky_headers
    assert "@media (min-width: 768px)" in sticky_headers
    assert (
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-table-head-viewport {"
        in sticky_headers
    )
    assert "z-index: 35;" in sticky_headers
    assert "top: var(--recipe-edit-ingredient-table-sticky-top, 113px);" in sticky_headers
    assert "background: var(--recipe-editor-surface-soft);" in sticky_headers
    ingredient_tools = script[
        script.index("function organizeRecipeEditIngredientTools()"):
        script.index("function organizeRecipeEditEquipmentTools()")
    ]
    assert '"recipe-edit-ingredient-table-head-viewport"' in ingredient_tools
    assert '"recipe-edit-ingredient-table-body-scroll"' in ingredient_tools
    assert "tableHeadViewport.appendChild(tableHead);" in ingredient_tools
    assert "tableBodyScroll.appendChild(ingredientList);" in ingredient_tools
    assert "syncRecipeEditIngredientTableHeaderScroll(tableScroll);" in ingredient_tools
    assert "headerViewport.scrollLeft = bodyScroll.scrollLeft;" in script
    sticky_offsets = script[
        script.index("function updateRecipeEditStickyOffsets()"):
        script.index("function setValue(", script.index("function updateRecipeEditStickyOffsets()"))
    ]
    assert '"body.recipe-edit-standalone-page #recipeEditPanelIngredients"' in sticky_offsets
    assert '":scope > .ingredients-toolbar"' in sticky_offsets
    assert '"body.recipe-edit-standalone-page .recipe-edit-header"' in sticky_offsets
    assert '["fixed", "sticky"].includes(editorHeaderStyle.position)' in sticky_offsets
    assert "ingredientsToolbar.offsetHeight" in sticky_offsets
    assert "ingredientsToolbarStyle" not in sticky_offsets
    assert '"--recipe-edit-ingredients-toolbar-sticky-top"' in sticky_offsets
    assert '"--recipe-edit-ingredient-table-sticky-top"' in sticky_offsets


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
