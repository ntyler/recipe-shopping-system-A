from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_index_uses_phase_one_app_shell_without_removing_existing_controls():
    template = read_text("PushShoppingList/templates/index.html")

    assert '{% import "includes/app_shell_macros.html" as shell %}' in template
    assert "app-shell-body" in template
    assert '<aside class="app-sidebar" aria-label="Primary navigation">' in template
    assert '<header class="app-topbar" aria-label="App toolbar">' in template
    assert '<header id="appPageHeader" class="app-page-header" data-app-home-header>' in template
    assert '<nav class="app-mobile-bottom-nav" aria-label="Mobile navigation">' in template
    assert 'class="app-nav-section-title">Discover &amp; Plan</div>' in template
    assert 'class="app-nav-section-title">Import</div>' in template
    assert 'class="app-nav-section-title">Account</div>' in template
    assert "app-sidebar-promo" in template
    assert 'data-app-global-search' in template
    assert "app-global-search-icon" in template
    assert "app-global-search-shortcut" in template
    assert "Ctrl + K" in template
    assert 'onsubmit="return submitAppGlobalSearch(this)"' in template
    assert "app-toolbar-primary" in template
    assert 'data-app-page-target="notificationsPage"' in template
    assert 'data-app-nav-action="account-workspace"' in template
    assert 'href="#recipesPage" data-app-nav-link data-app-nav-action="app-page" data-app-page-target="recipesPage" data-app-nav-target="recipesPage"' in template
    assert 'class="app-account-avatar-image"' in template
    assert "current_user.avatar_path" in template
    assert "current_user.picture" in template
    assert 'referrerpolicy="no-referrer"' in template
    assert 'data-app-nav-action="ai-pantry"' in template
    assert 'data-app-nav-lazy-section="pantry"' in template
    assert 'data-app-nav-lazy-section="current-recipes"' in template
    assert 'data-app-nav-lazy-section="recipe-view"' in template
    assert '{% include "sections/settings_workspace.html" %}' in template
    assert '{% include "sections/app_workspaces.html" %}' in template
    assert 'class="app-home-dashboard"' in template
    assert 'data-app-home-dashboard' in template
    assert 'data-app-nav-action="settings-section"' in template
    assert 'data-app-nav-action="app-page"' in template
    assert 'onclick="return collapseAllShoppingListPage()"' in template
    assert 'onclick="return expandAllShoppingListPage()"' in template
    assert 'data-public-workspace="{{ \'1\' if not current_user and not is_guest_demo else \'0\' }}"' in template


def test_index_topbar_uses_current_user_profile_image(monkeypatch, tmp_path):
    from PushShoppingList.app import create_app
    from PushShoppingList.services import user_account_service as accounts

    users_file = tmp_path / "users.json"
    monkeypatch.setattr(accounts, "USERS_FILE", users_file)
    accounts.save_users({
        "users": [
            {
                "user_id": "avatar-user",
                "first_name": "Nathaniel",
                "last_name": "Tyler",
                "username": "nathaniel",
                "email": "nathaniel@example.com",
                "auth_provider": "firebase",
                "picture": "https://example.com/avatar.jpg",
                "account_status": "active",
            }
        ]
    })

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "avatar-user"

        response = client.get("/")

    html = response.get_data(as_text=True)
    topbar_start = html.index('class="app-toolbar-button app-account-button"')
    topbar_end = html.index("</a>", topbar_start)
    topbar_markup = html[topbar_start:topbar_end]

    assert response.status_code == 200
    assert 'class="app-account-avatar-image"' in topbar_markup
    assert 'src="https://example.com/avatar.jpg"' in topbar_markup
    assert 'referrerpolicy="no-referrer"' in topbar_markup
    assert "Nathaniel Tyler" in topbar_markup
    assert ">N<" not in topbar_markup


def test_app_workspaces_define_mockup_style_individual_pages():
    template = read_text("PushShoppingList/templates/sections/app_workspaces.html")

    assert 'id="recipesPage"' in template
    assert 'id="menusPage"' in template
    assert 'id="cookbooksPage"' in template
    assert 'id="shoppingListsPage"' in template
    assert 'id="pantryPage"' in template
    assert 'id="storesPage"' in template
    assert 'id="priceComparisonPage"' in template
    assert 'id="importPage"' in template
    assert 'id="recipeUrlsPage"' in template
    assert 'id="importDocumentPage"' in template
    assert 'id="generateImagePage"' in template
    assert 'id="menuUrlPage"' in template
    assert 'id="menuDocumentPage"' in template
    assert 'id="notificationsPage"' in template
    assert 'data-app-page-workspace' in template
    assert 'store-logo-{{ store_key|replace(\'_\', \'-\') }}' in template
    assert '"kroger": "Kroger"' in template
    assert 'id="currentRecipeUrlLogCard"' in template
    assert 'id="cookbooksCard"' in template
    assert 'id="shoppingViewsSection"' in template
    assert 'id="aiPantrySection"' in template
    assert 'id="importWorkspaceSection"' in template
    assert 'class="app-page-layout"' in template
    assert 'class="app-page-rail"' in template
    assert 'class="app-page-tabs"' in template
    assert 'class="app-recipes-toolbar"' in template
    assert 'class="app-recipes-grid"' in template
    assert "{% for recipe in recipe_preview_rows %}" in template
    assert 'class="app-recipe-card{% if recipe.cover_image and recipe.cover_image.src %}' in template
    assert 'data-deferred-src="{{ recipe.cover_image.card_url or recipe.cover_image.thumb_url or recipe.cover_image.src }}"' in template
    assert 'data-app-page-target="recipeUrlsPage"' in template
    assert "app-import-method-grid" in template
    assert 'class="app-import-flow-card"' in template
    assert 'data-recipe-media-upload-status-mirror' in template
    assert 'id="menuUrlsTextarea"' in template
    assert "submitMenuUrlPageImport(this)" in template
    assert "Import Menu From Document" in template
    assert '{% include "sections/edit_items.html" %}' in template


def test_settings_workspace_groups_moved_sections_without_renaming_behaviors():
    template = read_text("PushShoppingList/templates/sections/settings_workspace.html")

    assert 'id="settingsWorkspaceSection"' in template
    assert 'data-settings-workspace' in template
    assert 'data-settings-section="usage-billing"' in template
    assert 'data-settings-section="rules-automation"' in template
    assert 'data-settings-section="location"' in template
    assert 'data-settings-section="stores-shopping"' in template
    assert 'Rules &amp; Automation' in template
    assert 'Stores &amp; Shopping' in template
    assert '{% include "sections/home_address.html" %}' in template
    assert 'id="rulesCard"' in template
    assert 'id="storeOptionsSection"' in template
    assert 'data-lazy-section="rules"' in template
    assert 'data-lazy-section="store-options"' in template
    assert 'data-firebase-change-password' in template
    assert 'data-firebase-sign-out-form' in template
    assert 'data-two-factor-open' in template
    assert 'data-push-notifications-open' in template
    assert 'data-delete-account-open' in template


def test_app_shell_context_provides_recipe_preview_rows():
    route = read_text("PushShoppingList/routes/main_routes.py")

    assert "recipe_preview_rows = recipe_url_log_rows(" in route
    assert "recipe_urls[:8]" in route
    assert 'image_variants=("card", "thumb")' in route
    assert '"recipe_preview_rows": recipe_preview_rows' in route


def test_app_css_defines_scoped_design_tokens_and_responsive_shell():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "--app-bg:" in css
    assert "--app-surface:" in css
    assert "--app-primary:" in css
    assert "--app-sidebar-width:" in css
    assert "--app-content-max:" in css
    assert "--app-control-height:" in css
    assert "--app-radius-lg:" in css
    assert "scrollbar-gutter: stable;" in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert ".app-shell-body {" in css
    assert ".app-sidebar {" in css
    assert ".app-brand-mark svg {" in css
    assert ".app-icon-svg" in css
    assert ".app-nav-section-title {" in css
    assert ".app-sidebar-promo {" in css
    assert ".app-topbar {" in css
    assert ".app-global-search-shortcut" in css
    assert ".app-toolbar-primary" in css
    assert ".app-page-header {" in css
    assert ".app-page-header[hidden]" in css
    assert ".app-mobile-bottom-nav {" in css
    assert ".app-account-avatar-image" in css
    assert ".app-home-dashboard {" in css
    assert ".app-home-dashboard[hidden]" in css
    assert ".settings-workspace-section" in css
    assert ".settings-category-button" in css
    assert ".settings-panel" in css
    assert ".app-page-workspace" in css
    assert ".app-page-layout" in css
    assert ".app-page-rail" in css
    assert ".app-recipes-toolbar" in css
    assert ".app-recipes-grid" in css
    assert ".app-recipe-card" in css
    assert ".app-recipe-card-media" in css
    assert ".app-page-actions > *" in css
    assert ".app-page-tabs button" in css
    assert ".app-page-tabs::-webkit-scrollbar" in css
    assert "scrollbar-width: none;" in css
    assert "width: auto;" in css
    assert ".app-import-method-grid" in css
    assert ".app-import-flow-card" in css
    assert ".app-page-summary-cards" in css
    assert ".app-page-chip-row" in css
    assert ".app-page-filter-card" in css
    assert ".app-page-action-grid" in css
    assert ".app-page-store-logo.store-logo-kroger" in css
    assert ".app-page-store-logo.store-logo-walmart" in css
    assert ".app-notification-list" in css
    assert ".user-account-card[hidden]" in css
    assert ".app-workspace-panel[hidden]" in css
    assert "@media (max-width: 1099px)" in css
    assert "@media (min-width: 768px) and (max-width: 1099px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (max-width: 1100px)" in css
    assert "@media (max-width: 768px)" in css
    assert "width: min(var(--app-content-max), calc(100% - 56px));" in css
    assert "width: min(var(--app-content-max), calc(100% - 32px));" in css
    assert "width: calc(100% - 24px);" in css
    assert "calc(100vw - var(--app-sidebar-width)" not in css
    assert ".app-shell-body .app-card" in css
    assert ".app-shell-body .settings-workspace-section.app-card" in css
    assert ".app-shell-body :where(input, select, textarea)" in css
    assert ".app-shell-body :where(table)" in css


def test_desktop_sidebar_logo_and_icons_use_readable_scale():
    css = read_text("PushShoppingList/static/css/app.css")
    desktop_shell = css[css.index("/* Desktop mockup fidelity pass"):]

    assert ".app-brand-mark {\n        flex-basis: 51px;\n        width: 51px;\n        height: 51px;" in desktop_shell
    assert ".app-nav-icon {\n        flex-basis: 23px;\n        width: 23px;\n        height: 23px;" in desktop_shell
    assert ".app-icon-svg {\n        width: 20px;\n        height: 20px;" in desktop_shell


def test_app_shell_navigation_reuses_existing_lazy_and_account_panel_functions():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function initAppShellNavigation()" in script
    assert "function submitAppGlobalSearch(form)" in script
    assert "function appShellNavActiveKey(link)" in script
    assert "function appShellSetActivePageLink(pageId)" in script
    assert "async function activateAppShellNavLink(link" in script
    assert 'return pageId ? `page:${pageId}` : `target:${targetId}`;' in script
    assert "appShellNavActiveKey(link) === activeKey" in script
    assert "appShellSetActivePageLink(pageId);" in script
    assert "sameAction" not in script
    assert 'return openAiPantryPanel({' in script
    assert 'pageId: String(link.dataset.appPageTarget || "") || "pantryPage"' in script
    assert "const pantryPageId = options.pageId || \"pantryPage\";" in script
    assert "if (!pantryPage || pantryPage.hidden)" in script
    assert "initDeferredImages(page);" in script
    assert "toggleUsageDashboardPanel(true)" in script
    assert "function openUserAccountWorkspace" in script
    assert "function setUserAccountWorkspaceVisible" in script
    assert "initAppShellInitialWorkspace" in script
    assert 'action === "account-workspace"' in script
    assert "menusPage" in script
    assert "notificationsPage" in script
    assert "recipeUrlsPage" in script
    assert "importDocumentPage" in script
    assert "generateImagePage" in script
    assert "menuUrlPage" in script
    assert "menuDocumentPage" in script
    assert "function submitMenuUrlPageImport" in script
    assert "function setRecipeMediaUploadStatus" in script
    assert "openFeedbackSupportSection()" in script
    assert "toggleUserProfileEditor(true)" in script
    assert "async function openAppPage" in script
    assert "function openHomeWorkspace" in script
    assert "function setHomeHeaderVisible" in script
    assert "setHomeHeaderVisible(false)" in script
    assert "setHomeHeaderVisible(true)" in script
    assert 'action === "app-page"' in script
    assert "async function openSettingsSection" in script
    assert "function openWorkspacePanel" in script
    assert "async function openHashTargetWorkspace" in script
    assert 'action === "settings-section"' in script
    assert 'action === "workspace-panel"' in script
    assert 'SETTINGS_SECTION_LAZY_SECTIONS[activeSection]' in script
    assert "await loadLazySection(lazySection" in script
    assert 'String(event.key || "").toLowerCase() === "k"' in script
    assert 'document.querySelector("[data-app-global-search]")' in script
    assert '["initAppShellNavigation", initAppShellNavigation]' in script
    assert '["initSettingsWorkspace", () => initSettingsWorkspace({ scroll: false })]' in script
