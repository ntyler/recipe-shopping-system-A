import { initializeApp } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-analytics.js";
import {
    getAuth,
    onAuthStateChanged,
    browserLocalPersistence,
    setPersistence,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    sendPasswordResetEmail,
    sendEmailVerification,
    signInWithPopup,
    GoogleAuthProvider,
    signOut
} from "https://www.gstatic.com/firebasejs/12.14.0/firebase-auth.js";

const localDevelopmentFirebaseConfig = {
    apiKey: "AIzaSyAzUeQBO2t98GVp_8zKpTFvmm_6ePX-U2U",
    authDomain: "recipe-shopping-app-d4a07.firebaseapp.com",
    projectId: "recipe-shopping-app-d4a07",
    storageBucket: "recipe-shopping-app-d4a07.firebasestorage.app",
    messagingSenderId: "1084430352486",
    appId: "1:1084430352486:web:71b25f380928a61bdfeda7",
    measurementId: "G-J44GKNGRDY"
};

window.shoppingFirebaseAuthStatus = window.shoppingFirebaseAuthStatus || {
    initialized: false
};

function firebaseConfigFromPage() {
    const element = document.getElementById("firebaseWebConfig");

    if (!element) {
        return localDevelopmentFirebaseConfig;
    }

    try {
        return {
            ...localDevelopmentFirebaseConfig,
            ...JSON.parse(element.textContent || "{}")
        };
    } catch (error) {
        console.warn("Firebase config JSON could not be parsed.", error);
        return localDevelopmentFirebaseConfig;
    }
}

function missingFirebaseConfig(config) {
    return ["apiKey", "authDomain", "projectId", "appId"].some((key) => !String(config[key] || "").trim());
}

function isDevelopmentHost() {
    return ["", "localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
}

const firebaseConfig = firebaseConfigFromPage();
let app = null;
let analytics = null;
let auth = null;
let googleProvider = null;

if (missingFirebaseConfig(firebaseConfig)) {
    console.warn("Firebase config is missing. Check the Flask Firebase web config values.");
} else {
    try {
        const initializedApp = initializeApp(firebaseConfig);
        const initializedAnalytics = getAnalytics(initializedApp);
        const initializedAuth = getAuth(initializedApp);
        const initializedGoogleProvider = new GoogleAuthProvider();

        app = initializedApp;
        analytics = initializedAnalytics;
        auth = initializedAuth;
        googleProvider = initializedGoogleProvider;
        setPersistence(auth, browserLocalPersistence).catch((error) => {
            console.warn("Firebase auth persistence could not be set.", error);
        });
        window.shoppingFirebaseAuthStatus.initialized = true;

        if (isDevelopmentHost()) {
            console.log("Firebase Auth initialized.");
        }
    } catch (error) {
        console.warn("Firebase Auth initialization failed.", error);
    }
}

let backendSession = null;
let explicitAuthInProgress = false;
const TWO_FACTOR_PANEL_RETURN_KEY = "shoppingTwoFactorPanelReturn";

function formValue(form, name) {
    return String((form.elements[name] || {}).value || "").trim();
}

function firebaseErrorMessage(error) {
    const code = String(error && error.code || "");

    if (code === "auth/email-already-in-use") {
        return "That email is already registered. Sign in instead.";
    }

    if (code === "auth/invalid-email") {
        return "Enter a valid email address.";
    }

    if (code === "auth/invalid-credential" || code === "auth/wrong-password" || code === "auth/user-not-found") {
        return "We could not sign you in with that email and password.";
    }

    if (code === "auth/weak-password") {
        return "Use a stronger password. Firebase requires at least 6 characters.";
    }

    if (code === "auth/popup-closed-by-user") {
        return "Google sign-in was canceled.";
    }

    if (code === "auth/configuration-not-found") {
        return "Firebase rejected this sign-in method. Confirm Email/Password and Google providers are enabled.";
    }

    return String(error && error.message || "Firebase authentication failed.");
}

function statusForForm(form) {
    if (!form) {
        return null;
    }

    let status = form.querySelector("[data-firebase-status]");
    if (status) {
        return status;
    }

    status = document.createElement("div");
    status.className = "user-firebase-status";
    status.setAttribute("data-firebase-status", "");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    const heading = form.querySelector("h3");
    if (heading && heading.nextSibling) {
        form.insertBefore(status, heading.nextSibling);
    } else {
        form.prepend(status);
    }

    return status;
}

function setStatus(form, message, type) {
    const status = statusForForm(form);

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("success", type === "success");
    status.classList.toggle("error", type === "error");
    status.hidden = !message;
}

function setBusy(form, busy) {
    if (!form) {
        return;
    }

    form.querySelectorAll("button, input, select, textarea").forEach((control) => {
        control.disabled = busy;
    });
}

async function backendJson(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        ...options
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok || payload.success === false) {
        const message = Array.isArray(payload.errors)
            ? payload.errors.join(" ")
            : (payload.error || payload.message || "The server could not complete authentication.");
        throw new Error(message);
    }

    return payload;
}

async function loadBackendSession() {
    backendSession = await backendJson("/auth/session", { method: "GET" });
    applyBackendSessionState(backendSession);
    return backendSession;
}

async function syncFirebaseUser(firebaseUser, profile = {}) {
    const idToken = await firebaseUser.getIdToken();
    return backendJson("/auth/firebase-login", {
        method: "POST",
        body: JSON.stringify({ idToken, profile })
    });
}

async function logoutBackend() {
    return backendJson("/auth/logout", {
        method: "POST",
        body: JSON.stringify({})
    });
}

async function accountExistsForPasswordReset(email) {
    const query = new URLSearchParams({ email });
    return backendJson(`/auth/account-exists?${query.toString()}`, { method: "GET" });
}

function reloadAccountSection() {
    window.location.hash = "userAccountSection";
    window.location.reload();
}

function hasAccountActionToken() {
    const params = new URLSearchParams(window.location.search);
    return Boolean(
        params.get("two_factor_recovery_token")
        || params.get("reset_token")
        || params.get("account_delete_token")
    );
}

function needsPostTwoFactorDisableSignOut() {
    const params = new URLSearchParams(window.location.search);
    return params.get("two_factor_disabled") === "1";
}

function removeQueryParams(names) {
    const params = new URLSearchParams(window.location.search);
    names.forEach((name) => params.delete(name));
    const query = params.toString();
    const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash || ""}`;
    window.history.replaceState({}, document.title, nextUrl);
}

async function finishPostTwoFactorDisableSignOut() {
    if (!auth || !needsPostTwoFactorDisableSignOut()) {
        return false;
    }

    explicitAuthInProgress = true;

    try {
        await signOut(auth);
    } catch (error) {
        console.warn("Firebase sign-out after two-factor disable failed.", error);
    }

    try {
        await logoutBackend();
    } catch (error) {
        console.warn("Backend sign-out after two-factor disable failed.", error);
    }

    removeQueryParams(["two_factor_disabled"]);
    explicitAuthInProgress = false;
    return true;
}

function handleFirebaseBackendLogin(result, form, successMessage) {
    if (result && result.requires_2fa) {
        setStatus(form, "Enter your authenticator code to finish signing in.", "success");
        reloadAccountSection();
        return true;
    }

    setStatus(form, successMessage, "success");
    reloadAccountSection();
    return true;
}

function firebaseEmailActionSettings() {
    return {
        url: `${window.location.origin}/#userAccountSection`,
        handleCodeInApp: false
    };
}

function setAccountMenuStatus(message, type = "success") {
    const status = document.querySelector("[data-account-menu-status]");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("success", type === "success");
    status.classList.toggle("error", type === "error");
    status.hidden = !message;
}

function setPushNotificationsStatus(message, type = "success") {
    const status = document.querySelector("[data-push-notifications-status]");

    if (!status) {
        return;
    }

    status.textContent = message || "";
    status.classList.toggle("success", type === "success");
    status.classList.toggle("error", type === "error");
    status.hidden = !message;
}

function setPushNotificationsBusy(panel, busy) {
    if (!panel) {
        return;
    }

    panel.querySelectorAll(
        "[data-push-notifications-enable], [data-push-notifications-disable], [data-push-notifications-test], [data-notification-preference]"
    ).forEach((control) => {
        control.disabled = busy;
    });
}

function collectNotificationPreferences(panel) {
    const preferences = {};

    if (!panel) {
        return preferences;
    }

    panel.querySelectorAll("[data-notification-preference]").forEach((input) => {
        preferences[String(input.dataset.notificationPreference || "")] = Boolean(input.checked);
    });

    return preferences;
}

function updatePushNotificationControls(panel, enabled) {
    if (!panel) {
        return;
    }

    const normalizedEnabled = Boolean(enabled);
    const statusLabel = panel.querySelector("[data-push-notifications-status-label]");
    const enableButton = panel.querySelector("[data-push-notifications-enable]");
    const disableButton = panel.querySelector("[data-push-notifications-disable]");
    const testButton = panel.querySelector("[data-push-notifications-test]");

    panel.dataset.notificationsEnabled = normalizedEnabled ? "1" : "0";

    if (statusLabel) {
        statusLabel.textContent = normalizedEnabled ? "Enabled" : "Disabled";
    }

    if (enableButton) {
        enableButton.disabled = normalizedEnabled;
    }

    if (disableButton) {
        disableButton.disabled = !normalizedEnabled;
    }

    if (testButton) {
        testButton.disabled = !normalizedEnabled;
    }
}

function applyNotificationSettingsUser(panel, user) {
    if (!panel || !user) {
        return;
    }

    updatePushNotificationControls(panel, Boolean(user.notifications_enabled));

    const preferences = user.notification_preferences || {};
    panel.querySelectorAll("[data-notification-preference]").forEach((input) => {
        const key = String(input.dataset.notificationPreference || "");

        if (Object.prototype.hasOwnProperty.call(preferences, key)) {
            input.checked = Boolean(preferences[key]);
        }
    });
}

async function saveNotificationSettings(panel, enabled = null) {
    const body = {
        preferences: collectNotificationPreferences(panel)
    };

    if (typeof enabled === "boolean") {
        body.enabled = enabled;
    }

    setPushNotificationsBusy(panel, true);
    setPushNotificationsStatus("Saving notification settings...", "success");

    try {
        const result = await backendJson("/account/notifications", {
            method: "POST",
            body: JSON.stringify(body)
        });
        applyNotificationSettingsUser(panel, result.user);
        setPushNotificationsStatus("Notification settings saved.", "success");
    } catch (error) {
        setPushNotificationsStatus(error.message, "error");
    } finally {
        setPushNotificationsBusy(panel, false);
        updatePushNotificationControls(panel, panel.dataset.notificationsEnabled === "1");
    }
}

function bindPushNotificationsPanel() {
    const panel = document.querySelector("[data-push-notifications-panel]");

    if (!panel) {
        return;
    }

    updatePushNotificationControls(panel, panel.dataset.notificationsEnabled === "1");

    document.querySelectorAll("[data-push-notifications-open]").forEach((button) => {
        button.addEventListener("click", () => {
            panel.hidden = false;
            setPushNotificationsStatus("", "success");
            hideAccountMenuPanels(panel);

            const menu = document.querySelector("[data-account-menu]");
            if (menu) {
                menu.open = false;
            }

            window.requestAnimationFrame(() => {
                panel.scrollIntoView({ behavior: "smooth", block: "start" });
                const firstControl = panel.querySelector("[data-push-notifications-close]");
                if (firstControl) {
                    firstControl.focus({ preventScroll: true });
                }
            });
        });
    });

    const closeButton = panel.querySelector("[data-push-notifications-close]");
    if (closeButton) {
        closeButton.addEventListener("click", () => {
            panel.hidden = true;
            setPushNotificationsStatus("", "success");
            if (typeof window.scrollToUserAccountTop === "function") {
                window.scrollToUserAccountTop("auto");
            }
        });
    }

    const enableButton = panel.querySelector("[data-push-notifications-enable]");
    if (enableButton) {
        enableButton.addEventListener("click", () => {
            saveNotificationSettings(panel, true);
        });
    }

    const disableButton = panel.querySelector("[data-push-notifications-disable]");
    if (disableButton) {
        disableButton.addEventListener("click", () => {
            saveNotificationSettings(panel, false);
        });
    }

    const testButton = panel.querySelector("[data-push-notifications-test]");
    if (testButton) {
        testButton.addEventListener("click", async () => {
            if (panel.dataset.notificationsEnabled !== "1") {
                setPushNotificationsStatus("Enable push notifications before sending a test notification.", "error");
                return;
            }

            setPushNotificationsBusy(panel, true);
            setPushNotificationsStatus("Sending test notification...", "success");

            try {
                const result = await backendJson("/account/notifications/test", {
                    method: "POST",
                    body: JSON.stringify({})
                });
                applyNotificationSettingsUser(panel, result.user);
                setPushNotificationsStatus("Test notification sent.", "success");
            } catch (error) {
                setPushNotificationsStatus(error.message, "error");
            } finally {
                setPushNotificationsBusy(panel, false);
                updatePushNotificationControls(panel, panel.dataset.notificationsEnabled === "1");
            }
        });
    }

    let preferenceSaveTimer = null;
    panel.querySelectorAll("[data-notification-preference]").forEach((input) => {
        input.addEventListener("change", () => {
            window.clearTimeout(preferenceSaveTimer);
            preferenceSaveTimer = window.setTimeout(() => {
                saveNotificationSettings(panel);
            }, 250);
        });
    });
}

function hideAccountMenuPanels(exceptPanel = null) {
    document.querySelectorAll(
        "#userProfileEditForm, [data-push-notifications-panel], [data-two-factor-panel], [data-delete-account-panel]"
    ).forEach((panel) => {
        if (panel !== exceptPanel) {
            panel.hidden = true;
        }
    });
}

function bindTwoFactorPanel() {
    const panel = document.querySelector("[data-two-factor-panel]");

    if (!panel) {
        return;
    }

    const scrollToPanel = (behavior = "smooth") => {
        window.requestAnimationFrame(() => {
            panel.scrollIntoView({ behavior, block: "start" });
            const firstControl = panel.querySelector("[data-two-factor-close]");
            if (firstControl) {
                firstControl.focus({ preventScroll: true });
            }
        });
    };

    const scrollToAccountProfile = (behavior = "smooth") => {
        const target = document.querySelector(".user-account-profile")
            || document.getElementById("userAccountSection");

        if (!target) {
            return;
        }

        const scrollToTarget = (scrollBehavior = behavior) => {
            target.scrollIntoView({ behavior: scrollBehavior, block: "start" });
        };

        window.requestAnimationFrame(() => {
            scrollToTarget();
            window.requestAnimationFrame(() => scrollToTarget("auto"));
            window.setTimeout(() => scrollToTarget("auto"), 120);

            const menuSummary = document.querySelector("[data-account-menu] summary");
            if (menuSummary) {
                menuSummary.focus({ preventScroll: true });
            }
        });
    };

    const clearTwoFactorPanelLocation = () => {
        const url = new URL(window.location.href);
        const hadTwoFactorPanelQuery = url.searchParams.get("account_panel") === "two_factor";
        const hadTwoFactorPanelHash = url.hash === "#accountTwoFactorPanel";

        if (!hadTwoFactorPanelQuery && !hadTwoFactorPanelHash) {
            return;
        }

        if (hadTwoFactorPanelQuery) {
            url.searchParams.delete("account_panel");
        }

        url.hash = "userAccountSection";
        window.history.replaceState({}, document.title, url.toString());
    };

    document.querySelectorAll("[data-two-factor-open]").forEach((button) => {
        button.addEventListener("click", () => {
            panel.hidden = false;
            hideAccountMenuPanels(panel);

            const menu = document.querySelector("[data-account-menu]");
            if (menu) {
                menu.open = false;
            }

            scrollToPanel("smooth");
        });
    });

    document.querySelectorAll("[data-two-factor-return-form]").forEach((form) => {
        form.addEventListener("submit", () => {
            window.sessionStorage.setItem(TWO_FACTOR_PANEL_RETURN_KEY, "1");
        });
    });

    const shouldReturnToPanel = (
        window.sessionStorage.getItem(TWO_FACTOR_PANEL_RETURN_KEY) === "1"
        || new URLSearchParams(window.location.search).get("account_panel") === "two_factor"
        || window.location.hash === "#accountTwoFactorPanel"
    );

    if (shouldReturnToPanel && !panel.hidden) {
        window.sessionStorage.removeItem(TWO_FACTOR_PANEL_RETURN_KEY);
        scrollToPanel("auto");
    }

    const closeButton = panel.querySelector("[data-two-factor-close]");
    if (closeButton) {
        closeButton.addEventListener("click", () => {
            clearTwoFactorPanelLocation();
            panel.hidden = true;
            window.sessionStorage.removeItem(TWO_FACTOR_PANEL_RETURN_KEY);
            scrollToAccountProfile("auto");
        });
    }
}

function bindDeleteAccountPanel() {
    const panel = document.querySelector("[data-delete-account-panel]");

    if (!panel) {
        return;
    }

    document.querySelectorAll("[data-delete-account-open]").forEach((button) => {
        button.addEventListener("click", () => {
            panel.hidden = false;
            hideAccountMenuPanels(panel);

            const menu = document.querySelector("[data-account-menu]");
            if (menu) {
                menu.open = false;
            }

            window.requestAnimationFrame(() => {
                panel.scrollIntoView({ behavior: "smooth", block: "start" });
                const firstControl = panel.querySelector("[data-delete-account-close]");
                if (firstControl) {
                    firstControl.focus({ preventScroll: true });
                }
            });
        });
    });

    const closeButton = panel.querySelector("[data-delete-account-close]");
    if (closeButton) {
        closeButton.addEventListener("click", () => {
            panel.hidden = true;
        });
    }
}

function applyBackendSessionState(session) {
    const indicator = document.querySelector("[data-firebase-connected-indicator]");
    const user = session && session.user ? session.user : null;
    const connected = Boolean(session && session.authenticated && user && user.auth_provider === "firebase");

    if (indicator) {
        indicator.hidden = !connected;
    }

    window.shoppingFirebaseAuthStatus.backendVerified = connected;
}

function firebaseUserProfile(firebaseUser, extra = {}) {
    const providerData = Array.isArray(firebaseUser.providerData) ? firebaseUser.providerData : [];
    const primaryProvider = providerData.find((provider) => provider && provider.providerId) || {};

    return {
        display_name: firebaseUser.displayName || "",
        email: firebaseUser.email || "",
        picture: firebaseUser.photoURL || "",
        provider: primaryProvider.providerId || "",
        ...extra
    };
}

function disableFirebaseAuthForms(message) {
    document.querySelectorAll(
        "[data-firebase-create-form], [data-firebase-sign-in-form], [data-firebase-forgot-form], [data-firebase-sign-out-form]"
    ).forEach((form) => {
        setBusy(form, true);
        setStatus(form, message || "Firebase Authentication is not ready.", "error");
    });
}

function bindCreateAccountForm() {
    const form = document.querySelector("[data-firebase-create-form]");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setStatus(form, "", "");

        const email = formValue(form, "email");
        const password = String((form.elements.password || {}).value || "");
        const confirmPassword = String((form.elements.confirm_password || {}).value || "");

        if (password !== confirmPassword) {
            setStatus(form, "Password and confirm password must match.", "error");
            return;
        }

        setBusy(form, true);
        explicitAuthInProgress = true;
        try {
            const credential = await createUserWithEmailAndPassword(auth, email, password);
            const result = await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user, {
                first_name: formValue(form, "first_name"),
                last_name: formValue(form, "last_name"),
                username: formValue(form, "username"),
                email
            }));
            handleFirebaseBackendLogin(result, form, "Account created. Signing you in...");
        } catch (error) {
            setStatus(form, firebaseErrorMessage(error), "error");
            setBusy(form, false);
            explicitAuthInProgress = false;
        }
    });
}

function bindSignInForm() {
    const form = document.querySelector("[data-firebase-sign-in-form]");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setStatus(form, "", "");
        setBusy(form, true);
        explicitAuthInProgress = true;

        try {
            const credential = await signInWithEmailAndPassword(
                auth,
                formValue(form, "identity"),
                String((form.elements.password || {}).value || "")
            );
            const result = await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
            handleFirebaseBackendLogin(result, form, "Signed in. Loading your workspace...");
        } catch (error) {
            setStatus(form, firebaseErrorMessage(error), "error");
            setBusy(form, false);
            explicitAuthInProgress = false;
        }
    });

    const googleButton = form.querySelector("[data-firebase-google-sign-in]");
    if (googleButton) {
        googleButton.addEventListener("click", async () => {
            setStatus(form, "", "");
            setBusy(form, true);
            explicitAuthInProgress = true;

            try {
                const credential = await signInWithPopup(auth, googleProvider);
                const result = await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
                handleFirebaseBackendLogin(result, form, "Signed in with Google. Loading your workspace...");
            } catch (error) {
                setStatus(form, firebaseErrorMessage(error), "error");
                setBusy(form, false);
                explicitAuthInProgress = false;
            }
        });
    }
}

function bindForgotPasswordForm() {
    const form = document.querySelector("[data-firebase-forgot-form]");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setStatus(form, "", "");
        setBusy(form, true);

        try {
            const email = formValue(form, "identity");
            const accountCheck = await accountExistsForPasswordReset(email);

            if (!accountCheck.exists) {
                setStatus(form, "No account was found for that email. Create an account first.", "error");
                return;
            }

            setStatus(form, "Account found. Sending password reset email...", "success");
            await sendPasswordResetEmail(auth, email, firebaseEmailActionSettings());
            setStatus(form, "Firebase sent a password reset email.", "success");
        } catch (error) {
            setStatus(form, firebaseErrorMessage(error), "error");
        } finally {
            setBusy(form, false);
        }
    });
}

function bindSignOutForm() {
    const form = document.querySelector("[data-firebase-sign-out-form]");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setBusy(form, true);

        try {
            await signOut(auth);
        } finally {
            try {
                await logoutBackend();
            } finally {
                reloadAccountSection();
            }
        }
    });
}

function bindTwoFactorCancelButton() {
    const button = document.querySelector("[data-firebase-cancel-two-factor]");

    if (!button) {
        return;
    }

    button.addEventListener("click", async (event) => {
        event.preventDefault();
        button.disabled = true;

        try {
            await signOut(auth);
        } catch (error) {
            console.warn("Firebase sign-out before canceling two-factor sign-in failed.", error);
        }

        const form = button.form;
        if (form) {
            form.action = button.formAction || form.action;
            form.submit();
        }
    });
}

function bindAccountMenuActions() {
    const changePasswordButton = document.querySelector("[data-firebase-change-password]");
    const verifyEmailButton = document.querySelector("[data-firebase-verify-email]");

    if (changePasswordButton) {
        changePasswordButton.addEventListener("click", async () => {
            const email = String(changePasswordButton.dataset.userEmail || (auth.currentUser || {}).email || "").trim();

            if (!email) {
                setAccountMenuStatus("This account does not have an email address.", "error");
                return;
            }

            changePasswordButton.disabled = true;
            setAccountMenuStatus("", "success");

            try {
                await sendPasswordResetEmail(auth, email, firebaseEmailActionSettings());
                setAccountMenuStatus("Password reset email sent.", "success");
            } catch (error) {
                setAccountMenuStatus(firebaseErrorMessage(error), "error");
            } finally {
                changePasswordButton.disabled = false;
            }
        });
    }

    if (verifyEmailButton) {
        verifyEmailButton.addEventListener("click", async () => {
            const firebaseUser = auth.currentUser;

            if (!firebaseUser) {
                setAccountMenuStatus("Refresh the page, then try verifying email again.", "error");
                return;
            }

            if (firebaseUser.emailVerified) {
                setAccountMenuStatus("Email is already verified.", "success");
                return;
            }

            verifyEmailButton.disabled = true;
            setAccountMenuStatus("", "success");

            try {
                await sendEmailVerification(firebaseUser, firebaseEmailActionSettings());
                setAccountMenuStatus("Verification email sent.", "success");
            } catch (error) {
                setAccountMenuStatus(firebaseErrorMessage(error), "error");
            } finally {
                verifyEmailButton.disabled = false;
            }
        });
    }
}

function bindAccountDeleteConfirmForm() {
    const form = document.querySelector("[data-firebase-account-delete-confirm-form]");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async (event) => {
        if (form.dataset.firebaseDeleteSubmitting === "1") {
            return;
        }

        event.preventDefault();
        form.dataset.firebaseDeleteSubmitting = "1";
        explicitAuthInProgress = true;
        form.querySelectorAll("button").forEach((button) => {
            button.disabled = true;
        });

        try {
            await signOut(auth);
        } catch (error) {
            console.warn("Firebase sign-out before account deletion failed.", error);
        }

        form.submit();
    });
}

function bindFirebaseForms() {
    bindCreateAccountForm();
    bindSignInForm();
    bindForgotPasswordForm();
    bindSignOutForm();
    bindTwoFactorCancelButton();
    bindAccountMenuActions();
    bindAccountDeleteConfirmForm();
}

document.addEventListener("DOMContentLoaded", async () => {
    bindPushNotificationsPanel();
    bindTwoFactorPanel();
    bindDeleteAccountPanel();

    if (auth) {
        bindFirebaseForms();
        await finishPostTwoFactorDisableSignOut();
    } else {
        disableFirebaseAuthForms("Firebase Authentication could not be initialized.");
    }

    try {
        await loadBackendSession();
    } catch (error) {
        console.warn("Could not load Flask auth session.", error);
    }
});

if (auth) {
    onAuthStateChanged(auth, async (firebaseUser) => {
        if (explicitAuthInProgress) {
            return;
        }

        if (needsPostTwoFactorDisableSignOut()) {
            return;
        }

        if (hasAccountActionToken()) {
            return;
        }

        try {
            const session = await loadBackendSession();

            if (firebaseUser && !session.authenticated && !session.pending_2fa) {
                const result = await syncFirebaseUser(firebaseUser, firebaseUserProfile(firebaseUser));
                if (result && result.requires_2fa) {
                    reloadAccountSection();
                    return;
                }
                reloadAccountSection();
                return;
            }

            if (!firebaseUser && session.user && session.user.auth_provider === "firebase") {
                await logoutBackend();
                reloadAccountSection();
            }
        } catch (error) {
            console.warn("Firebase auth state sync failed.", error);
        }
    });
}

window.shoppingFirebaseAuth = {
    app,
    analytics,
    auth,
    googleProvider
};
