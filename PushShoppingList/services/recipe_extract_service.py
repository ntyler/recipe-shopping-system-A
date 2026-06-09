import json
import os
import re
import html
import base64
import io
import mimetypes
import imghdr
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import urlparse

import openai
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

try:
    from openai import APIConnectionError, APITimeoutError, RateLimitError, AuthenticationError, BadRequestError
except Exception:  # pragma: no cover
    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class BadRequestError(Exception):
        pass

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services.openai_model_service import supports_custom_temperature
from PushShoppingList.services.openai_usage_service import record_openai_usage
from PushShoppingList.services.purchase_mapping_service import apply_purchase_mapping_to_ingredient
from PushShoppingList.services.storage_service import scoped_extractor_data_path
from PushShoppingList.services.storage_service import scoped_extractor_path
from PushShoppingList.services.user_account_service import current_public_user


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent

def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

EXTRACTOR_FOLDER = scoped_extractor_path()
OUTPUT_FOLDER = scoped_extractor_data_path("output")
RAW_FOLDER = scoped_extractor_data_path("raw")
LOG_FOLDER = scoped_extractor_data_path("logs")
UPLOAD_FOLDER = scoped_extractor_data_path("uploads")
VIDEO_FOLDER = scoped_extractor_data_path("video")
PDF_FOLDER = scoped_extractor_data_path("pdf")

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
RAW_FOLDER.mkdir(parents=True, exist_ok=True)
LOG_FOLDER.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
PDF_FOLDER.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("OPENAI_RECIPE_MODEL", "gpt-5.5")
VISION_MODEL_DEFAULT = "gpt-5.5"
VISION_MODEL_FALLBACK = "gpt-4o-mini"
OPENAI_RECIPE_MODEL_DEFAULT = "gpt-5.5"
OPENAI_PING_TEXT_MODEL = os.getenv("OPENAI_PING_TEXT_MODEL", "gpt-4o-mini")
VISION_REQUEST_TIMEOUT_SECONDS = _safe_int(
    os.getenv("OPENAI_VISION_REQUEST_TIMEOUT_SECONDS", "120"),
    120,
)
VISION_RETRY_DELAY_SECONDS = _safe_float(
    os.getenv("OPENAI_VISION_RETRY_DELAY_SECONDS", "0.75"),
    0.75,
)
VISION_MAX_RETRIES = _safe_int(
    os.getenv("OPENAI_VISION_MAX_RETRIES", "2"),
    2,
)
print(f"[Recipe AI] OPENAI_API_KEY present: {'yes' if bool(os.getenv('OPENAI_API_KEY')) else 'no'}")
print(f"[Recipe AI] Vision model: {os.getenv('OPENAI_VISION_MODEL') or VISION_MODEL_DEFAULT}")
MAX_PAGE_TEXT_CHARS = 35000
MAX_SOCIAL_VIDEO_PROMPT_CHARS = 12000
MAX_VIDEO_TRANSCRIPTION_SECONDS = int(os.getenv("MAX_VIDEO_TRANSCRIPTION_SECONDS", "180"))
MAX_VIDEO_AUDIO_BYTES = int(os.getenv("MAX_VIDEO_AUDIO_BYTES", str(24 * 1024 * 1024)))
MAX_SOCIAL_VIDEO_IMAGE_URLS = int(os.getenv("MAX_SOCIAL_VIDEO_IMAGE_URLS", "4"))
MAX_OPENAI_UPLOAD_IMAGE_SIDE = int(os.getenv("MAX_OPENAI_UPLOAD_IMAGE_SIDE", "2000"))
MAX_OPENAI_UPLOAD_IMAGE_BYTES = int(os.getenv("MAX_OPENAI_UPLOAD_IMAGE_BYTES", str(2 * 1024 * 1024)))
NORMALIZE_OPENAI_UPLOAD_IMAGE_BYTES = int(os.getenv("NORMALIZE_OPENAI_UPLOAD_IMAGE_BYTES", str(1024 * 1024)))
FOOD_IMAGE_INFERENCE_CONFIDENCE_THRESHOLD = float(
    os.getenv("FOOD_IMAGE_INFERENCE_CONFIDENCE_THRESHOLD", "0.75")
)
LOW_CONFIDENCE_FOOD_IMAGE_INFERENCE = float(
    os.getenv("LOW_CONFIDENCE_FOOD_IMAGE_INFERENCE", "0.55")
)
VISION_SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
VISION_CONVERTIBLE_IMAGE_MIME_TYPES = {
    "image/heic",
    "image/heif",
    "image/heic-sequence",
    "image/heif-sequence",
    "image/bmp",
    "image/x-ms-bmp",
    "image/tiff",
    "image/avif",
}
VISION_SUPPORTED_IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
}
VISION_CONVERTIBLE_IMAGE_SUFFIXES = {
    ".heic",
    ".heif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}

@dataclass
class OpenAIModelResolution:
    model: str
    source: str
    purpose: str


@dataclass
class VisionResult:
    ok: bool
    text: str = ""
    model_used: str = ""
    model_source: str = ""
    action_name: str = ""
    error_code: str = ""
    error_message: str = ""
    technical_message: str = ""
    exception_type: str = ""
    openai_error_code: str = ""
    openai_error_param: str = ""
    fallback_used: bool = False
    fallback_from_model: str = ""
    fallback_to_model: str = ""
    image_bytes: int = 0
    base64_length: int = 0
    temperature_included: bool = False
    debug: Optional[dict] = None

    def to_dict(self):
        payload = asdict(self)
        payload["model"] = self.model_used
        payload["action"] = self.action_name
        return payload


class VisionRequestError(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__(result.technical_message or result.error_message or result.error_code)


def resolve_openai_model(purpose="recipe", preferred_model=None, fallback=False):
    purpose = str(purpose or "recipe").strip().lower()
    preferred_model = str(preferred_model or "").strip()

    if fallback:
        return OpenAIModelResolution(
            model=VISION_MODEL_FALLBACK,
            source="fallback:gpt-4o-mini",
            purpose=purpose,
        )

    if preferred_model:
        return OpenAIModelResolution(
            model=preferred_model,
            source="preferred_model",
            purpose=purpose,
        )

    if purpose == "vision":
        env_model = os.getenv("OPENAI_VISION_MODEL", "").strip()
        if env_model:
            return OpenAIModelResolution(
                model=env_model,
                source="env:OPENAI_VISION_MODEL",
                purpose=purpose,
            )
        return OpenAIModelResolution(
            model=VISION_MODEL_DEFAULT,
            source="default:gpt-5.5",
            purpose=purpose,
        )

    env_model = os.getenv("OPENAI_RECIPE_MODEL", "").strip()
    if env_model:
        return OpenAIModelResolution(
            model=env_model,
            source="env:OPENAI_RECIPE_MODEL",
            purpose=purpose,
        )

    return OpenAIModelResolution(
        model=OPENAI_RECIPE_MODEL_DEFAULT,
        source="default:gpt-5.5",
        purpose=purpose,
    )


def resolve_vision_model():
    return resolve_openai_model("vision").model


def resolve_vision_model_source():
    return resolve_openai_model("vision").source


def resolve_recipe_model():
    return resolve_openai_model("recipe").model


OPENAI_UNSUPPORTED_PARAMETER_MESSAGE = (
    "The selected OpenAI model does not support one of the request settings. "
    "The app should remove that setting and retry."
)


def _coerce_openai_error_payload(value):
    if value is None:
        return None

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {"message": candidate}

    try:
        if hasattr(value, "dict"):
            parsed = value.dict()
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass

    return None


def get_openai_error_code_and_param(exc):
    if exc is None:
        return "", ""

    if isinstance(exc, VisionRequestError):
        result = exc.result
        return result.openai_error_code or result.error_code or "", result.openai_error_param or ""

    error_code = ""
    error_param = ""
    error_obj = _coerce_openai_error_payload(getattr(exc, "error", None))
    body_obj = _coerce_openai_error_payload(getattr(exc, "body", None))
    response_obj = getattr(exc, "response", None)

    if response_obj is not None:
        body_from_response = None
        if hasattr(response_obj, "json"):
            try:
                body_from_response = _coerce_openai_error_payload(response_obj.json())
            except Exception:
                body_from_response = None
        if body_from_response is None and hasattr(response_obj, "text"):
            body_from_response = _coerce_openai_error_payload(response_obj.text)
        if body_from_response:
            body_obj = body_from_response

    payloads = []
    if error_obj is not None:
        payloads.append(error_obj)
        nested_error = error_obj.get("error") if isinstance(error_obj, dict) else None
        if nested_error not in (None, error_obj) and isinstance(nested_error, dict):
            payloads.append(nested_error)
    if body_obj is not None and body_obj is not error_obj:
        payloads.append(body_obj)
        nested_error = body_obj.get("error") if isinstance(body_obj, dict) else None
        if nested_error not in (None, body_obj) and isinstance(nested_error, dict):
            payloads.append(nested_error)
    if body_obj is None and error_obj is not None:
        payloads.append(error_obj)
    if hasattr(exc, "response"):
        response_payload = _coerce_openai_error_payload(getattr(exc, "response", None))
        if response_payload:
            payloads.append(response_payload)

    checked_payloads = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue

        payload_id = id(payload)
        if payload_id in checked_payloads:
            continue
        checked_payloads.add(payload_id)

        if not error_code:
            error_code = payload.get("code")
        if not error_param:
            error_param = payload.get("param")
        if not error_code:
            error_code = payload.get("error_code")
        if not error_param:
            error_param = payload.get("param_name")
        if not error_code:
            error_code = payload.get("type")

        if isinstance(payload.get("error"), dict):
            nested_payload = payload.get("error")
            if not error_code:
                error_code = nested_payload.get("code")
            if not error_param:
                error_param = nested_payload.get("param")
            if not error_code:
                error_code = nested_payload.get("type")

    if not error_code:
        error_code = (
            getattr(exc, "code", "")
            or getattr(exc, "status_code", "")
            or getattr(exc, "type", "")
            or ""
        )
    if not error_param:
        error_param = (
            getattr(exc, "param", "")
            or getattr(exc, "error_param", "")
            or getattr(exc, "field", "")
            or ""
        )

    return str(error_code or "").strip(), str(error_param or "").strip()


def is_openai_unsupported_temperature_error(exc, error_code="", error_param=""):
    exception_text = str(exc or "").strip().lower()
    lowered_error_param = str(error_param or "").strip().lower()
    lowered_error_code = str(error_code or "").strip().lower()

    if lowered_error_param == "temperature":
        return True
    if lowered_error_param.startswith("temperature."):
        return True
    if lowered_error_param.startswith("temperature:"):
        return True

    return (
        lowered_error_code in {"unsupported_parameter", "invalid_request_error"}
        and "temperature" in exception_text
        and (
            "unsupported" in exception_text
            or "does not support" in exception_text
            or "unsupported value" in exception_text
            or "does not accept" in exception_text
        )
    )


def build_openai_chat_payload(
    model,
    endpoint_name,
    messages,
    response_format=None,
    temperature=None,
    **extra_kwargs,
):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing.")

    resolved_model = str(model or MODEL).strip() or MODEL
    supports_temperature = supports_custom_temperature(resolved_model)

    payload = {
        "model": resolved_model,
        "messages": messages,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    payload.update(extra_kwargs)

    if temperature is not None and supports_temperature:
        payload["temperature"] = temperature

    print(
        f"[OpenAI] action={endpoint_name} "
        f"model={resolved_model} "
        f"temperature_included={supports_temperature and temperature is not None}"
    )
    return payload, bool(supports_temperature and temperature is not None), resolved_model
NON_RECIPE_FOOD_DISH_ERROR = "This upload does not appear to contain a recipe or recognizable food dish."
NO_READABLE_UPLOAD_TEXT_ERROR = "No readable recipe text was found in this uploaded file."
NO_WRITTEN_PHOTO_TEXT_ERROR = "No written recipe text was found in this photo."
FOOD_PHOTO_NO_RECIPE_TEXT_ERROR = (
    "This looks like a food photo, but no written recipe was found. "
    "Add a description or recipe notes to generate a shopping list."
)
FOOD_PHOTO_DESCRIPTION_ESTIMATED_NOTE = "Estimated from photo/description."
NO_UPLOAD_INGREDIENTS_ERROR = "No recipe ingredients were found in this uploaded file."
DEFAULT_YOUTUBE_AUDIO_PLAYER_CLIENTS = ("android",)
OPENAI_FILE_INPUT_MIME_TYPES = {
    "application/pdf",
}
WORD_DOCUMENT_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
WORD_DOCUMENT_SUFFIXES = {
    ".doc",
    ".docx",
}
DEFAULT_RECIPE_SCALING_MULTIPLIERS = (
    {"label": "1/2x", "value": 0.5},
    {"label": "1x", "value": 1},
    {"label": "2x", "value": 2},
    {"label": "3x", "value": 3},
)
PDF_KIND_WEBPAGE_BACKUP = "webpage_backup"
PDF_KIND_GENERATED_RECIPE = "generated_recipe"
PDF_PAPER_WIDTH_IN = 8.5
PDF_MARGIN_TOP_IN = 0.65
PDF_MARGIN_BOTTOM_IN = 0.45
PDF_MARGIN_LEFT_IN = 0.45
PDF_MARGIN_RIGHT_IN = 0.45
PDF_BASE_SCALE = 0.92
PDF_MAX_CONTINUOUS_HEIGHT_IN = 200
PDF_MIN_CONTINUOUS_SCALE = 0.1
INGREDIENT_STORE_SECTIONS = {
    "produce": "PRODUCE",
    "beef": "MEAT & SEAFOOD",
    "chicken": "MEAT & SEAFOOD",
    "pork": "MEAT & SEAFOOD",
    "turkey": "MEAT & SEAFOOD",
    "fish": "MEAT & SEAFOOD",
    "shrimp": "MEAT & SEAFOOD",
    "salmon": "MEAT & SEAFOOD",
    "frozen": "FROZEN",
    "frozen peas": "FROZEN",
    "frozen raspberries": "FROZEN",
    "egg": "DAIRY & EGGS",
    "eggs": "DAIRY & EGGS",
    "yolk": "DAIRY & EGGS",
    "yolks": "DAIRY & EGGS",
    "milk": "DAIRY & EGGS",
    "butter": "DAIRY & EGGS",
    "yogurt": "DAIRY & EGGS",
    "cream": "DAIRY & EGGS",
    "cheese": "DAIRY & EGGS",
    "ricotta": "DAIRY & EGGS",
    "parmesan": "DAIRY & EGGS",
    "asparagus": "PRODUCE",
    "lemon": "PRODUCE",
    "garlic": "PRODUCE",
    "onion": "PRODUCE",
    "basil": "PRODUCE",
    "flour": "BAKING",
    "sugar": "BAKING",
    "confectioners sugar": "BAKING",
    "confectioners' sugar": "BAKING",
    "powdered sugar": "BAKING",
    "yeast": "BAKING",
    "baking powder": "BAKING",
    "baking soda": "BAKING",
    "chocolate chips": "BAKING",
    "chocolate": "BAKING",
    "cocoa powder": "BAKING",
    "dutch-processed cocoa powder": "BAKING",
    "cocoa butter": "BAKING",
    "corn syrup": "BAKING",
    "vanilla extract": "BAKING",
    "salt": "SPICES & SEASONINGS",
    "pepper": "SPICES & SEASONINGS",
    "cinnamon": "SPICES & SEASONINGS",
    "nutmeg": "SPICES & SEASONINGS",
    "paprika": "SPICES & SEASONINGS",
    "cumin": "SPICES & SEASONINGS",
    "oil": "OILS & VINEGARS",
    "vinegar": "OILS & VINEGARS",
    "clarified butter": "DAIRY & EGGS",
    "pasta": "PASTA, RICE & GRAINS",
    "pasta dough": "PASTA, RICE & GRAINS",
    "fresh pasta dough": "PASTA, RICE & GRAINS",
    "rice": "PASTA, RICE & GRAINS",
    "oats": "PASTA, RICE & GRAINS",
    "quinoa": "PASTA, RICE & GRAINS",
    "breadcrumbs": "PASTA, RICE & GRAINS",
    "sauce": "SAUCES & CONDIMENTS",
    "ketchup": "SAUCES & CONDIMENTS",
    "mustard": "SAUCES & CONDIMENTS",
}
STORE_SECTION_ORDER = {
    "PRODUCE": 1,
    "MEAT & SEAFOOD": 2,
    "DAIRY & EGGS": 3,
    "FROZEN": 4,
    "DRY GOODS": 5,
    "PASTA, RICE & GRAINS": 6,
    "BAKING": 7,
    "CANNED": 8,
    "SAUCES & CONDIMENTS": 9,
    "SNACKS": 10,
    "BEVERAGES": 11,
    "SPICES & SEASONINGS": 12,
    "OILS & VINEGARS": 13,
    "BAKERY": 14,
    "DELI": 15,
    "HOUSEHOLD": 16,
    "PERSONAL CARE": 17,
    "PET SUPPLIES": 18,
    "MISC": 19,
}
FRACTION_CHARS = "\u00bc\u00bd\u00be\u2150\u2151\u2152\u2153\u2154\u2155\u2156\u2157\u2158\u2159\u215a\u215b\u215c\u215d\u215e"
EQUIPMENT_INFERENCE_RULES = [
    ("oven", "appliance", [r"\bpreheat\b", r"\boven\b", r"\bbake\b"]),
    ("muffin tin", "cookware", [r"\bmuffin tins?\b", r"\bmuffin pans?\b", r"\bmuffin cups?\b"]),
    ("baking sheet", "cookware", [r"\bbaking sheets?\b", r"\bsheet pans?\b"]),
    ("mixing bowl", "prep", [r"\blarge bowl\b", r"\bmedium bowl\b", r"\bmixing bowl\b", r"\bin a bowl\b"]),
    ("whisk", "utensil", [r"\bwhisk\b"]),
    ("spatula", "utensil", [r"\bfold\b", r"\bspatula\b"]),
    ("cookie scoop", "utensil", [r"\bcookie scoop\b", r"\bscoop batter\b"]),
    ("wire rack", "prep", [r"\bwire rack\b"]),
    ("pot", "cookware", [r"\bboil\b", r"\bpot\b", r"\bpasta water\b"]),
    ("saucepan", "cookware", [r"\bsaucepan\b"]),
    ("skillet", "cookware", [r"\bskillet\b", r"\bfrying pan\b"]),
    ("knife", "prep", [r"\bcut\b", r"\bchop\b", r"\bslice\b", r"\bmince\b"]),
    ("cutting board", "prep", [r"\bcut\b", r"\bchop\b", r"\bslice\b", r"\bmince\b"]),
    ("rolling pin", "prep", [r"\broll(?:ed|ing)?\b", r"\brolling pin\b"]),
    ("pasta machine", "prep", [r"\bpasta machine\b", r"\bpasta roller\b", r"\bsetting\b"]),
    ("ravioli cutter", "prep", [r"\bravioli cutter\b", r"\bcut.*ravioli\b"]),
]
EQUIPMENT_PATTERNS_BY_NAME = {
    name: patterns
    for name, _category, patterns in EQUIPMENT_INFERENCE_RULES
}
PDF_PRINT_FIX_CSS = """
@media print {
  html,
  body {
    height: auto !important;
    margin: 0 !important;
    overflow: visible !important;
    padding-top: 0 !important;
    transform: none !important;
  }

  body {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  [style*="position: fixed"],
  [style*="position:fixed"],
  [style*="position: sticky"],
  [style*="position:sticky"],
  .fixed,
  .sticky,
  .sticky-header,
  .site-header,
  .site-header-wrapper,
  .mob-menu-header-holder {
    position: static !important;
    top: auto !important;
    transform: none !important;
  }
}
"""

client = None


def get_openai_client():
    global client

    if client is None:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)

    return client


def build_vision_debug(uploaded_file_path="", filename="", mime_type=""):
    model_resolution = resolve_openai_model("vision")
    return {
        "file_path": str(uploaded_file_path or ""),
        "filename": str(filename or ""),
        "mime_type": str(mime_type or ""),
        "file_exists": False,
        "file_size": 0,
        "uploaded_file_size": 0,
        "openai_image_bytes": 0,
        "model": model_resolution.model,
        "model_source": model_resolution.source,
        "temperature_included": False,
        "fallback_used": False,
        "fallback_from_model": "",
        "fallback_to_model": "",
        "image_type_supported": False,
        "image_readable": False,
        "image_uploaded": False,
        "request_started": False,
        "request_completed": False,
        "vision_request_sent": False,
        "vision_response_received": False,
        "json_parse_success": False,
        "recipe_json_parsed": False,
        "ingredient_count": 0,
        "recipe_creation_success": False,
        "encoded_base64_length": 0,
        "error_code": "",
        "error_message": "",
        "failed_status": "",
        "openai_error_code": "",
        "openai_error_param": "",
        "exception_type": "",
        "exception_message": "",
        "vision_request": {},
        "vision_response": "",
        "recipe_json": None,
        "steps": [],
    }


def openai_runtime_diagnostics(debug_mode=None, reloader_mode=None):
    recipe_resolution = resolve_openai_model("recipe")
    vision_resolution = resolve_openai_model("vision")
    return {
        "sys.executable": sys.executable,
        "sys.version": sys.version.replace("\n", " "),
        "os.getcwd": os.getcwd(),
        "openai.__version__": getattr(openai, "__version__", ""),
        "openai.__file__": getattr(openai, "__file__", ""),
        "OPENAI_API_KEY_present": "yes" if bool(os.getenv("OPENAI_API_KEY")) else "no",
        "OPENAI_RECIPE_MODEL": os.getenv("OPENAI_RECIPE_MODEL", ""),
        "OPENAI_VISION_MODEL": os.getenv("OPENAI_VISION_MODEL", ""),
        "resolved_recipe_model": recipe_resolution.model,
        "resolved_recipe_model_source": recipe_resolution.source,
        "resolved_vision_model": vision_resolution.model,
        "resolved_vision_model_source": vision_resolution.source,
        "flask_debug": bool(debug_mode) if debug_mode is not None else "",
        "flask_reloader": bool(reloader_mode) if reloader_mode is not None else "",
        "pid": os.getpid(),
    }


def log_openai_startup_diagnostics(debug_mode=None, reloader_mode=None):
    diagnostics = openai_runtime_diagnostics(debug_mode=debug_mode, reloader_mode=reloader_mode)
    print("[OpenAI Startup] diagnostics_begin")
    for key, value in diagnostics.items():
        print(f"[OpenAI Startup] {key} = {value}")
    print("[OpenAI Startup] diagnostics_end")
    return diagnostics


def log_vision_debug_step(debug, message, **details):
    if isinstance(debug, dict):
        step = {
            "message": message,
        }
        step.update({
            key: value
            for key, value in details.items()
            if value not in (None, "")
        })
        debug.setdefault("steps", []).append(step)

    suffix = ""
    if details:
        suffix = " " + " ".join(
            f"{key}={value!r}" for key, value in details.items() if value not in (None, "")
        )
    print(f"[Vision] {message}{suffix}")


def set_vision_debug_error(debug, error_code, error_message, failed_status=""):
    error_code = str(error_code or "VISION_FAILED").strip() or "VISION_FAILED"
    error_message = str(error_message or "Vision recipe generation failed.").strip()

    if isinstance(debug, dict):
        debug["error_code"] = error_code
        debug["error_message"] = error_message
        if failed_status:
            debug["failed_status"] = failed_status

    log_vision_debug_step(
        debug,
        "Failure",
        error_code=error_code,
        error_message=error_message,
        failed_status=failed_status,
    )
    return error_message


def classify_vision_ai_exception(exc):
    if isinstance(exc, VisionRequestError):
        result = exc.result
        return result.error_code or "AI_REQUEST_FAILED", result.error_message or "Vision AI request failed."

    if not os.getenv("OPENAI_API_KEY"):
        return (
            "OPENAI_API_KEY_MISSING",
            "OPENAI_API_KEY is missing or invalid.",
        )

    error_code, error_param = get_openai_error_code_and_param(exc)
    lowered_error_code = str(error_code or "").lower().strip()
    lowered_error_param = str(error_param or "").lower().strip()
    lowered_exception = str(exc or "").strip().lower()
    lowered_exception_type = str(type(exc).__name__).lower()
    lowered_status_code = str(getattr(exc, "status_code", "")).lower()

    is_auth_error = (
        isinstance(exc, AuthenticationError)
        or lowered_error_code in {"invalid_api_key", "authentication_error"}
        or "authentication" in lowered_exception
        or "api key" in lowered_exception
        or lowered_status_code == "401"
    )
    if is_auth_error:
        return "OPENAI_API_KEY_MISSING", "OPENAI_API_KEY is missing or invalid."

    is_temperature_error = (
        lowered_error_param == "temperature"
        or lowered_error_param.startswith("temperature.")
        or lowered_error_param.startswith("temperature:")
        or (
            "unsupported value" in lowered_exception
            and "temperature" in lowered_exception
            and lowered_status_code in {"400", "422"}
        )
        or lowered_exception.startswith("unsupported value: 0")
        or lowered_exception.startswith("unsupported value: \"temperature\"")
        or (
            is_openai_unsupported_temperature_error(
                exc,
                error_code=lowered_error_code,
                error_param=lowered_error_param,
            )
        )
    )
    if is_temperature_error:
        return (
            "OPENAI_UNSUPPORTED_PARAMETER",
            OPENAI_UNSUPPORTED_PARAMETER_MESSAGE,
        )

    is_timeout_error = (
        isinstance(exc, APITimeoutError)
        or isinstance(exc, TimeoutError)
        or lowered_status_code == "408"
        or "timed out" in lowered_exception
        or "timeout" in lowered_exception
    )
    if is_timeout_error:
        return "OPENAI_TIMEOUT", "Vision AI request timed out."

    is_model_error = (
        lowered_error_code in {
            "model_not_found",
            "model_not_supported",
            "unsupported_model",
            "invalid_model",
            "model_not_available",
            "unsupported_value",
        }
        or (
            "model" in lowered_exception
            and (
                "not found" in lowered_exception
                or "does not exist" in lowered_exception
                or "does not support" in lowered_exception
            )
        )
        or (
            lowered_status_code in {"404", "400"}
            and "model" in lowered_exception
            and (
                "does not exist" in lowered_exception
                or "not found" in lowered_exception
            )
        )
    )

    if isinstance(exc, APIConnectionError):
        return "OPENAI_CONNECTION_ERROR", "Vision AI connection failed."

    if is_model_error:
        return "OPENAI_UNSUPPORTED_MODEL", "OpenAI request failed: unsupported model."

    if isinstance(exc, RateLimitError) or "rate limit" in lowered_exception:
        return "OPENAI_RATE_LIMIT_ERROR", "Vision API rate limit exceeded."

    if lowered_error_code in {"unsupported_parameter", "invalid_request_error"} and lowered_status_code in {"400", "422"}:
        if is_temperature_error:
            return (
                "OPENAI_UNSUPPORTED_PARAMETER",
                OPENAI_UNSUPPORTED_PARAMETER_MESSAGE,
            )
        return (
            "OPENAI_BAD_REQUEST",
            (
                "Vision AI request failed: "
                f"{str(exc or '').strip() or type(exc).__name__}"
            ),
        )

    if (
        "unsupported" in lowered_exception
        and "image" in lowered_exception
        and "payload" in lowered_exception
    ):
        return "OPENAI_INVALID_IMAGE_PAYLOAD", "OpenAI request failed: invalid image payload."

    if (
        "quota" in lowered_exception
        or "insufficient_quota" in lowered_exception
    ):
        return "API_QUOTA_EXCEEDED", "API quota exceeded."

    if lowered_status_code == "400" and lowered_error_param:
        return (
            "OPENAI_BAD_REQUEST",
            f"Vision AI request failed: invalid request parameter ({lowered_error_param}).",
        )

    if (
        "phone photo format" in lowered_exception
        or "most compatible" in lowered_exception
    ):
        return (
            "UNSUPPORTED_IMAGE_FORMAT",
            "This phone photo format could not be read. Upload JPEG or PNG, "
            "or change the phone camera format to Most Compatible.",
        )

    if (
        "unsupported" in lowered_exception
        and "image" in lowered_exception
        and "format" in lowered_exception
    ):
        return "UNSUPPORTED_IMAGE_FORMAT", "Unsupported image format."

    if "invalid_request_error" in lowered_exception_type:
        return "OPENAI_BAD_REQUEST", "Vision AI request failed: invalid request."

    return "AI_REQUEST_FAILED", f"Vision AI request failed: {lowered_exception or type(exc).__name__}"


def set_vision_debug_exception(debug, exc):
    exception_type = type(exc).__name__
    exception_message = str(exc or "").strip() or exception_type
    error_code, error_param = get_openai_error_code_and_param(exc)
    if isinstance(exc, VisionRequestError):
        exception_type = exc.result.exception_type or exception_type
        exception_message = exc.result.technical_message or exc.result.error_message or exception_message
    if isinstance(debug, dict):
        debug["exception_type"] = exception_type
        debug["exception_message"] = exception_message
        debug["openai_error_code"] = error_code
        debug["openai_error_param"] = error_param

    log_vision_debug_step(
        debug,
        "Vision exception",
        exception_type=exception_type,
        exception_message=exception_message,
        openai_error_code=error_code,
        openai_error_param=error_param,
    )
    print(f"[Vision] Exception type: {exception_type}")
    print(f"[Vision] Exception message: {exception_message}")
    print(f"[Vision] OpenAI error code: {error_code}")
    print(f"[Vision] OpenAI error param: {error_param}")
    return exception_type, exception_message


def safe_filename(text):
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"www\.", "", text)
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    return text.strip("_")[:120] or "recipe"


def recipe_archive_pdf_path(recipe_url):
    return PDF_FOLDER / f"{safe_filename(recipe_url)}.pdf"


def generated_recipe_pdf_path(recipe_url):
    return PDF_FOLDER / f"{safe_filename(recipe_url)}_generated_recipe.pdf"


def recipe_pdf_path(recipe_url, pdf_kind=PDF_KIND_WEBPAGE_BACKUP):
    return (
        generated_recipe_pdf_path(recipe_url)
        if pdf_kind == PDF_KIND_GENERATED_RECIPE
        else recipe_archive_pdf_path(recipe_url)
    )


def recipe_archive_pdf_exists(recipe_url):
    return recipe_archive_pdf_path(recipe_url).exists()


def utc_iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cloudflare_pdf_upload_is_usable(upload_result):
    return bool(upload_result and (upload_result.get("ok") or upload_result.get("code") == "duplicate_object"))


def pdf_metadata_field_prefix(pdf_kind):
    return (
        "generated_recipe_pdf"
        if pdf_kind == PDF_KIND_GENERATED_RECIPE
        else "webpage_backup_pdf"
    )


def attach_cloudflare_pdf_metadata(
    recipe_url,
    json_data,
    upload_result,
    pdf_path=None,
    pdf_kind=PDF_KIND_WEBPAGE_BACKUP,
):
    if not isinstance(json_data, dict):
        return json_data

    pdf_kind = PDF_KIND_GENERATED_RECIPE if pdf_kind == PDF_KIND_GENERATED_RECIPE else PDF_KIND_WEBPAGE_BACKUP
    local_path = str(pdf_path or recipe_pdf_path(recipe_url, pdf_kind))
    prefix = pdf_metadata_field_prefix(pdf_kind)

    json_data[f"{prefix}_path"] = local_path
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        json_data["generated_pdf_path"] = local_path
        json_data["generated_cloudflare_pdf_path"] = str(json_data.get("generated_cloudflare_pdf_url") or "").strip()
    else:
        json_data["source_pdf_path"] = local_path
        json_data["source_cloudflare_pdf_path"] = str(json_data.get("source_cloudflare_pdf_url") or "").strip()
        json_data["pdf_path"] = local_path

    if not cloudflare_pdf_upload_is_usable(upload_result):
        print(
            "[recipe_pdf_fields] "
            f"action=extract_attach_local:{pdf_kind} "
            f"fields={{'source_url': {str(json_data.get('source_url') or recipe_url)!r}, "
            f"'source_pdf_path': {str(json_data.get('source_pdf_path') or '')!r}, "
            f"'source_cloudflare_pdf_url': {str(json_data.get('source_cloudflare_pdf_url') or '')!r}, "
            f"'generated_pdf_path': {str(json_data.get('generated_pdf_path') or '')!r}, "
            f"'generated_cloudflare_pdf_url': {str(json_data.get('generated_cloudflare_pdf_url') or '')!r}}}"
        )
        return json_data

    object_key = str(upload_result.get("object_key") or "").strip()
    public_url = str(upload_result.get("public_url") or "").strip()

    if not object_key or not public_url:
        return json_data

    uploaded_at = utc_iso_now()
    bucket = str(upload_result.get("bucket") or os.getenv("R2_BUCKET_NAME", "")).strip()
    kind_metadata = {
        "local_path": local_path,
        "r2_object_key": object_key,
        "r2_public_url": public_url,
        "uploaded_at": uploaded_at,
        "cloud_status": "uploaded",
        "cloudflare_r2": {
            "provider": "cloudflare_r2",
            "bucket": bucket,
            "object_key": object_key,
            "public_url": public_url,
            "uploaded_at": uploaded_at,
            "cloud_status": "uploaded",
        },
    }
    pdf_metadata = json_data.get("pdf") if isinstance(json_data.get("pdf"), dict) else {}
    pdf_metadata[pdf_kind] = kind_metadata

    if pdf_kind == PDF_KIND_WEBPAGE_BACKUP:
        pdf_metadata["local_path"] = local_path
        pdf_metadata["r2_object_key"] = object_key
        pdf_metadata["r2_public_url"] = public_url
        pdf_metadata["uploaded_at"] = uploaded_at
        pdf_metadata["cloud_status"] = "uploaded"
        pdf_metadata["cloudflare_r2"] = kind_metadata["cloudflare_r2"]

    json_data["pdf"] = pdf_metadata
    json_data[f"{prefix}_path"] = local_path
    json_data[f"{prefix}_url"] = public_url
    json_data[f"{prefix}_object_key"] = object_key
    json_data[f"{prefix}_uploaded_at"] = uploaded_at
    if pdf_kind == PDF_KIND_GENERATED_RECIPE:
        json_data["generated_pdf_path"] = local_path
        json_data["generated_cloudflare_pdf_url"] = public_url
        json_data["generated_cloudflare_pdf_path"] = public_url
    else:
        json_data["source_pdf_path"] = local_path
        json_data["source_cloudflare_pdf_url"] = public_url
        json_data["source_cloudflare_pdf_path"] = public_url
        json_data["pdf_path"] = local_path
        json_data["cloudflare_pdf_url"] = public_url

    print(
        "[recipe_pdf_fields] "
        f"action=extract_attach_cloudflare:{pdf_kind} "
        f"fields={{'source_url': {str(json_data.get('source_url') or recipe_url)!r}, "
        f"'source_pdf_path': {str(json_data.get('source_pdf_path') or '')!r}, "
        f"'source_cloudflare_pdf_url': {str(json_data.get('source_cloudflare_pdf_url') or '')!r}, "
        f"'generated_pdf_path': {str(json_data.get('generated_pdf_path') or '')!r}, "
        f"'generated_cloudflare_pdf_url': {str(json_data.get('generated_cloudflare_pdf_url') or '')!r}}}"
    )

    return json_data


def delete_local_pdf_after_cloudflare_upload(pdf_path):
    path = Path(pdf_path)

    if not cloudflare_r2_storage.delete_local_pdf_after_upload():
        return False

    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as exc:
        print(f"Cloudflare R2 upload succeeded, but local PDF cleanup failed: {exc}")
        return False


def maybe_upload_recipe_archive_pdf_to_cloudflare(recipe_url, progress_callback=None):
    if not cloudflare_r2_storage.has_any_r2_config():
        return None

    pdf_path = recipe_archive_pdf_path(recipe_url)
    if not pdf_path.exists():
        return None

    if progress_callback:
        progress_callback(
            "uploading recipe PDF to Cloudflare...",
            "Saving the PDF archive to Cloudflare R2 and preparing a public link.",
        )

    upload_result = cloudflare_r2_storage.upload_pdf(pdf_path)

    if cloudflare_pdf_upload_is_usable(upload_result):
        delete_local_pdf_after_cloudflare_upload(pdf_path)
        return upload_result

    print(f"Cloudflare R2 recipe PDF upload failed: {upload_result.get('error', 'Unknown error')}")

    if progress_callback:
        progress_callback(
            "Cloudflare PDF upload failed - continuing recipe import...",
            upload_result.get("error", "The recipe was imported, but the PDF was not uploaded to Cloudflare."),
        )

    return upload_result


def clean_json_response(text):
    text = str(text or "").strip()
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\r\n", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    return text.strip()


def default_recipe_scaling_options():
    return [dict(option) for option in DEFAULT_RECIPE_SCALING_MULTIPLIERS]


def parse_scaling_multiplier(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        multiplier = float(value)
        return multiplier if multiplier > 0 else None

    text = html.unescape(str(value or "")).strip().lower()
    if not text:
        return None

    text = text.replace("×", "x")
    x_match = re.search(r"(\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s*x\b", text)

    if x_match:
        text = x_match.group(1)
    else:
        text = text.rstrip("x").strip()

    text = re.sub(r"\s+", "", text)
    fraction_match = re.fullmatch(r"(\d+)/(\d+)", text)

    try:
        if fraction_match:
            denominator = float(fraction_match.group(2))
            if denominator == 0:
                return None
            multiplier = float(fraction_match.group(1)) / denominator
        else:
            multiplier = float(text)
    except ValueError:
        return None

    if multiplier <= 0:
        return None

    return multiplier


def scaling_multiplier_label(value):
    multiplier = parse_scaling_multiplier(value)

    if multiplier is None:
        return "1x"

    if abs(multiplier - 0.5) < 0.000001:
        return "1/2x"

    if float(multiplier).is_integer():
        return f"{int(multiplier)}x"

    return f"{multiplier:g}x"


def normalize_scaling_option(option):
    if isinstance(option, dict):
        raw_value = (
            option.get("value")
            if option.get("value") is not None
            else option.get("multiplier")
        )
        label = str(
            option.get("label")
            or option.get("text")
            or option.get("name")
            or ""
        ).strip()
    else:
        raw_value = option
        label = ""

    multiplier = parse_scaling_multiplier(raw_value)

    if multiplier is None and label:
        multiplier = parse_scaling_multiplier(label)

    if multiplier is None:
        return None

    return {
        "label": scaling_multiplier_label(multiplier),
        "value": multiplier,
    }


def normalize_scaling_options(options, default_to_common=True):
    normalized = {}

    for option in options or []:
        item = normalize_scaling_option(option)

        if not item:
            continue

        key = f"{item['value']:.6g}"
        normalized[key] = item

    if not normalized and default_to_common:
        return default_recipe_scaling_options()

    if normalized and "1" not in normalized:
        normalized["1"] = {"label": "1x", "value": 1}

    return sorted(normalized.values(), key=lambda item: item["value"])


def normalize_recipe_scaling_metadata(scaling=None, default_to_common=True):
    if not isinstance(scaling, dict):
        scaling = {}

    options = (
        scaling.get("available_multipliers")
        or scaling.get("multipliers")
        or scaling.get("scaling_multipliers")
        or []
    )
    normalized_options = normalize_scaling_options(options, default_to_common=default_to_common)

    if not normalized_options and not default_to_common:
        return None

    selected_multiplier = parse_scaling_multiplier(
        scaling.get("selected_multiplier")
        if scaling.get("selected_multiplier") is not None
        else scaling.get("scaling_multiplier")
    )
    base_multiplier = parse_scaling_multiplier(scaling.get("base_multiplier")) or 1

    option_values = [option["value"] for option in normalized_options]

    if selected_multiplier is None:
        selected_multiplier = 1 if 1 in option_values else (option_values[0] if option_values else 1)

    if normalized_options and not any(abs(option["value"] - selected_multiplier) < 0.000001 for option in normalized_options):
        normalized_options = sorted(
            [
                *normalized_options,
                {
                    "label": scaling_multiplier_label(selected_multiplier),
                    "value": selected_multiplier,
                },
            ],
            key=lambda item: item["value"],
        )

    return {
        "selected_multiplier": selected_multiplier,
        "base_multiplier": base_multiplier,
        "base_servings": str(scaling.get("base_servings") or "").strip(),
        "available_multipliers": normalized_options or default_recipe_scaling_options(),
    }


def recipe_scaling_from_data(json_data, default_to_common=True):
    if not isinstance(json_data, dict):
        return normalize_recipe_scaling_metadata(default_to_common=default_to_common)

    scaling = json_data.get("scaling")

    if isinstance(scaling, dict):
        raw_scaling = dict(scaling)
    else:
        raw_scaling = {}

    if json_data.get("scaling_multipliers") and not raw_scaling.get("available_multipliers"):
        raw_scaling["available_multipliers"] = json_data.get("scaling_multipliers")

    if json_data.get("scaling_multiplier") is not None and raw_scaling.get("selected_multiplier") is None:
        raw_scaling["selected_multiplier"] = json_data.get("scaling_multiplier")

    if json_data.get("servings") and not raw_scaling.get("base_servings"):
        raw_scaling["base_servings"] = json_data.get("servings")

    if not raw_scaling and not default_to_common:
        return None

    return normalize_recipe_scaling_metadata(raw_scaling, default_to_common=default_to_common)


def extract_recipe_scaling_from_html(html_text):
    html_text = str(html_text or "")

    if not html_text.strip():
        return None

    soup = BeautifulSoup(html_text, "html.parser")
    options = []
    selected_multiplier = None

    for element in soup.select("[data-multiplier]"):
        multiplier = parse_scaling_multiplier(element.get("data-multiplier"))

        if multiplier is None:
            multiplier = parse_scaling_multiplier(element.get_text(" ", strip=True))

        if multiplier is None:
            multiplier = parse_scaling_multiplier(element.get("aria-label"))

        if multiplier is None:
            continue

        options.append({
            "label": scaling_multiplier_label(multiplier),
            "value": multiplier,
        })

        classes = set(element.get("class") or [])
        if (
            "wprm-toggle-active" in classes
            or "active" in classes
            or str(element.get("aria-pressed") or "").lower() == "true"
            or str(element.get("aria-selected") or "").lower() == "true"
        ):
            selected_multiplier = multiplier

    if len(options) < 2:
        page_text = soup.get_text(" ", strip=True)
        multiplier_labels = re.findall(
            r"(?<![\w/])(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)\s*[x×]\b",
            page_text,
            flags=re.IGNORECASE,
        )
        options.extend({"label": label, "value": label} for label in multiplier_labels)

    normalized_options = normalize_scaling_options(options, default_to_common=False)

    if len(normalized_options) < 2:
        return None

    return normalize_recipe_scaling_metadata(
        {
            "available_multipliers": normalized_options,
            "selected_multiplier": selected_multiplier or 1,
        },
        default_to_common=False,
    )


def ensure_ingredient_base_quantities(json_data):
    if not isinstance(json_data, dict):
        return

    for item in json_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        if item.get("base_quantity") in (None, "") and item.get("quantity") not in (None, ""):
            item["base_quantity"] = item.get("quantity")

        if item.get("base_unit") in (None, "") and item.get("unit") not in (None, ""):
            item["base_unit"] = item.get("unit")


def apply_recipe_scaling_metadata(json_data, html_text=None):
    if not isinstance(json_data, dict):
        return

    html_scaling = extract_recipe_scaling_from_html(html_text) if html_text else None
    scaling = html_scaling or recipe_scaling_from_data(json_data, default_to_common=True)

    if json_data.get("servings") and not scaling.get("base_servings"):
        scaling["base_servings"] = str(json_data.get("servings") or "").strip()

    json_data["scaling"] = scaling
    ensure_ingredient_base_quantities(json_data)


def extract_recipe_from_structured_data(recipe_url, html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    page_text = soup.get_text(" ", strip=True)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(tag.get_text(strip=True))
        except Exception:
            continue

        recipe = find_recipe_node(payload)

        if not recipe:
            continue

        ingredients = build_structured_ingredients(recipe.get("recipeIngredient", []))

        if not ingredients:
            continue

        instructions = build_structured_instructions(recipe.get("recipeInstructions", []))
        equipment = infer_equipment_from_instructions(instructions)
        add_equipment_used_to_instructions(instructions, equipment)

        json_data = {
            "source_url": recipe_url,
            "recipe_title": recipe.get("name"),
            "servings": normalize_servings(recipe.get("recipeYield")),
            **extract_recipe_info_metadata(recipe, page_text),
            "ingredients": ingredients,
            "equipment": equipment,
            "instructions": instructions,
            "nutrition": build_structured_nutrition(recipe.get("nutrition", {})),
        }
        cover_image = normalize_recipe_cover_image(
            recipe.get("image"),
            base_url=recipe_url,
            fallback_alt=recipe.get("name") or "",
            source="structured_data",
        )

        if cover_image:
            json_data["cover_image"] = cover_image

        apply_recipe_scaling_metadata(json_data, html_text)
        apply_recipe_cover_image_metadata(json_data, html_text, recipe_url)

        return json_data

    return None


def find_recipe_node(payload):
    if isinstance(payload, dict):
        if node_has_recipe_type(payload):
            return payload

        graph = payload.get("@graph", [])

        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict) and node_has_recipe_type(node):
                    return node

    if isinstance(payload, list):
        for node in payload:
            recipe = find_recipe_node(node)

            if recipe:
                return recipe

    return None


def node_has_recipe_type(node):
    node_type = node.get("@type")

    if isinstance(node_type, list):
        return "Recipe" in node_type

    return node_type == "Recipe"


def extract_recipe_info_metadata(recipe, page_text=""):
    recipe = recipe if isinstance(recipe, dict) else {}
    text_values = extract_recipe_info_from_text(page_text)

    return {
        "level": clean_recipe_info_value(
            recipe.get("recipeDifficulty")
            or recipe.get("difficulty")
            or recipe.get("level")
            or text_values.get("level")
        ),
        "total_time": clean_recipe_info_value(
            format_recipe_duration(recipe.get("totalTime"))
            or text_values.get("total_time")
        ),
        "prep_time": clean_recipe_info_value(
            format_recipe_duration(recipe.get("prepTime"))
            or text_values.get("prep_time")
        ),
        "inactive_time": clean_recipe_info_value(
            format_recipe_duration(recipe.get("inactiveTime"))
            or recipe.get("inactive_time")
            or text_values.get("inactive_time")
        ),
        "cook_time": clean_recipe_info_value(
            format_recipe_duration(recipe.get("cookTime"))
            or text_values.get("cook_time")
        ),
    }


def apply_recipe_info_metadata(json_data, html_text=None):
    if not isinstance(json_data, dict):
        return

    page_text = ""
    if html_text:
        page_text = BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)
    text_values = extract_recipe_info_from_text(page_text)

    for key in ("level", "total_time", "prep_time", "inactive_time", "cook_time"):
        if not str(json_data.get(key) or "").strip() and text_values.get(key):
            json_data[key] = text_values[key]

    apply_recipe_info_estimates(json_data)


RECIPE_INFO_ESTIMATE_DEFAULTS = {
    "servings": "4 servings",
    "level": "Easy",
    "total_time": "45 min",
    "prep_time": "15 min",
    "inactive_time": "0 min",
    "cook_time": "30 min",
}

RECIPE_INFO_ESTIMATE_ALIASES = {
    "servings": (
        "servings",
        "recipe_amount",
        "recipe_yield",
        "yield",
        "portions",
        "serves",
        "recipeYield",
    ),
    "level": ("level", "difficulty", "recipe_difficulty"),
    "total_time": ("total_time", "total", "recipe_total_time", "estimated_total_time"),
    "prep_time": ("prep_time", "prep", "recipe_prep_time", "hands_on_time"),
    "inactive_time": (
        "inactive_time",
        "inactive",
        "recipe_inactive_time",
        "rest_time",
        "waiting_time",
        "chill_time",
        "rise_time",
    ),
    "cook_time": ("cook_time", "cook", "recipe_cook_time", "cooking_time"),
}

RECIPE_INFO_EMPTY_VALUES = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "not specified",
    "unknown",
}


def apply_recipe_info_estimates(json_data):
    if not isinstance(json_data, dict) or not structured_recipe_data_is_usable(json_data):
        return

    for key, default in RECIPE_INFO_ESTIMATE_DEFAULTS.items():
        value = recipe_info_estimate_value(json_data, key)
        json_data[key] = value or default


def recipe_info_estimate_value(json_data, key):
    for alias in RECIPE_INFO_ESTIMATE_ALIASES.get(key, (key,)):
        if alias not in json_data:
            continue

        value = json_data.get(alias)
        if isinstance(value, bool) or value in (None, "", [], {}):
            continue

        if isinstance(value, (int, float)):
            if key == "servings":
                return f"{value:g} servings"
            if key.endswith("_time"):
                return f"{value:g} min"

        if isinstance(value, (list, dict)):
            continue

        cleaned = (
            clean_recipe_text(value)
            if key == "servings"
            else clean_recipe_info_value(value)
        )
        if cleaned.lower() not in RECIPE_INFO_EMPTY_VALUES:
            return cleaned

    return ""


def extract_recipe_info_from_text(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return {}

    fields = {
        "level": "Level",
        "total_time": "Total",
        "prep_time": "Prep",
        "inactive_time": "Inactive",
        "cook_time": "Cook",
    }
    stop_labels = r"Level|Total|Prep|Inactive|Cook|Yield|Nutrition Info|Save Recipe|Ingredients|Directions"
    result = {}

    for key, label in fields.items():
        match = re.search(
            rf"\b{re.escape(label)}:\s*(.*?)(?=\s+(?:{stop_labels})\b\s*:|"
            rf"\s+(?:Nutrition Info|Save Recipe|Ingredients|Directions)\b|$)",
            text,
            re.IGNORECASE,
        )
        if match:
            value = clean_recipe_info_value(match.group(1))
            if value:
                result[key] = value

    return result


def clean_recipe_info_value(value):
    value = str(value or "").strip()
    if not value:
        return ""

    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+(?:Yield|Nutrition Info|Save Recipe|Ingredients|Directions)\b.*$", "", value, flags=re.I)
    return value.strip(" :-")


def format_recipe_duration(value):
    value = str(value or "").strip()
    if not value:
        return ""

    match = re.fullmatch(
        r"P(?:(?P<years>\d+(?:\.\d+)?)Y)?(?:(?P<months>\d+(?:\.\d+)?)M)?(?:(?P<days>\d+(?:\.\d+)?)D)?"
        r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        value,
        re.IGNORECASE,
    )
    if not match:
        return clean_recipe_info_value(value)

    parts = []
    days = duration_number(match.group("days"))
    hours = duration_number(match.group("hours"))
    minutes = duration_number(match.group("minutes"))

    if days:
        parts.append(f"{days:g} day" + ("" if days == 1 else "s"))
    if hours:
        parts.append(f"{hours:g} hr")
    if minutes:
        parts.append(f"{minutes:g} min")

    return " ".join(parts)


def duration_number(value):
    if value is None:
        return 0

    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0

    return int(number) if number.is_integer() else number


def apply_recipe_cover_image_metadata(json_data, html_text=None, recipe_url="", fallback_alt=""):
    if not isinstance(json_data, dict):
        return

    fallback_alt = (
        str(fallback_alt or "").strip()
        or str(json_data.get("recipe_title") or "").strip()
        or "Recipe cover image"
    )
    cover_image = recipe_cover_image_from_data(
        json_data,
        base_url=recipe_url,
        fallback_alt=fallback_alt,
    )

    if not cover_image and html_text:
        cover_image = extract_recipe_cover_image_from_html(
            html_text,
            recipe_url,
            fallback_alt=fallback_alt,
        )

    if cover_image:
        if not cover_image.get("alt"):
            cover_image["alt"] = fallback_alt
        json_data["cover_image"] = cover_image


def apply_recipe_owner_metadata(json_data):
    """Stamp imported recipes with the active account without exposing secrets."""
    if not isinstance(json_data, dict):
        return

    user = current_public_user()

    if not user:
        json_data.pop("owner_user_id", None)
        json_data.pop("owner_username", None)
        return

    json_data["owner_user_id"] = user.get("user_id", "")
    json_data["owner_username"] = user.get("username", "")


def recipe_cover_image_from_data(json_data, base_url="", fallback_alt=""):
    if not isinstance(json_data, dict):
        return {}

    cover_image = normalize_recipe_cover_image(
        json_data.get("cover_image"),
        base_url=base_url,
        fallback_alt=fallback_alt,
    )

    if cover_image:
        return cover_image

    for key in ("image", "images", "image_url", "thumbnail", "thumbnail_url", "thumbnailUrl"):
        cover_image = normalize_recipe_cover_image(
            json_data.get(key),
            base_url=base_url,
            fallback_alt=fallback_alt,
            source="extracted_json",
        )

        if cover_image:
            return cover_image

    return {}


def extract_recipe_cover_image_from_html(html_text, base_url="", fallback_alt=""):
    if not str(html_text or "").strip():
        return {}

    soup = BeautifulSoup(html_text or "", "html.parser")

    for tag in soup.find_all("script", attrs={"type": re.compile(r"json", re.I)}):
        try:
            payload = json.loads(tag.get_text(strip=True))
        except Exception:
            continue

        recipe = find_recipe_node(payload)
        if recipe:
            cover_image = normalize_recipe_cover_image(
                recipe.get("image"),
                base_url=base_url,
                fallback_alt=recipe.get("name") or fallback_alt,
                source="structured_data",
            )

            if cover_image:
                return cover_image

        cover_image = find_cover_image_in_json(payload, base_url, fallback_alt)
        if cover_image:
            return cover_image

    metadata_selectors = [
        ('meta[property="og:image"]', "content"),
        ('meta[property="og:image:url"]', "content"),
        ('meta[property="og:image:secure_url"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[name="twitter:image:src"]', "content"),
        ('meta[property="slick:featured_image"]', "content"),
        ('link[rel="image_src"]', "href"),
    ]

    for selector, attribute in metadata_selectors:
        tag = soup.select_one(selector)
        value = tag.get(attribute) if tag else ""
        cover_image = normalize_recipe_cover_image(
            value,
            base_url=base_url,
            fallback_alt=fallback_alt,
            source="html_metadata",
        )

        if cover_image:
            return cover_image

    return {}


def find_cover_image_in_json(payload, base_url="", fallback_alt=""):
    if isinstance(payload, dict):
        for key in (
            "image",
            "images",
            "featured_image",
            "thumbnail",
            "thumbnail_url",
            "thumbnailUrl",
            "ogImage",
        ):
            cover_image = normalize_recipe_cover_image(
                payload.get(key),
                base_url=base_url,
                fallback_alt=payload.get("name") or payload.get("title") or fallback_alt,
                source="json_metadata",
            )

            if cover_image:
                return cover_image

        for value in payload.values():
            if isinstance(value, (dict, list)):
                cover_image = find_cover_image_in_json(value, base_url, fallback_alt)
                if cover_image:
                    return cover_image

    if isinstance(payload, list):
        for item in payload:
            cover_image = find_cover_image_in_json(item, base_url, fallback_alt)
            if cover_image:
                return cover_image

    return {}


def normalize_recipe_cover_image(value, base_url="", fallback_alt="", source=""):
    if value in (None, "", []):
        return {}

    if isinstance(value, list):
        candidates = [
            candidate
            for candidate in (
                normalize_recipe_cover_image(
                    item,
                    base_url=base_url,
                    fallback_alt=fallback_alt,
                    source=source,
                )
                for item in value
            )
            if candidate
        ]

        if not candidates:
            return {}

        return max(candidates, key=cover_image_score)

    if isinstance(value, dict):
        local_path = clean_cover_image_text(value.get("path"))
        if local_path:
            cover_image = {
                "path": local_path,
                "alt": clean_cover_image_text(value.get("alt")) or fallback_alt,
                "source": clean_cover_image_text(value.get("source")) or source or "local_file",
            }
            url = clean_cover_image_text(value.get("url"))
            mime_type = clean_cover_image_text(value.get("mime_type"))
            if url:
                cover_image["url"] = absolutize_cover_image_url(url, base_url)
            if mime_type:
                cover_image["mime_type"] = mime_type
            return cover_image

        image_value = first_cover_image_value(
            value,
            "url",
            "contentUrl",
            "content_url",
            "thumbnailUrl",
            "thumbnail_url",
            "src",
            "@id",
        )

        if image_value in (None, "") and value.get("image") is not value:
            image_value = value.get("image")

        cover_image = normalize_recipe_cover_image(
            image_value,
            base_url=base_url,
            fallback_alt=(
                clean_cover_image_text(value.get("alt"))
                or clean_cover_image_text(value.get("name"))
                or clean_cover_image_text(value.get("caption"))
                or fallback_alt
            ),
            source=clean_cover_image_text(value.get("source")) or source,
        )

        if not cover_image:
            return {}

        width = normalize_cover_image_dimension(value.get("width"))
        height = normalize_cover_image_dimension(value.get("height"))
        if width:
            cover_image["width"] = width
        if height:
            cover_image["height"] = height
        return cover_image

    url = absolutize_cover_image_url(clean_cover_image_text(value), base_url)

    if not cover_image_url_looks_usable(url):
        return {}

    cover_image = {
        "url": url,
        "alt": clean_cover_image_text(fallback_alt),
        "source": clean_cover_image_text(source) or "recipe",
    }
    return {key: item for key, item in cover_image.items() if item}


def first_cover_image_value(data, *keys):
    for key in keys:
        value = data.get(key)

        if value not in (None, "", []):
            return value

    return ""


def clean_cover_image_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_cover_image_dimension(value):
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def cover_image_score(cover_image):
    width = cover_image.get("width") or 0
    height = cover_image.get("height") or 0
    area = width * height if width and height else 0
    return (1 if cover_image.get("path") else 0, area, len(cover_image.get("url") or ""))


def absolutize_cover_image_url(url, base_url=""):
    url = str(url or "").strip()

    if not url:
        return ""

    if url.startswith("data:image/"):
        return url

    if base_url:
        return urljoin(base_url, url)

    return url


def cover_image_url_looks_usable(url):
    url = str(url or "").strip()

    if not url:
        return False

    if url.startswith("data:image/"):
        return True

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    path = parsed.path.lower()
    blocked_path_terms = (
        "favicon",
        "apple-touch-icon",
        "/avatar",
        "/profile",
        "/author",
        "/logo",
    )

    if any(term in path for term in blocked_path_terms):
        return False

    return not path.endswith(".svg")


def normalize_servings(recipe_yield):
    if isinstance(recipe_yield, list):
        return recipe_yield[0] if recipe_yield else None

    return recipe_yield


def build_structured_ingredients(raw_ingredients):
    ingredient_rows = []
    seen = set()

    for original_text in raw_ingredients or []:
        original_text = str(original_text or "").strip()
        parsed = parse_structured_ingredient_line(original_text)
        ingredient = parsed["ingredient"]
        key = normalize_ingredient_key(ingredient)

        if not ingredient or key in seen:
            continue

        store_section = classify_store_section(ingredient)
        ingredient_rows.append({
            "section": None,
            "original_text": original_text,
            "quantity": parsed["quantity"],
            "recipe_qty": parsed["quantity"],
            "unit": parsed["unit"],
            "ingredient": ingredient,
            "preparation": parsed["preparation"],
            "optional": "optional" in original_text.lower(),
            "store_section": store_section,
            "store_section_order": STORE_SECTION_ORDER[store_section],
        })
        apply_purchase_mapping_to_ingredient(ingredient_rows[-1])
        seen.add(key)

    return ingredient_rows


def parse_structured_ingredient_line(original_text):
    text = clean_recipe_text(original_text)
    preparation = extract_preparation(text)
    text_without_prep = remove_preparation_text(text, preparation)
    quantity, unit, remainder = split_quantity_unit(text_without_prep)
    ingredient = normalize_ingredient_for_shopping_list(remainder or text_without_prep)

    return {
        "quantity": quantity,
        "unit": unit,
        "ingredient": ingredient,
        "preparation": preparation,
    }


def split_quantity_unit(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.sub(r"\s*[-–—]\s*", "-", text)

    fraction_pattern = f"[{FRACTION_CHARS}]"
    quantity_value_pattern = rf"(?:\d+\s+\d+/\d+|\d+(?:[./]\d+)?|{fraction_pattern})"
    quantity_pattern = rf"{quantity_value_pattern}(?:\s*(?:-|to)\s*{quantity_value_pattern})?"
    unit_pattern = (
        r"cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?"
    )

    match = re.match(
        rf"^(?P<quantity>{quantity_pattern})(?:\s*(?P<unit>{unit_pattern}))?\s+(?P<ingredient>.+)$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        unit_first_match = re.match(
            rf"^(?P<unit>{unit_pattern})\s+(?P<ingredient>.+)$",
            text,
            flags=re.IGNORECASE,
        )

        if unit_first_match:
            return (
                "1",
                unit_first_match.group("unit").strip(),
                unit_first_match.group("ingredient").strip(),
            )

    if not match:
        return None, None, text

    unit = match.group("unit")

    return (
        match.group("quantity").strip(),
        unit.strip() if unit else None,
        match.group("ingredient").strip(),
    )


def remove_preparation_text(text, preparation):
    if not preparation:
        return text

    text = re.sub(r"\([^)]*\)", " ", text)

    if "," in text:
        text = text.split(",", 1)[0]

    for phrase in str(preparation or "").split(","):
        phrase = phrase.strip()

        if phrase:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.IGNORECASE)

    return re.sub(r"\s+", " ", text).strip()


def classify_store_section(ingredient):
    normalized = normalize_ingredient_key(ingredient)
    normalized = normalized.replace("*", "")

    priority_keywords = (
        ("fresh pasta dough", "PASTA, RICE & GRAINS"),
        ("pasta dough", "PASTA, RICE & GRAINS"),
        ("cocoa butter", "BAKING"),
        ("cocoa powder", "BAKING"),
        ("dutch-processed cocoa powder", "BAKING"),
        ("semisweet chocolate", "BAKING"),
        ("chocolate", "BAKING"),
        ("corn syrup", "BAKING"),
        ("confectioners' sugar", "BAKING"),
        ("confectioners sugar", "BAKING"),
        ("powdered sugar", "BAKING"),
        ("salt and pepper", "SPICES & SEASONINGS"),
        ("tomato sauce", "SAUCES & CONDIMENTS"),
        ("clarified butter", "DAIRY & EGGS"),
        ("yolk", "DAIRY & EGGS"),
        ("greek yoghurt", "DAIRY & EGGS"),
        ("greek yogurt", "DAIRY & EGGS"),
        ("mozzarella", "DAIRY & EGGS"),
        ("cheddar", "DAIRY & EGGS"),
        ("pepperoni", "MEAT & SEAFOOD"),
        ("bread crumbs", "PASTA, RICE & GRAINS"),
        ("breadcrumbs", "PASTA, RICE & GRAINS"),
        ("bread", "BAKERY"),
        ("garlic powder", "SPICES & SEASONINGS"),
        ("onion powder", "SPICES & SEASONINGS"),
        ("italian herb seasoning", "SPICES & SEASONINGS"),
    )

    for keyword, section in priority_keywords:
        if keyword in normalized:
            return section

    for keyword, section in INGREDIENT_STORE_SECTIONS.items():
        if keyword in normalized:
            return section

    produce_words = (
        "basil",
        "lemon",
        "zest",
        "onion",
        "garlic",
        "tomato",
        "spinach",
        "parsley",
        "cilantro",
    )

    if any(word in normalized for word in produce_words):
        return "PRODUCE"

    return "MISC"


def extract_preparation(original_text):
    text = clean_recipe_text(original_text)
    usage_modifiers = [
        "to taste",
        "as desired",
        "for garnish",
        "for garnishing",
        "for serving",
        "sliced lengthways",
        "sliced lengthwise",
        "sliced",
        "chopped",
        "diced",
        "minced",
    ]
    lowered = text.lower()
    matched_modifiers = []
    for modifier in sorted(usage_modifiers, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(modifier)}\b", lowered):
            continue

        if any(modifier in existing for existing in matched_modifiers):
            continue

        matched_modifiers.append(modifier)

    parenthetical_matches = [
        match.strip()
        for match in re.findall(r"\(([^)]*)\)", text)
        if match.strip() and not re.search(r"\d", match)
    ]

    preparation_parts = []
    preparation_parts.extend(matched_modifiers)
    preparation_parts.extend(parenthetical_matches)

    if "," in text:
        comma_tail = text.split(",", 1)[1].strip()

        if not comma_tail.lower().startswith("or "):
            preparation_parts.append(comma_tail)

    if preparation_parts:
        return clean_preparation_text(", ".join(preparation_parts))

    return None


def clean_preparation_text(text):
    value = clean_recipe_text(text).lower()
    replacements = {
        "mleted": "melted",
    }

    for bad_value, good_value in replacements.items():
        value = value.replace(bad_value, good_value)

    parts = []
    seen = set()

    for part in value.split(","):
        part = part.strip()

        if part and part not in seen:
            parts.append(part)
            seen.add(part)

    return ", ".join(parts).strip() or None


def clean_recipe_text(text):
    value = html.unescape(str(text or ""))
    replacements = {
        "Â¼": "¼",
        "Â½": "½",
        "Â¾": "¾",
        "â…": "⅐",
        "â…‘": "⅑",
        "â…’": "⅒",
        "â…“": "⅓",
        "â…”": "⅔",
        "â…•": "⅕",
        "â…–": "⅖",
        "â…—": "⅗",
        "â…˜": "⅘",
        "â…™": "⅙",
        "â…š": "⅚",
        "â…›": "⅛",
        "â…œ": "⅜",
        "â…": "⅝",
        "â…ž": "⅞",
    }

    for bad_value, good_value in replacements.items():
        value = value.replace(bad_value, good_value)

    return re.sub(r"\s+", " ", value).strip()


def build_structured_instructions(raw_instructions):
    flattened = flatten_instruction_nodes(raw_instructions)
    instructions = []

    for index, instruction in enumerate(flattened, start=1):
        instruction = clean_recipe_text(instruction)

        if instruction:
            instructions.append({
                "section": None,
                "step_number": index,
                "instruction": instruction,
                "temperature": None,
                "time": None,
                "equipment_used": [],
            })

    return instructions


def infer_equipment_from_instructions(instructions):
    inferred = {}

    for step in instructions or []:
        instruction = step.get("instruction", "") if isinstance(step, dict) else str(step or "")
        for equipment_name, category, patterns in EQUIPMENT_INFERENCE_RULES:
            if any(re.search(pattern, instruction, flags=re.IGNORECASE) for pattern in patterns):
                inferred[equipment_name] = {
                    "name": equipment_name,
                    "category": category,
                }

    return [
        inferred[name]
        for name in sorted(inferred)
    ]


def equipment_item_name(item):
    if isinstance(item, dict):
        return str(
            item.get("name")
            or item.get("equipment")
            or item.get("text")
            or ""
        ).strip()

    return str(item or "").strip()


def add_equipment_used_to_instructions(instructions, equipment):
    equipment_names = [
        name
        for name in (equipment_item_name(item) for item in equipment or [])
        if name
    ]

    for step in instructions or []:
        if not isinstance(step, dict):
            continue

        instruction = step.get("instruction", "")
        used = []

        for equipment_name in equipment_names:
            patterns = EQUIPMENT_PATTERNS_BY_NAME.get(equipment_name, [])
            if any(re.search(pattern, instruction, flags=re.IGNORECASE) for pattern in patterns):
                used.append(equipment_name)

        step["equipment_used"] = used


def flatten_instruction_nodes(raw_instructions):
    if isinstance(raw_instructions, str):
        return [raw_instructions]

    if not isinstance(raw_instructions, list):
        return []

    instructions = []

    for item in raw_instructions:
        if isinstance(item, str):
            instructions.append(item)
        elif isinstance(item, dict):
            if item.get("@type") == "HowToSection":
                instructions.extend(flatten_instruction_nodes(item.get("itemListElement", [])))
            else:
                text = item.get("text") or item.get("name")
                if text:
                    instructions.append(text)

    return instructions


def build_structured_nutrition(nutrition):
    nutrition = nutrition or {}

    return {
        "serving_basis": "per serving" if nutrition.get("servingSize") else None,
        "calories": nutrition.get("calories"),
        "carbohydrates": nutrition.get("carbohydrateContent"),
        "protein": nutrition.get("proteinContent"),
        "fat": nutrition.get("fatContent"),
        "saturated_fat": nutrition.get("saturatedFatContent"),
        "polyunsaturated_fat": nutrition.get("polyunsaturatedFatContent"),
        "monounsaturated_fat": nutrition.get("monounsaturatedFatContent"),
        "trans_fat": nutrition.get("transFatContent"),
        "cholesterol": nutrition.get("cholesterolContent"),
        "sodium": nutrition.get("sodiumContent"),
        "potassium": nutrition.get("potassiumContent"),
        "fiber": nutrition.get("fiberContent"),
        "sugar": nutrition.get("sugarContent"),
        "vitamin_a": nutrition.get("vitaminAContent"),
        "vitamin_c": nutrition.get("vitaminCContent"),
        "calcium": nutrition.get("calciumContent"),
        "iron": nutrition.get("ironContent"),
        "other": [],
    }


def fetch_recipe_page(recipe_url, progress_callback=None):
    print(f"Fetching recipe page: {recipe_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_HTML.html"

    try:
        response = requests.get(recipe_url, headers=headers, timeout=(8, 15))
        response.raise_for_status()
        html_text = response.text
        html_path.write_text(html_text, encoding="utf-8")
    except Exception as exc:
        if is_forbidden_response(exc) and os.getenv("DISABLE_BROWSER_RECIPE_FETCH") != "1":
            if progress_callback:
                progress_callback(
                    "website blocked direct download - trying browser fetch...",
                    "The site returned 403, so Chrome is opening the page to grab the HTML.",
                )

            try:
                html_text = fetch_recipe_page_with_browser(recipe_url)
                html_path.write_text(html_text, encoding="utf-8")
            except Exception as browser_exc:
                if html_path.exists() and os.getenv("DISABLE_RECIPE_HTML_CACHE_FALLBACK") != "1":
                    print(f"Browser fetch failed; using cached HTML: {html_path}")
                    html_text = html_path.read_text(encoding="utf-8")
                else:
                    raise RuntimeError(
                        "Website blocked automated download with 403 Forbidden, "
                        f"and browser fallback failed: {browser_exc}"
                    ) from browser_exc
        elif html_path.exists() and os.getenv("DISABLE_RECIPE_HTML_CACHE_FALLBACK") != "1":
            print(f"Live fetch failed; using cached HTML: {html_path}")
            html_text = html_path.read_text(encoding="utf-8")
        else:
            raise

    archive_recipe_page_pdf(
        recipe_url,
        html_text,
        html_path,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback(
            "HTML downloaded - reading recipe card data...",
            "Reading structured recipe data from the webpage HTML.",
        )

    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    page_text = soup.get_text(" ", strip=True)
    page_text = re.sub(r"\s+", " ", page_text).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    raw_page_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PAGE_TEXT.txt"
    raw_page_path.write_text(page_text, encoding="utf-8")

    print(f"Loaded webpage text: {len(page_text)} characters")

    return html_text, page_text


def is_social_video_url(recipe_url):
    host = urlparse(str(recipe_url or "")).netloc.lower()
    return any(
        domain in host
        for domain in (
            "youtube.com",
            "youtu.be",
            "instagram.com",
        )
    )


def canonical_social_video_url(recipe_url):
    recipe_url = str(recipe_url or "").strip()
    parsed = urlparse(recipe_url)
    host = parsed.netloc.lower()

    if not parsed.scheme or not parsed.netloc:
        return recipe_url

    parts = [part for part in parsed.path.split("/") if part]

    if "instagram.com" in host and len(parts) >= 2 and parts[0].lower() in {"reel", "reels"}:
        return f"https://www.instagram.com/reel/{parts[1]}/"

    if "youtube.com" in host and len(parts) >= 2 and parts[0].lower() == "shorts":
        return f"https://www.youtube.com/shorts/{parts[1]}"

    if "youtu.be" in host and parts:
        return f"https://youtu.be/{parts[0]}"

    return recipe_url


def extract_recipe_from_social_video_url(recipe_url, progress_callback=None):
    recipe_url = canonical_social_video_url(recipe_url)

    if progress_callback:
        progress_callback(
            "reading social/video recipe text...",
            "Looking for title, caption, description, and transcript text.",
        )

    html_text, page_text = fetch_social_video_text(
        recipe_url,
        progress_callback=progress_callback,
    )
    cover_image = (
        extract_recipe_cover_image_from_html(html_text, recipe_url)
        or load_social_video_cover_image(recipe_url)
    )

    if not has_meaningful_social_video_text(page_text):
        fallback_result = extract_recipe_from_social_video_audio_images(
            recipe_url,
            page_text,
            cover_image=cover_image,
            progress_callback=progress_callback,
        )
        if fallback_result and fallback_result.get("ingredients"):
            return fallback_result

        return {
            "ok": False,
            "source_url": recipe_url,
            "error": "No public caption, description, or transcript text was found for that video URL.",
            "ingredients": [],
        }

    local_json_data = extract_recipe_from_social_video_text(recipe_url, page_text)
    if not isinstance(local_json_data, dict):
        local_json_data = {
            "source_url": recipe_url,
            "ingredients": [],
            "equipment": [],
            "instructions": [],
            "nutrition": empty_nutrition(),
        }

    if cover_image:
        local_json_data["cover_image"] = cover_image

    if structured_recipe_data_is_usable(local_json_data):
        if os.getenv("OPENAI_API_KEY") and social_video_result_needs_audio_image_enrichment(local_json_data):
            audio_image_result = extract_recipe_from_social_video_audio_images(
                recipe_url,
                page_text,
                cover_image=cover_image,
                progress_callback=progress_callback,
            )

            if audio_image_result and audio_image_result.get("ingredients"):
                return audio_image_result

        result_json_data = local_json_data
        extraction_method = "social_video_text"

        if os.getenv("OPENAI_API_KEY"):
            enriched_json_data = extract_video_recipe_pdf_data_with_openai(
                recipe_url,
                page_text,
                progress_callback=progress_callback,
            )

            if structured_recipe_data_is_usable(enriched_json_data):
                result_json_data = enriched_json_data
                extraction_method = "social_video_text_openai_estimates"

                if cover_image:
                    result_json_data["cover_image"] = cover_image

        archive_social_video_text_pdf(
            recipe_url,
            page_text,
            structured_recipe_data=result_json_data,
            prefer_openai=False,
            progress_callback=progress_callback,
        )
        save_extracted_recipe_json(recipe_url, result_json_data)

        if progress_callback:
            if extraction_method == "social_video_text_openai_estimates":
                progress_callback(
                    "video recipe estimates added.",
                    "ChatGPT filled missing recipe amount, timing, quantities, and nutrition where the video text supported estimates.",
                )
            else:
                progress_callback(
                    "recipe text parsed without OpenAI API fallback.",
                    "The public video description included ingredient and cooking-step sections.",
                )

        return build_extract_result(recipe_url, result_json_data, extraction_method)

    if not os.getenv("OPENAI_API_KEY"):
        archive_social_video_text_pdf(
            recipe_url,
            page_text,
            structured_recipe_data=local_json_data,
            progress_callback=progress_callback,
        )
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": "Missing OPENAI_API_KEY environment variable.",
            "ingredients": [],
        }

    if progress_callback:
        progress_callback(
            "sending video text to OpenAI API...",
            "ChatGPT is extracting recipe details from the public video text.",
        )

    response_text = send_prompt_to_openai(
        build_social_video_prompt(recipe_url, page_text[:MAX_SOCIAL_VIDEO_PROMPT_CHARS])
    )
    raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_API_RESPONSE.txt"
    raw_api_path.write_text(response_text, encoding="utf-8")

    success, json_data = save_json_response(recipe_url, response_text)

    if not success or not json_data:
        fallback_result = extract_recipe_from_social_video_audio_images(
            recipe_url,
            page_text,
            cover_image=cover_image,
            progress_callback=progress_callback,
        )
        if fallback_result and fallback_result.get("ingredients"):
            return fallback_result

        archive_social_video_text_pdf(
            recipe_url,
            page_text,
            progress_callback=progress_callback,
        )
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": "Invalid JSON returned by OpenAI.",
            "ingredients": [],
        }

    json_data["source_url"] = recipe_url
    if cover_image:
        json_data["cover_image"] = cover_image
    archive_social_video_text_pdf(
        recipe_url,
        page_text,
        structured_recipe_data=json_data,
        progress_callback=progress_callback,
    )
    result = build_extract_result(recipe_url, json_data, "social_video")

    if social_video_result_needs_audio_image_enrichment(json_data):
        audio_image_result = extract_recipe_from_social_video_audio_images(
            recipe_url,
            page_text,
            cover_image=cover_image,
            progress_callback=progress_callback,
        )

        if audio_image_result and audio_image_result.get("ingredients"):
            return audio_image_result

    if not result.get("ingredients"):
        fallback_result = extract_recipe_from_social_video_audio_images(
            recipe_url,
            page_text,
            cover_image=cover_image,
            progress_callback=progress_callback,
        )
        if fallback_result and fallback_result.get("ingredients"):
            return fallback_result

        return {
            "ok": False,
            "source_url": recipe_url,
            "error": "No ingredients were found in the public title, caption, description, or transcript text.",
            "ingredients": [],
            "raw": json_data,
            "extraction_method": "social_video",
        }

    save_extracted_recipe_json(recipe_url, json_data)
    return result


def fetch_social_video_text(recipe_url, progress_callback=None):
    recipe_url = canonical_social_video_url(recipe_url)
    raw_page_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_TEXT.txt"
    cached_page_text = load_cached_social_video_text(raw_page_path)

    if social_video_text_is_ready_for_extraction(recipe_url, cached_page_text):
        return "", cached_page_text

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    html_text = ""
    page_text = ""
    direct_error = None

    try:
        response = requests.get(recipe_url, headers=headers, timeout=(5, 10))
        response.raise_for_status()
        html_text = response.text
    except Exception as exc:
        if has_meaningful_social_video_text(cached_page_text):
            return "", cached_page_text
        direct_error = exc
    else:
        html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_HTML.html"
        html_path.write_text(html_text, encoding="utf-8")
        page_text = build_social_video_page_text(recipe_url, html_text)

        if social_video_text_is_ready_for_extraction(recipe_url, page_text):
            raw_page_path.write_text(page_text, encoding="utf-8")
            return html_text, page_text

    instagram_result = fetch_instagram_embed_text(
        recipe_url,
        headers=headers,
        progress_callback=progress_callback,
    )

    if instagram_result and social_video_text_is_ready_for_extraction(recipe_url, instagram_result[1]):
        html_text, page_text = instagram_result
        raw_page_path.write_text(page_text, encoding="utf-8")
        return html_text, page_text

    downloader_result = fetch_social_video_text_with_downloader(
        recipe_url,
        progress_callback=progress_callback,
    )

    if downloader_result and has_meaningful_social_video_text(downloader_result[1]):
        html_text, page_text = downloader_result
        raw_page_path.write_text(page_text, encoding="utf-8")
        return html_text, page_text

    browser_result = fetch_social_video_text_with_browser(
        recipe_url,
        progress_callback=progress_callback,
    )

    if browser_result and social_video_text_is_ready_for_extraction(recipe_url, browser_result[1]):
        html_text, page_text = browser_result
        raw_page_path.write_text(page_text, encoding="utf-8")
        return html_text, page_text

    if direct_error:
        raise direct_error

    raw_page_path.write_text(page_text, encoding="utf-8")
    return html_text, page_text


def social_video_text_is_ready_for_extraction(recipe_url, page_text):
    if not has_meaningful_social_video_text(page_text):
        return False

    if re.search(r"\btranscript\s*:", str(page_text or ""), flags=re.IGNORECASE):
        return True

    local_json_data = extract_recipe_from_social_video_text(recipe_url, page_text)
    return structured_recipe_data_is_usable(local_json_data)


def build_social_video_page_text(recipe_url, html_text, include_visible_text=False):
    metadata = extract_social_metadata(html_text)

    try:
        transcript = extract_youtube_transcript(recipe_url, html_text)
    except Exception as exc:
        transcript = ""
        transcript_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_TRANSCRIPT_ERROR.txt"
        transcript_error_path.write_text(str(exc), encoding="utf-8")

    parts = [
        f"Title: {metadata.get('title')}" if metadata.get("title") else "",
        f"Description: {metadata.get('description')}" if metadata.get("description") else "",
        f"Transcript: {transcript}" if transcript else "",
    ]

    if include_visible_text:
        visible_text = extract_visible_social_page_text(html_text)

        if visible_text:
            parts.append(f"Visible text: {visible_text}")

    page_text = "\n\n".join(part for part in parts if part).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    return page_text


def fetch_instagram_embed_text(recipe_url, headers=None, progress_callback=None):
    embed_url = instagram_embed_url(recipe_url)

    if not embed_url:
        return None

    if progress_callback:
        progress_callback(
            "opening Instagram embed page...",
            "Trying Instagram's public embed page for caption text.",
        )

    try:
        response = requests.get(embed_url, headers=headers or {}, timeout=(5, 10))
        response.raise_for_status()
    except Exception:
        return None

    html_text = response.text

    if not html_text:
        return None

    html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_INSTAGRAM_EMBED_HTML.html"
    html_path.write_text(html_text, encoding="utf-8")
    page_text = build_social_video_page_text(
        recipe_url,
        html_text,
        include_visible_text=True,
    )

    return html_text, page_text


def instagram_embed_url(recipe_url):
    parsed = urlparse(str(recipe_url or ""))
    host = parsed.netloc.lower()

    if "instagram.com" not in host:
        return None

    parts = [part for part in parsed.path.split("/") if part]

    if len(parts) < 2 or parts[0] not in {"p", "reel", "tv"}:
        return None

    return f"https://www.instagram.com/{parts[0]}/{parts[1]}/embed/captioned/"


def fetch_social_video_text_with_browser(recipe_url, progress_callback=None):
    if os.getenv("DISABLE_BROWSER_RECIPE_FETCH") == "1":
        return None

    if progress_callback:
        progress_callback(
            "opening video page in browser...",
            "The public video page is being opened like a normal webpage to read rendered text.",
        )

    for target_url in social_browser_candidate_urls(recipe_url):
        try:
            html_text = fetch_recipe_page_with_browser(target_url)
        except Exception:
            continue

        if not html_text:
            continue

        suffix = (
            "INSTAGRAM_EMBED_BROWSER_HTML"
            if target_url != recipe_url and instagram_embed_url(recipe_url) == target_url
            else "SOCIAL_BROWSER_HTML"
        )
        html_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_{suffix}.html"
        html_path.write_text(html_text, encoding="utf-8")
        page_text = build_social_video_page_text(
            recipe_url,
            html_text,
            include_visible_text=True,
        )

        if has_meaningful_social_video_text(page_text):
            return html_text, page_text

    return None


def social_browser_candidate_urls(recipe_url):
    urls = [recipe_url]
    embed_url = instagram_embed_url(recipe_url)

    if embed_url and embed_url not in urls:
        urls.append(embed_url)

    return urls


def fetch_social_video_text_with_downloader(recipe_url, progress_callback=None):
    if os.getenv("DISABLE_VIDEO_DOWNLOADER") == "1":
        return None

    if progress_callback:
        progress_callback(
            "checking video metadata with yt-dlp...",
            "Trying video captions, description, and audio when the public page text is unavailable.",
        )

    info = fetch_social_video_ytdlp_info(recipe_url)
    if not info:
        return None

    cover_image = (
        extract_recipe_cover_image_from_ytdlp_info(info)
        or extract_social_video_frame_cover_image(recipe_url, info)
    )
    save_social_video_cover_image(
        recipe_url,
        cover_image,
    )

    page_text = build_ytdlp_page_text(recipe_url, info)

    if has_meaningful_social_video_text(page_text):
        local_json_data = extract_recipe_from_social_video_text(recipe_url, page_text)

        if structured_recipe_data_is_usable(local_json_data):
            raw_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_YTDLP_TEXT.txt"
            raw_path.write_text(page_text, encoding="utf-8")
            return "", page_text

        transcript = transcribe_social_video_audio(
            recipe_url,
            info,
            progress_callback=progress_callback,
        )

        if transcript:
            page_text = append_social_transcript_text(page_text, transcript)

        raw_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_YTDLP_TEXT.txt"
        raw_path.write_text(page_text, encoding="utf-8")
        return "", page_text

    transcript = transcribe_social_video_audio(recipe_url, info, progress_callback=progress_callback)

    if not transcript:
        return None

    parts = [
        f"Title: {clean_recipe_text(info.get('title'))}" if info.get("title") else "",
        f"Description: {clean_recipe_text(info.get('description'))}" if info.get("description") else "",
        f"Transcript: {transcript}",
    ]
    page_text = "\n\n".join(part for part in parts if part).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    raw_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_YTDLP_TRANSCRIBED_TEXT.txt"
    raw_path.write_text(page_text, encoding="utf-8")
    return "", page_text


def fetch_social_video_ytdlp_info(recipe_url):
    if os.getenv("DISABLE_VIDEO_DOWNLOADER") == "1":
        return {}

    try:
        import yt_dlp
    except Exception as exc:
        write_social_downloader_error(recipe_url, f"yt-dlp is not installed: {exc}")
        return {}

    try:
        with yt_dlp.YoutubeDL(build_ytdlp_options(recipe_url, download=False)) as ydl:
            info = ydl.extract_info(recipe_url, download=False)
    except Exception as exc:
        write_social_downloader_error(recipe_url, exc)
        return {}

    return info if isinstance(info, dict) else {}


def append_social_transcript_text(page_text, transcript):
    transcript = clean_recipe_text(transcript)

    if not transcript:
        return page_text

    if "Transcript:" in str(page_text or ""):
        return page_text

    combined = f"{page_text}\n\nTranscript: {transcript}".strip()

    if len(combined) > MAX_PAGE_TEXT_CHARS:
        combined = combined[:MAX_PAGE_TEXT_CHARS]

    return combined


def extract_recipe_from_social_video_audio_images(recipe_url, page_text="", cover_image=None, progress_callback=None):
    if not os.getenv("OPENAI_API_KEY"):
        return None

    if progress_callback:
        progress_callback(
            "checking video audio and images with OpenAI...",
            "The app is combining audio transcription and video images to fill missing recipe details.",
        )

    context = build_social_video_audio_image_context(
        recipe_url,
        page_text=page_text,
        cover_image=cover_image,
        progress_callback=progress_callback,
    )
    image_urls = context.get("image_urls", [])
    combined_text = context.get("text", "")
    cover_image = context.get("cover_image") or cover_image

    if not combined_text and not image_urls:
        return None

    try:
        response_text = send_social_video_audio_image_prompt_to_openai(
            build_social_video_audio_image_prompt(recipe_url, combined_text),
            image_urls,
        )
    except Exception as exc:
        write_social_downloader_error(recipe_url, f"Social video audio/image OpenAI fallback failed: {exc}")
        return None

    raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_AUDIO_IMAGE_API_RESPONSE.txt"
    raw_api_path.write_text(response_text, encoding="utf-8")

    try:
        preview_data = json.loads(clean_json_response(response_text))
        if isinstance(preview_data, dict):
            archive_social_video_text_pdf(
                recipe_url,
                combined_text,
                structured_recipe_data=preview_data,
                progress_callback=progress_callback,
            )
    except Exception:
        pass

    success, json_data = save_json_response(recipe_url, response_text)

    if not success or not isinstance(json_data, dict):
        return None

    if cover_image and not json_data.get("cover_image"):
        json_data["cover_image"] = cover_image

    json_data = complete_social_video_recipe_with_openai_if_needed(
        recipe_url,
        json_data,
        combined_text,
        image_urls,
        cover_image=cover_image,
        progress_callback=progress_callback,
    )

    result = build_extract_result(recipe_url, json_data, "social_video_audio_image")
    return result if result.get("ingredients") else None


def build_social_video_audio_image_context(recipe_url, page_text="", cover_image=None, progress_callback=None):
    info = fetch_social_video_ytdlp_info(recipe_url)
    cover_image = (
        cover_image
        or extract_recipe_cover_image_from_ytdlp_info(info)
        or extract_social_video_frame_cover_image(recipe_url, info)
    )
    if cover_image:
        save_social_video_cover_image(recipe_url, cover_image)

    image_urls = social_video_image_urls_from_info(info, cover_image=cover_image)
    text_parts = []
    page_text = clean_recipe_text(page_text)

    if page_text:
        text_parts.append(page_text)

    if info:
        info_text = build_ytdlp_page_text(recipe_url, info)
        if info_text and info_text not in text_parts:
            text_parts.append(info_text)

        transcript = transcribe_social_video_audio(
            recipe_url,
            info,
            progress_callback=progress_callback,
        )
        if transcript:
            text_parts.append(f"Audio transcript: {transcript}")

    combined_text = "\n\n".join(part for part in text_parts if part).strip()

    if len(combined_text) > MAX_PAGE_TEXT_CHARS:
        combined_text = combined_text[:MAX_PAGE_TEXT_CHARS]

    return {
        "text": combined_text,
        "image_urls": image_urls[:MAX_SOCIAL_VIDEO_IMAGE_URLS],
        "cover_image": cover_image,
    }


def social_video_image_urls_from_info(info, cover_image=None):
    candidates = []
    seen = set()

    def add_candidate(candidate):
        normalized = normalize_recipe_cover_image(
            candidate,
            fallback_alt=clean_recipe_text((info or {}).get("title") or "") or "Recipe video image",
            source="video_thumbnail",
        )
        url = social_video_openai_image_url(normalized)
        if not url or url in seen:
            return
        seen.add(url)
        normalized["openai_url"] = url
        candidates.append(normalized)

    add_candidate(cover_image)

    if isinstance(info, dict):
        add_candidate(info.get("thumbnail"))
        for item in info.get("thumbnails") or []:
            add_candidate(item)

    candidates = sorted(candidates, key=cover_image_score, reverse=True)
    return [candidate["openai_url"] for candidate in candidates if candidate.get("openai_url")]


def social_video_openai_image_url(cover_image):
    if not isinstance(cover_image, dict):
        return ""

    url = str(cover_image.get("url") or "").strip()
    if url.startswith(("http://", "https://", "data:image/")):
        return url

    image_path = recipe_cover_image_file_path(cover_image)
    if not image_path:
        return ""

    try:
        image_bytes = image_path.read_bytes()
    except Exception:
        return ""

    if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
        return ""

    mime_type = (
        clean_cover_image_text(cover_image.get("mime_type"))
        or mimetypes.guess_type(str(image_path))[0]
        or "image/jpeg"
    )
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def build_ytdlp_options(recipe_url, download=False):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
        "skip_download": not download,
    }
    cookie_file = os.getenv("YTDLP_COOKIES_FILE")
    cookies_from_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    youtube_player_clients = ytdlp_youtube_player_clients(recipe_url, download=download)

    if cookie_file:
        options["cookiefile"] = cookie_file

    if cookies_from_browser:
        options["cookiesfrombrowser"] = tuple(
            part.strip()
            for part in cookies_from_browser.split(",")
            if part.strip()
        )

    if youtube_player_clients:
        options["extractor_args"] = {
            "youtube": {
                "player_client": youtube_player_clients,
            }
        }

    if download:
        options.update({
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "outtmpl": str(VIDEO_FOLDER / f"{safe_filename(recipe_url)}.%(ext)s"),
        })

    return options


def ytdlp_youtube_player_clients(recipe_url, download=False):
    if not is_youtube_url(recipe_url):
        return []

    configured_clients = os.getenv("YTDLP_YOUTUBE_PLAYER_CLIENTS")
    if configured_clients is not None:
        configured_clients = configured_clients.strip()
        if configured_clients.lower() in {"", "none", "off", "disabled"}:
            return []
        return [
            client.strip()
            for client in configured_clients.split(",")
            if client.strip()
        ]

    if download:
        return list(DEFAULT_YOUTUBE_AUDIO_PLAYER_CLIENTS)

    return []


def is_youtube_url(recipe_url):
    host = urlparse(recipe_url or "").netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def build_ytdlp_page_text(recipe_url, info):
    parts = []
    title = clean_recipe_text(info.get("title"))
    description = clean_recipe_text(info.get("description"))
    subtitle_text = extract_ytdlp_subtitle_text(recipe_url, info)

    if title:
        parts.append(f"Title: {title}")

    if description:
        parts.append(f"Description: {description}")

    if subtitle_text:
        parts.append(f"Transcript: {subtitle_text}")

    page_text = "\n\n".join(parts).strip()

    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    return page_text


def extract_recipe_cover_image_from_ytdlp_info(info):
    if not isinstance(info, dict):
        return {}

    fallback_alt = clean_recipe_text(info.get("title") or "") or "Recipe video cover image"
    candidates = []
    thumbnail = normalize_recipe_cover_image(
        info.get("thumbnail"),
        fallback_alt=fallback_alt,
        source="video_thumbnail",
    )

    if thumbnail:
        candidates.append(thumbnail)

    for item in info.get("thumbnails") or []:
        cover_image = normalize_recipe_cover_image(
            item,
            fallback_alt=fallback_alt,
            source="video_thumbnail",
        )

        if cover_image:
            candidates.append(cover_image)

    if not candidates:
        return {}

    return max(candidates, key=cover_image_score)


def extract_social_video_frame_cover_image(recipe_url, info=None):
    if os.getenv("DISABLE_SOCIAL_VIDEO_FRAME_COVER") == "1":
        return {}

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {}

    video_path = download_social_video_frame_source(recipe_url)
    if not video_path:
        return {}

    frame_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_TITLE_FRAME.jpg"
    timestamp = social_video_cover_frame_timestamp(info)
    if not save_video_frame_image(ffmpeg, video_path, frame_path, timestamp):
        if not save_video_frame_image(ffmpeg, video_path, frame_path, 0):
            return {}

    try:
        relative_path = frame_path.resolve().relative_to(EXTRACTOR_FOLDER.resolve())
    except Exception:
        return {}

    fallback_alt = clean_recipe_text((info or {}).get("title") or "") or "Recipe video title image"
    return normalize_recipe_cover_image(
        {
            "path": str(relative_path).replace("\\", "/"),
            "mime_type": "image/jpeg",
            "alt": fallback_alt,
            "source": "video_frame",
        },
        base_url=recipe_url,
        fallback_alt=fallback_alt,
    )


def social_video_cover_frame_timestamp(info):
    duration = 0

    if isinstance(info, dict):
        try:
            duration = float(info.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0

    if duration <= 0:
        return 1

    return min(max(duration * 0.25, 1), 8)


def download_social_video_frame_source(recipe_url):
    try:
        import yt_dlp
    except Exception as exc:
        write_social_downloader_error(recipe_url, f"yt-dlp is not installed: {exc}")
        return None

    base_name = f"{safe_filename(recipe_url)}_frame_source"
    before = set(VIDEO_FOLDER.glob(f"{base_name}.*"))
    options = build_ytdlp_options(recipe_url, download=True)
    options.update({
        "format": (
            "bestvideo[height<=720][ext=mp4]/"
            "best[height<=720][ext=mp4]/"
            "bestvideo[height<=720]/best[height<=720]/best"
        ),
        "outtmpl": str(VIDEO_FOLDER / f"{base_name}.%(ext)s"),
    })

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(recipe_url, download=True)
    except Exception as exc:
        write_social_downloader_error(recipe_url, exc)
        return None

    candidates = [
        path
        for path in VIDEO_FOLDER.glob(f"{base_name}.*")
        if path not in before and path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
    ]

    if not candidates:
        candidates = [
            path
            for path in VIDEO_FOLDER.glob(f"{base_name}.*")
            if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
        ]

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def save_video_frame_image(ffmpeg, video_path, frame_path, timestamp):
    frame_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{float(timestamp):.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(frame_path),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except Exception:
        return False

    return completed.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0


def social_video_cover_image_path(recipe_url):
    return RAW_FOLDER / f"{safe_filename(recipe_url)}_COVER_IMAGE.json"


def save_social_video_cover_image(recipe_url, cover_image):
    if not cover_image:
        return

    social_video_cover_image_path(recipe_url).write_text(
        json.dumps(cover_image, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_social_video_cover_image(recipe_url):
    cover_path = social_video_cover_image_path(recipe_url)

    if not cover_path.exists():
        return {}

    try:
        return normalize_recipe_cover_image(json.loads(cover_path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def extract_ytdlp_subtitle_text(recipe_url, info):
    tracks = info.get("subtitles") or {}
    automatic_tracks = info.get("automatic_captions") or {}
    track = choose_ytdlp_subtitle_track(tracks) or choose_ytdlp_subtitle_track(automatic_tracks)

    if not track:
        return ""

    for candidate in track:
        if not isinstance(candidate, dict):
            continue

        subtitle_url = candidate.get("url")

        if not subtitle_url:
            continue

        try:
            response = requests.get(subtitle_url, timeout=(5, 12))
            response.raise_for_status()
        except Exception:
            continue

        text = parse_subtitle_text(response.text, candidate.get("ext"))

        if text:
            raw_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_YTDLP_SUBTITLES.txt"
            raw_path.write_text(text, encoding="utf-8")
            return text

    return ""


def choose_ytdlp_subtitle_track(tracks):
    if not isinstance(tracks, dict) or not tracks:
        return None

    preferred_keys = [
        key
        for key in tracks
        if str(key).lower().startswith("en")
    ]
    key = preferred_keys[0] if preferred_keys else next(iter(tracks))
    track = tracks.get(key)

    return track if isinstance(track, list) else None


def parse_subtitle_text(raw_text, ext=None):
    text = str(raw_text or "")

    if str(ext or "").lower() == "json3":
        try:
            payload = json.loads(text)
        except Exception:
            payload = {}

        events = payload.get("events", []) if isinstance(payload, dict) else []
        lines = []

        for event in events:
            for segment in event.get("segs", []) if isinstance(event, dict) else []:
                value = segment.get("utf8") if isinstance(segment, dict) else ""

                if value:
                    lines.append(value)

        return clean_recipe_text(" ".join(lines))

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line or line.upper() == "WEBVTT":
            continue

        if re.match(r"^\d+$", line):
            continue

        if "-->" in line:
            continue

        if line.startswith(("NOTE", "STYLE", "Kind:", "Language:")):
            continue

        line = re.sub(r"<[^>]+>", " ", line)
        lines.append(line)

    return clean_recipe_text(" ".join(lines))


def transcribe_social_video_audio(recipe_url, info, progress_callback=None):
    if not os.getenv("OPENAI_API_KEY"):
        return ""

    duration = info.get("duration")

    try:
        duration_seconds = float(duration or 0)
    except (TypeError, ValueError):
        duration_seconds = 0

    if duration_seconds and duration_seconds > MAX_VIDEO_TRANSCRIPTION_SECONDS:
        write_social_downloader_error(
            recipe_url,
            f"Skipping transcription because video is {duration_seconds} seconds.",
        )
        return ""

    if progress_callback:
        progress_callback(
            "downloading video audio for transcription...",
            "No usable caption text was found, so the video audio is being transcribed.",
        )

    audio_path = download_social_video_audio(recipe_url)

    if not audio_path:
        return ""

    try:
        if audio_path.stat().st_size > MAX_VIDEO_AUDIO_BYTES:
            write_social_downloader_error(
                recipe_url,
                f"Skipping transcription because audio is {audio_path.stat().st_size} bytes.",
            )
            return ""

        transcript = send_audio_transcription_to_openai(audio_path)
    except Exception as exc:
        write_social_downloader_error(recipe_url, exc)
        return ""

    transcript = clean_recipe_text(transcript)

    if transcript:
        raw_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_AUDIO_TRANSCRIPT.txt"
        raw_path.write_text(transcript, encoding="utf-8")

    return transcript


def download_social_video_audio(recipe_url):
    try:
        import yt_dlp
    except Exception as exc:
        write_social_downloader_error(recipe_url, f"yt-dlp is not installed: {exc}")
        return None

    before = set(VIDEO_FOLDER.glob(f"{safe_filename(recipe_url)}.*"))

    try:
        with yt_dlp.YoutubeDL(build_ytdlp_options(recipe_url, download=True)) as ydl:
            ydl.extract_info(recipe_url, download=True)
    except Exception as exc:
        write_social_downloader_error(recipe_url, exc)
        return None

    candidates = [
        path
        for path in VIDEO_FOLDER.glob(f"{safe_filename(recipe_url)}.*")
        if path not in before and path.suffix.lower() in {".mp3", ".m4a", ".wav", ".webm", ".mp4"}
    ]

    if not candidates:
        candidates = [
            path
            for path in VIDEO_FOLDER.glob(f"{safe_filename(recipe_url)}.*")
            if path.suffix.lower() in {".mp3", ".m4a", ".wav", ".webm", ".mp4"}
        ]

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def send_audio_transcription_to_openai(audio_path):
    with audio_path.open("rb") as audio_file:
        response = get_openai_client().audio.transcriptions.create(
            model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
            file=audio_file,
            response_format="text",
        )
        record_openai_usage(
            response,
            "audio-transcription",
            model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
        )

    return str(response or "")


def write_social_downloader_error(recipe_url, error):
    error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_YTDLP_ERROR.txt"
    error_path.write_text(str(error), encoding="utf-8")


def extract_visible_social_page_text(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    page_text = soup.get_text(" ", strip=True)
    page_text = re.sub(r"\s+", " ", page_text).strip()

    if len(page_text) > MAX_SOCIAL_VIDEO_PROMPT_CHARS:
        page_text = page_text[:MAX_SOCIAL_VIDEO_PROMPT_CHARS]

    return page_text


def load_cached_social_video_text(raw_page_path):
    try:
        return raw_page_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_recipe_from_social_video_text(recipe_url, page_text):
    title = extract_social_text_label(page_text, "title")
    plain_text = social_video_plain_text(page_text)
    ingredient_lines = extract_social_ingredient_lines(plain_text)
    instruction_lines = extract_social_instruction_lines(plain_text)

    if not ingredient_lines:
        return None

    ingredients = build_structured_ingredients(ingredient_lines)
    instructions = build_social_video_instructions(instruction_lines)

    if not ingredients:
        return None

    equipment = infer_equipment_from_instructions(instructions)
    add_equipment_used_to_instructions(instructions, equipment)

    return {
        "source_url": recipe_url,
        "display_name": title,
        "recipe_title": title,
        "servings": None,
        "ingredients": ingredients,
        "equipment": equipment,
        "instructions": instructions,
        "nutrition": empty_nutrition(),
    }


def social_video_plain_text(page_text):
    text = str(page_text or "")
    text = re.sub(r"(?im)^\s*(title|description|transcript):\s*", "", text)
    text = re.sub(r"\s+", " ", clean_recipe_text(text))
    return text.strip()


def extract_social_text_label(page_text, label):
    pattern = rf"(?ims)^\s*{re.escape(label)}:\s*(.+?)(?=^\s*(?:title|description|transcript):|\Z)"
    match = re.search(pattern, str(page_text or ""))

    if not match:
        return None

    value = clean_recipe_text(match.group(1))
    return value or None


def extract_social_ingredient_lines(text):
    match = re.search(
        r"\bingredients?\b(?P<section>.+?)(?=\b(?:cooking\s+steps?|directions?|instructions?|method|macros?|nutrition|credit|ps\b|end\s+of)\b|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return []

    section = clean_social_ingredient_section(match.group("section"))
    starts = [
        found.start()
        for found in re.finditer(
            social_ingredient_start_pattern(),
            section,
            flags=re.IGNORECASE,
        )
    ]

    if not starts:
        return split_social_ingredient_lines(section)

    lines = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(section)
        line = clean_social_ingredient_line(section[start:end])

        if line:
            lines.append(line)

    return lines


def clean_social_ingredient_section(section):
    section = re.sub(r"(?:â¸»|⸻|[•·|]+)", " ", str(section or ""))
    section = re.sub(
        r"\bIf using\b.+?\b(?:baking powder|baking soda|yeast)\b",
        " ",
        section,
        flags=re.IGNORECASE,
    )
    section = re.sub(r"\bIf using\b.+?(?=\s+\d|\s+[{}]|$)".format(FRACTION_CHARS), " ", section, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", section).strip(" :-")


def social_ingredient_start_pattern():
    quantity_pattern = rf"(?:\d+\s+\d+/\d+|\d+(?:[./]\d+)?|[{FRACTION_CHARS}])"
    unit_pattern = (
        r"cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?"
    )
    return rf"(?<!\w){quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s*(?:{unit_pattern})?\b"


def split_social_ingredient_lines(section):
    return [
        clean_social_ingredient_line(line)
        for line in re.split(r"[\n;]+", section)
        if clean_social_ingredient_line(line)
    ]


def clean_social_ingredient_line(line):
    value = clean_recipe_text(line)
    value = re.sub(r"(?:â¸»|⸻)", " ", value)
    value = re.sub(r"\bregular or\s+(.+?)\s+works too\b", r"or \1", value, flags=re.IGNORECASE)
    value = re.sub(r"\boptional\b", " optional", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-")

    if not value or len(value) > 160:
        return ""

    return value


def extract_social_instruction_lines(text):
    match = re.search(
        r"\b(?:cooking\s+steps?|directions?|instructions?|method)\b(?P<section>.+?)(?=\b(?:macros?|nutrition|credit|ps\b|end\s+of)\b|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return []

    section = re.sub(r"(?:â¸»|⸻)", " ", match.group("section"))
    section = re.sub(r"\s+", " ", section).strip(" :-")
    matches = list(re.finditer(r"(?:^|\s)(\d+)\.\s+", section))

    if not matches:
        return [
            clean_recipe_text(line)
            for line in re.split(r"[\n;]+", section)
            if clean_recipe_text(line)
        ]

    lines = []
    for index, found in enumerate(matches):
        start = found.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        instruction = clean_recipe_text(section[start:end])

        if instruction:
            lines.append(instruction)

    return lines


def build_social_video_instructions(instruction_lines):
    return [
        {
            "section": None,
            "step_number": index,
            "instruction": instruction,
            "temperature": extract_instruction_temperature(instruction),
            "time": extract_instruction_time(instruction),
            "equipment_used": [],
        }
        for index, instruction in enumerate(instruction_lines, start=1)
    ]


def extract_instruction_temperature(instruction):
    match = re.search(r"\b\d{2,3}\s*(?:Â°|°)?\s*[CF]\b", instruction, flags=re.IGNORECASE)
    return match.group(0) if match else None


def extract_instruction_time(instruction):
    match = re.search(r"\b\d+(?:\s*(?:-|to)\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?)\b", instruction, flags=re.IGNORECASE)
    return match.group(0) if match else None


def empty_nutrition():
    return {
        "serving_basis": None,
        "calories": None,
        "carbohydrates": None,
        "protein": None,
        "fat": None,
        "saturated_fat": None,
        "polyunsaturated_fat": None,
        "monounsaturated_fat": None,
        "trans_fat": None,
        "cholesterol": None,
        "sodium": None,
        "potassium": None,
        "fiber": None,
        "sugar": None,
        "vitamin_a": None,
        "vitamin_c": None,
        "calcium": None,
        "iron": None,
        "other": [],
    }


def has_meaningful_social_video_text(page_text):
    text = clean_recipe_text(page_text)

    if not text:
        return False

    generic_values = {
        "instagram",
        "instagram photo",
        "instagram reel",
        "watch this instagram reel",
    }
    meaningful_lines = []

    for line in str(page_text or "").splitlines():
        value = clean_recipe_text(line)

        if not value:
            continue

        content = re.sub(
            r"^(title|description|transcript):\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

        if content.lower() in generic_values:
            continue

        meaningful_lines.append(content)

    meaningful_text = " ".join(meaningful_lines).strip()
    return len(meaningful_text) >= 40


def extract_social_metadata(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    def meta_content(*selectors):
        for selector in selectors:
            tag = soup.select_one(selector)
            value = tag.get("content") if tag else ""

            if value:
                return clean_recipe_text(value)

        return ""

    title = meta_content(
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        'meta[name="title"]',
    )

    if not title and soup.title and soup.title.string:
        title = clean_recipe_text(soup.title.string)

    description = meta_content(
        'meta[property="og:description"]',
        'meta[name="twitter:description"]',
        'meta[name="description"]',
    )

    player_response = extract_youtube_player_response(html_text)

    if isinstance(player_response, dict) and player_response:
        video_details = player_response.get("videoDetails") or {}
        microformat = (
            player_response.get("microformat", {})
            .get("playerMicroformatRenderer", {})
        )

        youtube_title = clean_recipe_text(video_details.get("title") or "")
        microformat_title = youtube_json_text(microformat.get("title"))
        if youtube_title:
            title = youtube_title
        elif microformat_title:
            title = microformat_title

        description_candidates = [
            description,
            clean_recipe_text(video_details.get("shortDescription") or ""),
            youtube_json_text(microformat.get("description")),
        ]
        description = max(description_candidates, key=lambda value: len(value or ""))

    return {
        "title": title,
        "description": description,
    }


def youtube_json_text(value):
    if isinstance(value, str):
        return clean_recipe_text(value)

    if not isinstance(value, dict):
        return ""

    if value.get("simpleText"):
        return clean_recipe_text(value.get("simpleText"))

    runs = value.get("runs")
    if isinstance(runs, list):
        return clean_recipe_text(
            "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict))
        )

    return ""


def extract_youtube_transcript(recipe_url, html_text):
    host = urlparse(recipe_url).netloc.lower()

    if "youtube.com" not in host and "youtu.be" not in host:
        return ""

    player_response = extract_youtube_player_response(html_text)
    caption_tracks = (
        player_response.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks", [])
        if isinstance(player_response, dict)
        else []
    )

    if not caption_tracks:
        return ""

    preferred_track = next(
        (
            track
            for track in caption_tracks
            if str(track.get("languageCode") or "").lower().startswith("en")
        ),
        caption_tracks[0],
    )
    base_url = preferred_track.get("baseUrl")

    if not base_url:
        return ""

    transcript_url = unquote(base_url)
    response = requests.get(transcript_url, timeout=(8, 15))
    response.raise_for_status()

    root = ET.fromstring(response.text)
    text_parts = [
        clean_recipe_text("".join(node.itertext()))
        for node in root.findall(".//text")
    ]

    return " ".join(part for part in text_parts if part)


def extract_youtube_player_response(html_text):
    patterns = [
        r"ytInitialPlayerResponse\s*=\s*(\{.+?\});",
        r'"ytInitialPlayerResponse"\s*:\s*(\{.+?\})\s*,\s*"',
    ]

    for pattern in patterns:
        match = re.search(pattern, html_text or "", flags=re.DOTALL)

        if not match:
            continue

        try:
            return json.loads(match.group(1))
        except Exception:
            continue

    return {}


def build_social_video_prompt(recipe_url, page_text):
    return build_prompt(
        recipe_url,
        f"""
This content came from a social/video recipe URL.

Extract the recipe from the public title, caption, description, and transcript text below.
Ignore comments, hashtags, creator bio text, channel promotions, subscribe reminders, and unrelated social media text.

Social/video text:
{page_text}
""",
        additional_rules=social_video_estimation_rules(),
    )


def build_social_video_audio_image_prompt(recipe_url, page_text):
    return build_prompt(
        recipe_url,
        f"""
This content came from a social/video recipe URL.

Text-only extraction did not find a complete recipe. Use the available audio transcript, public title/description/caption text, and attached video images/thumbnails together.

Extract a practical recipe only when the audio or images support it.
- Use audio/transcript details for ingredient quantities and steps when present.
- Use images to identify visible ingredients, dish type, cookware, and cooking state.
- If YouTube metadata is vague, generic, clickbait, or incomplete, use the audio and images to produce the recipe fields a user can cook from.
- Ignore comments, hashtags, channel promotions, creator bio text, and unrelated social media text.
- If the media still does not contain enough recipe information, return ingredients as [].

Social/video text and audio transcript:
{page_text}
""",
        additional_rules=social_video_estimation_rules(),
    )


def social_video_estimation_rules():
    return """
========================
SOCIAL / VIDEO ESTIMATION OVERRIDE
========================
These override rules apply only because this source is a social/video recipe.
- If the video, transcript, caption, title, description, thumbnail, or attached frames support the recipe but exact metadata is missing, estimate reasonable values instead of leaving them null.
- Fill display_name with a short, card-friendly recipe name inferred from the dish. Avoid generic YouTube titles such as "new way to make..." when the video reveals the actual dish.
- Fill recipe_title with a clear recipe title inferred from the dish, ingredients, audio, and visuals. Use the public title only when it is already descriptive.
- Fill servings with the recipe amount, yield, portions, or best practical estimate, such as "4 servings", "6 portions", or "1 9-inch pan".
- Fill level with an estimated difficulty such as "Easy", "Intermediate", or "Advanced".
- Fill total_time, prep_time, inactive_time, and cook_time with practical estimates using units, such as "45 min", "1 hr 15 min", or "0 min".
- Use inactive_time for waiting, resting, chilling, cooling, or rising time when implied by the food or method. Use "0 min" when none is implied.
- For visible or clearly mentioned ingredients, estimate quantity and unit when the exact amount is not provided. Keep estimates practical for a home cook, and set base_quantity/base_unit to the same estimated values.
- Do not leave quantity blank for visible or clearly mentioned ingredients. If the video only shows the ingredient visually, choose a practical home-cook amount that matches the recipe amount.
- Use a concrete unit whenever possible, such as cups, tablespoons, teaspoons, ounces, pounds, cloves, slices, cans, packages, or each. Use null only when no practical unit applies.
- Mark optional true only for garnishes, toppings, substitutions, "to taste", "as desired", or clearly optional ingredients.
- If extracted instructions are missing, too terse, or only describe what is visible without enough cooking detail, create the likely missing steps needed to cook the recipe safely and clearly.
- Improve vague steps into useful cooking directions with inferred order, temperatures, times, pan/cookware cues, and doneness cues when supported by the audio, images, dish type, or common preparation.
- Keep instructions grounded in the video/audio evidence and the identified dish. Do not add unrelated steps or ingredients.
- Fill nutrition as an estimated per serving basis when nutrition is not provided. Set serving_basis to "per serving (estimated)" and fill common nutrition fields with values and units.
- Do not invent a recipe from unrelated media. If the source does not show or describe enough to identify the dish and core ingredients, return ingredients as [].
"""


def social_video_result_needs_audio_image_enrichment(json_data):
    if not isinstance(json_data, dict):
        return True

    for key in ("display_name", "recipe_title", "prep_time", "inactive_time"):
        if not clean_recipe_text(json_data.get(key) or ""):
            return True

    ingredients = json_data.get("ingredients", [])
    if isinstance(ingredients, list):
        for item in ingredients:
            if not isinstance(item, dict):
                continue

            if not clean_recipe_text(item.get("quantity") or ""):
                return True

            if not clean_recipe_text(item.get("unit") or ""):
                ingredient_name = clean_recipe_text(item.get("ingredient") or item.get("original_text") or "")
                preparation = clean_recipe_text(item.get("preparation") or "")
                if ingredient_name and "to taste" not in preparation.lower():
                    return True

    instructions = json_data.get("instructions", [])
    instruction_texts = [
        clean_recipe_text(item.get("instruction") if isinstance(item, dict) else item)
        for item in instructions
        if clean_recipe_text(item.get("instruction") if isinstance(item, dict) else item)
    ] if isinstance(instructions, list) else []

    if not instruction_texts:
        return True

    if len(instruction_texts) <= 2 and len(ingredients) >= 4:
        return True

    return any(len(text.split()) < 7 for text in instruction_texts)


def social_video_ingredient_amounts_need_prediction(json_data):
    if not isinstance(json_data, dict):
        return False

    ingredients = json_data.get("ingredients", [])
    if not isinstance(ingredients, list):
        return False

    for item in ingredients:
        if not isinstance(item, dict):
            continue

        ingredient_name = clean_recipe_text(item.get("ingredient") or item.get("original_text") or "")
        if not ingredient_name:
            continue

        preparation = clean_recipe_text(item.get("preparation") or "")
        if "to taste" in preparation.lower():
            continue

        if not clean_recipe_text(item.get("quantity") or ""):
            return True

    return False


def complete_social_video_recipe_with_openai_if_needed(
    recipe_url,
    json_data,
    page_text,
    image_urls,
    cover_image=None,
    progress_callback=None,
):
    if not social_video_ingredient_amounts_need_prediction(json_data):
        return json_data

    if not os.getenv("OPENAI_API_KEY"):
        return json_data

    if progress_callback:
        progress_callback(
            "estimating missing ingredient amounts...",
            "ChatGPT is using the video audio and images to fill blank ingredient quantities where practical.",
        )

    try:
        response_text = send_social_video_audio_image_prompt_to_openai(
            build_social_video_recipe_completion_prompt(recipe_url, page_text, json_data),
            image_urls,
        )
        raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_REPAIR_API_RESPONSE.txt"
        raw_api_path.write_text(response_text, encoding="utf-8")
        repaired_data = json.loads(clean_json_response(response_text))
    except Exception as exc:
        error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_REPAIR_API_ERROR.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        return json_data

    if not structured_recipe_data_is_usable(repaired_data):
        return json_data

    repaired_data["source_url"] = recipe_url
    if cover_image and not recipe_cover_image_from_data(repaired_data, base_url=recipe_url):
        repaired_data["cover_image"] = cover_image

    normalize_extracted_recipe_identity(repaired_data)
    normalize_extracted_ingredient_fields(repaired_data)
    normalize_extracted_equipment_fields(repaired_data)
    apply_recipe_info_metadata(repaired_data)
    apply_recipe_scaling_metadata(repaired_data)
    apply_recipe_cover_image_metadata(repaired_data, recipe_url=recipe_url)
    apply_recipe_owner_metadata(repaired_data)
    save_extracted_recipe_json(recipe_url, repaired_data)
    return repaired_data


def build_social_video_recipe_completion_prompt(recipe_url, page_text, json_data):
    current_recipe_json = json.dumps(json_data, ensure_ascii=False, indent=2)
    return build_prompt(
        recipe_url,
        f"""
This content came from a social/video recipe URL.

The current recipe JSON was extracted from the video's metadata, audio transcript, thumbnails, and frames, but some ingredient quantities are still blank.

Repair the current recipe JSON using the social/video text, audio transcript, and attached images.
- Return the full recipe JSON, not just the changed fields.
- Preserve existing ingredients, equipment, instructions, nutrition, and recipe metadata unless a field is blank or clearly incomplete.
- For every visible or clearly mentioned ingredient with a blank quantity, estimate a practical home-cook quantity and unit.
- Set quantity, unit, base_quantity, base_unit, and recipe_qty consistently for each repaired ingredient.
- If a whole-count ingredient needs no measurement unit, use quantity like "1", "2", or "8" and unit null.
- If an ingredient is optional, keep optional true and still estimate an amount when the video supports it.
- Preserve or include cover_image when present in the current JSON.

Current recipe JSON:
{current_recipe_json}

Social/video text and audio transcript:
{page_text}
""",
        additional_rules=social_video_estimation_rules(),
    )


def is_forbidden_response(exc):
    response = getattr(exc, "response", None)
    return response is not None and response.status_code == 403


def create_headless_chrome_driver(
    window_size="1365,900",
    prefer_undetected=True,
    page_load_strategy="eager",
    headless=True,
    user_data_dir=None,
):
    profile_path = None
    if user_data_dir:
        try:
            profile_path = Path(user_data_dir)
            profile_path.mkdir(parents=True, exist_ok=True)
        except Exception:
            profile_path = None

    if prefer_undetected:
        try:
            import undetected_chromedriver as uc

            options = uc.ChromeOptions()
            options.page_load_strategy = page_load_strategy
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument(f"--window-size={window_size}")
            if profile_path:
                options.add_argument(f"--user-data-dir={profile_path}")
                options.add_argument("--no-first-run")
                options.add_argument("--no-default-browser-check")
            if not headless:
                options.add_argument("--start-maximized")
            return uc.Chrome(options=options, use_subprocess=True)
        except Exception:
            pass

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.page_load_strategy = page_load_strategy
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--window-size={window_size}")
    if profile_path:
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
    if not headless:
        options.add_argument("--start-maximized")
    return webdriver.Chrome(options=options)


def wait_for_browser_document(driver, timeout_seconds=8):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            ready_state = driver.execute_script("return document.readyState")
            if ready_state == "complete":
                return
        except Exception:
            pass

        time.sleep(0.25)


def prepare_page_for_pdf_print(driver):
    wait_for_browser_document(driver, timeout_seconds=20)

    try:
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "screen"})
    except Exception:
        pass

    try:
        driver.execute_script(
            """
            const existing = document.getElementById("shopping-app-pdf-print-fix");
            if (!existing) {
                const style = document.createElement("style");
                style.id = "shopping-app-pdf-print-fix";
                style.textContent = arguments[0];
                document.head.appendChild(style);
            }

            for (const element of document.querySelectorAll("*")) {
                const position = window.getComputedStyle(element).position;
                if (position === "fixed" || position === "sticky") {
                    element.style.setProperty("position", "static", "important");
                    element.style.setProperty("top", "auto", "important");
                    element.style.setProperty("bottom", "auto", "important");
                    element.style.setProperty("transform", "none", "important");
                }
            }

            document.documentElement.style.setProperty("scroll-padding-top", "0", "important");
            document.body.style.setProperty("padding-top", "0", "important");
            window.scrollTo(0, 0);
            """,
            PDF_PRINT_FIX_CSS,
        )
        time.sleep(0.4)
    except Exception:
        pass

    promote_lazy_assets_in_browser(driver)
    wait_for_pdf_page_stability(driver)

    try:
        driver.execute_script("window.scrollTo(0, 0);")
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "print"})
        time.sleep(0.7)
    except Exception:
        pass


def promote_lazy_assets_in_browser(driver):
    try:
        driver.execute_script(
            """
            const imageAttrs = [
                "data-src",
                "data-lazy-src",
                "data-original",
                "data-pin-media",
                "data-orig-file"
            ];
            const srcsetAttrs = ["data-srcset", "data-lazy-srcset"];

            for (const img of document.querySelectorAll("img")) {
                for (const attr of imageAttrs) {
                    const value = img.getAttribute(attr);
                    if (value && (!img.getAttribute("src") || img.getAttribute("src").startsWith("data:"))) {
                        img.setAttribute("src", value);
                        break;
                    }
                }

                for (const attr of srcsetAttrs) {
                    const value = img.getAttribute(attr);
                    if (value && !img.getAttribute("srcset")) {
                        img.setAttribute("srcset", value);
                        break;
                    }
                }

                img.setAttribute("loading", "eager");
                img.setAttribute("decoding", "sync");
            }

            for (const source of document.querySelectorAll("source")) {
                const srcset = source.getAttribute("data-srcset") || source.getAttribute("data-lazy-srcset");
                if (srcset && !source.getAttribute("srcset")) {
                    source.setAttribute("srcset", srcset);
                }
            }
            """
        )
    except Exception:
        pass


def wait_for_pdf_page_stability(driver, timeout_seconds=25):
    try:
        driver.set_script_timeout(timeout_seconds + 5)
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            const timeoutMs = arguments[0] * 1000;
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
            const pageHeight = () => Math.max(
                document.body ? document.body.scrollHeight : 0,
                document.documentElement ? document.documentElement.scrollHeight : 0
            );

            (async () => {
                const start = Date.now();
                let lastHeight = 0;
                let stableCount = 0;

                while (Date.now() - start < timeoutMs) {
                    const height = pageHeight();
                    const step = Math.max(320, Math.floor(window.innerHeight * 0.75));

                    for (let y = 0; y <= height; y += step) {
                        window.scrollTo(0, y);
                        await sleep(180);
                    }

                    if (document.fonts && document.fonts.ready) {
                        await Promise.race([document.fonts.ready, sleep(2500)]);
                    }

                    const images = Array.from(document.images || []);
                    await Promise.race([
                        Promise.all(images.map((img) => {
                            if (img.complete) {
                                return Promise.resolve();
                            }

                            return new Promise((resolve) => {
                                img.addEventListener("load", resolve, { once: true });
                                img.addEventListener("error", resolve, { once: true });
                            });
                        })),
                        sleep(5000)
                    ]);

                    const nextHeight = pageHeight();
                    if (Math.abs(nextHeight - lastHeight) < 8) {
                        stableCount += 1;
                    } else {
                        stableCount = 0;
                    }

                    lastHeight = nextHeight;

                    if (stableCount >= 1) {
                        break;
                    }

                    await sleep(350);
                }

                window.scrollTo(0, 0);
                done({
                    height: pageHeight(),
                    images: (document.images || []).length,
                    readyState: document.readyState
                });
            })().catch((error) => done({ error: String(error) }));
            """,
            timeout_seconds,
        )
    except Exception as exc:
        print(f"PDF render wait skipped after timeout/error: {exc}")


def write_pdf_source_html(recipe_url, html_text):
    base_tag = f'<base href="{html.escape(str(recipe_url or ""), quote=True)}">'
    print_fix_tag = f'<style id="shopping-app-pdf-print-fix">{PDF_PRINT_FIX_CSS}</style>'
    source_html = sanitize_html_for_pdf_source(html_text)
    head_inserts = "\n".join([base_tag, print_fix_tag])

    if not re.search(r"<base\b", source_html, flags=re.IGNORECASE):
        if re.search(r"<head[^>]*>", source_html, flags=re.IGNORECASE):
            source_html = re.sub(
                r"(<head[^>]*>)",
                lambda match: f"{match.group(1)}\n{head_inserts}",
                source_html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            source_html = f"{head_inserts}\n{source_html}"
    elif "shopping-app-pdf-print-fix" not in source_html:
        if re.search(r"<head[^>]*>", source_html, flags=re.IGNORECASE):
            source_html = re.sub(
                r"(<head[^>]*>)",
                lambda match: f"{match.group(1)}\n{print_fix_tag}",
                source_html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            source_html = f"{print_fix_tag}\n{source_html}"

    source_path = LOG_FOLDER / f"{safe_filename(recipe_url)}_PDF_SOURCE.html"
    source_path.write_text(source_html, encoding="utf-8")
    return source_path


def sanitize_html_for_pdf_source(html_text):
    source_html = str(html_text or "")

    try:
        soup = BeautifulSoup(source_html, "html.parser")

        for tag in soup(["script", "iframe"]):
            tag.decompose()

        for tag in soup.find_all(True):
            for attr_name in list(tag.attrs):
                if str(attr_name).lower().startswith("on"):
                    del tag.attrs[attr_name]

        for img in soup.find_all("img"):
            promote_lazy_tag_attribute(
                img,
                "src",
                [
                    "data-src",
                    "data-lazy-src",
                    "data-original",
                    "data-pin-media",
                    "data-orig-file",
                ],
            )
            promote_lazy_tag_attribute(
                img,
                "srcset",
                [
                    "data-srcset",
                    "data-lazy-srcset",
                ],
            )
            img["loading"] = "eager"
            img["decoding"] = "sync"

        for source in soup.find_all("source"):
            promote_lazy_tag_attribute(
                source,
                "srcset",
                [
                    "data-srcset",
                    "data-lazy-srcset",
                ],
            )

        return str(soup)
    except Exception:
        return source_html


def promote_lazy_tag_attribute(tag, target_attr, source_attrs):
    current_value = str(tag.get(target_attr) or "").strip()

    if current_value and not current_value.startswith("data:"):
        return

    for source_attr in source_attrs:
        value = str(tag.get(source_attr) or "").strip()

        if value:
            tag[target_attr] = value
            return


def print_current_browser_page_to_pdf(driver, pdf_path):
    driver.execute_cdp_cmd("Page.enable", {})
    print_options = build_continuous_pdf_print_options(driver)
    pdf_bytes = b""
    page_count = None

    for attempt_number in range(1, 5):
        pdf_result = driver.execute_cdp_cmd(
            "Page.printToPDF",
            print_options,
        )
        pdf_bytes = base64.b64decode(pdf_result.get("data") or "")

        if len(pdf_bytes) < 1000:
            raise RuntimeError("Chrome returned an empty recipe PDF.")

        page_count = count_pdf_pages_from_bytes(pdf_bytes)
        if page_count is None or page_count <= 1:
            break

        if attempt_number == 4:
            break

        print_options = continuous_pdf_retry_options(print_options, page_count)
        print(
            "PDF continuous retry: "
            f"pages={page_count} "
            f"height={print_options['paperHeight']:.2f}in "
            f"scale={print_options['scale']:.2f}"
        )

    pdf_path.write_bytes(pdf_bytes)

    if page_count and page_count > 1:
        print(f"PDF continuous warning: saved {page_count} pages after retry limit.")


def count_pdf_pages_from_bytes(pdf_bytes):
    try:
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return None


def continuous_pdf_retry_options(print_options, page_count):
    next_options = dict(print_options)
    current_height = max(float(next_options.get("paperHeight") or 11), 11)
    current_scale = max(float(next_options.get("scale") or PDF_BASE_SCALE), PDF_MIN_CONTINUOUS_SCALE)
    needed_height = current_height * max(page_count, 1)

    if needed_height <= PDF_MAX_CONTINUOUS_HEIGHT_IN:
        next_options["paperHeight"] = min(PDF_MAX_CONTINUOUS_HEIGHT_IN, needed_height + 0.5)
        return next_options

    scale_ratio = PDF_MAX_CONTINUOUS_HEIGHT_IN / needed_height
    next_options["paperHeight"] = PDF_MAX_CONTINUOUS_HEIGHT_IN
    next_options["scale"] = max(
        PDF_MIN_CONTINUOUS_SCALE,
        min(PDF_BASE_SCALE, current_scale * scale_ratio * 0.98),
    )
    return next_options


def build_continuous_pdf_print_options(driver):
    metrics = measure_pdf_document(driver)
    content_height_in = max(metrics.get("height_px", 0), 1) / 96
    vertical_margins = PDF_MARGIN_TOP_IN + PDF_MARGIN_BOTTOM_IN
    scale = PDF_BASE_SCALE
    page_height = (content_height_in * scale) + vertical_margins + 0.25

    if page_height > PDF_MAX_CONTINUOUS_HEIGHT_IN:
        available_height = max(PDF_MAX_CONTINUOUS_HEIGHT_IN - vertical_margins - 0.25, 1)
        scale = max(
            PDF_MIN_CONTINUOUS_SCALE,
            min(PDF_BASE_SCALE, available_height / content_height_in),
        )
        page_height = min(
            PDF_MAX_CONTINUOUS_HEIGHT_IN,
            (content_height_in * scale) + vertical_margins + 0.25,
        )

    page_height = max(11, page_height)
    print(f"PDF continuous page: height={page_height:.2f}in scale={scale:.2f}")

    return {
        "printBackground": True,
        "displayHeaderFooter": False,
        "preferCSSPageSize": False,
        "paperWidth": PDF_PAPER_WIDTH_IN,
        "paperHeight": page_height,
        "marginTop": PDF_MARGIN_TOP_IN,
        "marginBottom": PDF_MARGIN_BOTTOM_IN,
        "marginLeft": PDF_MARGIN_LEFT_IN,
        "marginRight": PDF_MARGIN_RIGHT_IN,
        "scale": scale,
    }


def measure_pdf_document(driver):
    try:
        metrics = driver.execute_script(
            """
            const body = document.body || {};
            const doc = document.documentElement || {};
            const height = Math.max(
                body.scrollHeight || 0,
                body.offsetHeight || 0,
                doc.clientHeight || 0,
                doc.scrollHeight || 0,
                doc.offsetHeight || 0
            );
            const width = Math.max(
                body.scrollWidth || 0,
                body.offsetWidth || 0,
                doc.clientWidth || 0,
                doc.scrollWidth || 0,
                doc.offsetWidth || 0
            );
            return { height_px: height, width_px: width };
            """
        )
    except Exception:
        return {"height_px": 11 * 96, "width_px": PDF_PAPER_WIDTH_IN * 96}

    return metrics if isinstance(metrics, dict) else {"height_px": 11 * 96, "width_px": PDF_PAPER_WIDTH_IN * 96}


def write_recipe_page_pdf(recipe_url, html_text, html_path, pdf_path):
    driver = None
    last_error = None
    source_path = None

    try:
        driver = create_headless_chrome_driver(
            window_size="1365,1400",
            prefer_undetected=False,
            page_load_strategy="normal",
        )
        driver.set_page_load_timeout(45)

        html_text = html_text or (
            html_path.read_text(encoding="utf-8") if html_path and html_path.exists() else ""
        )
        print_targets = []

        if html_text:
            source_path = write_pdf_source_html(recipe_url, html_text)
            print_targets.append(source_path.resolve().as_uri())
        elif str(recipe_url or "").lower().startswith(("http://", "https://")):
            print_targets.append(recipe_url)

        if not print_targets:
            raise RuntimeError("No recipe HTML was available to print.")

        for target in print_targets:
            try:
                try:
                    driver.get(target)
                except Exception:
                    if len(driver.page_source or "") < 1000:
                        raise

                    print("PDF page load timed out after partial load; printing current page.")

                prepare_page_for_pdf_print(driver)
                print_current_browser_page_to_pdf(driver, pdf_path)
                remove_temporary_pdf_source(source_path)
                return pdf_path
            except PermissionError:
                raise
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"Could not print recipe PDF: {last_error}") from last_error
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def remove_temporary_pdf_source(source_path):
    if not source_path:
        return

    try:
        source_path.unlink(missing_ok=True)
    except Exception:
        pass


def archive_recipe_page_pdf(recipe_url, html_text, html_path, progress_callback=None):
    if os.getenv("DISABLE_RECIPE_PDF_ARCHIVE") == "1":
        return None

    pdf_path = recipe_archive_pdf_path(recipe_url)

    if progress_callback:
        progress_callback(
            "saving recipe page PDF archive...",
            "Converting the downloaded webpage into a PDF for long-term review.",
        )

    try:
        saved_path = write_recipe_page_pdf(recipe_url, html_text, html_path, pdf_path)
        print(f"Saved recipe PDF archive: {saved_path}")
        return saved_path
    except Exception as exc:
        error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PDF_ERROR.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        print(f"Recipe PDF archive failed: {exc}")

        if progress_callback:
            progress_callback(
                "PDF archive failed - continuing ingredient extraction...",
                "Ingredients can still be extracted; the PDF error was saved with the raw extraction files.",
            )

    return None


def archive_uploaded_recipe_pdf(recipe_url, upload_path, mime_type, filename, page_text="", recipe_title=""):
    if os.getenv("DISABLE_RECIPE_PDF_ARCHIVE") == "1":
        return None

    pdf_path = recipe_archive_pdf_path(recipe_url)
    suffix = upload_file_suffix(filename, upload_path)

    try:
        if mime_type == "application/pdf" or suffix == ".pdf":
            shutil.copyfile(upload_path, pdf_path)
            print(f"Saved uploaded recipe PDF archive: {pdf_path}")
            return pdf_path

        if mime_type.startswith("image/"):
            html_text = build_upload_image_pdf_html(upload_path, mime_type, filename, recipe_title)
        elif suffix in {".html", ".htm"}:
            html_text = upload_path.read_text(encoding="utf-8", errors="ignore")
        else:
            text = page_text or extract_text_from_generic_document(upload_path, filename)
            if not text.strip():
                return None
            html_text = build_upload_text_pdf_html(text, filename, recipe_title)

        saved_path = write_recipe_page_pdf(recipe_url, html_text, None, pdf_path)
        print(f"Saved uploaded recipe PDF archive: {saved_path}")
        return saved_path
    except Exception as exc:
        error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PDF_ERROR.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        print(f"Uploaded recipe PDF archive failed: {exc}")

    return None


def archive_social_video_text_pdf(
    recipe_url,
    page_text,
    structured_recipe_data=None,
    prefer_openai=False,
    progress_callback=None,
):
    if os.getenv("DISABLE_RECIPE_PDF_ARCHIVE") == "1":
        return None

    page_text = str(page_text or "").strip()

    if not page_text:
        return None

    pdf_path = recipe_archive_pdf_path(recipe_url)

    if progress_callback:
        progress_callback(
            "saving video recipe PDF archive...",
            "Creating a recipe-style PDF from the video caption, transcript, or audio transcription text.",
        )

    try:
        title = extract_social_text_label(page_text, "title") or "Video Recipe Text"
        recipe_data = build_video_pdf_recipe_data(
            recipe_url,
            page_text,
            structured_recipe_data=structured_recipe_data,
            prefer_openai=prefer_openai,
            progress_callback=progress_callback,
        )
        html_text = build_video_text_pdf_html(
            recipe_url,
            page_text,
            title,
            recipe_data=recipe_data,
        )
        saved_path = write_recipe_page_pdf(recipe_url, html_text, None, pdf_path)
        print(f"Saved video recipe PDF archive: {saved_path}")
        return saved_path
    except Exception as exc:
        error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PDF_ERROR.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        print(f"Video recipe PDF archive failed: {exc}")

        if progress_callback:
            progress_callback(
                "video PDF archive failed - continuing ingredient extraction...",
                "Ingredients can still be extracted; the video PDF error was saved with the raw extraction files.",
            )

    return None


def build_video_pdf_recipe_data(
    recipe_url,
    page_text,
    structured_recipe_data=None,
    prefer_openai=False,
    progress_callback=None,
):
    if prefer_openai and os.getenv("OPENAI_API_KEY"):
        api_data = extract_video_recipe_pdf_data_with_openai(
            recipe_url,
            page_text,
            progress_callback=progress_callback,
        )

        if recipe_data_has_pdf_content(api_data):
            return api_data

    if recipe_data_has_pdf_content(structured_recipe_data):
        normalize_extracted_ingredient_fields(structured_recipe_data)
        normalize_extracted_equipment_fields(structured_recipe_data)
        return structured_recipe_data

    local_data = extract_recipe_from_social_video_text(recipe_url, page_text)

    if recipe_data_has_pdf_content(local_data):
        return local_data

    if os.getenv("OPENAI_API_KEY"):
        api_data = extract_video_recipe_pdf_data_with_openai(
            recipe_url,
            page_text,
            progress_callback=progress_callback,
        )

        if recipe_data_has_pdf_content(api_data):
            return api_data

    return structured_recipe_data if isinstance(structured_recipe_data, dict) else None


def extract_video_recipe_pdf_data_with_openai(recipe_url, page_text, progress_callback=None):
    if progress_callback:
        progress_callback(
            "formatting video recipe PDF with OpenAI...",
            "ChatGPT is turning the video text into recipe sections for the PDF.",
        )

    try:
        response_text = send_video_recipe_pdf_prompt_to_openai(
            build_video_recipe_pdf_prompt(
                recipe_url,
                page_text[:MAX_SOCIAL_VIDEO_PROMPT_CHARS],
            )
        )
        raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_PDF_API_RESPONSE.txt"
        raw_api_path.write_text(response_text, encoding="utf-8")

        json_data = json.loads(clean_json_response(response_text))
        json_data["source_url"] = recipe_url
        normalize_extracted_recipe_identity(json_data)
        normalize_extracted_ingredient_fields(json_data)
        normalize_extracted_equipment_fields(json_data)
        return json_data
    except Exception as exc:
        error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_SOCIAL_PDF_API_ERROR.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
        final_error_code, final_error_message = classify_vision_ai_exception(exc)
        print(
            "[OpenAI] action=video-recipe-pdf-extraction "
            f"model={MODEL} exception_type={type(exc).__name__} "
            f"openai_error_code={openai_error_code or 'n/a'} "
            f"openai_error_param={openai_error_param or 'n/a'} "
            f"final_error_code={final_error_code} "
            f"final_error_message={final_error_message}"
        )
        print(f"Video recipe PDF OpenAI formatting failed: {exc}")

    return None


def send_video_recipe_pdf_prompt_to_openai(prompt_text):
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        MODEL,
        "video-recipe-pdf-extraction",
        [
            {
                "role": "system",
                "content": (
                    "You turn social/video cooking text into structured recipe JSON "
                    "with ingredients, equipment, and instructions. Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action=video-recipe-pdf-extraction "
        f"model={resolved_model} temperature_included={temperature_included}"
    )
    response = get_openai_client().chat.completions.create(**payload)
    record_openai_usage(response, "video-recipe-pdf-extraction", model=MODEL)

    return response.choices[0].message.content


def build_video_recipe_pdf_prompt(recipe_url, page_text):
    return build_prompt(
        recipe_url,
        f"""
This content came from a social/video recipe URL.

Create a clean recipe export from the public title, caption, description, and transcript text below.
The PDF will be built from your JSON, so prioritize complete recipe sections:
- display_name
- recipe_title
- servings / recipe amount
- level
- total_time
- prep_time
- inactive_time
- cook_time
- ingredients with quantity, unit, ingredient, and preparation split out
- equipment inferred from the recipe actions
- ordered instructions with temperatures, times, and equipment_used when present
- nutrition as an estimated per serving basis when exact nutrition is not provided

If the video text mentions an ingredient quantity in spoken instructions instead of a formal ingredient list, extract that quantity.
Ignore comments, hashtags, creator bio text, channel promotions, subscribe reminders, and unrelated social media text.

Social/video text:
{page_text}
""",
        additional_rules=social_video_estimation_rules(),
    )


def recipe_data_has_pdf_content(recipe_data):
    if not isinstance(recipe_data, dict):
        return False

    return any(
        isinstance(recipe_data.get(key), list) and bool(recipe_data.get(key))
        for key in ("ingredients", "equipment", "instructions")
    )


def build_video_text_pdf_html(recipe_url, page_text, recipe_title="", recipe_data=None):
    title_value = video_recipe_pdf_title(recipe_data, recipe_title)
    title = html.escape(title_value)
    source_url = html.escape(str(recipe_url or ""))
    body_html = format_video_recipe_data_for_pdf(recipe_data)
    title_image_html = format_video_recipe_title_image_for_pdf(recipe_data)

    if not body_html:
        body_html = format_labeled_text_for_pdf(page_text)

    return f"""
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            padding: 32px;
            font-family: Arial, sans-serif;
            color: #111;
            background: #fff;
            line-height: 1.42;
        }}
        h1 {{
            margin: 0 0 6px 0;
            font-size: 28px;
            line-height: 1.15;
        }}
        .source {{
            margin: 0 0 22px 0;
            color: #555;
            font-size: 12px;
            overflow-wrap: anywhere;
        }}
        .title-image {{
            margin: 0 0 22px 0;
            page-break-inside: avoid;
        }}
        .title-image img {{
            display: block;
            width: 100%;
            max-height: 320px;
            object-fit: cover;
            border-radius: 8px;
        }}
        h2 {{
            border-bottom: 1px solid #ddd;
            margin: 24px 0 10px 0;
            padding-bottom: 5px;
            font-size: 18px;
        }}
        h3 {{
            margin: 14px 0 6px 0;
            font-size: 14px;
            color: #333;
        }}
        .meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 0 0 18px 0;
        }}
        .meta span {{
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 12px;
            color: #333;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        th,
        td {{
            border-bottom: 1px solid #e4e4e4;
            padding: 7px 8px;
            text-align: left;
            vertical-align: top;
        }}
        th {{
            background: #f3f3f3;
            color: #333;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .amount-cell {{
            width: 22%;
            white-space: nowrap;
        }}
        .section-row td {{
            background: #fafafa;
            color: #333;
            font-weight: 700;
            padding-top: 10px;
        }}
        ul,
        ol {{
            margin: 0;
            padding-left: 24px;
        }}
        li {{
            margin: 0 0 8px 0;
        }}
        .equipment-list {{
            padding-left: 20px;
        }}
        .equipment-category,
        .step-meta {{
            color: #666;
            font-size: 12px;
        }}
        pre {{
            margin: 0;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font: inherit;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="source">Source: {source_url}</div>
    {title_image_html}
    {body_html}
</body>
</html>
"""


def video_recipe_pdf_title(recipe_data, fallback_title=""):
    if isinstance(recipe_data, dict):
        title = clean_recipe_text(recipe_data.get("recipe_title") or "")

        if title:
            return title

    return fallback_title or "Video Recipe"


def format_video_recipe_title_image_for_pdf(recipe_data):
    if not isinstance(recipe_data, dict):
        return ""

    cover_image = recipe_data.get("cover_image") or {}

    if not isinstance(cover_image, dict) or not cover_image:
        return ""

    src = recipe_pdf_cover_image_src(cover_image)

    if not src:
        return ""

    alt = clean_cover_image_text(
        cover_image.get("alt")
        or recipe_data.get("recipe_title")
        or "Recipe title image"
    )

    return (
        "<figure class=\"title-image\">"
        f"<img src=\"{html.escape(src, quote=True)}\" alt=\"{html.escape(alt, quote=True)}\">"
        "</figure>"
    )


def recipe_pdf_cover_image_src(cover_image):
    if not isinstance(cover_image, dict):
        return ""

    image_path = recipe_cover_image_file_path(cover_image)

    if image_path:
        mime_type = (
            clean_cover_image_text(cover_image.get("mime_type"))
            or mimetypes.guess_type(str(image_path))[0]
            or "image/jpeg"
        )

        try:
            image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        except OSError:
            image_data = ""

        if image_data:
            return f"data:{mime_type};base64,{image_data}"

    for key in ("src", "url"):
        value = clean_cover_image_text(cover_image.get(key))

        if not value or value.startswith("/"):
            continue

        if value.startswith("data:image/") or cover_image_url_looks_usable(value):
            return value

    return ""


def format_video_recipe_data_for_pdf(recipe_data):
    if not recipe_data_has_pdf_content(recipe_data):
        return ""

    sections = []
    meta_html = format_video_recipe_meta_for_pdf(recipe_data)

    if meta_html:
        sections.append(meta_html)

    ingredients_html = format_video_recipe_ingredients_for_pdf(recipe_data.get("ingredients", []))

    if ingredients_html:
        sections.append(f"<h2>Ingredients</h2>{ingredients_html}")

    equipment_html = format_video_recipe_equipment_for_pdf(recipe_data.get("equipment", []))

    if equipment_html:
        sections.append(f"<h2>Equipment</h2>{equipment_html}")

    instructions_html = format_video_recipe_instructions_for_pdf(recipe_data.get("instructions", []))

    if instructions_html:
        sections.append(f"<h2>Instructions</h2>{instructions_html}")

    nutrition_html = format_video_recipe_nutrition_for_pdf(recipe_data.get("nutrition"))

    if nutrition_html:
        sections.append(f"<h2>Nutrition</h2>{nutrition_html}")

    return "\n".join(sections)


def format_video_recipe_meta_for_pdf(recipe_data):
    items = []
    fields = [
        ("servings", "Recipe Amount"),
        ("level", "Level"),
        ("total_time", "Total"),
        ("prep_time", "Prep"),
        ("inactive_time", "Inactive"),
        ("cook_time", "Cook"),
    ]

    for key, label in fields:
        value = clean_recipe_text(recipe_data.get(key) or "")

        if value:
            items.append(f"<span>{html.escape(label)}: {html.escape(value)}</span>")

    return f"<div class=\"meta\">{''.join(items)}</div>" if items else ""


def format_video_recipe_ingredients_for_pdf(ingredients):
    if not isinstance(ingredients, list) or not ingredients:
        return ""

    rows = []
    current_section = None

    for item in ingredients:
        if not isinstance(item, dict):
            value = clean_recipe_text(item)
            if value:
                rows.append(
                    "<tr>"
                    "<td class=\"amount-cell\"></td>"
                    f"<td>{html.escape(value)}</td>"
                    "<td></td>"
                    "</tr>"
                )
            continue

        section = clean_recipe_text(item.get("section") or "")

        if section and section != current_section:
            rows.append(
                "<tr class=\"section-row\">"
                f"<td colspan=\"3\">{html.escape(section)}</td>"
                "</tr>"
            )
            current_section = section

        amount = format_video_ingredient_amount(item)
        ingredient = clean_recipe_text(item.get("ingredient") or item.get("original_text") or "")
        preparation = clean_recipe_text(item.get("preparation") or "")

        if item.get("optional") and preparation:
            preparation = f"{preparation}; optional"
        elif item.get("optional"):
            preparation = "optional"

        if not ingredient and not amount and not preparation:
            continue

        rows.append(
            "<tr>"
            f"<td class=\"amount-cell\">{html.escape(amount)}</td>"
            f"<td>{html.escape(ingredient)}</td>"
            f"<td>{html.escape(preparation)}</td>"
            "</tr>"
        )

    if not rows:
        return ""

    return (
        "<table>"
        "<thead><tr><th>Amount</th><th>Ingredient</th><th>Prep</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def format_video_ingredient_amount(item):
    quantity = clean_recipe_text(item.get("quantity") or "")
    unit = clean_recipe_text(item.get("unit") or "")

    if quantity and unit:
        return f"{quantity} {unit}"

    return quantity or unit


def format_video_recipe_equipment_for_pdf(equipment):
    if not isinstance(equipment, list) or not equipment:
        return ""

    items = []
    seen = set()

    for item in equipment:
        if isinstance(item, dict):
            name = clean_recipe_text(item.get("name") or "")
            category = clean_recipe_text(item.get("category") or "")
        else:
            name = clean_recipe_text(item)
            category = ""

        key = name.lower()

        if not name or key in seen:
            continue

        seen.add(key)
        category_html = (
            f" <span class=\"equipment-category\">({html.escape(category)})</span>"
            if category
            else ""
        )
        items.append(f"<li>{html.escape(name)}{category_html}</li>")

    return f"<ul class=\"equipment-list\">{''.join(items)}</ul>" if items else ""


def format_video_recipe_instructions_for_pdf(instructions):
    if not isinstance(instructions, list) or not instructions:
        return ""

    parts = []
    items = []
    current_section = None

    for fallback_number, item in enumerate(instructions, start=1):
        if isinstance(item, dict):
            section = clean_recipe_text(item.get("section") or "")
            instruction = clean_recipe_text(item.get("instruction") or "")
            metadata = format_video_instruction_metadata(item)
        else:
            section = ""
            instruction = clean_recipe_text(item)
            metadata = ""

        if not instruction:
            continue

        if section and section != current_section:
            if items:
                parts.append(f"<ol>{''.join(items)}</ol>")
                items = []
            parts.append(f"<h3>{html.escape(section)}</h3>")
            current_section = section

        items.append(
            "<li>"
            f"{html.escape(instruction)}"
            f"{metadata}"
            "</li>"
        )

    if items:
        parts.append(f"<ol>{''.join(items)}</ol>")

    return "\n".join(parts)


def format_video_instruction_metadata(item):
    values = []
    temperature = clean_recipe_text(item.get("temperature") or "")
    time_value = clean_recipe_text(item.get("time") or "")
    equipment_used = item.get("equipment_used") or []

    if temperature:
        values.append(f"Temp: {temperature}")

    if time_value:
        values.append(f"Time: {time_value}")

    if isinstance(equipment_used, list):
        equipment_text = ", ".join(
            clean_recipe_text(value)
            for value in equipment_used
            if clean_recipe_text(value)
        )

        if equipment_text:
            values.append(f"Uses: {equipment_text}")

    if not values:
        return ""

    return f"<div class=\"step-meta\">{' | '.join(html.escape(value) for value in values)}</div>"


def format_video_recipe_nutrition_for_pdf(nutrition):
    if not isinstance(nutrition, dict):
        return ""

    labels = [
        ("serving_basis", "Serving basis"),
        ("calories", "Calories"),
        ("carbohydrates", "Carbohydrates"),
        ("protein", "Protein"),
        ("fat", "Fat"),
        ("saturated_fat", "Saturated fat"),
        ("fiber", "Fiber"),
        ("sugar", "Sugar"),
        ("sodium", "Sodium"),
    ]
    rows = []

    for key, label in labels:
        value = clean_recipe_text(nutrition.get(key) or "")

        if value:
            rows.append(
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f"<td>{html.escape(value)}</td>"
                "</tr>"
            )

    other = nutrition.get("other") or []

    if isinstance(other, list):
        for item in other:
            if not isinstance(item, dict):
                continue

            name = clean_recipe_text(item.get("name") or "")
            value = clean_recipe_text(item.get("value") or "")

            if name and value:
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(name)}</td>"
                    f"<td>{html.escape(value)}</td>"
                    "</tr>"
                )

    if not rows:
        return ""

    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def format_labeled_text_for_pdf(page_text):
    sections = split_labeled_social_text(page_text)

    if not sections:
        return f"<pre>{html.escape(str(page_text or '').strip())}</pre>"

    return "\n".join(
        f"<h2>{html.escape(label)}</h2><pre>{html.escape(text)}</pre>"
        for label, text in sections
        if text
    )


def split_labeled_social_text(page_text):
    pattern = r"(?ims)^\s*(title|description|transcript|visible text):\s*(.*?)(?=^\s*(?:title|description|transcript|visible text):|\Z)"
    sections = []

    for match in re.finditer(pattern, str(page_text or "")):
        label = clean_recipe_text(match.group(1)).title()
        text = clean_recipe_text(match.group(2))

        if text:
            sections.append((label, text))

    return sections


def build_upload_image_pdf_html(upload_path, mime_type, filename, recipe_title=""):
    image_data = base64.b64encode(upload_path.read_bytes()).decode("ascii")
    title = html.escape(recipe_title or filename or "Uploaded Recipe")

    return f"""
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            padding: 24px;
            font-family: Arial, sans-serif;
            color: #111;
            background: #fff;
        }}
        h1 {{
            margin: 0 0 16px 0;
            font-size: 22px;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <img src="data:{html.escape(mime_type)};base64,{image_data}" alt="{title}">
</body>
</html>
"""


def build_upload_text_pdf_html(page_text, filename, recipe_title=""):
    title = html.escape(recipe_title or filename or "Uploaded Recipe")
    text = html.escape(str(page_text or "").strip())

    return f"""
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            padding: 32px;
            font-family: Arial, sans-serif;
            color: #111;
            background: #fff;
            line-height: 1.45;
        }}
        h1 {{
            margin: 0 0 18px 0;
            font-size: 24px;
        }}
        pre {{
            margin: 0;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            font: inherit;
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <pre>{text}</pre>
</body>
</html>
"""


def fetch_recipe_page_with_browser(recipe_url):
    driver = None

    try:
        driver = create_headless_chrome_driver()
        driver.set_page_load_timeout(18)

        try:
            driver.get(recipe_url)
        except Exception:
            html_text = driver.page_source or ""

            if len(html_text) > 1000:
                print("Browser fetch timed out after partial page load; using current HTML.")
                return html_text

            raise

        return driver.page_source or ""
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def fetch_recipe_page_text(recipe_url):
    _, page_text = fetch_recipe_page(recipe_url)
    return page_text


# =========================================================
# PROMPT
# =========================================================
def build_prompt(recipe_url, page_text, additional_rules=""):
    additional_rules_text = str(additional_rules or "").strip()
    additional_rules_block = f"\n{additional_rules_text}\n" if additional_rules_text else ""

    return f"""
Extract the recipe information from this web page:

{recipe_url}

WEBPAGE TEXT:
{page_text}

Return ONLY valid JSON.

STRICT RULES:
- Do not include markdown.
- Do not include explanations.
- The final response must be valid JSON parsable by Python json.loads().
- Do not use trailing commas.
- Do not use smart quotes.
- Do not use comments.
- All string values must be wrapped in double quotes.
- Arrays and objects must have commas between every item.
- Use null if a value is missing or unknown.
- Preserve wording from the recipe when possible.
- Escape all newline characters inside JSON strings as \\n.
- Do NOT include raw line breaks inside JSON string values. Replace them with spaces.

========================
INGREDIENT RULES
========================
- ALWAYS split ingredients into: quantity, unit, ingredient, preparation.
- quantity and unit should only be null when truly absent from the recipe text.
- Preserve original_text exactly.
- Before returning JSON, re-read every original_text and verify quantity, unit, ingredient, and preparation are split correctly.
- If original_text starts with a number, fraction, mixed fraction, or range, quantity must not be null.
- If original_text has a measurement word immediately after the quantity, unit must not be null.
- If original_text has text after a comma or a non-metric parenthetical such as "(melted)", "(chopped)", "(divided)", or "(room temperature)", preparation must not be null.
- The ingredient field must be the unique grocery item name only.
- Do NOT include quantity, unit, package size, metric conversion, or preparation in the ingredient field.
- Do NOT include words like "divided", "chopped", "melted", "shredded", "to taste", "as desired", "for garnish", or "optional" in the ingredient field.
- Put preparation words in preparation.
- If an ingredient is optional, set optional = true.
- "pinch" and "pinches" are measurement units. Put them in unit, not ingredient.

- Preserve recipe usage modifiers in preparation:
  - "divided"
  - "room temperature"
  - "softened"
  - "cold"
  - "drained"
  - "rinsed"
  - "to taste"
  - "as desired"
  - "for garnish"

INGREDIENT CONFIDENCE RULES:
- Only extract ingredients that are explicitly present in the recipe.
- Do NOT infer missing ingredients from general cooking knowledge.
- Do NOT add water, oil, salt, or pepper unless explicitly mentioned.
- If uncertain whether something is an ingredient or instruction text, exclude it.

IMPORTANT QUANTITY EXTRACTION RULES:
- ALWAYS attempt to extract quantity and unit.
- Do this for EVERY ingredient object, using original_text as the source of truth.
- If ingredient quantities appear anywhere in the page, including ingredient lists, instruction steps, notes, fillings, sauces, dough sections, headings, or recipe cards, extract them.
- NEVER discard quantities when they are present.
- Preserve fractional values exactly as strings.
- Preserve ranges exactly as strings.
- Preserve package sizes.
- Set base_quantity and base_unit to the ingredient quantity and unit at the recipe's default scale.
- If the page has recipe scale controls, base_quantity and base_unit should be the 1x/default quantities.

ALTERNATIVE INGREDIENT RULES:
- If one ingredient line gives a choice using "or", keep it as ONE ingredient object when the alternatives are substitutes for each other.
- Do NOT put the second alternative's quantity or unit inside the ingredient name.
- The ingredient field should contain only the alternative grocery item names joined by " OR ".
- If the alternatives have different quantities or units, put the complete quantity choices in quantity and set unit to null.
- Preserve the full original line in original_text.
- Assign the store_section for the best primary grocery placement.

Examples:
- "1 egg"
  -> quantity = "1"
  -> unit = null
  -> ingredient = "egg"

- "125 g all-purpose flour"
  -> quantity = "125"
  -> unit = "g"
  -> ingredient = "all-purpose flour"

- "4 Tablespoons unsalted butter, melted"
  -> quantity = "4"
  -> unit = "Tablespoons"
  -> ingredient = "unsalted butter"
  -> preparation = "melted"

- "1 teaspoon vanilla extract"
  -> quantity = "1"
  -> unit = "teaspoon"
  -> ingredient = "vanilla extract"

- "salt and pepper to taste"
  -> quantity = null
  -> unit = null
  -> ingredient = "salt"
  -> preparation = "to taste"

- "Pinch ground nutmeg"
  -> quantity = "1"
  -> unit = "Pinch"
  -> ingredient = "ground nutmeg"
  -> preparation = null

- "Salt and pepper to taste (as desired)"
  -> quantity = null
  -> unit = null
  -> ingredient = "Salt and pepper"
  -> preparation = "to taste, as desired"

- "Parmesan and/or basil, for garnish"
  -> quantity = null
  -> unit = null
  -> ingredient = "Parmesan and/or basil"
  -> preparation = "for garnish"

- "Homemade Tomato Sauce, or sauce as desired, for serving"
  -> quantity = null
  -> unit = null
  -> ingredient = "Homemade Tomato Sauce"
  -> preparation = "or sauce as desired, for serving"

- "2 ounces cocoa butter or 1/4 cup vegetable oil"
  -> quantity = "2 ounces OR 1/4 cup"
  -> unit = null
  -> ingredient = "cocoa butter OR vegetable oil"
  -> preparation = null

- "1 cup butter or coconut oil, melted"
  -> quantity = "1"
  -> unit = "cup"
  -> ingredient = "butter OR coconut oil"
  -> preparation = "melted"

- If the webpage only contains instructions and no formal ingredient list:
  - infer ingredients from cooking steps
  - still extract quantities whenever they appear in the instructions

- If the same grocery item appears more than once because the page lists both US and metric measurements, keep only one ingredient object for that grocery item.
- Assign store_section and store_section_order.
- Use the grocery section that best matches the ingredient's real grocery store placement.
- Do NOT add ingredients that are not in the recipe.
- Combine duplicate ingredients when they clearly refer to the same grocery item.
- Keep the most complete quantity and preparation information.
- Do NOT create separate entries for metric conversions of the same ingredient.

- Convert unicode fractions into standard fraction strings:
  - "½" -> "1/2"
  - "¼" -> "1/4"
  - "¾" -> "3/4"

- Preserve mixed fractions exactly:
  - "1 1/2"
  - "2 3/4"

- Preserve quantity ranges exactly:
  - "2-4"
  - "3 to 5"

- If multiple units are shown for the same ingredient:
  - prefer the primary US measurement
  - ignore duplicate metric conversions when they refer to the same ingredient

FINAL INGREDIENT VALIDATION CHECK:
- For every item in ingredients:
  - Check original_text again.
  - If original_text = "1 egg", output quantity "1", unit null, ingredient "egg".
  - If original_text = "¼ cup plain yogurt", output quantity "1/4", unit "cup", ingredient "plain yogurt".
  - If original_text = "4 Tablespoons unsalted butter, melted", output quantity "4", unit "Tablespoons", ingredient "unsalted butter", preparation "melted".
  - If original_text = "4 Tablespoons unsalted butter (melted)", output quantity "4", unit "Tablespoons", ingredient "unsalted butter", preparation "melted".
  - If original_text = "2 ounces cocoa butter or 1/4 cup vegetable oil", output quantity "2 ounces OR 1/4 cup", unit null, ingredient "cocoa butter OR vegetable oil".
  - If any of these fields can be read from original_text, do not leave them null.

NORMALIZATION RULES:
- Singularize grocery ingredient names when appropriate.
  - "eggs" -> "egg"
  - "lemons" -> "lemon"
  - "limes" -> "lime"
  - "onions" -> "onion"
  - "tomatoes" -> "tomato"
  - "potatoes" -> "potato"
  - "carrots" -> "carrot"
- Apply singularization before duplicate detection so singular and plural forms do not both appear.

- Preserve branded or compound ingredient names exactly:
  - "cream of mushroom soup"
  - "soy sauce"
  - "olive oil"

- Do NOT over-normalize ingredient names.

CLASSIFICATION GUIDANCE:
- Eggs, milk, butter, yogurt, cream, cheese, and sour cream go in DAIRY & EGGS.
- Flour, sugar, brown sugar, powdered sugar, baking powder, baking soda, cocoa powder, chocolate chips, vanilla extract, and yeast go in BAKING.
- Salt, kosher salt, sea salt, black pepper, cinnamon, paprika, cumin, chili powder, garlic powder, onion powder, oregano, thyme, basil, and spice blends go in SPICES & SEASONINGS.
- Olive oil, vegetable oil, avocado oil, sesame oil, coconut oil, cooking spray, and vinegars go in OILS & VINEGARS.
- Pasta, noodles, rice, oats, quinoa, breadcrumbs, stuffing mix, and grains go in PASTA, RICE & GRAINS.
- Ketchup, mustard, mayonnaise, salsa, soy sauce, hot sauce, barbecue sauce, salad dressing, and marinades go in SAUCES & CONDIMENTS.
- Bread, buns, tortillas, bagels, rolls, croissants, and pastries go in BAKERY.
- Chips, crackers, popcorn, pretzels, granola bars, and cookies go in SNACKS.
- Frozen vegetables, frozen fruit, ice cream, frozen pizza, and frozen meals go in FROZEN.
- Fresh fruits, vegetables, herbs, and refrigerated produce go in PRODUCE.

STORE SECTIONS:
PRODUCE, MEAT & SEAFOOD, DAIRY & EGGS, FROZEN, DRY GOODS, PASTA, RICE & GRAINS, BAKING, CANNED, SAUCES & CONDIMENTS, SNACKS, BEVERAGES, SPICES & SEASONINGS, OILS & VINEGARS, BAKERY, DELI, HOUSEHOLD, PERSONAL CARE, PET SUPPLIES, MISC

ORDER:
PRODUCE = 1
MEAT & SEAFOOD = 2
DAIRY & EGGS = 3
FROZEN = 4
DRY GOODS = 5
PASTA, RICE & GRAINS = 6
BAKING = 7
CANNED = 8
SAUCES & CONDIMENTS = 9
SNACKS = 10
BEVERAGES = 11
SPICES & SEASONINGS = 12
OILS & VINEGARS = 13
BAKERY = 14
DELI = 15
HOUSEHOLD = 16
PERSONAL CARE = 17
PET SUPPLIES = 18
MISC = 19

========================
EQUIPMENT RULES
========================
- Extract ALL equipment/tools required to complete the recipe.
- You MUST infer equipment from the instructions when not explicitly listed.
- Before returning JSON, re-read every instruction and verify equipment includes all tools implied by the steps.
- Do not leave equipment empty when the instructions mention baking, boiling, mixing, whisking, cutting, rolling, draining, or cooling.

- Common inference examples:
  - "preheat oven" = oven
  - "bake on a sheet pan" = baking sheet
  - "cook in a skillet" = skillet
  - "boil water" = pot
  - "mix in a bowl" = mixing bowl
  - "whisk together" = whisk
  - "cut/chop" = knife, cutting board

- Include cooking tools, prep tools, cookware, and appliances.
- Use simple lowercase names.
- Remove duplicates.
- Do NOT include ingredients as equipment.
- If absolutely no equipment can be inferred, return an empty list [].
- Only include equipment that is actually used in the instructions.
- Always assign category using one of these exact values only: cookware, utensil, appliance, prep.
- Category mapping rules:
  - appliance: oven, microwave, stovetop, blender
  - cookware: skillet, pot, saucepan, baking sheet, dutch oven
  - utensil: whisk, spoon, spatula, tongs
  - prep: knife, cutting board, peeler, grater, mixing bowl

========================
COOKING INSTRUCTION RULES
========================
- Extract ONLY the actual cooking/preparation directions.
- Do NOT include intro text, serving suggestions, storage tips, FAQs, nutrition notes, comments, ads, or unrelated article text.
- Preserve the recipe's step order exactly.
- Each instruction must be one complete action step.
- Do NOT summarize the whole recipe into one paragraph.
- Do NOT invent missing steps.
- If the page has numbered instructions, use those numbers.
- If unnumbered, assign step_number in order starting at 1.
- Keep temperatures, times, pan sizes, ingredient amounts, and doneness cues exactly when present.
- Include prep steps such as chopping, boiling, draining, mixing, resting, baking, cooling, and serving only when they are part of the recipe directions.
- If instructions are split into sections such as "Make the sauce", "Cook the pasta", or "Assemble", preserve that section name.
- If no cooking instructions are found, return an empty list [].
- For each step, include "equipment_used" as a list of equipment names used in that step.

INSTRUCTION DEDUPE RULES:
- Remove duplicate instruction steps.
- Prefer the cleanest and most complete version of repeated instructions.
- Preserve original recipe order.

========================
NUTRITION RULES
========================
- Extract nutritional information ONLY if it appears on the recipe page.
- Do NOT calculate, estimate, or invent nutrition values.
- Preserve the displayed value and unit when possible.
- Use null when a value is missing or unknown.
- If the page lists nutrition per serving, set serving_basis to "per serving".
- If the page lists nutrition for the full recipe, set serving_basis to "full recipe".
- If the serving basis is unclear, set serving_basis to null.
- Keep units inside value strings, such as "331 kcal", "15 g", "400 mg", or "20%".
- Put any nutrition item that does not fit the common fields into other.
- If no nutrition information is found, return nutrition with all fields as null and other as [].

========================
IMAGE RULES
========================
- If the page content includes a clear final recipe/product image URL, put it in cover_image.url.
- Prefer the finished dish or final baked/cooked product over logo, avatar, icon, step-by-step, or ingredient images.
- If no final recipe image URL is visible in the provided content, set cover_image values to null.

========================
RECIPE SCALING RULES
========================
- If the page displays recipe scale controls such as "1/2x", "1x", "2x", or "3x", capture them.
- Put the active/default value in scaling.selected_multiplier. This is usually 1.
- Put every available option in scaling.available_multipliers.
- Each scaling option must have:
  - label: the visible label, such as "1/2x" or "2x"
  - value: the numeric multiplier, such as 0.5 or 2
- If the page does not show scale controls, use these default options: 1/2x, 1x, 2x, 3x.

========================
RECIPE INFO RULES
========================
- Fill servings with the recipe amount, yield, portions, or best practical estimate, such as "4 servings", "6 portions", or "1 9-inch pan".
- Fill level with the displayed or estimated recipe difficulty, such as "Easy", "Intermediate", or "Advanced".
- Fill total_time, prep_time, inactive_time, and cook_time with displayed values when present, otherwise use practical estimates with units, such as "45 min", "1 hr 15 min", or "0 min".
- Use inactive_time for waiting, resting, chilling, cooling, or rising time when the recipe implies it. Use "0 min" when none is implied.
- Preserve displayed wording when available, such as "Intermediate", "1 hr 55 min", or "30 min".

{additional_rules_block}
========================
FINAL OUTPUT FORMAT
========================
{{
  "source_url": "{recipe_url}",
  "display_name": null,
  "recipe_title": null,
  "cover_image": {{
    "url": null,
    "alt": null,
    "source": null
  }},
  "servings": null,
  "level": null,
  "total_time": null,
  "prep_time": null,
  "inactive_time": null,
  "cook_time": null,
  "scaling": {{
    "selected_multiplier": 1,
    "base_multiplier": 1,
    "base_servings": null,
    "available_multipliers": [
      {{
        "label": "1/2x",
        "value": 0.5
      }},
      {{
        "label": "1x",
        "value": 1
      }},
      {{
        "label": "2x",
        "value": 2
      }},
      {{
        "label": "3x",
        "value": 3
      }}
    ]
  }},
  "ingredients": [
    {{
      "section": null,
      "original_text": null,
      "quantity": null,
      "unit": null,
      "base_quantity": null,
      "base_unit": null,
      "ingredient": null,
      "preparation": null,
      "optional": false,
      "store_section": null,
      "store_section_order": null
    }}
  ],
  "equipment": [
    {{
      "name": null,
      "category": null
    }}
  ],
  "instructions": [
    {{
      "section": null,
      "step_number": null,
      "instruction": null,
      "temperature": null,
      "time": null,
      "equipment_used": []
    }}
  ],
  "nutrition": {{
    "serving_basis": null,
    "calories": null,
    "carbohydrates": null,
    "protein": null,
    "fat": null,
    "saturated_fat": null,
    "polyunsaturated_fat": null,
    "monounsaturated_fat": null,
    "trans_fat": null,
    "cholesterol": null,
    "sodium": null,
    "potassium": null,
    "fiber": null,
    "sugar": null,
    "vitamin_a": null,
    "vitamin_c": null,
    "calcium": null,
    "iron": null,
    "other": [
      {{
        "name": null,
        "value": null
      }}
    ]
  }}
}}
"""


def send_prompt_to_openai(prompt_text):
    payload, temperature_included, resolved_model = build_openai_chat_payload(
        MODEL,
        "recipe-text-extraction",
        [
            {
                "role": "system",
                "content": "You extract recipe ingredients and return only valid JSON.",
            },
            {
                "role": "user",
                "content": prompt_text,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action=recipe-text-extraction "
        f"model={resolved_model} temperature_included={temperature_included}"
    )
    response = get_openai_client().chat.completions.create(**payload)
    record_openai_usage(response, "recipe-text-extraction", model=MODEL)

    return response.choices[0].message.content


def detect_image_mime_type(image_path, mime_type=""):
    resolved_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if resolved_mime:
        return resolved_mime

    path = Path(image_path)
    extension_mime = mimetypes.guess_type(path.name or str(path))[0]
    if extension_mime:
        return extension_mime.lower()

    try:
        detected = imghdr.what(str(path))
        if detected:
            if detected == "jpeg":
                return "image/jpeg"
            return f"image/{detected.lower()}"
    except Exception:
        pass

    try:
        from PIL import Image
        ensure_heif_image_support()
        with Image.open(path) as image:
            if image.format:
                return f"image/{image.format.lower()}"
    except Exception:
        pass

    return "image/jpeg"


def ensure_heif_image_support():
    try:
        import pillow_heif
    except Exception:
        return False

    try:
        pillow_heif.register_heif_opener()
        return True
    except Exception:
        return False


def image_mime_needs_openai_conversion(mime_type, image_path=None):
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime in VISION_SUPPORTED_IMAGE_MIME_TYPES:
        return False

    if normalized_mime in VISION_CONVERTIBLE_IMAGE_MIME_TYPES:
        return True

    suffix = Path(image_path).suffix.lower() if image_path else ""
    return suffix in VISION_CONVERTIBLE_IMAGE_SUFFIXES


def unsupported_phone_image_message(mime_type=""):
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime in {
        "image/heic",
        "image/heif",
        "image/heic-sequence",
        "image/heif-sequence",
    }:
        return (
            "This phone photo format could not be read. Upload JPEG or PNG, "
            "or change the phone camera format to Most Compatible."
        )

    return "Unsupported image format."


def normalize_image_bytes_for_openai(image_path, mime_type="", debug=None):
    upload_path = Path(image_path)
    original_bytes = upload_path.read_bytes()
    original_mime = str(mime_type or detect_image_mime_type(upload_path, "") or "").split(";", 1)[0].strip().lower()

    try:
        ensure_heif_image_support()
        from PIL import Image
        from PIL import ImageOps
    except Exception as exc:
        raise RuntimeError(f"Pillow image support is unavailable: {exc}") from exc

    try:
        with Image.open(io.BytesIO(original_bytes)) as image:
            original_format = str(image.format or "")
            mode_before = str(image.mode or "")
            size_before = tuple(image.size or (0, 0))
            max_dimension_before = max(size_before) if size_before else 0
            transposed = ImageOps.exif_transpose(image)
            exif_transpose_applied = tuple(transposed.size or ()) != tuple(image.size or ())
            if transposed is not image:
                image = transposed

            if max(image.size or (0, 0)) > 1600:
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)

            if image.mode != "RGB":
                image = image.convert("RGB")

            mode_after = str(image.mode or "")
            size_after = tuple(image.size or (0, 0))
            max_dimension_after = max(size_after) if size_after else 0
            output = io.BytesIO()
            save_kwargs = {"format": "JPEG", "quality": 85}
            try:
                image.save(output, optimize=True, **save_kwargs)
            except Exception:
                output = io.BytesIO()
                image.save(output, **save_kwargs)
            normalized_bytes = output.getvalue()
    except Exception as exc:
        print(
            "[Vision] action=image_normalization_failed "
            f"file={str(upload_path)!r} original_mime={original_mime or 'unknown'} "
            f"original_bytes={len(original_bytes)} exception_type={type(exc).__name__} error={exc}"
        )
        raise RuntimeError(f"Image decode/conversion failed: {exc}") from exc

    details = {
        "original_format": original_format,
        "original_mime": original_mime or "application/octet-stream",
        "original_bytes": len(original_bytes),
        "output_format": "JPEG",
        "output_mime": "image/jpeg",
        "output_bytes": len(normalized_bytes),
        "image_mode_before": mode_before,
        "image_mode_after": mode_after,
        "exif_transpose_applied": bool(exif_transpose_applied),
        "max_dimension_before": max_dimension_before,
        "max_dimension_after": max_dimension_after,
    }
    if isinstance(debug, dict):
        debug.update(details)
        debug["mime_type"] = "image/jpeg"
        debug["openai_image_bytes"] = len(normalized_bytes)
    print(
        "[Vision] action=normalize_image_for_openai "
        f"original_format={original_format or 'unknown'} "
        f"original_mime={details['original_mime']} original_bytes={len(original_bytes)} "
        "output_format=JPEG output_mime=image/jpeg "
        f"output_bytes={len(normalized_bytes)} "
        f"image_mode_before={mode_before} image_mode_after={mode_after} "
        f"exif_transpose_applied={'yes' if exif_transpose_applied else 'no'} "
        f"max_dimension_before={max_dimension_before} max_dimension_after={max_dimension_after}"
    )
    return normalized_bytes, "image/jpeg", details


def prepare_image_bytes_for_openai(image_path, mime_type):
    image_bytes, output_mime, _details = normalize_image_bytes_for_openai(image_path, mime_type)
    return image_bytes, output_mime


def _openai_vision_result_from_exception(exc, action_name, model, model_source, image_bytes=0, base64_length=0, temperature_included=False, debug=None):
    openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
    error_code, error_message = classify_vision_ai_exception(exc)
    technical_message = str(exc or "").strip() or type(exc).__name__
    if isinstance(debug, dict):
        debug["error_code"] = error_code
        debug["error_message"] = error_message
        debug["technical_message"] = technical_message
        debug["exception_type"] = type(exc).__name__
        debug["exception_message"] = technical_message
        debug["openai_error_code"] = openai_error_code
        debug["openai_error_param"] = openai_error_param
        debug["request_completed"] = False
        debug["temperature_included"] = bool(temperature_included)

    print(
        "[Vision] action=openai_exception "
        f"action_name={action_name} model={model} model_source={model_source} "
        f"exception_type={type(exc).__name__} str={str(exc)!r} repr={repr(exc)} "
        f"cause={repr(getattr(exc, '__cause__', None))} "
        f"context={repr(getattr(exc, '__context__', None))} "
        f"openai_error_code={openai_error_code or 'n/a'} "
        f"openai_error_param={openai_error_param or 'n/a'} "
        f"image_bytes={image_bytes} base64_length={base64_length} "
        f"temperature_included={temperature_included} final_error_code={error_code}"
    )
    return VisionResult(
        ok=False,
        text="",
        model_used=model,
        model_source=model_source,
        action_name=action_name,
        error_code=error_code,
        error_message=error_message,
        technical_message=technical_message,
        exception_type=type(exc).__name__,
        openai_error_code=openai_error_code,
        openai_error_param=openai_error_param,
        image_bytes=image_bytes,
        base64_length=base64_length,
        temperature_included=bool(temperature_included),
        debug=debug if isinstance(debug, dict) else None,
    )


def _vision_failure_should_fallback(result):
    return result.error_code in {
        "OPENAI_CONNECTION_ERROR",
        "OPENAI_UNSUPPORTED_MODEL",
        "OPENAI_UNSUPPORTED_PARAMETER",
        "OPENAI_BAD_REQUEST",
        "OPENAI_INVALID_IMAGE_PAYLOAD",
    }


def call_openai_vision_image(
    image_path,
    prompt,
    action_name,
    preferred_model=None,
    debug=None,
):
    action_name = str(action_name or "vision").strip() or "vision"
    upload_path = Path(image_path)
    if isinstance(debug, dict):
        debug["action"] = action_name
        debug["file_path"] = str(upload_path)
        debug["filename"] = str(debug.get("filename") or upload_path.name)

    if not os.getenv("OPENAI_API_KEY"):
        result = VisionResult(
            ok=False,
            model_used=resolve_openai_model("vision", preferred_model).model,
            model_source=resolve_openai_model("vision", preferred_model).source,
            action_name=action_name,
            error_code="OPENAI_API_KEY_MISSING",
            error_message="OPENAI_API_KEY is missing or invalid.",
            technical_message="OPENAI_API_KEY is missing.",
            debug=debug if isinstance(debug, dict) else None,
        )
        if isinstance(debug, dict):
            debug["model"] = result.model_used
            debug["model_source"] = result.model_source
            debug["error_code"] = result.error_code
            debug["error_message"] = result.error_message
            debug["technical_message"] = result.technical_message
            debug["failed_status"] = "vision_request_sent"
        return result

    if not upload_path.is_file():
        result = VisionResult(
            ok=False,
            model_used=resolve_openai_model("vision", preferred_model).model,
            model_source=resolve_openai_model("vision", preferred_model).source,
            action_name=action_name,
            error_code="UPLOADED_FILE_MISSING",
            error_message="Uploaded image file does not exist.",
            technical_message=f"Missing file: {upload_path}",
            debug=debug if isinstance(debug, dict) else None,
        )
        if isinstance(debug, dict):
            debug["model"] = result.model_used
            debug["model_source"] = result.model_source
            debug["error_code"] = result.error_code
            debug["error_message"] = result.error_message
            debug["technical_message"] = result.technical_message
            debug["file_exists"] = False
            debug["failed_status"] = "image_uploaded"
        return result

    uploaded_file_size = upload_path.stat().st_size
    if isinstance(debug, dict):
        debug["file_exists"] = True
        debug["file_size"] = uploaded_file_size
        debug["uploaded_file_size"] = uploaded_file_size
        debug["image_uploaded"] = True

    try:
        image_bytes, output_mime, normalize_details = normalize_image_bytes_for_openai(
            upload_path,
            detect_image_mime_type(upload_path, ""),
            debug=debug,
        )
    except Exception as exc:
        result = _openai_vision_result_from_exception(
            exc,
            action_name,
            resolve_openai_model("vision", preferred_model).model,
            resolve_openai_model("vision", preferred_model).source,
            debug=debug,
        )
        result.error_code = "IMAGE_NORMALIZATION_FAILED"
        result.error_message = "Image decode/conversion failure."
        if isinstance(debug, dict):
            debug["error_code"] = result.error_code
            debug["error_message"] = result.error_message
            debug["failed_status"] = "image_uploaded"
        return result

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    base64_length = len(encoded_image)
    if isinstance(debug, dict):
        debug["mime_type"] = output_mime
        debug["openai_image_bytes"] = len(image_bytes)
        debug["encoded_base64_length"] = base64_length
        debug["vision_request"] = {
            "model": "",
            "model_source": "",
            "action": action_name,
            "filename": upload_path.name,
            "mime_type": output_mime,
            "prompt_length": len(str(prompt or "")),
            "data_url_prefix": "data:image/jpeg;base64,",
            **normalize_details,
        }

    attempts = [resolve_openai_model("vision", preferred_model)]
    if attempts[0].model != VISION_MODEL_FALLBACK:
        attempts.append(resolve_openai_model("vision", fallback=True))

    first_failure = None
    for attempt_index, model_resolution in enumerate(attempts):
        model = model_resolution.model
        model_source = model_resolution.source
        temperature_included = supports_custom_temperature(model)
        request_kwargs = {}
        if temperature_included:
            request_kwargs["temperature"] = 0
        if isinstance(debug, dict):
            debug["model"] = model
            debug["model_source"] = model_source
            debug["temperature_included"] = bool(temperature_included)
            debug["request_started"] = True
            debug["request_completed"] = False
            debug["vision_request_sent"] = True
            debug["failed_status"] = "vision_request_sent"
            debug["vision_request"]["model"] = model
            debug["vision_request"]["model_source"] = model_source
            debug["vision_request"]["temperature_included"] = bool(temperature_included)

        print(
            "[Vision] action=request_start "
            f"action_name={action_name} model={model} model_source={model_source} "
            f"temperature_included={temperature_included} "
            f"image_bytes={len(image_bytes)} base64_length={base64_length}"
        )
        try:
            client = OpenAI()
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(prompt or "")},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + encoded_image,
                            },
                        },
                    ],
                }],
                **request_kwargs,
            )
            text = str(response.choices[0].message.content or "")
            if not text.strip():
                empty_exc = RuntimeError("OpenAI returned an empty response.")
                result = _openai_vision_result_from_exception(
                    empty_exc,
                    action_name,
                    model,
                    model_source,
                    image_bytes=len(image_bytes),
                    base64_length=base64_length,
                    temperature_included=temperature_included,
                    debug=debug,
                )
                result.error_code = "OPENAI_EMPTY_RESPONSE"
                result.error_message = "OpenAI returned an empty response."
                if isinstance(debug, dict):
                    debug["error_code"] = result.error_code
                    debug["error_message"] = result.error_message
                return result

            record_openai_usage(response, action_name, model=model)
            if isinstance(debug, dict):
                debug["request_completed"] = True
                debug["vision_response_received"] = True
                debug["failed_status"] = ""
                debug["vision_response"] = text[:12000]

            result = VisionResult(
                ok=True,
                text=text,
                model_used=model,
                model_source=model_source,
                action_name=action_name,
                image_bytes=len(image_bytes),
                base64_length=base64_length,
                temperature_included=bool(temperature_included),
                debug=debug if isinstance(debug, dict) else None,
            )
            if attempt_index > 0 and first_failure is not None:
                result.fallback_used = True
                result.fallback_from_model = first_failure.model_used
                result.fallback_to_model = model
                if isinstance(debug, dict):
                    debug["fallback_used"] = True
                    debug["fallback_from_model"] = first_failure.model_used
                    debug["fallback_to_model"] = model
                print(
                    "[Vision] VISION_MODEL_FALLBACK_USED "
                    f"from_model={first_failure.model_used} to_model={model}"
                )
            print(
                "[Vision] action=request_success "
                f"action_name={action_name} model={model} model_source={model_source} "
                f"temperature_included={temperature_included}"
            )
            return result
        except Exception as exc:
            result = _openai_vision_result_from_exception(
                exc,
                action_name,
                model,
                model_source,
                image_bytes=len(image_bytes),
                base64_length=base64_length,
                temperature_included=temperature_included,
                debug=debug,
            )
            if attempt_index == 0 and len(attempts) > 1 and _vision_failure_should_fallback(result):
                first_failure = result
                print(
                    "[Vision] VISION_MODEL_FALLBACK_USED "
                    f"from_model={model} to_model={VISION_MODEL_FALLBACK}"
                )
                if isinstance(debug, dict):
                    debug["fallback_used"] = True
                    debug["fallback_from_model"] = model
                    debug["fallback_to_model"] = VISION_MODEL_FALLBACK
                continue
            if first_failure is not None:
                result.fallback_used = True
                result.fallback_from_model = first_failure.model_used
                result.fallback_to_model = model
                if isinstance(debug, dict):
                    debug["fallback_used"] = True
                    debug["fallback_from_model"] = first_failure.model_used
                    debug["fallback_to_model"] = model
            return result


def send_image_prompt_to_openai(
    prompt_text,
    image_path,
    mime_type,
    model=None,
    request_timeout=None,
    max_retries=None,
    debug=None,
    action=None,
):
    debug_action = (
        str(debug.get("action") or action or "generate_recipe_from_image")
        if isinstance(debug, dict)
        else str(action or "generate_recipe_from_image")
    )
    result = call_openai_vision_image(
        image_path=str(image_path),
        prompt=prompt_text,
        action_name=debug_action,
        preferred_model=model,
        debug=debug,
    )
    if not result.ok:
        raise VisionRequestError(result)
    return result.text


def send_social_video_audio_image_prompt_to_openai(prompt_text, image_urls):
    content = [{"type": "text", "text": prompt_text}]

    for image_url in image_urls[:MAX_SOCIAL_VIDEO_IMAGE_URLS]:
        if not str(image_url or "").startswith(("http://", "https://", "data:image/")):
            continue
        content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url,
            },
        })

    payload, temperature_included, resolved_model = build_openai_chat_payload(
        MODEL,
        "social-video-audio-image-extraction",
        [
            {
                "role": "system",
                "content": (
                    "You extract recipes from social video audio transcripts and video images. "
                    "Return only valid JSON."
                ),
            },
            {
                "role": "user",
                "content": content,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action=social-video-audio-image-extraction "
        f"model={resolved_model} temperature_included={temperature_included}"
    )
    response = get_openai_client().chat.completions.create(**payload)
    record_openai_usage(response, "social-video-audio-image-extraction", model=MODEL)

    return response.choices[0].message.content


def send_file_prompt_to_openai(prompt_text, file_path, mime_type, filename):
    file_bytes = file_path.read_bytes()
    file_data = base64.b64encode(file_bytes).decode("ascii")

    payload, temperature_included, resolved_model = build_openai_chat_payload(
        MODEL,
        "recipe-file-extraction",
        [
            {
                "role": "system",
                "content": "You extract recipe ingredients from recipe photos and documents and return only valid JSON.",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": f"data:{mime_type};base64,{file_data}",
                        },
                    },
                    {"type": "text", "text": prompt_text},
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    print(
        f"[OpenAI] action=recipe-file-extraction "
        f"model={resolved_model} temperature_included={temperature_included}"
    )
    response = get_openai_client().chat.completions.create(**payload)
    record_openai_usage(response, "recipe-file-extraction", model=MODEL)

    return response.choices[0].message.content


def save_json_response(recipe_url, response_text, html_text=None):
    cleaned = clean_json_response(response_text)

    base_name = safe_filename(recipe_url)
    json_path = OUTPUT_FOLDER / f"{base_name}.json"
    raw_path = RAW_FOLDER / f"{base_name}_RAW.txt"

    try:
        json_data = json.loads(cleaned)
        json_data["source_url"] = json_data.get("source_url") or recipe_url
        normalize_extracted_recipe_identity(json_data)
        normalize_extracted_ingredient_fields(json_data)
        normalize_extracted_equipment_fields(json_data)
        apply_recipe_info_metadata(json_data, html_text)
        apply_recipe_scaling_metadata(json_data, html_text)
        apply_recipe_cover_image_metadata(json_data, html_text, recipe_url)
        apply_recipe_owner_metadata(json_data)
        upload_result = maybe_upload_recipe_archive_pdf_to_cloudflare(recipe_url)
        attach_cloudflare_pdf_metadata(
            recipe_url,
            json_data,
            upload_result,
            recipe_archive_pdf_path(recipe_url),
        )

        json_path.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(f"Saved JSON: {json_path}")

        return True, json_data

    except json.JSONDecodeError as exc:
        raw_path.write_text(response_text, encoding="utf-8")

        print(f"Invalid JSON. Saved raw response: {raw_path}")
        print(f"JSON error: {exc}")

        return False, None


def parse_json_text_response(recipe_url, response_text):
    cleaned = clean_json_response(response_text)

    if not cleaned:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PARSE_ERROR.txt"
        raw_error_path.write_text(response_text, encoding="utf-8")
        return None, "The AI response was empty."

    try:
        json_data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PARSE_ERROR.txt"
        raw_error_path.write_text(response_text, encoding="utf-8")
        return None, f"Unable to parse AI response JSON: {exc}"

    if not isinstance(json_data, dict):
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_PARSE_ERROR.txt"
        raw_error_path.write_text(response_text, encoding="utf-8")
        return None, "The AI response was not a JSON object."

    return json_data, None


def build_normalized_import_object(
    source_type,
    source_name="",
    source_url="",
    uploaded_file_path="",
    extracted_text="",
    detected_food_photo=False,
    recipe_json=None,
    error_message="",
):
    return {
        "source_type": source_type,
        "source_name": source_name,
        "source_url": source_url,
        "uploaded_file_path": uploaded_file_path,
        "extracted_text": extracted_text,
        "detected_food_photo": bool(detected_food_photo),
        "recipe_json": recipe_json,
        "error_message": error_message,
    }


def upload_import_source_type(mime_type, filename, upload_path):
    suffix = upload_file_suffix(filename, upload_path)
    normalized_mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()

    if (
        normalized_mime_type.startswith("image/")
        or suffix in VISION_SUPPORTED_IMAGE_SUFFIXES
        or suffix in VISION_CONVERTIBLE_IMAGE_SUFFIXES
    ):
        return "image"

    if normalized_mime_type == "application/pdf" or suffix == ".pdf":
        return "pdf"

    if normalized_mime_type.startswith("text/") or suffix in {".txt", ".md"}:
        return "text"

    return "document"


def upload_source_type_label(source_type):
    return {
        "url": "URL",
        "image": "Image",
        "pdf": "PDF",
        "document": "Document",
        "text": "Text",
    }.get(str(source_type or "").strip().lower(), "File")


def build_upload_failure_result(import_object, error_message, failed_step="extract", **extra):
    import_object = import_object if isinstance(import_object, dict) else {}
    import_object["error_message"] = error_message
    source_type = str(import_object.get("source_type") or "").strip().lower()
    default_model = resolve_vision_model() if source_type == "image" else MODEL
    model_used = str(extra.pop("model_used", "")).strip() or str(default_model).strip() or str(MODEL)
    action = str(extra.pop("action", "read_text")).strip() or "read_text"
    error_code = str(extra.pop("error_code", "")).strip() or "OPENAI_REQUEST_FAILED"
    technical_message = str(extra.pop("technical_message", error_message) or error_message).strip()
    normalized_error_message = str(error_message or "").strip() or "Upload extraction failed."
    if normalized_error_message == error_code:
        normalized_error_message = f"{error_code}: {normalized_error_message}"
    debug_payload = extra.pop("debug", None)
    if not isinstance(debug_payload, dict):
        debug_payload = {}
    else:
        debug_payload = dict(debug_payload)
    debug_payload.setdefault("model", model_used)
    debug_payload["action"] = action
    debug_payload["error_code"] = error_code
    debug_payload["error_message"] = normalized_error_message
    debug_payload["technical_message"] = technical_message

    print(
        "[recipe_import] action=upload_import_failed "
        f"source_type={import_object.get('source_type')} "
        f"source_name={str(import_object.get('source_name') or '')!r} "
        f"failed_step={failed_step} action={action} model={model_used} "
        f"final_error_code={error_code} error={error_message} "
        f"openai_error_code={debug_payload.get('openai_error_code') or 'n/a'} "
        f"openai_error_param={debug_payload.get('openai_error_param') or 'n/a'} "
        f"exception_type={debug_payload.get('exception_type') or 'n/a'}"
    )

    result = {
        "success": False,
        "ok": False,
        "error": normalized_error_message,
        "error_code": error_code,
        "error_message": normalized_error_message,
        "technical_message": technical_message,
        "failed_step": failed_step,
        "ingredients": [],
        "import_source": import_object,
        "source_type": import_object.get("source_type"),
        "source_type_label": upload_source_type_label(import_object.get("source_type")),
        "source_name": import_object.get("source_name"),
        "source_url": import_object.get("source_url"),
        "uploaded_file_path": import_object.get("uploaded_file_path"),
        "extracted_text": import_object.get("extracted_text") or "",
        "detected_food_photo": bool(import_object.get("detected_food_photo")),
        "model_used": model_used,
        "model": model_used,
        "action": action,
        "debug": debug_payload,
    }
    result.update(extra)
    return result


def parse_confidence(value):
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "").strip()
        if not cleaned:
            return None
        value = cleaned

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if 0 <= value <= 1:
        return round(max(0.0, min(1.0, value)), 2)

    if 0 < value <= 100:
        return round(max(0.0, min(1.0, value / 100)), 2)

    return None


def normalize_confidence_level(value, default="medium"):
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in {"high", "medium", "low"}:
            return candidate

    parsed = parse_confidence(value)
    if parsed is None:
        return default

    if parsed >= 0.8:
        return "high"
    if parsed >= 0.55:
        return "medium"

    return "low"


FOOD_IMAGE_RECIPE_METADATA_DEFAULTS = {
    "servings": "4 servings",
    "level": "Easy",
    "total_time": "45 min",
    "prep_time": "15 min",
    "inactive_time": "0 min",
    "cook_time": "30 min",
}

FOOD_IMAGE_RECIPE_METADATA_ALIASES = {
    "servings": (
        "servings",
        "recipe_amount",
        "recipe_yield",
        "yield",
        "portions",
        "serves",
    ),
    "level": ("level", "difficulty", "recipe_difficulty"),
    "total_time": ("total_time", "total", "recipe_total_time", "estimated_total_time"),
    "prep_time": ("prep_time", "prep", "recipe_prep_time", "hands_on_time"),
    "inactive_time": (
        "inactive_time",
        "inactive",
        "recipe_inactive_time",
        "rest_time",
        "waiting_time",
        "chill_time",
        "rise_time",
    ),
    "cook_time": ("cook_time", "cook", "recipe_cook_time", "cooking_time"),
}

FOOD_IMAGE_EMPTY_RECIPE_INFO_VALUES = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "not specified",
    "unknown",
}


def normalize_food_image_recipe_metadata(json_data):
    if not isinstance(json_data, dict):
        return

    for key in FOOD_IMAGE_RECIPE_METADATA_DEFAULTS:
        value = food_image_recipe_metadata_value(json_data, key)
        json_data[key] = value or FOOD_IMAGE_RECIPE_METADATA_DEFAULTS[key]

    apply_recipe_scaling_metadata(json_data)


def food_image_recipe_metadata_value(json_data, key):
    for alias in FOOD_IMAGE_RECIPE_METADATA_ALIASES.get(key, (key,)):
        if alias not in json_data:
            continue

        value = json_data.get(alias)
        if isinstance(value, bool) or value in (None, "", [], {}):
            continue

        if isinstance(value, (int, float)):
            if key == "servings":
                return f"{value:g} servings"
            if key.endswith("_time"):
                return f"{value:g} min"

        if isinstance(value, (list, dict)):
            continue

        cleaned = (
            clean_recipe_text(value)
            if key == "servings"
            else clean_recipe_info_value(value)
        )
        if cleaned.lower() not in FOOD_IMAGE_EMPTY_RECIPE_INFO_VALUES:
            return cleaned

    return ""


def normalize_ingredient_candidates(raw_ingredients):
    rows = []
    seen = set()

    for item in raw_ingredients or []:
        if isinstance(item, str):
            row = {"original_text": clean_recipe_text(item)}
            parsed = parse_structured_ingredient_line(row["original_text"])
            row["quantity"] = row.get("quantity") or parsed["quantity"]
            row["unit"] = row.get("unit") or parsed["unit"]
            row["ingredient"] = row.get("ingredient") or parsed["ingredient"]
            row["preparation"] = ""
            row["optional"] = False
            rows.append(row)
            continue

        if not isinstance(item, dict):
            continue

        ingredient = clean_recipe_text(
            item.get("ingredient")
            or item.get("name")
            or item.get("original_text")
        )
        original_text = clean_recipe_text(item.get("original_text"))

        if not original_text and ingredient:
            pieces = [
                clean_recipe_text(item.get("quantity")),
                clean_recipe_text(item.get("unit")),
                ingredient,
                clean_recipe_text(item.get("preparation")),
            ]
            original_text = " ".join(part for part in pieces if part)

        if not ingredient and original_text:
            ingredient = parse_structured_ingredient_line(original_text)["ingredient"]

        if not ingredient:
            continue

        key = normalize_ingredient_key(ingredient)
        if not key or key in seen:
            continue

        row = {
            "original_text": original_text or ingredient,
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "ingredient": ingredient,
            "preparation": item.get("preparation"),
            "optional": bool(item.get("optional")),
            "section": item.get("section"),
            "store_section": item.get("store_section"),
        }

        rows.append(row)
        seen.add(key)

    if rows:
        normalize_extracted_ingredient_fields({"ingredients": rows})

    return rows


def normalize_vision_ingredient_candidates(raw_ingredients):
    rows = []

    for row in normalize_ingredient_candidates(raw_ingredients):
        if not isinstance(row, dict):
            continue

        original_text = clean_recipe_text(row.get("original_text") or "")
        parsed_line = parse_structured_ingredient_line(original_text)
        ingredient = clean_recipe_text(
            row.get("ingredient")
            or parsed_line.get("ingredient")
            or original_text
        )

        if not original_text:
            original_text = clean_recipe_text(
                " ".join(
                    part
                    for part in [
                        clean_recipe_text(row.get("quantity")),
                        clean_recipe_text(row.get("unit")),
                        ingredient,
                        clean_recipe_text(row.get("preparation")),
                    ]
                    if part
                )
            )

        rows.append({
            "section": clean_recipe_text(row.get("section") or ""),
            "original_text": original_text or ingredient,
            "quantity": clean_recipe_text(row.get("quantity") or ""),
            "unit": clean_recipe_text(row.get("unit") or ""),
            "ingredient": ingredient,
            "preparation": clean_recipe_text(row.get("preparation") or ""),
            "optional": bool(row.get("optional")),
            "estimated_from_image": bool(row.get("estimated_from_image", True)),
            "confidence": normalize_confidence_level(row.get("confidence"), default="medium"),
        })

    return rows


def normalize_recipe_text_list(value):
    if isinstance(value, list):
        rows = []

        for item in value:
            if isinstance(item, dict):
                text = clean_recipe_text(
                    item.get("text")
                    or item.get("instruction")
                    or item.get("step")
                    or item.get("name")
                    or item.get("note")
                )
            else:
                text = clean_recipe_text(item)

            if text:
                rows.append(text)

        return rows

    raw_text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    rows = [
        clean_recipe_text(part)
        for part in re.split(r"\n+", raw_text)
        if clean_recipe_text(part)
    ]
    if rows:
        return rows

    text = clean_recipe_text(value)
    return [text] if text else []


def build_food_image_inference_prompt(recipe_url, filename, user_description=""):
    user_description = clean_recipe_text(user_description)
    user_description_hint = (
        "\nUser description:\n"
        f"\"{user_description}\"\n"
        "Use this description to resolve ambiguous ingredients and missing steps.\n"
        if user_description
        else ""
    )
    return f"""
Analyze this food photo and create a likely recipe.
Identify visible ingredients, estimate reasonable quantities, equipment, and instructions.
Return strict JSON only.
Mark every ingredient as estimated_from_image=true and include confidence notes.
Do not claim certainty.
{user_description_hint}

Return JSON with exactly this shape:
{{
  "recipe_name": "AI-Inferred recipe title",
  "recipe_title": "AI-Inferred recipe title",
  "display_name": "Short card-friendly title",
  "servings": null,
  "estimated_from_image": true,
  "confidence_notes": ["Visible ingredients are estimated from the image."],
  "level": "Easy",
  "ingredients": [
    {{
      "quantity": "1",
      "unit": "cup",
      "ingredient": "rice",
      "estimated_from_image": true,
      "confidence": "medium",
      "preparation": "",
      "optional": false,
      "section": "",
      "original_text": "1 cup rice"
    }}
  ],
  "visible_ingredients": ["rice", "onions", "olive oil"],
  "inferred_ingredients": ["rice", "onion", "salt", "pepper", "olive oil"],
  "equipment": ["large pan", "spatula"],
  "instructions": ["Cook ingredients.", "Adjust seasoning and serve."],
  "nutrition": {{
    "calories": "",
    "protein": "",
    "carbs": "",
    "fat": "",
    "fiber": "",
    "sodium": ""
  }},
  "extraction_confidence": 0.0,
  "extraction_mode": "image_estimate",
  "image_analysis_notes": "notes...",
  "shopping_list_items": ["rice", "onion", "olive oil"]
}}

Rules:
- If the image does not show food or a meal, return an empty ingredients array and explain that in image_analysis_notes.
- Use only clearly visible ingredients in visible_ingredients.
- Use grocery-store ingredients with quantities and sections.
- Include reasonable likely pantry staples in inferred_ingredients and ingredients only when needed for a plausible recipe.
- If a user description is provided, treat it as a high-priority hint for ingredient selection and method flow.
- Do not claim the result is exact; treat all inferred items as estimated.
- Do not claim ingredient amounts are exact; they should be treated as estimates.
- Include a confidence score between 0 and 1 in extraction_confidence.
- Return `confidence` per ingredient as one of: "high", "medium", or "low".
- Return valid JSON only.
"""


def infer_food_image_recipe(recipe_url, upload_path, mime_type, filename, user_description="", debug=None):
    model_resolution = resolve_openai_model("vision")
    vision_model = model_resolution.model
    prompt_text = build_food_image_inference_prompt(recipe_url, filename, user_description)
    if isinstance(debug, dict):
        debug.setdefault("action", "generate_recipe_from_image")
        debug["vision_request"] = {
            "model": str(vision_model),
            "model_source": model_resolution.source,
            "filename": str(filename or ""),
            "mime_type": str(mime_type or ""),
            "prompt_length": len(prompt_text),
            "prompt": prompt_text,
        }
        debug["model"] = str(vision_model)
        debug["model_source"] = model_resolution.source

    if not str(vision_model or "").strip():
        return None, set_vision_debug_error(
            debug,
            "OPENAI_API_KEY_MISSING",
            "OPENAI_API_KEY is missing or invalid.",
            failed_status="vision_request_sent",
        )

    if not os.getenv("OPENAI_API_KEY"):
        return None, set_vision_debug_error(
            debug,
            "OPENAI_API_KEY_MISSING",
            "OPENAI_API_KEY is missing or invalid.",
            failed_status="vision_request_sent",
        )

    if isinstance(debug, dict):
        debug["vision_request_sent"] = True
    log_vision_debug_step(debug, "Sending image to AI", model=vision_model, filename=filename, mime_type=mime_type)

    try:
        response_text = send_image_prompt_to_openai(
            prompt_text,
            upload_path,
            mime_type,
            model=vision_model,
            debug=debug,
        )
    except Exception as exc:
        error_code, error_message = classify_vision_ai_exception(exc)
        set_vision_debug_exception(debug, exc)
        print(
            "[Vision] action=recipe_image_inference_failed "
            f"model={vision_model} "
            f"error_code={error_code} "
            f"exception_type={type(exc).__name__}"
        )
        return None, set_vision_debug_error(
            debug,
            error_code,
            error_message,
            failed_status="vision_response_received",
        )

    response_text = str(response_text or "")
    response_length = len(response_text)
    if isinstance(debug, dict):
        debug["vision_response_received"] = bool(response_text.strip())
        debug["response_length"] = response_length
        debug["vision_response"] = response_text[:12000]
    log_vision_debug_step(debug, "AI response received", received=bool(response_text.strip()))
    log_vision_debug_step(debug, "Response length", response_length=response_length)

    if not response_text.strip():
        return None, set_vision_debug_error(
            debug,
            "AI_EMPTY_RESPONSE",
            "AI returned empty response.",
            failed_status="vision_response_received",
        )

    parsed, parse_error = parse_json_text_response(recipe_url, response_text)
    if parse_error:
        if isinstance(debug, dict):
            debug["json_parse_success"] = False
            debug["recipe_json_parsed"] = False
        return None, set_vision_debug_error(
            debug,
            "VISION_RESPONSE_PARSE_FAILED",
            f"JSON parsing failed: {parse_error}",
            failed_status="json_parse_success",
        )

    parsed = parsed if isinstance(parsed, dict) else {}
    if isinstance(debug, dict):
        debug["json_parse_success"] = True
        debug["recipe_json_parsed"] = True
        debug["recipe_json"] = parsed
    log_vision_debug_step(debug, "JSON parse success")

    ingredient_candidates = (
        parsed.get("ingredients")
        or parsed.get("estimated_ingredients")
        or parsed.get("shopping_list_items")
        or []
    )
    ingredients = normalize_vision_ingredient_candidates(ingredient_candidates)
    visible = normalize_ingredient_candidates(parsed.get("visible_ingredients", []))
    inferred = normalize_ingredient_candidates(parsed.get("inferred_ingredients", []))
    parsed["ingredients"] = ingredients
    parsed["visible_ingredients"] = [row.get("ingredient") for row in visible if row.get("ingredient")]
    parsed["inferred_ingredients"] = [row.get("ingredient") for row in inferred if row.get("ingredient")]
    parsed["shopping_list_items"] = extract_ingredients_from_result({"ingredients": ingredients})
    if isinstance(debug, dict):
        debug["ingredient_count"] = len(ingredients)
    log_vision_debug_step(debug, "Ingredient count", ingredient_count=len(ingredients))

    parsed["equipment"] = normalize_recipe_text_list(parsed.get("equipment"))

    parsed["model_used"] = str(debug.get("model") if isinstance(debug, dict) else vision_model)
    parsed["model"] = str(debug.get("model") if isinstance(debug, dict) else vision_model)
    parsed["model_source"] = str(debug.get("model_source") if isinstance(debug, dict) else model_resolution.source)

    instructions = normalize_recipe_text_list(
        parsed.get("instructions")
        or parsed.get("steps")
        or parsed.get("method")
    )
    if ingredients and not instructions:
        instructions = [
            "Review the estimated ingredients from the food photo before cooking.",
            "Prepare the dish using the likely method for the visible meal, adjusting quantities and seasoning as needed.",
        ]
    parsed["instructions"] = instructions

    if not isinstance(parsed.get("nutrition"), dict):
        parsed["nutrition"] = {}
    nutrition_source = parsed["nutrition"]
    nutrition_serving_basis = clean_recipe_text(
        nutrition_source.get("serving_basis")
        or nutrition_source.get("basis")
        or nutrition_source.get("per")
        or ""
    )
    parsed["nutrition"] = {
        "serving_basis": nutrition_serving_basis,
        "calories": clean_recipe_text(nutrition_source.get("calories") or ""),
        "protein": clean_recipe_text(nutrition_source.get("protein") or ""),
        "carbs": clean_recipe_text(nutrition_source.get("carbs") or nutrition_source.get("carbohydrates") or ""),
        "fat": clean_recipe_text(nutrition_source.get("fat") or ""),
        "fiber": clean_recipe_text(nutrition_source.get("fiber") or ""),
        "sodium": clean_recipe_text(nutrition_source.get("sodium") or ""),
    }
    if parsed["nutrition"].get("calories") and not parsed["nutrition"].get("serving_basis"):
        parsed["nutrition"]["serving_basis"] = "per serving"

    extraction_confidence = parse_confidence(parsed.get("extraction_confidence"))
    parsed["extraction_confidence"] = extraction_confidence if extraction_confidence is not None else 0.55

    has_user_description = bool(clean_recipe_text(user_description))
    extraction_mode = "manual_description" if has_user_description else "image_estimate"
    recipe_name = clean_recipe_text(
        parsed.get("recipe_name")
        or parsed.get("recipe_title")
        or parsed.get("display_name")
    )
    parsed["recipe_name"] = recipe_name or "Estimated recipe from photo"
    parsed["recipe_title"] = parsed["recipe_name"]
    parsed["display_name"] = parsed.get("display_name") or parsed["recipe_name"]
    servings_value = parsed.get("servings")
    if isinstance(servings_value, str):
        servings_value = servings_value.strip()
        if servings_value.lower() in {"", "none", "null", "n/a", "na"}:
            servings_value = None
    elif servings_value == "":
        servings_value = None
    parsed["servings"] = servings_value
    parsed["estimated_from_image"] = True
    parsed["source_type"] = (
        "image"
    )
    parsed["extraction_mode"] = extraction_mode
    parsed["ai_inferred"] = True
    estimated_note = (
        FOOD_PHOTO_DESCRIPTION_ESTIMATED_NOTE
        if has_user_description
        else "Estimated from food photo and should be reviewed before shopping."
    )
    confidence_notes = normalize_recipe_text_list(
        parsed.get("confidence_notes")
        or parsed.get("confidence")
        or parsed.get("notes")
    )
    parsed["confidence_notes"] = confidence_notes
    analysis_notes = clean_recipe_text(
        parsed.get("image_analysis_notes")
        or parsed.get("analysis_notes")
        or parsed.get("photo_analysis_notes")
    )
    parsed["image_analysis_notes"] = (
        " ".join(
            part
            for part in [
                analysis_notes,
                " ".join(confidence_notes),
                estimated_note,
            ]
            if part
        )
    ).strip()

    for ingredient in parsed.get("ingredients", []):
        if isinstance(ingredient, dict):
            ingredient["estimated_from_image"] = True
            ingredient["confidence"] = normalize_confidence_level(
                ingredient.get("confidence"),
                default="medium",
            )

    apply_recipe_info_metadata(parsed)

    return parsed, None


def generateRecipeFromImage(uploaded_file_path, user_description="", recipe_url="", filename="", mime_type="", debug=None):
    upload_path = Path(uploaded_file_path)
    resolved_url = (
        str(recipe_url).strip()
        if str(recipe_url).strip()
        else f"uploaded://{upload_path.name}"
    )
    resolved_filename = str(filename or upload_path.name)
    resolved_mime_type = normalize_upload_mime_type(mime_type, resolved_filename, upload_path)

    return infer_food_image_recipe(
        resolved_url,
        upload_path,
        resolved_mime_type,
        resolved_filename,
        user_description=user_description,
        debug=debug,
    )


def normalize_extracted_ingredient_fields(json_data):
    for item in json_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        original_text = item.get("original_text") or ""

        if not original_text:
            if item.get("base_quantity") in (None, "") and item.get("quantity") not in (None, ""):
                item["base_quantity"] = item.get("quantity")

            if item.get("base_unit") in (None, "") and item.get("unit") not in (None, ""):
                item["base_unit"] = item.get("unit")

            apply_purchase_mapping_to_ingredient(item)
            continue

        parsed = parse_structured_ingredient_line(original_text)

        if parsed["quantity"] and not item.get("quantity"):
            item["quantity"] = parsed["quantity"]

        if parsed["unit"] and not item.get("unit"):
            item["unit"] = parsed["unit"]

        if parsed["preparation"] and not item.get("preparation"):
            item["preparation"] = parsed["preparation"]

        if parsed["ingredient"]:
            current_ingredient = normalize_ingredient_for_shopping_list(
                item.get("ingredient") or original_text
            )

            if not current_ingredient or current_ingredient == normalize_ingredient_for_shopping_list(original_text):
                item["ingredient"] = parsed["ingredient"]

        if item.get("base_quantity") in (None, "") and item.get("quantity") not in (None, ""):
            item["base_quantity"] = item.get("quantity")

        if item.get("base_unit") in (None, "") and item.get("unit") not in (None, ""):
            item["base_unit"] = item.get("unit")

        apply_purchase_mapping_to_ingredient(item)


def normalize_extracted_recipe_identity(json_data):
    if not isinstance(json_data, dict):
        return

    display_name = clean_recipe_text(json_data.get("display_name") or "")
    recipe_title = clean_recipe_text(json_data.get("recipe_title") or "")

    if display_name and not recipe_title:
        json_data["recipe_title"] = display_name

    if recipe_title and not display_name:
        json_data["display_name"] = recipe_title


def normalize_extracted_equipment_fields(json_data):
    instructions = json_data.get("instructions", [])

    if not isinstance(instructions, list):
        return

    existing_equipment = json_data.get("equipment", [])

    if not existing_equipment:
        json_data["equipment"] = infer_equipment_from_instructions(instructions)

    add_equipment_used_to_instructions(instructions, json_data.get("equipment", []))


def extract_ingredients_from_result(json_data):
    ingredients = []
    seen = set()

    for item in json_data.get("ingredients", []):
        if not isinstance(item, dict):
            continue

        value = normalize_ingredient_for_shopping_list(
            item.get("ingredient") or item.get("original_text")
        )

        key = normalize_ingredient_key(value)

        if value and key not in seen:
            ingredients.append(str(value).strip())
            seen.add(key)

    return ingredients


def structured_recipe_data_is_usable(json_data):
    if not isinstance(json_data, dict):
        return False

    return bool(json_data.get("ingredients")) and bool(json_data.get("instructions"))


def save_extracted_recipe_json(recipe_url, json_data):
    json_data["source_url"] = json_data.get("source_url") or recipe_url
    normalize_extracted_recipe_identity(json_data)
    normalize_extracted_ingredient_fields(json_data)
    normalize_extracted_equipment_fields(json_data)
    apply_recipe_info_metadata(json_data)
    apply_recipe_scaling_metadata(json_data)
    apply_recipe_cover_image_metadata(json_data, recipe_url=recipe_url)
    apply_recipe_owner_metadata(json_data)
    upload_result = maybe_upload_recipe_archive_pdf_to_cloudflare(recipe_url)
    attach_cloudflare_pdf_metadata(
        recipe_url,
        json_data,
        upload_result,
        recipe_archive_pdf_path(recipe_url),
    )

    json_path = OUTPUT_FOLDER / f"{safe_filename(recipe_url)}.json"
    json_path.write_text(
        json.dumps(json_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def extract_recipe_from_upload(file_storage, manual_description="", upload_mode="auto"):
    filename = Path(file_storage.filename or "uploaded-recipe").name
    safe_name = f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    upload_path = UPLOAD_FOLDER / safe_name
    file_storage.save(upload_path)
    manual_description = clean_recipe_text(manual_description)
    requested_upload_mode = str(upload_mode or "auto").strip().lower()
    if requested_upload_mode not in {
        "auto",
        "read",
        "read_text",
        "vision",
        "manual",
        "manual_description",
        "retry",
    }:
        requested_upload_mode = "auto"
    if requested_upload_mode in {"read", "retry"}:
        requested_upload_mode = "read_text"
    if requested_upload_mode == "manual":
        requested_upload_mode = "manual_description"
    requested_upload_action = {
        "vision": "generate_recipe_from_image",
        "manual_description": "describe_recipe",
    }.get(requested_upload_mode, "read_text")

    recipe_url = f"uploaded://{safe_name}"
    mime_type = (
        file_storage.mimetype
        or mimetypes.guess_type(str(upload_path))[0]
        or "application/octet-stream"
    )
    mime_type = normalize_upload_mime_type(mime_type, filename, upload_path)
    upload_suffix = upload_file_suffix(filename, upload_path)
    import_source_type = upload_import_source_type(mime_type, filename, upload_path)
    import_object = build_normalized_import_object(
        import_source_type,
        source_name=filename,
        source_url=recipe_url,
        uploaded_file_path=str(upload_path),
    )
    page_text = ""
    extraction_method = "upload"
    response_text = ""
    json_data = None

    try:
        upload_path_for_review = upload_path
        mime_type_for_review = mime_type
        filename_for_review = filename

        if import_source_type == "image" and requested_upload_mode == "vision":
            print(
                "[recipe_import] action=upload_food_photo_image_estimate_start "
                f"source_type={import_source_type} file={filename!r} mode=image_estimate"
            )
            vision_debug = build_vision_debug(uploaded_file_path=str(upload_path), filename=filename)
            vision_debug["action"] = requested_upload_action
            inferred_json, inference_error = generateRecipeFromImage(
                upload_path,
                user_description="",
                recipe_url=recipe_url,
                filename=filename,
                mime_type=mime_type,
                debug=vision_debug,
            )

            if inference_error:
                print(
                    "[recipe_import] action=upload_food_photo_image_estimate_failed "
                    f"source_type={import_source_type} file={filename!r} mode=image_estimate "
                    f"error={inference_error}"
                )
                failure_message = (
                    str(inference_error or "").strip()
                    or "Unable to estimate this food photo."
                )
                technical_message = (
                    str(vision_debug.get("technical_message") or vision_debug.get("exception_message") or vision_debug.get("error_message") or "")
                    or failure_message
                )
                return build_upload_failure_result(
                    import_object,
                    failure_message,
                    failed_step="extract",
                    extraction_method="image_estimate",
                    action=requested_upload_action,
                    error_code=str(vision_debug.get("error_code") or "OPENAI_REQUEST_FAILED"),
                    technical_message=technical_message,
                    debug=vision_debug,
                )

            extraction_method = "image_estimate"
            json_data = inferred_json
            import_object["recipe_json"] = json_data
        elif import_source_type == "image" and requested_upload_mode == "manual_description":
            if not manual_description:
                return build_upload_failure_result(
                    import_object,
                    "Please add a description before generating from photo content.",
                    failed_step="manual_description",
                    extraction_method="manual_description",
                    action=requested_upload_action,
                )

            print(
                "[recipe_import] action=upload_food_photo_image_estimate_start "
                f"source_type={import_source_type} file={filename!r} mode=manual_description"
            )
            vision_debug = build_vision_debug(uploaded_file_path=str(upload_path), filename=filename)
            vision_debug["action"] = requested_upload_action
            inferred_json, inference_error = generateRecipeFromImage(
                upload_path,
                user_description=manual_description,
                recipe_url=recipe_url,
                filename=filename,
                mime_type=mime_type,
                debug=vision_debug,
            )

            if inference_error:
                print(
                    "[recipe_import] action=upload_food_photo_image_estimate_failed "
                    f"source_type={import_source_type} file={filename!r} mode=manual_description "
                    f"error={inference_error}"
                )
                failure_message = (
                    str(inference_error or "").strip()
                    or "Unable to estimate this food photo from the description."
                )
                technical_message = (
                    str(vision_debug.get("technical_message") or vision_debug.get("exception_message") or vision_debug.get("error_message") or "")
                    or failure_message
                )
                return build_upload_failure_result(
                    import_object,
                    failure_message,
                    failed_step="manual_description",
                    extraction_method="manual_description",
                    action=requested_upload_action,
                    error_code=str(vision_debug.get("error_code") or "OPENAI_REQUEST_FAILED"),
                    technical_message=technical_message,
                    debug=vision_debug,
                )

            extraction_method = "manual_description"
            json_data = inferred_json
            import_object["manual_description"] = manual_description
            import_object["recipe_json"] = json_data
        elif import_source_type == "image":
            try:
                page_text, detected_food_photo, contains_written_recipe, read_error = read_upload_image_text(
                    recipe_url,
                    upload_path,
                    mime_type,
                    filename,
                )
            except Exception as exc:
                error_code, error_message = classify_vision_ai_exception(exc)
                openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
                raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_IMAGE_READ_ERROR.txt"
                raw_error_path.write_text(str(exc), encoding="utf-8")
                print(
                    "[recipe_import] action=image_read_exception "
                    f"model={resolve_vision_model()} "
                    f"exception_type={type(exc).__name__} "
                    f"openai_error_code={openai_error_code or 'n/a'} "
                    f"openai_error_param={openai_error_param or 'n/a'} "
                    f"final_error_code={error_code}"
                )
                return build_upload_failure_result(
                    import_object,
                    error_message,
                    failed_step="read",
                    extraction_method="ocr_text",
                    action=requested_upload_action,
                    error_code=error_code,
                    technical_message=str(exc),
                    debug={
                        "error_code": error_code,
                        "model": resolve_vision_model(),
                        "action": requested_upload_action,
                        "openai_error_code": openai_error_code,
                        "openai_error_param": openai_error_param,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                )
            import_object["extracted_text"] = page_text
            import_object["detected_food_photo"] = detected_food_photo
            import_object["contains_written_recipe"] = bool(contains_written_recipe)

            extraction_method = "ocr_text"

            if not page_text.strip() or not contains_written_recipe:
                no_text_message = "No visible recipe text found."
                debug_payload = build_vision_debug(uploaded_file_path=str(upload_path), filename=filename, mime_type=mime_type)
                debug_payload.update({
                    "action": requested_upload_action,
                    "image_uploaded": True,
                    "vision_request_sent": True,
                    "vision_response_received": True,
                    "json_parse_success": True,
                    "recipe_creation_success": False,
                    "error_code": "NO_VISIBLE_RECIPE_TEXT",
                    "error_message": no_text_message,
                    "technical_message": NO_READABLE_UPLOAD_TEXT_ERROR,
                    "model": resolve_vision_model(),
                    "model_source": resolve_vision_model_source(),
                })
                return {
                    "success": True,
                    "ok": True,
                    "read_text_only": True,
                    "no_visible_recipe_text": True,
                    "error": "",
                    "error_code": "NO_VISIBLE_RECIPE_TEXT",
                    "error_message": no_text_message,
                    "technical_message": NO_READABLE_UPLOAD_TEXT_ERROR,
                    "failed_step": "",
                    "ingredients": [],
                    "import_source": import_object,
                    "source_type": import_source_type,
                    "source_type_label": upload_source_type_label(import_source_type),
                    "source_name": filename,
                    "source_url": recipe_url,
                    "uploaded_file_path": str(upload_path),
                    "extracted_text": page_text,
                    "detected_food_photo": bool(detected_food_photo),
                    "contains_written_recipe": bool(contains_written_recipe),
                    "extraction_method": extraction_method,
                    "extraction_mode": extraction_method,
                    "extraction_mode_label": "OCR",
                    "model_used": resolve_vision_model(),
                    "model": resolve_vision_model(),
                    "model_source": resolve_vision_model_source(),
                    "action": requested_upload_action,
                    "debug": debug_payload,
                    "available_actions": [
                        "read_text",
                        "describe_recipe",
                        "generate_recipe_from_image",
                    ],
                }

            prompt_text = build_prompt(
                recipe_url,
                page_text[:MAX_PAGE_TEXT_CHARS],
                "This text was read from an uploaded image. Extract only the written recipe content.",
            )
            response_text = send_prompt_to_openai(prompt_text)
        elif upload_is_word_document(mime_type, filename, upload_path):
            if upload_suffix == ".docx":
                try:
                    page_text = extract_text_from_generic_document(upload_path, filename)
                except Exception as exc:
                    page_text = ""
                    print(
                        "[recipe_import] action=upload_word_text_failed "
                        f"file={filename!r} error={exc}"
                    )

            converted_pdf_path, page_text = convert_word_upload_to_pdf(
                recipe_url,
                upload_path,
                filename,
                page_text=page_text,
            )
            extraction_filename = f"{Path(filename).stem or 'uploaded-recipe'}.pdf"
            upload_path_for_review = converted_pdf_path
            mime_type_for_review = "application/pdf"
            filename_for_review = extraction_filename
            extraction_method = "document_text"

            if page_text.strip():
                prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
                response_text = send_prompt_to_openai(prompt_text)
            else:
                prompt_text = build_upload_prompt(recipe_url, extraction_filename)
                response_text = send_file_prompt_to_openai(
                    prompt_text,
                    converted_pdf_path,
                    "application/pdf",
                    extraction_filename,
                )
            import_object["extracted_text"] = page_text
        elif import_source_type == "text":
            page_text = upload_path.read_text(encoding="utf-8", errors="ignore")
            import_object["extracted_text"] = page_text

            if not page_text.strip():
                return build_upload_failure_result(
                    import_object,
                    NO_READABLE_UPLOAD_TEXT_ERROR,
                    failed_step="read",
                    extraction_method="document_text",
                    action=requested_upload_action,
                    error_code="OPENAI_REQUEST_FAILED",
                    technical_message=NO_READABLE_UPLOAD_TEXT_ERROR,
                )

            prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
            response_text = send_prompt_to_openai(prompt_text)
            extraction_method = "document_text"
        elif import_source_type == "pdf":
            try:
                page_text = extract_text_from_pdf(upload_path)
            except Exception as exc:
                page_text = ""
                print(
                    "[recipe_import] action=upload_pdf_text_failed "
                    f"file={filename!r} error={exc}"
                )
            import_object["extracted_text"] = page_text
            extraction_method = "document_text"

            if page_text.strip():
                prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
                response_text = send_prompt_to_openai(prompt_text)
            elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
                prompt_text = build_upload_prompt(recipe_url, filename)
                response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
            else:
                return build_upload_failure_result(
                    import_object,
                    NO_READABLE_UPLOAD_TEXT_ERROR,
                    failed_step="read",
                    extraction_method=extraction_method,
                    action=requested_upload_action,
                    error_code="OPENAI_REQUEST_FAILED",
                    technical_message=NO_READABLE_UPLOAD_TEXT_ERROR,
                )
        else:
            page_text = extract_text_from_generic_document(upload_path, filename)
            import_object["extracted_text"] = page_text

            if not page_text.strip():
                return build_upload_failure_result(
                    import_object,
                    NO_READABLE_UPLOAD_TEXT_ERROR,
                    failed_step="read",
                    extraction_method="document_text",
                    action=requested_upload_action,
                )

            prompt_text = build_prompt(recipe_url, page_text[:MAX_PAGE_TEXT_CHARS])
            response_text = send_prompt_to_openai(prompt_text)
            extraction_method = "document_text"

        if json_data is None:
            json_data, parse_error = parse_json_text_response(recipe_url, response_text)
            if parse_error:
                if extraction_method in {"image_estimate", "manual_description"}:
                    return build_upload_failure_result(
                        import_object,
                        NO_UPLOAD_INGREDIENTS_ERROR,
                        failed_step="manual_description",
                        extraction_method=extraction_method,
                        action=requested_upload_action,
                        error_code="OPENAI_REQUEST_FAILED",
                        technical_message=parse_error,
                    )
                print(
                    "[recipe_import] action=upload_extract_parse_failed "
                    f"source_type={import_source_type} file={filename!r} error={parse_error}"
                )
                return build_upload_failure_result(
                    import_object,
                    NO_UPLOAD_INGREDIENTS_ERROR,
                    failed_step="extract",
                    extraction_method=extraction_method,
                    action=requested_upload_action,
                    error_code="OPENAI_REQUEST_FAILED",
                    technical_message=parse_error,
                )

        import_object["recipe_json"] = json_data
        if not structured_recipe_data_is_usable(json_data):
            if extraction_method in {"image_estimate", "manual_description"}:
                return build_upload_failure_result(
                    import_object,
                    NO_UPLOAD_INGREDIENTS_ERROR,
                    failed_step="manual_description",
                    extraction_method=extraction_method,
                    action=requested_upload_action,
                    error_code="OPENAI_REQUEST_FAILED",
                    technical_message=NO_UPLOAD_INGREDIENTS_ERROR,
                )
            print(
                "[recipe_import] action=upload_extract_no_recipe_data "
                f"source_type={import_source_type} file={filename!r} "
                f"has_ingredients={bool(json_data.get('ingredients'))} "
                f"has_instructions={bool(json_data.get('instructions'))}"
            )
            return build_upload_failure_result(
                import_object,
                NO_UPLOAD_INGREDIENTS_ERROR,
                failed_step="extract",
                extraction_method=extraction_method,
                action=requested_upload_action,
            )

        if extraction_method in {"image_estimate", "manual_description"}:
            extraction_confidence = parse_confidence(json_data.get("extraction_confidence"))
            if extraction_confidence is None:
                extraction_confidence = 0.5
            json_data["extraction_confidence"] = extraction_confidence

            parsed_title = clean_recipe_text(
                json_data.get("recipe_title") or json_data.get("display_name") or ""
            )
            if extraction_method == "manual_description":
                json_data["recipe_title"] = (
                    f"Estimated from photo/description: {parsed_title}"
                    if parsed_title
                    else "Estimated from photo/description"
                )
                json_data["display_name"] = json_data["recipe_title"]
            elif extraction_method == "image_estimate":
                json_data["recipe_title"] = (
                    f"Estimated from food photo: {parsed_title}"
                    if parsed_title
                    else "Estimated from food photo"
                )
                json_data["display_name"] = json_data["recipe_title"]
            else:
                json_data["recipe_title"] = "Estimated recipe from food photo"
                json_data["display_name"] = "Estimated recipe from food photo"

            json_data["source_type"] = "image"
            json_data["extraction_mode"] = extraction_method
            json_data["ai_inferred"] = True
            json_data.setdefault("extracted_text", page_text)
            normalize_extracted_recipe_identity(json_data)
        else:
            title = determine_upload_recipe_title(
                recipe_url,
                upload_path_for_review,
                mime_type_for_review,
                filename_for_review,
                page_text,
            )
            if title:
                json_data["recipe_title"] = title
            json_data.setdefault("ai_inferred", False)
            json_data["source_type"] = (
                "photo_text" if extraction_method == "ocr_text" else "document_text"
            )
            if extraction_method == "ocr_text":
                json_data["extraction_mode"] = "ocr_text"

        json_data["import_source_type"] = import_source_type
        json_data["import_source_name"] = filename
        json_data["extracted_text"] = page_text
        json_data.setdefault("extraction_confidence", 0.90)

        json_data["source_url"] = recipe_url
        if json_data.get("ai_inferred") is None:
            json_data["ai_inferred"] = False

        cover_image = extract_recipe_cover_image_from_upload(
            upload_path,
            mime_type,
            filename,
            recipe_url,
            fallback_alt=json_data.get("recipe_title") or filename,
        )
        if cover_image:
            json_data["cover_image"] = cover_image
        if extraction_method not in {"image_estimate", "manual_description"}:
            merge_missing_upload_ingredients(
                recipe_url,
                json_data,
                upload_path_for_review,
                mime_type_for_review,
                filename_for_review,
                page_text,
            )

        json_data["extraction_method"] = extraction_method
        archive_uploaded_recipe_pdf(
            recipe_url,
            upload_path_for_review,
            mime_type_for_review,
            filename_for_review,
            page_text=page_text,
            recipe_title=json_data.get("recipe_title") or "",
        )
        save_extracted_recipe_json(recipe_url, json_data)

        result = build_extract_result(recipe_url, json_data, extraction_method)
        import_object["recipe_json"] = json_data
        result["import_source"] = import_object
        result["source_type"] = import_source_type
        result["source_type_label"] = upload_source_type_label(import_source_type)
        result["source_name"] = filename
        result["uploaded_file_path"] = str(upload_path)
        result["extracted_text"] = page_text
        result["detected_food_photo"] = bool(import_object.get("detected_food_photo"))
        return result
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_UPLOAD_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")
        error_code, error_message = classify_vision_ai_exception(exc)
        openai_error_code, error_param = get_openai_error_code_and_param(exc)
        request_model = resolve_vision_model() if import_source_type == "image" else MODEL
        print(
            "[recipe_import] action=upload_extract_exception "
            f"source_type={import_source_type} action={requested_upload_action} "
            f"model={request_model} file={filename!r} error={exc}"
        )
        print(
            f"[recipe_import] final_error_code={error_code} "
            f"final_error_message={error_message} "
            f"exception_type={type(exc).__name__} "
            f"openai_error_code={openai_error_code} "
            f"error_param={error_param}"
        )

        return build_upload_failure_result(
            import_object,
            error_message or f"Upload extraction failed: {exc}",
            failed_step="extract",
            extraction_method=extraction_method,
            action=requested_upload_action,
            error_code=error_code,
            technical_message=str(exc),
            debug={
                "model": resolve_vision_model() if import_source_type == "image" else MODEL,
                "action": requested_upload_action,
                "openai_error_code": openai_error_code,
                "openai_error_param": error_param,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        )


def upload_can_use_openai_file_input(mime_type, filename, upload_path):
    suffix = upload_file_suffix(filename, upload_path)

    if mime_type in OPENAI_FILE_INPUT_MIME_TYPES:
        return True

    return suffix == ".pdf"


def extract_recipe_cover_image_from_upload(upload_path, mime_type, filename, recipe_url, fallback_alt=""):
    if not str(mime_type or "").startswith("image/"):
        return {}

    try:
        relative_path = upload_path.resolve().relative_to(EXTRACTOR_FOLDER.resolve())
    except ValueError:
        return {}

    return normalize_recipe_cover_image(
        {
            "path": str(relative_path).replace("\\", "/"),
            "mime_type": mime_type,
            "alt": fallback_alt or Path(filename or "Uploaded recipe").stem,
            "source": "uploaded_image",
        },
        base_url=recipe_url,
    )


def recipe_cover_image_file_path(cover_image):
    if not isinstance(cover_image, dict):
        return None

    stored_path = clean_cover_image_text(cover_image.get("path"))

    if not stored_path:
        return None

    candidate = Path(stored_path)

    if not candidate.is_absolute():
        candidate = EXTRACTOR_FOLDER / candidate

    try:
        candidate = candidate.resolve()
        base = EXTRACTOR_FOLDER.resolve()
    except Exception:
        return None

    if candidate != base and base not in candidate.parents:
        return None

    if not candidate.is_file():
        return None

    return candidate


def upload_is_word_document(mime_type, filename, upload_path):
    suffix = upload_file_suffix(filename, upload_path)
    normalized_mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()

    return suffix in WORD_DOCUMENT_SUFFIXES or normalized_mime_type in WORD_DOCUMENT_MIME_TYPES


def convert_word_upload_to_pdf(recipe_url, upload_path, filename, page_text=""):
    pdf_path = UPLOAD_FOLDER / f"{upload_path.name}_converted.pdf"
    suffix = upload_file_suffix(filename, upload_path)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if convert_word_upload_with_libreoffice(upload_path, filename, pdf_path):
        return pdf_path, page_text

    if convert_word_upload_with_microsoft_word(upload_path, filename, pdf_path):
        return pdf_path, page_text

    if not page_text.strip() and suffix == ".docx":
        page_text = extract_text_from_generic_document(upload_path, filename)

    if not page_text.strip():
        raise RuntimeError(
            "Could not convert that Word document to PDF. Install Microsoft Word or LibreOffice, "
            "or upload a .docx file with readable text."
        )

    html_text = build_upload_text_pdf_html(
        page_text,
        filename,
        recipe_title=Path(filename or "Uploaded Recipe").stem,
    )
    saved_path = write_recipe_page_pdf(recipe_url, html_text, None, pdf_path)
    return saved_path, page_text


def convert_word_upload_with_libreoffice(upload_path, filename, pdf_path):
    converter = shutil.which("soffice") or shutil.which("libreoffice")

    if not converter:
        return False

    source_path, cleanup_source = prepare_word_conversion_source(upload_path, filename)
    expected_pdf_path = pdf_path.parent / f"{source_path.stem}.pdf"

    try:
        completed = subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_path.parent),
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

        if completed.returncode != 0 or not expected_pdf_path.exists():
            return False

        if expected_pdf_path.resolve() != pdf_path.resolve():
            pdf_path.unlink(missing_ok=True)
            expected_pdf_path.replace(pdf_path)

        return pdf_path.exists() and pdf_path.stat().st_size > 0
    except Exception:
        return False
    finally:
        if cleanup_source:
            source_path.unlink(missing_ok=True)


def convert_word_upload_with_microsoft_word(upload_path, filename, pdf_path):
    try:
        import win32com.client
    except Exception:
        return False

    source_path, cleanup_source = prepare_word_conversion_source(upload_path, filename)
    word_app = None
    document = None

    try:
        word_app = win32com.client.DispatchEx("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        document = word_app.Documents.Open(str(source_path.resolve()), ReadOnly=True)

        try:
            document.SaveAs2(str(pdf_path.resolve()), FileFormat=17)
        except AttributeError:
            document.SaveAs(str(pdf_path.resolve()), FileFormat=17)

        return pdf_path.exists() and pdf_path.stat().st_size > 0
    except Exception:
        return False
    finally:
        if document:
            try:
                document.Close(False)
            except Exception:
                pass

        if word_app:
            try:
                word_app.Quit()
            except Exception:
                pass

        if cleanup_source:
            source_path.unlink(missing_ok=True)


def prepare_word_conversion_source(upload_path, filename):
    suffix = upload_file_suffix(filename, upload_path)

    if upload_path.suffix.lower() == suffix:
        return upload_path, False

    source_path = upload_path.with_name(f"{upload_path.name}{suffix}")
    shutil.copyfile(upload_path, source_path)
    return source_path, True


def infer_safe_upload_suffix(value):
    name = Path(str(value or "")).name.lower()
    match = re.search(r"_(jpe?g|png|webp|gif|heic|heif|bmp|tiff?|avif|pdf|txt|md|docx?|html?)$", name)

    if not match:
        return ""

    suffix = match.group(1)
    if suffix == "jpeg":
        suffix = "jpg"
    return f".{suffix}"


def upload_image_mime_type_from_suffix(suffix):
    normalized_suffix = str(suffix or "").strip().lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".avif": "image/avif",
    }.get(normalized_suffix, "")


def upload_file_suffix(filename, upload_path):
    return (
        Path(filename or "").suffix.lower()
        or upload_path.suffix.lower()
        or infer_safe_upload_suffix(filename)
        or infer_safe_upload_suffix(upload_path)
    )


def normalize_upload_mime_type(mime_type, filename, upload_path):
    guessed_type = mimetypes.guess_type(filename or str(upload_path))[0]
    if not guessed_type:
        suffix = upload_file_suffix(filename, upload_path)
        if suffix:
            guessed_type = (
                mimetypes.guess_type(f"uploaded{suffix}")[0]
                or upload_image_mime_type_from_suffix(suffix)
            )

    if not mime_type or mime_type == "application/octet-stream":
        return guessed_type or "application/octet-stream"

    return mime_type


def build_upload_prompt(recipe_url, filename):
    return build_prompt(
        recipe_url,
        f"""
This recipe was uploaded as an image or document named {filename}.

Read the visible recipe content from the uploaded file. Extract the recipe title, servings,
ingredients, equipment, instructions, and nutrition if visible.

If the upload is a grocery package, handwritten note, printed recipe card, cookbook page,
screenshot, or recipe photo, use only the visible text. Do not invent hidden ingredients.
""",
    )


def build_upload_image_text_prompt(filename):
    return f"""
Read this uploaded image named {filename}.

Return ONLY valid JSON in this shape:
{{
  "extracted_text": "all readable recipe text from the image, preserving line breaks where useful",
  "detected_food_photo": false,
  "contains_written_recipe": false
}}

Rules:
- Transcribe readable written text only.
- If the image shows prepared food or a meal, set detected_food_photo to true.
- If the image has ingredient lines, directions, recipe title text, cookbook text, or recipe-card text, set contains_written_recipe to true.
- If there is no readable written recipe text, set extracted_text to an empty string.
- Do not infer a recipe from the food image.
"""


def read_upload_image_text(recipe_url, upload_path, mime_type, filename):
    response_text = send_image_prompt_to_openai(
        build_upload_image_text_prompt(filename),
        upload_path,
        mime_type,
        action="read_text",
    )
    data, parse_error = parse_json_text_response(recipe_url, response_text)
    if parse_error:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_IMAGE_READ_PARSE_ERROR.txt"
        raw_error_path.write_text(parse_error, encoding="utf-8")
        raw_response_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_IMAGE_READ_RESPONSE.txt"
        raw_response_path.write_text(response_text, encoding="utf-8")
        raise RuntimeError(f"Unable to parse image text response: {parse_error}")

    if not isinstance(data, dict):
        raise RuntimeError("Image text response was not a JSON object.")

    extracted_text = str(data.get("extracted_text") or "").strip()
    detected_food_photo = bool(data.get("detected_food_photo"))
    contains_written_recipe = bool(data.get("contains_written_recipe"))
    return extracted_text, detected_food_photo, contains_written_recipe, ""


def determine_upload_recipe_title(recipe_url, upload_path, mime_type, filename, page_text=""):
    prompt_text = build_upload_title_prompt(recipe_url, filename)

    try:
        if mime_type.startswith("image/"):
            response_text = send_image_prompt_to_openai(prompt_text, upload_path, mime_type)
        elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
            response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
        elif page_text.strip():
            response_text = send_prompt_to_openai(
                build_upload_title_prompt(recipe_url, filename, page_text[:MAX_PAGE_TEXT_CHARS])
            )
        else:
            return ""

        data = json.loads(clean_json_response(response_text))
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_TITLE_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")
        return ""

    return normalize_recipe_title(data.get("recipe_title") or data.get("title") or "")


def build_upload_title_prompt(recipe_url, filename, page_text=""):
    visible_text = f"\nReadable text:\n{page_text}\n" if page_text else ""

    return f"""
This recipe was uploaded as {filename}.

Read the entire uploaded document and determine the primary recipe title/name.

Rules:
- Use the title printed in the document when one is visible.
- Do not use the upload filename, random id, URL, or file extension as the title.
- If the document contains multiple recipes, choose the title that best matches the main ingredient list and instructions being extracted.
- Return null if no recipe title is visible or strongly implied.
{visible_text}
Return ONLY valid JSON in this shape:
{{
  "recipe_title": "Recipe title or null"
}}
"""


def normalize_recipe_title(value):
    title = re.sub(r"\s+", " ", str(value or "").strip())

    if not title or title.lower() in {"none", "null", "unknown", "untitled"}:
        return ""

    return title


def merge_missing_upload_ingredients(recipe_url, json_data, upload_path, mime_type, filename, page_text=""):
    raw_lines = audit_upload_ingredient_lines(
        recipe_url,
        upload_path,
        mime_type,
        filename,
        page_text,
    )

    if not raw_lines:
        return

    existing_keys = {
        normalize_ingredient_key(normalize_ingredient_for_shopping_list(
            item.get("ingredient") or item.get("original_text") or ""
        ))
        for item in json_data.get("ingredients", [])
        if isinstance(item, dict)
    }
    existing_original_keys = {
        normalize_ingredient_key(normalize_ingredient_for_shopping_list(
            item.get("original_text") or item.get("ingredient") or ""
        ))
        for item in json_data.get("ingredients", [])
        if isinstance(item, dict)
    }
    all_existing_keys = existing_keys | existing_original_keys
    missing_rows = []

    for row in build_structured_ingredients(raw_lines):
        key = normalize_ingredient_key(
            normalize_ingredient_for_shopping_list(row.get("ingredient") or row.get("original_text") or "")
        )

        if not key or ingredient_key_matches_existing(key, all_existing_keys):
            continue

        missing_rows.append(row)
        all_existing_keys.add(key)

    if missing_rows:
        json_data.setdefault("ingredients", []).extend(missing_rows)
        normalize_extracted_ingredient_fields(json_data)


def ingredient_key_matches_existing(candidate_key, existing_keys):
    if candidate_key in existing_keys:
        return True

    for existing_key in existing_keys:
        if candidate_key in alternative_ingredient_key_parts(existing_key):
            return True

        if existing_key in alternative_ingredient_key_parts(candidate_key):
            return True

    return False


def alternative_ingredient_key_parts(key):
    return {
        normalize_ingredient_key(part)
        for part in re.split(r"\s+or\s+", str(key or ""), flags=re.IGNORECASE)
        if normalize_ingredient_key(part)
    }


def audit_upload_ingredient_lines(recipe_url, upload_path, mime_type, filename, page_text=""):
    prompt_text = build_upload_ingredient_audit_prompt(recipe_url, filename)

    try:
        if mime_type.startswith("image/"):
            response_text = send_image_prompt_to_openai(prompt_text, upload_path, mime_type)
        elif upload_can_use_openai_file_input(mime_type, filename, upload_path):
            response_text = send_file_prompt_to_openai(prompt_text, upload_path, mime_type, filename)
        elif page_text.strip():
            response_text = send_prompt_to_openai(
                build_upload_ingredient_audit_prompt(recipe_url, filename, page_text[:MAX_PAGE_TEXT_CHARS])
            )
        else:
            return []

        data = json.loads(clean_json_response(response_text))
    except Exception as exc:
        raw_error_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_INGREDIENT_AUDIT_ERROR.txt"
        raw_error_path.write_text(str(exc), encoding="utf-8")
        return []

    ingredients = data.get("ingredients", [])

    if not isinstance(ingredients, list):
        return []

    return [
        str(item or "").strip()
        for item in ingredients
        if str(item or "").strip()
    ]


def build_upload_ingredient_audit_prompt(recipe_url, filename, page_text=""):
    visible_text = f"\nReadable text:\n{page_text}\n" if page_text else ""

    return f"""
This recipe was uploaded as {filename}.

Audit the uploaded recipe for visible ingredient lines only. Return every visible ingredient line exactly as written,
including ingredients that may need food-rule review such as corn syrup, food dyes, preservatives, or artificial ingredients.

Do not skip ingredients because they are unhealthy, optional, repeated, unusual, or visually separated from the main list.
Do not infer ingredients from instructions. Use only visible ingredient list lines.
{visible_text}
Return ONLY valid JSON in this shape:
{{
  "ingredients": [
    "1 cup Corn syrup"
  ]
}}
"""


def extract_text_from_pdf(upload_path):
    try:
        from PyPDF2 import PdfReader
    except Exception as exc:
        raise RuntimeError("PDF support requires PyPDF2 to be installed.") from exc

    reader = PdfReader(str(upload_path))
    page_text = []

    for page in reader.pages:
        page_text.append(page.extract_text() or "")

    return "\n".join(page_text)


def extract_text_from_generic_document(upload_path, filename=None):
    suffix = upload_file_suffix(filename, upload_path)

    if suffix == ".docx":
        return extract_text_from_docx(upload_path)

    text = upload_path.read_text(encoding="utf-8", errors="ignore")

    if suffix in {".html", ".htm"}:
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text("\n")

    if suffix == ".rtf":
        text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
        text = re.sub(r"[{}]", " ", text)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)

    return text


def extract_text_from_docx(upload_path):
    try:
        with zipfile.ZipFile(upload_path) as archive:
            xml_text = archive.read("word/document.xml")
    except Exception as exc:
        raise RuntimeError("Could not read text from that Word document.") from exc

    root = ET.fromstring(xml_text)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []

    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
        ).strip()

        if text:
            paragraphs.append(text)

    return "\n".join(paragraphs)


def build_extract_result(recipe_url, json_data, extraction_method):
    json_data = json_data if isinstance(json_data, dict) else {}
    ingredients = extract_ingredients_from_result(json_data)
    model_used = str(
        json_data.get("model_used")
        or json_data.get("model")
        or json_data.get("vision_request", {}).get("model")
        or MODEL
    ).strip() or str(MODEL)

    return {
        "success": True,
        "ok": True,
        "source_url": recipe_url,
        "display_name": json_data.get("display_name") or json_data.get("recipe_title"),
        "recipe_title": json_data.get("recipe_title"),
        "cover_image": json_data.get("cover_image") or {},
        "servings": json_data.get("servings"),
        "level": json_data.get("level"),
        "total_time": json_data.get("total_time"),
        "prep_time": json_data.get("prep_time"),
        "inactive_time": json_data.get("inactive_time"),
        "cook_time": json_data.get("cook_time"),
        "scaling": json_data.get("scaling"),
        "ingredients": ingredients,
        "equipment": json_data.get("equipment", []),
        "instructions": json_data.get("instructions", []),
        "nutrition": json_data.get("nutrition", {}),
        "raw": json_data,
        "source_type": json_data.get("source_type") or extraction_method,
        "ai_inferred": bool(json_data.get("ai_inferred")),
        "extraction_confidence": json_data.get("extraction_confidence"),
        "confidence_notes": json_data.get("confidence_notes") or [],
        "image_analysis_notes": json_data.get("image_analysis_notes"),
        "visible_ingredients": json_data.get("visible_ingredients") or [],
        "inferred_ingredients": json_data.get("inferred_ingredients") or [],
        "extraction_method": extraction_method,
        "extraction_mode": json_data.get("extraction_mode") or extraction_method,
        "model_used": model_used,
        "debug": {
            "model": model_used,
        },
    }


def normalize_ingredient_key(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def normalize_ingredient_for_shopping_list(text):
    value = clean_recipe_text(text)

    if not value:
        return ""

    value = (
        value.replace("Â", "")
        .replace("Ľ", "¼")
        .replace("˝", "½")
        .replace("ľ", "¾")
        .replace("â…›", "⅛")
    )
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\boptional\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()

    alternative_value = normalize_alternative_shopping_ingredient(value)
    if alternative_value:
        return alternative_value

    value = value.split(",", 1)[0].strip()

    alternative_value = normalize_alternative_shopping_ingredient(value)
    if alternative_value:
        return alternative_value

    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
    unit_pattern = (
        r"(?:cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?)"
    )

    value = re.sub(
        rf"^{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\b\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"^{quantity_pattern}\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"^{unit_pattern}\b\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(r"\s+", " ", value).strip()
    value = canonicalize_shopping_ingredient(value)
    return singularize_shopping_ingredient(value)


def canonicalize_shopping_ingredient(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    value = re.sub(r"^of\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:bunch|bunches)\s+(?=\w)", "", value, flags=re.IGNORECASE)
    return value.strip()


def singularize_shopping_ingredient(value):
    normalized = normalize_ingredient_key(value)
    singular_names = {
        "eggs": "egg",
        "lemons": "lemon",
        "limes": "lime",
        "onions": "onion",
        "tomatoes": "tomato",
        "potatoes": "potato",
        "carrots": "carrot",
        "cloves": "clove",
    }

    return singular_names.get(normalized, value)


def normalize_alternative_shopping_ingredient(value):
    value = re.sub(r",\s+or\s+", " or ", str(value or "").strip(), flags=re.IGNORECASE)
    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
    unit_pattern = (
        r"(?:cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?)"
    )
    match = re.match(
        rf"^(?:{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\s+)?"
        rf"(?P<first>.+?)\s+or\s+"
        rf"(?:{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\s+)?"
        rf"(?P<second>.+)$",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    first = strip_leading_amount(match.group("first"))
    second = strip_leading_amount(match.group("second"))

    if not first or not second:
        return ""

    return f"{first} OR {second}"


def strip_leading_amount(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    quantity_pattern = rf"(?:\d+(?:[./]\d+)?|\d+\s+\d+/\d+|[{FRACTION_CHARS}])+"
    unit_pattern = (
        r"(?:cups?|c|teaspoons?|tsp\.?|tablespoons?|tbsp\.?|pounds?|lbs?\.?|"
        r"ounces?|oz\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
        r"pinch|pinches|dash|dashes|cloves?|sticks?)"
    )

    value = re.sub(
        rf"^{quantity_pattern}(?:\s*(?:-|to)\s*{quantity_pattern})?\s+{unit_pattern}\b\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"^{quantity_pattern}\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip()


def extract_recipe_from_url(recipe_url, progress_callback=None):
    recipe_url = str(recipe_url or "").strip()

    if not recipe_url:
        return {
            "ok": False,
            "error": "Missing recipe URL.",
            "ingredients": [],
        }

    try:
        def report(message, summary=None):
            if progress_callback:
                progress_callback(message, summary)

        print("\n==================================================")
        print("Recipe 1/1")
        print(recipe_url)
        print("==================================================")

        if is_social_video_url(recipe_url):
            return extract_recipe_from_social_video_url(recipe_url, progress_callback=report)

        report(
            "downloading webpage HTML...",
            "Opening the recipe URL and saving the page HTML.",
        )
        html_text, page_text = fetch_recipe_page(recipe_url, progress_callback=report)

        if not page_text:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "No page text found.",
                "ingredients": [],
            }

        structured_json_data = extract_recipe_from_structured_data(recipe_url, html_text)

        force_openai = os.getenv("FORCE_OPENAI_RECIPE_EXTRACTION") == "1"

        if structured_recipe_data_is_usable(structured_json_data) and not force_openai:
            normalize_extracted_ingredient_fields(structured_json_data)
            normalize_extracted_equipment_fields(structured_json_data)
            save_extracted_recipe_json(recipe_url, structured_json_data)
            print("Structured recipe data found; using recipe card for fast extraction.")
            report(
                "recipe card found - extracted without OpenAI API fallback.",
                "Recipe-card HTML was enough to extract ingredients and instructions.",
            )
            return build_extract_result(recipe_url, structured_json_data, "structured_data")

        if structured_json_data:
            print("Structured recipe data found, but API extraction was forced.")

        if not os.getenv("OPENAI_API_KEY"):
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "Missing OPENAI_API_KEY environment variable.",
                "error_code": "OPENAI_API_KEY_MISSING",
                "error_message": "OPENAI_API_KEY is missing or invalid.",
                "technical_message": "Missing OPENAI_API_KEY environment variable.",
                "model": MODEL,
                "model_used": MODEL,
                "action": "read_text",
                "ingredients": [],
            }

        prompt_text = build_prompt(recipe_url, page_text)

        print("Sending to OpenAI API...")
        report(
            "sending webpage content to OpenAI API...",
            "No complete recipe card was found, so OpenAI is extracting from the page content.",
        )
        response_text = send_prompt_to_openai(prompt_text)

        raw_api_path = RAW_FOLDER / f"{safe_filename(recipe_url)}_API_RESPONSE.txt"
        raw_api_path.write_text(response_text, encoding="utf-8")

        success, json_data = save_json_response(recipe_url, response_text, html_text=html_text)

        if not success or not json_data:
            return {
                "ok": False,
                "source_url": recipe_url,
                "error": "Invalid JSON returned by OpenAI.",
                "ingredients": [],
            }

        return build_extract_result(recipe_url, json_data, "openai")

    except Exception as exc:
        error_code, error_message = classify_vision_ai_exception(exc)
        openai_error_code, openai_error_param = get_openai_error_code_and_param(exc)
        print(
            "[OpenAI] action=recipe-text-extraction "
            f"model={MODEL} exception_type={type(exc).__name__} "
            f"openai_error_code={openai_error_code or 'n/a'} "
            f"openai_error_param={openai_error_param or 'n/a'} "
            f"final_error_code={error_code}"
        )
        return {
            "ok": False,
            "source_url": recipe_url,
            "error": error_message or str(exc),
            "error_code": error_code,
            "error_message": error_message or str(exc),
            "technical_message": str(exc),
            "model": MODEL,
            "model_used": MODEL,
            "action": "read_text",
            "ingredients": [],
        }
