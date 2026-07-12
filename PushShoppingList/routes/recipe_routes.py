import json
import os
import re
from datetime import datetime
from datetime import timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import flash
from flask import Response
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import send_file
from werkzeug.utils import secure_filename

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
from PushShoppingList.services.extraction_progress_service import set_url_menu_recipes
from PushShoppingList.services.extraction_progress_service import start_progress
from PushShoppingList.services.extraction_progress_service import update_menu_recipe_step
from PushShoppingList.services.file_lock_service import workspace_write_lock
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_from_url
from PushShoppingList.services.recipe_extract_service import extract_menu_recipes_from_upload
from PushShoppingList.services.recipe_extract_service import extract_menu_recipes_from_url
from PushShoppingList.services.recipe_extract_service import extract_menu_stubs_from_url
from PushShoppingList.services.recipe_extract_service import generate_menu_recipe_from_stub
from PushShoppingList.services.recipe_extract_service import generateRecipeFromImage
from PushShoppingList.services.recipe_extract_service import build_vision_debug
from PushShoppingList.services.recipe_extract_service import call_openai_vision_image
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OPENAI_PING_TEXT_MODEL
from PushShoppingList.services.recipe_extract_service import openai_runtime_diagnostics
from PushShoppingList.services.recipe_extract_service import resolve_menu_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_model_source
from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model
from PushShoppingList.services.recipe_extract_service import resolve_menu_cleanup_model_source
from PushShoppingList.services.recipe_extract_service import resolve_vision_model
from PushShoppingList.services.recipe_extract_service import resolve_vision_model_source
from PushShoppingList.services.recipe_extract_service import classify_vision_ai_exception
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import build_extract_result
from PushShoppingList.services.recipe_extract_service import build_menu_stub_extract_result_from_items
from PushShoppingList.services.recipe_extract_service import apply_menu_source_pdf_metadata
from PushShoppingList.services.recipe_extract_service import menu_source_pdf_metadata_from_result
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
from PushShoppingList.services.recipe_extract_service import VISION_CONVERTIBLE_IMAGE_MIME_TYPES
from PushShoppingList.services.recipe_extract_service import VISION_CONVERTIBLE_IMAGE_SUFFIXES
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import recipe_cover_image_file_path
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import recipe_pdf_path
from PushShoppingList.services.recipe_extract_service import ensure_heif_image_support
from PushShoppingList.services.recipe_extract_service import unsupported_phone_image_message
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import ingredient_sections_from_recipe_data
from PushShoppingList.services.cookbook_service import is_unclassified_cookbook
from PushShoppingList.services.cookbook_service import cookbook_view
from PushShoppingList.services.cookbook_service import load_cookbooks
from PushShoppingList.services.cookbook_service import prepare_cookbook_menu_view
from PushShoppingList.services.cookbook_service import category_metadata_has_values
from PushShoppingList.services.cookbook_service import COOKBOOK_CATEGORY_ALL_FIELDS
from PushShoppingList.services.cookbook_service import CATEGORY_SOURCE_AI_INFERRED
from PushShoppingList.services.cookbook_service import CookbookCategoryOverwriteConflict
from PushShoppingList.services.cookbook_service import cookbook_recipe_record_for_url
from PushShoppingList.services.cookbook_service import MISCELLANEOUS_MENU_SECTION
from PushShoppingList.services.cookbook_service import move_recipes_to_cookbook
from PushShoppingList.services.cookbook_service import purge_recipe_from_all_cookbooks
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.cookbook_service import resolve_cookbook_destination
from PushShoppingList.services.cookbook_service import stored_category_metadata
from PushShoppingList.services.cookbook_service import update_cookbook_recipe_categories
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import shopping_item_food_rule_status
from PushShoppingList.services.food_review_alternative_service import suggest_food_review_alternatives
from PushShoppingList.services.recipe_edit_service import create_new_recipe
from PushShoppingList.services.recipe_edit_service import create_editable_recipe_pdf
from PushShoppingList.services.recipe_edit_service import delete_editable_recipe_pdf
from PushShoppingList.services.recipe_edit_service import decide_recipe_categories_with_chatgpt
from PushShoppingList.services.recipe_edit_service import estimate_recipe_nutrition
from PushShoppingList.services.recipe_edit_service import generate_recipe_cover_image
from PushShoppingList.services.recipe_edit_service import generate_recipe_equipment_image
from PushShoppingList.services.recipe_edit_service import generate_recipe_ingredient_image
from PushShoppingList.services.recipe_edit_service import generate_recipe_step_image
from PushShoppingList.services.recipe_edit_service import load_editable_recipe
from PushShoppingList.services.recipe_edit_service import load_recipe_output
from PushShoppingList.services.recipe_edit_service import log_recipe_pdf_timing
from PushShoppingList.services.recipe_edit_service import recipe_note_feedback
from PushShoppingList.services.recipe_edit_service import remove_recipe_cover_image
from PushShoppingList.services.recipe_edit_service import remove_recipe_detail_image
from PushShoppingList.services.recipe_edit_service import review_recipe_store_sections
from PushShoppingList.services.recipe_edit_service import save_editable_recipe
from PushShoppingList.services.recipe_edit_service import save_recipe_cover_image_upload
from PushShoppingList.services.recipe_edit_service import save_recipe_detail_image_upload
from PushShoppingList.services.recipe_edit_service import save_recipe_output
from PushShoppingList.services.recipe_edit_service import test_local_title_image_generation
from PushShoppingList.services.recipe_edit_service import create_source_url_pdf
from PushShoppingList.services.recipe_edit_service import ensure_recipe_pdf_cloudflare_link
from PushShoppingList.services.recipe_edit_service import normalize_pdf_kind
from PushShoppingList.services.recipe_edit_service import upload_recipe_pdf_to_cloudflare
from PushShoppingList.services.recipe_edit_service import upload_all_recipe_pdfs_to_cloudflare
from PushShoppingList.services.recipe_edit_service import update_editable_restaurant_source
from PushShoppingList.services.recipe_edit_service import update_editable_source_documents
from PushShoppingList.services.recipe_edit_service import editable_restaurant_usage
from PushShoppingList.services.recipe_edit_service import backfill_editable_restaurant_usage
from PushShoppingList.services.recipe_edit_service import editable_restaurant_logo_file_path
from PushShoppingList.services.recipe_edit_service import backfill_editable_restaurant_sources
from PushShoppingList.services.recipe_edit_service import create_editable_restaurant
from PushShoppingList.services.recipe_edit_service import get_editable_restaurant
from PushShoppingList.services.recipe_edit_service import list_editable_restaurants
from PushShoppingList.services.recipe_edit_service import update_editable_restaurant
from PushShoppingList.services.restaurant_details_fetch_service import apply_restaurant_information_scan
from PushShoppingList.services.restaurant_details_fetch_service import load_pending_restaurant_scan
from PushShoppingList.services.restaurant_details_fetch_service import scan_restaurant_information
from PushShoppingList.services.restaurant_details_fetch_service import store_pending_restaurant_scan
from PushShoppingList.services.restaurant_recipe_duplicate_service import commit_restaurant_recipe_delete
from PushShoppingList.services.restaurant_recipe_duplicate_service import commit_restaurant_recipe_merge
from PushShoppingList.services.restaurant_recipe_duplicate_service import decorate_restaurant_usage_with_duplicates
from PushShoppingList.services.restaurant_recipe_duplicate_service import restaurant_recipe_delete_preview
from PushShoppingList.services.restaurant_recipe_duplicate_service import restaurant_recipe_duplicate_group_detail
from PushShoppingList.services.restaurant_recipe_duplicate_service import restaurant_recipe_merge_preview
from PushShoppingList.services.restaurant_recipe_duplicate_service import set_restaurant_recipe_duplicate_disposition
from PushShoppingList.services.cookbook_item_inference_service import infer_missing_details_for_recipe
from PushShoppingList.services.cookbook_item_inference_service import regenerate_ingredients_for_recipe
from PushShoppingList.services.cookbook_item_inference_service import regenerate_recipe_notes_for_recipe
from PushShoppingList.services.recipe_image_progress_service import load_recipe_image_progress
from PushShoppingList.services.recipe_ingredient_service import remove_recipe_and_unused_ingredients
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipe
from PushShoppingList.services.recipe_master_data_service import sync_recipe_master_records
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
from PushShoppingList.services.guest_session_service import is_guest_session
from PushShoppingList.services.image_variant_service import ensure_webp_variant
from PushShoppingList.services.image_variant_service import generated_static_cache_seconds
from PushShoppingList.services.image_variant_service import image_mimetype_for_path
from PushShoppingList.services.job_queue_service import enqueue_job
from PushShoppingList.services.job_queue_service import inline_jobs_enabled
from PushShoppingList.services.job_queue_service import queue_name_for_job
from PushShoppingList.services.job_service import active_limit_for_job
from PushShoppingList.services.job_service import active_limit_wait_message
from PushShoppingList.services.job_service import create_job
from PushShoppingList.services.job_service import get_job
from PushShoppingList.services.job_service import job_for_client
from PushShoppingList.services.job_service import job_limit_key
from PushShoppingList.services.job_service import owner_job_count_for_limit_key
from PushShoppingList.services.job_service import queued_limit_status
from PushShoppingList.services.job_service import update_job
from PushShoppingList.services.menu_mega_json_service import default_nutrition_inference
from PushShoppingList.services.menu_mega_json_service import default_pdf_generation
from PushShoppingList.services.menu_mega_json_service import default_recipe_inference
from PushShoppingList.services.menu_mega_json_service import load_menu_mega_json_snapshot
from PushShoppingList.services.menu_mega_json_service import NUTRITION_INFERENCE_FIELDS
from PushShoppingList.services.menu_mega_json_service import unpack_mega_menu_json_to_sections
from PushShoppingList.services.openai_usage_service import openai_usage_dashboard_for_user
from PushShoppingList.services.openai_usage_service import record_app_activity
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_model_service import model_value_for_env as active_model_value_for_env
from PushShoppingList.services.storage_service import active_guest_session_id
from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.storage_service import workspace_data_root
from PushShoppingList.services.user_account_service import current_user
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import is_admin_user

recipe_bp = Blueprint("recipe_bp", __name__)

NO_INGREDIENTS_ERROR = "No ingredients were found for this recipe URL."
IMPORT_LOGIN_ERROR = "Sign in before importing recipes so imported data is saved to your account."
MENU_IMPORT_ADMIN_ERROR = "Menu import is admin-only. Sign in with an admin account to use menu extraction."
FOOD_REVIEW_LOGIN_ERROR = "Sign in before using food reviews so results stay tied to your account."
IMPORT_CATEGORY_STATUS_MESSAGE = "Import complete. Generating ChatGPT categories..."
IMAGE_RECIPE_WORKFLOW_STATES = {}


def active_openai_model(env_var, default_model=""):
    model, _source = active_model_value_for_env(env_var, default_model)
    return model or default_model


def static_asset_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except OSError:
        return 1


def recipe_edit_cookbook_view():
    view = cookbook_view([])

    for cookbook in view.get("cookbooks", []):
        cookbook["recipes"] = []
        cookbook["menu_sections"] = {}

    view["recipes"] = []
    return view


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
        return bool(calories and (serving_basis or "per serving"))

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

        return bool(calories and (serving_basis or "per serving"))

    return False


def _recipe_with_default_serving_basis(recipe):
    recipe = dict(recipe) if isinstance(recipe, dict) else {}
    nutrition = recipe.get("nutrition")

    if isinstance(nutrition, dict):
        nutrition = dict(nutrition)
        if _extract_nutrition_text_value(nutrition.get("calories")) and not _extract_nutrition_text_value(nutrition.get("serving_basis")):
            nutrition["serving_basis"] = "per serving"
        recipe["nutrition"] = nutrition
        return recipe

    if isinstance(nutrition, list):
        rows = [
            dict(item)
            for item in nutrition
            if isinstance(item, dict)
        ]
        has_calories = False
        has_serving_basis = False
        for row in rows:
            key = str(row.get("key") or "").strip().lower()
            value = _extract_nutrition_text_value(row.get("value"))
            if key == "calories" and value:
                has_calories = True
            elif key == "serving_basis" and value:
                has_serving_basis = True
        if has_calories and not has_serving_basis:
            rows.insert(0, {"key": "serving_basis", "value": "per serving"})
        recipe["nutrition"] = rows
        return recipe

    return recipe


def _nutrition_rows_from_value(nutrition):
    if isinstance(nutrition, list):
        return [
            {"key": str(item.get("key") or ""), "value": str(item.get("value") or "")}
            for item in nutrition
            if isinstance(item, dict) and str(item.get("key") or "").strip()
        ]

    if isinstance(nutrition, dict):
        rows = []
        for key, value in nutrition.items():
            if key == "other" and isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("key") or "").strip()
                    item_value = str(item.get("value") or "").strip()
                    if name or item_value:
                        rows.append({"key": name or "other", "value": item_value})
                continue
            if str(value or "").strip():
                rows.append({"key": str(key), "value": str(value)})
        return rows

    return []


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _nutrition_row_value(rows, key):
    key = str(key or "").strip().lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("key") or "").strip().lower() == key:
            return str(row.get("value") or "").strip()
    return ""


def _nutrition_row_value_any(rows, *keys):
    for key in keys:
        value = _nutrition_row_value(rows, key)
        if value:
            return value
    return ""


def _nutrition_number(value):
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _menu_nutrition_inference_from_rows(rows, model=""):
    rows = rows if isinstance(rows, list) else []
    field_values = {
        "serving_basis": _nutrition_row_value(rows, "serving_basis") or None,
        "calories": _nutrition_row_value(rows, "calories") or None,
        "carbohydrates": _nutrition_row_value_any(rows, "carbohydrates", "carbs") or None,
        "protein": _nutrition_row_value(rows, "protein") or None,
        "fat": _nutrition_row_value(rows, "fat") or None,
        "saturated_fat": _nutrition_row_value(rows, "saturated_fat") or None,
        "polyunsaturated_fat": _nutrition_row_value(rows, "polyunsaturated_fat") or None,
        "monounsaturated_fat": _nutrition_row_value(rows, "monounsaturated_fat") or None,
        "trans_fat": _nutrition_row_value(rows, "trans_fat") or None,
        "cholesterol": _nutrition_row_value(rows, "cholesterol") or None,
        "sodium": _nutrition_row_value(rows, "sodium") or None,
        "potassium": _nutrition_row_value(rows, "potassium") or None,
        "fiber": _nutrition_row_value(rows, "fiber") or None,
        "sugar": _nutrition_row_value(rows, "sugar") or None,
        "vitamin_a": _nutrition_row_value(rows, "vitamin_a") or None,
        "vitamin_c": _nutrition_row_value(rows, "vitamin_c") or None,
        "calcium": _nutrition_row_value(rows, "calcium") or None,
        "iron": _nutrition_row_value(rows, "iron") or None,
    }
    known_keys = set(NUTRITION_INFERENCE_FIELDS) | {"carbs"}
    other = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        value = str(row.get("value") or "").strip()
        if key and value and key.lower() not in known_keys:
            other.append({"name": key, "value": value})

    return {
        **default_nutrition_inference(),
        "status": "generated",
        **field_values,
        "other": other,
        "servings": field_values["serving_basis"],
        "calories_per_serving": _nutrition_number(field_values["calories"]),
        "protein_g": _nutrition_number(field_values["protein"]),
        "carbs_g": _nutrition_number(field_values["carbohydrates"]),
        "fat_g": _nutrition_number(field_values["fat"]),
        "sodium_mg": _nutrition_number(field_values["sodium"]),
        "model": str(model or active_openai_model("OPENAI_NUTRITION_MODEL", MODEL)),
        "generated_at": _utc_now_iso(),
        "notes": ["Estimated per serving basis was generated lazily."],
    }


def _menu_pdf_generation_from_result(existing, result):
    existing = existing if isinstance(existing, dict) else {}
    result = result if isinstance(result, dict) else {}
    generated_pdf_path = str(
        result.get("generated_pdf_path")
        or result.get("generated_recipe_pdf_path")
        or result.get("pdf_path")
        or existing.get("generated_pdf_path")
        or ""
    ).strip()
    generated_cloudflare_pdf_path = str(
        result.get("generated_cloudflare_pdf_path")
        or result.get("generated_cloudflare_pdf_url")
        or result.get("generated_recipe_pdf_url")
        or result.get("pdf_public_url")
        or result.get("public_url")
        or existing.get("generated_cloudflare_pdf_path")
        or ""
    ).strip()
    return {
        **default_pdf_generation(),
        **existing,
        "status": "generated" if result.get("ok") else existing.get("status", "not_generated"),
        "generated_pdf_path": generated_pdf_path,
        "generated_cloudflare_pdf_path": generated_cloudflare_pdf_path,
        "generated_at": _utc_now_iso() if result.get("ok") else existing.get("generated_at"),
    }


def _existing_nutrition_success(recipe, recipe_url=""):
    recipe = _recipe_with_default_serving_basis(recipe)
    nutrition = recipe.get("nutrition")
    rows = _nutrition_rows_from_value(nutrition)
    return {
        "ok": True,
        "success": True,
        "already_complete": True,
        "nutrition": rows,
        "recipe_json": recipe,
        "recipe_url": recipe_url,
        "error": "",
    }


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
        normalized_recipe = _recipe_with_default_serving_basis(recipe_payload)
        if normalized_recipe != recipe_payload:
            try:
                save_editable_recipe(url, normalized_recipe)
                print(f"[recipe_pdf] action=default_serving_basis_saved url={url}")
            except Exception as exc:
                print(f"[recipe_pdf] action=default_serving_basis_save_failed url={url} error={exc}")
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


def ensure_uploaded_recipe_nutrition_estimate(recipe_url):
    recipe_url = str(recipe_url or "").strip()

    if not _is_uploaded_recipe_url(recipe_url):
        return {
            "ok": True,
            "estimated": False,
            "recipe_url": recipe_url,
        }

    if _is_uploaded_recipe_nutrition_complete(recipe_url):
        return {
            "ok": True,
            "estimated": False,
            "already_complete": True,
            "recipe_url": recipe_url,
        }

    loaded_recipe = load_editable_recipe(recipe_url) or {}
    recipe_payload = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
    recipe_payload = recipe_payload if isinstance(recipe_payload, dict) else {}

    if not recipe_payload:
        _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
        return {
            "ok": False,
            "error": "Recipe payload is required before estimating nutrition.",
            "recipe_url": recipe_url,
        }

    estimate_result = estimate_recipe_nutrition(recipe_payload)
    if not estimate_result.get("ok"):
        _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
        return {
            **estimate_result,
            "ok": False,
            "recipe_url": recipe_url,
        }

    updated_recipe = {
        **recipe_payload,
        "nutrition": estimate_result.get("nutrition", []),
        "nutrition_inference": _menu_nutrition_inference_from_rows(
            estimate_result.get("nutrition", []),
            model=str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL)),
        ),
    }
    with workspace_write_lock("recipe-imports"):
        save_result = save_editable_recipe(recipe_url, updated_recipe)
    if not save_result.get("ok"):
        _mark_uploaded_recipe_nutrition_estimated(recipe_url, False)
        return {
            "ok": False,
            "error": save_result.get("error") or "Unable to save estimated nutrition.",
            "recipe_url": recipe_url,
            "recipe_json": updated_recipe,
        }

    _mark_uploaded_recipe_nutrition_estimated(recipe_url, _has_per_serving_estimate(updated_recipe.get("nutrition")))
    return {
        **estimate_result,
        "ok": True,
        "estimated": True,
        "recipe_url": recipe_url,
        "recipe_json": updated_recipe,
    }


def create_recipe_pdf_from_url(recipe_url):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "ok": False,
            "error": "Recipe URL is required.",
        }

    if not _is_uploaded_recipe_nutrition_complete(recipe_url):
        estimate_result = ensure_uploaded_recipe_nutrition_estimate(recipe_url)
        if not estimate_result.get("ok"):
            return {
                **estimate_result,
                "ok": False,
                "error": (
                    estimate_result.get("error")
                    or "Estimate per serving basis is required before creating the recipe PDF."
                ),
                "success": False,
            }

    if not _is_uploaded_recipe_nutrition_complete(recipe_url):
        return {
            "ok": False,
            "error": "Estimate per serving basis is required before creating the recipe PDF.",
            "success": False,
        }

    result = create_editable_recipe_pdf(recipe_url)
    if result.get("ok"):
        try:
            loaded_recipe = load_editable_recipe(recipe_url) or {}
            recipe_payload = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
            recipe_payload = recipe_payload if isinstance(recipe_payload, dict) else {}
            if recipe_payload:
                updated_recipe = {
                    **recipe_payload,
                    "pdf_generation": _menu_pdf_generation_from_result(
                        recipe_payload.get("pdf_generation"),
                        result,
                    ),
                }
                save_result = save_editable_recipe(recipe_url, updated_recipe)
                if save_result.get("ok"):
                    result["recipe_json"] = updated_recipe
                else:
                    result["pdf_generation_warning"] = save_result.get("error") or "Unable to save PDF generation status."
        except Exception as exc:
            result["pdf_generation_warning"] = str(exc)
    return result


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

    payload = {
        "url": recipe_url,
        "recipe_url": recipe_url,
        "context": context,
        "upload_to_cloudflare": True,
    }
    job, queue_result, error_message = start_import_background_job(
        "create-recipe-pdf",
        payload,
        total_items=1,
    )

    return {
        "queued": not bool(error_message),
        "url": recipe_url,
        "job_id": (job or {}).get("id", ""),
        "queue": {
            key: value
            for key, value in (queue_result or {}).items()
            if key != "details"
        },
        "error": error_message,
    }


def _menu_progress(progress_callback, message, summary=""):
    if progress_callback:
        progress_callback(message, summary)


def _menu_recipe_text_value(value):
    if value is None:
        return ""

    if isinstance(value, dict):
        return str(
            value.get("name")
            or value.get("ingredient")
            or value.get("text")
            or value.get("instruction")
            or value.get("key")
            or value.get("value")
            or ""
        ).strip()

    return str(value or "").strip()


def _menu_recipe_has_content(value):
    if isinstance(value, list):
        return any(_menu_recipe_text_value(item) for item in value)

    if isinstance(value, dict):
        return any(_menu_recipe_has_content(item) for item in value.values())

    return bool(_menu_recipe_text_value(value))


def _menu_recipe_food_review_status(recipe_result):
    ingredients = recipe_result.get("ingredients") if isinstance(recipe_result.get("ingredients"), list) else []
    matched_rules = []

    try:
        rules = load_food_rules()
    except Exception:
        rules = None

    for ingredient in ingredients:
        text = _menu_recipe_text_value(ingredient)
        if not text:
            continue

        status = shopping_item_food_rule_status(text, rules)
        if status.get("needs_review"):
            matched_rules.extend(status.get("blocked_by") or [])
            matched_rules.extend(status.get("missing_required") or [])

    unique_rules = sorted({str(rule) for rule in matched_rules if str(rule).strip()})
    return {
        "applied": bool(unique_rules),
        "count": len(unique_rules),
        "rules": unique_rules,
    }


def menu_recipe_progress_payload(recipe_result, recipe_url=""):
    recipe_result = recipe_result if isinstance(recipe_result, dict) else {}
    recipe_url = str(
        recipe_url
        or recipe_result.get("source_url")
        or recipe_result.get("recipe_url")
        or recipe_result.get("url")
        or ""
    ).strip()
    recipe_name = str(
        recipe_result.get("display_name")
        or recipe_result.get("recipe_title")
        or recipe_result.get("menu_item_name")
        or "Menu Recipe"
    ).strip()
    menu_section = str(recipe_result.get("menu_section") or "").strip()
    description = str(
        recipe_result.get("menu_description")
        or recipe_result.get("description")
        or recipe_result.get("extracted_description")
        or ""
    ).strip()
    food_review = _menu_recipe_food_review_status(recipe_result)
    checklist = {
        "recipe_extracted": bool(recipe_result.get("ok") and recipe_url),
        "recipe_information": bool(recipe_name),
        "ingredients": _menu_recipe_has_content(recipe_result.get("ingredients")),
        "equipment": _menu_recipe_has_content(recipe_result.get("equipment")),
        "instructions": _menu_recipe_has_content(recipe_result.get("instructions")),
        "nutrition": _menu_recipe_has_content(recipe_result.get("nutrition")),
        "food_review_applied": bool(food_review["applied"]),
        "estimate_per_serving": False,
    }
    running = {
        key: False
        for key in checklist
    }
    messages = {
        "estimate_per_serving": "Ready to run",
    }

    if food_review["applied"]:
        messages["food_review_applied"] = (
            f"Applied - {food_review['count']} matching rule"
            f"{'' if food_review['count'] == 1 else 's'}"
        )
    else:
        messages["food_review_applied"] = "Skipped - no matching rule"

    return {
        "recipe_id": normalize_recipe_url_key(recipe_url) or recipe_url,
        "recipe_url": recipe_url,
        "recipe_name": recipe_name,
        "menu_section": menu_section,
        "menu_price": str(recipe_result.get("menu_price") or "").strip(),
        "menu_description": description,
        "extracted_description": description,
        "checklist": checklist,
        "running": running,
        "messages": messages,
        "errors": {},
    }


def ensure_menu_recipe_serving_basis_estimate(recipe_url, recipe_result):
    recipe_url = str(recipe_url or "").strip()
    recipe_payload = (
        recipe_result.get("raw")
        if isinstance(recipe_result, dict) and isinstance(recipe_result.get("raw"), dict)
        else {}
    )

    if not recipe_payload:
        try:
            loaded_recipe = load_editable_recipe(recipe_url) or {}
            recipe_payload = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        except Exception:
            recipe_payload = {}

    recipe_payload = recipe_payload if isinstance(recipe_payload, dict) else {}

    if not recipe_payload:
        return {
            "ok": False,
            "recipe_url": recipe_url,
            "error": "Recipe payload is required before estimating serving basis.",
        }

    if _has_per_serving_estimate(recipe_payload.get("nutrition")):
        return {
            "ok": True,
            "recipe_url": recipe_url,
            "already_complete": True,
        }

    estimate_result = estimate_recipe_nutrition(recipe_payload)
    if not estimate_result.get("ok"):
        return {
            **estimate_result,
            "ok": False,
            "recipe_url": recipe_url,
        }

    updated_recipe = {
        **recipe_payload,
        "nutrition": estimate_result.get("nutrition", []),
        "nutrition_inference": _menu_nutrition_inference_from_rows(
            estimate_result.get("nutrition", []),
            model=str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL)),
        ),
    }
    with workspace_write_lock("recipe-imports"):
        save_result = save_editable_recipe(recipe_url, updated_recipe)
    if not save_result.get("ok"):
        return {
            "ok": False,
            "recipe_url": recipe_url,
            "error": save_result.get("error") or "Unable to save estimated serving basis.",
            "recipe_json": updated_recipe,
        }

    if isinstance(recipe_result, dict):
        recipe_result["raw"] = updated_recipe
        recipe_result["nutrition"] = updated_recipe.get("nutrition", [])

    return {
        **estimate_result,
        "ok": True,
        "estimated": True,
        "recipe_url": recipe_url,
        "recipe_json": updated_recipe,
    }


def menu_import_result_is_stub(recipe_result):
    recipe_result = recipe_result if isinstance(recipe_result, dict) else {}
    source_type = str(recipe_result.get("source_type") or "").strip().lower()
    raw = recipe_result.get("raw") if isinstance(recipe_result.get("raw"), dict) else {}
    return bool(
        source_type == "menu_item_stub"
        or str(raw.get("source_type") or "").strip().lower() == "menu_item_stub"
        or recipe_result.get("needs_ai_recipe")
        or raw.get("needs_ai_recipe")
        or str(recipe_result.get("recipe_status") or raw.get("recipe_status") or "").strip().lower() == "stub"
    )


def menu_stub_recipe_payload(recipe_result, recipe_url, cookbook):
    recipe_result = recipe_result if isinstance(recipe_result, dict) else {}
    raw = recipe_result.get("raw") if isinstance(recipe_result.get("raw"), dict) else {}
    payload = {
        **recipe_result,
        **raw,
    }
    cookbook = cookbook if isinstance(cookbook, dict) else {}
    payload.update({
        "source_url": recipe_url,
        "recipe_record_url": recipe_url,
        "source_type": "menu_item_inferred",
        "source_import_type": "menu_url_import",
        "ai_inferred": True,
        "needs_ai_recipe": True,
        "recipe_status": "stub",
        "import_status": "imported_basic",
        "basic_import_status": "imported_basic",
        "cookbook_id": cookbook.get("id", ""),
        "cookbook_name": cookbook.get("name", ""),
    })
    payload.setdefault("ingredients", [])
    payload.setdefault("equipment", [])
    payload.setdefault("instructions", [])
    payload.setdefault("nutrition", {})
    payload["recipe_inference"] = {
        **default_recipe_inference(),
        **(payload.get("recipe_inference") if isinstance(payload.get("recipe_inference"), dict) else {}),
    }
    payload["nutrition_inference"] = {
        **default_nutrition_inference(),
        **(payload.get("nutrition_inference") if isinstance(payload.get("nutrition_inference"), dict) else {}),
    }
    payload["pdf_generation"] = {
        **default_pdf_generation(),
        **(payload.get("pdf_generation") if isinstance(payload.get("pdf_generation"), dict) else {}),
    }
    payload.setdefault("recipe_title", recipe_result.get("recipe_title") or recipe_result.get("display_name") or recipe_url)
    payload.setdefault("display_name", payload.get("recipe_title") or recipe_url)
    return payload


def require_account_for_import(wants_json=False):
    """Keep recipe imports bound to signed-in, session, or temporary demo storage."""
    if current_user() or active_user_id() or is_guest_session():
        return None

    if wants_json:
        return jsonify({"ok": False, "error": IMPORT_LOGIN_ERROR}), 401

    flash(IMPORT_LOGIN_ERROR, "error")
    return redirect("/#userAccountSection")


def require_admin_for_menu_import(wants_json=False):
    """Restrict expensive menu extraction controls to admin accounts."""
    if is_admin_user(current_user()):
        return None

    if wants_json:
        return jsonify({"ok": False, "error": MENU_IMPORT_ADMIN_ERROR}), 403

    flash(MENU_IMPORT_ADMIN_ERROR, "error")
    return redirect("/#enterRecipeLinks")


def require_account_for_food_review():
    """Food-review alternatives use workspace-specific food rules and saved recipe data."""
    if current_user() or is_guest_session():
        return None

    return jsonify({"ok": False, "error": FOOD_REVIEW_LOGIN_ERROR}), 401


def wants_fetch_json_response():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    )


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


def import_recipe_text_value(recipe_metadata, *field_names):
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}

    for field_name in field_names:
        value = str(recipe_metadata.get(field_name) or "").strip()
        if value:
            return value

    return ""


def import_recipe_record(url, recipe_metadata=None):
    recipe_metadata = recipe_metadata if isinstance(recipe_metadata, dict) else {}
    title = import_recipe_title(recipe_metadata, url)
    menu_section = import_recipe_text_value(
        recipe_metadata,
        "menu_section",
        "section_name",
        "restaurant_menu_category",
    ) or MISCELLANEOUS_MENU_SECTION

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
        "menu_section": menu_section,
        "section_name": menu_section,
        "menu_section_id": import_recipe_text_value(recipe_metadata, "menu_section_id", "section_id"),
        "menu_item_id": import_recipe_text_value(recipe_metadata, "menu_item_id", "item_id"),
        "restaurant_id": import_recipe_text_value(recipe_metadata, "restaurant_id"),
        "menu_id": import_recipe_text_value(recipe_metadata, "menu_id"),
        "menu_item_name": import_recipe_text_value(
            recipe_metadata,
            "menu_item_name",
            "item_name",
            "display_name",
            "recipe_title",
        ),
        "item_name": import_recipe_text_value(
            recipe_metadata,
            "item_name",
            "menu_item_name",
            "display_name",
            "recipe_title",
        ),
        "menu_order_url": import_recipe_text_value(recipe_metadata, "menu_order_url", "deep_link_url"),
        "deep_link_url": import_recipe_text_value(recipe_metadata, "deep_link_url", "menu_order_url"),
        "menu_description": import_recipe_text_value(
            recipe_metadata,
            "menu_description",
            "item_description",
            "description",
            "summary",
        ),
        "menu_price": import_recipe_text_value(recipe_metadata, "menu_price", "price", "price_text"),
        "parent_menu_snapshot_id": import_recipe_text_value(recipe_metadata, "parent_menu_snapshot_id", "menu_mega_snapshot_id"),
        "menu_mega_snapshot_id": import_recipe_text_value(recipe_metadata, "menu_mega_snapshot_id", "parent_menu_snapshot_id"),
        "source_type": import_recipe_text_value(recipe_metadata, "source_type"),
        "source_import_type": import_recipe_text_value(recipe_metadata, "source_import_type"),
        "ai_inferred": bool(recipe_metadata.get("ai_inferred")),
        "needs_ai_recipe": bool(recipe_metadata.get("needs_ai_recipe")),
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


def import_request_is_menu_extract(source):
    mode = str(
        (source or {}).get("extraction_mode")
        or (source or {}).get("import_mode")
        or (source or {}).get("mode")
        or ""
    ).strip().lower()
    return mode in {"menu", "menu_extract", "menu-extract"}


def apply_imported_recipe_category_routine(
    url,
    recipe_metadata,
    assignment,
    trigger_source="recipe_import:all",
    overwrite_existing_categories=False,
):
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

    stored_record = cookbook_recipe_record_for_url(url)
    stored_metadata = stored_category_metadata(stored_record)
    if (
        not overwrite_existing_categories
        and category_metadata_has_values(stored_metadata)
    ):
        print(
            "[recipe_import_category] action=skipped "
            f"title={title} url={url} reason=existing_cookbook_categories"
        )
        return {
            "ok": True,
            "title": title,
            "status": "skipped_existing_categories",
            "skipped": True,
            "reason": "existing_cookbook_categories",
            "message": "Saved cookbook categories already exist; kept existing categories.",
        }

    print(
        "[recipe_import_category] action=started "
        f"title={title} url={url} cookbook_id={cookbook_id}"
    )

    decision = decide_recipe_categories_with_chatgpt(
        category_input,
        mode="all",
        current_categories={},
        trigger_source=trigger_source or "recipe_import:all",
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
            confirm_overwrite=overwrite_existing_categories,
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
    except CookbookCategoryOverwriteConflict:
        print(
            "[recipe_import_category] action=skipped "
            f"title={title} url={url} reason=existing_cookbook_categories"
        )
        return {
            "ok": True,
            "title": title,
            "status": "skipped_existing_categories",
            "skipped": True,
            "reason": "existing_cookbook_categories",
            "message": "Saved cookbook categories already exist; kept existing categories.",
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


def start_import_background_job(job_type, payload, total_items=0):
    payload = payload if isinstance(payload, dict) else {}
    user_id = active_user_id()
    guest_session_id = active_guest_session_id()
    queue_name = queue_name_for_job(job_type, payload)
    queued_status = queued_limit_status(
        user_id=user_id,
        guest_session_id=guest_session_id,
        job_type=job_type,
        input_payload=payload,
    )
    if not queued_status.get("ok"):
        return None, None, queued_status.get("message") or "Too many queued import jobs."

    limit_key = job_limit_key(job_type, payload)
    active_limit = active_limit_for_job(job_type, payload)
    active_count = owner_job_count_for_limit_key(
        user_id=user_id,
        guest_session_id=guest_session_id,
        limit_key=limit_key,
        statuses=["running"],
    ) if active_limit else 0

    job = create_job(
        job_type,
        input_payload=payload,
        user_id=user_id,
        guest_session_id=guest_session_id,
        total_items=total_items,
        queue_name=queue_name,
    )
    if active_limit and active_count >= active_limit:
        job = update_job(job["id"], current_step=active_limit_wait_message(limit_key), queue_name=queue_name) or job

    queue_result = enqueue_job(job["id"], queue_name_override=queue_name)
    job = get_job(job["id"]) or job
    if not queue_result.get("ok"):
        return job, queue_result, queue_result.get("error") or "Unable to queue import job."
    return job, queue_result, ""


def import_job_json_response(job, queue_result, error_message="", accepted_status=202):
    job_payload = job_for_client(job) if job else None
    body = {
        "ok": not bool(error_message),
        "accepted": not bool(error_message),
        "queued": bool(job and not error_message),
        "job_id": (job or {}).get("id", ""),
        "job": job_payload,
        "queue": {
            key: value
            for key, value in (queue_result or {}).items()
            if key != "details"
        },
    }
    if error_message:
        body["error"] = error_message
    return jsonify(with_openai_usage_dashboard(body)), accepted_status if not error_message else 503


def save_legacy_job_upload(uploaded_file):
    filename = secure_filename(uploaded_file.filename or "upload")
    suffix = Path(filename).suffix
    staging_dir = workspace_data_root() / "job_uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / f"{uuid4().hex}_{filename or ('upload' + suffix)}"
    uploaded_file.save(path)
    return path


@recipe_bp.route("/extract_recipe", methods=["POST"])
def extract_recipe_route():
    account_response = require_account_for_import()
    if account_response:
        return account_response

    recipe_urls = request.form.get("recipe_urls", "")
    menu_extract = import_request_is_menu_extract(request.form)

    urls = [
        line.strip()
        for line in recipe_urls.splitlines()
        if line.strip()
    ]

    if not urls:
        flash("Paste at least one recipe or menu URL before importing.")
        return redirect("/")

    cookbook = selected_import_cookbook_from_form(request.form)
    log_selected_import_cookbook("form-url", cookbook)
    payload = {
        "urls": urls,
        "extraction_mode": "menu_extract" if menu_extract else "recipe",
        "cookbook_id": cookbook.get("id", "") if isinstance(cookbook, dict) else "",
        "cookbook_name": cookbook.get("name", "") if isinstance(cookbook, dict) else "",
        "model_used": resolve_menu_cleanup_model() if menu_extract else MODEL,
        "model_source": resolve_menu_cleanup_model_source() if menu_extract else "recipe",
        "model_env_var": "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
        "model_env_var_used": "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
    }
    job_type = "menu-import" if menu_extract else "recipe-import"
    job, queue_result, error_message = start_import_background_job(job_type, payload, total_items=len(urls))
    if error_message:
        flash(error_message)
    else:
        flash(
            "Menu import queued. Watch Job Activity for progress."
            if menu_extract
            else "Recipe import queued. Watch Job Activity for progress."
        )
    return redirect("/")

    extracted_any = False

    for index, url in enumerate(urls):
        if is_cancel_requested(job_id):
            break

        mark_url_running(job_id, urls, index)
        try:
            progress_callback = lambda message, summary=None, idx=index: mark_url_message(
                job_id,
                urls,
                idx,
                message,
                summary,
            )
            if menu_extract:
                result = extract_menu_recipes_from_url(
                    url,
                    progress_callback=progress_callback,
                )
            else:
                result = extract_recipe_from_url(
                    url,
                    progress_callback=progress_callback,
                )
        except Exception as exc:
            mark_url_failed(job_id, urls, index, str(exc))
            continue

        if is_cancel_requested(job_id):
            break

        try:
            if menu_extract:
                if not result.get("ok"):
                    mark_url_failed(job_id, urls, index, result.get("error") or "Menu extraction failed.")
                    continue

                mark_url_message(
                    job_id,
                    urls,
                    index,
                    IMPORT_CATEGORY_STATUS_MESSAGE,
                    summary="Generating categories for new menu item recipes.",
                )
                committed = commit_menu_import_result(
                    result,
                    cookbook,
                    context="form-menu-url",
                    progress_callback=progress_callback,
                    menu_recipe_progress_callback=lambda recipes, idx=index: set_url_menu_recipes(
                        job_id,
                        urls,
                        idx,
                        recipes,
                        message="Updating menu recipe checklist",
                        summary="Saving inferred menu item recipes.",
                    ),
                )
                if committed.get("ok"):
                    extracted_any = True
                    if committed.get("partial_failure"):
                        mark_url_failed(job_id, urls, index, committed.get("error") or "Some menu items failed.")
                    else:
                        mark_url_done(job_id, urls, index, committed.get("created_count", 0))
                else:
                    mark_url_failed(job_id, urls, index, committed.get("error") or "No menu item recipes were created.")
                continue

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

    manual_description = str(
        request.form.get("photo_description")
        or request.form.get("recipe_description")
        or ""
    ).strip()
    upload_mode = str(request.form.get("upload_mode") or "").strip().lower()
    menu_extract = import_request_is_menu_extract(request.form)
    if menu_extract:
        admin_response = require_admin_for_menu_import(wants_json=wants_json)
        if admin_response:
            return admin_response

    normalized_upload_mode = upload_mode if upload_mode in {
        "auto",
        "read",
        "read_text",
        "vision",
        "manual",
        "manual_description",
        "retry",
    } else "auto"
    if normalized_upload_mode in {"read", "retry"}:
        normalized_upload_mode = "read_text"
    if normalized_upload_mode == "manual":
        normalized_upload_mode = "manual_description"
    upload_action = {
        "vision": "generate_recipe_from_image",
        "manual_description": "describe_recipe",
    }.get(normalized_upload_mode, "read_text")

    uploaded_file = request.files.get("recipe_media")

    if not uploaded_file or not uploaded_file.filename:
        if wants_json:
            message = "No file was selected."
            return jsonify({
                "ok": False,
                "success": False,
                "error": message,
                "error_code": "NO_FILE_SELECTED",
                "error_message": message,
                "technical_message": message,
                "model": resolve_vision_model() if upload_action != "read_text" else MODEL,
                "model_used": resolve_vision_model() if upload_action != "read_text" else MODEL,
                "action": upload_action,
            }), 400

        return redirect("/")

    cookbook = selected_import_cookbook_from_form(request.form)
    log_selected_import_cookbook("media-menu-upload" if menu_extract else "media-upload", cookbook)
    source_path = save_legacy_job_upload(uploaded_file)
    payload = {
        "source_path": str(source_path),
        "filename": uploaded_file.filename,
        "content_type": uploaded_file.content_type or "",
        "import_mode": "menu_extract" if menu_extract else "recipe",
        "extraction_mode": "menu_extract" if menu_extract else "recipe",
        "upload_mode": normalized_upload_mode,
        "manual_description": manual_description,
        "cookbook_id": cookbook.get("id", "") if isinstance(cookbook, dict) else "",
        "cookbook_name": cookbook.get("name", "") if isinstance(cookbook, dict) else "",
    }
    if menu_extract:
        payload.update({
            "model_used": resolve_menu_model(),
            "model_source": resolve_menu_model_source(),
            "model_env_var": "OPENAI_MENU_MODEL",
            "model_env_var_used": "OPENAI_MENU_MODEL",
        })
    elif normalized_upload_mode in {"vision", "manual_description"} or str(uploaded_file.content_type or "").lower().startswith("image/"):
        payload.update({
            "model_used": resolve_vision_model(),
            "model_source": resolve_vision_model_source(),
            "model_env_var": "OPENAI_VISION_MODEL",
            "model_env_var_used": "OPENAI_VISION_MODEL",
        })
    else:
        payload.update({
            "model_used": MODEL,
            "model_source": "recipe",
            "model_env_var": "OPENAI_RECIPE_MODEL",
            "model_env_var_used": "OPENAI_RECIPE_MODEL",
        })

    job, queue_result, error_message = start_import_background_job("doc-photo-import", payload, total_items=1)
    if wants_json:
        return import_job_json_response(job, queue_result, error_message)
    if error_message:
        flash(error_message)
    else:
        flash(
            "Menu file import queued. Watch Job Activity for progress."
            if menu_extract
            else "Recipe media import queued. Watch Job Activity for progress."
        )
    return redirect("/")

    if menu_extract:
        result = extract_menu_recipes_from_upload(uploaded_file)
        if result.get("ok"):
            result = commit_menu_import_result(
                result,
                cookbook,
                context="media-menu-upload",
            )
        if isinstance(result, dict):
            result.setdefault("success", bool(result.get("ok")))
            result.setdefault("menu_extract", True)
            result.setdefault("extraction_method", "menu_extract")
            result.setdefault("extraction_mode", "menu_extract")
            result.setdefault("extraction_mode_label", "Menu Extract")
            result.setdefault("model_used", result.get("model") or resolve_menu_model())
            result.setdefault("model_source", result.get("model_source") or resolve_menu_model_source())

        if wants_json:
            status = 200 if result.get("ok") else 400
            return jsonify(result), status

        return redirect("/")

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

    if not result.get("read_text_only"):
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
        result.setdefault(
            "model_source",
            resolve_vision_model_source() if str(result.get("source_type") or "").lower() == "image" else "recipe",
        )
        if "debug" not in result:
            result["debug"] = {
                "model": resolve_vision_model() if str(result.get("source_type") or "").lower() == "image" else MODEL,
                "model_source": resolve_vision_model_source() if str(result.get("source_type") or "").lower() == "image" else "recipe",
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

        status = 200 if result.get("ok") or result.get("read_text_only") else 400
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
            if context == "media-upload":
                pdf_job = schedule_generated_recipe_pdf_creation(recipe_url, context="media-upload")
            else:
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


def commit_menu_import_result(
    result,
    cookbook,
    context="menu-import",
    progress_callback=None,
    menu_recipe_progress_callback=None,
):
    result = result if isinstance(result, dict) else {}
    recipes = result.get("recipes") if isinstance(result.get("recipes"), list) else []
    existing_keys = {
        normalize_recipe_url_key(url)
        for url in load_recipe_urls()
    }
    committed = []
    newly_created = []
    new_recipe_entries = []
    new_stub_entries = []
    category_statuses = []
    serving_basis_statuses = []
    pdf_statuses = []
    source_pdf_statuses = []
    commit_failures = []
    has_stubs = any(menu_import_result_is_stub(recipe_result) for recipe_result in recipes)
    menu_source_pdf = menu_source_pdf_metadata_from_result(result)

    _menu_progress(
        progress_callback,
        "Saving menu items" if has_stubs else "Predicting ingredients",
        (
            "Saving lightweight menu item stubs without full AI generation."
            if has_stubs
            else "Saving inferred menu item ingredients into the recipe pipeline."
        ),
    )
    if menu_recipe_progress_callback:
        try:
            menu_recipe_progress_callback([
                menu_recipe_progress_payload(recipe_result)
                for recipe_result in recipes
                if isinstance(recipe_result, dict)
            ])
        except Exception as exc:
            print(f"[recipe_import] action=menu_recipe_progress_failed error={exc}")

    for recipe_result in recipes:
        if not isinstance(recipe_result, dict):
            continue

        recipe_url = str(recipe_result.get("source_url") or "").strip()
        apply_menu_source_pdf_metadata(recipe_result, menu_source_pdf)
        ingredients = recipe_result.get("ingredients") if isinstance(recipe_result.get("ingredients"), list) else []
        is_stub = menu_import_result_is_stub(recipe_result)
        if not recipe_url or not recipe_result.get("ok") or (not ingredients and not is_stub):
            commit_failures.append({
                "item_name": recipe_result.get("menu_item_name") or recipe_result.get("recipe_title") or recipe_url,
                "error_code": "MENU_ITEM_COMMIT_SKIPPED",
                "error_message": "Menu item recipe was missing a recipe URL, success flag, or ingredients.",
            })
            continue

        recipe_key = normalize_recipe_url_key(recipe_url)
        is_new_recipe = recipe_key not in existing_keys

        if is_stub:
            recipe_payload = menu_stub_recipe_payload(recipe_result, recipe_url, cookbook)
            apply_menu_source_pdf_metadata(recipe_payload, menu_source_pdf)
            save_extracted_recipe_json(recipe_url, recipe_payload)
            recipe_result = {
                **recipe_result,
                "raw": recipe_payload,
                "source_type": "menu_item_inferred",
                "source_import_type": "menu_url_import",
                "ai_inferred": True,
                "needs_ai_recipe": True,
                "recipe_status": "stub",
                "import_status": "imported_basic",
                "basic_import_status": "imported_basic",
                "ingredients": [],
                "equipment": recipe_payload.get("equipment", []),
                "instructions": recipe_payload.get("instructions", []),
                "nutrition": recipe_payload.get("nutrition", {}),
            }
        else:
            add_items(ingredients)
            save_ingredients_for_recipe(recipe_url, ingredients, recipe_result)
        if is_stub:
            sync_recipe_master_records(recipe_url, recipe_data=recipe_result)

        if recipe_result.get("display_name") or recipe_result.get("recipe_title"):
            save_recipe_url_name(
                recipe_url,
                recipe_result.get("display_name") or recipe_result.get("recipe_title"),
            )

        add_recipe_urls([recipe_url])
        assignment = save_import_cookbook_assignment(recipe_url, recipe_result, cookbook)
        action_name = "menu_item_stub_created" if is_stub else "menu_item_created"
        print(
            f"[recipe_import] action={action_name} "
            f"title={import_recipe_title(recipe_result, recipe_url)} "
            f"url={recipe_url} is_new_recipe={is_new_recipe}"
        )

        if is_new_recipe:
            newly_created.append(recipe_url)
            entry = {
                "url": recipe_url,
                "result": recipe_result,
                "assignment": assignment,
            }
            if is_stub:
                new_stub_entries.append(entry)
            else:
                new_recipe_entries.append(entry)
        else:
            print(
                "[recipe_import_category] action=skipped "
                f"title={import_recipe_title(recipe_result, recipe_url)} "
                f"url={recipe_url} reason=existing_recipe"
            )
            category_statuses.append({
                "ok": False,
                "title": import_recipe_title(recipe_result, recipe_url),
                "status": "skipped_existing_recipe",
                "error": "",
            })

        record_recipe_import_activity(recipe_url, recipe_result, context)
        committed.append(recipe_url)
        existing_keys.add(recipe_key)

    if committed and any(not menu_import_result_is_stub(recipe_result) for recipe_result in recipes):
        sort_ingredients()

    if new_recipe_entries:
        _menu_progress(
            progress_callback,
            "Preparing recipe checklists",
            "Updating menu item recipe completion statuses.",
        )
        for entry in new_recipe_entries:
            serving_basis_statuses.append({
                "ok": False,
                "recipe_url": entry["url"],
                "status": "manual_ready",
                "error": "",
            })

        _menu_progress(
            progress_callback,
            "Generating PDFs",
            "Creating generated recipe PDFs for the new menu item recipes.",
        )
        for entry in new_recipe_entries:
            recipe_url = entry["url"]
            if menu_source_pdf:
                source_pdf_statuses.append({
                    "recipe_url": recipe_url,
                    "shared_source_pdf": True,
                    "ok": bool(menu_source_pdf.get("ok")),
                    "status": menu_source_pdf.get("menu_source_pdf_status", ""),
                    "source_pdf_path": menu_source_pdf.get("source_pdf_path", ""),
                    "source_cloudflare_pdf_url": menu_source_pdf.get("source_cloudflare_pdf_url", ""),
                    "result": menu_source_pdf,
                })
            else:
                source_pdf_statuses.append({
                    "recipe_url": recipe_url,
                    "shared_source_pdf": True,
                    "ok": False,
                    "status": "not_attached",
                    "error": "Menu import did not provide a validated shared Source PDF.",
                })

            _menu_progress(
                progress_callback,
                "Uploading PDFs",
                f"Creating and uploading PDF for {import_recipe_title(entry['result'], recipe_url)}.",
            )
            try:
                pdf_result = run_generated_recipe_pdf_creation(recipe_url, context=context)
            except Exception as exc:
                pdf_result = {
                    "ok": False,
                    "error": str(exc),
                }
            pdf_statuses.append({
                "recipe_url": recipe_url,
                "ok": bool(pdf_result.get("ok")),
                "generated_pdf_path": (
                    pdf_result.get("generated_pdf_path")
                    or pdf_result.get("generated_recipe_pdf_path")
                    or pdf_result.get("pdf_path")
                    or ""
                ),
                "generated_cloudflare_pdf_url": (
                    pdf_result.get("generated_cloudflare_pdf_url")
                    or pdf_result.get("generated_recipe_pdf_url")
                    or pdf_result.get("pdf_public_url")
                    or pdf_result.get("public_url")
                    or ""
                ),
                "error": pdf_result.get("error", ""),
                "result": pdf_result,
            })

        _menu_progress(
            progress_callback,
            "Categorizing new recipes",
            "Running Have ChatGPT Decide All only for newly created menu item recipes.",
        )
        for entry in new_recipe_entries:
            recipe_url = entry["url"]
            category_status = apply_imported_recipe_category_routine(
                recipe_url,
                entry["result"],
                entry["assignment"],
            )
            category_statuses.append(category_status)

    category_success_count = sum(1 for status in category_statuses if status.get("ok"))
    pdf_success_count = sum(1 for status in pdf_statuses if status.get("ok"))
    pdf_upload_count = sum(
        1
        for status in pdf_statuses
        if str(status.get("generated_cloudflare_pdf_url") or "").strip()
    )
    ok = bool(committed)
    item_failures = [
        *(result.get("item_failures") if isinstance(result.get("item_failures"), list) else []),
        *commit_failures,
    ]
    unpacked_item_count = int(result.get("item_records_unpacked") or len(new_stub_entries))
    if new_stub_entries and not new_recipe_entries and result.get("menu_mega_json_saved"):
        category_status_message = (
            "Menu import complete. Created one mega menu JSON snapshot and "
            f"unpacked {unpacked_item_count} menu item"
            f"{'' if unpacked_item_count == 1 else 's'} into lightweight stubs."
        )
    elif new_stub_entries and not new_recipe_entries:
        category_status_message = (
            f"Imported {len(new_stub_entries)} menu item stub"
            f"{'' if len(new_stub_entries) == 1 else 's'}."
        )
    else:
        category_status_message = (
            f"Generated categories for {category_success_count} new menu item recipe"
            f"{'' if category_success_count == 1 else 's'}."
        )
    result = {
        **result,
        "ok": ok,
        "success": ok,
        "menu_extract": True,
        "menu_source_url": (
            menu_source_pdf.get("menu_source_url")
            or result.get("menu_source_url")
            or result.get("source_url")
            or ""
        ),
        "menu_source_pdf_status": (
            menu_source_pdf.get("menu_source_pdf_status")
            or result.get("menu_source_pdf_status")
            or ""
        ),
        "menu_source_pdf_path": (
            menu_source_pdf.get("menu_source_pdf_path")
            or result.get("menu_source_pdf_path")
            or ""
        ),
        "menu_source_cloudflare_pdf_url": (
            menu_source_pdf.get("menu_source_cloudflare_pdf_url")
            or result.get("menu_source_cloudflare_pdf_url")
            or ""
        ),
        "source_pdf_path": menu_source_pdf.get("source_pdf_path") or result.get("source_pdf_path") or "",
        "source_cloudflare_pdf_url": (
            menu_source_pdf.get("source_cloudflare_pdf_url")
            or result.get("source_cloudflare_pdf_url")
            or ""
        ),
        "created_count": len(newly_created),
        "committed_count": len(committed),
        "stubs_created": len(new_stub_entries),
        "menu_mega_json_saved": bool(result.get("menu_mega_json_saved")),
        "menu_mega_snapshot_id": result.get("menu_mega_snapshot_id", ""),
        "parent_menu_snapshot_id": result.get("parent_menu_snapshot_id", ""),
        "item_records_unpacked": int(result.get("item_records_unpacked") or 0),
        "duplicates_skipped": int(result.get("duplicates_skipped") or 0),
        "openai_calls_used": int(result.get("openai_calls_used") or 0),
        "estimated_token_usage": result.get("estimated_token_usage") if isinstance(result.get("estimated_token_usage"), dict) else {},
        "full_recipes_generated": len(new_recipe_entries),
        "nutrition_estimates_completed": 0,
        "pdfs_created": pdf_success_count,
        "committed_recipe_urls": committed,
        "created_recipe_urls": newly_created,
        "created_urls": newly_created,
        "recipe_urls": committed,
        "category_statuses": category_statuses,
        "serving_basis_statuses": serving_basis_statuses,
        "source_pdf_statuses": source_pdf_statuses,
        "pdf_statuses": pdf_statuses,
        "pdfs_generated": pdf_success_count,
        "pdfs_uploaded": pdf_upload_count,
        "item_failures": item_failures,
        "partial_failure": bool(item_failures),
        "category_status": {
            "ok": True,
            "status": "updated",
            "count": category_success_count,
        },
        "category_status_message": category_status_message,
    }
    if not ok:
        result["error"] = result.get("error") or "No menu item recipes were created."
        result["error_message"] = result.get("error_message") or result["error"]
    elif item_failures:
        result["error"] = (
            f"Created {len(newly_created)} new menu item recipe"
            f"{'' if len(newly_created) == 1 else 's'}, "
            f"but {len(item_failures)} menu item"
            f"{'' if len(item_failures) == 1 else 's'} failed."
        )
        result["error_message"] = result["error"]
    return result


def vision_failure_response(
    debug,
    error_code,
    error_message,
    action=None,
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
    action = str(action or debug.get("action") or "generate_recipe_from_image").strip() or "generate_recipe_from_image"
    model_used = str(debug.get("model") or resolve_vision_model())
    technical_message = str(
        debug.get("technical_message") or error_message
    ).strip() or error_message
    openai_error_code = str(debug.get("openai_error_code") or "").strip()
    openai_error_param = str(debug.get("openai_error_param") or "").strip()
    print(
        "[recipe_routes] action=vision_failure "
        f"action_name={action} error_code={error_code} final_error_code={error_code} "
        f"model={model_used} status={status} failed_step={failed_step} "
        f"openai_error_code={openai_error_code or 'n/a'} "
        f"openai_error_param={openai_error_param or 'n/a'}"
    )

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
        action=action,
        error_code=error_code,
        technical_message=technical_message,
        debug=debug,
    )
    payload.update({
        "success": False,
        "model_used": model_used,
        "model": model_used,
        "model_source": str(debug.get("model_source") or resolve_vision_model_source()),
        "error_code": error_code,
        "error_message": error_message,
        "technical_message": technical_message,
        "action": action,
        "exception_type": str(debug.get("exception_type") or ""),
        "openai_error_code": openai_error_code,
        "openai_error_param": openai_error_param,
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


def resolve_uploaded_image_path_for_api(uploaded_file_path, debug):
    uploaded_file_path = str(uploaded_file_path or "").strip()
    if not uploaded_file_path:
        return None, vision_failure_response(
            debug,
            "UPLOADED_FILE_PATH_REQUIRED",
            "uploaded_file_path is required.",
            failed_step="image_uploaded",
        )

    try:
        upload_root = UPLOAD_FOLDER.resolve()
        upload_path = Path(uploaded_file_path).resolve()
    except Exception:
        return None, vision_failure_response(
            debug,
            "INVALID_UPLOADED_FILE_PATH",
            "Invalid uploaded_file_path value.",
            failed_step="image_uploaded",
        )

    if upload_root not in upload_path.parents and upload_root != upload_path:
        return None, vision_failure_response(
            debug,
            "INVALID_UPLOADED_FILE_PATH",
            "Invalid uploaded_file_path value.",
            upload_path=upload_path,
            source_name=upload_path.name,
            failed_step="image_uploaded",
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
        return None, vision_failure_response(
            debug,
            debug.get("error_code") or "IMAGE_VALIDATION_FAILED",
            validation_error,
            upload_path=upload_path,
            source_name=upload_path.name,
            failed_step="image_uploaded",
        )

    return upload_path, None


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
    image_type_supported_by_openai = (
        normalized_mime_type in VISION_SUPPORTED_IMAGE_MIME_TYPES
        or suffix in VISION_SUPPORTED_IMAGE_SUFFIXES
    )
    image_type_convertible = (
        normalized_mime_type in VISION_CONVERTIBLE_IMAGE_MIME_TYPES
        or suffix in VISION_CONVERTIBLE_IMAGE_SUFFIXES
        or normalized_mime_type.startswith("image/")
    )
    image_type_supported = image_type_supported_by_openai or image_type_convertible
    debug["mime_type"] = normalized_mime_type
    debug["image_type_supported"] = image_type_supported
    debug["image_requires_conversion"] = bool(image_type_convertible and not image_type_supported_by_openai)
    log_vision_debug_step(
        debug,
        "Image type supported",
        mime_type=normalized_mime_type,
        suffix=suffix,
        image_type_supported=image_type_supported,
        image_requires_conversion=debug["image_requires_conversion"],
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

        if image_type_convertible:
            ensure_heif_image_support()

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
        error_message = (
            unsupported_phone_image_message(normalized_mime_type)
            if debug["image_requires_conversion"]
            else f"Uploaded image is not readable: {exc}"
        )
        return set_vision_debug_error(
            debug,
            "UNSUPPORTED_IMAGE_FORMAT" if debug["image_requires_conversion"] else "IMAGE_UNREADABLE",
            error_message,
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
        response = throttled_chat_completion(
            get_openai_client(),
            payload,
            action_name="openai-ping",
            model=model,
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


@recipe_bp.route("/api/describe-recipe-image", methods=["POST"])
def api_describe_recipe_image_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    data = request.get_json(force=True) or {}
    uploaded_file_path = str(data.get("uploaded_file_path") or "").strip()
    debug = build_vision_debug(uploaded_file_path=uploaded_file_path)
    debug["action"] = "describe_recipe"
    debug["request_user_agent"] = str(request.headers.get("User-Agent") or "")

    upload_path, error_response = resolve_uploaded_image_path_for_api(uploaded_file_path, debug)
    if error_response:
        return error_response

    prompt = (
        "Visually describe this food image for a recipe workflow. "
        "Mention the visible dish, likely major ingredients, preparation style, and any uncertainty. "
        "If no food is visible, say so plainly. Return concise plain text."
    )
    result = call_openai_vision_image(
        str(upload_path),
        prompt,
        "describe_recipe",
        debug=debug,
    )
    if not result.ok:
        return vision_failure_response(
            debug,
            result.error_code,
            result.error_message,
            action="describe_recipe",
            status=502,
            upload_path=upload_path,
            source_name=upload_path.name,
            failed_step="describe_recipe",
        )

    return jsonify({
        "ok": True,
        "success": True,
        "action": "describe_recipe",
        "description": result.text,
        "text": result.text,
        "model": result.model_used,
        "model_used": result.model_used,
        "model_source": result.model_source,
        "source_type": "image",
        "source_type_label": "Image",
        "source_name": upload_path.name,
        "uploaded_file_path": str(upload_path),
        "debug": debug,
    }), 200


@recipe_bp.route("/api/menu_mega_json_snapshots/<snapshot_id>", methods=["GET"])
def api_menu_mega_json_snapshot_route(snapshot_id):
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    snapshot = load_menu_mega_json_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Mega menu JSON snapshot was not found.",
            "error_code": "MENU_MEGA_JSON_NOT_FOUND",
        }), 404

    return jsonify({
        "ok": True,
        "success": True,
        "snapshot": snapshot,
    })


@recipe_bp.route("/api/menu_mega_json_snapshots/<snapshot_id>/download", methods=["GET"])
def api_menu_mega_json_snapshot_download_route(snapshot_id):
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    snapshot = load_menu_mega_json_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Mega menu JSON snapshot was not found.",
            "error_code": "MENU_MEGA_JSON_NOT_FOUND",
        }), 404

    filename = f"mega-menu-{snapshot.get('id') or snapshot_id}.json"
    return Response(
        json.dumps(snapshot.get("menu_mega_json") or {}, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@recipe_bp.route("/api/menu_mega_json_snapshots/<snapshot_id>/retry-unpack", methods=["POST"])
def api_menu_mega_json_snapshot_retry_unpack_route(snapshot_id):
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    snapshot = load_menu_mega_json_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Mega menu JSON snapshot was not found.",
            "error_code": "MENU_MEGA_JSON_NOT_FOUND",
        }), 404

    data = request.get_json(silent=True) or {}
    cookbook = selected_import_cookbook(
        data.get("cookbook_id") or snapshot.get("cookbook_id", ""),
        data.get("cookbook_name") or snapshot.get("cookbook_name", ""),
    )
    mega_json = snapshot.get("menu_mega_json") if isinstance(snapshot.get("menu_mega_json"), dict) else {}
    source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
    sections = unpack_mega_menu_json_to_sections(
        mega_json,
        snapshot_id=snapshot.get("id") or snapshot_id,
    )
    result = build_menu_stub_extract_result_from_items(
        source.get("source_url") or snapshot.get("source_url", ""),
        sections,
        source_name=source.get("source_url") or snapshot.get("source_url", ""),
        source_type="menu_url",
        extracted_text=(mega_json.get("raw_capture") or {}).get("text_snapshot", "")
        if isinstance(mega_json.get("raw_capture"), dict)
        else "",
        diagnostics={
            "retry_unpack": True,
            "menu_mega_snapshot_id": snapshot.get("id") or snapshot_id,
        },
        menu_snapshot=snapshot,
        skip_cleanup=True,
    )
    if result.get("ok"):
        result = commit_menu_import_result(
            result,
            cookbook,
            context="retry-menu-mega-unpack",
        )

    return jsonify(with_openai_usage_dashboard(result)), 200 if result.get("ok") else 400


@recipe_bp.route("/api/debug-openai-vision", methods=["GET", "POST"])
def api_debug_openai_vision_route():
    account_response = require_account_for_import(wants_json=True)
    if account_response:
        return account_response

    if not is_admin_user(current_user()):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
            "error_code": "ADMIN_REQUIRED",
        }), 403

    data = request.get_json(silent=True) if request.method == "POST" else {}
    data = data if isinstance(data, dict) else {}
    uploaded_file_path = str(
        data.get("uploaded_file_path")
        or request.args.get("uploaded_file_path")
        or ""
    ).strip()
    debug = build_vision_debug(uploaded_file_path=uploaded_file_path)
    debug["action"] = "debug_openai_vision"

    upload_path, error_response = resolve_uploaded_image_path_for_api(uploaded_file_path, debug)
    diagnostics = openai_runtime_diagnostics()
    if error_response:
        response, status_code = error_response
        payload = response.get_json(silent=True) or {}
        payload.update({
            "runtime": diagnostics,
            "sys_executable": diagnostics.get("sys.executable"),
            "openai_version": diagnostics.get("openai.__version__"),
            "openai_file": diagnostics.get("openai.__file__"),
        })
        return jsonify(payload), status_code

    prompt = str(data.get("prompt") or request.args.get("prompt") or "").strip()
    if not prompt:
        prompt = "Briefly describe this food image in one sentence."

    result = call_openai_vision_image(
        str(upload_path),
        prompt,
        "debug_openai_vision",
        preferred_model=str(data.get("model") or request.args.get("model") or "").strip() or None,
        debug=debug,
    )
    payload = {
        "ok": bool(result.ok),
        "success": bool(result.ok),
        "sys_executable": diagnostics.get("sys.executable"),
        "openai_version": diagnostics.get("openai.__version__"),
        "openai_file": diagnostics.get("openai.__file__"),
        "model": result.model_used,
        "model_used": result.model_used,
        "model_source": result.model_source,
        "response_preview": result.text[:1000],
        "debug": debug,
        "runtime": diagnostics,
    }
    if not result.ok:
        payload.update(result.to_dict())
        return jsonify(payload), 502

    return jsonify(payload), 200


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
    client_context = data.get("client_context") if isinstance(data.get("client_context"), dict) else {}
    debug = build_vision_debug(uploaded_file_path=uploaded_file_path)
    debug["action"] = "generate_recipe_from_image"
    debug["client_context"] = client_context
    debug["request_user_agent"] = str(request.headers.get("User-Agent") or "")
    log_vision_debug_step(debug, "Image path received", image_path=uploaded_file_path)
    log_vision_debug_step(
        debug,
        "Client context",
        user_agent=debug["request_user_agent"],
        platform=client_context.get("platform"),
        viewport=client_context.get("viewport"),
        max_touch_points=client_context.get("max_touch_points"),
    )

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

    if not inline_jobs_enabled():
        cookbook = selected_import_cookbook_from_json(data)
        log_selected_import_cookbook("media-upload-vision", cookbook)
        payload = {
            "source_path": str(upload_path),
            "filename": upload_path.name,
            "content_type": resolved_mime_type or "",
            "import_mode": "recipe",
            "extraction_mode": "recipe",
            "upload_mode": "manual_description" if user_description else "vision",
            "manual_description": user_description,
            "cookbook_id": cookbook.get("id", "") if isinstance(cookbook, dict) else "",
            "cookbook_name": cookbook.get("name", "") if isinstance(cookbook, dict) else "",
            "model_used": resolve_vision_model(),
            "model_source": resolve_vision_model_source(),
            "model_env_var": "OPENAI_VISION_MODEL",
            "model_env_var_used": "OPENAI_VISION_MODEL",
            "client_context": client_context,
        }
        job, queue_result, error_message = start_import_background_job("doc-photo-import", payload, total_items=1)
        return import_job_json_response(job, queue_result, error_message)

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
    result["model"] = str(debug.get("model") or resolve_vision_model())
    result["model_source"] = str(debug.get("model_source") or resolve_vision_model_source())
    result["fallback_used"] = bool(debug.get("fallback_used"))
    result["fallback_from_model"] = str(debug.get("fallback_from_model") or "")
    result["fallback_to_model"] = str(debug.get("fallback_to_model") or "")
    result["action"] = "generate_recipe_from_image"
    result["debug"] = debug
    _mark_uploaded_recipe_nutrition_estimated(
        recipe_url,
        _has_per_serving_estimate(parsed_recipe.get("nutrition") if isinstance(parsed_recipe, dict) else None),
    )
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
    nutrition_model = active_openai_model("OPENAI_NUTRITION_MODEL", MODEL)

    saved_recipe = {}
    if recipe_url:
        loaded_recipe = load_editable_recipe(recipe_url) or {}
        saved_recipe = loaded_recipe.get("recipe") if isinstance(loaded_recipe, dict) else {}
        saved_recipe = saved_recipe if isinstance(saved_recipe, dict) else {}

    if saved_recipe and _has_per_serving_estimate(saved_recipe.get("nutrition")):
        saved_recipe = _recipe_with_default_serving_basis(saved_recipe)
        _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)
        result = _existing_nutrition_success(saved_recipe, recipe_url)
        result["model_used"] = nutrition_model
        result["debug"] = {
            "model": result["model_used"],
            "recipe_url": recipe_url,
            "already_complete": True,
            "source": "saved_recipe",
        }
        return jsonify(with_openai_usage_dashboard(result)), 200

    if not recipe and saved_recipe:
        recipe = saved_recipe

    if not recipe:
        return jsonify(with_openai_usage_dashboard({
            "ok": False,
            "success": False,
            "error": "Recipe payload is required.",
            "model_used": nutrition_model,
            "debug": {
                "model": nutrition_model,
                "recipe_url": recipe_url,
            },
        })), 400

    if _has_per_serving_estimate(recipe.get("nutrition") if isinstance(recipe, dict) else None):
        recipe = _recipe_with_default_serving_basis(recipe)
        if recipe_url:
            save_result = save_editable_recipe(recipe_url, recipe)
            if not save_result.get("ok"):
                return jsonify(with_openai_usage_dashboard({
                    "ok": False,
                    "success": False,
                    "error": save_result.get("error") or "Unable to save existing nutrition.",
                    "recipe_json": recipe,
                    "recipe_url": recipe_url,
                })), 400
            _mark_uploaded_recipe_nutrition_estimated(recipe_url, True)
        result = _existing_nutrition_success(recipe, recipe_url)
        result["model_used"] = nutrition_model
        result["debug"] = {
            "model": result["model_used"],
            "recipe_url": recipe_url,
            "already_complete": True,
        }
        return jsonify(with_openai_usage_dashboard(result)), 200

    model_used = nutrition_model
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
        result["model_used"] = active_openai_model("OPENAI_NUTRITION_MODEL", MODEL)

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/menu_recipe_estimate_per_serving", methods=["POST"])
def api_menu_recipe_estimate_per_serving_route():
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
    recipe_id = str(data.get("recipe_id") or "").strip()
    job_id = str(data.get("job_id") or "").strip()

    if not recipe_url:
        return jsonify(with_openai_usage_dashboard({
            "ok": False,
            "success": False,
            "error": "Recipe URL is required.",
            "progress": load_progress(),
        })), 400

    if job_id:
        update_menu_recipe_step(
            job_id,
            recipe_id=recipe_id,
            recipe_url=recipe_url,
            step="estimate_per_serving",
            checked=False,
            running=True,
            message="Updating...",
            error="",
        )

    try:
        result = ensure_menu_recipe_serving_basis_estimate(recipe_url, {})
    except Exception as exc:
        result = {
            "ok": False,
            "recipe_url": recipe_url,
            "error": str(exc) or "Unable to estimate serving basis.",
        }

    if result.get("ok"):
        progress = update_menu_recipe_step(
            job_id,
            recipe_id=recipe_id,
            recipe_url=recipe_url,
            step="estimate_per_serving",
            checked=True,
            running=False,
            message="Already complete" if result.get("already_complete") else "Complete",
            error="",
        ) if job_id else load_progress()
    else:
        progress = update_menu_recipe_step(
            job_id,
            recipe_id=recipe_id,
            recipe_url=recipe_url,
            step="estimate_per_serving",
            checked=False,
            running=False,
            message="",
            error=result.get("error") or "Unable to estimate serving basis.",
        ) if job_id else load_progress()

    result = {
        **result,
        "success": bool(result.get("ok")),
        "progress": progress,
    }
    if "model_used" not in result:
        result["model_used"] = str(os.getenv("OPENAI_NUTRITION_MODEL", MODEL))
    status = 200 if result.get("ok") else 400

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
    menu_extract = import_request_is_menu_extract(data)
    cookbook = selected_import_cookbook_from_json(data)
    log_selected_import_cookbook("api-menu-url" if menu_extract else "api-url", cookbook)

    if not urls:
        urls = [url]

    if not [item for item in urls if item]:
        return jsonify(with_openai_usage_dashboard({
            "ok": False,
            "error": "At least one recipe URL is required.",
        })), 400

    payload = {
        **data,
        "urls": urls,
        "extraction_mode": "menu_extract" if menu_extract else "recipe",
        "model_used": resolve_menu_cleanup_model() if menu_extract else MODEL,
        "model_source": resolve_menu_cleanup_model_source() if menu_extract else "recipe",
        "model_env_var": "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
        "model_env_var_used": "OPENAI_MENU_CLEANUP_MODEL" if menu_extract else "OPENAI_RECIPE_MODEL",
    }
    job_type = "menu-import" if menu_extract else "recipe-import"
    job, queue_result, error_message = start_import_background_job(job_type, payload, total_items=len(urls))
    return import_job_json_response(job, queue_result, error_message)

    try:
        progress_callback = lambda message, summary=None: mark_url_message(
            job_id,
            urls,
            index,
            message,
            summary,
        )
        if menu_extract:
            result = extract_menu_recipes_from_url(
                url,
                progress_callback=progress_callback,
            )
        else:
            result = extract_recipe_from_url(
                url,
                progress_callback=progress_callback,
            )

        if is_cancel_requested(job_id) or not is_current_job(job_id):
            return jsonify({"ok": False, "cancelled": True, "error": "Extraction cancelled."}), 409

        if menu_extract:
            if not result.get("ok"):
                progress = mark_url_failed(job_id, urls, index, result.get("error") or "Menu extraction failed.")
                finish_batch_if_ready(job_id, progress)
                return jsonify(with_openai_usage_dashboard(result)), 400

            mark_url_message(
                job_id,
                urls,
                index,
                IMPORT_CATEGORY_STATUS_MESSAGE,
                summary="Generating categories for new menu item recipes.",
            )
            committed = commit_menu_import_result(
                result,
                cookbook,
                context="api-menu-url",
                progress_callback=progress_callback,
                menu_recipe_progress_callback=lambda recipes: set_url_menu_recipes(
                    job_id,
                    urls,
                    index,
                    recipes,
                    message="Updating menu recipe checklist",
                    summary="Saving inferred menu item recipes.",
                ),
            )
            if not committed.get("ok"):
                progress = mark_url_failed(job_id, urls, index, committed.get("error") or "No menu item recipes were created.")
                finish_batch_if_ready(job_id, progress)
                return jsonify(with_openai_usage_dashboard(committed)), 400

            if committed.get("partial_failure"):
                progress = mark_url_failed(job_id, urls, index, committed.get("error") or "Some menu items failed.")
            else:
                progress = mark_url_done(job_id, urls, index, committed.get("created_count", 0))
            finish_batch_if_ready(job_id, progress)
            status = 207 if committed.get("partial_failure") else 200
            return jsonify(with_openai_usage_dashboard(committed)), status

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

    extraction_mode = str(data.get("extraction_mode") or "").strip().lower()
    return jsonify(start_progress(urls, job_id=job_id, extraction_mode=extraction_mode))


@recipe_bp.route("/api/extract_progress", methods=["GET"])
def api_extract_progress_route():
    return jsonify(load_progress())


@recipe_bp.route("/api/cancel_extract", methods=["POST"])
def api_cancel_extract_route():
    data = request.get_json(silent=True) or {}
    job_id = str(data.get("job_id") or "").strip() or None

    progress = request_cancel(job_id)

    return jsonify(progress)


@recipe_bp.route("/recipe/edit", methods=["GET"])
def edit_recipe_page_route():
    recipe_url = str(request.args.get("url", "") or "").strip()

    if not recipe_url:
        abort(400)

    return render_template(
        "recipe_edit_page.html",
        recipe_url=recipe_url,
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        current_urls=[],
        current_recipe_count=0,
        cookbook_view=recipe_edit_cookbook_view(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
    )


@recipe_bp.route("/api/recipe/restaurant-source", methods=["POST"])
def update_recipe_restaurant_source_route():
    data = request.get_json(silent=True) or {}
    recipe_url = str(data.get("recipe_url") or "").strip()
    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400
    result = update_editable_restaurant_source(recipe_url, data)
    status = 200 if result.get("ok") else (409 if result.get("duplicate_detected") else 400)
    return jsonify(result), status


@recipe_bp.route("/api/recipe/restaurants", methods=["GET", "POST"])
def recipe_restaurants_route():
    if request.method == "GET":
        return jsonify(list_editable_restaurants(
            request.args.get("q", ""),
            request.args.get("limit", 100),
        ))
    data = request.get_json(silent=True) or {}
    result = create_editable_restaurant(data, create_anyway=data.get("create_anyway"))
    status = 201 if result.get("ok") else (409 if result.get("duplicate_detected") else 400)
    return jsonify(result), status


@recipe_bp.route("/api/recipe/restaurants/<restaurant_id>", methods=["GET", "PATCH"])
def recipe_restaurant_detail_route(restaurant_id):
    if request.method == "GET":
        result = get_editable_restaurant(restaurant_id)
    else:
        data = request.get_json(silent=True) or {}
        result = update_editable_restaurant(restaurant_id, data, menu_id=data.get("menu_id"))
    status = 200 if result.get("ok") else (
        404 if "not found" in str(result.get("error") or "").lower() else 400
    )
    return jsonify(result), status


@recipe_bp.route("/api/recipe/restaurants/<restaurant_id>/fetch-details", methods=["POST"])
def recipe_restaurant_fetch_details_route(restaurant_id):
    """Scan configured public sources and retain an evidence-backed pending review."""
    selected = get_editable_restaurant(restaurant_id)
    if not selected.get("ok"):
        return jsonify(selected), 404
    data = request.get_json(silent=True) or {}
    restaurant = {**(selected.get("restaurant") or {})}
    discovery_fields = {
        "restaurant_name": "restaurant_name",
        "restaurant_phone": "restaurant_phone",
        "restaurant_street_address": "restaurant_street_address",
        "restaurant_city": "restaurant_city",
        "restaurant_state": "restaurant_state",
        "restaurant_postal_code": "restaurant_postal_code",
        "restaurant_country": "restaurant_country",
        "restaurant_website_url": "restaurant_website_url",
        "source_menu_url": "source_menu_url",
        "menu_item_url": "menu_item_url",
    }
    for payload_key, record_key in discovery_fields.items():
        if payload_key in data:
            restaurant[record_key] = data.get(payload_key)
    result = store_pending_restaurant_scan(
        scan_restaurant_information(restaurant, force=data.get("force") is True)
    )
    return jsonify(result), 200


@recipe_bp.route("/api/recipe/restaurants/<restaurant_id>/apply-information-scan", methods=["POST"])
def recipe_restaurant_apply_information_scan_route(restaurant_id):
    data = request.get_json(silent=True) or {}
    scan = load_pending_restaurant_scan(data.get("scan_id"), restaurant_id)
    if not scan.get("ok"):
        return jsonify(scan), 404
    result = apply_restaurant_information_scan(
        restaurant_id,
        scan,
        selections=data.get("selections") or {},
        mode=str(data.get("mode") or "selected").strip(),
        lock_updates=data.get("lock_updates") or {},
    )
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/api/recipe/restaurants/backfill", methods=["POST"])
def recipe_restaurants_backfill_route():
    return jsonify(backfill_editable_restaurant_sources())


@recipe_bp.route("/api/recipe/restaurant-usage", methods=["GET"])
def recipe_restaurant_usage_route():
    result = editable_restaurant_usage(
        request.args.get("restaurant_id"),
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 50),
        query=request.args.get("q", ""),
        current_recipe_url=request.args.get("current_recipe_url", ""),
    )
    if result.get("ok"):
        result = decorate_restaurant_usage_with_duplicates(result, request.args.get("restaurant_id"))
    return jsonify(result), 200 if result.get("ok") else 404


@recipe_bp.route("/api/recipe/restaurant-usage/backfill", methods=["POST"])
def backfill_recipe_restaurant_usage_route():
    data = request.get_json(silent=True) or {}
    result = backfill_editable_restaurant_usage(data.get("restaurant_id"))
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/api/recipe/restaurant-duplicates/<group_id>", methods=["GET"])
def recipe_restaurant_duplicate_group_route(group_id):
    result = restaurant_recipe_duplicate_group_detail(request.args.get("restaurant_id"), group_id)
    return jsonify(result), 200 if result.get("ok") else 404


@recipe_bp.route("/api/recipe/restaurant-duplicates/<group_id>/disposition", methods=["POST"])
def recipe_restaurant_duplicate_disposition_route(group_id):
    data = request.get_json(silent=True) or {}
    result = set_restaurant_recipe_duplicate_disposition(
        data.get("restaurant_id"), group_id, str(data.get("disposition") or "").strip()
    )
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/api/recipe/restaurant-duplicates/<group_id>/merge", methods=["POST"])
def recipe_restaurant_duplicate_merge_route(group_id):
    data = request.get_json(silent=True) or {}
    if data.get("commit") is True and data.get("confirm_merge") is not True:
        return jsonify({"ok": False, "error": "Confirm the duplicate merge before committing it."}), 400
    secondary_record_keys = data.get("secondary_record_keys") or []
    if not isinstance(secondary_record_keys, list):
        return jsonify({"ok": False, "error": "Duplicate recipe selections are invalid."}), 400
    field_choices = data.get("field_choices") or {}
    if not isinstance(field_choices, dict):
        return jsonify({"ok": False, "error": "Merge field choices are invalid."}), 400
    args = (
        data.get("restaurant_id"), group_id, data.get("primary_record_key"), secondary_record_keys
    )
    result = (
        commit_restaurant_recipe_merge(*args, field_choices=field_choices)
        if data.get("commit") is True
        else restaurant_recipe_merge_preview(*args)
    )
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/api/recipe/restaurant-duplicates/<group_id>/delete", methods=["POST"])
def recipe_restaurant_duplicate_delete_route(group_id):
    data = request.get_json(silent=True) or {}
    if data.get("commit") is True and data.get("confirm_delete") is not True:
        return jsonify({"ok": False, "error": "Confirm duplicate deletion before committing it."}), 400
    args = (data.get("restaurant_id"), group_id, data.get("recipe_record_key"))
    result = commit_restaurant_recipe_delete(*args) if data.get("commit") is True else restaurant_recipe_delete_preview(*args)
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/api/recipe/source-documents", methods=["POST"])
def update_recipe_source_documents_route():
    data = request.get_json(silent=True) or {}
    recipe_url = str(data.get("recipe_url") or "").strip()
    result = update_editable_source_documents(recipe_url, data)
    return jsonify(result), 200 if result.get("ok") else 400


@recipe_bp.route("/restaurant_source_logo", methods=["GET"])
def restaurant_source_logo_route():
    logo_path = editable_restaurant_logo_file_path(request.args.get("restaurant_id"))
    if not logo_path:
        abort(404)
    return send_file(logo_path, mimetype=image_mimetype_for_path(logo_path), as_attachment=False, max_age=0)


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


def requested_recipe_urls_for_clear():
    requested_urls = []
    has_requested_urls = False
    payload = request.get_json(silent=True) or {}

    if isinstance(payload, dict):
        for key in ("recipe_urls", "urls", "selected_recipe_urls"):
            if key not in payload:
                continue

            has_requested_urls = True
            value = payload.get(key)
            if isinstance(value, list):
                requested_urls.extend(value)
            else:
                requested_urls.append(value)

    for key in ("recipe_urls", "urls", "selected_recipe_urls"):
        if key in request.form:
            has_requested_urls = True
            requested_urls.extend(request.form.getlist(key))

    return has_requested_urls, [
        str(url or "").strip()
        for url in requested_urls
        if str(url or "").strip()
    ]


def clear_recipe_urls_error_response(message, status_code, wants_json):
    if wants_json:
        return jsonify({"ok": False, "error": message}), status_code

    flash(message, "error")
    return redirect("/")


@recipe_bp.route("/api/recipe_urls/clear", methods=["POST"])
def api_clear_recipe_urls_route():
    current_urls = load_recipe_urls()
    wants_json = wants_fetch_json_response()
    has_requested_urls, requested_urls = requested_recipe_urls_for_clear()

    if has_requested_urls:
        requested_keys = {
            normalize_recipe_url_key(url)
            for url in requested_urls
            if normalize_recipe_url_key(url)
        }

        if not requested_keys:
            return clear_recipe_urls_error_response(
                "Select at least one recipe to clear.",
                400,
                wants_json,
            )

        urls_to_clear = []
        seen_keys = set()

        for url in current_urls:
            key = normalize_recipe_url_key(url)
            if key and key in requested_keys and key not in seen_keys:
                urls_to_clear.append(url)
                seen_keys.add(key)

        if not urls_to_clear:
            return clear_recipe_urls_error_response(
                "No selected current recipes matched.",
                400,
                wants_json,
            )
    else:
        urls_to_clear = current_urls

    try:
        for url in urls_to_clear:
            remove_recipe_and_unused_ingredients(url)
            remove_recipe_url(url)
    except Exception as exc:
        if wants_json:
            return jsonify({"ok": False, "error": str(exc) or "Unable to clear current recipes."}), 500
        raise

    if wants_json:
        return jsonify({
            "ok": True,
            "cleared_recipe_count": len(urls_to_clear),
            "redirect_url": "/",
        })

    return redirect("/")


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

    recipe_payload = data.get("recipe", {})
    if _is_uploaded_recipe_url(original_url) and isinstance(recipe_payload, dict):
        recipe_payload = _recipe_with_default_serving_basis(recipe_payload)

    result = save_editable_recipe(original_url, recipe_payload)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe/infer_missing_details", methods=["POST"])
def api_recipe_infer_missing_details_route():
    data = request.get_json(silent=True) or {}
    recipe_url = str(
        data.get("url")
        or data.get("recipe_url")
        or data.get("source_url")
        or ""
    ).strip()

    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    force_fields = data.get("force_fields") if isinstance(data.get("force_fields"), list) else []
    if data.get("force_recipe_notes") and "recipe_notes" not in force_fields:
        force_fields = [*force_fields, "recipe_notes"]

    result = infer_missing_details_for_recipe(
        recipe_url,
        cookbook_id=str(data.get("cookbook_id") or "").strip(),
        cookbook_name=str(data.get("cookbook_name") or "").strip(),
        overwrite_ai_fields=bool(data.get("overwrite_ai_fields")),
        preview_only=bool(data.get("preview_only")),
        user_id=active_user_id(),
        current_recipe=data.get("recipe") if isinstance(data.get("recipe"), dict) else None,
        force_fields=force_fields,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe/review_store_sections", methods=["POST"])
def api_recipe_review_store_sections_route():
    data = request.get_json(silent=True) or {}
    recipe_payload = data.get("recipe") if isinstance(data.get("recipe"), dict) else None
    recipe_url = str(
        data.get("original_url")
        or data.get("url")
        or data.get("recipe_url")
        or data.get("source_url")
        or (recipe_payload or {}).get("source_url")
        or ""
    ).strip()

    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    if recipe_payload is None:
        loaded = load_editable_recipe(recipe_url)
        recipe_payload = loaded.get("recipe") if isinstance(loaded, dict) else {}

    result = review_recipe_store_sections(recipe_payload)
    result["recipe_url"] = recipe_url
    result["applied"] = False

    if bool(data.get("apply")):
        recipe_to_save = result.get("recipe") if isinstance(result.get("recipe"), dict) else recipe_payload
        if _is_uploaded_recipe_url(recipe_url) and isinstance(recipe_to_save, dict):
            recipe_to_save = _recipe_with_default_serving_basis(recipe_to_save)
        save_result = save_editable_recipe(recipe_url, recipe_to_save)
        if not save_result.get("ok"):
            status = 400
            save_result.setdefault("changes", result.get("changes", []))
            save_result.setdefault("changed_count", result.get("changed_count", 0))
            save_result.setdefault("reviewed_count", result.get("reviewed_count", 0))
            save_result["applied"] = False
            return jsonify(save_result), status

        result.update(save_result)
        result["applied"] = True
        result["changes"] = result.get("changes", [])
        result["changed_count"] = len(result["changes"])
        result["reviewed_count"] = result.get("reviewed_count", 0)

    return jsonify(result), 200


@recipe_bp.route("/api/recipe/regenerate_ingredients", methods=["POST"])
def api_recipe_regenerate_ingredients_route():
    data = request.get_json(silent=True) or {}
    recipe_url = str(
        data.get("url")
        or data.get("original_url")
        or data.get("recipe_url")
        or data.get("source_url")
        or ""
    ).strip()

    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    result = regenerate_ingredients_for_recipe(
        recipe_url,
        current_recipe=data.get("recipe") if isinstance(data.get("recipe"), dict) else None,
        cookbook_id=str(data.get("cookbook_id") or "").strip(),
        cookbook_name=str(data.get("cookbook_name") or "").strip(),
        preview_only=bool(data.get("preview_only")),
        user_id=active_user_id(),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe/regenerate_notes", methods=["POST"])
def api_recipe_regenerate_notes_route():
    data = request.get_json(silent=True) or {}
    recipe_url = str(
        data.get("url")
        or data.get("original_url")
        or data.get("recipe_url")
        or data.get("source_url")
        or ""
    ).strip()

    if not recipe_url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    result = regenerate_recipe_notes_for_recipe(
        recipe_url,
        current_recipe=data.get("recipe") if isinstance(data.get("recipe"), dict) else None,
        cookbook_id=str(data.get("cookbook_id") or "").strip(),
        cookbook_name=str(data.get("cookbook_name") or "").strip(),
        preview_only=bool(data.get("preview_only")),
        user_id=active_user_id(),
    )
    status = 200 if result.get("ok") else 400
    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/create_recipe", methods=["POST"])
def api_create_recipe_route():
    return jsonify(create_new_recipe()), 201


@recipe_bp.route("/api/recipe_nutrition_estimate", methods=["POST"])
def api_recipe_nutrition_estimate_route():
    data = request.get_json(silent=True) or {}
    recipe = data.get("recipe", data)
    force_estimate = bool(data.get("force_estimate") or data.get("force"))
    if not force_estimate and _has_per_serving_estimate(recipe.get("nutrition") if isinstance(recipe, dict) else None):
        recipe = _recipe_with_default_serving_basis(recipe)
        return jsonify(with_openai_usage_dashboard(_existing_nutrition_success(recipe))), 200

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


@recipe_bp.route("/api/recipe_ingredient_image", methods=["POST"])
def api_recipe_ingredient_image_route():
    data = request.get_json(silent=True) or {}
    result = generate_recipe_ingredient_image(data)
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


@recipe_bp.route("/api/recipe_cover_image/generate", methods=["POST"])
def api_generate_recipe_cover_image_route():
    data = request.get_json(silent=True) or {}
    result = generate_recipe_cover_image(data)
    status = 200 if result.get("ok") else 400

    return jsonify(with_openai_usage_dashboard(result)), status


@recipe_bp.route("/api/recipe_cover_image/remove", methods=["POST"])
def api_remove_recipe_cover_image_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or data.get("recipe_url") or "").strip()
    result = remove_recipe_cover_image(url)
    status = 200 if result.get("ok") else 400

    return jsonify(result), status


@recipe_bp.route("/api/recipe_cover_image/test-local", methods=["POST"])
def api_test_local_recipe_cover_image_route():
    if not is_admin_user(current_user()):
        return jsonify({"ok": False, "error": "Admin access required."}), 403

    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt") or "").strip()
    result = test_local_title_image_generation(prompt=prompt)
    status = 200 if result.get("ok") else 503

    return jsonify(result), status


@recipe_bp.route("/api/recipe_detail_image", methods=["POST"])
def api_recipe_detail_image_route():
    url = str(request.form.get("url", "") or "").strip()
    kind = str(request.form.get("kind", "") or "").strip()
    target = (
        request.form.get("target")
        or request.form.get("ingredient_index")
        or request.form.get("ingredient_number")
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


@recipe_bp.route("/api/recipe_detail_image", methods=["DELETE"])
def api_remove_recipe_detail_image_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or data.get("recipe_url") or "").strip()
    kind = str(data.get("kind") or "").strip()
    target = (
        data.get("target")
        or data.get("ingredient_index")
        or data.get("ingredient_number")
        or data.get("equipment_index")
        or data.get("equipment_number")
        or data.get("step_number")
        or ""
    )
    result = remove_recipe_detail_image(url, kind, target)
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


@recipe_bp.route("/api/recipe_favorite", methods=["POST"])
def api_recipe_favorite_route():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or data.get("recipe_url") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "Recipe URL is required."}), 400

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return jsonify({"ok": False, "error": "Recipe was not found."}), 404

    favorite_value = data.get("favorite")
    favorite = not bool(recipe_data.get("favorite")) if favorite_value is None else bool(favorite_value)
    recipe_data["favorite"] = favorite
    save_recipe_output(recipe_data.get("source_url") or url, recipe_data)

    return jsonify({
        "ok": True,
        "favorite": favorite,
        "url": recipe_data.get("source_url") or url,
    })


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
    variant = str(request.args.get("variant", "") or "").strip().lower()

    if not url:
        abort(404)

    cover_image = find_recipe_cover_image(url)
    image_path = recipe_cover_image_file_path(cover_image)

    if not image_path:
        abort(404)

    if variant:
        variant_path = ensure_webp_variant(image_path, variant)

        if not variant_path:
            abort(404)

        return send_file(
            variant_path,
            mimetype="image/webp",
            as_attachment=False,
            download_name=variant_path.name,
            max_age=generated_static_cache_seconds(),
        )

    return send_file(
        image_path,
        mimetype=(
            cover_image.get("mime_type")
            if isinstance(cover_image, dict) and cover_image.get("mime_type")
            else image_mimetype_for_path(image_path)
        ),
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
    url = str(request.form.get("url") or data.get("url", "")).strip()
    wants_json = wants_fetch_json_response()

    if not url:
        message = "Recipe URL is required."
        if wants_json:
            return jsonify({"ok": False, "error": message}), 400
        flash(message, "error")
        return redirect("/")

    try:
        remove_recipe_and_unused_ingredients(url)
        remove_recipe_url(url)
    except Exception as exc:
        if wants_json:
            return jsonify({"ok": False, "error": str(exc) or "Unable to delete recipe."}), 500
        raise

    if wants_json:
        return jsonify({"ok": True, "redirect_url": "/"})

    return redirect("/")


@recipe_bp.route("/purge_recipe", methods=["POST"])
def purge_recipe_route():
    data = request.get_json(silent=True) or {}
    url = str(request.form.get("url") or data.get("url", "")).strip()
    wants_json = wants_fetch_json_response()

    if not url:
        message = "Recipe URL is required."
        if wants_json:
            return jsonify({"ok": False, "error": message}), 400
        flash(message, "error")
        return redirect("/")

    try:
        purge_recipe_from_all_cookbooks(url)
        remove_recipe_and_unused_ingredients(url)
        remove_recipe_url(url)
    except Exception as exc:
        if wants_json:
            return jsonify({"ok": False, "error": str(exc) or "Unable to purge recipe."}), 500
        raise

    if wants_json:
        return jsonify({"ok": True, "redirect_url": "/"})

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
