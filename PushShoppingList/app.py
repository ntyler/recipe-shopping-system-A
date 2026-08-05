import os
import mimetypes
import gzip
import secrets
import warnings
from datetime import timedelta

from flask import Flask
from flask import flash
from flask import g
from flask import jsonify
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from PushShoppingList.routes.account_routes import account_bp
from PushShoppingList.routes.feedback_routes import feedback_bp
from PushShoppingList.routes.job_routes import job_bp
from PushShoppingList.routes.main_routes import main_bp
from PushShoppingList.routes.menu_routes import menu_bp
from PushShoppingList.routes.pantry_routes import pantry_bp
from PushShoppingList.routes.pdf_routes import pdf_bp
from PushShoppingList.routes.recipe_routes import recipe_bp
from PushShoppingList.routes.store_routes import store_bp
from PushShoppingList.routes.product_routes import product_bp
from PushShoppingList.services.email_service import password_reset_email_configured
from PushShoppingList.services.guest_session_service import GUEST_COOKIE_NAME
from PushShoppingList.services.guest_session_service import clear_guest_cookie
from PushShoppingList.services.guest_session_service import cleanup_expired_guest_sessions
from PushShoppingList.services.guest_session_service import get_current_guest_session
from PushShoppingList.services.guest_session_service import guest_banner_context
from PushShoppingList.services.guest_session_service import is_guest_session
from PushShoppingList.services.guest_session_service import remembered_guest_cookie_status
from PushShoppingList.services.guest_session_service import restore_guest_session_from_cookie
from PushShoppingList.services.image_variant_service import generated_static_cache_seconds
from PushShoppingList.services.image_variant_service import is_cacheable_generated_static_path
from PushShoppingList.services.request_security_service import apply_private_no_store
from PushShoppingList.services.sms_service import password_reset_sms_configured
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import is_admin_user
from PushShoppingList.services.user_account_service import pending_two_factor_setup
from PushShoppingList.services.recipe_extract_service import log_openai_startup_diagnostics
from PushShoppingList.services.recipe_url_service import recipe_edit_page_url
from PushShoppingList.services.job_queue_service import log_job_queue_startup_diagnostics


mimetypes.add_type("image/webp", ".webp")


PUBLIC_ENDPOINTS = {
    "main_bp.index",
    "main_bp.terms_route",
    "main_bp.privacy_route",
    "main_bp.api_device_stale_route",
    "main_bp.api_device_status_route",
    "static",
    "account_bp.firebase_session_route",
    "account_bp.firebase_account_exists_route",
    "account_bp.firebase_login_route",
    "account_bp.firebase_logout_route",
    "account_bp.guest_start_route",
    "account_bp.guest_expired_route",
    "account_bp.guest_delete_route",
    "account_bp.logout_route",
    "account_bp.create_account_route",
    "account_bp.verify_account_creation_route",
    "account_bp.sign_in_route",
    "account_bp.verify_two_factor_route",
    "account_bp.cancel_two_factor_sign_in_route",
    "account_bp.request_two_factor_recovery_route",
    "account_bp.open_two_factor_recovery_route",
    "account_bp.complete_two_factor_recovery_route",
    "account_bp.request_password_reset_route",
    "account_bp.open_password_reset_route",
    "account_bp.complete_password_reset_route",
    "account_bp.open_account_delete_route",
    "account_bp.complete_account_delete_route",
    "account_bp.sign_out_route",
    "pdf_bp.share_pdf_route",
    "pdf_bp.download_shared_pdf_route",
    "feedback_bp.submit_feedback_route",
}

GUEST_BLOCKED_ENDPOINTS = {
    "account_bp.open_admin_support_record_route",
    "account_bp.update_admin_access_route",
    "account_bp.delete_expired_guest_demos_route",
    "account_bp.update_profile_route",
    "account_bp.update_notification_settings_route",
    "account_bp.start_device_notification_subscription_route",
    "account_bp.send_test_notification_route",
    "account_bp.request_phone_verification_route",
    "account_bp.confirm_phone_verification_route",
    "account_bp.request_account_delete_route",
    "account_bp.open_account_delete_route",
    "account_bp.complete_account_delete_route",
    "account_bp.start_two_factor_setup_route",
    "account_bp.enable_two_factor_route",
    "account_bp.cancel_two_factor_setup_route",
    "account_bp.disable_two_factor_route",
    "account_bp.regenerate_two_factor_backup_codes_route",
    "account_bp.request_two_factor_recovery_route",
    "main_bp.update_chatgpt_models_route",
    "store_bp.add_store_route",
    "store_bp.delete_store_route",
}

PROTECTED_BLUEPRINTS = {
    "account_bp",
    "main_bp",
    "pantry_bp",
    "pdf_bp",
    "product_bp",
    "recipe_bp",
    "job_bp",
    "menu_bp",
    "store_bp",
    "feedback_bp",
}

ADMIN_ENDPOINTS = {
    "pdf_bp.pdfs_route",
    "pdf_bp.view_pdf_route",
    "pdf_bp.create_pdf_share_route",
    "pdf_bp.revoke_pdf_share_route",
    "pdf_bp.upload_pdf_to_cloudflare_route",
    "pdf_bp.cloudflare_unlinked_pdfs_route",
    "pdf_bp.cloudflare_orphan_pdfs_route",
    "pdf_bp.delete_cloudflare_orphan_pdfs_route",
    "main_bp.update_chatgpt_models_route",
    "main_bp.recipe_master_data_backfill_route",
    "main_bp.recipe_master_data_backfill_status_route",
    "feedback_bp.update_feedback_admin_route",
}


KNOWN_INSECURE_SECRET_KEYS = frozenset({
    "dev-shopping-list-session-key",
    "replace-with-random-local-secret",
    "replace-with-a-random-secret",
    "change-me",
    "changeme",
    "secret",
})
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})
DEVELOPMENT_ENVIRONMENTS = frozenset({"development", "dev", "local"})
TEST_ENVIRONMENTS = frozenset({"testing", "test"})
MINIMUM_SECRET_KEY_LENGTH = 32


def runtime_environment(config=None):
    config = config or {}
    return str(
        config.get("SHOPPING_APP_ENV")
        or os.getenv("SHOPPING_APP_ENV")
        or os.getenv("FLASK_ENV")
        or "production"
    ).strip().lower()


def secret_key_is_acceptable(value):
    value = str(value or "").strip()
    return bool(
        len(value) >= MINIMUM_SECRET_KEY_LENGTH
        and value.lower() not in KNOWN_INSECURE_SECRET_KEYS
        and len(set(value)) >= 8
    )


def configure_session_security(app, supplied_config=None):
    """Configure signing and cookie security before the app accepts requests."""

    supplied_config = supplied_config or {}
    environment = runtime_environment(supplied_config)
    testing = bool(supplied_config.get("TESTING")) or environment in TEST_ENVIRONMENTS
    development = environment in DEVELOPMENT_ENVIRONMENTS
    production = not testing and not development
    configured_key = supplied_config.get("SECRET_KEY") or os.getenv("SHOPPING_APP_SECRET_KEY")

    if testing:
        if not secret_key_is_acceptable(configured_key):
            raise RuntimeError(
                "Testing requires an explicit deterministic SECRET_KEY or "
                "SHOPPING_APP_SECRET_KEY of at least 32 nontrivial characters."
            )
    elif production:
        if not secret_key_is_acceptable(configured_key):
            raise RuntimeError(
                "SHOPPING_APP_SECRET_KEY is required in production and must be "
                "at least 32 nontrivial characters without using a known default."
            )
    elif not secret_key_is_acceptable(configured_key):
        configured_key = secrets.token_urlsafe(48)
        warnings.warn(
            "SHOPPING_APP_SECRET_KEY is not securely configured; using an "
            "ephemeral local-development key. Signed-in sessions will reset "
            "when this process restarts.",
            RuntimeWarning,
            stacklevel=2,
        )

    app.config.update(
        SECRET_KEY=str(configured_key),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        SHOPPING_APP_ENV=environment,
    )


REGISTERED_SESSION_IDENTITY_KEYS = frozenset({
    "user_id",
    "firebase_uid",
    "email",
    "display_name",
    "picture",
    "provider",
    "is_admin",
    "pending_2fa_user_id",
    "pending_2fa_provider",
    "pending_2fa_context",
    "two_factor_backup_codes",
    "phone_verification_code",
    "admin_support_selected_user",
    "admin_support_reason",
    "admin_support_errors",
})


def clear_invalid_registered_session_identity():
    """Remove stale account state without disturbing an explicit guest session."""

    for key in REGISTERED_SESSION_IDENTITY_KEYS:
        session.pop(key, None)


def wants_json_response():
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/auth/")
        or request.path.startswith("/sections/")
        or request.path == "/recipe_pdf_link"
        or request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )


def auth_required_response():
    if wants_json_response():
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Sign in before managing this workspace.",
        }), 401

    flash("Sign in before managing this workspace.", "error")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


def admin_required_response():
    return jsonify({
        "ok": False,
        "success": False,
        "error": "Admin access is required.",
    }), 403


def guest_restricted_response():
    message = (
        "That account or admin setting is only available for full accounts. "
        "Create a free account to keep workspace settings permanently."
    )

    if wants_json_response():
        return jsonify({
            "ok": False,
            "success": False,
            "error": message,
            "guest_restricted": True,
        }), 403

    flash(message, "error")
    return redirect(url_for("main_bp.index", _anchor="userAccountSection"))


def gzip_response_if_supported(response):
    if (
        request.method == "HEAD"
        or response.status_code < 200
        or response.status_code >= 300
        or response.direct_passthrough
        or response.headers.get("Content-Encoding")
        or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
    ):
        return response

    compressible_mimetypes = {
        "application/javascript",
        "application/json",
        "text/css",
        "text/html",
        "text/javascript",
        "text/plain",
    }
    if response.mimetype not in compressible_mimetypes:
        return response

    body = response.get_data()
    if len(body) < 1024:
        return response

    response.set_data(gzip.compress(body, compresslevel=6))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    response.headers.pop("ETag", None)
    response.headers.add("Vary", "Accept-Encoding")
    return response


def create_app(config=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    config = dict(config or {})
    if config:
        app.config.update(config)
    configure_session_security(app, config)
    app.permanent_session_lifetime = timedelta(days=30)
    log_openai_startup_diagnostics(
        debug_mode=app.debug,
        reloader_mode=os.environ.get("WERKZEUG_RUN_MAIN") == "true",
    )
    log_job_queue_startup_diagnostics()

    app.register_blueprint(account_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(job_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(menu_bp)
    app.register_blueprint(pantry_bp)
    app.register_blueprint(pdf_bp)
    app.register_blueprint(recipe_bp)
    app.register_blueprint(store_bp)
    app.register_blueprint(product_bp)

    @app.before_request
    def protect_workspace_routes():
        if request.method == "OPTIONS":
            return None

        endpoint = request.endpoint or ""
        g.clear_guest_demo_cookie = False
        g.session_identity_validated = False
        g.authenticated_user_id = ""
        g.authenticated_guest_session_id = ""

        cleanup_expired_guest_sessions()

        if session.get("is_guest") and not get_current_guest_session():
            if str(session.get("user_id") or "").strip():
                clear_invalid_registered_session_identity()
            g.clear_guest_demo_cookie = True
            if endpoint != "account_bp.guest_expired_route":
                return redirect(url_for("account_bp.guest_expired_route"))

        raw_session_user_id = str(session.get("user_id") or "").strip()
        stale_registered_identity = False
        if session.get("is_guest"):
            # Guest workspaces are intentionally userless, including when a
            # stale or malformed signed session contains both identity modes.
            if raw_session_user_id:
                clear_invalid_registered_session_identity()
            user = None
        else:
            user = current_user()
            if raw_session_user_id and not user:
                clear_invalid_registered_session_identity()
                stale_registered_identity = True

        if not user and not session.get("is_guest") and not stale_registered_identity:
            remembered_status = remembered_guest_cookie_status(request.cookies.get(GUEST_COOKIE_NAME, ""))
            if remembered_status == "valid":
                restore_guest_session_from_cookie(request.cookies.get(GUEST_COOKIE_NAME, ""))
            elif remembered_status in {"invalid", "expired"}:
                g.clear_guest_demo_cookie = True
                if remembered_status == "expired" and endpoint == "main_bp.index":
                    return redirect(url_for("account_bp.guest_expired_route"))

        guest_active = is_guest_session()
        if guest_active:
            user = None
        elif not user:
            user = current_user()

        g.authenticated_user_id = str((user or {}).get("user_id") or "")
        g.authenticated_guest_session_id = str(
            session.get("guest_session_id") or ""
        ) if guest_active else ""
        g.session_identity_validated = True

        # Guest restrictions must run before the public-endpoint exit because
        # a few token/opening routes are intentionally public to signed-out
        # users yet still mutate full accounts and must be unavailable to a
        # guest workspace.
        if guest_active and (endpoint in GUEST_BLOCKED_ENDPOINTS or endpoint in ADMIN_ENDPOINTS):
            return guest_restricted_response()

        if endpoint in PUBLIC_ENDPOINTS:
            return None

        blueprint = endpoint.split(".", 1)[0] if "." in endpoint else ""
        if blueprint not in PROTECTED_BLUEPRINTS:
            return None

        if not user and not guest_active:
            return auth_required_response()

        if endpoint in ADMIN_ENDPOINTS and not is_admin_user(user):
            return admin_required_response()

        return None

    @app.context_processor
    def inject_current_user():
        return {
            "current_user": current_public_user(),
            "recipe_edit_page_url": recipe_edit_page_url,
            "password_reset_email_configured": password_reset_email_configured(),
            "password_reset_sms_configured": password_reset_sms_configured(),
            "pending_two_factor_sign_in": bool(session.get("pending_2fa_user_id")),
            "pending_two_factor_context": session.get("pending_2fa_context", ""),
            "two_factor_setup": pending_two_factor_setup(session.get("user_id")),
            "two_factor_backup_codes": session.pop("two_factor_backup_codes", None),
            "guest_demo": guest_banner_context(),
            "is_guest_demo": is_guest_session(),
        }

    @app.after_request
    def add_local_reorder_cors_headers(response):
        origin = request.headers.get("Origin", "")
        local_origins = (
            "http://127.0.0.1:",
            "http://localhost:",
        )

        reorder_paths = {
            "/api/recipe_urls/reorder",
            "/api/cookbooks/reorder",
        }

        if request.path in reorder_paths and origin.startswith(local_origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers.add("Vary", "Origin")

        if is_cacheable_generated_static_path(request.path):
            if request.path.lower().endswith(".webp"):
                response.mimetype = "image/webp"
            response.headers["Cache-Control"] = (
                f"public, max-age={generated_static_cache_seconds()}, immutable"
            )
        elif request.endpoint != "static":
            # Dynamic routes may depend on the signed Flask session even when
            # they return redirects, errors, JSON, or binary files. A single
            # authoritative policy prevents one route/status branch from
            # accidentally retaining private workspace data in a browser or
            # intermediary cache. Truly static files keep Flask's normal
            # asset policy; generated static bytes retain their immutable URL
            # policy above.
            apply_private_no_store(response)

        if getattr(g, "clear_guest_demo_cookie", False):
            clear_guest_cookie(response)

        return gzip_response_if_supported(response)

    return app
