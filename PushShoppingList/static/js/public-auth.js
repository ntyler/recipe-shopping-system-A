(function initializePublicAuthPage() {
    "use strict";

    const THEME_STORAGE_KEY = "ai-pantry-public-theme";
    const THEME_VALUES = new Set(["system", "light", "dark"]);
    const THEME_LABELS = {
        system: "System",
        light: "Light",
        dark: "Dark",
    };
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
            return THEME_VALUES.has(value) ? value : "system";
        } catch (error) {
            return "system";
        }
    }

    function syncPublicThemeMenus(theme) {
        const selectedTheme = THEME_VALUES.has(theme) ? theme : "system";

        document.querySelectorAll("[data-public-theme-menu]").forEach(menu => {
            const trigger = menu.querySelector("[data-public-theme-trigger]");
            const label = menu.querySelector("[data-public-theme-label]");

            if (trigger) {
                trigger.setAttribute("aria-label", `Color theme: ${THEME_LABELS[selectedTheme]}`);
            }
            if (label) {
                label.textContent = THEME_LABELS[selectedTheme];
            }

            menu.querySelectorAll("[data-public-theme-option]").forEach(option => {
                option.setAttribute(
                    "aria-checked",
                    option.dataset.publicThemeOption === selectedTheme ? "true" : "false"
                );
            });
        });
    }

    function applyPublicTheme(theme, options = {}) {
        const selectedTheme = THEME_VALUES.has(theme) ? theme : "system";

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

        syncPublicThemeMenus(selectedTheme);
    }

    function publicThemeMenuIsOpen(menu) {
        const panel = menu ? menu.querySelector("[data-public-theme-menu-panel]") : null;
        return Boolean(panel && !panel.hidden);
    }

    function closePublicThemeMenu(menu, options = {}) {
        const trigger = menu ? menu.querySelector("[data-public-theme-trigger]") : null;
        const panel = menu ? menu.querySelector("[data-public-theme-menu-panel]") : null;

        if (!menu || !trigger || !panel) {
            return;
        }

        const wasOpen = !panel.hidden;
        panel.hidden = true;
        menu.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");

        if (wasOpen && options.restoreFocus) {
            trigger.focus({ preventScroll: true });
        }
    }

    function publicThemeMenuOptions(menu) {
        return menu ? [...menu.querySelectorAll("[data-public-theme-option]")] : [];
    }

    function focusPublicThemeMenuOption(menu, target = "selected") {
        const options = publicThemeMenuOptions(menu);
        let option = options.find(item => item.getAttribute("aria-checked") === "true");

        if (target === "first") {
            option = options[0];
        } else if (target === "last") {
            option = options[options.length - 1];
        }

        option?.focus({ preventScroll: true });
    }

    function openPublicThemeMenu(menu, options = {}) {
        const trigger = menu ? menu.querySelector("[data-public-theme-trigger]") : null;
        const panel = menu ? menu.querySelector("[data-public-theme-menu-panel]") : null;

        if (!menu || !trigger || !panel) {
            return;
        }

        document.querySelectorAll("[data-public-theme-menu]").forEach(otherMenu => {
            if (otherMenu !== menu) {
                closePublicThemeMenu(otherMenu);
            }
        });

        panel.hidden = false;
        menu.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
        focusPublicThemeMenuOption(menu, options.focus || "selected");
    }

    function selectPublicThemeOption(menu, option) {
        const theme = option?.dataset.publicThemeOption || "";

        if (!THEME_VALUES.has(theme)) {
            return;
        }

        applyPublicTheme(theme);
        closePublicThemeMenu(menu, { restoreFocus: true });
    }

    function focusAdjacentPublicThemeOption(menu, direction) {
        const options = publicThemeMenuOptions(menu);
        const activeIndex = options.indexOf(document.activeElement);
        const nextIndex = activeIndex < 0
            ? (direction > 0 ? 0 : options.length - 1)
            : (activeIndex + direction + options.length) % options.length;

        options[nextIndex]?.focus({ preventScroll: true });
    }

    function bindPublicThemeMenu(menu) {
        if (!menu || menu.dataset.publicThemeMenuBound === "1") {
            return;
        }

        const trigger = menu.querySelector("[data-public-theme-trigger]");
        const panel = menu.querySelector("[data-public-theme-menu-panel]");
        if (!trigger || !panel) {
            return;
        }

        menu.dataset.publicThemeMenuBound = "1";
        closePublicThemeMenu(menu);

        trigger.addEventListener("click", () => {
            if (publicThemeMenuIsOpen(menu)) {
                closePublicThemeMenu(menu);
            } else {
                openPublicThemeMenu(menu);
            }
        });

        trigger.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
                event.preventDefault();
                if (publicThemeMenuIsOpen(menu)) {
                    closePublicThemeMenu(menu);
                } else {
                    openPublicThemeMenu(menu);
                }
                return;
            }

            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                openPublicThemeMenu(menu, {
                    focus: event.key === "ArrowDown" ? "first" : "last",
                });
                return;
            }

            if (event.key === "Escape" && publicThemeMenuIsOpen(menu)) {
                event.preventDefault();
                closePublicThemeMenu(menu, { restoreFocus: true });
            }
        });

        panel.addEventListener("click", event => {
            const option = event.target?.closest("[data-public-theme-option]");
            if (option && panel.contains(option)) {
                selectPublicThemeOption(menu, option);
            }
        });

        panel.addEventListener("keydown", event => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                focusAdjacentPublicThemeOption(menu, event.key === "ArrowDown" ? 1 : -1);
                return;
            }

            if (event.key === "Home" || event.key === "End") {
                event.preventDefault();
                focusPublicThemeMenuOption(menu, event.key === "Home" ? "first" : "last");
                return;
            }

            if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
                const option = event.target?.closest("[data-public-theme-option]");
                if (option && panel.contains(option)) {
                    event.preventDefault();
                    selectPublicThemeOption(menu, option);
                }
                return;
            }

            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                closePublicThemeMenu(menu, { restoreFocus: true });
            }
        });

        menu.addEventListener("focusout", () => {
            window.requestAnimationFrame(() => {
                if (publicThemeMenuIsOpen(menu) && !menu.contains(document.activeElement)) {
                    closePublicThemeMenu(menu);
                }
            });
        });
    }

    function bindPublicThemeControl() {
        applyPublicTheme(storedTheme(), { persist: false });
        document.querySelectorAll("[data-public-theme-menu]").forEach(menu => {
            bindPublicThemeMenu(menu);
        });

        if (document.documentElement.dataset.publicThemeMenuGlobalBound === "1") {
            return;
        }

        document.documentElement.dataset.publicThemeMenuGlobalBound = "1";
        document.addEventListener("click", event => {
            if (event.target?.closest("[data-public-theme-menu]")) {
                return;
            }

            document.querySelectorAll("[data-public-theme-menu]").forEach(menu => {
                if (publicThemeMenuIsOpen(menu)) {
                    closePublicThemeMenu(menu);
                }
            });
        });
        document.addEventListener("keydown", event => {
            if (event.key !== "Escape") {
                return;
            }

            const openMenu = [...document.querySelectorAll("[data-public-theme-menu]")]
                .find(menu => publicThemeMenuIsOpen(menu));
            if (openMenu) {
                event.preventDefault();
                closePublicThemeMenu(openMenu, { restoreFocus: true });
            }
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
