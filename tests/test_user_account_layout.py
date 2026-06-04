from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_two_factor_remember_checkbox_text_stays_adjacent():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="user-two-factor-checkbox"' in template
    assert "Remember this browser for 30 days" in template
    assert ".user-two-factor-checkbox input[type=\"checkbox\"]" in css
    assert "width: 20px !important;" in css
    assert "justify-content: flex-start;" in css


def test_verified_email_menu_action_is_disabled():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "{% if current_user.email_verified %}" in template
    assert "Email Verified" in template
    assert "Verify Email" in template
    assert 'data-firebase-verify-email' in template
    assert ".user-account-menu-panel button:disabled" in css
    assert ".user-account-menu-disabled" in css


def test_account_action_token_pages_stay_focused_and_visible():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "account-action-token" in index_template
    assert "{% elif not account_action_token %}" in account_template
    assert "cancelAccountActionLink()" in account_template
    assert "body.account-action-token.screen-preview-active #appContent" in css
    assert "body.account-action-token .app-content > :not(#userAccountSection)" in css
    assert "function hasAccountActionToken()" in script
    assert 'setScreenPreviewMode("live", { persist: false })' in script
    assert "function cancelAccountActionLink()" in script


def test_two_factor_disable_success_cleans_up_firebase_auto_sync():
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert 'two_factor_disabled="1"' in route
    assert "function needsPostTwoFactorDisableSignOut()" in script
    assert "async function finishPostTwoFactorDisableSignOut()" in script
    assert 'removeQueryParams(["two_factor_disabled"])' in script
    assert "if (needsPostTwoFactorDisableSignOut())" in script


def test_two_factor_panel_forms_return_to_panel_after_refresh():
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert "def two_factor_panel_redirect" in route
    assert 'account_panel", "two_factor"' in route
    assert '_anchor="accountTwoFactorPanel"' in route
    assert 'request.args.get("account_panel") == "two_factor"' in template
    assert "data-two-factor-return-form" in template
    assert "TWO_FACTOR_PANEL_RETURN_KEY" in script
    assert "scrollToPanel(\"auto\")" in script


def test_pending_two_factor_setup_confirmation_copy_is_less_alarming():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")

    assert 'pending_two_factor_context == "setup_confirmation"' in template
    assert "Two-factor authentication was enabled. Confirm the new code once" in template
    assert "Two-Factor Authentication Enabled" in template
    assert "Enter the code from your authenticator app to confirm setup." in template
    assert "Confirm Two-Factor Setup" in template


def test_two_factor_disable_has_code_and_email_recovery_paths():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")

    assert "Use your authenticator app or a backup code to disable two-factor authentication now." in template
    assert "action=\"{{ url_for('account_bp.disable_two_factor_route') }}\"" in template
    assert "Authenticator or Backup Code" in template
    assert "Disable Two-Factor Authentication</button>" in template
    assert "Lost authenticator or backup codes?" in template
    assert "Email Disable Verification Link" in template
    assert "Email a one-time verification link to {{ current_user.email }}" in template
    assert "Disable Two-Factor Authentication for {{ two_factor_recovery_user.email }}" in template
