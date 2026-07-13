(function initializePublicAuthPage() {
    "use strict";

    const THEME_STORAGE_KEY = "ai-pantry-public-theme";
    const AUTH_MODES = new Set(["sign-in", "create", "forgot"]);

    function normalizedAuthMode(mode) {
        return AUTH_MODES.has(mode) ? mode : "sign-in";
    }

    function setAuthPanelMode(mode, options = {}) {
        const selectedMode = normalizedAuthMode(mode);
        const root = document.querySelector("[data-public-auth-panel-root]");
        const panels = Array.from(document.querySelectorAll("[data-public-auth-panel]"));
        const selectedPanel = panels.find(panel => panel.dataset.publicAuthPanel === selectedMode);

        if (!root || !selectedPanel) {
            return false;
        }

        panels.forEach(panel => {
            panel.hidden = panel !== selectedPanel;
        });
        root.dataset.publicAuthMode = selectedMode;

        document.querySelectorAll("[data-auth-mode-target]").forEach(control => {
            control.setAttribute(
                "aria-expanded",
                control.dataset.authModeTarget === selectedMode ? "true" : "false"
            );
        });

        if (selectedMode === "forgot" && typeof window.updateForgotPasswordResetMethod === "function") {
            window.updateForgotPasswordResetMethod();
        }

        if (options.focus !== false) {
            window.requestAnimationFrame(() => {
                const firstControl = selectedPanel.querySelector("input:not([type='hidden']), button, select, textarea");
                if (firstControl) {
                    firstControl.focus({ preventScroll: true });
                }
            });
        }

        return true;
    }

    function bindAuthPanelModeControls() {
        document.querySelectorAll("[data-auth-mode-target]").forEach(control => {
            control.addEventListener("click", event => {
                event.preventDefault();
                setAuthPanelMode(control.dataset.authModeTarget || "sign-in");
            });
        });

        setAuthPanelMode("sign-in", { focus: false });
    }

    function bindPasswordVisibilityControls() {
        document.querySelectorAll("[data-password-visibility-toggle]").forEach(control => {
            control.addEventListener("click", () => {
                const field = control.closest(".public-auth-password-field");
                const input = field ? field.querySelector("input") : null;

                if (!input) {
                    return;
                }

                const showPassword = input.type === "password";
                input.type = showPassword ? "text" : "password";
                control.setAttribute("aria-label", showPassword ? "Hide password" : "Show password");
                control.setAttribute("aria-pressed", showPassword ? "true" : "false");
                input.focus({ preventScroll: true });
            });
        });
    }

    function cancelAccountActionLink() {
        const url = new URL(window.location.href);
        [
            "two_factor_recovery_token",
            "reset_token",
            "account_delete_token",
            "screen_preview_frame",
            "screen_preview_mode",
            "screen_preview_width",
        ].forEach(param => url.searchParams.delete(param));
        url.hash = "";
        window.location.href = url.toString();
        return false;
    }

    function storedTheme() {
        try {
            const value = localStorage.getItem(THEME_STORAGE_KEY) || "system";
            return ["system", "light", "dark"].includes(value) ? value : "system";
        } catch (error) {
            return "system";
        }
    }

    function applyPublicTheme(theme, options = {}) {
        const selectedTheme = ["light", "dark"].includes(theme) ? theme : "system";

        if (selectedTheme === "system") {
            delete document.documentElement.dataset.publicAuthTheme;
        } else {
            document.documentElement.dataset.publicAuthTheme = selectedTheme;
        }

        if (options.persist !== false) {
            try {
                localStorage.setItem(THEME_STORAGE_KEY, selectedTheme);
            } catch (error) {
                // The selected theme still applies for this page view.
            }
        }

        document.querySelectorAll("[data-public-theme-toggle]").forEach(select => {
            select.value = selectedTheme;
        });
    }

    function bindPublicThemeControl() {
        applyPublicTheme(storedTheme(), { persist: false });
        document.querySelectorAll("[data-public-theme-toggle]").forEach(select => {
            select.addEventListener("change", () => applyPublicTheme(select.value));
        });
    }

    function bindPublicAuthPage() {
        if (!document.querySelector("[data-public-auth-page]")) {
            return;
        }

        bindAuthPanelModeControls();
        bindPasswordVisibilityControls();
        bindPublicThemeControl();
    }

    window.setAuthPanelMode = setAuthPanelMode;
    window.cancelAccountActionLink = cancelAccountActionLink;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bindPublicAuthPage, { once: true });
    } else {
        bindPublicAuthPage();
    }
}());
