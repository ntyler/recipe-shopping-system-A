from pathlib import Path

from PushShoppingList.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_index_uses_phase_one_app_shell_without_removing_existing_controls():
    template = read_text("PushShoppingList/templates/index.html")
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")
    header = read_text("PushShoppingList/templates/includes/app_header.html")
    sidebar = read_text("PushShoppingList/templates/includes/app_sidebar.html")
    navigation = read_text("PushShoppingList/templates/includes/app_navigation_sections.html")
    plan_promo = read_text("PushShoppingList/templates/includes/app_plan_promo.html")
    mobile_navigation = read_text("PushShoppingList/templates/includes/app_mobile_navigation.html")
    shell_macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")

    assert '{% import "includes/app_shell_macros.html" as shell %}' in template
    assert '{% extends "layouts/app_layout.html" %}' in template
    assert "app-shell-body" in layout
    assert '{% include "includes/app_sidebar.html" %}' in layout
    assert '{% include "includes/app_header.html" %}' in layout
    assert '<aside class="app-sidebar' in sidebar
    assert '<header class="app-topbar" aria-label="App toolbar" data-app-header>' in header
    assert '<header id="appPageHeader" class="app-page-header" data-app-home-header>' in template
    assert '<nav class="app-mobile-bottom-nav" aria-label="Mobile navigation">' in mobile_navigation
    assert '{% include "includes/app_navigation_sections.html" %}' in sidebar
    assert '{% include "includes/app_navigation_sections.html" %}' in mobile_navigation
    assert navigation.count('class="app-nav-section-title"') == 4
    for heading in ("MAIN", "SHOP", "TOOLS", "ACCOUNT"):
        assert f'class="app-nav-section-title">{heading}</div>' in navigation
    for old_heading in ("Discover &amp; Plan", "CREATE RECIPES", "IMPORT MENUS", "PANTRY"):
        assert f'class="app-nav-section-title">{old_heading}</div>' not in navigation
    assert "app-sidebar-promo" in plan_promo
    assert "AI Pantry Pro" in plan_promo
    assert "Unlock more from your pantry." in plan_promo
    assert 'data-app-plan-link data-app-nav-action="usage-dashboard"' in plan_promo
    assert 'data-app-global-search' in header
    assert '<div class="app-header-search">' in header
    assert "app-global-search-icon" in header
    assert "app-global-search-shortcut" in header
    assert "Ctrl + K" in header
    assert 'onsubmit="return submitGlobalAppSearch(this)"' in header
    assert 'data-global-search-endpoint="/api/global-search"' in header
    assert 'role="combobox"' in header
    assert 'role="listbox"' in header
    assert "<datalist" not in header
    assert "app-toolbar-primary" in header
    assert 'aria-label="Import"' in header
    assert 'title="Import"' in header
    assert '<span class="app-import-label">Import</span>' in header
    assert '<div class="app-header-profile">' in header
    assert 'data-app-page-target="notificationsPage"' in header
    assert 'data-app-nav-action="account-workspace"' in shell_macros
    assert 'data-app-page-target="recipesPage"' in navigation
    assert 'class="app-account-avatar-image"' in shell_macros
    assert "current_user.avatar_path" in shell_macros
    assert "current_user.picture" in shell_macros
    assert 'referrerpolicy="no-referrer"' in shell_macros
    assert 'data-app-nav-action="ai-pantry"' in navigation
    assert 'data-app-nav-lazy-section="pantry"' in navigation
    assert 'data-app-nav-lazy-section="current-recipes"' in navigation
    assert 'data-app-nav-lazy-section="recipe-view"' in navigation
    assert '{% include "sections/settings_workspace.html" %}' in template
    assert '{% include "sections/app_workspaces.html" %}' in template
    assert 'class="app-home-dashboard"' in template
    assert 'data-app-home-dashboard' in template
    assert 'data-app-nav-action="settings-section"' in navigation
    assert 'data-app-nav-action="app-page"' in navigation
    assert 'onclick="return collapseAllShoppingListPage()"' in template
    assert 'onclick="return expandAllShoppingListPage()"' in template
    assert "data-public-workspace" not in template


def test_sidebar_has_exact_group_order_and_one_import_destination():
    navigation = read_text("PushShoppingList/templates/includes/app_navigation_sections.html")
    import_workspace = read_text("PushShoppingList/templates/sections/app_workspaces.html")

    ordered_labels = (
        'class="app-nav-section-title">MAIN</div>',
        '<span class="app-nav-text">Home</span>',
        '<span class="app-nav-text">Recipes</span>',
        '<span class="app-nav-text">Menus</span>',
        '<span class="app-nav-text">Cookbooks</span>',
        '<span class="app-nav-text">Shopping Lists</span>',
        '<span class="app-nav-text">Pantry</span>',
        '<span class="app-nav-text">Meal Planner</span>',
        'class="app-nav-section-title">SHOP</div>',
        '<span class="app-nav-text">Stores</span>',
        '<span class="app-nav-text">Compare Prices</span>',
        'class="app-nav-section-title">TOOLS</div>',
        '<span class="app-nav-text">Import</span>',
        '<span class="app-nav-text">Scan Barcode</span>',
        'class="app-nav-section-title">ACCOUNT</div>',
        '<span class="app-nav-text">Usage &amp; Billing</span>',
        '<span class="app-nav-text">Help &amp; Support</span>',
        '<span class="app-nav-text">Settings</span>',
    )
    positions = [navigation.index(label) for label in ordered_labels]

    assert positions == sorted(positions)
    assert navigation.count('<span class="app-nav-text">Import</span>') == 1
    assert 'data-app-page-target="importPage"' in navigation
    assert 'data-app-page-aliases="recipeUrlsPage importDocumentPage generateImagePage menuUrlPage menuDocumentPage"' in navigation
    for removed_label in ("Recipe URL", "Recipe Document", "Recipe Image", "Menu URL", "Menu Document"):
        assert f'<span class="app-nav-text">{removed_label}</span>' not in navigation
    assert "Stores / Store Links" not in navigation
    assert "Price Comparison" not in navigation
    assert 'href="{{ url_for(\'pantry_bp.pantry_coming_soon_route\') }}"' in navigation

    create_heading = import_workspace.index('id="createRecipesImportHeading"')
    menu_heading = import_workspace.index('id="importMenusHeading"')
    assert create_heading < menu_heading
    for page_target in (
        "recipeUrlsPage",
        "importDocumentPage",
        "generateImagePage",
        "menuUrlPage",
        "menuDocumentPage",
    ):
        assert f'data-app-page-target="{page_target}"' in import_workspace
    assert "Scan Barcode" not in import_workspace[create_heading:menu_heading + 1000]


def test_sidebar_navigation_uses_exact_lucide_outline_icon_mappings_only():
    sidebar = read_text("PushShoppingList/templates/includes/app_sidebar.html")
    navigation = read_text("PushShoppingList/templates/includes/app_navigation_sections.html")
    plan_promo = read_text("PushShoppingList/templates/includes/app_plan_promo.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")

    expected_usage = {
        "home": 1,
        "recipes": 1,
        "menus": 1,
        "cookbooks": 1,
        "shopping": 1,
        "pantry": 1,
        "meal": 1,
        "stores": 1,
        "price": 1,
        "import": 1,
        "barcode": 1,
        "billing": 1,
        "help": 1,
        "settings": 1,
    }
    for name, count in expected_usage.items():
        assert navigation.count(f'shell.sidebar_icon("{name}")') == count
        assert f'shell.app_icon("{name}")' not in navigation
    assert plan_promo.count('shell.sidebar_svg_icon("billing")') == 2

    exact_lucide_paths = (
        'd="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"',
        'd="M12 7v14"',
        'd="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"',
        'd="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"',
        'width="20" height="5" x="2" y="3" rx="1"',
        'width="18" height="18" x="3" y="4" rx="2"',
        'd="M17.774 10.31a1.12 1.12 0 0 0-1.549 0',
        'd="M12.586 2.586A2 2 0 0 0 11.172 2H4',
        'd="M8 5h13"',
        'd="M21 5v14"',
        'points="17 8 12 3 7 8"',
        'width="20" height="14" x="2" y="5" rx="2"',
        'd="M9.09 9a3 3 0 1 1 5.83 1c0 2-3 2-3 4"',
        'd="M12.22 2h-.44a2 2 0 0 0-2 2v.18',
    )
    for path in exact_lucide_paths:
        assert path in macros

    assert 'class="app-icon-svg app-sidebar-icon-svg"' in macros
    assert 'data-sidebar-icon="{{ name }}"' in macros
    assert "Lucide v1.24.0 outline icon geometry" in macros
    assert "shell.brand_mark()" in sidebar


def test_recipe_editor_sidebar_uses_the_same_import_task_groups():
    template = read_text("PushShoppingList/templates/recipe_edit_page.html")
    sidebar_template = read_text("PushShoppingList/templates/includes/app_sidebar.html")
    navigation = read_text("PushShoppingList/templates/includes/app_navigation_sections.html")

    assert '{% extends "layouts/app_layout.html" %}' in template
    assert '{% set app_active_nav_item = "recipes" %}' in template
    assert '<nav class="app-sidebar-nav"' not in template
    assert '{% include "includes/app_navigation_sections.html" %}' in sidebar_template
    assert '<span class="app-nav-text">Import</span>' in navigation
    assert "home_href ~ '#importPage'" in navigation
    assert 'data-app-page-aliases="recipeUrlsPage importDocumentPage generateImagePage menuUrlPage menuDocumentPage"' in navigation
    assert "url_for('pantry_bp.pantry_coming_soon_route')" in navigation


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


def test_home_and_recipe_editor_reuse_the_shared_logo_asset_from_app_layout():
    recipe_edit = read_text("PushShoppingList/templates/recipe_edit_page.html")
    index = read_text("PushShoppingList/templates/index.html")
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")

    assert '{% extends "layouts/app_layout.html" %}' in recipe_edit
    assert '{% extends "layouts/app_layout.html" %}' in index
    assert "images/ai-pantry-logo.svg" in layout
    assert "brand_mark_svg('#2eb66f')|urlencode" not in recipe_edit
    assert "brand_mark_svg('#2eb66f')|urlencode" not in index


def test_sidebar_import_targets_keep_existing_active_state_and_barcode_behavior():
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    navigation = read_text("PushShoppingList/templates/includes/app_navigation_sections.html")
    mobile_navigation = read_text("PushShoppingList/templates/includes/app_mobile_navigation.html")
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
    assert "function appShellNavPageTargets(link)" in script
    assert ".find(link => appShellNavPageTargets(link).includes(pageKey));" in script
    assert 'link.classList.toggle("is-active", Boolean(sameLinkKey));' in script
    assert 'link.setAttribute("aria-current", "page");' in script
    assert ".app-nav-link:hover," in css
    assert ".app-nav-link:focus-visible," in css
    assert ".app-sidebar-collapsed .app-nav-text," in css
    assert ".app-sidebar-collapsed .app-sidebar-promo-action-icon" in css
    assert "overflow-y: auto;" in css
    assert navigation.count('data-tooltip=') == 14
    assert navigation.count('aria-label=') == 14
    assert 'data-app-page-aliases="recipeUrlsPage importDocumentPage generateImagePage menuUrlPage menuDocumentPage"' in navigation
    assert 'data-app-mobile-nav-toggle' in mobile_navigation
    assert 'data-app-mobile-nav-drawer' in mobile_navigation
    assert 'data-app-mobile-nav-backdrop' in mobile_navigation
    assert "function setAppMobileNavigationOpen(open, options = {})" in script
    assert 'setAppMobileNavigationOpen(false, { restoreFocus: true });' in script
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
    topbar_end = html.index("</button>", topbar_start)
    topbar_markup = html[topbar_start:topbar_end]

    assert response.status_code == 200
    assert html.count('data-app-header') == 1
    assert html.count('aria-label="Primary navigation"') == 1
    assert 'class="app-account-avatar-image"' in topbar_markup
    assert 'src="https://example.com/avatar.jpg"' in topbar_markup
    assert 'referrerpolicy="no-referrer"' in topbar_markup
    assert "Nathaniel Tyler" in topbar_markup
    assert ">N<" not in topbar_markup
    assert html.count('id="appProfileMenuTrigger"') == 1
    assert html.count('id="appProfileMenu"') == 1
    assert 'aria-haspopup="menu"' in html
    assert 'aria-controls="appProfileMenu"' in html
    assert 'role="menu"' in html
    assert "nathaniel@example.com" in html
    for label in ("My Profile", "Billing &amp; Subscription", "Keyboard Shortcuts", "Send Feedback", "Sign Out"):
        assert label in html


def test_authenticated_full_page_templates_extend_the_single_app_layout():
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")
    authenticated_pages = (
        "PushShoppingList/templates/index.html",
        "PushShoppingList/templates/recipe_edit_page.html",
        "PushShoppingList/templates/master_data.html",
        "PushShoppingList/templates/pdfs.html",
        "PushShoppingList/templates/search_results.html",
        "PushShoppingList/templates/menus/cookbook_menu_pdf_log_page.html",
        "PushShoppingList/templates/menus/cookbook_menu_builder.html",
        "PushShoppingList/templates/menus/menu_builder.html",
        "PushShoppingList/templates/menus/menu_edit.html",
        "PushShoppingList/templates/menus/menu_preview.html",
        "PushShoppingList/templates/menus/menu_recipe_progress.html",
        "PushShoppingList/templates/menus/menu_view.html",
    )

    header_components = list((ROOT / "PushShoppingList/templates").rglob("app_header.html"))

    assert len(header_components) == 1
    assert layout.count('{% include "includes/app_header.html" %}') == 1
    assert layout.count('{% include "includes/app_sidebar.html" %}') == 1
    assert 'class="app-shell" data-app-layout' in layout
    assert 'class="app-main-shell" data-app-main-shell' in layout
    assert "data-app-content" in layout
    assert "{% block app_overlays %}{% endblock %}" in layout
    for page_path in authenticated_pages:
        page = read_text(page_path)
        assert '{% extends "layouts/app_layout.html" %}' in page
        assert '<header class="app-topbar"' not in page
        assert '<aside class="app-sidebar' not in page


def test_home_and_recipe_editor_reuse_the_single_app_header_and_account_control():
    home = read_text("PushShoppingList/templates/index.html")
    recipe_editor = read_text("PushShoppingList/templates/recipe_edit_page.html")
    layout = read_text("PushShoppingList/templates/layouts/app_layout.html")
    header = read_text("PushShoppingList/templates/includes/app_header.html")
    sidebar = read_text("PushShoppingList/templates/includes/app_sidebar.html")
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert "{% macro account_control(" in macros
    assert "current_user.display_name" in macros
    assert "Pro Plan" in macros
    assert '{% extends "layouts/app_layout.html" %}' in home
    assert '{% extends "layouts/app_layout.html" %}' in recipe_editor
    assert layout.count('{% include "includes/app_header.html" %}') == 1
    assert layout.count('{% include "includes/app_sidebar.html" %}') == 1
    assert header.count('<header class="app-topbar"') == 1
    assert sidebar.count('<aside class="app-sidebar"') == 1
    assert "data-app-sidebar" in sidebar
    assert "shell.account_control(current_user, is_guest_demo|default(false), account_href, in_shell)" in header
    assert '<header class="app-topbar"' not in home
    assert '<header class="app-topbar"' not in recipe_editor
    assert '<aside class="app-sidebar' not in home
    assert '<aside class="app-sidebar' not in recipe_editor
    assert 'class="app-toolbar-button app-account-button"' not in home
    assert 'class="app-toolbar-button app-account-button"' not in recipe_editor
    assert "recipe-edit-page-topbar" not in recipe_editor
    assert "recipe-edit-page-topbar" not in css
    assert ".app-header-search {" in css
    assert "flex: 1 1 auto;" in css
    assert "from PushShoppingList.services.user_account_service import current_public_user" in routes
    assert "current_user=current_public_user()," in routes


def test_header_profile_control_renders_accessible_grouped_dropdown_and_interactions():
    macros = read_text("PushShoppingList/templates/includes/app_shell_macros.html")
    css = read_text("PushShoppingList/static/css/app.css")
    script = read_text("PushShoppingList/static/js/app.js")

    menu_start = macros.index('<div class="app-profile-menu" data-profile-menu>')
    menu_end = macros.index("{% else %}", menu_start)
    menu_markup = macros[menu_start:menu_end]

    assert 'data-profile-menu-trigger' in menu_markup
    assert 'aria-haspopup="menu"' in menu_markup
    assert 'aria-expanded="false"' in menu_markup
    assert 'aria-controls="{{ profile_menu_id }}"' in menu_markup
    assert 'data-profile-menu-panel' in menu_markup
    assert 'role="menu"' in menu_markup
    assert menu_markup.count('role="menuitem"') == 12
    assert "current_user.email" in menu_markup
    assert "current_user.display_name" in menu_markup
    assert "Pro Plan" in menu_markup
    assert 'data-firebase-sign-out-form' in menu_markup
    assert "url_for('account_bp.sign_out_route')" in menu_markup

    expected_labels = (
        "ACCOUNT",
        "My Profile",
        "Account Settings",
        "Billing &amp; Subscription",
        "Security",
        "PREFERENCES",
        "Appearance",
        "Notifications",
        "Keyboard Shortcuts",
        "Language",
        "SUPPORT",
        "Help Center",
        "Send Feedback",
        "What&rsquo;s New",
        "Sign Out",
    )
    for label in expected_labels:
        assert label in menu_markup

    for sidebar_label in ("Recipes", "Cookbooks", "Shopping Lists", "Pantry", "Meal Planner"):
        assert f">{sidebar_label}<" not in menu_markup

    assert ".app-profile-menu-panel {" in css
    assert "top: calc(100% + 10px);" in css
    assert "right: 0;" in css
    assert "width: min(332px, calc(100vw - 24px));" in css
    assert "z-index: 18500;" in css
    assert ".app-profile-menu-item:focus-visible" in css
    assert ".app-profile-menu-sign-out:hover" in css

    assert "const HEADER_PROFILE_MENU_OPEN_DELAY_MS = 175;" in script
    assert "const HEADER_PROFILE_MENU_CLOSE_DELAY_MS = 200;" in script
    assert "function bindHeaderProfileMenus()" in script
    assert 'menu.addEventListener("pointerenter"' in script
    assert 'menu.addEventListener("pointerleave"' in script
    assert 'event.target.closest("[data-profile-menu]")' in script
    assert 'closeHeaderProfileMenu(openMenu, { focusTrigger: true });' in script
    for key in ("ArrowDown", "ArrowUp", "Home", "End", "Enter", "Escape"):
        assert f'event.key === "{key}"' in script or f'event.key !== "{key}"' in script


def test_recipe_edit_route_renders_exactly_one_shared_shell(monkeypatch, tmp_path):
    from PushShoppingList.services import user_account_service as accounts

    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    accounts.save_users({
        "users": [{
            "user_id": "shell-route-user",
            "username": "shell-route-user",
            "email": "shell-route@example.com",
            "account_status": "active",
        }]
    })
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "shell-route-user"
        response = client.get("/recipe/edit?url=https%3A%2F%2Fexample.test%2Frecipes%2Fsoup")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert html.count("data-app-layout>") == 1
    assert html.count("data-app-sidebar>") == 1
    assert html.count("data-app-header>") == 1
    assert html.count("data-app-main-shell>") == 1
    assert html.count("data-app-content") == 1


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
    assert "--app-sidebar-collapsed-width:" in css
    assert "--app-page-padding-inline:" in css
    assert "--app-shell-border-color:" in css
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
    assert "height: 100dvh;" in css
    assert "grid-template-rows: var(--app-toolbar-height) minmax(0, 1fr);" in css
    assert "grid-template-columns: var(--app-sidebar-width) minmax(0, 1fr);" in css
    assert "grid-template-columns: var(--app-sidebar-collapsed-width) minmax(0, 1fr);" in css
    assert "padding: 28px var(--app-page-padding-inline) 72px;" in css
    assert "overflow-y: auto;" in css
    assert ".app-shell-body:has(#recipesPage:not([hidden]))" not in css
    assert ".recipe-edit-page-main-shell" not in css
    assert ".recipe-edit-page-shell" not in css
    assert "calc(100vw - var(--app-sidebar-width)" not in css
    assert ".app-shell-body .app-card" in css
    assert ".app-shell-body .settings-workspace-section.app-card" in css
    assert ".app-shell-body :where(input, select, textarea)" in css
    assert ".app-shell-body :where(table)" in css
    tablet_shell = css[
        css.index("@media (min-width: 768px) and (max-width: 1099px)"):
        css.index("@media (max-width: 767px)")
    ]
    assert ".app-topbar-brand {\n        display: inline-flex;" in tablet_shell
    assert ".app-topbar-brand span:not(.app-brand-mark) {\n        display: none;" in tablet_shell
    assert ".app-header-search {\n        min-width: 220px;" in css
    assert "grid-template-columns: minmax(0, 1fr) auto auto;" in css


def test_app_header_preserves_import_and_profile_across_responsive_widths():
    header = read_text("PushShoppingList/templates/includes/app_header.html")
    css = read_text("PushShoppingList/static/css/app.css")

    assert header.index('class="app-header-search"') < header.index('class="app-toolbar-actions"')
    assert header.index('class="app-toolbar-actions"') < header.index('class="app-header-profile"')

    search_start = css.index(".app-header-search {")
    search_rule = css[search_start:css.index("}", search_start)]
    assert "flex: 1 1 auto;" in search_rule
    assert "min-width: 0;" in search_rule

    actions_start = css.index(".app-toolbar-actions {")
    actions_rule = css[actions_start:css.index("}", actions_start)]
    assert "flex: 0 0 auto;" in actions_rule
    assert "gap: 10px;" in actions_rule

    profile_start = css.index(".app-header-profile {")
    profile_rule = css[profile_start:css.index("}", profile_start)]
    assert "flex: 0 0 auto;" in profile_rule

    import_start = css.index(".app-toolbar-primary {")
    import_rule = css[import_start:css.index("}", import_start)]
    assert "flex: 0 0 auto;" in import_rule
    assert "white-space: nowrap;" in import_rule

    notification_start = css.index(".app-toolbar-icon-button {")
    notification_rule = css[notification_start:css.index("}", notification_start)]
    assert "flex: 0 0 auto;" in notification_rule

    search_input_start = css.index(".app-global-search input {")
    search_input_rule = css[search_input_start:css.index("}", search_input_start)]
    assert "padding: 0 82px 0 46px;" in search_input_rule

    preferred_width = css.index("@media (min-width: 1100px) and (max-width: 1280px)")
    shortcut_hidden = css.index("@media (max-width: 1150px)")
    plan_hidden = css.index("@media (min-width: 768px) and (max-width: 980px)")
    mobile = css.index("@media (max-width: 767px)")
    assert preferred_width < shortcut_hidden < plan_hidden < mobile

    mobile_shell = css[mobile:css.index("/* Desktop mockup fidelity pass", mobile)]
    assert ".app-import-label {\n        display: none;" in mobile_shell
    assert ".app-toolbar-primary {\n        width: 44px;" in mobile_shell
    assert ".app-account-label {\n        display: grid;" in mobile_shell
    assert ".app-account-label small {\n        display: none;" in mobile_shell
    assert "max-width: calc(100vw - 176px);" in mobile_shell


def test_full_page_tools_size_against_the_shared_main_content_not_the_viewport():
    app_css = read_text("PushShoppingList/static/css/app.css")
    menu_css = read_text("PushShoppingList/static/css/menu_builder.css")

    menu_workspace_start = menu_css.index(".menu-workspace,")
    menu_workspace_rule = menu_css[menu_workspace_start:menu_css.index("}", menu_workspace_start)]
    assert "width: 100%;" in menu_workspace_rule
    assert "max-width: none;" in menu_workspace_rule
    assert "100vw" not in menu_workspace_rule
    assert ".menu-builder-page {\n    min-height: 100vh;" not in menu_css

    assert ".recipe-edit-page-main-shell" not in app_css
    assert ".recipe-edit-page-shell" not in app_css
    assert "width: min(1680px, calc(100% - 48px));" not in app_css


def test_desktop_sidebar_logo_and_icons_use_readable_scale():
    css = read_text("PushShoppingList/static/css/app.css")
    desktop_shell = css[css.index("/* Desktop mockup fidelity pass"):]

    assert ".app-brand-mark {\n        flex-basis: 51px;\n        width: 51px;\n        height: 51px;" in desktop_shell
    assert ".app-nav-icon {\n        flex-basis: 23px;\n        width: 23px;\n        height: 23px;" in desktop_shell
    assert ".app-icon-svg {\n        width: 20px;\n        height: 20px;" in desktop_shell


def test_app_shell_navigation_reuses_existing_lazy_and_account_panel_functions():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function initAppShellNavigation()" in script
    assert "function appMainScrollRegion()" in script
    assert 'document.querySelector("[data-app-content]")' in script
    assert "function scrollAppMainBy(optionsOrX, y = 0)" in script
    assert "scrollAppMainBy(0, delta);" in script
    assert "function submitGlobalAppSearch(form)" in script
    assert "function initGlobalAppSearch()" in script
    assert "GLOBAL_APP_SEARCH_DEBOUNCE_MS = 250" in script
    assert "GLOBAL_APP_SEARCH_MIN_QUERY_LENGTH = 2" in script
    assert "new AbortController()" in script
    assert 'event.key === "ArrowDown" || event.key === "ArrowUp"' in script
    assert 'event.key === "Escape"' in script
    assert '["initGlobalAppSearch", initGlobalAppSearch]' in script
    assert "function submitRecipeEditGlobalSearch" not in script
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
