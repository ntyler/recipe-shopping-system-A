from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shopping_list_has_global_collapse_controls():
    index_template = read_text("PushShoppingList/templates/index.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "data-global-collapse-controls" in index_template
    assert "Collapse All" in index_template
    assert "Expand All" in index_template
    assert "onclick=\"return collapseAllShoppingListPage()\"" in index_template
    assert "onclick=\"return expandAllShoppingListPage()\"" in index_template
    assert "data-global-collapse-status" in index_template
    assert "aria-live=\"polite\"" in index_template
    assert ".shopping-global-collapse-controls" in css
    assert ".shopping-global-collapse-btn" in css
    assert ".shopping-global-collapse-status" in css
    assert "@media (max-width: 650px)" in css

    actions_start = css.index(".shopping-global-collapse-actions {")
    actions_end = css.index(".shopping-global-collapse-btn {", actions_start)
    actions_css = css[actions_start:actions_end]
    assert "display: grid;" in actions_css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in actions_css
    assert "gap: 10px;" in actions_css

    button_start = css.index(".shopping-global-collapse-btn {")
    button_end = css.index(".shopping-global-collapse-btn.secondary", button_start)
    button_css = css[button_start:button_end]
    assert "width: 100%;" in button_css
    assert "height: 32px;" in button_css
    assert "min-height: 32px;" in button_css
    assert "padding: 2px 12px;" in button_css
    assert "font-family: inherit;" in button_css
    assert "font-size: 13px;" in button_css
    assert "line-height: 1.1;" in button_css
    assert "min-height: 44px;" not in button_css
    assert "font-weight: 850;" not in button_css


def test_global_collapse_action_targets_page_sections_and_nested_panels():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    assert "function collapseAllShoppingListPage()" in script
    assert "function expandAllShoppingListPage()" in script
    assert "function setAllCardCollapseContentCollapsed(collapsed)" in script
    assert "function setShoppingListViewRowsCollapsed(collapsed)" in script
    assert "function setAllRecipeViewNestedPanelsCollapsed(collapsed)" in script
    assert "function setAllCookbookPanelsCollapsed(collapsed)" in script
    assert "function closeShoppingListExpandedPanels()" in script
    assert "setAllCardCollapseContentCollapsed(true)" in script
    assert "setShoppingListViewRowsCollapsed(true)" in script
    assert "setAllRecipeViewNestedPanelsCollapsed(true)" in script
    assert "setAllCookbookPanelsCollapsed(true)" in script
    assert 'setAllShoppingListRecipeImagesVisible(false, { keepTitleImages: true })' in script
    assert 'setShoppingGlobalCollapseStatus("Everything collapsed.")' in script
    assert "setAllShoppingListRecipeImagesVisible(recipeImagesShownByDefault())" in script
    assert ".recipe-global-image-hidden" in css


def test_auth_transition_can_request_collapse_before_lazy_sections_load():
    script = read_text("PushShoppingList/static/js/app.js")

    assert 'const AUTH_COLLAPSE_PENDING_KEY = "shopping-auth-collapse-all-pending";' in script
    assert 'const AUTH_COLLAPSE_ACTIVE_KEY = "shopping-auth-collapse-all-active";' in script
    assert "function requestShoppingListAuthCollapseAll()" in script
    assert "function consumeAuthCollapseAllRequest()" in script
    assert "function persistShoppingListCollapsedState()" in script
    assert "window.requestShoppingListAuthCollapseAll = requestShoppingListAuthCollapseAll;" in script
    assert '["consumeAuthCollapseAllRequest", consumeAuthCollapseAllRequest]' in script
    assert "if (authCollapseAllIsActive())" in script
    assert 'safeStorageSet(localStorage, `card-collapse:${key}`, "collapsed");' in script
    assert "safeStorageRemove(localStorage, USER_ACCOUNT_OPEN_PANEL_KEY);" in script


def test_global_collapse_keeps_recipe_title_images_visible():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "RECIPE_TITLE_IMAGE_SELECTOR" in script
    assert "[data-recipe-edit-title-image-panel]" in script
    assert ".recipe-url-summary-main" in script
    assert ".recipe-view-title-media" in script
    assert ".recipe-view-body-media" in script
    assert ".recipe-cover-image" in script
    assert "const keepTitleImages = Boolean(options.keepTitleImages);" in script
    assert 'element.classList.remove("recipe-global-image-hidden");' in script
    assert 'setAllShoppingListRecipeImagesVisible(false, { keepTitleImages: true })' in script
