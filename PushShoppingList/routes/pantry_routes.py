from flask import Blueprint
from flask import jsonify
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from PushShoppingList.services.pantry_service import DEFAULT_CONFIDENCE_BY_SOURCE
from PushShoppingList.services.pantry_service import add_or_increment_pantry_item
from PushShoppingList.services.pantry_service import clean_storage_location
from PushShoppingList.services.pantry_service import delete_pantry_item
from PushShoppingList.services.pantry_service import hydrate_receipt_review_dates
from PushShoppingList.services.pantry_service import receipt_candidate_display_storage_location
from PushShoppingList.services.pantry_service import save_receipt_upload
from PushShoppingList.services.pantry_service import storage_location_label
from PushShoppingList.services.pantry_service import update_pantry_item
from PushShoppingList.services.pantry_service import update_pantry_item_lifecycle_action
from PushShoppingList.services.pantry_service import update_receipt_history_status
from PushShoppingList.services.shopping_list_service import add_items


pantry_bp = Blueprint("pantry_bp", __name__)


def pantry_message(category, text):
    session["pantry_messages"] = [{"category": category, "text": text}]


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
        "category": request.form.get("category", ""),
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
            "category": request.form.get("category"),
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
    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


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


@pantry_bp.route("/pantry/items/<item_id>/delete", methods=["POST"])
def delete_pantry_item_route(item_id):
    result = delete_pantry_item(item_id)
    pantry_message("success" if result.get("ok") else "error", "Pantry item deleted." if result.get("ok") else "Pantry item was not found.")
    return redirect(url_for("main_bp.index", _anchor="aiPantryInventory"))


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
        receipt_note = " | ".join(
            part
            for part in [
                candidate.get("raw_line", ""),
                f"Receipt details: {', '.join(receipt_details)}",
            ]
            if part
        )

        result = add_or_increment_pantry_item({
            "ingredient_name": candidate.get("normalized_name") or candidate.get("product_name"),
            "product_name": candidate.get("product_name", ""),
            "quantity": candidate.get("quantity") or 1,
            "source": "receipt",
            "confidence": candidate.get("confidence", DEFAULT_CONFIDENCE_BY_SOURCE["receipt"]),
            "notes": receipt_note,
            "storage_location": storage_location,
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
