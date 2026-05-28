from flask import Flask
from flask import request

from PushShoppingList.routes.main_routes import main_bp
from PushShoppingList.routes.recipe_routes import recipe_bp
from PushShoppingList.routes.store_routes import store_bp
from PushShoppingList.routes.product_routes import product_bp


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.register_blueprint(main_bp)
    app.register_blueprint(recipe_bp)
    app.register_blueprint(store_bp)
    app.register_blueprint(product_bp)

    @app.after_request
    def add_local_reorder_cors_headers(response):
        origin = request.headers.get("Origin", "")
        local_origins = (
            "http://127.0.0.1:",
            "http://localhost:",
        )

        if request.path == "/api/recipe_urls/reorder" and origin.startswith(local_origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers.add("Vary", "Origin")

        return response

    return app
