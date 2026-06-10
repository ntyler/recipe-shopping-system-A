import os
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
from PushShoppingList.routes.main_routes import main_bp
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
from PushShoppingList.services.sms_service import password_reset_sms_configured
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import is_admin_user
from PushShoppingList.services.user_account_service import pending_two_factor_setup
from PushShoppingList.services.recipe_extract_service import log_openai_startup_diagnostics


PUBLIC_ENDPOINTS = {
    "main_bp.index",
    "static",
    "account_bp.firebase_session_route",
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
    "account_bp.open_two_factor_recovery_route",
    "account_bp.complete_two_factor_recovery_route",
    "account_bp.request_password_reset_route",
    "account_bp.open_password_reset_route",
    "account_bp.complete_password_reset_route",
    "account_bp.sign_out_route",
    "recipe_bp.recipe_archive_pdf_route",
    "recipe_bp.recipe_cover_image_route",
    "pdf_bp.share_pdf_route",
    "pdf_bp.download_shared_pdf_route",
    "feedback_bp.submit_feedback_route",
}

GUEST_BLOCKED_BLUEPRINTS = {
    "pantry_bp",
}

GUEST_BLOCKED_ENDPOINTS = {
    "account_bp.open_admin_support_record_route",
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
    "main_bp.api_openai_usage_dashboard_route",
    "main_bp.update_chatgpt_models_route",
    "main_bp.save_home_address_route",
    "main_bp.update_home_address_history_label_route",
    "main_bp.delete_home_address_history_entry_route",
    "main_bp.reverse_geocode_route",
    "main_bp.address_options_route",
    "main_bp.complete_address_route",
    "store_bp.save_store_settings_route",
    "store_bp.add_store_route",
    "store_bp.update_store_route",
    "store_bp.delete_store_route",
    "store_bp.select_nearby_store_location_route",
}

PROTECTED_BLUEPRINTS = {
    "main_bp",
    "pantry_bp",
    "pdf_bp",
    "product_bp",
    "recipe_bp",
    "store_bp",
    "feedback_bp",
}

ADMIN_ENDPOINTS = {
    "pdf_bp.pdfs_route",
    "pdf_bp.view_pdf_route",
    "pdf_bp.create_pdf_share_route",
    "pdf_bp.revoke_pdf_share_route",
    "pdf_bp.upload_pdf_to_cloudflare_route",
    "main_bp.update_chatgpt_models_route",
    "feedback_bp.update_feedback_admin_route",
}


def wants_json_response():
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/auth/")
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
        "AI Pantry is only available for full accounts. "
        "Create a free account to save pantry items, store preferences, and long-term shopping history."
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


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # Flask sessions keep the signed-in user id across refreshes.
    app.secret_key = os.getenv("SHOPPING_APP_SECRET_KEY", "dev-shopping-list-session-key")
    app.permanent_session_lifetime = timedelta(days=30)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    log_openai_startup_diagnostics(
        debug_mode=app.debug,
        reloader_mode=os.environ.get("WERKZEUG_RUN_MAIN") == "true",
    )

    app.register_blueprint(account_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(main_bp)
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

        cleanup_expired_guest_sessions()

        if session.get("is_guest") and not get_current_guest_session():
            g.clear_guest_demo_cookie = True
            if endpoint != "account_bp.guest_expired_route":
                return redirect(url_for("account_bp.guest_expired_route"))

        if not current_user() and not session.get("is_guest"):
            remembered_status = remembered_guest_cookie_status(request.cookies.get(GUEST_COOKIE_NAME, ""))
            if remembered_status == "valid":
                restore_guest_session_from_cookie(request.cookies.get(GUEST_COOKIE_NAME, ""))
            elif remembered_status in {"invalid", "expired"}:
                g.clear_guest_demo_cookie = True
                if remembered_status == "expired" and endpoint == "main_bp.index":
                    return redirect(url_for("account_bp.guest_expired_route"))

        if endpoint in PUBLIC_ENDPOINTS:
            return None

        blueprint = endpoint.split(".", 1)[0] if "." in endpoint else ""
        if blueprint not in PROTECTED_BLUEPRINTS:
            return None

        user = current_user()
        full_account_active = bool(user or session.get("user_id"))
        guest_active = is_guest_session()
        if not full_account_active and not guest_active:
            return auth_required_response()

        if guest_active and (blueprint in GUEST_BLOCKED_BLUEPRINTS or endpoint in GUEST_BLOCKED_ENDPOINTS or endpoint in ADMIN_ENDPOINTS):
            return guest_restricted_response()

        if endpoint in ADMIN_ENDPOINTS and not is_admin_user(user):
            return admin_required_response()

        return None

    @app.context_processor
    def inject_current_user():
        return {
            "current_user": current_public_user(),
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

        if getattr(g, "clear_guest_demo_cookie", False):
            clear_guest_cookie(response)

        return response

    return app
