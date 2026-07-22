import base64
from copy import deepcopy
import json
import logging
import math
import mimetypes
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import parse_qsl
from time import perf_counter
from time import sleep
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
from PushShoppingList.services.ingredient_unit_service import normalize_ingredient_unit_fields
from PushShoppingList.services.ingredient_unit_service import normalize_recipe_unit_fields
from PushShoppingList.services.image_variant_service import IMAGE_VARIANTS
from PushShoppingList.services.image_variant_service import cover_image_variant_payload
from PushShoppingList.services.image_variant_service import ensure_webp_variants
from PushShoppingList.services.image_variant_service import webp_variant_path
from PushShoppingList.services.recipe_extract_service import MODEL
from PushShoppingList.services.recipe_extract_service import OUTPUT_FOLDER
from PushShoppingList.services.recipe_extract_service import RAW_FOLDER
from PushShoppingList.services.recipe_extract_service import supports_custom_temperature
from PushShoppingList.services.recipe_extract_service import UPLOAD_FOLDER
from PushShoppingList.services.recipe_extract_service import build_video_text_pdf_html
from PushShoppingList.services.recipe_extract_service import clean_json_response
from PushShoppingList.services.recipe_extract_service import extract_recipe_cover_image_from_upload
from PushShoppingList.services.recipe_extract_service import extract_recipe_info_from_text
from PushShoppingList.services.recipe_extract_service import extract_ingredients_from_result
from PushShoppingList.services.recipe_extract_service import fetch_recipe_page
from PushShoppingList.services.recipe_extract_service import flatten_ingredient_substitution_alternatives
from PushShoppingList.services.recipe_extract_service import generated_recipe_pdf_path
from PushShoppingList.services.recipe_extract_service import get_openai_client
from PushShoppingList.services.recipe_extract_service import get_openai_error_code_and_param
from PushShoppingList.services.recipe_extract_service import apply_recipe_note_substitutions_to_ingredients
from PushShoppingList.services.recipe_extract_service import normalize_recipe_cover_image
from PushShoppingList.services.recipe_extract_service import normalize_extracted_equipment_fields
from PushShoppingList.services.recipe_extract_service import normalize_extracted_ingredient_fields
from PushShoppingList.services.recipe_extract_service import normalize_ingredient_substitutions as normalize_ingredient_substitution_options
from PushShoppingList.services.recipe_extract_service import normalize_recipe_note_sections
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
from PushShoppingList.services.recipe_ingredient_service import ingredient_detail_records
from PushShoppingList.services.recipe_ingredient_service import recipe_ingredients_for_key
from PushShoppingList.services.recipe_ingredient_service import remove_unused_ingredients_from_shopping_list
from PushShoppingList.services.recipe_ingredient_service import save_recipe_ingredients
from PushShoppingList.services.recipe_master_data_service import clean_ingredient_store_section
from PushShoppingList.services.recipe_master_data_service import classify_ingredient_store_section_result
from PushShoppingList.services.recipe_master_data_service import classify_ingredient_store_section
from PushShoppingList.services.recipe_master_data_service import clean_ingredient_store_section_source
from PushShoppingList.services.recipe_master_data_service import ingredient_store_section_confidence
from PushShoppingList.services.recipe_master_data_service import INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION
from PushShoppingList.services.recipe_master_data_service import ingredient_master_records_for_items
from PushShoppingList.services.recipe_master_data_service import ingredient_store_section_sort_key
from PushShoppingList.services.recipe_master_data_service import ingredient_store_section_options
from PushShoppingList.services.recipe_master_data_service import normalized_master_name
from PushShoppingList.services.recipe_master_data_service import recipe_master_rows
from PushShoppingList.services.recipe_master_data_service import remove_recipe_master_records_for_recipe
from PushShoppingList.services.recipe_master_data_service import resolve_ingredient_store_section
from PushShoppingList.services.recipe_master_data_service import sync_recipe_master_records
from PushShoppingList.services.shopping_list_service import add_items
from PushShoppingList.services.restaurant_hours_service import normalize_weekly_hours
from PushShoppingList.services.restaurant_hours_service import parse_weekly_hours_text
from PushShoppingList.services.restaurant_hours_service import weekly_hours_to_text
from PushShoppingList.services.storage_service import active_guest_session_id
from PushShoppingList.services.storage_service import active_user_id
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

LOGGER = logging.getLogger(__name__)
_RECIPE_OUTPUT_WRITE_LOCK = threading.RLock()


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
RESTAURANT_LOGO_UPLOAD_FOLDER = UPLOAD_FOLDER / "restaurant_logos"
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
TITLE_IMAGE_PROVIDER_ENV_VAR = "TITLE_IMAGE_PROVIDER"
TITLE_IMAGE_FALLBACK_PROVIDER_ENV_VAR = "TITLE_IMAGE_FALLBACK_PROVIDER"
TITLE_IMAGE_PROVIDER_OPENAI = "openai"
TITLE_IMAGE_PROVIDER_OLLAMA_PROMPT_ONLY = "ollama_prompt_only"
TITLE_IMAGE_PROVIDER_COMFYUI = "comfyui"
TITLE_IMAGE_PROVIDER_NONE = "none"
TITLE_IMAGE_ALLOWED_PROVIDERS = {
    TITLE_IMAGE_PROVIDER_OPENAI,
    TITLE_IMAGE_PROVIDER_OLLAMA_PROMPT_ONLY,
    TITLE_IMAGE_PROVIDER_COMFYUI,
}
TITLE_IMAGE_ALLOWED_FALLBACK_PROVIDERS = {
    TITLE_IMAGE_PROVIDER_OPENAI,
    TITLE_IMAGE_PROVIDER_NONE,
}
OLLAMA_URL_ENV_VAR = "OLLAMA_URL"
OLLAMA_PROMPT_MODEL_ENV_VAR = "OLLAMA_PROMPT_MODEL"
OLLAMA_PROMPT_MODEL_DEFAULT = "qwen2.5:7b"
OLLAMA_URL_DEFAULT = "http://localhost:11434"
COMFYUI_URL_ENV_VAR = "COMFYUI_URL"
COMFYUI_URL_DEFAULT = "http://127.0.0.1:8188"
COMFYUI_START_COMMAND_ENV_VAR = "COMFYUI_START_COMMAND"
COMFYUI_WORKFLOW_PATH_ENV_VAR = "COMFYUI_WORKFLOW_PATH"
COMFYUI_TITLE_WORKFLOW_PATH_ENV_VAR = "COMFYUI_TITLE_WORKFLOW_PATH"
COMFYUI_STEP_WORKFLOW_PATH_ENV_VAR = "COMFYUI_STEP_WORKFLOW_PATH"
COMFYUI_EQUIPMENT_WORKFLOW_PATH_ENV_VAR = "COMFYUI_EQUIPMENT_WORKFLOW_PATH"
LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE = "Local image generation is unavailable. Start ComfyUI and try again."
TITLE_IMAGE_OPENAI_SETUP_MESSAGE = "Image generation is not set up yet."
COMFYUI_START_LOCK = threading.Lock()
COMFYUI_START_ATTEMPTED = False


class TitleImageGenerationError(RuntimeError):
    def __init__(
        self,
        reason,
        user_message="",
        error_code="TITLE_IMAGE_GENERATION_FAILED",
        local_unavailable=False,
    ):
        super().__init__(reason)
        self.reason = str(reason or "unknown_error")
        self.user_message = str(user_message or "Unable to generate title image.")
        self.error_code = str(error_code or "TITLE_IMAGE_GENERATION_FAILED")
        self.local_unavailable = bool(local_unavailable)


def title_image_clean_text(value):
    return " ".join(str(value or "").strip().split())


def title_image_log_failure(reason):
    print(f"[TitleImage] failed reason={title_image_clean_text(reason) or 'unknown_error'}")


def title_image_env_int(name, default, minimum=1, maximum=600):
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


def title_image_env_float(name, default, minimum=0.1, maximum=60.0):
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


def title_image_configured_env_int(name, minimum=1, maximum=2048):
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None

    return max(int(minimum), min(int(maximum), value))


def title_image_configured_env_float(name, minimum=0.1, maximum=60.0):
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    return max(float(minimum), min(float(maximum), value))


def comfyui_purpose_env_name(base_name, image_purpose="recipe title image"):
    purpose = title_image_clean_text(image_purpose)
    purpose_prefix = ""
    if purpose == "recipe equipment item image":
        purpose_prefix = "COMFYUI_EQUIPMENT"
    elif purpose == "recipe instruction step image":
        purpose_prefix = "COMFYUI_STEP"
    elif purpose == "recipe title image":
        purpose_prefix = "COMFYUI_TITLE"

    if not purpose_prefix or not str(base_name or "").startswith("COMFYUI_"):
        return ""

    return f"{purpose_prefix}_{str(base_name)[len('COMFYUI_'):]}"


def title_image_env_int_for_purpose(name, image_purpose, default, minimum=1, maximum=600):
    purpose_name = comfyui_purpose_env_name(name, image_purpose)
    if purpose_name and os.getenv(purpose_name) is not None and str(os.getenv(purpose_name)).strip():
        return title_image_env_int(purpose_name, default, minimum=minimum, maximum=maximum)

    return title_image_env_int(name, default, minimum=minimum, maximum=maximum)


def title_image_env_float_for_purpose(name, image_purpose, default, minimum=0.1, maximum=60.0):
    purpose_name = comfyui_purpose_env_name(name, image_purpose)
    if purpose_name and os.getenv(purpose_name) is not None and str(os.getenv(purpose_name)).strip():
        return title_image_env_float(purpose_name, default, minimum=minimum, maximum=maximum)

    return title_image_env_float(name, default, minimum=minimum, maximum=maximum)


def title_image_env_text_for_purpose(name, image_purpose):
    purpose_name = comfyui_purpose_env_name(name, image_purpose)
    if purpose_name:
        purpose_value = title_image_clean_text(os.getenv(purpose_name))
        if purpose_value:
            return purpose_value

    return title_image_clean_text(os.getenv(name))


def title_image_configured_env_int_for_purpose(name, image_purpose, minimum=1, maximum=2048):
    purpose_name = comfyui_purpose_env_name(name, image_purpose)
    if purpose_name:
        purpose_value = title_image_configured_env_int(purpose_name, minimum=minimum, maximum=maximum)
        if purpose_value is not None:
            return purpose_value

    return title_image_configured_env_int(name, minimum=minimum, maximum=maximum)


def title_image_configured_env_float_for_purpose(name, image_purpose, minimum=0.1, maximum=60.0):
    purpose_name = comfyui_purpose_env_name(name, image_purpose)
    if purpose_name:
        purpose_value = title_image_configured_env_float(purpose_name, minimum=minimum, maximum=maximum)
        if purpose_value is not None:
            return purpose_value

    return title_image_configured_env_float(name, minimum=minimum, maximum=maximum)


def normalize_title_image_provider(value, default=TITLE_IMAGE_PROVIDER_OPENAI):
    provider = title_image_clean_text(value).lower()
    provider = provider.replace("-", "_")
    if provider in {"chatgpt", "chat_gpt", "gpt"}:
        provider = TITLE_IMAGE_PROVIDER_OPENAI
    return provider if provider in TITLE_IMAGE_ALLOWED_PROVIDERS else default


def title_image_provider(value=None):
    if value is not None and title_image_clean_text(value):
        return normalize_title_image_provider(value)
    return normalize_title_image_provider(os.getenv(TITLE_IMAGE_PROVIDER_ENV_VAR))


def title_image_provider_from_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    return title_image_provider(
        payload.get("image_provider")
        or payload.get("title_image_provider")
        or payload.get("provider")
    )


def title_image_fallback_provider(value=None):
    fallback = title_image_clean_text(
        value if value is not None else os.getenv(TITLE_IMAGE_FALLBACK_PROVIDER_ENV_VAR)
    ).lower().replace("-", "_")
    return fallback if fallback in TITLE_IMAGE_ALLOWED_FALLBACK_PROVIDERS else TITLE_IMAGE_PROVIDER_NONE


def ollama_prompt_model():
    return title_image_clean_text(os.getenv(OLLAMA_PROMPT_MODEL_ENV_VAR)) or OLLAMA_PROMPT_MODEL_DEFAULT


def ollama_prompt_base_url():
    return (
        title_image_clean_text(os.getenv(OLLAMA_URL_ENV_VAR))
        or title_image_clean_text(os.getenv("OLLAMA_BASE_URL"))
        or OLLAMA_URL_DEFAULT
    ).rstrip("/")


def comfyui_base_url():
    return (title_image_clean_text(os.getenv(COMFYUI_URL_ENV_VAR)) or COMFYUI_URL_DEFAULT).rstrip("/")


def comfyui_start_command():
    return title_image_clean_text(os.getenv(COMFYUI_START_COMMAND_ENV_VAR))


def comfyui_autostart_enabled():
    value = title_image_clean_text(os.getenv("COMFYUI_AUTOSTART")).lower()
    if value:
        return value not in {"0", "false", "no", "off"}
    return bool(comfyui_start_command())


def comfyui_start_wait_seconds():
    return title_image_env_float("COMFYUI_START_WAIT_SECONDS", 45.0, minimum=1.0, maximum=180.0)


def comfyui_url_is_local(base_url):
    host = title_image_clean_text(urlparse(base_url).hostname).lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def title_image_ollama_timeout_seconds():
    return title_image_env_float("OLLAMA_PROMPT_TIMEOUT_SECONDS", 30.0, minimum=1.0, maximum=180.0)


def comfyui_request_timeout_seconds():
    return title_image_env_float("COMFYUI_REQUEST_TIMEOUT_SECONDS", 15.0, minimum=1.0, maximum=120.0)


def comfyui_preflight_timeout_seconds():
    return title_image_env_float(
        "COMFYUI_PREFLIGHT_TIMEOUT_SECONDS",
        min(3.0, comfyui_request_timeout_seconds()),
        minimum=0.25,
        maximum=30.0,
    )


def comfyui_poll_timeout_seconds():
    return title_image_env_float("COMFYUI_POLL_TIMEOUT_SECONDS", 140.0, minimum=5.0, maximum=600.0)


def comfyui_poll_interval_seconds():
    return title_image_env_float("COMFYUI_POLL_INTERVAL_SECONDS", 1.0, minimum=0.25, maximum=10.0)


def title_image_recipe_context(recipe_data, recipe_title):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    cuisine = ", ".join(normalize_text_rows(recipe_data.get("cuisine_tags") or recipe_data.get("cuisine")))
    ingredients = recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", []))

    return {
        "recipe_name": title_image_clean_text(
            recipe_title
            or recipe_data.get("recipe_title")
            or recipe_data.get("display_name")
            or recipe_data.get("menu_item_name")
        ),
        "description": title_image_clean_text(
            recipe_data.get("description")
            or recipe_data.get("summary")
            or recipe_data.get("notes")
            or recipe_data.get("menu_description")
        ),
        "cuisine": cuisine,
        "menu_section": title_image_clean_text(recipe_data.get("menu_section") or recipe_data.get("section")),
        "ingredients": ingredients,
    }


def build_ollama_recipe_image_prompt_request(recipe_data, recipe_title, base_prompt, image_purpose="recipe title image"):
    purpose = title_image_clean_text(image_purpose) or "recipe image"
    if purpose == "recipe equipment item image":
        context = {
            "image_subject": "equipment item named in the base prompt",
        }
        prompt_domain = "local Stable Diffusion product photography"
        context_label = "Image context"
        purpose_rules = """- Return a product-photo prompt, not a room, renovation, real-estate, or interior-design prompt.
- The equipment item named in the base prompt must be the single obvious main subject.
- Preserve the exact equipment subject from the base prompt.
- Use an isolated, empty, clean equipment object on a plain seamless studio background.
- If the equipment title contains alternatives like "or", show exactly one clear matching appliance or tool."""
        style_rules = """- Include soft product-photography lighting, sharp focus, material texture, and camera style.
- Do not include text, logos, watermarks, branded packaging, labels, menus, rooms, cabinets, or appliances not named in the equipment subject."""
    else:
        context = title_image_recipe_context(recipe_data, recipe_title)
        prompt_domain = "local Stable Diffusion food photography"
        context_label = "Recipe context"
        purpose_rules = (
            "- Describe a realistic finished dish with appetizing plating."
            if purpose == "recipe title image"
            else f"- Preserve the requested {purpose}; do not turn it into a finished dish unless the base prompt asks for that."
        )
        style_rules = """- Include natural light, texture, camera style, and food styling cues.
- Do not include text, logos, watermarks, branded packaging, labels, or menus."""
    return f"""You improve prompts for {prompt_domain}.

Return only one polished image prompt. Do not return JSON. Do not add commentary.
You are not generating an image; you are only improving the prompt for an image model.

{context_label}:
{json.dumps(context, ensure_ascii=False)}

Base prompt:
{base_prompt}

Prompt rules:
{purpose_rules}
- Keep it suitable for Stable Diffusion or ComfyUI.
{style_rules}
"""


def strip_ollama_prompt_response(value):
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|prompt)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().strip('"').strip("'").strip()
    return text


def equipment_item_from_image_prompt(base_prompt):
    lines = str(base_prompt or "").splitlines()
    for index, line in enumerate(lines):
        if title_image_clean_text(line).lower() != "equipment item:":
            continue
        for next_line in lines[index + 1:]:
            item = title_image_clean_text(next_line)
            if item:
                return item
    return ""


def equipment_image_requested_subject(equipment_item):
    subject = title_image_clean_text(equipment_item)
    if not subject:
        return ""

    subject = title_image_clean_text(
        re.sub(
            r"^(?:kitchen\s+)?(?:equipment|tool|tools|appliance|appliances)\s*:\s*",
            "",
            subject,
            flags=re.IGNORECASE,
        )
    ) or subject

    required_pair_aliases = {
        "blender or food processor": "blender and food processor",
    }
    return required_pair_aliases.get(subject.lower(), subject)


def equipment_image_subject_phrase(equipment_item):
    equipment_item = equipment_image_requested_subject(equipment_item)
    if not equipment_item:
        return "one clean empty cooking tool"

    if re.search(r"\b(or|and/or)\b|/", equipment_item, flags=re.IGNORECASE):
        return f"one clean empty appliance or tool matching {equipment_item}, choose exactly one option"

    if re.search(r"\band\b", equipment_item, flags=re.IGNORECASE):
        return f"a clean empty equipment set matching {equipment_item}, show all named items side by side"

    return f"one clean empty {equipment_item}"


def safe_equipment_prompt_style_notes(polished_prompt):
    text = title_image_clean_text(polished_prompt)
    if not text:
        return ""

    forbidden_terms = (
        "food",
        "ingredient",
        "dish",
        "meal",
        "plated",
        "potato",
        "vegetable",
        "garnish",
        "sauce",
        "soup",
        "liquid",
        "kitchen",
        "cabinet",
        "cupboard",
        "island",
        "sink",
        "stove",
        "oven",
        "refrigerator",
        "fridge",
        "window",
        "room",
        "interior",
        "renovation",
        "real estate",
        "countertop",
        "counter",
        "collage",
        "split",
    )
    sentences = [
        title_image_clean_text(part)
        for part in re.split(r"(?<=[.!?])\s+|[;\n]+", text)
    ]
    safe_sentences = []
    for sentence in sentences:
        lower_sentence = sentence.lower()
        if not sentence or any(term in lower_sentence for term in forbidden_terms):
            continue
        safe_sentences.append(sentence)

    return title_image_clean_text(" ".join(safe_sentences))[:360]


def finalize_equipment_image_prompt(base_prompt, polished_prompt=""):
    equipment_item = equipment_item_from_image_prompt(base_prompt)
    subject = equipment_image_subject_phrase(equipment_item)
    style_notes = safe_equipment_prompt_style_notes(polished_prompt)
    if not style_notes:
        style_notes = "soft natural studio light, sharp focus, realistic material texture, 50mm lens, product catalog composition"

    exact_subject = equipment_image_requested_subject(equipment_item) or "the named equipment item"
    return title_image_clean_text(
        f"single isolated product reference photo of {subject}. "
        f"Exact equipment subject: {exact_subject}. "
        "Centered, fully visible, empty, unused, clean, and easy to identify. "
        "Plain seamless light gray studio background, neutral matte surface. "
        "Realistic product photography, high-detail homeware catalog image. "
        f"Style details: {style_notes}."
    )


def enhance_recipe_image_prompt_with_ollama(
    recipe_data,
    recipe_title,
    base_prompt,
    required=False,
    image_purpose="recipe title image",
):
    purpose = title_image_clean_text(image_purpose)
    model = ollama_prompt_model()
    base_url = ollama_prompt_base_url()
    print(f"[TitleImage] ollama_prompt_model={model}")

    payload = {
        "model": model,
        "prompt": build_ollama_recipe_image_prompt_request(
            recipe_data,
            recipe_title,
            base_prompt,
            image_purpose=image_purpose,
        ),
        "stream": False,
        "options": {
            "temperature": 0.4,
        },
    }

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=title_image_ollama_timeout_seconds(),
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("response")
        if text is None and isinstance(data.get("message"), dict):
            text = data["message"].get("content")
        polished_prompt = strip_ollama_prompt_response(text)
        if len(polished_prompt) < 20:
            raise TitleImageGenerationError(
                "ollama_prompt_empty",
                "Title image prompt enhancement failed. Please try again.",
                error_code="OLLAMA_PROMPT_FAILED",
            )
        if purpose == "recipe equipment item image":
            return finalize_equipment_image_prompt(base_prompt, polished_prompt)
        return polished_prompt
    except TitleImageGenerationError:
        if required:
            raise
    except Exception as exc:
        reason = f"ollama_prompt_failed:{type(exc).__name__}:{exc}"
        print(f"[TitleImage] ollama_prompt_failed reason={title_image_clean_text(reason)}")
        if required:
            raise TitleImageGenerationError(
                reason,
                "Title image prompt enhancement failed. Please try again.",
                error_code="OLLAMA_PROMPT_FAILED",
            ) from exc

    if purpose == "recipe equipment item image":
        return finalize_equipment_image_prompt(base_prompt)

    return base_prompt


def build_ollama_title_image_prompt_request(recipe_data, recipe_title, base_prompt):
    return build_ollama_recipe_image_prompt_request(
        recipe_data,
        recipe_title,
        base_prompt,
        image_purpose="recipe title image",
    )


def enhance_recipe_title_image_prompt_with_ollama(recipe_data, recipe_title, base_prompt, required=False):
    return enhance_recipe_image_prompt_with_ollama(
        recipe_data,
        recipe_title,
        base_prompt,
        required=required,
        image_purpose="recipe title image",
    )


def comfyui_object_info_checkpoint_names(base_url, request_timeout):
    response = requests.get(
        f"{base_url}/object_info/CheckpointLoaderSimple",
        timeout=request_timeout,
    )
    response.raise_for_status()
    data = response.json()
    checkpoint_info = (
        data.get("CheckpointLoaderSimple", {})
        .get("input", {})
        .get("required", {})
        .get("ckpt_name", [])
    )
    return checkpoint_info[0] if checkpoint_info and isinstance(checkpoint_info[0], list) else []


def comfyui_service_ready(base_url, request_timeout):
    try:
        response = requests.get(f"{base_url}/system_stats", timeout=request_timeout)
        response.raise_for_status()
        return True
    except Exception:
        return False


def ensure_comfyui_available(base_url=None, request_timeout=None):
    base_url = (title_image_clean_text(base_url) or comfyui_base_url()).rstrip("/")
    request_timeout = request_timeout if request_timeout is not None else comfyui_preflight_timeout_seconds()

    try:
        response = requests.get(f"{base_url}/system_stats", timeout=request_timeout)
        response.raise_for_status()
        return
    except requests.Timeout as exc:
        raise TitleImageGenerationError(
            f"comfyui_preflight_timeout:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_TIMEOUT",
            local_unavailable=True,
        ) from exc
    except requests.ConnectionError as exc:
        if maybe_start_local_comfyui(
            base_url,
            request_timeout,
            reason=f"preflight_connection_failed:{exc}",
        ):
            return

        raise TitleImageGenerationError(
            f"comfyui_preflight_connection_failed:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc
    except Exception as exc:
        raise TitleImageGenerationError(
            f"comfyui_preflight_failed:{type(exc).__name__}:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc


def maybe_start_local_comfyui(base_url, request_timeout, reason=""):
    global COMFYUI_START_ATTEMPTED

    command = comfyui_start_command()
    if not command or not comfyui_autostart_enabled() or not comfyui_url_is_local(base_url):
        return False

    with COMFYUI_START_LOCK:
        if comfyui_service_ready(base_url, request_timeout):
            return True

        if not COMFYUI_START_ATTEMPTED:
            COMFYUI_START_ATTEMPTED = True
            print(
                "[TitleImage] comfyui_autostart=starting "
                f"reason={title_image_clean_text(reason) or 'not_running'}"
            )
            try:
                subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as exc:
                print(f"[TitleImage] comfyui_autostart_failed reason={title_image_clean_text(exc)}")
                return False
        else:
            print("[TitleImage] comfyui_autostart=waiting_for_existing_attempt")

        deadline = perf_counter() + comfyui_start_wait_seconds()
        while perf_counter() < deadline:
            if comfyui_service_ready(base_url, request_timeout):
                print("[TitleImage] comfyui_autostart=ready")
                return True
            sleep(1)

    print("[TitleImage] comfyui_autostart=timeout")
    return False


def comfyui_checkpoint_name(base_url, request_timeout):
    configured_checkpoint = title_image_clean_text(os.getenv("COMFYUI_CHECKPOINT"))
    if configured_checkpoint:
        return configured_checkpoint

    try:
        checkpoint_names = comfyui_object_info_checkpoint_names(base_url, request_timeout)
        checkpoint_name = title_image_clean_text(checkpoint_names[0] if checkpoint_names else "")
        if checkpoint_name:
            return checkpoint_name
    except requests.ConnectionError as exc:
        if maybe_start_local_comfyui(base_url, request_timeout, reason=f"checkpoint_lookup_connection_failed:{exc}"):
            try:
                checkpoint_names = comfyui_object_info_checkpoint_names(base_url, request_timeout)
                checkpoint_name = title_image_clean_text(checkpoint_names[0] if checkpoint_names else "")
                if checkpoint_name:
                    return checkpoint_name
            except Exception as retry_exc:
                raise TitleImageGenerationError(
                    f"comfyui_checkpoint_lookup_failed_after_autostart:{type(retry_exc).__name__}:{retry_exc}",
                    LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                    error_code="COMFYUI_UNAVAILABLE",
                    local_unavailable=True,
                ) from retry_exc

        raise TitleImageGenerationError(
            f"comfyui_checkpoint_lookup_failed:{type(exc).__name__}:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc
    except Exception as exc:
        raise TitleImageGenerationError(
            f"comfyui_checkpoint_lookup_failed:{type(exc).__name__}:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc

    raise TitleImageGenerationError(
        "comfyui_checkpoint_not_found",
        LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
        error_code="COMFYUI_CHECKPOINT_NOT_FOUND",
        local_unavailable=True,
    )


def comfyui_negative_prompt_for_purpose(image_purpose="recipe title image"):
    purpose = title_image_clean_text(image_purpose)
    if purpose == "recipe equipment item image":
        equipment_negative = title_image_clean_text(os.getenv("COMFYUI_EQUIPMENT_NEGATIVE_PROMPT"))
        if equipment_negative:
            return equipment_negative

    configured_negative = title_image_clean_text(os.getenv("COMFYUI_NEGATIVE_PROMPT"))
    if configured_negative:
        return configured_negative

    base_negative = (
        "text, labels, captions, logos, watermarks, branded packaging, extra fingers, "
        "low quality, blurry, overexposed"
    )

    if purpose == "recipe equipment item image":
        return (
            "food, ingredients, chopped food, cooked food, prepared food, plated meal, "
            "potatoes, vegetables, garnish, sauce, soup, liquid, bowl of food, cooking action, hands, "
            "kitchen interior, room interior, cabinets, cupboards, kitchen island, countertop, sink, "
            "stove, oven, refrigerator, window, renovation, real estate photo, empty kitchen, "
            "collage, split image, multiple panels, unrelated appliances, background appliance, "
            f"{base_negative}"
        )

    return f"deformed food, {base_negative}"


def comfyui_workflow_path(image_purpose="recipe title image"):
    purpose = title_image_clean_text(image_purpose)
    env_names = []

    if purpose == "recipe equipment item image":
        env_names.append(COMFYUI_EQUIPMENT_WORKFLOW_PATH_ENV_VAR)
    elif purpose == "recipe instruction step image":
        env_names.append(COMFYUI_STEP_WORKFLOW_PATH_ENV_VAR)
    elif purpose == "recipe title image":
        env_names.append(COMFYUI_TITLE_WORKFLOW_PATH_ENV_VAR)

    env_names.append(COMFYUI_WORKFLOW_PATH_ENV_VAR)

    for name in env_names:
        configured = title_image_clean_text(os.getenv(name))
        if configured:
            return configured

    return ""


def comfyui_filename_prefix_for_purpose(image_purpose="recipe title image"):
    purpose = title_image_clean_text(image_purpose)
    if purpose == "recipe equipment item image":
        return "recipe_equipment"
    if purpose == "recipe instruction step image":
        return "recipe_step"
    return "recipe_title"


def load_custom_comfyui_workflow(image_purpose="recipe title image"):
    workflow_path = comfyui_workflow_path(image_purpose)
    if not workflow_path:
        return None

    path = Path(os.path.expandvars(workflow_path)).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TitleImageGenerationError(
            f"comfyui_workflow_not_found:{path}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_WORKFLOW_NOT_FOUND",
            local_unavailable=True,
        ) from exc
    except Exception as exc:
        raise TitleImageGenerationError(
            f"comfyui_workflow_load_failed:{type(exc).__name__}:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_INVALID_WORKFLOW",
            local_unavailable=True,
        ) from exc

    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        data = data["prompt"]

    if not isinstance(data, dict) or not data:
        raise TitleImageGenerationError(
            "comfyui_workflow_not_api_format",
            "ComfyUI workflow must be exported in API format.",
            error_code="COMFYUI_INVALID_WORKFLOW",
            local_unavailable=True,
        )

    workflow = deepcopy(data)
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise TitleImageGenerationError(
                f"comfyui_workflow_invalid_node:{node_id}",
                "ComfyUI workflow must be exported in API format.",
                error_code="COMFYUI_INVALID_WORKFLOW",
                local_unavailable=True,
            )

    return workflow


def comfyui_workflow_inputs(workflow, node_id):
    node = workflow.get(str(node_id)) if isinstance(workflow, dict) else None
    inputs = node.get("inputs") if isinstance(node, dict) else None
    return inputs if isinstance(inputs, dict) else None


def comfyui_text_encode_node_ids(workflow):
    node_ids = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or "text" not in inputs:
            continue
        class_type = title_image_clean_text(node.get("class_type")).lower()
        if "textencode" in class_type or "cliptextencode" in class_type or "text encode" in class_type:
            node_ids.append(str(node_id))
    return node_ids


def comfyui_prompt_looks_negative(text):
    lower_text = title_image_clean_text(text).lower()
    negative_markers = (
        "low quality",
        "bad anatomy",
        "extra digits",
        "missing digits",
        "missing limbs",
        "watermark",
        "logo",
        "text",
        "blurry",
    )
    return any(marker in lower_text for marker in negative_markers)


def comfyui_configured_node_id(name):
    node_id = title_image_clean_text(os.getenv(name))
    return node_id or ""


def comfyui_custom_prompt_node_ids(workflow):
    text_node_ids = comfyui_text_encode_node_ids(workflow)
    configured_positive = comfyui_configured_node_id("COMFYUI_POSITIVE_PROMPT_NODE_ID")
    configured_negative = comfyui_configured_node_id("COMFYUI_NEGATIVE_PROMPT_NODE_ID")

    negative_node_id = ""
    if configured_negative and comfyui_workflow_inputs(workflow, configured_negative):
        negative_node_id = configured_negative
    if not negative_node_id:
        for node_id in text_node_ids:
            inputs = comfyui_workflow_inputs(workflow, node_id) or {}
            if comfyui_prompt_looks_negative(inputs.get("text")):
                negative_node_id = node_id
                break
    if not negative_node_id and len(text_node_ids) > 1:
        negative_node_id = text_node_ids[1]

    positive_node_id = ""
    if configured_positive and comfyui_workflow_inputs(workflow, configured_positive):
        positive_node_id = configured_positive
    if not positive_node_id:
        for node_id in text_node_ids:
            if node_id != negative_node_id:
                positive_node_id = node_id
                break

    return positive_node_id, negative_node_id


def patch_custom_comfyui_workflow(prompt, workflow, image_purpose="recipe title image"):
    positive_node_id, negative_node_id = comfyui_custom_prompt_node_ids(workflow)
    positive_inputs = comfyui_workflow_inputs(workflow, positive_node_id)
    if not positive_inputs:
        raise TitleImageGenerationError(
            "comfyui_positive_prompt_node_not_found",
            "ComfyUI workflow is missing a positive prompt text node.",
            error_code="COMFYUI_INVALID_WORKFLOW",
            local_unavailable=True,
        )

    positive_inputs["text"] = prompt

    negative_inputs = comfyui_workflow_inputs(workflow, negative_node_id)
    if negative_inputs is not None:
        negative_inputs["text"] = comfyui_negative_prompt_for_purpose(image_purpose)

    seed = uuid.uuid4().int % 1_000_000_000_000
    configured_seed_node_id = comfyui_configured_node_id("COMFYUI_SEED_NODE_ID")
    seed_node_ids = [configured_seed_node_id] if configured_seed_node_id else [
        node_id
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        and isinstance(node.get("inputs"), dict)
        and "seed" in node["inputs"]
    ]
    for node_id in seed_node_ids:
        inputs = comfyui_workflow_inputs(workflow, node_id)
        if inputs is not None and "seed" in inputs:
            inputs["seed"] = seed

    sampler_overrides = {
        "steps": title_image_configured_env_int_for_purpose(
            "COMFYUI_STEPS",
            image_purpose,
            minimum=1,
            maximum=100,
        ),
        "cfg": title_image_configured_env_float_for_purpose(
            "COMFYUI_CFG",
            image_purpose,
            minimum=1.0,
            maximum=30.0,
        ),
        "sampler_name": title_image_env_text_for_purpose("COMFYUI_SAMPLER", image_purpose),
        "scheduler": title_image_env_text_for_purpose("COMFYUI_SCHEDULER", image_purpose),
    }
    sampler_overrides = {
        name: value
        for name, value in sampler_overrides.items()
        if value is not None and str(value).strip()
    }
    if sampler_overrides:
        configured_sampler_node_id = comfyui_configured_node_id("COMFYUI_SAMPLER_NODE_ID")
        sampler_node_ids = [configured_sampler_node_id] if configured_sampler_node_id else [
            node_id
            for node_id, node in workflow.items()
            if isinstance(node, dict)
            and isinstance(node.get("inputs"), dict)
            and any(name in node["inputs"] for name in sampler_overrides)
        ]
        for node_id in sampler_node_ids:
            inputs = comfyui_workflow_inputs(workflow, node_id)
            if not inputs:
                continue
            for name, value in sampler_overrides.items():
                if name in inputs:
                    inputs[name] = value

    width = title_image_configured_env_int_for_purpose(
        "COMFYUI_IMAGE_WIDTH",
        image_purpose,
        minimum=256,
        maximum=2048,
    )
    height = title_image_configured_env_int_for_purpose(
        "COMFYUI_IMAGE_HEIGHT",
        image_purpose,
        minimum=256,
        maximum=2048,
    )
    if width is not None or height is not None:
        configured_size_node_id = (
            comfyui_configured_node_id("COMFYUI_SIZE_NODE_ID")
            or comfyui_configured_node_id("COMFYUI_LATENT_NODE_ID")
        )
        size_node_ids = [configured_size_node_id] if configured_size_node_id else [
            node_id
            for node_id, node in workflow.items()
            if isinstance(node, dict)
            and isinstance(node.get("inputs"), dict)
            and ("width" in node["inputs"] or "height" in node["inputs"])
        ]
        for node_id in size_node_ids:
            inputs = comfyui_workflow_inputs(workflow, node_id)
            if not inputs:
                continue
            if width is not None and "width" in inputs:
                inputs["width"] = width
            if height is not None and "height" in inputs:
                inputs["height"] = height

    configured_checkpoint = title_image_env_text_for_purpose("COMFYUI_CHECKPOINT", image_purpose)
    if configured_checkpoint:
        configured_checkpoint_node_id = comfyui_configured_node_id("COMFYUI_CHECKPOINT_NODE_ID")
        checkpoint_node_ids = [configured_checkpoint_node_id] if configured_checkpoint_node_id else [
            node_id
            for node_id, node in workflow.items()
            if isinstance(node, dict)
            and isinstance(node.get("inputs"), dict)
            and "ckpt_name" in node["inputs"]
        ]
        for node_id in checkpoint_node_ids:
            inputs = comfyui_workflow_inputs(workflow, node_id)
            if inputs is not None and "ckpt_name" in inputs:
                inputs["ckpt_name"] = configured_checkpoint

    configured_save_node_id = comfyui_configured_node_id("COMFYUI_SAVE_IMAGE_NODE_ID")
    save_node_ids = [configured_save_node_id] if configured_save_node_id else [
        node_id
        for node_id, node in workflow.items()
        if isinstance(node, dict)
        and title_image_clean_text(node.get("class_type")).lower() == "saveimage"
    ]
    for node_id in save_node_ids:
        inputs = comfyui_workflow_inputs(workflow, node_id)
        if inputs is not None and "filename_prefix" in inputs:
            inputs["filename_prefix"] = comfyui_filename_prefix_for_purpose(image_purpose)

    return workflow


def build_default_comfyui_title_workflow(prompt, checkpoint_name, image_purpose="recipe title image"):
    width = title_image_env_int_for_purpose(
        "COMFYUI_IMAGE_WIDTH",
        image_purpose,
        1024,
        minimum=256,
        maximum=2048,
    )
    height = title_image_env_int_for_purpose(
        "COMFYUI_IMAGE_HEIGHT",
        image_purpose,
        1024,
        minimum=256,
        maximum=2048,
    )
    steps = title_image_env_int_for_purpose("COMFYUI_STEPS", image_purpose, 24, minimum=1, maximum=100)
    cfg = title_image_env_float_for_purpose("COMFYUI_CFG", image_purpose, 7.0, minimum=1.0, maximum=30.0)
    sampler_name = title_image_env_text_for_purpose("COMFYUI_SAMPLER", image_purpose) or "euler"
    scheduler = title_image_env_text_for_purpose("COMFYUI_SCHEDULER", image_purpose) or "normal"
    negative_prompt = comfyui_negative_prompt_for_purpose(image_purpose)
    seed = uuid.uuid4().int % 1_000_000_000_000

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": checkpoint_name,
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["4", 1],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative_prompt,
                "clip": ["4", 1],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": comfyui_filename_prefix_for_purpose(image_purpose),
                "images": ["8", 0],
            },
        },
    }


def build_comfyui_workflow(prompt, image_purpose, base_url, request_timeout):
    custom_workflow = load_custom_comfyui_workflow(image_purpose)
    if custom_workflow is not None:
        return patch_custom_comfyui_workflow(
            prompt,
            custom_workflow,
            image_purpose=image_purpose,
        )

    checkpoint_name = comfyui_checkpoint_name(base_url, request_timeout)
    return build_default_comfyui_title_workflow(
        prompt,
        checkpoint_name,
        image_purpose=image_purpose,
    )


def comfyui_history_record(history_payload, prompt_id):
    if not isinstance(history_payload, dict):
        return {}

    record = history_payload.get(prompt_id)
    if isinstance(record, dict):
        return record

    if "outputs" in history_payload:
        return history_payload

    return {}


def comfyui_history_error_reason(record):
    if not isinstance(record, dict):
        return ""

    status = record.get("status")
    if not isinstance(status, dict):
        return ""

    status_text = title_image_clean_text(status.get("status_str") or status.get("status"))
    if status_text.lower() not in {"error", "failed"}:
        return ""

    messages = status.get("messages")
    if isinstance(messages, list):
        return title_image_clean_text(json.dumps(messages, ensure_ascii=False))[:500]

    return status_text or "comfyui_generation_failed"


def first_comfyui_history_image(record):
    outputs = record.get("outputs") if isinstance(record, dict) else {}
    if not isinstance(outputs, dict):
        return {}

    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        images = output.get("images")
        if not isinstance(images, list):
            continue
        for image in images:
            if isinstance(image, dict) and image.get("filename"):
                return image

    return {}


def request_comfyui_image_bytes(prompt, image_purpose="recipe title image"):
    base_url = comfyui_base_url()
    request_timeout = comfyui_request_timeout_seconds()
    poll_timeout = comfyui_poll_timeout_seconds()
    poll_interval = comfyui_poll_interval_seconds()
    print(f"[TitleImage] comfyui_url={base_url}")

    try:
        workflow = build_comfyui_workflow(
            prompt,
            image_purpose,
            base_url,
            request_timeout,
        )
        response = requests.post(
            f"{base_url}/prompt",
            json={
                "prompt": workflow,
                "client_id": uuid.uuid4().hex,
            },
            timeout=request_timeout,
        )
        response.raise_for_status()
        prompt_id = title_image_clean_text(response.json().get("prompt_id"))
    except requests.ConnectionError as exc:
        raise TitleImageGenerationError(
            f"comfyui_connection_failed:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc
    except requests.Timeout as exc:
        raise TitleImageGenerationError(
            f"comfyui_request_timeout:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_TIMEOUT",
            local_unavailable=True,
        ) from exc
    except TitleImageGenerationError:
        raise
    except Exception as exc:
        raise TitleImageGenerationError(
            f"comfyui_prompt_submit_failed:{type(exc).__name__}:{exc}",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        ) from exc

    if not prompt_id:
        raise TitleImageGenerationError(
            "comfyui_prompt_id_missing",
            LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_INVALID_RESPONSE",
            local_unavailable=True,
        )

    deadline = perf_counter() + poll_timeout
    while perf_counter() < deadline:
        try:
            history_response = requests.get(
                f"{base_url}/history/{prompt_id}",
                timeout=request_timeout,
            )
            history_response.raise_for_status()
            record = comfyui_history_record(history_response.json(), prompt_id)
        except requests.ConnectionError as exc:
            raise TitleImageGenerationError(
                f"comfyui_history_connection_failed:{exc}",
                LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_UNAVAILABLE",
                local_unavailable=True,
            ) from exc
        except requests.Timeout as exc:
            raise TitleImageGenerationError(
                f"comfyui_history_timeout:{exc}",
                LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_TIMEOUT",
                local_unavailable=True,
            ) from exc
        except Exception as exc:
            raise TitleImageGenerationError(
                f"comfyui_history_failed:{type(exc).__name__}:{exc}",
                LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_UNAVAILABLE",
                local_unavailable=True,
            ) from exc

        error_reason = comfyui_history_error_reason(record)
        if error_reason:
            raise TitleImageGenerationError(
                f"comfyui_generation_failed:{error_reason}",
                LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_GENERATION_FAILED",
                local_unavailable=True,
            )

        image_info = first_comfyui_history_image(record)
        if image_info:
            try:
                image_response = requests.get(
                    f"{base_url}/view",
                    params={
                        "filename": image_info.get("filename"),
                        "subfolder": image_info.get("subfolder", ""),
                        "type": image_info.get("type", "output"),
                    },
                    timeout=request_timeout,
                )
                image_response.raise_for_status()
            except requests.Timeout as exc:
                raise TitleImageGenerationError(
                    f"comfyui_image_download_timeout:{exc}",
                    LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                    error_code="COMFYUI_TIMEOUT",
                    local_unavailable=True,
                ) from exc
            except Exception as exc:
                raise TitleImageGenerationError(
                    f"comfyui_image_download_failed:{type(exc).__name__}:{exc}",
                    LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                    error_code="COMFYUI_UNAVAILABLE",
                    local_unavailable=True,
                ) from exc

            if image_response.content:
                return image_response.content

            raise TitleImageGenerationError(
                "comfyui_image_empty",
                LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_EMPTY_IMAGE",
                local_unavailable=True,
            )

        sleep(poll_interval)

    raise TitleImageGenerationError(
        f"comfyui_poll_timeout:{poll_timeout:g}s",
        LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
        error_code="COMFYUI_TIMEOUT",
        local_unavailable=True,
    )


def request_comfyui_title_image_bytes(prompt):
    return request_comfyui_image_bytes(prompt, image_purpose="recipe title image")


def test_local_title_image_generation(prompt=""):
    prompt = title_image_clean_text(prompt) or (
        "A realistic cookbook photo of a bowl of tomato soup with basil, "
        "natural window light, shallow depth of field, no text or logos."
    )
    print(f"[TitleImage] provider={TITLE_IMAGE_PROVIDER_COMFYUI}")

    try:
        image_bytes = request_comfyui_title_image_bytes(prompt)
    except TitleImageGenerationError as exc:
        title_image_log_failure(exc.reason)
        return {
            "ok": False,
            "provider": TITLE_IMAGE_PROVIDER_COMFYUI,
            "comfyui_url": comfyui_base_url(),
            "error": exc.user_message,
            "error_code": exc.error_code,
            "local_generation_unavailable": exc.local_unavailable,
        }

    return {
        "ok": True,
        "provider": TITLE_IMAGE_PROVIDER_COMFYUI,
        "comfyui_url": comfyui_base_url(),
        "message": "Local image generation succeeded.",
        "byte_count": len(image_bytes),
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
    created_at = now_iso()
    recipe_data = {
        "recipe_id": uuid.uuid4().hex,
        "created_at": created_at,
        "updated_at": created_at,
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
        "recipe_notes": [],
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
    values = query.get("menu_item") or query.get("menuItemIdInput") or query.get("menu_item_id") or []
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

    item_query_keys = {"menu_item", "menu_item_id"}
    if not any(key in item_query_keys for key, _value in query_pairs):
        return ""

    filtered_query = urlencode(
        [(key, value) for key, value in query_pairs if key not in item_query_keys],
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


def recipe_cartana_id_from_candidates(prefix, *values):
    for value in values:
        text = clean_recipe_menu_text(value)
        if text and text.upper().startswith(prefix):
            return text
    return ""


def recipe_cartana_menu_item_order_url(candidate_url="", source_menu_url="", menu_id="", menu_item_id=""):
    for value in (candidate_url, source_menu_url):
        try:
            parsed = urlparse(str(value or ""))
        except ValueError:
            continue

        if not parsed.scheme or not parsed.netloc:
            continue

        if not (parsed.path.endswith("menu_home.action") or parsed.path.endswith("menuItem_home.action")):
            continue

        query = parse_qs(parsed.query or "")
        restaurant_id = first_recipe_menu_text((query.get("resInput") or [""])[0])
        cartana_menu_id = recipe_cartana_id_from_candidates(
            "MEN",
            (query.get("menuIdInput") or [""])[0],
            menu_id,
        )
        cartana_item_id = recipe_cartana_id_from_candidates(
            "MIT",
            (query.get("menuItemIdInput") or [""])[0],
            menu_item_id,
            (query.get("menu_item_id") or [""])[0],
        )
        if not restaurant_id or not cartana_menu_id or not cartana_item_id:
            continue

        item_path = parsed.path.rsplit("/", 1)[0] + "/menuItem_home.action"
        query_text = urlencode({
            "resInput": restaurant_id,
            "menuIdInput": cartana_menu_id,
            "menuItemIdInput": cartana_item_id,
            "orderType": "null",
        })
        return urlunparse((parsed.scheme, parsed.netloc, item_path, "", query_text, ""))

    return ""


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
                "menu_id": first_recipe_menu_text(item.get("menu_id"), metadata.get("menu_id")),
                "menu_item_id": current_item_id,
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


def normalize_editable_restaurant_status(value):
    token = re.sub(r"[^a-z]+", "_", clean_recipe_menu_text(value).casefold()).strip("_")
    aliases = {
        "open": "operating",
        "active": "operating",
        "operating": "operating",
        "temporarily_closed": "temporarily_closed",
        "permanently_closed": "permanently_closed",
        "closed": "unknown",
        "unknown": "unknown",
    }
    return aliases.get(token, "unknown")


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


def parse_recipe_menu_json_list(value):
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return split_recipe_menu_text_list(text)
    return parsed if isinstance(parsed, list) else []


def normalize_editable_restaurant_social_links(value):
    supported = {"facebook", "instagram", "tiktok", "x", "youtube", "linkedin", "other_social"}
    links = []
    seen = set()
    for item in parse_recipe_menu_json_list(value):
        item = item if isinstance(item, dict) else {"url": item}
        url = clean_recipe_menu_text(item.get("url") or item.get("href"))
        if not url:
            continue
        platform = clean_recipe_menu_text(item.get("platform") or item.get("type")).lower()
        if editable_restaurant_ordering_provider_for_url(url):
            continue
        if platform == "other":
            platform = "other_social"
        if platform not in supported:
            platform = "other_social"
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        links.append({"platform": platform, "url": url})
    return links


EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS = {
    "official_online_ordering": "Official Online Ordering",
    "doordash": "DoorDash",
    "grubhub": "Grubhub",
    "uber_eats": "Uber Eats",
    "postmates": "Postmates",
    "slice": "Slice",
    "chownow": "ChowNow",
    "toast": "Toast",
    "square_online": "Square Online",
    "clover": "Clover",
    "other": "Other",
}


def editable_restaurant_ordering_provider_for_url(value):
    try:
        hostname = (urlparse(clean_recipe_menu_text(value)).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""
    domain_map = (
        (("doordash.com",), "doordash"),
        (("grubhub.com",), "grubhub"),
        (("ubereats.com", "uber.com"), "uber_eats"),
        (("postmates.com",), "postmates"),
        (("slicelife.com",), "slice"),
        (("chownow.com",), "chownow"),
        (("toasttab.com",), "toast"),
        (("square.site", "squareup.com"), "square_online"),
        (("clover.com",), "clover"),
    )
    for domains, provider in domain_map:
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            return provider
    return ""


def normalize_editable_restaurant_ordering_links(value):
    links = []
    seen_urls = set()
    seen_providers = set()
    for item in parse_recipe_menu_json_list(value):
        item = item if isinstance(item, dict) else {"url": item}
        url = clean_recipe_menu_text(item.get("url") or item.get("website_url") or item.get("href"))
        if not url:
            continue
        provider = re.sub(
            r"[\s-]+", "_", clean_recipe_menu_text(
                item.get("provider") or item.get("provider_key") or item.get("provider_name") or item.get("platform")
            ).casefold()
        )
        if provider not in EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS:
            provider = editable_restaurant_ordering_provider_for_url(url) or "other"
        url_key = url.casefold()
        if url_key in seen_urls or (provider != "other" and provider in seen_providers):
            continue
        active = item.get("is_active", item.get("active", True))
        is_active = not (active is False or clean_recipe_menu_text(active).casefold() == "false")
        provider_name = clean_recipe_menu_text(item.get("provider_name"))
        source_url = clean_recipe_menu_text(item.get("source_url"))
        normalized = {"provider": provider, "url": url, "is_active": is_active}
        if provider == "other" and provider_name:
            normalized["provider_name"] = provider_name
        if source_url:
            normalized["source_url"] = source_url
        links.append(normalized)
        seen_urls.add(url_key)
        if provider != "other":
            seen_providers.add(provider)
    return links


def editable_restaurant_ordering_links_from_record(restaurant):
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    combined = []
    combined.extend(parse_recipe_menu_json_list(restaurant.get("ordering_delivery_links")))
    combined.extend(parse_recipe_menu_json_list(restaurant.get("ordering_links")))
    combined.extend(parse_recipe_menu_json_list(restaurant.get("ordering_providers")))
    combined.extend(parse_recipe_menu_json_list(restaurant.get("ordering_provider_urls")))
    for item in parse_recipe_menu_json_list(restaurant.get("social_links") or restaurant.get("social_urls")):
        url = item.get("url") if isinstance(item, dict) else item
        if editable_restaurant_ordering_provider_for_url(url):
            combined.append(item)
    return normalize_editable_restaurant_ordering_links(combined)


def editable_menu_source_option_value(restaurant_id="", menu_id=""):
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    menu_id = clean_recipe_menu_text(menu_id)
    return f"{restaurant_id}|{menu_id}"


def editable_menu_source_option_label(restaurant, menu):
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    menu = menu if isinstance(menu, dict) else {}
    name = first_recipe_menu_text(
        restaurant.get("restaurant_name"),
        menu.get("menu_title"),
        "Restaurant Menu",
    )
    detail = first_recipe_menu_text(
        menu.get("source_url"),
        restaurant.get("menu_url"),
        restaurant.get("source_menu_url"),
        restaurant.get("full_address"),
        restaurant.get("address_line"),
        menu.get("menu_title"),
    )
    if detail and detail != name:
        return f"{name} - {detail}"
    return name


def editable_restaurant_location(restaurant):
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    full_address = clean_recipe_menu_text(restaurant.get("full_address"))
    street = clean_recipe_menu_text(restaurant.get("address_line"))
    city = clean_recipe_menu_text(restaurant.get("city"))
    state = clean_recipe_menu_text(restaurant.get("state") or restaurant.get("state_or_region"))
    postal_code = clean_recipe_menu_text(restaurant.get("postal_code"))
    country = clean_recipe_menu_text(restaurant.get("country"))
    primary = full_address or street
    parts = [primary] if primary else []
    comparison = primary.casefold()

    if city and city.casefold() not in comparison:
        parts.append(city)
    state_postal = " ".join(value for value in (state, postal_code) if value)
    if state_postal and not all(value.casefold() in comparison for value in (state, postal_code) if value):
        parts.append(state_postal)
    if country and country.casefold() not in comparison:
        parts.append(country)

    return ", ".join(part for part in parts if part)


def editable_restaurant_owner_fields():
    """Return audit metadata for the already request-scoped restaurant store."""
    user_id = clean_recipe_menu_text(active_user_id())
    guest_id = clean_recipe_menu_text(active_guest_session_id())
    if guest_id:
        return {"owner_user_id": None, "account_scope": f"guest:{guest_id}"}
    if user_id:
        return {"owner_user_id": user_id, "account_scope": "user"}
    return {"owner_user_id": None, "account_scope": "legacy"}


def normalize_editable_restaurant_store_metadata(payload):
    payload = payload if isinstance(payload, dict) else {}
    now = menu_store_service.utc_now_iso()
    owner_fields = editable_restaurant_owner_fields()
    changed = False
    for restaurant in payload.get("restaurants", []):
        restaurant_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
        if not restaurant_id:
            continue
        legacy_weekly_hours, legacy_hours_notes = editable_restaurant_structured_hours(restaurant.get("hours_text"))
        weekly_hours = normalize_weekly_hours(restaurant.get("weekly_hours")) or legacy_weekly_hours
        hours_notes = clean_recipe_menu_text(restaurant.get("hours_notes")) or legacy_hours_notes
        defaults = {
            "id": restaurant_id,
            "restaurant_id": restaurant_id,
            "created_at": restaurant.get("imported_at") or restaurant.get("updated_at") or now,
            "updated_at": restaurant.get("updated_at") or restaurant.get("imported_at") or now,
            "logo": restaurant.get("logo_url"),
            "website_url": restaurant.get("restaurant_website_url"),
            "menu_url": restaurant.get("source_menu_url"),
            "state_or_region": restaurant.get("state"),
            "weekly_hours": weekly_hours,
            "hours_notes": hours_notes or None,
            "raw_hours_data": restaurant.get("hours_text"),
            "rewards_promotions": restaurant.get("rewards_text"),
            "online_payment": restaurant.get("online_payment_available"),
            "online_ordering": restaurant.get("online_ordering_available"),
            "delivery": restaurant.get("delivery_available"),
            **owner_fields,
        }
        for field, default in {
            "restaurant_name": None,
            "logo_url": None,
            "rating": None,
            "phone": None,
            "restaurant_website_url": None,
            "source_menu_url": None,
            "address_line": None,
            "city": None,
            "state": None,
            "postal_code": None,
            "country": None,
            "hours_text": None,
            "rewards_text": None,
            "promotions": [],
            "current_status": None,
            "online_payment_available": None,
            "online_ordering_available": None,
            "delivery_available": None,
        }.items():
            defaults.setdefault(field, default)
        for key, value in defaults.items():
            if key not in restaurant:
                restaurant[key] = value
                changed = True
        if restaurant.get("weekly_hours") != weekly_hours:
            restaurant["weekly_hours"] = weekly_hours
            changed = True
        normalized_status = normalize_editable_restaurant_status(restaurant.get("current_status"))
        if restaurant.get("current_status") != normalized_status:
            restaurant["current_status"] = normalized_status
            changed = True
        ordering_links = editable_restaurant_ordering_links_from_record(restaurant)
        social_links = normalize_editable_restaurant_social_links(
            restaurant.get("social_links") or restaurant.get("social_urls") or []
        )
        compatibility_providers = [
            {
                "provider": item["provider"],
                "provider_name": item.get("provider_name") or EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS[item["provider"]],
                "provider_type": "ordering_provider",
                "website_url": item["url"],
                "is_active": item["is_active"],
                **({"source_url": item["source_url"]} if item.get("source_url") else {}),
            }
            for item in ordering_links
        ]
        for field, normalized_value in (
            ("social_links", social_links),
            ("social_urls", [item["url"] for item in social_links]),
            ("ordering_delivery_links", ordering_links),
        ):
            if restaurant.get(field) != normalized_value:
                restaurant[field] = normalized_value
                changed = True
        if "ordering_provider_urls" not in restaurant:
            restaurant["ordering_provider_urls"] = [item["url"] for item in ordering_links]
            changed = True
        if "ordering_providers" not in restaurant:
            restaurant["ordering_providers"] = compatibility_providers
            changed = True
    return changed


def editable_restaurant_menu_for(payload, restaurant_id, preferred_menu_id=""):
    payload = payload if isinstance(payload, dict) else {}
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    preferred_menu_id = clean_recipe_menu_text(preferred_menu_id)
    if preferred_menu_id:
        preferred = menu_store_service.find_menu(payload, preferred_menu_id) or {}
        if clean_recipe_menu_text(preferred.get("restaurant_id")) == restaurant_id:
            return preferred
    menus = [
        menu
        for menu in payload.get("menus", [])
        if clean_recipe_menu_text(menu.get("restaurant_id")) == restaurant_id
    ]
    return sorted(
        menus,
        key=lambda menu: (
            0 if clean_recipe_menu_text(menu.get("source_url")) else 1,
            clean_recipe_menu_text(menu.get("created_at")),
            clean_recipe_menu_text(menu.get("id")),
        ),
    )[0] if menus else {}


def editable_restaurant_structured_hours(value):
    """Compatibility wrapper around the shared canonical hours codec."""
    return parse_weekly_hours_text(value)


def editable_menu_source_option_from_records(restaurant, menu):
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    menu = menu if isinstance(menu, dict) else {}
    restaurant_id = clean_recipe_menu_text(
        restaurant.get("id")
        or menu.get("restaurant_id")
    )
    menu_id = clean_recipe_menu_text(menu.get("id"))
    source_menu_url = first_recipe_menu_text(
        menu.get("source_url"),
        restaurant.get("menu_url"),
        restaurant.get("source_menu_url"),
    )

    if not restaurant_id and not menu_id:
        return {}

    weekly_hours = normalize_weekly_hours(restaurant.get("weekly_hours"))
    hours_notes = clean_recipe_menu_text(restaurant.get("hours_notes"))
    editor_hours_text = weekly_hours_to_text(weekly_hours, hours_notes) if weekly_hours else clean_recipe_menu_text(
        restaurant.get("hours_text")
    )
    LOGGER.debug(
        "restaurant_hours_hydration restaurant_id=%s persisted_days=%d editor_text=%s",
        restaurant_id,
        len(weekly_hours),
        bool(editor_hours_text),
    )

    return {
        "value": editable_menu_source_option_value(restaurant_id, menu_id),
        "id": restaurant_id,
        "restaurant_id": restaurant_id,
        "menu_id": menu_id,
        "label": editable_menu_source_option_label(restaurant, menu),
        "menu_title": clean_recipe_menu_text(menu.get("menu_title")),
        "restaurant_name": clean_recipe_menu_text(restaurant.get("restaurant_name")),
        "restaurant_website_url": clean_recipe_menu_text(
            restaurant.get("restaurant_website_url") or restaurant.get("website_url")
        ),
        "source_menu_url": source_menu_url,
        "restaurant_cuisine_tags": recipe_menu_text_list_for_editor(restaurant.get("cuisine_tags")),
        "restaurant_phone": clean_recipe_menu_text(restaurant.get("phone")),
        "restaurant_logo_url": clean_recipe_menu_text(restaurant.get("logo_url") or restaurant.get("logo")),
        "restaurant_rating": clean_recipe_menu_text(restaurant.get("rating")),
        "restaurant_street_address": first_recipe_menu_text(restaurant.get("address_line"), restaurant.get("full_address")),
        "restaurant_city": clean_recipe_menu_text(restaurant.get("city")),
        "restaurant_state": clean_recipe_menu_text(restaurant.get("state") or restaurant.get("state_or_region")),
        "restaurant_postal_code": clean_recipe_menu_text(restaurant.get("postal_code")),
        "restaurant_country": clean_recipe_menu_text(restaurant.get("country")),
        "restaurant_address": editable_restaurant_location(restaurant),
        "restaurant_hours_text": editor_hours_text,
        "restaurant_weekly_hours": weekly_hours,
        "restaurant_hours_notes": hours_notes,
        "restaurant_raw_hours_data": clean_recipe_menu_text(restaurant.get("raw_hours_data")),
        "restaurant_current_status": normalize_editable_restaurant_status(restaurant.get("current_status")),
        "restaurant_promotions": "\n".join(dict.fromkeys(filter(None, (
            clean_recipe_menu_text(restaurant.get("rewards_text")),
            recipe_menu_text_list_for_editor(restaurant.get("promotions")),
        )))),
        "restaurant_rewards_program": clean_recipe_menu_text(restaurant.get("rewards_text")),
        "restaurant_active_promotions": (
            restaurant.get("promotions") if isinstance(restaurant.get("promotions"), list) else []
        ),
        "restaurant_online_payment_available": recipe_menu_bool_for_editor(
            first_recipe_menu_text(
                restaurant.get("online_payment_available") if restaurant else None,
                restaurant.get("online_payment") if restaurant else None,
            ),
        ),
        "restaurant_delivery_available": recipe_menu_bool_for_editor(
            first_recipe_menu_text(
                restaurant.get("delivery_available") if restaurant else None,
                restaurant.get("delivery") if restaurant else None,
            ),
        ),
        "restaurant_online_ordering_available": recipe_menu_bool_for_editor(restaurant.get("online_ordering_available")),
        "restaurant_pickup_available": recipe_menu_bool_for_editor(restaurant.get("pickup_available")),
        "restaurant_reservation_available": recipe_menu_bool_for_editor(restaurant.get("reservation_available")),
        "restaurant_latitude": clean_recipe_menu_text(restaurant.get("latitude")),
        "restaurant_longitude": clean_recipe_menu_text(restaurant.get("longitude")),
        "restaurant_rating_count": clean_recipe_menu_text(restaurant.get("rating_count")),
        "restaurant_social_links": restaurant.get("social_links") if isinstance(restaurant.get("social_links"), list) else [],
        "restaurant_social_urls": restaurant.get("social_urls") if isinstance(restaurant.get("social_urls"), list) else [],
        "restaurant_ordering_links": editable_restaurant_ordering_links_from_record(restaurant),
        "restaurant_ordering_provider_urls": restaurant.get("ordering_provider_urls") if isinstance(restaurant.get("ordering_provider_urls"), list) else [],
        "restaurant_ordering_providers": restaurant.get("ordering_providers") if isinstance(restaurant.get("ordering_providers"), list) else [],
        "restaurant_allergy_information_note": clean_recipe_menu_text(restaurant.get("allergy_information_note")),
        "restaurant_note_text": clean_recipe_menu_text(restaurant.get("restaurant_note") or restaurant.get("restaurant_notes")),
        "restaurant_information_locked_fields": restaurant.get("restaurant_information_locked_fields") if isinstance(restaurant.get("restaurant_information_locked_fields"), list) else [],
        "restaurant_information_last_scanned_at": clean_recipe_menu_text(restaurant.get("restaurant_information_last_scanned_at")),
        "created_at": clean_recipe_menu_text(restaurant.get("created_at") or restaurant.get("imported_at")),
        "updated_at": clean_recipe_menu_text(restaurant.get("updated_at")),
    }


def editable_restaurant_url_domain(value):
    try:
        hostname = (urlparse(clean_recipe_menu_text(value)).hostname or "").casefold()
    except ValueError:
        return ""
    return hostname.removeprefix("www.")


def editable_restaurant_match_text(value):
    return re.sub(r"[^a-z0-9]+", " ", clean_recipe_menu_text(value).casefold()).strip()


def editable_restaurant_phone_key(value):
    digits = re.sub(r"\D+", "", clean_recipe_menu_text(value))
    return digits[-10:] if len(digits) >= 10 else digits


def editable_restaurant_candidate_from_values(values):
    values = values if isinstance(values, dict) else {}
    return {
        "restaurant_name": clean_recipe_menu_text(values.get("restaurant_name") or values.get("name")),
        "restaurant_website_url": clean_recipe_menu_text(
            values.get("restaurant_website_url") or values.get("website_url")
        ),
        "source_menu_url": clean_recipe_menu_text(
            values.get("source_menu_url") or values.get("menu_url")
        ),
        "phone": clean_recipe_menu_text(values.get("restaurant_phone") or values.get("phone")),
        "address_line": clean_recipe_menu_text(
            values.get("restaurant_street_address") or values.get("address_line")
        ),
        "city": clean_recipe_menu_text(values.get("restaurant_city") or values.get("city")),
        "state": clean_recipe_menu_text(
            values.get("restaurant_state") or values.get("state") or values.get("state_or_region")
        ),
    }


def editable_restaurant_duplicate_reasons(candidate, restaurant):
    candidate = candidate if isinstance(candidate, dict) else {}
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    reasons = []
    candidate_name = editable_restaurant_match_text(candidate.get("restaurant_name"))
    restaurant_name = editable_restaurant_match_text(restaurant.get("restaurant_name"))
    if candidate_name and candidate_name == restaurant_name:
        reasons.append("restaurant_name")

    candidate_domain = editable_restaurant_url_domain(candidate.get("restaurant_website_url"))
    restaurant_domain = editable_restaurant_url_domain(restaurant.get("restaurant_website_url"))
    if candidate_domain and candidate_domain == restaurant_domain:
        reasons.append("website_domain")

    candidate_phone = editable_restaurant_phone_key(candidate.get("phone"))
    restaurant_phone = editable_restaurant_phone_key(restaurant.get("phone"))
    if len(candidate_phone) >= 7 and candidate_phone == restaurant_phone:
        reasons.append("phone")

    candidate_address = editable_restaurant_match_text(candidate.get("address_line"))
    restaurant_address = editable_restaurant_match_text(
        restaurant.get("address_line") or restaurant.get("full_address")
    )
    if candidate_address and candidate_address == restaurant_address:
        reasons.append("street_address")

    candidate_city_state = "|".join(filter(None, (
        editable_restaurant_match_text(candidate.get("city")),
        editable_restaurant_match_text(candidate.get("state")),
    )))
    restaurant_city_state = "|".join(filter(None, (
        editable_restaurant_match_text(restaurant.get("city")),
        editable_restaurant_match_text(restaurant.get("state") or restaurant.get("state_or_region")),
    )))
    if candidate_city_state and candidate_city_state == restaurant_city_state:
        reasons.append("city_state")

    candidate_menu = menu_store_service.menu_source_identity_key(candidate.get("source_menu_url"))
    restaurant_menu = menu_store_service.menu_source_identity_key(
        restaurant.get("menu_url") or restaurant.get("source_menu_url")
    )
    if candidate_menu and candidate_menu == restaurant_menu:
        reasons.append("menu_url")
    return reasons


def editable_restaurant_duplicate_candidates(payload, values, exclude_restaurant_id=""):
    payload = payload if isinstance(payload, dict) else {}
    candidate = editable_restaurant_candidate_from_values(values)
    exclude_restaurant_id = clean_recipe_menu_text(exclude_restaurant_id)
    matches = []
    for restaurant in payload.get("restaurants", []):
        restaurant_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
        if not restaurant_id or restaurant_id == exclude_restaurant_id:
            continue
        reasons = editable_restaurant_duplicate_reasons(candidate, restaurant)
        strong = bool(set(reasons) & {"phone", "street_address", "menu_url"})
        strong = strong or "restaurant_name" in reasons or (
            "website_domain" in reasons and "city_state" in reasons
        )
        if not strong:
            continue
        menu = editable_restaurant_menu_for(payload, restaurant_id)
        option = editable_menu_source_option_from_records(restaurant, menu)
        option["duplicate_reasons"] = reasons
        matches.append(option)
    return sorted(matches, key=lambda item: (
        editable_restaurant_match_text(item.get("restaurant_name")),
        clean_recipe_menu_text(item.get("restaurant_id")),
    ))


def validate_editable_restaurant_values(values):
    values = values if isinstance(values, dict) else {}
    name = clean_recipe_menu_text(values.get("restaurant_name"))
    if not name:
        return "Restaurant Name is required."

    rating = clean_recipe_menu_text(values.get("restaurant_rating"))
    if rating:
        try:
            numeric_rating = float(rating)
        except ValueError:
            return "Rating must be a number between 0 and 5."
        if numeric_rating < 1 or numeric_rating > 5:
            return "Rating must be between 1 and 5."

    rating_count = clean_recipe_menu_text(values.get("restaurant_rating_count"))
    if rating_count:
        try:
            numeric_rating_count = int(rating_count)
        except ValueError:
            return "Rating Count must be a whole number."
        if numeric_rating_count < 0:
            return "Rating Count cannot be negative."

    for field, label, minimum, maximum in (
        ("restaurant_latitude", "Latitude", -90, 90),
        ("restaurant_longitude", "Longitude", -180, 180),
    ):
        value = clean_recipe_menu_text(values.get(field))
        if not value:
            continue
        try:
            coordinate = float(value)
        except ValueError:
            return f"{label} must be a number."
        if coordinate < minimum or coordinate > maximum:
            return f"{label} must be between {minimum} and {maximum}."

    for field, label in (
        ("restaurant_website_url", "Website URL"),
        ("source_menu_url", "Menu URL"),
        ("menu_item_url", "Menu Item URL"),
        ("restaurant_logo_url", "Restaurant Logo URL"),
    ):
        value = clean_recipe_menu_text(values.get(field))
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"{label} must be a valid http or https URL."

    social_links = normalize_editable_restaurant_social_links(values.get("restaurant_social_links"))
    for link in social_links:
        parsed = urlparse(link.get("url") or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Each Social Link must be a valid http or https URL."

    raw_ordering_links = parse_recipe_menu_json_list(values.get("restaurant_ordering_links"))
    seen_ordering_urls = set()
    seen_ordering_providers = set()
    for item in raw_ordering_links:
        item = item if isinstance(item, dict) else {"url": item}
        url = clean_recipe_menu_text(item.get("url") or item.get("website_url") or item.get("href"))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Each Ordering & Delivery Link must be a valid http or https URL."
        provider = re.sub(
            r"[\s-]+", "_", clean_recipe_menu_text(
                item.get("provider") or item.get("provider_key") or item.get("provider_name")
            ).casefold()
        )
        if provider not in EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS:
            provider = editable_restaurant_ordering_provider_for_url(url) or "other"
        url_key = url.casefold()
        if url_key in seen_ordering_urls:
            return "Each Ordering & Delivery Link URL may only be listed once."
        if provider != "other" and provider in seen_ordering_providers:
            return f"{EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS[provider]} may only be listed once."
        seen_ordering_urls.add(url_key)
        if provider != "other":
            seen_ordering_providers.add(provider)

    for url in split_recipe_menu_text_list(values.get("restaurant_ordering_provider_urls")):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Each Ordering Provider URL must be a valid http or https URL."
    return ""


def apply_editable_restaurant_values(restaurant, values):
    """Update shared normalized fields only; recipe-specific URLs are excluded."""
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    values = values if isinstance(values, dict) else {}
    now = menu_store_service.utc_now_iso()
    restaurant_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
    restaurant["id"] = restaurant_id
    restaurant["restaurant_id"] = restaurant_id
    restaurant.setdefault("created_at", restaurant.get("imported_at") or now)
    for key, value in editable_restaurant_owner_fields().items():
        restaurant.setdefault(key, value)

    field_map = {
        "restaurant_name": "restaurant_name",
        "restaurant_rating": "rating",
        "restaurant_phone": "phone",
        "restaurant_website_url": "restaurant_website_url",
        "restaurant_street_address": "address_line",
        "restaurant_city": "city",
        "restaurant_state": "state",
        "restaurant_postal_code": "postal_code",
        "restaurant_country": "country",
        "restaurant_note_text": "restaurant_note",
        "restaurant_allergy_information_note": "allergy_information_note",
    }
    for source_field, store_field in field_map.items():
        if source_field in values:
            restaurant[store_field] = clean_recipe_menu_text(values.get(source_field)) or None
    if "restaurant_current_status" in values:
        restaurant["current_status"] = normalize_editable_restaurant_status(
            values.get("restaurant_current_status")
        )

    restaurant["full_address"] = None
    restaurant["state_or_region"] = restaurant.get("state")
    restaurant["website_url"] = restaurant.get("restaurant_website_url")
    source_menu_url = clean_recipe_menu_text(values.get("source_menu_url")) if "source_menu_url" in values else clean_recipe_menu_text(
        restaurant.get("menu_url") or restaurant.get("source_menu_url")
    )
    restaurant["source_menu_url"] = source_menu_url or None
    restaurant["menu_url"] = source_menu_url or None

    legacy_promotions_supplied = "restaurant_promotions" in values
    if "restaurant_rewards_program" in values:
        restaurant["rewards_text"] = clean_recipe_menu_text(values.get("restaurant_rewards_program")) or None
    elif legacy_promotions_supplied:
        restaurant["rewards_text"] = clean_recipe_menu_text(values.get("restaurant_promotions")) or None
    if "restaurant_active_promotions" in values:
        restaurant["promotions"] = split_recipe_menu_text_list(values.get("restaurant_active_promotions"))
    elif legacy_promotions_supplied and "restaurant_rewards_program" not in values:
        restaurant["promotions"] = split_recipe_menu_text_list(values.get("restaurant_promotions"))
    rewards_promotions = [
        clean_recipe_menu_text(restaurant.get("rewards_text")),
        recipe_menu_text_list_for_editor(restaurant.get("promotions")),
    ]
    restaurant["rewards_promotions"] = "\n".join(value for value in rewards_promotions if value) or None

    if "restaurant_rating_count" in values:
        rating_count = clean_recipe_menu_text(values.get("restaurant_rating_count"))
        restaurant["rating_count"] = int(rating_count) if rating_count else None
    for source_field, store_field in (
        ("restaurant_latitude", "latitude"),
        ("restaurant_longitude", "longitude"),
    ):
        if source_field in values:
            coordinate = clean_recipe_menu_text(values.get(source_field))
            restaurant[store_field] = float(coordinate) if coordinate else None

    legacy_ordering_from_social = []
    if "restaurant_social_links" in values:
        raw_social_links = parse_recipe_menu_json_list(values.get("restaurant_social_links"))
        legacy_ordering_from_social = [
            item for item in raw_social_links
            if editable_restaurant_ordering_provider_for_url(item.get("url") if isinstance(item, dict) else item)
        ]
        social_links = normalize_editable_restaurant_social_links(raw_social_links)
        restaurant["social_links"] = social_links
        restaurant["social_urls"] = [item["url"] for item in social_links]
    ordering_fields_supplied = any(field in values for field in (
        "restaurant_ordering_links", "restaurant_ordering_provider_urls", "restaurant_ordering_providers"
    )) or bool(legacy_ordering_from_social)
    if ordering_fields_supplied:
        ordering_values = []
        ordering_values.extend(parse_recipe_menu_json_list(values.get("restaurant_ordering_links")))
        ordering_values.extend(parse_recipe_menu_json_list(values.get("restaurant_ordering_providers")))
        ordering_values.extend(parse_recipe_menu_json_list(values.get("restaurant_ordering_provider_urls")))
        ordering_values.extend(legacy_ordering_from_social)
        ordering_links = normalize_editable_restaurant_ordering_links(ordering_values)
        restaurant["ordering_delivery_links"] = ordering_links
        restaurant["ordering_provider_urls"] = [item["url"] for item in ordering_links]
        restaurant["ordering_providers"] = [
            {
                "provider": item["provider"],
                "provider_name": item.get("provider_name") or EDITABLE_RESTAURANT_ORDERING_PROVIDER_LABELS[item["provider"]],
                "provider_type": "ordering_provider",
                "website_url": item["url"],
                "is_active": item["is_active"],
                **({"source_url": item["source_url"]} if item.get("source_url") else {}),
            }
            for item in ordering_links
        ]

    if "restaurant_online_payment_available" in values:
        restaurant["online_payment_available"] = parse_recipe_menu_bool(values.get("restaurant_online_payment_available"))
    if "restaurant_online_ordering_available" in values:
        restaurant["online_ordering_available"] = parse_recipe_menu_bool(values.get("restaurant_online_ordering_available"))
    if "restaurant_pickup_available" in values:
        restaurant["pickup_available"] = parse_recipe_menu_bool(values.get("restaurant_pickup_available"))
    if "restaurant_delivery_available" in values:
        restaurant["delivery_available"] = parse_recipe_menu_bool(values.get("restaurant_delivery_available"))
    if "restaurant_reservation_available" in values:
        restaurant["reservation_available"] = parse_recipe_menu_bool(values.get("restaurant_reservation_available"))
    restaurant["online_payment"] = restaurant.get("online_payment_available")
    restaurant["online_ordering"] = restaurant.get("online_ordering_available")
    restaurant["pickup"] = restaurant.get("pickup_available")
    restaurant["delivery"] = restaurant.get("delivery_available")
    restaurant["reservations"] = restaurant.get("reservation_available")

    structured_hours_supplied = "restaurant_weekly_hours" in values
    legacy_hours_supplied = "restaurant_hours_text" in values
    if structured_hours_supplied:
        weekly_hours = normalize_weekly_hours(values.get("restaurant_weekly_hours"))
        notes = clean_recipe_menu_text(
            values.get("restaurant_hours_notes")
            if "restaurant_hours_notes" in values
            else restaurant.get("hours_notes")
        )
        restaurant["weekly_hours"] = weekly_hours
        restaurant["hours_notes"] = notes or None
        restaurant["hours_text"] = weekly_hours_to_text(weekly_hours, notes) or None
    elif legacy_hours_supplied:
        legacy_hours = str(values.get("restaurant_hours_text") or "").strip()
        weekly_hours, notes = editable_restaurant_structured_hours(legacy_hours)
        if weekly_hours:
            restaurant["weekly_hours"] = weekly_hours
            restaurant["hours_notes"] = clean_recipe_menu_text(
                values.get("restaurant_hours_notes") if "restaurant_hours_notes" in values else notes
            ) or None
            restaurant["hours_text"] = weekly_hours_to_text(
                weekly_hours, restaurant.get("hours_notes")
            ) or None
        if legacy_hours and not clean_recipe_menu_text(restaurant.get("raw_hours_data")):
            restaurant["raw_hours_data"] = legacy_hours
    if "restaurant_raw_hours_data" in values:
        restaurant["raw_hours_data"] = clean_recipe_menu_text(values.get("restaurant_raw_hours_data")) or None

    LOGGER.debug(
        "restaurant_save_payload restaurant_id=%s structured_hours=%s legacy_hours=%s status=%s online_ordering=%s online_payment=%s pickup=%s delivery=%s",
        restaurant_id,
        structured_hours_supplied,
        legacy_hours_supplied,
        "restaurant_current_status" in values,
        "restaurant_online_ordering_available" in values,
        "restaurant_online_payment_available" in values,
        "restaurant_pickup_available" in values,
        "restaurant_delivery_available" in values,
    )

    previous_logo_path = clean_recipe_menu_text(restaurant.get("logo_path"))
    logo_data_url = clean_recipe_menu_text(values.get("restaurant_logo_data_url"))
    logo_action = clean_recipe_menu_text(values.get("restaurant_logo_action")).lower()
    if not logo_action:
        logo_action = "url" if "restaurant_logo_url" in values else "keep"
    if logo_action == "upload" and logo_data_url:
        logo_path, logo_url = save_editable_restaurant_logo_data(restaurant_id, logo_data_url)
        restaurant["logo_path"] = str(logo_path)
        restaurant["logo_url"] = logo_url
    elif logo_action == "remove":
        restaurant["logo_url"] = None
        restaurant["logo_path"] = None
    elif logo_action == "url":
        restaurant["logo_url"] = clean_recipe_menu_text(values.get("restaurant_logo_url")) or None
        restaurant["logo_path"] = None
    restaurant["logo"] = restaurant.get("logo_url")
    for key, default in {
        "restaurant_name": None,
        "rating": None,
        "rating_count": None,
        "phone": None,
        "restaurant_website_url": None,
        "website_url": None,
        "source_menu_url": None,
        "menu_url": None,
        "address_line": None,
        "city": None,
        "state": None,
        "state_or_region": None,
        "postal_code": None,
        "country": None,
        "latitude": None,
        "longitude": None,
        "weekly_hours": {},
        "hours_notes": None,
        "raw_hours_data": None,
        "hours_text": None,
        "rewards_text": None,
        "rewards_promotions": None,
        "promotions": [],
        "social_links": [],
        "social_urls": [],
        "ordering_delivery_links": [],
        "ordering_provider_urls": [],
        "ordering_providers": [],
        "allergy_information_note": None,
        "restaurant_note": None,
        "current_status": None,
        "online_payment_available": None,
        "online_payment": None,
        "online_ordering_available": None,
        "online_ordering": None,
        "pickup_available": None,
        "pickup": None,
        "delivery_available": None,
        "delivery": None,
        "reservation_available": None,
        "reservations": None,
    }.items():
        restaurant.setdefault(key, default)
    restaurant["updated_at"] = now
    return previous_logo_path


def remove_replaced_editable_restaurant_logo(previous_logo_path, restaurant):
    previous_logo_path = clean_recipe_menu_text(previous_logo_path)
    if not previous_logo_path or previous_logo_path == clean_recipe_menu_text(restaurant.get("logo_path")):
        return
    try:
        previous_path = Path(previous_logo_path).resolve()
        if RESTAURANT_LOGO_UPLOAD_FOLDER.resolve() in previous_path.parents:
            previous_path.unlink(missing_ok=True)
    except OSError:
        pass


def list_editable_restaurants(query="", limit=100):
    with menu_store_service.MENU_STORE_LOCK:
        payload = menu_store_service.load_menu_store()
        if normalize_editable_restaurant_store_metadata(payload):
            menu_store_service.save_menu_store(payload)
    query_key = editable_restaurant_match_text(query)
    restaurants = []
    for restaurant in payload.get("restaurants", []):
        restaurant_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
        if not restaurant_id:
            continue
        menu = editable_restaurant_menu_for(payload, restaurant_id)
        option = editable_menu_source_option_from_records(restaurant, menu)
        searchable = editable_restaurant_match_text(" ".join(filter(None, (
            option.get("restaurant_name"),
            option.get("restaurant_city"),
            option.get("restaurant_state"),
            option.get("restaurant_street_address"),
            editable_restaurant_url_domain(option.get("restaurant_website_url")),
        ))))
        if query_key and query_key not in searchable:
            continue
        restaurants.append(option)
    restaurants.sort(key=lambda item: (
        editable_restaurant_match_text(item.get("restaurant_name")),
        editable_restaurant_match_text(item.get("restaurant_address")),
    ))
    try:
        limit = max(1, min(250, int(limit or 100)))
    except (TypeError, ValueError):
        limit = 100
    return {"ok": True, "restaurants": restaurants[:limit], "count": len(restaurants)}


def get_editable_restaurant(restaurant_id):
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    with menu_store_service.MENU_STORE_LOCK:
        payload = menu_store_service.load_menu_store()
        if normalize_editable_restaurant_store_metadata(payload):
            menu_store_service.save_menu_store(payload)
    restaurant = menu_store_service.restaurant_for(payload, restaurant_id)
    if not restaurant:
        return {"ok": False, "error": "Restaurant source was not found."}
    menu = editable_restaurant_menu_for(payload, restaurant_id)
    return {"ok": True, "restaurant": editable_menu_source_option_from_records(restaurant, menu)}


def editable_restaurant_logo_file_path(restaurant_id):
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    if not restaurant_id:
        return None
    store = menu_store_service.load_menu_store()
    restaurant = menu_store_service.restaurant_for(store, restaurant_id)
    raw_path = clean_recipe_menu_text((restaurant or {}).get("logo_path"))
    if not raw_path:
        return None
    try:
        path = Path(raw_path).resolve()
        root = RESTAURANT_LOGO_UPLOAD_FOLDER.resolve()
    except (OSError, RuntimeError):
        return None
    return path if path.is_file() and root in path.parents else None


def save_editable_restaurant_logo_data(restaurant_id, data_url):
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)", str(data_url or "").strip())
    if not match:
        raise ValueError("Choose a PNG, JPG, JPEG, or WebP logo image.")
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("The selected logo image could not be read.") from exc
    if not payload or len(payload) > 5 * 1024 * 1024:
        raise ValueError("Restaurant logos must be 5 MB or smaller.")
    mime_type = match.group(1)
    valid_signature = (
        (mime_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"))
        or (mime_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff"))
        or (mime_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP")
    )
    if not valid_signature:
        raise ValueError("The selected file is not a valid PNG, JPG, JPEG, or WebP image.")
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
    RESTAURANT_LOGO_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    path = RESTAURANT_LOGO_UPLOAD_FOLDER / f"{safe_filename(restaurant_id)}_{uuid.uuid4().hex}{extension}"
    path.write_bytes(payload)
    return path, f"/restaurant_source_logo?restaurant_id={quote(restaurant_id, safe='')}&v={path.stat().st_mtime_ns}"


def create_editable_restaurant(values, create_anyway=False):
    values = values if isinstance(values, dict) else {}
    error = validate_editable_restaurant_values(values)
    if error:
        return {"ok": False, "error": error}
    with menu_store_service.MENU_STORE_LOCK:
        store = menu_store_service.load_menu_store()
        duplicates = editable_restaurant_duplicate_candidates(store, values)
        if duplicates and parse_recipe_menu_bool(create_anyway) is not True:
            return {
                "ok": False,
                "error": "A similar restaurant already exists.",
                "duplicate_detected": True,
                "duplicates": duplicates,
            }
        restaurant_id = menu_store_service.new_id("restaurant")
        restaurant = {"id": restaurant_id, "restaurant_id": restaurant_id}
        try:
            apply_editable_restaurant_values(restaurant, values)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        store["restaurants"].append(restaurant)
        menu_store_service.save_menu_store(store)
        option = editable_menu_source_option_from_records(restaurant, {})
    return {"ok": True, "created": True, "restaurant": option}


def update_editable_restaurant(restaurant_id, values, menu_id=""):
    values = values if isinstance(values, dict) else {}
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    menu_id = clean_recipe_menu_text(menu_id)
    error = validate_editable_restaurant_values(values)
    if error:
        return {"ok": False, "error": error}
    with menu_store_service.MENU_STORE_LOCK:
        store = menu_store_service.load_menu_store()
        restaurant = menu_store_service.restaurant_for(store, restaurant_id)
        if not restaurant:
            return {"ok": False, "error": "Restaurant source was not found."}
        menu = menu_store_service.find_menu(store, menu_id) if menu_id else editable_restaurant_menu_for(
            store, restaurant_id
        )
        if menu and clean_recipe_menu_text(menu.get("restaurant_id")) != restaurant_id:
            return {"ok": False, "error": "The selected menu does not belong to this restaurant."}
        try:
            previous_logo_path = apply_editable_restaurant_values(restaurant, values)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if menu and "source_menu_url" in values:
            menu["source_url"] = clean_recipe_menu_text(values.get("source_menu_url")) or None
            menu["updated_at"] = restaurant["updated_at"]
        menu_store_service.save_menu_store(store)
        option = editable_menu_source_option_from_records(restaurant, menu)
    remove_replaced_editable_restaurant_logo(previous_logo_path, restaurant)
    return {"ok": True, "created": False, "restaurant": option}


def assign_editable_restaurant_to_recipe(recipe_url, restaurant_id, menu_id="", menu_item_url=None):
    recipe_url = clean_recipe_menu_text(recipe_url)
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    menu_id = clean_recipe_menu_text(menu_id)
    recipe_data = load_recipe_output(recipe_url)
    if not isinstance(recipe_data, dict):
        return {"ok": False, "error": "Recipe source was not found."}
    previous_restaurant_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
    previous_menu_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "menu_id"))
    association_changed = previous_restaurant_id != restaurant_id or (menu_id and menu_id != previous_menu_id)
    recipe_data["restaurant_id"] = restaurant_id
    metadata = recipe_menu_source_metadata(recipe_data)
    if metadata:
        metadata["restaurant_id"] = restaurant_id

    if menu_id:
        recipe_data["menu_id"] = menu_id
        if metadata:
            metadata["menu_id"] = menu_id
    elif previous_restaurant_id != restaurant_id:
        recipe_data.pop("menu_id", None)
        if metadata:
            metadata.pop("menu_id", None)

    if association_changed and previous_menu_id != menu_id:
        for field in ("menu_section_id", "menu_item_id"):
            recipe_data.pop(field, None)
            if metadata:
                metadata.pop(field, None)

    if menu_item_url is not None:
        normalized_item_url = clean_recipe_menu_text(menu_item_url)
        if normalized_item_url:
            recipe_data["menu_item_url"] = normalized_item_url
        else:
            recipe_data.pop("menu_item_url", None)
    stored_source_url = clean_recipe_menu_text(recipe_data.get("source_url")) or recipe_url
    save_recipe_output(stored_source_url, recipe_data)
    return {"ok": True, "association_changed": association_changed, "recipe": recipe_data}


def update_editable_restaurant_source(recipe_url, values):
    values = values if isinstance(values, dict) else {}
    recipe_url = clean_recipe_menu_text(recipe_url)
    action = clean_recipe_menu_text(values.get("action") or "update").lower()
    if action not in {"create", "update"}:
        return {"ok": False, "error": "Restaurant action must be create or update."}
    recipe_data = load_recipe_output(recipe_url)
    if not isinstance(recipe_data, dict):
        return {"ok": False, "error": "Recipe source was not found."}

    current_restaurant_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
    menu_id = clean_recipe_menu_text(values.get("menu_id"))
    if action == "create":
        saved = create_editable_restaurant(values, create_anyway=values.get("create_anyway"))
        if not saved.get("ok"):
            return saved
        restaurant_id = clean_recipe_menu_text(saved.get("restaurant", {}).get("restaurant_id"))
        menu_id = ""
    else:
        restaurant_id = clean_recipe_menu_text(values.get("restaurant_id"))
        if not restaurant_id:
            return {"ok": False, "error": "Restaurant source is required."}
        if (
            current_restaurant_id != restaurant_id
            and parse_recipe_menu_bool(values.get("assign_restaurant")) is not True
        ):
            return {"ok": False, "error": "This restaurant is not linked to the current recipe."}
        saved = update_editable_restaurant(restaurant_id, values, menu_id=menu_id)
        if not saved.get("ok"):
            return saved

    assigned = assign_editable_restaurant_to_recipe(
        recipe_url,
        restaurant_id,
        menu_id=menu_id,
        menu_item_url=values.get("menu_item_url") if "menu_item_url" in values else None,
    )
    if not assigned.get("ok"):
        return assigned
    option = saved.get("restaurant", {})
    option["menu_item_url"] = clean_recipe_menu_text(assigned.get("recipe", {}).get("menu_item_url"))
    return {
        "ok": True,
        "created": bool(saved.get("created")),
        "association_changed": bool(assigned.get("association_changed")),
        "restaurant": option,
    }


def update_editable_source_documents(recipe_url, values):
    values = values if isinstance(values, dict) else {}
    recipe_url = clean_recipe_menu_text(recipe_url)
    if not recipe_url:
        return {"ok": False, "error": "Recipe URL is required."}
    fields = {
        "document_source_url": clean_recipe_menu_text(values.get("document_source_url")),
        "source_menu_url": clean_recipe_menu_text(values.get("source_menu_url")),
        "menu_item_url": clean_recipe_menu_text(values.get("menu_item_url")),
    }
    for field, label in (("document_source_url", "Source URL"), ("source_menu_url", "Source Menu URL"), ("menu_item_url", "Menu Item URL")):
        value = fields[field]
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "error": f"{label} must be a valid HTTP or HTTPS URL."}

    recipe_data = load_recipe_output(recipe_url)
    if not isinstance(recipe_data, dict):
        return {"ok": False, "error": "Recipe source was not found."}
    stored_source_url = clean_recipe_menu_text(recipe_data.get("source_url")) or recipe_url
    for field, value in fields.items():
        if value:
            recipe_data[field] = value
        else:
            recipe_data.pop(field, None)

    menu_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "menu_id"))
    restaurant_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
    if restaurant_id and fields["source_menu_url"]:
        with menu_store_service.MENU_STORE_LOCK:
            store = menu_store_service.load_menu_store()
            menu = menu_store_service.find_menu(store, menu_id) if menu_id else {}
            if menu and clean_recipe_menu_text(menu.get("restaurant_id")) == restaurant_id:
                menu["source_url"] = fields["source_menu_url"]
                menu["updated_at"] = menu_store_service.utc_now_iso()
            restaurant = menu_store_service.restaurant_for(store, restaurant_id)
            if restaurant:
                restaurant["source_menu_url"] = fields["source_menu_url"]
                restaurant["menu_url"] = fields["source_menu_url"]
                restaurant["updated_at"] = menu_store_service.utc_now_iso()
            if menu or restaurant:
                menu_store_service.save_menu_store(store)
    save_recipe_output(stored_source_url, recipe_data)
    return {"ok": True, **fields}


def editable_restaurant_usage_recipe_records():
    """Load every distinct recipe output in the active account without UI/page limits."""
    records = []
    seen = set()
    for output_path in OUTPUT_FOLDER.glob("*.json"):
        if output_path.name == "sorted_ingredients.json":
            continue
        recipe_data = _read_recipe_output_json(output_path)
        if not isinstance(recipe_data, dict):
            continue
        metadata = recipe_menu_source_metadata(recipe_data)
        recipe_url = first_recipe_menu_text(
            recipe_data.get("source_url"),
            recipe_data.get("recipe_record_url"),
            recipe_data.get("url"),
            metadata.get("source_url"),
            metadata.get("recipe_record_url"),
        )
        stable_id = first_recipe_menu_text(
            recipe_data.get("recipe_id"),
            recipe_data.get("id"),
            metadata.get("recipe_id"),
        )
        identity = (
            f"id:{stable_id}"
            if stable_id
            else f"url:{normalize_recipe_url_key(recipe_url)}"
            if normalize_recipe_url_key(recipe_url)
            else f"file:{output_path.name.casefold()}"
        )
        if identity in seen:
            continue
        seen.add(identity)
        records.append({
            "identity": identity,
            "path": output_path,
            "data": recipe_data,
            "url": recipe_url,
        })
    return records


def editable_restaurant_usage_reference_values(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return {
        "restaurant_name": first_recipe_menu_text(
            recipe_data.get("restaurant_name"),
            metadata.get("restaurant_name"),
        ),
        "restaurant_website_url": first_recipe_menu_text(
            recipe_data.get("restaurant_website_url"),
            recipe_data.get("website_url"),
            metadata.get("restaurant_website_url"),
            metadata.get("website_url"),
        ),
        "source_menu_url": first_recipe_menu_text(
            recipe_data.get("source_menu_url"),
            recipe_data.get("menu_source_url"),
            metadata.get("source_menu_url"),
            recipe_menu_source_url_from_candidates(recipe_data),
        ),
        "phone": first_recipe_menu_text(recipe_data.get("restaurant_phone"), metadata.get("restaurant_phone")),
        "address_line": first_recipe_menu_text(
            recipe_data.get("restaurant_street_address"),
            recipe_data.get("restaurant_address"),
            metadata.get("restaurant_street_address"),
            metadata.get("restaurant_address"),
        ),
        "city": first_recipe_menu_text(recipe_data.get("restaurant_city"), metadata.get("restaurant_city")),
        "state": first_recipe_menu_text(recipe_data.get("restaurant_state"), metadata.get("restaurant_state")),
    }


def editable_restaurant_usage_match(recipe_data, restaurant, menu=None):
    """Classify only high-confidence legacy links; ambiguous matches remain diagnostics."""
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    restaurant = restaurant if isinstance(restaurant, dict) else {}
    menu = menu if isinstance(menu, dict) else {}
    selected_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
    linked_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
    if linked_id:
        return ("normalized", ["restaurant_id"]) if linked_id == selected_id else ("other", [])

    selected_menu_key = menu_store_service.menu_source_identity_key(
        menu.get("source_url")
        or restaurant.get("source_menu_url")
        or restaurant.get("menu_url")
    )
    recipe_menu_keys = {
        menu_store_service.menu_source_identity_key(value)
        for value in (
            editable_restaurant_usage_reference_values(recipe_data).get("source_menu_url"),
            *recipe_menu_source_url_candidates(recipe_data),
        )
        if menu_store_service.menu_source_identity_key(value)
    }
    if selected_menu_key and selected_menu_key in recipe_menu_keys:
        return "legacy_clear", ["menu_url"]

    candidate = editable_restaurant_usage_reference_values(recipe_data)
    reasons = editable_restaurant_duplicate_reasons(candidate, restaurant)
    reason_set = set(reasons)
    strong = bool(reason_set & {"phone", "street_address"})
    strong = strong or "menu_url" in reason_set
    strong = strong or "restaurant_name" in reason_set and "website_domain" in reason_set
    if strong:
        return "legacy_clear", reasons
    if reason_set & {"restaurant_name", "website_domain", "city_state"}:
        return "legacy_ambiguous", reasons
    return "unrelated", []


def editable_restaurant_duplicate_candidates_for_usage(store, restaurant):
    selected_id = clean_recipe_menu_text(restaurant.get("id") or restaurant.get("restaurant_id"))
    values = {
        "restaurant_name": restaurant.get("restaurant_name"),
        "restaurant_website_url": restaurant.get("restaurant_website_url") or restaurant.get("website_url"),
        "source_menu_url": restaurant.get("source_menu_url") or restaurant.get("menu_url"),
        "restaurant_phone": restaurant.get("phone"),
        "restaurant_street_address": restaurant.get("address_line") or restaurant.get("full_address"),
        "restaurant_city": restaurant.get("city"),
        "restaurant_state": restaurant.get("state") or restaurant.get("state_or_region"),
    }
    return editable_restaurant_duplicate_candidates(store, values, exclude_restaurant_id=selected_id)


def editable_restaurant_usage_inventory(restaurant_id):
    restaurant_id = clean_recipe_menu_text(restaurant_id)
    if not restaurant_id:
        return {"ok": False, "error": "Restaurant source is required."}
    if has_request_context():
        cache = getattr(g, "_editable_restaurant_usage_inventories", None)
        if isinstance(cache, dict) and restaurant_id in cache:
            return cache[restaurant_id]
    store = menu_store_service.load_menu_store()
    restaurant = menu_store_service.restaurant_for(store, restaurant_id)
    if not restaurant:
        return {"ok": False, "error": "Restaurant source was not found."}
    menu = editable_restaurant_menu_for(store, restaurant_id)
    buckets = {"normalized": [], "legacy_clear": [], "legacy_ambiguous": [], "duplicate_linked": []}
    duplicate_candidates = editable_restaurant_duplicate_candidates_for_usage(store, restaurant)
    duplicate_ids = {clean_recipe_menu_text(item.get("restaurant_id")) for item in duplicate_candidates}
    duplicate_records = [
        menu_store_service.restaurant_for(store, duplicate_id)
        for duplicate_id in duplicate_ids
        if duplicate_id
    ]
    cookbook_ids = set()
    for record in editable_restaurant_usage_recipe_records():
        recipe_data = record["data"]
        match_kind, reasons = editable_restaurant_usage_match(recipe_data, restaurant, menu=menu)
        linked_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
        if match_kind == "legacy_clear" and any(
            editable_restaurant_usage_match(recipe_data, duplicate_record, menu=editable_restaurant_menu_for(
                store,
                clean_recipe_menu_text(duplicate_record.get("id") or duplicate_record.get("restaurant_id")),
            ))[0] == "legacy_clear"
            for duplicate_record in duplicate_records
            if isinstance(duplicate_record, dict)
        ):
            match_kind = "legacy_ambiguous"
            reasons = [*reasons, "duplicate_restaurant_candidate"]
        if match_kind == "other" and linked_id in duplicate_ids:
            match_kind = "duplicate_linked"
            reasons = ["duplicate_restaurant_id"]
        if match_kind not in buckets:
            continue
        recipe_url = record["url"]
        assignment = cookbook_recipe_assignment_for_url(recipe_url) if recipe_url else {}
        cookbook_id = clean_recipe_menu_text(assignment.get("cookbook_id"))
        if match_kind in {"normalized", "legacy_clear"} and cookbook_id:
            cookbook_ids.add(cookbook_id)
        output_path = record["path"]
        buckets[match_kind].append({
            **record,
            "match_reasons": reasons,
            "cookbook_id": cookbook_id,
            "cookbook_name": clean_recipe_menu_text(assignment.get("cookbook_name")),
            "last_modified": datetime.fromtimestamp(output_path.stat().st_mtime, timezone.utc).isoformat(),
        })

    result = {
        "ok": True,
        "restaurant": restaurant,
        "menu": menu,
        "buckets": buckets,
        "cookbook_ids": cookbook_ids,
        "duplicate_candidates": duplicate_candidates,
    }
    if has_request_context():
        cache = getattr(g, "_editable_restaurant_usage_inventories", None)
        if not isinstance(cache, dict):
            cache = {}
            g._editable_restaurant_usage_inventories = cache
        cache[restaurant_id] = result
    return result


def editable_restaurant_usage_time(value):
    text = clean_recipe_menu_text(value)
    if not text:
        return ""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:min|mins|minutes)?", text, re.I)
    if not match:
        return text
    minutes = float(match.group(1))
    if minutes <= 0:
        return ""
    display = str(int(minutes)) if minutes.is_integer() else str(minutes).rstrip("0").rstrip(".")
    return f"{display} min"


def editable_restaurant_usage_calories(recipe_data):
    nutrition = recipe_data.get("nutrition") if isinstance(recipe_data, dict) else {}
    if not isinstance(nutrition, dict):
        return ""
    serving_basis = clean_recipe_menu_text(nutrition.get("serving_basis")).casefold()
    if serving_basis and "serving" not in serving_basis:
        return ""
    calories = clean_recipe_menu_text(
        nutrition.get("calories_per_serving")
        or nutrition.get("calories")
    )
    if not calories:
        return ""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:kcal|cal|calories)?", calories, re.I)
    if not match:
        return calories
    numeric = float(match.group(1))
    if numeric <= 0:
        return ""
    display = str(int(numeric)) if numeric.is_integer() else str(numeric).rstrip("0").rstrip(".")
    return f"{display} cal"


def editable_restaurant_usage_category(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    value = first_recipe_menu_text(
        recipe_data.get("meal_type"),
        recipe_data.get("menu_section"),
        recipe_data.get("section"),
        recipe_data.get("category"),
        recipe_data.get("primary_category"),
        metadata.get("menu_section"),
        metadata.get("meal_type"),
    )
    if isinstance(value, (list, tuple)):
        value = next((clean_recipe_menu_text(item) for item in value if clean_recipe_menu_text(item)), "")
    return clean_recipe_menu_text(value)


def editable_restaurant_usage_thumbnail(recipe_url, recipe_data, recipe_meta=None):
    """Build a lazy thumbnail URL without reading or generating image variants."""
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    cover_image = recipe_data.get("cover_image")
    if not isinstance(cover_image, dict) or not cover_image:
        cover_image = recipe_meta.get("cover_image")
    if not isinstance(cover_image, dict) or not cover_image:
        return {}
    normalized = normalize_recipe_cover_image(
        cover_image,
        base_url=recipe_url,
        fallback_alt=first_recipe_menu_text(recipe_data.get("recipe_title"), "Recipe image"),
    )
    if not normalized:
        return {}
    if normalized.get("path") and recipe_url:
        src = f"/recipe_cover_image?url={quote(recipe_url, safe='')}&variant=thumb"
    else:
        src = first_recipe_menu_text(
            cover_image.get("thumb_url"),
            cover_image.get("card_url"),
            normalized.get("url"),
        )
    return {
        "src": src,
        "alt": first_recipe_menu_text(normalized.get("alt"), cover_image.get("alt")),
    } if src else {}


RESTAURANT_USAGE_REVIEW_LABELS = {
    "possible_duplicate": "Possible duplicate",
    "missing_title": "Title missing",
    "missing_ingredients": "Ingredients missing",
    "missing_instructions": "Instructions missing",
    "missing_equipment": "Equipment missing",
    "missing_nutrition": "Nutrition missing",
    "missing_image": "Image missing",
    "missing_cookbook_assignment": "Cookbook missing",
    "missing_source_information": "Source missing",
    "invalid_recipe_data": "Invalid data",
    "ai_inferred_unreviewed": "Needs AI review",
    "low_confidence": "Low confidence",
    "validation_warning": "Needs review",
    "restaurant_link": "Needs restaurant link",
}


def _editable_restaurant_usage_has_items(value):
    if isinstance(value, dict):
        return any(_editable_restaurant_usage_has_items(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_editable_restaurant_usage_has_items(item) for item in value)
    if isinstance(value, bool):
        return value
    return bool(clean_recipe_menu_text(value))


def _editable_restaurant_usage_metadata_fields(recipe_data, keys):
    values = set()
    for key in keys:
        raw = recipe_data.get(key)
        if isinstance(raw, str):
            raw = raw.split(",")
        if isinstance(raw, (list, tuple, set)):
            values.update(clean_recipe_menu_text(item).casefold() for item in raw if clean_recipe_menu_text(item))
    return values


def _editable_restaurant_usage_confidence(value):
    if isinstance(value, str):
        normalized = value.strip().casefold().rstrip("%")
        if normalized in {"low", "poor", "uncertain"}:
            return 0.0
        value = normalized
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1:
        numeric /= 100
    return max(0.0, min(1.0, numeric))


def editable_restaurant_usage_review_reasons(record, recipe_meta=None, duplicate_review=None):
    """Project saved health/review signals into inexpensive list-filter reason codes."""
    record = record if isinstance(record, dict) else {}
    recipe_data = record.get("data") if isinstance(record.get("data"), dict) else {}
    recipe_meta = recipe_meta if isinstance(recipe_meta, dict) else {}
    reasons = []

    def add(code):
        if code not in reasons:
            reasons.append(code)

    if duplicate_review:
        add("possible_duplicate")
    title = first_recipe_menu_text(
        recipe_data.get("recipe_title"), recipe_data.get("menu_item_name"), recipe_data.get("display_name")
    )
    if not title:
        add("missing_title")
    if not _editable_restaurant_usage_has_items(recipe_data.get("ingredients") or recipe_meta.get("ingredients")):
        add("missing_ingredients")
    if not _editable_restaurant_usage_has_items(recipe_data.get("instructions")):
        add("missing_instructions")
    if not _editable_restaurant_usage_has_items(recipe_data.get("equipment")):
        add("missing_equipment")
    nutrition = recipe_data.get("nutrition")
    if isinstance(nutrition, dict):
        nutrition = {
            key: value
            for key, value in nutrition.items()
            if clean_recipe_menu_text(key).casefold() not in {
                "serving_basis", "source", "nutrition_source", "confidence", "confidence_score", "ai_inferred"
            }
        }
    if not _editable_restaurant_usage_has_items(nutrition):
        add("missing_nutrition")
    cover_image = recipe_data.get("cover_image") or recipe_meta.get("cover_image")
    has_image = _editable_restaurant_usage_has_items(cover_image) or bool(first_recipe_menu_text(
        recipe_data.get("cover_image_url"), recipe_data.get("image_url"), recipe_data.get("title_image_url")
    ))
    if not has_image:
        add("missing_image")
    if not first_recipe_menu_text(record.get("cookbook_id"), record.get("cookbook_name")):
        add("missing_cookbook_assignment")
    source_metadata = recipe_menu_source_metadata(recipe_data)
    if not first_recipe_menu_text(
        record.get("url"), recipe_data.get("source_url"), recipe_data.get("source_menu_url"),
        recipe_data.get("source_pdf_path"), recipe_data.get("generated_pdf_path"),
        source_metadata.get("source_url"), source_metadata.get("source_menu_url"),
    ):
        add("missing_source_information")
    if record.get("match_kind") == "legacy_clear":
        add("restaurant_link")

    validation_values = [
        recipe_data.get("validation_errors"), recipe_data.get("invalid_fields"),
        recipe_data.get("recipe_validation_errors"),
    ]
    if recipe_data.get("valid") is False or any(_editable_restaurant_usage_has_items(value) for value in validation_values):
        add("invalid_recipe_data")
    warning_values = [
        recipe_data.get("validation_warnings"), recipe_data.get("warnings"),
        recipe_data.get("recipe_health_warnings"), recipe_data.get("needs_review_fields"),
        recipe_data.get("review_required_fields"), recipe_data.get("warning_fields"),
    ]
    ingredient_review = any(
        isinstance(item, dict) and (
            item.get("warning")
            or isinstance(item.get("food_review"), dict) and (
                item["food_review"].get("needs_review")
                or clean_recipe_menu_text(item["food_review"].get("status")).casefold() == "needs_review"
            )
        )
        for item in (recipe_data.get("ingredients") or [])
    )
    if ingredient_review or any(_editable_restaurant_usage_has_items(value) for value in warning_values):
        add("validation_warning")

    inferred_fields = _editable_restaurant_usage_metadata_fields(recipe_data, (
        "ai_generated_fields", "ai_inferred_fields", "inferred_fields", "cookbook_item_inferred_fields",
    ))
    verified_fields = _editable_restaurant_usage_metadata_fields(recipe_data, (
        "user_verified_fields", "verified_fields", "confirmed_fields",
    ))
    if inferred_fields - verified_fields or (recipe_data.get("ai_inferred") is True and not inferred_fields):
        add("ai_inferred_unreviewed")

    confidence_values = [
        recipe_data.get("ai_confidence"), recipe_data.get("ai_confidence_score"),
        recipe_data.get("inference_confidence_score"), recipe_data.get("confidence_score"),
        recipe_data.get("extraction_confidence_score"), recipe_data.get("nutrition_confidence_score"),
        recipe_data.get("duplicate_detection_confidence"),
    ]
    confidences = [score for score in (_editable_restaurant_usage_confidence(value) for value in confidence_values) if score is not None]
    if confidences and min(confidences) < 0.6:
        add("low_confidence")
    return reasons


def editable_restaurant_usage_row(record, recipe_meta=None):
    recipe_data = record.get("data") if isinstance(record, dict) else {}
    recipe_url = clean_recipe_menu_text(record.get("url"))
    thumbnail = editable_restaurant_usage_thumbnail(recipe_url, recipe_data, recipe_meta)
    return {
        "title": first_recipe_menu_text(
            recipe_data.get("recipe_title"),
            recipe_data.get("menu_item_name"),
            recipe_data.get("display_name"),
            "Untitled Recipe",
        ),
        "url": recipe_url,
        "cookbook_name": clean_recipe_menu_text(record.get("cookbook_name")),
        "last_modified": clean_recipe_menu_text(record.get("last_modified")),
        "relationship_status": "linked" if record.get("match_kind") == "normalized" else "legacy_clear",
        "thumbnail_url": clean_recipe_menu_text(thumbnail.get("src")),
        "thumbnail_alt": clean_recipe_menu_text(thumbnail.get("alt")),
        "total_time": editable_restaurant_usage_time(
            recipe_data.get("total_time") or recipe_data.get("total_time_minutes")
        ),
        "calories_per_serving": editable_restaurant_usage_calories(recipe_data),
        "category_label": editable_restaurant_usage_category(recipe_data),
        "review_reason_codes": list(record.get("review_reason_codes") or []),
        "review_reason_labels": list(record.get("review_reason_labels") or []),
    }


def editable_restaurant_usage(
    restaurant_id,
    page=1,
    per_page=50,
    query="",
    current_recipe_url="",
    review_only=False,
    duplicate_review_index=None,
):
    inventory = editable_restaurant_usage_inventory(restaurant_id)
    if not inventory.get("ok"):
        return inventory
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(100, int(per_page or 50)))
    except (TypeError, ValueError):
        per_page = 50

    buckets = inventory["buckets"]
    matched_records = []
    for match_kind in ("normalized", "legacy_clear"):
        for record in buckets[match_kind]:
            matched_records.append({**record, "match_kind": match_kind})
    matched_records.sort(key=lambda item: first_recipe_menu_text(
        item["data"].get("recipe_title"), item["data"].get("menu_item_name"), "Untitled Recipe"
    ).casefold())
    recipe_count = len(matched_records)
    duplicate_review_index = duplicate_review_index if isinstance(duplicate_review_index, dict) else {}
    recipe_meta_index = load_recipe_ingredients()
    for record in matched_records:
        recipe_key = normalize_recipe_url_key(record.get("url"))
        recipe_meta = recipe_meta_index.get(recipe_key, {})
        reason_codes = editable_restaurant_usage_review_reasons(
            record,
            recipe_meta,
            duplicate_review=duplicate_review_index.get(recipe_key),
        )
        record["review_reason_codes"] = reason_codes
        record["review_reason_labels"] = [RESTAURANT_USAGE_REVIEW_LABELS[code] for code in reason_codes]
    review_recipe_count = sum(bool(record.get("review_reason_codes")) for record in matched_records)
    query_key = clean_recipe_menu_text(query).casefold()
    filtered = matched_records
    if review_only:
        filtered = [record for record in filtered if record.get("review_reason_codes")]
    if query_key:
        filtered = [record for record in filtered if query_key in " ".join((
            first_recipe_menu_text(record["data"].get("recipe_title"), record["data"].get("menu_item_name")),
            clean_recipe_menu_text(record.get("cookbook_name")),
        )).casefold()]
    start = (page - 1) * per_page
    page_records = filtered[start:start + per_page]
    current_key = normalize_recipe_url_key(current_recipe_url)
    included_current_recipe = bool(current_key) and any(
        normalize_recipe_url_key(record.get("url")) == current_key for record in matched_records
    )
    restaurant = inventory["restaurant"]
    migration_status = {
        "normalized_recipe_count": len(buckets["normalized"]),
        "legacy_possible_match_count": len(buckets["legacy_clear"]),
        "ambiguous_match_count": len(buckets["legacy_ambiguous"]),
        "duplicate_linked_recipe_count": len(buckets["duplicate_linked"]),
    }
    LOGGER.info(
        "restaurant_usage restaurant_id=%s account_id=%s normalized=%s legacy_possible=%s ambiguous=%s duplicates=%s per_page=%s cookbook_ids=%s",
        restaurant_id,
        clean_recipe_menu_text(active_user_id()) or f"guest:{clean_recipe_menu_text(active_guest_session_id())}" or "legacy",
        migration_status["normalized_recipe_count"],
        migration_status["legacy_possible_match_count"],
        migration_status["ambiguous_match_count"],
        len(inventory["duplicate_candidates"]),
        per_page,
        sorted(inventory["cookbook_ids"]),
    )
    return {
        "ok": True,
        "restaurant_id": restaurant_id,
        "restaurant_name": clean_recipe_menu_text(restaurant.get("restaurant_name")),
        "recipe_count": recipe_count,
        "cookbook_count": len(inventory["cookbook_ids"]),
        "included_current_recipe": included_current_recipe,
        "migration_status": migration_status,
        "duplicate_restaurant_count": len(inventory["duplicate_candidates"]),
        "duplicate_restaurants": inventory["duplicate_candidates"],
        "created_at": clean_recipe_menu_text(restaurant.get("created_at") or restaurant.get("imported_at")),
        "last_updated": clean_recipe_menu_text(restaurant.get("updated_at")),
        "page": page,
        "per_page": per_page,
        "filtered_recipe_count": len(filtered),
        "review_recipe_count": review_recipe_count,
        "review_only": bool(review_only),
        "has_more": start + len(page_records) < len(filtered),
        "recipes": [
            editable_restaurant_usage_row(
                record,
                recipe_meta_index.get(normalize_recipe_url_key(record.get("url")), {}),
            )
            for record in page_records
        ],
    }


def backfill_editable_restaurant_usage(restaurant_id):
    """Persist only deterministic legacy links; ambiguous records remain untouched."""
    inventory = editable_restaurant_usage_inventory(restaurant_id)
    if not inventory.get("ok"):
        return inventory
    updated = 0
    for record in inventory["buckets"]["legacy_clear"]:
        recipe_data = record["data"]
        recipe_data["restaurant_id"] = clean_recipe_menu_text(restaurant_id)
        metadata = recipe_data.get("source_metadata")
        if isinstance(metadata, dict):
            metadata["restaurant_id"] = clean_recipe_menu_text(restaurant_id)
        record["path"].write_text(json.dumps(recipe_data, indent=2, ensure_ascii=False), encoding="utf-8")
        updated += 1
    if has_request_context():
        g.pop("_recipe_edit_output_index", None)
        cache = getattr(g, "_editable_restaurant_usage_inventories", None)
        if isinstance(cache, dict):
            cache.pop(clean_recipe_menu_text(restaurant_id), None)
    result = editable_restaurant_usage(restaurant_id, page=1, per_page=50)
    result["backfilled_recipe_count"] = updated
    return result


def editable_menu_source_option_identity(option):
    option = option if isinstance(option, dict) else {}
    source_menu_url = first_recipe_menu_text(
        option.get("source_menu_url"),
        option.get("menu_source_url"),
    )
    source_menu_url = recipe_menu_source_url_from_item_url(source_menu_url) or source_menu_url
    source_key = normalize_recipe_url_key(source_menu_url)
    if source_key:
        return f"source:{source_key}"

    website_key = normalize_recipe_url_key(option.get("restaurant_website_url"))
    address_key = recipe_menu_match_text(option.get("restaurant_address"))
    name_key = recipe_menu_match_text(option.get("restaurant_name") or option.get("label"))
    if website_key:
        return f"website:{website_key}|{address_key or name_key}"
    if name_key and address_key:
        return f"place:{name_key}|{address_key}"
    return f"value:{clean_recipe_menu_text(option.get('value'))}"


def editable_menu_source_option_rank(option):
    option = option if isinstance(option, dict) else {}
    return (
        1 if clean_recipe_menu_text(option.get("menu_id")) else 0,
        1 if clean_recipe_menu_text(option.get("source_menu_url")) else 0,
        1 if clean_recipe_menu_text(option.get("restaurant_website_url")) else 0,
        len(clean_recipe_menu_text(option.get("label"))),
    )


def dedupe_editable_menu_source_options(options):
    deduped = []
    positions = {}

    for option in options or []:
        option = option if isinstance(option, dict) else {}
        identity = editable_menu_source_option_identity(option)
        if not identity or identity == "value:":
            continue
        if identity not in positions:
            positions[identity] = len(deduped)
            deduped.append(option)
            continue

        current_index = positions[identity]
        current = deduped[current_index]
        if editable_menu_source_option_rank(option) > editable_menu_source_option_rank(current):
            deduped[current_index] = option

    return deduped


def editable_menu_source_options():
    payload = menu_store_service.load_menu_store()
    restaurants = {
        restaurant.get("id"): restaurant
        for restaurant in payload.get("restaurants", [])
        if restaurant.get("id")
    }
    options = []

    for menu in payload.get("menus", []):
        restaurant = restaurants.get(menu.get("restaurant_id"), {})
        option = editable_menu_source_option_from_records(restaurant, menu)
        if option.get("value"):
            options.append(option)

    for restaurant in payload.get("restaurants", []):
        option = editable_menu_source_option_from_records(restaurant, {})
        if option.get("value"):
            options.append(option)

    return sorted(dedupe_editable_menu_source_options(options), key=lambda option: (
        recipe_menu_match_text(option.get("restaurant_name")),
        recipe_menu_match_text(option.get("source_menu_url")),
        recipe_menu_match_text(option.get("menu_title")),
    ))


def editable_menu_source_option_for_recipe(menu_metadata, options):
    menu_metadata = menu_metadata if isinstance(menu_metadata, dict) else {}
    selected_value = editable_menu_source_option_value(
        menu_metadata.get("restaurant_id"),
        menu_metadata.get("menu_id"),
    )
    for option in options or []:
        if clean_recipe_menu_text(option.get("value")) == selected_value:
            return option

    current_option = {
        "value": selected_value,
        "restaurant_id": menu_metadata.get("restaurant_id", ""),
        "menu_id": menu_metadata.get("menu_id", ""),
        "label": menu_metadata.get("restaurant_name", ""),
        "restaurant_name": menu_metadata.get("restaurant_name", ""),
        "restaurant_website_url": menu_metadata.get("restaurant_website_url", ""),
        "source_menu_url": menu_metadata.get("source_menu_url", ""),
        "restaurant_address": menu_metadata.get("restaurant_address", ""),
    }
    current_identity = editable_menu_source_option_identity(current_option)
    if not current_identity or current_identity == "value:":
        return {}

    return next(
        (
            option for option in options or []
            if editable_menu_source_option_identity(option) == current_identity
        ),
        {},
    )


def apply_editable_menu_source_option(menu_metadata, option):
    menu_metadata = dict(menu_metadata) if isinstance(menu_metadata, dict) else {}
    option = option if isinstance(option, dict) else {}
    if not option:
        return menu_metadata

    for field in (
        "restaurant_id",
        "menu_id",
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
    ):
        value = option.get(field)
        if clean_recipe_menu_text(value):
            menu_metadata[field] = value

    return menu_metadata


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
        menu.get("source_url"),
        restaurant.get("menu_url"),
        restaurant.get("source_menu_url"),
        recipe_data.get("source_menu_url"),
        recipe_data.get("menu_source_url"),
        metadata.get("source_menu_url"),
        snapshot_fields.get("source_menu_url"),
        recipe_menu_source_url_from_candidates(recipe_data),
        recipe_data.get("source_display_url") if recipe_has_menu_metadata(recipe_data) else "",
    )
    raw_menu_order_url = first_recipe_menu_text(
        recipe_data.get("menu_order_url"),
        recipe_data.get("deep_link_url"),
        metadata.get("menu_order_url"),
        metadata.get("deep_link_url"),
        item.get("menu_order_url"),
        item.get("deep_link_url"),
        snapshot_item_fields.get("menu_order_url"),
    )
    menu_order_url = (
        recipe_cartana_menu_item_order_url(
            raw_menu_order_url,
            source_menu_url,
            first_recipe_menu_text(
                recipe_menu_relation_value(recipe_data, "menu_id"),
                snapshot_item_fields.get("menu_id"),
            ),
            first_recipe_menu_text(
                recipe_menu_relation_value(recipe_data, "menu_item_id"),
                snapshot_item_fields.get("menu_item_id"),
            ),
        )
        or raw_menu_order_url
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
        "menu_order_url": menu_order_url,
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
    return any(field in payload for field in (*RESTAURANT_MENU_METADATA_FIELDS, *RESTAURANT_MENU_RELATION_FIELDS))


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

    previous_menu_id = recipe_menu_relation_value(recipe_data, "menu_id")
    relation_values = {}
    for field in RESTAURANT_MENU_RELATION_FIELDS:
        if field not in payload:
            continue
        relation_values[field] = clean_recipe_menu_text(payload.get(field))
        if relation_values[field]:
            recipe_data[field] = relation_values[field]
        else:
            recipe_data.pop(field, None)

    if (
        "menu_id" in relation_values
        and relation_values.get("menu_id") != previous_menu_id
        and "menu_item_id" not in relation_values
    ):
        recipe_data.pop("menu_item_id", None)
        recipe_data.pop("menu_section_id", None)

    payload_has_value = any(
        parse_recipe_menu_bool(payload.get(field)) is not None
        if field in {"restaurant_online_payment_available", "restaurant_delivery_available"}
        else bool(clean_recipe_menu_text(payload.get(field)))
        for field in RESTAURANT_MENU_METADATA_FIELDS
        if field in payload
    )
    if (
        not payload_has_value
        and not any(relation_values.values())
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


def embedded_restaurant_values_for_backfill(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    metadata = recipe_menu_source_metadata(recipe_data)
    return {
        "restaurant_name": first_recipe_menu_text(
            recipe_data.get("restaurant_name"), metadata.get("restaurant_name")
        ),
        "restaurant_logo_url": first_recipe_menu_text(
            recipe_data.get("restaurant_logo_url"), metadata.get("restaurant_logo_url")
        ),
        "restaurant_rating": first_recipe_menu_text(
            recipe_data.get("restaurant_rating"), metadata.get("restaurant_rating")
        ),
        "restaurant_phone": first_recipe_menu_text(
            recipe_data.get("restaurant_phone"), metadata.get("restaurant_phone")
        ),
        "restaurant_website_url": first_recipe_menu_text(
            recipe_data.get("restaurant_website_url"), metadata.get("restaurant_website_url")
        ),
        "source_menu_url": first_recipe_menu_text(
            recipe_data.get("source_menu_url"),
            recipe_data.get("menu_source_url"),
            metadata.get("source_menu_url"),
            recipe_menu_source_url_from_candidates(recipe_data),
        ),
        "restaurant_street_address": first_recipe_menu_text(
            recipe_data.get("restaurant_street_address"),
            recipe_data.get("restaurant_address"),
            metadata.get("restaurant_address"),
        ),
        "restaurant_city": first_recipe_menu_text(recipe_data.get("restaurant_city"), metadata.get("restaurant_city")),
        "restaurant_state": first_recipe_menu_text(recipe_data.get("restaurant_state"), metadata.get("restaurant_state")),
        "restaurant_postal_code": first_recipe_menu_text(
            recipe_data.get("restaurant_postal_code"), metadata.get("restaurant_postal_code")
        ),
        "restaurant_country": first_recipe_menu_text(
            recipe_data.get("restaurant_country"), metadata.get("restaurant_country")
        ),
        "restaurant_hours_text": first_recipe_menu_text(
            recipe_data.get("restaurant_hours_text"), metadata.get("restaurant_hours_text")
        ),
        "restaurant_current_status": first_recipe_menu_text(
            recipe_data.get("restaurant_current_status"), metadata.get("restaurant_current_status")
        ),
        "restaurant_promotions": first_recipe_menu_text(
            recipe_data.get("restaurant_promotions"), metadata.get("restaurant_promotions")
        ),
        "restaurant_online_payment_available": recipe_menu_bool_for_editor(
            recipe_data.get("restaurant_online_payment_available"),
            metadata.get("restaurant_online_payment_available"),
        ),
        "restaurant_delivery_available": recipe_menu_bool_for_editor(
            recipe_data.get("restaurant_delivery_available"),
            metadata.get("restaurant_delivery_available"),
        ),
    }


def lazy_backfill_editable_recipe_restaurant(recipe_url, recipe_data):
    """Attach one legacy embedded recipe to a normalized record without deleting snapshots."""
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    restaurant_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
    menu_id = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "menu_id"))
    with menu_store_service.MENU_STORE_LOCK:
        store = menu_store_service.load_menu_store()
        current = menu_store_service.restaurant_for(store, restaurant_id) if restaurant_id else {}
        if current:
            if normalize_editable_restaurant_store_metadata(store):
                menu_store_service.save_menu_store(store)
            return recipe_data

        target_restaurant_id = ""
        resolved_menu_id = menu_id
        resolved_menu_item = {}
        menu = menu_store_service.find_menu(store, menu_id) if menu_id else {}
        if menu:
            target_restaurant_id = clean_recipe_menu_text(menu.get("restaurant_id"))
            if not menu_store_service.restaurant_for(store, target_restaurant_id):
                target_restaurant_id = ""
        if not target_restaurant_id:
            resolved_menu_item = find_recipe_menu_item_by_url(store, recipe_data)
            if resolved_menu_item:
                resolved_menu_id = clean_recipe_menu_text(resolved_menu_item.get("menu_id"))
                target_restaurant_id = clean_recipe_menu_text(resolved_menu_item.get("restaurant_id"))
                if not target_restaurant_id and resolved_menu_id:
                    resolved_menu = menu_store_service.find_menu(store, resolved_menu_id) or {}
                    target_restaurant_id = clean_recipe_menu_text(resolved_menu.get("restaurant_id"))
                if not menu_store_service.restaurant_for(store, target_restaurant_id):
                    target_restaurant_id = ""

        legacy_values = embedded_restaurant_values_for_backfill(recipe_data)
        if not target_restaurant_id and not clean_recipe_menu_text(legacy_values.get("restaurant_name")):
            return recipe_data
        if not target_restaurant_id:
            duplicates = editable_restaurant_duplicate_candidates(store, legacy_values)
            if len(duplicates) > 1:
                print(
                    "[restaurant_backfill] ambiguous "
                    f"recipe={clean_recipe_menu_text(recipe_url)} "
                    f"candidate_ids={[row.get('restaurant_id') for row in duplicates]}"
                )
                return recipe_data
            if duplicates:
                target_restaurant_id = clean_recipe_menu_text(duplicates[0].get("restaurant_id"))
            else:
                target_restaurant_id = menu_store_service.new_id("restaurant")
                restaurant = {"id": target_restaurant_id, "restaurant_id": target_restaurant_id}
                try:
                    apply_editable_restaurant_values(restaurant, legacy_values)
                except ValueError as exc:
                    print(
                        "[restaurant_backfill] skipped "
                        f"recipe={clean_recipe_menu_text(recipe_url)} error={clean_recipe_menu_text(exc)}"
                    )
                    return recipe_data
                store["restaurants"].append(restaurant)
                menu_store_service.save_menu_store(store)

    recipe_data["restaurant_id"] = target_restaurant_id
    metadata = recipe_menu_source_metadata(recipe_data)
    if metadata:
        metadata["restaurant_id"] = target_restaurant_id
    if resolved_menu_id and not recipe_menu_relation_value(recipe_data, "menu_id"):
        recipe_data["menu_id"] = resolved_menu_id
        if metadata:
            metadata["menu_id"] = resolved_menu_id
    if resolved_menu_item:
        for recipe_field, item_field in (
            ("menu_section_id", "menu_section_id"),
            ("menu_item_id", "id"),
        ):
            value = clean_recipe_menu_text(resolved_menu_item.get(item_field))
            if value and not recipe_menu_relation_value(recipe_data, recipe_field):
                recipe_data[recipe_field] = value
                if metadata:
                    metadata[recipe_field] = value
    save_recipe_output(clean_recipe_menu_text(recipe_data.get("source_url")) or recipe_url, recipe_data)
    return recipe_data


def backfill_editable_restaurant_sources():
    summary = {"ok": True, "linked": 0, "unchanged": 0, "ambiguous_or_skipped": 0}
    for recipe_data in list(recipe_output_index().values()):
        if not isinstance(recipe_data, dict):
            continue
        recipe_url = clean_recipe_menu_text(recipe_data.get("source_url"))
        before = clean_recipe_menu_text(recipe_menu_relation_value(recipe_data, "restaurant_id"))
        updated = lazy_backfill_editable_recipe_restaurant(recipe_url, recipe_data)
        after = clean_recipe_menu_text(recipe_menu_relation_value(updated, "restaurant_id"))
        if after and after != before:
            summary["linked"] += 1
        elif after:
            summary["unchanged"] += 1
        elif clean_recipe_menu_text(embedded_restaurant_values_for_backfill(recipe_data).get("restaurant_name")):
            summary["ambiguous_or_skipped"] += 1
    return summary


def load_editable_recipe(url):
    url = str(url or "").strip()
    recipe_data = load_recipe_output(url) or {"source_url": url}
    recipe_data = lazy_backfill_editable_recipe_restaurant(url, recipe_data)
    apply_recipe_pdf_asset_aliases(recipe_data)
    source_url = str(recipe_data.get("source_url") or url).strip() or url
    hydrate_source_pdf_assets_from_url(recipe_data, source_url)
    menu_metadata = editable_recipe_menu_metadata(recipe_data)
    menu_source_options = editable_menu_source_options()
    menu_source_option = editable_menu_source_option_for_recipe(menu_metadata, menu_source_options)
    if menu_source_option:
        menu_metadata = apply_editable_menu_source_option(menu_metadata, menu_source_option)
    menu_source_value = editable_menu_source_option_value(
        menu_metadata.get("restaurant_id"),
        menu_metadata.get("menu_id"),
    )
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
    cover_image_prompt = str(
        recipe_data.get("cover_image_prompt")
        or (cover_image.get("prompt") if isinstance(cover_image, dict) else "")
        or ""
    ).strip()
    category_metadata = recipe_category_metadata_for_editor(url, recipe_data, meta)
    recipe_notes = normalize_recipe_note_sections(
        recipe_data.get("recipe_notes")
        or recipe_data.get("recipe_note_sections")
        or recipe_data.get("source_notes")
    )
    apply_recipe_note_substitutions_to_ingredients(
        recipe_data.get("ingredients", []),
        recipe_notes,
    )

    return {
        "ok": True,
        "recipe": {
            "recipe_id": recipe_data.get("recipe_id") or "",
            "created_at": recipe_data.get("created_at") or "",
            "updated_at": recipe_data.get("updated_at") or "",
            "source_url": recipe_data.get("source_url") or url,
            "document_source_url": recipe_data.get("document_source_url") or recipe_data.get("source_url") or url,
            "menu_item_url": recipe_data.get("menu_item_url") or recipe_data.get("source_url") or url,
            "source_display_url": editable_recipe_source_display_url(recipe_data.get("source_url") or url),
            "type": recipe_url_type(url),
            "display_name": meta.get("name") or recipe_data.get("display_name") or recipe_data.get("recipe_title") or "",
            "quantity": normalize_recipe_quantity(meta.get("quantity", 1)),
            "cookbook_id": cookbook_assignment.get("cookbook_id", ""),
            "cookbook_name": cookbook_assignment.get("cookbook_name", ""),
            "cookbook_is_unclassified": cookbook_assignment.get("cookbook_is_unclassified", False),
            "recipe_title": recipe_data.get("recipe_title") or "",
            "description": recipe_info_clean_value(
                recipe_data.get("description") or recipe_data.get("menu_description"),
                "description",
            ),
            "servings": servings,
            "cover_image": cover_image,
            "cover_image_prompt": cover_image_prompt,
            **recipe_info,
            "scaling": scaling,
            "ingredients": annotate_ingredients_for_food_review(
                normalize_edit_ingredients(recipe_data.get("ingredients", []), recipe_url=source_url)
            ),
            "equipment": normalize_equipment_records(recipe_data.get("equipment", [])),
            "instructions": normalize_instruction_rows(recipe_data.get("instructions", [])),
            "nutrition": normalize_nutrition_rows(
                recipe_data.get("nutrition", {}),
                include_defaults=recipe_url_type(url) == "Manual",
            ),
            "rating": normalize_recipe_rating(recipe_data.get("rating")),
            "favorite": bool(recipe_data.get("favorite")),
            "recipe_notes": recipe_notes,
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
            "menu_source_value": menu_source_value,
            "menu_source_options": menu_source_options,
            **category_metadata,
        },
        "food_rules": load_food_rules(),
        "store_sections": ingredient_store_section_options(),
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
    image_prompt = str(
        recipe_data.get("cover_image_prompt")
        or cover_image.get("prompt")
        or cover_image.get("image_prompt")
        or recipe_meta.get("cover_image_prompt")
        or ""
    ).strip()
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

    result = {
        **normalized,
        "alt": normalized.get("alt") or fallback_alt,
        "src": src,
        **variants,
    }
    if image_prompt:
        result["prompt"] = image_prompt
        result["image_prompt"] = image_prompt

    return result


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


def recipe_save_error(error, message, field_errors=None, status_code=400):
    return {
        "ok": False,
        "success": False,
        "error": str(error or "save_failed"),
        "message": str(message or "The recipe could not be saved."),
        "field_errors": field_errors if isinstance(field_errors, dict) else {},
        "status_code": int(status_code or 400),
    }


def recipe_amount_is_valid(value):
    if value in (None, ""):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value)) and float(value) >= 0

    text = str(value or "").strip().lower()
    if not text:
        return True
    if text in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return False
    if re.search(r"\d\s*(?:\.\.|,,|//|--)\s*\d?", text):
        return False
    if re.search(r"\d+(?:\.\d+){2,}", text):
        return False
    if re.match(r"^-\s*(?:\d|\.\d)", text):
        return False
    if re.search(r"\b(?:to|or)\s+-\s*(?:\d|\.\d)", text):
        return False

    for fraction_match in re.finditer(r"(?<![\d/])(\d+)\s*/\s*(\d+)(?![\d/])", text):
        if int(fraction_match.group(2)) == 0:
            return False

    compact_number = text.replace(",", "")
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+-]?\d+)?", compact_number):
        try:
            numeric_value = float(compact_number)
        except ValueError:
            return False
        return math.isfinite(numeric_value) and numeric_value >= 0

    return True


def nutrition_numeric_value_is_valid(key, value):
    text = str(value or "").strip()
    if not text or key == "serving_basis" or not re.search(r"\d", text):
        return True
    return not bool(re.search(r"\d\s*(?:\.\.|,,|//|--+)\s*\d", text))


def validate_recipe_save_payload(payload):
    if not isinstance(payload, dict):
        return {"recipe": "Recipe data must be a JSON object."}

    errors = {}
    title = str(payload.get("recipe_title") or "").strip()
    if not title:
        errors["recipe_title"] = "Recipe name is required."

    source_url = str(payload.get("source_url") or "").strip()
    if source_url.lower() in {"not available", "n/a", "none", "null"}:
        errors["source_url"] = "Source URL must be a real URL or recipe identifier."

    quantity = payload.get("quantity")
    if quantity not in (None, ""):
        try:
            numeric_quantity = float(quantity)
        except (TypeError, ValueError):
            numeric_quantity = 0
        if not math.isfinite(numeric_quantity) or numeric_quantity <= 0:
            errors["quantity"] = "Recipe quantity must be greater than zero."

    rating = payload.get("rating")
    if rating not in (None, ""):
        try:
            numeric_rating = int(rating)
        except (TypeError, ValueError):
            numeric_rating = -1
        if numeric_rating < 0 or numeric_rating > 5:
            errors["rating"] = "Rating must be between 0 and 5."

    collection_fields = ("ingredients", "equipment", "instructions", "nutrition")
    for field in collection_fields:
        if field in payload and not isinstance(payload.get(field), list):
            errors[field] = f"{field.replace('_', ' ').title()} must be a list."

    ingredients = payload.get("ingredients") if isinstance(payload.get("ingredients"), list) else []
    if not ingredients and "ingredients" not in errors:
        errors["ingredients"] = "Add at least one ingredient."
    for index, item in enumerate(ingredients):
        if not isinstance(item, dict):
            errors[f"ingredients.{index}"] = "Ingredient row must be an object."
            continue
        if not str(item.get("ingredient") or item.get("original_text") or "").strip():
            errors[f"ingredients.{index}.ingredient"] = "Ingredient name is required."
        amount = item.get("quantity") if "quantity" in item else item.get("recipe_qty")
        if not recipe_amount_is_valid(amount):
            errors[f"ingredients.{index}.amount"] = "Ingredient amount is invalid."

    equipment = payload.get("equipment") if isinstance(payload.get("equipment"), list) else []
    for index, item in enumerate(equipment):
        if isinstance(item, dict):
            text = item.get("equipment") or item.get("text") or item.get("name")
        else:
            text = item
        if not str(text or "").strip():
            errors[f"equipment.{index}.equipment"] = "Equipment name is required."

    instructions = payload.get("instructions") if isinstance(payload.get("instructions"), list) else []
    if not instructions and "instructions" not in errors:
        errors["instructions"] = "Add at least one instruction."
    for index, item in enumerate(instructions):
        if isinstance(item, dict):
            text = item.get("instruction") or item.get("text")
        else:
            text = item
        if not str(text or "").strip():
            errors[f"instructions.{index}.instruction"] = "Instruction text is required."
        if isinstance(item, dict) and item.get("step_number") not in (None, ""):
            try:
                step_number = float(item.get("step_number"))
            except (TypeError, ValueError):
                step_number = 0
            if not math.isfinite(step_number) or step_number <= 0:
                errors[f"instructions.{index}.step_number"] = "Step number must be greater than zero."

    nutrition = payload.get("nutrition") if isinstance(payload.get("nutrition"), list) else []
    for index, item in enumerate(nutrition):
        if not isinstance(item, dict):
            errors[f"nutrition.{index}"] = "Nutrition row must be an object."
            continue
        key = str(item.get("key") or item.get("label") or item.get("name") or "").strip()
        value = str(item.get("value") or item.get("amount") or "").strip()
        if not key and value:
            errors[f"nutrition.{index}.key"] = "Nutrient name is required."
        elif key and not value:
            errors[f"nutrition.{index}.value"] = "Nutrient value is required."
        elif key and value:
            normalized_key = key.lower().replace(" ", "_").replace("-", "_")
            if not nutrition_numeric_value_is_valid(normalized_key, value):
                errors[f"nutrition.{index}.value"] = "Nutrient value is invalid."

    return errors


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


def save_editable_recipe(original_url, payload, require_existing=False):
    original_url = str(original_url or "").strip()

    if not original_url:
        return recipe_save_error(
            "validation_error",
            "Some fields need attention.",
            {"original_url": "Recipe URL is required."},
            status_code=422,
        )

    if not isinstance(payload, dict):
        return recipe_save_error(
            "validation_error",
            "Some fields need attention.",
            {"recipe": "Recipe data must be a JSON object."},
            status_code=422,
        )

    submitted_recipe_id = str(payload.get("recipe_id") or "").strip()
    existing_data = load_recipe_output(original_url)
    if (
        (not isinstance(existing_data, dict) or not existing_data)
        and require_existing
        and submitted_recipe_id
    ):
        recipe_id_matches = [
            recipe
            for recipe in recipe_output_index().values()
            if isinstance(recipe, dict)
            and str(recipe.get("recipe_id") or "").strip() == submitted_recipe_id
        ]
        if len(recipe_id_matches) > 1:
            return recipe_save_error(
                "recipe_conflict",
                "More than one saved recipe has that recipe identifier.",
                {"recipe_id": "Reload the recipe before saving these changes."},
                status_code=409,
            )
        if recipe_id_matches:
            resolved_source_url = str(recipe_id_matches[0].get("source_url") or "").strip()
            if resolved_source_url:
                existing_data = recipe_id_matches[0]
                original_url = resolved_source_url

    if (not isinstance(existing_data, dict) or not existing_data) and require_existing:
        return recipe_save_error(
            "not_found",
            "The recipe could not be found. Reload the recipe and try again.",
            {"original_url": "Recipe was not found."},
            status_code=404,
        )
    if not isinstance(existing_data, dict) or not existing_data:
        existing_data = {"source_url": original_url}

    existing_recipe_id = str(existing_data.get("recipe_id") or "").strip()
    if (
        require_existing
        and existing_recipe_id
        and submitted_recipe_id
        and existing_recipe_id != submitted_recipe_id
    ):
        return recipe_save_error(
            "recipe_conflict",
            "Recipe identity does not match the open recipe.",
            {"recipe_id": "Reload the recipe before saving these changes."},
            status_code=409,
        )

    source_url = str(payload.get("source_url") or original_url).strip()

    if not source_url:
        source_url = original_url

    identity_changed = normalize_recipe_url_key(source_url) != normalize_recipe_url_key(original_url)
    target_data_before = load_recipe_output(source_url) if identity_changed else None
    if require_existing and identity_changed:
        if isinstance(target_data_before, dict) and target_data_before:
            existing_recipe_id = str(existing_data.get("recipe_id") or "").strip()
            target_recipe_id = str(target_data_before.get("recipe_id") or "").strip()
            if not existing_recipe_id or not target_recipe_id or existing_recipe_id != target_recipe_id:
                return recipe_save_error(
                    "recipe_conflict",
                    "Another recipe already uses that source URL.",
                    {"source_url": "Choose a source URL that is not assigned to another recipe."},
                    status_code=409,
                )

    previous_recipe_data = load_recipe_ingredients()
    previous_ingredients = recipe_ingredients_for_key(
        normalize_recipe_url_key(original_url),
        previous_recipe_data,
    )
    apply_recipe_pdf_asset_aliases(existing_data)
    log_recipe_pdf_fields("save_editable_recipe:existing", existing_data)
    payload_cover_image = payload.get("cover_image") if isinstance(payload.get("cover_image"), dict) else {}
    existing_cover_image = existing_data.get("cover_image") if isinstance(existing_data.get("cover_image"), dict) else {}
    cover_image_prompt_supplied = (
        "cover_image_prompt" in payload
        or "prompt" in payload_cover_image
        or "image_prompt" in payload_cover_image
    )
    if "cover_image_prompt" in payload:
        cover_image_prompt = str(payload.get("cover_image_prompt") or "").strip()
    elif "prompt" in payload_cover_image or "image_prompt" in payload_cover_image:
        cover_image_prompt = str(
            payload_cover_image.get("prompt")
            or payload_cover_image.get("image_prompt")
            or ""
        ).strip()
    else:
        cover_image_prompt = str(
            existing_data.get("cover_image_prompt")
            or existing_cover_image.get("prompt")
            or existing_cover_image.get("image_prompt")
            or ""
        ).strip()
    cover_image = sanitize_recipe_cover_image(
        payload.get("cover_image") or existing_data.get("cover_image"),
        source_url,
        payload.get("recipe_title") or existing_data.get("recipe_title") or "",
    )
    existing_recipe_notes = (
        existing_data.get("recipe_notes")
        or existing_data.get("recipe_note_sections")
        or existing_data.get("source_notes")
        or []
    )
    recipe_data = {
        **existing_data,
        "recipe_id": str(existing_recipe_id or submitted_recipe_id or uuid.uuid4().hex).strip(),
        "created_at": str(existing_data.get("created_at") or now_iso()).strip(),
        "updated_at": now_iso(),
        "source_url": source_url,
        "cover_image_prompt": cover_image_prompt,
        "recipe_title": str(
            payload.get("recipe_title")
            if "recipe_title" in payload
            else existing_data.get("recipe_title") or ""
        ).strip(),
        "description": str(
            payload.get("description")
            if "description" in payload
            else existing_data.get("description") or ""
        ).strip(),
        "servings": str(payload.get("servings") if "servings" in payload else existing_data.get("servings") or "").strip(),
        "level": str(payload.get("level") if "level" in payload else existing_data.get("level") or "").strip(),
        "total_time": str(payload.get("total_time") if "total_time" in payload else existing_data.get("total_time") or "").strip(),
        "prep_time": str(payload.get("prep_time") if "prep_time" in payload else existing_data.get("prep_time") or "").strip(),
        "inactive_time": str(payload.get("inactive_time") if "inactive_time" in payload else existing_data.get("inactive_time") or "").strip(),
        "cook_time": str(payload.get("cook_time") if "cook_time" in payload else existing_data.get("cook_time") or "").strip(),
        "scaling": normalize_recipe_scaling_metadata(
            payload.get("scaling") or existing_data.get("scaling")
        ),
        "ingredients": sanitize_ingredients(
            payload.get("ingredients") if "ingredients" in payload else existing_data.get("ingredients", []),
            existing_data.get("ingredients", []),
        ),
        "equipment": sanitize_equipment_list(
            payload.get("equipment") if "equipment" in payload else existing_data.get("equipment", []),
            existing_data.get("equipment", []),
        ),
        "instructions": sanitize_instruction_list(
            payload.get("instructions") if "instructions" in payload else existing_data.get("instructions", []),
            existing_data.get("instructions", []),
        ),
        "nutrition": sanitize_nutrition(
            payload.get("nutrition") if "nutrition" in payload else normalize_nutrition_rows(existing_data.get("nutrition", {})),
            existing_data.get("nutrition", {}),
        ),
        "rating": normalize_recipe_rating(
            payload.get("rating") if "rating" in payload else existing_data.get("rating")
        ),
        "recipe_notes": sanitize_recipe_notes(
            payload.get("recipe_notes", existing_recipe_notes),
            existing_recipe_notes,
        ),
        "reflection_notes": sanitize_reflection_notes(
            payload.get("reflection_notes") if "reflection_notes" in payload else existing_data.get("reflection_notes", []),
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
        if cover_image_prompt:
            cover_image["prompt"] = cover_image_prompt
            cover_image["image_prompt"] = cover_image_prompt
        elif cover_image_prompt_supplied:
            cover_image.pop("prompt", None)
            cover_image.pop("image_prompt", None)
        recipe_data["cover_image"] = cover_image
    else:
        recipe_data.pop("cover_image", None)
    if recipe_data["servings"] and not recipe_data["scaling"].get("base_servings"):
        recipe_data["scaling"]["base_servings"] = recipe_data["servings"]

    substitution_metadata = [
        deepcopy(item.get("substitutions") or []) if isinstance(item, dict) else []
        for item in recipe_data.get("ingredients", [])
    ]
    normalize_extracted_ingredient_fields(recipe_data)
    for index, item in enumerate(recipe_data.get("ingredients", [])):
        if not isinstance(item, dict):
            continue
        existing_substitutions = substitution_metadata[index] if index < len(substitution_metadata) else []
        item["substitutions"] = normalize_ingredient_substitutions(
            item.get("substitutions"),
            existing_substitutions,
            parent_item=item,
        )
    normalize_extracted_equipment_fields(recipe_data)
    log_recipe_pdf_fields("save_editable_recipe:before_write", recipe_data)
    save_recipe_output(source_url, recipe_data)

    if identity_changed:
        try:
            replace_recipe_url(original_url, source_url)
            move_recipe_meta(original_url, source_url)
            remove_stale_recipe_output(original_url, source_url)
        except Exception:
            LOGGER.exception("Recipe identity migration failed; restoring the prior recipe output.")
            try:
                if isinstance(target_data_before, dict) and target_data_before:
                    save_recipe_output(source_url, target_data_before)
                else:
                    remove_recipe_output_file(source_url)
                save_recipe_output(original_url, existing_data)
                replace_recipe_url(source_url, original_url)
                move_recipe_meta(source_url, original_url)
            except Exception:
                LOGGER.exception("Recipe identity migration rollback was incomplete.")
            raise

    quantity = normalize_recipe_quantity(payload.get("quantity", 1))
    display_name = str(payload.get("display_name") or "").strip()

    warnings = []
    derived_syncs = (
        ("Recipe quantity metadata", lambda: save_recipe_url_quantity(source_url, quantity)),
        ("Recipe display name", lambda: save_recipe_url_name(source_url, display_name)),
        ("Ingredient and equipment master data", lambda: update_recipe_ingredient_record(source_url, quantity, recipe_data)),
        ("Scaled recipe quantities", lambda: update_recipe_quantity(source_url, quantity)),
        ("Shopping list", lambda: sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients)),
    )
    for label, sync_callback in derived_syncs:
        try:
            sync_callback()
        except Exception:
            LOGGER.exception("%s synchronization failed after the recipe was saved.", label)
            warnings.append(f"{label} could not be synchronized.")

    try:
        result = load_editable_recipe(source_url)
    except Exception:
        LOGGER.exception("The saved recipe could not be refreshed for the response.")
        warnings.append("The saved recipe could not be refreshed in the response.")
        result = {"recipe": recipe_data}
    result.update({
        "ok": True,
        "success": True,
        "recipe_id": recipe_data["recipe_id"],
        "updated_at": recipe_data["updated_at"],
        "message": "Recipe saved successfully",
        "warnings": warnings,
    })
    return result


def editable_recipe_ingredient_reference_name(item):
    if not isinstance(item, dict):
        return ""
    return nullable_string(
        item.get("ingredient")
        or item.get("name")
        or item.get("original_text")
        or item.get("purchasable_item")
        or item.get("buy_as")
    ) or ""


def editable_recipe_ingredient_name_matches(item, reference_name):
    reference_key = instruction_match_text_key(reference_name)
    if not reference_key or not isinstance(item, dict):
        return False
    return any(
        instruction_match_text_key(item.get(field)) == reference_key
        for field in (
            "ingredient",
            "name",
            "original_text",
            "parsed_name",
            "normalized_name",
            "purchasable_item",
            "buy_as",
        )
        if item.get(field)
    )


def resolve_editable_recipe_ingredient_index(ingredients, ingredient, ingredient_ref=None):
    ingredients = ingredients if isinstance(ingredients, list) else []
    ingredient = ingredient if isinstance(ingredient, dict) else {}
    ingredient_ref = ingredient_ref if isinstance(ingredient_ref, dict) else {}
    stable_fields = ("recipe_ingredient_id", "row_id", "id")
    stable_values = {}
    for field in stable_fields:
        value = nullable_string(ingredient_ref.get(field))
        if not value:
            value = nullable_string(ingredient.get(field))
        if value:
            stable_values[field] = value

    if stable_values:
        match_sets = []
        for field, expected in stable_values.items():
            match_sets.append({
                index
                for index, item in enumerate(ingredients)
                if isinstance(item, dict)
                and nullable_string(item.get(field)) == expected
            })
        matching = set.intersection(*match_sets) if match_sets else set()
        if len(matching) == 1:
            return {"ok": True, "index": matching.pop(), "matched_by": "stable_id"}
        if not matching and all(match_set for match_set in match_sets):
            return recipe_save_error(
                "ingredient_conflict",
                "Ingredient identifiers do not refer to the same saved row.",
                {"ingredient_ref": "Reload the recipe before saving this ingredient."},
                status_code=409,
            )
        if not matching:
            return recipe_save_error(
                "ingredient_not_found",
                "The ingredient could not be found. Reload the recipe and try again.",
                {"ingredient_ref": "Saved ingredient identifiers no longer match."},
                status_code=404,
            )
        return recipe_save_error(
            "ingredient_conflict",
            "More than one ingredient has the same saved identifier.",
            {"ingredient_ref": "Reload the recipe before saving this ingredient."},
            status_code=409,
        )

    raw_index = ingredient_ref.get("index")
    if raw_index in (None, ""):
        raw_index = ingredient_ref.get("ingredient_index")
    reference_name = editable_recipe_ingredient_reference_name(ingredient_ref)
    submitted_name = editable_recipe_ingredient_reference_name(ingredient)

    if raw_index not in (None, ""):
        try:
            target_index = int(raw_index)
        except (TypeError, ValueError):
            target_index = -1
        if isinstance(raw_index, bool) or target_index < 0 or target_index >= len(ingredients):
            return recipe_save_error(
                "ingredient_not_found",
                "The ingredient position is no longer available.",
                {"ingredient_ref.index": "Reload the recipe before saving this ingredient."},
                status_code=404,
            )
        expected_name = reference_name or submitted_name
        if not expected_name or not editable_recipe_ingredient_name_matches(
            ingredients[target_index],
            expected_name,
        ):
            return recipe_save_error(
                "ingredient_conflict",
                "The ingredient at that position has changed.",
                {"ingredient_ref": "Include the original ingredient name or reload the recipe."},
                status_code=409,
            )
        return {"ok": True, "index": target_index, "matched_by": "index_and_name"}

    expected_name = reference_name or submitted_name
    if not expected_name:
        return recipe_save_error(
            "validation_error",
            "An ingredient identifier is required.",
            {"ingredient_ref": "Provide a saved ingredient ID or its original position and name."},
            status_code=422,
        )
    matching = [
        index
        for index, item in enumerate(ingredients)
        if editable_recipe_ingredient_name_matches(item, expected_name)
    ]
    if len(matching) == 1:
        return {"ok": True, "index": matching[0], "matched_by": "unique_name"}
    if not matching:
        return recipe_save_error(
            "ingredient_not_found",
            "The ingredient could not be found. Reload the recipe and try again.",
            {"ingredient_ref": "No saved ingredient matches that name."},
            status_code=404,
        )
    return recipe_save_error(
        "ingredient_conflict",
        "More than one ingredient has that name.",
        {"ingredient_ref": "Use a saved ingredient ID to choose the correct row."},
        status_code=409,
    )


def save_editable_recipe_ingredient(
    original_url,
    ingredient,
    *,
    ingredient_ref=None,
    recipe_id="",
):
    original_url = str(original_url or "").strip()
    ingredient = ingredient if isinstance(ingredient, dict) else None
    ingredient_ref = ingredient_ref if isinstance(ingredient_ref, dict) else {}
    if not original_url:
        return recipe_save_error(
            "validation_error",
            "Some fields need attention.",
            {"original_url": "Recipe URL is required."},
            status_code=422,
        )
    if ingredient is None:
        return recipe_save_error(
            "validation_error",
            "Some fields need attention.",
            {"ingredient": "Ingredient data must be a JSON object."},
            status_code=422,
        )

    with _RECIPE_OUTPUT_WRITE_LOCK:
        existing_data = load_recipe_output(original_url)
        if not isinstance(existing_data, dict) or not existing_data:
            return recipe_save_error(
                "not_found",
                "The recipe could not be found. Reload the recipe and try again.",
                {"original_url": "Recipe was not found."},
                status_code=404,
            )

        saved_recipe_id = nullable_string(existing_data.get("recipe_id")) or ""
        requested_recipe_id = nullable_string(recipe_id) or ""
        if saved_recipe_id and requested_recipe_id and saved_recipe_id != requested_recipe_id:
            return recipe_save_error(
                "recipe_conflict",
                "Recipe identity does not match the open recipe.",
                {"recipe_id": "Reload the recipe before saving this ingredient."},
                status_code=409,
            )

        existing_ingredients = (
            existing_data.get("ingredients")
            if isinstance(existing_data.get("ingredients"), list)
            else []
        )
        creating = truthy(ingredient_ref.get("create"))
        if creating:
            raw_index = ingredient_ref.get("index", len(existing_ingredients))
            try:
                target_index = int(raw_index)
            except (TypeError, ValueError):
                target_index = -1
            if (
                isinstance(raw_index, bool)
                or target_index < 0
                or target_index > len(existing_ingredients)
            ):
                return recipe_save_error(
                    "validation_error",
                    "Some fields need attention.",
                    {"ingredient_ref.index": "New ingredient position is invalid."},
                    status_code=422,
                )
            resolved = {"ok": True, "index": target_index, "matched_by": "create"}
            existing_ingredient = {}
            merged_ingredient = deepcopy(ingredient)
            for field in ("recipe_ingredient_id", "row_id", "id"):
                merged_ingredient.pop(field, None)
        else:
            resolved = resolve_editable_recipe_ingredient_index(
                existing_ingredients,
                ingredient,
                ingredient_ref,
            )
            if not resolved.get("ok"):
                return resolved
            target_index = resolved["index"]
            existing_ingredient = existing_ingredients[target_index]
            merged_ingredient = {
                **deepcopy(existing_ingredient),
                **deepcopy(ingredient),
            }
            for field in ("recipe_ingredient_id", "row_id", "id"):
                if existing_ingredient.get(field) not in (None, ""):
                    merged_ingredient[field] = existing_ingredient[field]
        substitution_fields = (
            "substitutions",
            "substitution_options",
            "alternatives",
            "substitutions_text",
        )
        substitutions_supplied = any(field in ingredient for field in substitution_fields)

        if not str(merged_ingredient.get("ingredient") or "").strip():
            return recipe_save_error(
                "validation_error",
                "Some fields need attention.",
                {"ingredient.ingredient": "Ingredient name is required."},
                status_code=422,
            )
        amount = (
            merged_ingredient.get("quantity")
            if "quantity" in merged_ingredient
            else merged_ingredient.get("recipe_qty")
        )
        if not recipe_amount_is_valid(amount):
            return recipe_save_error(
                "validation_error",
                "Some fields need attention.",
                {"ingredient.amount": "Ingredient amount is invalid."},
                status_code=422,
            )

        sanitized = sanitize_ingredients([merged_ingredient], [existing_ingredient])
        if not sanitized:
            return recipe_save_error(
                "validation_error",
                "Some fields need attention.",
                {"ingredient": "Ingredient data could not be saved."},
                status_code=422,
            )
        substitution_metadata = deepcopy(sanitized[0].get("substitutions") or [])
        normalization_context = {
            **existing_data,
            "ingredients": sanitized,
        }
        normalize_extracted_ingredient_fields(normalization_context)
        saved_ingredient = normalization_context["ingredients"][0]
        if creating:
            for field in ("recipe_ingredient_id", "row_id", "id"):
                saved_ingredient.pop(field, None)
        if substitutions_supplied:
            saved_ingredient["substitutions"] = normalize_ingredient_substitutions(
                saved_ingredient.get("substitutions"),
                substitution_metadata,
                parent_item=saved_ingredient,
            )
        else:
            saved_ingredient["substitutions"] = deepcopy(
                existing_ingredient.get("substitutions")
                or existing_ingredient.get("substitution_options")
                or existing_ingredient.get("alternatives")
                or []
            )

        recipe_data = deepcopy(existing_data)
        recipe_data["ingredients"] = deepcopy(existing_ingredients)
        if creating:
            recipe_data["ingredients"].insert(target_index, saved_ingredient)
        else:
            recipe_data["ingredients"][target_index] = saved_ingredient
        recipe_data["updated_at"] = now_iso()
        source_url = str(recipe_data.get("source_url") or original_url).strip() or original_url
        previous_recipe_data = load_recipe_ingredients()
        previous_ingredients = recipe_ingredients_for_key(
            normalize_recipe_url_key(source_url),
            previous_recipe_data,
        )
        recipe_meta = previous_recipe_data.get(normalize_recipe_url_key(source_url), {})
        quantity = normalize_recipe_quantity(
            recipe_meta.get("quantity", 1) if isinstance(recipe_meta, dict) else 1
        )
        save_recipe_output(source_url, recipe_data)

    warnings = []
    derived_syncs = (
        ("Ingredient and equipment master data", lambda: update_recipe_ingredient_record(source_url, quantity, recipe_data)),
        ("Scaled recipe quantities", lambda: update_recipe_quantity(source_url, quantity)),
        ("Shopping list", lambda: sync_saved_recipe_with_shopping_list(recipe_data, previous_ingredients)),
    )
    for label, sync_callback in derived_syncs:
        try:
            sync_callback()
        except Exception:
            LOGGER.exception("%s synchronization failed after the ingredient was saved.", label)
            warnings.append(f"{label} could not be synchronized.")

    try:
        normalized_response_ingredient = normalize_edit_ingredients(
            [saved_ingredient],
            recipe_url=source_url,
        )[0]
        response_ingredient = {
            **deepcopy(saved_ingredient),
            **normalized_response_ingredient,
        }
    except Exception:
        LOGGER.exception("The saved ingredient could not be normalized for the response.")
        response_ingredient = deepcopy(saved_ingredient)
        warnings.append("The saved ingredient could not be refreshed in the response.")

    result = {
        "ok": True,
        "success": True,
        "message": "Ingredient saved successfully",
        "recipe_id": saved_recipe_id,
        "source_url": source_url,
        "updated_at": recipe_data["updated_at"],
        "ingredient_index": target_index,
        "matched_by": resolved.get("matched_by") or "",
        "ingredient": response_ingredient,
        "warnings": warnings,
    }
    if creating:
        result["created"] = True
    return result


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
    for field in (
        "cover_image_generated_at",
        "cover_image_provider",
        "cover_image_fallback_used",
        "cover_image_prompt",
    ):
        existing_data.pop(field, None)
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


def save_generated_recipe_cover_image(
    recipe_source_url,
    recipe_data,
    image_bytes,
    fallback_alt,
    image_source,
    provider,
    fallback_used=False,
    image_prompt="",
):
    generated_at = datetime.now(timezone.utc).isoformat()
    image_prompt = str(image_prompt or "").strip()
    COVER_IMAGE_UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    filename_provider = "local" if provider == TITLE_IMAGE_PROVIDER_COMFYUI else "ai"
    image_filename = f"{safe_filename(recipe_source_url)}_title_{filename_provider}_{uuid.uuid4().hex[:12]}.png"
    image_path = COVER_IMAGE_UPLOAD_FOLDER / image_filename
    image_path.write_bytes(image_bytes)

    cover_image = extract_recipe_cover_image_from_upload(
        image_path,
        "image/png",
        image_filename,
        recipe_source_url,
        fallback_alt=fallback_alt,
    )

    if not cover_image:
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "Unable to save the generated title image."}

    cover_image["source"] = image_source
    cover_image["provider"] = provider
    if fallback_used:
        cover_image["fallback_used"] = True

    recipe_data["source_url"] = recipe_source_url
    recipe_data["cover_image"] = cover_image
    recipe_data["cover_image_generated_at"] = generated_at
    recipe_data["cover_image_provider"] = provider
    recipe_data["cover_image_fallback_used"] = bool(fallback_used)
    if image_prompt:
        recipe_data["cover_image_prompt"] = image_prompt
    else:
        recipe_data.pop("cover_image_prompt", None)
    save_recipe_output(recipe_source_url, recipe_data)

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(recipe_source_url), {})
    quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    update_recipe_ingredient_record(recipe_source_url, quantity, recipe_data)

    loaded = load_editable_recipe(recipe_source_url)
    response_recipe = loaded.get("recipe", {})
    response_cover_image = response_recipe.get("cover_image") or editable_recipe_cover_image(
        recipe_source_url,
        recipe_data,
        recipe_meta,
    )

    return {
        "ok": True,
        "url": recipe_source_url,
        "cover_image": response_cover_image,
        "recipe": response_recipe,
        "cover_image_generated_at": generated_at,
        "cover_image_prompt": image_prompt,
        "provider": provider,
        "fallback_used": bool(fallback_used),
    }


def remove_recipe_cover_image_files(cover_image):
    image_path = recipe_cover_image_file_path(cover_image)
    deleted_files = []

    if not image_path:
        return deleted_files

    paths = [image_path]
    for variant in IMAGE_VARIANTS:
        variant_path = webp_variant_path(image_path, variant)
        if variant_path:
            paths.append(variant_path)

    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                deleted_files.append(str(path))
        except OSError:
            pass

    return deleted_files


def remove_recipe_cover_image(original_url):
    original_url = str(original_url or "").strip()

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(original_url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_source_url = str(recipe_data.get("source_url") or original_url).strip() or original_url
    deleted_files = remove_recipe_cover_image_files(recipe_data.get("cover_image"))

    for field in (
        "cover_image",
        "cover_image_generated_at",
        "cover_image_provider",
        "cover_image_fallback_used",
        "cover_image_prompt",
    ):
        recipe_data.pop(field, None)

    recipe_data["source_url"] = recipe_source_url
    save_recipe_output(recipe_source_url, recipe_data)

    recipe_meta = load_recipe_ingredients().get(normalize_recipe_url_key(recipe_source_url), {})
    quantity = normalize_recipe_quantity(recipe_meta.get("quantity", 1))
    update_recipe_ingredient_record(
        recipe_source_url,
        quantity,
        recipe_data,
        preserve_existing_cover=False,
    )

    loaded = load_editable_recipe(recipe_source_url)
    response_recipe = loaded.get("recipe", {})

    return {
        "ok": True,
        "url": recipe_source_url,
        "cover_image": {},
        "recipe": response_recipe,
        "deleted_file_count": len(deleted_files),
    }


def generate_recipe_cover_image_with_openai(prompt):
    if not os.getenv("OPENAI_API_KEY"):
        raise TitleImageGenerationError(
            "openai_api_key_missing",
            TITLE_IMAGE_OPENAI_SETUP_MESSAGE,
            error_code="OPENAI_API_KEY_MISSING",
        )

    return request_recipe_title_image_bytes(prompt)


def generate_recipe_cover_image_bytes_for_provider(provider, recipe_data, recipe_title, base_prompt):
    if provider == TITLE_IMAGE_PROVIDER_OPENAI:
        return (
            generate_recipe_cover_image_with_openai(base_prompt),
            TITLE_IMAGE_PROVIDER_OPENAI,
            "ai_generated_image",
            False,
            base_prompt,
        )

    if provider == TITLE_IMAGE_PROVIDER_OLLAMA_PROMPT_ONLY:
        if not os.getenv("OPENAI_API_KEY"):
            raise TitleImageGenerationError(
                "openai_api_key_missing",
                TITLE_IMAGE_OPENAI_SETUP_MESSAGE,
                error_code="OPENAI_API_KEY_MISSING",
            )
        enhanced_prompt = enhance_recipe_title_image_prompt_with_ollama(
            recipe_data,
            recipe_title,
            base_prompt,
            required=True,
        )
        print("[TitleImage] Ollama only created the prompt; image_provider=openai")
        return (
            request_recipe_title_image_bytes(enhanced_prompt),
            TITLE_IMAGE_PROVIDER_OPENAI,
            "ai_generated_image",
            False,
            enhanced_prompt,
        )

    if provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        ensure_comfyui_available()
        enhanced_prompt = enhance_recipe_title_image_prompt_with_ollama(
            recipe_data,
            recipe_title,
            base_prompt,
            required=False,
        )
        return (
            request_comfyui_title_image_bytes(enhanced_prompt),
            TITLE_IMAGE_PROVIDER_COMFYUI,
            "local_comfyui_image",
            False,
            enhanced_prompt,
        )

    raise TitleImageGenerationError(
        f"unsupported_provider:{provider}",
        "Unsupported title image provider.",
        error_code="UNSUPPORTED_TITLE_IMAGE_PROVIDER",
    )


def generate_recipe_detail_image_with_openai(prompt):
    if not os.getenv("OPENAI_API_KEY"):
        raise TitleImageGenerationError(
            "openai_api_key_missing",
            TITLE_IMAGE_OPENAI_SETUP_MESSAGE,
            error_code="OPENAI_API_KEY_MISSING",
        )

    return request_recipe_step_image_bytes(prompt)


def openai_recipe_detail_image_prompt(base_prompt, image_purpose):
    if title_image_clean_text(image_purpose) == "recipe equipment item image":
        return finalize_equipment_image_prompt(base_prompt)

    return base_prompt


def notify_recipe_detail_image_prompt(prompt_callback, image_prompt, provider):
    if not prompt_callback:
        return

    prompt_callback(image_prompt, provider)


def generate_recipe_detail_image_bytes_for_provider(
    provider,
    recipe_data,
    recipe_title,
    base_prompt,
    image_purpose,
    prompt_callback=None,
):
    if provider == TITLE_IMAGE_PROVIDER_OPENAI:
        image_prompt = openai_recipe_detail_image_prompt(base_prompt, image_purpose)
        notify_recipe_detail_image_prompt(prompt_callback, image_prompt, TITLE_IMAGE_PROVIDER_OPENAI)
        return (
            generate_recipe_detail_image_with_openai(image_prompt),
            TITLE_IMAGE_PROVIDER_OPENAI,
            False,
            image_prompt,
        )

    if provider == TITLE_IMAGE_PROVIDER_OLLAMA_PROMPT_ONLY:
        if not os.getenv("OPENAI_API_KEY"):
            raise TitleImageGenerationError(
                "openai_api_key_missing",
                TITLE_IMAGE_OPENAI_SETUP_MESSAGE,
                error_code="OPENAI_API_KEY_MISSING",
            )
        enhanced_prompt = enhance_recipe_image_prompt_with_ollama(
            recipe_data,
            recipe_title,
            base_prompt,
            required=True,
            image_purpose=image_purpose,
        )
        print("[TitleImage] Ollama only created the prompt; image_provider=openai")
        notify_recipe_detail_image_prompt(prompt_callback, enhanced_prompt, TITLE_IMAGE_PROVIDER_OPENAI)
        return (
            request_recipe_step_image_bytes(enhanced_prompt),
            TITLE_IMAGE_PROVIDER_OPENAI,
            False,
            enhanced_prompt,
        )

    if provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        ensure_comfyui_available()
        enhanced_prompt = enhance_recipe_image_prompt_with_ollama(
            recipe_data,
            recipe_title,
            base_prompt,
            required=False,
            image_purpose=image_purpose,
        )
        notify_recipe_detail_image_prompt(prompt_callback, enhanced_prompt, TITLE_IMAGE_PROVIDER_COMFYUI)
        return (
            request_comfyui_image_bytes(enhanced_prompt, image_purpose=image_purpose),
            TITLE_IMAGE_PROVIDER_COMFYUI,
            False,
            enhanced_prompt,
        )

    raise TitleImageGenerationError(
        f"unsupported_provider:{provider}",
        "Unsupported image provider.",
        error_code="UNSUPPORTED_TITLE_IMAGE_PROVIDER",
    )


def generate_recipe_detail_image_bytes(
    recipe_data,
    recipe_title,
    base_prompt,
    image_purpose,
    provider=None,
    prompt_callback=None,
):
    provider = title_image_provider(provider)
    print(f"[TitleImage] provider={provider}")

    try:
        return generate_recipe_detail_image_bytes_for_provider(
            provider,
            recipe_data,
            recipe_title,
            base_prompt,
            image_purpose,
            prompt_callback=prompt_callback,
        )
    except TitleImageGenerationError as exc:
        title_image_log_failure(exc.reason)
        fallback_provider = title_image_fallback_provider()
        if provider == TITLE_IMAGE_PROVIDER_COMFYUI and fallback_provider == TITLE_IMAGE_PROVIDER_OPENAI:
            try:
                image_prompt = openai_recipe_detail_image_prompt(base_prompt, image_purpose)
                notify_recipe_detail_image_prompt(prompt_callback, image_prompt, TITLE_IMAGE_PROVIDER_OPENAI)
                return (
                    generate_recipe_detail_image_with_openai(image_prompt),
                    TITLE_IMAGE_PROVIDER_OPENAI,
                    True,
                    image_prompt,
                )
            except TimeoutError:
                title_image_log_failure("fallback_openai_timeout")
                raise
            except TitleImageGenerationError as fallback_exc:
                title_image_log_failure(f"fallback_{fallback_exc.reason}")
                raise
            except Exception as fallback_exc:
                title_image_log_failure(
                    f"fallback_openai_failed:{type(fallback_exc).__name__}:{fallback_exc}"
                )
                raise TitleImageGenerationError(
                    f"fallback_openai_failed:{type(fallback_exc).__name__}:{fallback_exc}",
                    "Image generation failed. Please try again.",
                    error_code="RECIPE_DETAIL_IMAGE_FAILED",
                ) from fallback_exc
        raise


def generated_recipe_detail_image_local_path(image_url):
    image_url = str(image_url or "").strip()
    prefix = f"{STEP_IMAGE_URL_PREFIX}/"
    if not image_url.startswith(prefix):
        return ""

    filename = image_url[len(prefix):].strip().replace("\\", "/").split("/")[-1]
    if not filename:
        return ""

    return str(STEP_IMAGE_FOLDER / filename)


def generate_recipe_cover_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    overwrite = bool(payload.get("overwrite") or payload.get("force"))
    provider = title_image_provider_from_payload(payload)
    print(f"[TitleImage] provider={provider}")

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_source_url = str(recipe_data.get("source_url") or url).strip() or url
    fallback_alt = str(
        payload.get("alt")
        or recipe_data.get("recipe_title")
        or recipe_data.get("display_name")
        or "Recipe title image"
    ).strip()

    existing_cover_image = editable_recipe_cover_image(recipe_source_url, recipe_data)
    if existing_cover_image and not overwrite:
        return {
            "ok": False,
            "error": "This recipe already has a title image. Use Regenerate title image to replace it.",
            "cover_image": existing_cover_image,
        }

    recipe_title = str(recipe_data.get("recipe_title") or recipe_data.get("display_name") or "").strip()
    if not recipe_title:
        return {"ok": False, "error": "Add a recipe title before generating a title image."}

    prompt = build_recipe_cover_image_prompt(recipe_data, recipe_title)

    try:
        image_bytes, used_provider, image_source, fallback_used, image_prompt = generate_recipe_cover_image_bytes_for_provider(
            provider,
            recipe_data,
            recipe_title,
            prompt,
        )
    except TitleImageGenerationError as exc:
        title_image_log_failure(exc.reason)
        fallback_provider = title_image_fallback_provider()
        if provider == TITLE_IMAGE_PROVIDER_COMFYUI and fallback_provider == TITLE_IMAGE_PROVIDER_OPENAI:
            try:
                image_bytes = generate_recipe_cover_image_with_openai(prompt)
                used_provider = TITLE_IMAGE_PROVIDER_OPENAI
                image_source = "ai_generated_image"
                fallback_used = True
                image_prompt = prompt
            except TimeoutError:
                title_image_log_failure("fallback_openai_timeout")
                return {
                    "ok": False,
                    "error": "Title image generation timed out. Please try again.",
                    "error_code": "OPENAI_TIMEOUT",
                }
            except TitleImageGenerationError as fallback_exc:
                title_image_log_failure(f"fallback_{fallback_exc.reason}")
                return {
                    "ok": False,
                    "error": fallback_exc.user_message,
                    "error_code": fallback_exc.error_code,
                }
            except Exception as fallback_exc:
                title_image_log_failure(f"fallback_openai_failed:{type(fallback_exc).__name__}:{fallback_exc}")
                return {
                    "ok": False,
                    "error": "Title image generation failed. Please try again.",
                    "error_code": "RECIPE_TITLE_IMAGE_FAILED",
                }
        else:
            return {
                "ok": False,
                "error": exc.user_message,
                "error_code": exc.error_code,
                "provider": provider,
                "local_generation_unavailable": exc.local_unavailable,
            }
    except TimeoutError:
        title_image_log_failure("openai_timeout")
        return {
            "ok": False,
            "error": "Title image generation timed out. Please try again.",
            "error_code": "OPENAI_TIMEOUT",
        }
    except Exception as exc:
        title_image_log_failure(f"title_image_failed:{type(exc).__name__}:{exc}")
        return {
            "ok": False,
            "error": "Title image generation failed. Please try again.",
            "error_code": "RECIPE_TITLE_IMAGE_FAILED",
        }

    if not image_bytes:
        title_image_log_failure("empty_image_response")
        return {
            "ok": False,
            "error": "Title image generation did not return an image. Please try again.",
            "error_code": "RECIPE_TITLE_IMAGE_EMPTY",
        }

    result = save_generated_recipe_cover_image(
        recipe_source_url,
        recipe_data,
        image_bytes,
        fallback_alt,
        image_source,
        used_provider,
        fallback_used=fallback_used,
        image_prompt=image_prompt,
    )
    if result.get("ok") and used_provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        generated_path = str((result.get("cover_image") or {}).get("path") or "").strip()
        print(f"[TitleImage] generated_local_image_path={generated_path}")
    return result


def save_recipe_detail_image_upload(original_url, kind, target, uploaded_file):
    original_url = str(original_url or "").strip()
    requested_kind = str(kind or "").strip().lower()
    image_kind = requested_kind if requested_kind in {"equipment", "ingredient"} else "step"

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
        target_equipment["equipment_image_prompt"] = ""
        equipment_items[target_index] = {
            **target_equipment,
            "equipment": equipment_text,
            "text": equipment_text,
        }
        recipe_data["equipment"] = equipment_items
        save_recipe_output(recipe_source_url, recipe_data)
        sync_recipe_master_records(recipe_source_url, recipe_data=recipe_data)
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

    if image_kind == "ingredient":
        ingredients = [
            dict(item)
            for item in recipe_data.get("ingredients", [])
            if isinstance(item, dict)
        ]
        target_index, target_ingredient = find_ingredient_for_index(ingredients, target)

        if target_ingredient is None:
            return {"ok": False, "error": "Ingredient was not found."}

        image_url = save_uploaded_recipe_detail_image_file(
            recipe_source_url,
            image_kind,
            target_index + 1,
            uploaded_file,
            extension,
        )
        ingredient_text = str(
            target_ingredient.get("ingredient")
            or target_ingredient.get("name")
            or target_ingredient.get("purchasable_item")
            or target_ingredient.get("original_text")
            or ""
        ).strip()
        target_ingredient["ingredient_image_url"] = image_url
        target_ingredient["ingredient_image_generated_at"] = generated_at
        target_ingredient["ingredient_image_prompt"] = ""
        ingredients[target_index] = {
            **target_ingredient,
            "ingredient": ingredient_text,
        }
        recipe_data["ingredients"] = ingredients
        save_recipe_output(recipe_source_url, recipe_data)
        sync_recipe_master_records(recipe_source_url, recipe_data=recipe_data)
        finish_recipe_image_progress(
            "ingredient",
            recipe_source_url,
            target_index + 1,
            ok=True,
            image_url=image_url,
            generated_at=generated_at,
        )

        return {
            "ok": True,
            "url": recipe_source_url,
            "kind": "ingredient",
            "ingredient_index": target_index + 1,
            "ingredient_image_url": image_url,
            "ingredient_image_generated_at": generated_at,
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


def remove_recipe_detail_image(original_url, kind, target):
    original_url = str(original_url or "").strip()
    requested_kind = str(kind or "").strip().lower()
    image_kind = requested_kind if requested_kind in {"equipment", "ingredient"} else "step"

    if not original_url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(original_url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_source_url = str(recipe_data.get("source_url") or original_url).strip() or original_url
    recipe_data["source_url"] = recipe_source_url

    if image_kind == "equipment":
        equipment_items = normalize_equipment_records(recipe_data.get("equipment", []))
        target_index, target_equipment = find_equipment_for_index(equipment_items, target)

        if target_equipment is None:
            return {"ok": False, "error": "Equipment item was not found."}

        equipment_text = str(
            target_equipment.get("equipment")
            or target_equipment.get("text")
            or target_equipment.get("name")
            or ""
        ).strip()
        target_equipment.pop("image_url", None)
        target_equipment.pop("image_generated_at", None)
        target_equipment["equipment_image_url"] = ""
        target_equipment["equipment_image_generated_at"] = ""
        target_equipment["equipment_image_prompt"] = ""
        equipment_items[target_index] = {
            **target_equipment,
            "equipment": equipment_text,
            "text": equipment_text,
        }
        recipe_data["equipment"] = equipment_items
        save_recipe_output(recipe_source_url, recipe_data)
        sync_recipe_master_records(recipe_source_url, recipe_data=recipe_data)

        return {
            "ok": True,
            "url": recipe_source_url,
            "kind": "equipment",
            "equipment_index": target_index + 1,
            "equipment_image_url": "",
            "equipment_image_generated_at": "",
            "image_url": "",
            "generated_at": "",
        }

    if image_kind == "ingredient":
        ingredients = [
            dict(item)
            for item in recipe_data.get("ingredients", [])
            if isinstance(item, dict)
        ]
        target_index, target_ingredient = find_ingredient_for_index(ingredients, target)

        if target_ingredient is None:
            return {"ok": False, "error": "Ingredient was not found."}

        ingredient_text = str(
            target_ingredient.get("ingredient")
            or target_ingredient.get("name")
            or target_ingredient.get("purchasable_item")
            or target_ingredient.get("original_text")
            or ""
        ).strip()
        target_ingredient.pop("image_url", None)
        target_ingredient.pop("image_generated_at", None)
        target_ingredient["ingredient_image_url"] = ""
        target_ingredient["ingredient_image_generated_at"] = ""
        target_ingredient["ingredient_image_prompt"] = ""
        ingredients[target_index] = {
            **target_ingredient,
            "ingredient": ingredient_text,
        }
        recipe_data["ingredients"] = ingredients
        save_recipe_output(recipe_source_url, recipe_data)
        sync_recipe_master_records(recipe_source_url, recipe_data=recipe_data)

        return {
            "ok": True,
            "url": recipe_source_url,
            "kind": "ingredient",
            "ingredient_index": target_index + 1,
            "ingredient_image_url": "",
            "ingredient_image_generated_at": "",
            "image_url": "",
            "generated_at": "",
        }

    instructions = sorted(
        normalize_instruction_records(recipe_data.get("instructions", [])),
        key=lambda item: item["step_number"],
    )
    target_index, target_instruction = find_instruction_for_step(instructions, target)

    if target_instruction is None:
        return {"ok": False, "error": "Instruction step was not found."}

    step_number = target_instruction.get("step_number")
    instruction_text = str(target_instruction.get("instruction") or target_instruction.get("text") or "").strip()
    target_instruction.pop("image_url", None)
    target_instruction.pop("image_generated_at", None)
    target_instruction["step_image_url"] = ""
    target_instruction["step_image_generated_at"] = ""
    instructions[target_index] = {
        **target_instruction,
        "instruction": instruction_text,
        "text": instruction_text,
    }
    recipe_data["instructions"] = instructions
    save_recipe_output(recipe_source_url, recipe_data)

    return {
        "ok": True,
        "url": recipe_source_url,
        "kind": "step",
        "step_number": step_number,
        "step_image_url": "",
        "step_image_generated_at": "",
        "image_url": "",
        "generated_at": "",
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
    provider = title_image_provider_from_payload(payload)

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

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
    start_recipe_image_progress("step", url, progress_target, "Generating step image...", image_prompt=prompt)
    image_prompt = prompt

    def record_step_image_prompt(resolved_prompt, prompt_provider):
        del prompt_provider
        nonlocal image_prompt
        image_prompt = resolved_prompt
        start_recipe_image_progress(
            "step",
            url,
            progress_target,
            "Generating step image...",
            image_prompt=image_prompt,
        )

    try:
        image_bytes, used_provider, fallback_used, image_prompt = generate_recipe_detail_image_bytes(
            recipe_data,
            recipe_title,
            prompt,
            "recipe instruction step image",
            provider=provider,
            prompt_callback=record_step_image_prompt,
        )
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }
    except TitleImageGenerationError as exc:
        error = exc.user_message
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "error_code": exc.error_code,
            "provider": provider,
            "local_generation_unavailable": exc.local_unavailable,
            "image_prompt": image_prompt,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("step", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    step_image_url = save_recipe_step_image_file(url, target_instruction.get("step_number"), image_bytes)
    if used_provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        print(f"[TitleImage] generated_local_image_path={generated_recipe_detail_image_local_path(step_image_url)}")
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
        image_prompt=image_prompt,
    )

    return {
        "ok": True,
        "url": url,
        "step_number": target_instruction.get("step_number"),
        "step_image_url": step_image_url,
        "step_image_generated_at": generated_at,
        "provider": used_provider,
        "fallback_used": bool(fallback_used),
        "image_prompt": image_prompt,
    }


def generate_recipe_equipment_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_index = payload.get("equipment_index") or payload.get("equipment_number")
    provider = title_image_provider_from_payload(payload)

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

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
    image_prompt = finalize_equipment_image_prompt(prompt)
    start_recipe_image_progress(
        "equipment",
        url,
        progress_target,
        "Generating equipment image...",
        image_prompt=image_prompt,
    )

    def record_equipment_image_prompt(resolved_prompt, prompt_provider):
        del prompt_provider
        nonlocal image_prompt
        image_prompt = resolved_prompt
        start_recipe_image_progress(
            "equipment",
            url,
            progress_target,
            "Generating equipment image...",
            image_prompt=image_prompt,
        )

    try:
        image_bytes, used_provider, fallback_used, image_prompt = generate_recipe_detail_image_bytes(
            recipe_data,
            recipe_title,
            prompt,
            "recipe equipment item image",
            provider=provider,
            prompt_callback=record_equipment_image_prompt,
        )
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }
    except TitleImageGenerationError as exc:
        error = exc.user_message
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "error_code": exc.error_code,
            "provider": provider,
            "local_generation_unavailable": exc.local_unavailable,
            "image_prompt": image_prompt,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("equipment", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    equipment_image_url = save_recipe_equipment_image_file(url, target_index + 1, image_bytes)
    if used_provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        print(f"[TitleImage] generated_local_image_path={generated_recipe_detail_image_local_path(equipment_image_url)}")
    generated_at = datetime.now(timezone.utc).isoformat()
    target_equipment["equipment_image_url"] = equipment_image_url
    target_equipment["equipment_image_generated_at"] = generated_at
    target_equipment["equipment_image_prompt"] = image_prompt

    equipment_items[target_index] = {
        **target_equipment,
        "equipment": equipment_text,
        "text": equipment_text,
    }
    recipe_data["equipment"] = equipment_items
    save_recipe_output(url, recipe_data)
    sync_recipe_master_records(url, recipe_data=recipe_data)
    finish_recipe_image_progress(
        "equipment",
        url,
        progress_target,
        ok=True,
        image_url=equipment_image_url,
        generated_at=generated_at,
        image_prompt=image_prompt,
    )

    return {
        "ok": True,
        "url": url,
        "equipment_index": target_index + 1,
        "equipment_image_url": equipment_image_url,
        "equipment_image_generated_at": generated_at,
        "provider": used_provider,
        "fallback_used": bool(fallback_used),
        "image_prompt": image_prompt,
    }


def generate_recipe_ingredient_image(payload):
    payload = payload if isinstance(payload, dict) else {}
    url = str(payload.get("url") or payload.get("recipe_url") or "").strip()
    requested_index = payload.get("ingredient_index") or payload.get("ingredient_number")
    provider = title_image_provider_from_payload(payload)

    if not url:
        return {"ok": False, "error": "Recipe URL is required."}

    recipe_data = load_recipe_output(url)
    if not recipe_data:
        return {"ok": False, "error": "Recipe data was not found."}

    recipe_title = str(recipe_data.get("recipe_title") or recipe_data.get("display_name") or "").strip()
    ingredients = [
        dict(item)
        for item in recipe_data.get("ingredients", [])
        if isinstance(item, dict)
    ]
    target_index, target_ingredient = find_ingredient_for_index(ingredients, requested_index)

    if target_ingredient is None:
        return {"ok": False, "error": "Ingredient was not found."}

    ingredient_text = str(
        target_ingredient.get("ingredient")
        or target_ingredient.get("name")
        or target_ingredient.get("purchasable_item")
        or target_ingredient.get("original_text")
        or ""
    ).strip()
    if not ingredient_text:
        return {"ok": False, "error": "Add ingredient text before generating an image."}

    prompt = build_recipe_ingredient_image_prompt(
        recipe_title=recipe_title,
        servings=str(recipe_data.get("servings") or "").strip(),
        ingredient_number=target_index + 1,
        ingredient=target_ingredient,
    )

    progress_target = target_index + 1
    image_prompt = prompt
    start_recipe_image_progress(
        "ingredient",
        url,
        progress_target,
        "Generating ingredient image...",
        image_prompt=image_prompt,
    )

    def record_ingredient_image_prompt(resolved_prompt, prompt_provider):
        del prompt_provider
        nonlocal image_prompt
        image_prompt = resolved_prompt
        start_recipe_image_progress(
            "ingredient",
            url,
            progress_target,
            "Generating ingredient image...",
            image_prompt=image_prompt,
        )

    try:
        image_bytes, used_provider, fallback_used, image_prompt = generate_recipe_detail_image_bytes(
            recipe_data,
            recipe_title or ingredient_text,
            prompt,
            "recipe ingredient image",
            provider=provider,
            prompt_callback=record_ingredient_image_prompt,
        )
    except TimeoutError:
        error = "Image generation timed out. Please try again."
        finish_recipe_image_progress("ingredient", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }
    except TitleImageGenerationError as exc:
        error = exc.user_message
        finish_recipe_image_progress("ingredient", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "error_code": exc.error_code,
            "provider": provider,
            "local_generation_unavailable": exc.local_unavailable,
            "image_prompt": image_prompt,
        }
    except Exception:
        error = "Image generation failed. Please try again."
        finish_recipe_image_progress("ingredient", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    if not image_bytes:
        error = "Image generation did not return an image. Please try again."
        finish_recipe_image_progress("ingredient", url, progress_target, ok=False, error=error, image_prompt=image_prompt)
        return {
            "ok": False,
            "error": error,
            "image_prompt": image_prompt,
        }

    ingredient_image_url = save_recipe_ingredient_image_file(url, target_index + 1, image_bytes)
    if used_provider == TITLE_IMAGE_PROVIDER_COMFYUI:
        print(f"[TitleImage] generated_local_image_path={generated_recipe_detail_image_local_path(ingredient_image_url)}")
    generated_at = datetime.now(timezone.utc).isoformat()
    target_ingredient["ingredient_image_url"] = ingredient_image_url
    target_ingredient["ingredient_image_generated_at"] = generated_at
    target_ingredient["ingredient_image_prompt"] = image_prompt

    ingredients[target_index] = {
        **target_ingredient,
        "ingredient": ingredient_text,
    }
    recipe_data["ingredients"] = ingredients
    save_recipe_output(url, recipe_data)
    sync_recipe_master_records(url, recipe_data=recipe_data)
    finish_recipe_image_progress(
        "ingredient",
        url,
        progress_target,
        ok=True,
        image_url=ingredient_image_url,
        generated_at=generated_at,
        image_prompt=image_prompt,
    )

    return {
        "ok": True,
        "url": url,
        "ingredient_index": target_index + 1,
        "ingredient_image_url": ingredient_image_url,
        "ingredient_image_generated_at": generated_at,
        "provider": used_provider,
        "fallback_used": bool(fallback_used),
        "image_prompt": image_prompt,
    }


def find_ingredient_for_index(ingredients, requested_index):
    try:
        index = int(float(requested_index)) - 1
    except (TypeError, ValueError):
        index = -1

    if 0 <= index < len(ingredients):
        return index, ingredients[index]

    return -1, None


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
    del recipe_title, servings, ingredients
    return f"""Generate a realistic product reference image for one cooking equipment item.

Equipment item number:
{equipment_item_number}

Equipment item:
{equipment_item}

Visual requirements:
- The equipment item text is the subject; match it literally
- Show one clean, empty {equipment_item} as the single obvious main subject
- Use a plain seamless studio background, not a kitchen, room, or countertop scene
- Make the equipment visually clear, centered, and easy to identify
- Bright soft product photography lighting
- Realistic product catalog photography
- High-end cookware or appliance reference style
- Plain unlabeled object surface
- No food, ingredients, liquids, hands, room interiors, cabinets, sinks, stoves, or windows
"""


def build_recipe_ingredient_image_prompt(recipe_title, servings, ingredient_number, ingredient):
    ingredient = ingredient if isinstance(ingredient, dict) else {}
    ingredient_name = str(
        ingredient.get("ingredient")
        or ingredient.get("name")
        or ingredient.get("purchasable_item")
        or ingredient.get("original_text")
        or ""
    ).strip()
    quantity = str(ingredient.get("quantity") or ingredient.get("recipe_qty") or "").strip()
    unit = str(ingredient.get("unit") or "").strip()
    preparation = str(ingredient.get("preparation") or "").strip()
    purchasable_item = str(ingredient.get("purchasable_item") or ingredient.get("buy_as") or "").strip()

    return f"""Generate a realistic product reference image for one recipe ingredient.

Recipe title:
{recipe_title or "Not specified"}

Servings:
{servings or "Not specified"}

Ingredient number:
{ingredient_number}

Ingredient:
{ingredient_name}

Quantity:
{" ".join(part for part in [quantity, unit] if part).strip() or "Not specified"}

Preparation:
{preparation or "Not specified"}

Shopping form:
{purchasable_item or ingredient_name}

Visual requirements:
- The ingredient is the single obvious main subject; match it literally
- Show the ingredient as a clean food reference image, not as a finished dish
- Use a plain seamless studio background or simple neutral surface
- Make the ingredient visually clear, centered, and easy to identify
- Bright soft product photography lighting
- Realistic grocery or cookbook ingredient photography
- No text, labels, logos, brand packaging, price tags, hands, utensils, or recipe cards
- Do not show unrelated ingredients, cooked steps, plated meals, or restaurant scenes
"""


def build_recipe_cover_image_prompt(recipe_data, recipe_title):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    servings = str(recipe_data.get("servings") or "").strip()
    cuisine = ", ".join(normalize_text_rows(recipe_data.get("cuisine_tags") or recipe_data.get("cuisine")))
    description = str(
        recipe_data.get("description")
        or recipe_data.get("summary")
        or recipe_data.get("notes")
        or ""
    ).strip()
    menu_section = str(recipe_data.get("menu_section") or recipe_data.get("section") or "").strip()
    ingredients = recipe_step_image_prompt_ingredients(recipe_data.get("ingredients", []))

    return f"""Generate a realistic finished-dish title image for this recipe.

Recipe title:
{recipe_title}

Servings:
{servings or "Not specified"}

Cuisine or menu tags:
{cuisine or "Not specified"}

Menu section:
{menu_section or "Not specified"}

Description:
{description or "Not specified"}

Ingredients:
{ingredients or "Not specified"}

Visual requirements:
- Show the finished dish, plated and ready to eat
- Use the actual recipe ingredients and likely cuisine style
- Bright natural light with appetizing color and texture
- High-end cookbook food photography
- Clean table or kitchen background
- Do not include text, captions, labels, menus, logos, watermarks, or branded packaging
- Do not pretend this is an actual restaurant photo
- Avoid extra side dishes unless they are clearly implied by the recipe
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


def request_recipe_title_image_bytes(prompt):
    timeout_seconds = int(os.getenv("OPENAI_RECIPE_TITLE_IMAGE_TIMEOUT_SECONDS", "90"))
    model = os.getenv(
        "OPENAI_RECIPE_TITLE_IMAGE_MODEL",
        os.getenv("OPENAI_STEP_IMAGE_MODEL", "gpt-image-1"),
    )
    size = os.getenv("OPENAI_RECIPE_TITLE_IMAGE_SIZE", os.getenv("OPENAI_STEP_IMAGE_SIZE", "1024x1024"))
    quality = os.getenv("OPENAI_RECIPE_TITLE_IMAGE_QUALITY", os.getenv("OPENAI_STEP_IMAGE_QUALITY", "medium"))

    client = get_openai_client()
    if hasattr(client, "with_options"):
        client = client.with_options(timeout=timeout_seconds)

    try:
        print(
            f"[OpenAI] action=recipe-title-image model={model} "
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
            action_name="recipe-title-image",
            model=model,
        )
        record_openai_usage(
            response,
            "recipe-title-image",
            model=model,
            metadata={"size": size, "quality": quality},
        )
    except Exception as exc:
        is_timeout = "timeout" in str(exc).lower() or "timed out" in str(exc).lower()
        log_recipe_edit_openai_exception(
            "recipe-title-image",
            model,
            exc,
            "OPENAI_TIMEOUT" if is_timeout else "RECIPE_TITLE_IMAGE_FAILED",
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


def save_recipe_ingredient_image_file(recipe_url, ingredient_index, image_bytes):
    STEP_IMAGE_FOLDER.mkdir(parents=True, exist_ok=True)
    ingredient_key = safe_filename(str(ingredient_index or "ingredient"))
    filename = f"{safe_filename(recipe_url)}_ingredient_{ingredient_key}_{uuid.uuid4().hex[:12]}.png"
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

        item = normalize_ingredient_unit_fields(dict(item))

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


def remove_recipe_output_file(url):
    recipe_key = normalize_recipe_url_key(url)
    json_path = Path(os.fspath(OUTPUT_FOLDER / f"{safe_filename(url)}.json"))
    with _RECIPE_OUTPUT_WRITE_LOCK:
        json_path.unlink(missing_ok=True)
    if has_request_context():
        cached = getattr(g, "_recipe_edit_output_index", None)
        if isinstance(cached, dict):
            cached.pop(recipe_key, None)


def remove_stale_recipe_output(original_url, source_url):
    original_path = Path(os.fspath(OUTPUT_FOLDER / f"{safe_filename(original_url)}.json"))
    source_path = Path(os.fspath(OUTPUT_FOLDER / f"{safe_filename(source_url)}.json"))
    if original_path == source_path or not original_path.exists():
        return False

    original_data = _read_recipe_output_json(original_path)
    original_key = normalize_recipe_url_key(original_url)
    if not isinstance(original_data, dict):
        return False
    if normalize_recipe_url_key(original_data.get("source_url")) != original_key:
        return False

    remove_recipe_output_file(original_url)
    return True


def save_recipe_output(url, recipe_data):
    normalize_recipe_unit_fields(recipe_data)
    json_path = Path(os.fspath(OUTPUT_FOLDER / f"{safe_filename(url)}.json"))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = json_path.with_name(f".{json_path.name}.{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(recipe_data, indent=2, ensure_ascii=False)
    with _RECIPE_OUTPUT_WRITE_LOCK:
        try:
            temporary_path.write_text(serialized, encoding="utf-8")
            os.replace(temporary_path, json_path)
        finally:
            temporary_path.unlink(missing_ok=True)
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
    remove_recipe_master_records_for_recipe(original_url)


def update_recipe_ingredient_record(url, quantity, recipe_data, preserve_existing_cover=True):
    data = load_recipe_ingredients()
    key = normalize_recipe_url_key(url)
    existing = data.get(key, {})
    cover_image = recipe_data.get("cover_image")
    if not cover_image and preserve_existing_cover:
        cover_image = existing.get("cover_image")
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
        "ingredient_details": ingredient_detail_records(recipe_metadata=recipe_data),
    }

    if cover_image:
        record["cover_image"] = cover_image

    data[key] = record
    save_recipe_ingredients(data)
    sync_recipe_master_records(
        url,
        ingredients=record.get("ingredients", []),
        recipe_data=recipe_data,
        force_store_sections_from_recipe=True,
    )


def recipe_edit_log_value(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def recipe_edit_ingredient_name(item):
    if not isinstance(item, dict):
        return ""

    return nullable_string(
        item.get("ingredient")
        or item.get("name")
        or item.get("normalized_name")
        or item.get("parsed_name")
        or item.get("purchasable_item")
        or item.get("original_text")
    )


def recipe_edit_ingredient_classification_text(item, master_record=None):
    item = item if isinstance(item, dict) else {}
    master_record = master_record if isinstance(master_record, dict) else {}
    return " ".join(
        part
        for part in (
            recipe_edit_ingredient_name(item),
            item.get("buy_as"),
            item.get("purchasable_item"),
            item.get("original_recipe_text"),
            item.get("original_text"),
            item.get("normalized_name"),
            item.get("master_normalized_name"),
            master_record.get("name"),
            master_record.get("normalized_name"),
        )
        if part
    )


def recipe_edit_ingredient_master_id(item):
    if not isinstance(item, dict):
        return 0

    for key in ("ingredient_id", "master_ingredient_id"):
        try:
            ingredient_id = int(item.get(key) or 0)
        except (TypeError, ValueError):
            ingredient_id = 0
        if ingredient_id > 0:
            return ingredient_id

    return 0


def recipe_edit_ingredient_normalized_keys(item):
    if not isinstance(item, dict):
        return []

    keys = []
    for key in (
        "master_normalized_name",
        "normalized_name",
        "ingredient",
        "name",
        "parsed_name",
        "purchasable_item",
        "buy_as",
    ):
        normalized = normalized_master_name(item.get(key))
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def recipe_edit_add_master_record_to_lookup(lookup, row):
    if not isinstance(row, dict):
        return

    try:
        ingredient_id = int(row.get("ingredient_id") or row.get("id") or 0)
    except (TypeError, ValueError):
        ingredient_id = 0

    section = clean_ingredient_store_section(
        row.get("master_store_section") or row.get("store_section"),
        default="",
    )
    normalized = normalized_master_name(row.get("normalized_name") or row.get("name"))
    if not ingredient_id and not normalized:
        return

    record = {
        **row,
        "id": ingredient_id or row.get("id"),
        "ingredient_id": ingredient_id,
        "store_section": section,
        "normalized_name": normalized or row.get("normalized_name") or "",
    }
    if ingredient_id:
        lookup["by_id"][ingredient_id] = record
    if normalized:
        lookup["by_normalized_name"][normalized] = record


def clean_recipe_custom_store_section(value):
    return re.sub(r"\s+", " ", str(value or "").strip())[:60]


def recipe_edit_ingredient_master_lookup(ingredients, recipe_url=None):
    lookup = ingredient_master_records_for_items(ingredients)
    lookup = {
        "by_id": dict(lookup.get("by_id") or {}),
        "by_normalized_name": dict(lookup.get("by_normalized_name") or {}),
    }
    recipe_url = str(recipe_url or "").strip()
    if not recipe_url:
        return lookup

    for row in recipe_master_rows("recipe_ingredients", recipe_url):
        recipe_edit_add_master_record_to_lookup(lookup, row)

    return lookup


def recipe_edit_master_record_for_ingredient(item, master_lookup):
    ingredient_id = recipe_edit_ingredient_master_id(item)
    if ingredient_id:
        record = (master_lookup.get("by_id") or {}).get(ingredient_id)
        if record:
            return record

    by_normalized_name = master_lookup.get("by_normalized_name") or {}
    for normalized in recipe_edit_ingredient_normalized_keys(item):
        record = by_normalized_name.get(normalized)
        if record:
            return record

    return None


def recipe_edit_store_section_for_ingredient(item, master_lookup, recipe_id=""):
    ingredient_name = recipe_edit_ingredient_name(item)
    master_record = recipe_edit_master_record_for_ingredient(item, master_lookup)
    custom_section = (
        clean_recipe_custom_store_section(item.get("store_section"))
        if truthy(item.get("store_section_custom"))
        else ""
    )
    if custom_section:
        classification = {
            "store_section": custom_section,
            "store_section_source": "manual",
            "store_section_confidence": 1.0,
            "store_section_user_confirmed": True,
            "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": "User selected a custom store section.",
            "store_section_rule": "manual.custom_section",
            "raw_name": item.get("raw_name") or item.get("original_text") or ingredient_name,
            "normalized_name": item.get("normalized_name") or normalized_master_name(ingredient_name),
            "canonical_ingredient": item.get("canonical_ingredient") or "",
            "form": item.get("form") or "",
            "preparation": item.get("preparation") or "",
        }
        return custom_section, master_record, classification

    item_confirmed = truthy(item.get("store_section_user_confirmed"))
    item_source = clean_ingredient_store_section_source(
        item.get("store_section_source"),
        default="legacy",
    )
    if master_record:
        master_section = master_record.get("master_store_section") or master_record.get("store_section")
        master_confirmed = truthy(
            master_record.get("master_store_section_user_confirmed")
            or master_record.get("store_section_user_confirmed")
        )
        master_source = clean_ingredient_store_section_source(
            master_record.get("master_store_section_source")
            or master_record.get("store_section_source"),
            default="legacy",
        )
        trusted_master = master_confirmed or master_source in {"manual", "user_master_data"}
        classification = classify_ingredient_store_section_result(
            {
                **item,
                "raw_name": item.get("raw_name") or item.get("original_text") or ingredient_name,
            },
            recipe_override=item.get("store_section") if item_confirmed else None,
            recipe_override_confirmed=item_confirmed,
            user_master_data=(
                {
                    "store_section": master_section,
                    "store_section_confidence": master_record.get("master_store_section_confidence")
                    or master_record.get("store_section_confidence"),
                    "store_section_reason": master_record.get("master_store_section_reason")
                    or master_record.get("store_section_reason"),
                    "store_section_rule": master_record.get("master_store_section_rule")
                    or master_record.get("store_section_rule"),
                }
                if trusted_master
                else None
            ),
            legacy_section=master_section if not trusted_master else None,
            ai_result=(
                {
                    "store_section": item.get("store_section"),
                    "confidence": item.get("store_section_confidence"),
                    "reason": item.get("store_section_reason"),
                    "normalized_name": item.get("normalized_name"),
                }
                if item_source == "ai"
                else None
            ),
            default="MISC",
        )
        section = classification["store_section"]
        if section:
            print(
                "[IngredientMaster] "
                f"action=store_section_loaded_from_master "
                f"recipe_id={recipe_id} "
                f"ingredient=\"{recipe_edit_log_value(ingredient_name)}\" "
                f"section=\"{section}\""
            )
            return section, master_record, classification

    classification = classify_ingredient_store_section_result(
        {
            **item,
            "raw_name": item.get("raw_name") or item.get("original_text") or ingredient_name,
        },
        recipe_override=item.get("store_section") if item_confirmed else None,
        recipe_override_confirmed=item_confirmed,
        legacy_section=(
            item.get("store_section") or item.get("section")
            if item_source != "ai"
            else None
        ),
        ai_result=(
            {
                "store_section": item.get("store_section"),
                "confidence": item.get("store_section_confidence"),
                "reason": item.get("store_section_reason"),
                "normalized_name": item.get("normalized_name"),
            }
            if item_source == "ai"
            else None
        ),
        default="MISC",
    )
    row_section = classification["store_section"]
    if row_section:
        if row_section == "MISC" and classification.get("store_section_source") == "fallback":
            print(
                "[IngredientMaster] "
                f"action=store_section_missing_default "
                f"ingredient=\"{recipe_edit_log_value(ingredient_name)}\" "
                'section="MISC"'
            )
        return row_section, master_record, classification

    print(
        "[IngredientMaster] "
        f"action=store_section_missing_default "
        f"ingredient=\"{recipe_edit_log_value(ingredient_name)}\" "
        'section="MISC"'
    )
    return "MISC", master_record, classification


def recipe_edit_master_image_url(item, master_record):
    item = item if isinstance(item, dict) else {}
    master_record = master_record if isinstance(master_record, dict) else {}
    return (
        item.get("ingredient_image_url")
        or item.get("image_url")
        or master_record.get("image_url")
        or ""
    )


RECIPE_INGREDIENT_MATCH_METADATA_FIELDS = (
    "matching_status",
    "match_confidence",
    "master_match_confidence",
    "normalization_confidence",
    "matched_master_ingredient",
    "master_ingredient_name",
    "matched_ingredient",
    "best_match",
    "is_best_match",
    "best_available_match",
    "alternative_matches",
    "match_alternatives",
    "match_candidates",
    "candidates",
    "match_source",
    "matching_source",
    "match_reason",
    "matching_reason",
    "match_attempted",
    "needs_match_review",
    "review_match",
    "multiple_matches",
    "pantry_staple",
    "is_pantry_staple",
)


def recipe_ingredient_match_metadata(item, existing=None):
    """Return matching-analysis fields without interpreting or recalculating them."""
    item = item if isinstance(item, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    metadata = {}
    for field in RECIPE_INGREDIENT_MATCH_METADATA_FIELDS:
        if field in item:
            metadata[field] = deepcopy(item[field])
        elif field in existing:
            metadata[field] = deepcopy(existing[field])
    return metadata


def recipe_ingredient_type_value(item):
    """Return the editor Type, using the legacy optional flag only when Type is absent."""
    item = item if isinstance(item, dict) else {}
    explicit_type = str(
        item.get("section")
        or item.get("ingredient_type")
        or item.get("type")
        or ""
    ).strip()
    if explicit_type:
        return explicit_type
    return "optional" if truthy(item.get("optional")) else "main"


def recipe_ingredient_is_optional(item):
    type_key = " ".join(
        recipe_ingredient_type_value(item).lower().replace("_", " ").replace("-", " ").split()
    )
    return type_key == "optional"


def normalize_edit_ingredients(ingredients, recipe_url=None):
    if not isinstance(ingredients, list):
        return []

    master_lookup = recipe_edit_ingredient_master_lookup(ingredients, recipe_url=recipe_url)
    recipe_id = normalize_recipe_url_key(recipe_url) if recipe_url else ""
    rows = []
    for item in ingredients:
        if not isinstance(item, dict):
            continue
        # Normalize a copy for display so legacy rows whose unknown unit was
        # moved into review metadata regain their recipe-specific unit text.
        item = normalize_ingredient_unit_fields(dict(item))

        store_section, master_record, store_section_result = recipe_edit_store_section_for_ingredient(
            item,
            master_lookup,
            recipe_id=recipe_id,
        )
        if master_record:
            try:
                ingredient_id = int(master_record.get("ingredient_id") or master_record.get("id") or 0)
            except (TypeError, ValueError):
                ingredient_id = 0
        else:
            ingredient_id = recipe_edit_ingredient_master_id(item)
        ingredient_image_url = recipe_edit_master_image_url(item, master_record)
        rows.append(apply_purchase_mapping_to_ingredient({
            "ingredient_id": str(ingredient_id) if ingredient_id else "",
            "section": recipe_ingredient_type_value(item),
            "original_text": item.get("original_text") or "",
            "quantity": item.get("quantity") or "",
            "quantity_text": item.get("quantity_text") or "",
            "recipe_qty": item.get("recipe_qty") or item.get("quantity") or "",
            "unit": item.get("unit") or "",
            "unit_id": item.get("unit_id") or "",
            "unit_raw": item.get("unit_raw") or "",
            "unit_review_required": truthy(item.get("unit_review_required")),
            "unit_review_value": item.get("unit_review_value") or "",
            "unit_custom": truthy(item.get("unit_custom")),
            "base_quantity": item.get("base_quantity") or item.get("quantity") or "",
            "base_unit": item.get("base_unit") or item.get("unit") or "",
            "ingredient": item.get("ingredient") or "",
            "parsed_name": item.get("parsed_name") or "",
            "normalized_name": item.get("normalized_name") or "",
            "master_normalized_name": item.get("master_normalized_name") or item.get("normalized_name") or "",
            "preparation": item.get("preparation") or "",
            "size": item.get("size") or "",
            "notes": item.get("notes") or "",
            "confidence": item.get("confidence") or "",
            "match_status": item.get("match_status") or "",
            **recipe_ingredient_match_metadata(item),
            "inferred": truthy(item.get("inferred")),
            "warning": item.get("warning") or "",
            "food_review": normalize_food_review_payload(item.get("food_review")),
            "optional": recipe_ingredient_is_optional(item),
            "store_section": store_section,
            "store_section_custom": truthy(item.get("store_section_custom")),
            "raw_name": item.get("raw_name") or store_section_result.get("raw_name") or item.get("original_text") or item.get("ingredient") or "",
            "canonical_ingredient": item.get("canonical_ingredient") or store_section_result.get("canonical_ingredient") or "",
            "form": item.get("form") or store_section_result.get("form") or "",
            "store_section_source": store_section_result.get("store_section_source") or "fallback",
            "store_section_confidence": ingredient_store_section_confidence(
                store_section_result.get("store_section_confidence")
            ),
            "store_section_user_confirmed": truthy(
                item.get("store_section_user_confirmed")
                or store_section_result.get("store_section_user_confirmed")
            ),
            "store_section_save_to_master": truthy(item.get("store_section_save_to_master")),
            "classifier_version": store_section_result.get("classifier_version") or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": store_section_result.get("store_section_reason") or "",
            "store_section_rule": store_section_result.get("store_section_rule") or "",
            "store_section_order": ingredient_store_section_sort_key(store_section),
            "purchasable_item": item.get("purchasable_item") or item.get("buy_as") or "",
            "purchase_group": item.get("purchase_group") or "",
            "substitutions": normalize_ingredient_substitutions(
                item.get("substitutions")
                or item.get("substitution_options")
                or item.get("alternatives"),
                parent_item=item,
            ),
            "ingredient_image_url": ingredient_image_url,
            "ingredient_image_generated_at": (
                item.get("ingredient_image_generated_at") or item.get("image_generated_at") or ""
            ),
            "ingredient_image_prompt": item.get("ingredient_image_prompt") or item.get("image_prompt") or "",
        }))
    return rows


def normalize_food_review_payload(value):
    if not isinstance(value, dict) or not value:
        return {}

    status = (nullable_string(value.get("status")) or "").lower()
    if status not in {"open", "accepted", "ignored", "reviewed", "manual_edit"}:
        status = "open" if truthy(value.get("needs_review")) else ""

    options = []
    raw_options = value.get("options") if isinstance(value.get("options"), list) else []
    for option in raw_options[:6]:
        if not isinstance(option, dict):
            continue
        ingredient = nullable_string(option.get("ingredient") or option.get("name"))
        if not ingredient:
            continue
        confidence = (nullable_string(option.get("confidence")) or "").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = ""
        options.append({
            "ingredient": ingredient,
            "purchasable_item": nullable_string(option.get("purchasable_item") or option.get("buy_as") or ingredient),
            "quantity": nullable_string(option.get("quantity")),
            "unit": nullable_string(option.get("unit")),
            "original_text": nullable_string(option.get("original_text")),
            "preparation": nullable_string(option.get("preparation")),
            "store_section": nullable_string(option.get("store_section")),
            "reason": nullable_string(option.get("reason")),
            "confidence": confidence,
        })

    needs_review = truthy(value.get("needs_review")) and status not in {"accepted", "ignored", "reviewed"}
    kind = nullable_string(value.get("kind")) or ("ingredient_text" if needs_review or status or options else "")

    if not any((
        needs_review,
        status,
        kind,
        options,
        nullable_string(value.get("reason")),
        nullable_string(value.get("warning")),
        nullable_string(value.get("original_ingredient")),
        nullable_string(value.get("suspicious_phrase")),
    )):
        return {}

    return {
        "needs_review": needs_review,
        "kind": kind or "ingredient_text",
        "status": status or ("open" if needs_review else ""),
        "reason": nullable_string(value.get("reason")),
        "prompt": nullable_string(value.get("prompt")),
        "options": options,
        "source": nullable_string(value.get("source")),
        "confidence": nullable_string(value.get("confidence")),
        "warning": nullable_string(value.get("warning")),
        "original_ingredient": nullable_string(value.get("original_ingredient")),
        "suspicious_phrase": nullable_string(value.get("suspicious_phrase")),
        "text_key": nullable_string(value.get("text_key")),
    }


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
            equipment_image_prompt = str(item.get("equipment_image_prompt") or item.get("image_prompt") or "").strip()
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""
            equipment_image_prompt = ""

        if not text:
            continue

        record.update({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
            "equipment_image_prompt": equipment_image_prompt,
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
    row_metadata = nutrition.get("_row_metadata")
    row_metadata = row_metadata if isinstance(row_metadata, dict) else {}

    if include_defaults:
        for key in DEFAULT_MANUAL_NUTRITION_FIELDS:
            fallback = "per serving" if key == "serving_basis" else ""
            rows.append({
                **(row_metadata.get(key) if isinstance(row_metadata.get(key), dict) else {}),
                "key": key,
                "value": str(nutrition.get(key) or fallback),
            })
            included.add(key)

    for key in NUTRITION_FIELDS:
        if key in included or not nutrition.get(key):
            continue

        rows.append({
            **(row_metadata.get(key) if isinstance(row_metadata.get(key), dict) else {}),
            "key": key,
            "value": str(nutrition.get(key) or ""),
        })
        included.add(key)

    other = nutrition.get("other", [])
    if isinstance(other, list):
        for item in other:
            if isinstance(item, dict):
                key = str(item.get("label") or item.get("name") or "").strip()
                value = str(item.get("value") or item.get("amount") or "").strip()
                if key or value:
                    rows.append({
                        **item,
                        "key": key,
                        "value": value,
                    })

    return rows


def normalize_ingredient_substitutions(value, existing_value=None, parent_item=None):
    candidates = value
    if candidates is None:
        candidates = existing_value

    normalized = normalize_ingredient_substitution_options(candidates, parent_item=parent_item)
    metadata_by_group_and_name = {}
    metadata_by_name = {}
    for option_rows in (existing_value, candidates):
        for option in flatten_ingredient_substitution_alternatives(option_rows):
            if not isinstance(option, dict):
                continue
            name = str(
                option.get("ingredient")
                or option.get("name")
                or option.get("replacement")
                or option.get("substitution")
                or ""
            ).strip()
            key = instruction_match_text_key(name)
            if key:
                alternative_id = str(option.get("alternative_id") or "").strip()
                metadata_key = (alternative_id, key)
                metadata_lookup = (
                    metadata_by_group_and_name
                    if alternative_id
                    else metadata_by_name
                )
                lookup_key = metadata_key if alternative_id else key
                metadata_lookup[lookup_key] = {
                    **metadata_lookup.get(lookup_key, {}),
                    **option,
                }

    rows = []
    for row in normalized:
        name_key = instruction_match_text_key(row.get("ingredient"))
        alternative_id = str(row.get("alternative_id") or "").strip()
        metadata = (
            metadata_by_group_and_name.get((alternative_id, name_key), {})
            if alternative_id
            else metadata_by_name.get(name_key, {})
        )
        merged = {**metadata, **row}
        custom_section = (
            clean_recipe_custom_store_section(metadata.get("store_section"))
            if truthy(metadata.get("store_section_custom"))
            else ""
        )
        if custom_section:
            merged["store_section"] = custom_section
            merged["store_section_custom"] = True
            merged["store_section_order"] = ingredient_store_section_sort_key(custom_section)
        else:
            merged["store_section_custom"] = False
        rows.append(merged)
    return rows


def sanitize_ingredients(value, existing_value=None):
    if not isinstance(value, list):
        return []

    existing_rows = [
        dict(item)
        for item in (existing_value or [])
        if isinstance(item, dict)
    ]
    existing_by_text = {}
    existing_by_row_id = {}
    for existing in existing_rows:
        row_identity = recipe_edit_row_identity(
            existing,
            "recipe_ingredient_id",
            "row_id",
            "id",
        )
        if row_identity:
            existing_by_row_id.setdefault(row_identity, existing)
        for text in (
            existing.get("ingredient"),
            existing.get("name"),
            existing.get("purchasable_item"),
            existing.get("original_text"),
        ):
            key = instruction_match_text_key(text)
            if key:
                existing_by_text.setdefault(key, existing)

    ingredients = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        name = str(item.get("ingredient") or "").strip()
        original_text = str(item.get("original_text") or "").strip()

        if not name and not original_text:
            continue

        base_quantity = nullable_string(item.get("base_quantity"))
        base_unit = nullable_string(item.get("base_unit"))
        row_identity = recipe_edit_row_identity(
            item,
            "recipe_ingredient_id",
            "row_id",
            "id",
        )
        existing = (
            existing_by_row_id.get(row_identity)
            or existing_by_text.get(instruction_match_text_key(name))
            or existing_by_text.get(instruction_match_text_key(item.get("purchasable_item") or item.get("buy_as")))
            or existing_by_text.get(instruction_match_text_key(original_text))
            or (existing_rows[index] if index < len(existing_rows) else {})
            or {}
        )
        store_section_custom = (
            truthy(item.get("store_section_custom"))
            if "store_section_custom" in item
            else truthy(existing.get("store_section_custom"))
        )
        custom_store_section = (
            clean_recipe_custom_store_section(item.get("store_section") or existing.get("store_section"))
            if store_section_custom
            else ""
        )
        if custom_store_section:
            store_section = custom_store_section
            store_section_result = {
                "store_section": store_section,
                "store_section_source": "manual",
                "store_section_confidence": 1.0,
                "store_section_user_confirmed": True,
                "classifier_version": INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
                "store_section_reason": "User selected a custom store section.",
                "store_section_rule": "manual.custom_section",
                "raw_name": item.get("raw_name") or original_text or name,
                "normalized_name": item.get("normalized_name") or normalized_master_name(name),
                "canonical_ingredient": item.get("canonical_ingredient") or "",
                "form": item.get("form") or "",
            }
        else:
            store_section_custom = False
            supplied_source = clean_ingredient_store_section_source(
                item.get("store_section_source") or existing.get("store_section_source"),
                default="legacy",
            )
            user_confirmed = truthy(
                item.get("store_section_user_confirmed")
                if "store_section_user_confirmed" in item
                else existing.get("store_section_user_confirmed")
            )
            supplied_section = item.get("store_section") or existing.get("store_section")
            store_section_result = classify_ingredient_store_section_result(
                {
                    **existing,
                    **item,
                    "raw_name": item.get("raw_name") or original_text or name,
                    "normalized_name": item.get("normalized_name") or name,
                },
                recipe_override=supplied_section if user_confirmed else None,
                recipe_override_confirmed=user_confirmed,
                legacy_section=supplied_section if supplied_source != "ai" else None,
                ai_result=(
                    {
                        "store_section": supplied_section,
                        "confidence": item.get("store_section_confidence"),
                        "reason": item.get("store_section_reason"),
                        "normalized_name": item.get("normalized_name"),
                    }
                    if supplied_source == "ai"
                    else None
                ),
                default="MISC",
            )
            store_section = store_section_result["store_section"]
            if supplied_source == "manual" and truthy(item.get("store_section_save_to_master")):
                store_section_result.update({
                    "store_section_source": "manual",
                    "store_section_user_confirmed": True,
                    "store_section_confidence": 1.0,
                    "store_section_reason": "User confirmed this section for future occurrences.",
                    "store_section_rule": "manual.master_data",
                })
        ingredient_image_url = (
            nullable_string(item.get("ingredient_image_url") or item.get("image_url"))
            or nullable_string(existing.get("ingredient_image_url") or existing.get("image_url"))
        )
        ingredient_image_generated_at = (
            nullable_string(item.get("ingredient_image_generated_at") or item.get("image_generated_at"))
            or nullable_string(existing.get("ingredient_image_generated_at") or existing.get("image_generated_at"))
        )
        ingredient_image_prompt = (
            nullable_string(item.get("ingredient_image_prompt") or item.get("image_prompt"))
            or nullable_string(existing.get("ingredient_image_prompt") or existing.get("image_prompt"))
        )
        substitution_value = next(
            (item.get(field) for field in (
                "substitutions",
                "substitution_options",
                "alternatives",
                "substitutions_text",
            ) if field in item),
            None,
        )
        substitutions = normalize_ingredient_substitutions(
            substitution_value,
            existing.get("substitutions")
            or existing.get("substitution_options")
            or existing.get("alternatives"),
            parent_item={**existing, **item},
        )
        ingredient_type = recipe_ingredient_type_value(item)

        row = {
            "id": nullable_string(item.get("id") or existing.get("id")),
            "recipe_ingredient_id": nullable_string(
                item.get("recipe_ingredient_id") or existing.get("recipe_ingredient_id")
            ),
            "row_id": nullable_string(item.get("row_id") or existing.get("row_id")),
            "ingredient_id": nullable_string(
                item.get("ingredient_id")
                or item.get("master_ingredient_id")
                or existing.get("ingredient_id")
                or existing.get("master_ingredient_id")
            ),
            "section": ingredient_type,
            "original_text": original_text,
            "raw_name": nullable_string(
                item.get("raw_name")
                or store_section_result.get("raw_name")
                or original_text
                or name
            ),
            "quantity": nullable_string(item.get("quantity")),
            "quantity_text": nullable_string(item.get("quantity_text")),
            "recipe_qty": nullable_string(item.get("recipe_qty") or item.get("quantity")),
            "unit": nullable_string(item.get("unit")),
            "unit_id": nullable_string(item.get("unit_id")),
            "unit_raw": nullable_string(item.get("unit_raw") or existing.get("unit_raw")),
            "unit_review_required": truthy(item.get("unit_review_required")),
            "unit_review_value": nullable_string(item.get("unit_review_value")),
            "unit_custom": truthy(item.get("unit_custom") or existing.get("unit_custom")),
            "base_quantity": base_quantity or nullable_string(item.get("quantity")),
            "base_unit": base_unit or nullable_string(item.get("unit")),
            "ingredient": name or original_text,
            "parsed_name": nullable_string(item.get("parsed_name")),
            "normalized_name": nullable_string(
                item.get("normalized_name") or store_section_result.get("normalized_name")
            ),
            "canonical_ingredient": nullable_string(
                item.get("canonical_ingredient")
                or store_section_result.get("canonical_ingredient")
                or existing.get("canonical_ingredient")
            ),
            "form": nullable_string(
                item.get("form")
                or store_section_result.get("form")
                or existing.get("form")
            ),
            "master_normalized_name": nullable_string(
                item.get("master_normalized_name")
                or item.get("normalized_name")
                or existing.get("master_normalized_name")
                or existing.get("normalized_name")
            ),
            "preparation": nullable_string(item.get("preparation")),
            "size": nullable_string(item.get("size")),
            "notes": nullable_string(item.get("notes")),
            "confidence": nullable_string(item.get("confidence")),
            "match_status": nullable_string(item.get("match_status")),
            **recipe_ingredient_match_metadata(item, existing),
            "inferred": truthy(item.get("inferred")),
            "warning": nullable_string(item.get("warning")),
            "food_review": normalize_food_review_payload(item.get("food_review")),
            "optional": recipe_ingredient_is_optional({**item, "section": ingredient_type}),
            "store_section": store_section,
            "store_section_custom": store_section_custom,
            "store_section_source": store_section_result.get("store_section_source") or "fallback",
            "store_section_confidence": ingredient_store_section_confidence(
                store_section_result.get("store_section_confidence")
            ),
            "store_section_user_confirmed": truthy(
                store_section_result.get("store_section_user_confirmed")
            ),
            "store_section_save_to_master": truthy(item.get("store_section_save_to_master")),
            "classifier_version": store_section_result.get("classifier_version") or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": nullable_string(store_section_result.get("store_section_reason")),
            "store_section_rule": nullable_string(store_section_result.get("store_section_rule")),
            "store_section_order": ingredient_store_section_sort_key(store_section),
            "purchasable_item": nullable_string(item.get("purchasable_item") or item.get("buy_as")),
            "purchase_group": nullable_string(item.get("purchase_group")),
            "substitutions": substitutions,
            "ingredient_image_url": ingredient_image_url,
            "ingredient_image_generated_at": ingredient_image_generated_at,
            "ingredient_image_prompt": ingredient_image_prompt,
        }
        normalize_ingredient_unit_fields(row)
        ingredients.append(apply_purchase_mapping_to_ingredient(row))

    return ingredients


def recipe_ingredient_store_section_review_text(item):
    if not isinstance(item, dict):
        return ""

    parts = (
        item.get("ingredient"),
        item.get("name"),
        item.get("parsed_name"),
        item.get("normalized_name"),
        item.get("master_normalized_name"),
        item.get("purchasable_item") or item.get("buy_as"),
        item.get("original_text"),
        item.get("original_recipe_text"),
    )
    return " ".join(
        str(part or "").strip()
        for part in parts
        if str(part or "").strip()
    )


def review_recipe_store_sections(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    ingredients = recipe_data.get("ingredients") if isinstance(recipe_data.get("ingredients"), list) else []
    reviewed_count = 0
    changes = []
    updated_ingredients = []

    for index, item in enumerate(ingredients):
        if not isinstance(item, dict):
            updated_ingredients.append(item)
            continue

        updated_item = dict(item)
        review_text = recipe_ingredient_store_section_review_text(item)
        if not review_text:
            updated_ingredients.append(updated_item)
            continue

        reviewed_count += 1
        current_section = clean_ingredient_store_section(item.get("store_section"), default="MISC")
        user_confirmed = truthy(item.get("store_section_user_confirmed"))
        classification = classify_ingredient_store_section_result(
            {
                **item,
                "raw_name": item.get("raw_name") or item.get("original_text") or review_text,
            },
            recipe_override=current_section if user_confirmed else None,
            recipe_override_confirmed=user_confirmed,
            legacy_section=current_section if user_confirmed else None,
            default="MISC",
        )
        proposed_section = classification["store_section"]
        updated_item["store_section"] = proposed_section
        updated_item["store_section_order"] = ingredient_store_section_sort_key(proposed_section)
        updated_item.update({
            "raw_name": updated_item.get("raw_name") or classification.get("raw_name") or "",
            "normalized_name": updated_item.get("normalized_name") or classification.get("normalized_name") or "",
            "canonical_ingredient": classification.get("canonical_ingredient") or updated_item.get("canonical_ingredient") or "",
            "form": classification.get("form") or updated_item.get("form") or "",
            "store_section_source": classification.get("store_section_source") or "fallback",
            "store_section_confidence": ingredient_store_section_confidence(
                classification.get("store_section_confidence")
            ),
            "store_section_user_confirmed": user_confirmed,
            "classifier_version": classification.get("classifier_version") or INGREDIENT_STORE_SECTION_CLASSIFIER_VERSION,
            "store_section_reason": classification.get("store_section_reason") or "",
            "store_section_rule": classification.get("store_section_rule") or "",
        })
        updated_ingredients.append(updated_item)

        if proposed_section != current_section:
            changes.append({
                "index": index,
                "ingredient": nullable_string(
                    item.get("ingredient")
                    or item.get("name")
                    or item.get("purchasable_item")
                    or item.get("buy_as")
                    or item.get("original_text")
                ),
                "current_store_section": current_section,
                "proposed_store_section": proposed_section,
                "store_section_source": classification.get("store_section_source"),
                "store_section_confidence": classification.get("store_section_confidence"),
                "classifier_version": classification.get("classifier_version"),
                "reason": classification.get("store_section_reason"),
                "rule": classification.get("store_section_rule"),
            })

    updated_recipe = dict(recipe_data)
    updated_recipe["ingredients"] = updated_ingredients

    return {
        "ok": True,
        "recipe": updated_recipe,
        "changes": changes,
        "changed_count": len(changes),
        "reviewed_count": reviewed_count,
    }


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


def recipe_edit_row_identity(item, *field_names):
    if not isinstance(item, dict):
        return ""
    for field in field_names:
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return ""


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
    existing_by_id = {
        recipe_edit_row_identity(item, "equipment_row_id", "equipment_id", "row_id", "id"): item
        for item in existing_rows
        if recipe_edit_row_identity(item, "equipment_row_id", "equipment_id", "row_id", "id")
    }
    equipment = []

    for index, item in enumerate(value):
        prompt_supplied = isinstance(item, dict) and (
            "equipment_image_prompt" in item
            or "image_prompt" in item
        )
        if isinstance(item, dict):
            text = str(item.get("equipment") or item.get("text") or item.get("name") or "").strip()
            equipment_image_url = nullable_string(item.get("equipment_image_url") or item.get("image_url"))
            equipment_image_generated_at = nullable_string(
                item.get("equipment_image_generated_at") or item.get("image_generated_at")
            )
            equipment_image_prompt = nullable_string(item.get("equipment_image_prompt") or item.get("image_prompt"))
        else:
            text = str(item or "").strip()
            equipment_image_url = ""
            equipment_image_generated_at = ""
            equipment_image_prompt = ""

        if not text:
            continue

        item_identity = recipe_edit_row_identity(
            item,
            "equipment_row_id",
            "equipment_id",
            "row_id",
            "id",
        )
        existing = existing_by_id.get(item_identity) if item_identity else None
        existing = existing or existing_by_text.get(instruction_match_text_key(text))
        if existing is None and index < len(existing_rows):
            existing = existing_rows[index]
        existing = existing or {}
        equipment_image_url = equipment_image_url or nullable_string(existing.get("equipment_image_url")) or ""
        equipment_image_generated_at = (
            equipment_image_generated_at
            or nullable_string(existing.get("equipment_image_generated_at"))
            or ""
        )
        if not prompt_supplied:
            equipment_image_prompt = (
                equipment_image_prompt
                or nullable_string(existing.get("equipment_image_prompt"))
                or ""
            )

        record = {
            **existing,
            **(item if isinstance(item, dict) else {}),
        }
        record.update({
            "equipment": text,
            "text": text,
            "equipment_image_url": equipment_image_url,
            "equipment_image_generated_at": equipment_image_generated_at,
            "equipment_image_prompt": equipment_image_prompt,
        })
        equipment.append(record)

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
    existing_by_id = {
        recipe_edit_row_identity(item, "instruction_id", "step_id", "row_id", "id"): item
        for item in existing_rows
        if recipe_edit_row_identity(item, "instruction_id", "step_id", "row_id", "id")
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

        item_identity = recipe_edit_row_identity(
            item,
            "instruction_id",
            "step_id",
            "row_id",
            "id",
        )
        existing = existing_by_id.get(item_identity) if item_identity else None
        existing = (
            existing
            or existing_by_text.get(instruction_match_text_key(text))
            or existing_by_step.get(instruction_match_step_key(step_number))
            or {}
        )
        step_image_url = step_image_url or nullable_string(existing.get("step_image_url")) or ""
        step_image_generated_at = (
            step_image_generated_at
            or nullable_string(existing.get("step_image_generated_at"))
            or ""
        )

        record = {
            **existing,
            **(item if isinstance(item, dict) else {}),
        }
        record.update({
            "step_number": step_number,
            "instruction": text,
            "text": text,
            "step_image_url": step_image_url,
            "step_image_generated_at": step_image_generated_at,
        })
        record.setdefault("section", None)
        record.setdefault("temperature", None)
        record.setdefault("time", None)
        record.setdefault("equipment_used", [])
        instructions.append(record)

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


def sanitize_nutrition(value, existing_value=None):
    if not isinstance(value, list):
        return {}

    nutrition = {}
    other = []
    row_metadata = {}
    existing_rows = normalize_nutrition_rows(existing_value or {})
    existing_by_key = {
        str(item.get("key") or "").strip().lower().replace(" ", "_").replace("-", "_"): item
        for item in existing_rows
        if str(item.get("key") or "").strip()
    }

    for item in value:
        if not isinstance(item, dict):
            continue

        key = str(item.get("key") or "").strip()
        value_text = str(item.get("value") or "").strip()

        if not key or not value_text:
            continue

        normalized_key = key.lower().replace(" ", "_").replace("-", "_")
        existing = existing_by_key.get(normalized_key, {})
        metadata = {
            key_name: metadata_value
            for key_name, metadata_value in {**existing, **item}.items()
            if key_name not in {"key", "value", "label", "name", "amount"}
        }
        if normalized_key in NUTRITION_FIELDS:
            nutrition[normalized_key] = value_text
            if metadata:
                row_metadata[normalized_key] = metadata
        else:
            other.append({
                **metadata,
                "label": key,
                "value": value_text,
            })

    if other:
        nutrition["other"] = other
    if row_metadata:
        nutrition["_row_metadata"] = row_metadata

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


def sanitize_recipe_notes(value, existing_value=None):
    if value is None:
        value = existing_value

    return normalize_recipe_note_sections(value)


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


def truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
