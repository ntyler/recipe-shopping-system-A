import json
import logging
import os


DEFAULT_FIREBASE_WEB_CONFIG = {
    "apiKey": "AIzaSyAzUeQBO2t98GVp_8zKpTFvmm_6ePX-U2U",
    "authDomain": "recipe-shopping-app-d4a07.firebaseapp.com",
    "projectId": "recipe-shopping-app-d4a07",
    "storageBucket": "recipe-shopping-app-d4a07.firebasestorage.app",
    "messagingSenderId": "1084430352486",
    "appId": "1:1084430352486:web:71b25f380928a61bdfeda7",
    "measurementId": "G-J44GKNGRDY",
}
FIREBASE_ADMIN_APP_NAME = "recipe_shopping_app"
LOGGER = logging.getLogger(__name__)


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


def firebase_admin_app():
    try:
        import firebase_admin
        from firebase_admin import credentials
    except Exception:
        LOGGER.error("Firebase Admin SDK is not installed. Add firebase-admin to requirements and install it.")
        return None, {
            "ok": False,
            "code": "firebase_admin_sdk_missing",
            "errors": ["Backend Firebase Admin SDK is not installed."],
        }

    try:
        return firebase_admin.get_app(FIREBASE_ADMIN_APP_NAME), {"ok": True}
    except ValueError:
        pass

    service_account_path = env_value("FIREBASE_SERVICE_ACCOUNT_PATH")
    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()

    if service_account_path:
        try:
            credential = credentials.Certificate(service_account_path)
        except Exception as err:
            LOGGER.error("Firebase service account path could not be loaded: %s", err.__class__.__name__)
            return None, {
                "ok": False,
                "code": "firebase_admin_credentials_invalid",
                "errors": ["Backend Firebase Admin credentials could not be loaded from FIREBASE_SERVICE_ACCOUNT_PATH."],
            }
    elif service_account_json:
        try:
            credential = credentials.Certificate(json.loads(service_account_json))
        except Exception as err:
            LOGGER.error("Firebase service account JSON could not be loaded: %s", err.__class__.__name__)
            return None, {
                "ok": False,
                "code": "firebase_admin_credentials_invalid",
                "errors": ["Backend Firebase Admin credentials could not be loaded from FIREBASE_SERVICE_ACCOUNT_JSON."],
            }
    else:
        LOGGER.error(
            "Firebase Admin credentials are missing. Set FIREBASE_SERVICE_ACCOUNT_PATH or FIREBASE_SERVICE_ACCOUNT_JSON."
        )
        return None, {
            "ok": False,
            "code": "firebase_admin_credentials_missing",
            "errors": [
                "Backend Firebase Admin credentials are missing. Set FIREBASE_SERVICE_ACCOUNT_PATH or FIREBASE_SERVICE_ACCOUNT_JSON."
            ],
        }

    try:
        return firebase_admin.initialize_app(credential, name=FIREBASE_ADMIN_APP_NAME), {"ok": True}
    except Exception as err:
        LOGGER.error("Firebase Admin initialization failed: %s", err.__class__.__name__)
        return None, {
            "ok": False,
            "code": "firebase_admin_initialization_failed",
            "errors": ["Backend Firebase Admin initialization failed."],
        }


def firebase_user_from_id_token(id_token):
    id_token = str(id_token or "").strip()

    if not id_token:
        return {"ok": False, "errors": ["Firebase ID token is missing."]}

    admin_app, app_result = firebase_admin_app()

    if not app_result.get("ok"):
        return app_result

    try:
        from firebase_admin import auth

        firebase_user = auth.verify_id_token(id_token, app=admin_app)
    except Exception as err:
        LOGGER.warning("Firebase ID token verification failed: %s", err.__class__.__name__)
        return {
            "ok": False,
            "code": "firebase_token_verification_failed",
            "errors": ["Backend Firebase token verification failed."],
        }

    if not str(firebase_user.get("uid") or "").strip():
        return {"ok": False, "errors": ["Firebase user id is missing."]}

    return {"ok": True, "firebase_user": firebase_user}
