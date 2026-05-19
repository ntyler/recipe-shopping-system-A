from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import suggest_food_rules_from_prompt
from PushShoppingList.services.food_rules_service import update_food_rules
from PushShoppingList.services.product_selection_service import clear_product_choices
from PushShoppingList.services.product_selection_service import grab_best_products
from PushShoppingList.services.product_selection_service import normalize_item_key
from PushShoppingList.services.product_selection_service import product_choice_for_item
from PushShoppingList.services.product_selection_service import product_choices_by_item
from PushShoppingList.services.product_selection_service import select_product_choice

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


@product_bp.route("/api/food_rules")
def api_food_rules_route():
    return jsonify({
        "ok": True,
        "food_rules": load_food_rules(),
    })


@product_bp.route("/api/food_rules", methods=["POST"])
def api_save_food_rules_route():
    data = request.get_json(silent=True) or {}
    rules = update_food_rules(data.get("food_rules", data))

    return jsonify({
        "ok": True,
        "food_rules": rules,
    })


@product_bp.route("/api/food_rules/suggest", methods=["POST"])
def api_suggest_food_rules_route():
    data = request.get_json(silent=True) or {}
    result = suggest_food_rules_from_prompt(
        data.get("prompt", ""),
        data.get("food_rules"),
    )
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@product_bp.route("/preview_grab_best_products", methods=["POST"])
def preview_grab_best_products_route():
    result = grab_best_products()

    if wants_json_response():
        return jsonify(result)

    return redirect("/")


@product_bp.route("/api/grab_best_products", methods=["POST"])
def api_grab_best_products_route():
    data = request.get_json(silent=True) or {}
    items = data.get("items") if isinstance(data.get("items"), list) else None

    return jsonify(grab_best_products(items=items))


@product_bp.route("/find_products", methods=["POST"])
def find_products_route():
    item = str(request.form.get("item", "") or "").strip()

    if not item:
        if wants_json_response():
            return jsonify({
                "ok": False,
                "error": "No ingredient was provided.",
            }), 400

        return redirect("/")

    result = grab_best_products(items=[item])

    if wants_json_response():
        return jsonify(result)

    return redirect("/")


@product_bp.route("/clear_product_picks", methods=["POST"])
def clear_product_picks_route():
    clear_product_choices()

    if wants_json_response():
        return jsonify({"ok": True})

    return redirect("/")


@product_bp.route("/api/product_choices")
def api_product_choices_route():
    return jsonify({
        "ok": True,
        "items": product_choices_by_item(),
    })


@product_bp.route("/api/product_choice")
def api_product_choice_route():
    item_key = normalize_item_key(request.args.get("item_key", ""))
    choice = product_choice_for_item(item_key)

    if not choice:
        return jsonify({
            "ok": False,
            "error": "No product choices are saved for that ingredient.",
            "item_key": item_key,
        }), 404

    return jsonify({
        "ok": True,
        "item_key": item_key,
        "choice": choice,
    })


@product_bp.route("/api/product_choice/select", methods=["POST"])
def api_select_product_choice_route():
    data = request.get_json(silent=True) or {}
    result = select_product_choice(
        data.get("item_key", ""),
        data.get("product_id", ""),
    )
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )
