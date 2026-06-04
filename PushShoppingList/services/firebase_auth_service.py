import os

import requests


DEFAULT_FIREBASE_WEB_CONFIG = {
    "apiKey": "AIzaSyAzUeQBO2t98GVp_8zKpTFvmm_6ePX-U2U",
    "authDomain": "recipe-shopping-app-d4a07.firebaseapp.com",
    "projectId": "recipe-shopping-app-d4a07",
    "storageBucket": "recipe-shopping-app-d4a07.firebasestorage.app",
    "messagingSenderId": "1084430352486",
    "appId": "1:1084430352486:web:71b25f380928a61bdfeda7",
    "measurementId": "G-J44GKNGRDY",
}
FIREBASE_ACCOUNTS_LOOKUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"


def env_value(*names, default=""):
    for name in names:
        value = os.getenv(name)

        if value:
            return str(value).strip()

    return str(default).strip()


def firebase_web_config():
    return {
        "apiKey": env_value(
            "FIREBASE_API_KEY",
            "SHOPPING_APP_FIREBASE_WEB_API_KEY",
            default=DEFAULT_FIREBASE_WEB_CONFIG["apiKey"],
        ),
        "authDomain": env_value(
            "FIREBASE_AUTH_DOMAIN",
            "SHOPPING_APP_FIREBASE_AUTH_DOMAIN",
            default=DEFAULT_FIREBASE_WEB_CONFIG["authDomain"],
        ),
        "projectId": env_value(
            "FIREBASE_PROJECT_ID",
            "SHOPPING_APP_FIREBASE_PROJECT_ID",
            default=DEFAULT_FIREBASE_WEB_CONFIG["projectId"],
        ),
        "storageBucket": env_value(
            "FIREBASE_STORAGE_BUCKET",
            "SHOPPING_APP_FIREBASE_STORAGE_BUCKET",
            default=DEFAULT_FIREBASE_WEB_CONFIG["storageBucket"],
        ),
        "messagingSenderId": env_value(
            "FIREBASE_MESSAGING_SENDER_ID",
            "SHOPPING_APP_FIREBASE_MESSAGING_SENDER_ID",
            default=DEFAULT_FIREBASE_WEB_CONFIG["messagingSenderId"],
        ),
        "appId": env_value(
            "FIREBASE_APP_ID",
            "SHOPPING_APP_FIREBASE_APP_ID",
            default=DEFAULT_FIREBASE_WEB_CONFIG["appId"],
        ),
        "measurementId": env_value(
            "FIREBASE_MEASUREMENT_ID",
            "SHOPPING_APP_FIREBASE_MEASUREMENT_ID",
            default=DEFAULT_FIREBASE_WEB_CONFIG["measurementId"],
        ),
    }


def firebase_user_from_id_token(id_token):
    id_token = str(id_token or "").strip()
    api_key = firebase_web_config().get("apiKey", "")

    if not id_token:
        return {"ok": False, "errors": ["Firebase ID token is missing."]}

    if not api_key:
        return {"ok": False, "errors": ["Firebase web API key is not configured."]}

    try:
        response = requests.post(
            FIREBASE_ACCOUNTS_LOOKUP_URL,
            params={"key": api_key},
            json={"idToken": id_token},
            timeout=15,
        )
    except Exception as err:
        return {"ok": False, "errors": [f"Firebase token verification failed. {err}"]}

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code >= 400:
        message = (
            payload.get("error", {}).get("message")
            if isinstance(payload.get("error"), dict)
            else ""
        )
        return {"ok": False, "errors": [message or "Firebase ID token is invalid."]}

    users = payload.get("users") if isinstance(payload, dict) else None
    if not users:
        return {"ok": False, "errors": ["Firebase ID token is invalid."]}

    firebase_user = users[0]
    if not str(firebase_user.get("localId") or "").strip():
        return {"ok": False, "errors": ["Firebase user id is missing."]}

    return {"ok": True, "firebase_user": firebase_user}
