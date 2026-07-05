import mimetypes

from flask import Blueprint
from flask import abort
from flask import jsonify
from flask import redirect
from flask import request
from flask import send_file
from flask import session
from flask import url_for

from PushShoppingList.services.pantry_service import DEFAULT_CONFIDENCE_BY_SOURCE
from PushShoppingList.services.pantry_service import add_pantry_storage_location
from PushShoppingList.services.pantry_service import add_or_increment_pantry_item
from PushShoppingList.services.pantry_service import apply_pantry_item_name_suggestion
from PushShoppingList.services.pantry_service import clean_storage_location
from PushShoppingList.services.pantry_service import delete_pantry_item
from PushShoppingList.services.pantry_service import delete_pantry_items
from PushShoppingList.services.pantry_service import generate_pantry_item_image
from PushShoppingList.services.pantry_service import hydrate_receipt_review_dates
from PushShoppingList.services.pantry_service import pantry_name_suggestion
from PushShoppingList.services.pantry_service import pantry_receipt_upload_file_path
from PushShoppingList.services.pantry_service import receipt_candidate_display_storage_location
from PushShoppingList.services.pantry_service import remove_pantry_storage_locations
from PushShoppingList.services.pantry_service import rename_pantry_storage_location
from PushShoppingList.services.pantry_service import save_receipt_upload
from PushShoppingList.services.pantry_service import save_pantry_item_image_upload
from PushShoppingList.services.pantry_service import storage_location_label
from PushShoppingList.services.pantry_service import update_pantry_item
from PushShoppingList.services.pantry_service import update_pantry_item_lifecycle_action
from PushShoppingList.services.pantry_service import update_receipt_history_status
from PushShoppingList.services.openai_usage_service import openai_usage_dashboard_for_user
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.user_account_service import current_user


pantry_bp = Blueprint("pantry_bp", __name__)


def pantry_message(category, text):
    session["pantry_messages"] = [{"category": category, "text": text}]


def with_openai_usage_dashboard(result):
    if not isinstance(result, dict):
        return result

    return {
        **result,
        "openai_usage_dashboard": openai_usage_dashboard_for_user(current_user()),
    }


def selected_storage_location(choice, custom_value=""):
    if str(choice or "") == "__custom__":
        return clean_storage_location(custom_value)
    return clean_storage_location(choice)


@pantry_bp.route("/pantry/items/add", methods=["POST"])
def add_pantry_item_route():
    ingredient_name = str(request.form.get("ingredient_name") or "").strip()

    if not ingredient_name:
        pantry_message("error", "Ingredient name is required.")
        return redirect(url_for("main_bp.index", _anchor="aiPantryAddItems"))

    result = add_or_increment_pantry_item({
        "ingredient_name": ingredient_name,
        "product_name": request.form.get("product_name", ""),
        "store": request.form.get("store", ""),
        "quantity": request.form.get("quantity") or 1,
        "unit": request.form.get("unit", ""),
        "store_section": request.form.get("store_section", ""),
        "source": "manual",
        "confidence": DEFAULT_CONFIDENCE_BY_SOURCE["manual"],
        "notes": request.form.get("notes", ""),
        "purchased_date": request.form.get("purchased_date", ""),
        "opened_date": request.form.get("opened_date", ""),
        "expiration_date": request.form.get("expiration_date", ""),
        "freeze_by_date": request.form.get("freeze_by_date", ""),
        "frozen_date": request.form.get("frozen_date", ""),
        "storage_location": request.form.get("storage_location", ""),
        "status": request.form.get("status", ""),
    })
    action = "added" if result.get("created") else "updated"
    pantry_message("success", f"{ingredient_name} {action} in pantry.")
    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


@pantry_bp.route("/pantry/items/<item_id>/update", methods=["POST"])
def update_pantry_item_route(item_id):
    result = update_pantry_item(
        item_id,
        {
            "quantity": request.form.get("quantity"),
            "unit": request.form.get("unit"),
            "store_section": request.form.get("store_section"),
            "notes": request.form.get("notes"),
            "purchased_date": request.form.get("purchased_date"),
            "opened_date": request.form.get("opened_date"),
            "expiration_date": request.form.get("expiration_date"),
            "freeze_by_date": request.form.get("freeze_by_date"),
            "frozen_date": request.form.get("frozen_date"),
            "storage_location": request.form.get("storage_location"),
            "status": request.form.get("status"),
        },
    )
    pantry_message("success" if result.get("ok") else "error", "Pantry item updated." if result.get("ok") else result.get("error", "Unable to update pantry item."))
    anchor = f"pantryItem-{item_id}" if result.get("ok") else "aiPantryInventory"
    return redirect(url_for("main_bp.index", _anchor=anchor))


@pantry_bp.route("/pantry/locations/add", methods=["POST"])
def add_pantry_storage_location_route():
    result = add_pantry_storage_location(request.form.get("storage_location", ""))
    if result.get("ok") and result.get("created"):
        pantry_message("success", f"Added pantry location {result.get('label')}.")
    elif result.get("ok"):
        pantry_message("success", f"Pantry location {result.get('label')} already exists.")
    else:
        pantry_message("error", result.get("error", "Unable to add pantry location."))
    return redirect(url_for("main_bp.index", _anchor="aiPantryLocations"))


@pantry_bp.route("/pantry/locations/delete", methods=["POST"])
def delete_pantry_storage_locations_route():
    result = remove_pantry_storage_locations(request.form.getlist("storage_location"))
    deleted_count = int(result.get("deleted_count") or 0)

    if result.get("ok") and deleted_count:
        location_label = "location" if deleted_count == 1 else "locations"
        pantry_message("success", f"Removed {deleted_count} pantry {location_label}.")
    else:
        pantry_message("error", result.get("error", "Unable to remove pantry locations."))

    return redirect(url_for("main_bp.index", _anchor="aiPantryLocations"))


@pantry_bp.route("/pantry/locations/update", methods=["POST"])
def update_pantry_storage_location_route():
    result = rename_pantry_storage_location(
        request.form.get("old_storage_location", ""),
        request.form.get("storage_location", ""),
    )

    if result.get("ok") and result.get("changed"):
        pantry_message("success", f"Updated pantry location to {result.get('label')}.")
    elif result.get("ok"):
        pantry_message("success", f"Pantry location {result.get('label')} is unchanged.")
    else:
        pantry_message("error", result.get("error", "Unable to update pantry location."))

    return redirect(url_for("main_bp.index", _anchor="aiPantryLocations"))


@pantry_bp.route("/pantry/items/<item_id>/lifecycle", methods=["POST"])
def update_pantry_item_lifecycle_route(item_id):
    result = update_pantry_item_lifecycle_action(
        item_id,
        request.form.get("action", ""),
    )
    pantry_message(
        "success" if result.get("ok") else "error",
        "Pantry item updated." if result.get("ok") else result.get("error", "Unable to update pantry item."),
    )
    return redirect(url_for("main_bp.index", _anchor="aiPantryUseSoon"))


@pantry_bp.route("/pantry/items/delete_selected", methods=["POST"])
def delete_selected_pantry_items_route():
    item_ids = request.form.getlist("pantry_item_id") or request.form.getlist("item_id")
    result = delete_pantry_items(item_ids)
    deleted_count = int(result.get("deleted_count") or 0)

    if not item_ids:
        pantry_message("error", "Select at least one pantry item to delete.")
    elif deleted_count:
        item_label = "item" if deleted_count == 1 else "items"
        pantry_message("success", f"Deleted {deleted_count} pantry {item_label}.")
    else:
        pantry_message("error", "No matching pantry items were found.")

    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


@pantry_bp.route("/pantry/items/<item_id>/delete", methods=["POST"])
def delete_pantry_item_route(item_id):
    result = delete_pantry_item(item_id)
    pantry_message("success" if result.get("ok") else "error", "Pantry item deleted." if result.get("ok") else "Pantry item was not found.")
    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


@pantry_bp.route("/api/pantry_item_image/generate", methods=["POST"])
def generate_pantry_item_image_route():
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("item_id") or data.get("pantry_item_id") or "").strip()
    result = generate_pantry_item_image(item_id)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@pantry_bp.route("/api/pantry_item_image", methods=["POST"])
def pantry_item_image_upload_route():
    item_id = str(
        request.form.get("item_id")
        or request.form.get("pantry_item_id")
        or ""
    ).strip()
    uploaded_file = (
        request.files.get("image")
        or request.files.get("pantry_image")
        or request.files.get("item_image")
    )
    result = save_pantry_item_image_upload(item_id, uploaded_file)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@pantry_bp.route("/api/pantry_item_name", methods=["POST"])
def pantry_item_name_route():
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("item_id") or data.get("pantry_item_id") or "").strip()
    suggested_name = str(data.get("suggested_name") or data.get("product_name") or "").strip()
    result = apply_pantry_item_name_suggestion(item_id, suggested_name=suggested_name)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@pantry_bp.route("/pantry/move_bought_items", methods=["POST"])
def move_bought_items_to_pantry_route():
    data = request.get_json(silent=True) or {}
    items = data.get("items") if isinstance(data.get("items"), list) else request.form.getlist("items")
    added = []

    for item in items:
        if isinstance(item, dict):
            item_name = str(item.get("name") or item.get("ingredient_name") or "").strip()
            quantity = item.get("quantity") or 1
        else:
            item_name = str(item or "").strip()
            quantity = 1

        if not item_name:
            continue

        result = add_or_increment_pantry_item({
            "ingredient_name": item_name,
            "quantity": quantity,
            "source": "shopping_list",
            "confidence": DEFAULT_CONFIDENCE_BY_SOURCE["shopping_list"],
            "purchased_date": data.get("purchased_date", ""),
        })
        added.append(result["item"].get("ingredient_name") or item_name)

    if not added:
        return jsonify({
            "ok": False,
            "error": "Check at least one shopping list item before moving it to the pantry.",
        }), 400

    message = f"Moved {len(added)} item{'s' if len(added) != 1 else ''} to pantry: {', '.join(added[:6])}"
    if len(added) > 6:
        message += f", and {len(added) - 6} more"

    return jsonify({
        "ok": True,
        "message": message,
        "items": added,
    })


@pantry_bp.route("/pantry/receipt/upload", methods=["POST"])
def upload_receipt_route():
    result = save_receipt_upload(
        request.files.get("receipt_file"),
        request.form.get("receipt_text", ""),
    )
    session["pantry_receipt_review"] = {
        "receipt_id": result["receipt_id"],
        "candidates": result["candidates"],
    }

    if result["candidates"]:
        pantry_message("success", f"Detected {len(result['candidates'])} possible purchase item(s).")
    else:
        pantry_message("error", "Receipt saved, but no purchase items were detected. Paste receipt text for this MVP if the file has no extractable text.")

    return redirect(url_for("main_bp.index", _anchor="aiPantryReceiptReview"))


@pantry_bp.route("/pantry/receipts/<receipt_id>/file")
def view_pantry_receipt_file_route(receipt_id):
    receipt_path = pantry_receipt_upload_file_path(receipt_id)

    if not receipt_path:
        abort(404)

    return send_file(
        receipt_path,
        mimetype=mimetypes.guess_type(receipt_path.name)[0] or "application/octet-stream",
        as_attachment=False,
        download_name=receipt_path.name,
        max_age=0,
    )


@pantry_bp.route("/pantry/receipt/add", methods=["POST"])
def add_receipt_candidates_route():
    review = session.get("pantry_receipt_review") if isinstance(session.get("pantry_receipt_review"), dict) else {}
    review = hydrate_receipt_review_dates(review)
    candidates = review.get("candidates") if isinstance(review.get("candidates"), list) else []
    action = request.form.get("action", "selected")

    if action == "cancel":
        update_receipt_history_status(review.get("receipt_id", ""), "cancelled", 0)
        session.pop("pantry_receipt_review", None)
        pantry_message("success", "Receipt review cancelled.")
        return redirect(url_for("main_bp.index", _anchor="aiPantryUploadReceipt"))

    if action == "all":
        selected_indexes = set(range(len(candidates)))
    else:
        selected_indexes = {
            int(value)
            for value in request.form.getlist("candidate_index")
            if str(value).isdigit()
        }

    added = []
    for index, candidate in enumerate(candidates):
        if index not in selected_indexes:
            continue

        lifecycle_dates = {
            "purchased_date": request.form.get(f"candidate_{index}_purchased_date") or candidate.get("purchased_date", ""),
            "opened_date": request.form.get(f"candidate_{index}_opened_date") or candidate.get("opened_date", ""),
            "expiration_date": request.form.get(f"candidate_{index}_expiration_date") or candidate.get("expiration_date", ""),
            "freeze_by_date": request.form.get(f"candidate_{index}_freeze_by_date") or candidate.get("freeze_by_date", ""),
            "frozen_date": request.form.get(f"candidate_{index}_frozen_date") or candidate.get("frozen_date", ""),
        }
        storage_field = f"candidate_{index}_storage_location"
        if storage_field in request.form:
            storage_location = selected_storage_location(
                request.form.get(storage_field, ""),
                request.form.get(f"{storage_field}_custom", ""),
            )
        else:
            storage_location = receipt_candidate_display_storage_location({**candidate, **lifecycle_dates})
        use_suggested_name = str(request.form.get(f"candidate_{index}_use_suggested_name") or "").lower() in {"1", "true", "yes", "on"}
        name_suggestion = pantry_name_suggestion(
            candidate.get("product_name", ""),
            candidate.get("normalized_name", ""),
        )
        product_name = candidate.get("product_name", "")
        ingredient_name = candidate.get("normalized_name") or product_name
        if use_suggested_name:
            suggested_product_name = (
                request.form.get(f"candidate_{index}_suggested_product_name")
                or name_suggestion.get("suggested_name")
                or ""
            ).strip()
            if suggested_product_name:
                product_name = suggested_product_name
                ingredient_name = suggested_product_name
        receipt_details = [f"Qty {candidate.get('quantity') or 1}"]
        if candidate.get("unit_price_label"):
            receipt_details.append(f"Each {candidate.get('unit_price_label')}")
        if candidate.get("line_total_label"):
            receipt_details.append(f"Total {candidate.get('line_total_label')}")
        if storage_location:
            receipt_details.append(f"Storage {storage_location_label(storage_location)}")
        for label, field in (
            ("Bought", "purchased_date"),
            ("Opened", "opened_date"),
            ("Use by", "expiration_date"),
            ("Freeze by", "freeze_by_date"),
            ("Frozen on", "frozen_date"),
        ):
            if lifecycle_dates.get(field):
                receipt_details.append(f"{label} {lifecycle_dates[field]}")
        if use_suggested_name and product_name != candidate.get("product_name", ""):
            receipt_details.append(f"Name corrected from {candidate.get('product_name', '')} to {product_name}")
        receipt_note = " | ".join(
            part
            for part in [
                candidate.get("raw_line", ""),
                f"Receipt details: {', '.join(receipt_details)}",
            ]
            if part
        )

        result = add_or_increment_pantry_item({
            "ingredient_name": ingredient_name,
            "product_name": product_name,
            "quantity": candidate.get("quantity") or 1,
            "source": "receipt",
            "confidence": candidate.get("confidence", DEFAULT_CONFIDENCE_BY_SOURCE["receipt"]),
            "notes": receipt_note,
            "storage_location": storage_location,
            "source_receipt_id": review.get("receipt_id", ""),
            "source_receipt_line": candidate.get("raw_line", ""),
            **lifecycle_dates,
        })
        added.append(result["item"].get("ingredient_name") or candidate.get("product_name", "Item"))

    update_receipt_history_status(review.get("receipt_id", ""), "added", len(added))
    session.pop("pantry_receipt_review", None)
    pantry_message("success" if added else "error", f"Added {len(added)} receipt item(s) to pantry." if added else "No receipt items were selected.")
    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


@pantry_bp.route("/pantry/add_missing", methods=["POST"])
def add_missing_ingredients_route():
    missing_items = [
        str(item or "").strip()
        for item in request.form.getlist("missing_items")
        if str(item or "").strip()
    ]

    add_items(missing_items)
    pantry_message(
        "success" if missing_items else "error",
        f"Added {len(missing_items)} missing ingredient(s) to the shopping list." if missing_items else "No missing ingredients were selected.",
    )
    return redirect(url_for("main_bp.index", _anchor="sectionView"))


@pantry_bp.route("/pantry/coming-soon")
def pantry_coming_soon_route():
    pantry_message("success", "Coming soon.")
    return redirect(url_for("main_bp.index", _anchor="aiPantrySection"))
