import os
from pathlib import Path

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import send_file
from flask import url_for

from PushShoppingList.routes.recipe_routes import commit_menu_import_result
from PushShoppingList.routes.recipe_routes import ensure_menu_recipe_serving_basis_estimate
from PushShoppingList.routes.recipe_routes import menu_recipe_progress_payload
from PushShoppingList.routes.recipe_routes import require_account_for_import
from PushShoppingList.routes.recipe_routes import selected_import_cookbook_from_form
from PushShoppingList.routes.recipe_routes import selected_import_cookbook_from_json
from PushShoppingList.routes.recipe_routes import with_openai_usage_dashboard
from PushShoppingList.services.cookbook_service import load_cookbooks
from PushShoppingList.services.cookbook_service import resolve_cookbook_destination
from PushShoppingList.services.extraction_progress_service import load_progress
from PushShoppingList.services.menu_builder_service import generate_custom_menu
from PushShoppingList.services.menu_import_service import extract_menu_facts_from_upload
from PushShoppingList.services.menu_import_service import extract_menu_facts_from_url
from PushShoppingList.services.menu_pdf_service import export_upload_menu_pdf
from PushShoppingList.services.menu_pdf_service import generate_menu_pdf
from PushShoppingList.services.menu_pdf_service import upload_menu_pdf
from PushShoppingList.services.menu_store_service import delete_menu_pdf_log
from PushShoppingList.services.menu_store_service import get_menu
from PushShoppingList.services.menu_store_service import menu_pdf_logs_for_cookbook
from PushShoppingList.services.menu_store_service import selected_items_as_sections
from PushShoppingList.services.menu_store_service import update_menu_fields
from PushShoppingList.services.menu_store_service import upsert_menu_from_facts
from PushShoppingList.services.recipe_extract_service import build_menu_extract_result_from_items
from PushShoppingList.services.recipe_extract_service import resolve_menu_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
from PushShoppingList.services.user_account_service import current_public_user


menu_bp = Blueprint("menu_bp", __name__)


def static_asset_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except OSError:
        return 1


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
        or request.path.startswith("/api/")
    )


def menu_template_context(**extra):
    return {
        "current_user": current_public_user(),
        "app_css_version": static_asset_version("css/app.css"),
        "menu_builder_css_version": static_asset_version("css/menu_builder.css"),
        "app_js_version": static_asset_version("js/app.js"),
        **extra,
    }


def selected_cookbook_from_menu(menu_detail):
    menu = (menu_detail or {}).get("menu", {})
    cookbook_id = menu.get("cookbook_id", "")
    cookbook_name = menu.get("cookbook_name", "")
    return resolve_cookbook_destination(cookbook_id, cookbook_name, create_missing=bool(cookbook_name))


def first_menu_url_from_form():
    direct = str(request.form.get("menu_url") or "").strip()
    if direct:
        return direct

    recipe_urls = str(request.form.get("recipe_urls") or "").strip()
    for line in recipe_urls.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def render_menu_preview(menu_detail, fact_result=None, validation_message="", status_code=200):
    return render_template(
        "menus/menu_preview.html",
        **menu_template_context(
            menu_detail=menu_detail,
            fact_result=fact_result or {},
            validation_message=validation_message,
        ),
    ), status_code


@menu_bp.route("/menu-import/preview", methods=["POST"])
def menu_import_preview_route():
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response

    cookbook = selected_import_cookbook_from_form(request.form)
    uploaded_file = request.files.get("menu_media") or request.files.get("recipe_media")
    menu_url = first_menu_url_from_form()

    try:
        if uploaded_file and uploaded_file.filename:
            fact_result = extract_menu_facts_from_upload(uploaded_file)
        elif menu_url:
            fact_result = extract_menu_facts_from_url(menu_url)
        else:
            fact_result = {
                "ok": False,
                "success": False,
                "error": "Choose a menu URL or upload a menu file.",
            }
    except Exception as exc:
        fact_result = {
            "ok": False,
            "success": False,
            "error": str(exc) or "Unable to extract menu facts.",
        }

    if not fact_result.get("ok"):
        if wants_json_response():
            return jsonify(with_openai_usage_dashboard(fact_result)), 400
        return render_template(
            "menus/menu_preview.html",
            **menu_template_context(
                menu_detail={},
                fact_result=fact_result,
                validation_message=fact_result.get("error", "Unable to extract menu facts."),
            ),
        ), 400

    menu_detail = upsert_menu_from_facts(
        {
            **fact_result,
            "source_type": "imported_menu",
            "menu_source_type": "imported_menu",
        },
        cookbook_id=(cookbook or {}).get("id", ""),
        cookbook_name=(cookbook or {}).get("name", ""),
    )

    if wants_json_response():
        return jsonify(with_openai_usage_dashboard({
            "ok": True,
            "success": True,
            "menu_id": menu_detail.get("menu", {}).get("id", ""),
            "preview_url": url_for("menu_bp.menu_import_preview_get_route", menu_id=menu_detail.get("menu", {}).get("id", "")),
            "menu": menu_detail,
            "fact_result": fact_result,
        }))

    return render_menu_preview(menu_detail, fact_result=fact_result)


@menu_bp.route("/menu-import/preview/<menu_id>", methods=["GET"])
def menu_import_preview_get_route(menu_id):
    account_response = require_account_for_import(wants_json=False)
    if account_response:
        return account_response

    menu_detail = get_menu(menu_id)
    if not menu_detail:
        abort(404)

    return render_menu_preview(menu_detail)


@menu_bp.route("/menu-import/generate", methods=["POST"])
def menu_import_generate_route():
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response

    data = request.get_json(silent=True) if request.is_json else None
    data = data if isinstance(data, dict) else {}
    menu_id = str(data.get("menu_id") or request.form.get("menu_id") or "").strip()
    item_ids = data.get("menu_item_ids") if isinstance(data.get("menu_item_ids"), list) else request.form.getlist("menu_item_ids")
    item_ids = [str(item_id).strip() for item_id in item_ids if str(item_id).strip()]
    menu_detail = get_menu(menu_id)

    if not menu_detail:
        return jsonify({"ok": False, "error": "Menu was not found."}), 404

    if not item_ids:
        if wants_json_response():
            return jsonify({"ok": False, "error": "Select at least one menu item."}), 400
        return render_menu_preview(
            menu_detail,
            validation_message="Select at least one menu item.",
            status_code=400,
        )

    sections = selected_items_as_sections(menu_id, item_ids)
    if not sections:
        if wants_json_response():
            return jsonify({"ok": False, "error": "Selected menu items were not found."}), 400
        return render_menu_preview(
            menu_detail,
            validation_message="Selected menu items were not found.",
            status_code=400,
        )

    menu = menu_detail.get("menu", {})
    source_url = menu.get("source_url") or menu.get("source_uploaded_file_path") or f"menu://{menu_id}"
    result = build_menu_extract_result_from_items(
        source_url,
        sections,
        source_name=menu.get("menu_title", ""),
        source_type=menu.get("source_type", "imported_menu"),
        extracted_text="",
        diagnostics={
            "staged_menu_import": True,
            "restaurant_id": menu.get("restaurant_id", ""),
            "menu_id": menu_id,
            "selected_menu_item_count": len(item_ids),
        },
    )

    cookbook = selected_cookbook_from_menu(menu_detail)
    committed = commit_menu_import_result(
        result,
        cookbook,
        context="staged-menu-import",
    )
    progress_items = [
        menu_recipe_progress_payload(recipe_result)
        for recipe_result in result.get("recipes", [])
        if isinstance(recipe_result, dict)
    ]

    if wants_json_response():
        return jsonify(with_openai_usage_dashboard({
            **committed,
            "menu_id": menu_id,
            "progress_items": progress_items,
        })), 200 if committed.get("ok") else 400

    return render_template(
        "menus/menu_recipe_progress.html",
        **menu_template_context(
            menu_detail=get_menu(menu_id),
            generation_result=committed,
            progress_items=progress_items,
            selected_count=len(item_ids),
            model_used=result.get("model_used") or resolve_menu_model(),
            model_source=result.get("model_source") or resolve_menu_model_source(),
        ),
    ), 200 if committed.get("ok") else 400


@menu_bp.route("/menu-import/status/<job_id>", methods=["GET"])
def menu_import_status_route(job_id):
    progress = load_progress()
    return jsonify({
        "ok": bool(progress),
        "job_id": job_id,
        "progress": progress,
    })


@menu_bp.route("/menu-import/recipe/<recipe_id>/estimate", methods=["POST"])
def menu_import_recipe_estimate_route(recipe_id):
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(silent=True) or {}
    recipe_url = str(data.get("recipe_url") or data.get("url") or request.form.get("recipe_url") or "").strip()
    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required.", "recipe_id": recipe_id}), 400

    result = ensure_menu_recipe_serving_basis_estimate(recipe_url, {})
    status = 200 if result.get("ok") else 400
    return jsonify(with_openai_usage_dashboard(result)), status


@menu_bp.route("/menus/custom-builder", methods=["GET", "POST"])
def custom_menu_builder_route():
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response

    if request.method == "GET":
        return render_template(
            "menus/menu_builder.html",
            **menu_template_context(error="", form_values={}, cookbooks=load_cookbooks().get("cookbooks", [])),
        )

    cookbook = selected_import_cookbook_from_form(request.form)
    options = {
        "restaurant_name": request.form.get("restaurant_name", ""),
        "cuisine_type": request.form.get("cuisine_type", ""),
        "theme": request.form.get("theme", ""),
        "price_level": request.form.get("price_level", "casual"),
        "section_count": request.form.get("section_count", "4"),
        "items_per_section": request.form.get("items_per_section", "6"),
        "include_descriptions": request.form.get("include_descriptions") == "1",
        "include_prices": request.form.get("include_prices") == "1",
        "include_dietary_tags": request.form.get("include_dietary_tags") == "1",
        "include_spicy_indicators": request.form.get("include_spicy_indicators") == "1",
        "notes": request.form.get("notes", ""),
    }

    try:
        result = generate_custom_menu(
            options,
            cookbook_id=(cookbook or {}).get("id", ""),
            cookbook_name=(cookbook or {}).get("name", ""),
        )
    except Exception as exc:
        if wants_json_response():
            return jsonify({"ok": False, "success": False, "error": str(exc)}), 400
        return render_template(
            "menus/menu_builder.html",
            **menu_template_context(error=str(exc), form_values=options, cookbooks=load_cookbooks().get("cookbooks", [])),
        ), 400

    if wants_json_response():
        return jsonify(with_openai_usage_dashboard(result))

    return redirect(url_for("menu_bp.menu_view_route", menu_id=result.get("menu_id", "")))


@menu_bp.route("/menus/<menu_id>", methods=["GET"])
def menu_view_route(menu_id):
    account_response = require_account_for_import(wants_json=False)
    if account_response:
        return account_response

    menu_detail = get_menu(menu_id)
    if not menu_detail:
        abort(404)

    return render_template(
        "menus/menu_view.html",
        **menu_template_context(menu_detail=menu_detail),
    )


@menu_bp.route("/menus/<menu_id>/edit", methods=["GET", "POST"])
def menu_edit_route(menu_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response

    menu_detail = get_menu(menu_id)
    if not menu_detail:
        abort(404)

    if request.method == "GET":
        return render_template(
            "menus/menu_edit.html",
            **menu_template_context(menu_detail=menu_detail, error=""),
        )

    updated = update_menu_fields(
        menu_id,
        {
            "menu_title": request.form.get("menu_title", ""),
            "menu_subtitle": request.form.get("menu_subtitle", ""),
            "menu_description": request.form.get("menu_description", ""),
            "menu_theme": request.form.get("menu_theme", ""),
            "menu_style": request.form.get("menu_style", ""),
            "is_public": request.form.get("is_public") == "1",
        },
        {
            "restaurant_name": request.form.get("restaurant_name", ""),
            "restaurant_website_url": request.form.get("restaurant_website_url", ""),
            "phone": request.form.get("phone", ""),
            "full_address": request.form.get("full_address", ""),
            "hours_text": request.form.get("hours_text", ""),
            "current_status": request.form.get("current_status", ""),
            "rewards_text": request.form.get("rewards_text", ""),
        },
    )

    if wants_json_response():
        return jsonify({"ok": True, "success": True, "menu": updated})

    return redirect(url_for("menu_bp.menu_view_route", menu_id=menu_id))


def menu_pdf_route_response(result, menu_id):
    if wants_json_response():
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    if result.get("ok"):
        flash("Menu PDF updated.", "success")
    else:
        flash(result.get("error") or "Unable to update menu PDF.", "error")
    return redirect(url_for("menu_bp.menu_view_route", menu_id=menu_id))


@menu_bp.route("/menus/<menu_id>/export-pdf", methods=["POST"])
def export_menu_pdf_route(menu_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response
    return menu_pdf_route_response(generate_menu_pdf(menu_id), menu_id)


@menu_bp.route("/menus/<menu_id>/upload-pdf", methods=["POST"])
def upload_menu_pdf_route(menu_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response
    return menu_pdf_route_response(upload_menu_pdf(menu_id, log_id=request.form.get("pdf_log_id", "")), menu_id)


@menu_bp.route("/menus/<menu_id>/export-upload-pdf", methods=["POST"])
def export_upload_menu_pdf_route(menu_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response
    return menu_pdf_route_response(export_upload_menu_pdf(menu_id), menu_id)


@menu_bp.route("/menus/<menu_id>/pdf/<log_id>", methods=["GET"])
def view_menu_pdf_route(menu_id, log_id):
    account_response = require_account_for_import(wants_json=False)
    if account_response:
        return account_response

    menu_detail = get_menu(menu_id)
    log = next((row for row in menu_detail.get("pdf_logs", []) if row.get("id") == log_id), None)
    if not log:
        abort(404)
    pdf_path = Path(str(log.get("local_pdf_path") or ""))
    if not pdf_path.exists():
        abort(404)
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=pdf_path.name,
        max_age=0,
    )


@menu_bp.route("/menus/<menu_id>/pdf-log/<log_id>/delete", methods=["POST"])
def delete_menu_pdf_log_route(menu_id, log_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response

    deleted = delete_menu_pdf_log(log_id)
    if wants_json_response():
        return jsonify({"ok": deleted, "success": deleted})
    return redirect(url_for("menu_bp.menu_view_route", menu_id=menu_id))


@menu_bp.route("/menus/<menu_id>/pdf-log/<log_id>/regenerate", methods=["POST"])
def regenerate_menu_pdf_log_route(menu_id, log_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response
    return menu_pdf_route_response(generate_menu_pdf(menu_id), menu_id)


@menu_bp.route("/menus/<menu_id>/pdf-log/<log_id>/reupload", methods=["POST"])
def reupload_menu_pdf_log_route(menu_id, log_id):
    account_response = require_account_for_import(wants_json=wants_json_response())
    if account_response:
        return account_response
    return menu_pdf_route_response(upload_menu_pdf(menu_id, log_id=log_id), menu_id)


@menu_bp.route("/cookbooks/<cookbook_id>/menu-pdf-log", methods=["GET"])
def cookbook_menu_pdf_log_route(cookbook_id):
    account_response = require_account_for_import(wants_json=False)
    if account_response:
        return account_response
    return render_template(
        "menus/cookbook_menu_pdf_log.html",
        **menu_template_context(
            cookbook_id=cookbook_id,
            menu_pdf_logs=menu_pdf_logs_for_cookbook(cookbook_id),
        ),
    )
