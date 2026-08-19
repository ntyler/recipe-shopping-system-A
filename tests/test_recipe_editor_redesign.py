import json
import re
import shutil
import subprocess
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


def test_add_tag_button_is_borderless_until_hover_with_keyboard_focus_ring():
    css = read_text("PushShoppingList/static/css/app.css")
    base_selector = ".recipe-edit-standalone-page .recipe-edit-tag-add {"
    hover_selector = ".recipe-edit-standalone-page .recipe-edit-tag-add:hover {"
    focus_selector = ".recipe-edit-standalone-page .recipe-edit-tag-add:focus-visible {"

    base_start = css.index(base_selector)
    base_rule = css[base_start:css.index("}", base_start)]
    hover_start = css.index(hover_selector)
    hover_rule = css[hover_start:css.index("}", hover_start)]
    focus_start = css.index(focus_selector)
    focus_rule = css[focus_start:css.index("}", focus_start)]

    assert "border-color: transparent;" in base_rule
    assert "border-color: var(--app-border);" in hover_rule
    assert "outline: 2px solid var(--app-focus);" in focus_rule
    assert "outline-offset: 2px;" in focus_rule
    assert ".recipe-edit-tag-clear" not in base_rule + hover_rule + focus_rule


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
    assert 'detailsHeading.textContent = "Recipe Details"' in organizer
    assert 'classificationHeading.textContent = "Classification"' in organizer
    assert 'descriptionRow.className = "recipe-edit-description-row"' in organizer
    assert "[servingsField, totalField, prepField, cookField, inactiveField, levelField, scaleField]" in organizer
    assert 'setRecipeEditFieldLabel(levelField, "Difficulty")' in organizer
    assert 'setRecipeEditFieldLabel(scaleField, "Scale")' in organizer
    assert 'setRecipeEditFieldLabel(priceField, "Menu Price (optional)")' in organizer
    assert 'setRecipeEditFieldLabel(cuisineCategoryField, "Cuisine Categories")' in organizer
    assert 'heading.className = "recipe-edit-metadata-heading"' in script
    assert 'data-recipe-metadata-icon="servings"' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("utensils")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert 'shell.svg_icon("cooking-pot")' in read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    assert "data-recipe-edit-multiselect-chips" in script
    assert "renderRecipeEditCuisineChips" in script
    assert "recipe-edit-price-control" in organizer
    assert template.count('class="recipe-edit-price-control recipe-edit-cookbook-value"') == 1
    assert 'id="recipeEditMenuPriceCurrency"' in template
    assert 'id="recipeEditMenuPriceCurrencyTrigger"' in template
    assert 'aria-label="Menu price currency, $ USD, US Dollar"' in template
    assert 'aria-haspopup="listbox"' in template
    assert 'data-recipe-edit-currency-code>USD</span>' in template
    assert 'data-recipe-edit-currency-search' in template
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
    assert "detailsSection," in organizer
    assert "categoriesPanel," in organizer
    assert "tagRow" not in organizer
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
    assert "display: flex;" in price_styles
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
    assert ".recipe-edit-info-panel .recipe-edit-detail-field > .recipe-edit-cookbook-value" in hierarchy_css
    assert 'class="recipe-edit-file-field recipe-edit-cookbook-field recipe-edit-detail-field"' in template
    assert 'class="recipe-edit-cookbook-label">Menu Price</span>' in template
    assert 'class="recipe-edit-price-control recipe-edit-cookbook-value"' in template


def test_recipe_summary_selectors_share_accessible_state_feedback():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Summary selector fields use the Cookbook field structure and state feedback. */"
    controls = css[css.index(marker):css.index(
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized .recipe-edit-description-row {",
        css.index(marker),
    )]

    shared_value_selector = (
        ".recipe-edit-info-panel .recipe-edit-detail-field > "
        ".recipe-edit-cookbook-value"
    )
    assert shared_value_selector in controls
    assert "> .recipe-edit-cookbook-value" in controls
    assert "> .recipe-edit-cookbook-value:focus-within" in controls
    assert '.recipe-edit-cookbook-select[aria-expanded="true"]' in controls
    assert '.recipe-edit-price-currency[aria-expanded="true"]' in controls
    assert ".recipe-edit-cookbook-select:disabled" in controls
    assert "#recipeEditMenuPrice:disabled" in controls

    for declaration in (
        "border-color: transparent;",
        "background: transparent;",
        "transition: border-color 140ms ease, box-shadow 140ms ease;",
        "border-color: var(--app-primary-hover);",
        "box-shadow: 0 0 0 2px color-mix(in srgb, var(--app-primary-hover) 34%, transparent);",
        "outline: 2px solid var(--app-focus);",
        "outline-offset: 2px;",
    ):
        assert declaration in controls

    assert "background: var(--app-surface-soft);" not in controls

    for hover_declaration in (
        "border-color: color-mix(in srgb, var(--app-primary-hover) 72%, var(--app-border-strong));",
        "box-shadow: 0 0 0 1px color-mix(in srgb, var(--app-primary-hover) 18%, transparent);",
    ):
        assert controls.count(hover_declaration) == 1

    cookbook_value_start = css.index(".recipe-edit-cookbook-value {")
    cookbook_value_rule = css[cookbook_value_start:css.index("}", cookbook_value_start)]
    for shared_declaration in (
        "width: 100%;",
        "min-height: 40px;",
        "padding: 0;",
        "border: 1px solid #263447;",
        "border-radius: 7px;",
    ):
        assert shared_declaration in cookbook_value_rule

    assert ".recipe-edit-price-control:hover:not(:focus-within)" not in controls
    assert ".recipe-edit-price-control:focus-within:not(:has(" not in controls
    assert ".recipe-edit-price-control:has(#recipeEditMenuPrice:disabled)" not in controls
    assert ".recipe-edit-price-control:has(" in controls


def test_recipe_detail_fields_use_bounded_accessible_controls():
    css = read_text("PushShoppingList/static/css/app.css")
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    assert 'id="recipeEditServingsCount"' in template
    assert 'min="1"' in template
    assert 'step="1"' in template
    assert 'aria-label="Decrease servings"' in template
    assert 'aria-label="Increase servings"' in template
    assert '<span class="recipe-edit-servings-value">' in template
    assert '<span class="recipe-edit-servings-unit" aria-hidden="true">servings</span>' in template
    assert 'class="recipe-edit-scale-control recipe-edit-metadata-value"' in template
    assert '<input type="text"\n                                   name="scaling_multiplier"' in template
    assert 'inputmode="decimal"' in template
    assert 'aria-label="Scale multiplier"' in template
    assert 'aria-describedby="recipeEditScaleError"' in template
    assert "recipe-edit-scale-suffix" not in template
    assert "&times;" not in template
    assert 'data-recipe-edit-scale-preset' not in template
    assert 'data-recipe-edit-scale-segments' not in template
    assert ".recipe-edit-servings-stepper" in styles
    assert ".recipe-edit-scale-control" in styles
    assert ".recipe-edit-scale-segments" not in styles
    assert "border: 1px solid var(--app-border-strong);" in styles
    assert "flex: 1 1 auto;" in styles
    assert "outline: 2px solid color-mix" in styles
    assert ".recipe-edit-total-time-field #recipeEditTotalTime" in styles
    assert "font-size: 13px;" in styles
    assert ".recipe-edit-total-time-status" in styles
    assert ".recipe-edit-detail-field:has(:is(#recipeEditTotalTime, #recipeEditLevel))" in styles
    assert "field-sizing: content;" in styles
    assert "flex: 0 1 auto;" in styles
    assert "min-width: 72px;" in styles
    assert "max-width: 170px;" in styles


def test_recipe_select_chevrons_are_contextual_on_desktop_and_persistent_on_touch():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    assert (
        "[levelField, mealTypeField, mainIngredientField, cookingMethodField, occasionField]"
        in organizer
    )
    assert 'classList.add("recipe-edit-contextual-select-field")' in organizer
    assert ".recipe-edit-contextual-select-field .recipe-edit-metadata-value > select" in styles
    assert "appearance: none;" in styles
    assert "padding-right: 50px;" in styles
    assert ".recipe-edit-contextual-select-field .recipe-edit-metadata-value::after" in styles
    assert "pointer-events: none;" in styles
    assert "transition: opacity 140ms ease;" in styles
    assert "@media (hover: hover) and (pointer: fine)" in styles
    assert "opacity: 0;" in styles
    assert ".recipe-edit-metadata-value:is(:hover, :focus-within)::after" in styles
    assert ".recipe-edit-metadata-value:has(> select:open)::after" in styles


def test_requested_labels_highlight_only_their_associated_control_surface():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    for association in (
        '[servingsField, servingsField?.querySelector(".recipe-edit-servings-stepper")]',
        '[scaleField, scaleField?.querySelector(".recipe-edit-scale-control")]',
        '[totalField, document.getElementById("recipeEditTotalTime")]',
        '[cuisineCategoryField, cuisineCategoryField?.querySelector(".recipe-edit-multiselect-control")]',
        '[dietaryPreferenceField, dietaryPreferenceField?.querySelector(".recipe-edit-multiselect-control")]',
        '[customCategoriesField, customCategoriesField?.querySelector(".recipe-edit-multiselect-control")]',
    ):
        assert association in organizer
    assert 'classList.add("recipe-edit-label-control-highlight-field")' in organizer
    assert 'classList.add("recipe-edit-label-control-highlight-target")' in organizer
    assert ".recipe-edit-label-control-highlight-target {" in styles
    assert ".recipe-edit-metadata-tooltip-label-trigger:is(:hover, :focus-visible)" in styles
    assert ".recipe-edit-label-control-highlight-target:is(:hover, :active)" in styles
    assert ".recipe-edit-label-control-highlight-field.is-open" in styles
    assert ".recipe-edit-label-control-highlight-field:focus-within" in styles
    assert "border-color: var(--app-primary-hover);" in styles
    assert "box-shadow: inset 0 0 0 1px transparent;" in styles
    assert "0 0 0 2px color-mix(in srgb, var(--app-primary-hover) 24%, transparent);" in styles


def test_requested_recipe_detail_inputs_size_to_their_content():
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]
    target_ids = {
        "recipeEditServingsCount",
        "recipeEditScaleMultiplier",
        "recipeEditPrepTime",
        "recipeEditCookTime",
        "recipeEditInactiveTime",
    }
    content_sized_ids = {
        field_id
        for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", styles)
        if "field-sizing: content;" in declarations and "width: auto;" in declarations
        for field_id in target_ids
        if f"#{field_id}" in selectors
    }

    assert content_sized_ids == target_ids
    assert ".recipe-edit-details-primary-grid .recipe-edit-servings-stepper" in styles
    assert ".recipe-edit-details-primary-grid .recipe-edit-scale-control" in styles
    assert styles.count("width: fit-content;") >= 2
    assert "min-width: 72px;" in styles
    assert "max-width: 170px;" in styles
    assert "function resizeRecipeEditContentSizedInput(input)" in script
    assert 'window.CSS.supports("field-sizing", "content")' in script
    assert "function bindRecipeEditContentSizing()" in script
    assert "bindRecipeEditContentSizing();" in script


def test_recipe_content_sizing_fallback_measures_and_bounds_width():
    node = shutil.which("node")
    if not node:
        return
    script = read_text("PushShoppingList/static/js/app.js")
    helper = script[
        script.index("const RECIPE_EDIT_CONTENT_SIZED_INPUT_SELECTOR"):
        script.index("function recipeEditServingsParts")
    ]
    harness = r'''
const inputStyle = {
    width: "",
    removeProperty(name) { if (name === "width") this.width = ""; },
};
const input = {
    value: "1",
    placeholder: "",
    style: inputStyle,
    matches() { return true; },
};
let standaloneEditorActive = true;
function recipeEditorStandalonePageIsActive() { return standaloneEditorActive; }
const computedStyle = {
    font: "700 13px Arial",
    letterSpacing: "normal",
    paddingLeft: "10px",
    paddingRight: "38px",
    borderLeftWidth: "0px",
    borderRightWidth: "0px",
    minWidth: "64px",
    maxWidth: "170px",
};
const window = {
    CSS: { supports() { return false; } },
    getComputedStyle() { return computedStyle; },
};
const document = {
    createElement() {
        return {
            getContext() {
                return {
                    font: "",
                    measureText(text) { return { width: text.length * 8 }; },
                };
            },
        };
    },
};
''' + helper + r'''
resizeRecipeEditContentSizedInput(input);
const shortWidth = input.style.width;
input.value = "123456789012345";
resizeRecipeEditContentSizedInput(input);
const longWidth = input.style.width;
standaloneEditorActive = false;
input.value = "1";
resizeRecipeEditContentSizedInput(input);
const legacyModalWidth = input.style.width;
standaloneEditorActive = true;
window.CSS.supports = () => true;
resizeRecipeEditContentSizedInput(input);
process.stdout.write(JSON.stringify({ shortWidth, longWidth, legacyModalWidth, nativeWidth: input.style.width }));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "shortWidth": "64px",
        "longWidth": "170px",
        "legacyModalWidth": "170px",
        "nativeWidth": "",
    }


def test_recipe_metadata_strip_uses_equal_responsive_columns_without_internal_separators():
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
        "display: grid;",
        "grid-template-columns: repeat(4, minmax(0, 1fr));",
        "align-items: stretch;",
        "gap: 16px;",
        "border: 0;",
        "border-radius: 0;",
        "outline: 0;",
        "background: transparent;",
        "box-shadow: none;",
    ):
        assert declaration in strip_rule

    metric_rule_start = css.index(
        f"{strip_selector[:-1]}> label,",
        strip_start,
    )
    metric_rule = css[metric_rule_start : css.index("}", metric_rule_start)]
    assert "width: 100%;" in metric_rule
    assert "min-height: 84px;" in metric_rule
    assert "justify-items: start;" in metric_rule
    assert "text-align: left;" in metric_rule
    assert "border: 0;" in metric_rule

    medium_start = css.index("@media (max-width: 1099px)", strip_start)
    medium_rule_start = css.index(strip_selector, medium_start)
    medium_rule = css[medium_rule_start : css.index("}", medium_rule_start)]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in medium_rule

    narrow_start = css.index("@media (max-width: 767px)", medium_rule_start)
    narrow_rule_start = css.index(strip_selector, narrow_start)
    narrow_rule = css[narrow_rule_start : css.index("}", narrow_rule_start)]
    assert "grid-template-columns: minmax(0, 1fr);" in narrow_rule

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


def test_recipe_metadata_controls_are_full_width_left_aligned_and_untruncated():
    css = read_text("PushShoppingList/static/css/app.css")
    phase_two_start = css.index(
        "/* Phase 2 recipe editor redesign using the AI Pantry shell tokens. */"
    )
    styles = css[phase_two_start:]

    value_start = styles.index(".recipe-edit-metadata-value {")
    value_rule = styles[value_start:styles.index("}", value_start)]
    assert "width: 100%;" in value_rule
    assert "justify-content: flex-start;" in value_rule
    assert "text-align: left;" in value_rule

    control_start = styles.index(".recipe-edit-metadata-value :is(input, select) {")
    control_rule = styles[control_start:styles.index("}", control_start)]
    for declaration in (
        "width: 100%;",
        "max-width: none;",
        "min-height: 36px;",
        "text-align: left;",
    ):
        assert declaration in control_rule

    input_start = styles.index(".recipe-edit-metadata-value input {")
    input_rule = styles[input_start:styles.index("}", input_start)]
    assert "width: 80px;" in input_rule
    assert "max-width: 100%;" in input_rule
    assert "flex: 0 1 80px;" in input_rule

    category_marker = "/* Edit Recipe: inline category metadata and reusable custom-category tags. */"
    category_styles = css[css.index(category_marker):]
    select_start = category_styles.rindex(
        ".recipe-edit-category-metadata-strip .recipe-edit-metadata-value select {"
    )
    select_rule = category_styles[select_start:category_styles.index("}", select_start)]
    assert "overflow: visible;" in select_rule
    assert "text-overflow: clip;" in select_rule
    assert "white-space: normal;" in select_rule
    assert "ellipsis" not in select_rule


def test_recipe_details_match_classification_layout_and_field_order():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    assert 'detailsHeading.textContent = "Recipe Details"' in organizer
    assert 'detailsHeadingRow.className = "recipe-edit-form-section-heading"' in organizer
    assert "appendRecipeEditWorkspaceChildren(detailsHeadingRow, [detailsHeading, detailsMenu])" in organizer
    assert 'detailsMenuButton.setAttribute("aria-label", "Recipe detail actions")' in organizer
    assert 'onclick="return toggleRecipeEditSectionMenu(this, event)"' in template
    assert 'timeBreakdownGroup.id = "recipeEditTimeBreakdown"' in organizer
    assert 'timeBreakdownGroup.setAttribute("role", "group")' in organizer
    assert (
        "appendRecipeEditWorkspaceChildren(timeBreakdownGroup, "
        "[prepField, cookField, inactiveField])"
    ) in organizer
    assert "[servingsField, scaleField, totalField, timeBreakdownGroup, levelField]" in organizer
    assert 'addRecipeEditMetadataIcon(totalField, "total")' not in organizer
    assert 'data-recipe-metadata-icon="total"' not in template
    assert "totalTimeLabel.insertAdjacentElement(\"afterend\", timeBreakdownToggle)" in organizer
    assert "setRecipeEditTimeBreakdownExpanded(loadRecipeEditTimeBreakdownExpanded())" in organizer
    assert '<label for="recipeEditTotalTime">Total</label>' in template
    assert "recipeEditCookingDetailsPanel" not in organizer
    assert '"More cooking details"' not in organizer
    assert "recipe-edit-scale-disclosure" not in organizer
    assert "syncRecipeEditTotalTimeStatus" in organizer
    assert ".recipe-edit-details-primary-grid" in styles
    assert ".recipe-edit-details-secondary-grid" not in styles
    assert ".recipe-edit-scale-disclosure" not in styles
    assert ".recipe-edit-optional-details" not in styles
    primary_grid_start = styles.index(
        ".recipe-edit-details-primary-grid {"
    )
    primary_grid_rule = styles[
        primary_grid_start:styles.index("}", primary_grid_start)
    ]
    assert "minmax(145px, 1.25fr)" in primary_grid_rule
    assert "minmax(72px, .65fr)" in primary_grid_rule
    assert "repeat(4, minmax(88px, 1fr))" in primary_grid_rule
    assert "minmax(112px, 1fr)" in primary_grid_rule
    assert "width: min(100%, 960px);" in styles
    assert (
        "grid-template-columns: minmax(180px, 220px) repeat(2, minmax(260px, 320px));"
        in styles
    )
    assert "row-gap: 22px;" in styles
    assert "column-gap: clamp(32px, 2vw, 40px);" in styles
    assert "column-gap: clamp(24px, 1.7vw, 32px);" in primary_grid_rule
    assert "gap: 8px;" in styles
    assert ".recipe-edit-details-primary-grid .recipe-edit-metadata-heading" in styles
    assert "min-height: 22px;" in styles

    collapsed_rules = re.findall(
        r"\.recipe-edit-details-primary-grid\.recipe-edit-time-breakdown-collapsed\s*\{([^{}]*)\}",
        styles,
    )
    assert len(collapsed_rules) >= 5
    assert any(
        "grid-template-columns: repeat(4, minmax(0, 1fr));" in rule
        for rule in collapsed_rules
    )
    assert sum(
        "grid-template-columns: repeat(2, minmax(0, 1fr));" in rule
        for rule in collapsed_rules
    ) >= 1
    assert sum(
        "grid-template-columns: minmax(0, 1fr);" in rule
        for rule in collapsed_rules
    ) >= 2


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
    setter = script[
        script.index("function setRecipeEditTimeBreakdownExpanded"):
        script.index("function createRecipeEditTimeBreakdownControl")
    ]

    assert 'button.type = "button"' in control
    assert 'button.setAttribute("aria-expanded", "true")' in control
    assert 'button.setAttribute("aria-controls", "recipeEditTimeBreakdown")' in control
    assert 'button.setAttribute("aria-label", "Hide detailed cooking times")' in control
    assert 'class="recipe-edit-time-breakdown-chevron" aria-hidden="true"' in control
    assert 'button.addEventListener("click"' in control
    assert 'button.setAttribute("aria-expanded", String(isExpanded))' in disclosure
    assert '`${isExpanded ? "Hide" : "Show"} detailed cooking times`' in disclosure
    assert 'timeBreakdownGroup.id = "recipeEditTimeBreakdown"' in organizer
    assert 'timeBreakdownGroup.setAttribute("role", "group")' in organizer
    assert 'timeBreakdownGroup.setAttribute("aria-label", "Detailed cooking times")' in organizer
    assert (
        "appendRecipeEditWorkspaceChildren(timeBreakdownGroup, "
        "[prepField, cookField, inactiveField])"
    ) in organizer
    assert "recipe-edit-time-breakdown-collapsed" in disclosure
    assert "group.hidden = !isExpanded" in disclosure
    assert ".value" not in setter

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
    assert ".recipe-edit-time-breakdown-group > .recipe-edit-detail-field" in css
    assert ".recipe-edit-details-primary-grid.recipe-edit-time-breakdown-collapsed" in css


def test_recipe_time_breakdown_toggle_preserves_values_and_calculation():
    node = shutil.which("node")
    if not node:
        return
    script = read_text("PushShoppingList/static/js/app.js")
    behavior = script[
        script.index("function recipeEditTimeBreakdownStorageKey()"):
        script.index("function bindRecipeEditNameInput")
    ]
    harness = r'''
const storage = new Map();
const listeners = {};
const attributes = new Map();
const activeClasses = new Set();
const values = {
    recipeEditPrepTime: { value: "15 min" },
    recipeEditCookTime: { value: "45 min" },
    recipeEditInactiveTime: { value: "20 min" },
    recipeEditTotalTime: { value: "1 hr 20 min" },
};
const grid = {
    classList: {
        toggle(name, force) {
            if (force) activeClasses.add(name);
            else activeClasses.delete(name);
        },
        contains(name) { return activeClasses.has(name); },
    },
};
const group = {
    hidden: false,
    closest(selector) {
        return selector === ".recipe-edit-details-primary-grid" ? grid : null;
    },
};
const button = {
    type: "",
    className: "",
    dataset: {},
    id: "",
    innerHTML: "",
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.get(name) || null; },
    addEventListener(name, listener) { listeners[name] = listener; },
};
const document = {
    body: { dataset: { userId: "qa-user" } },
    createElement(tag) {
        if (tag !== "button") throw new Error(`Unexpected element: ${tag}`);
        return button;
    },
    querySelector(selector) {
        return selector === "[data-recipe-edit-time-breakdown-toggle]" ? button : null;
    },
    getElementById(id) {
        if (id === "recipeEditTimeBreakdown") return group;
        return values[id] || null;
    },
};
const window = {
    localStorage: {
        getItem(key) { return storage.has(key) ? storage.get(key) : null; },
        setItem(key, value) { storage.set(key, String(value)); },
    },
};
const RECIPE_EDIT_TIME_BREAKDOWN_STORAGE_KEY = "ai-pantry:recipe-editor:time-breakdown:v1";
''' + behavior + r'''
const control = createRecipeEditTimeBreakdownControl();
const cookingValues = () => [
    values.recipeEditPrepTime.value,
    values.recipeEditCookTime.value,
    values.recipeEditInactiveTime.value,
];
const initial = {
    expanded: control.getAttribute("aria-expanded"),
    label: control.getAttribute("aria-label"),
    hidden: group.hidden,
    values: cookingValues(),
};
listeners.click();
const collapsed = {
    expanded: control.getAttribute("aria-expanded"),
    label: control.getAttribute("aria-label"),
    hidden: group.hidden,
    compact: grid.classList.contains("recipe-edit-time-breakdown-collapsed"),
    values: cookingValues(),
};
listeners.click();
const reopened = {
    expanded: control.getAttribute("aria-expanded"),
    label: control.getAttribute("aria-label"),
    hidden: group.hidden,
    compact: grid.classList.contains("recipe-edit-time-breakdown-collapsed"),
    values: cookingValues(),
};
process.stdout.write(JSON.stringify({
    type: control.type,
    controls: control.getAttribute("aria-controls"),
    initial,
    collapsed,
    reopened,
    totalMinutes: calculateRecipeEditTimeBreakdownMinutes(),
    totalValue: values.recipeEditTotalTime.value,
    savedState: storage.get("ai-pantry:recipe-editor:time-breakdown:v1:qa-user"),
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "type": "button",
        "controls": "recipeEditTimeBreakdown",
        "initial": {
            "expanded": "true",
            "label": "Hide detailed cooking times",
            "hidden": False,
            "values": ["15 min", "45 min", "20 min"],
        },
        "collapsed": {
            "expanded": "false",
            "label": "Show detailed cooking times",
            "hidden": True,
            "compact": True,
            "values": ["15 min", "45 min", "20 min"],
        },
        "reopened": {
            "expanded": "true",
            "label": "Hide detailed cooking times",
            "hidden": False,
            "compact": False,
            "values": ["15 min", "45 min", "20 min"],
        },
        "totalMinutes": 80,
        "totalValue": "1 hr 20 min",
        "savedState": "expanded",
    }


def test_recipe_classification_rows_render_without_optional_disclosure():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    assert 'id: "recipeEditCookingDetailsPanel"' not in organizer
    assert 'id: "recipeEditClassificationDetailsPanel"' not in organizer
    assert "createRecipeEditOptionalDetails" not in script
    assert "More classification details" not in organizer
    assert "classificationSecondaryRow," in organizer
    assert organizer.index("classificationPrimaryRow,") < organizer.index("classificationSecondaryRow,")
    assert ".recipe-edit-optional-details" not in styles


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
    assert "syncRecipeEditTotalTimeStatus();" in calculation
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
    organizer = script[
        script.index("function organizeRecipeEditInformationCard()"):
        script.index("function organizeRecipeEditAiAssistant()")
    ]
    attached = organizer.index("grid.replaceChildren()")
    bound = organizer.index("bindRecipeEditTotalTimeCalculation()", attached)
    assert attached < bound
    assert 'return `${rounded} min`' in calculation
    assert '`${hours} hr ${remainingMinutes} min`' in calculation


def test_recipe_total_time_calculation_formats_component_sum():
    node = shutil.which("node")
    if not node:
        return
    script = read_text("PushShoppingList/static/js/app.js")
    calculation = script[
        script.index("function parseRecipeEditDurationMinutes"):
        script.index("function bindRecipeEditNameInput")
    ]
    harness = r'''
const values = {
    recipeEditPrepTime: { value: "15 min" },
    recipeEditCookTime: { value: "45 min" },
    recipeEditInactiveTime: { value: "20 min" },
};
const document = { getElementById(id) { return values[id] || null; } };
''' + calculation + r'''
process.stdout.write(JSON.stringify({
    total: calculateRecipeEditTimeBreakdownMinutes(),
    formatted: formatRecipeEditDurationMinutes(calculateRecipeEditTimeBreakdownMinutes()),
    parsed: parseRecipeEditDurationMinutes("1 hr 20 min"),
}));
'''
    completed = subprocess.run(
        [node],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "total": 80,
        "formatted": "1 hr 20 min",
        "parsed": 80,
    }


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
        "Servings": "Number of people or portions the base recipe serves. Scale does not change this saved value.",
        "Total Time": "Total elapsed time from start to finish, typically including prep, cooking, and inactive time.",
        "Prep Time": "Hands-on preparation time.",
        "Cook Time": "Time the food is actively cooking.",
        "Inactive Time": "Hands-off waiting time, such as resting, marinating, chilling, rising, or cooling.",
        "Difficulty": "Overall complexity based on skill, steps, timing, and equipment.",
        "Scale": "Shopping multiplier and ingredient preview. It does not rewrite the recipe's saved Servings or base amounts.",
        "Custom Tags": "Add descriptive tags to organize recipes and improve searching. Select an existing tag or create a new one.",
    }
    for label, help_text in expected_tooltips.items():
        assert f'"{label}", "{help_text}"' in organizer

    assert "function addRecipeEditMetadataTooltip(field, label, helpText, options = {})" in script
    assert 'const labelTrigger = options.trigger === "label"' in script
    assert organizer.count('{ trigger: "label" }') == 2
    assert 'trigger.setAttribute("role", "button")' in script
    assert 'trigger.setAttribute("tabindex", "0")' in script
    assert 'trigger.setAttribute("aria-describedby", tooltipId)' in script
    assert 'control.setAttribute("aria-describedby", Array.from(describedBy).join(" "))' in script
    assert 'tooltip.setAttribute("role", "tooltip")' in script
    assert 'trigger.addEventListener("pointerenter"' in script
    assert 'trigger.addEventListener("focus"' in script
    assert 'trigger.addEventListener("click"' in script
    assert 'trigger.addEventListener("pointerdown"' in script
    assert 'event.key === "Enter" || event.key === " "' in script
    assert 'tooltip.addEventListener("pointerenter", cancelRecipeEditMetadataTooltipClose)' in script
    assert "const overlapsControlBelow = controlRect" in script
    for field_name, placement in (
        ("cuisine", "top-start"),
        ("dietary_preference", "top"),
        ("custom_categories", "top-start"),
    ):
        assert f'{field_name}: "{placement}"' in script
    assert 'field.closest(".recipe-edit-info-panel-organized")' in script
    assert '"input:not([type=\'hidden\']), select, .recipe-edit-multiselect-control"' in script
    assert "const boundaryPadding = 8;" in script
    assert "const aboveTop = triggerRect.top - gap - tooltipHeight;" in script
    assert "tooltip.dataset.recipeEditTooltipPlacement = resolvedPlacement;" in script
    assert 'document.addEventListener("pointerdown"' in script
    assert ".recipe-edit-metadata-tooltip-trigger:focus-visible" in css
    assert ".recipe-edit-metadata-tooltip-label-trigger {" in css
    assert "text-decoration-style: dotted;" in css
    assert "cursor: help;" in css
    assert ".recipe-edit-metadata-tooltip[hidden]" in css
    tooltip_trigger_rule = css[
        css.index(".recipe-edit-metadata-tooltip-trigger:not(.recipe-edit-metadata-tooltip-label-trigger) {"):
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
    assert "pointer-events: auto;" in css[css.index("body.recipe-edit-standalone-page .recipe-edit-metadata-tooltip {"):]


def test_recipe_details_and_classification_controls_are_transparent_until_active():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe details and classification: bounded responsive controls with consolidated tags. */"
    styles = css[css.index(marker):]

    shared_control_start = styles.index(
        ':is(input:not([type="hidden"]):not(.recipe-edit-multiselect-search), select),'
    )
    shared_control_rule = styles[
        shared_control_start:styles.index("}", shared_control_start)
    ]
    assert "background: transparent !important;" in shared_control_rule

    classification_select_start = styles.index(
        '> select:not([aria-invalid="true"]):not([data-recipe-edit-validation-invalid="true"]) {'
    )
    classification_select_rule = styles[
        classification_select_start:styles.index("}", classification_select_start)
    ]
    assert "background-color: transparent !important;" in classification_select_rule

    quiet_control_start = styles.index(
        ":is(.recipe-edit-servings-stepper, .recipe-edit-scale-control) {"
    )
    quiet_control_rule = styles[
        quiet_control_start:styles.index("}", quiet_control_start)
    ]
    assert "background-color: transparent;" in quiet_control_rule

    multiselect_selector = (
        "body.recipe-edit-standalone-page .recipe-edit-info-panel-organized "
        ".recipe-edit-multiselect-control {"
    )
    multiselect_start = styles.rindex(multiselect_selector)
    multiselect_rule = styles[multiselect_start:styles.index("}", multiselect_start)]
    assert "background: transparent !important;" in multiselect_rule
    assert "background-color: color-mix(in srgb, var(--app-primary-soft) 18%, transparent) !important;" in styles
    assert "background-color: color-mix(in srgb, var(--app-primary-soft) 24%, transparent) !important;" in styles


def test_recipe_editor_standard_fields_are_quiet_until_active():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Recipe workspace: keep standard fields quiet until they are active or invalid. */"
    targeted_summary_marker = (
        "/* Summary selector fields use the Cookbook field structure and state feedback. */"
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
    assert ".recipe-edit-price-control:not(.recipe-edit-cookbook-value):not(:focus-within):not(:has(" in quiet_fields
    price_hover_start = quiet_fields.index(".recipe-edit-price-control:not(.recipe-edit-cookbook-value):hover:not(:focus-within):not(:has(")
    price_hover_rule = quiet_fields[price_hover_start:quiet_fields.index("}", price_hover_start)]
    assert "border-color: transparent;" in price_hover_rule
    assert "box-shadow: none;" in price_hover_rule
    assert ".recipe-edit-price-control:not(.recipe-edit-cookbook-value):focus-within" in quiet_fields
    assert ".recipe-edit-price-control:has(" in quiet_fields
    assert "#recipeEditMenuPrice:is([aria-invalid=\"true\"], [data-recipe-edit-validation-invalid=\"true\"])" in quiet_fields


def test_recipe_category_fields_use_the_compact_metadata_visual_hierarchy():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Edit Recipe: inline category metadata and reusable custom-category tags. */"
    marker_start = css.index(marker)
    category_styles = css[marker_start:]

    section_start = category_styles.index(".recipe-edit-inline-categories {")
    section_rule = category_styles[section_start:category_styles.index("}", section_start)]
    assert "min-width: 0;" in section_rule
    assert "border: 0;" in section_rule

    row_start = category_styles.index(".recipe-edit-category-metadata-strip {")
    row_rule = category_styles[row_start:category_styles.index("}", row_start)]
    assert "margin-top: 0;" in row_rule
    assert "padding-top: 6px;" in row_rule

    select_start = category_styles.rindex(
        ".recipe-edit-category-metadata-strip .recipe-edit-metadata-value select {"
    )
    select_rule = category_styles[select_start:category_styles.index("}", select_start)]
    assert "overflow: visible;" in select_rule
    assert "text-overflow: clip;" in select_rule
    assert "white-space: normal;" in select_rule

    custom_start = category_styles.index(
        "> .recipe-edit-custom-categories-field {"
    )
    custom_rule = category_styles[custom_start:category_styles.index("}", custom_start)]
    assert "display: grid;" in custom_rule
    assert "min-width: 0;" in custom_rule
    assert "flex: 0 1 auto;" in custom_rule


def test_recipe_category_and_difficulty_values_align_with_calm_typography():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Edit Recipe: inline category metadata and reusable custom-category tags. */"
    category_styles = css[css.index(marker):]
    selector = (
        ".recipe-edit-category-metadata-strip .recipe-edit-category-metadata-field\n"
        "    .recipe-edit-metadata-value select {"
    )
    rule_start = category_styles.index(selector)
    rule = category_styles[rule_start:category_styles.index("}", rule_start)]

    for declaration in (
        "padding-left: 20px;",
        "font-size: 12px;",
        "font-weight: 600;",
    ):
        assert declaration in rule

    assert ".recipe-edit-metadata-value #recipeEditLevel," in category_styles[:rule_start]


def test_mobile_recipe_category_fields_wrap_without_horizontal_overflow():
    css = read_text("PushShoppingList/static/css/app.css")
    marker = "/* Edit Recipe: inline category metadata and reusable custom-category tags. */"
    category_styles = css[css.index(marker):]
    mobile = category_styles[category_styles.index("@media (max-width: 767px)"):]

    row_start = mobile.index(".recipe-edit-category-metadata-strip {")
    row_rule = mobile[row_start:mobile.index("}", row_start)]
    assert "gap: 16px;" in row_rule

    custom_start = mobile.index(".recipe-edit-custom-category-tag-row {")
    custom_rule = mobile[custom_start:mobile.index("}", custom_start)]
    assert "align-items: flex-start;" in custom_rule
    assert "padding-inline: 0;" in custom_rule

    assert "@media (max-width: 380px)" not in category_styles


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
    assert "open>" not in card
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

    assert "Recipe workspace v3: editor content follows the shared shell tokens" in css
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
    assert '--recipe-editor-bg: #101415;' in css
    assert ".recipe-edit-ingredient-row label.recipe-edit-section-label" in css
    assert ".recipe-edit-substitution-row-menu:not([hidden])" in css
    assert "@media (max-width: 1499px)" in css
    assert "@media (max-width: 767px)" in css


def test_recipe_editor_uses_the_recipes_page_card_visual_system_in_both_themes():
    css = read_text("PushShoppingList/static/css/app.css")
    v15_start = css.index("/* Recipe workspace v15: accepted two-column Edit Recipe mockup. */")
    v16_start = css.index("/* Recipe workspace v16: native-zoom readability and container-aware context rail. */")
    workspace = css[v15_start:v16_start]

    theme_start = workspace.index(
        "body.recipe-edit-standalone-page :is(\n"
        "    .recipe-edit-standalone-shell,\n"
        "    .recipe-edit-floating-menu,\n"
        "    .recipe-edit-ingredient-action-tooltip"
    )
    theme_rule = workspace[theme_start:workspace.index("}", theme_start)]
    for declaration in (
        "--app-text-soft: color-mix(in srgb, var(--app-text) 76%, var(--app-bg));",
        "--recipe-editor-bg: #f8faf9;",
        "--recipe-editor-surface: #ffffff;",
        "--recipe-editor-border: #dfe6e2;",
        "--recipe-editor-border-soft: #e8eeeb;",
        "color-scheme: inherit;",
    ):
        assert declaration in theme_rule

    dark_theme_start = workspace.index(
        'html[data-public-auth-theme="dark"] body.recipe-edit-standalone-page :is('
    )
    dark_theme_rule = workspace[dark_theme_start:workspace.index("}", dark_theme_start)]
    for declaration in (
        "--recipe-editor-bg: #101415;",
        "--recipe-editor-surface: #171c1e;",
        "--recipe-editor-surface-soft: #1c2325;",
        "--recipe-editor-border: #343b3d;",
        "--recipe-editor-border-soft: #2a3234;",
        "--submenu-bg: #171c1e;",
        "--submenu-text: #e7eae8;",
    ):
        assert declaration in dark_theme_rule

    assert 'html:not([data-public-auth-theme="light"]) body.recipe-edit-standalone-page :is(' in workspace
    assert "Keep editor content color-locked" not in css

    for declaration in (
        "--submenu-bg: #ffffff;",
        "--submenu-border: #dfe6e2;",
        "--submenu-divider: #e8eeeb;",
        "--submenu-text: #17233a;",
    ):
        assert declaration in theme_rule

    shell_start = workspace.index(
        "body.recipe-edit-standalone-page .recipe-edit-standalone-shell {",
        theme_start,
    )
    shell_rule = workspace[shell_start:workspace.index("}", shell_start)]
    assert "background: var(--recipe-editor-bg);" in shell_rule
    assert "color: var(--app-text);" in shell_rule

    card_start = workspace.index(
        "body.recipe-edit-standalone-page :is(\n"
        "    .recipe-edit-info-panel,\n"
        "    .recipe-edit-tabs-card,\n"
        "    .recipe-edit-context-card,\n"
        "    .recipe-edit-ai-assistant-card"
    )
    card_rule = workspace[card_start:workspace.index("}", card_start)]
    for declaration in (
        "border: 1px solid var(--recipe-editor-border);",
        "border-radius: 12px;",
        "background: var(--recipe-editor-surface);",
        "color: var(--app-text);",
        "box-shadow: 0 1px 2px rgba(16, 29, 49, .02);",
    ):
        assert declaration in card_rule
    assert "linear-gradient" not in card_rule
    assert "0 10px 30px" not in card_rule

    categories_start = workspace.index(
        "body.recipe-edit-standalone-page .recipe-edit-categories-panel {"
    )
    categories_rule = workspace[categories_start:workspace.index("}", categories_start)]
    assert "background: var(--recipe-editor-surface);" in categories_rule
    assert "box-shadow: 0 1px 2px rgba(16, 29, 49, .02);" in categories_rule

    view_menu_start = workspace.index(
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-view-menu {"
    )
    view_menu_rule = workspace[view_menu_start:workspace.index("}", view_menu_start)]
    assert "background: var(--recipe-editor-surface);" in view_menu_rule
    assert "color: var(--app-text);" in view_menu_rule
    assert "linear-gradient" not in view_menu_rule

    assert (
        "body.recipe-edit-standalone-page .recipe-edit-ingredient-action-tooltip {"
        in workspace
    )
    assert (
        "body.recipe-edit-standalone-page .recipe-edit-standalone-shell :is(\n"
        "    input,\n"
        "    select,\n"
        "    textarea,\n"
        "    button\n"
        "):disabled {"
        in workspace
    )
    assert "opacity: 1 !important;" in workspace


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
