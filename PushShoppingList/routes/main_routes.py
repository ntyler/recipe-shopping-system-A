import html
import json
import os
import re
import uuid
from datetime import date
from datetime import datetime
from datetime import timezone
from fractions import Fraction
from urllib.parse import parse_qsl
from urllib.parse import urlparse

import requests
from openai import OpenAI
from flask import Blueprint
from flask import abort
from flask import current_app
from flask import g
from flask import jsonify
from flask import has_request_context
from flask import redirect
from flask import make_response
from flask import request
from flask import render_template
from flask import session
from flask import url_for

from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients
from PushShoppingList.services import recipe_master_data_service as recipe_master_data
from PushShoppingList.services import recipe_master_image_service as recipe_master_images
from PushShoppingList.services import master_data_url_service
from PushShoppingList.services import ingredient_store_section_review_service as ingredient_store_section_reviews
from PushShoppingList.services import ingredient_duplicate_review_service as ingredient_duplicate_reviews
from PushShoppingList.services import ingredient_type_service as ingredient_types
from PushShoppingList.services import unit_suggestion_service as unit_suggestions
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.food_rules_service import shopping_item_food_rule_status
from PushShoppingList.services.feedback_service import feedback_dashboard_for_user
from PushShoppingList.services.guest_session_service import is_guest_session
from PushShoppingList.services.cookbook_service import cookbook_view
from PushShoppingList.services.cookbook_service import duration_minutes
from PushShoppingList.services.cookbook_service import create_cookbook
from PushShoppingList.services.cookbook_service import find_cookbook
from PushShoppingList.services.cookbook_service import find_or_create_cookbook
from PushShoppingList.services.cookbook_service import is_unclassified_cookbook
from PushShoppingList.services.cookbook_service import load_cookbooks
from PushShoppingList.services.cookbook_service import cookbook_recipes_for_urls
from PushShoppingList.services.cookbook_service import cookbook_recipe_index
from PushShoppingList.services.cookbook_service import CookbookCategoryOverwriteConflict
from PushShoppingList.services.cookbook_service import CookbookRecipeConflict
from PushShoppingList.services.cookbook_service import delete_cookbook
from PushShoppingList.services.cookbook_service import delete_cookbook_and_purge_recipe_urls
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import move_recipes_to_cookbook
from PushShoppingList.services.cookbook_service import prepare_cookbook_menu_view
from PushShoppingList.services.cookbook_service import purge_cookbook_recipe_urls
from PushShoppingList.services.cookbook_service import purge_selected_cookbook_recipe_urls
from PushShoppingList.services.cookbook_service import purge_unclassified_cookbook_recipe_urls
from PushShoppingList.services.cookbook_service import recipe_ingredients_for_record
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.cookbook_service import remove_recipe_from_cookbook
from PushShoppingList.services.cookbook_service import remove_recipes_from_cookbook
from PushShoppingList.services.cookbook_service import rename_cookbook
from PushShoppingList.services.cookbook_service import reorder_cookbooks
from PushShoppingList.services.cookbook_service import reorder_cookbook_menu_section
from PushShoppingList.services.cookbook_service import update_cookbook_recipe_categories
from PushShoppingList.services.cookbook_item_inference_service import infer_missing_details_for_cookbook
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.home_address_service import load_home_address_history
from PushShoppingList.services.home_address_service import save_home_address
from PushShoppingList.services.home_address_service import delete_home_address_history_entry
from PushShoppingList.services.home_address_service import update_home_address_history_label
from PushShoppingList.services.home_store_location_service import DEFAULT_STORE_SEARCH_RADIUS_MILES
from PushShoppingList.services.home_store_location_service import format_store_search_radius
from PushShoppingList.services.home_store_location_service import load_nearest_store_results
from PushShoppingList.services.home_store_location_service import resolve_nearest_stores_for_home_address
from PushShoppingList.services.ingredient_text_review_service import fallback_ingredient_text_review
from PushShoppingList.services.ingredient_text_review_service import normalize_ingredient_text_review
from PushShoppingList.services.ingredient_option_service import IngredientOptionSelectionRequired
from PushShoppingList.services.ingredient_option_service import ingredient_requirements
from PushShoppingList.services.ingredient_option_service import public_requirement
from PushShoppingList.services.ingredient_option_service import resolve_ingredient_requirements
from PushShoppingList.services.ingredient_option_service import shopping_item_name
from PushShoppingList.services.ingredient_unit_service import unit_registry_payload
from PushShoppingList.services.ingredient_unit_service import canonical_unit
from PushShoppingList.services.ingredient_unit_service import display_unit
from PushShoppingList.services.image_variant_service import cover_image_variant_payload as build_cover_image_variant_payload
from PushShoppingList.services.image_variant_service import local_static_image_variants
from PushShoppingList.services.item_state_service import load_item_state
from PushShoppingList.services.item_state_service import save_item_manual_qty
from PushShoppingList.services.item_state_service import save_item_purchase_mapping
from PushShoppingList.services.pantry_service import pantry_items_for_view
from PushShoppingList.services.pantry_service import pantry_recipe_matches_for_view
from PushShoppingList.services.pantry_service import pantry_storage_location_options_for_view
from PushShoppingList.services.pantry_service import pantry_store_sections_for_view
from PushShoppingList.services.pantry_service import pantry_use_soon_items_for_view
from PushShoppingList.services.pantry_service import hydrate_receipt_review_dates
from PushShoppingList.services.pantry_service import receipt_history_for_view
from PushShoppingList.services.pdf_share_service import list_available_pdfs
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_item
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_for_recipe_ingredient
from PushShoppingList.services.purchase_mapping_service import purchase_mapping_lookup_for_items
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import recipe_edit_page_url
from PushShoppingList.services.recipe_url_service import canonicalize_private_recipe_url
from PushShoppingList.services.recipe_url_service import recipe_archive_pdf_url
from PushShoppingList.services.recipe_url_service import recipe_cover_image_url
from PushShoppingList.services.recipe_url_service import add_recipe_urls
from PushShoppingList.services.recipe_url_service import remove_recipe_url
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import remove_recipe_and_unused_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import save_ingredients_for_recipe
from PushShoppingList.services.recipe_ingredient_service import update_saved_recipe_purchase_mapping
from PushShoppingList.services.recipe_quantity_service import ingredient_key
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_exists
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import recipe_cover_image_file_path
from PushShoppingList.services.recipe_extract_service import normalize_recipe_note_sections
from PushShoppingList.services.recipe_extract_service import recipe_scaling_from_data
from PushShoppingList.services.recipe_extract_service import scaling_multiplier_label
from PushShoppingList.services.recipe_extract_service import supports_custom_temperature
from PushShoppingList.services.recipe_edit_service import is_shareable_pdf_public_url
from PushShoppingList.services.recipe_edit_service import PDF_KIND_GENERATED_RECIPE
from PushShoppingList.services.recipe_edit_service import PDF_KIND_WEBPAGE_BACKUP
from PushShoppingList.services.recipe_edit_service import normalize_recipe_pdf_storage_metadata
from PushShoppingList.services.recipe_edit_service import load_recipe_output
from PushShoppingList.services.recipe_edit_service import save_recipe_output
from PushShoppingList.services.recipe_edit_service import delete_generated_recipe_pdf_for_recipe_deletion
from PushShoppingList.services.product_selection_service import product_choices_by_item
from PushShoppingList.services.product_selection_service import store_price_cells_for_item
from PushShoppingList.services.rules_display_service import load_rules_display
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.shopping_list_service import save_items
from PushShoppingList.services.shopping_list_service import save_recipe_option_selections
from PushShoppingList.services.store_settings_service import clean_store_settings
from PushShoppingList.services.store_settings_service import load_store_settings
from PushShoppingList.services.firebase_auth_service import firebase_web_config
from PushShoppingList.services.openai_model_service import chatgpt_models_dashboard_for_user
from PushShoppingList.services.openai_model_service import refresh_lowest_viable_openai_model_recommendations
from PushShoppingList.services.openai_model_service import refresh_openai_model_recommendations
from PushShoppingList.services.openai_model_service import update_openai_model_settings_for_admin
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_usage_service import openai_usage_dashboard_for_user
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.menu_store_service import menu_pdf_logs_by_cookbook
from PushShoppingList.services.menu_store_service import menus_by_cookbook
from PushShoppingList.services.meal_plan_service import add_meal
from PushShoppingList.services.meal_plan_service import delete_meal
from PushShoppingList.services.meal_plan_service import load_meal_plan
from PushShoppingList.services.meal_plan_service import meal_plan_yield_label
from PushShoppingList.services.meal_plan_service import meal_plan_home_preview
from PushShoppingList.services.meal_plan_service import meal_plan_for_week
from PushShoppingList.services.meal_plan_service import normalize_planned_servings
from PushShoppingList.services.meal_plan_service import planned_servings_from_yield
from PushShoppingList.services.meal_plan_service import update_meal_ingredient_option_selections
from PushShoppingList.services.global_search_service import global_search
from PushShoppingList.services.global_search_service import ACTUAL_RECORD_GROUPS
from PushShoppingList.services.global_search_service import DEFAULT_RESULT_LIMIT
from PushShoppingList.services.global_search_service import GROUP_LABELS
from PushShoppingList.services.global_search_service import MAX_RESULT_LIMIT
from PushShoppingList.services.global_search_service import recent_global_search
from PushShoppingList.services.global_search_service import record_recent_global_search_result
from PushShoppingList.services.request_security_service import build_canonical_url
from PushShoppingList.services.request_security_service import validate_authenticated_viewer
from PushShoppingList.services.job_service import job_for_client
from PushShoppingList.services.job_service import recent_jobs
from PushShoppingList.services.legal_content import legal_document as get_legal_document
from PushShoppingList.services.storage_service import active_guest_session_id
from PushShoppingList.services.storage_service import active_user_id
from PushShoppingList.services.user_account_service import SUPPORT_ADMIN_EMAILS
from PushShoppingList.services.user_account_service import SUPPORT_EMAIL
from PushShoppingList.services.user_account_service import current_public_user
from PushShoppingList.services.user_account_service import is_admin_user
from PushShoppingList.services.user_account_service import load_users
from PushShoppingList.services.user_account_service import public_two_factor_recovery_user
from PushShoppingList.services.user_account_service import user_display_name
from PushShoppingList.services.admin_support_service import admin_support_dashboard_for_user
from PushShoppingList.services.admin_support_service import support_access_notices_for_user
from PushShoppingList.services.device_status_service import device_status_summary
from PushShoppingList.services.device_status_service import device_status_account_type_filter_options
from PushShoppingList.services.device_status_service import device_status_filter_options
from PushShoppingList.services.device_status_service import record_device_status_event

main_bp = Blueprint("main_bp", __name__)
address_openai_client = None
APP_LOCAL_DATE_COOKIE = "ai_pantry_local_date"
MASTER_DATA_PAGE_CONFIG = {
    "ingredients": {
        "title": "Ingredient Master Data",
        "nav_label": "Ingredients",
        "empty_label": "ingredients",
        "route_endpoint": "main_bp.master_data_ingredients_route",
        "list_func": recipe_master_data.list_ingredients,
        "count_func": recipe_master_data.count_ingredients,
    },
    "equipment": {
        "title": "Equipment Master Data",
        "nav_label": "Equipment",
        "empty_label": "equipment",
        "route_endpoint": "main_bp.master_data_equipment_route",
        "list_func": recipe_master_data.list_equipment,
        "count_func": recipe_master_data.count_equipment,
    },
}


def validate_master_data_viewer_scope():
    """Validate an optional viewer query value against the Flask session."""

    if hasattr(g, "master_data_viewer_user_id"):
        return g.master_data_viewer_user_id
    viewer_values = request.args.getlist("viewer_user_id")
    if len(viewer_values) > 1:
        abort(400)
    session_viewer_user_id = active_user_id()
    supplied_viewer_user_id = str(viewer_values[0]) if viewer_values else ""
    if supplied_viewer_user_id.strip() and (
        (
            session_viewer_user_id
            and supplied_viewer_user_id != session_viewer_user_id
        )
        or (is_guest_session() and not session_viewer_user_id)
    ):
        abort(403)

    g.master_data_viewer_user_id = session_viewer_user_id
    return session_viewer_user_id


@main_bp.before_request
def validate_optional_master_data_viewer_parameter():
    """Reject supplied viewer values that conflict with the signed session.

    Master-data URLs derive the viewer from the session. Legacy URLs may still
    supply the value, but it is never trusted and is removed canonically.
    """

    if not (
        request.path == "/admin/master-data"
        or request.path.startswith("/admin/master-data/")
        or request.path == "/api/master-data"
        or request.path.startswith("/api/master-data/")
    ):
        return None

    validate_master_data_viewer_scope()
    return None


def request_local_calendar_date():
    """Return the browser's local calendar date, with a host-local fallback."""
    if has_request_context():
        try:
            return date.fromisoformat(request.cookies.get(APP_LOCAL_DATE_COOKIE, ""))
        except (TypeError, ValueError):
            pass
    return date.today()


def static_asset_version(filename):
    try:
        return int(os.path.getmtime(os.path.join(current_app.static_folder, filename)))
    except OSError:
        return 1


def lightweight_cookbook_view():
    view = cookbook_view([])

    for cookbook in view.get("cookbooks", []):
        cookbook["recipe_count"] = len(cookbook.get("recipes", []))
        cookbook["recipes"] = []
        cookbook["menu_sections"] = {}

    view["recipes"] = []
    return view


def shared_page_context(active_public_user=None):
    active_public_user = active_public_user or current_public_user()
    admin_support_notices = support_access_notices_for_user(active_public_user, limit=2)
    admin_support_history = support_access_notices_for_user(active_public_user, limit=None)
    openai_usage_dashboard = openai_usage_dashboard_for_user(active_public_user)
    chatgpt_force_refresh = bool(session.pop("chatgpt_model_force_refresh", False))
    chatgpt_show_advanced = bool(session.get("chatgpt_model_show_advanced", False))
    chatgpt_models_dashboard = chatgpt_models_dashboard_for_user(
        active_public_user,
        show_advanced_models=chatgpt_show_advanced,
        force_refresh=chatgpt_force_refresh,
    )
    chatgpt_models_dashboard["messages"] = [
        *session.pop("chatgpt_model_messages", []),
        *chatgpt_models_dashboard.get("messages", []),
    ]

    two_factor_recovery_token = request.args.get("two_factor_recovery_token", "")

    return {
        "message": "",
        "feedback_dashboard": feedback_dashboard_for_user(active_public_user),
        "openai_usage_dashboard": openai_usage_dashboard,
        "chatgpt_models_dashboard": chatgpt_models_dashboard,
        "feedback_messages": session.pop("feedback_messages", []),
        "admin_support_dashboard": {
            "is_admin": is_admin_user(active_public_user),
            "users": [],
            "recent_audit": [],
            "device_status_events": [],
            "device_status_filter_options": [],
            "device_status_account_type_filter_options": [],
            "selected_user": None,
            "errors": [],
            "reason": session.get("admin_support_reason", ""),
        },
        "admin_support_notices": admin_support_notices,
        "admin_support_history": admin_support_history,
        "password_reset_token": request.args.get("reset_token", ""),
        "two_factor_recovery_token": two_factor_recovery_token,
        "two_factor_recovery_user": public_two_factor_recovery_user(two_factor_recovery_token),
        "account_delete_token": request.args.get("account_delete_token", ""),
        "app_css_version": static_asset_version("css/app.css"),
        "menu_builder_css_version": static_asset_version("css/menu_builder.css"),
        "app_js_version": static_asset_version("js/app.js"),
        "firebase_auth_js_version": static_asset_version("js/firebase-auth.js"),
        "firebase_web_config": firebase_web_config(),
        "support_public_config": {
            "supportEmail": SUPPORT_EMAIL,
            "supportAdminEmails": list(SUPPORT_ADMIN_EMAILS) if is_admin_user(active_public_user) else [],
        },
        "performance_diagnostics_enabled": (
            current_app.debug
            or os.getenv("SHOPPING_PERFORMANCE_DIAGNOSTICS", "").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
    }


def public_auth_page_context():
    """Return only the data needed by the signed-out authentication page."""
    two_factor_recovery_token = request.args.get("two_factor_recovery_token", "")

    return {
        "app_public_auth": True,
        "password_reset_token": request.args.get("reset_token", ""),
        "two_factor_recovery_token": two_factor_recovery_token,
        "two_factor_recovery_user": public_two_factor_recovery_user(two_factor_recovery_token),
        "account_delete_token": request.args.get("account_delete_token", ""),
        "app_css_version": static_asset_version("css/app.css"),
        "app_js_version": static_asset_version("js/app.js"),
        "public_auth_js_version": static_asset_version("js/public-auth.js"),
        "firebase_auth_js_version": static_asset_version("js/firebase-auth.js"),
        "firebase_web_config": firebase_web_config(),
        "support_email": SUPPORT_EMAIL,
        "support_public_config": {
            "supportEmail": SUPPORT_EMAIL,
            "supportAdminEmails": [],
        },
    }


def legal_page_context(slug):
    """Return shared context for a public legal document."""
    document = get_legal_document(slug)
    endpoint = "main_bp.terms_route" if slug == "terms" else "main_bp.privacy_route"

    return {
        "app_public_auth": True,
        "app_css_version": static_asset_version("css/app.css"),
        "public_auth_js_version": static_asset_version("js/public-auth.js"),
        "legal_document": document,
        "support_email": SUPPORT_EMAIL,
        "canonical_url": url_for(endpoint, _external=True),
        "account_deletion_url": url_for("main_bp.index", _anchor="settingsDangerZonePanel"),
    }


def recipe_rows_context(recipe_urls=None, food_rules=None, image_variants=None, include_detail_images=True):
    recipe_urls = recipe_urls if recipe_urls is not None else recipe_url_rows()
    food_rules = food_rules if food_rules is not None else load_food_rules()
    recipe_rows = recipe_view_rows(
        recipe_urls,
        food_rules=food_rules,
        image_variants=image_variants,
        include_detail_images=include_detail_images,
    )
    ensure_unclassified_cookbook_for_recipes(recipe_rows)
    cookbook_assignments = recipe_cookbook_assignments()
    apply_cookbook_assignments_to_recipe_rows(recipe_rows, cookbook_assignments)
    rendered_cookbook_view = cookbook_view_for_render(
        recipe_rows,
        food_rules=food_rules,
        image_variants=image_variants,
    )
    attach_restaurant_menu_assets_to_cookbooks(rendered_cookbook_view)
    cookbook_recipe_count = sum(
        len(cookbook.get("recipes", []))
        for cookbook in rendered_cookbook_view.get("cookbooks", [])
    )

    return {
        "recipe_urls": recipe_urls,
        "food_rules": food_rules,
        "recipe_view_rows": recipe_rows,
        "cookbook_view": rendered_cookbook_view,
        "cookbook_count": len(rendered_cookbook_view.get("cookbooks", [])),
        "cookbook_recipe_count": cookbook_recipe_count,
        "cookbook_assignments": cookbook_assignments,
    }


def attach_restaurant_menu_assets_to_cookbooks(rendered_cookbook_view):
    logs_by_cookbook = menu_pdf_logs_by_cookbook()
    menus_grouped = menus_by_cookbook()

    for cookbook in rendered_cookbook_view.get("cookbooks", []):
        cookbook_id = cookbook.get("id", "")
        cookbook["menu_pdf_logs"] = logs_by_cookbook.get(cookbook_id, [])
        cookbook["restaurant_menus"] = menus_grouped.get(cookbook_id, [])

    return rendered_cookbook_view


def recipe_workspace_context(image_variants=None, include_detail_images=True):
    recipe_context = recipe_rows_context(
        image_variants=image_variants,
        include_detail_images=include_detail_images,
    )
    recipe_log_rows = recipe_url_log_rows(
        recipe_context["recipe_urls"],
        recipe_context["cookbook_assignments"],
        food_rules=recipe_context["food_rules"],
        image_variants=image_variants,
    )

    return {
        **recipe_context,
        "current_urls": recipe_log_rows,
        "current_recipe_count": len(recipe_log_rows),
    }


def current_recipes_context():
    recipe_urls = recipe_url_rows()
    food_rules = load_food_rules()
    current_rows = recipe_url_log_rows(
        recipe_urls,
        food_rules=food_rules,
        image_variants=("thumb",),
    )
    ensure_unclassified_cookbook_for_recipes(current_rows)
    cookbook_assignments = recipe_cookbook_assignments()
    apply_cookbook_assignments_to_recipe_rows(current_rows, cookbook_assignments)
    cookbook_view_data = lightweight_cookbook_view()

    return {
        "recipe_urls": recipe_urls,
        "food_rules": food_rules,
        "current_urls": current_rows,
        "current_recipe_count": len(current_rows),
        "cookbook_view": cookbook_view_data,
        "cookbook_count": len(cookbook_view_data.get("cookbooks", [])),
        "cookbook_recipe_count": sum(
            len(cookbook.get("recipes", []))
            for cookbook in cookbook_view_data.get("cookbooks", [])
        ),
        "ingredient_unit_config": unit_registry_payload(),
        "ingredient_type_config": ingredient_types.ingredient_type_registry_payload(),
    }


def cookbooks_context():
    return recipe_rows_context(
        image_variants=("thumb", "card"),
        include_detail_images=False,
    )


def shopping_views_context():
    items = load_items()
    item_state = load_item_state()
    store_settings = load_store_settings()
    product_choices = product_choices_by_item()
    recipe_context = recipe_rows_context(
        image_variants=("thumb", "card", "detail"),
        include_detail_images=True,
    )
    recipe_rows = recipe_context["recipe_view_rows"]
    purchase_mappings = purchase_mapping_lookup_for_items(shopping_items_only(items), item_state)
    recipe_item_quantities = recipe_quantity_lookup(recipe_rows)
    recipe_item_quantity_sources = recipe_quantity_sources_lookup(recipe_rows)
    item_quantities = apply_manual_item_quantities(
        recipe_item_quantities,
        item_state,
    )

    return {
        **recipe_context,
        "items": items,
        "shopping_items": shopping_items_only(items),
        "purchase_mappings": purchase_mappings,
        "item_state": item_state,
        "item_quantities": item_quantities,
        "recipe_item_quantities": recipe_item_quantities,
        "recipe_item_quantity_sources": recipe_item_quantity_sources,
        "section_counts": section_counts(items),
        "store_view": build_store_view(
            items,
            item_state,
            store_settings["stores"],
            store_settings["enabled_stores"],
        ),
        "available_stores": store_settings["stores"],
        "enabled_stores": store_settings["enabled_stores"],
        "product_choices": product_choices,
        "item_store_price_cells": store_price_cells_for_item,
        "normalize": normalize,
        "is_section_header": is_section_header,
        "food_rule_status": lambda item_name: shopping_item_food_rule_status(
            item_name,
            rules=recipe_context["food_rules"],
        ),
    }


def store_options_context():
    store_settings = load_store_settings()
    can_edit_workspace_stores = bool(current_public_user() or is_guest_session())

    if not can_edit_workspace_stores:
        store_settings = clean_store_settings(store_settings)

    nearest_store_results = load_nearest_store_results()

    return {
        "home_address": load_home_address(),
        "home_address_history": load_home_address_history(),
        "nearest_store_results": nearest_store_results,
        "nearest_store_locations": nearest_store_results.get("store_locations", {}),
        "nearest_store_search_radius_miles": format_store_search_radius(
            nearest_store_results.get("search_radius_miles", DEFAULT_STORE_SEARCH_RADIUS_MILES)
        ),
        "available_stores": store_settings["stores"],
        "enabled_stores": store_settings["enabled_stores"],
        "can_toggle_stores": can_edit_workspace_stores,
        "can_edit_store_credentials": can_edit_workspace_stores,
        "store_options_public_view": not can_edit_workspace_stores,
    }


def rules_context():
    store_settings = load_store_settings()
    food_rules = load_food_rules()

    return {
        "home_address": load_home_address(),
        "available_stores": store_settings["stores"],
        "enabled_stores": store_settings["enabled_stores"],
        "food_rules": food_rules,
        "rules_display": load_rules_display(),
    }


def pantry_context():
    recipe_context = recipe_rows_context(
        image_variants=("thumb",),
        include_detail_images=False,
    )
    pantry_items = pantry_items_for_view()
    pantry_storage_locations = pantry_storage_location_options_for_view()
    pantry_receipt_review = hydrate_receipt_review_dates(session.get("pantry_receipt_review", {}))
    if pantry_receipt_review.get("candidates"):
        session["pantry_receipt_review"] = pantry_receipt_review

    return {
        **recipe_context,
        "pantry_items": pantry_items,
        "pantry_storage_locations": pantry_storage_locations,
        "pantry_has_removable_storage_locations": any(
            option.get("removable") for option in pantry_storage_locations
        ),
        "pantry_storage_location_values": [
            option["value"] for option in pantry_storage_locations
        ],
        "pantry_store_sections": pantry_store_sections_for_view(),
        "pantry_use_soon_items": pantry_use_soon_items_for_view(),
        "pantry_recipe_matches": pantry_recipe_matches_for_view(
            recipe_context["recipe_view_rows"],
            pantry_items,
        ),
        "pantry_receipt_review": pantry_receipt_review,
        "pantry_receipt_history": receipt_history_for_view(),
        "pantry_messages": session.pop("pantry_messages", []),
    }


def meal_plan_recipe_option_rows(recipe_urls, recipe_ingredient_data=None):
    recipe_ingredient_data = (
        recipe_ingredient_data
        if isinstance(recipe_ingredient_data, dict)
        else load_recipe_ingredients()
    )
    options = []

    for recipe in recipe_urls or []:
        if not isinstance(recipe, dict):
            continue
        recipe_url = str(recipe.get("url") or "").strip()
        if not recipe_url:
            continue

        recipe_key = normalize_recipe_url_key(recipe_url)
        recipe_meta = recipe_ingredient_data.get(recipe_key, {})
        recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
        recipe_data = load_saved_recipe_output(recipe_url)
        scaling = recipe_scaling_from_data(recipe_data, default_to_common=False) or {}
        raw_scaling = (
            recipe_data.get("scaling")
            if isinstance(recipe_data.get("scaling"), dict)
            else {}
        )
        recipe_yield = (
            recipe_data.get("servings")
            or raw_scaling.get("base_servings")
            or scaling.get("base_servings")
            or recipe_meta.get("base_servings")
            or recipe_meta.get("servings")
            or recipe.get("base_servings")
            or recipe.get("servings")
        )
        options.append({
            "url": recipe_url,
            "name": str(
                recipe.get("name")
                or recipe.get("title")
                or recipe_url
                or "Recipe"
            ).strip(),
            "default_servings": planned_servings_from_yield(recipe_yield) or 1,
            "yield_label": meal_plan_yield_label(recipe_yield),
            "ingredient_requirements": [
                public_requirement(requirement)
                for requirement in ingredient_requirements(recipe_data)
                if requirement["selection_required"]
            ],
        })

    return options


def shell_context(active_public_user=None):
    items = load_items()
    recipe_urls = recipe_url_rows()
    recipe_ingredient_data = load_recipe_ingredients()
    recipe_cookbook_index = cookbook_recipe_index()
    cookbook_assignments = recipe_cookbook_index.get("assignments", {})
    active_recipe_keys = {
        normalize_recipe_url_key(recipe.get("url"))
        for recipe in recipe_urls
        if isinstance(recipe, dict) and normalize_recipe_url_key(recipe.get("url"))
    }
    recipe_preview_rows = recipe_url_log_rows(
        recipe_urls[:8],
        cookbook_assignments,
        image_variants=("card", "thumb"),
        recipe_ingredient_data=recipe_ingredient_data,
    )
    cookbook_records_by_key = recipe_cookbook_index.get("records_by_key", {})
    for recipe in recipe_preview_rows:
        recipe_key = normalize_recipe_url_key(recipe.get("url"))
        cookbook_record = cookbook_records_by_key.get(recipe_key, {})
        recipe["home_badge"] = recipe_home_badge_label(recipe, cookbook_record)
        recipe["home_preview_time"] = recipe_home_preview_time_label(recipe)
        recipe["card_cook_time"] = recipe_card_cook_time_label(recipe)
        recipe["card_calories"] = recipe_card_calories_label(recipe.get("calories"))
    cookbook_view_data = lightweight_cookbook_view()
    store_settings = load_store_settings()
    pantry_items = pantry_items_for_view()
    local_calendar_date = request_local_calendar_date()
    requested_meal_week = str(request.args.get("meal_week") or "").strip()
    meal_plan = meal_plan_for_week(
        requested_meal_week,
        reference_date=local_calendar_date,
    )
    home_meal_plan = meal_plan_home_preview(reference_date=local_calendar_date)
    home_preview_meals = [
        meal
        for slot in home_meal_plan["slots"]
        for meal in slot["meals"]
    ]
    recipe_options = meal_plan_recipe_option_rows(
        recipe_urls,
        recipe_ingredient_data=recipe_ingredient_data,
    )
    planned_recipe_keys = {
        normalize_recipe_url_key(meal.get("recipe_url"))
        for meal in [*meal_plan["meals"], *home_preview_meals]
        if normalize_recipe_url_key(meal.get("recipe_url"))
    }
    preview_recipe_keys = {
        normalize_recipe_url_key(recipe.get("url"))
        for recipe in recipe_preview_rows
        if normalize_recipe_url_key(recipe.get("url"))
    }
    missing_planned_recipe_keys = planned_recipe_keys - preview_recipe_keys
    planned_recipe_rows = [
        recipe
        for recipe in recipe_urls
        if normalize_recipe_url_key(recipe.get("url")) in missing_planned_recipe_keys
    ]
    planned_preview_rows = (
        recipe_url_log_rows(
            planned_recipe_rows,
            cookbook_assignments,
            image_variants=("card", "thumb"),
            recipe_ingredient_data=recipe_ingredient_data,
        )
        if planned_recipe_rows
        else []
    )
    recipe_preview_by_key = {
        normalize_recipe_url_key(recipe.get("url")): recipe
        for recipe in [*recipe_preview_rows, *planned_preview_rows]
        if normalize_recipe_url_key(recipe.get("url"))
    }
    for meal in [*meal_plan["meals"], *home_preview_meals]:
        preview = recipe_preview_by_key.get(normalize_recipe_url_key(meal["recipe_url"]), {})
        meal["cover_image"] = preview.get("cover_image") or {}
        linked_recipe_url = str(preview.get("url") or "").strip()
        meal["edit_url"] = recipe_edit_page_url(linked_recipe_url)

    pantry_running_low = [
        item
        for item in pantry_items
        if str(item.get("status") or "").lower() in {"running low", "low", "out of stock"}
        or item.get("running_low")
    ]
    pantry_expiring_soon = [
        item
        for item in pantry_items
        if (item.get("lifecycle_status") or {}).get("urgency")
        in {"expired", "urgent", "soon"}
    ]
    pantry_out_of_stock = [
        item
        for item in pantry_items
        if str(item.get("status") or "").lower() == "out of stock"
    ]
    actor_user_id = str((active_public_user or {}).get("user_id") or "").strip()
    actor_guest_session_id = str(active_guest_session_id() or "").strip()
    home_recent_imports = []
    if actor_user_id or actor_guest_session_id:
        home_recent_imports = home_recent_import_rows([
            job_for_client(
                job,
                existing_recipe_urls=[
                    recipe.get("url")
                    for recipe in recipe_urls
                    if isinstance(recipe, dict) and recipe.get("url")
                ],
            )
            for job in recent_jobs(
                user_id=actor_user_id,
                guest_session_id=actor_guest_session_id,
                limit=100,
            )
        ])

    return {
        **shared_page_context(active_public_user),
        "raw_items": "\n".join(items),
        "items": items,
        "recipe_preview_rows": recipe_preview_rows,
        "home_recent_imports": home_recent_imports,
        "recipe_collection_breakdown": recipe_collection_breakdown(
            recipe_urls,
            records_by_key=recipe_cookbook_index.get("records_by_key", {}),
        ),
        "recipe_top_ingredients": recipe_top_ingredient_rows(
            recipe_urls,
            recipe_ingredient_data=recipe_ingredient_data,
        ),
        "current_recipe_count": len(recipe_urls),
        "cookbook_view": cookbook_view_data,
        "cookbook_count": len(cookbook_view_data.get("cookbooks", [])),
        "cookbook_recipe_count": sum(
            1 for recipe_key in active_recipe_keys if recipe_key in cookbook_assignments
        ),
        "available_stores": store_settings["stores"],
        "enabled_stores": store_settings["enabled_stores"],
        "home_address": load_home_address(),
        "home_address_history": load_home_address_history(),
        "pdf_share_view": {"pdfs": []},
        "pantry_preview_items": pantry_items[:5],
        "pantry_use_soon_items": pantry_expiring_soon[:5],
        "pantry_summary": {
            "total": len(pantry_items),
            "running_low": len(pantry_running_low),
            "expiring_soon": len(pantry_expiring_soon),
            "out_of_stock": len(pantry_out_of_stock),
        },
        "meal_plan": meal_plan,
        "home_meal_plan": home_meal_plan,
        "meal_plan_recipe_options": recipe_options,
        "initial_app_page": "mealPlannerPage" if requested_meal_week else "",
    }


def admin_support_context(active_public_user=None):
    active_public_user = active_public_user or current_public_user()
    dashboard = admin_support_dashboard_for_user(
        active_public_user,
        selected_user=session.get("admin_support_selected_user"),
        errors=session.pop("admin_support_errors", []),
        reason=session.get("admin_support_reason", ""),
    )
    if dashboard.get("is_admin"):
        dashboard["device_status_events"] = device_status_summary()
        dashboard["device_status_filter_options"] = device_status_filter_options(
            dashboard["device_status_events"]
        )
        dashboard["device_status_account_type_filter_options"] = device_status_account_type_filter_options(
            dashboard["device_status_events"]
        )

    return {
        **shared_page_context(active_public_user),
        "admin_support_dashboard": dashboard,
    }


def int_query_arg(name, default, minimum=None, maximum=None):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)

    return value


def master_data_short_user_id(user_id):
    user_id = str(user_id or "").strip()
    if len(user_id) <= 18:
        return user_id
    return f"{user_id[:10]}...{user_id[-6:]}"


def master_data_user_identity(user_id, user=None):
    user_id = str(user_id or "").strip()
    short_id = master_data_short_user_id(user_id)
    email = str((user or {}).get("email") or "").strip()

    if user:
        display_name = user_display_name(user) or email or str(user.get("username") or "").strip() or user_id
    elif user_id == recipe_master_data.LOCAL_USER_ID:
        display_name = "Local recipe data"
    elif user_id.startswith("guest:"):
        display_name = "Guest session"
    elif user_id:
        display_name = "Unknown user"
    else:
        display_name = "Unknown user"

    email_detail = email if email.lower() != display_name.lower() else ""
    label_parts = [part for part in (display_name, email_detail, short_id) if part]
    return {
        "user_id": user_id,
        "short_id": short_id,
        "display_name": display_name,
        "email": email,
        "email_detail": email_detail,
        "label": " - ".join(label_parts),
    }


def master_data_user_identity_lookup(user_ids):
    normalized_ids = {
        str(user_id or "").strip()
        for user_id in user_ids
        if str(user_id or "").strip()
    }
    users_by_id = {
        str(user.get("user_id") or ""): user
        for user in load_users().get("users", [])
        if isinstance(user, dict) and str(user.get("user_id") or "")
    }
    return {
        user_id: master_data_user_identity(user_id, users_by_id.get(user_id))
        for user_id in sorted(normalized_ids)
    }


def enrich_master_data_rows_with_users(rows, user_identities):
    enriched = []
    for row in rows:
        row_data = dict(row)
        user_id = str(row_data.get("user_id") or "").strip()
        row_data["user_identity"] = user_identities.get(user_id) or master_data_user_identity(user_id)
        enriched.append(row_data)
    return enriched


MASTER_DATA_PAGE_ENDPOINTS = {
    "ingredients": "main_bp.master_data_ingredients_route",
    "equipment": "main_bp.master_data_equipment_route",
    "units": "main_bp.master_data_units_route",
    "types": "main_bp.master_data_types_route",
    "store_sections": "main_bp.master_data_store_sections_route",
}


def master_data_query_values(values, name):
    if hasattr(values, "getlist"):
        return list(values.getlist(name))
    if isinstance(values, dict):
        value = values.get(name)
        return list(value) if isinstance(value, (list, tuple)) else [value] if value is not None else []

    found = []
    for key, value in values or ():
        if str(key) == name:
            found.append(value)
    return found


def master_data_registered_user_ids():
    return {
        str(user.get("user_id") or "")
        for user in load_users().get("users", [])
        if isinstance(user, dict) and str(user.get("user_id") or "")
    }


def validate_master_data_target_scope(is_admin, values=None, *, allow_admin_scope=True):
    """Resolve an optional admin target without changing viewer authority."""

    values = request.args if values is None else values
    target_values = master_data_query_values(values, "user_id")
    if len(target_values) > 1:
        abort(400)

    current_scope_user_id = recipe_master_data.scoped_recipe_user_id()
    requested_user_id = str(target_values[0] or "").strip() if target_values else ""
    requested_scope = str(
        (master_data_query_values(values, "scope") or ["mine"])[0] or "mine"
    ).strip().lower()
    scope_was_supplied = bool(master_data_query_values(values, "scope"))

    mine = {
        "user_id": current_scope_user_id,
        "include_all_users": False,
        "scope": "mine",
        "current_scope_user_id": current_scope_user_id,
    }
    if not is_admin or not allow_admin_scope:
        return mine

    if requested_scope == "all":
        return {
            "user_id": "",
            "include_all_users": True,
            "scope": "all",
            "current_scope_user_id": current_scope_user_id,
        }

    # Before explicit scopes were introduced, generated admin bookmarks used
    # only ?user_id=<target>. Preserve those bookmarks without making user_id
    # authoritative for non-admin sessions.
    legacy_user_scope = bool(requested_user_id and not scope_was_supplied)
    if requested_scope == "user" or legacy_user_scope:
        if not requested_user_id or requested_user_id not in master_data_registered_user_ids():
            abort(400)
        return {
            "user_id": requested_user_id,
            "include_all_users": False,
            "scope": "user",
            "current_scope_user_id": current_scope_user_id,
        }

    return mine


def master_data_scope(is_admin):
    return validate_master_data_target_scope(is_admin, request.args)


def build_canonical_master_data_url(
    page,
    *,
    parameters=None,
    scope_info=None,
    overrides=None,
):
    scope_info = scope_info or {
        "scope": "mine",
        "user_id": recipe_master_data.scoped_recipe_user_id(),
    }
    viewer_user_id = str(scope_info.get("viewer_user_id") or active_user_id() or "")
    if is_guest_session():
        viewer_user_id = ""
    return master_data_url_service.build_master_data_url(
        page,
        parameters=parameters,
        viewer_user_id=viewer_user_id,
        scope=scope_info.get("scope") or "mine",
        target_user_id=(
            scope_info.get("user_id")
            if scope_info.get("scope") == "user"
            else ""
        ),
        overrides=overrides,
        base_path=url_for(MASTER_DATA_PAGE_ENDPOINTS[page]),
    )


def canonicalize_master_data_redirect_url(
    redirect_url,
    *,
    default_page="ingredients",
    fallback_scope_info=None,
):
    """Return a safe canonical page URL for mutation responses."""

    raw_url = str(redirect_url or "").strip()
    parsed = urlparse(raw_url)
    page_by_path = {
        url_for(endpoint): page
        for page, endpoint in MASTER_DATA_PAGE_ENDPOINTS.items()
    }
    page = page_by_path.get(parsed.path) if not parsed.scheme and not parsed.netloc else None
    parameters = parse_qsl(parsed.query, keep_blank_values=True) if page else None

    if page:
        scope_info = validate_master_data_target_scope(
            is_admin_user(current_public_user()),
            parameters,
            allow_admin_scope=page not in {"store_sections", "units", "types"},
        )
    else:
        page = default_page
        scope_info = fallback_scope_info or {
            "scope": "mine",
            "user_id": recipe_master_data.scoped_recipe_user_id(),
            "current_scope_user_id": recipe_master_data.scoped_recipe_user_id(),
        }

    scope_info = dict(scope_info)
    scope_info["viewer_user_id"] = active_user_id()
    return build_canonical_master_data_url(
        page,
        parameters=parameters,
        scope_info=scope_info,
    )


def validate_canonical_master_data_page_request(page, *, allow_admin_scope=True):
    """Validate the viewer and return the canonical target scope/redirect."""

    session_viewer_user_id = validate_master_data_viewer_scope()

    active_public_user = current_public_user()
    scope_info = validate_master_data_target_scope(
        is_admin_user(active_public_user),
        request.args,
        allow_admin_scope=allow_admin_scope,
    )
    scope_info["viewer_user_id"] = session_viewer_user_id

    canonical_url = build_canonical_master_data_url(
        page,
        parameters=request.args,
        scope_info=scope_info,
    )
    requested_url = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    if requested_url != canonical_url:
        return scope_info, redirect(canonical_url)
    return scope_info, None


def ingredient_duplicate_review_workspace(active_public_user, values):
    values = values if isinstance(values, dict) or hasattr(values, "get") else {}
    scope_info = validate_master_data_target_scope(
        is_admin_user(active_public_user),
        values,
    )
    return "" if scope_info["scope"] == "all" else scope_info["user_id"]


def master_data_form_scope():
    scope_info = validate_master_data_target_scope(
        is_admin_user(current_public_user()),
        request.form,
    )
    scope_info["viewer_user_id"] = active_user_id()
    return scope_info


def master_data_context(record_type, scope_info=None):
    config = MASTER_DATA_PAGE_CONFIG[record_type]
    active_public_user = current_public_user()
    is_admin = is_admin_user(active_public_user)
    status = recipe_master_data.recipe_master_db_status()
    search = recipe_master_data.clean_text(request.args.get("search"))
    sort = str(request.args.get("sort") or "updated_at_desc").strip()
    if sort not in recipe_master_data.MASTER_RECORD_SORTS:
        sort = "updated_at_desc"
    limit = int_query_arg("limit", 100, minimum=1, maximum=500)
    page = int_query_arg("page", 1, minimum=1)
    offset = (page - 1) * limit
    scope_info = scope_info or master_data_scope(is_admin)
    store_section = ""
    store_section_details = []
    if record_type == "ingredients":
        store_section_details = recipe_master_data.ingredient_store_section_details(
            user_id=scope_info["user_id"] or scope_info["current_scope_user_id"],
        )
        store_section = recipe_master_data.ingredient_store_section_from_source(
            request.args.get("store_section"),
            user_id=scope_info["user_id"] or scope_info["current_scope_user_id"],
        )
    equipment_section = ""
    if record_type == "equipment":
        equipment_section = recipe_master_data.equipment_section_from_source(
            request.args.get("equipment_section")
        )

    rows = []
    total_count = 0
    available_user_ids = []
    if status["exists"]:
        rows = config["list_func"](
            user_id=scope_info["user_id"],
            search=search,
            limit=limit,
            offset=offset,
            sort=sort,
            include_all_users=scope_info["include_all_users"],
            store_section=store_section if record_type == "ingredients" else None,
            equipment_section=equipment_section if record_type == "equipment" else None,
        )
        total_count = config["count_func"](
            user_id=scope_info["user_id"],
            search=search,
            include_all_users=scope_info["include_all_users"],
            store_section=store_section if record_type == "ingredients" else None,
            equipment_section=equipment_section if record_type == "equipment" else None,
        )
        if is_admin:
            registered_user_ids = master_data_registered_user_ids()
            available_user_ids = [
                user_id
                for user_id in recipe_master_data.recipe_master_user_ids()
                if user_id in registered_user_ids
            ]

    latest_ingredient_merge = None
    latest_store_section_reclassification = None
    if (
        status["exists"]
        and record_type == "ingredients"
        and scope_info["scope"] != "all"
        and scope_info["user_id"]
    ):
        latest_ingredient_merge = recipe_master_data.latest_undoable_ingredient_merge(
            scope_info["user_id"]
        )
        latest_store_section_reclassification = (
            recipe_master_data.latest_undoable_ingredient_store_section_reclassification(
                scope_info["user_id"]
            )
        )

    total_pages = max(1, (total_count + limit - 1) // limit)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * limit
        if total_count:
            rows = config["list_func"](
                user_id=scope_info["user_id"],
                search=search,
                limit=limit,
                offset=offset,
                sort=sort,
                include_all_users=scope_info["include_all_users"],
                store_section=store_section if record_type == "ingredients" else None,
                equipment_section=equipment_section if record_type == "equipment" else None,
            )

    user_ids_for_labels = set(available_user_ids)
    user_ids_for_labels.update(str(row.get("user_id") or "").strip() for row in rows)
    user_ids_for_labels.add(scope_info["current_scope_user_id"])
    if scope_info["user_id"]:
        user_ids_for_labels.add(scope_info["user_id"])
    user_identities = master_data_user_identity_lookup(user_ids_for_labels)
    rows = enrich_master_data_rows_with_users(rows, user_identities)
    available_users = [
        user_identities.get(str(user_id or "").strip()) or master_data_user_identity(user_id)
        for user_id in available_user_ids
    ]
    current_scope_user = (
        user_identities.get(scope_info["current_scope_user_id"])
        or master_data_user_identity(scope_info["current_scope_user_id"])
    )
    scope_user = (
        user_identities.get(scope_info["user_id"])
        or master_data_user_identity(scope_info["user_id"])
    )

    endpoint = config["route_endpoint"]
    page_name = record_type
    canonical_overrides = {
        "search": search or None,
        "sort": sort,
        "limit": limit,
        "store_section": store_section if record_type == "ingredients" else None,
        "equipment_section": equipment_section if record_type == "equipment" else None,
    }
    prev_url = None
    next_url = None
    if page > 1:
        prev_url = build_canonical_master_data_url(
            page_name,
            parameters=request.args,
            scope_info=scope_info,
            overrides={**canonical_overrides, "page": page - 1},
        )
    if page < total_pages:
        next_url = build_canonical_master_data_url(
            page_name,
            parameters=request.args,
            scope_info=scope_info,
            overrides={**canonical_overrides, "page": page + 1},
        )
    current_url = build_canonical_master_data_url(
        page_name,
        parameters=request.args,
        scope_info=scope_info,
        overrides={
            **canonical_overrides,
            "page": page if page > 1 else None,
        },
    )

    ingredient_url = build_canonical_master_data_url(
        "ingredients",
        parameters=request.args,
        scope_info=scope_info,
        overrides={"equipment_section": None},
    )
    equipment_url = build_canonical_master_data_url(
        "equipment",
        parameters=request.args,
        scope_info=scope_info,
        overrides={"store_section": None},
    )
    store_section_url = build_canonical_master_data_url(
        "store_sections",
        scope_info={
            "scope": "mine",
            "user_id": scope_info["current_scope_user_id"],
            "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
        },
    )
    units_url = build_canonical_master_data_url(
        "units",
        scope_info={
            "scope": "mine",
            "user_id": scope_info["current_scope_user_id"],
            "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
        },
    )
    types_url = build_canonical_master_data_url(
        "types",
        scope_info={
            "scope": "mine",
            "user_id": scope_info["current_scope_user_id"],
            "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
        },
    )

    row_groups = []
    if record_type == "ingredients" and rows and not store_section:
        for section_detail in store_section_details:
            section = section_detail["section_key"]
            section_rows = [
                row
                for row in rows
                if recipe_master_data.clean_ingredient_store_section(
                    row.get("store_section"),
                    user_id=row.get("user_id"),
                ) == section
            ]
            if section_rows:
                default_display_name = (
                    recipe_master_data.INGREDIENT_STORE_SECTION_DISPLAY_NAMES.get(section)
                )
                display_name = section_detail["display_name"]
                row_groups.append({
                    "section": (
                        section
                        if display_name == default_display_name
                        else display_name
                    ),
                    "section_key": section,
                    "rows": section_rows,
                })
    elif record_type == "equipment" and rows and not equipment_section:
        for section in recipe_master_data.equipment_section_options():
            section_rows = [
                row
                for row in rows
                if recipe_master_data.clean_equipment_section(row.get("equipment_section")) == section
            ]
            if section_rows:
                row_groups.append({
                    "section": section,
                    "rows": section_rows,
                })

    return {
        "record_type": record_type,
        "title": config["title"],
        "nav_label": config["nav_label"],
        "empty_label": config["empty_label"],
        "route_endpoint": endpoint,
        "rows": rows,
        "row_groups": row_groups,
        "total_count": total_count,
        "page": page,
        "total_pages": total_pages,
        "limit": limit,
        "offset": offset,
        "search": search,
        "sort": sort,
        "store_section": store_section,
        "store_section_options": [
            section["section_key"]
            for section in store_section_details
        ],
        "store_section_labels": {
            section["section_key"]: section["display_name"]
            for section in store_section_details
        },
        "equipment_section": equipment_section,
        "equipment_section_options": recipe_master_data.equipment_section_options()
        if record_type == "equipment"
        else [],
        "group_by_store_section": bool(record_type == "ingredients" and not store_section),
        "group_by_equipment_section": bool(record_type == "equipment" and not equipment_section),
        "table_column_count": (
            5
            if record_type == "ingredients" and scope_info["scope"] == "all"
            else 4
            if record_type == "ingredients"
            else 6
            if scope_info["scope"] == "all"
            else 5
        ),
        "sort_options": [
            {"value": "updated_at_desc", "label": "Updated At"},
            {"value": "usage_count_desc", "label": "Usage Count"},
            {"value": "name_asc", "label": "Name"},
        ],
        "limit_options": [50, 100, 250, 500],
        "db_status": status,
        "is_admin": is_admin,
        "scope": scope_info["scope"],
        "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
        "scope_user_id": scope_info["user_id"],
        "current_scope_user_id": scope_info["current_scope_user_id"],
        "available_user_ids": available_user_ids,
        "available_users": available_users,
        "current_scope_user": current_scope_user,
        "scope_user": scope_user,
        "messages": session.pop("recipe_master_data_messages", []),
        "ingredient_url": ingredient_url,
        "equipment_url": equipment_url,
        "units_url": units_url,
        "types_url": types_url,
        "store_section_url": store_section_url,
        "backfill_status_url": url_for("main_bp.recipe_master_data_backfill_status_route"),
        "image_generation_url": url_for("main_bp.recipe_master_data_generate_missing_images_route"),
        "image_generation_status_url": url_for("main_bp.recipe_master_data_image_generation_status_route"),
        "ingredient_duplicate_scan_url": url_for("main_bp.ingredient_duplicate_scan_route"),
        "ingredient_duplicate_reviews_url": url_for("main_bp.ingredient_duplicate_reviews_route"),
        "ingredient_duplicate_review_history_url": url_for(
            "main_bp.ingredient_duplicate_review_history_route"
        ),
        "ingredient_duplicate_decision_url": url_for(
            "main_bp.ingredient_duplicate_decision_route",
            review_id=0,
        ),
        "ingredient_duplicate_ai_second_opinion_url": url_for(
            "main_bp.ingredient_duplicate_ai_second_opinion_route",
            review_id=0,
        ),
        "ingredient_duplicate_bulk_decision_url": url_for(
            "main_bp.ingredient_duplicate_bulk_decision_route"
        ),
        "ingredient_duplicate_restore_decision_url": url_for(
            "main_bp.ingredient_duplicate_restore_decision_route",
            review_id=0,
        ),
        "ingredient_merge_undo_url": url_for(
            "main_bp.undo_ingredient_master_merge_route"
        ),
        "ingredient_merge_undo_preview_url": url_for(
            "main_bp.preview_ingredient_master_merge_undo_route"
        ),
        "latest_ingredient_merge": latest_ingredient_merge,
        "ingredient_store_section_undo_url": url_for(
            "main_bp.undo_misc_ingredient_reclassification_route"
        ),
        "latest_store_section_reclassification": latest_store_section_reclassification,
        "ingredient_reference_url": url_for(
            "main_bp.master_data_record_references_route",
            record_type="ingredients",
            record_id=0,
        ),
        "current_url": current_url,
        "prev_url": prev_url,
        "next_url": next_url,
    }


def render_master_data_page(record_type, scope_info):
    return render_template(
        "master_data.html",
        master_data=master_data_context(record_type, scope_info),
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
        master_data_js_version=static_asset_version("js/master-data.js"),
    )


@main_bp.route("/admin/master-data/ingredients")
def master_data_ingredients_route():
    scope_info, canonical_redirect = validate_canonical_master_data_page_request("ingredients")
    if canonical_redirect:
        return canonical_redirect
    return render_master_data_page("ingredients", scope_info)


@main_bp.route("/admin/master-data/equipment")
def master_data_equipment_route():
    scope_info, canonical_redirect = validate_canonical_master_data_page_request("equipment")
    if canonical_redirect:
        return canonical_redirect
    return render_master_data_page("equipment", scope_info)


def unit_master_data_context(scope_info):
    workspace_user_id = scope_info["current_scope_user_id"]
    registry = recipe_master_data.workspace_unit_registry_with_usage(workspace_user_id)

    category_labels = {
        item["key"]: item["label"]
        for item in registry.get("categories", [])
    }
    category_order = tuple(category_labels)
    categories = []
    for category in category_order:
        units = []
        for unit in registry["units"]:
            if unit["category"] != category:
                continue
            unit_data = dict(unit)
            unit_data["aliases"] = sorted(
                unit.get("aliases", []),
                key=lambda value: (len(value), value.lower()),
            )
            units.append(unit_data)
        categories.append({
            "key": category,
            "label": category_labels[category],
            "units": units,
        })

    workspace_scope = {
        "scope": "mine",
        "user_id": scope_info["current_scope_user_id"],
        "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
    }
    return {
        "title": "Units",
        "record_type": "units",
        "viewer_user_id": workspace_scope["viewer_user_id"],
        "scope_user_id": workspace_scope["user_id"],
        "registry": registry,
        "categories": categories,
        "seeded_count": sum(1 for unit in registry["units"] if unit.get("seeded")),
        "custom_count": sum(1 for unit in registry["units"] if not unit.get("seeded")),
        "alias_count": sum(len(unit.get("aliases", [])) for unit in registry["units"]),
        "category_count": len({unit["category"] for unit in registry["units"]}),
        "category_options": registry.get("categories", []),
        "create_url": url_for("main_bp.master_data_units_api_route"),
        "update_url_template": url_for(
            "main_bp.master_data_unit_api_route",
            unit_id="__UNIT_ID__",
        ),
        "usage_url_template": url_for(
            "main_bp.master_data_unit_references_route",
            unit_id="__UNIT_ID__",
        ),
        "import_url": url_for("main_bp.master_data_units_import_api_route"),
        "suggest_url": url_for("main_bp.master_data_units_suggest_api_route"),
        "ingredient_url": build_canonical_master_data_url(
            "ingredients",
            scope_info=workspace_scope,
        ),
        "equipment_url": build_canonical_master_data_url(
            "equipment",
            scope_info=workspace_scope,
        ),
        "units_url": build_canonical_master_data_url(
            "units",
            scope_info=workspace_scope,
        ),
        "types_url": build_canonical_master_data_url(
            "types",
            scope_info=workspace_scope,
        ),
        "store_section_url": build_canonical_master_data_url(
            "store_sections",
            scope_info=workspace_scope,
        ),
    }


@main_bp.route("/admin/master-data/units")
def master_data_units_route():
    scope_info, canonical_redirect = validate_canonical_master_data_page_request(
        "units",
        allow_admin_scope=False,
    )
    if canonical_redirect:
        return canonical_redirect
    return render_template(
        "units.html",
        master_data=unit_master_data_context(scope_info),
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
        units_js_version=static_asset_version("js/units.js"),
    )


@main_bp.route("/api/master-data/units", methods=["GET", "POST"])
def master_data_units_api_route():
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "registry": recipe_master_data.workspace_unit_registry_with_usage(
                workspace_user_id
            ),
        })

    payload = request.get_json(silent=True) or {}
    result = recipe_master_data.save_workspace_unit(
        payload,
        user_id=workspace_user_id,
    )
    if result.get("ok"):
        result["registry"] = recipe_master_data.workspace_unit_registry_with_usage(
            workspace_user_id
        )
    status = int(result.pop("status", 201 if result.get("created") else 200))
    return jsonify(result), status


@main_bp.route("/api/master-data/units/<unit_id>", methods=["PUT", "PATCH"])
def master_data_unit_api_route(unit_id):
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    result = recipe_master_data.save_workspace_unit(
        request.get_json(silent=True) or {},
        unit_id=unit_id,
        user_id=workspace_user_id,
    )
    if result.get("ok"):
        result["registry"] = recipe_master_data.workspace_unit_registry_with_usage(
            workspace_user_id
        )
    status = int(result.pop("status", 200))
    return jsonify(result), status


@main_bp.route("/api/master-data/units/<unit_id>/references")
def master_data_unit_references_route(unit_id):
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    result = recipe_master_data.workspace_unit_recipe_references(
        unit_id,
        user_id=workspace_user_id,
        limit=int_query_arg("limit", 100, minimum=1, maximum=500),
    )
    if not result.get("unit"):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Unit not found for this workspace.",
        }), 404

    for reference in result.get("references", []):
        recipe_url = recipe_master_data.clean_text(reference.get("recipe_url"))
        reference["edit_url"] = recipe_edit_page_url(recipe_url) if recipe_url else ""
        cover_image = (
            reference.get("cover_image")
            if isinstance(reference.get("cover_image"), dict)
            else {}
        )
        rendered_cover_image = recipe_cover_image_for_view(
            recipe_url,
            {
                "recipe_title": reference.get("recipe_title"),
                "cover_image": cover_image,
            },
            {"cover_image": cover_image},
            variants=("thumb", "detail"),
        )
        reference["recipe_image_url"] = (
            rendered_cover_image.get("thumb_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        reference["recipe_image_srcset"] = rendered_cover_image.get("srcset") or ""
        reference["recipe_image_alt"] = (
            rendered_cover_image.get("alt")
            or f"{reference.get('recipe_title') or 'Recipe'} image"
        )

    return jsonify({
        "ok": True,
        "success": True,
        **result,
    })


@main_bp.route("/api/master-data/units/suggest", methods=["POST"])
def master_data_units_suggest_api_route():
    result = unit_suggestions.suggest_workspace_unit(
        request.get_json(silent=True) or {},
        user_id=recipe_master_data.scoped_recipe_user_id(),
    )
    status = int(result.pop("status", 200))
    return jsonify(result), status


@main_bp.route("/api/master-data/units/import-local", methods=["POST"])
def master_data_units_import_api_route():
    payload = request.get_json(silent=True) or {}
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    result = recipe_master_data.import_workspace_unit_names(
        payload.get("units"),
        user_id=workspace_user_id,
    )
    result["registry"] = recipe_master_data.workspace_unit_registry_with_usage(
        workspace_user_id
    )
    return jsonify(result)


def ingredient_type_master_data_context(scope_info):
    workspace_scope = {
        "scope": "mine",
        "user_id": scope_info["current_scope_user_id"],
        "viewer_user_id": scope_info.get("viewer_user_id") or active_user_id(),
    }
    registry = ingredient_types.ingredient_type_registry_payload(
        workspace_scope["user_id"],
        include_usage=True,
    )
    type_rows = registry.get("types", [])
    return {
        "title": "Types",
        "record_type": "types",
        "viewer_user_id": workspace_scope["viewer_user_id"],
        "scope_user_id": workspace_scope["user_id"],
        "registry": registry,
        "types": type_rows,
        "seeded_count": sum(1 for item in type_rows if item.get("seeded")),
        "custom_count": sum(1 for item in type_rows if item.get("custom")),
        "active_count": sum(1 for item in type_rows if item.get("active")),
        "used_count": sum(1 for item in type_rows if item.get("recipe_count")),
        "create_url": url_for("main_bp.master_data_types_api_route"),
        "update_url_template": url_for(
            "main_bp.master_data_type_api_route",
            type_id="__TYPE_ID__",
        ),
        "usage_url_template": url_for(
            "main_bp.master_data_type_references_route",
            type_id="__TYPE_ID__",
        ),
        "import_url": url_for("main_bp.master_data_types_import_api_route"),
        "ingredient_url": build_canonical_master_data_url(
            "ingredients",
            scope_info=workspace_scope,
        ),
        "equipment_url": build_canonical_master_data_url(
            "equipment",
            scope_info=workspace_scope,
        ),
        "units_url": build_canonical_master_data_url(
            "units",
            scope_info=workspace_scope,
        ),
        "types_url": build_canonical_master_data_url(
            "types",
            scope_info=workspace_scope,
        ),
        "store_section_url": build_canonical_master_data_url(
            "store_sections",
            scope_info=workspace_scope,
        ),
    }


@main_bp.route("/admin/master-data/types")
def master_data_types_route():
    scope_info, canonical_redirect = validate_canonical_master_data_page_request(
        "types",
        allow_admin_scope=False,
    )
    if canonical_redirect:
        return canonical_redirect
    return render_template(
        "types.html",
        master_data=ingredient_type_master_data_context(scope_info),
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
        types_js_version=static_asset_version("js/types.js"),
    )


@main_bp.route("/api/master-data/types", methods=["GET", "POST"])
def master_data_types_api_route():
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "registry": ingredient_types.ingredient_type_registry_payload(
                workspace_user_id,
                include_usage=True,
            ),
        })

    result = ingredient_types.save_workspace_ingredient_type(
        request.get_json(silent=True) or {},
        user_id=workspace_user_id,
    )
    if result.get("ok"):
        result["registry"] = ingredient_types.ingredient_type_registry_payload(
            workspace_user_id,
            include_usage=True,
        )
    status = int(result.pop("status", 201 if result.get("created") else 200))
    return jsonify(result), status


@main_bp.route(
    "/api/master-data/types/<type_id>",
    methods=["PUT", "PATCH", "DELETE"],
)
def master_data_type_api_route(type_id):
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    if request.method == "DELETE":
        result = ingredient_types.delete_workspace_ingredient_type(
            type_id,
            user_id=workspace_user_id,
        )
    else:
        result = ingredient_types.save_workspace_ingredient_type(
            request.get_json(silent=True) or {},
            type_id=type_id,
            user_id=workspace_user_id,
        )
    if result.get("ok"):
        result["registry"] = ingredient_types.ingredient_type_registry_payload(
            workspace_user_id,
            include_usage=True,
        )
    status = int(result.pop("status", 200))
    return jsonify(result), status


@main_bp.route("/api/master-data/types/<type_id>/references")
def master_data_type_references_route(type_id):
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    result = ingredient_types.workspace_ingredient_type_recipe_references(
        type_id,
        user_id=workspace_user_id,
        limit=int_query_arg("limit", 100, minimum=1, maximum=500),
    )
    if not result.get("type"):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Type not found for this workspace.",
        }), 404

    for reference in result.get("references", []):
        recipe_url = recipe_master_data.clean_text(reference.get("recipe_url"))
        reference["edit_url"] = recipe_edit_page_url(recipe_url) if recipe_url else ""
        cover_image = (
            reference.get("cover_image")
            if isinstance(reference.get("cover_image"), dict)
            else {}
        )
        rendered_cover_image = recipe_cover_image_for_view(
            recipe_url,
            {
                "recipe_title": reference.get("recipe_title"),
                "cover_image": cover_image,
            },
            {"cover_image": cover_image},
            variants=("thumb", "detail"),
        )
        reference["recipe_image_url"] = (
            rendered_cover_image.get("thumb_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        reference["recipe_image_srcset"] = rendered_cover_image.get("srcset") or ""
        reference["recipe_image_alt"] = (
            rendered_cover_image.get("alt")
            or f"{reference.get('recipe_title') or 'Recipe'} image"
        )

    return jsonify({"ok": True, "success": True, **result})


@main_bp.route("/api/master-data/types/import-local", methods=["POST"])
def master_data_types_import_api_route():
    payload = request.get_json(silent=True) or {}
    workspace_user_id = recipe_master_data.scoped_recipe_user_id()
    result = ingredient_types.import_workspace_ingredient_type_names(
        payload.get("types"),
        user_id=workspace_user_id,
    )
    result["registry"] = ingredient_types.ingredient_type_registry_payload(
        workspace_user_id,
        include_usage=True,
    )
    return jsonify(result)


def store_section_master_data_context():
    user_id = recipe_master_data.scoped_recipe_user_id()
    viewer_user_id = active_user_id()
    sections = recipe_master_data.ingredient_store_section_details(
        user_id=user_id,
        include_inactive=True,
        create=True,
    )
    active_sections = [section for section in sections if section["is_active"]]
    return {
        "title": "Store Sections",
        "record_type": "store_sections",
        "viewer_user_id": viewer_user_id,
        "scope_user_id": user_id,
        "sections": sections,
        "active_count": len(active_sections),
        "archived_count": len(sections) - len(active_sections),
        "ingredient_count": sum(
            int(section.get("ingredient_count") or 0)
            for section in sections
        ),
        "recipe_reference_count": sum(
            int(section.get("recipe_reference_count") or 0)
            for section in sections
        ),
        "icon_options": recipe_master_data.INGREDIENT_STORE_SECTION_ICON_OPTIONS,
        "messages": session.pop("recipe_master_data_messages", []),
        "ingredient_url": build_canonical_master_data_url("ingredients"),
        "equipment_url": build_canonical_master_data_url("equipment"),
        "units_url": build_canonical_master_data_url("units"),
        "types_url": build_canonical_master_data_url("types"),
        "store_section_url": build_canonical_master_data_url("store_sections"),
        "create_url": build_canonical_master_data_url("store_sections"),
    }


@main_bp.route("/admin/master-data/store-sections")
def master_data_store_sections_route():
    _scope_info, canonical_redirect = validate_canonical_master_data_page_request(
        "store_sections",
        allow_admin_scope=False,
    )
    if canonical_redirect:
        return canonical_redirect
    return render_template(
        "store_sections.html",
        master_data=store_section_master_data_context(),
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
    )


@main_bp.route("/api/master-data/store-sections/<int:section_id>/usage")
def master_data_store_section_usage_route(section_id):
    usage = recipe_master_data.ingredient_store_section_usage(
        section_id,
        user_id=active_user_id(),
    )
    if not usage:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Store Section was not found for this workspace.",
        }), 404

    section_key = recipe_master_data.clean_text(
        usage.get("section", {}).get("section_key")
    )
    ingredients = []
    for ingredient in usage.get("ingredients", []):
        item = dict(ingredient)
        item["manage_url"] = build_canonical_master_data_url(
            "ingredients",
            overrides={
                "store_section": section_key,
                "search": item.get("name") or None,
                "sort": "name_asc",
            },
        )
        ingredients.append(item)

    recipes = []
    for recipe in usage.get("recipes", []):
        item = dict(recipe)
        recipe_url = recipe_master_data.clean_text(item.get("recipe_url"))
        item["edit_url"] = recipe_edit_page_url(recipe_url)
        cover_image = (
            item.get("cover_image")
            if isinstance(item.get("cover_image"), dict)
            else {}
        )
        rendered_cover_image = recipe_cover_image_for_view(
            recipe_url,
            {
                "recipe_title": item.get("recipe_title"),
                "cover_image": cover_image,
            },
            {"cover_image": cover_image},
            variants=("thumb", "detail"),
        )
        item["recipe_image_url"] = (
            rendered_cover_image.get("thumb_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        item["recipe_image_full_url"] = (
            rendered_cover_image.get("full_url")
            or rendered_cover_image.get("detail_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        item["recipe_image_srcset"] = rendered_cover_image.get("srcset") or ""
        item["recipe_image_alt"] = (
            rendered_cover_image.get("alt")
            or f"{item.get('recipe_title') or 'Recipe'} image"
        )
        recipes.append(item)

    return jsonify({
        "ok": True,
        "success": True,
        **usage,
        "ingredients": ingredients,
        "recipes": recipes,
    })


def set_store_section_master_data_message(result, *, success_prefix):
    if result.get("ok"):
        message = success_prefix.format(
            name=result.get("display_name") or "Store Section"
        )
        category = "success"
    else:
        message = result.get("error") or "Store Section could not be updated."
        category = "error"
    session["recipe_master_data_messages"] = [{
        "category": category,
        "text": message,
    }]


@main_bp.route("/admin/master-data/store-sections", methods=["POST"])
def create_master_data_store_section_route():
    result = recipe_master_data.create_ingredient_store_section(
        request.form.get("display_name"),
        request.form.get("icon"),
        user_id=active_user_id(),
    )
    set_store_section_master_data_message(
        result,
        success_prefix="Store Section created: {name}.",
    )
    return redirect(build_canonical_master_data_url("store_sections"))


@main_bp.route("/admin/master-data/store-sections/<int:section_id>", methods=["POST"])
def update_master_data_store_section_route(section_id):
    action = recipe_master_data.clean_text(request.form.get("action")).lower() or "save"
    result = recipe_master_data.update_ingredient_store_section_definition(
        section_id,
        action=action,
        display_name=request.form.get("display_name"),
        icon=request.form.get("icon"),
        position=request.form.get("position"),
        user_id=active_user_id(),
    )
    action_messages = {
        "save": "Store Section updated: {name}.",
        "move_up": "Store Section moved up: {name}.",
        "move_down": "Store Section moved down: {name}.",
        "move_to": "Store Section moved: {name}.",
        "archive": "Store Section archived: {name}.",
        "restore": "Store Section restored: {name}.",
        "delete": "Store Section deleted: {name}.",
    }
    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    ):
        return jsonify(result), int(result.get("status") or 200)
    set_store_section_master_data_message(
        result,
        success_prefix=action_messages.get(action, "Store Section updated: {name}."),
    )
    return redirect(build_canonical_master_data_url("store_sections"))


@main_bp.route("/api/master-data/ingredients/options")
def ingredient_master_options_route():
    search = recipe_master_data.clean_text(
        request.args.get("search") or request.args.get("q")
    )
    limit = int_query_arg("limit", 20, minimum=1, maximum=50)
    rows = recipe_master_data.list_ingredients(
        search=search,
        limit=limit,
        sort="usage_count_desc",
    )
    return jsonify({
        "ok": True,
        "success": True,
        "search": search,
        "ingredients": [
            {
                "ingredient_id": int(row.get("id") or 0),
                "name": recipe_master_data.clean_text(row.get("name")),
                "normalized_name": recipe_master_data.normalized_master_name(
                    row.get("normalized_name") or row.get("name")
                ),
                "store_section": recipe_master_data.clean_ingredient_store_section(
                    row.get("store_section")
                ),
                "image_url": recipe_master_data.clean_text(row.get("image_url")),
                "usage_count": int(row.get("usage_count") or 0),
                "aliases": [
                    recipe_master_data.clean_text(alias)
                    for alias in row.get("aliases", [])
                    if recipe_master_data.clean_text(alias)
                ],
            }
            for row in rows
        ],
        "manage_url": build_canonical_master_data_url("ingredients"),
    })


@main_bp.route("/api/master-data/ingredients/reclassify-misc", methods=["POST"])
def reclassify_misc_ingredient_master_data_route():
    payload = request.get_json(silent=True) or {}
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else None
    if bool(payload.get("apply")) and decisions is not None:
        result = recipe_master_data.apply_misc_ingredient_store_section_decisions(
            user_id=active_user_id(),
            decisions=decisions,
        )
    else:
        result = recipe_master_data.review_misc_ingredient_store_sections(
            user_id=active_user_id(),
            apply=bool(payload.get("apply")),
        )
    status = 200 if result.get("ok") else int(result.get("status") or 400)
    return jsonify({**result, "success": result.get("ok", False)}), status


@main_bp.route("/api/master-data/ingredients/reclassify-misc/ai-second-opinion", methods=["POST"])
def reclassify_misc_ingredient_ai_second_opinion_route():
    payload = request.get_json(silent=True) or {}
    ingredient_ids = payload.get("ingredient_ids") if isinstance(payload.get("ingredient_ids"), list) else None
    result = ingredient_store_section_reviews.review_misc_ingredient_store_sections_with_ai(
        user_id=active_user_id(),
        scope=payload.get("scope") or "suggested",
        ingredient_ids=ingredient_ids,
    )
    status = 200 if result.get("ok") else int(result.get("status") or 400)
    return jsonify({**result, "success": result.get("ok", False)}), status


@main_bp.route("/api/master-data/ingredients/reclassify-misc/undo", methods=["POST"])
def undo_misc_ingredient_reclassification_route():
    payload = request.get_json(silent=True) or {}
    result = recipe_master_data.undo_last_ingredient_store_section_reclassification(
        user_id=active_user_id(),
        expected_batch_id=payload.get("batch_id"),
        expected_ingredient_id=payload.get("ingredient_id"),
    )
    status = 200 if result.get("ok") else int(result.get("status") or 400)
    restored_count = int(result.get("restored_ingredient_count") or 0)
    message = (
        f"Restored {restored_count} ingredient store-section "
        f"decision{'s' if restored_count != 1 else ''}."
        if result.get("ok")
        else result.get("error")
    )
    return jsonify({
        **result,
        "success": result.get("ok", False),
        "message": message,
        "undo_available": bool(result.get("next_batch")),
    }), status


@main_bp.route("/api/master-data/ingredients/reclassify-misc/undo-preview")
def preview_misc_ingredient_reclassification_undo_route():
    result = recipe_master_data.ingredient_store_section_reclassification_undo_preview(
        user_id=active_user_id(),
        batch_id=request.args.get("batch_id"),
        ingredient_id=request.args.get("ingredient_id"),
    )
    status = 200 if result.get("ok") else int(result.get("status") or 400)
    if not result.get("ok"):
        return jsonify({**result, "success": False}), status
    return jsonify({
        "ok": True,
        "success": True,
        "preview": result,
        "batches": result.get("undoable_batches", []),
        "items": result.get("history_items", []),
    }), status


@main_bp.route("/api/master-data/ingredients/duplicate-scan", methods=["POST"])
def ingredient_duplicate_scan_route():
    active_public_user = current_public_user()
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    workspace_user_id = ingredient_duplicate_review_workspace(active_public_user, payload)
    if not workspace_user_id:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Choose one user workspace before scanning for duplicate ingredients.",
        }), 400

    result = ingredient_duplicate_reviews.scan_potential_duplicates(workspace_user_id)
    return jsonify({**result, "success": result.get("ok", False)})


@main_bp.route("/api/master-data/ingredients/duplicate-reviews")
def ingredient_duplicate_reviews_route():
    active_public_user = current_public_user()
    workspace_user_id = ingredient_duplicate_review_workspace(active_public_user, request.args)
    if not workspace_user_id:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Choose one user workspace to view duplicate ingredient reviews.",
        }), 400
    reviews = ingredient_duplicate_reviews.list_duplicate_reviews(workspace_user_id)
    return jsonify({
        "ok": True,
        "success": True,
        "user_id": workspace_user_id,
        "review_count": len(reviews),
        "reviews": reviews,
        "scan": ingredient_duplicate_reviews.duplicate_scan_summary(workspace_user_id),
    })


@main_bp.route("/api/master-data/ingredients/duplicate-reviews/history")
def ingredient_duplicate_review_history_route():
    active_public_user = current_public_user()
    workspace_user_id = ingredient_duplicate_review_workspace(active_public_user, request.args)
    if not workspace_user_id:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Choose one user workspace to view review decision history.",
        }), 400
    decisions = ingredient_duplicate_reviews.list_duplicate_decision_history(
        workspace_user_id,
        limit=int_query_arg("limit", 200, minimum=1, maximum=500),
    )
    return jsonify({
        "ok": True,
        "success": True,
        "user_id": workspace_user_id,
        "decision_count": len(decisions),
        "decisions": decisions,
    })


@main_bp.route(
    "/api/master-data/ingredients/duplicate-reviews/<int:review_id>/ai-second-opinion",
    methods=["POST"],
)
def ingredient_duplicate_ai_second_opinion_route(review_id):
    active_public_user = current_public_user()
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    force = str(payload.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
    result = ingredient_duplicate_reviews.generate_ai_second_opinion(
        review_id,
        allow_other_users=is_admin_user(active_public_user),
        force=force,
    )
    if not result.get("ok"):
        return jsonify({**result, "success": False}), int(result.get("status") or 400)
    return jsonify({
        **result,
        "success": True,
        "message": "AI second opinion updated.",
    })


@main_bp.route(
    "/api/master-data/ingredients/duplicate-reviews/<int:review_id>/decision",
    methods=["POST"],
)
def ingredient_duplicate_decision_route(review_id):
    active_public_user = current_public_user()
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    result = ingredient_duplicate_reviews.decide_duplicate_review(
        review_id,
        payload.get("action"),
        target_ingredient_id=payload.get("target_ingredient_id"),
        allow_other_users=is_admin_user(active_public_user),
    )
    if result.get("ok"):
        if result.get("action") == "merge":
            merge = result.get("merge") or {}
            message = (
                f"Merged {merge.get('source_name')} into {merge.get('target_name')} and kept "
                "the removed name as an alias."
            )
        elif result.get("action") == "related":
            message = "Marked as a related variant. This pair will not be suggested again."
        else:
            message = "Marked as not a duplicate. This pair will not be suggested again."
        return jsonify({
            **result,
            "success": True,
            "message": message,
        })
    return jsonify({
        **result,
        "success": False,
    }), int(result.get("status") or 400)


@main_bp.route(
    "/api/master-data/ingredients/duplicate-reviews/<int:review_id>/restore",
    methods=["POST"],
)
def ingredient_duplicate_restore_decision_route(review_id):
    active_public_user = current_public_user()
    result = ingredient_duplicate_reviews.restore_duplicate_review_decision(
        review_id,
        allow_other_users=is_admin_user(active_public_user),
    )
    if not result.get("ok"):
        return jsonify({**result, "success": False}), int(result.get("status") or 400)
    return jsonify({
        **result,
        "success": True,
        "message": (
            f"Restored {result.get('left_name')} and {result.get('right_name')} "
            "to the duplicate review queue."
        ),
    })


@main_bp.route(
    "/api/master-data/ingredients/duplicate-reviews/bulk-decision",
    methods=["POST"],
)
def ingredient_duplicate_bulk_decision_route():
    active_public_user = current_public_user()
    payload = request.get_json(silent=True) if request.is_json else {}
    payload = payload if isinstance(payload, dict) else {}
    result = ingredient_duplicate_reviews.decide_duplicate_reviews(
        payload.get("decisions"),
        allow_other_users=is_admin_user(active_public_user),
    )
    if not result.get("ok"):
        return jsonify({**result, "success": False}), int(result.get("status") or 400)

    succeeded_count = int(result.get("succeeded_count") or 0)
    failed_count = int(result.get("failed_count") or 0)
    merged_count = int(result.get("merged_count") or 0)
    message = f"Applied {succeeded_count} bulk review decision{'s' if succeeded_count != 1 else ''}."
    if failed_count:
        message += f" {failed_count} item{'s' if failed_count != 1 else ''} could not be applied."
    if merged_count:
        message += f" {merged_count} duplicate pair{'s' if merged_count != 1 else ''} merged."
        session["recipe_master_data_messages"] = [{
            "category": "success" if not failed_count else "warning",
            "text": message,
        }]
    return jsonify({
        **result,
        "success": True,
        "message": message,
    })


@main_bp.route("/api/master-data/ingredients/merges/undo-preview")
def preview_ingredient_master_merge_undo_route():
    active_public_user = current_public_user()
    workspace_user_id = ingredient_duplicate_review_workspace(active_public_user, request.args)
    if not workspace_user_id:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Choose one user workspace before previewing an ingredient merge undo.",
        }), 400

    result = recipe_master_data.ingredient_merge_undo_preview(
        workspace_user_id,
        merge_id=request.args.get("merge_id"),
    )
    if not result.get("ok"):
        return jsonify({**result, "success": False}), int(result.get("status") or 400)
    return jsonify({
        "ok": True,
        "success": True,
        "merge": result,
        "merges": result.get("undoable_merges", []),
    })


@main_bp.route("/api/master-data/ingredients/merges/undo", methods=["POST"])
def undo_ingredient_master_merge_route():
    active_public_user = current_public_user()
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    workspace_user_id = ingredient_duplicate_review_workspace(active_public_user, payload)
    if not workspace_user_id:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Choose one user workspace before undoing an ingredient merge.",
        }), 400

    result = recipe_master_data.undo_last_ingredient_master_merge(
        workspace_user_id,
        expected_merge_id=payload.get("merge_id"),
    )
    if not result.get("ok"):
        return jsonify({**result, "success": False}), int(result.get("status") or 400)

    restored_count = int(result.get("restored_reference_count") or 0)
    message = (
        f"Restored {result.get('source_name')} after undoing its merge into "
        f"{result.get('target_name')}; restored {restored_count} recipe "
        f"reference{'s' if restored_count != 1 else ''}."
    )
    return jsonify({
        **result,
        "success": True,
        "message": message,
        "undo_available": bool(result.get("next_merge")),
    })


@main_bp.route("/api/master-data/<record_type>/<int:record_id>/references")
def master_data_record_references_route(record_type, record_id):
    if record_type not in MASTER_DATA_PAGE_CONFIG:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Unsupported master data type.",
        }), 404

    active_public_user = current_public_user()
    scope_info = master_data_scope(is_admin_user(active_public_user))
    references = recipe_master_data.list_master_record_recipe_references(
        record_type,
        record_id,
        user_id=scope_info["user_id"],
        include_all_users=scope_info["include_all_users"],
        limit=int_query_arg("limit", 25, minimum=1, maximum=500),
    )
    if not references.get("record"):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Master data record was not found for this scope.",
        }), 404

    enriched_references = []
    for reference in references.get("references", []):
        recipe_url = recipe_master_data.clean_text(reference.get("recipe_url"))
        reference = dict(reference)
        reference_owner_user_id = str(reference.get("user_id") or "")
        active_viewer_user_id = str((active_public_user or {}).get("user_id") or "")
        # An administrator can inspect another account's master-data
        # references, but /recipe/edit always resolves the signed-in viewer's
        # workspace. Emitting an admin-viewer editor URL here would therefore
        # open an unrelated recipe (or an empty editor) and misrepresent the
        # selected target scope.
        reference["edit_url"] = (
            recipe_edit_page_url(recipe_url)
            if reference_owner_user_id == active_viewer_user_id
            else ""
        )
        cover_image = reference.get("cover_image") if isinstance(reference.get("cover_image"), dict) else {}
        rendered_cover_image = recipe_cover_image_for_view(
            recipe_url,
            {
                "recipe_title": reference.get("recipe_title"),
                "cover_image": cover_image,
            },
            {"cover_image": cover_image},
            variants=("thumb", "detail"),
        )
        reference["recipe_image_url"] = (
            rendered_cover_image.get("thumb_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        reference["recipe_image_full_url"] = (
            rendered_cover_image.get("full_url")
            or rendered_cover_image.get("detail_url")
            or rendered_cover_image.get("display_url")
            or rendered_cover_image.get("src")
            or ""
        )
        reference["recipe_image_srcset"] = rendered_cover_image.get("srcset") or ""
        reference["recipe_image_alt"] = (
            rendered_cover_image.get("alt")
            or f"{reference.get('recipe_title') or 'Recipe'} image"
        )
        enriched_references.append(reference)

    return jsonify({
        "ok": True,
        "success": True,
        "record_type": record_type,
        "record": references.get("record"),
        "references": enriched_references,
        "total": int(references.get("total") or 0),
        "total_reference_count": int(references.get("total_reference_count") or 0),
        "ingredient_name_recipe_count": int(
            references.get("ingredient_name_recipe_count") or 0
        ),
        "buy_as_recipe_count": int(references.get("buy_as_recipe_count") or 0),
        "limit": int(references.get("limit") or 0),
    })


@main_bp.route("/admin/master-data/ingredients/<int:ingredient_id>", methods=["POST"])
def update_ingredient_master_record_route(ingredient_id):
    active_public_user = current_public_user()
    allow_other_users = is_admin_user(active_public_user)
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    redirect_url = canonicalize_master_data_redirect_url(
        payload.get("redirect_url"),
        default_page="ingredients",
    )
    result = recipe_master_data.update_ingredient_master_record(
        ingredient_id,
        payload.get("name"),
        payload.get("normalized_name"),
        payload.get("store_section"),
        allow_other_users=allow_other_users,
    )
    if result.get("ok"):
        if result.get("changed"):
            message = f"Ingredient master record updated: {result.get('name')}."
        else:
            message = f"Ingredient master record was already up to date: {result.get('name')}."
        category = "success"
    else:
        message = result.get("error") or "Ingredient master record could not be updated."
        category = "error"

    session["recipe_master_data_messages"] = [{
        "category": category,
        "text": message,
    }]
    wants_json = (
        request.is_json
        or request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        status = 200 if result.get("ok") else int(result.get("status") or 400)
        return jsonify({
            "ok": result.get("ok", False),
            "success": result.get("ok", False),
            "category": category,
            "message": message,
            "result": result,
            "redirect_url": redirect_url,
        }), status

    return redirect(redirect_url)


@main_bp.route("/api/master-data/ingredients/<int:ingredient_id>/merge-options")
def ingredient_master_merge_options_route(ingredient_id):
    active_public_user = current_public_user()
    allow_other_users = is_admin_user(active_public_user)
    source = recipe_master_data.master_record_for_id(
        "ingredients",
        ingredient_id,
        include_all_users=allow_other_users,
    )
    if not source:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Ingredient record was not found.",
        }), 404

    search = recipe_master_data.clean_text(request.args.get("search"))
    limit = int_query_arg("limit", 20, minimum=1, maximum=50)
    rows = recipe_master_data.list_ingredients(
        user_id=source["user_id"],
        search=search,
        limit=min(50, limit + 1),
        sort="usage_count_desc" if not search else "name_asc",
    )
    candidates = [
        row
        for row in rows
        if int(row.get("id") or 0) != int(source["id"])
    ][:limit]
    return jsonify({
        "ok": True,
        "success": True,
        "search": search,
        "source": {
            "ingredient_id": int(source["id"]),
            "name": recipe_master_data.clean_text(source.get("name")),
            "normalized_name": recipe_master_data.normalized_master_name(source.get("normalized_name")),
            "usage_count": recipe_master_data.count_ingredient_usage(
                source["id"],
                user_id=source["user_id"],
            ),
        },
        "ingredients": [
            {
                "ingredient_id": int(row.get("id") or 0),
                "name": recipe_master_data.clean_text(row.get("name")),
                "normalized_name": recipe_master_data.normalized_master_name(
                    row.get("normalized_name") or row.get("name")
                ),
                "store_section": recipe_master_data.clean_ingredient_store_section(
                    row.get("store_section")
                ),
                "image_url": recipe_master_data.clean_text(row.get("image_url")),
                "usage_count": int(row.get("usage_count") or 0),
                "aliases": [
                    recipe_master_data.clean_text(alias)
                    for alias in row.get("aliases", [])
                    if recipe_master_data.clean_text(alias)
                ],
            }
            for row in candidates
        ],
    })


@main_bp.route("/admin/master-data/ingredients/<int:ingredient_id>/merge", methods=["POST"])
def merge_ingredient_master_record_route(ingredient_id):
    active_public_user = current_public_user()
    allow_other_users = is_admin_user(active_public_user)
    payload = request.get_json(silent=True) if request.is_json else request.form
    payload = payload if isinstance(payload, dict) or hasattr(payload, "get") else {}
    redirect_url = canonicalize_master_data_redirect_url(
        payload.get("redirect_url"),
        default_page="ingredients",
    )
    result = recipe_master_data.merge_ingredient_master_records(
        ingredient_id,
        payload.get("target_ingredient_id"),
        allow_other_users=allow_other_users,
    )
    if result.get("ok"):
        moved_count = int(result.get("moved_reference_count") or 0)
        message = (
            f"Merged {result.get('source_name')} into {result.get('target_name')}; "
            f"moved {moved_count} recipe reference{'s' if moved_count != 1 else ''} "
            "and kept the old name as an alias."
        )
        category = "success"
    else:
        message = result.get("error") or "Ingredient records could not be merged."
        category = "error"

    session["recipe_master_data_messages"] = [{
        "category": category,
        "text": message,
    }]
    wants_json = (
        request.is_json
        or request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        status = 200 if result.get("ok") else int(result.get("status") or 400)
        return jsonify({
            "ok": result.get("ok", False),
            "success": result.get("ok", False),
            "category": category,
            "message": message,
            "result": result,
            "redirect_url": redirect_url,
        }), status

    return redirect(redirect_url)


@main_bp.route("/admin/master-data/ingredients/<int:ingredient_id>/store-section", methods=["POST"])
def update_ingredient_master_store_section_route(ingredient_id):
    active_public_user = current_public_user()
    allow_other_users = is_admin_user(active_public_user)
    redirect_url = canonicalize_master_data_redirect_url(
        request.form.get("redirect_url"),
        default_page="ingredients",
    )
    result = recipe_master_data.update_ingredient_store_section(
        ingredient_id,
        request.form.get("store_section"),
        allow_other_users=allow_other_users,
    )
    if result.get("ok"):
        section = result.get("store_section") or "MISC"
        if result.get("changed"):
            message = f"Store section updated to {section}."
        else:
            message = f"Store section was already {section}."
        category = "success"
    else:
        message = result.get("error") or "Store section could not be updated."
        category = "error"

    session["recipe_master_data_messages"] = [{
        "category": category,
        "text": message,
    }]

    wants_json = (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        return jsonify({
            "ok": result.get("ok", False),
            "success": result.get("ok", False),
            "category": category,
            "message": message,
            "result": result,
            "redirect_url": redirect_url,
        }), 200 if result.get("ok") else 404

    return redirect(redirect_url)


@main_bp.route("/admin/master-data/backfill", methods=["POST"])
def recipe_master_data_backfill_route():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    record_type = str(request.form.get("record_type") or "ingredients").strip()
    if record_type not in MASTER_DATA_PAGE_CONFIG:
        record_type = "ingredients"
    scope_info = master_data_form_scope()
    redirect_url = canonicalize_master_data_redirect_url(
        request.form.get("redirect_url"),
        default_page=record_type,
        fallback_scope_info=scope_info,
    )

    include_legacy = str(request.form.get("include_legacy") or "").strip().lower() in {"1", "true", "yes", "on"}
    force = str(request.form.get("force") or "").strip().lower() in {"1", "true", "yes", "on"}
    job_id = recipe_master_data.clean_text(request.form.get("job_id")) or uuid.uuid4().hex
    wants_json = (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )
    recipe_master_data.start_recipe_master_backfill_progress(
        job_id,
        include_legacy=include_legacy,
        force=force,
    )

    try:
        result = recipe_master_data.backfill_all_recipe_master_records(
            include_legacy=include_legacy,
            force=force,
            progress_callback=lambda event, payload: recipe_master_data.update_recipe_master_backfill_progress(
                job_id,
                event,
                payload,
            ),
        )
        if result.get("skipped"):
            message = (
                "Backfill was skipped because the recipe master migration marker already exists. "
                "Use Force rerun if you need to rebuild it."
            )
            category = "warning"
        else:
            message = (
                "Backfill finished: "
                f"{int(result.get('users') or 0)} users, "
                f"{int(result.get('recipes') or 0)} recipes, "
                f"{int(result.get('ingredient_rows') or 0)} ingredient links, "
                f"{int(result.get('equipment_rows') or 0)} equipment links."
            )
            category = "success"
    except Exception as exc:
        message = f"Backfill failed: {exc}"
        category = "error"
        recipe_master_data.update_recipe_master_backfill_progress(
            job_id,
            "failed",
            {"error": message},
        )

    progress = recipe_master_data.recipe_master_backfill_progress(job_id)

    session["recipe_master_data_messages"] = [{
        "category": category,
        "text": message,
    }]

    if wants_json:
        return jsonify({
            "ok": category != "error",
            "success": category != "error",
            "job_id": job_id,
            "category": category,
            "message": message,
            "progress": progress,
            "redirect_url": redirect_url,
        }), 200 if category != "error" else 500

    return redirect(redirect_url)


@main_bp.route("/api/master-data/backfill-status")
def recipe_master_data_backfill_status_route():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    job_id = recipe_master_data.clean_text(request.args.get("job_id"))
    progress = recipe_master_data.recipe_master_backfill_progress(job_id)
    if not progress:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "No backfill progress was found.",
        }), 404

    return jsonify({
        "ok": True,
        "success": True,
        "progress": progress,
    })


@main_bp.route("/api/master-data/generate-missing-images", methods=["POST"])
def recipe_master_data_generate_missing_images_route():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    record_type = recipe_master_data.clean_text(request.form.get("record_type")) or "ingredients"
    if record_type not in MASTER_DATA_PAGE_CONFIG:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Missing-image generation is not available for this master data type.",
        }), 400

    scope_info = master_data_form_scope()
    redirect_url = canonicalize_master_data_redirect_url(
        request.form.get("redirect_url"),
        default_page=record_type,
        fallback_scope_info=scope_info,
    )

    job_id = recipe_master_data.clean_text(request.form.get("job_id")) or uuid.uuid4().hex
    search = recipe_master_data.clean_text(request.form.get("search"))
    progress = recipe_master_images.start_master_image_generation_job(
        job_id,
        record_type=record_type,
        user_id=scope_info["user_id"],
        include_all_users=scope_info["include_all_users"],
        search=search,
    )

    return jsonify({
        "ok": True,
        "success": True,
        "job_id": job_id,
        "progress": progress,
        "scope": scope_info["scope"],
        "user_id": scope_info["user_id"],
        "include_all_users": scope_info["include_all_users"],
        "redirect_url": redirect_url,
    })


@main_bp.route("/api/master-data/image-generation-status")
def recipe_master_data_image_generation_status_route():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    job_id = recipe_master_data.clean_text(request.args.get("job_id"))
    progress = recipe_master_images.master_image_progress(job_id)
    if not progress:
        return jsonify({
            "ok": False,
            "success": False,
            "error": "No image-generation progress was found.",
        }), 404

    return jsonify({
        "ok": True,
        "success": True,
        "progress": progress,
    })


@main_bp.route("/api/device-stale", methods=["POST"])
def api_device_stale_route():
    return api_device_status_route()


@main_bp.route("/api/device-status", methods=["POST"])
def api_device_status_route():
    payload = request.get_json(silent=True) or {}
    user_id = str(active_user_id() or "").strip()
    guest_session_id = str(active_guest_session_id() or "").strip()
    if not user_id:
        payload = dict(payload)
        payload.pop("user_id", None)
    event = record_device_status_event(
        payload,
        request_user_agent=request.headers.get("User-Agent", ""),
        session_user_id=user_id,
        guest_session_id=guest_session_id,
    )
    return jsonify({
        "ok": True,
        "event": {
            "timestamp": event.get("timestamp"),
            "device_id": event.get("device_id"),
            "stale_reason": event.get("stale_reason"),
        },
    })


@main_bp.route("/api/openai_usage_dashboard", methods=["GET"])
def api_openai_usage_dashboard_route():
    return jsonify({
        "ok": True,
        "dashboard": openai_usage_dashboard_for_user(current_public_user()),
    })


@main_bp.route("/admin/chatgpt-models", methods=["POST"])
def update_chatgpt_models_route():
    user = current_public_user()
    if not is_admin_user(user):
        return jsonify({
            "ok": False,
            "success": False,
            "error": "Admin access is required.",
        }), 403

    show_advanced_models = request.form.get("show_advanced_models") == "1"
    action = request.form.get("action")
    refresh_models = action == "refresh_models"
    refresh_mappings = action == "refresh_mappings"
    refresh_lowest_viable_mappings = action == "refresh_lowest_viable_mappings"

    if refresh_models:
        session["chatgpt_model_force_refresh"] = True
        session["chatgpt_model_show_advanced"] = show_advanced_models
        session["chatgpt_model_messages"] = [
            {"category": "success", "text": "Refreshing OpenAI model list."}
        ]
    elif refresh_mappings:
        refresh_openai_model_recommendations()
        session["chatgpt_model_show_advanced"] = show_advanced_models
        session["chatgpt_model_messages"] = [
            {"category": "success", "text": "Refreshing recommended model mappings."}
        ]
    elif refresh_lowest_viable_mappings:
        refresh_lowest_viable_openai_model_recommendations()
        session["chatgpt_model_show_advanced"] = show_advanced_models
        session["chatgpt_model_messages"] = [
            {"category": "success", "text": "Refreshing lowest viable model mappings."}
        ]
    else:
        result = update_openai_model_settings_for_admin(user, request.form)
        if result.get("ok"):
            if str(action or "").startswith("use_proposed:"):
                session["chatgpt_model_force_refresh"] = True
            session["chatgpt_model_show_advanced"] = show_advanced_models
            session["chatgpt_model_messages"] = [
                {"category": "success", "text": "Chat GPT model settings updated."}
            ]
        else:
            session["chatgpt_model_messages"] = [
                {"category": "error", "text": error}
                for error in result.get("errors", ["Unable to update Chat GPT model settings."])
            ]

    return redirect(url_for("main_bp.index", account_panel="chatgpt_models", _anchor="chatGptModelsSection"))


def pdf_share_view_for_render():
    rows = []

    for row in list_available_pdfs():
        active_share = row.get("active_share")
        if active_share:
            active_share = {
                **active_share,
                "share_url": url_for("pdf_bp.share_pdf_route", token=active_share.get("token"), _external=True),
            }

        rows.append({
            **row,
            "view_url": (
                row.get("r2_public_url")
                or url_for("pdf_bp.view_pdf_route", pdf_filename=row["pdf_filename"])
            ),
            "active_share": active_share,
        })

    return {
        "pdfs": rows,
    }


US_STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


DEFAULT_STORES = {
    "aldi": {
        "label": "Aldi",
        "url": "https://www.aldi.us/store/aldi/s?k=",
        "urlStoreSelector": "https://info.aldi.us/stores",
    },
    "kroger": {
        "label": "Kroger",
        "url": "https://www.kroger.com/search?query=",
        "urlStoreSelector": "https://www.kroger.com/stores/search",
    },
    "walmart": {
        "label": "Walmart",
        "url": "https://www.walmart.com/search?q=",
        "urlStoreSelector": "https://www.walmart.com/",
    },
    "meijer": {
        "label": "Meijer",
        "url": "https://www.meijer.com/shopping/search.html?text=",
        "urlStoreSelector": "https://www.meijer.com/",
    },
    "target": {
        "label": "Target",
        "url": "https://www.target.com/s?searchTerm=",
        "urlStoreSelector": "https://www.target.com/store-locator/find-stores",
    },
    "costco": {
        "label": "Costco",
        "url": "https://www.costco.com/CatalogSearch?keyword=",
        "urlStoreSelector": "https://www.costco.com/s?keyword=&openFMW=true",
    },
}


def normalize(text):
    return " ".join(str(text).strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def shopping_items_only(items):
    return [
        item
        for item in items
        if not is_section_header(item)
    ]


def section_counts(items):
    counts = {}
    current_section = None

    for item in items:
        if is_section_header(item):
            current_section = item.replace("===", "").strip()
            counts.setdefault(current_section, 0)
            continue

        if current_section:
            counts[current_section] = counts.get(current_section, 0) + 1

    return counts


def recipe_pdf_public_url(recipe_url, pdf_kind=PDF_KIND_GENERATED_RECIPE):
    recipe_data = load_saved_recipe_output(recipe_url)
    metadata = normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind)
    public_url = str(metadata.get("public_url") or "").strip()

    return public_url if is_shareable_pdf_public_url(public_url) else ""


def recipe_view_rows(recipe_urls, food_rules=None, image_variants=None, include_detail_images=True):
    rows = []
    recipe_ingredient_data = load_recipe_ingredients()

    for index, recipe in enumerate(recipe_urls, start=1):
        recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
        recipe_data = load_saved_recipe_output(recipe["url"])
        recipe_meta = recipe_ingredient_data.get(normalize_recipe_url_key(recipe["url"]), {})
        cover_image = recipe_cover_image_for_view(
            recipe["url"],
            recipe_data,
            recipe_meta,
            variants=image_variants,
        )
        nutrition_summary = recipe_view_nutrition_summary(recipe_data.get("nutrition", {}))
        use_scaled_meta = multipliers_match(recipe_meta.get("quantity", 1), recipe_quantity)
        scaled_ingredients = recipe_meta.get("scaled_ingredients", {}) if use_scaled_meta else {}
        scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None
        sections = build_recipe_sections(
            recipe_data,
            recipe_quantity,
            scaled_ingredients,
            image_variants=image_variants,
        )

        rows.append({
            "number": index,
            "name": recipe_data.get("recipe_title") or recipe["name"],
            "url": recipe["url"],
            "source_type": recipe_data.get("source_type", ""),
            "ai_inferred": bool(recipe_data.get("ai_inferred")),
            "needs_ai_recipe": bool(recipe_data.get("needs_ai_recipe")),
            "recipe_status": recipe_data.get("recipe_status", ""),
            "menu_section": recipe_data.get("menu_section", ""),
            "menu_order_url": clean_display_text(recipe_data.get("menu_order_url") or recipe_data.get("deep_link_url")),
            "deep_link_url": clean_display_text(recipe_data.get("deep_link_url") or recipe_data.get("menu_order_url")),
            "parent_menu_snapshot_id": recipe_menu_snapshot_id(recipe_data),
            "menu_mega_snapshot_id": recipe_menu_snapshot_id(recipe_data),
            "source_href": recipe_source_href(recipe["url"]),
            "source_display_url": recipe_source_display_url(recipe["url"]),
            "pdf_public_url": recipe_pdf_public_url(recipe["url"]),
            "source_pdf_public_url": recipe_pdf_public_url(recipe["url"], PDF_KIND_WEBPAGE_BACKUP),
            "cover_image": cover_image,
            "description": recipe_description_for_view(recipe_data),
            "servings": recipe_data.get("servings", ""),
            "level": recipe_data.get("level", ""),
            "prep_time": recipe_data.get("prep_time", ""),
            "inactive_time": recipe_data.get("inactive_time", ""),
            "cook_time": recipe_data.get("cook_time", ""),
            "total_time": recipe_data.get("total_time", ""),
            "preview_time": recipe_preview_time_label(recipe_data),
            "quantity": recipe_quantity,
            "scaling_options": recipe_log_scaling_options(recipe_data, recipe_quantity),
            "archive_pdf_available": recipe_archive_pdf_exists(recipe["url"]),
            "food_rule_status": recipe_food_rule_status(recipe_data, food_rules=food_rules),
            "import_failure_status": recipe_import_failure_status(recipe_data),
            "rating": recipe_rating_for_view(recipe_data),
            "rating_stars": recipe_rating_stars_for_view(recipe_data),
            "favorite": bool(recipe_data.get("favorite")),
            "base_servings": recipe_data.get("servings"),
            "scaled_servings": scaled_servings or scale_servings(recipe_data.get("servings"), recipe_quantity),
            "serving_basis": nutrition_summary["serving_basis"],
            "calories": nutrition_summary["calories"],
            "equipment_items": (
                normalize_equipment_items(recipe_data.get("equipment", []), image_variants=image_variants)
                if include_detail_images
                else []
            ),
            "instruction_items": (
                normalize_instruction_items(recipe_data.get("instructions", []), image_variants=image_variants)
                if include_detail_images
                else []
            ),
            "recipe_notes": recipe_notes_for_view(recipe_data),
            "nutrition_items": normalize_nutrition_items(recipe_data.get("nutrition", {})),
            "sections": sections,
        })

    return rows


def recipe_view_nutrition_summary(nutrition):
    if not isinstance(nutrition, dict):
        return {"serving_basis": "", "calories": ""}

    return {
        "serving_basis": clean_display_text(nutrition.get("serving_basis")),
        "calories": clean_display_text(nutrition.get("calories")),
    }


def recipe_description_for_view(recipe_data):
    if not isinstance(recipe_data, dict):
        return ""

    for key in ("description", "summary", "recipe_description", "excerpt"):
        value = clean_display_text(recipe_data.get(key))
        if value:
            return value

    return ""


def recipe_notes_for_view(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    sections = []

    for key in ("recipe_notes", "recipe_note_sections", "source_notes"):
        sections.extend(normalize_recipe_note_sections(recipe_data.get(key)))

    raw = recipe_data.get("raw") if isinstance(recipe_data.get("raw"), dict) else {}
    for key in ("recipe_notes", "recipe_note_sections", "source_notes"):
        sections.extend(normalize_recipe_note_sections(raw.get(key)))

    seen = set()
    unique_sections = []
    for section in sections:
        heading = clean_display_text(section.get("heading"))
        items = [
            clean_display_text(item)
            for item in section.get("items", [])
            if clean_display_text(item)
        ]
        if not heading and not items:
            continue
        signature = (heading.lower(), tuple(item.lower() for item in items))
        if signature in seen:
            continue
        seen.add(signature)
        unique_sections.append({
            "heading": heading,
            "items": items,
        })

    return unique_sections


def recipe_import_failure_status(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    failures = recipe_data.get("menu_import_failures")
    normalized = []
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            stage = clean_display_text(failure.get("stage"))
            error = clean_display_text(failure.get("error") or failure.get("message"))
            if stage or error:
                normalized.append({
                    "stage": stage,
                    "error": error,
                    "failed_at": clean_display_text(failure.get("failed_at")),
                })

    if not normalized and (
        recipe_data.get("menu_import_failed")
        or recipe_data.get("menu_import_failure_error")
        or recipe_data.get("menu_import_failure_stage")
    ):
        normalized.append({
            "stage": clean_display_text(recipe_data.get("menu_import_failure_stage")),
            "error": clean_display_text(recipe_data.get("menu_import_failure_error")),
            "failed_at": clean_display_text(recipe_data.get("menu_import_failure_at")),
        })

    if not normalized:
        return {
            "failed": False,
            "label": "",
            "title": "",
            "stage": "",
            "error": "",
            "failures": [],
        }

    latest = normalized[-1]
    stage = latest.get("stage") or "Import"
    error = latest.get("error") or "This item failed during import."
    label = f"Failed: {stage}" if stage else "Failed"
    return {
        "failed": True,
        "label": label,
        "title": f"{stage}: {error}" if stage and error else error or label,
        "stage": stage,
        "error": error,
        "failures": normalized,
    }


def recipe_menu_snapshot_id(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_data.get("source_metadata") if isinstance(recipe_data.get("source_metadata"), dict) else {}
    return clean_display_text(
        recipe_data.get("parent_menu_snapshot_id")
        or recipe_data.get("menu_mega_snapshot_id")
        or recipe_data.get("menu_snapshot_id")
        or metadata.get("parent_menu_snapshot_id")
        or metadata.get("menu_mega_snapshot_id")
        or metadata.get("menu_snapshot_id")
    )


def recipe_rating_for_view(recipe_data):
    try:
        rating = int((recipe_data or {}).get("rating") or 0)
    except (TypeError, ValueError):
        return 0

    return max(0, min(5, rating))


def recipe_rating_stars_for_view(recipe_data):
    rating = recipe_rating_for_view(recipe_data)

    return "\u2605" * rating + "\u2606" * (5 - rating)


def apply_cookbook_assignments_to_recipe_rows(rows, cookbook_assignments):
    cookbook_assignments = cookbook_assignments or {}

    for row in rows:
        recipe_key = normalize_recipe_url_key(row.get("url", ""))
        cookbook_assignment = cookbook_assignments.get(recipe_key, {})
        row["cookbook_id"] = cookbook_assignment.get("cookbook_id", "")
        row["cookbook_name"] = cookbook_assignment.get("cookbook_name", "")
        row["cookbook_is_unclassified"] = cookbook_assignment.get("cookbook_is_unclassified", False)

    return rows


def recipe_url_log_rows(
    recipe_urls,
    cookbook_assignments=None,
    food_rules=None,
    image_variants=None,
    recipe_ingredient_data=None,
):
    rows = []
    recipe_ingredient_data = (
        recipe_ingredient_data
        if isinstance(recipe_ingredient_data, dict)
        else load_recipe_ingredients()
    )
    cookbook_assignments = cookbook_assignments or {}

    for recipe in recipe_urls:
        recipe_key = normalize_recipe_url_key(recipe["url"])
        recipe_data = load_saved_recipe_output(recipe["url"])
        recipe_meta = recipe_ingredient_data.get(recipe_key, {})
        nutrition_summary = recipe_view_nutrition_summary(recipe_data.get("nutrition", {}))
        recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
        use_scaled_meta = multipliers_match(recipe_meta.get("quantity", 1), recipe_quantity)
        scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None
        cookbook_assignment = cookbook_assignments.get(recipe_key, {})
        rows.append({
            **recipe,
            "quantity": recipe_quantity,
            "scaling_options": recipe_log_scaling_options(recipe_data, recipe_quantity),
            "source_type": recipe_data.get("source_type", ""),
            "ai_inferred": bool(recipe_data.get("ai_inferred")),
            "needs_ai_recipe": bool(recipe_data.get("needs_ai_recipe")),
            "recipe_status": recipe_data.get("recipe_status", ""),
            "meal_type": recipe_data.get("meal_type", ""),
            "recipe_category": recipe_data.get("recipe_category") or recipe_data.get("category") or "",
            "recipe_tags": recipe_data.get("tags") or recipe_data.get("recipe_tags") or [],
            "menu_section": recipe_data.get("menu_section", ""),
            "menu_order_url": clean_display_text(recipe_data.get("menu_order_url") or recipe_data.get("deep_link_url")),
            "deep_link_url": clean_display_text(recipe_data.get("deep_link_url") or recipe_data.get("menu_order_url")),
            "parent_menu_snapshot_id": recipe_menu_snapshot_id(recipe_data),
            "menu_mega_snapshot_id": recipe_menu_snapshot_id(recipe_data),
            "source_href": recipe_source_href(recipe["url"]),
            "source_display_url": recipe_source_display_url(recipe["url"]),
            "pdf_public_url": recipe_pdf_public_url(recipe["url"]),
            "source_pdf_public_url": recipe_pdf_public_url(recipe["url"], PDF_KIND_WEBPAGE_BACKUP),
            "cover_image": recipe_cover_image_for_view(
                recipe["url"],
                recipe_data,
                recipe_meta,
                variants=image_variants,
            ),
            "description": recipe_description_for_view(recipe_data),
            "servings": recipe_data.get("servings", ""),
            "level": recipe_data.get("level", ""),
            "prep_time": recipe_data.get("prep_time", ""),
            "inactive_time": recipe_data.get("inactive_time", ""),
            "cook_time": recipe_data.get("cook_time", ""),
            "total_time": recipe_data.get("total_time", ""),
            "food_rule_status": recipe_food_rule_status(recipe_data, food_rules=food_rules),
            "import_failure_status": recipe_import_failure_status(recipe_data),
            "rating": recipe_rating_for_view(recipe_data),
            "rating_stars": recipe_rating_stars_for_view(recipe_data),
            "favorite": bool(recipe_data.get("favorite")),
            "archive_pdf_available": recipe_archive_pdf_exists(recipe["url"]),
            "base_servings": recipe_data.get("servings"),
            "scaled_servings": scaled_servings or scale_servings(recipe_data.get("servings"), recipe_quantity),
            "serving_basis": nutrition_summary["serving_basis"],
            "calories": nutrition_summary["calories"],
            "cookbook_id": cookbook_assignment.get("cookbook_id", ""),
            "cookbook_name": cookbook_assignment.get("cookbook_name", ""),
            "cookbook_is_unclassified": cookbook_assignment.get("cookbook_is_unclassified", False),
        })

    return rows


def recipe_collection_breakdown(recipe_urls, records_by_key=None):
    records_by_key = records_by_key if isinstance(records_by_key, dict) else {}
    counts = {
        "created_by_you": 0,
        "ai_inferred": 0,
        "imported": 0,
    }

    for recipe in recipe_urls or []:
        if not isinstance(recipe, dict):
            continue

        recipe_url = str(recipe.get("url") or "").strip()
        recipe_key = normalize_recipe_url_key(recipe_url)
        recipe_record = records_by_key.get(recipe_key, {})
        recipe_record = recipe_record if isinstance(recipe_record, dict) else {}

        if recipe_url_type(recipe_url) == "Manual":
            counts["created_by_you"] += 1
        elif (
            recipe_record.get("ai_inferred")
            or str(recipe_record.get("source_type") or "").strip().lower() == "menu_item_inferred"
        ):
            counts["ai_inferred"] += 1
        else:
            counts["imported"] += 1

    return counts


def recipe_preview_time_label(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}

    for key in ("total_time", "cook_time", "prep_time"):
        value = str(recipe_data.get(key) or "").strip()
        if not value:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return f"{value} min"
        return value

    return "Time TBD"


def home_label_text(value):
    if isinstance(value, (list, tuple)):
        value = next((item for item in value if str(item or "").strip()), "")
    text = clean_display_text(value)
    text = re.sub(r"^[^A-Za-z0-9]+", "", text).strip()
    return text


def recipe_home_badge_label(recipe, cookbook_record=None):
    recipe = recipe if isinstance(recipe, dict) else {}
    cookbook_record = cookbook_record if isinstance(cookbook_record, dict) else {}
    candidates = (
        recipe.get("meal_type"),
        cookbook_record.get("meal_type"),
        recipe.get("recipe_category"),
        cookbook_record.get("recipe_category") or cookbook_record.get("category"),
        recipe.get("menu_section"),
        cookbook_record.get("menu_section") or cookbook_record.get("section_name"),
        recipe.get("recipe_tags"),
        cookbook_record.get("custom_categories"),
        cookbook_record.get("categories"),
        cookbook_record.get("menu_tags"),
    )
    return next((label for label in map(home_label_text, candidates) if label), "")


def recipe_card_cook_time_label(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    value = clean_display_text(recipe_data.get("cook_time"))
    if not value:
        return ""

    minutes = duration_minutes(value)
    if minutes is not None:
        return format_home_duration(minutes)
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return f"{value} min"
    return value


def recipe_card_calories_label(value):
    text = clean_display_text(value)
    if not text:
        return ""

    lowered = text.lower()
    if re.search(r"\b(?:cal|kcal|calorie|calories)\b", lowered):
        return text
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        number = float(text)
        display_number = str(int(number)) if number.is_integer() else text
        return f"{display_number} cal"
    return text


def format_home_duration(minutes):
    if minutes is None:
        return ""
    minutes = max(0, int(minutes))
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours} hr {remainder} min"
    if hours:
        return f"{hours} hr"
    return f"{remainder} min"


def recipe_home_preview_time_label(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    total_time = duration_minutes(recipe_data.get("total_time"))
    if total_time is not None:
        return format_home_duration(total_time)

    prep_time = duration_minutes(recipe_data.get("prep_time"))
    cook_time = duration_minutes(recipe_data.get("cook_time"))
    if prep_time is not None and cook_time is not None:
        return format_home_duration(prep_time + cook_time)
    if cook_time is not None:
        return format_home_duration(cook_time)
    return ""


HOME_IMPORT_JOB_TYPES = {
    "recipe-import": {"fallback_title": "Recipe URL import", "count_noun": "recipes imported", "icon": "link"},
    "doc-photo-import": {"fallback_title": "Recipe document import", "count_noun": "recipes extracted", "icon": "document"},
    "menu-import": {"fallback_title": "Menu import", "count_noun": "menu items extracted", "icon": "menus"},
    "menu-generate-recipes": {"fallback_title": "Menu recipe import", "count_noun": "recipes imported", "icon": "menus"},
}


def relative_time_label(value, reference_time=None):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference_time = reference_time or datetime.now(timezone.utc)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    seconds = max(0, int((reference_time - parsed.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def home_import_source_title(job, fallback_title):
    source_items = job.get("source_items") if isinstance(job.get("source_items"), list) else []
    first = source_items[0] if source_items and isinstance(source_items[0], dict) else {}
    label = clean_display_text(first.get("label"))
    if label.lower().startswith(("http://", "https://")):
        parsed = urlparse(label)
        path_name = parsed.path.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
        label = path_name or parsed.netloc
    if not label:
        label = fallback_title
    remaining = max(0, len(source_items) - 1)
    return f"{label} + {remaining} more" if remaining else label


def home_import_success_count(job):
    result = job.get("result_payload") if isinstance(job.get("result_payload"), dict) else {}
    for key in ("created_urls", "successful_urls", "recipes", "extracted_recipes"):
        values = result.get(key)
        if isinstance(values, list):
            return len(values)
    return max(0, int(job.get("completed_items") or 0))


def home_import_deleted_count(job):
    result = job.get("result_payload") if isinstance(job.get("result_payload"), dict) else {}
    deleted_urls = result.get("deleted_recipe_urls")
    if isinstance(deleted_urls, list):
        return len(deleted_urls)
    return max(0, int(result.get("deleted_recipe_count") or 0))


def home_import_count_text(count, count_noun):
    count = max(0, int(count or 0))
    noun = str(count_noun or "").strip()
    if count == 1:
        singular_nouns = {
            "recipes imported": "recipe imported",
            "recipes extracted": "recipe extracted",
            "menu items extracted": "menu item extracted",
        }
        noun = singular_nouns.get(noun, noun)
    return f"{count} {noun}".strip()


def home_recent_import_rows(jobs, limit=3, reference_time=None):
    rows = []
    for job in jobs or []:
        job_type = str((job or {}).get("job_type") or "").strip()
        config = HOME_IMPORT_JOB_TYPES.get(job_type)
        if not config:
            continue
        status = str(job.get("status") or "").strip().lower()
        completed_count = home_import_success_count(job)
        deleted_count = home_import_deleted_count(job)
        failed_count = max(0, int(job.get("failed_items") or 0))
        if status == "completed" and failed_count:
            status = "failed" if not completed_count else "completed_with_warnings"
        if status in {"completed", "completed_with_warnings"} and deleted_count:
            status = "completed_recipe_deleted"
        timestamp = (
            job.get("completed_at")
            or job.get("finished_at")
            or job.get("updated_at")
            or job.get("created_at")
        )
        count_text = ""
        if completed_count:
            count_text = home_import_count_text(completed_count, config["count_noun"])
        elif status in {"queued", "running", "cancel_requested"}:
            total_items = max(0, int(job.get("total_items") or 0))
            count_text = (
                f"{int(job.get('progress_percent') or 0)}% complete"
                if int(job.get("progress_percent") or 0)
                else (f"0 of {total_items} processed" if total_items else "Processing")
            )
        elif status in {"failed", "cancelled"}:
            count_text = "Import failed" if status == "failed" else "Import cancelled"
        result_note = ""
        if deleted_count == 1:
            result_note = "Recipe deleted"
        elif deleted_count > 1:
            result_note = f"{deleted_count} imported recipes deleted"
        rows.append({
            "job_id": str(job.get("id") or job.get("job_id") or ""),
            "title": home_import_source_title(job, config["fallback_title"]),
            "count_text": count_text,
            "time_label": relative_time_label(timestamp, reference_time=reference_time),
            "status": status or "queued",
            "source_icon": config["icon"],
            "error_message": clean_display_text(job.get("error_message")),
            "result_note": result_note,
        })
        if len(rows) >= max(1, int(limit or 3)):
            break
    return rows


def recipe_top_ingredient_rows(recipe_urls, recipe_ingredient_data=None, limit=5):
    recipe_ingredient_data = (
        recipe_ingredient_data
        if isinstance(recipe_ingredient_data, dict)
        else load_recipe_ingredients()
    )
    ingredient_counts = {}
    ingredient_labels = {}

    for recipe in recipe_urls or []:
        if not isinstance(recipe, dict):
            continue

        recipe_url = str(recipe.get("url") or "").strip()
        recipe_key = normalize_recipe_url_key(recipe_url)
        recipe_data = (
            recipe_ingredient_data.get(recipe_key)
            or recipe_ingredient_data.get(recipe_url)
            or {}
        )
        if not isinstance(recipe_data, dict):
            continue

        seen_ingredients = set()
        for ingredient in recipe_data.get("ingredients", []) or []:
            if isinstance(ingredient, dict):
                display_name = str(
                    ingredient.get("ingredient")
                    or ingredient.get("name")
                    or ingredient.get("original_text")
                    or ""
                ).strip()
            else:
                display_name = str(ingredient or "").strip()

            normalized_name = ingredient_key(display_name)
            if not normalized_name or normalized_name in seen_ingredients:
                continue

            seen_ingredients.add(normalized_name)
            ingredient_counts[normalized_name] = ingredient_counts.get(normalized_name, 0) + 1
            if normalized_name not in ingredient_labels:
                ingredient_labels[normalized_name] = (
                    display_name.title()
                    if display_name == display_name.lower()
                    else display_name
                )

    ranked_ingredients = sorted(
        ingredient_counts,
        key=lambda name: (-ingredient_counts[name], ingredient_labels.get(name, name).lower()),
    )
    return [
        {
            "name": ingredient_labels.get(name, name),
            "recipe_count": ingredient_counts[name],
        }
        for name in ranked_ingredients[:max(0, int(limit or 0))]
    ]


def recipe_cover_image_for_view(recipe_url, recipe_data, recipe_meta=None, variants=None):
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    candidates = []

    if isinstance(recipe_data, dict):
        candidates.append(recipe_data.get("cover_image"))

    candidates.append(recipe_meta.get("cover_image"))

    for cover_image in candidates:
        if not isinstance(cover_image, dict):
            continue

        src = recipe_cover_image_src(recipe_url, cover_image)

        if not src:
            continue

        variant_payload = recipe_cover_image_variant_payload(recipe_url, cover_image, src, variants=variants)
        alt = (
            str(cover_image.get("alt") or "").strip()
            or str((recipe_data or {}).get("recipe_title") or "").strip()
            or "Recipe cover image"
        )
        return {
            **cover_image,
            "src": src,
            "alt": alt,
            **variant_payload,
        }

    return {}


def recipe_cover_image_variant_payload(recipe_url, cover_image, original_src, variants=None):
    image_path = recipe_cover_image_file_path(cover_image)

    if not image_path:
        return local_static_image_variants(original_src, variants=variants)

    def build_url(variant, version):
        return recipe_cover_image_url(
            recipe_url,
            variant=variant,
            version=version,
        )

    return build_cover_image_variant_payload(original_src, image_path, build_url, variants=variants)


def recipe_cover_image_src(recipe_url, cover_image):
    if cover_image.get("path"):
        try:
            return recipe_cover_image_url(recipe_url)
        except RuntimeError:
            return ""

    return canonicalize_private_recipe_url(cover_image.get("url"))


def canonicalize_recipe_cover_image_payload(cover_image):
    """Refresh legacy rendered image links before returning them to a viewer."""

    result = dict(cover_image) if isinstance(cover_image, dict) else {}
    for field in (
        "url",
        "src",
        "thumb_url",
        "card_url",
        "detail_url",
        "display_url",
        "full_url",
    ):
        if result.get(field):
            result[field] = canonicalize_private_recipe_url(result[field])

    srcset = str(result.get("srcset") or "").strip()
    if "/recipe_cover_image" in srcset:
        entries = []
        for entry in srcset.split(","):
            parts = entry.strip().split()
            if parts:
                parts[0] = canonicalize_private_recipe_url(parts[0])
                entries.append(" ".join(parts))
        result["srcset"] = ", ".join(entries)

    return result


def cookbook_cover_image_for_view(recipe, recipe_data=None, recipe_meta=None, variants=None):
    if not isinstance(recipe, dict):
        return {}

    cover_image = recipe.get("cover_image")

    if isinstance(cover_image, dict):
        if cover_image.get("src"):
            alt = str(cover_image.get("alt") or recipe.get("name") or "Recipe cover image").strip()
            return {
                **canonicalize_recipe_cover_image_payload(cover_image),
                "alt": alt,
            }

        rendered_cover_image = recipe_cover_image_for_view(
            recipe.get("url", ""),
            {
                "recipe_title": recipe.get("name"),
                "cover_image": cover_image,
            },
            {"cover_image": cover_image},
            variants=variants,
        )

        if rendered_cover_image:
            return rendered_cover_image

    return recipe_cover_image_for_view(
        recipe.get("url", ""),
        recipe_data if isinstance(recipe_data, dict) else {},
        recipe_meta if isinstance(recipe_meta, dict) else {},
        variants=variants,
    )


def cookbook_view_for_render(recipe_rows, food_rules=None, image_variants=None):
    view = cookbook_view(recipe_rows)
    recipe_ingredient_data = load_recipe_ingredients()

    for cookbook in view.get("cookbooks", []):
        for recipe in cookbook.get("recipes", []):
            recipe_url = recipe.get("url", "")
            recipe_key = normalize_recipe_url_key(recipe_url)
            recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
            recipe_data = load_saved_recipe_output(recipe_url)
            recipe_meta = recipe_ingredient_data.get(recipe_key, {})
            nutrition_summary = recipe_view_nutrition_summary(recipe_data.get("nutrition", {}))
            use_scaled_meta = multipliers_match(recipe_meta.get("quantity", 1), recipe_quantity)
            scaled_servings = recipe_meta.get("scaled_servings") if use_scaled_meta else None

            recipe["name"] = recipe.get("name") or recipe_data.get("recipe_title") or recipe_url
            recipe_source_link = recipe.get("source_href") or recipe_source_href(recipe_url)
            recipe["source_href"] = (
                recipe_source_link
                if recipe_source_href_is_openable(recipe_source_link)
                else recipe_source_href(recipe_url)
            )
            recipe["source_display_url"] = (
                recipe.get("source_display_url")
                if recipe["source_href"]
                else recipe_source_display_url(recipe_url)
            ) or recipe_source_display_url(recipe_url)
            recipe["source_type"] = recipe_data.get("source_type") or recipe.get("source_type") or ""
            recipe["ai_inferred"] = bool(recipe_data.get("ai_inferred") or recipe.get("ai_inferred"))
            if recipe_data:
                recipe["needs_ai_recipe"] = bool(recipe_data.get("needs_ai_recipe"))
            else:
                recipe["needs_ai_recipe"] = bool(recipe.get("needs_ai_recipe"))
            recipe["recipe_status"] = recipe_data.get("recipe_status") or recipe.get("recipe_status") or ""
            if str(recipe["recipe_status"] or "").strip().lower() == "generated":
                recipe["needs_ai_recipe"] = False
            recipe["menu_section"] = recipe.get("menu_section") or recipe_data.get("menu_section", "")
            recipe["restaurant_id"] = recipe.get("restaurant_id") or recipe_data.get("restaurant_id", "")
            recipe["menu_id"] = recipe.get("menu_id") or recipe_data.get("menu_id", "")
            recipe["menu_section_id"] = recipe.get("menu_section_id") or recipe_data.get("menu_section_id", "")
            recipe["menu_item_id"] = recipe.get("menu_item_id") or recipe_data.get("menu_item_id", "")
            recipe["menu_item_name"] = recipe.get("menu_item_name") or recipe_data.get("menu_item_name", "")
            recipe["menu_description"] = recipe.get("menu_description") or recipe_data.get("menu_description", "")
            recipe["menu_price"] = recipe.get("menu_price") or recipe_data.get("menu_price", "")
            recipe["menu_order_url"] = clean_display_text(
                recipe.get("menu_order_url")
                or recipe_data.get("menu_order_url")
                or recipe.get("deep_link_url")
                or recipe_data.get("deep_link_url")
            )
            recipe["deep_link_url"] = clean_display_text(
                recipe.get("deep_link_url")
                or recipe_data.get("deep_link_url")
                or recipe.get("menu_order_url")
                or recipe_data.get("menu_order_url")
            )
            recipe["parent_menu_snapshot_id"] = recipe.get("parent_menu_snapshot_id") or recipe_menu_snapshot_id(recipe_data)
            recipe["menu_mega_snapshot_id"] = recipe.get("menu_mega_snapshot_id") or recipe_menu_snapshot_id(recipe_data)
            recipe["quantity"] = recipe_quantity
            recipe["description"] = recipe.get("description") or recipe_description_for_view(recipe_data)
            recipe["servings"] = recipe.get("servings") or recipe_data.get("servings", "")
            recipe["level"] = recipe.get("level") or recipe_data.get("level", "")
            recipe["prep_time"] = recipe.get("prep_time") or recipe_data.get("prep_time", "")
            recipe["inactive_time"] = recipe.get("inactive_time") or recipe_data.get("inactive_time", "")
            recipe["cook_time"] = recipe.get("cook_time") or recipe_data.get("cook_time", "")
            recipe["total_time"] = recipe.get("total_time") or recipe_data.get("total_time", "")
            recipe["scaling_options"] = recipe_log_scaling_options(recipe_data, recipe_quantity)
            recipe["food_rule_status"] = recipe_food_rule_status(recipe_data, food_rules=food_rules)
            recipe["import_failure_status"] = recipe_import_failure_status(recipe_data)
            recipe["rating"] = recipe_rating_for_view(recipe_data)
            recipe["rating_stars"] = recipe_rating_stars_for_view(recipe_data)
            recipe["favorite"] = bool(recipe_data.get("favorite"))
            recipe["pdf_public_url"] = recipe_pdf_public_url(recipe_url)
            recipe["source_pdf_public_url"] = recipe_pdf_public_url(recipe_url, PDF_KIND_WEBPAGE_BACKUP)
            recipe["archive_pdf_available"] = recipe_archive_pdf_exists(recipe_url)
            recipe["base_servings"] = recipe.get("base_servings") or recipe_data.get("servings")
            recipe["scaled_servings"] = (
                scaled_servings
                or recipe.get("scaled_servings")
                or scale_servings(recipe_data.get("servings"), recipe_quantity)
            )
            recipe["serving_basis"] = recipe.get("serving_basis") or nutrition_summary["serving_basis"]
            recipe["calories"] = recipe.get("calories") or nutrition_summary["calories"]
            recipe["cover_image"] = cookbook_cover_image_for_view(
                recipe,
                recipe_data=recipe_data,
                recipe_meta=recipe_meta,
                variants=image_variants,
            )

    for recipe in view.get("recipes", []):
        recipe["cover_image"] = cookbook_cover_image_for_view(recipe, variants=image_variants)

    return prepare_cookbook_menu_view(view)


def recipe_log_scaling_options(recipe_data, selected_multiplier):
    scaling = recipe_scaling_from_data(recipe_data, default_to_common=True)
    options = scaling.get("available_multipliers", [])
    selected_multiplier = normalize_recipe_quantity(selected_multiplier)
    normalized_options = []
    selected_found = False

    for option in options:
        value = normalize_recipe_quantity(option.get("value") if isinstance(option, dict) else option)
        selected = multipliers_match(value, selected_multiplier)
        selected_found = selected_found or selected
        normalized_options.append({
            "label": option.get("label") if isinstance(option, dict) and option.get("label") else scaling_multiplier_label(value),
            "value": value,
            "selected": selected,
        })

    if not selected_found:
        normalized_options.append({
            "label": scaling_multiplier_label(selected_multiplier),
            "value": selected_multiplier,
            "selected": True,
        })

    return sorted(normalized_options, key=lambda option: float(option["value"]))


def multipliers_match(left, right):
    return abs(float(normalize_recipe_quantity(left)) - float(normalize_recipe_quantity(right))) < 0.000001


def recipe_source_href(recipe_url):
    if imported_recipe_uses_pdf_path(recipe_url):
        return recipe_archive_pdf_url(recipe_url)

    return recipe_url if recipe_source_href_is_openable(recipe_url) else ""


def recipe_source_href_is_openable(value):
    value = clean_display_text(value)
    if not value:
        return False

    lower_value = value.lower()
    if lower_value.startswith(("uploaded://", "manual://", "menu-item://")):
        return False

    return lower_value.startswith(("http://", "https://", "/"))


def recipe_source_display_url(recipe_url):
    if recipe_url_type(recipe_url) == "File":
        if not recipe_archive_pdf_exists(recipe_url):
            filename = str(recipe_url or "").replace("uploaded://", "", 1).strip()
            return f"Uploaded file: {filename}" if filename else "Uploaded file"
        return str(recipe_archive_pdf_path(recipe_url))

    return recipe_url


def imported_recipe_uses_pdf_path(recipe_url):
    return recipe_url_type(recipe_url) == "File" and recipe_archive_pdf_exists(recipe_url)


def recipe_food_rule_status(recipe_data, food_rules=None):
    flagged_items = []

    for ingredient in recipe_data.get("ingredients", []) or []:
        if isinstance(ingredient, dict):
            name = str(ingredient.get("ingredient") or ingredient.get("original_text") or "").strip()
            text = " ".join([
                str(ingredient.get("ingredient") or ""),
                str(ingredient.get("original_text") or ""),
                str(ingredient.get("preparation") or ""),
            ])
        else:
            name = str(ingredient or "").strip()
            text = name

        if not text.strip():
            continue

        status = shopping_item_food_rule_status(text, rules=food_rules)
        label = name or "Ingredient"

        if status.get("needs_review"):
            issue_text = status.get("marker", "").replace("Food rule review: ", "")
            flagged_items.append(f"{label}: {issue_text}" if issue_text else label)

        text_review = recipe_view_ingredient_food_review(ingredient) if isinstance(ingredient, dict) else {}
        if text_review.get("needs_review"):
            issue_text = str(text_review.get("reason") or "").strip()
            flagged_items.append(f"{label}: {issue_text}" if issue_text else label)

    seen = set()
    unique_items = []
    for item in flagged_items:
        key = item.lower()
        if key not in seen:
            unique_items.append(item)
            seen.add(key)

    return {
        "needs_review": bool(unique_items),
        "marker": "Food rule review: " + "; ".join(unique_items) if unique_items else "",
        "count": len(unique_items),
    }


def recipe_food_rule_ingredient_has_text(ingredient):
    if isinstance(ingredient, dict):
        return bool(" ".join([
            str(ingredient.get("ingredient") or ""),
            str(ingredient.get("original_text") or ""),
            str(ingredient.get("preparation") or ""),
        ]).strip())

    return bool(str(ingredient or "").strip())


def recipe_food_rule_checked_ingredient_count(recipe_data):
    return sum(
        1
        for ingredient in recipe_data.get("ingredients", []) or []
        if recipe_food_rule_ingredient_has_text(ingredient)
    )


def recipe_food_rule_apply_summary(recipe_url, recipe_data, food_rules=None):
    status = recipe_food_rule_status(recipe_data, food_rules=food_rules)
    return {
        "recipe_url": recipe_url,
        "recipe_name": (
            recipe_data.get("display_name")
            or recipe_data.get("recipe_title")
            or recipe_url
        ),
        "checked_ingredients": recipe_food_rule_checked_ingredient_count(recipe_data),
        "flagged_ingredients": status.get("count", 0),
        "needs_review": bool(status.get("needs_review")),
        "marker": status.get("marker", ""),
    }


def apply_food_rules_to_saved_recipe(recipe_url, food_rules=None):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_saved_recipe_output(recipe_url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe was not found."}

    rules = food_rules if food_rules is not None else load_food_rules()
    source_url = str(recipe_data.get("source_url") or recipe_url).strip() or recipe_url
    applied_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = recipe_food_rule_apply_summary(source_url, recipe_data, food_rules=rules)
    recipe_data["food_rules_last_applied_at"] = applied_at
    recipe_data["food_rules_last_applied"] = {
        **summary,
        "applied_at": applied_at,
    }
    save_recipe_output(recipe_url, recipe_data)

    return {
        "ok": True,
        **summary,
        "applied_at": applied_at,
    }


def cookbook_for_food_rule_apply(cookbook_id):
    cookbook_id = str(cookbook_id or "").strip()

    for cookbook in load_cookbooks().get("cookbooks", []):
        if str(cookbook.get("id") or "").strip() == cookbook_id:
            return cookbook

    return {}


def recipe_quantity_lookup(recipe_rows):
    quantities = {}

    for recipe in recipe_rows:
        for section_items in recipe.get("sections", {}).values():
            for item in section_items:
                display_name = item.get("display_name") or item.get("name")
                quantity_display = item.get("quantity_display") or item.get("base_display")

                if not display_name or not quantity_display:
                    continue

                key = normalize(display_name)
                quantities.setdefault(key, []).append(str(quantity_display).strip())

    return {
        key: summarize_quantity_displays(values)
        for key, values in quantities.items()
    }


def recipe_quantity_sources_lookup(recipe_rows):
    sources = {}

    for recipe in recipe_rows:
        recipe_number = recipe.get("number")
        recipe_label = f"Recipe {recipe_number} Qty" if recipe_number else "Recipe Qty"

        for section_items in recipe.get("sections", {}).values():
            for item in section_items:
                display_name = item.get("display_name") or item.get("name")
                quantity_display = item.get("quantity_display") or item.get("base_display")

                if not display_name or not quantity_display:
                    continue

                key = normalize(display_name)
                sources.setdefault(key, []).append({
                    "label": recipe_label,
                    "ingredient": str(item.get("name") or display_name).strip(),
                    "recipe_ingredient": str(item.get("name") or display_name).strip(),
                    "purchasable_item": str(item.get("purchasable_item") or item.get("buy_as") or display_name).strip(),
                    "purchase_group": str(item.get("purchase_group") or item.get("purchasable_item") or item.get("buy_as") or display_name).strip(),
                    "purchase_group_key": str(item.get("purchase_group_key") or key).strip(),
                    "default_quantity": str(item.get("base_display") or "").strip(),
                    "default_quantity_value": str(item.get("base_quantity") or "").strip(),
                    "default_unit": str(item.get("unit") or "").strip(),
                    "recipe_number": recipe_number,
                    "recipe_quantity": recipe.get("quantity") or 1,
                    "url": recipe.get("url") or "",
                    "quantity": str(quantity_display).strip(),
                })

    return sources


def apply_manual_item_quantities(item_quantities, item_state):
    quantities = dict(item_quantities)

    for item_key, state in item_state.items():
        if not isinstance(state, dict):
            continue

        manual_qty = str(state.get("manual_qty") or "").strip()
        if manual_qty:
            quantities[normalize(item_key)] = manual_qty

    return quantities


def summarize_quantity_displays(values):
    cleaned_values = [
        value
        for value in values
        if value
    ]

    if not cleaned_values:
        return ""

    if len(cleaned_values) == 1:
        return cleaned_values[0]

    summed = sum_quantity_displays(cleaned_values)
    if summed:
        return summed

    unique_values = []
    seen = set()

    for value in cleaned_values:
        key = normalize(value)

        if key not in seen:
            unique_values.append(value)
            seen.add(key)

    return " + ".join(unique_values)


def sum_quantity_displays(values):
    parsed_values = [
        parse_quantity_display(value)
        for value in values
    ]

    if not parsed_values or any(value is None for value in parsed_values):
        return ""

    unit_order = []
    grouped_values = {}

    for value in parsed_values:
        unit = value["unit"]

        if unit not in grouped_values:
            unit_order.append(unit)
            grouped_values[unit] = []

        grouped_values[unit].append(value)

    return " + ".join(
        sum_parsed_quantity_group(grouped_values[unit], unit)
        for unit in unit_order
    )


def sum_parsed_quantity_group(values, unit):
    low_total = sum(value["low"] for value in values)
    has_range = any(value["high"] is not None for value in values)
    high_total = (
        sum(value["high"] if value["high"] is not None else value["low"] for value in values)
        if has_range
        else None
    )

    if high_total is not None and high_total != low_total:
        quantity_text = f"{format_fraction(low_total)} to {format_fraction(high_total)}"
    else:
        quantity_text = format_fraction(low_total)

    return format_quantity_unit(quantity_text, unit)


def parse_quantity_display(value):
    text = str(value or "").strip()

    if not text or " OR " in text.upper():
        return None

    match = re.match(
        r"^(?P<low>\d+(?:\s+\d+/\d+|/\d+)?)(?:\s*(?:-|to)\s*(?P<high>\d+(?:\s+\d+/\d+|/\d+)?))?(?:\s+(?P<unit>.+))?$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    low = parse_quantity_fraction(match.group("low"))
    high = parse_quantity_fraction(match.group("high")) if match.group("high") else None

    if low is None or (match.group("high") and high is None):
        return None

    return {
        "low": low,
        "high": high,
        "unit": normalize_quantity_unit(match.group("unit")),
    }


def normalize_quantity_unit(unit):
    unit = str(unit or "").strip()
    registered = canonical_unit(unit)
    if registered:
        return registered["name"]
    unit_key = unit.lower()
    singular_units = {
        "c": "cup",
        "c.": "cup",
        "cups": "cup",
        "tsp": "teaspoon",
        "tsp.": "teaspoon",
        "teaspoons": "teaspoon",
        "tbsp": "tablespoon",
        "tbsp.": "tablespoon",
        "tbs": "tablespoon",
        "tbs.": "tablespoon",
        "tablespoons": "tablespoon",
        "oz": "ounce",
        "oz.": "ounce",
        "ounces": "ounce",
        "lb": "pound",
        "lb.": "pound",
        "lbs": "pound",
        "lbs.": "pound",
        "pounds": "pound",
        "g": "g",
        "grams": "gram",
        "kg": "kilogram",
        "kilograms": "kilogram",
        "ml": "milliliter",
        "milliliters": "milliliter",
        "l": "liter",
        "liters": "liter",
        "pinches": "pinch",
        "dashes": "dash",
        "cloves": "clove",
        "sticks": "stick",
    }

    return singular_units.get(unit_key, unit)


def saved_recipe_output_index():
    if has_request_context():
        cached = getattr(g, "_saved_recipe_output_index", None)
        if cached is not None:
            return cached

    index = {}

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        recipe_key = normalize_recipe_url_key(data.get("source_url", ""))
        if recipe_key:
            index[recipe_key] = data

    if has_request_context():
        g._saved_recipe_output_index = index

    return index


def load_saved_recipe_output(recipe_url):
    # The editor loader overlays the user-scoped normalized SQLite hierarchy
    # when it exists. Keep route-level meal/shopping resolution on that same
    # source of truth instead of consulting the JSON-only index directly.
    return load_recipe_output(recipe_url) or {}


def build_recipe_sections(recipe_data, recipe_quantity=1, scaled_ingredients=None, image_variants=None):
    sections = {section: [] for section in STORE_SECTION_ORDER.keys()}
    scaled_ingredients = scaled_ingredients or {}

    for ingredient_index, ingredient in enumerate(recipe_data.get("ingredients", []) or [], start=1):
        if not isinstance(ingredient, dict):
            continue

        name = str(ingredient.get("ingredient", "") or "").strip()
        if not name:
            continue

        section = str(ingredient.get("store_section", "") or "MISC").strip().upper()
        if section not in sections:
            section = "MISC"

        scaled_value = scaled_ingredients.get(name) or scaled_ingredients.get(ingredient_key(name)) or {}
        scaled_quantity = scaled_value.get("quantity") if isinstance(scaled_value, dict) else None
        scaled_unit = scaled_value.get("unit") if isinstance(scaled_value, dict) else None
        scaled_display = scaled_value.get("display") if isinstance(scaled_value, dict) else None
        fallback_quantity = scale_quantity(ingredient.get("quantity"), recipe_quantity)
        display_name = name
        base_display = format_quantity_unit(ingredient.get("quantity"), ingredient.get("unit"))
        quantity_display = scaled_display
        alternative = parse_quantity_alternative(
            name,
            ingredient.get("quantity"),
            ingredient.get("unit"),
            recipe_quantity,
            scaled_quantity or fallback_quantity,
        )

        if alternative:
            display_name = alternative["name"]
            base_display = alternative["base_display"]
            quantity_display = alternative["scaled_display"] if not multipliers_match(recipe_quantity, 1) else alternative["base_display"]

        purchase_mapping = purchase_mapping_for_recipe_ingredient(ingredient)
        food_review = recipe_view_ingredient_food_review(ingredient)
        ingredient_image_url = clean_display_text(
            ingredient.get("ingredient_image_url") or ingredient.get("image_url") or ""
        )
        ingredient_image_generated_at = clean_display_text(
            ingredient.get("ingredient_image_generated_at") or ingredient.get("image_generated_at") or ""
        )
        image_variant_payload = local_static_image_variants(
            ingredient_image_url,
            variants=image_variants,
        )

        sections[section].append({
            "ingredient_index": ingredient_index,
            "name": name,
            "display_name": display_name,
            "purchasable_item": purchase_mapping["purchasable_item"],
            "buy_as": purchase_mapping["buy_as"],
            "purchase_group": purchase_mapping["purchase_group"],
            "purchase_group_key": purchase_mapping["purchase_group_key"],
            "purchase_is_mapped": purchase_mapping["is_mapped"],
            "quantity": ingredient.get("quantity"),
            "base_quantity": ingredient.get("quantity"),
            "scaled_quantity": scaled_quantity or fallback_quantity,
            "unit": scaled_unit if scaled_unit is not None else ingredient.get("unit"),
            "base_display": base_display,
            "quantity_display": quantity_display,
            "url": recipe_data.get("source_url"),
            "food_review": food_review,
            "ingredient_image_url": ingredient_image_url,
            "ingredient_image_display_url": image_variant_payload.get("display_url") or ingredient_image_url,
            "ingredient_image_srcset": image_variant_payload.get("srcset", ""),
            "ingredient_image_full_url": image_variant_payload.get("full_url") or ingredient_image_url,
            "ingredient_image_generated_at": ingredient_image_generated_at,
        })

    return {
        section: sorted(items, key=lambda item: normalize(item["name"]))
        for section, items in sections.items()
        if items
    }


def recipe_view_ingredient_food_review(ingredient):
    if not isinstance(ingredient, dict):
        return {}

    review = ingredient.get("food_review")
    if not review:
        review = fallback_ingredient_text_review(ingredient)

    normalized = normalize_ingredient_text_review(review, ingredient)
    if isinstance(normalized, dict):
        return normalized

    return recipe_ingredient_choice_review(ingredient)


def recipe_ingredient_choice_review(ingredient):
    if not isinstance(ingredient, dict):
        return {}

    primary_fields = (
        ("ingredient", ingredient.get("ingredient")),
        ("purchasable_item", ingredient.get("purchasable_item")),
    )

    for source_field, value in primary_fields:
        review = ingredient_choice_review_from_text(value, source_field)

        if review:
            return review

    has_named_ingredient = any(
        str(value or "").strip()
        for _source_field, value in primary_fields
    )

    if not has_named_ingredient:
        return ingredient_choice_review_from_text(ingredient.get("original_text"), "original_text")

    return {}


INGREDIENT_CHOICE_SEPARATOR_PATTERN = re.compile(r"\s+(?:and\s*/\s*or|and/or|or)\s+", re.IGNORECASE)
INGREDIENT_AND_OR_SEPARATOR_PATTERN = re.compile(r"\s+(?:and\s*/\s*or|and/or)\s+", re.IGNORECASE)


def ingredient_choice_review_from_text(value, source_field):
    text = str(value or "").strip()
    choice_text = re.sub(r"\([^)]*\)", " ", text)

    if not INGREDIENT_CHOICE_SEPARATOR_PATTERN.search(choice_text):
        return {}

    options = unique_ingredient_choice_options(
        expand_ingredient_choice_shared_nouns(
            [
                clean_ingredient_choice_option(option)
                for option in INGREDIENT_CHOICE_SEPARATOR_PATTERN.split(choice_text)
            ]
        )
    )

    if len(options) < 2 or len(options) > 4:
        return {}

    return {
        "needs_review": True,
        "kind": "ingredient_choice",
        "reason": "Pick one option: " + ", ".join(options) + ".",
        "prompt": "Pick one option",
        "options": [
            {
                "ingredient": option,
                "purchasable_item": option,
                "reason": "",
            }
            for option in options
        ],
        "source": source_field,
        "allow_create_ingredient": bool(INGREDIENT_AND_OR_SEPARATOR_PATTERN.search(choice_text)),
    }


def clean_ingredient_choice_option(value):
    text = str(value or "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"^[\s,;:/-]+", "", text)
    text = re.sub(r"^[\d\s./]+", "", text)
    text = re.sub(
        r"^(?:cups?|tablespoons?|tbsp\.?|teaspoons?|tsp\.?|ounces?|oz\.?|"
        r"pounds?|lbs?\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch(?:es)?|dash(?:es)?|cloves?|slices?|cans?|packages?|pkg\.?)\b\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:divided|optional|to taste|as needed)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^[\s,;:/-]+|[\s,;:/-]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def expand_ingredient_choice_shared_nouns(options):
    cleaned = [
        str(option or "").strip()
        for option in options
        if str(option or "").strip()
    ]

    if any(re.search(r"\btortillas?\b", option, flags=re.IGNORECASE) for option in cleaned):
        return [normalize_tortilla_choice_option(option) for option in cleaned]

    return cleaned


def normalize_tortilla_choice_option(option):
    cleaned = re.sub(r"\bflower\b", "flour", str(option or ""), flags=re.IGNORECASE)
    cleaned = re.sub(r"\btortillas\b", "tortilla", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned or re.search(r"\btortilla\b", cleaned, flags=re.IGNORECASE):
        return cleaned

    return f"{cleaned} tortilla"


def unique_ingredient_choice_options(options):
    seen = set()
    cleaned = []

    for option in options:
        value = str(option or "").strip()
        key = normalize(value)

        if not value or len(value) < 2 or not key or key in seen:
            continue

        seen.add(key)
        cleaned.append(value)

    return cleaned


def scale_servings(servings, multiplier):
    servings_text = str(servings or "").strip()

    if not servings_text or multiplier == 1:
        return servings

    match = re.search(r"\d+(?:\.\d+)?", servings_text)
    if not match:
        return servings

    scaled = format_number(float(match.group(0)) * multiplier)
    return servings_text[:match.start()] + scaled + servings_text[match.end():]


def scale_quantity(quantity, multiplier):
    quantity_text = str(quantity or "").strip()

    if not quantity_text or multiplier == 1:
        return quantity

    range_match = re.match(r"^(.+?)\s*(?:-|to)\s*(.+)$", quantity_text)
    if range_match:
        left = scale_quantity_part(range_match.group(1), multiplier)
        right = scale_quantity_part(range_match.group(2), multiplier)
        separator = " to " if " to " in quantity_text else "-"
        return f"{left}{separator}{right}"

    return scale_quantity_part(quantity_text, multiplier)


def parse_quantity_alternative(name, quantity, unit, recipe_quantity, scaled_quantity):
    match = re.match(
        r"^(?P<first>.+?)\s+or\s+(?P<quantity>\d+(?:\s+\d+/\d+|/\d+)?|\d+/\d+)\s+(?P<unit>[A-Za-z]+)\s+(?P<second>.+)$",
        str(name or "").strip(),
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    first_name = match.group("first").strip()
    second_quantity = match.group("quantity").strip()
    second_unit = match.group("unit").strip()
    second_name = match.group("second").strip()
    first_base = format_quantity_unit(quantity, unit)
    second_base = format_quantity_unit(second_quantity, second_unit)
    first_scaled = format_quantity_unit(scaled_quantity, unit)
    second_scaled = format_quantity_unit(scale_quantity(second_quantity, recipe_quantity), second_unit)

    return {
        "name": f"{first_name} OR {second_name}",
        "base_display": f"{first_base} OR {second_base}",
        "scaled_display": f"{first_scaled} OR {second_scaled}",
    }


def format_quantity_unit(quantity, unit):
    quantity = str(quantity or "").strip()
    unit = display_unit(unit, quantity)

    if not quantity:
        return ""

    return f"{quantity} {unit}".strip()


def scale_quantity_part(value, multiplier):
    parsed = parse_quantity_fraction(value)

    if parsed is None:
        return value

    return format_fraction(parsed * multiplier)


def parse_quantity_fraction(value):
    text = str(value or "").strip()

    mixed_match = re.match(r"^(\d+)\s+(\d+)/(\d+)$", text)
    if mixed_match:
        whole, numerator, denominator = mixed_match.groups()
        return Fraction(int(whole), 1) + Fraction(int(numerator), int(denominator))

    fraction_match = re.match(r"^(\d+)/(\d+)$", text)
    if fraction_match:
        numerator, denominator = fraction_match.groups()
        return Fraction(int(numerator), int(denominator))

    decimal_match = re.match(r"^\d+(?:\.\d+)?$", text)
    if decimal_match:
        return Fraction(text)

    return None


def format_fraction(value):
    value = Fraction(value)

    if value.denominator == 1:
        return str(value.numerator)

    whole = value.numerator // value.denominator
    remainder = value - whole

    if whole:
        return f"{whole} {remainder.numerator}/{remainder.denominator}"

    return f"{remainder.numerator}/{remainder.denominator}"


def format_number(value):
    if float(value).is_integer():
        return str(int(value))

    return f"{value:g}"


def normalize_text_list(value):
    if not value:
        return []

    if isinstance(value, str):
        return [value]

    if not isinstance(value, list):
        return []

    items = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("name") or item.get("text") or item.get("equipment") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            items.append(text)

    return items


def normalize_equipment_items(value, image_variants=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_list(value)

    items = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = clean_display_text(item.get("equipment") or item.get("text") or item.get("name") or "")
            equipment_image_url = clean_display_text(item.get("equipment_image_url") or item.get("image_url") or "")
            equipment_image_generated_at = clean_display_text(
                item.get("equipment_image_generated_at") or item.get("image_generated_at") or ""
            )
        else:
            text = clean_display_text(item)
            equipment_image_url = ""
            equipment_image_generated_at = ""

        if text:
            image_variant_payload = local_static_image_variants(
                equipment_image_url,
                variants=image_variants,
            )
            items.append({
                "number": index,
                "text": text,
                "equipment": text,
                "equipment_image_url": equipment_image_url,
                "equipment_image_display_url": image_variant_payload.get("display_url") or equipment_image_url,
                "equipment_image_srcset": image_variant_payload.get("srcset", ""),
                "equipment_image_full_url": image_variant_payload.get("full_url") or equipment_image_url,
                "equipment_image_generated_at": equipment_image_generated_at,
            })

    return items


def normalize_instruction_items(value, image_variants=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_list(value)

    items = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = clean_display_text(item.get("instruction") or item.get("text") or "")
            step_number = item.get("step_number") or index
            step_image_url = clean_display_text(item.get("step_image_url") or item.get("image_url") or "")
            step_image_generated_at = clean_display_text(
                item.get("step_image_generated_at") or item.get("image_generated_at") or ""
            )
        else:
            text = clean_display_text(item)
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if text:
            image_variant_payload = local_static_image_variants(
                step_image_url,
                variants=image_variants,
            )
            items.append({
                "step_number": step_number,
                "text": text,
                "instruction": text,
                "step_image_url": step_image_url,
                "step_image_display_url": image_variant_payload.get("display_url") or step_image_url,
                "step_image_srcset": image_variant_payload.get("srcset", ""),
                "step_image_full_url": image_variant_payload.get("full_url") or step_image_url,
                "step_image_generated_at": step_image_generated_at,
            })

    return items


def clean_display_text(value):
    return " ".join(html.unescape(str(value or "")).split())


def normalize_nutrition_items(nutrition):
    if not isinstance(nutrition, dict):
        return []

    labels = {
        "serving_basis": "Serving basis",
        "calories": "Calories",
        "carbohydrates": "Carbohydrates",
        "protein": "Protein",
        "fat": "Fat",
        "saturated_fat": "Saturated fat",
        "polyunsaturated_fat": "Polyunsaturated fat",
        "monounsaturated_fat": "Monounsaturated fat",
        "trans_fat": "Trans fat",
        "cholesterol": "Cholesterol",
        "sodium": "Sodium",
        "potassium": "Potassium",
        "fiber": "Fiber",
        "sugar": "Sugar",
        "vitamin_a": "Vitamin A",
        "vitamin_c": "Vitamin C",
        "calcium": "Calcium",
        "iron": "Iron",
    }

    items = [
        {"label": label, "value": value}
        for key, label in labels.items()
        for value in [nutrition.get(key)]
        if value
    ]

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                label = item.get("label") or item.get("name") or "Other"
                value = item.get("value") or item.get("amount")
                if value:
                    items.append({"label": label, "value": value})

    return items


def build_store_view(items, item_state, available_stores, enabled_stores):
    section_order = []
    item_sections = {}
    current_section = "MISC"

    for item in items:
        if is_section_header(item):
            current_section = item.replace("===", "").strip()
            if current_section not in section_order:
                section_order.append(current_section)
            continue

        item_sections[item] = current_section

    if "MISC" not in section_order:
        section_order.append("MISC")

    store_keys = [
        store_key
        for store_key in enabled_stores
        if store_key in available_stores
    ]
    buckets = {store_key: {} for store_key in store_keys}
    buckets["unselected"] = {}

    for item, section in item_sections.items():
        purchase_mapping = purchase_mapping_for_item(item, item_state=item_state)
        purchase_state = item_state.get(purchase_mapping["purchase_group_key"], {})
        item_specific_state = item_state.get(normalize(item), {})
        selected_store = purchase_state.get("store") or item_specific_state.get("store")
        bucket_key = selected_store if selected_store in store_keys else "unselected"
        buckets[bucket_key].setdefault(section, []).append(item)

    display_rows = []

    for store_key in store_keys + ["unselected"]:
        sections = buckets.get(store_key, {})
        cleaned_sections = []

        for section in section_order:
            section_items = sections.get(section, [])
            if section_items:
                cleaned_sections.append({
                    "name": section,
                    "items": sorted(section_items, key=normalize),
                })

        if not cleaned_sections:
            continue

        store = available_stores.get(store_key, {})
        display_rows.append({
            "key": store_key,
            "label": store.get("label", "Unselected" if store_key == "unselected" else store_key.title()),
            "sections": cleaned_sections,
        })

    return display_rows


@main_bp.route("/")
def index():
    active_public_user = current_public_user()

    if not active_public_user and not is_guest_session():
        response = make_response(render_template("public_auth.html", **public_auth_page_context()))
    else:
        response = make_response(render_template("index.html", **shell_context(active_public_user)))

    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


@main_bp.route("/terms")
def terms_route():
    return render_template("legal_page.html", **legal_page_context("terms"))


@main_bp.route("/privacy")
def privacy_route():
    return render_template("legal_page.html", **legal_page_context("privacy"))


def clean_global_search_query(value):
    """Normalize decoded search text before the canonical encoding pass."""

    return " ".join(str(value or "").strip().split())[:160]


def clean_global_search_group(value):
    group = str(value or "").strip().lower()
    return group if group in GROUP_LABELS else ""


def clean_global_search_limit(value, *, query):
    """Return the effective compact-search limit and its canonical value."""

    default = DEFAULT_RESULT_LIMIT if query else 4
    maximum = MAX_RESULT_LIMIT if query else 4
    try:
        limit = int(str(value).strip())
    except (TypeError, ValueError):
        limit = default
    return max(1, min(maximum, limit)), default


def canonical_global_search_request(*, api):
    """Validate viewer identity and normalize one global-search GET URL."""

    viewer = validate_authenticated_viewer(request.args)
    query = clean_global_search_query(request.args.get("q"))
    group_filter = clean_global_search_group(request.args.get("type"))
    if api and not query:
        # An empty API query returns recent records, so a record type is not a
        # meaningful filter and must not survive in a canonical URL.
        group_filter = ""

    overrides = [
        ("viewer_user_id", viewer.viewer_user_id),
        ("q", query),
        ("type", group_filter),
    ]
    allowed_keys = {"viewer_user_id", "q", "type"}
    limit = DEFAULT_RESULT_LIMIT
    if api:
        limit, default_limit = clean_global_search_limit(
            request.args.get("limit"),
            query=query,
        )
        overrides.append(("limit", "" if limit == default_limit else str(limit)))
        allowed_keys.add("limit")

    canonical_url = build_canonical_url(
        request.path,
        parameters=request.args,
        overrides=overrides,
        allowed_keys=allowed_keys,
    )
    requested_url = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    return {
        "viewer_user_id": viewer.viewer_user_id,
        "query": query,
        "group_filter": group_filter,
        "limit": limit,
        "redirect": redirect(canonical_url) if requested_url != canonical_url else None,
    }


@main_bp.route("/api/global-search", methods=["GET"])
def global_search_route():
    """Return a compact, active-workspace-only result set for AppHeader."""
    if not current_public_user() and not is_guest_session():
        return jsonify({"ok": False, "error": "Sign in to search AI Pantry."}), 401

    canonical_request = canonical_global_search_request(api=True)
    if canonical_request["redirect"] is not None:
        return canonical_request["redirect"]

    query = canonical_request["query"]
    group_filter = canonical_request["group_filter"]
    limit = canonical_request["limit"]
    try:
        if not query.strip():
            return jsonify(recent_global_search(limit=limit))
        # Header page shortcuts are sourced from the rendered shared Sidebar so
        # their SPA handlers remain intact. The API supplies record results only.
        return jsonify(global_search(
            query,
            limit=limit,
            group_filter=[group_filter] if group_filter else None,
            include_pages=False,
        ))
    except Exception:
        current_app.logger.exception("Global application search failed")
        return jsonify({
            "ok": False,
            "query": query,
            "error": "AI Pantry search is temporarily unavailable.",
        }), 500


@main_bp.route("/api/global-search/recent", methods=["POST"])
def record_global_search_recent_route():
    """Record a clicked, server-resolved result in the active workspace."""
    if not current_public_user() and not is_guest_session():
        return jsonify({"ok": False, "error": "Sign in to update recent search records."}), 401
    # POST requests are not redirected for a missing assertion, but any
    # producer-supplied assertion must still match the resolved session.
    validate_authenticated_viewer(request.args)

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    group = str(payload.get("group") or "").strip().lower()
    stable_id = str(payload.get("id") or "").strip()
    if group not in ACTUAL_RECORD_GROUPS or not stable_id or len(stable_id) > 240:
        return jsonify({"ok": False, "error": "A record group and id are required."}), 400

    try:
        result = record_recent_global_search_result(group, stable_id)
    except Exception:
        current_app.logger.exception("Recording recent global search result failed")
        return jsonify({"ok": False, "error": "The recent item could not be recorded."}), 500
    if not result:
        return jsonify({"ok": False, "error": "That search record was not found."}), 404
    return jsonify({"ok": True, "result": result})


@main_bp.route("/search", methods=["GET"])
def global_search_results_route():
    """Render the grouped full-results view for the active workspace."""
    if not current_public_user() and not is_guest_session():
        return redirect(url_for("main_bp.index", _anchor="userAccountSection"))

    canonical_request = canonical_global_search_request(api=False)
    if canonical_request["redirect"] is not None:
        return canonical_request["redirect"]

    query = canonical_request["query"]
    group_filter = canonical_request["group_filter"]
    viewer_user_id = canonical_request["viewer_user_id"]
    try:
        search_payload = global_search(
            query,
            group_filter=[group_filter] if group_filter else None,
            full=True,
        )
        search_error = ""
    except Exception:
        current_app.logger.exception("Global full-results search failed")
        search_payload = {
            "ok": False,
            "query": query,
            "total_count": 0,
            "groups": [],
            "available_groups": [],
        }
        search_error = "AI Pantry search is temporarily unavailable. Please try again."

    return render_template(
        "search_results.html",
        search_payload=search_payload,
        search_error=search_error,
        search_type_filter=group_filter,
        search_viewer_user_id=viewer_user_id,
        current_user=current_public_user(),
        is_guest_demo=is_guest_session(),
        app_css_version=static_asset_version("css/app.css"),
        app_js_version=static_asset_version("js/app.js"),
    )


@main_bp.route("/api/meal-plan", methods=["POST"])
def add_meal_plan_entry_route():
    if not current_public_user() and not is_guest_session():
        return jsonify({"ok": False, "error": "Sign in or start a guest workspace to plan meals."}), 403

    payload = request.get_json(silent=True) or {}
    recipe_url = str(payload.get("recipe_url") or "").strip()
    available_recipes = {
        recipe["url"]: recipe
        for recipe in meal_plan_recipe_option_rows(recipe_url_rows())
    }
    if recipe_url not in available_recipes:
        return jsonify({"ok": False, "error": "Choose a recipe from your current recipe collection."}), 400

    try:
        planned_servings = (
            normalize_planned_servings(payload.get("planned_servings"))
            if "planned_servings" in payload
            else available_recipes[recipe_url]["default_servings"]
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        recipe_data = load_recipe_output(recipe_url) or {}
        ingredient_resolution = resolve_ingredient_requirements(
            recipe_data,
            payload.get("ingredient_option_selections"),
        )
        meal = add_meal({
            "date": payload.get("date"),
            "meal_type": payload.get("meal_type"),
            "recipe_url": recipe_url,
            "recipe_name": available_recipes[recipe_url]["name"],
            "planned_servings": planned_servings,
            "ingredient_option_selections": ingredient_resolution["selected_options"],
            "unresolved_ingredient_requirement_ids": [
                requirement["id"]
                for requirement in ingredient_resolution["unresolved_requirements"]
            ],
            "ingredient_selection_needed": ingredient_resolution["selection_needed"],
            "ingredients": ingredient_resolution["items"],
        })
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "meal": meal}), 201


@main_bp.route("/api/meal-plan/<meal_id>", methods=["DELETE"])
def delete_meal_plan_entry_route(meal_id):
    if not current_public_user() and not is_guest_session():
        return jsonify({"ok": False, "error": "Sign in or start a guest workspace to update meal plans."}), 403
    if not delete_meal(meal_id):
        return jsonify({"ok": False, "error": "That planned meal was not found."}), 404
    return jsonify({"ok": True})


@main_bp.route("/api/meal-plan/<meal_id>/ingredient-options", methods=["PATCH"])
def update_meal_plan_ingredient_options_route(meal_id):
    if not current_public_user() and not is_guest_session():
        return jsonify({"ok": False, "error": "Sign in or start a guest workspace to update meal plans."}), 403
    meal = next(
        (item for item in load_meal_plan()["meals"] if item["id"] == meal_id),
        None,
    )
    if not meal:
        return jsonify({"ok": False, "error": "That planned meal was not found."}), 404
    payload = request.get_json(silent=True) or {}
    resolution = resolve_ingredient_requirements(
        load_recipe_output(meal["recipe_url"]) or {},
        payload.get("ingredient_option_selections"),
    )
    updated = update_meal_ingredient_option_selections(
        meal_id,
        resolution["selected_options"],
        [
            requirement["id"]
            for requirement in resolution["unresolved_requirements"]
        ],
        ingredients=resolution["items"],
    )
    return jsonify({
        "ok": True,
        "meal": updated,
        "selection_needed": resolution["selection_needed"],
        "requirements": resolution["unresolved_requirements"],
    })


@main_bp.route("/sections/current-recipes")
def current_recipes_section():
    return render_template(
        "sections/current_recipe_url_log.html",
        **current_recipes_context(),
        normalize=normalize,
    )


@main_bp.route("/sections/admin-support")
def admin_support_section():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return "", 204

    return render_template(
        "sections/admin_support.html",
        **admin_support_context(active_public_user),
        admin_support_account_panel=True,
    )


@main_bp.route("/sections/shared-recipe-pdfs")
def shared_recipe_pdfs_section():
    active_public_user = current_public_user()
    if not is_admin_user(active_public_user):
        return "", 204

    return render_template(
        "sections/shared_recipe_pdfs.html",
        **shared_page_context(active_public_user),
        pdf_share_view=pdf_share_view_for_render(),
        shared_recipe_pdfs_account_panel=True,
    )


@main_bp.route("/sections/cookbooks")
def cookbooks_section():
    return render_template(
        "sections/cookbooks.html",
        **cookbooks_context(),
    )


@main_bp.route("/sections/recipe-view")
def recipe_view_section():
    return render_template(
        "sections/shopping_views.html",
        **shopping_views_context(),
    )


@main_bp.route("/sections/rules")
def rules_section():
    return render_template(
        "sections/rules.html",
        **rules_context(),
    )


@main_bp.route("/sections/pantry")
def pantry_section():
    if is_guest_session():
        return render_template(
            "sections/guest_ai_pantry.html",
            ai_pantry_account_panel=True,
        )

    return render_template(
        "sections/ai_pantry.html",
        **pantry_context(),
        ai_pantry_account_panel=True,
    )


@main_bp.route("/sections/store-options")
def store_options_section():
    return render_template(
        "sections/store_options.html",
        **store_options_context(),
    )


@main_bp.route("/clear", methods=["POST"])
def clear_list():
    save_items([])
    save_recipe_urls([])
    save_recipe_ingredients({})

    return redirect("/")


@main_bp.route("/save", methods=["POST"])
def save_list():
    raw_items = request.form.get("items", "")
    items = [
        line.strip()
        for line in raw_items.splitlines()
        if line.strip()
    ]

    save_items(items)
    sort_ingredients()

    return redirect("/")


@main_bp.route("/api/cookbooks", methods=["POST"])
def create_cookbook_route():
    try:
        if request.form.get("reuse_existing") == "1":
            cookbook = find_or_create_cookbook(request.form.get("name", ""))
        else:
            cookbook = create_cookbook(request.form.get("name", ""))
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({
        "ok": True,
        "cookbook": {
            "id": cookbook.get("id", ""),
            "name": cookbook.get("name", ""),
        },
    })


@main_bp.route("/api/cookbooks/<cookbook_id>", methods=["DELETE"])
def delete_cookbook_route(cookbook_id):
    try:
        delete_cookbook(cookbook_id)
    except ValueError as err:
        status = 400 if "cannot be deleted" in str(err).lower() else 404
        return jsonify({"ok": False, "error": str(err)}), status

    return jsonify({"ok": True})


def generated_pdf_cleanup_warnings(recipe_urls):
    warnings = []
    for recipe_url in recipe_urls or []:
        cleanup = delete_generated_recipe_pdf_for_recipe_deletion(recipe_url)
        if cleanup.get("ok"):
            continue
        warnings.append(
            cleanup.get("error")
            or f"The generated PDF for {recipe_url} could not be fully removed."
        )
    return warnings


@main_bp.route("/api/cookbooks/<cookbook_id>/purge", methods=["DELETE"])
def purge_cookbook_route(cookbook_id):
    cleanup_warnings = []
    try:
        recipe_urls = delete_cookbook_and_purge_recipe_urls(cookbook_id)
        for recipe_url in recipe_urls:
            remove_recipe_and_unused_ingredients(recipe_url)
            remove_recipe_url(recipe_url)
        cleanup_warnings = generated_pdf_cleanup_warnings(recipe_urls)
    except ValueError as err:
        status = 400 if "cannot be purged" in str(err).lower() else 404
        return jsonify({"ok": False, "error": str(err)}), status
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc) or "Unable to purge cookbook.",
        }), 500

    response = {
        "ok": True,
        "purged_recipe_count": len(recipe_urls),
    }
    if cleanup_warnings:
        response["warnings"] = cleanup_warnings
    return jsonify(response)


@main_bp.route("/api/cookbooks/<cookbook_id>/purge_recipes", methods=["POST"])
def purge_cookbook_recipes_route(cookbook_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        data = {}

    confirmation = data.get("confirm_purge_recipes") or request.form.get("confirm_purge_recipes", "")
    if str(confirmation or "").strip().upper() != "PURGE":
        return jsonify({
            "ok": False,
            "error": "Type PURGE to confirm purging cookbook recipes.",
        }), 400

    cleanup_warnings = []
    try:
        cookbook = find_cookbook(load_cookbooks(), cookbook_id)
        unclassified_purge = is_unclassified_cookbook(cookbook)
        if unclassified_purge:
            recipe_urls = purge_unclassified_cookbook_recipe_urls(cookbook_id)
        else:
            recipe_urls = purge_cookbook_recipe_urls(cookbook_id)
            for recipe_url in recipe_urls:
                remove_recipe_and_unused_ingredients(recipe_url)
                remove_recipe_url(recipe_url)
            cleanup_warnings = generated_pdf_cleanup_warnings(recipe_urls)
    except ValueError as err:
        status = 400 if "unclassified" in str(err).lower() else 404
        return jsonify({"ok": False, "error": str(err)}), status
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc) or "Unable to purge cookbook recipes.",
        }), 500

    response = {
        "ok": True,
        "purged_recipe_count": len(recipe_urls),
    }
    if cleanup_warnings:
        response["warnings"] = cleanup_warnings
    return jsonify(response)


def selected_cookbook_recipe_urls_from_request():
    data = request.get_json(silent=True) or {}
    requested_urls = []

    if isinstance(data, dict):
        for key in ("recipe_urls", "urls", "selected_recipe_urls"):
            value = data.get(key)

            if isinstance(value, list):
                requested_urls.extend(value)
            elif value:
                requested_urls.append(value)

    for key in ("recipe_urls", "urls", "selected_recipe_urls"):
        requested_urls.extend(request.form.getlist(key))

    return [
        str(url or "").strip()
        for url in requested_urls
        if str(url or "").strip()
    ]


@main_bp.route("/api/cookbooks/<cookbook_id>/remove_selected_recipes", methods=["POST"])
def remove_selected_cookbook_recipes_route(cookbook_id):
    try:
        removed_urls = remove_recipes_from_cookbook(
            cookbook_id,
            selected_cookbook_recipe_urls_from_request(),
        )
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({
        "ok": True,
        "removed_recipe_count": len(removed_urls),
    })


@main_bp.route("/api/cookbooks/<cookbook_id>/purge_selected_recipes", methods=["POST"])
def purge_selected_cookbook_recipes_route(cookbook_id):
    cleanup_warnings = []
    try:
        recipe_urls = purge_selected_cookbook_recipe_urls(
            cookbook_id,
            selected_cookbook_recipe_urls_from_request(),
        )
        for recipe_url in recipe_urls:
            remove_recipe_and_unused_ingredients(recipe_url)
            remove_recipe_url(recipe_url)
        cleanup_warnings = generated_pdf_cleanup_warnings(recipe_urls)
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc) or "Unable to purge selected cookbook recipes.",
        }), 500

    response = {
        "ok": True,
        "purged_recipe_count": len(recipe_urls),
    }
    if cleanup_warnings:
        response["warnings"] = cleanup_warnings
    return jsonify(response)


@main_bp.route("/api/cookbooks/<cookbook_id>/rename", methods=["POST"])
def rename_cookbook_route(cookbook_id):
    try:
        rename_cookbook(cookbook_id, request.form.get("name", ""))
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/reorder", methods=["POST"])
def reorder_cookbooks_route():
    data = request.get_json(silent=True) or {}
    cookbook_ids = data.get("cookbook_ids") if isinstance(data.get("cookbook_ids"), list) else []

    if not cookbook_ids:
        return jsonify({
            "ok": False,
            "error": "Cookbook order is required.",
        }), 400

    try:
        cookbooks = reorder_cookbooks(cookbook_ids)
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({
        "ok": True,
        "cookbook_ids": [
            cookbook.get("id", "")
            for cookbook in cookbooks
            if cookbook.get("id")
        ],
    })


@main_bp.route("/api/cookbooks/move_recipes", methods=["POST"])
def move_cookbook_recipes_route():
    try:
        move_recipes_to_cookbook(
            request.form.get("cookbook_id", ""),
            request.form.getlist("recipe_urls"),
            recipe_view_rows(recipe_url_rows()),
            overwrite_existing=request.form.get("overwrite_existing") == "1",
            insert_before_recipe_url=request.form.get("insert_before_recipe_url", ""),
            insert_after_recipe_url=request.form.get("insert_after_recipe_url", ""),
        )
    except CookbookRecipeConflict as err:
        return jsonify({
            "ok": False,
            "error": str(err),
            "conflict": "cookbook_recipe_exists",
            "conflicts": err.conflicts,
        })
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/remove_recipe", methods=["POST"])
def remove_cookbook_recipe_route():
    try:
        remove_recipe_from_cookbook(
            request.form.get("cookbook_id", ""),
            request.form.get("recipe_url", ""),
        )
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/<cookbook_id>/recipe_categories", methods=["POST"])
def update_cookbook_recipe_categories_route(cookbook_id):
    categories = {
        "meal_type": request.form.get("meal_type", ""),
        "cuisine": request.form.get("cuisine", ""),
        "main_ingredient": request.form.get("main_ingredient", ""),
        "cooking_method": request.form.get("cooking_method", ""),
        "occasion": request.form.get("occasion", ""),
        "dietary_preference": request.form.get("dietary_preference", ""),
        "prep_time_group": request.form.get("prep_time_group", ""),
        "custom_categories": request.form.get("custom_categories", ""),
    }
    if "menu_section" in request.form:
        categories["menu_section"] = request.form.get("menu_section", "")

    category_sources = {}
    category_sources_json = request.form.get("category_sources", "")
    if category_sources_json:
        try:
            parsed_sources = json.loads(category_sources_json)
            if isinstance(parsed_sources, dict):
                category_sources = parsed_sources
        except (TypeError, ValueError):
            category_sources = {}

    try:
        update_cookbook_recipe_categories(
            cookbook_id,
            request.form.get("recipe_url", ""),
            categories,
            confirm_overwrite=request.form.get("confirm_overwrite") == "1",
            category_sources=category_sources,
        )
    except CookbookCategoryOverwriteConflict as err:
        return jsonify({
            "ok": False,
            "error": str(err),
            "conflict": "cookbook_category_overwrite",
            "recipe_name": err.recipe_name,
        }), 409
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True})


@main_bp.route("/api/cookbooks/<cookbook_id>/menu_sections/reorder", methods=["POST"])
def reorder_cookbook_menu_section_route(cookbook_id):
    try:
        section_order = reorder_cookbook_menu_section(
            cookbook_id,
            request.form.get("menu_section", ""),
            request.form.get("direction", ""),
        )
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({
        "ok": True,
        "menu_section_order": section_order,
    })


@main_bp.route("/api/cookbooks/<cookbook_id>/infer_missing_details", methods=["POST"])
def infer_cookbook_missing_details_route(cookbook_id):
    data = request.get_json(silent=True) or {}
    overwrite_ai_fields = False
    preview_only = False
    if isinstance(data, dict):
        overwrite_ai_fields = bool(data.get("overwrite_ai_fields"))
        preview_only = bool(data.get("preview_only"))
    if request.form:
        overwrite_ai_fields = overwrite_ai_fields or request.form.get("overwrite_ai_fields") == "1"
        preview_only = preview_only or request.form.get("preview_only") == "1"

    try:
        result = infer_missing_details_for_cookbook(
            cookbook_id,
            overwrite_ai_fields=overwrite_ai_fields,
            preview_only=preview_only,
        )
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 404

    return jsonify({
        **result,
        "openai_usage_dashboard": openai_usage_dashboard_for_user(current_public_user()),
    }), 200 if result.get("ok") else 400


@main_bp.route("/api/recipes/reapply_food_rules", methods=["POST"])
def reapply_recipe_food_rules_route():
    data = request.get_json(silent=True) or {}
    recipe_url = ""
    if isinstance(data, dict):
        recipe_url = str(
            data.get("recipe_url")
            or data.get("url")
            or data.get("source_url")
            or ""
        ).strip()
    recipe_url = recipe_url or str(request.form.get("recipe_url") or request.form.get("url") or "").strip()

    result = apply_food_rules_to_saved_recipe(recipe_url)
    status = 200 if result.get("ok") else (404 if "not found" in str(result.get("error", "")).lower() else 400)
    return jsonify(result), status


def summarize_food_rule_reapply_results(results, scope_label):
    checked_results = [result for result in results if result.get("ok")]
    skipped_results = [result for result in results if not result.get("ok")]
    flagged_recipe_count = sum(1 for result in checked_results if result.get("needs_review"))
    flagged_ingredient_count = sum(int(result.get("flagged_ingredients") or 0) for result in checked_results)
    checked_ingredient_count = sum(int(result.get("checked_ingredients") or 0) for result in checked_results)
    summary_message = (
        f"Food rules reapplied to {len(checked_results)} recipe"
        f"{'' if len(checked_results) == 1 else 's'} in {scope_label}. "
        f"{flagged_ingredient_count} ingredient"
        f"{'' if flagged_ingredient_count == 1 else 's'} need review."
    )
    if skipped_results:
        summary_message += (
            f" {len(skipped_results)} recipe"
            f"{'' if len(skipped_results) == 1 else 's'} skipped."
        )

    return {
        "recipe_count": len(results),
        "checked_recipe_count": len(checked_results),
        "skipped_recipe_count": len(skipped_results),
        "flagged_recipe_count": flagged_recipe_count,
        "checked_ingredient_count": checked_ingredient_count,
        "flagged_ingredient_count": flagged_ingredient_count,
        "summary_message": summary_message,
        "results": results,
    }


@main_bp.route("/api/recipes/current/reapply_food_rules", methods=["POST"])
def reapply_current_recipes_food_rules_route():
    food_rules = load_food_rules()
    seen_recipe_keys = set()
    results = []

    for recipe in recipe_url_rows():
        recipe_url = str(recipe.get("url") if isinstance(recipe, dict) else "").strip()
        recipe_key = normalize_recipe_url_key(recipe_url)

        if not recipe_url or not recipe_key or recipe_key in seen_recipe_keys:
            continue

        seen_recipe_keys.add(recipe_key)
        results.append(apply_food_rules_to_saved_recipe(recipe_url, food_rules=food_rules))

    return jsonify({
        "ok": True,
        "scope": "current_recipes",
        **summarize_food_rule_reapply_results(results, "Current Recipes"),
    })


@main_bp.route("/api/cookbooks/<cookbook_id>/reapply_food_rules", methods=["POST"])
def reapply_cookbook_food_rules_route(cookbook_id):
    cookbook = cookbook_for_food_rule_apply(cookbook_id)
    if not cookbook:
        return jsonify({"ok": False, "error": "Cookbook was not found."}), 404

    food_rules = load_food_rules()
    seen_recipe_keys = set()
    results = []

    for recipe in cookbook.get("recipes", []) or []:
        recipe_url = str(recipe.get("url") if isinstance(recipe, dict) else "").strip()
        recipe_key = normalize_recipe_url_key(recipe_url)

        if not recipe_url or not recipe_key or recipe_key in seen_recipe_keys:
            continue

        seen_recipe_keys.add(recipe_key)
        results.append(apply_food_rules_to_saved_recipe(recipe_url, food_rules=food_rules))

    cookbook_name = cookbook.get("name") or "this cookbook"

    return jsonify({
        "ok": True,
        "cookbook_id": cookbook_id,
        "cookbook_name": cookbook_name,
        **summarize_food_rule_reapply_results(results, cookbook_name),
    })


@main_bp.route("/api/cookbooks/restore_recipes", methods=["POST"])
def restore_cookbook_recipes_route():
    raw_selections = request.form.get("option_selections") or ""
    try:
        option_selections = json.loads(raw_selections) if raw_selections else {}
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Ingredient option selections are invalid."}), 400
    try:
        result = restore_cookbook_recipes_to_log(
            request.form.getlist("recipe_urls"),
            option_selections=option_selections,
        )
    except IngredientOptionSelectionRequired as err:
        return jsonify({
            "ok": False,
            "selection_required": True,
            "error": str(err),
            "requirements": err.requirements,
        }), 409
    except ValueError as err:
        return jsonify({"ok": False, "error": str(err)}), 400

    return jsonify({"ok": True, **result})


def restore_cookbook_recipes_to_log(recipe_urls, option_selections=None):
    recipes = cookbook_recipes_for_urls(recipe_urls)
    urls = []
    ingredients_by_recipe = {}
    selected_options_by_recipe = {}
    all_ingredients = []
    unresolved_requirements = []
    option_selections = option_selections if isinstance(option_selections, dict) else {}

    for recipe in recipes:
        url = recipe.get("url")

        if not url:
            continue

        recipe_data = load_recipe_output(url)
        if isinstance(recipe_data, dict) and recipe_data.get("ingredients"):
            recipe_selections = option_selections.get(url)
            if not isinstance(recipe_selections, dict) and len(recipes) == 1:
                recipe_selections = option_selections
            resolution = resolve_ingredient_requirements(
                recipe_data,
                recipe_selections,
            )
            if resolution["unresolved_requirements"]:
                for requirement in resolution["unresolved_requirements"]:
                    requirement["recipe_url"] = url
                    requirement["recipe_name"] = recipe.get("name") or "Recipe"
                    unresolved_requirements.append(requirement)
                continue
            ingredients = [
                shopping_item_name(item)
                for item in resolution["items"]
                if shopping_item_name(item)
            ]
            selected_options_by_recipe[url] = resolution["selected_options"]
        else:
            ingredients = recipe_ingredients_for_record(recipe)

        urls.append(url)
        ingredients_by_recipe[url] = ingredients
        all_ingredients.extend(ingredients)

    if unresolved_requirements:
        raise IngredientOptionSelectionRequired(unresolved_requirements)

    if not urls:
        raise ValueError("Selected cookbook recipes were not found.")

    if not all_ingredients:
        raise ValueError("No ingredients were found for the selected cookbook recipes.")

    add_items(all_ingredients)
    for url, selections in selected_options_by_recipe.items():
        save_recipe_option_selections(url, selections)

    for recipe in recipes:
        url = recipe.get("url")

        if not url:
            continue

        save_ingredients_for_recipe(url, ingredients_by_recipe.get(url, []), recipe)
        save_recipe_url_name(url, recipe.get("name", ""))
        save_recipe_url_quantity(url, recipe.get("quantity", 1))

    add_recipe_urls(urls)
    sort_ingredients()

    return {
        "restored_count": len(urls),
        "ingredient_count": len(all_ingredients),
    }


@main_bp.route("/sort", methods=["POST"])
def sort_list():
    sort_ingredients()

    return redirect("/")


@main_bp.route("/save_home_address", methods=["POST"])
def save_home_address_route():
    saved_address = save_home_address(request.form)
    nearest_store_results = None

    if request.form.get("action") == "run_find_nearest":
        nearest_store_results = resolve_nearest_stores_for_home_address(
            saved_address,
            search_radius_miles=request.form.get("store_search_radius_miles"),
        )

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        response = {
            "ok": True,
            "home_address": saved_address,
            "home_address_history": load_home_address_history(),
        }
        if nearest_store_results is not None:
            response["nearest_store_results"] = nearest_store_results
            if nearest_store_results.get("error"):
                response["warning"] = nearest_store_results.get("error")
        return jsonify(response)

    return redirect("/#storeOptionsSection" if nearest_store_results is not None else "/#home-address-section")


@main_bp.route("/api/home_address_history/<entry_id>/label", methods=["POST"])
def update_home_address_history_label_route(entry_id):
    data = request.get_json(silent=True) or {}
    label = data.get("label") if "label" in data else request.form.get("label", "")
    result = update_home_address_history_label(entry_id, label)
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


@main_bp.route("/api/home_address_history/<entry_id>/delete", methods=["POST"])
def delete_home_address_history_entry_route(entry_id):
    result = delete_home_address_history_entry(entry_id)
    status = 200 if result.get("ok") else 404

    return jsonify(result), status


@main_bp.route("/api/reverse_geocode", methods=["POST"])
def reverse_geocode_route():
    data = request.get_json(silent=True) or {}

    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Latitude and longitude are required.",
        }), 400

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return jsonify({
            "ok": False,
            "error": "Latitude or longitude is out of range.",
        }), 400

    try:
        result = reverse_geocode_coordinates(latitude, longitude)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"Unable to look up address for this location: {exc}",
        }), 502

    return jsonify({
        "ok": True,
        "address": result["address"],
        "display_name": result["display_name"],
    })


@main_bp.route("/api/address_options", methods=["POST"])
def address_options_route():
    data = request.get_json(silent=True) or {}
    query = build_address_options_query(data)

    if not query:
        return jsonify({
            "ok": False,
            "error": "Enter at least part of an address before searching.",
        }), 400

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "jsonv2",
                "q": query,
                "addressdetails": 1,
                "countrycodes": "us",
                "limit": 8,
            },
            headers={
                "User-Agent": "PushShoppingList/1.0 local address lookup",
            },
            timeout=(5, 12),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"Unable to search address options: {exc}",
        }), 502

    return jsonify({
        "ok": True,
        "query": query,
        "options": normalize_address_options(payload if isinstance(payload, list) else []),
    })


@main_bp.route("/api/complete_address", methods=["POST"])
def complete_address_route():
    data = request.get_json(silent=True) or {}
    candidate_address = normalize_address_form_fields(data.get("address") or {})
    current_address = normalize_address_form_fields(data.get("current_address") or {})
    display_name = str(data.get("display_name") or "").strip()
    completed_address = complete_address_fields_locally(
        candidate_address,
        current_address,
        display_name,
    )
    completion_source = "local"

    if os.getenv("OPENAI_API_KEY") and address_needs_completion(completed_address):
        openai_address = complete_address_fields_with_openai(
            candidate_address,
            current_address,
            display_name,
        )

        if openai_address:
            completed_address = merge_completed_address_fields(
                openai_address,
                completed_address,
            )
            completion_source = "openai"

    return jsonify({
        "ok": True,
        "address": completed_address,
        "source": completion_source,
        "openai_usage_dashboard": openai_usage_dashboard_for_user(current_public_user()),
    })


def reverse_geocode_coordinates(latitude, longitude):
    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "addressdetails": 1,
        },
        headers={
            "User-Agent": "PushShoppingList/1.0 local address lookup",
        },
        timeout=(5, 12),
    )
    response.raise_for_status()
    payload = response.json()
    address = payload.get("address") if isinstance(payload, dict) else {}

    return {
        "address": reverse_geocode_address_fields(address or {}),
        "display_name": payload.get("display_name", "") if isinstance(payload, dict) else "",
    }


def build_address_options_query(data):
    query = str(data.get("query", "") or "").strip()

    if query:
        return query

    street = str(data.get("street") or data.get("address_street") or "").strip()
    city = str(data.get("city") or data.get("address_city") or "").strip()
    state = str(data.get("state") or data.get("address_state") or "").strip()
    zip_code = str(data.get("zip") or data.get("address_zip") or "").strip()

    return ", ".join(part for part in [street, city, state, zip_code] if part)


def normalize_address_options(results):
    options = []
    seen = set()

    for result in results:
        if not isinstance(result, dict):
            continue

        display_name = str(result.get("display_name") or "").strip()
        key = normalize(display_name)

        if not display_name or key in seen:
            continue

        seen.add(key)
        address = result.get("address") if isinstance(result.get("address"), dict) else {}
        options.append({
            "display_name": display_name,
            "address": reverse_geocode_address_fields(address),
            "latitude": result.get("lat"),
            "longitude": result.get("lon"),
        })

    return options


def normalize_address_form_fields(data):
    if not isinstance(data, dict):
        data = {}

    return {
        "street": address_field_value(
            data,
            "street",
            "address_street",
            "street_address",
            "streetaddress",
            "line1",
            "address1",
        ),
        "apartment": address_field_value(
            data,
            "apartment",
            "address_apartment",
            "unit",
            "line2",
            "address2",
        ),
        "city": address_field_value(data, "city", "address_city"),
        "county": address_field_value(data, "county", "address_county"),
        "state": abbreviate_us_state(address_field_value(data, "state", "address_state")),
        "zip": address_field_value(
            data,
            "zip",
            "address_zip",
            "zip_code",
            "zipcode",
            "postal_code",
            "postcode",
        ),
        "country": address_field_value(data, "country", "address_country"),
    }


def address_field_value(data, *keys):
    lower_data = {
        str(key).lower(): value
        for key, value in data.items()
    }

    for key in keys:
        value = data.get(key)

        if value in (None, ""):
            value = lower_data.get(key.lower())

        value = str(value or "").strip()

        if value:
            return value

    return ""


def complete_address_fields_locally(candidate_address, current_address, display_name):
    parsed_address = parse_display_name_address(display_name)

    return {
        "street": best_street_value(
            candidate_address.get("street"),
            parsed_address.get("street"),
            current_address.get("street"),
        ),
        "apartment": first_address_value_from_dicts(
            [candidate_address, current_address, parsed_address],
            "apartment",
        ),
        "city": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "city",
        ),
        "county": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "county",
        ),
        "state": abbreviate_us_state(first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "state",
        )),
        "zip": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "zip",
        ).split("-")[0],
        "country": first_address_value_from_dicts(
            [candidate_address, parsed_address, current_address],
            "country",
        ),
    }


def parse_display_name_address(display_name):
    parts = [
        part.strip()
        for part in str(display_name or "").split(",")
        if part.strip()
    ]
    parsed = {
        "street": "",
        "apartment": "",
        "city": "",
        "county": "",
        "state": "",
        "zip": "",
        "country": "",
    }

    for part in parts:
        zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", part)
        if zip_match and not parsed["zip"]:
            parsed["zip"] = zip_match.group(0).split("-")[0]

        state_text = re.sub(r"\b\d{5}(?:-\d{4})?\b", "", part).strip(" ,")
        state = abbreviate_us_state(state_text)
        if state != part or re.fullmatch(r"[A-Z]{2}", state):
            parsed["state"] = parsed["state"] or state

    if parts:
        parsed["street"] = parts[0]

    for part in parts[1:]:
        lowered = part.lower()

        if lowered in {"united states", "usa", "us"}:
            parsed["country"] = parsed["country"] or part
            continue

        if lowered.endswith(" county"):
            parsed["county"] = parsed["county"] or part
            continue

        if parsed["zip"] and parsed["zip"] in part:
            continue

        if parsed["state"] and part.upper() == parsed["state"]:
            continue

        if abbreviate_us_state(part) == parsed["state"]:
            continue

        parsed["city"] = parsed["city"] or part

    return parsed


def first_address_value_from_dicts(dicts, key):
    for data in dicts:
        value = str((data or {}).get(key, "") or "").strip()

        if value:
            return value

    return ""


def best_street_value(*values):
    cleaned_values = [
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    ]

    if not cleaned_values:
        return ""

    return max(cleaned_values, key=street_value_score)


def street_value_score(value):
    value = str(value or "")
    return (
        100 if re.search(r"\d", value) else 0,
        len(value.split()),
        len(value),
    )


def address_needs_completion(address):
    street = str(address.get("street") or "")

    return (
        not street
        or not re.search(r"\d", street)
        or not address.get("city")
        or not address.get("state")
        or not address.get("zip")
    )


def complete_address_fields_with_openai(candidate_address, current_address, display_name):
    global address_openai_client

    if address_openai_client is None:
        address_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=20)

    prompt = f"""
Extract the most complete US mailing address fields from the data below.

Rules:
- Return only JSON.
- Use only information present in the candidate, display text, or current form fields.
- Do not invent a house number.
- Preserve the current apartment/unit when the candidate does not include one.
- Prefer a full street address with house number over a road-only value.
- Use a two-letter US state abbreviation when possible.
- Unknown fields should be empty strings.

Candidate address fields:
{json.dumps(candidate_address, ensure_ascii=False)}

Candidate display text:
{display_name}

Current form fields:
{json.dumps(current_address, ensure_ascii=False)}

Output shape:
{{
  "street": "",
  "apartment": "",
  "city": "",
  "county": "",
  "state": "",
  "zip": "",
  "country": ""
}}
"""

    address_model = os.getenv("OPENAI_ADDRESS_MODEL", "gpt-4o-mini")

    try:
        messages = [
            {
                "role": "system",
                "content": "You extract structured US mailing address fields and return only JSON.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        request_payload = {
            "model": address_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if supports_custom_temperature(address_model):
            request_payload["temperature"] = 0

        response = throttled_chat_completion(
            address_openai_client,
            request_payload,
            action_name="address-completion",
            model=address_model,
        )
        record_openai_usage(
            response,
            "address-completion",
            model=address_model,
        )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        print(f"OpenAI address completion failed; using local address fields: {exc}")
        return {}

    return normalize_address_form_fields(data)


def merge_completed_address_fields(primary, fallback):
    return {
        key: str(primary.get(key) or fallback.get(key) or "").strip()
        for key in ["street", "apartment", "city", "county", "state", "zip", "country"]
    }


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text


def reverse_geocode_address_fields(address):
    road = first_address_value(address, [
        "road",
        "pedestrian",
        "footway",
        "path",
        "residential",
        "neighbourhood",
    ])
    house_number = first_address_value(address, ["house_number"])
    street = " ".join(part for part in [house_number, road] if part)
    state = first_address_value(address, ["state_code"]) or abbreviate_us_state(
        first_address_value(address, ["state"])
    )

    return {
        "street": street,
        "apartment": "",
        "city": first_address_value(address, [
            "city",
            "town",
            "village",
            "municipality",
            "hamlet",
            "county",
        ]),
        "county": first_address_value(address, ["county"]),
        "state": state,
        "zip": first_address_value(address, ["postcode"]).split("-")[0],
        "country": first_address_value(address, ["country"]),
    }


def first_address_value(address, keys):
    for key in keys:
        value = str(address.get(key, "") or "").strip()

        if value:
            return value

    return ""


def abbreviate_us_state(state):
    state = str(state or "").strip()

    if len(state) == 2:
        return state.upper()

    return US_STATE_ABBREVIATIONS.get(state.lower(), state)


@main_bp.route("/save_item_qty", methods=["POST"])
def save_item_qty_route():
    item_key = normalize(request.form.get("item_key", ""))
    manual_qty = str(request.form.get("manual_qty", "") or "").strip()
    purchasable_item = str(request.form.get("purchasable_item", "") or "").strip()

    if item_key:
        save_item_manual_qty(item_key, manual_qty)
        save_item_purchase_mapping(item_key, purchasable_item)
        update_saved_recipe_purchase_mapping(item_key, purchasable_item)

    if (
        request.headers.get("X-Requested-With") == "fetch"
        or request.form.get("ajax") == "1"
    ):
        purchase_mapping = purchase_mapping_for_item(item_key, item_state=load_item_state())
        return jsonify({
            "ok": True,
            "item_key": item_key,
            "manual_qty": manual_qty,
            "purchasable_item": purchase_mapping["purchasable_item"],
            "purchase_group": purchase_mapping["purchase_group"],
            "purchase_group_key": purchase_mapping["purchase_group_key"],
        })

    return redirect("/")
