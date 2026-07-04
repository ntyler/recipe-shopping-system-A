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

    assert "function collapseAllShoppingListPage(options = {})" in script
    assert "function expandAllShoppingListPage()" in script
    assert "function setAllCardCollapseContentCollapsed(collapsed" in script
    assert "function setShoppingListViewRowsCollapsed(collapsed)" in script
    assert "function setAllRecipeViewNestedPanelsCollapsed(collapsed" in script
    assert "function setAllCookbookPanelsCollapsed(collapsed" in script
    assert "function closeShoppingListExpandedPanels()" in script
    assert "setAllCardCollapseContentCollapsed(true," in script
    assert "setShoppingListViewRowsCollapsed(true)" not in script
    assert "setShoppingListViewRowsCollapsed(false)" in script
    assert "setAllRecipeViewNestedPanelsCollapsed(true," in script
    assert "setAllCookbookPanelsCollapsed(true," in script
    assert 'setAllShoppingListRecipeImagesVisible(false, { keepTitleImages: true })' in script
    assert 'setShoppingGlobalCollapseStatus("Everything collapsed.")' in script
    assert "setAllShoppingListRecipeImagesVisible(recipeImagesShownByDefault())" in script
    assert ".recipe-global-image-hidden" in css


def test_shopping_list_section_and_store_ingredients_stay_expanded_after_load():
    script = read_text("PushShoppingList/static/js/app.js")

    helper_start = script.index("function setShoppingListViewRowsCollapsed(collapsed)")
    helper_end = script.index("function setAllRecipeViewNestedPanelsCollapsed", helper_start)
    helper_block = script[helper_start:helper_end]
    show_view_start = script.index("function showView(viewName)")
    show_view_end = script.index("function eventStartedInNestedInteractive", show_view_start)
    show_view_block = script[show_view_start:show_view_end]

    assert "if (collapsed) {\n        return;\n    }" in helper_block
    assert '"#sectionView .section-header-row"' in helper_block
    assert '"#storeView .store-section-header"' in helper_block
    assert "setShoppingListViewRowsCollapsed(false);" in show_view_block
    assert 'activeView === "section" || activeView === "store"' in show_view_block


def test_auth_transition_can_request_collapse_before_lazy_sections_load():
    script = read_text("PushShoppingList/static/js/app.js")

    assert 'const AUTH_COLLAPSE_PENDING_KEY = "shopping-auth-collapse-all-pending";' in script
    assert 'const AUTH_COLLAPSE_ACTIVE_KEY = "shopping-auth-collapse-all-active";' in script
    assert "function requestShoppingListAuthCollapseAll()" in script
    assert 'safeStorageSet(sessionStorage, AUTH_COLLAPSE_ACTIVE_KEY, "1");' in script
    assert 'applyShoppingListCollapsedDomState({ showStatus: true });' in script
    assert "function clearShoppingListAuthCollapseAllRequest()" in script
    assert "function consumeAuthCollapseAllRequest()" in script
    assert "function persistShoppingListCollapsedState()" in script
    assert "window.requestShoppingListAuthCollapseAll = requestShoppingListAuthCollapseAll;" in script
    assert "window.clearShoppingListAuthCollapseAllRequest = clearShoppingListAuthCollapseAllRequest;" in script
    assert '["consumeAuthCollapseAllRequest", consumeAuthCollapseAllRequest]' in script
    assert "if (authCollapseAllIsActive())" in script
    assert "const userRequestedLoad = options.userInitiated === true || options.focus === true;" in script
    assert "if (authCollapseAllIsActive() && userRequestedLoad)" in script
    assert "clearAuthCollapseAllMode();" in script
    assert "if (authCollapseAllIsActive() && options.allowDuringAuthCollapse !== true)" in script
    assert 'safeStorageSet(localStorage, `card-collapse:${key}`, "collapsed");' in script
    assert "safeStorageRemove(localStorage, USER_ACCOUNT_OPEN_PANEL_KEY);" in script


def test_auth_collapse_still_allows_manual_lazy_section_open():
    script = read_text("PushShoppingList/static/js/app.js")
    index_template = read_text("PushShoppingList/templates/index.html")

    lazy_load_start = script.index("async function loadLazySection(sectionName, options = {})")
    lazy_load_end = script.index("async function refreshLazySection", lazy_load_start)
    lazy_load_block = script[lazy_load_start:lazy_load_end]

    assert "const userRequestedLoad = options.userInitiated === true || options.focus === true;" in lazy_load_block
    assert (
        "if (authCollapseAllIsActive() && userRequestedLoad) {\n"
        "        clearAuthCollapseAllMode();\n"
        "    }"
    ) in lazy_load_block
    assert (
        "if (authCollapseAllIsActive() && options.allowDuringAuthCollapse !== true) {\n"
        "        placeholder.dataset.lazyQueued = \"\";"
    ) in lazy_load_block
    assert lazy_load_block.index(
        "if (userRequestedLoad && options.persistExpanded !== false) {\n"
        "                setLazySectionSavedState(sectionName, true);\n"
        "            }"
    ) < lazy_load_block.index("afterDynamicMarkupLoaded({ root: nextElement });")
    assert (
        "if (options.persistExpanded !== false && !userRequestedLoad) {\n"
        "                setLazySectionSavedState(sectionName, true);\n"
        "            }"
    ) in lazy_load_block
    assert 'onclick="loadLazySection(\'current-recipes\', { focus: true }); return false;"' in index_template
    assert 'onclick="loadLazySection(\'cookbooks\', { focus: true }); return false;"' in index_template
    assert 'await loadLazySection("pantry", { focus: false, userInitiated: true });' in script
    assert 'await loadLazySection("admin-support", { focus: false, userInitiated: true });' in script
    assert 'await loadLazySection("shared-recipe-pdfs", { focus: false, userInitiated: true });' in script


def test_lazy_section_loader_rejects_auth_redirect_and_full_page_markup():
    script = read_text("PushShoppingList/static/js/app.js")
    app = read_text("PushShoppingList/app.py")

    assert 'or request.path.startswith("/sections/")' in app
    assert "const LAZY_SECTION_ROOT_SELECTORS = {" in script
    assert '"current-recipes": "#currentRecipeUrlLogCard"' in script
    assert '"recipe-view": "#shoppingViewsSection"' in script
    assert 'function firstRenderableElementFromHtml(html, sectionName = "")' in script
    assert "nextPage.body.querySelector(expectedSelector)" in script
    assert '"X-Requested-With": "fetch"' in script
    assert "if (response.redirected)" in script
    assert 'throw new Error("Section load redirected.");' in script
    assert 'response.headers.get("content-type")' in script
    assert "await response.json().catch(() => ({}))" in script
    assert 'err.message === "Sign in before managing this workspace."' in script
    assert "Sign in or try the demo to open this section." in script
    assert "firstRenderableElementFromHtml(await response.text(), sectionName)" in script
    assert 'throw new Error("Section returned unexpected markup.");' in script


def test_cookbooks_lazy_section_keeps_images_lazy():
    index_template = read_text("PushShoppingList/templates/index.html")
    cookbooks_template = read_text("PushShoppingList/templates/sections/cookbooks.html")

    cookbooks_start = index_template.index('data-lazy-section="cookbooks"')
    cookbooks_end = index_template.index('data-lazy-url="{{ url_for(\'main_bp.cookbooks_section\') }}"', cookbooks_start)
    cookbooks_placeholder = index_template[cookbooks_start:cookbooks_end]

    assert 'class="app-card lazy-section-placeholder"' in index_template
    assert 'data-lazy-section="cookbooks"' in cookbooks_placeholder
    assert 'onclick="loadLazySection(\'cookbooks\', { focus: true }); return false;"' in index_template
    assert 'data-deferred-src="{{ recipe.cover_image.thumb_url or recipe.cover_image.card_url or recipe.cover_image.src }}"' in cookbooks_template
    assert 'loading="lazy"' in cookbooks_template


def test_firebase_auth_requests_collapse_before_sign_in_and_sign_out_work():
    script = read_text("PushShoppingList/static/js/firebase-auth.js")

    assert "function cancelCollapseAllBeforeAuthReload()" in script
    assert "window.clearShoppingListAuthCollapseAllRequest" in script
    assert (
        "requestCollapseAllBeforeAuthReload();\n"
        "        try {\n"
        "            const credential = await createUserWithEmailAndPassword"
    ) in script
    assert (
        "requestCollapseAllBeforeAuthReload();\n"
        "\n"
        "        try {\n"
        "            const credential = await signInWithEmailAndPassword"
    ) in script
    assert (
        "requestCollapseAllBeforeAuthReload();\n"
        "\n"
        "            try {\n"
        "                const credential = await signInWithPopup"
    ) in script
    assert "cancelCollapseAllBeforeAuthReload();\n            setStatus(form, firebaseErrorMessage(error), \"error\");" in script
    assert (
        "if (firebaseUser && !session.authenticated && !session.pending_2fa) {\n"
        "                requestCollapseAllBeforeAuthReload();\n"
        "                const result = await syncFirebaseUser"
    ) in script
    assert (
        "if (!firebaseUser && session.user && session.user.auth_provider === \"firebase\") {\n"
        "                requestCollapseAllBeforeAuthReload();\n"
        "                await logoutBackend();"
    ) in script


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
