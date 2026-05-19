from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import suggest_food_rules_from_prompt
from PushShoppingList.services.food_rules_service import update_food_rules
from PushShoppingList.services.home_address_service import save_home_address
from PushShoppingList.services.product_selection_service import clear_product_choices
from PushShoppingList.services.product_selection_service import grab_best_products
from PushShoppingList.services.product_selection_service import load_product_progress
from PushShoppingList.services.product_selection_service import normalize_item_key
from PushShoppingList.services.product_selection_service import product_choice_for_item
from PushShoppingList.services.product_selection_service import product_choices_by_item
from PushShoppingList.services.product_selection_service import select_product_choice
from PushShoppingList.services.rules_display_service import save_home_store_rule_text
from PushShoppingList.services.rules_display_service import save_rules_display_section
from PushShoppingList.services.store_settings_service import save_enabled_stores

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


@product_bp.route("/api/rules_display/home_stores", methods=["POST"])
def api_save_home_store_rules_route():
    data = request.get_json(silent=True) or {}
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    enabled_stores = data.get("enabled_stores") if isinstance(data.get("enabled_stores"), list) else []
    saved_address = save_home_address({
        "address_street": address.get("street", ""),
        "address_apartment": address.get("apartment", ""),
        "address_city": address.get("city", ""),
        "address_county": address.get("county", ""),
        "address_state": address.get("state", ""),
        "address_zip": address.get("zip", ""),
        "address_country": address.get("country", ""),
    })
    store_settings = save_enabled_stores(enabled_stores)
    section = save_home_store_rule_text(data.get("rows", []))

    return jsonify({
        "ok": True,
        "home_address": saved_address,
        "enabled_stores": store_settings["enabled_stores"],
        "section": section,
    })


@product_bp.route("/api/rules_display/<section_key>", methods=["POST"])
def api_save_rules_display_section_route(section_key):
    data = request.get_json(silent=True) or {}
    result = save_rules_display_section(section_key, data.get("rows", []))
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@product_bp.route("/preview_grab_best_products", methods=["POST"])
def preview_grab_best_products_route():
    result = grab_best_products(job_id=request.form.get("job_id"))

    if wants_json_response():
        return jsonify(result)

    return redirect("/")


@product_bp.route("/api/grab_best_products", methods=["POST"])
def api_grab_best_products_route():
    data = request.get_json(silent=True) or {}
    items = data.get("items") if isinstance(data.get("items"), list) else None

    return jsonify(grab_best_products(items=items, job_id=data.get("job_id")))


@product_bp.route("/api/product_progress")
def api_product_progress_route():
    progress = load_product_progress()
    job_id = request.args.get("job_id")

    if job_id and progress.get("job_id") != job_id:
        return jsonify({
            "active": False,
            "job_id": job_id,
            "status": "idle",
            "summary": "Waiting for product search to start.",
            "total": 0,
            "completed": 0,
            "percent": 0,
            "downloads": [],
        })

    return jsonify(progress)


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

    result = grab_best_products(items=[item], job_id=request.form.get("job_id"))

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
    store_key = str(request.args.get("store_key", "") or "").strip()
    choice = product_choice_for_item(item_key, store_key=store_key)

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
        data.get("store_key", ""),
    )
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )
