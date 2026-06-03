import os

from flask import Flask
from flask import request
from flask import session

from PushShoppingList.routes.account_routes import account_bp
from PushShoppingList.routes.feedback_routes import feedback_bp
from PushShoppingList.routes.main_routes import main_bp
from PushShoppingList.routes.pantry_routes import pantry_bp
from PushShoppingList.routes.recipe_routes import recipe_bp
from PushShoppingList.routes.store_routes import store_bp
from PushShoppingList.routes.product_routes import product_bp
from PushShoppingList.services.email_service import password_reset_email_configured
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import pending_two_factor_setup


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # Flask sessions keep the signed-in user id across refreshes.
    app.secret_key = os.getenv("SHOPPING_APP_SECRET_KEY", "dev-shopping-list-session-key")

    app.register_blueprint(account_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(pantry_bp)
    app.register_blueprint(recipe_bp)
    app.register_blueprint(store_bp)
    app.register_blueprint(product_bp)

    @app.context_processor
    def inject_current_user():
        return {
            "current_user": current_public_user(),
            "password_reset_email_configured": password_reset_email_configured(),
            "pending_two_factor_sign_in": bool(session.get("pending_2fa_user_id")),
            "two_factor_setup": pending_two_factor_setup(session.get("user_id")),
            "two_factor_backup_codes": session.pop("two_factor_backup_codes", None),
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

        return response

    return app
