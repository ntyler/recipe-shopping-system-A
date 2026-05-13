from flask import Blueprint
from flask import jsonify

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules

product_bp = Blueprint("product_bp", __name__)


@product_bp.route("/api/products")
def api_products():
    products = []
    annotated_products = [
        annotate_product_food_rules(product)
        for product in products
    ]

    return jsonify({
        "food_rules": load_food_rules(),
        "products": annotated_products,
    })
