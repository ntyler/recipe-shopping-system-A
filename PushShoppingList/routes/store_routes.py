from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request

from PushShoppingList.services.store_settings_service import add_store
from PushShoppingList.services.store_settings_service import clean_store_settings
from PushShoppingList.services.store_settings_service import delete_store
from PushShoppingList.services.home_store_location_service import select_nearby_store_location
from PushShoppingList.services.item_state_service import reset_item_stores
from PushShoppingList.services.item_state_service import save_item_store
from PushShoppingList.services.store_settings_service import load_store_settings
from PushShoppingList.services.store_settings_service import save_enabled_stores
from PushShoppingList.services.store_settings_service import update_store
from PushShoppingList.services.store_settings_service import update_store_credentials
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import is_admin_user

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
    if not current_user_can_manage_stores():
        return forbidden_store_response("Only the administrator can activate or deactivate stores.")

    settings = save_enabled_stores(request.form.getlist("enabled_stores"))

    if wants_json_response():
        return jsonify({
            "ok": True,
            "enabled_stores": settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/add_store", methods=["POST"])
def add_store_route():
    if not current_user_can_manage_stores():
        return forbidden_store_response("Only the administrator can add stores.")

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
        public_settings = clean_store_settings(settings)
        return jsonify({
            "ok": True,
            "stores": public_settings["stores"],
            "enabled_stores": public_settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/update_store/<store_key>", methods=["POST"])
def update_store_route(store_key):
    user = current_public_user()

    if not user:
        return forbidden_store_response("Sign in before updating store login details.")

    if is_admin_user(user):
        settings = update_store(store_key, request.form)
    else:
        settings = update_store_credentials(store_key, request.form)

    if wants_json_response():
        public_settings = clean_store_settings(settings)
        return jsonify({
            "ok": True,
            "stores": public_settings["stores"],
            "enabled_stores": public_settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/delete_store/<store_key>", methods=["POST"])
def delete_store_route(store_key):
    if not current_user_can_manage_stores():
        return forbidden_store_response("Only the administrator can remove stores.")

    settings = delete_store(store_key)

    if wants_json_response():
        public_settings = clean_store_settings(settings)
        return jsonify({
            "ok": True,
            "stores": public_settings["stores"],
            "enabled_stores": public_settings["enabled_stores"],
        })

    return redirect("/#store-options")


@store_bp.route("/reset_stores", methods=["POST"])
def reset_stores_route():
    reset_item_stores()

    if wants_json_response():
        return jsonify({
            "ok": True,
        })

    return redirect("/")


@store_bp.route("/select_nearby_store_location/<store_key>", methods=["POST"])
def select_nearby_store_location_route(store_key):
    result = select_nearby_store_location(store_key, request.form.get("nearby_index"))

    if wants_json_response():
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    return redirect("/#storeOptionsSection")


@store_bp.route("/save_item_store", methods=["POST"])
def save_item_store_route():
    item_key = str(request.form.get("item_key", "") or "").strip()
    store_key = str(request.form.get("store_key", "") or "").strip()

    if item_key:
        save_item_store(item_key, store_key)

    if wants_json_response():
        return jsonify({
            "ok": True,
        })

    return redirect("/")


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )


def current_user_can_manage_stores():
    return is_admin_user(current_public_user())


def forbidden_store_response(error):
    if wants_json_response():
        return jsonify({
            "ok": False,
            "error": error,
        }), 403

    return redirect("/#store-options")
