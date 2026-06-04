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


def test_account_settings_editor_has_header_close_and_closes_menu():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert '<h3>Account Settings</h3>' in template
    assert "data-user-profile-close" in template
    assert "toggleUserProfileEditor(false)" in template
    assert ".user-account-edit-header" in css
    assert "function toggleUserProfileEditor(open = null)" in script
    assert 'document.querySelector("[data-account-menu]")' in script
    assert "const isAlreadyOpen = !form.hidden" in script
    assert "if (!explicitState && isAlreadyOpen)" in script
    assert "accountMenu.open = false" in script


def test_mobile_account_dates_stack_left_aligned():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    mobile_start = css.index("@media (max-width: 650px)", css.index(".user-account-profile"))
    detail_start = css.index(".user-account-detail-list {", mobile_start)
    detail_end = css.index(".user-account-actions", detail_start)
    mobile_detail_css = css[detail_start:detail_end]

    assert "width: min(100%, 240px);" in mobile_detail_css
    assert "text-align: left;" in mobile_detail_css
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_detail_css
    assert "justify-items: start;" in mobile_detail_css


def test_admin_support_view_is_admin_only_reasoned_and_audited():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    support_template = (ROOT / "PushShoppingList/templates/sections/admin_support.html").read_text(encoding="utf-8")
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    service = (ROOT / "PushShoppingList/services/admin_support_service.py").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "admin_support_dashboard.is_admin" in index_template
    assert 'id="adminSupportSection"' in support_template
    assert 'name="support_reason"' in support_template
    assert "required" in support_template
    assert "open_admin_support_record_route" in route
    assert "is_admin_user(admin_user)" in route
    assert "record_support_access" in service
    assert "password_hash" not in support_template
    assert "two_factor.secret" not in support_template
    assert ".admin-support-card" in css


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


def test_screen_preview_mode_resets_when_preview_controls_are_absent():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert 'document.getElementById("screenSettingsCard")' in script
    assert 'document.getElementById("screenPreviewStage")' in script
    assert 'localStorage.setItem(SCREEN_PREVIEW_MODE_KEY, "live")' in script
    assert 'setScreenPreviewMode("live", { persist: false })' in script


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


def test_two_factor_close_returns_to_account_profile():
    script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert "const scrollToAccountProfile" in script
    assert 'document.querySelector(".user-account-profile")' in script
    assert 'document.getElementById("userAccountSection")' in script
    assert "const clearTwoFactorPanelLocation" in script
    assert 'url.searchParams.delete("account_panel")' in script
    assert 'url.hash = "userAccountSection"' in script
    assert 'scrollToAccountProfile("auto")' in script


def test_pending_two_factor_setup_confirmation_copy_is_less_alarming():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")

    assert 'pending_two_factor_context == "setup_confirmation"' in template
    assert "Two-factor authentication was enabled. Confirm the new code once" in template
    assert "Two-Factor Authentication Enabled" in template
    assert "Enter the code from your authenticator app to confirm setup." in template
    assert "Confirm Two-Factor Setup" in template


def test_two_factor_disable_has_code_and_email_recovery_paths():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "Use your authenticator app or a backup code to disable two-factor authentication now." in template
    assert "action=\"{{ url_for('account_bp.disable_two_factor_route') }}\"" in template
    assert "Authenticator or Backup Code" in template
    assert "Disable Two-Factor Authentication</button>" in template
    assert "Lost authenticator or backup codes?" in template
    assert "Email Disable Verification Link" in template
    assert "Email a one-time verification link to {{ current_user.email }}" in template
    assert "Disable Two-Factor Authentication for {{ two_factor_recovery_user.email }}" in template

    recovery_style_start = css.index("#accountTwoFactorPanel .user-two-factor-recovery-request-form {")
    recovery_style_end = css.index("}", recovery_style_start)
    recovery_style = css[recovery_style_start:recovery_style_end]
    assert "border:" not in recovery_style
    assert "background:" not in recovery_style


def test_regenerate_backup_codes_returns_to_top_of_account_section():
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")

    form_start = template.index("regenerate_two_factor_backup_codes_route")
    form_end = template.index("</form>", form_start)
    regenerate_form = template[form_start:form_end]

    assert 'return redirect(url_for("main_bp.index", _anchor="userAccountSection"))' in route
    assert "data-two-factor-return-form" not in regenerate_form
