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
    assert '<header id="appPageHeader" class="app-page-header">' in template
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
    assert 'data-app-nav-action="ai-pantry"' in template
    assert 'data-app-nav-lazy-section="pantry"' in template
    assert 'data-app-nav-lazy-section="current-recipes"' in template
    assert 'data-app-nav-lazy-section="recipe-view"' in template
    assert 'onclick="return collapseAllShoppingListPage()"' in template
    assert 'onclick="return expandAllShoppingListPage()"' in template
    assert 'data-public-workspace="{{ \'1\' if not current_user and not is_guest_demo else \'0\' }}"' in template


def test_app_css_defines_scoped_design_tokens_and_responsive_shell():
    css = read_text("PushShoppingList/static/css/app.css")

    assert "--app-bg:" in css
    assert "--app-surface:" in css
    assert "--app-primary:" in css
    assert "--app-sidebar-width:" in css
    assert "--app-content-max:" in css
    assert "--app-control-height:" in css
    assert "--app-radius-lg:" in css
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
    assert ".app-mobile-bottom-nav {" in css
    assert "@media (max-width: 1099px)" in css
    assert "@media (min-width: 768px) and (max-width: 1099px)" in css
    assert "@media (max-width: 767px)" in css
    assert ".app-shell-body .app-card" in css
    assert ".app-shell-body :where(input, select, textarea)" in css
    assert ".app-shell-body :where(table)" in css


def test_app_shell_navigation_reuses_existing_lazy_and_account_panel_functions():
    script = read_text("PushShoppingList/static/js/app.js")

    assert "function initAppShellNavigation()" in script
    assert "function submitAppGlobalSearch(form)" in script
    assert "async function activateAppShellNavLink(link" in script
    assert 'openAiPantryPanel({ targetId: targetId || "aiPantrySection" })' in script
    assert "toggleUsageDashboardPanel(true)" in script
    assert "openFeedbackSupportSection()" in script
    assert "toggleUserProfileEditor(true)" in script
    assert "await loadLazySection(lazySection" in script
    assert 'String(event.key || "").toLowerCase() === "k"' in script
    assert 'document.querySelector("[data-app-global-search]")' in script
    assert '["initAppShellNavigation", initAppShellNavigation]' in script
