import { initializeApp } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-app.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/12.14.0/firebase-analytics.js";
import {
    getAuth,
    onAuthStateChanged,
    browserLocalPersistence,
    browserSessionPersistence,
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
    apiKey: "",
    authDomain: "",
    projectId: "",
    storageBucket: "",
    messagingSenderId: "",
    appId: "",
    measurementId: ""
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
const POST_SIGN_OUT_RESET_KEY = "shopping-post-sign-out-reset";
const POST_AUTH_HOME_LOCAL_STORAGE_KEYS = [
    "scrollY",
    "user-account-open-panel",
    "user-account-settings-open",
];
const POST_AUTH_HOME_SESSION_STORAGE_KEYS = [
    TWO_FACTOR_PANEL_RETURN_KEY,
    "recipe-edit-page-return-state",
    "recipe-edit-pending-action",
    POST_SIGN_OUT_RESET_KEY,
];
const POST_AUTH_HOME_RESET_KEY = "shopping-post-auth-home-reset";
const POST_SIGN_OUT_LOCAL_STORAGE_KEYS = [
    ...POST_AUTH_HOME_LOCAL_STORAGE_KEYS,
    "shopping-auth-collapse-all-pending",
    "store-open-panels",
    "shopping-view",
    "import-recipe-cookbook-destination",
    "recipe-image-progress-event",
];
const POST_SIGN_OUT_LOCAL_STORAGE_PREFIXES = [
    "extract_closed_",
    "extract_refreshed_",
    "item-checked:",
    "recipe-task-checked:",
];

function formValue(form, name) {
    return String((form.elements[name] || {}).value || "").trim();
}

async function setFirebasePersistenceForForm(form) {
    const rememberChoice = form ? form.elements.remember_me : null;
    const persistence = rememberChoice && !rememberChoice.checked
        ? browserSessionPersistence
        : browserLocalPersistence;

    await setPersistence(auth, persistence);
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
    let headingBlock = heading;

    while (headingBlock && headingBlock.parentElement !== form) {
        headingBlock = headingBlock.parentElement;
    }

    if (headingBlock) {
        headingBlock.insertAdjacentElement("afterend", status);
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

function requestCollapseAllBeforeAuthReload() {
    if (typeof window.requestShoppingListAuthCollapseAll === "function") {
        window.requestShoppingListAuthCollapseAll();
        return;
    }

    try {
        localStorage.setItem("shopping-auth-collapse-all-pending", "1");
    } catch (error) {
        // Collapse-on-auth is a UI preference; auth should continue if storage is unavailable.
    }
}

function cancelCollapseAllBeforeAuthReload() {
    if (typeof window.clearShoppingListAuthCollapseAllRequest === "function") {
        window.clearShoppingListAuthCollapseAllRequest();
        return;
    }

    try {
        localStorage.removeItem("shopping-auth-collapse-all-pending");
        sessionStorage.removeItem("shopping-auth-collapse-all-active");
    } catch (error) {
        // Collapse-on-auth is a UI preference; auth should continue if storage is unavailable.
    }
}

function clearPostAuthenticationNavigationState() {
    try {
        POST_AUTH_HOME_LOCAL_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));
    } catch (error) {
        // Storage can be unavailable in private or restricted browser contexts.
    }

    try {
        POST_AUTH_HOME_SESSION_STORAGE_KEYS.forEach((key) => sessionStorage.removeItem(key));
    } catch (error) {
        // Storage can be unavailable in private or restricted browser contexts.
    }
}

function closePostAuthenticationTransientUi() {
    document.querySelectorAll("dialog[open]").forEach((dialog) => {
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
    });
    document.querySelectorAll("[data-account-menu][open]").forEach((menu) => menu.removeAttribute("open"));
    document.querySelectorAll("[data-profile-menu-panel], [data-app-mobile-nav-drawer], [data-app-mobile-nav-backdrop]")
        .forEach((panel) => {
            panel.hidden = true;
            panel.setAttribute("aria-hidden", "true");
        });
    document.querySelectorAll("[data-profile-menu-trigger], [data-app-mobile-nav-toggle]")
        .forEach((trigger) => trigger.setAttribute("aria-expanded", "false"));
    document.body.classList.remove("app-mobile-navigation-open");
}

function removeSignOutFailureNotice() {
    const notice = document.querySelector("[data-sign-out-error]");
    if (notice) {
        notice.remove();
    }
}

function beginSignOutProtection() {
    removeSignOutFailureNotice();
    closePostAuthenticationTransientUi();

    const appLayout = document.querySelector("[data-app-layout]");
    if (appLayout) {
        appLayout.inert = true;
        appLayout.setAttribute("aria-hidden", "true");
    }

    let screen = document.querySelector("[data-sign-out-protection]");
    if (!screen) {
        screen = document.createElement("div");
        screen.className = "auth-sign-out-screen";
        screen.setAttribute("data-sign-out-protection", "");
        screen.setAttribute("role", "status");
        screen.setAttribute("aria-live", "polite");

        const spinner = document.createElement("span");
        spinner.className = "auth-sign-out-spinner";
        spinner.setAttribute("aria-hidden", "true");

        const label = document.createElement("span");
        label.textContent = "Signing out...";

        screen.append(spinner, label);
        document.body.append(screen);
    }

    document.body.classList.add("auth-sign-out-pending");
}

function endSignOutProtection() {
    document.body.classList.remove("auth-sign-out-pending");
    const screen = document.querySelector("[data-sign-out-protection]");
    if (screen) {
        screen.remove();
    }

    const appLayout = document.querySelector("[data-app-layout]");
    if (appLayout) {
        appLayout.inert = false;
        appLayout.removeAttribute("aria-hidden");
    }
}

function showSignOutFailure(form, error) {
    const message = firebaseErrorMessage(error);
    setStatus(form, message, "error");

    const notice = document.createElement("div");
    notice.className = "auth-sign-out-error";
    notice.setAttribute("data-sign-out-error", "");
    notice.setAttribute("role", "alert");
    notice.textContent = message;
    document.body.append(notice);
}

function clearPostSignOutClientState(logoutResult = {}) {
    backendSession = {
        ...logoutResult,
        success: true,
        authenticated: false,
        pending_2fa: false,
        user: null,
    };
    applyBackendSessionState(backendSession);

    try {
        const keysToRemove = [];
        for (let index = 0; index < localStorage.length; index += 1) {
            const key = localStorage.key(index);
            if (key && POST_SIGN_OUT_LOCAL_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
                keysToRemove.push(key);
            }
        }
        [...POST_SIGN_OUT_LOCAL_STORAGE_KEYS, ...keysToRemove]
            .forEach((key) => localStorage.removeItem(key));
    } catch (error) {
        // Authentication is already cleared even if browser storage is restricted.
    }

    try {
        sessionStorage.clear();
        sessionStorage.setItem(POST_SIGN_OUT_RESET_KEY, "1");
    } catch (error) {
        // The canonical navigation still prevents in-page state restoration.
    }

    window.shoppingFirebaseAuthStatus.backendVerified = false;
}

function navigateToCanonicalSignInAfterSignOut() {
    const canonicalSignInUrl = new URL("/", window.location.origin);
    if ("scrollRestoration" in window.history) {
        window.history.scrollRestoration = "manual";
    }

    window.history.replaceState({}, document.title, canonicalSignInUrl.pathname);
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    window.location.replace(canonicalSignInUrl.href);
}

function enforcePostSignOutDestination() {
    let shouldEnforce = false;
    try {
        shouldEnforce = sessionStorage.getItem(POST_SIGN_OUT_RESET_KEY) === "1";
    } catch (error) {
        return false;
    }

    if (!shouldEnforce) {
        return false;
    }

    const canonicalSignInUrl = new URL("/", window.location.origin);
    const publicSignInPage = document.querySelector("[data-public-auth-content]");
    if (publicSignInPage) {
        window.history.replaceState({}, document.title, canonicalSignInUrl.pathname);
        window.scrollTo({ top: 0, left: 0, behavior: "auto" });
        return true;
    }

    beginSignOutProtection();
    window.history.replaceState({}, document.title, canonicalSignInUrl.pathname);
    window.location.replace(canonicalSignInUrl.href);
    return true;
}

function navigateToCanonicalHomeAfterAuthentication(options = {}) {
    if (options.collapseAllBeforeReload) {
        requestCollapseAllBeforeAuthReload();
    }

    clearPostAuthenticationNavigationState();
    closePostAuthenticationTransientUi();

    try {
        sessionStorage.setItem(POST_AUTH_HOME_RESET_KEY, "1");
    } catch (error) {
        // The canonical URL replacement still resets the page when storage is unavailable.
    }

    if (typeof window.openHomeWorkspace === "function") {
        window.openHomeWorkspace({ updateHash: false, scroll: false });
    }

    const homeLink = document.querySelector('[data-app-nav-action="home"]');
    if (homeLink && typeof window.appShellSetActiveLink === "function") {
        window.appShellSetActiveLink(homeLink);
    }

    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    const mainContent = document.querySelector("[data-app-content]");
    if (mainContent && typeof mainContent.scrollTo === "function") {
        mainContent.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }

    const canonicalHomeUrl = new URL("/", window.location.origin);
    if ("scrollRestoration" in window.history) {
        window.history.scrollRestoration = "manual";
    }
    window.history.replaceState({}, document.title, canonicalHomeUrl.pathname);
    window.location.replace(canonicalHomeUrl.href);
}

async function accountExistsForPasswordReset(email) {
    const query = new URLSearchParams({ email });
    return backendJson(`/auth/account-exists?${query.toString()}`, { method: "GET" });
}

function reloadAccountSection(options = {}) {
    if (options.collapseAllBeforeReload) {
        requestCollapseAllBeforeAuthReload();
    }

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
    requestCollapseAllBeforeAuthReload();
    beginSignOutProtection();

    try {
        await signOut(auth);
    } catch (error) {
        cancelCollapseAllBeforeAuthReload();
        explicitAuthInProgress = false;
        endSignOutProtection();
        showSignOutFailure(null, error);
        return false;
    }

    try {
        const result = await logoutBackend();
        clearPostSignOutClientState(result);
    } catch (error) {
        cancelCollapseAllBeforeAuthReload();
        explicitAuthInProgress = false;
        endSignOutProtection();
        showSignOutFailure(null, error);
        return false;
    }

    removeQueryParams(["two_factor_disabled"]);
    navigateToCanonicalSignInAfterSignOut();
    return true;
}

function handleFirebaseBackendLogin(result, form, successMessage) {
    if (result && result.requires_2fa) {
        setStatus(form, "Enter your authenticator code to finish signing in.", "success");
        reloadAccountSection();
        return true;
    }

    setStatus(form, successMessage, "success");
    navigateToCanonicalHomeAfterAuthentication({ collapseAllBeforeReload: true });
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
        "[data-push-notifications-enable], [data-push-device-subscribe], [data-push-notifications-disable], [data-push-notifications-test], [data-notification-preference]"
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
    const statusSummary = panel.querySelector("[data-push-notifications-summary]");
    const stateCard = panel.querySelector("[data-push-state-card]");
    const enableButton = panel.querySelector("[data-push-notifications-enable]");
    const disableButton = panel.querySelector("[data-push-notifications-disable]");
    const testButton = panel.querySelector("[data-push-notifications-test]");

    panel.dataset.notificationsEnabled = normalizedEnabled ? "1" : "0";

    if (statusLabel) {
        statusLabel.textContent = normalizedEnabled ? "Notifications Enabled" : "Notifications Disabled";
    }

    if (statusSummary) {
        statusSummary.textContent = normalizedEnabled
            ? "You'll be notified when selected shopping-list events finish."
            : "Enable notifications to get updates from this app on this device.";
    }

    if (stateCard) {
        stateCard.classList.toggle("enabled", normalizedEnabled);
        stateCard.classList.toggle("disabled", !normalizedEnabled);
    }

    if (enableButton) {
        enableButton.disabled = false;
        enableButton.textContent = normalizedEnabled ? "Notifications Enabled" : "Enable Notifications";
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
    updatePushNotificationTopicUi(panel, user);
    updatePushNotificationDevices(panel, user.notification_devices || []);

    const preferences = user.notification_preferences || {};
    panel.querySelectorAll("[data-notification-preference]").forEach((input) => {
        const key = String(input.dataset.notificationPreference || "");

        if (Object.prototype.hasOwnProperty.call(preferences, key)) {
            input.checked = Boolean(preferences[key]);
        }
    });
}

function updatePushNotificationTopicUi(panel, user) {
    if (!panel || !user) {
        return;
    }

    const topic = String(user.notification_topic || user.ntfy_topic || "").trim();
    const historyUrl = String(user.ntfy_url || "").trim();
    const deepLink = String(user.ntfy_deep_link || "").trim();
    const topicNode = panel.querySelector("[data-push-notification-topic]");
    const historyLink = panel.querySelector("[data-push-history-link]");
    const copyButton = panel.querySelector("[data-ntfy-url]");
    const lastTest = panel.querySelector("[data-push-last-test-label]");

    panel.dataset.notificationTopic = topic;
    panel.dataset.ntfyUrl = historyUrl;
    panel.dataset.ntfyDeepLink = deepLink;

    if (topicNode) {
        topicNode.textContent = topic || "Not created yet";
    }

    if (historyLink) {
        historyLink.href = historyUrl || "#";
    }

    if (copyButton) {
        copyButton.dataset.ntfyUrl = historyUrl;
    }

    if (lastTest) {
        lastTest.textContent = user.last_test_notification_label || "Not sent yet";
    }
}

function updatePushNotificationDevices(panel, devices) {
    if (!panel || !Array.isArray(devices)) {
        return;
    }

    devices.forEach((device) => {
        const key = String(device.key || "").trim();
        const item = key ? panel.querySelector(`[data-notification-device="${key}"]`) : null;

        if (!item) {
            return;
        }

        const status = String(device.status || "Not Connected").trim() || "Not Connected";
        const statusClass = String(device.status_class || status.toLowerCase().replace(/\s+/g, "-")).trim();
        const statusNode = item.querySelector("[data-notification-device-status]");

        item.classList.remove("connected", "pending", "not-connected");
        item.classList.add(statusClass);

        if (statusNode) {
            statusNode.textContent = status;
        }
    });
}

function notificationDeviceType() {
    const ua = navigator.userAgent || "";

    if (/iphone|ipad|ipod/i.test(ua)) {
        return "iphone";
    }

    if (/android/i.test(ua)) {
        return "android";
    }

    return "browser";
}

function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; i += 1) {
        outputArray[i] = rawData.charCodeAt(i);
    }

    return outputArray;
}

async function buildBrowserPushSubscription(panel) {
    if (!("Notification" in window)) {
        return {
            permission: "unsupported",
            subscription: null,
            message: "Browser notifications are not supported here."
        };
    }

    let permission = Notification.permission;

    if (permission === "default") {
        permission = await Notification.requestPermission();
    }

    if (permission !== "granted") {
        return {
            permission,
            subscription: null,
            message: "Notification permission was not granted."
        };
    }

    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        return {
            permission,
            subscription: null,
            message: "Browser push is not supported here."
        };
    }

    let registration = null;

    try {
        registration = await navigator.serviceWorker.register("/static/js/push-notifications-sw.js");
    } catch (error) {
        return {
            permission,
            subscription: null,
            message: "Browser permission is enabled, but the service worker could not be registered."
        };
    }

    const publicKey = String(panel.dataset.webPushPublicKey || "").trim();

    if (!publicKey) {
        return {
            permission,
            subscription: null,
            message: "Browser permission is enabled. Add SHOPPING_APP_WEB_PUSH_PUBLIC_KEY to store a browser push subscription."
        };
    }

    let subscription = await registration.pushManager.getSubscription();

    if (!subscription) {
        subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(publicKey)
        });
    }

    return {
        permission,
        subscription: subscription.toJSON ? subscription.toJSON() : subscription,
        message: "Browser notifications connected."
    };
}

async function saveNotificationSettings(panel, enabled = null, options = {}) {
    const body = {
        preferences: collectNotificationPreferences(panel)
    };

    if (typeof enabled === "boolean") {
        body.enabled = enabled;
    }

    if (options.browserPermission !== undefined) {
        body.browser_permission = options.browserPermission;
    }

    if (options.browserSubscription) {
        body.browser_push_subscription = options.browserSubscription;
    }

    if (options.device) {
        body.device = options.device;
    }

    setPushNotificationsBusy(panel, true);
    setPushNotificationsStatus(options.statusMessage || "Saving notification settings...", "success");

    try {
        const result = await backendJson("/account/notifications", {
            method: "POST",
            body: JSON.stringify(body)
        });
        applyNotificationSettingsUser(panel, result.user);
        setPushNotificationsStatus(options.successMessage || "Notification settings saved.", "success");
        return result;
    } catch (error) {
        setPushNotificationsStatus(error.message, "error");
        throw error;
    } finally {
        setPushNotificationsBusy(panel, false);
        updatePushNotificationControls(panel, panel.dataset.notificationsEnabled === "1");
    }
}

async function enablePushNotifications(panel) {
    setPushNotificationsBusy(panel, true);
    setPushNotificationsStatus("Enabling notifications...", "success");

    try {
        const browserPush = await buildBrowserPushSubscription(panel);
        const result = await saveNotificationSettings(panel, true, {
            browserPermission: browserPush.permission,
            browserSubscription: browserPush.subscription,
            statusMessage: "Saving notification subscription...",
            successMessage: browserPush.subscription
                ? "Notifications Enabled."
                : `Notifications Enabled. ${browserPush.message}`
        });

        applyNotificationSettingsUser(panel, result.user);

        if (!browserPush.subscription && notificationDeviceType() !== "browser") {
            await subscribeCurrentDeviceToNtfy(panel, { silent: true });
        }
    } catch (error) {
        setPushNotificationsStatus(error.message, "error");
    } finally {
        setPushNotificationsBusy(panel, false);
        updatePushNotificationControls(panel, panel.dataset.notificationsEnabled === "1");
    }
}

async function subscribeCurrentDeviceToNtfy(panel, options = {}) {
    const deviceType = notificationDeviceType();
    const isBrowserDevice = deviceType === "browser";

    if (isBrowserDevice && !options.forceBrowserHistory) {
        setPushNotificationsStatus("Browser notifications are handled by Enable Notifications.", "success");
        return;
    }

    try {
        const result = await backendJson("/account/notifications/device-subscribe", {
            method: "POST",
            body: JSON.stringify({ device_type: deviceType })
        });
        applyNotificationSettingsUser(panel, result.user);

        const deepLink = String(result.deep_link || panel.dataset.ntfyDeepLink || "").trim();
        const historyUrl = String(result.history_url || panel.dataset.ntfyUrl || "").trim();

        if (deepLink) {
            window.location.href = deepLink;
            window.setTimeout(() => {
                if (historyUrl) {
                    window.open(historyUrl, "_blank", "noopener,noreferrer");
                }
            }, 900);
        } else if (historyUrl) {
            window.open(historyUrl, "_blank", "noopener,noreferrer");
        }

        if (!options.silent) {
            setPushNotificationsStatus("Subscription opened on this device.", "success");
        }
    } catch (error) {
        setPushNotificationsStatus(error.message, "error");
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
            if (typeof window.openUserAccountWorkspace === "function") {
                window.openUserAccountWorkspace({
                    targetId: "accountPushNotificationsPanel",
                    updateHash: false,
                    scroll: false,
                });
            }
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
            if (typeof window.rememberAccountPanelElement === "function") {
                window.rememberAccountPanelElement(panel, false);
            }
            setPushNotificationsStatus("", "success");
            if (typeof window.scrollToUserAccountProfile === "function") {
                window.scrollToUserAccountProfile("auto");
            }
        });
    }

    const enableButton = panel.querySelector("[data-push-notifications-enable]");
    if (enableButton) {
        enableButton.addEventListener("click", () => {
            enablePushNotifications(panel);
        });
    }

    const deviceSubscribeButton = panel.querySelector("[data-push-device-subscribe]");
    if (deviceSubscribeButton) {
        deviceSubscribeButton.addEventListener("click", () => {
            subscribeCurrentDeviceToNtfy(panel, { forceBrowserHistory: true });
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
                setPushNotificationsStatus("Notification sent successfully", "success");
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
        "#userProfileEditForm, [data-account-notices-panel], [data-usage-dashboard-panel], [data-ai-pantry-panel], [data-admin-support-panel], [data-chatgpt-models-panel], [data-job-activity-panel], [data-shared-recipe-pdfs-panel], [data-push-notifications-panel], [data-feedback-support-panel], [data-two-factor-panel], [data-delete-account-panel]"
    ).forEach((panel) => {
        if (panel !== exceptPanel) {
            panel.hidden = true;
        }
    });

    if (typeof window.rememberAccountPanelElement === "function" && exceptPanel) {
        window.rememberAccountPanelElement(exceptPanel, true);
    } else if (typeof window.clearRememberedAccountPanelOpen === "function") {
        window.clearRememberedAccountPanelOpen();
    }
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
        if (typeof window.scrollToUserAccountProfile === "function") {
            window.scrollToUserAccountProfile(behavior);
            return;
        }

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
            if (typeof window.rememberAccountPanelElement === "function") {
                window.rememberAccountPanelElement(panel, false);
            }
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
            if (typeof window.rememberAccountPanelElement === "function") {
                window.rememberAccountPanelElement(panel, false);
            }
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

window.addEventListener("shopping:device-stale-revalidate", async () => {
    try {
        await loadBackendSession();
    } catch (error) {
        console.warn("Could not revalidate Flask auth session after stale report.", error);
    }
});

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
        "[data-firebase-create-form], [data-firebase-sign-in-form], [data-firebase-forgot-form]"
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
        requestCollapseAllBeforeAuthReload();
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
            cancelCollapseAllBeforeAuthReload();
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
        requestCollapseAllBeforeAuthReload();

        try {
            await setFirebasePersistenceForForm(form);
            const credential = await signInWithEmailAndPassword(
                auth,
                formValue(form, "identity"),
                String((form.elements.password || {}).value || "")
            );
            const result = await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
            handleFirebaseBackendLogin(result, form, "Signed in. Loading your workspace...");
        } catch (error) {
            cancelCollapseAllBeforeAuthReload();
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
            requestCollapseAllBeforeAuthReload();

            try {
                await setFirebasePersistenceForForm(form);
                const credential = await signInWithPopup(auth, googleProvider);
                const result = await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
                handleFirebaseBackendLogin(result, form, "Signed in with Google. Loading your workspace...");
            } catch (error) {
                cancelCollapseAllBeforeAuthReload();
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
    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("[data-firebase-sign-out-form]");
        if (!form || form.dataset.firebaseSignOutPending === "1") {
            return;
        }

        event.preventDefault();
        form.dataset.firebaseSignOutPending = "1";
        setStatus(form, "", "");
        setBusy(form, true);
        explicitAuthInProgress = true;
        requestCollapseAllBeforeAuthReload();
        beginSignOutProtection();

        try {
            if (auth) {
                await signOut(auth);
            }
            const result = await logoutBackend();
            clearPostSignOutClientState(result);
            navigateToCanonicalSignInAfterSignOut();
        } catch (error) {
            cancelCollapseAllBeforeAuthReload();
            explicitAuthInProgress = false;
            endSignOutProtection();
            setBusy(form, false);
            delete form.dataset.firebaseSignOutPending;
            showSignOutFailure(form, error);
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
        requestCollapseAllBeforeAuthReload();

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
        requestCollapseAllBeforeAuthReload();

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
    bindTwoFactorCancelButton();
    bindAccountMenuActions();
    bindAccountDeleteConfirmForm();
}

document.addEventListener("DOMContentLoaded", async () => {
    enforcePostSignOutDestination();
    bindSignOutForm();
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
                requestCollapseAllBeforeAuthReload();
                const result = await syncFirebaseUser(firebaseUser, firebaseUserProfile(firebaseUser));
                if (result && result.requires_2fa) {
                    reloadAccountSection();
                    return;
                }
                navigateToCanonicalHomeAfterAuthentication({ collapseAllBeforeReload: true });
                return;
            }

            if (!firebaseUser && session.user && session.user.auth_provider === "firebase") {
                requestCollapseAllBeforeAuthReload();
                beginSignOutProtection();
                try {
                    const result = await logoutBackend();
                    clearPostSignOutClientState(result);
                    navigateToCanonicalSignInAfterSignOut();
                } catch (error) {
                    cancelCollapseAllBeforeAuthReload();
                    endSignOutProtection();
                    showSignOutFailure(null, error);
                    throw error;
                }
            }
        } catch (error) {
            console.warn("Firebase auth state sync failed.", error);
        }
    });
}

window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
        enforcePostSignOutDestination();
    }
});

window.shoppingFirebaseAuth = {
    app,
    analytics,
    auth,
    googleProvider
};
