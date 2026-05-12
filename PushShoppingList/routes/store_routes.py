from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.services.store_settings_service import add_store
from PushShoppingList.services.store_settings_service import delete_store
from PushShoppingList.services.store_settings_service import load_store_settings
from PushShoppingList.services.store_settings_service import save_enabled_stores
from PushShoppingList.services.store_settings_service import update_store

store_bp = Blueprint("store_bp", __name__)


@store_bp.route("/api/stores")
def api_stores():
    settings = load_store_settings()

    return jsonify({
        "stores": list(settings["stores"].keys()),
        "enabled_stores": settings["enabled_stores"],
    })


@store_bp.route("/save_store_settings", methods=["POST"])
def save_store_settings_route():
    settings = save_enabled_stores(request.form.getlist("enabled_stores"))

    if wants_json_response():
        return jsonify({
            "ok": True,
            "enabled_stores": settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/add_store", methods=["POST"])
def add_store_route():
    label = str(request.form.get("store_label", "") or "").strip()

    if not label:
        if wants_json_response():
            return jsonify({
                "ok": False,
                "error": "Store name is required.",
            }), 400

        return redirect("/#store-options")

    settings = add_store(request.form)

    if wants_json_response():
        return jsonify({
            "ok": True,
            "stores": settings["stores"],
            "enabled_stores": settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/update_store/<store_key>", methods=["POST"])
def update_store_route(store_key):
    update_store(store_key, request.form)

    return redirect("/#store-options")


@store_bp.route("/delete_store/<store_key>", methods=["POST"])
def delete_store_route(store_key):
    settings = delete_store(store_key)

    if wants_json_response():
        return jsonify({
            "ok": True,
            "stores": settings["stores"],
            "enabled_stores": settings["enabled_stores"],
        })

    return redirect("/#store-options")


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )
