import re
from pathlib import Path

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service as accounts


ROOT = Path(__file__).resolve().parents[1]


def configure_auth_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")


def seeded_app(monkeypatch, tmp_path):
    configure_auth_storage(monkeypatch, tmp_path)
    accounts.save_users({
        "users": [{
            "user_id": "public-auth-user",
            "first_name": "Pantry",
            "last_name": "Cook",
            "username": "pantry-cook",
            "email": "cook@example.com",
            "auth_provider": "firebase",
            "account_status": "active",
        }]
    })
    app = create_app()
    app.config.update(TESTING=True)
    return app


def opening_tag(html, element_id):
    start = html.index(f'id="{element_id}"')
    tag_start = html.rfind("<", 0, start)
    tag_end = html.index(">", start)
    return html[tag_start:tag_end + 1]


def test_signed_out_index_renders_only_standalone_public_auth_page(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        response = client.get("/")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for marker in (
        "data-public-auth-page",
        "data-public-auth-layout",
        "data-public-auth-header",
        "data-public-auth-main",
        "data-public-auth-intro",
        "data-public-auth-card",
        "data-public-auth-privacy",
        "data-public-auth-footer",
    ):
        assert marker in html

    for authenticated_shell_marker in (
        "data-app-layout",
        "data-app-sidebar",
        "data-app-header",
        "data-app-global-search",
        "app-mobile-bottom-nav",
        "data-app-home-dashboard",
        "data-app-page-workspace",
        "data-settings-workspace",
        "data-global-collapse-controls",
    ):
        assert authenticated_shell_marker not in html

    assert 'static/js/app.js' not in html
    assert 'static/js/public-auth.js' in html


def test_public_auth_copy_features_footer_and_provider_claims_are_truthful(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)

    assert "Your recipes." in html
    assert "Smarter with AI." in html
    assert "Import from any website, menu, or photo." in html
    assert "AI extracts, organizes, and helps you cook" in html
    assert "and shop with confidence." in html

    feature_titles = (
        "Import Anything",
        "AI-Powered",
        "Smart Shopping",
        "Meal Planning",
        "Learn &amp; Improve",
        "Private &amp; Secure",
    )
    positions = [html.index(title) for title in feature_titles]
    assert positions == sorted(positions)
    assert html.count("data-public-auth-feature") == 6

    assert "Your sign-in is handled by Firebase Authentication." in html
    assert "AI Pantry does not store or have access to your password." in html
    assert html.count("AI Pantry does not store or have access to your password.") == 1
    assert "Continue with Google" in html
    assert "Continue with Microsoft" not in html
    assert "Continue with Apple" not in html

    for capability in (
        "Recipe Imports",
        "Smart Shopping Lists",
        "Meal Planning",
        "Private &amp; Secure",
    ):
        assert capability in html
    assert "&copy; 2026 AI Pantry" in html
    for fabricated_stat in ("10,000+", "5,000+", "2,000+", "99.9%"):
        assert fabricated_stat not in html


def test_public_auth_feature_icons_match_reference_mapping():
    template = (ROOT / "PushShoppingList/templates/public_auth.html").read_text(encoding="utf-8")
    icon_macros = (ROOT / "PushShoppingList/templates/includes/app_shell_macros.html").read_text(
        encoding="utf-8"
    )
    app_css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    expected_icons = (
        ("recipe-document-linked", "Import Anything"),
        ("brain-rounded", "AI-Powered"),
        ("shopping-cart", "Smart Shopping"),
        ("clipboard-checklist", "Meal Planning"),
        ("sparkles", "Learn &amp; Improve"),
        ("lock", "Private &amp; Secure"),
    )

    feature_grid = template[
        template.index('class="public-auth-feature-grid"'):
        template.index('data-public-auth-privacy')
    ]
    for icon_name, title in expected_icons:
        assert re.search(
            rf'svg_icon\("{re.escape(icon_name)}"\).*?<strong>{re.escape(title)}</strong>',
            feature_grid,
            re.DOTALL,
        )

    for obsolete_icon in ("brain", "infer-sparkles", "shield-check", "meal"):
        assert f'svg_icon("{obsolete_icon}")' not in feature_grid
    for new_icon in ("recipe-document-linked", "brain-rounded", "shopping-cart", "clipboard-checklist"):
        assert f'elif name == "{new_icon}"' in icon_macros

    feature_icon_css = app_css[
        app_css.index(".public-auth-feature-icon {"):
        app_css.index(".public-auth-feature > span:last-child")
    ]
    assert "width: 58px;" in feature_icon_css
    assert "height: 58px;" in feature_icon_css
    assert "width: 28px;" in feature_icon_css
    assert "height: 28px;" in feature_icon_css
    assert "stroke-width: 1.8;" in feature_icon_css
    assert ".public-auth-feature-icon-brain .app-icon-svg" in feature_icon_css
    assert "width: 32px;" in feature_icon_css
    assert "height: 32px;" in feature_icon_css


def test_public_auth_circled_icons_match_reference_without_changing_behavior():
    public_template = (ROOT / "PushShoppingList/templates/public_auth.html").read_text(encoding="utf-8")
    card_template = (ROOT / "PushShoppingList/templates/sections/public_auth_card.html").read_text(
        encoding="utf-8"
    )
    public_header = (ROOT / "PushShoppingList/templates/includes/public_page_macros.html").read_text(
        encoding="utf-8"
    )
    icon_macros = (ROOT / "PushShoppingList/templates/includes/app_shell_macros.html").read_text(
        encoding="utf-8"
    )
    app_css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    theme_control = public_header[
        public_header.index('class="public-auth-theme-control"'):
        public_header.index('data-public-theme-menu-panel')
    ]
    assert 'svg_icon("sun")' in theme_control
    assert 'svg_icon("sparkles")' not in theme_control
    assert 'data-public-theme-trigger' in theme_control
    assert 'svg_icon("chevron-down")' in public_header

    sign_in_form = card_template[
        card_template.index('id="firebaseSignInForm"'):
        card_template.index('id="firebaseCreateAccountForm"')
    ]
    assert 'class="public-auth-email-field"' in sign_in_form
    assert 'class="public-auth-email-icon" aria-hidden="true"' in sign_in_form
    assert 'svg_icon("mail")' in sign_in_form
    assert 'svg_icon("user-plus")' in sign_in_form
    assert 'data-auth-mode-target="create"' in sign_in_form

    guest_form = card_template[
        card_template.index('class="public-auth-guest-access"'):
        card_template.index('class="public-auth-legal"')
    ]
    assert 'svg_icon("user")' in guest_form
    assert 'action="{{ url_for(\'account_bp.guest_start_route\') }}"' in guest_form
    assert "Continue as Guest" in guest_form

    privacy_card = public_template[
        public_template.index('class="public-auth-privacy-card"'):
        public_template.index("</section>", public_template.index('class="public-auth-privacy-card"'))
    ]
    assert 'class="public-auth-privacy-icon">{{ shell.svg_icon("shield-check") }}' in privacy_card
    assert 'class="public-auth-privacy-art" aria-hidden="true"' in privacy_card
    assert "shell.privacy_shield_art()" in privacy_card

    for icon_name in ("sun", "mail", "user-plus", "brain-rounded"):
        assert f'elif name == "{icon_name}"' in icon_macros
    assert "macro privacy_shield_art()" in icon_macros
    assert "padding-right: 46px !important;" in app_css
    assert ".public-auth-email-icon" in app_css
    assert ".public-auth-privacy-art-shield" in app_css
    assert ".public-auth-privacy-art-decoration" in app_css
    assert ".public-auth-privacy-copy" in app_css
    assert "pointer-events: none;" in app_css


def test_privacy_art_uses_opaque_layered_shield_with_explicit_dark_theme_colors():
    icon_macros = (ROOT / "PushShoppingList/templates/includes/app_shell_macros.html").read_text(
        encoding="utf-8"
    )
    app_css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    artwork = icon_macros[
        icon_macros.index("macro privacy_shield_art()"):
        icon_macros.index("macro app_icon(name)")
    ]
    artwork_css = app_css[
        app_css.index(".public-auth-privacy-art {"):
        app_css.index(".public-auth-privacy-card h2")
    ]

    for layer in (
        "public-auth-privacy-art-shield-layers",
        "public-auth-privacy-art-shield",
        "public-auth-privacy-art-shield-inner",
        "public-auth-privacy-art-shield-facet",
        "public-auth-privacy-art-check",
    ):
        assert layer in artwork
        assert f".{layer}" in artwork_css
    assert 'transform="rotate(-2 126 69)"' in artwork
    assert "public-auth-privacy-art-highlight" not in artwork
    assert '--public-privacy-art-outer: #158b3b;' in artwork_css
    assert '--public-privacy-art-inner: #68d67d;' in artwork_css
    assert '--public-privacy-art-check: #08712c;' in artwork_css
    assert 'html[data-public-auth-theme="dark"] .public-auth-privacy-art' in artwork_css
    assert '--public-privacy-art-outer: #08713a;' in artwork_css
    assert '--public-privacy-art-inner: #42c979;' in artwork_css
    assert '--public-privacy-art-check: #063f22;' in artwork_css
    assert "stroke-width: 6;" in artwork_css


def test_auth_card_defaults_to_single_sign_in_mode_and_keeps_auth_contracts(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)

    assert "Welcome back" in html
    assert "Sign in to your AI Pantry account" in html
    assert "hidden" not in opening_tag(html, "firebaseSignInForm")
    assert "hidden" in opening_tag(html, "firebaseCreateAccountForm")
    assert "hidden" in opening_tag(html, "forgotPasswordForm")

    sign_in = html[html.index('id="firebaseSignInForm"'):html.index("</form>", html.index('id="firebaseSignInForm"'))]
    create = html[html.index('id="firebaseCreateAccountForm"'):html.index("</form>", html.index('id="firebaseCreateAccountForm"'))]
    forgot = html[html.index('id="forgotPasswordForm"'):html.index("</form>", html.index('id="forgotPasswordForm"'))]

    assert "data-firebase-sign-in-form" in sign_in
    assert 'name="identity"' in sign_in
    assert 'name="password"' in sign_in
    assert 'autocomplete="current-password"' in sign_in
    assert "data-firebase-google-sign-in" in sign_in
    assert "Sign in with Email" in sign_in
    assert 'name="remember_me"' in sign_in

    assert "data-firebase-create-form" in create
    for field_name in ("first_name", "last_name", "username", "email", "password", "confirm_password"):
        assert f'name="{field_name}"' in create
    assert "data-firebase-forgot-form" in forgot
    assert 'name="identity"' in forgot

    assert html.index('id="firebaseSignInForm"') < html.index("data-guest-demo-access")
    assert "Continue as Guest" in html
    assert "Explore with temporary demo data." in html
    assert "Nothing is saved permanently." in html

    legal_start = html.index('class="public-auth-legal"')
    legal_end = html.index("</p>", legal_start)
    legal = html[legal_start:legal_end]
    assert "Terms of Service" in legal
    assert "Privacy Policy" in legal
    assert '<a href="/terms">Terms of Service</a>' in legal
    assert '<a href="/privacy">Privacy Policy</a>' in legal
    assert "and acknowledge our" in legal
    assert "target=" not in legal


def test_public_auth_interactions_and_persistence_controls_are_wired():
    template = (ROOT / "PushShoppingList/templates/sections/public_auth_card.html").read_text(encoding="utf-8")
    public_header = (ROOT / "PushShoppingList/templates/includes/public_page_macros.html").read_text(
        encoding="utf-8"
    )
    public_script = (ROOT / "PushShoppingList/static/js/public-auth.js").read_text(encoding="utf-8")
    app_css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert 'data-auth-mode-target="create"' in template
    assert 'data-auth-mode-target="sign-in"' in template
    assert 'data-auth-mode-target="forgot"' in template
    assert "data-password-visibility-toggle" in template
    assert "function setAuthPanelMode(mode, options = {})" in public_script
    assert "function bindAuthPanelModeControls()" in public_script
    assert "function bindPasswordVisibilityControls()" in public_script
    assert "function bindPublicThemeControl()" in public_script
    assert 'localStorage.setItem(THEME_STORAGE_KEY, selectedTheme)' in public_script
    assert '<select data-public-theme-toggle' not in public_header
    assert 'aria-haspopup="menu"' in public_header
    assert 'aria-controls="publicThemeMenu"' in public_header
    assert 'role="menu"' in public_header
    assert public_header.count('role="menuitemradio"') == 1
    assert 'data-public-theme-option="{{ value }}"' in public_header
    assert 'aria-checked="{{ \'true\' if value == \'system\' else \'false\' }}"' in public_header
    assert "function bindPublicThemeMenu(menu)" in public_script
    assert "function closePublicThemeMenu(menu, options = {})" in public_script
    assert "function focusAdjacentPublicThemeOption(menu, direction)" in public_script
    for key in ('"ArrowDown"', '"ArrowUp"', '"Home"', '"End"', '"Enter"', '"Escape"'):
        assert key in public_script
    assert 'event.target?.closest("[data-public-theme-menu]")' in public_script
    assert '.public-auth-theme-option[aria-checked="true"]' in app_css
    assert "top: calc(100% + 8px);" in app_css
    assert "right: 0;" in app_css
    assert "max-width: calc(100vw - 24px);" in app_css
    assert "max-height: calc(100dvh - 90px);" in app_css
    assert "z-index: 200;" in app_css

    assert "browserLocalPersistence" in firebase_script
    assert "browserSessionPersistence" in firebase_script
    assert "async function setFirebasePersistenceForForm(form)" in firebase_script
    assert "await setFirebasePersistenceForForm(form);" in firebase_script
    assert firebase_script.count("await setFirebasePersistenceForForm(form);") == 2
    assert 'while (headingBlock && headingBlock.parentElement !== form)' in firebase_script
    assert 'headingBlock.insertAdjacentElement("afterend", status);' in firebase_script


def test_public_theme_menu_renders_three_accessible_high_contrast_options(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)

    assert 'data-public-theme-trigger' in html
    assert 'aria-label="Color theme: System"' in html
    assert 'aria-haspopup="menu"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="publicThemeMenu"' in html
    assert 'role="menu"' in html
    assert html.count('role="menuitemradio"') == 3
    for value, label in (("system", "System"), ("light", "Light"), ("dark", "Dark")):
        assert f'data-public-theme-option="{value}"' in html
        assert f"<span>{label}</span>" in html
    assert '<select data-public-theme-toggle' not in html


def test_signed_in_and_guest_sessions_keep_the_normal_application_shell(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "public-auth-user"
        signed_in_html = client.get("/").get_data(as_text=True)

    assert signed_in_html.count("data-app-layout") == 1
    assert signed_in_html.count("data-app-sidebar>") == 1
    assert signed_in_html.count("data-app-header>") == 1
    assert "data-public-auth-page" not in signed_in_html
    assert 'static/js/app.js' in signed_in_html
    assert 'static/js/public-auth.js' not in signed_in_html

    with app.test_client() as client:
        client.get("/guest/start")
        guest_html = client.get("/").get_data(as_text=True)

    assert guest_html.count("data-app-layout") == 1
    assert guest_html.count("data-app-sidebar>") == 1
    assert guest_html.count("data-app-header>") == 1
    assert "data-public-auth-page" not in guest_html
    assert 'static/js/app.js' in guest_html
    assert 'static/js/public-auth.js' not in guest_html
    assert "Guest Demo Mode" in guest_html
    assert "Demo auto-deletes in" in guest_html


def test_reset_and_two_factor_states_stay_in_the_standalone_public_surface(monkeypatch, tmp_path):
    app = seeded_app(monkeypatch, tmp_path)

    with app.test_client() as client:
        reset_html = client.get("/?reset_token=test-token").get_data(as_text=True)
        with client.session_transaction() as session:
            session["pending_2fa_user_id"] = "public-auth-user"
        two_factor_html = client.get("/").get_data(as_text=True)

    assert "data-public-auth-page" in reset_html
    assert "data-app-layout" not in reset_html
    assert "Reset Password" in reset_html
    assert 'value="test-token"' in reset_html
    assert 'id="firebaseSignInForm"' not in reset_html

    assert "data-public-auth-page" in two_factor_html
    assert "data-app-layout" not in two_factor_html
    assert "Two-Factor Verification" in two_factor_html
    assert 'id="firebaseSignInForm"' not in two_factor_html
