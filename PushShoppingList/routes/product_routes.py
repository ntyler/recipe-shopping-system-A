from flask import Blueprint
from flask import jsonify

product_bp = Blueprint("product_bp", __name__)


@product_bp.route("/api/products")
def api_products():
    return jsonify({
        "products": []
    })
