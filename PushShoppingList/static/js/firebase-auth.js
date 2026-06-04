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

function reloadAccountSection() {
    window.location.hash = "userAccountSection";
    window.location.reload();
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
            await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user, {
                first_name: formValue(form, "first_name"),
                last_name: formValue(form, "last_name"),
                username: formValue(form, "username"),
                email
            }));
            setStatus(form, "Account created. Signing you in...", "success");
            reloadAccountSection();
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
            await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
            setStatus(form, "Signed in. Loading your workspace...", "success");
            reloadAccountSection();
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
                await syncFirebaseUser(credential.user, firebaseUserProfile(credential.user));
                setStatus(form, "Signed in with Google. Loading your workspace...", "success");
                reloadAccountSection();
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
            await sendPasswordResetEmail(auth, formValue(form, "identity"), firebaseEmailActionSettings());
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
    bindAccountMenuActions();
    bindAccountDeleteConfirmForm();
}

document.addEventListener("DOMContentLoaded", async () => {
    if (auth) {
        bindFirebaseForms();
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

        try {
            const session = await loadBackendSession();

            if (firebaseUser && !session.authenticated) {
                await syncFirebaseUser(firebaseUser, firebaseUserProfile(firebaseUser));
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
