from flask import Blueprint
from flask import jsonify

store_bp = Blueprint("store_bp", __name__)


@store_bp.route("/api/stores")
def api_stores():
    return jsonify({
        "stores": [
            "aldi",
            "meijer",
            "walmart",
            "target",
            "kroger",
        ]
    })
