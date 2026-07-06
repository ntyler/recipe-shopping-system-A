from pathlib import Path

from PushShoppingList.services import user_account_service as accounts


ROOT = Path(__file__).resolve().parents[1]


def test_ntylerbert_gmail_is_admin():
    user = {"email": "ntylerbert@gmail.com"}

    assert accounts.is_admin_user(user) is True
    assert accounts.public_user(user)["role"] == "Admin"


def test_delegated_admin_access_is_record_backed():
    user = {"email": "helper@example.com", "admin_access_enabled": True}
    public = accounts.public_user(user)

    assert accounts.is_admin_user(user) is True
    assert public["role"] == "Admin"
    assert public["admin_access_enabled"] is True
    assert public["admin_access_locked"] is False
    assert accounts.can_manage_admin_access(user) is False


def test_two_factor_remember_checkbox_text_stays_adjacent():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert 'class="user-two-factor-checkbox"' in template
    assert "Remember this browser for 30 days" in template
    assert ".user-two-factor-checkbox input[type=\"checkbox\"]" in css
    assert "width: 20px !important;" in css
    assert "justify-content: flex-start;" in css


def test_guest_demo_access_is_primary_path_above_account_forms():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    app_config = (ROOT / "PushShoppingList/app.py").read_text(encoding="utf-8")

    demo_start = template.index('class="user-guest-demo-access"')
    create_start = template.index('id="firebaseCreateAccountForm"')
    sign_in_start = template.index('id="firebaseSignInForm"')

    assert demo_start < create_start < sign_in_start
    assert 'method="GET"' in template[demo_start:create_start]
    assert "url_for('account_bp.guest_start_route')" in template[demo_start:create_start]
    assert "✨ Guest Demo" in template[demo_start:create_start]
    assert "Try Demo Without Password" in template[demo_start:create_start]
    assert 'aria-label="Start temporary guest demo session"' in template[demo_start:create_start]
    assert "Explore with temporary demo data. Nothing is saved permanently." in template[demo_start:create_start]
    assert 'data-guest-countdown' in template[demo_start:create_start]
    assert "Demo auto-deletes in" in template[demo_start:create_start]
    assert "url_for('account_bp.guest_delete_route')" in template[demo_start:create_start]
    assert "Delete Demo Session" in template[demo_start:create_start]
    assert 'data-guest-auth-choice="create"' in template[demo_start:create_start]
    assert 'data-guest-auth-choice="sign-in"' in template[demo_start:create_start]
    assert "Create Full Account" in template[demo_start:create_start]
    assert 'data-guest-auth-form="create" hidden' in template
    assert 'data-guest-auth-form="sign-in" hidden' in template
    assert ".user-guest-demo-access {" in css
    assert "width: min(100%, 500px);" in css
    assert ".user-guest-demo-access button {" in css
    assert "background: #115e9f;" in css
    assert ".user-guest-demo-access button:focus-visible" in css
    assert ".user-guest-session-panel {" in css
    assert ".user-guest-countdown strong" in css
    assert ".user-guest-delete-btn" in css
    assert ".user-guest-auth-choice {" in css
    assert ".user-guest-auth-choice button {" in css
    assert "function initGuestCountdowns()" in script
    assert "function formatGuestCountdown(msRemaining)" in script
    assert "function bindGuestAuthChoices()" in script
    assert "function showGuestAuthForm(choice, options = {})" in script
    assert '["initGuestCountdowns", initGuestCountdowns]' in script
    assert '["bindGuestAuthChoices", bindGuestAuthChoices]' in script
    assert "@media (max-width: 650px)" in css
    assert '@account_bp.route("/guest/start", methods=["GET"])' in route
    assert '@account_bp.route("/guest/delete", methods=["POST"])' in route
    assert "account_bp.guest_start_route" in app_config
    assert "account_bp.guest_delete_route" in app_config


def test_guest_demo_banner_has_create_and_sign_in_shortcuts():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    banner_start = index_template.index('class="guest-demo-banner"')
    banner_end = index_template.index("</div>", index_template.index('class="guest-demo-banner-actions"', banner_start))
    banner_markup = index_template[banner_start:banner_end]

    assert "guest-demo-banner-actions" in banner_markup
    assert 'data-guest-auth-choice="create"' in banner_markup
    assert 'data-guest-auth-choice="sign-in"' in banner_markup
    assert "Create Full Account" in banner_markup
    assert "Sign In" in banner_markup
    assert ".guest-demo-banner-content {" in css
    assert ".guest-demo-banner-actions {" in css
    assert ".guest-demo-banner a.secondary" in css


def test_guest_start_route_returns_to_guest_account_section():
    from PushShoppingList.app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "signed-in-user"
            session["firebase_uid"] = "firebase-user"

        response = client.get("/guest/start")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#userAccountSection")

        with client.session_transaction() as session:
            assert "user_id" not in session
            assert "firebase_uid" not in session


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
    for label in ("PROFILE", "USAGE &amp; BILLING", "ACTIVITY", "DISPLAY", "SECURITY", "COMMUNICATIONS", "SESSION", "DANGER ZONE"):
        assert f">{label}</div>" in menu_markup
    for label in (
        "Account Settings",
        "Account Notices",
        "AI Usage &amp; Billing",
        "Chat GPT Models",
        "Job Activity / Import Progress",
        "Screen Settings",
        "Change Password",
        "Email Verified",
        "Two-Factor Authentication",
        "Push Notifications",
        "Feedback &amp; Support",
        "Sign Out",
        "Delete Account",
    ):
        assert label in menu_markup
    assert menu_markup.index(">PROFILE</div>") < menu_markup.index("Account Settings")
    assert menu_markup.index(">USAGE &amp; BILLING</div>") < menu_markup.index("AI Usage &amp; Billing")
    assert menu_markup.index(">USAGE &amp; BILLING</div>") < menu_markup.index(">ACTIVITY</div>")
    assert menu_markup.index(">ACTIVITY</div>") < menu_markup.index("Job Activity / Import Progress")
    assert menu_markup.index(">ACTIVITY</div>") < menu_markup.index(">DISPLAY</div>")
    assert menu_markup.index(">DISPLAY</div>") < menu_markup.index("Screen Settings")
    assert menu_markup.index(">DISPLAY</div>") < menu_markup.index(">SECURITY</div>")
    assert menu_markup.index(">SESSION</div>") < menu_markup.index("Sign Out")
    assert menu_markup.index(">DANGER ZONE</div>") < menu_markup.index("Delete Account")
    assert menu_markup.index("Sign Out") < menu_markup.index("Delete Account")
    assert "user-account-menu-item" in menu_markup
    assert "user-account-menu-item-icon" in menu_markup
    assert "user-account-menu-item-label" in menu_markup
    assert "user-account-menu-danger" in menu_markup
    assert 'class="secondary"' not in menu_markup
    assert 'class="danger"' not in menu_markup
    assert ".user-account-menu-panel {" in css
    assert "width: min(320px, calc(100vw - 32px));" in css
    assert "overflow-y: auto;" in css
    assert "var(--submenu-bg)" in css
    assert ".user-account-menu-section-title" in css
    assert ".user-account-menu-panel .user-account-menu-item" in css
    assert "justify-content: flex-start;" in css
    assert ".user-account-menu-item-icon" in css
    assert "flex: 0 0 22px;" in css
    assert ".user-account-menu-item-label" in css
    assert ".user-account-menu-panel .user-account-menu-danger" in css
    assert 'aria-controls="accountUsageDashboardPanel"' in menu_markup
    assert 'aria-controls="chatGptModelsSection"' in menu_markup
    assert 'aria-controls="jobActivitySection"' in menu_markup
    assert 'aria-controls="screenSettingsCard"' in menu_markup
    assert "toggleUsageDashboardPanel()" in menu_markup
    assert "toggleChatGptModelsPanel()" in menu_markup
    assert "openJobActivityPanel()" in menu_markup
    assert "toggleScreenSettingsPanel()" in menu_markup
    assert "function toggleUsageDashboardPanel(open = null)" in script
    assert "function openJobActivityPanel()" in script
    assert "function toggleScreenSettingsPanel(open = null)" in script
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


def test_firebase_connected_status_has_customer_friendly_security_details():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "data-firebase-connected-indicator" in template
    assert "data-firebase-auth-info" in template
    assert "data-firebase-auth-info-trigger" in template
    assert "Secure sign-in via Firebase" in template
    assert "Learn about secure sign-in" in template
    assert "Your sign-in is handled by Firebase Authentication. AI Pantry does not store or have access to your password." in template
    assert "Password storage: handled by Firebase / login provider" in template
    assert "data-firebase-auth-learn-more" in template
    assert "How your sign-in is protected" in template
    assert "AI Pantry uses Firebase Authentication to manage sign-ins." in template
    assert "your plain-text password" in template
    assert "your password hash" in template
    assert "your Google/Apple/Microsoft account password" in template
    assert "firebase_uid" not in template[template.index("data-firebase-auth-info"):template.index("data-firebase-auth-info-modal")]

    assert ".user-firebase-auth-wrap" in css
    assert ".user-firebase-connected-indicator" in css
    assert "cursor: pointer;" in css
    assert ".user-firebase-info-btn" in css
    assert ".user-firebase-info-popover" in css
    assert "width: min(360px, calc(100vw - 56px));" in css
    assert "max-width: calc(100vw - 56px);" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".user-firebase-info-learn" in css
    assert "background: #f8fafc;" in css
    assert "color: #10231a;" in css
    assert ".user-firebase-info-learn:hover" in css
    assert "width: min(100%, calc(100vw - 96px));" in css
    assert ".user-firebase-info-modal-backdrop" in css
    assert ".user-firebase-info-modal-backdrop.open" in css

    assert "function bindFirebaseAuthInfo()" in script
    assert "function setFirebaseAuthInfoPopoverOpen(wrapper, open)" in script
    assert "function setFirebaseAuthInfoPinned(wrapper, pinned)" in script
    assert "function firebaseAuthInfoIsPinned(wrapper)" in script
    assert "function openFirebaseAuthInfoModal(wrapper, trigger)" in script
    assert "function closeFirebaseAuthInfoModal(options = {})" in script
    assert "if (!firebaseAuthInfoIsPinned(wrapper))" in script
    assert "setFirebaseAuthInfoPinned(wrapper, true)" in script
    assert 'event.key === "Enter" || event.key === " "' in script
    assert 'event.key === "Escape"' in script
    assert '["bindFirebaseAuthInfo", bindFirebaseAuthInfo]' in script


def test_login_forms_include_password_safety_notice_and_learn_more():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    notice = "🔒 Passwords are handled by Firebase Authentication. AI Pantry does not store or see your password."
    details = (
        "AI Pantry uses Firebase Authentication for account sign-in. Your password is handled by Firebase or your "
        "login provider, such as Google. AI Pantry stores your account preferences, recipes, cookbooks, shopping "
        "lists, and settings — not your password."
    )

    create_markup = template[template.index('id="firebaseCreateAccountForm"'):template.index('id="firebaseSignInForm"')]
    sign_in_markup = template[template.index('id="firebaseSignInForm"'):template.index('id="forgotPasswordForm"')]

    assert create_markup.index('name="password"') < create_markup.index("user-password-safety-notice")
    assert create_markup.index('name="confirm_password"') < create_markup.index("user-password-safety-notice")
    assert sign_in_markup.index('name="password"') < sign_in_markup.index("user-password-safety-notice")
    assert create_markup.count(notice) == 1
    assert sign_in_markup.count(notice) == 1
    assert create_markup.count("Learn more") == 1
    assert sign_in_markup.count("Learn more") == 1
    assert details in create_markup
    assert details in sign_in_markup
    assert "plain text" not in create_markup.lower()
    assert "plain text" not in sign_in_markup.lower()

    assert ".user-password-safety-notice" in css
    assert ".user-password-safety-learn" in css
    assert ".user-password-safety-popover" in css
    assert "font-size: 12px;" in css
    assert "color: #aebbd0;" in css

    assert "function bindPasswordSafetyInfo()" in script
    assert "function setPasswordSafetyPopoverOpen(wrapper, open)" in script
    assert "function closePasswordSafetyPopovers()" in script
    assert 'event.key === "Enter" || event.key === " "' in script
    assert 'event.key === "Escape"' in script
    assert '["bindPasswordSafetyInfo", bindPasswordSafetyInfo]' in script


def test_usage_dashboard_menu_opens_visible_account_panel():
    template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert 'id="accountUsageDashboardPanel"' in template
    assert "data-usage-dashboard-panel" in template
    assert "<h3>AI Usage &amp; Billing</h3>" in template
    assert "data-usage-dashboard-close" in template
    assert "toggleUsageDashboardPanel(false)" in template
    assert "user-usage-dashboard-divider" in template
    assert "app-section-divider recipe-entry-section-divider user-usage-dashboard-divider" in template
    assert "API Usage Notice" in template
    assert "This dashboard tracks only OpenAI API usage made by this shopping-list app." in template
    assert "Does include:" in template
    assert "Recipe imports processed by this app" in template
    assert "Pantry/photo scans processed by this app" in template
    assert "Product searches processed by this app" in template
    assert "Generated images created by this app" in template
    assert "Does not include:" in template
    assert "ChatGPT app usage" in template
    assert "ChatGPT website usage" in template
    assert "ChatGPT Plus/Pro subscription usage" in template
    assert "OpenAI API usage from other apps" in template
    assert "user-usage-dashboard-grid" in template
    assert "Personal Workspace" in template
    assert "OpenAI API Pay-As-You-Go" in template
    assert "Billing Type" in template
    assert "Monthly API Budget" in template
    assert "API Usage This Month" in template
    assert "Budget Remaining" in template
    assert "API Requests This Month" in template
    assert "Input Tokens" in template
    assert "Output Tokens" in template
    assert "Estimated API Cost" in template
    assert "Billable AI Cost" in template
    assert "Configured app ledger amount" in template
    assert "Not available yet" in template
    assert "Monthly Spend Limit" in template
    assert "Lifetime Tokens" in template
    assert "Last API Request" in template
    assert "Tokens are pieces of text processed by the AI." in template
    assert "Estimated API cost is calculated from OpenAI API usage returned by this app." in template
    assert "Billable AI Cost uses this app's configured pricing ledger for user pass-through costs." in template
    for metric in (
        "plan_label",
        "billing_type_label",
        "monthly_budget_label",
        "monthly_total_tokens_label",
        "monthly_budget_remaining_label",
        "monthly_request_count_label",
        "monthly_prompt_tokens_label",
        "monthly_completion_tokens_label",
        "monthly_estimated_cost_label",
        "monthly_billable_cost_label",
        "lifetime_total_tokens_label",
        "last_used_at_label",
        "monthly_recipe_import_count_label",
        "monthly_pantry_scan_count_label",
        "monthly_product_search_count_label",
        "monthly_generated_image_count_label",
    ):
        assert f'data-openai-usage-metric="{metric}"' in template
    assert "data-openai-usage-budget-meter" in template
    assert "data-openai-usage-budget-text" in template
    assert "data-openai-usage-budget-badge" in template
    assert "data-openai-usage-empty-state" in template
    assert "user-usage-pricing-note" in template
    assert "data-openai-usage-pricing-note" in template
    assert "Recipe Imports" in template
    assert "Pantry Scans" in template
    assert "Product Searches" in template
    assert "Generated Images" in template
    assert "Monthly Spend Controls" in template
    assert "Alert at 50%" in template
    assert "Alert at 80%" in template
    assert "Pause AI features at 100%" in template
    assert "No monthly API budget configured." in template
    assert "No OpenAI API usage has been recorded for this app yet." in template
    assert "When this app makes OpenAI API requests, token usage and estimated costs will appear here." in template
    assert "Note: ChatGPT website/app subscription usage is separate and cannot be shown in this local dashboard." in template
    assert "No ChatGPT/OpenAI API tokens have been recorded yet." not in template
    assert ".user-usage-dashboard-panel" in css
    assert ".user-usage-api-notice" in css
    assert ".user-usage-info-badge" in css
    assert ".user-usage-dashboard-grid" in css
    assert ".user-usage-dashboard-card" in css
    assert ".user-usage-dashboard-card-wide" in css
    assert ".user-usage-dashboard-close" in css
    assert ".user-usage-activity-grid" in css
    assert ".user-usage-budget-panel" in css
    assert ".user-usage-budget-badge" in css
    assert ".user-usage-meter" in css
    assert ".user-usage-dashboard-note" in css
    assert "function toggleUsageDashboardPanel(open = null)" in script
    assert "function applyOpenAiUsageDashboard(dashboard)" in script
    assert "function refreshOpenAiUsageDashboard()" in script
    assert "function syncOpenAiUsageDashboardFromResponse(data, options = {})" in script
    assert 'fetch(`/api/openai_usage_dashboard?t=${Date.now()}`' in script
    assert "[data-usage-dashboard-panel]" in script
    assert 'panel.scrollIntoView({ behavior: "smooth", block: "start" })' in script
    assert "[data-usage-dashboard-panel]" in firebase_script


def test_account_panels_remember_open_state_across_refreshes():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert 'const USER_ACCOUNT_OPEN_PANEL_KEY = "user-account-open-panel";' in script
    assert "USER_ACCOUNT_REMEMBERED_PANEL_SELECTORS" in script
    for panel_key in (
        "accountSettings",
        "accountNotices",
        "usageDashboard",
        "chatGptModels",
        "jobActivity",
        "twoFactor",
        "pushNotifications",
        "deleteAccount",
    ):
        assert panel_key in script
    for selector in (
        "#userProfileEditForm",
        "[data-account-notices-panel]",
        "[data-usage-dashboard-panel]",
        "[data-chatgpt-models-panel]",
        "[data-job-activity-panel]",
        "[data-two-factor-panel]",
        "[data-push-notifications-panel]",
        "[data-delete-account-panel]",
    ):
        assert selector in script
        assert selector in firebase_script
    assert "function rememberAccountPanelOpen(panelKey)" in script
    assert "function clearRememberedAccountPanelOpen(panelKey = null)" in script
    assert "function rememberAccountPanelElement(panel, open)" in script
    assert "function restoreRememberedAccountPanelOpenWithOptions(options = {})" in script
    assert "if (options.scroll === false)" in script
    assert "function restoreRememberedAccountPanelOpen()" in script
    assert "restoreRememberedAccountPanelOpen();" in script
    assert "restoreRememberedAccountPanelOpenWithOptions({ scroll: false })" in script
    assert "rememberAccountPanelElement(form, shouldOpen)" in script
    assert "rememberAccountPanelElement(panel, shouldOpen)" in script
    assert "hideRememberedAccountPanels(panel)" in script
    assert "window.rememberAccountPanelElement(exceptPanel, true)" in firebase_script
    assert "window.rememberAccountPanelElement(panel, false)" in firebase_script


def test_chatgpt_models_live_inside_account_menu_panel():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    models_template = (ROOT / "PushShoppingList/templates/sections/chatgpt_models.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")
    route = (ROOT / "PushShoppingList/routes/main_routes.py").read_text(encoding="utf-8")
    service = (ROOT / "PushShoppingList/services/openai_model_service.py").read_text(encoding="utf-8")

    assert '{% include "sections/chatgpt_models.html" %}' not in index_template
    assert '{% include "sections/chatgpt_models.html" %}' in account_template
    assert 'aria-controls="chatGptModelsSection"' in account_template
    assert "toggleChatGptModelsPanel()" in account_template
    assert 'data-chatgpt-models-panel' in models_template
    assert 'request.args.get("account_panel") == "chatgpt_models"' in models_template
    assert "user-chatgpt-models-divider" in models_template
    assert "data-chatgpt-models-close" in models_template
    assert "toggleChatGptModelsPanel(false)" in models_template
    assert 'name="model_{{ row.env_var }}"' in models_template
    assert "row.model_groups" in models_template
    assert "optgroup label=\"{{ model_group.label }}\"" in models_template
    assert "Show Advanced Models" in models_template
    assert "Refresh Model List" in models_template
    assert "Refresh Recommended Mappings" in models_template
    assert "Refresh Lowest Viable Mappings" in models_template
    assert 'value="refresh_lowest_viable_mappings"' in models_template
    assert "Available Models:" in models_template
    assert "Last Refreshed:" in models_template
    assert "Recommended Mappings:" in models_template
    assert "Last Mapping Refresh:" in models_template
    assert "Source:" in models_template
    assert "<th scope=\"col\">Feature</th>" in models_template
    assert "<p>{{ row.description }}</p>" in models_template
    assert "Proposed Model" in models_template
    assert '<table class="chatgpt-model-table">' in models_template
    assert '<th scope="col">Active Model</th>' in models_template
    assert '<th scope="col">Proposed Model</th>' in models_template
    assert '<tr class="chatgpt-model-row">' in models_template
    assert "Reason: {{ row.proposed_model_reason }}" in models_template
    assert "Use Proposed Model" in models_template
    assert 'value="use_proposed:{{ row.env_var }}"' in models_template
    assert "type=\"text\"" not in models_template
    assert "account_panel=\"chatgpt_models\"" in route
    assert "refresh_lowest_viable_mappings" in route
    assert "refresh_openai_model_recommendations" in route
    assert "refresh_mappings" in route
    assert "chatgpt_model_force_refresh" in route
    assert "OPENAI_MODEL_CHOICES" not in service
    assert "fetch_openai_models_from_api" in service
    assert "openai_model_list(force_refresh=force_refresh)" in service
    assert "openai_model_recommendations()" in service
    assert "proposed_model_for_row" in service
    assert "Deprecated or unavailable" in service
    assert '"proposed_model": proposed_model' in service
    assert '"proposed_model_reason": proposed_model_reason' in service
    assert '"recommended_mapping_count": int(recommendations.get("total_count") or 0)' in service
    assert '"model_groups": choices["groups"]' in service
    assert ".chatgpt-models-card" in css
    assert "background: transparent;" in css
    assert ".user-chatgpt-models-divider" in css
    assert ".chatgpt-models-header-actions" in css
    assert ".chatgpt-model-status-banner" in css
    assert ".chatgpt-model-refresh-btn" in css
    assert ".chatgpt-model-use-proposed-btn" in css
    assert ".chatgpt-model-toolbar-actions" in css
    assert ".chatgpt-model-table-wrap" in css
    assert ".chatgpt-model-table {" in css
    assert ".chatgpt-model-warning-badge" in css
    assert ".chatgpt-model-row select" in css
    assert "border-collapse: collapse;" in css
    assert "table-layout: fixed;" in css
    assert "function toggleChatGptModelsPanel(open = null)" in script
    assert "[data-chatgpt-models-panel]" in script
    assert "#chatGptModelsSection" in script
    assert "[data-chatgpt-models-panel]" in firebase_script


def test_job_activity_lives_inside_account_menu_panel():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    job_template = (ROOT / "PushShoppingList/templates/sections/job_activity.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    firebase_script = (ROOT / "PushShoppingList/static/js/firebase-auth.js").read_text(encoding="utf-8")

    assert '{% include "sections/job_activity.html" %}' not in index_template
    assert '{% include "sections/job_activity.html" %}' in account_template
    assert "{% set job_activity_account_panel = true %}" in account_template
    assert 'aria-controls="jobActivitySection"' in account_template
    assert "data-job-activity-open" in account_template
    assert "openJobActivityPanel()" in account_template
    assert "job_activity_account_panel|default(false)" in job_template
    assert "user-job-activity-panel" in job_template
    assert "user-job-activity-divider" in job_template
    assert "data-job-activity-close" in job_template
    assert "closeJobActivityPanel()" in job_template
    assert "hidden{% endif %}" in job_template
    assert "function openJobActivityPanel()" in script
    assert "function closeJobActivityPanel()" in script
    assert "function expandJobActivityContent()" in script
    assert '"#jobActivitySection": "jobActivity"' in script
    assert "refreshJobActivityPanel({ force: true })" in script
    assert ".user-job-activity-panel.job-activity-card" in css
    assert ".user-job-activity-panel[hidden]" in css
    assert ".user-job-activity-header .job-activity-toggle" in css
    assert ".user-job-activity-close" in css
    assert "[data-job-activity-panel]" in firebase_script


def test_usage_dashboard_receives_openai_usage_summary_from_route():
    route = (ROOT / "PushShoppingList/routes/main_routes.py").read_text(encoding="utf-8")

    assert '@main_bp.route("/api/openai_usage_dashboard", methods=["GET"])' in route
    assert "def api_openai_usage_dashboard_route():" in route
    assert '"dashboard": openai_usage_dashboard_for_user(current_public_user())' in route
    assert "openai_usage_dashboard_for_user" in route
    assert "openai_usage_dashboard = openai_usage_dashboard_for_user(active_public_user)" in route


def test_usage_dashboard_refreshes_after_openai_routines():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    recipe_routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")
    product_routes = (ROOT / "PushShoppingList/routes/product_routes.py").read_text(encoding="utf-8")
    main_routes = (ROOT / "PushShoppingList/routes/main_routes.py").read_text(encoding="utf-8")

    assert script.count("syncOpenAiUsageDashboardFromResponse(data)") >= 9
    assert "scheduleOpenAiUsageDashboardRefresh(0)" in script
    assert "recipeImageProgressUsageRefreshKeys" in script
    assert "scheduleOpenAiUsageDashboardRefresh(250)" in script
    for endpoint in (
        "/api/recipe_nutrition_estimate",
        "/api/recipe_note_feedback",
        "/api/recipe_cover_image/generate",
        "/api/recipe_step_image",
        "/api/recipe_equipment_image",
        "/api/food_review_alternatives",
    ):
        assert endpoint in script
    assert "/api/food_rules/suggest" in script
    assert "/test-grab-aldi" in script
    assert "with_openai_usage_dashboard(result)" in recipe_routes
    assert "with_openai_usage_dashboard(result)" in product_routes
    assert '"openai_usage_dashboard": openai_usage_dashboard_for_user(current_user())' in recipe_routes
    assert '"openai_usage_dashboard": openai_usage_dashboard_for_user(current_user())' in product_routes
    assert '"openai_usage_dashboard": openai_usage_dashboard_for_user(current_public_user())' in main_routes


def test_recipe_editor_has_generate_title_image_action():
    template = (ROOT / "PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert 'id="recipeEditImageProvider"' in template
    assert '<option value="comfyui" selected>ComfyUI local</option>' in template
    assert '<option value="openai">ChatGPT / OpenAI</option>' in template
    assert 'id="recipeEditCoverGenerate"' in template
    assert 'id="recipeEditCoverGenerateLabel">Generate title image' in template
    assert "generateRecipeCoverImage(this)" in template
    assert "function selectedRecipeImageProvider()" in script
    assert "function recipeImageProviderPayload()" in script
    assert "...recipeImageProviderPayload()" in script
    assert '["initRecipeImageProviderSelector", initRecipeImageProviderSelector]' in script
    assert "function generateRecipeCoverImage(button)" in script
    assert 'fetch("/api/recipe_cover_image/generate"' in script
    assert '@recipe_bp.route("/api/recipe_cover_image/generate", methods=["POST"])' in routes


def test_admin_support_has_local_title_image_generation_test_action():
    template = (ROOT / "PushShoppingList/templates/sections/admin_support.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert "Test Local Image Generation" in template
    assert "data-local-title-image-status" in template
    assert "function testLocalTitleImageGeneration(button)" in script
    assert 'fetch("/api/recipe_cover_image/test-local"' in script
    assert '@recipe_bp.route("/api/recipe_cover_image/test-local", methods=["POST"])' in routes


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


def test_mobile_account_menu_sits_beside_profile_summary():
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    mobile_start = css.index("@media (max-width: 650px)", css.index(".user-account-profile"))
    mobile_end = css.index(".user-ntfy-link-row", mobile_start)
    mobile_css = css[mobile_start:mobile_end]

    assert "grid-template-columns: minmax(0, 1fr) auto;" in mobile_css
    assert "grid-template-areas:" in mobile_css
    assert '"avatar avatar"' in mobile_css
    assert '"summary actions"' in mobile_css
    assert ".user-account-avatar-wrap {" in mobile_css
    assert "grid-area: avatar;" in mobile_css
    assert "justify-self: center;" in mobile_css
    assert ".user-account-summary {" in mobile_css
    assert "grid-area: summary;" in mobile_css
    assert "grid-column: 1 / -1;" in mobile_css
    assert "grid-row: 2;" in mobile_css
    assert "padding-right: 50px;" in mobile_css
    assert "padding-left: 50px;" in mobile_css
    assert ".user-account-actions {" in mobile_css
    assert "grid-area: actions;" in mobile_css
    assert "grid-column: 2;" in mobile_css
    assert "align-self: start;" in mobile_css
    assert "justify-self: end;" in mobile_css
    assert "width: auto;" in mobile_css
    assert ".user-account-menu-panel {" in mobile_css
    assert "right: 0;" in mobile_css
    assert "transform: none;" in mobile_css


def test_admin_support_view_is_admin_only_reasoned_and_audited():
    index_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    support_template = (ROOT / "PushShoppingList/templates/sections/admin_support.html").read_text(encoding="utf-8")
    account_template = (ROOT / "PushShoppingList/templates/sections/user_account.html").read_text(encoding="utf-8")
    route = (ROOT / "PushShoppingList/routes/account_routes.py").read_text(encoding="utf-8")
    service = (ROOT / "PushShoppingList/services/admin_support_service.py").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "admin_support_dashboard.is_admin" in index_template
    assert 'id="adminSupportSection"' in support_template
    assert "Admin Access" in support_template
    assert "update_admin_access_route" in route
    assert "update_account_admin_access" in route
    assert "admin_access_action" in support_template
    assert "Grant Admin" in support_template
    assert "Revoke Admin" in support_template
    assert "Recent Admin Access Changes" in support_template
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
    assert 'const SUPPORT_EMAIL = SUPPORT_PUBLIC_CONFIG.supportEmail || "support@recipeshoppinglist.com";' in script
    assert "const SUPPORT_ADMIN_EMAILS = Array.isArray(SUPPORT_PUBLIC_CONFIG.supportAdminEmails)" in script
    assert "function getPublicSupportEmail(email)" in script
    assert "function getPublicSupportIdentity(email)" in script
    assert "? SUPPORT_EMAIL" in script
    assert "function openFeedbackSupportSection()" in script
    assert "function toggleAccountNoticesPanel(open = null)" in script
    assert "function toggleAccountAccessHistory(button)" in script
    assert "password_hash" not in support_template
    assert "two_factor.secret" not in support_template
    assert ".admin-support-card" in css
    assert ".admin-access-form" in css
    assert ".admin-access-revoke-btn" in css

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
    assert ".feedback-support-card .user-push-panel-close" in css
    assert ".feedback-support-card .user-push-panel-close:hover" in css


def test_feedback_support_tickets_are_compact_collapsible_portal_rows():
    support_template = (ROOT / "PushShoppingList/templates/sections/feedback_support.html").read_text(encoding="utf-8")
    ticket_template = (ROOT / "PushShoppingList/templates/sections/feedback_ticket.html").read_text(encoding="utf-8")
    admin_ticket_template = (ROOT / "PushShoppingList/templates/sections/feedback_admin_ticket.html").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "feedback-form-attachments-heading" in support_template
    assert "Attachments" in support_template
    assert "Collapse All Feedback" in support_template
    assert "adminFeedbackTitle" in support_template
    assert "feedback-admin-count" in support_template
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
    assert "data-feedback-ticket" in admin_ticket_template
    assert "data-feedback-ticket-toggle" in admin_ticket_template
    assert 'aria-expanded="false"' in admin_ticket_template
    assert "data-feedback-ticket-body hidden" in admin_ticket_template
    assert "feedback-ticket-summary" in admin_ticket_template
    assert "feedback-ticket-badges" in admin_ticket_template
    assert "Last Updated {{ feedback.display_updated_at }}" in admin_ticket_template
    assert "feedback-admin-requester" in admin_ticket_template
    assert "feedback.user_attachments" in admin_ticket_template
    assert "feedback.support_attachments" in admin_ticket_template
    assert "feedback-ticket-top" not in admin_ticket_template
    assert ".feedback-ticket-summary" in css
    assert ".feedback-ticket-badges" in css
    assert ".feedback-ticket-body[hidden]" in css
    assert ".feedback-form-attachments-heading" in css
    assert ".feedback-section-actions" in css
    assert ".feedback-collapse-all-btn" in css
    assert ".feedback-attachments" in css
    assert ".feedback-admin-requester" in css
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
    assert "body.account-action-token.screen-settings-open.screen-preview-active #appContent" in css
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
