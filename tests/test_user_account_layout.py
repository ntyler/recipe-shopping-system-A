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


def test_two_factor_disable_uses_email_verification_link():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")

    assert "Email Disable Verification Link" in template
    assert "Email a one-time verification link to {{ current_user.email }}" in template
    assert "Disable Two-Factor Authentication for {{ two_factor_recovery_user.email }}" in template
    assert "action=\"{{ url_for('account_bp.disable_two_factor_route') }}\"" not in template
