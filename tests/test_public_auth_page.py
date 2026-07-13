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
    assert "&copy; 2026 AI Pantry. All rights reserved." in html
    for fabricated_stat in ("10,000+", "5,000+", "2,000+", "99.9%"):
        assert fabricated_stat not in html


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
    assert "<a " not in legal


def test_public_auth_interactions_and_persistence_controls_are_wired():
    template = (ROOT / "PushShoppingList/templates/sections/public_auth_card.html").read_text(encoding="utf-8")
    public_script = (ROOT / "PushShoppingList/static/js/public-auth.js").read_text(encoding="utf-8")
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

    assert "browserLocalPersistence" in firebase_script
    assert "browserSessionPersistence" in firebase_script
    assert "async function setFirebasePersistenceForForm(form)" in firebase_script
    assert "await setFirebasePersistenceForForm(form);" in firebase_script
    assert firebase_script.count("await setFirebasePersistenceForForm(form);") == 2
    assert 'while (headingBlock && headingBlock.parentElement !== form)' in firebase_script
    assert 'headingBlock.insertAdjacentElement("afterend", status);' in firebase_script


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
