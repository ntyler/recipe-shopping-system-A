import json
import os
import threading
from pathlib import Path
from time import perf_counter

from flask import Blueprint
from flask import abort
from flask import copy_current_request_context
from flask import flash
from flask import has_request_context
from flask import Response
from flask import jsonify
from flask import redirect
from flask import request
from flask import send_file

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services.extraction_progress_service import batch_has_success
from PushShoppingList.services.extraction_progress_service import batch_is_finished
from PushShoppingList.services.extraction_progress_service import finish_progress
from PushShoppingList.services.extraction_progress_service import is_cancel_requested
from PushShoppingList.services.extraction_progress_service import is_current_job
from PushShoppingList.services.extraction_progress_service import load_progress
from PushShoppingList.services.extraction_progress_service import mark_url_done
from PushShoppingList.services.extraction_progress_service import mark_url_failed
from PushShoppingList.services.extraction_progress_service import mark_url_message
from PushShoppingList.services.extraction_progress_service import mark_url_running
from PushShoppingList.services.extraction_progress_service import new_job_id
from PushShoppingList.services.extraction_progress_service import request_cancel
from PushShoppingList.services.extraction_progress_service import start_progress
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.recipe_extract_service import generateRecipeFromImage
from PushShoppingList.services.recipe_extract_service import build_vision_debug
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OPENAI_PING_TEXT_MODEL
from PushShoppingList.services.recipe_extract_service import resolve_vision_model
from PushShoppingList.services.recipe_extract_service import classify_vision_ai_exception
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import build_extract_result
from PushShoppingList.services.recipe_extract_service import log_vision_debug_step
from PushShoppingList.services.recipe_extract_service import send_image_prompt_to_openai
from PushShoppingList.services.recipe_extract_service import supports_custom_temperature
from PushShoppingList.services.recipe_extract_service import normalize_upload_mime_type
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_recipe_identity
from PushShoppingList.services.recipe_extract_service import NO_UPLOAD_INGREDIENTS_ERROR
from PushShoppingList.services.recipe_extract_service import UPLOAD_FOLDER
from PushShoppingList.services.recipe_extract_service import build_upload_failure_result
from PushShoppingList.services.recipe_extract_service import set_vision_debug_error
from PushShoppingList.services.recipe_extract_service import save_extracted_recipe_json
from PushShoppingList.services.recipe_extract_service import VISION_SUPPORTED_IMAGE_MIME_TYPES
from PushShoppingList.services.recipe_extract_service import VISION_SUPPORTED_IMAGE_SUFFIXES
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import recipe_cover_image_file_path
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import recipe_pdf_path
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import ingredient_sections_from_recipe_data
from PushShoppingList.services.cookbook_service import COOKBOOK_CATEGORY_ALL_FIELDS
from PushShoppingList.services.cookbook_service import CATEGORY_SOURCE_AI_INFERRED
from PushShoppingList.services.cookbook_service import move_recipes_to_cookbook
from PushShoppingList.services.cookbook_service import purge_recipe_from_all_cookbooks
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.cookbook_service import resolve_cookbook_destination
from PushShoppingList.services.cookbook_service import update_cookbook_recipe_categories
from PushShoppingList.services.food_review_alternative_service import suggest_food_review_alternatives
from PushShoppingList.services.recipe_edit_service import create_new_recipe
from PushShoppingList.services.recipe_edit_service import create_editable_recipe_pdf
from PushShoppingList.services.recipe_edit_service import delete_editable_recipe_pdf
from PushShoppingList.services.recipe_edit_service import decide_recipe_categories_with_chatgpt
from PushShoppingList.services.recipe_edit_service import estimate_recipe_nutrition
from PushShoppingList.services.recipe_edit_service import generate_recipe_equipment_image
from PushShoppingList.services.recipe_edit_service import generate_recipe_step_image
from PushShoppingList.services.recipe_edit_service import load_editable_recipe
from PushShoppingList.services.recipe_edit_service import log_recipe_pdf_timing
from PushShoppingList.services.recipe_edit_service import recipe_note_feedback
from PushShoppingList.services.recipe_edit_service import save_editable_recipe
from PushShoppingList.services.recipe_edit_service import save_recipe_cover_image_upload
from PushShoppingList.services.recipe_edit_service import save_recipe_detail_image_upload
from PushShoppingList.services.recipe_edit_service import create_source_url_pdf
from PushShoppingList.services.recipe_edit_service import ensure_recipe_pdf_cloudflare_link
from PushShoppingList.services.recipe_edit_service import normalize_pdf_kind
from PushShoppingList.services.recipe_edit_service import upload_recipe_pdf_to_cloudflare
from PushShoppingList.services.recipe_edit_service import upload_all_recipe_pdfs_to_cloudflare
from PushShoppingList.services.recipe_image_progress_service import load_recipe_image_progress
from PushShoppingList.services.recipe_ingredient_service import remove_recipe_and_unused_ingredients
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipe
from PushShoppingList.services.recipe_url_service import add_recipe_urls
from PushShoppingList.services.recipe_url_service import load_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import remove_recipe_url
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_quantity_service import update_recipe_ingredient_quantity
from PushShoppingList.services.recipe_quantity_service import update_recipe_quantity
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.openai_usage_service import openai_usage_dashboard_for_user
from PushShoppingList.services.openai_usage_service import record_app_activity
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import is_admin_user

recipe_bp = Blueprint("recipe_bp", __name__)

NO_INGREDIENTS_ERROR = "No ingredients were found for this recipe URL."
IMPORT_LOGIN_ERROR = "Sign in before importing recipes so imported data is saved to your account."
FOOD_REVIEW_LOGIN_ERROR = "Sign in before using food reviews so results stay tied to your account."
IMPORT_CATEGORY_STATUS_MESSAGE = "Import complete. Generating ChatGPT categories..."
IMAGE_RECIPE_WORKFLOW_STATES = {}


def _uploaded_recipe_workflow_key(url):
    return str(url or "").strip()


def _is_uploaded_recipe_url(url):
    return str(url or "").startswith("uploaded://")


def _extract_nutrition_text_value(value):
    if value is None:
        return ""

    return str(value).strip()


def _has_per_serving_estimate(nutrition):
    if isinstance(nutrition, dict):
        serving_basis = _extract_nutrition_text_value(nutrition.get("serving_basis"))
        calories = _extract_nutrition_text_value(nutrition.get("calories"))
        return bool(serving_basis and calories)

    if isinstance(nutrition, list):
        serving_basis = ""
        calories = ""

        for item in nutrition:
            if not isinstance(item, dict):
                continue

            key = str(item.get("key") or "").strip().lower()
            value = _extract_nutrition_text_value(item.get("value"))

            if key == "serving_basis":
                serving_basis = value
            elif key == "calories":
                calories = value

        return bool(serving_basis and calories)

    return False


def _is_uploaded_recipe_nutrition_complete(url):
    if not _is_uploaded_recipe_url(url):
        return True

    key = _uploaded_recipe_workflow_key(url)
    state = IMAGE_RECIPE_WORKFLOW_STATES.get(key, {})
    if state.get("estimate_per_serving_completed"):
        return True

    try:
        recipe_data = load_editable_recipe(url) if key else {}
    except Exception:
        recipe_data = {}

    recipe_payload = recipe_data.get("recipe") if isinstance(recipe_data, dict) else {}
    if _has_per_serving_estimate(recipe_payload.get("nutrition")):
        IMAGE_RECIPE_WORKFLOW_STATES[key] = {
            **state,
            "estimate_per_serving_completed": True,
            "last_checked_at": perf_counter(),
        }
        return True

    return False


def _should_auto_generate_recipe_pdf(url, extraction_source=""):
    extraction_source = str(extraction_source or "").strip().lower()

    if not _is_uploaded_recipe_url(url):
        return True

    return extraction_source not in {"image_estimate", "manual_description", "vision"}


def _mark_uploaded_recipe_nutrition_estimated(url, estimated):
    key = _uploaded_recipe_workflow_key(url)
    if not key:
        return

    state = IMAGE_RECIPE_WORKFLOW_STATES.get(key, {})
    state["estimate_per_serving_completed"] = bool(estimated)
    state["updated_at"] = perf_counter()
    IMAGE_RECIPE_WORKFLOW_STATES[key] = state


def _extract_recipe_payload_for_nutrition(data):
    if not isinstance(data, dict):
        return {}

    recipe = data.get("recipe")
    if isinstance(recipe, dict):
        return recipe

    recipe_json = data.get("recipe_json")
    if isinstance(recipe_json, dict):
        return recipe_json

    return {}


def create_recipe_pdf_from_url(recipe_url):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "ok": False,
            "error": "Recipe URL is required.",
        }

    if not _is_uploaded_recipe_nutrition_complete(recipe_url):
        return {
            "ok": False,
            "error": "Estimate per serving basis is required before creating the recipe PDF.",
            "success": False,
        }

    return create_editable_recipe_pdf(recipe_url)


def run_generated_recipe_pdf_creation(recipe_url, context="import"):
    recipe_url = str(recipe_url or "").strip()
    context = str(context or "import").strip() or "import"

    if not recipe_url:
        return {
            "ok": False,
            "error": "Recipe URL is required.",
        }

    print(f"[recipe_pdf] action=auto_generated_start context={context} url={recipe_url}")

    result = create_recipe_pdf_from_url(recipe_url)

    public_url = str(
        result.get("generated_cloudflare_pdf_url")
        or result.get("generated_recipe_pdf_url")
        or result.get("pdf_public_url")
        or result.get("public_url")
        or ""
    ).strip()
    pdf_path = str(
        result.get("generated_pdf_path")
        or result.get("generated_recipe_pdf_path")
        or result.get("pdf_path")
        or ""
    ).strip()

    if result.get("ok") and public_url:
        print(
            "[recipe_pdf] "
            f"action=auto_generated_done context={context} url={recipe_url} "
            f"generated_pdf_path={pdf_path} generated_cloudflare_pdf_url={public_url}"
        )
    elif result.get("ok"):
        print(
            "[recipe_pdf] "
            f"action=auto_generated_local_only context={context} url={recipe_url} "
            f"generated_pdf_path={pdf_path} error={result.get('error') or ''}"
        )
    else:
        print(
            "[recipe_pdf] "
            f"action=auto_generated_failed context={context} url={recipe_url} "
            f"error={result.get('error') or 'Unable to create generated recipe PDF.'}"
        )

    return result


def schedule_generated_recipe_pdf_creation(recipe_url, context="import"):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "queued": False,
            "error": "Recipe URL is required.",
        }

    def worker():
        run_generated_recipe_pdf_creation(recipe_url, context=context)

    target = copy_current_request_context(worker) if has_request_context() else worker
    thread = threading.Thread(
        target=target,
        name=f"recipe-generated-pdf-{len(recipe_url)}",
        daemon=True,
    )
    thread.start()

    return {
        "queued": True,
        "url": recipe_url,
    }


def require_account_for_import(wants_json=False):
    """Keep recipe imports bound to a signed-in user's scoped storage."""
    if current_user():
        return None

    if wants_json:
        return jsonify({"ok": False, "error": IMPORT_LOGIN_ERROR}), 401

    flash(IMPORT_LOGIN_ERROR, "error")
    return redirect("/#userAccountSection")


def require_account_for_food_review():
    """Food-review alternatives use account-specific food rules and saved recipe data."""
    if current_user():
        return None

    return jsonify({"ok": False, "error": FOOD_REVIEW_LOGIN_ERROR}), 401


def ensure_recipe_has_default_cookbook(url, recipe_metadata=None):
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    recipe_title = str(
        recipe_metadata.get("display_name")
        or recipe_metadata.get("recipe_title")
        or recipe_metadata.get("name")
        or ""
    ).strip()

    ensure_unclassified_cookbook_for_recipes([{
        "url": url,
        "name": recipe_title or url,
        "source_href": url,
        "source_display_url": url,
        "quantity": 1,
        "archive_pdf_available": bool(recipe_metadata.get("archive_pdf_available")),
        "servings": recipe_metadata.get("servings", ""),
        "level": recipe_metadata.get("level", ""),
        "total_time": recipe_metadata.get("total_time", ""),
        "prep_time": recipe_metadata.get("prep_time", ""),
        "inactive_time": recipe_metadata.get("inactive_time", ""),
        "cook_time": recipe_metadata.get("cook_time", ""),
        "base_servings": recipe_metadata.get("servings", ""),
        "cover_image": recipe_metadata.get("cover_image") or {},
    }])


def import_recipe_title(recipe_metadata, fallback_url=""):
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    return str(
        recipe_metadata.get("display_name")
        or recipe_metadata.get("recipe_title")
        or recipe_metadata.get("name")
        or fallback_url
        or ""
    ).strip()


def import_text_items(values, field_names):
    if not isinstance(values, list):
        return []

    items = []

    for value in values:
        if isinstance(value, dict):
            text = ""
            for field_name in field_names:
                text = str(value.get(field_name) or "").strip()
                if text:
                    break
        else:
            text = str(value or "").strip()

        if text:
            items.append(text)

    return items


def import_recipe_record(url, recipe_metadata=None):
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    title = import_recipe_title(recipe_metadata, url)

    return {
        "url": url,
        "name": title or url,
        "source_href": url,
        "source_display_url": url,
        "quantity": 1,
        "description": recipe_metadata.get("description") or recipe_metadata.get("summary") or "",
        "servings": recipe_metadata.get("servings", ""),
        "level": recipe_metadata.get("level", ""),
        "prep_time": recipe_metadata.get("prep_time", ""),
        "inactive_time": recipe_metadata.get("inactive_time", ""),
        "cook_time": recipe_metadata.get("cook_time", ""),
        "total_time": recipe_metadata.get("total_time", ""),
        "rating": recipe_metadata.get("rating", 0),
        "archive_pdf_available": bool(recipe_metadata.get("archive_pdf_available")),
        "base_servings": recipe_metadata.get("servings", ""),
        "equipment_items": import_text_items(
            recipe_metadata.get("equipment", []),
            ("name", "display_name", "equipment", "item"),
        ),
        "instruction_items": import_text_items(
            recipe_metadata.get("instructions", []),
            ("text", "instruction", "step", "description"),
        ),
        "sections": ingredient_sections_from_recipe_data(recipe_metadata.get("ingredients", [])),
        "cover_image": recipe_metadata.get("cover_image") or {},
    }


def selected_import_cookbook(cookbook_id="", cookbook_name=""):
    cookbook_id = str(cookbook_id or "").strip()
    cookbook_name = str(cookbook_name or "").strip()

    if not cookbook_id and not cookbook_name:
        return None

    cookbook = resolve_cookbook_destination(
        cookbook_id,
        cookbook_name,
        create_missing=bool(cookbook_name),
    )

    if cookbook is None:
        print(
            "[recipe_import] "
            f"action=selected_cookbook_not_found cookbook_id={cookbook_id} cookbook_name={cookbook_name}"
        )

    return cookbook


def selected_import_cookbook_from_form(form):
    return selected_import_cookbook(
        form.get("cookbook_id", ""),
        form.get("cookbook_name", ""),
    )


def selected_import_cookbook_from_json(data):
    data = data if isinstance(data, dict) else {}
    return selected_import_cookbook(
        data.get("cookbook_id", ""),
        data.get("cookbook_name", ""),
    )


def log_selected_import_cookbook(source, cookbook):
    cookbook = cookbook if isinstance(cookbook, dict) else {}
    print(
        "[recipe_import] "
        f"action=selected_cookbook source={source} "
        f"cookbook_id={cookbook.get('id', '')} cookbook_name={cookbook.get('name', '') or 'default'}"
    )


def save_import_cookbook_assignment(url, recipe_metadata=None, cookbook=None):
    if cookbook and cookbook.get("id"):
        move_recipes_to_cookbook(
            cookbook.get("id", ""),
            [url],
            [import_recipe_record(url, recipe_metadata)],
            overwrite_existing=True,
        )
    else:
        ensure_recipe_has_default_cookbook(url, recipe_metadata)

    assignment = recipe_cookbook_assignments().get(normalize_recipe_url_key(url), {})
    assigned_name = assignment.get("cookbook_name") or (cookbook or {}).get("name", "") or "unclassified"
    print(
        "[recipe_import] "
        f"action=recipe_created title={import_recipe_title(recipe_metadata, url)} "
        f"assigned_cookbook={assigned_name} url={url}"
    )
    return assignment


def record_recipe_import_activity(url, result, source):
    result = result if isinstance(result, dict) else {}
    record_app_activity(
        "recipe-import",
        metadata={
            "source": source,
            "recipeUrl": url,
            "recipeTitle": result.get("display_name") or result.get("recipe_title") or result.get("name") or "",
            "ingredientCount": len(result.get("ingredients", [])),
        },
    )


def apply_imported_recipe_category_routine(url, recipe_metadata, assignment):
    url = str(url or "").strip()
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    assignment = assignment if isinstance(assignment, dict) else {}
    title = import_recipe_title(recipe_metadata, url)

    if not url:
        print("[recipe_import_category] action=skipped reason=no_recipe_url")
        return {"ok": False, "error": "Recipe URL is required."}

    cookbook_id = str(assignment.get("cookbook_id", "")).strip()
    if not cookbook_id:
        print(
            "[recipe_import_category] action=skipped "
            f"title={title} url={url} reason=missing_cookbook_assignment"
        )
        return {"ok": False, "error": "Recipe cookbook assignment is required."}

    category_input = {
        **recipe_metadata,
    }
    category_input.setdefault("source_url", url)
    category_input.setdefault("source_display_url", url)
    category_input.setdefault("url", url)

    print(
        "[recipe_import_category] action=started "
        f"title={title} url={url} cookbook_id={cookbook_id}"
    )

    decision = decide_recipe_categories_with_chatgpt(
        category_input,
        mode="all",
        current_categories={},
        trigger_source="recipe_import:all",
    )

    if not decision.get("ok"):
        error = str(decision.get("error") or "Unable to infer categories.")
        print(
            "[recipe_import_category] action=failed "
            f"title={title} url={url} error={error}"
        )
        return {"ok": False, "error": error, "title": title}

    categories = decision.get("categories") or {}
    if not isinstance(categories, dict):
        print(
            "[recipe_import_category] action=failed "
            f"title={title} url={url} error=invalid_category_payload"
        )
        return {"ok": False, "error": "Invalid category payload.", "title": title}

    category_sources = {}
    for field in COOKBOOK_CATEGORY_ALL_FIELDS:
        if (
            field == "custom_categories"
            and isinstance(categories.get(field), list)
            and categories.get(field)
        ) or str(categories.get(field) or "").strip():
            category_sources[field] = CATEGORY_SOURCE_AI_INFERRED

    try:
        update_cookbook_recipe_categories(
            cookbook_id,
            url,
            categories,
            category_sources=category_sources,
        )
        print(
            "[recipe_import_category] action=success "
            f"title={title} url={url} "
            f"categories={json.dumps(categories, ensure_ascii=False)}"
        )
        return {
            "ok": True,
            "title": title,
            "categories": categories,
            "status": "updated",
        }
    except Exception as exc:
        error = str(exc)
        print(
            "[recipe_import_category] action=failed "
            f"title={title} url={url} error={error}"
        )
        return {"ok": False, "error": error, "title": title}


def with_openai_usage_dashboard(result):
    if not isinstance(result, dict):
        return result

    return {
        **result,
        "openai_usage_dashboard": openai_usage_dashboard_for_user(current_user()),
    }


@recipe_bp.route("/extract_recipe", methods=["POST"])
def extract_recipe_route():
    account_response = require_account_for_import()
    if account_response:
        return account_response

    recipe_urls = request.form.get("recipe_urls", "")

    urls = [
        line.strip()
        for line in recipe_urls.splitlines()
        if line.strip()
    ]

    job_id = new_job_id()
    start_progress(urls, job_id=job_id)
    cookbook = selected_import_cookbook_from_form(request.form)
    log_selected_import_cookbook("form-url", cookbook)

    extracted_any = False

    for index, url in enumerate(urls):
        if is_cancel_requested(job_id):
            break

        mark_url_running(job_id, urls, index)
        try:
            result = extract_recipe_from_url(
                url,
                progress_callback=lambda message, summary=None, idx=index: mark_url_message(
                    job_id,
                    urls,
                    idx,
                    message,
                    summary,
                ),
            )
        except Exception as exc:
            mark_url_failed(job_id, urls, index, str(exc))
            continue

        if is_cancel_requested(job_id):
            break

        try:
            ingredients = result.get("ingredients", [])

            if result.get("ok") and ingredients:
                add_items(ingredients)
                save_ingredients_for_recipe(url, ingredients, result)
                if result.get("display_name") or result.get("recipe_title"):
                    save_recipe_url_name(url, result.get("display_name") or result.get("recipe_title"))
                add_recipe_urls([url])
                assignment = save_import_cookbook_assignment(url, result, cookbook)
                print(f"[recipe_import] action=created title={import_recipe_title(result, url)} url={url}")
                print(f"[recipe_import] action=categories_start title={import_recipe_title(result, url)}")
                mark_url_message(
                    job_id,
                    urls,
                    index,
                    IMPORT_CATEGORY_STATUS_MESSAGE,
                    summary="Generating categories with ChatGPT.",
                )
                apply_imported_recipe_category_routine(url, result, assignment)
                create_source_url_pdf(url)
                schedule_generated_recipe_pdf_creation(url, context="form-url")
                record_recipe_import_activity(url, result, "form-url")
                extracted_any = True
                mark_url_done(job_id, urls, index, len(ingredients))
            else:
                mark_url_failed(job_id, urls, index, result.get("error") or NO_INGREDIENTS_ERROR)
        except Exception as exc:
            mark_url_failed(job_id, urls, index, str(exc))

    if extracted_any:
        sort_ingredients()

    finish_progress(job_id, ok=extracted_any)

    return redirect("/")


@recipe_bp.route("/upload_recipe_media", methods=["POST"])
def upload_recipe_media_route():
    wants_json = (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )
    account_response = require_account_for_import(wants_json=wants_json)
    if account_response:
        return account_response

    uploaded_file = request.files.get("recipe_media")

    if not uploaded_file or not uploaded_file.filename:
        if wants_json:
            return jsonify({"ok": False, "error": "No file was selected."}), 400

        return redirect("/")

    cookbook = selected_import_cookbook_from_form(request.form)
    log_selected_import_cookbook("media-upload", cookbook)

    manual_description = str(
        request.form.get("photo_description")
        or request.form.get("recipe_description")
        or ""
    ).strip()
    upload_mode = str(request.form.get("upload_mode") or "").strip().lower()

    result = extract_recipe_from_upload(
        uploaded_file,
        manual_description=manual_description,
        upload_mode=upload_mode,
    )
    extraction_source = str(
        result.get("extraction_mode")
        or result.get("extraction_method")
        or result.get("source_type")
        or "upload"
    ).strip()
    extraction_confidence = result.get("extraction_confidence")
    extraction_error = str(result.get("error") or "").strip()
    path_label = {
        "image": "uploaded image",
        "pdf": "uploaded PDF/document",
        "document": "uploaded PDF/document",
        "text": "uploaded text",
        "document_text": "text recipe import",
        "ocr_text": "text recipe import",
        "image_estimate": "estimated from food photo",
        "manual_description": "estimated from photo/description",
        "not_recipe_image": "not recipe/food",
    }.get(extraction_source, "not recipe/food")

    print(
        f"[recipe_import] action=media_upload_path path={path_label} "
        f"title={import_recipe_title(result, result.get('source_url') or '')} "
        f"confidence={extraction_confidence}"
        f"{f' error={extraction_error}' if extraction_error else ''}"
    )

    result = commit_media_import_result(
        result,
        cookbook,
        recipe_url=str(result.get("source_url") or ""),
        context="media-upload",
    )
    if isinstance(result, dict):
        result.setdefault("success", bool(result.get("ok")))
        result.setdefault(
            "model_used",
            resolve_vision_model() if str(result.get("source_type") or "").lower() == "image" else MODEL,
        )
        if "debug" not in result:
            result["debug"] = {
                "model": resolve_vision_model() if str(result.get("source_type") or "").lower() == "image" else MODEL,
            }

    if wants_json:
        extraction_mode_label = (
            {
                "ocr_text": "OCR",
                "image_estimate": "Vision",
                "vision": "Vision",
                "manual_description": "Manual",
            }.get(extraction_source, "Unknown")
            if extraction_source
            else "Unknown"
        )
        if extraction_mode_label and extraction_mode_label != "Unknown":
            result["extraction_mode_label"] = extraction_mode_label

        if extraction_source in {"manual_description", "image_estimate", "vision"}:
            result["estimation_banner"] = (
                "Recipe estimated from uploaded image. Review ingredients before saving."
                if extraction_source == "image_estimate"
                else "Recipe estimated from photo/description. Review before saving."
            )
        if extraction_source:
            result["extraction_mode"] = extraction_source

        result["recipe_json"] = result.get("raw")

        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    return redirect("/")


def commit_media_import_result(result, cookbook, recipe_url="", context="media-upload"):
    result = result if isinstance(result, dict) else {}
    ingredients = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
    recipe_url = str(recipe_url or result.get("source_url") or "").strip()
    if recipe_url:
        result["source_url"] = recipe_url

    if result.get("ok") and ingredients:
        add_items(ingredients)
        save_ingredients_for_recipe(recipe_url, ingredients, result)
        if result.get("display_name") or result.get("recipe_title"):
            save_recipe_url_name(recipe_url, result.get("display_name") or result.get("recipe_title"))

        add_recipe_urls([recipe_url])
        assignment = save_import_cookbook_assignment(recipe_url, result, cookbook)
        print(
            f"[recipe_import] action=created title={import_recipe_title(result, recipe_url)} url={recipe_url}"
        )
        print(
            f"[recipe_import] action=categories_start title={import_recipe_title(result, recipe_url)}"
        )
        category_status = apply_imported_recipe_category_routine(recipe_url, result, assignment)
        result = {
            **result,
            "import_category_status": category_status,
            "category_status": category_status,
            "category_status_message": IMPORT_CATEGORY_STATUS_MESSAGE if category_status.get("ok") else category_status.get("error", ""),
        }
        create_source_url_pdf(recipe_url)

        extraction_source = str(
            result.get("extraction_mode")
            or result.get("extraction_method")
            or ""
        ).strip()
        if _should_auto_generate_recipe_pdf(recipe_url, extraction_source):
            pdf_job = schedule_generated_recipe_pdf_creation(recipe_url, context=context)
            result = {
                **result,
                "generated_recipe_pdf_job": pdf_job,
            }

        record_recipe_import_activity(recipe_url, result, context)
        sort_ingredients()
        return result

    if result.get("ok"):
        result["error"] = result.get("error") or NO_UPLOAD_INGREDIENTS_ERROR
        result["ok"] = False

    return result


def vision_failure_response(
    debug,
    error_code,
    error_message,
    status=400,
    upload_path=None,
    source_name="",
    source_url="",
    failed_step="extract",
    extra=None,
):
    debug = debug if isinstance(debug, dict) else build_vision_debug()
    if not debug.get("error_code"):
        set_vision_debug_error(
            debug,
            error_code,
            error_message,
            failed_status=debug.get("failed_status") or "",
        )

    upload_path_text = str(upload_path or debug.get("file_path") or "").strip()
    source_name = source_name or (Path(upload_path_text).name if upload_path_text else "")
    error_code = debug.get("error_code") or error_code
    error_message = debug.get("error_message") or error_message
    model_used = str(debug.get("model") or resolve_vision_model())

    payload = build_upload_failure_result(
        {
            "source_type": "image",
            "source_name": source_name,
            "source_url": source_url,
            "uploaded_file_path": upload_path_text,
            "detected_food_photo": True,
            "recipe_json": debug.get("recipe_json"),
        },
        error_message,
        failed_step=failed_step,
    )
    payload.update({
        "success": False,
        "model_used": model_used,
        "error_code": error_code,
        "error_message": error_message,
        "debug": debug,
        "source_type": "image",
        "source_type_label": "Image",
        "source_name": source_name,
        "uploaded_file_path": upload_path_text,
        "extraction_mode": "vision",
        "extraction_mode_label": "Vision",
        "raw": debug.get("recipe_json"),
        "recipe_json": debug.get("recipe_json"),
    })
    if source_url:
        payload["source_url"] = source_url
    if extra:
        payload.update(extra)
    payload.setdefault("model_used", model_used)
    return jsonify(payload), status


def validate_vision_image_upload(upload_path, filename, mime_type, debug):
    file_exists = upload_path.is_file()
    debug["file_exists"] = file_exists
    log_vision_debug_step(debug, "File exists", file_exists=file_exists)

    if not file_exists:
        return set_vision_debug_error(
            debug,
            "UPLOADED_FILE_MISSING",
            "Uploaded file missing.",
            failed_status="image_uploaded",
        )

    try:
        file_size = upload_path.stat().st_size
    except OSError as exc:
        return set_vision_debug_error(
            debug,
            "UPLOADED_FILE_UNREADABLE",
            f"Uploaded file could not be read: {exc}",
            failed_status="image_uploaded",
        )

    debug["file_size"] = file_size
    log_vision_debug_step(debug, "File size", file_size=file_size)

    if file_size <= 0:
        return set_vision_debug_error(
            debug,
            "EMPTY_IMAGE_FILE",
            "Uploaded image file is empty.",
            failed_status="image_uploaded",
        )

    normalized_mime_type = normalize_upload_mime_type(mime_type, filename, upload_path)
    normalized_mime_type = str(normalized_mime_type or "").split(";", 1)[0].strip().lower()
    suffix = upload_path.suffix.lower()
    image_type_supported = (
        normalized_mime_type in VISION_SUPPORTED_IMAGE_MIME_TYPES
        or suffix in VISION_SUPPORTED_IMAGE_SUFFIXES
    )
    debug["mime_type"] = normalized_mime_type
    debug["image_type_supported"] = image_type_supported
    log_vision_debug_step(
        debug,
        "Image type supported",
        mime_type=normalized_mime_type,
        suffix=suffix,
        image_type_supported=image_type_supported,
    )

    if not image_type_supported:
        return set_vision_debug_error(
            debug,
            "UNSUPPORTED_IMAGE_FORMAT",
            "Unsupported image format.",
            failed_status="image_uploaded",
        )

    try:
        from PIL import Image

        with Image.open(upload_path) as image:
            debug["image_format"] = str(image.format or "")
            debug["image_width"] = image.size[0]
            debug["image_height"] = image.size[1]
            image.verify()
    except ImportError:
        return set_vision_debug_error(
            debug,
            "IMAGE_VALIDATION_UNAVAILABLE",
            "Image validation unavailable because Pillow is not installed.",
            failed_status="image_uploaded",
        )
    except Exception as exc:
        return set_vision_debug_error(
            debug,
            "IMAGE_UNREADABLE",
            f"Uploaded image is not readable: {exc}",
            failed_status="image_uploaded",
        )

    debug["image_readable"] = True
    debug["image_uploaded"] = True
    log_vision_debug_step(debug, "Image readable", image_format=debug.get("image_format"))
    return ""


@recipe_bp.route("/api/debug/openai-ping", methods=["GET"])
def api_debug_openai_ping():
    model = str(
        request.args.get("model")
        or OPENAI_PING_TEXT_MODEL
    ).strip()
    if not model:
        model = "gpt-4o-mini"

    if not os.getenv("OPENAI_API_KEY"):
        return jsonify(
            {
                "success": False,
                "model": model,
                "error_type": "MISSING_OPENAI_API_KEY",
                "error_message": "OPENAI_API_KEY is missing.",
            }
        ), 401

    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Return the word OK."}],
            "max_tokens": 8,
            "response_format": {"type": "text"},
        }
        if supports_custom_temperature(model):
            payload["temperature"] = 0

        print(
            f"[OpenAI] action=openai-ping model={model} "
            f"temperature_included={supports_custom_temperature(model)}"
        )
        response = get_openai_client().chat.completions.create(
            **payload
        )
        message = str((response.choices[0].message.content or "").strip())
        message = message.strip('"').strip("'") or "OK"
        return jsonify({"success": True, "model": model, "message": message}), 200
    except Exception as exc:
        error_code, error_param = get_openai_error_code_and_param(exc)
        print(f"[OpenAI] action=openai-ping error_code={error_code} error_param={error_param}")
        return jsonify(
            {
                "success": False,
                "model": model,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "error_code": error_code,
                "error_param": error_param,
            }
        ), 502


@recipe_bp.route("/api/debug/vision-ping", methods=["POST"])
def api_debug_vision_ping():
    data = request.get_json(silent=True) or {}
    uploaded_file_path = str(data.get("uploaded_file_path") or "").strip()
    if not uploaded_file_path:
        return jsonify(
            {
                "success": False,
                "error_type": "INVALID_REQUEST",
                "error_message": "uploaded_file_path is required.",
            }
        ), 400

    upload_path = Path(uploaded_file_path)
    if not upload_path.exists() or not upload_path.is_file():
        return jsonify(
            {
                "success": False,
                "error_type": "UPLOADED_FILE_MISSING",
                "error_message": "Uploaded image file does not exist.",
            }
        ), 400

    debug = build_vision_debug(uploaded_file_path=uploaded_file_path, filename=upload_path.name)
    resolved_mime = normalize_upload_mime_type(
        str(data.get("mime_type") or "").strip(),
        upload_path.name,
        upload_path,
    )

    prompt = (
        "Briefly describe this image in one sentence. "
        'Return JSON only: {"description":""}'
    )

    try:
        response_text = send_image_prompt_to_openai(
            prompt,
            upload_path,
            resolved_mime,
            model=resolve_vision_model(),
            debug=debug,
        )
    except Exception as exc:
        debug_model = str(debug.get("model") or resolve_vision_model())
        error_code, error_message = classify_vision_ai_exception(exc)
        set_vision_debug_error(
            debug,
            error_code,
            error_message,
            failed_status="vision_response_received",
        )
        return jsonify(
            {
                "success": False,
                "model": debug_model,
                "error_code": error_code,
                "error_type": type(exc).__name__,
                "error_message": error_message,
                "debug": debug,
            }
        ), 502

    try:
        parsed_response = json.loads(response_text)
    except Exception as exc:
        debug_model = str(debug.get("model") or resolve_vision_model())
        return jsonify(
            {
                "success": False,
                "model": debug_model,
                "error_code": "VISION_PING_PARSE_ERROR",
                "error_message": str(exc),
                "raw_response": response_text,
                "debug": debug,
            }
        ), 502

    return jsonify(
        {
            "success": True,
            "model": str(debug.get("model") or resolve_vision_model()),
            "raw_response": response_text,
            "parsed_response": parsed_response,
            "debug": debug,
        }
    ), 200


@recipe_bp.route("/api/generate-recipe-from-image", methods=["POST"])
def api_generate_recipe_from_image_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(force=True) or {}
    uploaded_file_path = str(data.get("uploaded_file_path") or "").strip()
    source_type = str(data.get("source_type") or "").strip().lower() or "image"
    extraction_mode = str(data.get("extraction_mode") or "").strip().lower() or "vision"
    user_description = str(
        data.get("photo_description")
        or data.get("recipe_description")
        or data.get("description")
        or ""
    ).strip()
    debug = build_vision_debug(uploaded_file_path=uploaded_file_path)
    log_vision_debug_step(debug, "Image path received", image_path=uploaded_file_path)

    if source_type != "image":
        set_vision_debug_error(
            debug,
            "INVALID_SOURCE_TYPE",
            "image source_type is required.",
            failed_status="image_uploaded",
        )
        return vision_failure_response(debug, "INVALID_SOURCE_TYPE", "image source_type is required.")

    if extraction_mode != "vision":
        set_vision_debug_error(
            debug,
            "INVALID_EXTRACTION_MODE",
            "extraction_mode must be vision.",
            failed_status="vision_request_sent",
        )
        return vision_failure_response(debug, "INVALID_EXTRACTION_MODE", "extraction_mode must be vision.")

    if not uploaded_file_path:
        set_vision_debug_error(
            debug,
            "UPLOADED_FILE_PATH_REQUIRED",
            "uploaded_file_path is required.",
            failed_status="image_uploaded",
        )
        return vision_failure_response(debug, "UPLOADED_FILE_PATH_REQUIRED", "uploaded_file_path is required.")

    try:
        upload_root = UPLOAD_FOLDER.resolve()
        upload_path = Path(uploaded_file_path).resolve()
    except Exception:
        set_vision_debug_error(
            debug,
            "INVALID_UPLOADED_FILE_PATH",
            "Invalid uploaded_file_path value.",
            failed_status="image_uploaded",
        )
        return vision_failure_response(debug, "INVALID_UPLOADED_FILE_PATH", "Invalid uploaded_file_path value.")

    if upload_root not in upload_path.parents and upload_root != upload_path:
        set_vision_debug_error(
            debug,
            "INVALID_UPLOADED_FILE_PATH",
            "Invalid uploaded_file_path value.",
            failed_status="image_uploaded",
        )
        return vision_failure_response(
            debug,
            "INVALID_UPLOADED_FILE_PATH",
            "Invalid uploaded_file_path value.",
            upload_path=upload_path,
            source_name=upload_path.name,
        )

    if not upload_path.name:
        set_vision_debug_error(
            debug,
            "UPLOADED_FILE_NAME_MISSING",
            "Uploaded image name is missing.",
            failed_status="image_uploaded",
        )
        return vision_failure_response(
            debug,
            "UPLOADED_FILE_NAME_MISSING",
            "Uploaded image name is missing.",
            upload_path=upload_path,
        )

    resolved_mime_type = normalize_upload_mime_type("", upload_path.name, upload_path)
    debug.update({
        "file_path": str(upload_path),
        "filename": upload_path.name,
        "mime_type": str(resolved_mime_type or ""),
    })
    validation_error = validate_vision_image_upload(
        upload_path,
        upload_path.name,
        resolved_mime_type,
        debug,
    )
    if validation_error:
        return vision_failure_response(
            debug,
            debug.get("error_code") or "IMAGE_VALIDATION_FAILED",
            validation_error,
            upload_path=upload_path,
            source_name=upload_path.name,
        )

    cookbook = selected_import_cookbook_from_json(data)
    log_selected_import_cookbook("media-upload-vision", cookbook)

    recipe_url = f"uploaded://{upload_path.name}"
    extraction_method = "manual_description" if user_description else "image_estimate"
    extraction_mode_label = "Vision + Description" if user_description else "Vision"
    estimation_banner = (
        "Recipe estimated from uploaded image and your description. Review before saving."
        if user_description
        else "Recipe estimated from uploaded image. Review ingredients before saving."
    )
    vision_unavailable_message = (
        "Could not estimate a recipe from this image. Try describing the meal manually."
    )
    parsed_recipe, inference_error = generateRecipeFromImage(
        upload_path,
        user_description=user_description,
        recipe_url=recipe_url,
        filename=upload_path.name,
        mime_type=resolved_mime_type,
        debug=debug,
    )

    if inference_error:
        if parsed_recipe is not None:
            debug["recipe_json"] = parsed_recipe
        return vision_failure_response(
            debug,
            debug.get("error_code") or "VISION_RECIPE_GENERATION_FAILED",
            inference_error or vision_unavailable_message,
            upload_path=upload_path,
            source_name=upload_path.name,
            source_url=recipe_url,
            extra={
                "raw": parsed_recipe,
                "recipe_json": parsed_recipe,
            },
        )

    if parsed_recipe is not None:
        parsed_recipe = dict(parsed_recipe)
        parsed_recipe["source_url"] = recipe_url
        parsed_recipe["extraction_mode"] = extraction_method
        if user_description:
            parsed_recipe["manual_description"] = user_description
        normalize_extracted_recipe_identity(parsed_recipe)
        normalize_extracted_ingredient_fields(parsed_recipe)
        normalize_extracted_equipment_fields(parsed_recipe)
        cover_image = extract_recipe_cover_image_from_upload(
            upload_path,
            resolved_mime_type,
            upload_path.name,
            recipe_url,
            fallback_alt=parsed_recipe.get("recipe_title") or upload_path.name,
        )
        if cover_image:
            parsed_recipe["cover_image"] = cover_image
        debug["vision_request_sent"] = True
        debug["vision_response_received"] = True
        debug["json_parse_success"] = True
        debug["recipe_json_parsed"] = True
        debug["recipe_json"] = parsed_recipe

    result = build_extract_result(recipe_url, parsed_recipe, extraction_method)
    result["source_type"] = source_type
    result["source_type_label"] = "Image"
    result["source_url"] = recipe_url
    result["source_name"] = upload_path.name
    result["uploaded_file_path"] = str(upload_path)
    result["detected_food_photo"] = True
    result["extraction_mode"] = extraction_method
    result["extraction_mode_label"] = extraction_mode_label
    result["estimation_banner"] = estimation_banner
    result["raw"] = parsed_recipe
    result["recipe_json"] = parsed_recipe
    result["ok"] = bool(result.get("ok") and result.get("ingredients"))
    debug["recipe_json"] = parsed_recipe
    debug["ingredient_count"] = len(result.get("ingredients") or [])

    if not result.get("ingredients"):
        set_vision_debug_error(
            debug,
            "NO_INGREDIENTS_FOUND",
            "No ingredients found.",
            failed_status="recipe_creation_success",
        )
        return vision_failure_response(
            debug,
            "NO_INGREDIENTS_FOUND",
            "No ingredients found.",
            upload_path=upload_path,
            source_name=upload_path.name,
            source_url=recipe_url,
            extra={
                **result,
                "ok": False,
            },
        )

    save_extracted_recipe_json(recipe_url, parsed_recipe)
    result = commit_media_import_result(
        result,
        cookbook,
        recipe_url=recipe_url,
        context="media-upload",
    )
    result["source_type"] = source_type
    result["source_type_label"] = "Image"
    result["source_url"] = recipe_url
    result["source_name"] = upload_path.name
    result["uploaded_file_path"] = str(upload_path)
    result["detected_food_photo"] = True
    result["extraction_mode"] = extraction_method
    result["extraction_mode_label"] = extraction_mode_label
    result["estimation_banner"] = estimation_banner
    result["raw"] = parsed_recipe
    result["recipe_json"] = parsed_recipe
    result["success"] = bool(result.get("ok"))
    result["model_used"] = str(debug.get("model") or resolve_vision_model())
    result["debug"] = debug
    _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
    debug["recipe_creation_success"] = bool(result.get("ok"))
    log_vision_debug_step(debug, "Recipe creation success", recipe_creation_success=debug["recipe_creation_success"])

    return jsonify(result), 200


@recipe_bp.route("/api/estimate-per-serving", methods=["POST"])
def api_estimate_per_serving_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(silent=True) or {}
    recipe_url = str(
        data.get("recipe_url")
        or data.get("url")
        or data.get("source_url")
        or ""
    ).strip()
    recipe = _extract_recipe_payload_for_nutrition(data)

    if not recipe and recipe_url:
        recipe = load_editable_recipe(recipe_url) or {}

    if not recipe:
        return jsonify(with_openai_usage_dashboard({
            "ok": False,
            "success": False,
            "error": "Recipe payload is required.",
            "model_used": str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL)),
            "debug": {
                "model": str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL)),
                "recipe_url": recipe_url,
            },
        })), 400

    model_used = str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL))
    result = estimate_recipe_nutrition(recipe)

    if result.get("ok") and recipe_url:
        updated_recipe = {
            **recipe,
            "nutrition": result.get("nutrition", []),
        }
        save_result = save_editable_recipe(recipe_url, updated_recipe)
        if not save_result.get("ok"):
            result = {
                **result,
                "ok": False,
                "success": False,
                "error": save_result.get("error") or "Unable to save estimated nutrition.",
            }
            _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
        else:
            result["recipe_json"] = updated_recipe
            result["recipe_url"] = recipe_url
            _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)

    if result.get("ok"):
        result["success"] = True
        result["recipe_json"] = result.get("recipe_json", recipe)
    else:
        result["success"] = False

    result["model_used"] = model_used
    result["debug"] = {
        "model": model_used,
        "recipe_url": recipe_url,
    }
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/create-recipe-pdf", methods=["POST"])
def api_create_recipe_pdf_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or data.get("recipe_url") or data.get("source_url") or "").strip()

    if not url:
        return jsonify(with_openai_usage_dashboard({
            "ok": False,
            "success": False,
            "error": "Recipe URL is required.",
        })), 400

    result = create_recipe_pdf_from_url(url)
    status = 200 if result.get("ok") else 400
    result["success"] = bool(result.get("ok"))
    if "model_used" not in result:
        result["model_used"] = str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL))

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/extract_recipe", methods=["POST"])
def api_extract_recipe_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(force=True)

    url = str(data.get("url", "")).strip()
    urls = [
        str(item).strip()
        for item in data.get("urls", [url])
        if str(item).strip()
    ]
    job_id = str(data.get("job_id") or new_job_id())
    index = int(data.get("index", 0))
    cookbook = selected_import_cookbook_from_json(data)
    log_selected_import_cookbook("api-url", cookbook)

    if not urls:
        urls = [url]

    if is_cancel_requested(job_id):
        return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

    mark_url_running(job_id, urls, index)

    if not is_current_job(job_id):
        return jsonify({"ok": False, "cancelled": True, "error": "Extraction superseded."}), 409

    try:
        result = extract_recipe_from_url(
            url,
            progress_callback=lambda message, summary=None: mark_url_message(
                job_id,
                urls,
                index,
                message,
                summary,
            ),
        )

        if is_cancel_requested(job_id) or not is_current_job(job_id):
            return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

        ingredients = result.get("ingredients", [])

        if not result.get("ok") or not ingredients:
            if result.get("ok"):
                result = {
                    **result,
                    "ok": False,
                    "error": NO_INGREDIENTS_ERROR,
                }

            progress = mark_url_failed(job_id, urls, index, result.get("error") or NO_INGREDIENTS_ERROR)
            finish_batch_if_ready(job_id, progress)

            return jsonify(with_openai_usage_dashboard(result)), 400

        add_items(ingredients)
        save_ingredients_for_recipe(url, ingredients, result)
        if result.get("display_name") or result.get("recipe_title"):
            save_recipe_url_name(url, result.get("display_name") or result.get("recipe_title"))
        add_recipe_urls([url])
        assignment = save_import_cookbook_assignment(url, result, cookbook)
        mark_url_message(
            job_id,
            urls,
            index,
            IMPORT_CATEGORY_STATUS_MESSAGE,
            summary="Generating categories with ChatGPT.",
        )
        category_status = apply_imported_recipe_category_routine(url, result, assignment)
        create_source_url_pdf(url)
        pdf_job = schedule_generated_recipe_pdf_creation(url, context="api-url")
        result = {
            **result,
            "generated_recipe_pdf_job": pdf_job,
            "import_category_status": category_status,
            "category_status": category_status,
            "category_status_message": IMPORT_CATEGORY_STATUS_MESSAGE if category_status.get("ok") else category_status.get("error", ""),
        }
        record_recipe_import_activity(url, result, "api-url")
        progress = mark_url_done(job_id, urls, index, len(ingredients))
        finish_batch_if_ready(job_id, progress)

        return jsonify(with_openai_usage_dashboard(result))
    except Exception as exc:
        if is_cancel_requested(job_id) or not is_current_job(job_id):
            return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

        result = {"ok": False, "error": str(exc) or "Recipe extraction failed."}
        progress = mark_url_failed(job_id, urls, index, result["error"])
        finish_batch_if_ready(job_id, progress)

        return jsonify(with_openai_usage_dashboard(result)), 500


@recipe_bp.route("/api/start_extract_progress", methods=["POST"])
def api_start_extract_progress_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(force=True)
    urls = [
        str(item).strip()
        for item in data.get("urls", [])
        if str(item).strip()
    ]
    job_id = str(data.get("job_id") or new_job_id())
    cookbook = selected_import_cookbook_from_json(data)
    log_selected_import_cookbook("api-url-batch", cookbook)

    return jsonify(start_progress(urls, job_id=job_id))


@recipe_bp.route("/api/extract_progress", methods=["GET"])
def api_extract_progress_route():
    return jsonify(load_progress())


@recipe_bp.route("/api/cancel_extract", methods=["POST"])
def api_cancel_extract_route():
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "").strip() or None

    progress = request_cancel(job_id)

    return jsonify(progress)


@recipe_bp.route("/api/recipe_quantity", methods=["POST"])
def api_recipe_quantity_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    quantity = data.get("quantity", 1)
    quantity = normalize_recipe_quantity(quantity)

    return jsonify(update_recipe_quantity(url, quantity))


@recipe_bp.route("/api/recipe_ingredient_quantity", methods=["POST"])
def api_recipe_ingredient_quantity_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    ingredient = str(data.get("ingredient", "") or "").strip()
    quantity = str(data.get("quantity", "") or "").strip()
    unit = str(data.get("unit", "") or "").strip()

    result = update_recipe_ingredient_quantity(url, ingredient, quantity, unit)
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


@recipe_bp.route("/api/recipe_name", methods=["POST"])
def api_recipe_name_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    name = str(data.get("name", "") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    save_recipe_url_name(url, name)

    return jsonify({
        "ok": True,
        "url": url,
        "name": name,
    })


@recipe_bp.route("/api/recipe_urls/reorder", methods=["POST"])
def api_reorder_recipe_urls_route():
    data = request.get_json(silent=True) or {}
    requested_urls = data.get("urls") if isinstance(data.get("urls"), list) else []

    if not requested_urls:
        return jsonify({
            "ok": False,
            "error": "Recipe URL order is required.",
        }), 400

    current_urls = load_recipe_urls()
    current_by_key = {
        normalize_recipe_url_key(url): url
        for url in current_urls
    }
    ordered_urls = []
    seen = set()

    for url in requested_urls:
        key = normalize_recipe_url_key(url)

        if not key or key in seen or key not in current_by_key:
            continue

        ordered_urls.append(current_by_key[key])
        seen.add(key)

    for url in current_urls:
        key = normalize_recipe_url_key(url)

        if key and key not in seen:
            ordered_urls.append(url)
            seen.add(key)

    if current_urls and not ordered_urls:
        return jsonify({
            "ok": False,
            "error": "No current recipe URLs matched the requested order.",
        }), 400

    save_recipe_urls(ordered_urls)

    return jsonify({
        "ok": True,
        "urls": ordered_urls,
    })


@recipe_bp.route("/api/recipe", methods=["GET", "POST"])
def api_recipe_route():
    if request.method == "GET":
        url = str(request.args.get("url", "") or "").strip()

        if not url:
            return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

        return jsonify(load_editable_recipe(url))

    data = request.get_json(silent=True) or {}
    original_url = str(data.get("original_url", "") or "").strip()

    if not original_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    result = save_editable_recipe(original_url, data.get("recipe", {}))
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/create_recipe", methods=["POST"])
def api_create_recipe_route():
    return jsonify(create_new_recipe()), 201


@recipe_bp.route("/api/recipe_nutrition_estimate", methods=["POST"])
def api_recipe_nutrition_estimate_route():
    data = request.get_json(silent=True) or {}
    recipe = data.get("recipe", data)
    result = estimate_recipe_nutrition(recipe)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_note_feedback", methods=["POST"])
def api_recipe_note_feedback_route():
    data = request.get_json(silent=True) or {}
    result = recipe_note_feedback(data)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_category_decision", methods=["POST"])
def api_recipe_category_decision_route():
    data = request.get_json(silent=True) or {}
    recipe = data.get("recipe", data)
    mode = data.get("mode", "missing")
    result = decide_recipe_categories_with_chatgpt(
        recipe,
        mode=mode,
        current_categories=data.get("current_categories", {}),
        trigger_source=data.get("trigger_source") or f"recipe_editor:{mode}",
    )
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_step_image", methods=["POST"])
def api_recipe_step_image_route():
    data = request.get_json(silent=True) or {}
    result = generate_recipe_step_image(data)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_equipment_image", methods=["POST"])
def api_recipe_equipment_image_route():
    data = request.get_json(silent=True) or {}
    result = generate_recipe_equipment_image(data)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_cover_image", methods=["POST"])
def api_recipe_cover_image_route():
    url = str(request.form.get("url", "") or "").strip()
    source_url = str(request.form.get("source_url", "") or "").strip()
    fallback_alt = str(request.form.get("alt", "") or "").strip()
    uploaded_file = request.files.get("cover_image") or request.files.get("recipe_cover_image")
    result = save_recipe_cover_image_upload(url, uploaded_file, source_url, fallback_alt)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_detail_image", methods=["POST"])
def api_recipe_detail_image_route():
    url = str(request.form.get("url", "") or "").strip()
    kind = str(request.form.get("kind", "") or "").strip()
    target = (
        request.form.get("target")
        or request.form.get("equipment_index")
        or request.form.get("equipment_number")
        or request.form.get("step_number")
        or ""
    )
    uploaded_file = (
        request.files.get("image")
        or request.files.get("detail_image")
        or request.files.get("recipe_image")
    )
    result = save_recipe_detail_image_upload(url, kind, target, uploaded_file)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_image_progress", methods=["GET"])
def api_recipe_image_progress_route():
    url = str(request.args.get("url", "") or "").strip()

    return jsonify(load_recipe_image_progress(url=url or None))


@recipe_bp.route("/api/recipe_pdf", methods=["POST"])
def api_recipe_pdf_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    result = create_recipe_pdf_from_url(url)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/source_url_pdf", methods=["POST"])
def api_source_url_pdf_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    result = create_source_url_pdf(url)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_pdf/delete", methods=["POST"])
def api_delete_recipe_pdf_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    result = delete_editable_recipe_pdf(url)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_pdf/cloudflare_upload", methods=["POST"])
def api_upload_recipe_pdf_to_cloudflare_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    kind = normalize_pdf_kind(data.get("kind") or data.get("pdf_kind") or "")
    result = upload_recipe_pdf_to_cloudflare(url, pdf_kind=kind)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_pdfs/cloudflare_upload", methods=["POST"])
def api_upload_recipe_pdfs_to_cloudflare_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "") or "").strip()
    result = upload_all_recipe_pdfs_to_cloudflare(url)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/recipe_pdf_link", methods=["GET"])
def recipe_pdf_link_route():
    url = str(request.args.get("url", "") or "").strip()

    if not url:
        return jsonify({
            "success": False,
            "cached": False,
            "public_url": "",
            "error": "Recipe URL is required.",
        }), 400

    kind = normalize_pdf_kind(request.args.get("kind") or request.args.get("pdf_kind") or "")
    result = ensure_recipe_pdf_cloudflare_link(url, allow_local_fallback=False, pdf_kind=kind)
    public_url = str(result.get("public_url") or result.get("pdf_public_url") or "").strip()
    success = bool(result.get("success") and public_url)
    status = 200 if success else 400

    return jsonify({
        "success": success,
        "cached": bool(result.get("cached")),
        "public_url": public_url,
        "r2_object_key": result.get("r2_object_key") or result.get("pdf_object_key") or "",
        "uploaded_at": result.get("uploaded_at") or result.get("pdf_uploaded_at") or "",
        "cloud_status": result.get("cloud_status") or ("uploaded" if success else ""),
        "timings": result.get("timings", {}),
        "error": "" if success else result.get("error", "Unable to prepare Cloudflare PDF link."),
    }), status


@recipe_bp.route("/recipe_archive_pdf", methods=["GET"])
def recipe_archive_pdf_route():
    url = str(request.args.get("url", "") or "").strip()
    wants_download = str(request.args.get("download", "") or "").strip().lower() in {"1", "true", "yes"}
    kind = normalize_pdf_kind(request.args.get("kind") or request.args.get("pdf_kind") or "")

    if not url:
        abort(404)

    if wants_download:
        user = current_user()
        if not is_admin_user(user):
            return Response("Admin access is required to download local recipe PDFs.", status=403)

        pdf_path = recipe_pdf_path(url, kind)

        if not pdf_path.exists():
            abort(404)

        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=pdf_path.name,
        )

    result = ensure_recipe_pdf_cloudflare_link(url, allow_local_fallback=True, pdf_kind=kind)
    public_url = str(result.get("public_url") or result.get("pdf_public_url") or "").strip()

    if result.get("success") and public_url:
        timings = result.get("timings", {})
        redirect_start = perf_counter()
        response = redirect(public_url)
        timings["redirect_ms"] = round((perf_counter() - redirect_start) * 1000, 2)
        log_recipe_pdf_timing("redirect", url, timings)

        return response

    pdf_path = recipe_pdf_path(url, kind)

    if pdf_path.exists():
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=pdf_path.name,
        )

    abort(404)


@recipe_bp.route("/recipe_cover_image", methods=["GET"])
def recipe_cover_image_route():
    url = str(request.args.get("url", "") or "").strip()

    if not url:
        abort(404)

    cover_image = find_recipe_cover_image(url)
    image_path = recipe_cover_image_file_path(cover_image)

    if not image_path:
        abort(404)

    return send_file(
        image_path,
        mimetype=cover_image.get("mime_type") if isinstance(cover_image, dict) else None,
        as_attachment=False,
        download_name=image_path.name,
        max_age=0,
    )


def find_recipe_cover_image(url):
    recipe_key = normalize_recipe_url_key(url)

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if normalize_recipe_url_key(data.get("source_url", "")) == recipe_key:
            cover_image = data.get("cover_image")
            if isinstance(cover_image, dict):
                return cover_image

    recipe_meta = load_recipe_ingredients().get(recipe_key, {})
    cover_image = recipe_meta.get("cover_image") if isinstance(recipe_meta, dict) else None
    return cover_image if isinstance(cover_image, dict) else {}


@recipe_bp.route("/api/food_review_alternatives", methods=["POST"])
def api_food_review_alternatives_route():
    account_response = require_account_for_food_review()
    if account_response:
        return account_response

    data = request.get_json(silent=True) or {}
    result = suggest_food_review_alternatives(data)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/remove_recipe", methods=["POST"])
def remove_recipe_route():
    data = request.get_json(silent=True) or {}
    url = request.form.get("url") or data.get("url", "")

    remove_recipe_and_unused_ingredients(url)
    remove_recipe_url(url)

    return redirect("/")


@recipe_bp.route("/purge_recipe", methods=["POST"])
def purge_recipe_route():
    data = request.get_json(silent=True) or {}
    url = request.form.get("url") or data.get("url", "")

    purge_recipe_from_all_cookbooks(url)
    remove_recipe_and_unused_ingredients(url)
    remove_recipe_url(url)

    return redirect("/")


def finish_batch_if_ready(job_id, progress):
    if progress.get("cancel_requested"):
        return

    if not batch_is_finished(progress):
        return

    if batch_has_success(progress):
        sort_ingredients()

    finish_progress(job_id, ok=not any(
        item.get("state") == "failed"
        for item in progress.get("urls", [])
    ))
