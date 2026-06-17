import base64
from copy import deepcopy
import json
import mimetypes
import os
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import parse_qsl
from time import perf_counter
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

import requests

from flask import g
from flask import has_request_context

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import menu_store_service
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.menu_mega_json_service import load_menu_mega_json_snapshot
from PushShoppingList.services.menu_mega_json_service import load_snapshot_index
from PushShoppingList.services.cookbook_service import COOKBOOK_CATEGORY_ALL_FIELDS
from PushShoppingList.services.cookbook_service import COOKBOOK_CATEGORY_FIELDS
from PushShoppingList.services.cookbook_service import clean_category_payload
from PushShoppingList.services.cookbook_service import clean_custom_categories
from PushShoppingList.services.cookbook_service import cookbook_category_choices
from PushShoppingList.services.cookbook_service import ensure_unclassified_cookbook_for_recipes
from PushShoppingList.services.cookbook_service import infer_recipe_categories
from PushShoppingList.services.cookbook_service import recipe_category_metadata_for_editor
from PushShoppingList.services.cookbook_service import cookbook_recipe_assignment_for_url
from PushShoppingList.services.cookbook_service import recipe_cookbook_assignments
from PushShoppingList.services.ingredient_text_review_service import annotate_ingredients_for_food_review
from PushShoppingList.services.image_variant_service import cover_image_variant_payload
from PushShoppingList.services.image_variant_service import ensure_webp_variants
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import RAW_FOLDER
from PushShoppingList.services.recipe_extract_service import supports_custom_temperature
from PushShoppingList.services.recipe_extract_service import STORE_SECTION_ORDER
from PushShoppingList.services.recipe_extract_service import UPLOAD_FOLDER
from PushShoppingList.services.recipe_extract_service import build_video_text_pdf_html
from PushShoppingList.services.recipe_extract_service import classify_store_section
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_info_from_text
from PushShoppingList.services.recipe_extract_service import extract_ingredients_from_result
from PushShoppingList.services.recipe_extract_service import fetch_recipe_page
from PushShoppingList.services.recipe_extract_service import generated_recipe_pdf_path
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
from PushShoppingList.services.recipe_extract_service import normalize_recipe_cover_image
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_recipe_scaling_metadata
from PushShoppingList.services.recipe_extract_service import PDF_KIND_GENERATED_RECIPE
from PushShoppingList.services.recipe_extract_service import PDF_KIND_WEBPAGE_BACKUP
from PushShoppingList.services.recipe_extract_service import RECIPE_INFO_EMPTY_VALUES
from PushShoppingList.services.recipe_extract_service import RECIPE_INFO_ESTIMATE_ALIASES
from PushShoppingList.services.recipe_extract_service import RECIPE_INFO_ESTIMATE_DEFAULTS
from PushShoppingList.services.recipe_extract_service import recipe_archive_pdf_path
from PushShoppingList.services.recipe_extract_service import recipe_cover_image_file_path
from PushShoppingList.services.recipe_extract_service import recipe_pdf_path
from PushShoppingList.services.recipe_extract_service import safe_filename
from PushShoppingList.services.recipe_extract_service import write_recipe_page_pdf
from PushShoppingList.services.job_runtime_context import model_value_for_env as job_model_value_for_env
from PushShoppingList.services.openai_throttle_service import throttled_chat_completion
from PushShoppingList.services.openai_throttle_service import throttled_image_generation
from PushShoppingList.services.purchase_mapping_service import apply_purchase_mapping_to_ingredient
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_ingredient_service import recipe_ingredients_for_key
from PushShoppingList.services.recipe_ingredient_service import remove_unused_ingredients_from_shopping_list
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.recipe_url_service import load_recipe_urls
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_type
from PushShoppingList.services.recipe_url_service import save_recipe_urls
from PushShoppingList.services.recipe_url_service import save_recipe_url_name
from PushShoppingList.services.recipe_url_service import save_recipe_url_quantity
from PushShoppingList.services.recipe_quantity_service import update_recipe_quantity
from PushShoppingList.services.recipe_image_progress_service import finish_recipe_image_progress
from PushShoppingList.services.recipe_image_progress_service import start_recipe_image_progress
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.scripts.sort_ingredients import main as sort_ingredients


NUTRITION_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "polyunsaturated_fat",
    "monounsaturated_fat",
    "trans_fat",
    "cholesterol",
    "sodium",
    "potassium",
    "fiber",
    "sugar",
    "vitamin_a",
    "vitamin_c",
    "calcium",
    "iron",
]


def log_recipe_edit_openai_exception(action, model, exc, final_error_code):
    openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
    print(
        f"[OpenAI] action={action} model={model} "
        f"exception_type={type(exc).__name__} "
        f"openai_error_code={openai_error_code or 'n/a'} "
        f"openai_error_param={openai_error_param or 'n/a'} "
        f"final_error_code={final_error_code}"
    )


DEFAULT_MANUAL_NUTRITION_FIELDS = [
    "serving_basis",
    "calories",
    "carbohydrates",
    "protein",
    "fat",
    "saturated_fat",
    "cholesterol",
    "sodium",
    "fiber",
    "sugar",
]
NUTRITION_ESTIMATE_FIELDS = [
    field
    for field in DEFAULT_MANUAL_NUTRITION_FIELDS
    if field != "serving_basis"
]
STEP_IMAGE_FOLDER = Path(__file__).resolve().parents[1] / "static" / "generated" / "recipe_steps"
STEP_IMAGE_URL_PREFIX = "/static/generated/recipe_steps"
COVER_IMAGE_UPLOAD_FOLDER = UPLOAD_FOLDER / "recipe_covers"
COVER_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
COVER_IMAGE_MIME_EXTENSIONS = {
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

RECIPE_PDF_ASSET_FIELDS = (
    "source_pdf_path",
    "source_cloudflare_pdf_url",
    "generated_pdf_path",
    "generated_cloudflare_pdf_url",
)

RESTAURANT_MENU_METADATA_FIELDS = (
    "restaurant_name",
    "restaurant_website_url",
    "source_menu_url",
    "restaurant_cuisine_tags",
    "restaurant_phone",
    "restaurant_address",
    "restaurant_hours_text",
    "restaurant_current_status",
    "restaurant_promotions",
    "restaurant_online_payment_available",
    "restaurant_delivery_available",
    "menu_section",
    "menu_item_name",
    "menu_order_url",
    "menu_price",
    "menu_description",
)

RESTAURANT_MENU_RELATION_FIELDS = (
    "restaurant_id",
    "menu_id",
    "menu_section_id",
    "menu_item_id",
)


def clean_pdf_asset_value(value):
    return str(value or "").strip()


def first_pdf_asset_value(*values):
    for value in values:
        text = clean_pdf_asset_value(value)
        if text:
            return text
    return ""


def apply_recipe_pdf_asset_aliases(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    source_path = first_pdf_asset_value(
        recipe_data.get("source_pdf_path"),
        recipe_data.get("webpage_backup_pdf_path"),
        recipe_data.get("pdf_path"),
    )
    source_url = first_pdf_asset_value(
        recipe_data.get("source_cloudflare_pdf_url"),
        recipe_data.get("source_cloudflare_pdf_path"),
        recipe_data.get("webpage_backup_pdf_url"),
        recipe_data.get("cloudflare_pdf_url"),
    )
    generated_path = first_pdf_asset_value(
        recipe_data.get("generated_pdf_path"),
        recipe_data.get("generated_recipe_pdf_path"),
    )
    generated_url = first_pdf_asset_value(
        recipe_data.get("generated_cloudflare_pdf_url"),
        recipe_data.get("generated_cloudflare_pdf_path"),
        recipe_data.get("generated_recipe_pdf_url"),
    )

    recipe_data["source_pdf_path"] = source_path
    recipe_data["source_cloudflare_pdf_url"] = source_url
    recipe_data["source_cloudflare_pdf_path"] = source_url
    recipe_data["generated_pdf_path"] = generated_path
    recipe_data["generated_cloudflare_pdf_url"] = generated_url
    recipe_data["generated_cloudflare_pdf_path"] = generated_url

    if source_path:
        recipe_data["webpage_backup_pdf_path"] = source_path
    if source_url:
        recipe_data["webpage_backup_pdf_url"] = source_url
    if generated_path:
        recipe_data["generated_recipe_pdf_path"] = generated_path
    if generated_url:
        recipe_data["generated_recipe_pdf_url"] = generated_url

    return recipe_data


def apply_recipe_pdf_asset_payload(recipe_data, payload):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    if "source_cloudflare_pdf_path" in payload and "source_cloudflare_pdf_url" not in payload:
        payload = {
            **payload,
            "source_cloudflare_pdf_url": payload.get("source_cloudflare_pdf_path"),
        }
    if "generated_cloudflare_pdf_path" in payload and "generated_cloudflare_pdf_url" not in payload:
        payload = {
            **payload,
            "generated_cloudflare_pdf_url": payload.get("generated_cloudflare_pdf_path"),
        }

    for field in RECIPE_PDF_ASSET_FIELDS:
        if field in payload:
            value = clean_pdf_asset_value(payload.get(field))
            recipe_data[field] = value
            if field == "source_pdf_path" and not value:
                recipe_data["webpage_backup_pdf_path"] = ""
                recipe_data["pdf_path"] = ""
            elif field == "source_cloudflare_pdf_url" and not value:
                recipe_data["source_cloudflare_pdf_path"] = ""
                recipe_data["webpage_backup_pdf_url"] = ""
                recipe_data["cloudflare_pdf_url"] = ""
            elif field == "generated_pdf_path" and not value:
                recipe_data["generated_recipe_pdf_path"] = ""
            elif field == "generated_cloudflare_pdf_url" and not value:
                recipe_data["generated_cloudflare_pdf_path"] = ""
                recipe_data["generated_recipe_pdf_url"] = ""

    return apply_recipe_pdf_asset_aliases(recipe_data)


def recipe_pdf_field_snapshot(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    normalized = apply_recipe_pdf_asset_aliases(dict(recipe_data))
    return {
        "source_url": clean_pdf_asset_value(normalized.get("source_url")),
        "source_pdf_path": clean_pdf_asset_value(normalized.get("source_pdf_path")),
        "source_cloudflare_pdf_url": clean_pdf_asset_value(normalized.get("source_cloudflare_pdf_url")),
        "generated_pdf_path": clean_pdf_asset_value(normalized.get("generated_pdf_path")),
        "generated_cloudflare_pdf_url": clean_pdf_asset_value(normalized.get("generated_cloudflare_pdf_url")),
    }


def log_recipe_pdf_fields(action, recipe_data):
    print(f"[recipe_pdf_fields] action={action} fields={recipe_pdf_field_snapshot(recipe_data)}")


def create_new_recipe():
    source_url = f"manual://recipe/{uuid.uuid4().hex}"
    recipe_data = {
        "source_url": source_url,
        "recipe_title": "New Recipe",
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "nutrition": empty_recipe_nutrition(),
        "rating": 0,
        "reflection_notes": [],
        "chatgpt_feedback": "",
        "chatgpt_feedback_created_at": "",
        "scaling": normalize_recipe_scaling_metadata(),
        "source_pdf_path": "",
        "source_cloudflare_pdf_url": "",
        "generated_pdf_path": "",
        "generated_cloudflare_pdf_url": "",
    }

    save_recipe_output(source_url, recipe_data)
    save_recipe_urls(load_recipe_urls() + [source_url])
    save_recipe_url_quantity(source_url, 1)
    save_recipe_url_name(source_url, "New Recipe")
    update_recipe_ingredient_record(source_url, 1, recipe_data)
    ensure_unclassified_cookbook_for_recipes([{
        "url": source_url,
        "name": "New Recipe",
        "source_href": source_url,
        "source_display_url": source_url,
        "quantity": 1,
        "base_servings": "",
    }])
    result = load_editable_recipe(source_url)
    result["url"] = source_url
    return result


def empty_recipe_nutrition():
    return {
        **{field: "" for field in DEFAULT_MANUAL_NUTRITION_FIELDS},
        "serving_basis": "per serving",
        "other": [],
    }


def clean_recipe_menu_text(value):
    if isinstance(value, list):
        return ", ".join(clean_recipe_menu_text(item) for item in value if clean_recipe_menu_text(item))
    return str(value or "").strip()


def first_recipe_menu_text(*values):
    for value in values:
        text = clean_recipe_menu_text(value)
        if text:
            return text
    return ""


def recipe_menu_source_metadata(recipe_data):
    metadata = recipe_data.get("source_metadata") if isinstance(recipe_data, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def recipe_menu_relation_value(recipe_data, key):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return first_recipe_menu_text(recipe_data.get(key), metadata.get(key))


def recipe_menu_source_url_candidates(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    candidates = [
        recipe_data.get("source_url"),
        recipe_data.get("recipe_record_url"),
        recipe_data.get("url"),
        recipe_data.get("source_display_url"),
        recipe_data.get("menu_order_url"),
        recipe_data.get("deep_link_url"),
        metadata.get("recipe_record_url"),
        metadata.get("source_url"),
        metadata.get("source_display_url"),
        metadata.get("menu_order_url"),
        metadata.get("deep_link_url"),
    ]
    return [clean_recipe_menu_text(value) for value in candidates if clean_recipe_menu_text(value)]


def recipe_menu_item_token_from_url(url):
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""

    query = parse_qs(parsed.query or "")
    values = query.get("menu_item") or query.get("menuItemIdInput") or []
    return clean_recipe_menu_text(values[0]) if values else ""


def recipe_menu_source_url_from_item_url(url):
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""

    query_pairs = parse_qsl(parsed.query or "", keep_blank_values=True)
    if parsed.path.endswith("menuItem_home.action"):
        query = dict(query_pairs)
        res_input = clean_recipe_menu_text(query.get("resInput"))
        if not res_input:
            return ""
        base_path = parsed.path.rsplit("/", 1)[0] + "/menu_home.action"
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            base_path,
            "",
            urlencode({"resInput": res_input}),
            "",
        ))

    if not any(key == "menu_item" for key, _value in query_pairs):
        return ""

    filtered_query = urlencode(
        [(key, value) for key, value in query_pairs if key != "menu_item"],
        doseq=True,
    )
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        filtered_query,
        "",
    ))


def recipe_menu_source_url_from_candidates(recipe_data):
    for candidate in recipe_menu_source_url_candidates(recipe_data):
        source_menu_url = recipe_menu_source_url_from_item_url(candidate)
        if source_menu_url:
            return source_menu_url
    return ""


def recipe_menu_source_url_keys(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    candidates = [
        recipe_data.get("source_menu_url"),
        recipe_data.get("menu_source_url"),
        metadata.get("source_menu_url"),
        recipe_menu_source_url_from_candidates(recipe_data),
    ]
    keys = {
        normalize_recipe_url_key(candidate)
        for candidate in candidates
        if normalize_recipe_url_key(candidate)
    }
    for candidate in recipe_menu_source_url_candidates(recipe_data):
        source_menu_url = recipe_menu_source_url_from_item_url(candidate)
        key = normalize_recipe_url_key(source_menu_url)
        if key:
            keys.add(key)
    return keys


def recipe_menu_match_text(value):
    return clean_recipe_menu_text(value).lower()


def recipe_menu_item_name_candidates(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return {
        recipe_menu_match_text(value)
        for value in (
            recipe_data.get("menu_item_name"),
            recipe_data.get("item_name"),
            recipe_data.get("recipe_title"),
            recipe_data.get("display_name"),
            metadata.get("menu_item_name"),
            metadata.get("item_name"),
        )
        if recipe_menu_match_text(value)
    }


def recipe_menu_section_candidates(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return {
        recipe_menu_match_text(value)
        for value in (
            recipe_data.get("menu_section"),
            recipe_data.get("section_name"),
            metadata.get("menu_section"),
            metadata.get("section_name"),
        )
        if recipe_menu_match_text(value)
    }


def menu_store_item_source_url_keys(item):
    item = item if isinstance(item, dict) else {}
    keys = set()
    for value in (item.get("recipe_url"), item.get("recipe_id"), item.get("url")):
        source_menu_url = recipe_menu_source_url_from_item_url(value)
        key = normalize_recipe_url_key(source_menu_url)
        if key:
            keys.add(key)
    for value in (item.get("menu_order_url"), item.get("deep_link_url")):
        source_menu_url = recipe_menu_source_url_from_item_url(value)
        key = normalize_recipe_url_key(source_menu_url)
        if key:
            keys.add(key)
    return keys


def recipe_menu_snapshot_id(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return first_recipe_menu_text(
        recipe_data.get("parent_menu_snapshot_id"),
        recipe_data.get("menu_mega_snapshot_id"),
        recipe_data.get("menu_snapshot_id"),
        metadata.get("parent_menu_snapshot_id"),
        metadata.get("menu_mega_snapshot_id"),
        metadata.get("menu_snapshot_id"),
    )


def recipe_menu_snapshot_source_url(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return first_recipe_menu_text(
        recipe_data.get("source_menu_url"),
        recipe_data.get("menu_source_url"),
        metadata.get("source_menu_url"),
        recipe_menu_source_url_from_candidates(recipe_data),
        recipe_data.get("source_display_url") if recipe_has_menu_metadata(recipe_data) else "",
    )


def load_recipe_menu_snapshot(recipe_data):
    snapshot_id = recipe_menu_snapshot_id(recipe_data)
    if snapshot_id:
        snapshot = load_menu_mega_json_snapshot(snapshot_id)
        if snapshot:
            return snapshot

    source_url = recipe_menu_snapshot_source_url(recipe_data)
    source_key = normalize_recipe_url_key(source_url)
    if not source_key:
        return {}

    index = load_snapshot_index()
    for summary in index.get("snapshots") if isinstance(index.get("snapshots"), list) else []:
        if not isinstance(summary, dict):
            continue
        summary_urls = (
            summary.get("source_url"),
            summary.get("final_url"),
        )
        if any(normalize_recipe_url_key(url) == source_key for url in summary_urls if url):
            snapshot = load_menu_mega_json_snapshot(summary.get("id", ""))
            if snapshot:
                return snapshot

    return {}


def recipe_menu_snapshot_text_list(value):
    if isinstance(value, list):
        return ", ".join(clean_recipe_menu_text(item) for item in value if clean_recipe_menu_text(item))
    return clean_recipe_menu_text(value)


def recipe_menu_snapshot_restaurant_fields(recipe_data):
    snapshot = load_recipe_menu_snapshot(recipe_data)
    mega_json = snapshot.get("menu_mega_json") if isinstance(snapshot.get("menu_mega_json"), dict) else {}
    restaurant = mega_json.get("restaurant") if isinstance(mega_json.get("restaurant"), dict) else {}
    source = mega_json.get("source") if isinstance(mega_json.get("source"), dict) else {}
    metadata = restaurant.get("metadata") if isinstance(restaurant.get("metadata"), dict) else {}

    if not restaurant and not source:
        return {}

    restaurant_name = first_recipe_menu_text(
        metadata.get("restaurant_name"),
        metadata.get("name"),
        restaurant.get("name") if clean_recipe_menu_text(restaurant.get("name")).lower() != "restaurant menu" else "",
    )

    return {
        "restaurant_name": restaurant_name,
        "restaurant_website_url": first_recipe_menu_text(
            restaurant.get("website"),
            metadata.get("restaurant_website_url"),
            metadata.get("website_url"),
            metadata.get("website"),
        ),
        "source_menu_url": first_recipe_menu_text(
            metadata.get("source_menu_url"),
            source.get("source_url"),
            source.get("final_url"),
        ),
        "restaurant_cuisine_tags": first_recipe_menu_text(
            recipe_menu_snapshot_text_list(metadata.get("cuisine_tags")),
            recipe_menu_snapshot_text_list(metadata.get("cuisines")),
        ),
        "restaurant_phone": first_recipe_menu_text(restaurant.get("phone"), metadata.get("phone")),
        "restaurant_address": first_recipe_menu_text(
            restaurant.get("address"),
            metadata.get("full_address"),
            metadata.get("address"),
            metadata.get("address_line"),
        ),
        "restaurant_hours_text": first_recipe_menu_text(
            recipe_menu_snapshot_text_list(restaurant.get("hours")),
            metadata.get("hours_text"),
            recipe_menu_snapshot_text_list(metadata.get("hours")),
        ),
        "restaurant_current_status": first_recipe_menu_text(
            metadata.get("current_status"),
            metadata.get("status"),
        ),
        "restaurant_promotions": first_recipe_menu_text(
            metadata.get("rewards_text"),
            recipe_menu_snapshot_text_list(metadata.get("promotions")),
            metadata.get("rewards"),
        ),
        "restaurant_online_payment_available": metadata.get("online_payment_available"),
        "restaurant_delivery_available": metadata.get("delivery_available"),
    }


def recipe_menu_snapshot_item_fields(recipe_data):
    snapshot = load_recipe_menu_snapshot(recipe_data)
    mega_json = snapshot.get("menu_mega_json") if isinstance(snapshot.get("menu_mega_json"), dict) else {}
    menu = mega_json.get("menu") if isinstance(mega_json.get("menu"), dict) else {}
    sections = menu.get("sections") if isinstance(menu.get("sections"), list) else []
    item_id = recipe_menu_relation_value(recipe_data, "menu_item_id")
    item_name_candidates = recipe_menu_item_name_candidates(recipe_data)
    section_candidates = recipe_menu_section_candidates(recipe_data)
    name_matches = []

    for section in sections:
        if not isinstance(section, dict):
            continue
        section_name = clean_recipe_menu_text(section.get("section_name") or "")
        for item in (section.get("items") if isinstance(section.get("items"), list) else []):
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            current_item_id = first_recipe_menu_text(item.get("menu_item_id"), metadata.get("menu_item_id"))
            item_name = recipe_menu_match_text(item.get("name") or item.get("item_name"))
            item_section = recipe_menu_match_text(section_name)
            item_fields = {
                "menu_section": section_name,
                "menu_item_name": first_recipe_menu_text(item.get("name"), item.get("item_name")),
                "menu_order_url": first_recipe_menu_text(item.get("menu_order_url"), item.get("deep_link_url")),
                "menu_price": first_recipe_menu_text(item.get("price_text"), item.get("price")),
                "menu_description": first_recipe_menu_text(item.get("description"), item.get("menu_description")),
            }

            if item_id and current_item_id == item_id:
                return item_fields

            if item_name_candidates and item_name in item_name_candidates:
                name_matches.append((item_section, item_fields))

    if len(name_matches) == 1:
        return name_matches[0][1]

    if name_matches and section_candidates:
        for item_section, item_fields in name_matches:
            if item_section in section_candidates:
                return item_fields

    return {}


def find_recipe_menu_item_by_url(payload, recipe_data):
    payload = payload if isinstance(payload, dict) else {}
    candidates = recipe_menu_source_url_candidates(recipe_data)
    candidate_keys = {
        normalize_recipe_url_key(candidate)
        for candidate in candidates
        if normalize_recipe_url_key(candidate)
    }
    menu_item_tokens = {
        recipe_menu_item_token_from_url(candidate)
        for candidate in candidates
        if recipe_menu_item_token_from_url(candidate)
    }
    source_menu_keys = recipe_menu_source_url_keys(recipe_data)
    item_name_candidates = recipe_menu_item_name_candidates(recipe_data)
    section_candidates = recipe_menu_section_candidates(recipe_data)

    if not candidate_keys and not menu_item_tokens and not source_menu_keys:
        return {}

    source_name_matches = []
    for item in payload.get("items", []):
        item_urls = [
            item.get("recipe_url"),
            item.get("recipe_id"),
            item.get("url"),
            item.get("menu_order_url"),
            item.get("deep_link_url"),
        ]
        if any(normalize_recipe_url_key(value) in candidate_keys for value in item_urls if value):
            return item

        if menu_item_tokens:
            item_token = first_recipe_menu_text(
                recipe_menu_item_token_from_url(item.get("recipe_url")),
                recipe_menu_item_token_from_url(item.get("recipe_id")),
                item.get("menu_item_token"),
            )
            if item_token and item_token in menu_item_tokens:
                return item

        if source_menu_keys and item_name_candidates:
            item_source_keys = menu_store_item_source_url_keys(item)
            item_name = recipe_menu_match_text(item.get("item_name"))
            if item_source_keys & source_menu_keys and item_name in item_name_candidates:
                source_name_matches.append(item)

    if len(source_name_matches) == 1:
        return source_name_matches[0]

    if source_name_matches and section_candidates:
        for item in source_name_matches:
            item_section = recipe_menu_match_text(item.get("menu_section"))
            if item_section in section_candidates:
                return item

    return {}


def linked_recipe_menu_records(recipe_data, payload=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    payload = payload or menu_store_service.load_menu_store()
    item = {}
    menu = {}
    restaurant = {}
    section = {}

    menu_item_id = recipe_menu_relation_value(recipe_data, "menu_item_id")
    if menu_item_id:
        item = menu_store_service.find_menu_item(payload, menu_item_id) or {}

    if not item:
        item = find_recipe_menu_item_by_url(payload, recipe_data)

    menu_id = first_recipe_menu_text(
        recipe_menu_relation_value(recipe_data, "menu_id"),
        item.get("menu_id"),
    )
    if menu_id:
        menu = menu_store_service.find_menu(payload, menu_id) or {}

    restaurant_id = first_recipe_menu_text(
        recipe_menu_relation_value(recipe_data, "restaurant_id"),
        item.get("restaurant_id"),
        menu.get("restaurant_id"),
    )
    if restaurant_id:
        restaurant = menu_store_service.restaurant_for(payload, restaurant_id) or {}

    section_id = first_recipe_menu_text(
        recipe_menu_relation_value(recipe_data, "menu_section_id"),
        item.get("menu_section_id"),
    )
    if section_id:
        section = next(
            (row for row in payload.get("sections", []) if row.get("id") == section_id),
            {},
        )

    if not section and item.get("menu_section"):
        section = {"section_name": item.get("menu_section")}

    if not menu and section.get("menu_id"):
        menu = menu_store_service.find_menu(payload, section.get("menu_id")) or {}

    if not restaurant and section.get("restaurant_id"):
        restaurant = menu_store_service.restaurant_for(payload, section.get("restaurant_id")) or {}

    if not restaurant and menu.get("restaurant_id"):
        restaurant = menu_store_service.restaurant_for(payload, menu.get("restaurant_id")) or {}

    return {
        "payload": payload,
        "restaurant": restaurant,
        "menu": menu,
        "section": section,
        "item": item,
    }


def recipe_menu_text_list_for_editor(value):
    if isinstance(value, list):
        return ", ".join(clean_recipe_menu_text(item) for item in value if clean_recipe_menu_text(item))
    return clean_recipe_menu_text(value)


def recipe_menu_bool_for_editor(*values):
    for value in values:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            continue
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return "true"
        if text in {"false", "0", "no", "off"}:
            return "false"
    return ""


def parse_recipe_menu_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def split_recipe_menu_text_list(value):
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").replace("\r", "\n").replace(";", ",").split(",")
        if len(raw_values) == 1:
            raw_values = str(value or "").split("\n")

    values = []
    seen = set()
    for item in raw_values:
        text = clean_recipe_menu_text(item)
        key = text.lower()
        if text and key not in seen:
            values.append(text)
            seen.add(key)
    return values


def recipe_has_menu_metadata(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)

    if clean_recipe_menu_text(recipe_data.get("source_type")).lower() in {"menu_item_inferred", "menu_item_stub"}:
        return True

    if any(recipe_menu_relation_value(recipe_data, field) for field in RESTAURANT_MENU_RELATION_FIELDS):
        return True

    for field in RESTAURANT_MENU_METADATA_FIELDS:
        value = recipe_data.get(field)
        if field == "source_menu_url":
            value = value or recipe_data.get("menu_source_url") or recipe_data.get("source_display_url")
        if clean_recipe_menu_text(value):
            return True

    return any(clean_recipe_menu_text(metadata.get(field)) for field in RESTAURANT_MENU_METADATA_FIELDS)


def recipe_is_menu_derived(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    source_type = clean_recipe_menu_text(recipe_data.get("source_type")).lower()

    if source_type in {"menu_item_inferred", "menu_item_stub"}:
        return True

    return bool(recipe_data.get("ai_inferred")) and recipe_has_menu_metadata(recipe_data)


def editable_recipe_menu_metadata(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    records = linked_recipe_menu_records(recipe_data)
    restaurant = records.get("restaurant", {})
    menu = records.get("menu", {})
    section = records.get("section", {})
    item = records.get("item", {})
    snapshot_fields = recipe_menu_snapshot_restaurant_fields(recipe_data)
    snapshot_item_fields = recipe_menu_snapshot_item_fields(recipe_data)
    source_menu_url = first_recipe_menu_text(
        recipe_data.get("source_menu_url"),
        recipe_data.get("menu_source_url"),
        metadata.get("source_menu_url"),
        menu.get("source_url"),
        restaurant.get("source_menu_url"),
        snapshot_fields.get("source_menu_url"),
        recipe_menu_source_url_from_candidates(recipe_data),
        recipe_data.get("source_display_url") if recipe_has_menu_metadata(recipe_data) else "",
    )
    fields = {
        "restaurant_name": first_recipe_menu_text(
            restaurant.get("restaurant_name"),
            recipe_data.get("restaurant_name"),
            metadata.get("restaurant_name"),
            snapshot_fields.get("restaurant_name"),
        ),
        "restaurant_website_url": first_recipe_menu_text(
            restaurant.get("restaurant_website_url"),
            recipe_data.get("restaurant_website_url"),
            metadata.get("restaurant_website_url"),
            snapshot_fields.get("restaurant_website_url"),
        ),
        "source_menu_url": source_menu_url,
        "restaurant_cuisine_tags": first_recipe_menu_text(
            recipe_menu_text_list_for_editor(restaurant.get("cuisine_tags")),
            recipe_data.get("restaurant_cuisine_tags"),
            metadata.get("restaurant_cuisine_tags"),
            snapshot_fields.get("restaurant_cuisine_tags"),
        ),
        "restaurant_phone": first_recipe_menu_text(
            restaurant.get("phone"),
            recipe_data.get("restaurant_phone"),
            metadata.get("restaurant_phone"),
            snapshot_fields.get("restaurant_phone"),
        ),
        "restaurant_address": first_recipe_menu_text(
            restaurant.get("full_address"),
            restaurant.get("address_line"),
            recipe_data.get("restaurant_address"),
            metadata.get("restaurant_address"),
            snapshot_fields.get("restaurant_address"),
        ),
        "restaurant_hours_text": first_recipe_menu_text(
            restaurant.get("hours_text"),
            recipe_data.get("restaurant_hours_text"),
            metadata.get("restaurant_hours_text"),
            snapshot_fields.get("restaurant_hours_text"),
        ),
        "restaurant_current_status": first_recipe_menu_text(
            restaurant.get("current_status"),
            recipe_data.get("restaurant_current_status"),
            metadata.get("restaurant_current_status"),
            snapshot_fields.get("restaurant_current_status"),
        ),
        "restaurant_promotions": first_recipe_menu_text(
            restaurant.get("rewards_text"),
            recipe_menu_text_list_for_editor(restaurant.get("promotions")),
            recipe_data.get("restaurant_promotions"),
            metadata.get("restaurant_promotions"),
            snapshot_fields.get("restaurant_promotions"),
        ),
        "restaurant_online_payment_available": recipe_menu_bool_for_editor(
            restaurant.get("online_payment_available") if restaurant else None,
            recipe_data.get("restaurant_online_payment_available"),
            metadata.get("restaurant_online_payment_available"),
            snapshot_fields.get("restaurant_online_payment_available"),
        ),
        "restaurant_delivery_available": recipe_menu_bool_for_editor(
            restaurant.get("delivery_available") if restaurant else None,
            recipe_data.get("restaurant_delivery_available"),
            metadata.get("restaurant_delivery_available"),
            snapshot_fields.get("restaurant_delivery_available"),
        ),
        "menu_section": first_recipe_menu_text(
            recipe_data.get("menu_section"),
            metadata.get("menu_section"),
            section.get("section_name"),
            item.get("menu_section"),
            snapshot_item_fields.get("menu_section"),
        ),
        "menu_item_name": first_recipe_menu_text(
            recipe_data.get("menu_item_name"),
            metadata.get("menu_item_name"),
            item.get("item_name"),
            snapshot_item_fields.get("menu_item_name"),
        ),
        "menu_order_url": first_recipe_menu_text(
            recipe_data.get("menu_order_url"),
            recipe_data.get("deep_link_url"),
            metadata.get("menu_order_url"),
            metadata.get("deep_link_url"),
            item.get("menu_order_url"),
            item.get("deep_link_url"),
            snapshot_item_fields.get("menu_order_url"),
        ),
        "menu_price": first_recipe_menu_text(
            recipe_data.get("menu_price"),
            metadata.get("menu_price"),
            metadata.get("price"),
            item.get("menu_price"),
            snapshot_item_fields.get("menu_price"),
        ),
        "menu_description": first_recipe_menu_text(
            recipe_data.get("menu_description"),
            metadata.get("menu_description"),
            metadata.get("description"),
            item.get("menu_description"),
            snapshot_item_fields.get("menu_description"),
        ),
    }
    has_metadata = recipe_has_menu_metadata({**recipe_data, **fields})
    is_menu_derived = recipe_is_menu_derived({**recipe_data, **fields})

    return {
        **fields,
        "restaurant_id": first_recipe_menu_text(
            recipe_menu_relation_value(recipe_data, "restaurant_id"),
            restaurant.get("id"),
        ),
        "menu_id": first_recipe_menu_text(
            recipe_menu_relation_value(recipe_data, "menu_id"),
            menu.get("id"),
        ),
        "menu_section_id": first_recipe_menu_text(
            recipe_menu_relation_value(recipe_data, "menu_section_id"),
            section.get("id"),
            item.get("menu_section_id"),
        ),
        "menu_item_id": first_recipe_menu_text(
            recipe_menu_relation_value(recipe_data, "menu_item_id"),
            item.get("id"),
        ),
        "is_menu_derived": bool(is_menu_derived or has_metadata),
        "menu_metadata_available": bool(has_metadata),
    }


def recipe_with_menu_metadata(recipe_data):
    recipe_data = dict(recipe_data) if isinstance(recipe_data, dict) else {}
    metadata = editable_recipe_menu_metadata(recipe_data)

    if metadata.get("is_menu_derived") or metadata.get("menu_metadata_available"):
        recipe_data.update(metadata)

    return recipe_data


def payload_includes_menu_metadata(payload):
    payload = payload if isinstance(payload, dict) else {}
    return any(field in payload for field in RESTAURANT_MENU_METADATA_FIELDS)


def apply_recipe_menu_metadata_to_store(recipe_data, payload):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    payload = payload if isinstance(payload, dict) else {}

    with menu_store_service.MENU_STORE_LOCK:
        store = menu_store_service.load_menu_store()
        records = linked_recipe_menu_records(recipe_data, payload=store)
        restaurant = records.get("restaurant", {})
        menu = records.get("menu", {})
        section = records.get("section", {})
        item = records.get("item", {})
        now = menu_store_service.utc_now_iso()
        updated = False

        if restaurant:
            field_map = {
                "restaurant_name": "restaurant_name",
                "restaurant_website_url": "restaurant_website_url",
                "restaurant_phone": "phone",
                "restaurant_address": "full_address",
                "restaurant_hours_text": "hours_text",
                "restaurant_current_status": "current_status",
                "restaurant_promotions": "rewards_text",
            }
            for payload_key, store_key in field_map.items():
                if payload_key in payload:
                    restaurant[store_key] = clean_recipe_menu_text(payload.get(payload_key)) or None
                    updated = True
            if "restaurant_cuisine_tags" in payload:
                restaurant["cuisine_tags"] = split_recipe_menu_text_list(payload.get("restaurant_cuisine_tags"))
                updated = True
            if "restaurant_promotions" in payload:
                restaurant["promotions"] = split_recipe_menu_text_list(payload.get("restaurant_promotions"))
                updated = True
            if "restaurant_online_payment_available" in payload:
                restaurant["online_payment_available"] = parse_recipe_menu_bool(
                    payload.get("restaurant_online_payment_available")
                )
                updated = True
            if "restaurant_delivery_available" in payload:
                restaurant["delivery_available"] = parse_recipe_menu_bool(
                    payload.get("restaurant_delivery_available")
                )
                updated = True
            if "source_menu_url" in payload:
                restaurant["source_menu_url"] = clean_recipe_menu_text(payload.get("source_menu_url")) or None
                updated = True
            if updated:
                restaurant["updated_at"] = now

        if menu and "source_menu_url" in payload:
            menu["source_url"] = clean_recipe_menu_text(payload.get("source_menu_url"))
            menu["updated_at"] = now
            updated = True

        if section and "menu_section" in payload:
            section["section_name"] = clean_recipe_menu_text(payload.get("menu_section")) or None
            updated = True

        if item:
            item_updated = False
            item_field_map = {
                "menu_section": "menu_section",
                "menu_item_name": "item_name",
                "menu_order_url": "menu_order_url",
                "menu_price": "menu_price",
                "menu_description": "menu_description",
            }
            for payload_key, store_key in item_field_map.items():
                if payload_key in payload:
                    item[store_key] = clean_recipe_menu_text(payload.get(payload_key)) or None
                    updated = True
                    item_updated = True
            if "menu_section" in payload and section:
                item["menu_section_id"] = section.get("id", item.get("menu_section_id"))
            if item_updated:
                item["updated_at"] = now

        if updated:
            menu_store_service.save_menu_store(store)

    return updated


def apply_recipe_menu_metadata_payload(recipe_data, payload):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    payload = payload if isinstance(payload, dict) else {}

    if not payload_includes_menu_metadata(payload):
        return recipe_data

    payload_has_value = any(
        parse_recipe_menu_bool(payload.get(field)) is not None
        if field in {"restaurant_online_payment_available", "restaurant_delivery_available"}
        else bool(clean_recipe_menu_text(payload.get(field)))
        for field in RESTAURANT_MENU_METADATA_FIELDS
        if field in payload
    )
    if (
        not payload_has_value
        and not recipe_is_menu_derived(recipe_data)
        and not recipe_has_menu_metadata(recipe_data)
    ):
        return recipe_data

    linked_records = linked_recipe_menu_records(recipe_data)
    has_normalized_link = any(
        recipe_menu_relation_value(recipe_data, field)
        for field in RESTAURANT_MENU_RELATION_FIELDS
    ) or any(
        linked_records.get(field)
        for field in ("restaurant", "menu", "section", "item")
    )

    if has_normalized_link:
        apply_recipe_menu_metadata_to_store(recipe_data, payload)

    for field in ("menu_section", "menu_item_name", "menu_order_url", "menu_price", "menu_description", "source_menu_url"):
        if field in payload:
            recipe_data[field] = clean_recipe_menu_text(payload.get(field))

    if not has_normalized_link:
        for field in RESTAURANT_MENU_METADATA_FIELDS:
            if field not in payload:
                continue
            if field in {"restaurant_online_payment_available", "restaurant_delivery_available"}:
                parsed = parse_recipe_menu_bool(payload.get(field))
                recipe_data[field] = "" if parsed is None else parsed
            else:
                recipe_data[field] = clean_recipe_menu_text(payload.get(field))

    if recipe_data.get("source_menu_url") and not recipe_data.get("menu_source_url"):
        recipe_data["menu_source_url"] = recipe_data["source_menu_url"]
    if recipe_data.get("menu_order_url") and not recipe_data.get("deep_link_url"):
        recipe_data["deep_link_url"] = recipe_data["menu_order_url"]

    return recipe_data


def load_editable_recipe(url):
    url = str(url or "").strip()
    recipe_data = load_recipe_output(url) or {"source_url": url}
    apply_recipe_pdf_asset_aliases(recipe_data)
    source_url = str(recipe_data.get("source_url") or url).strip() or url
    hydrate_source_pdf_assets_from_url(recipe_data, source_url)
    menu_metadata = editable_recipe_menu_metadata(recipe_data)
    log_recipe_pdf_fields("load_editable_recipe", recipe_data)
    meta = load_recipe_ingredients().get(normalize_recipe_url_key(url), {})
    cookbook_assignment = cookbook_recipe_assignment_for_url(url)
    pdf = editable_recipe_pdf_info(source_url, recipe_data)
    scaling = normalize_recipe_scaling_metadata(recipe_data.get("scaling"))
    recipe_data_servings = recipe_info_clean_value(recipe_data.get("servings"), "servings")
    if recipe_data_servings and not scaling.get("base_servings"):
        scaling["base_servings"] = recipe_data_servings
    recipe_info = recipe_information_fields(recipe_data, url)
    for key in recipe_information_keys():
        recipe_info[key] = recipe_info.get(key) or recipe_info_clean_value(meta.get(key), key)
    servings = (
        recipe_data_servings
        or recipe_info_clean_value(meta.get("servings"), "servings")
        or recipe_info_clean_value(meta.get("base_servings"), "servings")
    )
    if editor_recipe_info_defaults_available(recipe_data):
        servings = servings or editor_recipe_info_default_value(recipe_data, "servings")
        for key in recipe_information_keys():
            recipe_info[key] = recipe_info.get(key) or editor_recipe_info_default_value(recipe_data, key)
    if servings and not scaling.get("base_servings"):
        scaling["base_servings"] = servings
    cover_image = editable_recipe_cover_image(url, recipe_data, meta)
    category_metadata = recipe_category_metadata_for_editor(url, recipe_data, meta)

    return {
        "ok": True,
        "recipe": {
            "source_url": recipe_data.get("source_url") or url,
            "source_display_url": editable_recipe_source_display_url(recipe_data.get("source_url") or url),
            "type": recipe_url_type(url),
            "display_name": meta.get("name") or recipe_data.get("display_name") or recipe_data.get("recipe_title") or "",
            "quantity": normalize_recipe_quantity(meta.get("quantity", 1)),
            "cookbook_id": cookbook_assignment.get("cookbook_id", ""),
            "cookbook_name": cookbook_assignment.get("cookbook_name", ""),
            "cookbook_is_unclassified": cookbook_assignment.get("cookbook_is_unclassified", False),
            "recipe_title": recipe_data.get("recipe_title") or "",
            "servings": servings,
            "cover_image": cover_image,
            **recipe_info,
            "scaling": scaling,
            "ingredients": annotate_ingredients_for_food_review(
                normalize_edit_ingredients(recipe_data.get("ingredients", []))
            ),
            "equipment": normalize_equipment_records(recipe_data.get("equipment", [])),
            "instructions": normalize_instruction_rows(recipe_data.get("instructions", [])),
            "nutrition": normalize_nutrition_rows(
                recipe_data.get("nutrition", {}),
                include_defaults=recipe_url_type(url) == "Manual",
            ),
            "rating": normalize_recipe_rating(recipe_data.get("rating")),
            "reflection_notes": normalize_reflection_notes(recipe_data.get("reflection_notes")),
            "chatgpt_feedback": str(recipe_data.get("chatgpt_feedback") or "").strip(),
            "chatgpt_feedback_created_at": str(recipe_data.get("chatgpt_feedback_created_at") or "").strip(),
            "source_pdf_path": pdf["webpage_backup"]["path"],
            "source_cloudflare_pdf_url": pdf["webpage_backup"]["public_url"],
            "source_cloudflare_pdf_path": pdf["webpage_backup"]["public_url"],
            "generated_pdf_path": pdf["generated_recipe"]["path"],
            "generated_cloudflare_pdf_url": pdf["generated_recipe"]["public_url"],
            "generated_cloudflare_pdf_path": pdf["generated_recipe"]["public_url"],
            "source_pdf_available": pdf["webpage_backup"]["available"],
            "source_pdf_local_available": pdf["webpage_backup"]["local_available"],
            "generated_pdf_available": pdf["generated_recipe"]["available"],
            "generated_pdf_local_available": pdf["generated_recipe"]["local_available"],
            "pdf_path": pdf["path"],
            "pdf_available": pdf["available"],
            "pdf_local_available": pdf["local_available"],
            "pdf_public_url": pdf["public_url"],
            "pdf_object_key": pdf["object_key"],
            "pdf_uploaded_at": pdf["uploaded_at"],
            "pdf_status": pdf["status"],
            "generated_recipe_pdf_path": pdf["generated_recipe"]["path"],
            "generated_recipe_pdf_available": pdf["generated_recipe"]["available"],
            "generated_recipe_pdf_local_available": pdf["generated_recipe"]["local_available"],
            "generated_recipe_pdf_url": pdf["generated_recipe"]["public_url"],
            "generated_recipe_pdf_object_key": pdf["generated_recipe"]["object_key"],
            "generated_recipe_pdf_uploaded_at": pdf["generated_recipe"]["uploaded_at"],
            "generated_recipe_pdf_status": pdf["generated_recipe"]["status"],
            "webpage_backup_pdf_path": pdf["webpage_backup"]["path"],
            "webpage_backup_pdf_available": pdf["webpage_backup"]["available"],
            "webpage_backup_pdf_local_available": pdf["webpage_backup"]["local_available"],
            "webpage_backup_pdf_url": pdf["webpage_backup"]["public_url"],
            "webpage_backup_pdf_object_key": pdf["webpage_backup"]["object_key"],
            "webpage_backup_pdf_uploaded_at": pdf["webpage_backup"]["uploaded_at"],
            "webpage_backup_pdf_status": pdf["webpage_backup"]["status"],
            "source_type": recipe_data.get("source_type", ""),
            "ai_inferred": bool(recipe_data.get("ai_inferred")),
            "restaurant_id": recipe_menu_relation_value(recipe_data, "restaurant_id"),
            "menu_id": recipe_menu_relation_value(recipe_data, "menu_id"),
            "menu_section_id": recipe_menu_relation_value(recipe_data, "menu_section_id"),
            "menu_item_id": recipe_menu_relation_value(recipe_data, "menu_item_id"),
            **menu_metadata,
            **category_metadata,
        },
        "food_rules": load_food_rules(),
        "store_sections": list(STORE_SECTION_ORDER.keys()),
    }


def editable_recipe_cover_image(url, recipe_data, recipe_meta=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    cover_image = recipe_data.get("cover_image")

    if not isinstance(cover_image, dict) or not cover_image:
        cover_image = recipe_meta.get("cover_image")

    if not isinstance(cover_image, dict) or not cover_image:
        return {}

    source_url = str(recipe_data.get("source_url") or url or "").strip()
    fallback_alt = (
        str(cover_image.get("alt") or "").strip()
        or str(recipe_data.get("recipe_title") or recipe_meta.get("name") or "Recipe title image").strip()
    )
    normalized = normalize_recipe_cover_image(
        cover_image,
        base_url=source_url,
        fallback_alt=fallback_alt,
    )

    if not normalized:
        return {}

    src = ""
    if normalized.get("path") and source_url:
        src = f"/recipe_cover_image?url={quote(source_url, safe='')}"
    elif normalized.get("url"):
        src = normalized.get("url")

    variants = {}
    image_path = recipe_cover_image_file_path(normalized)
    if image_path and source_url:
        version = f"{int(image_path.stat().st_mtime)}-{image_path.stat().st_size}"

        def build_variant_url(variant, version_value):
            return (
                f"/recipe_cover_image?url={quote(source_url, safe='')}"
                f"&variant={quote(variant, safe='')}&v={quote(version_value, safe='')}"
            )

        variants = cover_image_variant_payload(src, image_path, build_variant_url)

    return {
        **normalized,
        "alt": normalized.get("alt") or fallback_alt,
        "src": src,
        **variants,
    }


def normalize_pdf_kind(pdf_kind):
    value = str(pdf_kind or "").strip().lower()

    if value in {
        PDF_KIND_GENERATED_RECIPE,
        "generated",
        "recipe",
        "clean",
        "clean_recipe",
        "generated-recipe",
    }:
        return PDF_KIND_GENERATED_RECIPE

    return PDF_KIND_WEBPAGE_BACKUP


def pdf_metadata_field_prefix(pdf_kind):
    return (
        "generated_recipe_pdf"
        if normalize_pdf_kind(pdf_kind) == PDF_KIND_GENERATED_RECIPE
        else "webpage_backup_pdf"
    )


def pdf_status_label(local_available, public_url):
    if public_url:
        return "Uploaded"
    if local_available:
        return "Saved"
    return "Missing"


def editable_recipe_pdf_kind_info(url, recipe_data=None, pdf_kind=PDF_KIND_GENERATED_RECIPE):
    pdf_kind = normalize_pdf_kind(pdf_kind)
    default_pdf_path = recipe_pdf_path(url, pdf_kind)
    metadata = normalize_recipe_pdf_storage_metadata(recipe_data or load_recipe_output(url) or {}, pdf_kind)
    public_url = metadata.get("public_url", "")
    if not is_shareable_pdf_public_url(public_url):
        public_url = ""
    stored_path = str(metadata.get("local_path") or "").strip()
    display_path = stored_path
    local_available = False

    for candidate in (stored_path, str(default_pdf_path)):
        if not candidate:
            continue
        try:
            if Path(candidate).exists():
                local_available = True
                if not display_path:
                    display_path = candidate
                break
        except (OSError, TypeError, ValueError):
            continue

    if not display_path and pdf_kind == PDF_KIND_WEBPAGE_BACKUP and default_pdf_path.exists():
        display_path = str(default_pdf_path)

    return {
        "path": display_path,
        "available": local_available or bool(public_url),
        "local_available": local_available,
        "public_url": public_url,
        "object_key": metadata.get("object_key", ""),
        "uploaded_at": metadata.get("uploaded_at", ""),
        "cloud_status": metadata.get("cloud_status", ""),
        "status": pdf_status_label(local_available, public_url),
    }


def editable_recipe_pdf_info(url, recipe_data=None):
    recipe_data = recipe_data or load_recipe_output(url) or {}
    generated = editable_recipe_pdf_kind_info(url, recipe_data, PDF_KIND_GENERATED_RECIPE)
    webpage_backup = editable_recipe_pdf_kind_info(url, recipe_data, PDF_KIND_WEBPAGE_BACKUP)

    return {
        **generated,
        "generated_recipe": generated,
        "webpage_backup": webpage_backup,
    }


def source_pdf_asset_reference_for_url(source_url, fallback_recipe_data=None):
    source_url = str(source_url or "").strip()
    fallback_recipe_data = fallback_recipe_data if isinstance(fallback_recipe_data, dict) else {}
    reference = load_recipe_output(source_url) if source_url else None

    if not isinstance(reference, dict):
        reference = {}

    apply_recipe_pdf_asset_aliases(reference)

    reference_pdf_info = (
        editable_recipe_pdf_kind_info(
            source_url,
            reference,
            PDF_KIND_WEBPAGE_BACKUP,
        )
        if source_url
        else {}
    )

    if not first_pdf_asset_value(
        reference.get("source_pdf_path"),
        reference.get("source_cloudflare_pdf_url"),
        reference_pdf_info.get("path"),
        reference_pdf_info.get("public_url"),
    ):
        fallback_reference = apply_recipe_pdf_asset_aliases(dict(fallback_recipe_data))
        for field in (
            "source_pdf_path",
            "webpage_backup_pdf_path",
            "pdf_path",
            "source_cloudflare_pdf_url",
            "source_cloudflare_pdf_path",
            "webpage_backup_pdf_url",
            "cloudflare_pdf_url",
        ):
            if clean_pdf_asset_value(reference.get(field)) or not clean_pdf_asset_value(fallback_reference.get(field)):
                continue
            reference[field] = fallback_reference.get(field)
        if not isinstance(reference.get("pdf"), dict) and isinstance(fallback_reference.get("pdf"), dict):
            reference["pdf"] = deepcopy(fallback_reference["pdf"])
        apply_recipe_pdf_asset_aliases(reference)
        reference_pdf_info = (
            editable_recipe_pdf_kind_info(
                source_url,
                reference,
                PDF_KIND_WEBPAGE_BACKUP,
            )
            if source_url
            else {}
        )

    if source_url:
        source_pdf_path = first_pdf_asset_value(
            reference.get("source_pdf_path"),
            reference_pdf_info.get("path"),
        )
        source_cloudflare_pdf_url = first_pdf_asset_value(
            reference.get("source_cloudflare_pdf_url"),
            reference_pdf_info.get("public_url"),
        )
        if source_pdf_path:
            reference["source_pdf_path"] = source_pdf_path
            reference["webpage_backup_pdf_path"] = source_pdf_path
            reference["pdf_path"] = source_pdf_path
        if source_cloudflare_pdf_url:
            reference["source_cloudflare_pdf_url"] = source_cloudflare_pdf_url
            reference["source_cloudflare_pdf_path"] = source_cloudflare_pdf_url
            reference["webpage_backup_pdf_url"] = source_cloudflare_pdf_url
            reference["cloudflare_pdf_url"] = source_cloudflare_pdf_url

    return apply_recipe_pdf_asset_aliases(reference)


def hydrate_source_pdf_assets_from_url(recipe_data, source_url=None):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    source_url = str(source_url or recipe_data.get("source_url") or "").strip()

    if not source_url:
        return recipe_data

    apply_recipe_pdf_asset_aliases(recipe_data)
    reference = source_pdf_asset_reference_for_url(source_url, recipe_data)
    source_pdf_path = first_pdf_asset_value(reference.get("source_pdf_path"))
    source_cloudflare_pdf_url = first_pdf_asset_value(reference.get("source_cloudflare_pdf_url"))

    if source_pdf_path and not clean_pdf_asset_value(recipe_data.get("source_pdf_path")):
        recipe_data["source_pdf_path"] = source_pdf_path
        recipe_data["webpage_backup_pdf_path"] = source_pdf_path
        recipe_data["pdf_path"] = source_pdf_path

    if source_cloudflare_pdf_url and not clean_pdf_asset_value(recipe_data.get("source_cloudflare_pdf_url")):
        recipe_data["source_cloudflare_pdf_url"] = source_cloudflare_pdf_url
        recipe_data["source_cloudflare_pdf_path"] = source_cloudflare_pdf_url
        recipe_data["webpage_backup_pdf_url"] = source_cloudflare_pdf_url
        recipe_data["cloudflare_pdf_url"] = source_cloudflare_pdf_url

    reference_pdf = reference.get("pdf") if isinstance(reference.get("pdf"), dict) else {}
    if reference_pdf:
        recipe_pdf = deepcopy(recipe_data.get("pdf")) if isinstance(recipe_data.get("pdf"), dict) else {}
        for field in (
            PDF_KIND_WEBPAGE_BACKUP,
            "local_path",
            "r2_object_key",
            "r2_public_url",
            "uploaded_at",
            "cloud_status",
            "cloudflare_r2",
        ):
            if field not in reference_pdf or recipe_pdf.get(field):
                continue
            recipe_pdf[field] = deepcopy(reference_pdf[field])
        if recipe_pdf:
            recipe_data["pdf"] = recipe_pdf

    for field in (
        "webpage_backup_pdf_object_key",
        "webpage_backup_pdf_uploaded_at",
    ):
        if reference.get(field) and not recipe_data.get(field):
            recipe_data[field] = reference.get(field)

    return apply_recipe_pdf_asset_aliases(recipe_data)


def editable_recipe_source_display_url(url):
    if recipe_url_type(url) == "File":
        return str(recipe_archive_pdf_path(url))

    return url


def utc_iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    pdf_kind = normalize_pdf_kind(pdf_kind)
    prefix = pdf_metadata_field_prefix(pdf_kind)
    is_generated = pdf_kind == PDF_KIND_GENERATED_RECIPE
    pdf_metadata = recipe_data.get("pdf") if isinstance(recipe_data.get("pdf"), dict) else {}
    kind_metadata = pdf_metadata.get(pdf_kind) if isinstance(pdf_metadata.get(pdf_kind), dict) else {}
    if pdf_kind == PDF_KIND_WEBPAGE_BACKUP and not kind_metadata:
        kind_metadata = pdf_metadata
    r2_metadata = (
        kind_metadata.get("cloudflare_r2")
        if isinstance(kind_metadata.get("cloudflare_r2"), dict)
        else {}
    )
    object_key = (
        str(recipe_data.get(f"{prefix}_object_key") or "").strip()
        or str(kind_metadata.get("r2_object_key") or "").strip()
        or str(r2_metadata.get("object_key") or "").strip()
    )
    public_url = (
        (
            (
                str(recipe_data.get("generated_cloudflare_pdf_url") or "").strip()
                or str(recipe_data.get("generated_cloudflare_pdf_path") or "").strip()
            )
            if is_generated
            else (
                str(recipe_data.get("source_cloudflare_pdf_url") or "").strip()
                or str(recipe_data.get("source_cloudflare_pdf_path") or "").strip()
            )
        )
        or str(recipe_data.get(f"{prefix}_url") or "").strip()
        or (
            ""
            if is_generated
            else str(recipe_data.get("cloudflare_pdf_url") or "").strip()
        )
        or str(kind_metadata.get("r2_public_url") or "").strip()
        or str(r2_metadata.get("public_url") or "").strip()
    )
    uploaded_at = (
        str(recipe_data.get(f"{prefix}_uploaded_at") or "").strip()
        or str(kind_metadata.get("uploaded_at") or "").strip()
        or str(r2_metadata.get("uploaded_at") or "").strip()
    )
    cloud_status = (
        str(kind_metadata.get("cloud_status") or "").strip()
        or str(r2_metadata.get("cloud_status") or "").strip()
        or ("uploaded" if object_key and public_url and uploaded_at else "")
    )

    return {
        "local_path": (
            (
                str(recipe_data.get("generated_pdf_path") or "").strip()
                if is_generated
                else str(recipe_data.get("source_pdf_path") or "").strip()
            )
            or str(recipe_data.get(f"{prefix}_path") or "").strip()
            or (
                ""
                if is_generated
                else str(recipe_data.get("pdf_path") or "").strip()
            )
            or str(kind_metadata.get("local_path") or "").strip()
        ),
        "object_key": object_key,
        "public_url": public_url,
        "uploaded_at": uploaded_at,
        "cloud_status": cloud_status,
        "bucket": str(r2_metadata.get("bucket") or "").strip(),
    }


def save_recipe_pdf_storage_metadata(
    url,
    upload_result,
    local_pdf_path=None,
    pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
):
    url = str(url or "").strip()
    upload_result = upload_result if isinstance(upload_result, dict) else {}
    pdf_kind = normalize_pdf_kind(pdf_kind)
    prefix = pdf_metadata_field_prefix(pdf_kind)

    if not url:
        return {
            "ok": False,
            "error": "Recipe URL is required.",
        }

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {
            "ok": False,
            "error": "Recipe data was not found.",
        }

    object_key = str(upload_result.get("object_key") or "").strip()
    public_url = str(upload_result.get("public_url") or "").strip()

    if not object_key or not public_url:
        return {
            "ok": False,
            "error": "Cloudflare R2 upload metadata is incomplete.",
        }

    uploaded_at = utc_iso_now()
    pdf_metadata = recipe_data.get("pdf") if isinstance(recipe_data.get("pdf"), dict) else {}
    local_path = str(local_pdf_path or recipe_pdf_path(url, pdf_kind))
    kind_metadata = {
        "local_path": local_path,
        "r2_object_key": object_key,
        "r2_public_url": public_url,
        "uploaded_at": uploaded_at,
        "cloud_status": "uploaded",
    }
    kind_metadata["cloudflare_r2"] = {
        "provider": "cloudflare_r2",
        "bucket": str(upload_result.get("bucket") or os.getenv("R2_BUCKET_NAME", "")).strip(),
        "object_key": object_key,
        "public_url": public_url,
        "uploaded_at": uploaded_at,
        "cloud_status": "uploaded",
    }
    pdf_metadata[pdf_kind] = kind_metadata

    if pdf_kind == PDF_KIND_WEBPAGE_BACKUP:
        pdf_metadata["local_path"] = local_path
        pdf_metadata["r2_object_key"] = object_key
        pdf_metadata["r2_public_url"] = public_url
        pdf_metadata["uploaded_at"] = uploaded_at
        pdf_metadata["cloud_status"] = "uploaded"
        pdf_metadata["cloudflare_r2"] = kind_metadata["cloudflare_r2"]

    recipe_data["pdf"] = pdf_metadata
    recipe_data[f"{prefix}_path"] = local_path
    recipe_data[f"{prefix}_url"] = public_url
    recipe_data[f"{prefix}_object_key"] = object_key
    recipe_data[f"{prefix}_uploaded_at"] = uploaded_at
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        recipe_data["generated_pdf_path"] = local_path
        recipe_data["generated_cloudflare_pdf_url"] = public_url
        recipe_data["generated_cloudflare_pdf_path"] = public_url
    else:
        recipe_data["source_pdf_path"] = local_path
        recipe_data["source_cloudflare_pdf_url"] = public_url
        recipe_data["source_cloudflare_pdf_path"] = public_url
        recipe_data["pdf_path"] = local_path
        recipe_data["cloudflare_pdf_url"] = public_url
    apply_recipe_pdf_asset_aliases(recipe_data)
    log_recipe_pdf_fields(f"save_pdf_metadata:{pdf_kind}", recipe_data)
    save_recipe_output(url, recipe_data)

    return {
        "ok": True,
        "metadata": normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind),
    }


def recipe_url_for_pdf_filename(pdf_filename):
    filename = Path(str(pdf_filename or "")).name

    if not filename or Path(filename).suffix.lower() != ".pdf":
        return ""

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        source_url = str(data.get("source_url") or "").strip()
        if source_url and any(
            recipe_pdf_path(source_url, pdf_kind).name == filename
            for pdf_kind in (PDF_KIND_WEBPAGE_BACKUP, PDF_KIND_GENERATED_RECIPE)
        ):
            return source_url

    return ""


def recipe_pdf_kind_for_filename(pdf_filename):
    filename = Path(str(pdf_filename or "")).name

    if not filename or Path(filename).suffix.lower() != ".pdf":
        return PDF_KIND_WEBPAGE_BACKUP

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        source_url = str(data.get("source_url") or "").strip()
        if not source_url:
            continue

        if recipe_pdf_path(source_url, PDF_KIND_GENERATED_RECIPE).name == filename:
            return PDF_KIND_GENERATED_RECIPE

        if recipe_pdf_path(source_url, PDF_KIND_WEBPAGE_BACKUP).name == filename:
            return PDF_KIND_WEBPAGE_BACKUP

    return (
        PDF_KIND_GENERATED_RECIPE
        if filename.lower().endswith("_generated_recipe.pdf")
        else PDF_KIND_WEBPAGE_BACKUP
    )


def recipe_pdf_storage_metadata_for_filename(pdf_filename):
    filename = Path(str(pdf_filename or "")).name
    source_url = recipe_url_for_pdf_filename(filename)

    if not source_url:
        return {}

    recipe_data = load_recipe_output(source_url) or {}
    pdf_kind = recipe_pdf_kind_for_filename(filename)
    metadata = normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind)

    if not is_shareable_pdf_public_url(metadata.get("public_url", "")):
        return {}

    return {
        **metadata,
        "source_url": source_url,
        "pdf_filename": filename,
        "pdf_kind": pdf_kind,
    }


def list_recipe_pdf_storage_metadata():
    rows = []

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        try:
            recipe_data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        source_url = str(recipe_data.get("source_url") or "").strip()

        if not source_url:
            continue

        for pdf_kind in (PDF_KIND_WEBPAGE_BACKUP, PDF_KIND_GENERATED_RECIPE):
            metadata = normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind)
            public_url = metadata.get("public_url", "")
            object_key = metadata.get("object_key", "")

            if not is_shareable_pdf_public_url(public_url):
                continue

            filename = (
                Path(metadata.get("local_path") or "").name
                or Path(object_key).name
                or recipe_pdf_path(source_url, pdf_kind).name
            )
            rows.append({
                **metadata,
                "source_url": source_url,
                "pdf_kind": pdf_kind,
                "pdf_filename": filename,
                "recipe_title": recipe_data.get("recipe_title") or "",
            })

    return rows


def cloudflare_upload_success(upload_result):
    return bool(upload_result and (upload_result.get("ok") or upload_result.get("code") == "duplicate_object"))


def recipe_pdf_timing_ms(start):
    return round((perf_counter() - start) * 1000, 2)


def recipe_pdf_timing_log():
    return {
        "cache_lookup_ms": 0,
        "pdf_generation_ms": 0,
        "r2_upload_ms": 0,
        "redirect_ms": 0,
    }


def log_recipe_pdf_timing(action, url, timings):
    timings = timings if isinstance(timings, dict) else {}
    print(
        "[recipe_pdf] "
        f"action={action} "
        f"url={url} "
        f"cache_lookup_ms={timings.get('cache_lookup_ms', 0)} "
        f"pdf_generation_ms={timings.get('pdf_generation_ms', 0)} "
        f"r2_upload_ms={timings.get('r2_upload_ms', 0)} "
        f"redirect_ms={timings.get('redirect_ms', 0)}"
    )


def is_app_tunnel_or_local_url(url):
    parsed = urlparse(str(url or "").strip())
    hostname = (parsed.hostname or "").lower()

    return (
        hostname in {"127.0.0.1", "localhost", "::1"}
        or hostname.endswith(".trycloudflare.com")
    )


def is_shareable_pdf_public_url(url):
    parsed = urlparse(str(url or "").strip())

    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not is_app_tunnel_or_local_url(url)
    )


def cloudflare_metadata_is_uploaded(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}

    return (
        metadata.get("cloud_status") == "uploaded"
        and bool(metadata.get("object_key"))
        and bool(metadata.get("uploaded_at"))
        and is_shareable_pdf_public_url(metadata.get("public_url"))
    )


def recipe_pdf_cloudflare_result(
    url,
    metadata,
    cached,
    pdf_path=None,
    timings=None,
    pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
):
    metadata = metadata if isinstance(metadata, dict) else {}
    pdf_kind = normalize_pdf_kind(pdf_kind)
    path = Path(pdf_path) if pdf_path else recipe_pdf_path(url, pdf_kind)
    prefix = pdf_metadata_field_prefix(pdf_kind)
    public_url = metadata.get("public_url", "")
    object_key = metadata.get("object_key", "")
    uploaded_at = metadata.get("uploaded_at", "")

    result = {
        "ok": True,
        "success": True,
        "cached": bool(cached),
        "url": url,
        "pdf_kind": pdf_kind,
        "public_url": public_url,
        "pdf_public_url": public_url,
        "r2_public_url": public_url,
        "pdf_object_key": object_key,
        "r2_object_key": object_key,
        "pdf_uploaded_at": uploaded_at,
        "uploaded_at": uploaded_at,
        "cloud_status": metadata.get("cloud_status", "uploaded"),
        "pdf_path": str(path),
        "pdf_available": True,
        "pdf_local_available": path.exists(),
        "timings": timings or recipe_pdf_timing_log(),
    }
    result[f"{prefix}_path"] = str(path)
    result[f"{prefix}_url"] = public_url
    result[f"{prefix}_object_key"] = object_key
    result[f"{prefix}_uploaded_at"] = uploaded_at
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        result["generated_pdf_path"] = str(path)
        result["generated_cloudflare_pdf_url"] = public_url
        result["generated_cloudflare_pdf_path"] = public_url
    else:
        result["source_pdf_path"] = str(path)
        result["source_cloudflare_pdf_url"] = public_url
        result["source_cloudflare_pdf_path"] = public_url
    return result


def cached_recipe_pdf_cloudflare_result(url, timings=None, pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    recipe_data = load_recipe_output(url) or {}
    pdf_kind = normalize_pdf_kind(pdf_kind)
    metadata = normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind)

    if not cloudflare_metadata_is_uploaded(metadata):
        return None

    return recipe_pdf_cloudflare_result(url, metadata, cached=True, timings=timings, pdf_kind=pdf_kind)


def existing_r2_recipe_pdf_result(url, timings=None, pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    if not cloudflare_r2_storage.has_required_r2_config():
        return None

    pdf_kind = normalize_pdf_kind(pdf_kind)
    pdf_path = recipe_pdf_path(url, pdf_kind)

    try:
        object_key = cloudflare_r2_storage.object_key_for_pdf(pdf_path)
        public_url = cloudflare_r2_storage.get_public_url(object_key)
        if not cloudflare_r2_storage.object_exists(object_key):
            return None
    except Exception as exc:
        print(f"[recipe_pdf] R2 cache probe failed for {url}: {exc}")
        return None

    upload_result = {
        "ok": True,
        "object_key": object_key,
        "public_url": public_url,
        "bucket": os.getenv("R2_BUCKET_NAME", "").strip(),
    }
    metadata_result = save_recipe_pdf_storage_metadata(url, upload_result, pdf_path, pdf_kind)
    metadata = (
        metadata_result.get("metadata", {})
        if metadata_result.get("ok")
        else {
            "local_path": str(pdf_path),
            "object_key": object_key,
            "public_url": public_url,
            "uploaded_at": utc_iso_now(),
            "cloud_status": "uploaded",
        }
    )

    return recipe_pdf_cloudflare_result(url, metadata, cached=True, timings=timings, pdf_kind=pdf_kind)


def delete_uploaded_local_pdf_if_configured(pdf_path):
    path = Path(pdf_path)

    if not cloudflare_r2_storage.delete_local_pdf_after_upload():
        return False, ""

    try:
        path.unlink(missing_ok=True)
        return True, ""
    except PermissionError:
        return False, "PDF uploaded to Cloudflare R2, but the local file is open and could not be deleted."
    except OSError as exc:
        return False, f"PDF uploaded to Cloudflare R2, but the local file could not be deleted: {exc}"


def upload_local_pdf_path_to_cloudflare(local_pdf_path, url="", pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    path = Path(local_pdf_path)
    pdf_kind = normalize_pdf_kind(pdf_kind)
    prefix = pdf_metadata_field_prefix(pdf_kind)
    upload_result = cloudflare_r2_storage.upload_pdf(path)

    if not cloudflare_upload_success(upload_result):
        return {
            "ok": False,
            "success": False,
            "url": str(url or ""),
            "pdf_path": str(path),
            "pdf_available": path.exists(),
            "pdf_local_available": path.exists(),
            "pdf_kind": pdf_kind,
            "cloudflare_upload": upload_result,
            "error": upload_result.get("error", "Unable to upload PDF to Cloudflare R2."),
        }

    if str(url or "").strip():
        save_recipe_pdf_storage_metadata(url, upload_result, path, pdf_kind)

    deleted_local_pdf, delete_warning = delete_uploaded_local_pdf_if_configured(path)
    public_url = str(upload_result.get("public_url") or "").strip()
    object_key = str(upload_result.get("object_key") or "").strip()
    uploaded_at = utc_iso_now()

    result = {
        "ok": True,
        "success": True,
        "url": str(url or ""),
        "pdf_kind": pdf_kind,
        "cached": upload_result.get("code") == "duplicate_object",
        "pdf_path": str(path),
        "pdf_available": path.exists() or bool(public_url),
        "pdf_local_available": path.exists(),
        "public_url": public_url,
        "r2_public_url": public_url,
        "pdf_public_url": public_url,
        "r2_object_key": object_key,
        "pdf_object_key": object_key,
        "pdf_uploaded_at": uploaded_at,
        "uploaded_at": uploaded_at,
        "cloud_status": "uploaded",
        "deleted_local_pdf": deleted_local_pdf,
        "delete_warning": delete_warning,
        "already_exists": upload_result.get("code") == "duplicate_object",
        "cloudflare_upload": upload_result,
    }
    result[f"{prefix}_path"] = str(path)
    result[f"{prefix}_url"] = public_url
    result[f"{prefix}_object_key"] = object_key
    result[f"{prefix}_uploaded_at"] = uploaded_at
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        result["generated_pdf_path"] = str(path)
        result["generated_cloudflare_pdf_url"] = public_url
        result["generated_cloudflare_pdf_path"] = public_url
    else:
        result["source_pdf_path"] = str(path)
        result["source_cloudflare_pdf_url"] = public_url
        result["source_cloudflare_pdf_path"] = public_url
    return result


def upload_recipe_pdf_to_cloudflare(url, pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    url = str(url or "").strip()
    pdf_kind = normalize_pdf_kind(pdf_kind)

    if not url:
        return {
            "ok": False,
            "success": False,
            "error": "Recipe URL is required.",
        }

    pdf_path = recipe_pdf_path(url, pdf_kind)
    recipe_data = load_recipe_output(url) or {}
    existing_metadata = normalize_recipe_pdf_storage_metadata(recipe_data, pdf_kind)

    if not pdf_path.exists():
        if cloudflare_metadata_is_uploaded(existing_metadata):
            return recipe_pdf_cloudflare_result(
                url,
                existing_metadata,
                cached=True,
                pdf_path=pdf_path,
                pdf_kind=pdf_kind,
            ) | {
                "already_exists": True,
                "cloudflare_upload": {
                    "ok": True,
                    "object_key": existing_metadata.get("object_key", ""),
                    "public_url": existing_metadata.get("public_url", ""),
                },
            }

        return {
            "ok": False,
            "success": False,
            "url": url,
            "pdf_kind": pdf_kind,
            "pdf_path": str(pdf_path),
            "pdf_available": False,
            "pdf_local_available": False,
            "error": "Create the recipe PDF before uploading it to Cloudflare R2.",
        }

    return upload_local_pdf_path_to_cloudflare(pdf_path, url=url, pdf_kind=pdf_kind)


def upload_all_recipe_pdfs_to_cloudflare(url):
    results = {}

    for pdf_kind in (PDF_KIND_WEBPAGE_BACKUP, PDF_KIND_GENERATED_RECIPE):
        pdf_path = recipe_pdf_path(url, pdf_kind)
        if not pdf_path.exists():
            if pdf_kind == PDF_KIND_GENERATED_RECIPE:
                generate_editable_recipe_pdf_file(url)
            elif is_web_source_url(url):
                generate_source_url_pdf_file(url)

        results[pdf_kind] = upload_recipe_pdf_to_cloudflare(url, pdf_kind=pdf_kind)

    ok = all(result.get("ok") for result in results.values())
    return {
        "ok": ok,
        "url": url,
        "webpage_backup": results.get(PDF_KIND_WEBPAGE_BACKUP, {}),
        "generated_recipe": results.get(PDF_KIND_GENERATED_RECIPE, {}),
        "error": "" if ok else "One or more PDFs could not be uploaded to Cloudflare.",
    }


def maybe_upload_generated_recipe_pdf_to_cloudflare(url, pdf_path):
    if not cloudflare_r2_storage.has_any_r2_config():
        return None

    return upload_local_pdf_path_to_cloudflare(pdf_path, url=url, pdf_kind=PDF_KIND_GENERATED_RECIPE)


def attach_cloudflare_pdf_result(result, upload_result, pdf_kind=PDF_KIND_GENERATED_RECIPE):
    if not upload_result:
        return result

    pdf_kind = normalize_pdf_kind(pdf_kind)
    prefix = pdf_metadata_field_prefix(pdf_kind)
    result["cloudflare_upload"] = upload_result.get("cloudflare_upload", upload_result)
    public_url = upload_result.get("pdf_public_url", "") or upload_result.get("public_url", "")
    object_key = upload_result.get("pdf_object_key", "") or upload_result.get("r2_object_key", "") or upload_result.get("object_key", "")
    uploaded_at = upload_result.get("uploaded_at", "") or upload_result.get("pdf_uploaded_at", "")
    result["public_url"] = public_url
    result["r2_public_url"] = result["public_url"]
    result["pdf_public_url"] = public_url
    result["r2_object_key"] = object_key
    result["pdf_object_key"] = object_key
    result["pdf_uploaded_at"] = uploaded_at
    result["uploaded_at"] = uploaded_at
    result["cloud_status"] = upload_result.get("cloud_status", "")
    result["pdf_local_available"] = upload_result.get("pdf_local_available", result.get("pdf_local_available", False))
    result["pdf_available"] = upload_result.get("pdf_available", result.get("pdf_available", False))
    result["deleted_local_pdf"] = upload_result.get("deleted_local_pdf", False)
    result[f"{prefix}_path"] = upload_result.get(f"{prefix}_path", result.get("pdf_path", ""))
    result[f"{prefix}_url"] = public_url
    result[f"{prefix}_object_key"] = object_key
    result[f"{prefix}_uploaded_at"] = uploaded_at
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        result["generated_pdf_path"] = result[f"{prefix}_path"]
        result["generated_cloudflare_pdf_url"] = public_url
        result["generated_cloudflare_pdf_path"] = public_url
    else:
        result["source_pdf_path"] = result[f"{prefix}_path"]
        result["source_cloudflare_pdf_url"] = public_url
        result["source_cloudflare_pdf_path"] = public_url

    if upload_result.get("delete_warning"):
        result["delete_warning"] = upload_result["delete_warning"]

    return result


def recipe_information_fields(recipe_data, url=""):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    parsed = {}

    if not all(recipe_info_value(recipe_data, key) for key in recipe_information_keys()):
        parsed = extract_recipe_info_from_saved_text(url)

    return {
        key: recipe_info_value(recipe_data, key) or parsed.get(key, "")
        for key in recipe_information_keys()
    }


def recipe_information_keys():
    return ("level", "total_time", "prep_time", "inactive_time", "cook_time")


def recipe_info_value(recipe_data, key):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    for alias in RECIPE_INFO_ESTIMATE_ALIASES.get(key, (key,)):
        value = recipe_info_clean_value(recipe_data.get(alias), key)
        if value:
            return value

    return ""


def recipe_info_clean_value(value, key=""):
    if isinstance(value, bool) or value in (None, "", [], {}):
        return ""

    if isinstance(value, (int, float)):
        if key == "servings":
            return f"{value:g} servings"
        if str(key).endswith("_time"):
            return f"{value:g} min"

    if isinstance(value, (list, dict)):
        return ""

    text = clean_recipe_menu_text(value)
    if text.lower() in RECIPE_INFO_EMPTY_VALUES:
        return ""
    return text


def editor_recipe_info_defaults_available(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    if not recipe_data.get("ingredients") or not recipe_data.get("instructions"):
        return False

    source_type = clean_recipe_menu_text(recipe_data.get("source_type")).lower()
    recipe_status = clean_recipe_menu_text(recipe_data.get("recipe_status")).lower()
    if source_type in {"menu_item_inferred", "menu_item_stub"}:
        return True
    if recipe_data.get("ai_inferred"):
        return True
    return recipe_status == "generated"


def editor_recipe_info_default_value(recipe_data, key):
    value = recipe_info_value(recipe_data, key)
    return value or RECIPE_INFO_ESTIMATE_DEFAULTS.get(key, "")


def extract_recipe_info_from_saved_text(url):
    url = str(url or "").strip()
    if not url:
        return {}

    text_path = RAW_FOLDER / f"{safe_filename(url)}_PAGE_TEXT.txt"

    if not text_path.exists():
        return {}

    try:
        return extract_recipe_info_from_text(text_path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}


def generate_editable_recipe_pdf_file(url, pdf_kind=PDF_KIND_GENERATED_RECIPE):
    url = str(url or "").strip()
    pdf_kind = normalize_pdf_kind(pdf_kind)

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(url)

    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    title = (
        recipe_data.get("recipe_title")
        or load_recipe_ingredients().get(normalize_recipe_url_key(url), {}).get("name")
        or "Recipe"
    )
    recipe_data_for_pdf = recipe_with_menu_metadata(recipe_data)
    html_text = build_video_text_pdf_html(
        url,
        "",
        title,
        recipe_data=recipe_data_for_pdf,
    )
    pdf_path = recipe_pdf_path(url, pdf_kind)
    saved_path = write_recipe_page_pdf(url, html_text, None, pdf_path)
    prefix = pdf_metadata_field_prefix(pdf_kind)
    local_path = str(saved_path)
    recipe_data[f"{prefix}_path"] = local_path
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        recipe_data["generated_pdf_path"] = local_path
    else:
        recipe_data["source_pdf_path"] = local_path
        recipe_data["pdf_path"] = local_path
    apply_recipe_pdf_asset_aliases(recipe_data)
    log_recipe_pdf_fields(f"generate_pdf_file:{pdf_kind}", recipe_data)
    save_recipe_output(url, recipe_data)
    result = {
        "ok": True,
        "url": url,
        "pdf_kind": pdf_kind,
        "pdf_path": str(saved_path),
        "pdf_available": True,
        "pdf_local_available": Path(saved_path).exists(),
    }
    result[f"{prefix}_path"] = str(saved_path)
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        result["generated_pdf_path"] = str(saved_path)
        result["generated_cloudflare_pdf_url"] = ""
        result["generated_cloudflare_pdf_path"] = ""
    else:
        result["source_pdf_path"] = str(saved_path)
        result["source_cloudflare_pdf_url"] = ""
        result["source_cloudflare_pdf_path"] = ""

    return result


def generate_source_url_pdf_file(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Source URL is required."}

    if not is_web_source_url(url):
        return generate_editable_recipe_pdf_file(url, pdf_kind=PDF_KIND_WEBPAGE_BACKUP)

    try:
        fetch_recipe_page(url)
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "error": f"Webpage PDF creation failed: {exc}",
        }

    pdf_path = recipe_pdf_path(url, PDF_KIND_WEBPAGE_BACKUP)
    if pdf_path.exists():
        recipe_data = load_recipe_output(url) or {"source_url": url}
        recipe_data["source_url"] = recipe_data.get("source_url") or url
        recipe_data["source_pdf_path"] = str(pdf_path)
        recipe_data["webpage_backup_pdf_path"] = str(pdf_path)
        recipe_data["pdf_path"] = str(pdf_path)
        apply_recipe_pdf_asset_aliases(recipe_data)
        log_recipe_pdf_fields("generate_source_url_pdf_file", recipe_data)
        save_recipe_output(url, recipe_data)
    result = {
        "ok": pdf_path.exists(),
        "url": url,
        "pdf_kind": PDF_KIND_WEBPAGE_BACKUP,
        "pdf_path": str(pdf_path),
        "pdf_available": pdf_path.exists(),
        "pdf_local_available": pdf_path.exists(),
        "error": None if pdf_path.exists() else "PDF file was not created.",
        "webpage_backup_pdf_path": str(pdf_path),
    }

    return result


def ensure_recipe_pdf_cloudflare_link(
    url,
    allow_local_fallback=True,
    pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
    force_regenerate=False,
):
    url = str(url or "").strip()
    pdf_kind = normalize_pdf_kind(pdf_kind)
    timings = recipe_pdf_timing_log()

    if not url:
        return {
            "ok": False,
            "success": False,
            "cached": False,
            "error": "Recipe URL is required.",
            "timings": timings,
        }

    cache_start = perf_counter()
    cached_result = None if force_regenerate else cached_recipe_pdf_cloudflare_result(
        url,
        timings=timings,
        pdf_kind=pdf_kind,
    )
    timings["cache_lookup_ms"] = recipe_pdf_timing_ms(cache_start)

    if cached_result:
        cached_result["timings"] = timings
        log_recipe_pdf_timing("cache_hit", url, timings)
        return cached_result

    r2_probe_start = perf_counter()
    existing_r2_result = None if force_regenerate else existing_r2_recipe_pdf_result(
        url,
        timings=timings,
        pdf_kind=pdf_kind,
    )
    timings["cache_lookup_ms"] += recipe_pdf_timing_ms(r2_probe_start)

    if existing_r2_result:
        existing_r2_result["timings"] = timings
        log_recipe_pdf_timing("r2_object_hit", url, timings)
        return existing_r2_result

    pdf_path = recipe_pdf_path(url, pdf_kind)
    local_result = {
        "ok": True,
        "url": url,
        "pdf_kind": pdf_kind,
        "pdf_path": str(pdf_path),
        "pdf_available": pdf_path.exists(),
        "pdf_local_available": pdf_path.exists(),
    }

    if force_regenerate or not pdf_path.exists():
        generation_start = perf_counter()
        local_result = (
            generate_editable_recipe_pdf_file(url, pdf_kind=pdf_kind)
            if pdf_kind == PDF_KIND_GENERATED_RECIPE
            else generate_source_url_pdf_file(url)
        )
        timings["pdf_generation_ms"] = recipe_pdf_timing_ms(generation_start)

        if not local_result.get("ok"):
            post_generation_cached_result = cached_recipe_pdf_cloudflare_result(
                url,
                timings=timings,
                pdf_kind=pdf_kind,
            )
            if post_generation_cached_result:
                post_generation_cached_result["cached"] = False
                post_generation_cached_result["timings"] = timings
                log_recipe_pdf_timing("generated_cached_upload", url, timings)
                return post_generation_cached_result

            local_result["success"] = False
            local_result["cached"] = False
            local_result["timings"] = timings
            log_recipe_pdf_timing("generation_failed", url, timings)
            return local_result

        pdf_path = Path(local_result.get("pdf_path") or recipe_pdf_path(url, pdf_kind))

    if cloudflare_r2_storage.has_any_r2_config():
        upload_start = perf_counter()
        upload_result = upload_local_pdf_path_to_cloudflare(pdf_path, url=url, pdf_kind=pdf_kind)
        timings["r2_upload_ms"] = recipe_pdf_timing_ms(upload_start)
        upload_result["cached"] = upload_result.get("already_exists", False)
        upload_result["timings"] = timings

        if upload_result.get("ok") and upload_result.get("pdf_public_url"):
            log_recipe_pdf_timing("uploaded", url, timings)
            return upload_result

        if not allow_local_fallback:
            upload_result["success"] = False
            log_recipe_pdf_timing("upload_failed", url, timings)
            return upload_result

        local_result["cloudflare_upload"] = upload_result.get("cloudflare_upload", upload_result)
        local_result["error"] = upload_result.get("error", "Unable to upload PDF to Cloudflare R2.")
    else:
        local_result["error"] = "Cloudflare R2 is not configured; using local PDF fallback."

    local_result.update({
        "success": False,
        "cached": False,
        "public_url": "",
        "r2_public_url": "",
        "pdf_public_url": "",
        "cloud_status": "local_only",
        "pdf_available": pdf_path.exists(),
        "pdf_local_available": pdf_path.exists(),
        "timings": timings,
    })
    log_recipe_pdf_timing("local_fallback", url, timings)

    return local_result


def create_editable_recipe_pdf(url):
    result = ensure_recipe_pdf_cloudflare_link(
        url,
        pdf_kind=PDF_KIND_GENERATED_RECIPE,
        force_regenerate=True,
    )
    log_recipe_pdf_fields("create_editable_recipe_pdf", load_recipe_output(url) or {"source_url": url})
    return result


def create_source_url_pdf(url):
    return ensure_recipe_pdf_cloudflare_link(
        url,
        pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
    )


def ensure_recipe_pdf_pair(url, regenerate_generated=False):
    results = {}

    try:
        results[PDF_KIND_WEBPAGE_BACKUP] = ensure_recipe_pdf_cloudflare_link(
            url,
            pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
            force_regenerate=False,
        )
    except Exception as exc:
        results[PDF_KIND_WEBPAGE_BACKUP] = {
            "ok": False,
            "error": str(exc),
        }

    try:
        results[PDF_KIND_GENERATED_RECIPE] = ensure_recipe_pdf_cloudflare_link(
            url,
            pdf_kind=PDF_KIND_GENERATED_RECIPE,
            force_regenerate=regenerate_generated,
        )
    except Exception as exc:
        results[PDF_KIND_GENERATED_RECIPE] = {
            "ok": False,
            "error": str(exc),
        }

    return {
        "ok": any(result.get("ok") for result in results.values()),
        "url": url,
        "webpage_backup": results.get(PDF_KIND_WEBPAGE_BACKUP, {}),
        "generated_recipe": results.get(PDF_KIND_GENERATED_RECIPE, {}),
    }


def is_web_source_url(url):
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def delete_editable_recipe_pdf(url):
    url = str(url or "").strip()

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    pdf_path = recipe_pdf_path(url, PDF_KIND_GENERATED_RECIPE)

    try:
        pdf_path.unlink(missing_ok=True)
    except PermissionError:
        return {
            "ok": False,
            "error": "Close the PDF before deleting it.",
            "url": url,
            "pdf_path": str(pdf_path),
            "pdf_available": pdf_path.exists(),
        }

    recipe_data = load_recipe_output(url) or {}
    if recipe_data:
        recipe_data["generated_pdf_path"] = ""
        recipe_data["generated_cloudflare_pdf_url"] = ""
        recipe_data["generated_cloudflare_pdf_path"] = ""
        recipe_data["generated_recipe_pdf_path"] = ""
        recipe_data["generated_recipe_pdf_url"] = ""
        pdf_metadata = recipe_data.get("pdf") if isinstance(recipe_data.get("pdf"), dict) else {}
        pdf_metadata.pop(PDF_KIND_GENERATED_RECIPE, None)
        recipe_data["pdf"] = pdf_metadata
        apply_recipe_pdf_asset_aliases(recipe_data)
        log_recipe_pdf_fields("delete_editable_recipe_pdf", recipe_data)
        save_recipe_output(url, recipe_data)

    return {
        "ok": True,
        "url": url,
        "pdf_path": str(pdf_path),
        "pdf_available": False,
        "generated_pdf_path": "",
        "generated_cloudflare_pdf_url": "",
        "generated_cloudflare_pdf_path": "",
    }


def save_editable_recipe(original_url, payload):
    original_url = str(original_url or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    source_url = str(payload.get("source_url") or original_url).strip()

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not source_url:
        source_url = original_url

    previous_recipe_data = load_recipe_ingredients()
    previous_ingredients = recipe_ingredients_for_key(
        normalize_recipe_url_key(original_url),
        previous_recipe_data,
    )
    existing_data = load_recipe_output(original_url) or {"source_url": original_url}
    apply_recipe_pdf_asset_aliases(existing_data)
    log_recipe_pdf_fields("save_editable_recipe:existing", existing_data)
    cover_image = sanitize_recipe_cover_image(
        payload.get("cover_image") or existing_data.get("cover_image"),
        source_url,
        payload.get("recipe_title") or existing_data.get("recipe_title") or "",
    )
    recipe_data = {
        **existing_data,
        "source_url": source_url,
        "recipe_title": str(payload.get("recipe_title") or "").strip(),
        "servings": str(payload.get("servings") or "").strip(),
        "level": str(payload.get("level") or "").strip(),
        "total_time": str(payload.get("total_time") or "").strip(),
        "prep_time": str(payload.get("prep_time") or "").strip(),
        "inactive_time": str(payload.get("inactive_time") or "").strip(),
        "cook_time": str(payload.get("cook_time") or "").strip(),
        "scaling": normalize_recipe_scaling_metadata(
            payload.get("scaling") or existing_data.get("scaling")
        ),
        "ingredients": sanitize_ingredients(payload.get("ingredients", [])),
        "equipment": sanitize_equipment_list(
            payload.get("equipment", []),
            existing_data.get("equipment", []),
        ),
        "instructions": sanitize_instruction_list(
            payload.get("instructions", []),
            existing_data.get("instructions", []),
        ),
        "nutrition": sanitize_nutrition(payload.get("nutrition", [])),
        "rating": normalize_recipe_rating(payload.get("rating")),
        "reflection_notes": sanitize_reflection_notes(
            payload.get("reflection_notes", []),
            existing_data.get("reflection_notes", []),
        ),
        "chatgpt_feedback": str(
            payload.get("chatgpt_feedback")
            or existing_data.get("chatgpt_feedback")
            or ""
        ).strip(),
        "chatgpt_feedback_created_at": str(
            payload.get("chatgpt_feedback_created_at")
            or existing_data.get("chatgpt_feedback_created_at")
            or ""
        ).strip(),
    }
    apply_recipe_pdf_asset_payload(recipe_data, payload)
    hydrate_source_pdf_assets_from_url(recipe_data, source_url)
    apply_recipe_menu_metadata_payload(recipe_data, payload)
    if cover_image:
        recipe_data["cover_image"] = cover_image
    else:
        recipe_data.pop("cover_image", None)
    if recipe_data["servings"] and not recipe_data["scaling"].get("base_servings"):
        recipe_data["scaling"]["base_servings"] = recipe_data["servings"]

    normalize_extracted_ingredient_fields(recipe_data)
    normalize_extracted_equipment_fields(recipe_data)
    log_recipe_pdf_fields("save_editable_recipe:before_write", recipe_data)
    save_recipe_output(source_url, recipe_data)

    if normalize_recipe_url_key(source_url) != normalize_recipe_url_key(original_url):
        replace_recipe_url(original_url, source_url)
        move_recipe_meta(original_url, source_url)

    quantity = normalize_recipe_quantity(payload.get("quantity", 1))
    display_name = str(payload.get("display_name") or "").strip()

    save_recipe_url_quantity(source_url, quantity)
    save_recipe_url_name(source_url, display_name)
    update_recipe_ingredient_record(source_url, quantity, recipe_data)
    update_recipe_quantity(source_url, quantity)
    sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients)

    return load_editable_recipe(source_url)


def save_recipe_cover_image_upload(original_url, uploaded_file, source_url="", fallback_alt=""):
    original_url = str(original_url or "").strip()
    source_url = str(source_url or original_url).strip() or original_url

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not uploaded_file or not uploaded_file.filename:
        return {"ok": False, "error": "No title image was selected."}

    mime_type = str(
        uploaded_file.mimetype
        or mimetypes.guess_type(uploaded_file.filename or "")[0]
        or ""
    ).split(";", 1)[0].strip().lower()
    guessed_mime_type = str(mimetypes.guess_type(uploaded_file.filename or "")[0] or "").lower()
    if not mime_type.startswith("image/") and guessed_mime_type.startswith("image/"):
        mime_type = guessed_mime_type
    extension = recipe_cover_upload_extension(uploaded_file.filename, mime_type)

    if not extension or not mime_type.startswith("image/"):
        return {"ok": False, "error": "Choose a PNG, JPG, WebP, GIF, BMP, or AVIF image."}

    COVER_IMAGE_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    upload_path = COVER_IMAGE_UPLOAD_FOLDER / (
        f"{safe_filename(source_url or original_url)}_title_{uuid.uuid4().hex}{extension}"
    )
    uploaded_file.save(upload_path)

    existing_data = load_recipe_output(original_url) or {"source_url": source_url}
    recipe_source_url = str(existing_data.get("source_url") or source_url or original_url).strip()
    alt = str(fallback_alt or existing_data.get("recipe_title") or "Recipe title image").strip()
    cover_image = extract_recipe_cover_image_from_upload(
        upload_path,
        mime_type,
        uploaded_file.filename,
        recipe_source_url,
        fallback_alt=alt,
    )

    if not cover_image:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "Unable to save this title image."}

    existing_data["source_url"] = recipe_source_url
    existing_data["cover_image"] = cover_image
    save_recipe_output(recipe_source_url, existing_data)

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(recipe_source_url), {})
    quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    update_recipe_ingredient_record(recipe_source_url, quantity, existing_data)

    loaded = load_editable_recipe(recipe_source_url)
    response_recipe = loaded.get("recipe", {})
    response_cover_image = response_recipe.get("cover_image") or editable_recipe_cover_image(
        recipe_source_url,
        existing_data,
        recipe_meta,
    )

    return {
        "ok": True,
        "cover_image": response_cover_image,
        "recipe": response_recipe,
    }


def save_recipe_detail_image_upload(original_url, kind, target, uploaded_file):
    original_url = str(original_url or "").strip()
    image_kind = "equipment" if str(kind or "").strip().lower() == "equipment" else "step"

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not uploaded_file or not uploaded_file.filename:
        return {"ok": False, "error": "No image was selected."}

    mime_type = str(
        uploaded_file.mimetype
        or mimetypes.guess_type(uploaded_file.filename or "")[0]
        or ""
    ).split(";", 1)[0].strip().lower()
    guessed_mime_type = str(mimetypes.guess_type(uploaded_file.filename or "")[0] or "").lower()
    if not mime_type.startswith("image/") and guessed_mime_type.startswith("image/"):
        mime_type = guessed_mime_type

    extension = recipe_cover_upload_extension(uploaded_file.filename, mime_type)
    if not extension or not mime_type.startswith("image/"):
        return {"ok": False, "error": "Choose a PNG, JPG, WebP, GIF, BMP, or AVIF image."}

    recipe_data = load_recipe_output(original_url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_source_url = str(recipe_data.get("source_url") or original_url).strip() or original_url
    recipe_data["source_url"] = recipe_source_url
    generated_at = datetime.now(timezone.utc).isoformat()

    if image_kind == "equipment":
        equipment_items = normalize_equipment_records(recipe_data.get("equipment", []))
        target_index, target_equipment = find_equipment_for_index(equipment_items, target)

        if target_equipment is None:
            return {"ok": False, "error": "Equipment item was not found."}

        image_url = save_uploaded_recipe_detail_image_file(
            recipe_source_url,
            image_kind,
            target_index + 1,
            uploaded_file,
            extension,
        )
        equipment_text = str(
            target_equipment.get("equipment")
            or target_equipment.get("text")
            or target_equipment.get("name")
            or ""
        ).strip()
        target_equipment["equipment_image_url"] = image_url
        target_equipment["equipment_image_generated_at"] = generated_at
        equipment_items[target_index] = {
            **target_equipment,
            "equipment": equipment_text,
            "text": equipment_text,
        }
        recipe_data["equipment"] = equipment_items
        save_recipe_output(recipe_source_url, recipe_data)
        finish_recipe_image_progress(
            "equipment",
            recipe_source_url,
            target_index + 1,
            ok=True,
            image_url=image_url,
            generated_at=generated_at,
        )

        return {
            "ok": True,
            "url": recipe_source_url,
            "kind": "equipment",
            "equipment_index": target_index + 1,
            "equipment_image_url": image_url,
            "equipment_image_generated_at": generated_at,
            "image_url": image_url,
            "generated_at": generated_at,
        }

    instructions = sorted(
        normalize_instruction_records(recipe_data.get("instructions", [])),
        key=lambda item: item["step_number"],
    )
    target_index, target_instruction = find_instruction_for_step(instructions, target)

    if target_instruction is None:
        return {"ok": False, "error": "Instruction step was not found."}

    step_number = target_instruction.get("step_number")
    image_url = save_uploaded_recipe_detail_image_file(
        recipe_source_url,
        image_kind,
        step_number,
        uploaded_file,
        extension,
    )
    instruction_text = str(target_instruction.get("instruction") or target_instruction.get("text") or "").strip()
    target_instruction["step_image_url"] = image_url
    target_instruction["step_image_generated_at"] = generated_at
    instructions[target_index] = {
        **target_instruction,
        "instruction": instruction_text,
        "text": instruction_text,
    }
    recipe_data["instructions"] = instructions
    save_recipe_output(recipe_source_url, recipe_data)
    finish_recipe_image_progress(
        "step",
        recipe_source_url,
        step_number,
        ok=True,
        image_url=image_url,
        generated_at=generated_at,
    )

    return {
        "ok": True,
        "url": recipe_source_url,
        "kind": "step",
        "step_number": step_number,
        "step_image_url": image_url,
        "step_image_generated_at": generated_at,
        "image_url": image_url,
        "generated_at": generated_at,
    }


def recipe_cover_upload_extension(filename, mime_type=""):
    suffix = Path(str(filename or "")).suffix.lower()

    if suffix in COVER_IMAGE_EXTENSIONS:
        return suffix

    normalized_mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime_type in COVER_IMAGE_MIME_EXTENSIONS:
        return COVER_IMAGE_MIME_EXTENSIONS[normalized_mime_type]

    guessed_extension = mimetypes.guess_extension(normalized_mime_type or "")
    guessed_extension = ".jpg" if guessed_extension == ".jpe" else guessed_extension

    if guessed_extension in COVER_IMAGE_EXTENSIONS:
        return guessed_extension

    return ""


def sanitize_recipe_cover_image(value, source_url="", fallback_alt=""):
    cover_image = normalize_recipe_cover_image(
        value,
        base_url=str(source_url or ""),
        fallback_alt=str(fallback_alt or "Recipe title image"),
    )

    if not cover_image:
        return {}

    return cover_image


def category_context_text(value):
    return " ".join(str(value or "").strip().split())


def category_context_ingredients(ingredients):
    rows = []

    for item in ingredients or []:
        if isinstance(item, dict):
            name = category_context_text(
                item.get("ingredient")
                or item.get("name")
                or item.get("display_name")
                or item.get("purchasable_item")
                or item.get("buy_as")
            )
            original = category_context_text(item.get("original_text"))
            preparation = category_context_text(item.get("preparation"))
            section = category_context_text(item.get("section") or item.get("store_section"))
            row = {
                key: value
                for key, value in {
                    "name": name,
                    "original_text": original,
                    "preparation": preparation,
                    "section": section,
                }.items()
                if value
            }
        else:
            name = category_context_text(item)
            row = {"name": name} if name else {}

        if row:
            rows.append(row)

    return rows


def category_context_text_rows(items, *fields):
    rows = []

    for item in items or []:
        if isinstance(item, dict):
            text = ""
            for field in fields:
                text = category_context_text(item.get(field))
                if text:
                    break
        else:
            text = category_context_text(item)

        if text:
            rows.append(text)

    return rows


def recipe_category_prompt_context(payload):
    payload = payload if isinstance(payload, dict) else {}

    return {
        "title": category_context_text(payload.get("recipe_title") or payload.get("display_name")),
        "display_name": category_context_text(payload.get("display_name")),
        "servings": category_context_text(payload.get("servings")),
        "level": category_context_text(payload.get("level")),
        "total_time": category_context_text(payload.get("total_time")),
        "prep_time": category_context_text(payload.get("prep_time")),
        "inactive_time": category_context_text(payload.get("inactive_time")),
        "cook_time": category_context_text(payload.get("cook_time")),
        "ingredients": category_context_ingredients(payload.get("ingredients", [])),
        "equipment": category_context_text_rows(payload.get("equipment", []), "equipment", "text", "name"),
        "instructions": category_context_text_rows(payload.get("instructions", []), "instruction", "text"),
    }


def recipe_category_inference_record(payload):
    context = recipe_category_prompt_context(payload)
    section_items = [
        {"name": item.get("name")}
        for item in context.get("ingredients", [])
        if item.get("name")
    ]

    return {
        "name": context.get("title") or context.get("display_name"),
        "description": "",
        "prep_time": context.get("prep_time"),
        "cook_time": context.get("cook_time"),
        "total_time": context.get("total_time"),
        "equipment_items": context.get("equipment", []),
        "instruction_items": context.get("instructions", []),
        "sections": {"INGREDIENTS": section_items} if section_items else {},
    }


def build_recipe_category_decision_prompt(payload):
    choices = cookbook_category_choices()
    context = recipe_category_prompt_context(payload)

    return f"""
Choose cookbook menu categories for this recipe.

Return only a JSON object with these exact keys:
meal_type, cuisine, main_ingredient, cooking_method, occasion, dietary_preference, prep_time_group, custom_categories.

Rules:
- For meal_type, cuisine, main_ingredient, cooking_method, occasion, dietary_preference, and prep_time_group, choose exactly one label from the allowed options.
- If a field is uncertain, choose the closest useful option instead of leaving it blank.
- custom_categories should be an array of 0 to 3 concise user-friendly cookbook groups.
- Re-analyze the recipe title, ingredients, equipment, times, and instructions.
- Main ingredient must describe the dominant ingredient type. Do not choose Vegan as main_ingredient; put Vegan under dietary_preference when applicable.
- For prep_time_group, use total_time when it is available. Use prep_time only when total_time is blank.
- Do not include markdown or explanatory text.

Allowed options:
{json.dumps(choices, ensure_ascii=False, indent=2)}

Recipe:
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()


def recipe_category_value_has_content(field, value):
    if field == "custom_categories":
        return bool(clean_custom_categories(value))

    return bool(str(value or "").strip())


def recipe_category_effective_decision_values(old_values, suggested_values, mode):
    mode = "all" if mode == "all" else "missing"
    old_values = clean_category_payload(old_values)
    suggested_values = clean_category_payload(suggested_values)
    effective = {
        field: old_values.get(field, [])
        for field in COOKBOOK_CATEGORY_ALL_FIELDS
    }

    for field in COOKBOOK_CATEGORY_ALL_FIELDS:
        if mode == "all" or not recipe_category_value_has_content(field, old_values.get(field)):
            effective[field] = suggested_values.get(field, [] if field == "custom_categories" else "")

    return clean_category_payload(effective)


def recipe_category_changed_fields(old_values, new_values):
    old_values = clean_category_payload(old_values)
    new_values = clean_category_payload(new_values)
    changed = []

    for field in COOKBOOK_CATEGORY_FIELDS:
        if str(old_values.get(field) or "").strip() != str(new_values.get(field) or "").strip():
            changed.append(field)

    if clean_custom_categories(old_values.get("custom_categories")) != clean_custom_categories(new_values.get("custom_categories")):
        changed.append("custom_categories")

    return changed


def recipe_category_payload_id(payload):
    payload = payload if isinstance(payload, dict) else {}
    return (
        category_context_text(payload.get("source_url"))
        or category_context_text(payload.get("url"))
        or category_context_text(payload.get("source_display_url"))
        or category_context_text(payload.get("recipe_title"))
        or category_context_text(payload.get("display_name"))
        or "unknown"
    )


def normalize_chatgpt_category_decision(cleaned, fallback):
    cleaned = clean_category_payload(cleaned)
    fallback = clean_category_payload(fallback)

    for field in COOKBOOK_CATEGORY_FIELDS:
        if not cleaned.get(field):
            cleaned[field] = fallback.get(field, "")

    if "vegan" in str(cleaned.get("main_ingredient") or "").lower():
        replacement = fallback.get("main_ingredient", "")
        if not replacement or "vegan" in replacement.lower():
            replacement = next(
                (choice for choice in cookbook_category_choices().get("main_ingredient", []) if "Vegetarian" in choice),
                "",
            )
        cleaned["main_ingredient"] = replacement

    if fallback.get("prep_time_group"):
        cleaned["prep_time_group"] = fallback["prep_time_group"]

    return cleaned


def log_recipe_category_inference(recipe_id, trigger_source, old_values, new_values, fields_changed):
    payload = {
        "recipe_id": recipe_id,
        "trigger_source": trigger_source,
        "old_values": old_values,
        "new_values": new_values,
        "fields_changed": fields_changed,
    }
    print(f"[recipe_category_inference] {json.dumps(payload, ensure_ascii=False)}")


def decide_recipe_categories_with_chatgpt(
    payload,
    mode="missing",
    current_categories=None,
    trigger_source="recipe_editor",
):
    payload = payload if isinstance(payload, dict) else {}
    mode = "all" if mode == "all" else "missing"
    trigger_source = str(trigger_source or f"recipe_editor:{mode}").strip()

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    prompt = build_recipe_category_decision_prompt(payload)
    model, _model_source = job_model_value_for_env(
        "OPENAI_RECIPE_CATEGORY_MODEL",
        os.getenv("OPENAI_RECIPE_CATEGORY_MODEL", MODEL),
        "env:OPENAI_RECIPE_CATEGORY_MODEL" if os.getenv("OPENAI_RECIPE_CATEGORY_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
    )
    include_temperature = supports_custom_temperature(model)

    try:
        print(
            f"[OpenAI] action=recipe-category-decision model={model} "
            f"temperature_included={include_temperature}"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You classify recipes into cookbook menu categories and return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if include_temperature:
            request_payload["temperature"] = 0
        response = throttled_chat_completion(
            get_openai_client(),
            request_payload,
            action_name="recipe-category-decision",
            model=model,
        )
        record_openai_usage(
            response,
            "recipe-category-decision",
            model=model,
        )
        content = response.choices[0].message.content
        data = json.loads(clean_json_response(content))
    except Exception as exc:
        log_recipe_edit_openai_exception(
            "recipe-category-decision",
            model,
            exc,
            "RECIPE_CATEGORY_DECISION_FAILED",
        )
        return {
            "ok": False,
            "error": f"Recipe category decision failed: {exc}",
        }

    categories = data.get("categories") if isinstance(data, dict) and isinstance(data.get("categories"), dict) else data

    if not isinstance(categories, dict):
        return {
            "ok": False,
            "error": "Recipe category decision returned an unexpected response.",
        }

    cleaned = clean_category_payload(categories)
    fallback = infer_recipe_categories(recipe_category_inference_record(payload))
    cleaned = normalize_chatgpt_category_decision(cleaned, fallback)
    old_values = clean_category_payload(current_categories or {})
    effective_values = recipe_category_effective_decision_values(old_values, cleaned, mode)
    fields_changed = recipe_category_changed_fields(old_values, effective_values)

    log_recipe_category_inference(
        recipe_category_payload_id(payload),
        trigger_source,
        old_values,
        effective_values,
        fields_changed,
    )

    return {
        "ok": True,
        "categories": cleaned,
    }


def estimate_recipe_nutrition(payload):
    payload = payload if isinstance(payload, dict) else {}

    if not payload.get("ingredients"):
        return {
            "ok": False,
            "error": "Add at least one ingredient before estimating nutrition.",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    serving_basis = recipe_nutrition_serving_basis(payload.get("nutrition"))
    prompt = build_nutrition_estimate_prompt(payload, serving_basis)
    model, _model_source = job_model_value_for_env(
        "OPENAI_NUTRITION_MODEL",
        os.getenv("OPENAI_NUTRITION_MODEL", MODEL),
        "env:OPENAI_NUTRITION_MODEL" if os.getenv("OPENAI_NUTRITION_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
    )
    include_temperature = supports_custom_temperature(model)

    try:
        print(
            f"[OpenAI] action=nutrition-estimate model={model} "
            f"temperature_included={include_temperature}"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You estimate recipe nutrition and return only valid JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if include_temperature:
            request_payload["temperature"] = 0
        response = throttled_chat_completion(
            get_openai_client(),
            request_payload,
            action_name="nutrition-estimate",
            model=model,
        )
        record_openai_usage(
            response,
            "nutrition-estimate",
            model=model,
        )
        content = response.choices[0].message.content
        data = json.loads(clean_json_response(content))
    except Exception as exc:
        log_recipe_edit_openai_exception(
            "nutrition-estimate",
            model,
            exc,
            "NUTRITION_ESTIMATE_FAILED",
        )
        return {
            "ok": False,
            "error": f"Nutrition estimate failed: {exc}",
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "Nutrition estimate returned an unexpected response.",
        }

    nutrition = data.get("nutrition") if isinstance(data.get("nutrition"), dict) else data

    rows = [{"key": "serving_basis", "value": serving_basis}]
    for key in NUTRITION_ESTIMATE_FIELDS:
        value = normalize_estimated_nutrition_value(key, nutrition.get(key))
        rows.append({"key": key, "value": value})

    return {
        "ok": True,
        "nutrition": rows,
    }


def recipe_note_feedback(payload):
    payload = payload if isinstance(payload, dict) else {}
    note_text = str(payload.get("note") or payload.get("text") or "").strip()

    if not note_text:
        return {
            "ok": False,
            "error": "Add a recipe note before asking ChatGPT for feedback.",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "error": "Missing OPENAI_API_KEY environment variable.",
        }

    prompt = build_recipe_note_feedback_prompt(payload, note_text)
    model, _model_source = job_model_value_for_env(
        "OPENAI_RECIPE_NOTE_MODEL",
        os.getenv("OPENAI_RECIPE_NOTE_MODEL", MODEL),
        "env:OPENAI_RECIPE_NOTE_MODEL" if os.getenv("OPENAI_RECIPE_NOTE_MODEL") else "fallback:OPENAI_RECIPE_MODEL",
    )
    include_temperature = supports_custom_temperature(model)

    try:
        print(
            f"[OpenAI] action=recipe-note-feedback model={model} "
            f"temperature_included={include_temperature}"
        )
        request_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a practical cooking coach. Give concise, useful feedback on recipe reflection notes.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        }
        if include_temperature:
            request_payload["temperature"] = 0.2
        response = throttled_chat_completion(
            get_openai_client(),
            request_payload,
            action_name="recipe-note-feedback",
            model=model,
        )
        record_openai_usage(
            response,
            "recipe-note-feedback",
            model=model,
        )
        feedback = str(response.choices[0].message.content or "").strip()
    except Exception as exc:
        log_recipe_edit_openai_exception(
            "recipe-note-feedback",
            model,
            exc,
            "RECIPE_NOTE_FEEDBACK_FAILED",
        )
        return {
            "ok": False,
            "error": f"Recipe note feedback failed: {exc}",
        }

    if not feedback:
        return {
            "ok": False,
            "error": "ChatGPT did not return feedback for this note.",
        }

    return {
        "ok": True,
        "feedback": feedback,
        "created_at": now_iso(),
    }


def build_recipe_note_feedback_prompt(payload, note_text):
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else payload
    recipe_payload = {
        "title": str(recipe.get("recipe_title") or recipe.get("display_name") or "").strip(),
        "rating": normalize_recipe_rating(recipe.get("rating")),
        "servings": str(recipe.get("servings") or "").strip(),
        "total_time": str(recipe.get("total_time") or "").strip(),
        "prep_time": str(recipe.get("prep_time") or "").strip(),
        "cook_time": str(recipe.get("cook_time") or "").strip(),
        "ingredients": nutrition_prompt_ingredients(recipe.get("ingredients", [])),
        "instructions": nutrition_prompt_instructions(recipe.get("instructions", [])),
    }

    return f"""
Review this cook's reflection note and give useful feedback.

Rules:
- Be concise: 3-5 bullets max.
- Focus on practical cooking adjustments, timing, flavor, texture, and what to try next time.
- Use the recipe context, but do not invent facts the note does not support.
- If the note is mostly positive, suggest one small experiment for next time.

Recipe context:
{json.dumps(recipe_payload, ensure_ascii=False, indent=2)}

Reflection note:
{note_text}
"""


def generate_recipe_step_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_step = payload.get("step_number")

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"ok": False, "error": "Image generation is not set up yet."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_title = str(recipe_data.get("recipe_title") or "").strip()
    if not recipe_title:
        return {"ok": False, "error": "Add a recipe title before generating a step image."}

    instructions = sorted(
        normalize_instruction_records(recipe_data.get("instructions", [])),
        key=lambda item: item["step_number"],
    )
    target_index, target_instruction = find_instruction_for_step(instructions, requested_step)

    if target_instruction is None:
        return {"ok": False, "error": "Instruction step was not found."}

    instruction_text = str(target_instruction.get("instruction") or target_instruction.get("text") or "").strip()
    if not instruction_text:
        return {"ok": False, "error": "Add instruction text before generating a step image."}

    prompt = build_recipe_step_image_prompt(
        recipe_title=recipe_title,
        servings=str(recipe_data.get("servings") or "").strip(),
        ingredients=recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", [])),
        equipment=recipe_step_image_prompt_equipment(recipe_data.get("equipment", [])),
        step_number=target_instruction.get("step_number"),
        instruction_step=instruction_text,
    )

    progress_target = target_instruction.get("step_number")
    start_recipe_image_progress("step", url, progress_target, "Generating step image...")

    try:
        image_bytes = request_recipe_step_image_bytes(prompt)
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    step_image_url = save_recipe_step_image_file(url, target_instruction.get("step_number"), image_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()
    target_instruction["step_image_url"] = step_image_url
    target_instruction["step_image_generated_at"] = generated_at

    instructions[target_index] = {
        **target_instruction,
        "instruction": instruction_text,
        "text": instruction_text,
    }
    recipe_data["instructions"] = instructions
    save_recipe_output(url, recipe_data)
    finish_recipe_image_progress(
        "step",
        url,
        progress_target,
        ok=True,
        image_url=step_image_url,
        generated_at=generated_at,
    )

    return {
        "ok": True,
        "url": url,
        "step_number": target_instruction.get("step_number"),
        "step_image_url": step_image_url,
        "step_image_generated_at": generated_at,
    }


def generate_recipe_equipment_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_index = payload.get("equipment_index") or payload.get("equipment_number")

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"ok": False, "error": "Image generation is not set up yet."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_title = str(recipe_data.get("recipe_title") or "").strip()
    if not recipe_title:
        return {"ok": False, "error": "Add a recipe title before generating an equipment image."}

    equipment_items = normalize_equipment_records(recipe_data.get("equipment", []))
    target_index, target_equipment = find_equipment_for_index(equipment_items, requested_index)

    if target_equipment is None:
        return {"ok": False, "error": "Equipment item was not found."}

    equipment_text = str(
        target_equipment.get("equipment")
        or target_equipment.get("text")
        or target_equipment.get("name")
        or ""
    ).strip()
    if not equipment_text:
        return {"ok": False, "error": "Add equipment text before generating an image."}

    prompt = build_recipe_equipment_image_prompt(
        recipe_title=recipe_title,
        servings=str(recipe_data.get("servings") or "").strip(),
        ingredients=recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", [])),
        equipment_item_number=target_index + 1,
        equipment_item=equipment_text,
    )

    progress_target = target_index + 1
    start_recipe_image_progress("equipment", url, progress_target, "Generating equipment image...")

    try:
        image_bytes = request_recipe_step_image_bytes(prompt)
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error)
        return {
            "ok": False,
            "error": error,
        }

    equipment_image_url = save_recipe_equipment_image_file(url, target_index + 1, image_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()
    target_equipment["equipment_image_url"] = equipment_image_url
    target_equipment["equipment_image_generated_at"] = generated_at

    equipment_items[target_index] = {
        **target_equipment,
        "equipment": equipment_text,
        "text": equipment_text,
    }
    recipe_data["equipment"] = equipment_items
    save_recipe_output(url, recipe_data)
    finish_recipe_image_progress(
        "equipment",
        url,
        progress_target,
        ok=True,
        image_url=equipment_image_url,
        generated_at=generated_at,
    )

    return {
        "ok": True,
        "url": url,
        "equipment_index": target_index + 1,
        "equipment_image_url": equipment_image_url,
        "equipment_image_generated_at": generated_at,
    }


def find_equipment_for_index(equipment_items, requested_index):
    try:
        index = int(float(requested_index)) - 1
    except (TypeError, ValueError):
        index = -1

    if 0 <= index < len(equipment_items):
        return index, equipment_items[index]

    return -1, None


def find_instruction_for_step(instructions, requested_step):
    requested_key = instruction_match_step_key(requested_step)

    for index, instruction in enumerate(instructions):
        if instruction_match_step_key(instruction.get("step_number")) == requested_key:
            return index, instruction

    try:
        requested_index = int(float(requested_step)) - 1
    except (TypeError, ValueError):
        requested_index = -1

    if 0 <= requested_index < len(instructions):
        return requested_index, instructions[requested_index]

    return -1, None


def build_recipe_step_image_prompt(
    recipe_title,
    servings,
    ingredients,
    equipment,
    step_number,
    instruction_step,
):
    return f"""Generate a realistic cookbook-style image for one recipe instruction step.

Recipe title:
{recipe_title}

Servings:
{servings or "Not specified"}

Ingredients:
{ingredients or "Not specified"}

Equipment:
{equipment or "Not specified"}

Step number:
{step_number}

Instruction step:
{instruction_step}

Visual requirements:
- Show only this specific cooking step
- Use the actual ingredients from the recipe
- Bright natural kitchen lighting
- Realistic food photography
- Clean kitchen counter background
- High-end cookbook style
- No text inside the image
- No numbered badges
- No labels
- Make the cooking action visually clear
- Final step should show the finished dish if the instruction is about serving or garnish
"""


def build_recipe_equipment_image_prompt(
    recipe_title,
    servings,
    ingredients,
    equipment_item_number,
    equipment_item,
):
    return f"""Generate a realistic cookbook-style image for one recipe equipment item.

Recipe title:
{recipe_title}

Servings:
{servings or "Not specified"}

Ingredients:
{ingredients or "Not specified"}

Equipment item number:
{equipment_item_number}

Equipment item:
{equipment_item}

Visual requirements:
- Show only this specific equipment item
- Make the equipment visually clear and easy to identify
- It should look ready to use for this recipe
- Include actual recipe ingredients nearby only if they help communicate scale or use
- Bright natural kitchen lighting
- Realistic food photography
- Clean kitchen counter background
- High-end cookbook style
- No text inside the image
- No numbered badges
- No labels
"""


def recipe_step_image_prompt_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return ""

    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            text = str(item or "").strip()
            if text:
                rows.append(f"- {text}")
            continue

        name = str(item.get("ingredient") or item.get("original_text") or "").strip()
        quantity = str(item.get("quantity") or item.get("recipe_qty") or "").strip()
        unit = str(item.get("unit") or "").strip()
        preparation = str(item.get("preparation") or "").strip()
        text = " ".join(part for part in [quantity, unit, name] if part).strip()
        if preparation:
            text = f"{text}, {preparation}" if text else preparation

        if text:
            rows.append(f"- {text}")

    return "\n".join(rows[:80])


def recipe_step_image_prompt_equipment(equipment):
    rows = normalize_text_rows(equipment)
    return "\n".join(f"- {item}" for item in rows[:40])


def request_recipe_step_image_bytes(prompt):
    timeout_seconds = int(os.getenv("OPENAI_STEP_IMAGE_TIMEOUT_SECONDS", "90"))
    model = os.getenv("OPENAI_STEP_IMAGE_MODEL", "gpt-image-1")
    size = os.getenv("OPENAI_STEP_IMAGE_SIZE", "1024x1024")
    quality = os.getenv("OPENAI_STEP_IMAGE_QUALITY", "medium")

    client = get_openai_client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_seconds)

    try:
        print(
            f"[OpenAI] action=recipe-step-image model={model} "
            "temperature_included=False"
        )
        response = throttled_image_generation(
            client,
            {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "n": 1,
            },
            action_name="recipe-step-image",
            model=model,
        )
        record_openai_usage(
            response,
            "recipe-step-image",
            model=model,
            metadata={"size": size, "quality": quality},
        )
    except Exception as exc:
        is_timeout = "timeout" in str(exc).lower() or "timed out" in str(exc).lower()
        log_recipe_edit_openai_exception(
            "recipe-step-image",
            model,
            exc,
            "OPENAI_TIMEOUT" if is_timeout else "RECIPE_STEP_IMAGE_FAILED",
        )
        if is_timeout:
            raise TimeoutError() from exc
        raise

    image_record = first_openai_image_record(response)
    if not image_record:
        return b""

    b64_json = openai_image_field(image_record, "b64_json")
    if b64_json:
        encoded = str(b64_json).split(",", 1)[-1]
        return base64.b64decode(encoded)

    image_url = openai_image_field(image_record, "url")
    if image_url:
        try:
            result = requests.get(image_url, timeout=timeout_seconds)
            result.raise_for_status()
        except requests.Timeout as exc:
            raise TimeoutError() from exc
        return result.content

    return b""


def first_openai_image_record(response):
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")

    if not data:
        return None

    return data[0]


def openai_image_field(image_record, field_name):
    if isinstance(image_record, dict):
        return image_record.get(field_name)

    return getattr(image_record, field_name, None)


def save_recipe_step_image_file(recipe_url, step_number, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    step_key = safe_filename(str(step_number or "step"))
    filename = f"{safe_filename(recipe_url)}_step_{step_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    ensure_webp_variants(image_path)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}"


def save_recipe_equipment_image_file(recipe_url, equipment_index, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    equipment_key = safe_filename(str(equipment_index or "equipment"))
    filename = f"{safe_filename(recipe_url)}_equipment_{equipment_key}_{uuid.uuid4().hex[:12]}.png"
    image_path = STEP_IMAGE_FOLDER / filename
    image_path.write_bytes(image_bytes)
    ensure_webp_variants(image_path)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}"


def save_uploaded_recipe_detail_image_file(recipe_url, image_kind, target, uploaded_file, extension):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    kind_key = safe_filename(str(image_kind or "recipe"))
    target_key = safe_filename(str(target or "image"))
    filename = f"{safe_filename(recipe_url)}_{kind_key}_{target_key}_{uuid.uuid4().hex[:12]}{extension}"
    image_path = STEP_IMAGE_FOLDER / filename
    uploaded_file.save(image_path)
    ensure_webp_variants(image_path)
    return f"{STEP_IMAGE_URL_PREFIX}/{filename}"


def recipe_nutrition_serving_basis(nutrition_rows):
    if isinstance(nutrition_rows, dict):
        return str(nutrition_rows.get("serving_basis") or "per serving").strip() or "per serving"

    if isinstance(nutrition_rows, list):
        for row in nutrition_rows:
            if not isinstance(row, dict):
                continue

            key = str(row.get("key") or row.get("label") or "").strip().lower()
            if key == "serving_basis":
                return str(row.get("value") or "per serving").strip() or "per serving"

    return "per serving"


def build_nutrition_estimate_prompt(recipe, serving_basis):
    recipe_payload = {
        "title": str(recipe.get("recipe_title") or recipe.get("display_name") or "").strip(),
        "servings": str(recipe.get("servings") or "").strip(),
        "serving_basis": serving_basis,
        "ingredients": nutrition_prompt_ingredients(recipe.get("ingredients", [])),
        "equipment": sanitize_text_list(recipe.get("equipment", [])),
        "instructions": nutrition_prompt_instructions(recipe.get("instructions", [])),
    }

    return f"""
Estimate the nutrition values for this recipe.

Return ONLY valid JSON with this exact shape:
{{
  "nutrition": {{
    "calories": "659 kcal",
    "carbohydrates": "57 g",
    "protein": "17 g",
    "fat": "40 g",
    "saturated_fat": "16 g",
    "cholesterol": "37 mg",
    "sodium": "649 mg",
    "fiber": "3 g",
    "sugar": "0.2 g"
  }}
}}

Rules:
- Estimate values for the serving basis: {serving_basis}.
- Use the recipe servings to divide the full recipe when servings are available.
- Use the provided ingredient quantities, units, and preparation details.
- Use common USDA-style approximations when exact brands are unknown.
- Do not invent extra ingredients.
- Return strings with units.
- calories must use kcal.
- carbohydrates, protein, fat, saturated_fat, fiber, and sugar must use g.
- cholesterol and sodium must use mg.
- If a value cannot be estimated, use an empty string.

Recipe JSON:
{json.dumps(recipe_payload, ensure_ascii=False, indent=2)}
"""


def nutrition_prompt_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            continue

        rows.append({
            "ingredient": str(item.get("ingredient") or "").strip(),
            "quantity": str(item.get("quantity") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "preparation": str(item.get("preparation") or "").strip(),
            "original_text": str(item.get("original_text") or "").strip(),
        })

    return [
        row
        for row in rows
        if row["ingredient"] or row["original_text"]
    ]


def nutrition_prompt_instructions(instructions):
    if not isinstance(instructions, list):
        return []

    rows = []
    for item in instructions:
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_estimated_nutrition_value(key, value):
    if value is None:
        return ""

    if isinstance(value, dict):
        amount = str(value.get("amount") or value.get("value") or "").strip()
        unit = str(value.get("unit") or "").strip()
        return f"{amount} {unit}".strip()

    if isinstance(value, (int, float)):
        if key == "calories":
            return f"{value:g} kcal"

        if key in {"cholesterol", "sodium"}:
            return f"{value:g} mg"

        return f"{value:g} g"

    return str(value or "").strip()


def sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients):
    ingredients = extract_ingredients_from_result(recipe_data)

    if ingredients:
        add_items(ingredients)

    remove_unused_ingredients_from_shopping_list(
        previous_ingredients,
        load_recipe_ingredients(),
    )
    sort_ingredients()


def _read_recipe_output_json(json_path):
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_recipe_output_index():
    index = {}

    for json_path in OUTPUT_FOLDER.glob("*.json"):
        if json_path.name == "sorted_ingredients.json":
            continue

        data = _read_recipe_output_json(json_path)
        if not isinstance(data, dict):
            continue

        recipe_key = normalize_recipe_url_key(data.get("source_url", ""))
        if recipe_key:
            index[recipe_key] = data

    return index


def recipe_output_index():
    if has_request_context():
        cached = getattr(g, "_recipe_edit_output_index", None)
        if cached is None:
            cached = build_recipe_output_index()
            g._recipe_edit_output_index = cached
        return cached

    return build_recipe_output_index()


def load_recipe_output(url):
    recipe_key = normalize_recipe_url_key(url)
    direct_path = OUTPUT_FOLDER / f"{safe_filename(url)}.json"

    if direct_path.exists():
        data = _read_recipe_output_json(direct_path)
        if isinstance(data, dict):
            source_key = normalize_recipe_url_key(data.get("source_url", ""))
            if not source_key or source_key == recipe_key:
                return data

    return recipe_output_index().get(recipe_key)


def save_recipe_output(url, recipe_data):
    json_path = OUTPUT_FOLDER / f"{safe_filename(url)}.json"
    json_path.write_text(
        json.dumps(recipe_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if has_request_context():
        cached = getattr(g, "_recipe_edit_output_index", None)
        if isinstance(cached, dict):
            recipe_key = normalize_recipe_url_key(
                recipe_data.get("source_url", "") if isinstance(recipe_data, dict) else ""
            ) or normalize_recipe_url_key(url)
            if recipe_key:
                cached[recipe_key] = recipe_data
    return json_path


def replace_recipe_url(original_url, source_url):
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)
    next_urls = []
    replaced = False

    for url in load_recipe_urls():
        if normalize_recipe_url_key(url) == original_key:
            if not any(normalize_recipe_url_key(item) == source_key for item in next_urls):
                next_urls.append(source_url)
            replaced = True
        else:
            next_urls.append(url)

    if not replaced:
        next_urls.append(source_url)

    save_recipe_urls(next_urls)


def move_recipe_meta(original_url, source_url):
    data = load_recipe_ingredients()
    original_key = normalize_recipe_url_key(original_url)
    source_key = normalize_recipe_url_key(source_url)

    if original_key == source_key or original_key not in data:
        return

    existing = data.pop(original_key)
    destination = data.get(source_key, {})
    destination.update(existing)
    destination["url"] = source_url
    data[source_key] = destination
    save_recipe_ingredients(data)


def update_recipe_ingredient_record(url, quantity, recipe_data):
    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    existing = data.get(key, {})
    cover_image = recipe_data.get("cover_image") or existing.get("cover_image")
    record = {
        "url": url,
        "quantity": quantity,
        "name": existing.get("name") or recipe_data.get("display_name") or recipe_data.get("recipe_title"),
        "servings": recipe_data.get("servings") or existing.get("servings"),
        "level": recipe_data.get("level") or existing.get("level"),
        "total_time": recipe_data.get("total_time") or existing.get("total_time"),
        "prep_time": recipe_data.get("prep_time") or existing.get("prep_time"),
        "inactive_time": recipe_data.get("inactive_time") or existing.get("inactive_time"),
        "cook_time": recipe_data.get("cook_time") or existing.get("cook_time"),
        "base_servings": recipe_data.get("servings") or existing.get("base_servings"),
        "scaled_servings": existing.get("scaled_servings"),
        "scaled_ingredients": existing.get("scaled_ingredients", {}),
        "ingredients": extract_ingredients_from_result(recipe_data),
    }

    if cover_image:
        record["cover_image"] = cover_image

    data[key] = record
    save_recipe_ingredients(data)


def normalize_edit_ingredients(ingredients):
    if not isinstance(ingredients, list):
        return []

    rows = [
        apply_purchase_mapping_to_ingredient({
            "section": item.get("section") or "",
            "original_text": item.get("original_text") or "",
            "quantity": item.get("quantity") or "",
            "recipe_qty": item.get("recipe_qty") or item.get("quantity") or "",
            "unit": item.get("unit") or "",
            "base_quantity": item.get("base_quantity") or item.get("quantity") or "",
            "base_unit": item.get("base_unit") or item.get("unit") or "",
            "ingredient": item.get("ingredient") or "",
            "preparation": item.get("preparation") or "",
            "optional": bool(item.get("optional")),
            "store_section": item.get("store_section") or classify_store_section(item.get("ingredient") or ""),
            "purchasable_item": item.get("purchasable_item") or item.get("buy_as") or "",
            "purchase_group": item.get("purchase_group") or "",
        })
        for item in ingredients
        if isinstance(item, dict)
    ]
    return rows


def normalize_text_rows(value):
    if isinstance(value, str):
        return [value] if value.strip() else []

    if not isinstance(value, list):
        return []

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("name") or item.get("text") or item.get("equipment") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def normalize_equipment_records(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_rows(value)

    records = []
    for index, item in enumerate(value, start=1):
        record = dict(item) if isinstance(item, dict) else {}
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
            equipment_image_url = str(item.get("equipment_image_url") or item.get("image_url") or "").strip()
            equipment_image_generated_at = str(
                item.get("equipment_image_generated_at") or item.get("image_generated_at") or ""
            ).strip()
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""

        if not text:
            continue

        record.update({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
        })
        records.append(record)

    return records


def normalize_instruction_rows(value):
    return sorted(
        normalize_instruction_records(value),
        key=lambda item: item["step_number"],
    )


def normalize_nutrition_rows(nutrition, include_defaults=False):
    if not isinstance(nutrition, dict):
        return []

    rows = []
    included = set()

    if include_defaults:
        for key in DEFAULT_MANUAL_NUTRITION_FIELDS:
            fallback = "per serving" if key == "serving_basis" else ""
            rows.append({"key": key, "value": str(nutrition.get(key) or fallback)})
            included.add(key)

    for key in NUTRITION_FIELDS:
        if key in included or not nutrition.get(key):
            continue

        rows.append({"key": key, "value": str(nutrition.get(key) or "")})
        included.add(key)

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                key = str(item.get("label") or item.get("name") or "").strip()
                value = str(item.get("value") or item.get("amount") or "").strip()
                if key or value:
                    rows.append({"key": key, "value": value})

    return rows


def sanitize_ingredients(value):
    if not isinstance(value, list):
        return []

    ingredients = []
    for item in value:
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient") or "").strip()
        original_text = str(item.get("original_text") or "").strip()

        if not name and not original_text:
            continue

        store_section = classify_store_section(name or original_text)
        base_quantity = nullable_string(item.get("base_quantity"))
        base_unit = nullable_string(item.get("base_unit"))

        row = {
            "section": nullable_string(item.get("section")),
            "original_text": original_text,
            "quantity": nullable_string(item.get("quantity")),
            "recipe_qty": nullable_string(item.get("recipe_qty") or item.get("quantity")),
            "unit": nullable_string(item.get("unit")),
            "base_quantity": base_quantity or nullable_string(item.get("quantity")),
            "base_unit": base_unit or nullable_string(item.get("unit")),
            "ingredient": name or original_text,
            "preparation": nullable_string(item.get("preparation")),
            "optional": bool(item.get("optional")),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER.get(store_section, STORE_SECTION_ORDER["MISC"]),
            "purchasable_item": nullable_string(item.get("purchasable_item") or item.get("buy_as")),
            "purchase_group": nullable_string(item.get("purchase_group")),
        }
        ingredients.append(apply_purchase_mapping_to_ingredient(row))

    return ingredients


def sanitize_text_list(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    rows = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
        else:
            text = str(item or "").strip()

        if text:
            rows.append(text)

    return rows


def sanitize_equipment_list(value, existing_value=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    existing_rows = normalize_equipment_records(existing_value or [])
    existing_by_text = {
        instruction_match_text_key(item.get("equipment") or item.get("text")): item
        for item in existing_rows
        if instruction_match_text_key(item.get("equipment") or item.get("text"))
    }
    equipment = []

    for index, item in enumerate(value):
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
            equipment_image_url = nullable_string(item.get("equipment_image_url") or item.get("image_url"))
            equipment_image_generated_at = nullable_string(
                item.get("equipment_image_generated_at") or item.get("image_generated_at")
            )
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""

        if not text:
            continue

        existing = existing_by_text.get(instruction_match_text_key(text))
        if existing is None and index < len(existing_rows):
            existing = existing_rows[index]
        existing = existing or {}
        equipment_image_url = equipment_image_url or nullable_string(existing.get("equipment_image_url")) or ""
        equipment_image_generated_at = (
            equipment_image_generated_at
            or nullable_string(existing.get("equipment_image_generated_at"))
            or ""
        )

        equipment.append({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
        })

    return equipment


def sanitize_instruction_list(value, existing_value=None):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        return []

    existing_rows = normalize_instruction_records(existing_value or [])
    existing_by_step = {
        instruction_match_step_key(item.get("step_number")): item
        for item in existing_rows
    }
    existing_by_text = {
        instruction_match_text_key(item.get("instruction")): item
        for item in existing_rows
        if instruction_match_text_key(item.get("instruction"))
    }
    instructions = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
            step_image_url = nullable_string(item.get("step_image_url") or item.get("image_url"))
            step_image_generated_at = nullable_string(
                item.get("step_image_generated_at") or item.get("image_generated_at")
            )
        else:
            text = str(item or "").strip()
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if not text:
            continue

        existing = (
            existing_by_step.get(instruction_match_step_key(step_number))
            or existing_by_text.get(instruction_match_text_key(text))
            or {}
        )
        step_image_url = step_image_url or nullable_string(existing.get("step_image_url")) or ""
        step_image_generated_at = (
            step_image_generated_at
            or nullable_string(existing.get("step_image_generated_at"))
            or ""
        )

        instructions.append({
            "section": None,
            "step_number": step_number,
            "instruction": text,
            "text": text,
            "temperature": None,
            "time": None,
            "equipment_used": [],
            "step_image_url": step_image_url,
            "step_image_generated_at": step_image_generated_at,
        })

    return sorted(instructions, key=lambda item: item["step_number"])


def normalize_instruction_records(value):
    if isinstance(value, str):
        value = value.splitlines()

    if not isinstance(value, list):
        value = normalize_text_rows(value)

    records = []
    for index, item in enumerate(value, start=1):
        record = dict(item) if isinstance(item, dict) else {}
        if isinstance(item, dict):
            text = str(item.get("instruction") or item.get("text") or "").strip()
            step_number = normalize_step_number(item.get("step_number"), index)
            step_image_url = str(item.get("step_image_url") or item.get("image_url") or "").strip()
            step_image_generated_at = str(
                item.get("step_image_generated_at") or item.get("image_generated_at") or ""
            ).strip()
        else:
            text = str(item or "").strip()
            step_number = index
            step_image_url = ""
            step_image_generated_at = ""

        if not text:
            continue

        record.update({
            "step_number": step_number,
            "instruction": text,
            "text": text,
            "step_image_url": step_image_url,
            "step_image_generated_at": step_image_generated_at,
        })
        records.append(record)

    return records


def instruction_match_step_key(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()

    if number.is_integer():
        return str(int(number))

    return f"{number:g}"


def instruction_match_text_key(value):
    return " ".join(str(value or "").strip().lower().split())


def normalize_step_number(value, fallback):
    try:
        step_number = float(value)
    except (TypeError, ValueError):
        return fallback

    if step_number <= 0:
        return fallback

    if step_number.is_integer():
        return int(step_number)

    return step_number


def sanitize_nutrition(value):
    if not isinstance(value, list):
        return {}

    nutrition = {}
    other = []

    for item in value:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key") or "").strip()
        value_text = str(item.get("value") or "").strip()

        if not key or not value_text:
            continue

        normalized_key = key.lower().replace(" ", "_").replace("-", "_")
        if normalized_key in NUTRITION_FIELDS:
            nutrition[normalized_key] = value_text
        else:
            other.append({"label": key, "value": value_text})

    if other:
        nutrition["other"] = other

    return nutrition


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_recipe_rating(value):
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, min(5, rating))


def normalize_reflection_notes(value):
    if isinstance(value, str):
        value = [{"text": value}] if value.strip() else []

    if not isinstance(value, list):
        return []

    notes = []
    for item in value:
        if not isinstance(item, dict):
            item = {"text": item}

        text = str(item.get("text") or item.get("note") or "").strip()
        if not text:
            continue

        notes.append({
            "note_id": str(item.get("note_id") or item.get("id") or uuid.uuid4().hex).strip(),
            "text": text,
            "created_at": str(item.get("created_at") or item.get("timestamp") or now_iso()).strip(),
            "chatgpt_feedback": str(item.get("chatgpt_feedback") or "").strip(),
            "chatgpt_feedback_created_at": str(item.get("chatgpt_feedback_created_at") or "").strip(),
        })

    return notes


def sanitize_reflection_notes(value, existing_value=None):
    existing_notes = {
        str(item.get("note_id") or ""): item
        for item in normalize_reflection_notes(existing_value)
        if item.get("note_id")
    }
    sanitized = []

    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            item = {"text": item}

        text = str(item.get("text") or item.get("note") or "").strip()
        if not text:
            continue

        note_id = str(item.get("note_id") or item.get("id") or "").strip()
        existing = existing_notes.get(note_id, {}) if note_id else {}
        sanitized.append({
            "note_id": note_id or uuid.uuid4().hex,
            "text": text,
            "created_at": str(item.get("created_at") or existing.get("created_at") or now_iso()).strip(),
            "chatgpt_feedback": str(
                item.get("chatgpt_feedback")
                or existing.get("chatgpt_feedback")
                or ""
            ).strip(),
            "chatgpt_feedback_created_at": str(
                item.get("chatgpt_feedback_created_at")
                or existing.get("chatgpt_feedback_created_at")
                or ""
            ).strip(),
        })

    return sanitized


def nullable_string(value):
    text = str(value or "").strip()
    return text or None
