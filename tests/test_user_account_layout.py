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


def test_account_menu_uses_compact_grouped_dropdown_style():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    menu_start = template.index('<details class="user-account-menu" data-account-menu>')
    menu_end = template.index("</details>", menu_start)
    menu_markup = template[menu_start:menu_end]

    assert 'aria-haspopup="menu"' in menu_markup
    assert 'aria-expanded="false"' in menu_markup
    assert 'role="menu"' in menu_markup
    assert 'role="menuitem"' in menu_markup
    assert 'class="sr-only">Account Menu</span>' in menu_markup
    assert "user-account-menu-trigger-icon" in menu_markup
    for label in ("PROFILE", "SECURITY", "COMMUNICATIONS", "SESSION", "DANGER ZONE"):
        assert f">{label}</div>" in menu_markup
    for label in (
        "⚙ Account Settings",
        "🔔 Account Notices",
        "🔒 Change Password",
        "✅ Email Verified",
        "🛡 Two-Factor Authentication",
        "📱 Push Notifications",
        "💬 Feedback &amp; Support",
        "↪ Sign Out",
        "🗑 Delete Account",
    ):
        assert label in menu_markup
    assert menu_markup.index(">SESSION</div>") < menu_markup.index("↪ Sign Out")
    assert menu_markup.index(">DANGER ZONE</div>") < menu_markup.index("🗑 Delete Account")
    assert menu_markup.index("↪ Sign Out") < menu_markup.index("🗑 Delete Account")
    assert "user-account-menu-item" in menu_markup
    assert "user-account-menu-danger" in menu_markup
    assert 'class="secondary"' not in menu_markup
    assert 'class="danger"' not in menu_markup
    assert ".user-account-menu-panel {" in css
    assert "width: min(320px, calc(100vw - 32px));" in css
    assert "overflow-y: auto;" in css
    assert "var(--submenu-bg)" in css
    assert ".user-account-menu-section-title" in css
    assert ".user-account-menu-panel .user-account-menu-item" in css
    assert ".user-account-menu-panel .user-account-menu-danger" in css
    assert "function bindAccountMenuDropdowns()" in script
    assert "function closeAccountMenuDropdown(menu, options = {})" in script
    assert 'event.target.closest("[data-account-menu]")' in script
    assert 'event.key !== "Escape"' in script


def test_account_settings_editor_has_header_close_and_closes_menu():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert '<h3>Account Settings</h3>' in template
    assert "user-account-settings-divider" in template
    assert "app-section-divider recipe-entry-section-divider user-account-settings-divider" in template
    assert "data-user-profile-close" in template
    assert "toggleUserProfileEditor(false)" in template
    assert ".user-account-edit-header" in css
    assert ".user-account-settings-divider" in css
    assert "border: 0;" in css
    assert "background: transparent;" in css
    assert "function toggleUserProfileEditor(open = null)" in script
    assert "function scrollToUserAccountProfile(behavior = \"auto\")" in script
    assert "function scrollToUserAccountTop(behavior = \"auto\")" in script
    assert 'document.querySelector(".user-account-profile")' in script
    assert 'document.getElementById("userAccountSection")' in script
    assert 'document.querySelector("[data-account-menu]")' in script
    assert "const isAlreadyOpen = !form.hidden" in script
    assert "if (!explicitState && isAlreadyOpen)" in script
    assert "accountMenu.open = false" in script
    assert "form.scrollIntoView({ behavior: \"smooth\", block: \"start\" })" in script
    assert 'scrollToUserAccountProfile("auto")' in script
    assert "form.querySelector(\"[data-user-profile-close]\")" in script
    assert "firstControl.focus({ preventScroll: true })" in script
    assert "#userProfileEditForm, [data-account-notices-panel]" in firebase_script
    assert 'window.scrollToUserAccountProfile("auto")' in firebase_script


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
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
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
    assert '"actorUid":' in service
    assert '"actorPrivateEmail":' in service
    assert '"actorPublicEmail":' in service
    assert "get_public_support_identity(actor_private_email)" in service
    assert "support_access_notices" in account_template
    assert "Account Notices" in account_template
    assert 'id="accountNoticesPanel"' in account_template
    assert "data-account-notices-panel" in account_template
    assert "user-account-notices-divider" in account_template
    assert "app-section-divider recipe-entry-section-divider user-account-notices-divider" in account_template
    assert "onclick=\"return toggleAccountNoticesPanel()\"" in account_template
    assert "onclick=\"return toggleAccountNoticesPanel(false)\"" in account_template
    assert "Feedback &amp; Support" in account_template
    assert "onclick=\"return openFeedbackSupportSection()\"" in account_template
    assert 'aria-controls="feedbackSupportSection"' in account_template
    assert "View account access history" in account_template
    assert "data-account-access-history-toggle" in account_template
    assert "admin_support_history" in account_template
    assert "notice.actorPublicEmail" in account_template
    assert "notice.admin_email" not in account_template
    assert "entry.actorPrivateEmail" in support_template
    assert ".user-account-access-notices" in css
    assert ".user-account-notices-divider" in css
    assert ".user-account-access-notices[hidden]" in css
    assert ".user-account-access-notices-actions" in css
    assert ".user-account-access-history-toggle" in css
    assert ".user-account-access-list[hidden]" in css
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")
    assert "[data-account-notices-panel]" in firebase_script
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    assert 'const SUPPORT_EMAIL = "support@recipeshoppinglist.com";' in script
    assert 'const SUPPORT_ADMIN_EMAILS = ["ntylerbert@gmail.com"];' in script
    assert "function getPublicSupportEmail(email)" in script
    assert "function getPublicSupportIdentity(email)" in script
    assert "? SUPPORT_EMAIL" in script
    assert "function openFeedbackSupportSection()" in script
    assert "function toggleAccountNoticesPanel(open = null)" in script
    assert "function toggleAccountAccessHistory(button)" in script
    assert "password_hash" not in support_template
    assert "two_factor.secret" not in support_template
    assert ".admin-support-card" in css

    notices_css_start = css.index(".user-account-access-notices {")
    notices_css_end = css.index(".user-account-notices-divider", notices_css_start)
    notices_css = css[notices_css_start:notices_css_end]
    assert "padding: 0;" in notices_css
    assert "border: 0;" in notices_css
    assert "background: transparent;" in notices_css


def test_feedback_support_follows_account_and_closes_to_profile():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    feedback_template = (ROOT / "PushShoppingList/templates/sections/feedback_support.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    account_include = '{% include "sections/user_account.html" %}'
    feedback_include = '{% include "sections/feedback_support.html" %}'
    push_panel_marker = 'data-push-notifications-panel'
    two_factor_panel_marker = 'data-two-factor-panel'

    assert index_template.index(account_include) < index_template.index("{% if not current_user %}")
    assert index_template.count(feedback_include) == 1
    assert account_template.index(push_panel_marker) < account_template.index(feedback_include)
    assert account_template.index(feedback_include) < account_template.index(two_factor_panel_marker)
    assert "{% set feedback_support_account_panel = true %}" in account_template
    assert "data-feedback-support-panel" in feedback_template
    assert "user-feedback-support-panel" in feedback_template
    assert "data-feedback-support-close" in feedback_template
    assert "onclick=\"return closeFeedbackSupportSection()\"" in feedback_template
    assert "user-push-panel-header feedback-support-panel-header" in feedback_template
    assert "function closeFeedbackSupportSection()" in script
    assert 'toggleCardCollapse("feedback-support")' in script
    assert "function hideAccountPanelsForFeedback(exceptPanel = null)" in script
    assert "[data-feedback-support-panel]" in script
    assert "[data-feedback-support-panel]" in firebase_script
    assert 'scrollToUserAccountProfile("auto")' in script
    assert ".user-feedback-support-panel" in css
    assert ".feedback-support-content" in css


def test_feedback_support_tickets_are_compact_collapsible_portal_rows():
    support_template = (ROOT / "PushShoppingList/templates/sections/feedback_support.html").read_text(encoding="utf-8")
    ticket_template = (ROOT / "PushShoppingList/templates/sections/feedback_ticket.html").read_text(encoding="utf-8")
    admin_ticket_template = (ROOT / "PushShoppingList/templates/sections/feedback_admin_ticket.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "feedback-form-attachments-heading" in support_template
    assert "Attachments" in support_template
    assert "Collapse All Feedback" in support_template
    assert "collapseAllFeedbackTickets()" in support_template
    assert "data-feedback-ticket" in ticket_template
    assert "data-feedback-ticket-toggle" in ticket_template
    assert 'aria-expanded="false"' in ticket_template
    assert "data-feedback-ticket-body hidden" in ticket_template
    assert "feedback-ticket-badges" in ticket_template
    assert "Last Updated {{ feedback.display_updated_at }}" in ticket_template
    assert "Support Team" in ticket_template
    assert "{{ feedback.support_public_email }}" in ticket_template
    assert "feedback.user_attachments" in ticket_template
    assert "attachment.display_label" in ticket_template
    assert "<strong>{{ event.event }}</strong>" in ticket_template
    assert "<strong>{{ event.event }}</strong>" in admin_ticket_template
    assert ".feedback-ticket-summary" in css
    assert ".feedback-ticket-badges" in css
    assert ".feedback-ticket-body[hidden]" in css
    assert ".feedback-form-attachments-heading" in css
    assert ".feedback-section-actions" in css
    assert ".feedback-collapse-all-btn" in css
    assert ".feedback-attachments" in css
    assert ".feedback-timeline::before" in css
    assert "function toggleFeedbackTicket(toggle)" in script
    assert "function collapseAllFeedbackTickets()" in script
    assert "function bindFeedbackTickets()" in script
    assert 'window.matchMedia("(max-width: 650px)")' in script
    assert "closeSiblingFeedbackTickets(ticket)" in script
    assert "expandFeedbackTicketFromHash()" in script
    assert "bindFeedbackTickets();" in script
    assert "bindAccountMenuDropdowns();" in script


def test_push_notifications_panel_uses_divider_without_outer_border():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "user-push-notifications-divider" in template
    assert "app-section-divider recipe-entry-section-divider user-push-notifications-divider" in template
    assert ".user-push-notifications-divider" in css

    push_css_start = css.index(".user-push-notifications-panel {")
    push_css_end = css.index(".user-push-notifications-divider", push_css_start)
    push_css = css[push_css_start:push_css_end]
    assert "padding: 0;" in push_css
    assert "border: 0;" in push_css
    assert "background: transparent;" in push_css


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
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "def two_factor_panel_redirect" in route
    assert 'account_panel", "two_factor"' in route
    assert '_anchor="accountTwoFactorPanel"' in route
    assert 'request.args.get("account_panel") == "two_factor"' in template
    assert "data-two-factor-return-form" in template
    assert "user-two-factor-divider" in template
    assert "app-section-divider recipe-entry-section-divider user-two-factor-divider" in template
    assert "TWO_FACTOR_PANEL_RETURN_KEY" in script
    assert "scrollToPanel(\"auto\")" in script
    assert ".user-two-factor-divider" in css

    two_factor_css_start = css.index(".user-two-factor-card {")
    two_factor_css_end = css.index(".user-two-factor-divider", two_factor_css_start)
    two_factor_css = css[two_factor_css_start:two_factor_css_end]
    assert "padding: 0;" in two_factor_css
    assert "border: 0;" in two_factor_css
    assert "background: transparent;" in two_factor_css


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
