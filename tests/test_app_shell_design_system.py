from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_index_uses_phase_one_app_shell_without_removing_existing_controls():
    template = read_text("PushShoppingList/templates/index.html")
    shell_macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")

    assert '{% import "includes/app_shell_macros.html" as shell %}' in template
    assert "app-shell-body" in template
    assert '<aside class="app-sidebar" aria-label="Primary navigation">' in template
    assert "shell.app_topbar(" in template
    assert '<header class="app-topbar" aria-label="App toolbar">' in shell_macros
    assert '<header id="appPageHeader" class="app-page-header" data-app-home-header>' in template
    assert '<nav class="app-mobile-bottom-nav" aria-label="Mobile navigation">' in template
    assert 'class="app-nav-section-title">Discover &amp; Plan</div>' in template
    assert 'class="app-nav-section-title">CREATE RECIPES</div>' in template
    assert 'class="app-nav-section-title">IMPORT MENUS</div>' in template
    assert 'class="app-nav-section-title">PANTRY</div>' in template
    assert 'class="app-nav-section-title">Account</div>' in template
    assert "app-sidebar-promo" in template
    assert 'data-app-global-search' in shell_macros
    assert "app-global-search-icon" in shell_macros
    assert "app-global-search-shortcut" in shell_macros
    assert "Ctrl + K" in shell_macros
    assert "'submitAppGlobalSearch'" in template
    assert "app-toolbar-primary" in shell_macros
    assert 'data-app-page-target="notificationsPage"' in shell_macros
    assert 'data-app-nav-action="account-workspace"' in shell_macros
    assert 'href="#recipesPage" data-app-nav-link data-app-nav-action="app-page" data-app-page-target="recipesPage" data-app-nav-target="recipesPage"' in template
    assert 'class="app-account-avatar-image"' in shell_macros
    assert "current_user.avatar_path" in shell_macros
    assert "current_user.picture" in shell_macros
    assert 'referrerpolicy="no-referrer"' in shell_macros
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


def test_sidebar_import_actions_are_grouped_by_task_without_duplicate_hub_link():
    template = read_text("PushShoppingList/templates/index.html")
    nav_start = template.index('<nav class="app-sidebar-nav" aria-label="App sections">')
    nav_end = template.index("</nav>", nav_start)
    sidebar = template[nav_start:nav_end]

    ordered_labels = (
        'class="app-nav-section-title">CREATE RECIPES</div>',
        '<span class="app-nav-text">Recipe URL</span>',
        '<span class="app-nav-text">Recipe Document</span>',
        '<span class="app-nav-text">Recipe Image</span>',
        'class="app-nav-section-title">IMPORT MENUS</div>',
        '<span class="app-nav-text">Menu URL</span>',
        '<span class="app-nav-text">Menu Document</span>',
        'class="app-nav-section-title">PANTRY</div>',
        '<span class="app-nav-text">Scan Barcode</span>',
    )
    positions = [sidebar.index(label) for label in ordered_labels]

    assert positions == sorted(positions)
    for old_label in ("Recipe URLs", "Import From Document", "Generate From Image", "Import Menu From Document"):
        assert f'<span class="app-nav-text">{old_label}</span>' not in sidebar
    assert '<span class="app-nav-text">Import</span>' not in sidebar
    assert 'data-app-page-target="importPage"' not in sidebar
    assert sidebar.count('class="app-nav-section-title">CREATE RECIPES</div>') == 1
    assert sidebar.count('class="app-nav-section-title">IMPORT MENUS</div>') == 1
    assert sidebar.count('class="app-nav-section-title">PANTRY</div>') == 1
    assert sidebar.index('<span class="app-nav-text">Pantry</span>') < positions[0]

    for page_target, label in (
        ("recipeUrlsPage", "Recipe URL"),
        ("importDocumentPage", "Recipe Document"),
        ("generateImagePage", "Recipe Image"),
        ("menuUrlPage", "Menu URL"),
        ("menuDocumentPage", "Menu Document"),
    ):
        label_markup = f'<span class="app-nav-text">{label}</span>'
        label_position = sidebar.index(label_markup)
        link_start = sidebar.rfind("<a ", 0, label_position)
        link_end = sidebar.index("</a>", label_position)
        link = sidebar[link_start:link_end]

        assert f'href="#{page_target}"' in link
        assert 'data-app-nav-link' in link
        assert 'data-app-nav-action="app-page"' in link
        assert f'data-app-page-target="{page_target}"' in link
        assert f'data-app-nav-target="{page_target}"' in link

    assert 'class="app-nav-link app-nav-link-multiline"' in sidebar
    assert 'href="{{ url_for(\'pantry_bp.pantry_coming_soon_route\') }}"' in sidebar


def test_recipe_editor_sidebar_uses_the_same_import_task_groups():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")
    nav_start = template.index('<nav class="app-sidebar-nav" aria-label="App sections">')
    nav_end = template.index("</nav>", nav_start)
    sidebar = template[nav_start:nav_end]

    assert '<span class="app-nav-text">Import</span>' not in sidebar
    assert sidebar.count('class="app-nav-section-title">CREATE RECIPES</div>') == 1
    assert sidebar.count('class="app-nav-section-title">IMPORT MENUS</div>') == 1
    assert sidebar.count('class="app-nav-section-title">PANTRY</div>') == 1
    for label in ("Recipe URL", "Recipe Document", "Recipe Image", "Menu URL", "Menu Document"):
        assert f'<span class="app-nav-text">{label}</span>' in sidebar
    for old_label in ("Recipe URLs", "Import From Document", "Generate From Image", "Import Menu From Document"):
        assert f'<span class="app-nav-text">{old_label}</span>' not in sidebar
    assert '{{ url_for(\'main_bp.index\') }}#recipeUrlsPage' in sidebar
    assert '{{ url_for(\'main_bp.index\') }}#importDocumentPage' in sidebar
    assert '{{ url_for(\'main_bp.index\') }}#generateImagePage' in sidebar
    assert '{{ url_for(\'main_bp.index\') }}#menuUrlPage' in sidebar
    assert '{{ url_for(\'main_bp.index\') }}#menuDocumentPage' in sidebar
    assert '{{ url_for(\'pantry_bp.pantry_coming_soon_route\') }}' in sidebar


def test_brand_mark_uses_chef_hat_check_cart_logo():
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    brand_start = macros.index("{% macro brand_mark_svg(color=\"currentColor\") -%}")
    brand_end = macros.index("{%- endmacro %}", brand_start)
    brand_markup = macros[brand_start:brand_end]
    css = read_text("PushShoppingList/static/css/app.css")

    assert 'viewBox="0 0 134 147"' in brand_markup
    assert "M40 64.5C25.2 64.2 14 54.6" in brand_markup
    assert "M39.4 62.5 44 106.5" in brand_markup
    assert "M53 94.3h38" in brand_markup
    assert "m53.2 64.4 12.2 10.5 18-18.7" in brand_markup
    assert '<circle cx="52.2" cy="133.2" r="6"></circle>' in brand_markup
    assert '<circle cx="87.4" cy="133.2" r="6"></circle>' in brand_markup
    assert 'stroke="{{ color }}"' in brand_markup
    assert "stroke-width: 6;" in css


def test_recipe_edit_favicon_reuses_shared_brand_mark_only_on_standalone_editor():
    recipe_edit = read_text("PushShoppingList/templates/recipe_edit_page.html")
    index = read_text("PushShoppingList/templates/index.html")

    assert "shell.brand_mark_svg('#2eb66f')|urlencode" in recipe_edit
    assert "images/ai-pantry-logo.svg" not in recipe_edit
    assert "shell.brand_mark_svg('#2eb66f')" not in index


def test_sidebar_import_targets_keep_existing_active_state_and_barcode_behavior():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    pantry_routes = read_text("PushShoppingList/routes/pantry_routes.py")

    for page_target in (
        "recipeUrlsPage",
        "importDocumentPage",
        "generateImagePage",
        "menuUrlPage",
        "menuDocumentPage",
    ):
        assert f'{page_target}: "{page_target}"' in script

    assert "function appShellSetActivePageLink(pageId)" in script
    assert 'link.classList.toggle("is-active", Boolean(sameLinkKey));' in script
    assert ".app-nav-link:hover," in css
    assert ".app-nav-link:focus-visible," in css
    assert ".app-sidebar-collapsed .app-nav-text," in css
    assert "overflow-y: auto;" in css
    assert '@pantry_bp.route("/pantry/coming-soon")' in pantry_routes
    assert 'redirect(url_for("main_bp.index", _anchor="aiPantrySection"))' in pantry_routes


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


def test_home_and_recipe_editor_reuse_the_same_topbar_and_account_control():
    home = read_text("PushShoppingList/templates/index.html")
    recipe_editor = read_text("PushShoppingList/templates/recipe_edit_page.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert "{% macro account_control(" in macros
    assert "{% macro app_topbar(" in macros
    assert "current_user.display_name" in macros
    assert "Pro Plan" in macros
    assert "shell.app_topbar(" in home
    assert "shell.app_topbar(" in recipe_editor
    assert "{{ account_control(current_user, is_guest_demo, account_href, in_shell) }}" in macros
    assert 'class="app-toolbar-button app-account-button"' not in home
    assert 'class="app-toolbar-button app-account-button"' not in recipe_editor
    assert "recipe-edit-page-topbar" not in recipe_editor
    assert "recipe-edit-page-topbar" not in css
    assert "grid-template-columns: minmax(280px, 620px) minmax(0, 1fr) auto;" in css
    assert "from PushShoppingList.services.user_account_service import current_public_user" in routes
    assert "current_user=current_public_user()," in routes


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
    assert 'recipe["card_cook_time"] = recipe_card_cook_time_label(recipe)' in route
    assert 'recipe["card_calories"] = recipe_card_calories_label(recipe.get("calories"))' in route
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
    assert ".app-nav-link-multiline .app-nav-text {" in css
    assert "white-space: normal;" in css
    assert "overflow-wrap: anywhere;" in css
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
    tablet_shell = css[
        css.index("@media (min-width: 768px) and (max-width: 1099px)"):
        css.index("@media (max-width: 767px)")
    ]
    assert "grid-template-columns: auto minmax(240px, 1fr) auto;" in tablet_shell
    assert ".app-topbar-brand {\n        display: inline-flex;" in tablet_shell
    assert ".app-topbar-brand span:not(.app-brand-mark) {\n        display: none;" in tablet_shell
    assert ".app-global-search {\n        grid-column: 2;" in tablet_shell
    assert ".app-toolbar-actions {\n        grid-column: 3;" in tablet_shell


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
