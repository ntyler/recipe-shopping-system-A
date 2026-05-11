from flask import Flask

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

    return app