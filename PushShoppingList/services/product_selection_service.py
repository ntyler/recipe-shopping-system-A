import base64
import hashlib
import html as html_lib
import json
import math
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from concurrent.futures import as_completed
from datetime import datetime
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import quote_plus
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

from PushShoppingList.services.food_rules_service import annotate_product_food_rules
from PushShoppingList.services.food_rules_service import load_food_rules
from PushShoppingList.services.home_address_service import load_home_address
from PushShoppingList.services.item_state_service import load_item_state
from PushShoppingList.services.item_state_service import save_item_store
from PushShoppingList.services.recipe_ingredient_service import load_recipe_ingredients
from PushShoppingList.services.recipe_quantity_service import format_quantity_display
from PushShoppingList.services.recipe_quantity_service import load_saved_recipe_output
from PushShoppingList.services.recipe_quantity_service import scale_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_quantity
from PushShoppingList.services.recipe_url_service import normalize_recipe_url_key
from PushShoppingList.services.recipe_url_service import recipe_url_rows
from PushShoppingList.services.rules_display_service import load_rules_display
from PushShoppingList.services.shopping_list_service import load_items
from PushShoppingList.services.store_settings_service import load_store_settings


BASE_DIR = Path(__file__).resolve().parent
PRODUCT_CHOICES_FILE = BASE_DIR / "recipe-extractor" / "data" / "product_choices.json"
PRODUCT_RESULTS_FILE = BASE_DIR / "recipe-extractor" / "data" / "product_results.json"
PRODUCT_PROGRESS_FILE = BASE_DIR / "recipe-extractor" / "data" / "product_progress.json"
PRODUCT_RENDERED_HTML_DIR = BASE_DIR / "recipe-extractor" / "data" / "raw" / "product_pages"
PRODUCT_PROMPTS_DIR = BASE_DIR / "recipe-extractor" / "data" / "raw" / "product_prompts"
PRODUCT_BROWSER_PROFILES_DIR = BASE_DIR / "recipe-extractor" / "data" / "browser_profiles"
PRODUCT_CHOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
PRODUCT_RENDERED_HTML_DIR.mkdir(parents=True, exist_ok=True)
PRODUCT_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
PRODUCT_BROWSER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

REQUEST_HEADERS = {
    "User-Agent": "PushShoppingList/1.0 local product finder",
    "Accept-Language": "en-US,en;q=0.9",
}
PRICE_PATTERN = re.compile(r"\$\s*\d+(?:,\d{3})*(?:\.\d{2})?")
MEIJER_PRODUCT_URL_PATTERN = re.compile(r"https://www\.meijer\.com/shopping/product/[^)\s]+", re.IGNORECASE)
PRODUCT_PROGRESS_LOCK = threading.RLock()
PRODUCT_FINAL_STATES = {"done", "failed", "skipped", "cancelled"}
PRODUCT_BROWSER_FETCH_LOCK = threading.BoundedSemaphore(1)
PACKAGE_SIZE_PATTERN = re.compile(
    r"(?<![\w.])(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*(?:\d+\s*/\s*\d+|\d+(?:\.\d+)?))?\s*"
    r"(?:fl\s*oz|fluid\s*ounces?|ounces?|oz|pounds?|lbs?|lb|grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|"
    r"count|ct|pack|pk|each|ea)\b",
    re.IGNORECASE,
)
UNIT_PRICE_PATTERN = re.compile(
    r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:/|per)\s*"
    r"(fl\s*oz|fluid\s*ounce|ounce|oz|pound|lb|gram|g|kg|count|ct|each|ea|piece|pc)\b",
    re.IGNORECASE,
)
INGREDIENT_ALTERNATIVE_PATTERN = re.compile(r"\s+(?:and\s*/\s*or|and/or|or)\s+", re.IGNORECASE)
GROCERY_QUERY_REPLACEMENTS = [
    (re.compile(r"\byoghurt\b", re.IGNORECASE), "yogurt"),
    (re.compile(r"\bself[-\s]+raising\b", re.IGNORECASE), "self rising"),
]
QUALIFIER_TOKENS = {
    "fat",
    "free",
    "light",
    "lite",
    "low",
    "lower",
    "reduced",
    "regular",
    "nonfat",
    "non",
    "unsalted",
    "salted",
    "whole",
    "skim",
    "sugar",
    "zero",
}
TOKEN_ALIASES = {
    "yoghurt": "yogurt",
}
WHOLE_ITEM_FALLBACK_AVOID_TERMS = {
    "ade",
    "bar",
    "beverage",
    "cake",
    "cleaner",
    "cookie",
    "drink",
    "extract",
    "filling",
    "frosting",
    "gatorade",
    "juice",
    "lemonade",
    "limeade",
    "marinade",
    "mix",
    "scent",
    "seasoning",
    "soda",
    "tea",
}
WHOLE_ITEM_PACKAGE_TERMS = {
    "bag",
    "bunch",
    "each",
    "large",
    "package",
    "pkg",
    "whole",
}
EGG_PRODUCT_AVOID_TERMS = {
    "bites",
    "boiled",
    "cooked",
    "liquid",
    "omelet",
    "omelette",
    "patties",
    "plant",
    "plantbased",
    "substitute",
    "substitutes",
    "vegan",
    "whites",
}
EGG_PRODUCT_SHELL_TERMS = {
    "brown",
    "cage",
    "carton",
    "count",
    "ct",
    "dozen",
    "egg",
    "eggs",
    "free",
    "large",
    "organic",
    "shell",
    "white",
}
DETAIL_REQUIRED = os.getenv("PRODUCT_REQUIRE_DETAIL_PAGE", "1") != "0"
BROWSER_SEARCH_MODE = os.getenv("PRODUCT_SEARCH_BROWSER_MODE", "always").strip().lower()
PRODUCT_ANALYSIS_MODEL = os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL", os.getenv("OPENAI_RECIPE_MODEL", "gpt-4o-mini"))
PRODUCT_ANALYSIS_CLIENT = None
PRODUCT_AI_ANALYSIS_LOCK = threading.BoundedSemaphore(2)


def product_candidate_limit():
    try:
        configured = int(os.getenv("PRODUCT_CANDIDATE_LIMIT_PER_STORE", "96"))
    except (TypeError, ValueError):
        configured = 96

    return max(8, min(96, configured))


def product_image_embedding_enabled():
    return os.getenv("DISABLE_PRODUCT_IMAGE_EMBEDDING") != "1"


def product_prompt_include_embedded_images():
    return os.getenv("PRODUCT_PROMPT_INCLUDE_EMBEDDED_IMAGES") == "1"


def product_image_embed_max_bytes():
    try:
        configured = int(os.getenv("PRODUCT_IMAGE_EMBED_MAX_BYTES", "350000"))
    except (TypeError, ValueError):
        configured = 350000

    return max(50000, min(1500000, configured))


def product_image_embed_max_dimension():
    try:
        configured = int(os.getenv("PRODUCT_IMAGE_EMBED_MAX_DIMENSION", "320"))
    except (TypeError, ValueError):
        configured = 320

    return max(96, min(900, configured))


def product_image_embed_limit():
    try:
        configured = int(os.getenv("PRODUCT_IMAGE_EMBED_LIMIT_PER_STORE", "12"))
    except (TypeError, ValueError):
        configured = 12

    return max(0, min(product_candidate_limit(), configured))


def product_rendered_html_chatgpt_min_visible_cards():
    try:
        configured = int(os.getenv("PRODUCT_RENDERED_HTML_CHATGPT_MIN_VISIBLE_CARDS", "3"))
    except (TypeError, ValueError):
        configured = 3

    return max(0, min(product_candidate_limit(), configured))


def product_rendered_html_prompt_limit():
    try:
        configured = int(os.getenv("PRODUCT_RENDERED_HTML_PROMPT_CHARS", "120000"))
    except (TypeError, ValueError):
        configured = 120000

    return max(12000, min(500000, configured))


def product_browser_wait_seconds():
    try:
        configured = float(os.getenv("PRODUCT_BROWSER_WAIT_SECONDS", "14"))
    except (TypeError, ValueError):
        configured = 14

    return max(4, min(45, configured))


def product_rendered_scroll_max_passes():
    try:
        configured = int(os.getenv("PRODUCT_RENDERED_SCROLL_MAX_PASSES", "5"))
    except (TypeError, ValueError):
        configured = 5

    return max(1, min(18, configured))


def product_rendered_scroll_target_cards():
    try:
        configured = int(os.getenv("PRODUCT_RENDERED_SCROLL_TARGET_CARDS", "48"))
    except (TypeError, ValueError):
        configured = 48

    return max(8, min(product_candidate_limit(), configured))


def product_rendered_scroll_settle_seconds():
    try:
        configured = float(os.getenv("PRODUCT_RENDERED_SCROLL_SETTLE_SECONDS", "0.6"))
    except (TypeError, ValueError):
        configured = 0.6

    return max(0.2, min(2.0, configured))


def product_search_browser_enabled():
    if os.getenv("DISABLE_BROWSER_PRODUCT_SEARCH") == "1":
        return False

    return BROWSER_SEARCH_MODE not in {"0", "off", "false", "disabled"}


def should_open_store_search_page(has_request_candidates):
    if not product_search_browser_enabled():
        return False

    if BROWSER_SEARCH_MODE in {"fallback", "if-needed", "if_needed"}:
        return not has_request_candidates

    return True


def product_static_search_fallback_enabled():
    return os.getenv("PRODUCT_ALLOW_STATIC_PRODUCT_SEARCH_FALLBACK") == "1"


def localized_inventory_blocking_failure(reasons):
    text = normalize_match_text(" ".join(str(reason or "") for reason in reasons or []))
    blocking_phrases = [
        "localized inventory cannot be searched",
        "localized inventory cannot",
        "localized store session could not be proven",
        "nearest localized store could not be verified",
        "saved full address could not be geocoded",
        "refusing zip only",
        "refusing to treat this as localized inventory",
        "rendered page did not match the saved store context",
        "expected store zip",
        "store selector failure",
        "localization failure",
        "missing localization proof",
    ]
    return any(phrase in text for phrase in blocking_phrases)


def product_worker_count(total_downloads=None):
    try:
        configured = int(os.getenv("PRODUCT_SEARCH_WORKERS", "6"))
    except (TypeError, ValueError):
        configured = 6

    configured = max(1, min(16, configured))

    if total_downloads:
        return max(1, min(configured, int(total_downloads)))

    return configured


def load_item_quantity_context(items=None):
    item_keys = {
        normalize_item_key(item)
        for item in (items or load_items())
        if str(item or "").strip() and not is_section_header(item)
    }
    quantity_values = {}
    quantity_sources = {}
    recipe_meta = load_recipe_ingredients()

    for recipe in recipe_url_rows():
        recipe_quantity = normalize_recipe_quantity(recipe.get("quantity") or 1)
        recipe_data = load_saved_recipe_output(recipe.get("url", ""))
        if not recipe_data:
            continue

        meta = recipe_meta.get(normalize_recipe_url_key(recipe.get("url", "")), {})
        use_scaled_meta = quantities_match(meta.get("quantity", 1), recipe_quantity)
        scaled_ingredients = meta.get("scaled_ingredients", {}) if use_scaled_meta else {}
        recipe_label = recipe.get("name") or recipe_data.get("recipe_title") or "Recipe"

        for ingredient in recipe_data.get("ingredients", []) or []:
            if not isinstance(ingredient, dict):
                continue

            name = clean_text(ingredient.get("ingredient"))
            if not name:
                continue

            item_key = normalize_item_key(name)
            if item_keys and item_key not in item_keys:
                continue

            scaled_value = (
                scaled_ingredients.get(name)
                or scaled_ingredients.get(item_key)
                or {}
            )
            scaled_quantity = scaled_value.get("quantity") if isinstance(scaled_value, dict) else None
            scaled_unit = scaled_value.get("unit") if isinstance(scaled_value, dict) else None
            display = clean_text(scaled_value.get("display") if isinstance(scaled_value, dict) else "")
            unit = scaled_unit if scaled_unit is not None else ingredient.get("unit")

            if not display:
                display = format_quantity_display(
                    scaled_quantity or scale_quantity(ingredient.get("quantity"), recipe_quantity),
                    unit,
                )

            display = clean_text(display)
            if not display:
                continue

            quantity_values.setdefault(item_key, []).append(display)
            quantity_sources.setdefault(item_key, []).append({
                "label": recipe_label,
                "ingredient": name,
                "quantity": display,
                "recipe_quantity": recipe_quantity,
                "url": recipe.get("url", ""),
            })

    for item_key, state in load_item_state().items():
        normalized_key = normalize_item_key(item_key)
        if item_keys and normalized_key not in item_keys:
            continue

        if not isinstance(state, dict):
            continue

        manual_qty = clean_text(state.get("manual_qty"))
        if not manual_qty:
            continue

        quantity_values[normalized_key] = [manual_qty]
        quantity_sources[normalized_key] = [{
            "label": "Manual quantity",
            "ingredient": item_key,
            "quantity": manual_qty,
            "manual": True,
        }]

    return {
        item_key: {
            "display": summarized,
            "sources": quantity_sources.get(item_key, []),
        }
        for item_key, values in quantity_values.items()
        for summarized in [summarize_quantity_values(values)]
        if summarized
    }


def quantities_match(left, right):
    left_value = safe_float(left)
    right_value = safe_float(right)

    if left_value is None or right_value is None:
        return clean_text(left) == clean_text(right)

    return abs(left_value - right_value) < 0.000001


def summarize_quantity_values(values):
    cleaned = [
        clean_text(value)
        for value in values
        if clean_text(value)
    ]

    if not cleaned:
        return ""

    if len(cleaned) == 1:
        return cleaned[0]

    summed = sum_quantity_values(cleaned)
    if summed:
        return summed

    return " + ".join(unique_texts(cleaned))


def sum_quantity_values(values):
    parsed_values = [
        parse_display_quantity(value)
        for value in values
    ]

    if not parsed_values or any(value is None for value in parsed_values):
        return ""

    grouped = {}
    unit_order = []

    for value in parsed_values:
        unit = value.get("unit", "")
        if unit not in grouped:
            grouped[unit] = []
            unit_order.append(unit)
        grouped[unit].append(value)

    return " + ".join(
        format_quantity_range(
            sum(value["low"] for value in grouped[unit]),
            sum((value["high"] if value["high"] is not None else value["low"]) for value in grouped[unit])
            if any(value["high"] is not None for value in grouped[unit])
            else None,
            unit,
        )
        for unit in unit_order
    )


def parse_display_quantity(value):
    text = clean_quantity_text(value)

    if not text or " OR " in text.upper():
        return None

    match = re.match(
        r"^(?P<low>\d+(?:\s+\d+/\d+|/\d+)?)(?:\s*(?:-|to)\s*(?P<high>\d+(?:\s+\d+/\d+|/\d+)?))?(?:\s+(?P<unit>.+))?$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    low = parse_fraction_number(match.group("low"))
    high = parse_fraction_number(match.group("high")) if match.group("high") else None

    if low is None or (match.group("high") and high is None):
        return None

    return {
        "low": float(low),
        "high": float(high) if high is not None else None,
        "unit": normalize_unit(match.group("unit")),
    }


def clean_quantity_text(value):
    text = clean_text(value)
    text = text.replace("\u00c2\u00bc", "1/4").replace("\u00c2\u00bd", "1/2").replace("\u00c2\u00be", "3/4")
    replacements = {
        "\u00bc": "1/4",
        "\u00bd": "1/2",
        "\u00be": "3/4",
        "\u215b": "1/8",
        "\u2153": "1/3",
        "\u2154": "2/3",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def parse_fraction_number(value):
    text = clean_quantity_text(value)

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


def format_quantity_range(low, high, unit):
    if high is not None and abs(float(high) - float(low)) > 0.000001:
        quantity = f"{format_quantity_number(low)} to {format_quantity_number(high)}"
    else:
        quantity = format_quantity_number(low)

    return f"{quantity} {unit}".strip()


def format_quantity_number(value):
    number = Fraction(str(value)).limit_denominator(64)

    if number.denominator == 1:
        return str(number.numerator)

    whole = number.numerator // number.denominator
    remainder = number - whole

    if whole:
        return f"{whole} {remainder.numerator}/{remainder.denominator}"

    return f"{remainder.numerator}/{remainder.denominator}"


def apply_quantity_context_to_candidate(candidate, quantity_context):
    quantity_context = quantity_context or {}
    if not quantity_context.get("display"):
        return candidate

    candidate["requested_quantity"] = quantity_context.get("display", "")
    candidate["requested_quantity_context"] = {
        "display": quantity_context.get("display", ""),
        "sources": quantity_context.get("sources", [])[:6],
    }
    return candidate


def product_detail_limit():
    try:
        configured = int(os.getenv("PRODUCT_DETAIL_LIMIT_PER_STORE", "8"))
    except (TypeError, ValueError):
        configured = 8

    return max(1, min(16, configured))


def product_ai_analysis_limit():
    try:
        configured = int(os.getenv("PRODUCT_AI_ANALYSIS_LIMIT_PER_STORE", "1"))
    except (TypeError, ValueError):
        configured = 1

    return max(0, min(4, configured))


def product_ai_html_chars():
    try:
        configured = int(os.getenv("PRODUCT_AI_HTML_CHARS", "45000"))
    except (TypeError, ValueError):
        configured = 45000

    return max(8000, min(100000, configured))


def product_ai_text_chars():
    try:
        configured = int(os.getenv("PRODUCT_AI_TEXT_CHARS", "20000"))
    except (TypeError, ValueError):
        configured = 20000

    return max(4000, min(50000, configured))


def product_ai_browser_wait_seconds():
    try:
        configured = float(os.getenv("PRODUCT_AI_BROWSER_WAIT_SECONDS", "6"))
    except (TypeError, ValueError):
        configured = 6

    return max(2, min(15, configured))


def product_search_timeout_seconds():
    try:
        configured = float(os.getenv("PRODUCT_SEARCH_TIMEOUT_SECONDS", "900"))
    except (TypeError, ValueError):
        configured = 900

    return max(60, min(3600, configured))


def product_ai_analysis_enabled():
    if os.getenv("DISABLE_PRODUCT_CHATGPT_ANALYSIS") == "1":
        return False

    return bool(os.getenv("OPENAI_API_KEY"))


def product_reader_proxy_enabled():
    return os.getenv("DISABLE_PRODUCT_READER_PROXY") != "1"


def product_reader_proxy_url(target_url):
    prefix = os.getenv("PRODUCT_READER_PROXY_PREFIX", "https://r.jina.ai/http://r.jina.ai/http://")
    return prefix + str(target_url or "").strip()


def should_use_product_reader_proxy(url):
    if not product_reader_proxy_enabled():
        return False

    return "meijer.com/" in str(url or "").lower()


def product_final_selection_agent_enabled():
    if os.getenv("DISABLE_PRODUCT_FINAL_SELECTION_AGENT") == "1":
        return False

    return product_ai_analysis_enabled()


def product_final_selection_candidate_limit():
    try:
        configured = int(os.getenv("PRODUCT_FINAL_SELECTION_CANDIDATES", "96"))
    except (TypeError, ValueError):
        configured = 96

    return max(4, min(96, configured))


def get_product_analysis_client():
    global PRODUCT_ANALYSIS_CLIENT

    if not product_ai_analysis_enabled():
        return None

    if PRODUCT_ANALYSIS_CLIENT is None:
        PRODUCT_ANALYSIS_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)

    return PRODUCT_ANALYSIS_CLIENT


def new_product_job_id():
    return uuid.uuid4().hex


def default_product_progress():
    return {
        "active": False,
        "job_id": None,
        "status": "idle",
        "summary": "No product search is running.",
        "home_address": "",
        "enabled_stores": [],
        "max_workers": product_worker_count(),
        "total": 0,
        "completed": 0,
        "percent": 0,
        "downloads": [],
        "updated_at": time.time(),
    }


def load_product_progress():
    with PRODUCT_PROGRESS_LOCK:
        if not PRODUCT_PROGRESS_FILE.exists():
            return default_product_progress()

        try:
            progress = json.loads(PRODUCT_PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return default_product_progress()

        if not isinstance(progress, dict):
            return default_product_progress()

        progress.setdefault("downloads", [])
        progress.setdefault("completed", completed_product_download_count(progress))
        progress.setdefault("percent", product_progress_percent(progress.get("completed", 0), progress.get("total", 0)))
        return progress


def save_product_progress(progress):
    with PRODUCT_PROGRESS_LOCK:
        progress = progress if isinstance(progress, dict) else default_product_progress()
        progress["updated_at"] = time.time()
        progress["completed"] = completed_product_download_count(progress)
        if not progress.get("active") and progress.get("status") == "running":
            progress["status"] = (
                "failed"
                if any(item.get("state") == "failed" for item in progress.get("downloads", []))
                else "complete"
            )
        if progress.get("total"):
            progress["percent"] = product_progress_percent(progress.get("completed", 0), progress.get("total", 0))
        else:
            progress["percent"] = 100 if progress.get("status") in {"complete", "failed"} else 0
        PRODUCT_PROGRESS_FILE.write_text(
            json.dumps(progress, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return progress


def start_product_progress(downloads, job_id=None, home_address="", enabled_stores=None, max_workers=None):
    with PRODUCT_PROGRESS_LOCK:
        job_id = job_id or new_product_job_id()
        downloads = [dict(item) for item in downloads]
        progress = {
            "active": bool(downloads),
            "job_id": job_id,
            "status": "running" if downloads else "complete",
            "summary": "Preparing product downloads." if downloads else "No product downloads were needed.",
            "home_address": home_address or "",
            "enabled_stores": enabled_stores or [],
            "max_workers": max_workers or product_worker_count(len(downloads)),
            "total": len(downloads),
            "completed": 0,
            "percent": 3 if downloads else 100,
            "downloads": downloads,
        }
        return save_product_progress(progress)


def update_product_progress_summary(job_id, summary, status=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        progress["active"] = True
        progress["status"] = status or progress.get("status") or "running"
        progress["summary"] = summary
        return save_product_progress(progress)


def mark_product_download(job_id, index, state, message, candidates_count=None, selected_name=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        downloads = progress.setdefault("downloads", [])
        if 0 <= index < len(downloads):
            item = downloads[index]
            item["state"] = state
            item["message"] = message
            item["updated_at"] = time.time()

            if state == "running" and not item.get("started_at"):
                item["started_at"] = time.time()

            if state in PRODUCT_FINAL_STATES:
                item["finished_at"] = time.time()

            if candidates_count is not None:
                item["candidates_count"] = candidates_count

            if selected_name:
                item["selected_name"] = selected_name

        progress["active"] = state == "running" or any(
            item.get("state") in {"waiting", "running"}
            for item in downloads
        )
        progress["status"] = "running" if progress["active"] else progress.get("status", "running")
        return save_product_progress(progress)


def update_product_progress_picks(job_id, ingredient, record):
    if not job_id or not record:
        return None

    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if progress.get("job_id") != job_id:
            return progress

        selected = record.get("selected_product") or {}
        selected_id = selected.get("id", "")
        store_results = {
            result.get("store_key"): result
            for result in record.get("store_results_list", [])
            if isinstance(result, dict) and result.get("store_key")
        }

        for item in progress.get("downloads", []):
            if item.get("ingredient") != ingredient:
                continue

            store_result = store_results.get(item.get("store_key")) or {}
            store_best = store_result.get("best_product") or {}
            product = store_best or (
                selected if selected and selected.get("store_key") == item.get("store_key") else {}
            )

            item["selected_product"] = compact_progress_product(product)
            item["selected_name"] = product.get("product_name", "") if product else ""
            item["selected_price"] = product.get("price", "") if product else ""
            item["selected_product_url"] = product.get("product_url", "") if product else ""
            item["selected_is_overall"] = bool(product and selected_id and product.get("id") == selected_id)
            item["selection_reason"] = (
                product.get("reason_selected")
                or store_result.get("reason_selected")
                or store_result.get("reason_skipped")
                or ""
            )

        return save_product_progress(progress)


def compact_progress_product(product):
    if not product:
        return None

    return {
        "id": product.get("id", ""),
        "product_name": product.get("product_name", ""),
        "store_name": product.get("store_name", ""),
        "store_key": product.get("store_key", ""),
        "price": product.get("price", ""),
        "size": product_size(product),
        "unit_price": product.get("unit_price", ""),
        "requested_quantity": product.get("requested_quantity", ""),
        "quantity_fit": product.get("quantity_fit", {}),
        "product_url": product.get("product_url", ""),
        "search_url": product.get("search_url", ""),
        "confidence": product.get("confidence"),
        "score": product.get("score"),
        "reason_selected": product.get("reason_selected", ""),
        "viable": product.get("viable"),
    }


def finish_product_progress(job_id, ok=True, summary=None):
    with PRODUCT_PROGRESS_LOCK:
        progress = load_product_progress()

        if job_id and progress.get("job_id") != job_id:
            return progress

        downloads = progress.get("downloads", [])
        has_failed = any(
            item.get("state") == "failed"
            for item in downloads
        )
        ok = bool(ok) and not has_failed
        unfinished_state = "skipped" if ok else "failed"
        unfinished_message = (
            "Product search ended before this download ran."
            if ok
            else "Product search stopped before this download completed."
        )

        for item in downloads:
            if item.get("state") in PRODUCT_FINAL_STATES:
                continue

            item["state"] = unfinished_state
            item["message"] = unfinished_message
            item["updated_at"] = time.time()
            item["finished_at"] = time.time()
            item.setdefault("candidates_count", 0)

        progress["active"] = False
        progress["status"] = "complete" if ok else "failed"
        progress["summary"] = summary or (
            "Product search complete. Refreshing shopping list..."
            if ok
            else "Product search finished with errors."
        )
        progress["percent"] = 100
        return save_product_progress(progress)


def completed_product_download_count(progress):
    return sum(
        1
        for item in progress.get("downloads", [])
        if item.get("state") in PRODUCT_FINAL_STATES
    )


def product_progress_percent(done_count, total):
    if not total:
        return 100 if done_count else 0

    return max(3, min(100, round((done_count / total) * 100)))


def load_product_choices():
    if not PRODUCT_CHOICES_FILE.exists():
        return {"items": {}}

    try:
        data = json.loads(PRODUCT_CHOICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}

    if not isinstance(data, dict):
        return {"items": {}}

    data.setdefault("items", {})
    return data


def compact_product_state_for_storage(data):
    data = data if isinstance(data, dict) else {"items": {}}
    compacted = compact_product_value_for_storage(data)
    if not isinstance(compacted, dict):
        compacted = {"items": {}}
    compacted.setdefault("items", {})
    return compacted


def compact_product_value_for_storage(value, key=""):
    if key in {"prompt", "chatgpt_final_selection_prompt"} and is_chatgpt_prompt_payload(value):
        return save_product_prompt_payload(value)

    if key in {
        "alternative_products",
        "alternatives",
        "valid_alternatives",
        "valid_products",
        "rejected_products",
    } and isinstance(value, list):
        return [
            compact_product_candidate_reference(item)
            for item in value
        ]

    if key == "rendered_page_html_excerpt":
        return ""

    if key == "embedded_image_base64":
        return embedded_image_prompt_placeholder(value) if value else ""

    if key in {"raw_product_html_snippet", "card_text_excerpt", "detail_text_excerpt"}:
        return clean_text(str(value or ""))[:4500]

    if isinstance(value, dict):
        compacted = {}
        for child_key, child_value in value.items():
            compacted[child_key] = compact_product_value_for_storage(child_value, child_key)
        return compacted

    if isinstance(value, list):
        return [
            compact_product_value_for_storage(item, key)
            for item in value
        ]

    return value


def compact_product_candidate_reference(candidate):
    if not isinstance(candidate, dict):
        return candidate

    return {
        "id": candidate.get("id", ""),
        "product_name": candidate.get("product_name", ""),
        "store_key": candidate.get("store_key", ""),
        "store_name": candidate.get("store_name", ""),
        "price": candidate.get("price", ""),
        "size": product_size(candidate),
        "unit_price": candidate.get("unit_price", ""),
        "product_url": candidate.get("product_url", ""),
        "image_url": candidate.get("image_url", ""),
        "viable": candidate.get("viable"),
        "ranking_status": candidate.get("ranking_status", ""),
        "rejection_reason": candidate.get("rejection_reason", ""),
        "rejection_reasons": candidate.get("rejection_reasons", [])[:3],
        "confidence": candidate.get("confidence"),
        "confidence_score": candidate.get("confidence_score"),
        "score": candidate.get("score"),
    }


def is_chatgpt_prompt_payload(value):
    return bool(
        isinstance(value, dict)
        and isinstance(value.get("messages"), list)
        and any(isinstance(message, dict) and message.get("content") for message in value.get("messages", []))
    )


def save_product_prompt_payload(prompt_payload):
    if not is_chatgpt_prompt_payload(prompt_payload):
        return {}

    payload_text = json.dumps(prompt_payload, indent=2, ensure_ascii=False)
    digest = hashlib.sha1(payload_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    kind = normalize_item_key(prompt_payload.get("kind", "chatgpt_prompt")) or "chatgpt_prompt"
    path = PRODUCT_PROMPTS_DIR / f"{kind}_{digest}.json"

    try:
        if not path.exists():
            path.write_text(payload_text, encoding="utf-8")
        saved_path = str(path)
    except Exception:
        saved_path = ""

    return {
        "kind": prompt_payload.get("kind", ""),
        "model": prompt_payload.get("model", ""),
        "temperature": prompt_payload.get("temperature"),
        "prompt_path": saved_path,
        "prompt_chars": len(payload_text),
        "messages": [],
    }


def read_product_prompt_payload_from_ref(prompt_ref):
    if is_chatgpt_prompt_payload(prompt_ref):
        return prompt_ref

    if not isinstance(prompt_ref, dict):
        return {}

    prompt_path = str(prompt_ref.get("prompt_path") or "").strip()
    if not prompt_path:
        return {}

    try:
        path = Path(prompt_path).resolve()
        prompt_root = PRODUCT_PROMPTS_DIR.resolve()
        if path != prompt_root and prompt_root not in path.parents:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if is_chatgpt_prompt_payload(data) else {}


def prompt_ref_has_payload(prompt_ref):
    return bool(is_chatgpt_prompt_payload(prompt_ref) or read_product_prompt_payload_from_ref(prompt_ref))


def product_results_payload(data):
    data = compact_product_state_for_storage(data)
    items = data.get("items", {}) if isinstance(data.get("items"), dict) else {}
    return {
        "schema": "hybrid-agentic-shopping-results/v1",
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "architecture": hybrid_shopping_architecture(),
        "items": items,
    }


def save_product_results(data):
    payload = product_results_payload(data)
    PRODUCT_RESULTS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def save_product_choices(data):
    data = compact_product_state_for_storage(data)
    PRODUCT_CHOICES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    save_product_results(data)
    return data


def clear_product_choices():
    return save_product_choices({"items": {}})


def hybrid_shopping_architecture():
    return [
        "Planner Agent",
        "Store Resolution Agent",
        "Browser Worker Agent",
        "Product Extraction/Normalization Agent",
        "Validation Layer",
        "Ranking Agent",
    ]


def agent_stage(name, status="done", message="", metadata=None):
    return {
        "name": name,
        "status": status,
        "message": message,
        "metadata": metadata or {},
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def product_choices_by_item():
    return hydrate_saved_product_choices(load_product_choices().get("items", {}))


def hydrate_saved_product_choices(items):
    if not isinstance(items, dict):
        return {}

    return {
        item_key: hydrate_saved_product_choice(choice)
        for item_key, choice in items.items()
        if isinstance(choice, dict)
    }


def hydrate_saved_product_choice(choice):
    store_results_list = choice.get("store_results_list", [])
    candidates = choice.get("candidates", [])

    if not store_results_list or not candidates:
        return choice

    ingredient = choice.get("ingredient") or choice.get("item_key") or ""
    hydrated_results = []
    changed = False

    for store_result in store_results_list:
        if not isinstance(store_result, dict):
            hydrated_results.append(store_result)
            continue

        hydrated = store_result
        if not store_result.get("best_product"):
            store_key = store_result.get("store_key", "")
            store_candidates = [
                candidate
                for candidate in candidates
                if isinstance(candidate, dict) and candidate.get("store_key") == store_key
            ]
            viable_candidates = [
                candidate
                for candidate in store_candidates
                if candidate.get("viable")
            ]
            best = viable_candidates[0] if viable_candidates else best_available_store_candidate(
                ingredient,
                store_candidates,
            )

            if best:
                hydrated = hydrate_store_result_best_product(
                    store_result,
                    best,
                    ingredient,
                    viable=bool(best.get("viable") is not False),
                )
                changed = True

        hydrated_results.append(hydrated)

    if not changed:
        return choice

    hydrated_choice = dict(choice)
    hydrated_choice["store_results_list"] = hydrated_results
    hydrated_choice["store_results"] = {
        result.get("store_key"): result
        for result in hydrated_results
        if isinstance(result, dict) and result.get("store_key")
    }
    return hydrated_choice


def hydrate_store_result_best_product(store_result, best, ingredient, viable=True):
    store_name = store_result.get("store_name") or best.get("store_name", "")
    best = dict(best)
    reason = best.get("reason_selected") or (
        product_selection_reason(best, store_name)
        if viable
        else best_available_product_reason(ingredient, best, store_name)
    )
    best["reason_selected"] = reason
    best["selected_reason"] = reason

    hydrated = dict(store_result)
    hydrated.update({
        "best_product_id": best.get("id", ""),
        "best_product": best,
        "best_product_is_viable": viable,
        "best_product_match": best.get("product_name", ""),
        "price": best.get("price", ""),
        "size": product_size(best),
        "unit_price": best.get("unit_price", ""),
        "product_url": best.get("product_url", ""),
        "image_url": best.get("image_url", ""),
        "reason_selected": reason,
    })
    return hydrated


def product_choice_for_item(item_key, store_key=None):
    choice = product_choices_by_item().get(normalize_item_key(item_key), {})

    if store_key and choice:
        return product_choice_for_store(choice, store_key)

    return choice


def product_choice_for_store(choice, store_key):
    store_key = str(store_key or "").strip()
    filtered = dict(choice)
    candidates = [
        candidate
        for candidate in choice.get("candidates", [])
        if candidate.get("store_key") == store_key
    ]
    store_result = find_store_result(choice, store_key)
    selected = (store_result or {}).get("best_product")
    if not selected and (choice.get("selected_product") or {}).get("store_key") == store_key:
        selected = choice.get("selected_product")

    filtered["filtered_store_key"] = store_key
    filtered["filtered_store_name"] = (store_result or {}).get("store_name", "") or (selected or {}).get("store_name", "")
    filtered["store_result"] = store_result or {}
    filtered["candidates"] = candidates
    filtered["valid_alternatives"] = [
        candidate
        for candidate in candidates
        if candidate.get("viable") is not False
    ]
    filtered["rejected_products"] = [
        candidate
        for candidate in candidates
        if candidate.get("viable") is False
    ]
    filtered["selected_product"] = selected
    filtered["selected_product_id"] = (store_result or {}).get("best_product_id") or (selected or {}).get("id", "")
    filtered["skip_reasons"] = (
        [(store_result or {}).get("reason_skipped")]
        if (store_result or {}).get("reason_skipped")
        else filtered.get("skip_reasons", [])
    )
    return filtered


def product_prompt_for_item(item_key, store_key="", product_id="", prompt_kind=""):
    choice = product_choice_for_item(item_key, store_key=store_key)

    if not choice:
        return {
            "ok": False,
            "error": "No product choices are saved for that ingredient.",
        }

    product_id = str(product_id or "").strip()
    prompt_kind = normalize_item_key(prompt_kind)
    candidate = {}
    if product_id:
        candidate = next(
            (
                item
                for item in choice.get("candidates", [])
                if isinstance(item, dict) and item.get("id") == product_id
            ),
            {},
        )
    if not candidate:
        candidate = choice.get("selected_product") or {}

    prompt_ref = product_prompt_ref_for_choice(choice, candidate, prompt_kind)
    prompt_payload = read_product_prompt_payload_from_ref(prompt_ref)

    if not prompt_payload:
        return {
            "ok": False,
            "error": "No saved ChatGPT prompt was found for that product.",
        }

    return {
        "ok": True,
        "prompt": prompt_payload,
        "prompt_kind": prompt_kind,
        "title": product_prompt_title(prompt_kind),
        "product_id": candidate.get("id", ""),
        "item_key": normalize_item_key(item_key),
    }


def product_prompt_ref_for_choice(choice, candidate, prompt_kind):
    prompt_candidates = []

    if prompt_kind in {"choice_final_selection", "final_selection", ""}:
        prompt_candidates.append(choice.get("chatgpt_final_selection_prompt"))
        prompt_candidates.append(choice.get("chatgpt_final_selection_prompt_ref"))

    if candidate:
        if prompt_kind in {"rendered_html_product_reasoning", "rendered_html", "html_reasoning", ""}:
            prompt_candidates.append((candidate.get("chatgpt_rendered_html_agent") or {}).get("prompt"))
            prompt_candidates.append((candidate.get("chatgpt_rendered_html_agent") or {}).get("prompt_ref"))
        if prompt_kind in {"store_product_ranking", "store_ranking", ""}:
            prompt_candidates.append((candidate.get("chatgpt_store_ranking_agent") or {}).get("prompt"))
            prompt_candidates.append((candidate.get("chatgpt_store_ranking_agent") or {}).get("prompt_ref"))
        if prompt_kind in {"product_page_analysis", "page_analysis", ""}:
            prompt_candidates.append((candidate.get("chatgpt_analysis") or {}).get("prompt"))
            prompt_candidates.append((candidate.get("chatgpt_analysis") or {}).get("prompt_ref"))
        if prompt_kind in {"final_selection", ""}:
            prompt_candidates.append((candidate.get("final_selection_agent") or {}).get("prompt"))
            prompt_candidates.append((candidate.get("final_selection_agent") or {}).get("prompt_ref"))

    for prompt_ref in prompt_candidates:
        if is_chatgpt_prompt_payload(prompt_ref) or (
            isinstance(prompt_ref, dict) and prompt_ref.get("prompt_path")
        ):
            return prompt_ref

    return {}


def product_prompt_title(prompt_kind):
    if prompt_kind in {"choice_final_selection", "final_selection"}:
        return "Final Selection Prompt"
    if prompt_kind in {"rendered_html_product_reasoning", "rendered_html", "html_reasoning"}:
        return "Rendered HTML Product Reasoning Prompt"
    if prompt_kind in {"store_product_ranking", "store_ranking"}:
        return "Store Product Ranking Prompt"
    if prompt_kind in {"product_page_analysis", "page_analysis"}:
        return "Product Page Analysis Prompt"
    return "ChatGPT Prompt"


def find_store_result(choice, store_key):
    store_results = choice.get("store_results", {})
    if isinstance(store_results, dict) and store_key in store_results:
        return store_results.get(store_key)

    for result in choice.get("store_results_list", []):
        if result.get("store_key") == store_key:
            return result

    return None


def grab_best_products(items=None, job_id=None):
    shopping_items = items if items is not None else load_items()
    ingredients = [
        str(item or "").strip()
        for item in shopping_items
        if str(item or "").strip() and not is_section_header(item)
    ]
    store_settings = load_store_settings()
    stores = store_settings.get("stores", {})
    enabled_stores = [
        key
        for key in store_settings.get("enabled_stores", [])
        if key in stores
    ]
    home_address = load_home_address()
    full_address = home_address.get("full_address", "")
    quantity_context_by_item = load_item_quantity_context(ingredients)
    downloads = build_product_download_plan(
        ingredients,
        enabled_stores,
        stores,
        quantity_context_by_item=quantity_context_by_item,
    )
    max_workers = product_worker_count(len(downloads))
    planner_stage = agent_stage(
        "Planner Agent",
        message="Built ingredient/store search plan from current shopping list.",
        metadata={
            "ingredient_count": len(ingredients),
            "enabled_stores": enabled_stores,
            "download_count": len(downloads),
            "max_workers": max_workers,
        },
    )

    if job_id:
        start_product_progress(
            downloads,
            job_id=job_id,
            home_address=full_address,
            enabled_stores=enabled_stores,
            max_workers=max_workers,
        )

    if not ingredients:
        if job_id:
            finish_product_progress(job_id, ok=True, summary="No ingredients were available to search.")

        return {
            "ok": True,
            "home_address": full_address,
            "home_location": None,
            "enabled_stores": enabled_stores,
            "download_count": 0,
            "max_workers": max_workers,
            "count": 0,
            "selected_count": 0,
            "agent_stages": [planner_stage],
            "results": [],
        }

    if job_id:
        update_product_progress_summary(job_id, "Finding the nearest enabled store locations from the saved Full Address.")

    home_location = geocode_home_address(full_address)
    store_locations = {
        store_key: find_nearest_store_location(
            store_key,
            stores[store_key],
            full_address,
            home_location,
        )
        for store_key in enabled_stores
    }
    store_resolution_stage = agent_stage(
        "Store Resolution Agent",
        message="Resolved nearest pickup-oriented store locations from the saved Full Address.",
        metadata={
            "home_address": full_address,
            "home_location": home_location,
            "store_locations": store_locations,
        },
    )
    store_results_by_ingredient = {
        ingredient: []
        for ingredient in ingredients
    }
    expected_download_counts = {}
    completed_download_counts = {}
    saved_ingredients = set()
    state = load_product_choices()
    item_records = state.setdefault("items", {})
    results_by_ingredient = {}

    for download in downloads:
        ingredient = download.get("ingredient", "")
        if ingredient:
            expected_download_counts[ingredient] = expected_download_counts.get(ingredient, 0) + 1

    if downloads:
        if job_id:
            update_product_progress_summary(
                job_id,
                f"Downloading product search pages with up to {max_workers} searches running at once.",
            )

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = {
                executor.submit(
                    search_store_products_for_download,
                    download,
                    stores,
                    full_address,
                    home_location,
                    store_locations,
                    job_id,
                ): download
                for download in downloads
            }

            try:
                completed_futures = as_completed(futures, timeout=product_search_timeout_seconds())
                for future in completed_futures:
                    download = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = failed_product_download_result(download, exc, job_id=job_id)

                    ingredient = result.get("ingredient", "")
                    store_results_by_ingredient.setdefault(ingredient, []).append(result)
                    completed_download_counts[ingredient] = completed_download_counts.get(ingredient, 0) + 1

                    if (
                        ingredient
                        and ingredient not in saved_ingredients
                        and completed_download_counts.get(ingredient, 0) >= expected_download_counts.get(ingredient, 0)
                    ):
                        record = save_product_record_for_ingredient(
                            ingredient,
                            store_results_by_ingredient.get(ingredient, []),
                            full_address,
                            state,
                            item_records,
                            quantity_context=quantity_context_by_item.get(normalize_item_key(ingredient), {}),
                            job_id=job_id,
                        )
                        results_by_ingredient[ingredient] = record
                        saved_ingredients.add(ingredient)
            except FuturesTimeoutError:
                for future, download in futures.items():
                    if future.done():
                        continue

                    future.cancel()
                    message = (
                        f"{download.get('store_name')}: product search timed out after "
                        f"{int(product_search_timeout_seconds())} seconds."
                    )
                    if job_id:
                        mark_product_download(
                            job_id,
                            download.get("index", 0),
                            "failed",
                            message,
                            candidates_count=0,
                        )
                    result = {
                        "index": download.get("index", 0),
                        "item_key": download.get("item_key") or normalize_item_key(download.get("ingredient", "")),
                        "ingredient": download.get("ingredient", ""),
                        "quantity": (download.get("quantity_context") or {}).get("display", ""),
                        "quantity_context": download.get("quantity_context") or {},
                        "search_term": download.get("search_term", ""),
                        "store_key": download.get("store_key", ""),
                        "store_name": download.get("store_name", ""),
                        "search_url": download.get("search_url", ""),
                        "candidates": [],
                        "skip_reasons": [message],
                    }
                    ingredient = result.get("ingredient", "")
                    store_results_by_ingredient.setdefault(ingredient, []).append(result)
                    completed_download_counts[ingredient] = completed_download_counts.get(ingredient, 0) + 1
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    elif job_id:
        update_product_progress_summary(job_id, "No enabled store search URLs are configured.")

    results = []

    for ingredient in ingredients:
        record = results_by_ingredient.get(ingredient)
        if not record:
            record = save_product_record_for_ingredient(
                ingredient,
                store_results_by_ingredient.get(ingredient, []),
                full_address,
                state,
                item_records,
                quantity_context=quantity_context_by_item.get(normalize_item_key(ingredient), {}),
                job_id=job_id,
            )

        results.append(record)

    save_product_choices(state)

    if job_id:
        finish_product_progress(
            job_id,
            ok=True,
            summary=f"Product search complete. Saved {sum(1 for item in results if item.get('selected_product'))} best product pick(s).",
        )

    return {
        "ok": True,
        "home_address": full_address,
        "home_location": home_location,
        "enabled_stores": enabled_stores,
        "download_count": len(downloads),
        "max_workers": max_workers,
        "count": len(results),
        "selected_count": sum(1 for item in results if item.get("selected_product")),
        "agent_stages": [planner_stage, store_resolution_stage],
        "results": results,
    }


def failed_product_download_result(download, exc, job_id=None):
    message = f"{download.get('store_name')}: product search failed: {exc}"
    if job_id:
        mark_product_download(
            job_id,
            download.get("index", 0),
            "failed",
            message,
            candidates_count=0,
        )

    return {
        "index": download.get("index", 0),
        "item_key": download.get("item_key") or normalize_item_key(download.get("ingredient", "")),
        "ingredient": download.get("ingredient", ""),
        "quantity": (download.get("quantity_context") or {}).get("display", ""),
        "quantity_context": download.get("quantity_context") or {},
        "search_term": download.get("search_term", ""),
        "store_key": download.get("store_key", ""),
        "store_name": download.get("store_name", ""),
        "search_url": download.get("search_url", ""),
        "candidates": [],
        "skip_reasons": [message],
        "agent_stages": [
            agent_stage(
                "Browser Worker Agent",
                status="failed",
                message=message,
                metadata={
                    "store_key": download.get("store_key", ""),
                    "search_url": download.get("search_url", ""),
                },
            ),
        ],
    }


def save_product_record_for_ingredient(
    ingredient,
    store_results,
    full_address,
    state,
    item_records,
    quantity_context=None,
    job_id=None,
):
    record = build_product_choice_record_from_results(
        ingredient,
        store_results,
        full_address,
        quantity_context=quantity_context,
    )
    record = compact_product_value_for_storage(record)
    item_records[record["item_key"]] = record
    selected = record.get("selected_product")

    if selected and selected.get("source") != "search-page-fallback":
        save_item_store(record["item_key"], selected.get("store_key") or "")

    save_product_choices(state)
    update_product_progress_picks(job_id, ingredient, record)
    return record


def build_product_download_plan(ingredients, enabled_stores, stores, quantity_context_by_item=None):
    quantity_context_by_item = quantity_context_by_item or {}
    downloads = []

    for ingredient in ingredients:
        quantity_context = quantity_context_by_item.get(normalize_item_key(ingredient), {})
        for search_term in ingredient_search_terms(ingredient):
            for store_key in enabled_stores:
                store = stores.get(store_key, {})
                store_name = store.get("label") or store_key.title()
                search_url = build_product_search_url(store, search_term)
                downloads.append({
                    "index": len(downloads),
                    "item_key": normalize_item_key(ingredient),
                    "ingredient": ingredient,
                    "search_term": search_term,
                    "store_key": store_key,
                    "store_name": store_name,
                    "search_url": search_url,
                    "quantity": quantity_context.get("display", ""),
                    "quantity_context": quantity_context,
                    "state": "waiting",
                    "message": "Queued.",
                    "candidates_count": None,
                })

    return downloads


def store_location_searchable_status(store_name, full_address, home_location, store_location):
    if not clean_text(full_address):
        return {
            "ok": False,
            "message": f"{store_name}: saved Full Address is missing, so localized inventory cannot be searched.",
        }

    if not home_location:
        return {
            "ok": False,
            "message": f"{store_name}: saved Full Address could not be geocoded; refusing ZIP-only or generic inventory.",
        }

    store_location = store_location or {}
    if store_location.get("skip_reason"):
        return {
            "ok": False,
            "message": f"{store_name}: nearest store resolution failed: {store_location.get('skip_reason')}",
        }

    if not clean_text(store_location.get("address")):
        return {
            "ok": False,
            "message": f"{store_name}: nearest store address was not resolved from the saved Full Address.",
        }

    return {"ok": True, "message": ""}


def search_store_products_for_download(
    download,
    stores,
    full_address,
    home_location,
    store_locations,
    job_id=None,
    product_agent_prompt_builder=None,
    browser_visible=False,
    browser_visual_pause_seconds=0,
    browser_visual_hold_seconds=0,
):
    index = download.get("index", 0)
    ingredient = download.get("ingredient", "")
    store_key = download.get("store_key", "")
    store = stores.get(store_key, {})
    store_name = download.get("store_name") or store.get("label") or store_key.title()
    search_url = download.get("search_url", "")
    search_term = download.get("search_term") or ingredient
    quantity_context = download.get("quantity_context") or {}
    search_url = contextualized_product_search_url(
        search_url,
        store_key,
        full_address,
        store_locations.get(store_key, {}),
    )
    search_label = search_term if normalize_match_text(search_term) != normalize_match_text(ingredient) else ingredient
    store_location = store_locations.get(store_key, {})
    store_search_status = store_location_searchable_status(
        store_name,
        full_address,
        home_location,
        store_location,
    )

    if not store_search_status.get("ok"):
        message = store_search_status.get("message") or f"{store_name}: nearest localized store could not be verified."
        if job_id:
            mark_product_download(job_id, index, "failed", message, candidates_count=0)
        return {
            "index": index,
            "item_key": download.get("item_key") or normalize_item_key(ingredient),
            "ingredient": ingredient,
            "quantity": quantity_context.get("display", ""),
            "quantity_context": quantity_context,
            "store_key": store_key,
            "store_name": store_name,
            "search_url": search_url,
            "search_term": search_term,
            "store_location": store_location,
            "store_location_name": (store_location or {}).get("name", ""),
            "store_location_address": (store_location or {}).get("address", ""),
            "store_location_distance_miles": (store_location or {}).get("distance_miles"),
            "candidates": [],
            "skip_reasons": [message],
            "agent_stages": [
                agent_stage(
                    "Store Resolution Agent",
                    status="failed",
                    message=message,
                    metadata={
                        "home_address": full_address,
                        "home_location": home_location,
                        "store_location": store_location,
                    },
                ),
            ],
        }

    if not search_url:
        message = f"{store_name}: no product search URL is configured."
        if job_id:
            mark_product_download(job_id, index, "skipped", message, candidates_count=0)
        return {
            "index": index,
            "item_key": download.get("item_key") or normalize_item_key(ingredient),
            "ingredient": ingredient,
            "quantity": quantity_context.get("display", ""),
            "quantity_context": quantity_context,
            "store_key": store_key,
            "store_name": store_name,
            "search_url": search_url,
            "store_location": store_location,
            "candidates": [],
            "skip_reasons": [message],
            "agent_stages": [
                agent_stage(
                    "Browser Worker Agent",
                    status="skipped",
                    message=message,
                    metadata={"store_location": store_location},
                ),
            ],
        }

    if job_id:
        mark_product_download(
            job_id,
            index,
            "running",
            f"Downloading {store_name} search results for {search_label}...",
        )

    try:
        candidates, skip_reasons = search_store_products(
            ingredient,
            store_key,
            store,
            full_address,
            home_location,
            store_locations.get(store_key, {}),
            search_term=search_term,
            search_url=search_url,
            product_agent_prompt_builder=product_agent_prompt_builder,
            browser_visible=browser_visible,
            browser_visual_pause_seconds=browser_visual_pause_seconds,
            browser_visual_hold_seconds=browser_visual_hold_seconds,
        )
    except Exception as exc:
        candidates = []
        skip_reasons = [f"{store_name}: product search failed: {exc}"]

    if candidates:
        candidates = [
            apply_quantity_context_to_candidate(candidate, quantity_context)
            for candidate in candidates
        ]
        candidates = prioritize_candidates_for_detail(ingredient, candidates)
        candidates = enrich_product_candidates_from_pages(
            candidates,
            ingredient,
            store_name,
            job_id=job_id,
            progress_index=index,
        )
        candidates = embed_product_candidate_images(
            candidates,
            job_id=job_id,
            progress_index=index,
            store_name=store_name,
        )

    raw_direct_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
    )
    direct_count = sum(
        1
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback" and candidate.get("detail_evaluated")
    )
    rankable_card_count = sum(
        1
        for candidate in candidates
        if candidate_has_rankable_card_evidence(ingredient, candidate)
    )
    detail_failed_count = max(0, raw_direct_count - direct_count)
    failed = any("product search failed" in str(reason).lower() for reason in skip_reasons)
    failed = failed or localized_inventory_blocking_failure(skip_reasons)

    if direct_count:
        state = "done"
        message = f"Opened and evaluated {direct_count} full product page(s) from {store_name}."
        candidates_count = direct_count
    elif rankable_card_count:
        state = "done"
        message = f"Captured {rankable_card_count} rankable product card(s) from {store_name}."
        candidates_count = rankable_card_count
    elif detail_failed_count:
        state = "failed"
        message = f"Found {detail_failed_count} product link(s), but no full product page could be evaluated."
        candidates_count = 0
    elif failed:
        state = "failed"
        message = skip_reasons[0] if skip_reasons else f"{store_name}: product search failed."
        candidates_count = 0
    else:
        state = "done"
        message = skip_reasons[0] if skip_reasons else f"{store_name}: no product candidates were found."
        candidates_count = direct_count

    if job_id:
        mark_product_download(
            job_id,
            index,
            state,
            message,
            candidates_count=candidates_count,
        )

    return {
        "index": index,
        "item_key": download.get("item_key") or normalize_item_key(ingredient),
        "ingredient": ingredient,
        "quantity": quantity_context.get("display", ""),
        "quantity_context": quantity_context,
        "store_key": store_key,
        "store_name": store_name,
        "search_url": search_url,
        "search_term": search_term,
        "store_location": store_location,
        "store_location_name": (store_location or {}).get("name", ""),
        "store_location_address": (store_location or {}).get("address", ""),
        "store_location_distance_miles": (store_location or {}).get("distance_miles"),
        "candidates": candidates,
        "skip_reasons": skip_reasons,
        "agent_stages": [
            agent_stage(
                "Browser Worker Agent",
                status="failed" if failed else "done",
                message=message,
                metadata={
                    "store_key": store_key,
                    "store_name": store_name,
                    "search_url": search_url,
                    "search_term": search_term,
                    "store_location": store_location,
                },
            ),
            agent_stage(
                "Product Extraction/Normalization Agent",
                status="done" if raw_direct_count else "failed",
                message=f"Captured and normalized {raw_direct_count} visible/direct product candidate(s).",
                metadata={
                    "candidate_count": raw_direct_count,
                    "detail_evaluated_count": direct_count,
                    "image_embedded_count": sum(1 for candidate in candidates if candidate.get("embedded_image_base64")),
                },
            ),
        ],
    }


def build_product_choice_record_from_results(ingredient, store_results, full_address, quantity_context=None):
    candidates = []
    skip_reasons = []
    quantity_context = quantity_context or first_quantity_context(store_results)
    store_results = sorted(
        [
            result
            for result in store_results
            if isinstance(result, dict)
        ],
        key=lambda item: item.get("index", 0),
    )

    for result in store_results:
        candidates.extend(result.get("candidates", []))
        skip_reasons.extend(result.get("skip_reasons", []))

    candidates = [
        apply_quantity_context_to_candidate(candidate, quantity_context)
        for candidate in candidates
    ]
    candidates = rank_product_candidates(ingredient, candidates, quantity_context=quantity_context)
    candidates = apply_chatgpt_store_product_rankings(
        ingredient,
        candidates,
        full_address=full_address,
        quantity_context=quantity_context,
    )
    candidates = apply_chatgpt_final_product_selection(
        ingredient,
        candidates,
        full_address=full_address,
        quantity_context=quantity_context,
    )
    candidates = apply_validation_layer(ingredient, candidates)
    store_product_results_list = build_store_product_results(
        ingredient,
        store_results,
        candidates,
    )
    store_product_results = {
        result.get("store_key"): result
        for result in store_product_results_list
        if result.get("store_key")
    }
    viable_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("viable")
    ]
    selected = viable_candidates[0] if viable_candidates else None
    final_selection_agent = (selected or {}).get("final_selection_agent") or {}
    validation_summary = product_validation_summary(candidates)

    if not selected and not skip_reasons:
        skip_reasons.append("No valid product candidates were found for the enabled stores.")

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    return {
        "item_key": normalize_item_key(ingredient),
        "ingredient": ingredient,
        "quantity": quantity_context.get("display", ""),
        "quantity_context": quantity_context,
        "home_address": full_address,
        "selected_product_id": selected.get("id") if selected else "",
        "selected_product": selected,
        "manual_override": False,
        "agent_stages": product_record_agent_stages(
            store_results,
            candidates,
            validation_summary,
            final_selection_agent,
        ),
        "chatgpt_final_selection": final_selection_agent,
        "chatgpt_final_selection_prompt": final_selection_agent.get("prompt") or {},
        "store_results": store_product_results,
        "store_results_list": store_product_results_list,
        "candidates": candidates,
        "valid_products": [candidate for candidate in candidates if candidate.get("viable")],
        "rejected_products": [candidate for candidate in candidates if not candidate.get("viable")],
        "validation_summary": validation_summary,
        "skip_reasons": unique_texts(skip_reasons),
        "updated_at": now,
    }


def first_quantity_context(store_results):
    for result in store_results:
        if not isinstance(result, dict):
            continue

        quantity_context = result.get("quantity_context") or {}
        if isinstance(quantity_context, dict) and quantity_context.get("display"):
            return quantity_context

        quantity = clean_text(result.get("quantity"))
        if quantity:
            return {"display": quantity, "sources": []}

    return {}


def apply_validation_layer(ingredient, candidates):
    for candidate in candidates:
        rejection_reasons = unique_texts(candidate.get("skip_reasons", []))
        candidate["rejected"] = not bool(candidate.get("viable"))
        candidate["rejection_reasons"] = rejection_reasons if candidate["rejected"] else []
        candidate["validation"] = {
            "status": "valid" if candidate.get("viable") else "rejected",
            "is_relevant": product_matches_ingredient(ingredient, candidate),
            "in_stock": candidate.get("in_stock"),
            "has_direct_product_url": candidate_has_direct_product_url(candidate),
            "reasons": [] if candidate.get("viable") else rejection_reasons,
        }
        candidate["ranking_status"] = candidate.get("ranking_status") or ("alternative" if candidate.get("viable") else "rejected")
        candidate["confidence_score"] = candidate.get("confidence_score", candidate.get("confidence"))
        if candidate["rejected"] and rejection_reasons and not candidate.get("rejection_reason"):
            candidate["rejection_reason"] = rejection_reasons[0]
        candidate["scoring_metadata"] = {
            "score": candidate.get("score"),
            "confidence": candidate.get("confidence"),
            "confidence_score": candidate.get("confidence_score"),
            "ranking_status": candidate.get("ranking_status"),
            "ranking_metadata": candidate.get("ranking_metadata", {}),
            "quantity_fit": candidate.get("quantity_fit", {}),
            "egg_product": candidate.get("egg_product", {}),
            "ranking_reasons": candidate.get("ranking_reasons", []),
            "skip_reasons": candidate.get("skip_reasons", []),
            "shortlisted_for_detail": candidate.get("shortlisted_for_detail"),
            "shortlisted_for_chatgpt_analysis": candidate.get("shortlisted_for_chatgpt_analysis"),
            "chatgpt_rendered_html_reasoning": candidate.get("chatgpt_rendered_html_agent", {}),
            "chatgpt_store_ranking": candidate.get("chatgpt_store_ranking_agent", {}),
        }

    return candidates


def product_validation_summary(candidates):
    total = len(candidates)
    valid = sum(1 for candidate in candidates if candidate.get("viable"))
    rejected = total - valid
    return {
        "total": total,
        "valid": valid,
        "rejected": rejected,
        "direct_product_url_count": sum(1 for candidate in candidates if candidate_has_direct_product_url(candidate)),
        "in_stock_count": sum(1 for candidate in candidates if candidate.get("in_stock") is True),
        "unknown_stock_count": sum(1 for candidate in candidates if candidate.get("in_stock") is None),
    }


def product_record_agent_stages(store_results, candidates, validation_summary, final_selection_agent):
    raw_stages = []
    for result in store_results:
        if isinstance(result, dict):
            raw_stages.extend(result.get("agent_stages", []))

    return raw_stages + [
        agent_stage(
            "Validation Layer",
            message="Rejected irrelevant, unavailable, or rule-failing candidates and preserved rejection reasons.",
            metadata=validation_summary,
        ),
        agent_stage(
            "Ranking Agent",
            message="Ranked generic browser candidates, using ChatGPT only on cleaned rendered HTML and extracted product-content blocks when available.",
            metadata={
                "candidate_count": len(candidates),
                "rendered_html_reasoning_candidate_count": sum(
                    1
                    for candidate in candidates
                    if candidate.get("chatgpt_rendered_html_agent")
                ),
                "store_ranking_candidate_count": sum(
                    1
                    for candidate in candidates
                    if candidate.get("chatgpt_store_ranking_agent")
                ),
                "chatgpt_status": final_selection_agent.get("status", "not-run") if final_selection_agent else "not-run",
                "selected_product_id": final_selection_agent.get("selected_product_id", "") if final_selection_agent else "",
            },
        ),
    ]


def build_store_product_results(ingredient, raw_store_results, ranked_candidates):
    records = []

    for raw in group_raw_store_results_by_store(raw_store_results):
        store_key = raw.get("store_key", "")
        store_name = raw.get("store_name") or store_key.title()
        raw_ids = {
            candidate.get("id")
            for candidate in raw.get("candidates", [])
            if candidate.get("id")
        }
        store_candidates = [
            candidate
            for candidate in ranked_candidates
            if (
                candidate.get("store_key") == store_key
                and (not raw_ids or candidate.get("id") in raw_ids)
            )
        ]
        viable_candidates = [
            candidate
            for candidate in store_candidates
            if candidate.get("viable")
        ]
        rejected_candidates = [
            candidate
            for candidate in store_candidates
            if not candidate.get("viable")
        ]
        best = viable_candidates[0] if viable_candidates else best_available_store_candidate(
            ingredient,
            store_candidates,
        )
        best_is_viable = bool(best and best.get("viable") is not False)
        store_localization = first_store_localization(store_candidates)

        if best:
            best["reason_selected"] = (
                product_selection_reason(best, store_name)
                if best_is_viable
                else best_available_product_reason(ingredient, best, store_name)
            )
            best["selected_reason"] = best["reason_selected"]
            skip_reason = "" if best_is_viable else store_skip_reason(store_name, raw, store_candidates)
        else:
            skip_reason = store_skip_reason(store_name, raw, store_candidates)

        for candidate in store_candidates:
            if candidate is best and best_is_viable:
                candidate["ranking_status"] = "best"
            elif candidate.get("viable"):
                candidate["ranking_status"] = candidate.get("ranking_status") or "alternative"
            else:
                candidate["ranking_status"] = "rejected"
                rejection_reason = candidate.get("rejection_reason") or (candidate.get("skip_reasons", [""]) or [""])[0]
                if rejection_reason:
                    candidate["rejection_reason"] = rejection_reason

            candidate["confidence_score"] = candidate.get("confidence_score", candidate.get("confidence"))

        record = {
            "store_key": store_key,
            "store_name": store_name,
            "item_key": raw.get("item_key") or normalize_item_key(ingredient),
            "ingredient": ingredient,
            "quantity": raw.get("quantity", ""),
            "quantity_context": raw.get("quantity_context", {}),
            "search_url": raw.get("search_url", ""),
            "search_urls": raw.get("search_urls", []),
            "search_terms": raw.get("search_terms", []),
            "store_location": raw.get("store_location", {}),
            "store_location_name": raw.get("store_location_name", ""),
            "store_location_address": raw.get("store_location_address", ""),
            "store_location_distance_miles": raw.get("store_location_distance_miles"),
            "store_localization": store_localization,
            "proof_of_store_selection": store_localization.get("proof_of_store_selection", []),
            "best_product_id": best.get("id") if best else "",
            "best_product": best,
            "best_product_is_viable": best_is_viable,
            "best_product_match": best.get("product_name") if best else "",
            "price": best.get("price") if best else "",
            "size": product_size(best) if best else "",
            "unit_price": best.get("unit_price", "") if best else "",
            "product_url": best.get("product_url", "") if best else "",
            "image_url": best.get("image_url", "") if best else "",
            "reason_selected": best.get("reason_selected", "") if best else "",
            "reason_skipped": skip_reason,
            "skip_reason": skip_reason,
            "candidate_count": len(store_candidates),
            "valid_candidate_count": len(viable_candidates),
            "rejected_candidate_count": len(rejected_candidates),
            "alternative_products": store_candidates,
            "alternatives": store_candidates,
            "valid_alternatives": viable_candidates,
            "rejected_products": rejected_candidates,
            "skip_reasons": unique_texts(raw.get("skip_reasons", [])),
            "agent_stages": raw.get("agent_stages", []),
        }
        records.append(record)

    return records


def first_store_localization(candidates):
    for candidate in candidates or []:
        if isinstance(candidate, dict) and isinstance(candidate.get("store_localization"), dict):
            localization = candidate.get("store_localization")
            if localization.get("proof_of_store_selection") or localization.get("verified") is not None:
                return localization
    return {}


def group_raw_store_results_by_store(raw_store_results):
    grouped = {}
    order = []

    for raw in raw_store_results:
        if not isinstance(raw, dict):
            continue

        store_key = raw.get("store_key", "")
        key = store_key or f"__raw_{len(order)}"

        if key not in grouped:
            grouped[key] = {
                "index": raw.get("index", len(order)),
                "item_key": raw.get("item_key") or normalize_item_key(raw.get("ingredient", "")),
                "ingredient": raw.get("ingredient", ""),
                "quantity": raw.get("quantity", ""),
                "quantity_context": raw.get("quantity_context", {}),
                "store_key": store_key,
                "store_name": raw.get("store_name", ""),
                "search_url": raw.get("search_url", ""),
                "search_urls": [],
                "search_terms": [],
                "store_location": raw.get("store_location", {}),
                "store_location_name": raw.get("store_location_name", ""),
                "store_location_address": raw.get("store_location_address", ""),
                "store_location_distance_miles": raw.get("store_location_distance_miles"),
                "candidates": [],
                "skip_reasons": [],
                "agent_stages": [],
            }
            order.append(key)

        record = grouped[key]
        record["index"] = min(record.get("index", raw.get("index", 0)), raw.get("index", record.get("index", 0)))
        if not record.get("item_key") and raw.get("item_key"):
            record["item_key"] = raw.get("item_key", "")
        if not record.get("quantity") and raw.get("quantity"):
            record["quantity"] = raw.get("quantity", "")
        if not record.get("quantity_context") and raw.get("quantity_context"):
            record["quantity_context"] = raw.get("quantity_context", {})
        record["candidates"].extend(raw.get("candidates", []))
        record["skip_reasons"] = unique_texts(record.get("skip_reasons", []) + raw.get("skip_reasons", []))
        record["agent_stages"].extend(raw.get("agent_stages", []))

        if raw.get("search_url"):
            record["search_urls"] = unique_texts(record.get("search_urls", []) + [raw.get("search_url")])
            record["search_url"] = record.get("search_url") or raw.get("search_url", "")

        if raw.get("search_term"):
            record["search_terms"] = unique_texts(record.get("search_terms", []) + [raw.get("search_term")])

        for key_name in [
            "store_location",
            "store_location_name",
            "store_location_address",
            "store_location_distance_miles",
        ]:
            if not record.get(key_name) and raw.get(key_name):
                record[key_name] = raw.get(key_name)

    return sorted(grouped.values(), key=lambda item: item.get("index", 0))


def best_available_store_candidate(ingredient, candidates):
    direct_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
        and candidate_has_direct_product_url(candidate)
    ]
    pool = direct_candidates or [
        candidate
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
    ]

    if not pool:
        return None

    return max(
        pool,
        key=lambda candidate: best_available_store_candidate_score(ingredient, candidate),
    )


def best_available_store_candidate_score(ingredient, candidate):
    match = best_ingredient_candidate_match(ingredient, candidate)
    name_tokens = set(tokenize(candidate.get("product_name", "")))
    score = 0.0

    score += 140 if match.get("exact_name_match") else 0
    score += 70 if match.get("exact_phrase_match") else 0
    score += match.get("name_token_ratio", 0) * 120
    score += match.get("token_ratio", 0) * 60
    score += max(-80, min(80, safe_float(candidate.get("score")) or 0)) * 0.2

    if candidate_has_direct_product_url(candidate):
        score += 45

    if candidate.get("price"):
        score += 8

    if candidate.get("detail_evaluated"):
        score += 8

    if is_plain_whole_item_request(ingredient):
        if name_tokens & WHOLE_ITEM_FALLBACK_AVOID_TERMS:
            score -= 120
        if name_tokens & WHOLE_ITEM_PACKAGE_TERMS:
            score += 20

    if candidate.get("viable") is False:
        score -= 8

    return score


def is_plain_whole_item_request(ingredient):
    tokens = set(tokenize(ingredient))

    if not tokens:
        return False

    product_form_terms = {
        "bar",
        "broth",
        "cream",
        "dough",
        "extract",
        "flour",
        "juice",
        "mix",
        "oil",
        "powder",
        "sauce",
        "seasoning",
        "sugar",
    }
    return not bool(tokens & product_form_terms)


def best_available_product_reason(ingredient, candidate, store_name=""):
    reasons = []
    if candidate_has_direct_product_url(candidate):
        reasons.append("direct product link")
    if candidate.get("price"):
        reasons.append("visible price")

    match = best_ingredient_candidate_match(ingredient, candidate)
    if match.get("exact_phrase_match") or match.get("name_token_ratio", 0) >= 0.8:
        reasons.append("closest product-name match")

    skip_reasons = candidate.get("skip_reasons", [])
    if skip_reasons:
        reasons.append("strict-rule issue: " + skip_reasons[0])

    return "Best available {store} candidate: {reasons}.".format(
        store=store_name or "store",
        reasons="; ".join(reasons) if reasons else "highest fallback match",
    )


def product_selection_reason(candidate, store_name=""):
    final_agent = candidate.get("final_selection_agent") or {}
    if final_agent.get("selected") and final_agent.get("reason"):
        return "Selected as the best {store} match because {reason}".format(
            store=store_name or "store",
            reason=final_agent.get("reason"),
        )

    reasons = [
        reason
        for reason in candidate.get("ranking_reasons", [])
        if reason
    ][:4]

    if reasons:
        return "Selected as the best {store} match because {reasons}.".format(
            store=store_name or "store",
            reasons="; ".join(reasons),
        )

    return "Selected as the highest-ranked valid product match for this store."


def store_skip_reason(store_name, raw_result, candidates):
    reasons = []
    reasons.extend(raw_result.get("skip_reasons", []))

    for candidate in candidates:
        reasons.extend(candidate.get("skip_reasons", []))

    reason = unique_texts(reasons)
    if reason:
        text = reason[0]
    elif candidates:
        text = "Product cards were found, but none passed matching, availability, price, detail, or food-rule checks."
    else:
        text = "No visible product cards or direct product links were found."

    if text.lower().startswith((store_name or "").lower()):
        return text

    return f"{store_name}: {text}" if store_name else text


def product_size(candidate):
    if not candidate:
        return ""

    return candidate.get("size") or candidate.get("package_size") or ""


def build_product_choice_record(
    ingredient,
    enabled_stores,
    stores,
    full_address,
    home_location,
    store_locations,
):
    candidates = []
    skip_reasons = []

    for store_key in enabled_stores:
        store = stores.get(store_key, {})
        store_location = store_locations.get(store_key, {})
        store_candidates, store_skips = search_store_products(
            ingredient,
            store_key,
            store,
            full_address,
            home_location,
            store_location,
        )
        store_candidates = enrich_product_candidates_from_pages(
            store_candidates,
            ingredient,
            store.get("label") or store_key.title(),
        )
        candidates.extend(store_candidates)
        skip_reasons.extend(store_skips)

    return build_product_choice_record_from_results(
        ingredient,
        [{
            "candidates": candidates,
            "skip_reasons": skip_reasons,
        }],
        full_address,
    )


def prioritize_candidates_for_detail(ingredient, candidates):
    return sorted(
        candidates,
        key=lambda candidate: pre_detail_candidate_score(ingredient, candidate),
        reverse=True,
    )


def pre_detail_candidate_score(ingredient, candidate):
    name = candidate.get("product_name", "")
    text = " ".join([
        name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("card_text_excerpt", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    match_candidate = dict(candidate)
    match_candidate["description"] = text
    match = best_ingredient_candidate_match(ingredient, match_candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    text_tokens = set(tokenize(text))
    name_tokens = set(tokenize(name))
    normalized_ingredient = normalize_match_text(match.get("ingredient", ingredient))
    normalized_name = normalize_match_text(name)
    score = 0

    if normalized_ingredient and normalized_ingredient == normalized_name:
        score += 80
    elif normalized_ingredient and normalized_ingredient in normalized_name:
        score += 55

    score += len(ingredient_tokens & name_tokens) * 22
    score += len(ingredient_tokens & text_tokens) * 10

    if candidate.get("price"):
        score += 8
    if candidate.get("image_url"):
        score += 3
    if candidate_needs_product_detail(candidate):
        score += 5
    if "organic" in text.lower():
        score += 4

    return score


def enrich_product_candidates_from_pages(
    candidates,
    ingredient,
    store_name,
    job_id=None,
    progress_index=None,
):
    enriched = []
    skip_detail_when_cards_are_rankable = any(
        candidate_has_rankable_card_evidence(ingredient, candidate)
        for candidate in candidates
    )
    detail_candidates = [
        candidate
        for candidate in candidates
        if candidate_needs_product_detail(candidate)
        and not skip_detail_when_cards_are_rankable
    ]
    limit = product_detail_limit()
    detail_ids = {
        candidate.get("id")
        for candidate in detail_candidates[:limit]
    }
    analysis_ids = {
        candidate.get("id")
        for candidate in detail_candidates[:product_ai_analysis_limit()]
    }
    total = min(len(detail_candidates), limit)
    evaluated = 0

    for candidate in candidates:
        if not candidate_needs_product_detail(candidate):
            candidate["shortlisted_for_detail"] = False
            enriched.append(mark_detail_skipped(candidate, "No direct product page URL was available."))
            continue

        if candidate.get("id") not in detail_ids:
            candidate["shortlisted_for_detail"] = False
            reason = (
                "Full product page was skipped because rendered product cards had enough direct evidence for ranking."
                if skip_detail_when_cards_are_rankable
                else f"Full product page was not evaluated because the per-store detail limit is {limit}."
            )
            enriched.append(mark_detail_skipped(
                candidate,
                reason,
            ))
            continue

        evaluated += 1
        candidate["shortlisted_for_detail"] = True
        use_chatgpt_analysis = candidate.get("id") in analysis_ids
        candidate["shortlisted_for_chatgpt_analysis"] = use_chatgpt_analysis
        if job_id and progress_index is not None:
            action = (
                "Opening fully loaded page for ChatGPT analysis"
                if use_chatgpt_analysis
                else "Opening full product page"
            )
            mark_product_download(
                job_id,
                progress_index,
                "running",
                f"{action} from {store_name} {evaluated} of {total}: {candidate.get('product_name', ingredient)}",
            )

        enriched.append(enrich_product_candidate_from_page(
            candidate,
            ingredient,
            use_chatgpt_analysis=use_chatgpt_analysis,
        ))

    return enriched


def candidate_needs_product_detail(candidate):
    if candidate.get("source") == "search-page-fallback":
        return False

    product_url = str(candidate.get("product_url") or "").strip()
    search_url = str(candidate.get("search_url") or "").strip()

    return product_url.startswith(("http://", "https://")) and product_url != search_url


def candidate_has_rankable_card_evidence(ingredient, candidate):
    if candidate.get("source") == "search-page-fallback":
        return False

    if not candidate_has_direct_product_url(candidate):
        return False

    card_evidence = clean_text(" ".join([
        candidate.get("card_text_excerpt", ""),
        candidate.get("product_card_text", ""),
        candidate.get("raw_product_html_snippet", ""),
        candidate.get("detail_text_excerpt", ""),
    ]))
    if not any([
        candidate.get("price"),
        candidate.get("package_size"),
        candidate.get("unit_price"),
        card_evidence,
    ]):
        return False

    match = best_ingredient_candidate_match(ingredient, candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    if not ingredient_tokens:
        return True

    name = candidate.get("product_name", "")
    name_tokens = set(tokenize(name))
    name_is_specific = (
        len(name_tokens) >= len(ingredient_tokens) + 1
        and len(clean_text(name)) <= 100
        and not PRICE_PATTERN.search(name)
    )
    if name_is_specific and match.get("name_token_ratio", 0) >= 0.8:
        return True

    url_text = normalize_match_text(urlparse(candidate.get("product_url") or "").path.replace("-", " "))
    url_overlap = len(ingredient_tokens & set(tokenize(url_text)))
    return url_overlap >= max(1, min(len(ingredient_tokens), 2))


def mark_detail_skipped(candidate, reason):
    candidate["detail_evaluated"] = False
    candidate["detail_fetch"] = {
        "status": "skipped",
        "method": "",
        "url": candidate.get("product_url", ""),
        "reason": reason,
    }
    candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + [reason])
    return candidate


def embed_product_candidate_images(candidates, job_id=None, progress_index=None, store_name=""):
    if not product_image_embedding_enabled():
        for candidate in candidates:
            candidate.setdefault("embedded_image_base64", "")
        return candidates

    limit = product_image_embed_limit()
    image_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("image_url") and not candidate.get("embedded_image_base64")
    ][:limit]
    image_candidate_ids = {candidate.get("id") for candidate in image_candidates if candidate.get("id")}
    total = len(image_candidates)
    completed = 0

    for candidate in candidates:
        if candidate.get("id") not in image_candidate_ids:
            candidate.setdefault("embedded_image_base64", "")
            continue

        if not candidate.get("image_url") or candidate.get("embedded_image_base64"):
            candidate.setdefault("embedded_image_base64", "")
            continue

        completed += 1
        if job_id and progress_index is not None:
            mark_product_download(
                job_id,
                progress_index,
                "running",
                "Embedding product image {done} of {total} from {store}: {name}".format(
                    done=completed,
                    total=total,
                    store=store_name or candidate.get("store_name", "store"),
                    name=candidate.get("product_name", "product"),
                ),
            )

        data_uri = product_image_data_uri(
            candidate.get("image_url", ""),
            referer=candidate.get("source_page_url") or candidate.get("product_url") or candidate.get("search_url") or "",
        )
        candidate["embedded_image_base64"] = data_uri
        candidate["embedded_image_base64_length"] = len(data_uri)

    return candidates


def product_image_data_uri(image_url, referer=""):
    image_url = clean_text(image_url)
    if not image_url:
        return ""

    if image_url.startswith("data:image/"):
        return image_url

    try:
        headers = dict(REQUEST_HEADERS)
        headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        if referer:
            headers["Referer"] = referer
        response = requests.get(
            image_url,
            headers=headers,
            timeout=(4, 12),
        )
        response.raise_for_status()
        content = response.content or b""
    except Exception:
        return ""

    if not content:
        return ""

    content_type = clean_text(response.headers.get("Content-Type", "")).split(";", 1)[0].lower()
    return image_bytes_to_data_uri(content, content_type=content_type)


def image_bytes_to_data_uri(content, content_type=""):
    max_bytes = product_image_embed_max_bytes()

    try:
        from PIL import Image

        image = Image.open(BytesIO(content))
        image.thumbnail(
            (product_image_embed_max_dimension(), product_image_embed_max_dimension()),
            Image.LANCZOS,
        )
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        png_bytes = output.getvalue()

        if len(png_bytes) > max_bytes:
            return ""

        return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    except Exception:
        pass

    if len(content) > max_bytes:
        return ""

    safe_type = content_type if content_type.startswith("image/") else "image/png"
    return "data:{mime};base64,{payload}".format(
        mime=safe_type,
        payload=base64.b64encode(content).decode("ascii"),
    )


def enrich_product_candidate_from_page(candidate, ingredient, use_chatgpt_analysis=False):
    product_url = candidate.get("product_url", "")
    fetch = fetch_product_page_html(
        product_url,
        candidate.get("product_name", ""),
        candidate.get("home_address", ""),
        candidate.get("home_location"),
        prefer_browser=use_chatgpt_analysis,
    )

    candidate["detail_fetch"] = {
        key: value
        for key, value in fetch.items()
        if key != "html"
    }

    html_text = fetch.get("html") or ""
    if not html_text:
        candidate["detail_evaluated"] = False
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + [f"Full product page could not be evaluated: {fetch.get('error') or 'empty page content'}"]
        )
        return candidate

    details = extract_product_details_from_html(html_text, fetch.get("final_url") or product_url, candidate)
    apply_product_details_to_candidate(candidate, details, fetch, ingredient)

    if use_chatgpt_analysis:
        apply_chatgpt_product_page_analysis(candidate, html_text, ingredient)

    return candidate


def fetch_product_page_html(product_url, expected_name="", full_address="", home_location=None, prefer_browser=False):
    result = {
        "status": "failed",
        "method": "requests",
        "url": product_url,
        "final_url": product_url,
        "html": "",
        "error": "",
    }
    browser_result = {}

    if should_use_product_reader_proxy(product_url):
        reader_result = fetch_product_page_html_with_reader(product_url, expected_name=expected_name)
        if reader_result.get("html"):
            return reader_result

    if prefer_browser and os.getenv("DISABLE_BROWSER_PRODUCT_FETCH") != "1":
        browser_result = fetch_product_page_html_with_browser(
            product_url,
            expected_name,
            full_address=full_address,
            home_location=home_location,
            wait_seconds=product_ai_browser_wait_seconds(),
            page_load_strategy="none",
        )
        if browser_result.get("html"):
            return browser_result

    try:
        response = requests.get(
            product_url,
            headers=REQUEST_HEADERS,
            timeout=(5, 12),
        )
        response.raise_for_status()
        result["final_url"] = response.url or product_url
        result["html"] = response.text or ""
        result["status"] = "done"
    except Exception as exc:
        result["error"] = str(exc)

    if (
        result.get("html")
        and product_page_html_looks_useful(result["html"], expected_name)
    ):
        result["text_length"] = len(BeautifulSoup(result["html"], "html.parser").get_text(" ", strip=True))
        return result

    if os.getenv("DISABLE_BROWSER_PRODUCT_FETCH") == "1":
        if not result.get("html"):
            return result

        result["status"] = "done"
        result["method"] = "requests"
        result["warning"] = (
            "Browser full-page fetch is disabled."
            if prefer_browser
            else "Page content looked sparse, and browser product fetch is disabled."
        )
        return result

    if not prefer_browser:
        browser_result = fetch_product_page_html_with_browser(
            product_url,
            expected_name,
            full_address=full_address,
            home_location=home_location,
        )
        if browser_result.get("html"):
            return browser_result

    if result.get("html"):
        result["status"] = "done"
        result["warning"] = browser_result.get("error") or "Browser fallback did not return page content."
        return result

    result["error"] = result.get("error") or browser_result.get("error") or "No page content was returned."
    return result


def fetch_product_page_html_with_reader(product_url, expected_name=""):
    result = {
        "status": "failed",
        "method": "reader-proxy",
        "url": product_url,
        "final_url": product_url,
        "reader_url": product_reader_proxy_url(product_url),
        "html": "",
        "error": "",
    }

    try:
        response = requests.get(
            result["reader_url"],
            headers=REQUEST_HEADERS,
            timeout=(6, 30),
        )
        response.raise_for_status()
        text = response.text or ""
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["html"] = text
    result["status"] = "done" if text else "failed"
    result["text_length"] = len(clean_text(text))

    if expected_name and text and not product_page_html_looks_useful(text, expected_name):
        result["warning"] = "Reader-loaded page content looked sparse."

    return result


def fetch_product_page_html_with_browser(
    product_url,
    expected_name="",
    full_address="",
    home_location=None,
    wait_seconds=None,
    page_load_strategy="eager",
):
    result = {
        "status": "failed",
        "method": "browser",
        "url": product_url,
        "final_url": product_url,
        "html": "",
        "error": "",
    }
    wait_seconds = wait_seconds or product_browser_wait_seconds()

    with PRODUCT_BROWSER_FETCH_LOCK:
        driver = None
        try:
            from PushShoppingList.services.recipe_extract_service import create_headless_chrome_driver

            driver = create_headless_chrome_driver(
                window_size="1365,1000",
                prefer_undetected=True,
                page_load_strategy=page_load_strategy,
            )
            driver.set_page_load_timeout(max(4, min(wait_seconds + 3, product_browser_wait_seconds() + 8)))
            driver.set_script_timeout(max(2, min(5, wait_seconds)))
            configure_browser_home_location(driver, product_url, home_location)

            try:
                driver.get(product_url)
            except Exception:
                try:
                    driver.execute_script("window.stop && window.stop();")
                except Exception:
                    pass
                if len(driver.page_source or "") < 800:
                    raise

            wait_for_browser_body_text(driver, timeout_seconds=wait_seconds)
            handle_browser_popups_and_location(driver, full_address)

            try:
                driver.execute_script(
                    """
                    window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.35));
                    setTimeout(() => window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.7)), 350);
                    setTimeout(() => window.scrollTo(0, 0), 700);
                    """
                )
                time.sleep(1.2)
            except Exception:
                pass

            html_text = driver.page_source or ""
            result["final_url"] = driver.current_url or product_url
            result["html"] = html_text
            result["status"] = "done" if html_text else "failed"
            result["text_length"] = len(BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True))

            if html_text and not product_page_html_looks_useful(html_text, expected_name):
                result["warning"] = "Browser-loaded page content looked sparse."
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    return result


def wait_for_browser_body_text(driver, timeout_seconds=6):
    deadline = time.monotonic() + max(1, timeout_seconds)

    while time.monotonic() < deadline:
        try:
            text_length = driver.execute_script(
                "return (document.body && document.body.innerText || '').length"
            )
        except Exception:
            text_length = 0

        if text_length >= 300:
            return True

        time.sleep(0.35)

    return False


def product_page_html_looks_useful(html_text, expected_name=""):
    soup = BeautifulSoup(html_text or "", "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))

    if len(page_text) < 300:
        return False

    lowered = page_text.lower()
    expected_tokens = set(tokenize(expected_name))
    matching_tokens = [
        token
        for token in expected_tokens
        if token in lowered
    ]

    if expected_tokens and len(matching_tokens) >= max(1, min(2, len(expected_tokens))):
        return True

    return any(term in lowered for term in ["price", "ingredients", "nutrition", "in stock", "pickup", "product"])


def extract_product_details_from_html(html_text, page_url, seed_candidate):
    soup = BeautifulSoup(html_text or "", "html.parser")
    mapping = best_product_mapping_for_candidate(soup, seed_candidate)
    visible_text = clean_text(soup.get_text(" ", strip=True))
    meta_description = meta_content(soup, "description", "og:description", "twitter:description")
    meta_title = meta_content(soup, "og:title", "twitter:title")
    title = clean_text(meta_title or (soup.title.get_text(" ", strip=True) if soup.title else ""))
    mapped_name = clean_text(
        mapping.get("name")
        or mapping.get("title")
        or mapping.get("productName")
        or mapping.get("product_name")
    ) if mapping else ""
    mapped_description = clean_text(
        mapping.get("description")
        or mapping.get("shortDescription")
        or mapping.get("longDescription")
    ) if mapping else ""
    brand = extract_brand_from_mapping(mapping) if mapping else ""
    price = extract_price_from_mapping(mapping) if mapping else ""
    image_url = extract_image_url_from_mapping(mapping) if mapping else ""
    canonical_url = canonical_product_url(soup, mapping, page_url)
    detail_text = clean_text(" ".join([
        mapped_name,
        title,
        brand,
        mapped_description,
        meta_description,
        visible_text[:2500],
    ]))
    ingredients_text = extract_ingredients_text(visible_text)
    package_size = extract_package_size(" ".join([mapped_name, title, visible_text[:1500]]))
    unit_price = extract_unit_price(" ".join([visible_text[:2500], mapped_description]))
    availability = extract_availability(mapping, visible_text)

    if not price:
        price_match = PRICE_PATTERN.search(visible_text)
        if price_match:
            price = price_match.group(0).replace(" ", "")

    return {
        "name": best_detail_name(mapped_name, title, seed_candidate.get("product_name", "")),
        "brand": brand,
        "description": mapped_description or meta_description,
        "ingredients_text": ingredients_text,
        "category": clean_text(mapping.get("category")) if mapping else "",
        "sku": clean_text(mapping.get("sku")) if mapping else "",
        "gtin": clean_text(
            mapping.get("gtin")
            or mapping.get("gtin12")
            or mapping.get("gtin13")
            or mapping.get("gtin14")
        ) if mapping else "",
        "price": price,
        "package_size": package_size,
        "size": package_size,
        "unit_price": unit_price.get("display", ""),
        "unit_price_value": unit_price.get("value"),
        "unit_price_unit": unit_price.get("unit", ""),
        "image_url": urljoin(page_url, image_url) if image_url else "",
        "availability": availability.get("text", ""),
        "in_stock": availability.get("in_stock"),
        "product_url": canonical_url,
        "detail_text_excerpt": detail_text[:2200],
        "is_organic": "organic" in detail_text.lower(),
    }


def apply_product_details_to_candidate(candidate, details, fetch, ingredient):
    candidate["detail_evaluated"] = True
    candidate["detail_source"] = fetch.get("method", "")

    for key in [
        "brand",
        "description",
        "ingredients_text",
        "category",
        "sku",
        "gtin",
        "size",
        "package_size",
        "unit_price",
        "unit_price_value",
        "unit_price_unit",
        "image_url",
        "availability",
        "in_stock",
        "detail_text_excerpt",
        "is_organic",
    ]:
        value = details.get(key)
        if value not in (None, ""):
            candidate[key] = value

    if details.get("name"):
        candidate["product_name"] = details["name"]

    if details.get("price"):
        candidate["price"] = details["price"]

    if details.get("product_url"):
        candidate["product_url"] = details["product_url"]

    if candidate.get("package_size") and not candidate.get("size"):
        candidate["size"] = candidate["package_size"]

    candidate["id"] = product_candidate_id(
        candidate.get("store_key"),
        candidate.get("product_url"),
        candidate.get("product_name"),
        candidate.get("price"),
    )
    candidate["ranking_reasons"] = unique_texts(
        candidate.get("ranking_reasons", [])
        + [f"Full product page evaluated with {fetch.get('method', 'requests')}."]
    )

    rule_text = " ".join([
        candidate.get("product_name", ""),
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
        "organic" if candidate.get("is_organic") else "",
    ])
    annotated = annotate_product_food_rules({
        "name": candidate.get("product_name", ""),
        "description": rule_text,
    })
    candidate["food_rule_status"] = annotated.get("food_rule_status", {})

    if not product_matches_ingredient(ingredient, candidate):
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + ["Full product page content did not confirm a strong ingredient match."]
        )


def apply_chatgpt_product_page_analysis(candidate, html_text, ingredient):
    analysis = analyze_product_page_with_chatgpt(candidate, html_text, ingredient)
    candidate["chatgpt_analysis"] = analysis

    if analysis.get("status") != "done":
        candidate["ranking_reasons"] = unique_texts(
            candidate.get("ranking_reasons", [])
            + [analysis.get("message") or "ChatGPT product page analysis was skipped."]
        )
        return candidate

    for key in [
        "brand",
        "description",
        "ingredients_text",
        "category",
        "size",
        "package_size",
        "unit_price",
        "image_url",
        "availability",
    ]:
        value = analysis.get(key)
        if value not in (None, ""):
            candidate[key] = value

    if analysis.get("product_name"):
        candidate["product_name"] = analysis["product_name"]

    if analysis.get("price"):
        candidate["price"] = analysis["price"]

    if analysis.get("unit_price_value") is not None:
        candidate["unit_price_value"] = analysis["unit_price_value"]

    if analysis.get("unit_price_unit"):
        candidate["unit_price_unit"] = analysis["unit_price_unit"]

    if analysis.get("in_stock") is not None:
        candidate["in_stock"] = analysis["in_stock"]

    if analysis.get("is_organic") is not None:
        candidate["is_organic"] = analysis["is_organic"]

    if candidate.get("package_size") and not candidate.get("size"):
        candidate["size"] = candidate["package_size"]

    candidate["chatgpt_confidence"] = analysis.get("confidence")
    candidate["chatgpt_ingredient_match_confidence"] = analysis.get("ingredient_match_confidence")
    candidate["chatgpt_food_rules_ok"] = analysis.get("food_rules_ok")
    candidate["chatgpt_is_correct_product"] = analysis.get("is_correct_product")
    candidate["ranking_reasons"] = unique_texts(
        candidate.get("ranking_reasons", [])
        + [analysis.get("reason") or "ChatGPT analyzed the fully loaded product page against the saved rules."]
    )

    missing_required = analysis.get("missing_required", [])
    blocked_by = analysis.get("blocked_by", [])
    food_rules_ok = analysis.get("food_rules_ok")
    deterministic_status = deterministic_candidate_food_rule_status(candidate)

    if food_rules_ok is False and not missing_required and not blocked_by:
        missing_required = ["ChatGPT could not confirm the required food preferences."]

    blocked_by = unique_texts(blocked_by + (deterministic_status.get("blocked_by") or []))
    if deterministic_status.get("missing_required"):
        missing_required = unique_texts(missing_required + deterministic_status.get("missing_required", []))
    else:
        missing_required = []

    if food_rules_ok is not None:
        food_rules_ok = bool(food_rules_ok) or (
            not missing_required
            and not blocked_by
            and not deterministic_status.get("missing_required")
        )

    if food_rules_ok is not None:
        candidate["food_rule_status"] = {
            "ok": bool(food_rules_ok) and not missing_required and not blocked_by,
            "needs_review": bool(missing_required or blocked_by or not food_rules_ok),
            "missing_required": missing_required,
            "blocked_by": blocked_by,
            "marker": food_rule_marker_text(missing_required, blocked_by),
        }

    if analysis.get("is_correct_product") is False:
        candidate["skip_reasons"] = unique_texts(
            candidate.get("skip_reasons", [])
            + ["ChatGPT analysis says the fully loaded product page does not match this shopping item."]
        )

    candidate["id"] = product_candidate_id(
        candidate.get("store_key"),
        candidate.get("product_url"),
        candidate.get("product_name"),
        candidate.get("price"),
    )
    return candidate


def deterministic_candidate_food_rule_status(candidate):
    rule_text = " ".join([
        candidate.get("product_name", ""),
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
        "organic" if candidate.get("is_organic") else "",
    ])
    annotated = annotate_product_food_rules({
        "name": candidate.get("product_name", ""),
        "description": rule_text,
    })
    return annotated.get("food_rule_status", {}) or {}


def analyze_product_page_with_chatgpt(candidate, html_text, ingredient):
    client = get_product_analysis_client()

    if not client:
        return {
            "status": "skipped",
            "message": "ChatGPT product analysis skipped because OPENAI_API_KEY is not set.",
        }

    page_payload = product_page_ai_payload(html_text)
    rules_payload = product_analysis_rules_payload()
    system_prompt = (
        "You analyze grocery product pages for a shopping-list app. "
        "Use the user's saved rules strictly. Return only valid JSON."
    )
    user_prompt = build_product_page_analysis_prompt(
        ingredient,
        candidate,
        rules_payload,
        page_payload,
    )
    prompt_payload = chatgpt_prompt_payload(
        "product-page-analysis",
        PRODUCT_ANALYSIS_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )

    try:
        with PRODUCT_AI_ANALYSIS_LOCK:
            response = client.chat.completions.create(
                model=PRODUCT_ANALYSIS_MODEL,
                messages=prompt_payload["messages"],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"ChatGPT product analysis failed: {exc}",
            "prompt": prompt_payload,
        }

    analysis = normalize_chatgpt_product_analysis(data)
    analysis["status"] = "done"
    analysis["model"] = PRODUCT_ANALYSIS_MODEL
    analysis["prompt"] = prompt_payload
    analysis["html_chars_sent"] = len(page_payload.get("html", ""))
    analysis["visible_text_chars_sent"] = len(page_payload.get("visible_text", ""))
    analysis["html_truncated"] = page_payload.get("html_truncated", False)
    analysis["visible_text_truncated"] = page_payload.get("visible_text_truncated", False)
    return analysis


def chatgpt_prompt_payload(kind, model, messages, temperature=0):
    return {
        "kind": kind,
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": message.get("role", ""),
                "content": message.get("content", ""),
            }
            for message in messages
        ],
    }


def product_page_ai_payload(html_text):
    soup = BeautifulSoup(html_text or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    visible_text = clean_text(soup.get_text(" ", strip=True))
    compact_html = re.sub(r"\s+", " ", str(soup)).strip()
    max_html = product_ai_html_chars()
    max_text = product_ai_text_chars()

    return {
        "visible_text": visible_text[:max_text],
        "visible_text_truncated": len(visible_text) > max_text,
        "html": compact_html[:max_html],
        "html_truncated": len(compact_html) > max_html,
    }


def product_analysis_rules_payload():
    try:
        food_rules = load_food_rules()
    except Exception:
        food_rules = {"require": [], "avoid": []}

    try:
        rules_display = load_rules_display()
        ranking_rules = rules_display.get("best_product_ranking", {}).get("rows", [])
    except Exception:
        ranking_rules = []

    return {
        "food_rules": food_rules,
        "best_product_ranking": ranking_rules,
    }


def build_product_page_analysis_prompt(ingredient, candidate, rules_payload, page_payload):
    extracted = {
        "store": candidate.get("store_name", ""),
        "candidate_name": candidate.get("product_name", ""),
        "candidate_price": candidate.get("price", ""),
        "candidate_size": product_size(candidate),
        "requested_quantity": candidate.get("requested_quantity", ""),
        "candidate_url": candidate.get("product_url", ""),
        "search_url": candidate.get("search_url", ""),
        "local_food_rule_status": candidate.get("food_rule_status", {}),
    }

    return f"""
Analyze this grocery product page for the shopping item:
{ingredient}

Total shopping-list quantity needed:
{candidate.get("requested_quantity") or "Not specified"}

Candidate already extracted by the app:
{json.dumps(extracted, ensure_ascii=False)}

Saved food rules:
{json.dumps(rules_payload.get("food_rules", {}), ensure_ascii=False)}

Saved best-product ranking guidance:
{json.dumps(rules_payload.get("best_product_ranking", []), ensure_ascii=False)}

Rules for your analysis:
- Decide whether this is a specific purchasable grocery product that matches the shopping item. If the shopping item contains OR/and-or alternatives, matching any one alternative is acceptable.
- Take the total shopping-list quantity into account when judging whether the package size is a good fit.
- For a plain whole-food item such as lemon, onion, basil, asparagus, or egg, prefer the actual whole grocery item over juice, extract, drinks, desserts, mixes, prepared foods, cleaners, or scented products unless the shopping item asks for those forms.
- Apply required food rules strictly. If the fully loaded product page does not confirm a required trait, include that rule under missing_required.
- Apply avoid rules strictly. If the product page ingredients, title, labels, or description include an avoided term, include that rule under blocked_by.
- Do not call a product food_rules_ok if required rules are missing or avoid rules are present.
- Prefer evidence from product name, labels, ingredients, nutrition, availability, and price. Do not use unrelated recommendations, ads, or footer text.

Fully loaded product page visible text:
{page_payload.get("visible_text", "")}

Fully loaded product page HTML excerpt:
{page_payload.get("html", "")}

Return only JSON with this shape:
{{
  "is_product_page": true,
  "is_correct_product": true,
  "ingredient_match_confidence": 0.0,
  "food_rules_ok": true,
  "missing_required": [],
  "blocked_by": [],
  "product_name": "",
  "brand": "",
  "description": "",
  "ingredients_text": "",
  "category": "",
  "price": "",
  "size": "",
  "package_size": "",
  "unit_price": "",
  "unit_price_value": null,
  "unit_price_unit": "",
  "availability": "",
  "in_stock": null,
  "is_organic": null,
  "confidence": 0.0,
  "reason": "",
  "evidence": []
}}
"""


def normalize_chatgpt_product_analysis(data):
    data = data if isinstance(data, dict) else {}

    return {
        "is_product_page": bool_or_none(data.get("is_product_page")),
        "is_correct_product": bool_or_none(data.get("is_correct_product")),
        "ingredient_match_confidence": bounded_confidence(data.get("ingredient_match_confidence")),
        "food_rules_ok": bool_or_none(data.get("food_rules_ok")),
        "missing_required": clean_text_list(data.get("missing_required")),
        "blocked_by": clean_text_list(data.get("blocked_by")),
        "product_name": clean_text(data.get("product_name")),
        "brand": clean_text(data.get("brand")),
        "description": clean_text(data.get("description")),
        "ingredients_text": clean_text(data.get("ingredients_text")),
        "category": clean_text(data.get("category")),
        "price": clean_text(data.get("price")),
        "size": clean_text(data.get("size")),
        "package_size": clean_text(data.get("package_size")),
        "unit_price": clean_text(data.get("unit_price")),
        "unit_price_value": safe_float(data.get("unit_price_value")),
        "unit_price_unit": clean_text(data.get("unit_price_unit")),
        "availability": clean_text(data.get("availability")),
        "in_stock": bool_or_none(data.get("in_stock")),
        "is_organic": bool_or_none(data.get("is_organic")),
        "confidence": bounded_confidence(data.get("confidence")),
        "reason": clean_text(data.get("reason")),
        "evidence": clean_text_list(data.get("evidence")),
    }


def clean_json_response(text):
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    return value


def bool_or_none(value):
    if isinstance(value, bool):
        return value

    text = str(value or "").strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False

    return None


def bounded_confidence(value):
    number = safe_float(value)
    if number is None:
        return None

    return round(max(0.0, min(1.0, number)), 3)


def clean_text_list(value):
    if isinstance(value, str):
        parts = re.split(r"[,;\n]+", value)
    elif isinstance(value, list):
        parts = value
    else:
        parts = []

    return unique_texts(parts)


def food_rule_marker_text(missing_required, blocked_by):
    issues = []
    issues.extend(missing_required or [])
    issues.extend(blocked_by or [])

    return "Food rule review: " + "; ".join(issues) if issues else ""


def best_product_mapping_for_candidate(soup, candidate):
    mappings = []
    mappings.extend(extract_json_ld_products(soup))
    mappings.extend(extract_embedded_product_mappings(soup))

    if not mappings:
        return {}

    candidate_name = str(candidate.get("product_name") or "").lower()
    candidate_tokens = set(tokenize(candidate_name))

    def mapping_score(mapping):
        name = clean_text(
            mapping.get("name")
            or mapping.get("title")
            or mapping.get("productName")
            or mapping.get("product_name")
        ).lower()
        tokens = set(tokenize(name))
        score = len(candidate_tokens & tokens) * 5

        if candidate_name and candidate_name in name:
            score += 20

        if has_price_value(mapping):
            score += 4

        if mapping.get("description"):
            score += 3

        return score

    return max(mappings, key=mapping_score)


def meta_content(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    return ""


def canonical_product_url(soup, mapping, page_url):
    mapped_url = extract_product_url_from_mapping(mapping or {})
    if mapped_url:
        return urljoin(page_url, str(mapped_url))

    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        return urljoin(page_url, canonical.get("href"))

    return page_url


def best_detail_name(mapped_name, title, fallback):
    for value in [mapped_name, title, fallback]:
        text = clean_text(value)
        if text and len(text) <= 180:
            return text

    return clean_text(fallback)


def extract_brand_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    brand = mapping.get("brand") or mapping.get("manufacturer")

    if isinstance(brand, dict):
        return clean_text(brand.get("name") or brand.get("brandName"))

    if isinstance(brand, list):
        names = [
            extract_brand_from_mapping({"brand": item})
            for item in brand
        ]
        return clean_text(" ".join(name for name in names if name))

    return clean_text(brand)


def extract_ingredients_text(visible_text):
    match = re.search(
        r"\bingredients?\b[:\s]+(.{20,900}?)(?:\bcontains\b|\bnutrition\b|\bdirections\b|\bwarnings\b|\babout\b|$)",
        visible_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return clean_text(match.group(1))[:800]


def extract_package_size(text):
    match = PACKAGE_SIZE_PATTERN.search(str(text or ""))
    return clean_text(match.group(0)) if match else ""


def extract_unit_price(text):
    match = UNIT_PRICE_PATTERN.search(str(text or ""))

    if not match:
        return {}

    value = safe_float(match.group(1))
    unit = normalize_unit(match.group(2))

    return {
        "display": f"${value:.2f}/{unit}" if value is not None and unit else clean_text(match.group(0)),
        "value": value,
        "unit": unit,
    }


def extract_availability(mapping, visible_text):
    text_parts = []

    if isinstance(mapping, dict):
        offers = mapping.get("offers") or mapping.get("offer")
        if isinstance(offers, dict):
            text_parts.append(str(offers.get("availability") or ""))
            text_parts.append(str(offers.get("inventoryLevel") or ""))
        elif isinstance(offers, list):
            for offer in offers[:4]:
                if isinstance(offer, dict):
                    text_parts.append(str(offer.get("availability") or ""))
                    text_parts.append(str(offer.get("inventoryLevel") or ""))

    text_parts.append(str(visible_text or "")[:2500])
    haystack = clean_text(" ".join(text_parts)).lower()

    out_terms = [
        "out of stock",
        "currently unavailable",
        "not available",
        "unavailable",
        "sold out",
    ]
    in_terms = [
        "in stock",
        "pickup available",
        "available for pickup",
        "available today",
        "delivery available",
        "add to cart",
    ]

    if any(term in haystack for term in out_terms):
        return {"text": "Out of stock or unavailable", "in_stock": False}

    if any(term in haystack for term in in_terms):
        return {"text": "Available", "in_stock": True}

    return {"text": "", "in_stock": None}


def product_matches_ingredient(ingredient, candidate):
    match = best_ingredient_candidate_match(ingredient, candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    if not ingredient_tokens:
        return True

    overlap = match.get("overlap", 0)

    return overlap >= max(1, min(len(ingredient_tokens), 2))


def search_store_products(
    ingredient,
    store_key,
    store,
    full_address,
    home_location,
    store_location,
    search_term=None,
    search_url=None,
    product_agent_prompt_builder=None,
    browser_visible=False,
    browser_visual_pause_seconds=0,
    browser_visual_hold_seconds=0,
):
    store_name = store.get("label") or store_key.title()
    search_term = search_term or ingredient
    search_url = search_url or build_product_search_url(store, search_term)
    skip_reasons = []

    if not search_url:
        return [], [f"{store_name}: no product search URL is configured."]

    request_candidates = []
    request_skip_reasons = []

    if product_search_browser_enabled():
        browser_candidates, browser_skip_reasons = search_store_products_with_browser_agent(
            ingredient,
            store_key,
            store,
            search_url,
            full_address,
            home_location,
            store_location,
            search_term=search_term,
            product_agent_prompt_builder=product_agent_prompt_builder,
            browser_visible=browser_visible,
            browser_visual_pause_seconds=browser_visual_pause_seconds,
            browser_visual_hold_seconds=browser_visual_hold_seconds,
        )

        if browser_candidates:
            return browser_candidates, unique_texts(browser_skip_reasons)

        skip_reasons.extend(browser_skip_reasons)

        if localized_inventory_blocking_failure(skip_reasons):
            return [], unique_texts(skip_reasons)

    if product_search_browser_enabled() and not product_static_search_fallback_enabled():
        fallback = build_search_page_candidate(
            ingredient,
            store_key,
            store_name,
            search_url,
            full_address,
            store_location,
            "The generic browser agent did not return product candidates, and static request scraping is disabled.",
        )
        return [fallback], unique_texts(skip_reasons + [f"{store_name}: generic browser agent returned no product candidates."])

    try:
        response = requests.get(
            search_url,
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
    except Exception as exc:
        request_skip_reasons.append(f"{store_name}: product search request failed: {exc}")
        response = None
    else:
        request_candidates = parse_product_candidates_from_html(
            response.text,
            response.url,
            ingredient,
            store_key,
            store_name,
            search_url,
            full_address,
            home_location,
            store_location,
        )

        if not request_candidates:
            request_skip_reasons.append(f"{store_name}: no parseable product cards were found in the initial HTML.")

    if request_candidates:
        if skip_reasons:
            for candidate in request_candidates:
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Used request HTML product data only after Selenium rendered-page extraction did not return visible cards."]
                )
        return request_candidates, unique_texts(skip_reasons)

    skip_reasons.extend(request_skip_reasons)

    fallback = build_search_page_candidate(
        ingredient,
        store_key,
        store_name,
        (response.url if response else "") or search_url,
        full_address,
        store_location,
        "No product cards with prices could be parsed from this store page.",
    )
    return [fallback], unique_texts(skip_reasons + [f"{store_name}: no parseable product cards were found."])


def search_store_products_with_browser_agent(
    ingredient,
    store_key,
    store,
    search_url,
    full_address,
    home_location,
    store_location,
    search_term=None,
    product_agent_prompt_builder=None,
    browser_visible=False,
    browser_visual_pause_seconds=0,
    browser_visual_hold_seconds=0,
):
    store_name = store.get("label") or store_key.title()

    with PRODUCT_BROWSER_FETCH_LOCK:
        driver = None

        try:
            from PushShoppingList.services.recipe_extract_service import create_headless_chrome_driver
            from PushShoppingList.services.recipe_extract_service import wait_for_browser_document

            driver = create_headless_chrome_driver(
                window_size="1440,1100",
                prefer_undetected=True,
                page_load_strategy="normal",
                headless=not browser_visible,
                user_data_dir=store_browser_profile_dir(store_key, full_address, store_location),
            )
            if browser_visible:
                try:
                    driver.maximize_window()
                except Exception:
                    pass
            driver.set_page_load_timeout(product_browser_wait_seconds() + 8)
            configure_browser_home_location(driver, search_url, home_location)

            store_session_status = prepare_store_session_before_product_search(
                driver,
                store_key,
                store,
                search_url,
                full_address,
                home_location,
                store_location,
                store_name,
                browser_visible,
                browser_visual_pause_seconds,
            )
            if (
                store_session_status
                and not store_session_status.get("ok")
                and (
                    store_session_has_zip_mismatch(store_session_status)
                    or not store_session_update_allows_product_search(store_session_status)
                )
            ):
                return [], [
                    store_session_status.get("message")
                    or f"{store_name}: selected store location could not be updated before search."
                ]

            open_product_search_after_storefront(
                driver,
                search_url,
                store_key,
                store_session_status,
                search_term=search_term,
            )

            visual_browser_pause(browser_visible, browser_visual_pause_seconds)
            wait_for_browser_document(driver, timeout_seconds=product_browser_wait_seconds())
            handle_browser_popups_and_location(driver, full_address, store_location=store_location)
            visual_browser_pause(browser_visible, browser_visual_pause_seconds)
            wait_for_rendered_product_cards(
                driver,
                timeout_seconds=max(3, product_browser_wait_seconds() / 3),
            )
            scroll_rendered_product_results_until_stable(driver)
            visual_browser_pause(browser_visible, browser_visual_pause_seconds)
            handle_browser_popups_and_location(driver, full_address, store_location=store_location)
            final_url = driver.current_url or search_url
            rendered_snapshot = capture_rendered_product_page_snapshot(driver)
            context_status = rendered_store_context_status(
                driver,
                store_key,
                store_name,
                full_address,
                store_location,
            )
            context_status = merge_store_session_selection_proof(
                context_status,
                store_session_status,
            )
            rendered_page = save_rendered_product_search_html(
                store_key,
                ingredient,
                search_term=search_term or ingredient,
                page_url=final_url,
                html_text=rendered_snapshot.get("html", ""),
                visible_text=rendered_snapshot.get("visible_text", ""),
                product_related_html=rendered_snapshot.get("product_related_html", ""),
                localization_status=context_status,
            )
            if not context_status.get("ok"):
                message = context_status.get("message") or f"{store_name}: rendered page did not match the saved store context."
                if rendered_page.get("path"):
                    message = f"{message} Saved rendered page HTML: {rendered_page.get('path')}"
                return [], [message]

            close_browser_after_rendered_snapshot(driver, browser_visible, browser_visual_hold_seconds)
            driver = None

            visible_cards = rendered_snapshot.get("visible_cards", [])
            visible_candidates = product_candidates_from_visible_cards(
                visible_cards,
                ingredient,
                store_key,
                store_name,
                final_url,
                search_url,
                full_address,
                home_location,
                store_location,
            )
            if should_skip_rendered_html_chatgpt(ingredient, visible_candidates):
                chatgpt_candidates = []
                chatgpt_skip_reasons = [
                    f"{store_name}: ChatGPT rendered-HTML product reasoning skipped because visible product cards were already extracted."
                ]
            else:
                chatgpt_candidates, chatgpt_skip_reasons = identify_rendered_html_products_with_chatgpt(
                    ingredient,
                    store_key,
                    store_name,
                    final_url,
                    search_url,
                    full_address,
                    home_location,
                    store_location,
                    rendered_page,
                    visible_cards,
                    prompt_builder=product_agent_prompt_builder,
                )
            rendered_candidates = parse_product_candidates_from_html(
                rendered_snapshot.get("html", ""),
                final_url,
                ingredient,
                store_key,
                store_name,
                search_url,
                full_address,
                home_location,
                store_location,
            )

            candidates = dedupe_candidates(chatgpt_candidates + visible_candidates + rendered_candidates)
            if candidates:
                for candidate in candidates:
                    candidate["rendered_page_url"] = rendered_page.get("url", final_url)
                    candidate["rendered_page_html_path"] = rendered_page.get("path", "")
                    candidate["rendered_page_text_path"] = rendered_page.get("visible_text_path", "")
                    candidate["rendered_page_prompt_preview_path"] = rendered_page.get("prompt_preview_path", "")
                    candidate["rendered_page_product_related_html_path"] = rendered_page.get("product_related_html_path", "")
                    candidate["rendered_page_html_length"] = rendered_page.get("html_length", 0)
                    candidate["rendered_page_visible_text_length"] = rendered_page.get("visible_text_length", 0)
                    candidate["rendered_page_html_excerpt"] = rendered_page.get("prompt_html", "")
                    candidate["store_localization"] = rendered_page.get("localization", {})
                    candidate["proof_of_store_selection"] = rendered_page.get("localization", {}).get("proof_of_store_selection", [])
                    candidate["ranking_reasons"] = unique_texts(
                        candidate.get("ranking_reasons", [])
                        + ["Generic browser agent opened, fully rendered, scrolled, cleaned, and saved the grocery page using the saved home address context."]
                    )
                return candidates[:product_candidate_limit()], unique_texts(chatgpt_skip_reasons)

            return [], unique_texts(chatgpt_skip_reasons + [f"{store_name}: generic browser agent found no visible product-related content on the rendered search page."])
        except Exception as exc:
            return [], [f"{store_name}: browser agent could not inspect rendered search page: {exc}"]
        finally:
            if driver is not None:
                visual_browser_pause(browser_visible, browser_visual_hold_seconds)
                try:
                    driver.quit()
                except Exception:
                    pass


def visual_browser_pause(enabled, seconds):
    if not enabled:
        return
    try:
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return
    time.sleep(min(60, seconds))


def store_browser_profile_dir(store_key, full_address="", store_location=None):
    if normalize_item_key(store_key) != "aldi":
        return None

    zip_code = extract_zip_code((store_location or {}).get("address", "")) or extract_zip_code(full_address)
    profile_key = zip_code or hashlib.sha1(clean_text(full_address).encode("utf-8", errors="ignore")).hexdigest()[:10]
    profile_key = re.sub(r"[^a-zA-Z0-9_-]+", "_", profile_key or "default").strip("_") or "default"
    return PRODUCT_BROWSER_PROFILES_DIR / f"aldi_{profile_key}"


def should_skip_rendered_html_chatgpt(ingredient, visible_candidates):
    required = product_rendered_html_chatgpt_min_visible_cards()
    if required <= 0:
        return False

    rankable_count = sum(
        1
        for candidate in visible_candidates or []
        if candidate_has_rankable_card_evidence(ingredient, candidate)
    )
    return rankable_count >= required


def close_browser_after_rendered_snapshot(driver, browser_visible=False, browser_visual_hold_seconds=0):
    if driver is None:
        return

    visual_browser_pause(browser_visible, browser_visual_hold_seconds)
    try:
        driver.quit()
    except Exception:
        pass


def store_session_update_payload(store_session_status):
    if not isinstance(store_session_status, dict):
        return {}

    update = store_session_status.get("home_store_update")
    if not isinstance(update, dict):
        update = store_session_status

    return update if isinstance(update, dict) else {}


def store_session_update_has_store_confirmation(store_session_status):
    update = store_session_update_payload(store_session_status)
    return any(
        bool(update.get(key))
        for key in [
            "ok",
            "clicked_shop_this_store",
            "clicked_continue",
            "clicked_final",
        ]
    )


def store_session_update_has_address_selection(store_session_status):
    update = store_session_update_payload(store_session_status)
    return any(
        bool(update.get(key))
        for key in [
            "clicked_address_suggestion",
            "clicked_save_address",
        ]
    )


def store_session_update_allows_product_search(store_session_status):
    if store_session_has_zip_mismatch(store_session_status):
        return False
    return (
        store_session_update_has_store_confirmation(store_session_status)
        or store_session_update_has_address_selection(store_session_status)
    )


def store_session_has_zip_mismatch(store_session_status):
    if not isinstance(store_session_status, dict):
        return False
    haystack = " ".join(
        clean_text(value)
        for value in [
            store_session_status.get("message", ""),
            *store_session_status.get("errors", []),
        ]
    ).lower()
    return "expected store zip" in haystack and "found visible zip" in haystack


def merge_store_session_selection_proof(context_status, store_session_status):
    context_status = context_status if isinstance(context_status, dict) else {}

    if context_status.get("ok") or not store_session_update_has_store_confirmation(store_session_status):
        return context_status

    update = store_session_update_payload(store_session_status)
    proof = unique_texts(
        context_status.get("proof_of_store_selection", [])
        + [
            "Store selector flow completed before search: first store card was selected and the store confirmation button was clicked."
        ]
    )
    errors = [
        error
        for error in context_status.get("errors", [])
        if "localized store session could not be proven" not in clean_text(error).lower()
    ]

    context_status.update({
        "ok": not errors,
        "verified": not errors,
        "message": " ".join(errors),
        "proof_of_store_selection": proof,
        "errors": errors,
        "home_store_update": update,
    })
    return context_status


def open_product_search_after_storefront(driver, search_url, store_key, store_session_status=None, search_term=None):
    if normalize_item_key(store_key) == "aldi" and store_session_update_allows_product_search(store_session_status):
        if (
            store_session_update_has_store_confirmation(store_session_status)
            and not store_session_reused_profile(store_session_status)
            and not store_session_context_verified(store_session_status)
        ):
            wait_for_current_url_contains(driver, "/store/aldi/storefront", timeout_seconds=12)
        return open_aldi_product_search(driver, search_url, search_term=search_term)

    try:
        driver.get(search_url)
    except Exception:
        if len(driver.page_source or "") < 800:
            raise


def open_aldi_product_search(driver, search_url, search_term=None):
    search_url = str(search_url or "").strip()
    if not search_url:
        return False

    search_term = clean_text(search_term or aldi_search_term_from_url(search_url))
    if aldi_search_page_loaded(driver, search_url, search_term) and not aldi_current_url_is_product_detail(driver):
        return True

    if aldi_current_url_is_product_detail(driver):
        force_open_aldi_search_url(driver, search_url)
        if wait_for_aldi_search_page(driver, search_url, search_term, timeout_seconds=6):
            return True

    if search_term and submit_aldi_search_box(driver, search_term):
        if wait_for_aldi_search_page(driver, search_url, search_term, timeout_seconds=8):
            return True

    force_open_aldi_search_url(driver, search_url)

    if wait_for_aldi_search_page(driver, search_url, search_term, timeout_seconds=8):
        return True

    if search_term and submit_aldi_search_box(driver, search_term):
        return wait_for_aldi_search_page(driver, search_url, search_term, timeout_seconds=8)

    return False


def force_open_aldi_search_url(driver, search_url):
    search_url = str(search_url or "").strip()
    if not search_url:
        return False

    if aldi_current_url_is_product_detail(driver):
        try:
            driver.execute_script("window.location.assign(arguments[0]);", search_url)
        except Exception:
            pass
        else:
            return True

    try:
        driver.get(search_url)
    except Exception:
        if len(driver.page_source or "") < 800:
            raise

    if not aldi_current_url_is_product_detail(driver):
        return True

    try:
        driver.get("about:blank")
    except Exception:
        pass

    try:
        driver.get(search_url)
        return True
    except Exception:
        if len(driver.page_source or "") < 800:
            raise

    try:
        driver.execute_script("window.location.assign(arguments[0]);", search_url)
        return True
    except Exception:
        return False


def submit_aldi_search_box(driver, search_term):
    search_term = clean_text(search_term)
    if not search_term:
        return False

    try:
        return bool(driver.execute_script(
            """
            const term = arguments[0];
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                "value"
            ).set;

            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const style = window.getComputedStyle(node);
                    if (node.hidden || style.display === "none" || style.visibility === "hidden") {
                        return false;
                    }
                    node = node.parentElement;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            const selectors = [
                "form[role='search'] input",
                "form[data-identifier='search_input'] input",
                "#search-bar-input",
                "input[aria-autocomplete]",
                "input[type='search']",
                "input[placeholder*='Search' i]"
            ];
            const inputs = selectors
                .flatMap(selector => Array.from(document.querySelectorAll(selector)))
                .filter((input, index, all) => all.indexOf(input) === index)
                .filter(visible);
            const input = inputs[0];
            if (!input) {
                return false;
            }

            input.focus();
            nativeInputValueSetter.call(input, term);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));

            const form = input.closest("form");
            if (form) {
                if (typeof form.requestSubmit === "function") {
                    form.requestSubmit();
                } else {
                    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
                }
                return true;
            }

            const button = document.querySelector(
                "form[role='search'] button[type='submit'], form[data-identifier='search_input'] button[type='submit'], button[aria-label='Search']"
            );
            if (button && visible(button)) {
                button.click();
                return true;
            }

            input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
            input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
            return true;
            """,
            search_term,
        ))
    except Exception:
        return False


def wait_for_aldi_search_page(driver, search_url, search_term="", timeout_seconds=8):
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        if aldi_search_page_loaded(driver, search_url, search_term):
            return True
        time.sleep(0.4)
    return False


def aldi_search_page_loaded(driver, search_url, search_term=""):
    search_term = clean_text(search_term or aldi_search_term_from_url(search_url))
    normalized_term = normalize_match_text(search_term)

    try:
        current_url = str(driver.current_url or "")
    except Exception:
        current_url = ""

    if current_url:
        parsed = urlparse(current_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        current_term = clean_text(query.get("k") or query.get("q") or "")
        if "/store/aldi/s" in parsed.path and (
            not normalized_term
            or normalize_match_text(current_term) == normalized_term
        ):
            return True

    if normalized_term:
        try:
            text = clean_text(driver.execute_script("return document.body && document.body.innerText || '';"))
        except Exception:
            text = ""
        normalized_text = normalize_match_text(text[:4000])
        if re.search(rf"\bresults for\b.{0,20}\b{re.escape(normalized_term)}\b", normalized_text):
            return True

    return False


def aldi_search_term_from_url(search_url):
    try:
        parsed = urlparse(str(search_url or ""))
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        return clean_text(query.get("k") or query.get("q") or "")
    except Exception:
        return ""


def wait_for_current_url_contains(driver, text, timeout_seconds=10):
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        try:
            current_url = str(driver.current_url or "")
        except Exception:
            current_url = ""
        if text in current_url:
            return True
        time.sleep(0.4)
    return False


def store_session_reused_profile(store_session_status):
    update = store_session_update_payload(store_session_status)
    return bool(update.get("reused_profile_session"))


def store_session_context_verified(store_session_status):
    return bool(
        isinstance(store_session_status, dict)
        and (
            store_session_status.get("ok")
            or store_session_status.get("verified")
            or store_session_status.get("proof_of_store_selection")
        )
    )


def prepare_store_session_before_product_search(
    driver,
    store_key,
    store,
    search_url,
    full_address,
    home_location,
    store_location,
    store_name,
    browser_visible=False,
    browser_visual_pause_seconds=0,
):
    if normalize_item_key(store_key) == "aldi":
        start_url = aldi_store_session_url(search_url, full_address, store_location)
    else:
        start_url = str(store.get("urlStoreSelector") or store.get("url") or "").strip()
    if not start_url:
        start_url = store.get("urlStoreSelector") or store.get("url") or search_url

    try:
        from PushShoppingList.services.recipe_extract_service import wait_for_browser_document
        from PushShoppingList.scripts.stores.home_store_router import route_update_home_store

        configure_browser_home_location(driver, start_url, home_location)

        if normalize_item_key(store_key) == "aldi":
            reused_status = try_reuse_aldi_profile_store_session(
                driver,
                search_url,
                start_url,
                store_key,
                store_name,
                full_address,
                store_location,
                wait_for_browser_document,
            )
            if reused_status.get("ok"):
                reused_status["pre_search_store_url"] = start_url
                return reused_status

        update_result = route_update_home_store(
            driver=driver,
            store_key=store_key,
            store=store,
            full_address=full_address,
            store_location=store_location,
            start_url=start_url,
            worker_id=0,
            wait_seconds=max(2, min(8, product_browser_wait_seconds() / 2)),
        )
        visual_browser_pause(browser_visible, browser_visual_pause_seconds)
        if not update_result.get("already_selected"):
            wait_for_browser_document(driver, timeout_seconds=product_browser_wait_seconds())

        status = rendered_store_context_status(
            driver,
            store_key,
            store_name,
            full_address,
            store_location,
        )
        if update_result.get("already_selected"):
            status.update({
                "ok": True,
                "verified": True,
                "message": "",
                "proof_of_store_selection": unique_texts(
                    status.get("proof_of_store_selection", [])
                    + ["ALDI home store was already confirmed from the visible page before product search."]
                ),
                "errors": [],
            })
        status["home_store_update"] = update_result
        status["pre_search_store_url"] = start_url
        if not status.get("ok"):
            status["message"] = (
                status.get("message")
                or update_result.get("message")
                or f"{store_name}: could not update the website selected store before searching."
            )
        return status
    except Exception as exc:
        return {
            "ok": False,
            "verified": False,
            "message": f"{store_name}: could not update selected store before search: {exc}",
            "pre_search_store_url": start_url,
            "proof_of_store_selection": [],
            "errors": [str(exc)],
        }


def try_reuse_aldi_profile_store_session(
    driver,
    search_url,
    start_url,
    store_key,
    store_name,
    full_address,
    store_location,
    wait_for_browser_document,
):
    search_url = str(search_url or "").strip()
    start_url = str(start_url or "").strip()
    profile_probe_url = search_url or start_url
    search_term = aldi_search_term_from_url(search_url)

    try:
        driver.get(profile_probe_url)
        wait_for_browser_document(driver, timeout_seconds=max(3, min(7, product_browser_wait_seconds() / 2)))
        status = rendered_store_context_status(
            driver,
            store_key,
            store_name,
            full_address,
            store_location,
        )
        if status.get("ok") and search_url and (
            aldi_current_url_is_product_detail(driver)
            or (search_term and not aldi_search_page_loaded(driver, search_url, search_term))
        ):
            force_open_aldi_search_url(driver, search_url)
            wait_for_browser_document(driver, timeout_seconds=max(3, min(7, product_browser_wait_seconds() / 2)))
            refreshed_status = rendered_store_context_status(
                driver,
                store_key,
                store_name,
                full_address,
                store_location,
            )
            if refreshed_status.get("ok"):
                status = refreshed_status
        elif search_url and search_term and not aldi_search_page_loaded(driver, search_url, search_term):
            open_aldi_product_search(driver, search_url, search_term=search_term)
            wait_for_browser_document(driver, timeout_seconds=max(3, min(7, product_browser_wait_seconds() / 2)))
            status = rendered_store_context_status(
                driver,
                store_key,
                store_name,
                full_address,
                store_location,
            )
    except Exception as exc:
        return {
            "ok": False,
            "verified": False,
            "message": f"{store_name}: saved browser profile could not be checked quickly: {exc}",
            "home_store_update": {
                "attempted": False,
                "ok": False,
                "reused_profile_session": False,
            },
        }

    if not status.get("ok"):
        return status

    status["home_store_update"] = {
        "attempted": False,
        "ok": True,
        "message": "Aldi saved browser profile already had the expected store session.",
        "reused_profile_session": True,
        "store_key": store_key,
        "store_name": store_name,
        "store_location": store_location,
        "profile_probe_url": profile_probe_url,
        "store_session_url": start_url,
    }
    status["profile_reused"] = True
    return status


def aldi_current_url_is_product_detail(driver):
    try:
        parsed = urlparse(str(driver.current_url or ""))
    except Exception:
        return False

    return "/store/aldi/products/" in parsed.path


def aldi_store_session_url(search_url, full_address="", store_location=None):
    search_url = str(search_url or "").strip()
    if not search_url:
        return ""

    zip_code = extract_zip_code(full_address) or extract_zip_code((store_location or {}).get("address", ""))
    try:
        parsed = urlparse(search_url)
        path = parsed.path or "/store/aldi"
        if "/store/aldi" in path:
            path = path[: path.index("/store/aldi") + len("/store/aldi")]
        else:
            path = "/store/aldi"
        query = {}
        if zip_code:
            query["zipcode"] = zip_code
        return urlunparse(parsed._replace(path=path, query=urlencode(query), fragment=""))
    except Exception:
        base = "https://www.aldi.us/store/aldi"
        return f"{base}?zipcode={quote_plus(zip_code)}" if zip_code else base


def open_store_selector_for_location(driver):
    try:
        clicked = driver.execute_script(
            """
            const preferredPatterns = [
                /change store/i,
                /edit/i,
                /find stores?/i,
                /store selector/i,
                /select another store/i,
                /choose another store/i,
                /pickup.*change/i,
                /delivery.*change/i
            ];
            const blockedPatterns = [
                /add to cart/i,
                /checkout/i,
                /sign in/i,
                /log in/i,
                /create account/i,
                /remove/i
            ];

            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const nodeStyle = window.getComputedStyle(node);
                    if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none" || parseFloat(nodeStyle.opacity || "1") < 0.02) {
                        return false;
                    }
                    node = node.parentElement;
                }
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    !el.disabled &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function textOf(el) {
                return [
                    el.innerText,
                    el.value,
                    el.getAttribute("aria-label"),
                    el.getAttribute("title")
                ].filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
            }

            const controls = Array.from(document.querySelectorAll(
                "button, a, [role='button'], input[type='button'], input[type='submit']"
            ));
            const candidates = [];
            for (const control of controls) {
                if (!visible(control)) {
                    continue;
                }
                const text = textOf(control);
                if (!text || blockedPatterns.some(pattern => pattern.test(text))) {
                    continue;
                }
                const scoreIndex = preferredPatterns.findIndex(pattern => pattern.test(text));
                if (scoreIndex >= 0) {
                    candidates.push({ control, text, score: 100 - scoreIndex });
                }
            }

            candidates.sort((a, b) => b.score - a.score);
            if (!candidates.length) {
                return "";
            }
            candidates[0].control.click();
            return candidates[0].text;
            """
        )
    except Exception:
        clicked = ""

    if clicked:
        time.sleep(0.8)
    return clicked or ""


def rendered_product_content_html(cards):
    fragments = []

    for index, card in enumerate(cards or [], start=1):
        if not isinstance(card, dict):
            continue

        html = clean_product_card_html(card.get("raw_product_html_snippet") or card.get("html"))
        text = clean_text(card.get("text"))
        product_url = clean_text(card.get("product_url"))
        image_url = clean_text(card.get("image_url"))
        price = normalize_price(card.get("price"))
        name = clean_text(card.get("name"))
        attrs = [
            f'data-product-index="{index}"',
        ]

        if product_url:
            attrs.append(f'data-product-url="{escape_html_attribute(product_url)}"')
        if image_url:
            attrs.append(f'data-image-url="{escape_html_attribute(image_url)}"')
        if price:
            attrs.append(f'data-price="{escape_html_attribute(price)}"')
        if name:
            attrs.append(f'data-name="{escape_html_attribute(name)}"')

        if html:
            fragments.append(f"<article {' '.join(attrs)}>{html}</article>")
        elif text:
            fragments.append(f"<article {' '.join(attrs)}>{escape_html_text(text)}</article>")

    return "\n".join(fragments)


def escape_html_attribute(value):
    return html_lib.escape(str(value or ""), quote=True)


def escape_html_text(value):
    return html_lib.escape(str(value or ""), quote=False)


def save_rendered_product_search_html(
    store_key,
    ingredient,
    search_term,
    page_url,
    html_text,
    visible_text="",
    product_related_html="",
    localization_status=None,
):
    html_text = str(html_text or "")
    visible_text = str(visible_text or "")
    product_related_html = str(product_related_html or "")
    prompt_source_html = product_related_html or html_text
    prompt_html = clean_rendered_page_html_for_prompt(prompt_source_html)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(
        "|".join([store_key or "", ingredient or "", search_term or "", page_url or ""]).encode("utf-8", errors="ignore")
    ).hexdigest()[:10]
    filename = "{timestamp}_{store}_{item}_{digest}.html".format(
        timestamp=timestamp,
        store=normalize_item_key(store_key or "store") or "store",
        item=normalize_item_key(ingredient or search_term or "item") or "item",
        digest=digest,
    )
    path = PRODUCT_RENDERED_HTML_DIR / filename
    text_path = path.with_name(path.stem + "_TEXT.txt")
    preview_path = path.with_name(path.stem + "_PROMPT_PREVIEW.html")
    products_path = path.with_name(path.stem + "_PRODUCTS.html")
    saved_products_path = ""

    try:
        path.write_text(html_text, encoding="utf-8")
        saved_path = str(path)
    except Exception:
        saved_path = ""

    try:
        text_path.write_text(visible_text, encoding="utf-8")
        saved_text_path = str(text_path)
    except Exception:
        saved_text_path = ""

    try:
        preview_path.write_text(prompt_html, encoding="utf-8")
        saved_preview_path = str(preview_path)
    except Exception:
        saved_preview_path = ""

    try:
        products_path.write_text(product_related_html, encoding="utf-8")
        saved_products_path = str(products_path)
    except Exception:
        saved_products_path = ""

    return {
        "url": page_url,
        "path": saved_path,
        "visible_text_path": saved_text_path,
        "prompt_preview_path": saved_preview_path,
        "product_related_html_path": saved_products_path,
        "html_length": len(html_text),
        "visible_text_length": len(visible_text),
        "product_related_html_length": len(product_related_html),
        "localization": localization_status or {},
        "prompt_html": prompt_html,
        "prompt_html_length": len(prompt_html),
    }


def clean_rendered_page_html_for_prompt(html_text):
    html_text = str(html_text or "")
    if not html_text:
        return ""

    try:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "meta", "link"]):
            tag.decompose()

        tracking_pattern = re.compile(
            r"(?:analytics|tracking|tracker|pixel|beacon|gtm|googletag|doubleclick|advert|ad-|ads-|sponsored)",
            re.IGNORECASE,
        )
        for tag in list(soup.find_all(True)):
            attr_text = " ".join(
                str(value)
                for key, value in tag.attrs.items()
                if key in {"id", "class", "data-testid", "data-test", "data-qa", "aria-label", "role"}
            )
            if tracking_pattern.search(attr_text):
                tag.decompose()

        allowed_attrs = {
            "href",
            "src",
            "alt",
            "title",
            "aria-label",
            "role",
            "itemprop",
            "data-testid",
            "data-test",
            "data-qa",
            "data-product-index",
            "data-product-url",
            "data-image-url",
            "data-price",
            "data-name",
        }
        for tag in soup.find_all(True):
            tag.attrs = {
                key: value
                for key, value in tag.attrs.items()
                if key in allowed_attrs
            }

        html_text = str(soup)
    except Exception:
        pass

    html_text = re.sub(r"\s+", " ", html_text).strip()
    return html_text[:product_rendered_html_prompt_limit()]


def rendered_store_context_status(driver, store_key, store_name, full_address, store_location=None):
    store_location = store_location or {}
    store_name = clean_text(store_name or store_location.get("name") or store_key)
    expected_zip = extract_zip_code((store_location or {}).get("address", "")) or extract_zip_code(full_address)
    expected_city = expected_store_city(store_location, full_address)

    try:
        text = driver.execute_script("return document.body && document.body.innerText || '';")
    except Exception:
        text = ""

    context_text = clean_text(text[:8000])
    proof = []
    errors = []
    store_id = extract_visible_store_id(context_text, store_name)

    if text_matches_store_name(context_text, store_name):
        proof.append(f"Visible store name/chain text: {store_name}.")

    if expected_city and re.search(rf"\b{re.escape(expected_city)}\b", context_text, flags=re.IGNORECASE):
        proof.append(f"Visible store city/locality text: {expected_city}.")

    if expected_zip and expected_zip in context_text:
        proof.append(f"Visible store ZIP/postal code: {expected_zip}.")

    address_match = visible_store_address_match(context_text, store_location.get("address", ""))
    if address_match:
        proof.append(f"Visible selected-store address evidence: {address_match}.")

    localized_indicator = visible_localized_inventory_indicator(context_text)
    if localized_indicator:
        proof.append(localized_indicator)

    if store_id:
        proof.append(f"Visible store/session identifier: {store_id}.")

    found_zips = unique_texts(re.findall(r"\b\d{5}\b", context_text))
    if expected_zip and found_zips and expected_zip not in found_zips:
        errors.append(
            f"Expected store ZIP {expected_zip} from the saved Full Address/store resolution, found visible ZIP(s): {', '.join(found_zips)}."
        )

    verified = localization_proof_is_verified(
        proof,
        has_address=bool(address_match),
        has_zip=bool(expected_zip and expected_zip in context_text),
        has_city=bool(expected_city and re.search(rf"\b{re.escape(expected_city)}\b", context_text, flags=re.IGNORECASE)),
        has_store_name=text_matches_store_name(context_text, store_name),
        has_indicator=bool(localized_indicator),
        has_store_id=bool(store_id),
    )

    if not verified and not errors:
        errors.append(
            "Localized store session could not be proven from visible page text. Refusing to treat this as localized inventory."
        )

    return {
        "ok": bool(verified and not errors),
        "verified": bool(verified and not errors),
        "message": "" if verified and not errors else " ".join(errors),
        "store_name": store_name,
        "store_address": store_location.get("address", ""),
        "distance_miles": store_location.get("distance_miles"),
        "store_id": store_id,
        "pickup_supported": store_location.get("pickup_enabled"),
        "delivery_supported": None,
        "proof_of_store_selection": proof,
        "visible_context_excerpt": context_text[:1600],
        "errors": errors,
    }


def expected_store_city(store_location, full_address):
    values = [
        clean_text((store_location or {}).get("address", "")),
        clean_text(full_address),
    ]
    for value in values:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        for part in parts:
            if re.search(r"\bcounty\b|\b\d{5}\b|\bUnited States\b", part, flags=re.IGNORECASE):
                continue
            if re.search(r"\b(?:street|st|road|rd|drive|dr|avenue|ave|boulevard|blvd|lane|ln|way|court|ct)\b", part, flags=re.IGNORECASE):
                continue
            if part and not re.search(r"\d", part):
                return part
    return ""


def visible_store_address_match(context_text, store_address):
    store_address = clean_text(store_address)
    if not store_address:
        return ""

    parts = [clean_text(part) for part in store_address.split(",") if clean_text(part)]
    candidates = []
    if parts:
        candidates.append(parts[0])
    zip_code = extract_zip_code(store_address)
    if zip_code:
        candidates.append(zip_code)

    street_number_match = re.search(r"\b\d{2,6}\b", store_address)
    if street_number_match:
        candidates.append(street_number_match.group(0))

    for candidate in unique_texts(candidates):
        if candidate and candidate in context_text:
            return candidate

    return ""


def text_matches_store_name(context_text, store_name):
    name = normalize_match_text(store_name)
    if not name:
        return False
    tokens = [token for token in tokenize(name) if len(token) >= 3]
    context = normalize_match_text(context_text)
    return bool(tokens and any(re.search(rf"\b{re.escape(token)}\b", context) for token in tokens))


def visible_localized_inventory_indicator(context_text):
    patterns = [
        r"\bshopping at\b.{0,120}",
        r"\bselected store\b.{0,120}",
        r"\byour store\b.{0,120}",
        r"\bpickup\b.{0,120}",
        r"\bdelivery\b.{0,120}",
        r"\bitem pricing and availability may vary\b.{0,120}",
        r"\blocal(?:ized)? (?:inventory|pricing|availability)\b.{0,120}",
    ]
    for pattern in patterns:
        match = re.search(pattern, context_text, flags=re.IGNORECASE)
        if match:
            return "Visible localized inventory/session indicator: " + clean_text(match.group(0))
    return ""


def extract_visible_store_id(context_text, store_name=""):
    patterns = [
        r"\b(?:store|location)\s*(?:#|id|number)?\s*[:#-]?\s*([A-Z]{0,5}\s*\d{1,5})\b",
        r"\b[A-Z]{2,5}\s+\d{1,5}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, context_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))
    return ""


def localization_proof_is_verified(proof, has_address=False, has_zip=False, has_city=False, has_store_name=False, has_indicator=False, has_store_id=False):
    if has_address and (has_store_name or has_indicator):
        return True
    if has_zip and has_store_name and (has_city or has_indicator or has_store_id):
        return True
    if has_store_id and has_store_name and has_indicator:
        return True
    return False


def identify_rendered_html_products_with_chatgpt(
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
    rendered_page,
    visible_cards,
    prompt_builder=None,
):
    client = get_product_analysis_client()
    prompt_html = (rendered_page or {}).get("prompt_html", "")

    if not client:
        return [], [f"{store_name}: ChatGPT rendered-HTML product reasoning skipped because OPENAI_API_KEY is not set."]

    if not prompt_html:
        return [], [f"{store_name}: generic browser agent did not produce cleaned rendered HTML for ChatGPT."]

    system_prompt = (
        "You are a grocery product reasoning function. A generic browser automation layer has already opened, "
        "rendered, scrolled, and cleaned a grocery page. Do not browse or fetch anything. Identify product "
        "candidates only from the supplied rendered HTML and return only valid JSON."
    )
    prompt_builder = prompt_builder or build_rendered_html_product_agent_prompt
    user_prompt = prompt_builder(
        ingredient,
        store_name,
        full_address,
        store_location,
        rendered_page,
        visible_cards,
    )
    prompt_payload = chatgpt_prompt_payload(
        "rendered-html-product-reasoning",
        PRODUCT_ANALYSIS_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    try:
        with PRODUCT_AI_ANALYSIS_LOCK:
            response = client.chat.completions.create(
                model=PRODUCT_ANALYSIS_MODEL,
                messages=prompt_payload["messages"],
                response_format={"type": "json_object"},
                temperature=0,
            )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return [], [f"{store_name}: ChatGPT rendered-HTML product reasoning failed: {exc}"]

    selection = normalize_rendered_html_product_agent_response(data)
    selection["status"] = "done"
    selection["model"] = PRODUCT_ANALYSIS_MODEL
    selection["prompt"] = prompt_payload
    candidates = rendered_html_agent_candidates_from_response(
        selection,
        ingredient,
        store_key,
        store_name,
        page_url,
        search_url,
        full_address,
        home_location,
        store_location,
        rendered_page,
        visible_cards,
    )

    return candidates, clean_text_list(selection.get("errors", []))


def build_rendered_html_product_agent_prompt(
    ingredient,
    store_name,
    full_address,
    store_location,
    rendered_page,
    visible_cards,
):
    rules_payload = product_analysis_rules_payload()
    store_location = store_location or {}
    rendered_page = rendered_page or {}
    localization = rendered_page.get("localization", {}) if isinstance(rendered_page.get("localization"), dict) else {}
    product_blocks = [
        {
            "product_index": index,
            "name_hint": clean_text(card.get("name")) if isinstance(card, dict) else "",
            "price_hint": normalize_price(card.get("price")) if isinstance(card, dict) else "",
            "product_url_hint": clean_text(card.get("product_url")) if isinstance(card, dict) else "",
            "image_url_hint": clean_text(card.get("image_url")) if isinstance(card, dict) else "",
            "text": clean_text(card.get("text"))[:1400] if isinstance(card, dict) else "",
            "html": clean_product_card_html((card or {}).get("raw_product_html_snippet") if isinstance(card, dict) else ""),
        }
        for index, card in enumerate(visible_cards or [], start=1)
        if isinstance(card, dict)
    ]

    return f"""
You are a grocery product collection and product ranking agent for localized grocery inventory extraction.

The generic browser agent already opened, rendered, scrolled, cleaned, and saved the grocery page before this prompt was created.

CORE OBJECTIVE:
1. Use the user's exact address as the home point.
2. Search ONLY localized grocery inventory for the target store.
3. Use ONLY the cleaned rendered HTML/content supplied below.
4. Identify product candidates, best product, best value pick, best premium pick, alternatives, and rejected products.
5. Return clean structured JSON only.

CRITICAL RULES:
- Do not browse, fetch, or infer from outside websites.
- You MUST NOT browse, fetch, or infer from outside websites.
- You MUST NOT use generic national catalog results.
- You MUST NOT hallucinate inventory or fabricate store localization.
- You MUST include only edible grocery products unless the target explicitly requests a non-food grocery item.
- You MUST reject decorative, toy, beauty, pet, household, bath, craft, and other non-food products unless explicitly requested.
- You MUST reject candy unless the target explicitly requests candy.
- You MUST rank using value, stock, package size, pickup eligibility, quality, and category-aware unit economics.
- If localized inventory proof is missing or invalid, return empty product objects/arrays and include an error.

USER LOCATION:
{full_address}

TARGET PRODUCT:
{ingredient}

TARGET STORE:
{store_name}

VERIFIED STORE INFO FROM BROWSER AUTOMATION:
{json.dumps({
    "verified": localization.get("verified"),
    "store_name": localization.get("store_name") or store_name,
    "store_address": localization.get("store_address") or store_location.get("address", ""),
    "distance_miles": localization.get("distance_miles", store_location.get("distance_miles")),
    "store_id": localization.get("store_id", ""),
    "pickup_supported": localization.get("pickup_supported", store_location.get("pickup_enabled")),
    "delivery_supported": localization.get("delivery_supported"),
    "proof_of_store_selection": localization.get("proof_of_store_selection", []),
    "errors": localization.get("errors", []),
}, ensure_ascii=False)}

Nearest store metadata resolved from the saved Full Address:
{json.dumps(store_location, ensure_ascii=False)}

Saved food rules:
{json.dumps(rules_payload.get("food_rules", {}), ensure_ascii=False)}

Saved best-product ranking guidance:
{json.dumps(rules_payload.get("best_product_ranking", []), ensure_ascii=False)}

Rendered page metadata:
{json.dumps({
    "url": rendered_page.get("url", ""),
    "html_path": rendered_page.get("path", ""),
    "visible_text_path": rendered_page.get("visible_text_path", ""),
    "prompt_preview_path": rendered_page.get("prompt_preview_path", ""),
    "product_related_html_path": rendered_page.get("product_related_html_path", ""),
    "html_length": rendered_page.get("html_length", 0),
    "visible_text_length": rendered_page.get("visible_text_length", 0),
    "product_related_html_length": rendered_page.get("product_related_html_length", 0),
    "prompt_html_length": rendered_page.get("prompt_html_length", 0),
}, ensure_ascii=False)}

Visible product blocks extracted generically:
{json.dumps(product_blocks, ensure_ascii=False)}

Cleaned rendered product HTML/content:
{rendered_page.get("prompt_html", "")}

LOCALIZATION VERIFICATION REQUIREMENTS:
- Product results MUST come from the verified localized store session above.
- Valid proof may include selected store banner text, active pickup location, localized inventory indicator, store address, store/session ID, or pickup/delivery availability tied to that location.
- If proof_of_store_selection is empty or verified is false, STOP and return no products with an error.

SEARCH RULES:
- Search/extract ONLY for: {ingredient}
- Capture ALL visible matching product cards from the supplied content.
- Do not include unrelated products unless rejecting them with a rejection reason.

PRODUCT DATA TO EXTRACT WHEN VISIBLE:
- store name
- selected store address
- product name
- brand
- product category/type
- package count
- package size
- price
- unit price
- stock status
- pickup availability
- delivery availability
- product URL
- image URL
- product ID/SKU

PRODUCT RANKING RULES:
1. Best value per unit.
2. In-stock products first.
3. Larger value packs preferred.
4. Higher-quality products preferred when value difference is reasonable.
5. Organic/premium products preferred only if competitively priced.
6. Avoid overpriced specialty products unless clearly premium.
7. Prefer pickup-eligible products.
8. Prefer reputable grocery brands.
9. Prefer products actually available at the localized store.

CATEGORY-SPECIFIC RULES:
- eggs -> price per egg; prefer standard shell egg cartons, 12-count or larger; reject liquid eggs, egg whites only, boiled eggs, egg bites, and plant-based substitutes when possible.
- milk -> price per ounce.
- produce -> price per pound or each as appropriate.
- meat -> price per pound plus quality.
- detergent -> loads per dollar.
- paper towels -> sheets per dollar.

RETURN REQUIREMENTS:
- searched_store must include proof_of_store_selection.
- best_product is the overall best balanced product.
- best_value_pick is the best unit value.
- best_premium_pick is the best higher-quality/premium option when present.
- alternatives contains all other valid edible alternatives.
- rejected_products contains irrelevant/non-food/unavailable/rule-failing products with rejection_reason.
- errors contains localization/blocking/CAPTCHA/store selector failures.

Return ONLY valid JSON.

Output schema:
{{
  "timestamp": "",
  "home_address": "{full_address}",
  "search_item": "{normalize_match_text(ingredient)}",
  "target_product": "{ingredient}",
  "target_store": "{store_name}",
  "searched_store": {{
    "store_name": "",
    "store_address": "",
    "distance_miles": "",
    "store_id": "",
    "pickup_supported": true,
    "delivery_supported": true,
    "proof_of_store_selection": []
  }},
  "best_product": {{}},
  "best_value_pick": {{}},
  "best_premium_pick": {{}},
  "alternatives": [],
  "rejected_products": [],
  "errors": [],
  "results": [
    {{
      "product_index": 1,
      "ranking_status": "best|alternative|rejected",
      "rejection_reason": "",
      "confidence_score": 0,
      "reason": "",
      "product_name": "",
      "brand": "",
      "product_category": "",
      "package_count": "",
      "size": "",
      "price": "",
      "unit_price": "",
      "stock_status": "",
      "in_stock": true,
      "pickup_available": true,
      "delivery_available": true,
      "product_url": "",
      "image_url": "",
      "product_id": ""
    }}
  ]
}}
"""


def normalize_rendered_html_product_agent_response(data):
    data = data if isinstance(data, dict) else {}
    best_product = data.get("best_product") if isinstance(data.get("best_product"), dict) else {}
    raw_results = rendered_html_agent_response_products(data)
    best_signature = rendered_html_product_signature(best_product)
    results = []

    for raw, default_status in raw_results:
        if not isinstance(raw, dict):
            continue

        product_name = clean_text(raw.get("product_name") or raw.get("name") or raw.get("title"))
        product_url = clean_text(raw.get("product_url") or raw.get("url"))
        if not product_name and not product_url:
            continue

        status = normalize_ranking_status(raw.get("ranking_status") or raw.get("status") or default_status)
        if not status and rendered_html_product_signature(raw) == best_signature:
            status = "best"
        elif not status:
            status = "alternative"

        results.append({
            "product_index": parse_int(raw.get("product_index") or raw.get("index")),
            "ranking_status": status,
            "rejection_reason": clean_text(raw.get("rejection_reason") or raw.get("reject_reason")),
            "confidence_score": bounded_confidence(raw.get("confidence_score") or raw.get("confidence")) or 0,
            "reason": clean_text(raw.get("reason")),
            "product_name": product_name,
            "brand": clean_text(raw.get("brand")),
            "product_category": clean_text(raw.get("product_category") or raw.get("egg_type") or raw.get("category") or raw.get("type")),
            "package_count": clean_text(raw.get("package_count") or raw.get("count")),
            "size": clean_text(raw.get("size") or raw.get("package_size") or raw.get("count")),
            "price": normalize_price(raw.get("price")),
            "unit_price": clean_text(raw.get("unit_price") or raw.get("price_per_unit") or raw.get("price_per_egg")),
            "stock_status": clean_text(raw.get("stock_status") or raw.get("availability")),
            "in_stock": normalize_optional_bool(raw.get("in_stock")),
            "pickup_available": normalize_optional_bool(first_present_value(raw.get("pickup_available"), raw.get("pickup_eligible"))),
            "delivery_available": normalize_optional_bool(first_present_value(raw.get("delivery_available"), raw.get("delivery_eligible"))),
            "product_url": product_url,
            "image_url": clean_text(raw.get("image_url")),
            "product_id": clean_text(raw.get("product_id") or raw.get("sku") or raw.get("id")),
        })

    if results and not any(result.get("ranking_status") == "best" for result in results):
        best_result = next((result for result in results if rendered_html_product_signature(result) == best_signature), None)
        if best_result:
            best_result["ranking_status"] = "best"

    return {
        "timestamp": clean_text(data.get("timestamp")),
        "search_item": clean_text(data.get("search_item")),
        "store_name": clean_text(data.get("store_name")),
        "store_address": clean_text(data.get("store_address")),
        "home_address": clean_text(data.get("home_address")),
        "target_product": clean_text(data.get("target_product")),
        "target_store": clean_text(data.get("target_store")),
        "searched_store": data.get("searched_store") if isinstance(data.get("searched_store"), dict) else {},
        "best_product": best_product,
        "results": results,
        "errors": clean_text_list(data.get("errors")),
    }


def rendered_html_agent_response_products(data):
    rows = []
    seen_keys = set()

    def add(raw, status):
        if not isinstance(raw, dict):
            return
        key = rendered_html_product_signature(raw) or clean_text(raw.get("product_id") or raw.get("sku") or raw.get("id"))
        key = key or f"row-{len(rows)}"
        if key in seen_keys:
            return
        seen_keys.add(key)
        item = dict(raw)
        item.setdefault("ranking_status", status)
        rows.append((item, status))

    for raw in data.get("results") if isinstance(data.get("results"), list) else []:
        add(raw, normalize_ranking_status(raw.get("ranking_status") or raw.get("status")) or "alternative")

    for raw in data.get("alternatives") if isinstance(data.get("alternatives"), list) else []:
        add(raw, "alternative")

    for raw in data.get("rejected_products") if isinstance(data.get("rejected_products"), list) else []:
        add(raw, "rejected")

    add(data.get("best_product"), "best")
    add(data.get("best_value_pick"), "alternative")
    add(data.get("best_premium_pick"), "alternative")

    return rows


def rendered_html_agent_candidates_from_response(
    selection,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
    rendered_page,
    visible_cards,
):
    candidates = []
    agent_summary_base = {
        "status": selection.get("status", ""),
        "model": selection.get("model", PRODUCT_ANALYSIS_MODEL),
        "result_count": len(selection.get("results", [])),
    }
    if selection.get("prompt"):
        agent_summary_base["prompt"] = selection.get("prompt")

    for result in selection.get("results", []):
        product_name = clean_text(result.get("product_name"))
        product_url = clean_text(result.get("product_url"))
        price = normalize_price(result.get("price"))

        if not product_name:
            continue

        if product_url:
            product_url = urljoin(page_url, product_url)
        else:
            product_url = search_url

        candidate = build_candidate(
            ingredient,
            store_key,
            store_name,
            product_name,
            price,
            product_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="chatgpt-rendered-html",
            image_url=urljoin(page_url, result.get("image_url")) if result.get("image_url") else "",
        )
        block = match_rendered_product_block(result, visible_cards, page_url)
        status = normalize_ranking_status(result.get("ranking_status"))
        confidence = bounded_confidence(result.get("confidence_score")) or 0
        rejection_reason = clean_text(result.get("rejection_reason"))
        reason = clean_text(result.get("reason"))

        candidate["brand"] = clean_text(result.get("brand"))
        candidate["product_category"] = clean_text(result.get("product_category"))
        candidate["package_count"] = clean_text(result.get("package_count"))
        candidate["product_id"] = clean_text(result.get("product_id"))
        candidate["package_size"] = clean_text(result.get("size"))
        candidate["size"] = candidate["package_size"]
        candidate["unit_price"] = clean_text(result.get("unit_price"))
        candidate["availability"] = clean_text(result.get("stock_status"))
        candidate["in_stock"] = result.get("in_stock")
        candidate["pickup_available"] = result.get("pickup_available")
        candidate["delivery_available"] = result.get("delivery_available")
        candidate["source_page_url"] = page_url
        candidate["rendered_page_url"] = rendered_page.get("url", page_url)
        candidate["rendered_page_html_path"] = rendered_page.get("path", "")
        candidate["rendered_page_text_path"] = rendered_page.get("visible_text_path", "")
        candidate["rendered_page_prompt_preview_path"] = rendered_page.get("prompt_preview_path", "")
        candidate["rendered_page_product_related_html_path"] = rendered_page.get("product_related_html_path", "")
        candidate["rendered_page_html_length"] = rendered_page.get("html_length", 0)
        candidate["rendered_page_visible_text_length"] = rendered_page.get("visible_text_length", 0)
        candidate["rendered_page_html_excerpt"] = rendered_page.get("prompt_html", "")
        candidate["store_localization"] = rendered_page.get("localization", {})
        candidate["proof_of_store_selection"] = rendered_page.get("localization", {}).get("proof_of_store_selection", [])
        candidate["card_text_excerpt"] = clean_text((block or {}).get("text"))[:1600]
        candidate["raw_product_html_snippet"] = clean_product_card_html((block or {}).get("raw_product_html_snippet"))
        candidate["ranking_status"] = status
        candidate["confidence"] = confidence
        candidate["confidence_score"] = confidence
        candidate["chatgpt_rendered_html_agent"] = {
            **agent_summary_base,
            "ranking_status": status,
            "confidence_score": confidence,
            "reason": reason,
            "rejection_reason": rejection_reason,
            "selected": status == "best",
        }

        if status == "rejected":
            candidate["viable"] = False
            if rejection_reason:
                candidate["rejection_reason"] = rejection_reason
                candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + [rejection_reason])
            candidate["score"] = -80
        elif status == "best":
            candidate["score"] = 80 + confidence * 20
            candidate["reason_selected"] = reason or "ChatGPT rendered-HTML reasoning chose this product as the best match."
            candidate["ranking_reasons"] = unique_texts(
                candidate.get("ranking_reasons", [])
                + ["ChatGPT identified this product from the cleaned rendered HTML and chose it as best.", reason]
            )
        else:
            candidate["score"] = 35 + confidence * 10
            candidate["ranking_reasons"] = unique_texts(
                candidate.get("ranking_reasons", [])
                + ["ChatGPT identified this product from the cleaned rendered HTML as a valid alternative.", reason]
            )

        candidates.append(candidate)

    return dedupe_candidates(candidates)


def match_rendered_product_block(result, visible_cards, page_url):
    product_index = result.get("product_index")
    if product_index:
        try:
            indexed = list(visible_cards or [])[int(product_index) - 1]
            if isinstance(indexed, dict):
                return indexed
        except Exception:
            pass

    product_url = clean_text(result.get("product_url"))
    if product_url:
        absolute_url = urljoin(page_url, product_url)
        for card in visible_cards or []:
            if not isinstance(card, dict):
                continue
            if clean_text(card.get("product_url")) == absolute_url:
                return card

    name_tokens = set(tokenize(result.get("product_name")))
    if name_tokens:
        for card in visible_cards or []:
            if not isinstance(card, dict):
                continue
            card_text = " ".join([
                clean_text(card.get("name")),
                clean_text(card.get("text")),
            ])
            card_tokens = set(tokenize(card_text))
            if len(name_tokens & card_tokens) >= max(1, min(3, len(name_tokens))):
                return card

    return {}


def rendered_html_product_signature(value):
    if not isinstance(value, dict):
        return ""

    return "|".join([
        normalize_match_text(value.get("product_name") or value.get("name") or value.get("title")),
        normalize_match_text(value.get("product_url") or value.get("url")),
    ]).strip("|")


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_present_value(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def normalize_optional_bool(value):
    if isinstance(value, bool) or value is None:
        return value

    text = normalize_match_text(value)
    if text in {"true", "yes", "y", "1", "in stock", "available", "many in stock", "low stock"}:
        return True
    if text in {"false", "no", "n", "0", "out of stock", "unavailable", "sold out"}:
        return False
    return None


def search_meijer_products_with_reader(
    ingredient,
    store_key,
    store,
    search_url,
    full_address,
    home_location,
    store_location,
):
    store_name = store.get("label") or store_key.title()

    if not should_use_product_reader_proxy(search_url):
        return [], []

    result = fetch_product_page_html_with_reader(search_url, expected_name=ingredient)
    if not result.get("html"):
        return [], [f"{store_name}: reader fallback could not inspect Meijer search results: {result.get('error') or 'empty page content'}"]

    candidates = parse_meijer_reader_product_candidates(
        result.get("html", ""),
        ingredient,
        store_key,
        store_name,
        search_url,
        full_address,
        home_location,
        store_location,
    )

    if candidates:
        for candidate in candidates:
            candidate["ranking_reasons"] = unique_texts(
                candidate.get("ranking_reasons", [])
                + ["Meijer search was read through a reader fallback because Meijer blocked direct automated search access."]
            )
        return candidates[:product_candidate_limit()], [
            f"{store_name}: direct search/browser access was blocked, so product links were recovered from the rendered reader view."
        ]

    return [], [f"{store_name}: reader fallback found no direct product links on the Meijer search page."]


def parse_meijer_reader_product_candidates(
    markdown_text,
    ingredient,
    store_key,
    store_name,
    search_url,
    full_address,
    home_location,
    store_location,
):
    candidates = []

    for line in str(markdown_text or "").splitlines():
        if "/shopping/product/" not in line or "##" not in line:
            continue

        url_match = MEIJER_PRODUCT_URL_PATTERN.search(line)
        if not url_match:
            continue

        product_url = url_match.group(0).rstrip(".")
        display = meijer_reader_product_display_text(line, product_url)
        product_name = meijer_reader_product_name(display, product_url)
        if not product_name:
            continue

        image_url = meijer_reader_product_image_url(line)
        price = meijer_reader_product_price(display)
        candidate = build_candidate(
            ingredient,
            store_key,
            store_name,
            product_name,
            price,
            product_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="meijer-reader-search",
            image_url=image_url,
        )
        package_size = extract_package_size(display)
        unit_price = extract_unit_price(display)

        if package_size:
            candidate["package_size"] = package_size
            candidate["size"] = package_size

        if unit_price:
            candidate["unit_price"] = unit_price.get("display", "")
            candidate["unit_price_value"] = unit_price.get("value")
            candidate["unit_price_unit"] = unit_price.get("unit", "")

        lowered = display.lower()
        if "out of stock" in lowered:
            candidate["in_stock"] = False
        elif "in stock" in lowered or "low stock" in lowered:
            candidate["in_stock"] = True

        candidate["card_text_excerpt"] = display[:900]
        candidate["detail_text_excerpt"] = display[:900]
        candidate["ranking_reasons"].append("Direct Meijer product link was found in rendered reader search results.")
        candidates.append(candidate)

    return dedupe_candidates(candidates)


def meijer_reader_product_display_text(line, product_url):
    display = str(line or "")
    display = display[:display.find(product_url)] if product_url in display else display
    display = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", display)
    display = display.lstrip("[")
    display = clean_text(display)

    if "##" in display:
        display = display.split("##", 1)[1]

    return clean_text(display)


def meijer_reader_product_name(display, product_url=""):
    text = re.sub(r"^(?:Low Stock|In Stock)\s+", "", clean_text(display), flags=re.IGNORECASE)
    text = re.split(
        r"\b(?:Sale price|Original price|Save \$|In stock|Low Stock|\(\d+\)|\d+(?:\.\d+)? out of 5)",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = clean_text(text)

    if text:
        return text

    path_parts = [part for part in urlparse(product_url).path.split("/") if part]
    if len(path_parts) >= 3:
        return clean_text(path_parts[-2].replace("-", " ").title())

    return ""


def meijer_reader_product_price(display):
    text = clean_text(display)
    for pattern in [
        r"Sale price\s+Buy\s+\d+\s+for\s+\$\s*\d+(?:\.\d{2})?",
        r"Sale price\s+\$\s*\d+(?:\.\d{2})?",
        r"Original price\s+\$\s*\d+(?:\.\d{2})?(?:/[A-Za-z]+)?",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))

    return normalize_price(text)


def meijer_reader_product_image_url(line):
    match = re.search(r"!\[[^\]]*\]\((https://www\.meijer\.com/content/dam/meijer/product/[^)]+)\)", str(line or ""))
    return match.group(1) if match else ""


def configure_browser_home_location(driver, target_url, home_location):
    if not home_location:
        return

    try:
        parsed = urlparse(target_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        driver.execute_cdp_cmd(
            "Browser.grantPermissions",
            {
                "origin": origin,
                "permissions": ["geolocation"],
            },
        )
        driver.execute_cdp_cmd(
            "Emulation.setGeolocationOverride",
            {
                "latitude": float(home_location.get("latitude")),
                "longitude": float(home_location.get("longitude")),
                "accuracy": 60,
            },
        )
    except Exception:
        pass


def handle_browser_popups_and_location(driver, full_address, store_location=None):
    for _ in range(3):
        try:
            clicked = driver.execute_script(
                """
                const patterns = [
                    /accept all/i, /accept/i, /agree/i, /allow/i,
                    /use current location/i, /use my location/i,
                    /confirm/i, /continue/i, /got it/i, /no thanks/i, /not now/i,
                    /dismiss/i, /^close$/i
                ];
                const blocked = [/add to cart/i, /checkout/i, /sign in/i, /log in/i, /create account/i];

                function visible(el) {
                    let node = el;
                    while (node && node.nodeType === 1) {
                        const nodeStyle = window.getComputedStyle(node);
                        if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none") {
                            return false;
                        }
                        node = node.parentElement;
                    }
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style && style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                }

                const controls = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input[type="button"], input[type="submit"]'
                ));

                for (const control of controls) {
                    if (!visible(control)) {
                        continue;
                    }

                    const text = [
                        control.innerText,
                        control.value,
                        control.getAttribute("aria-label"),
                        control.getAttribute("title")
                    ].filter(Boolean).join(" ").trim();

                    if (!text || blocked.some(pattern => pattern.test(text))) {
                        continue;
                    }

                    if (patterns.some(pattern => pattern.test(text))) {
                        control.click();
                        return text;
                    }
                }

                return "";
                """
            )
        except Exception:
            clicked = ""

        if clicked:
            time.sleep(0.45)

    fill_location_inputs(driver, full_address)
    select_nearest_pickup_store(driver, store_location)


def select_nearest_pickup_store(driver, store_location):
    store_location = store_location or {}
    store_name = clean_text(store_location.get("name"))
    store_address = clean_text(store_location.get("address"))
    store_zip = extract_zip_code(store_address)

    if not (store_name or store_address or store_zip):
        return ""

    try:
        clicked = driver.execute_script(
            """
            const storeName = String(arguments[0] || "").toLowerCase();
            const storeAddress = String(arguments[1] || "").toLowerCase();
            const storeZip = String(arguments[2] || "").toLowerCase();
            const pickupPatterns = [
                /pickup/i,
                /shop this store/i,
                /select store/i,
                /set store/i,
                /set as my store/i,
                /make this my store/i,
                /choose store/i,
                /use this store/i,
                /confirm/i,
                /continue/i,
                /start shopping/i
            ];
            const blockedPatterns = [
                /add to cart/i,
                /checkout/i,
                /sign in/i,
                /log in/i,
                /create account/i,
                /remove/i
            ];

            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const nodeStyle = window.getComputedStyle(node);
                    if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none" || parseFloat(nodeStyle.opacity || "1") < 0.02) {
                        return false;
                    }
                    node = node.parentElement;
                }
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    !el.disabled &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function textOf(el) {
                return [
                    el.innerText,
                    el.value,
                    el.getAttribute("aria-label"),
                    el.getAttribute("title")
                ].filter(Boolean).join(" ").replace(/\\s+/g, " ").trim();
            }

            function contextText(el) {
                const context = el.closest("article, li, section, [role='dialog'], [class*='store' i], [data-testid*='store' i]") || el.parentElement || el;
                return String(context.innerText || context.textContent || "").replace(/\\s+/g, " ").trim();
            }

            const controls = Array.from(document.querySelectorAll(
                "button, a, [role='button'], input[type='button'], input[type='submit']"
            ));
            const candidates = [];

            for (const control of controls) {
                if (!visible(control)) {
                    continue;
                }

                const text = textOf(control);
                const context = contextText(control);
                const combined = `${text} ${context}`.toLowerCase();

                if (!text || blockedPatterns.some(pattern => pattern.test(text))) {
                    continue;
                }

                let score = pickupPatterns.some(pattern => pattern.test(text)) ? 10 : 0;
                if (storeZip && combined.includes(storeZip)) {
                    score += 8;
                }
                if (storeAddress && combined.includes(storeAddress.slice(0, Math.min(18, storeAddress.length)))) {
                    score += 6;
                }
                if (storeName && combined.includes(storeName.slice(0, Math.min(14, storeName.length)))) {
                    score += 3;
                }

                if (score >= 10 || (score >= 8 && /store|pickup/i.test(text))) {
                    candidates.push({ control, score, text });
                }
            }

            candidates.sort((a, b) => b.score - a.score);
            if (!candidates.length) {
                return "";
            }

            candidates[0].control.click();
            return candidates[0].text;
            """,
            store_name,
            store_address,
            store_zip,
        )
    except Exception:
        clicked = ""

    if clicked:
        time.sleep(0.8)

    return clicked or ""


def fill_location_inputs(driver, full_address):
    zip_code = extract_zip_code(full_address)
    if not full_address and not zip_code:
        return

    try:
        driver.execute_script(
            """
            const zipCode = arguments[0] || "";
            const fullAddress = arguments[1] || "";
            const addressValue = zipCode || fullAddress;
            const fullValue = fullAddress || zipCode;

            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const nodeStyle = window.getComputedStyle(node);
                    if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none") {
                        return false;
                    }
                    node = node.parentElement;
                }
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    !el.disabled &&
                    !el.readOnly &&
                    rect.width > 0 &&
                    rect.height > 0;
            }

            function attrs(el) {
                return [
                    el.getAttribute("name"),
                    el.getAttribute("id"),
                    el.getAttribute("placeholder"),
                    el.getAttribute("aria-label"),
                    el.getAttribute("autocomplete")
                ].filter(Boolean).join(" ").toLowerCase();
            }

            const inputs = Array.from(document.querySelectorAll('input, textarea'));
            for (const input of inputs) {
                if (!visible(input)) {
                    continue;
                }

                const attrText = attrs(input);
                const looksLocation = /(zip|postal|postcode|address|location|store)/i.test(attrText);
                const looksSearch = /(search|query|keyword|product|item)/i.test(attrText);

                if (!looksLocation || looksSearch) {
                    continue;
                }

                input.focus();
                input.value = /(address|location|store)/i.test(attrText) ? fullValue : addressValue;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));

                const form = input.closest("form");
                const submit = form
                    ? form.querySelector('button[type="submit"], input[type="submit"], button')
                    : null;

                if (submit && visible(submit)) {
                    submit.click();
                } else {
                    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
                }

                return true;
            }

            return false;
            """,
            zip_code,
            full_address,
        )
        time.sleep(0.8)
    except Exception:
        pass


def wait_for_browser_text_to_settle(driver, timeout_seconds=3):
    deadline = time.monotonic() + max(1, timeout_seconds)
    last_length = -1
    stable_seen = 0

    while time.monotonic() < deadline:
        try:
            text_length = driver.execute_script(
                "return (document.body && document.body.innerText || '').length"
            )
        except Exception:
            text_length = 0

        if text_length == last_length and text_length > 0:
            stable_seen += 1
            if stable_seen >= 2:
                return
        else:
            stable_seen = 0
            last_length = text_length

        time.sleep(0.4)


def wait_for_rendered_product_cards(driver, timeout_seconds=8):
    deadline = time.monotonic() + max(2, timeout_seconds)

    while time.monotonic() < deadline:
        try:
            count = driver.execute_script(
                """
                const pricePattern = /\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?/;
                function visible(el) {
                    let node = el;
                    while (node && node.nodeType === 1) {
                        const nodeStyle = window.getComputedStyle(node);
                        if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none" || parseFloat(nodeStyle.opacity || "1") < 0.02) {
                            return false;
                        }
                        node = node.parentElement;
                    }
                    const rect = el.getBoundingClientRect();
                    return rect.width >= 60 && rect.height >= 35;
                }
                const selectors = [
                    '[data-testid*="product" i]',
                    '[data-test*="product" i]',
                    '[data-qa*="product" i]',
                    '[class*="product" i]',
                    'article',
                    'li'
                ].join(',');
                return Array.from(document.querySelectorAll(selectors))
                    .filter(el => visible(el) && pricePattern.test(el.innerText || el.textContent || ''))
                    .length;
                """
            )
        except Exception:
            count = 0

        if count:
            return

        time.sleep(0.5)


def scroll_rendered_product_page(driver):
    try:
        for ratio in [0, 0.28, 0.58, 0.9, 1, 0]:
            driver.execute_script(
                "window.scrollTo(0, Math.floor((document.body.scrollHeight || 0) * arguments[0]));",
                ratio,
            )
            time.sleep(0.35)
    except Exception:
        pass


def scroll_rendered_product_results_until_stable(driver, max_passes=None, stable_passes=2):
    max_passes = max_passes or product_rendered_scroll_max_passes()
    target_cards = product_rendered_scroll_target_cards()
    settle_seconds = product_rendered_scroll_settle_seconds()
    last_count = -1
    unchanged = 0

    for _ in range(max_passes):
        cards = extract_visible_product_cards_from_browser(driver)
        count = len(cards)

        if count > last_count:
            last_count = count
            unchanged = 0
        else:
            unchanged += 1

        try:
            at_bottom = driver.execute_script(
                """
                const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
                const viewport = window.innerHeight || document.documentElement.clientHeight || 0;
                const height = Math.max(
                    document.body.scrollHeight || 0,
                    document.documentElement.scrollHeight || 0
                );
                window.scrollBy(0, Math.max(650, viewport * 0.82));
                return scrollTop + viewport >= height - 12;
                """
            )
        except Exception:
            at_bottom = False

        wait_for_browser_text_to_settle(driver, timeout_seconds=settle_seconds)

        if count >= target_cards and unchanged >= 1:
            break

        if unchanged >= stable_passes and at_bottom:
            break

    try:
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.25)
    except Exception:
        pass

    return max(0, last_count)


def capture_rendered_product_page_snapshot(driver):
    visible_cards = extract_visible_product_cards_from_browser(driver)
    return {
        "html": extract_browser_document_html(driver),
        "visible_text": extract_browser_visible_text(driver),
        "visible_cards": visible_cards,
        "product_related_html": rendered_product_content_html(visible_cards),
    }


def extract_browser_document_html(driver):
    try:
        html_text = driver.execute_script("return document.documentElement && document.documentElement.outerHTML || '';")
    except Exception:
        html_text = ""

    if html_text:
        return str(html_text)

    try:
        return str(driver.page_source or "")
    except Exception:
        return ""


def extract_browser_visible_text(driver):
    try:
        return str(driver.execute_script("return document.body && document.body.innerText || '';") or "")
    except Exception:
        return ""


def extract_visible_product_cards_from_browser(driver):
    try:
        cards = driver.execute_script(
            """
            const limit = arguments[0] || 48;
            const pricePattern = /\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?/g;
            const badLinePattern = /^(add|add to cart|sponsored|sale|save|pickup|delivery|shipping|in stock|out of stock|rating|stars?|reviews?|view details|quick view)$/i;

            function visible(el) {
                let node = el;
                while (node && node.nodeType === 1) {
                    const nodeStyle = window.getComputedStyle(node);
                    if (node.hidden || nodeStyle.visibility === "hidden" || nodeStyle.display === "none" || parseFloat(nodeStyle.opacity || "1") < 0.02) {
                        return false;
                    }
                    node = node.parentElement;
                }
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style &&
                    style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    parseFloat(style.opacity || "1") > 0.02 &&
                    rect.width >= 60 &&
                    rect.height >= 35;
            }

            function textOf(el) {
                return String(el.innerText || el.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            function priceMatches(text) {
                return String(text || "").match(pricePattern) || [];
            }

            function usefulNameLine(line) {
                const value = String(line || "").replace(/\\s+/g, " ").trim();
                if (!value || value.length < 3 || value.length > 180) {
                    return "";
                }
                if (pricePattern.test(value)) {
                    pricePattern.lastIndex = 0;
                    return "";
                }
                pricePattern.lastIndex = 0;
                if (badLinePattern.test(value)) {
                    return "";
                }
                if (/^\\d+(?:\\.\\d+)?\\s*(ct|oz|lb|lbs|g|kg|ml|l|each|ea)$/i.test(value)) {
                    return "";
                }
                return value;
            }

            function bestName(root) {
                const targets = Array.from(root.querySelectorAll(
                    '[data-testid*="title" i], [data-test*="title" i], [class*="title" i], [class*="name" i], a[href], img[alt]'
                ));
                const values = [];

                for (const target of targets) {
                    values.push(target.getAttribute("aria-label"));
                    values.push(target.getAttribute("title"));
                    values.push(target.getAttribute("alt"));
                    values.push(target.innerText);
                }

                values.push(...String(root.innerText || "").split(/\\n+/));

                for (const value of values) {
                    const cleaned = usefulNameLine(value);
                    if (cleaned) {
                        return cleaned;
                    }
                }

                return "";
            }

            function bestLink(root) {
                const links = Array.from(root.querySelectorAll("a[href]"));
                const preferred = links.find(link => {
                    const text = textOf(link);
                    const href = link.getAttribute("href") || "";
                    return text.length > 2 || /product|p\\//i.test(href);
                }) || links[0];
                return preferred ? preferred.href : "";
            }

            function bestImage(root) {
                const image = Array.from(root.querySelectorAll("img"))
                    .find(img => visible(img) && (img.currentSrc || img.src || img.getAttribute("data-src")));
                return image ? (image.currentSrc || image.src || image.getAttribute("data-src") || "") : "";
            }

            function cardHtml(root) {
                const clone = root.cloneNode(true);
                clone.querySelectorAll("script, style, noscript, svg").forEach(el => el.remove());
                return String(clone.outerHTML || "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .slice(0, 4500);
            }

            const selector = [
                'article',
                'li',
                '[itemtype*="Product" i]',
                '[data-testid*="product" i]',
                '[data-test*="product" i]',
                '[data-qa*="product" i]',
                '[class*="product" i]',
                '[class*="Product"]',
                'section',
                'div'
            ].join(',');
            const potential = Array.from(document.querySelectorAll(selector))
                .filter(el => {
                    if (!visible(el)) {
                        return false;
                    }
                    const text = textOf(el);
                    const prices = priceMatches(text);
                    return text.length >= 15 &&
                        text.length <= 1400 &&
                        prices.length >= 1 &&
                        prices.length <= 5 &&
                        (el.querySelector("a[href]") || el.querySelector("img"));
                })
                .sort((a, b) => textOf(a).length - textOf(b).length);

            const roots = [];
            for (const el of potential) {
                if (roots.some(root => root.contains(el) || el.contains(root))) {
                    continue;
                }
                roots.push(el);
                if (roots.length >= limit) {
                    break;
                }
            }

            return roots.map(root => {
                const rawText = String(root.innerText || root.textContent || "");
                const text = textOf(root);
                const prices = priceMatches(text);
                return {
                    name: bestName(root),
                    price: prices[0] || "",
                    product_url: bestLink(root),
                    image_url: bestImage(root),
                    text: rawText.slice(0, 1600),
                    raw_product_html_snippet: cardHtml(root)
                };
            }).filter(card => card.name || card.product_url || card.price);
            """,
            product_candidate_limit(),
        )
    except Exception:
        cards = []

    return cards if isinstance(cards, list) else []


def product_candidates_from_visible_cards(
    cards,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
):
    candidates = []

    for card in cards:
        if not isinstance(card, dict):
            continue

        name = clean_text(card.get("name"))
        price = normalize_price(card.get("price"))
        product_url = clean_text(card.get("product_url"))
        image_url = clean_text(card.get("image_url"))
        raw_product_html_snippet = clean_product_card_html(card.get("raw_product_html_snippet") or card.get("html"))
        raw_card_text = str(card.get("text") or "")
        card_text = clean_text(raw_card_text)

        ingredient_tokens = set(tokenize(ingredient))
        name_tokens = set(tokenize(name))
        needs_better_name = (
            not name
            or len(name) > 100
            or PRICE_PATTERN.search(name)
            or (ingredient_tokens and not (ingredient_tokens & name_tokens))
        )

        if needs_better_name:
            better_name = best_visible_card_name(ingredient, raw_card_text)
            if better_name:
                name = better_name

        if not name:
            continue

        candidate = build_candidate(
            ingredient,
            store_key,
            store_name,
            name,
            price,
            urljoin(page_url, product_url) if product_url else page_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="browser-visible-card",
            image_url=urljoin(page_url, image_url) if image_url else "",
        )
        candidate["source_page_url"] = page_url
        package_size = extract_package_size(" ".join([name, card_text]))
        unit_price = extract_unit_price(card_text)
        availability = extract_availability({}, card_text)
        if package_size:
            candidate["package_size"] = package_size
            candidate["size"] = package_size
        if unit_price:
            candidate["unit_price"] = unit_price.get("display", "")
            candidate["unit_price_value"] = unit_price.get("value")
            candidate["unit_price_unit"] = unit_price.get("unit", "")
        if availability.get("text"):
            candidate["availability"] = availability.get("text", "")
        if availability.get("in_stock") is not None:
            candidate["in_stock"] = availability.get("in_stock")
        if card_text:
            candidate["card_text_excerpt"] = card_text[:900]
            candidate["detail_text_excerpt"] = card_text[:900]
        if raw_product_html_snippet:
            candidate["raw_product_html_snippet"] = raw_product_html_snippet

        candidate["ranking_reasons"].append("Visible product card was extracted from the rendered store page.")
        candidates.append(candidate)

    return dedupe_candidates(candidates)[:product_candidate_limit()]


def clean_product_card_html(html, max_chars=4500):
    html = str(html or "").strip()
    if not html:
        return ""

    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        allowed_attrs = {"href", "src", "alt", "title", "aria-label", "itemprop"}
        for tag in soup.find_all(True):
            tag.attrs = {
                key: value
                for key, value in tag.attrs.items()
                if key in allowed_attrs
            }

        html = str(soup)
    except Exception:
        pass

    return re.sub(r"\s+", " ", html).strip()[:max_chars]


def best_visible_card_name(ingredient, card_text):
    ingredient_tokens = set(tokenize(ingredient))
    text = str(card_text or "")
    text = re.sub(
        r"\bcurrent\s+price\s*:\s*\$\s*\d+(?:,\d{3})*(?:\.\d{2})?",
        " | ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\$\s*\d+\s+\d{2}\b", " | ", text)
    text = re.sub(r"\$\s*\d+(?:,\d{3})*(?:\.\d{2})?", " | ", text)
    text = PACKAGE_SIZE_PATTERN.sub(" | ", text)
    text = re.sub(
        r"\b(?:many in stock|in stock|out of stock|add|best seller|store choice|sponsored)\b",
        " | ",
        text,
        flags=re.IGNORECASE,
    )
    lines = [
        clean_text(line)
        for line in re.split(r"[\n|]+", text)
        if clean_text(line)
    ]
    candidates = []

    for line in lines:
        if len(line) > 180 or PRICE_PATTERN.search(line):
            continue

        for value in unique_texts([strip_leading_product_badges(line), line]):
            lowered = value.lower()
            if any(term in lowered for term in ["add to cart", "pickup", "delivery", "rating", "reviews"]):
                continue

            line_tokens = set(tokenize(value))
            overlap = len(ingredient_tokens & line_tokens)
            candidates.append((overlap, len(line_tokens), value))

    if not candidates:
        return ""

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def strip_leading_product_badges(value):
    text = clean_text(value)
    badge_pattern = re.compile(
        r"^(?:(?:\d+%|organic|whole|low fat|fat free|skim|dairy free|vegan|vegetarian|"
        r"gluten free|low carb|best seller|store choice|sponsored)\s+)+(.+)$",
        re.IGNORECASE,
    )
    match = badge_pattern.match(text)

    if not match:
        return text

    stripped = clean_text(match.group(1))

    if len(tokenize(stripped)) >= 3:
        return stripped

    return text


def parse_product_candidates_from_html(
    html_text,
    page_url,
    ingredient,
    store_key,
    store_name,
    search_url,
    full_address,
    home_location,
    store_location,
):
    soup = BeautifulSoup(html_text or "", "html.parser")
    candidates = []
    limit = product_candidate_limit()

    for product in extract_json_ld_products(soup):
        candidate = product_candidate_from_mapping(
            product,
            ingredient,
            store_key,
            store_name,
            page_url,
            search_url,
            full_address,
            home_location,
            store_location,
            source="json-ld",
        )
        if candidate:
            candidates.append(candidate)

    if len(candidates) < limit:
        for product in extract_embedded_product_mappings(soup):
            candidate = product_candidate_from_mapping(
                product,
                ingredient,
                store_key,
                store_name,
                page_url,
                search_url,
                full_address,
                home_location,
                store_location,
                source="embedded-json",
            )
            if candidate:
                candidates.append(candidate)
                if len(candidates) >= limit:
                    break

    if len(candidates) < limit:
        candidates.extend(extract_anchor_product_candidates(
            soup,
            ingredient,
            store_key,
            store_name,
            page_url,
            search_url,
            full_address,
            home_location,
            store_location,
        ))

    return dedupe_candidates(candidates)[:limit]


def extract_json_ld_products(soup):
    products = []

    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text("", strip=True)
        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=True))

    return products


def extract_embedded_product_mappings(soup):
    products = []
    limit = product_candidate_limit()

    for script in soup.find_all("script"):
        text = script.string or script.get_text("", strip=True)

        if not text or len(text) > 1_500_000:
            continue

        lowered = text.lower()
        if "price" not in lowered or ("product" not in lowered and "name" not in lowered):
            continue

        for payload in parse_json_payloads(text):
            products.extend(find_product_mappings(payload, require_product_type=False))

        if len(products) >= limit:
            break

    return products


def parse_json_payloads(text):
    payloads = []
    text = str(text or "").strip()

    if not text:
        return payloads

    try:
        payloads.append(json.loads(text))
        return payloads
    except Exception:
        pass

    for match in re.finditer(r"({.*?})", text):
        snippet = match.group(1)
        if len(snippet) > 200_000:
            continue
        try:
            payloads.append(json.loads(snippet))
        except Exception:
            continue

        if len(payloads) >= 5:
            break

    return payloads


def find_product_mappings(value, require_product_type=False):
    found = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return

        if not isinstance(node, dict):
            return

        node_type = node.get("@type") or node.get("type") or ""
        type_text = " ".join(node_type) if isinstance(node_type, list) else str(node_type)
        looks_like_product = (
            "product" in type_text.lower()
            or node.get("productName")
            or node.get("product_name")
            or (node.get("name") and has_price_value(node))
        )

        if looks_like_product and (not require_product_type or "product" in type_text.lower()):
            found.append(node)

        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value)

    walk(value)
    return found


def has_price_value(value):
    return bool(extract_price_from_mapping(value))


def product_candidate_from_mapping(
    product,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
    source,
):
    name = clean_text(
        product.get("name")
        or product.get("title")
        or product.get("productName")
        or product.get("product_name")
    )
    price = extract_price_from_mapping(product)
    product_url = extract_product_url_from_mapping(product)
    product_url = urljoin(page_url, str(product_url or page_url))
    image_url = extract_image_url_from_mapping(product)
    image_url = urljoin(page_url, str(image_url)) if image_url else ""

    if not name or len(name) > 180:
        return None

    candidate = build_candidate(
        ingredient,
        store_key,
        store_name,
        name,
        price,
        product_url,
        search_url,
        full_address,
        home_location,
        store_location,
        source,
        image_url=image_url,
    )
    candidate["source_page_url"] = page_url
    return candidate


def extract_product_url_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    product_url = mapping.get("url") or mapping.get("canonicalUrl") or mapping.get("productUrl")

    if isinstance(product_url, dict):
        product_url = product_url.get("@id") or product_url.get("url")

    if product_url:
        return product_url

    offers = mapping.get("offers") or mapping.get("offer")
    if isinstance(offers, list):
        for offer in offers:
            product_url = extract_product_url_from_mapping(offer)
            if product_url:
                return product_url
    elif isinstance(offers, dict):
        return extract_product_url_from_mapping(offers)

    return ""


def extract_image_url_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    image = mapping.get("image") or mapping.get("images") or mapping.get("thumbnail") or mapping.get("thumbnailUrl")

    if isinstance(image, str):
        return image

    if isinstance(image, dict):
        return (
            image.get("url")
            or image.get("contentUrl")
            or image.get("@id")
            or ""
        )

    if isinstance(image, list):
        for item in image:
            image_url = extract_image_url_from_mapping({"image": item})
            if image_url:
                return image_url

    media = mapping.get("media") or mapping.get("primaryImage")
    if isinstance(media, (dict, list, str)):
        return extract_image_url_from_mapping({"image": media})

    return ""


def extract_product_card_assets_from_html(html_text, page_url=""):
    soup = BeautifulSoup(html_text or "", "html.parser")
    assets = {}

    for anchor in soup.find_all("a", href=True):
        product_url = urljoin(page_url or "", anchor.get("href") or "")
        if not product_url or "/products/" not in urlparse(product_url).path:
            continue

        asset = product_card_asset_from_anchor(anchor, page_url)
        if not asset.get("product_url"):
            continue

        for key in product_card_asset_keys(asset.get("product_url", "")):
            if not key:
                continue
            assets[key] = merge_product_card_asset(assets.get(key, {}), asset)

    return assets


def product_card_asset_from_anchor(anchor, page_url=""):
    product_url = urljoin(page_url or "", anchor.get("href") or "")
    root = closest_product_card_node(anchor)
    root_text = clean_text(root.get_text(" ", strip=True) if root else anchor.get_text(" ", strip=True))
    name = product_card_asset_name(anchor, root)
    price = normalize_price(root_text)
    image_url = product_card_image_url(anchor, page_url) or product_card_image_url(root, page_url)
    raw_html = clean_product_card_html(str(root or anchor))
    package_size = extract_package_size(root_text)

    return {
        "product_url": product_url,
        "name": name,
        "price": price,
        "image_url": image_url,
        "raw_product_html_snippet": raw_html,
        "card_text_excerpt": root_text[:900],
        "package_size": package_size,
    }


def closest_product_card_node(anchor):
    node = anchor
    fallback = anchor

    for _ in range(8):
        if not node or not getattr(node, "name", None):
            break

        if node.name in {"li", "article"}:
            return node

        attrs = getattr(node, "attrs", {}) or {}
        if attrs.get("data-item-card") or attrs.get("data-product-url"):
            fallback = node

        node = node.parent

    return fallback


def product_card_asset_name(anchor, root):
    for node in [root, anchor]:
        if not node:
            continue

        for attr in ["data-name", "aria-label", "title"]:
            value = clean_text(node.get(attr))
            if value and len(value) <= 180:
                return value

        image = node.find("img") if hasattr(node, "find") else None
        alt = clean_text(image.get("alt") if image else "")
        if alt and len(alt) <= 180:
            return alt

    return clean_text(anchor.get_text(" ", strip=True))


def product_card_image_url(node, page_url=""):
    if not node:
        return ""

    image = node.find("img") if hasattr(node, "find") and getattr(node, "name", "") != "img" else node
    candidates = []

    for source in [node, image]:
        if not source:
            continue
        for attr in ["data-image-url", "currentSrc", "src", "data-src"]:
            candidates.append(source.get(attr))
        candidates.append(first_srcset_url(source.get("srcset")))

    for value in candidates:
        value = clean_text(value)
        if value:
            return urljoin(page_url or "", value)

    return ""


def first_srcset_url(value):
    text = str(value or "").strip()
    if not text:
        return ""

    first = text.split(",", 1)[0].strip()
    return first.split()[0].strip() if first else ""


def product_card_asset_keys(product_url):
    text = clean_text(product_url).lower().rstrip("/")
    if not text:
        return []

    keys = [text]
    try:
        parsed = urlparse(text)
        path = parsed.path.rstrip("/")
        if path:
            keys.append(path)
        match = re.search(r"/products/([^/?#]+)", path)
        if match:
            keys.append(match.group(1))
    except Exception:
        pass

    return unique_texts(keys)


def merge_product_card_asset(existing, new):
    merged = dict(existing or {})
    for key, value in (new or {}).items():
        if value and not merged.get(key):
            merged[key] = value
    return merged


def extract_price_from_mapping(mapping):
    if not isinstance(mapping, dict):
        return ""

    for key in ["price", "salePrice", "regularPrice", "currentPrice", "finalPrice"]:
        value = mapping.get(key)
        price = normalize_price(value)
        if price:
            return price

    offers = mapping.get("offers") or mapping.get("offer")
    if isinstance(offers, list):
        for offer in offers:
            price = extract_price_from_mapping(offer)
            if price:
                return price
    elif isinstance(offers, dict):
        price = extract_price_from_mapping(offers)
        if price:
            return price

    prices = mapping.get("prices")
    if isinstance(prices, dict):
        return extract_price_from_mapping(prices)

    return ""


def normalize_price(value):
    if value in (None, ""):
        return ""

    if isinstance(value, dict):
        for key in ["value", "amount", "price", "formatted", "display"]:
            price = normalize_price(value.get(key))
            if price:
                return price
        return ""

    if isinstance(value, (int, float)):
        return f"${float(value):.2f}"

    text = clean_text(value)
    match = PRICE_PATTERN.search(text)
    if match:
        return match.group(0).replace(" ", "")

    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        return f"${float(text):.2f}"

    return text if "$" in text else ""


def extract_anchor_product_candidates(
    soup,
    ingredient,
    store_key,
    store_name,
    page_url,
    search_url,
    full_address,
    home_location,
    store_location,
):
    candidates = []
    ingredient_tokens = set(tokenize(ingredient))
    limit = product_candidate_limit()

    for anchor in soup.find_all("a", href=True):
        asset = product_card_asset_from_anchor(anchor, page_url)
        raw_name = clean_text(asset.get("name") or anchor.get_text(" ", strip=True))
        name = raw_name

        if not name or len(name) > 140:
            better_name = best_visible_card_name(
                ingredient,
                asset.get("card_text_excerpt") or anchor.get_text(" ", strip=True),
            )
            if better_name:
                name = better_name
            else:
                continue

        name_tokens = set(tokenize(name))
        overlap = len(ingredient_tokens & name_tokens)
        if ingredient_tokens and overlap == 0:
            continue

        parent_text = asset.get("card_text_excerpt") or clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else name)
        price = asset.get("price") or ""

        candidate = build_candidate(
            ingredient,
            store_key,
            store_name,
            name,
            price,
            urljoin(page_url, anchor.get("href")),
            search_url,
            full_address,
            home_location,
            store_location,
            source="html-anchor",
            image_url=asset.get("image_url", ""),
        )
        candidate["source_page_url"] = page_url
        if asset.get("raw_product_html_snippet"):
            candidate["raw_product_html_snippet"] = asset.get("raw_product_html_snippet")
        if parent_text:
            candidate["card_text_excerpt"] = parent_text[:900]
            candidate["detail_text_excerpt"] = parent_text[:900]
        if asset.get("package_size"):
            candidate["package_size"] = asset.get("package_size")
            candidate["size"] = asset.get("package_size")
        candidates.append(candidate)

        if len(candidates) >= limit:
            break

    return candidates


def build_search_page_candidate(
    ingredient,
    store_key,
    store_name,
    search_url,
    full_address,
    store_location,
    reason,
):
    candidate = build_candidate(
        ingredient,
        store_key,
        store_name,
        f"{ingredient} search results",
        "",
        search_url,
        search_url,
        full_address,
        None,
        store_location,
        source="search-page-fallback",
    )
    candidate["viable"] = True
    candidate["skip_reasons"].append(reason)
    candidate["ranking_reasons"].append("Fallback search page saved because product cards were not parseable.")
    candidate["confidence"] = 0.2
    return candidate


def build_candidate(
    ingredient,
    store_key,
    store_name,
    product_name,
    price,
    product_url,
    search_url,
    full_address,
    home_location,
    store_location,
    source,
    image_url="",
):
    store_location = store_location or {}
    candidate = {
        "id": product_candidate_id(store_key, product_url, product_name, price),
        "ingredient": ingredient,
        "store_key": store_key,
        "store_name": store_name,
        "store_location_name": store_location.get("name", ""),
        "store_location_address": store_location.get("address", ""),
        "store_location_distance_miles": store_location.get("distance_miles"),
        "store_locator_url": store_location.get("locator_url", ""),
        "store_address": store_location.get("address", ""),
        "pickup_enabled": store_location.get("pickup_enabled"),
        "store_selection_context": {
            "home_address": full_address,
            "nearest_store_name": store_location.get("name", ""),
            "nearest_store_address": store_location.get("address", ""),
            "nearest_store_distance_miles": store_location.get("distance_miles"),
            "pickup_enabled": store_location.get("pickup_enabled"),
            "pickup_status": store_location.get("pickup_status", ""),
        },
        "home_address": full_address,
        "home_location": home_location,
        "product_name": product_name,
        "brand": "",
        "product_category": "",
        "package_count": "",
        "product_id": "",
        "price": price,
        "size": "",
        "package_size": "",
        "unit_price": "",
        "pickup_available": None,
        "delivery_available": None,
        "image_url": image_url,
        "embedded_image_base64": "",
        "product_url": product_url,
        "search_url": search_url,
        "source_page_url": search_url,
        "source": source,
        "score": 0,
        "confidence": 0,
        "viable": True,
        "ranking_reasons": [],
        "skip_reasons": [],
        "store_localization": {},
        "proof_of_store_selection": [],
    }
    annotated = annotate_product_food_rules({
        "name": product_name,
        "description": product_name,
    })
    candidate["food_rule_status"] = annotated.get("food_rule_status", {})
    return candidate


def rank_product_candidates(ingredient, candidates, quantity_context=None):
    ranked = []
    seen = set()

    for candidate in candidates:
        key = candidate.get("id")
        if not key or key in seen:
            continue

        seen.add(key)
        apply_quantity_context_to_candidate(candidate, quantity_context or {})
        score, reasons, skip_reasons, viable = score_candidate(
            ingredient,
            candidate,
            quantity_context=quantity_context,
        )
        candidate["score"] = round(score, 2)
        candidate["confidence"] = round(max(0.05, min(0.98, score / 100)), 2)
        candidate["ranking_reasons"] = unique_texts(candidate.get("ranking_reasons", []) + reasons)
        candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + skip_reasons)
        candidate["viable"] = bool(viable)
        ranked.append(candidate)

    ranked = apply_relative_candidate_preferences(ranked)
    return sorted(ranked, key=lambda item: item.get("score", 0), reverse=True)


def apply_chatgpt_store_product_rankings(ingredient, candidates, full_address="", quantity_context=None):
    if not product_final_selection_agent_enabled():
        return candidates

    grouped = {}
    for candidate in candidates:
        if candidate.get("source") == "search-page-fallback":
            continue
        store_key = candidate.get("store_key", "")
        grouped.setdefault(store_key, []).append(candidate)

    for store_key, store_candidates in grouped.items():
        rankable = [
            candidate
            for candidate in sorted(store_candidates, key=lambda item: item.get("score", 0), reverse=True)
            if candidate.get("id")
        ][:product_final_selection_candidate_limit()]
        allowed_ids = {candidate.get("id") for candidate in rankable if candidate.get("id")}

        if not allowed_ids:
            continue

        selection = choose_store_products_with_chatgpt(
            ingredient,
            rankable,
            full_address=full_address,
            quantity_context=quantity_context,
            allowed_ids=allowed_ids,
        )

        apply_store_product_ranking_selection(rankable, selection)

    return sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)


def choose_store_products_with_chatgpt(ingredient, candidates, full_address="", quantity_context=None, allowed_ids=None):
    client = get_product_analysis_client()

    if not client:
        return {
            "status": "skipped",
            "message": "ChatGPT store product ranking skipped because OPENAI_API_KEY is not set.",
        }

    prompt_ids = {candidate.get("id") for candidate in candidates if candidate.get("id")}
    allowed_ids = prompt_ids & set(allowed_ids or prompt_ids)
    system_prompt = (
        "You are a grocery product ranking function. Selenium has already loaded the store page, "
        "selected the nearby store context, scrolled the page, and extracted product-card data. "
        "Do not browse. Rank only the supplied candidates and return only valid JSON."
    )
    user_prompt = build_store_product_ranking_prompt(
        ingredient,
        candidates,
        full_address,
        quantity_context=quantity_context,
    )
    prompt_payload = chatgpt_prompt_payload(
        "store-product-ranking",
        PRODUCT_ANALYSIS_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    try:
        with PRODUCT_AI_ANALYSIS_LOCK:
            response = client.chat.completions.create(
                model=PRODUCT_ANALYSIS_MODEL,
                messages=prompt_payload["messages"],
                response_format={"type": "json_object"},
                temperature=0,
            )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"ChatGPT store product ranking failed: {exc}",
            "prompt": prompt_payload,
        }

    selection = normalize_store_product_ranking_response(data, allowed_ids)
    selection["status"] = "done"
    selection["model"] = PRODUCT_ANALYSIS_MODEL
    selection["prompt"] = prompt_payload
    selection["candidate_count_sent"] = len(candidates)
    return selection


def build_store_product_ranking_prompt(ingredient, candidates, full_address, quantity_context=None):
    rules_payload = product_analysis_rules_payload()
    quantity_context = quantity_context or {}
    store_candidate = candidates[0] if candidates else {}
    candidate_payload = [
        final_product_candidate_payload(candidate)
        for candidate in candidates
    ]
    rendered_page_html = store_candidate.get("rendered_page_html_excerpt", "")
    rendered_page_meta = {
        "url": store_candidate.get("rendered_page_url", ""),
        "html_path": store_candidate.get("rendered_page_html_path", ""),
        "html_length": store_candidate.get("rendered_page_html_length", 0),
        "prompt_html_length": len(rendered_page_html),
        "prompt_html_was_truncated": (
            bool(store_candidate.get("rendered_page_html_length"))
            and len(rendered_page_html) >= product_rendered_html_prompt_limit()
            and len(rendered_page_html) < int(store_candidate.get("rendered_page_html_length") or 0)
        ),
    }

    return f"""
You are a grocery product ranking function.

Selenium/undetected Chrome already opened the actual grocery website, used the saved address context, selected the nearest pickup-oriented store when available, fully loaded the product search page, scrolled until no new product cards appeared, saved the rendered page HTML, and extracted the product-card HTML/data below.

Do not browse, fetch, or infer from outside websites. Use only the supplied product-card data and saved rules.

Requested item:
{ingredient}

Current saved address:
{full_address}

Store:
{store_candidate.get("store_name", "")}

Store address:
{store_candidate.get("store_location_address", "")}

Total shopping-list quantity needed:
{quantity_context.get("display") or "Not specified"}

Quantity sources:
{json.dumps(quantity_context.get("sources", []), ensure_ascii=False)}

Saved food rules:
{json.dumps(rules_payload.get("food_rules", {}), ensure_ascii=False)}

Saved best-product ranking guidance:
{json.dumps(rules_payload.get("best_product_ranking", []), ensure_ascii=False)}

Rendered page source metadata:
{json.dumps(rendered_page_meta, ensure_ascii=False)}

Cleaned rendered page HTML from the fully loaded Selenium page:
{rendered_page_html}

Captured product cards from the fully loaded Selenium page:
{json.dumps(candidate_payload, ensure_ascii=False)}

Rules:
- Return every supplied candidate in results. Never return partial product lists.
- Choose exactly one best product when a valid confident match exists.
- Mark other valid products as alternative.
- Mark irrelevant, unavailable, rule-failing, search-page-only, or ambiguous products as rejected.
- Include a rejection_reason for every rejected product.
- Include confidence_score from 0 to 1 for every product.
- Product URLs should be direct product pages when available, not search pages.
- Relevance comes first, then in-stock status, best unit value, package fit for the total quantity needed, saved preferences such as organic, and nearest valid store context.
- For eggs, prefer standard shell egg cartons, 12-count or larger cartons, availability, nearby stores, and lowest price per egg. Reject liquid eggs, egg whites only, boiled eggs, egg bites, and plant-based substitutes when possible.

Return ONLY valid JSON.

Output schema:
{{
  "timestamp": "",
  "search_item": "{normalize_match_text(ingredient)}",
  "store_name": "{store_candidate.get("store_name", "")}",
  "store_address": "{store_candidate.get("store_location_address", "")}",
  "best_product_id": "",
  "best_product": {{}},
  "results": [
    {{
      "id": "",
      "ranking_status": "best|alternative|rejected",
      "rejection_reason": "",
      "confidence_score": 0,
      "reason": ""
    }}
  ]
}}
"""


def normalize_store_product_ranking_response(data, allowed_ids):
    data = data if isinstance(data, dict) else {}
    allowed_ids = set(allowed_ids or [])
    best_product = data.get("best_product") if isinstance(data.get("best_product"), dict) else {}
    best_product_id = clean_text(
        data.get("best_product_id")
        or best_product.get("id")
        or best_product.get("product_id")
        or best_product.get("candidate_id")
    )
    if best_product_id not in allowed_ids:
        best_product_id = ""

    raw_results = data.get("results") if isinstance(data.get("results"), list) else []
    results = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        product_id = clean_text(raw.get("id") or raw.get("product_id") or raw.get("candidate_id"))
        if product_id not in allowed_ids:
            continue

        status = normalize_ranking_status(raw.get("ranking_status") or raw.get("status"))
        if not status and product_id == best_product_id:
            status = "best"
        elif not status:
            status = "alternative"

        results.append({
            "id": product_id,
            "ranking_status": status,
            "rejection_reason": clean_text(raw.get("rejection_reason") or raw.get("reject_reason")),
            "confidence_score": bounded_confidence(raw.get("confidence_score") or raw.get("confidence")) or 0,
            "reason": clean_text(raw.get("reason")),
        })

    result_ids = {result.get("id") for result in results}
    for product_id in allowed_ids - result_ids:
        results.append({
            "id": product_id,
            "ranking_status": "best" if product_id == best_product_id else "alternative",
            "rejection_reason": "",
            "confidence_score": 0,
            "reason": "",
        })

    if not best_product_id:
        for result in results:
            if result.get("ranking_status") == "best":
                best_product_id = result.get("id", "")
                break

    return {
        "best_product_id": best_product_id,
        "best_product": best_product,
        "results": results,
        "timestamp": clean_text(data.get("timestamp")),
        "search_item": clean_text(data.get("search_item")),
        "store_name": clean_text(data.get("store_name")),
        "store_address": clean_text(data.get("store_address")),
    }


def normalize_ranking_status(value):
    text = normalize_match_text(value)
    if text in {"best", "selected", "winner", "pick", "picked"}:
        return "best"
    if text in {"alternative", "valid", "valid alternative", "candidate"}:
        return "alternative"
    if text in {"rejected", "reject", "invalid", "unavailable", "not relevant", "not selectable"}:
        return "rejected"
    return ""


def apply_store_product_ranking_selection(candidates, selection):
    if selection.get("status") != "done":
        return candidates

    results_by_id = {
        result.get("id"): result
        for result in selection.get("results", [])
        if result.get("id")
    }
    best_product_id = selection.get("best_product_id", "")

    for candidate in candidates:
        result = results_by_id.get(candidate.get("id"), {})
        status = normalize_ranking_status(result.get("ranking_status"))
        confidence = bounded_confidence(result.get("confidence_score")) or 0
        reason = clean_text(result.get("reason"))
        rejection_reason = clean_text(result.get("rejection_reason"))
        selected = candidate.get("id") == best_product_id

        if selected and status != "rejected":
            status = "best"

        agent_summary = {
            "status": "done",
            "model": selection.get("model", PRODUCT_ANALYSIS_MODEL),
            "selected_product_id": best_product_id,
            "ranking_status": status,
            "confidence_score": confidence,
            "reason": reason,
            "rejection_reason": rejection_reason,
            "selected": selected,
        }
        if selection.get("prompt"):
            agent_summary["prompt"] = selection.get("prompt")
        candidate["chatgpt_store_ranking_agent"] = agent_summary

        if confidence:
            candidate["confidence"] = round(max(candidate.get("confidence", 0), confidence), 2)
            candidate["confidence_score"] = candidate["confidence"]

        if status:
            candidate["ranking_status"] = status

        if status == "rejected":
            candidate["viable"] = False
            if rejection_reason:
                candidate["rejection_reason"] = rejection_reason
                candidate["skip_reasons"] = unique_texts(candidate.get("skip_reasons", []) + [rejection_reason])
            candidate["score"] = round(candidate.get("score", 0) - 80, 2)
        elif status == "best":
            candidate["score"] = round(candidate.get("score", 0) + 65 + (confidence * 20), 2)
            candidate["reason_selected"] = reason or "ChatGPT store ranking chose this product-card candidate as the best store match."
            candidate["ranking_reasons"] = unique_texts(
                candidate.get("ranking_reasons", [])
                + ["ChatGPT store ranking chose this product-card candidate as the best store match.", reason]
            )
        elif status == "alternative":
            candidate["score"] = round(candidate.get("score", 0) + (confidence * 8), 2)
            candidate["ranking_reasons"] = unique_texts(
                candidate.get("ranking_reasons", [])
                + ["ChatGPT store ranking kept this product as a valid alternative.", reason]
            )

    return candidates


def apply_chatgpt_final_product_selection(ingredient, candidates, full_address="", quantity_context=None):
    if not product_final_selection_agent_enabled():
        return candidates

    agent_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("source") != "search-page-fallback"
        and candidate_has_direct_product_url(candidate)
    ]
    selectable_ids = {
        candidate.get("id")
        for candidate in agent_candidates
        if candidate.get("viable") and candidate.get("id")
    }

    if not agent_candidates or not selectable_ids:
        return candidates

    selection = choose_best_product_with_chatgpt(
        ingredient,
        sorted(agent_candidates, key=lambda item: item.get("score", 0), reverse=True),
        full_address=full_address,
        quantity_context=quantity_context,
        selectable_ids=selectable_ids,
    )

    if selection.get("status") != "done":
        return candidates

    selected_id = selection.get("selected_product_id", "")
    if not selected_id:
        return candidates

    selected_seen = False
    for candidate in candidates:
        agent_summary = {
            "status": "done",
            "model": selection.get("model", PRODUCT_ANALYSIS_MODEL),
            "selected_product_id": selected_id,
            "confidence": selection.get("confidence"),
            "reason": selection.get("reason", ""),
            "best_result": selection.get("best_result", {}),
            "result_count": len(selection.get("results", [])),
            "selected": candidate.get("id") == selected_id,
        }
        if candidate.get("id") == selected_id and selection.get("prompt"):
            agent_summary["prompt"] = selection.get("prompt")
        candidate["final_selection_agent"] = agent_summary

        if candidate.get("id") != selected_id:
            continue

        selected_seen = True
        confidence = selection.get("confidence")
        confidence_score = confidence if isinstance(confidence, (int, float)) else 0
        candidate["score"] = round(candidate.get("score", 0) + 85 + (confidence_score * 25), 2)
        candidate["confidence"] = round(max(candidate.get("confidence", 0), confidence_score), 2)
        candidate["reason_selected"] = selection.get("reason", "")
        candidate["ranking_reasons"] = unique_texts(
            candidate.get("ranking_reasons", [])
            + [
                "ChatGPT final selection agent chose this direct product link as the closest match.",
                selection.get("reason", ""),
            ]
        )

    if not selected_seen:
        return candidates

    return sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)


def choose_best_product_with_chatgpt(ingredient, candidates, full_address="", quantity_context=None, selectable_ids=None):
    client = get_product_analysis_client()

    if not client:
        return {
            "status": "skipped",
            "message": "ChatGPT final product selection skipped because OPENAI_API_KEY is not set.",
        }

    limited_candidates = candidates[:product_final_selection_candidate_limit()]
    prompt_ids = {candidate.get("id") for candidate in limited_candidates if candidate.get("id")}
    allowed_ids = prompt_ids & set(selectable_ids or prompt_ids)
    system_prompt = (
        "You are a grocery product collection agent for a shopping-list app. "
        "Normalize every supplied product-card candidate, choose one best_result from those candidates only, "
        "use saved rules strictly, prefer direct product links, and return only valid JSON."
    )
    user_prompt = build_final_product_selection_prompt(
        ingredient,
        limited_candidates,
        full_address,
        quantity_context=quantity_context,
    )
    prompt_payload = chatgpt_prompt_payload(
        "final-product-selection",
        PRODUCT_ANALYSIS_MODEL,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    try:
        with PRODUCT_AI_ANALYSIS_LOCK:
            response = client.chat.completions.create(
                model=PRODUCT_ANALYSIS_MODEL,
                messages=prompt_payload["messages"],
                response_format={"type": "json_object"},
                temperature=0,
            )
        data = json.loads(clean_json_response(response.choices[0].message.content))
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"ChatGPT final product selection failed: {exc}",
            "prompt": prompt_payload,
        }

    selection = normalize_final_product_selection(data, allowed_ids)
    selection["status"] = "done"
    selection["model"] = PRODUCT_ANALYSIS_MODEL
    selection["prompt"] = prompt_payload
    selection["candidate_count_sent"] = len(limited_candidates)
    return selection


def build_final_product_selection_prompt(ingredient, candidates, full_address, quantity_context=None):
    rules_payload = product_analysis_rules_payload()
    quantity_context = quantity_context or {}
    candidate_payload = [
        final_product_candidate_payload(candidate)
        for candidate in candidates
    ]
    source_pages = unique_texts([
        candidate.get("source_page_url") or candidate.get("search_url", "")
        for candidate in candidates
        if candidate.get("source_page_url") or candidate.get("search_url")
    ])

    return f"""
You are a grocery product collection agent.

Requested item:
{ingredient}

The app has already searched nearby activated stores, loaded the search/category pages, and captured visible product cards. Treat the candidate list below as the product-card collection to normalize and judge. Do not invent products or omit candidates that were supplied.

Total shopping-list quantity needed:
{quantity_context.get("display") or "Not specified"}

Quantity sources:
{json.dumps(quantity_context.get("sources", []), ensure_ascii=False)}

Current saved address:
{full_address}

Captured source/search pages:
{json.dumps(source_pages, ensure_ascii=False)}

Saved food rules:
{json.dumps(rules_payload.get("food_rules", {}), ensure_ascii=False)}

Saved best-product ranking guidance:
{json.dumps(rules_payload.get("best_product_ranking", []), ensure_ascii=False)}

Captured product-card JSON from activated nearby stores:
{json.dumps(candidate_payload, ensure_ascii=False)}

Collection requirements:
- Return every candidate product supplied above in results. Never return partial product lists.
- Preserve the candidate id, store name, store location, product name, brand, size/count, price, price per egg if available, price per unit if shown, in-stock status, product URL, image URL, raw product-card HTML snippet, product-card text, and embedded image status/value.
- Product URLs must be direct product pages when available, not search pages.
- If a field is not available, leave it as an empty string or null.
- You must not browse or fetch any store website. Rank only the product-card data supplied in this prompt.

Best-result rules:
- Pick best_result from the supplied results only.
- Match the requested item as closely as possible. If the item contains OR/and-or alternatives, matching any one alternative is acceptable.
- Take the total shopping-list quantity into account. Prefer a package or item count that covers the needed quantity with the least practical excess/waste.
- For eggs, prefer standard shell eggs, 12-count or larger cartons, availability, nearby stores, and the lowest price per egg when possible. Include cage-free, organic, brown, white, large, extra-large, 18-count, and 24-count shell eggs. Exclude unrelated egg products when possible, including liquid eggs, egg whites only, boiled eggs, egg bites, and plant-based egg substitutes.
- If the needed quantity is a small unitless count (for example 1 lemon, 1 onion, 2 eggs), prefer an each/single item or the smallest count package over a bulk bag, multi-pack, or multi-pound package unless the bulk package is the only candidate that satisfies strict food rules.
- For a plain whole-food item such as lemon, onion, basil, asparagus, or egg, prefer the actual whole grocery item over juice, extract, drinks, desserts, mixes, prepared foods, cleaners, or scented products unless the shopping item asks for those forms.
- Required food rules are strict. If a candidate does not confirm a required trait, do not choose it.
- Avoid rules are strict. Do not choose a candidate that contains avoided ingredients, labels, or terms.
- Prefer visible price, unit price/value, package size, in-stock status, nearby store distance, and evidence from fully loaded product-page analysis.
- If no candidate is a confident product match, return best_result as an empty object.

Return ONLY valid JSON.

Output schema:
{{
  "timestamp": "",
  "search_item": "{normalize_match_text(ingredient)}",
  "source_page_url": "",
  "best_result": {{}},
  "results": []
}}
"""


def final_product_candidate_payload(candidate):
    page_analysis = candidate.get("chatgpt_analysis") or {}
    rendered_html_agent = candidate.get("chatgpt_rendered_html_agent") or {}
    embedded_image = candidate.get("embedded_image_base64", "")
    embedded_image_value = (
        embedded_image
        if product_prompt_include_embedded_images()
        else embedded_image_prompt_placeholder(embedded_image)
    )

    return {
        "id": candidate.get("id", ""),
        "store_name": candidate.get("store_name", ""),
        "store_location": {
            "name": candidate.get("store_location_name", ""),
            "address": candidate.get("store_location_address", ""),
            "distance_miles": candidate.get("store_location_distance_miles"),
            "pickup_enabled": candidate.get("pickup_enabled"),
        },
        "source_page_url": candidate.get("source_page_url") or candidate.get("search_url", ""),
        "rendered_page_url": candidate.get("rendered_page_url", ""),
        "rendered_page_html_path": candidate.get("rendered_page_html_path", ""),
        "rendered_page_text_path": candidate.get("rendered_page_text_path", ""),
        "rendered_page_prompt_preview_path": candidate.get("rendered_page_prompt_preview_path", ""),
        "rendered_page_product_related_html_path": candidate.get("rendered_page_product_related_html_path", ""),
        "rendered_page_html_length": candidate.get("rendered_page_html_length", 0),
        "rendered_page_visible_text_length": candidate.get("rendered_page_visible_text_length", 0),
        "product_name": candidate.get("product_name", ""),
        "brand": candidate.get("brand", ""),
        "product_category": candidate.get("product_category", ""),
        "package_count": candidate.get("package_count", ""),
        "product_id": candidate.get("product_id", ""),
        "requested_quantity": candidate.get("requested_quantity", ""),
        "quantity_fit": candidate.get("quantity_fit", {}),
        "size_count": product_size(candidate),
        "price": candidate.get("price", ""),
        "price_per_egg": candidate.get("price_per_egg", ""),
        "price_per_egg_value": candidate.get("price_per_egg_value"),
        "price_per_unit": candidate.get("unit_price", ""),
        "price_per_unit_value": candidate.get("unit_price_value"),
        "price_per_unit_unit": candidate.get("unit_price_unit", ""),
        "product_url": candidate.get("product_url", ""),
        "image_url": candidate.get("image_url", ""),
        "raw_product_html_snippet": candidate.get("raw_product_html_snippet", ""),
        "product_card_text": candidate.get("card_text_excerpt") or candidate.get("detail_text_excerpt", ""),
        "embedded_image_base64": embedded_image_value,
        "embedded_image_base64_captured": bool(embedded_image),
        "embedded_image_base64_length": len(embedded_image),
        "availability": candidate.get("availability", ""),
        "in_stock": candidate.get("in_stock"),
        "pickup_available": candidate.get("pickup_available"),
        "delivery_available": candidate.get("delivery_available"),
        "store_localization": candidate.get("store_localization", {}),
        "proof_of_store_selection": candidate.get("proof_of_store_selection", []),
        "ranking_status": candidate.get("ranking_status", ""),
        "rejection_reason": candidate.get("rejection_reason", ""),
        "egg_product": candidate.get("egg_product", {}),
        "local_confidence": candidate.get("confidence"),
        "confidence_score": candidate.get("confidence_score", candidate.get("confidence")),
        "local_score": candidate.get("score"),
        "food_rule_status": candidate.get("food_rule_status", {}),
        "ranking_reasons": candidate.get("ranking_reasons", [])[:6],
        "skip_reasons": candidate.get("skip_reasons", [])[:6],
        "chatgpt_page_analysis": {
            "status": page_analysis.get("status", ""),
            "is_product_page": page_analysis.get("is_product_page"),
            "is_correct_product": page_analysis.get("is_correct_product"),
            "ingredient_match_confidence": page_analysis.get("ingredient_match_confidence"),
            "food_rules_ok": page_analysis.get("food_rules_ok"),
            "confidence": page_analysis.get("confidence"),
            "reason": page_analysis.get("reason", ""),
            "evidence": page_analysis.get("evidence", [])[:4],
        },
        "chatgpt_rendered_html_reasoning": {
            "status": rendered_html_agent.get("status", ""),
            "ranking_status": rendered_html_agent.get("ranking_status", ""),
            "confidence_score": rendered_html_agent.get("confidence_score"),
            "reason": rendered_html_agent.get("reason", ""),
            "rejection_reason": rendered_html_agent.get("rejection_reason", ""),
        },
    }


def embedded_image_prompt_placeholder(value):
    if not value:
        return ""

    return "[embedded image stored on candidate; {length} chars omitted from ChatGPT prompt]".format(
        length=len(value),
    )


def normalize_final_product_selection(data, allowed_ids):
    data = data if isinstance(data, dict) else {}
    best_result = data.get("best_result") if isinstance(data.get("best_result"), dict) else {}
    selected_id = clean_text(
        data.get("selected_product_id")
        or best_result.get("id")
        or best_result.get("product_id")
        or best_result.get("candidate_id")
    )
    if selected_id not in allowed_ids:
        selected_id = ""

    return {
        "selected_product_id": selected_id,
        "confidence": bounded_confidence(data.get("confidence") or best_result.get("confidence")) or 0,
        "reason": clean_text(data.get("reason") or best_result.get("reason")),
        "timestamp": clean_text(data.get("timestamp")),
        "search_item": clean_text(data.get("search_item")),
        "source_page_url": clean_text(data.get("source_page_url")),
        "best_result": best_result,
        "results": data.get("results") if isinstance(data.get("results"), list) else [],
        "ranked_product_ids": [
            product_id
            for product_id in clean_text_list(data.get("ranked_product_ids"))
            if product_id in allowed_ids
        ],
        "rejected_product_ids": [
            product_id
            for product_id in clean_text_list(data.get("rejected_product_ids"))
            if product_id in allowed_ids
        ],
    }


def product_quantity_score(ingredient, candidate, quantity_context=None):
    quantity_context = quantity_context or candidate.get("requested_quantity_context") or {}
    requested = parse_display_quantity(quantity_context.get("display") or candidate.get("requested_quantity"))
    metadata = {
        "requested_quantity": quantity_context.get("display") or candidate.get("requested_quantity", ""),
    }

    if not requested:
        return {"score": 0, "reasons": [], "skip_reasons": [], "metadata": metadata}

    package = parse_candidate_package_quantity(candidate)
    metadata["requested_low"] = requested.get("low")
    metadata["requested_high"] = requested.get("high")
    metadata["requested_unit"] = requested.get("unit", "")
    metadata["package"] = package
    reasons = [f"Total shopping-list quantity needed: {metadata['requested_quantity']}."]
    skip_reasons = []
    score = 0

    requested_amount = requested.get("high") or requested.get("low")
    requested_unit = normalize_unit(requested.get("unit", ""))
    if requested_unit and requested_unit_matches_ingredient(ingredient, requested_unit):
        requested_unit = ""
        metadata["requested_unit_treated_as_count"] = True
    package_amount = package.get("amount")
    package_unit = normalize_unit(package.get("unit", ""))

    if requested_amount and package_amount and units_compatible_for_quantity(requested_unit, package_unit):
        comparable_requested = convert_quantity_amount(requested_amount, requested_unit, package_unit)
        if comparable_requested:
            ratio = package_amount / comparable_requested
            metadata["coverage_ratio"] = round(ratio, 3)

            if ratio < 0.95:
                score -= 22
                skip_reasons.append("Package appears smaller than the total quantity needed.")
            elif ratio <= 1.35:
                score += 28
                reasons.append("Package size closely fits the total quantity needed.")
            elif ratio <= 2.25:
                score += 12
                reasons.append("Package covers the total quantity with modest extra.")
            elif ratio <= 4:
                score -= 8
                skip_reasons.append("Package is larger than needed for the total quantity.")
            else:
                score -= 24
                skip_reasons.append("Package is much larger than the total quantity needed.")

            return {"score": score, "reasons": reasons, "skip_reasons": skip_reasons, "metadata": metadata}

    if requested_unit == "" and requested_amount:
        whole_item_adjustment = unitless_whole_item_quantity_score(
            ingredient,
            candidate,
            requested_amount,
            package,
        )
        metadata.update(whole_item_adjustment.get("metadata", {}))
        score += whole_item_adjustment.get("score", 0)
        reasons.extend(whole_item_adjustment.get("reasons", []))
        skip_reasons.extend(whole_item_adjustment.get("skip_reasons", []))

    return {"score": score, "reasons": reasons, "skip_reasons": skip_reasons, "metadata": metadata}


def unitless_whole_item_quantity_score(ingredient, candidate, requested_amount, package):
    text = " ".join([
        candidate.get("product_name", ""),
        candidate.get("package_size", ""),
        candidate.get("size", ""),
    ]).lower()
    package_unit = normalize_unit(package.get("unit", ""))
    package_amount = package.get("amount")
    metadata = {}

    if package_amount and package_unit in {"ct", "ea", "pack", "pk"}:
        ratio = package_amount / requested_amount
        metadata["coverage_ratio"] = round(ratio, 3)
        if ratio <= 1.25:
            return {
                "score": 28,
                "reasons": ["Package count closely fits the total quantity needed."],
                "skip_reasons": [],
                "metadata": metadata,
            }
        if ratio <= 2.5:
            return {
                "score": 8,
                "reasons": ["Package count covers the total quantity with modest extra."],
                "skip_reasons": [],
                "metadata": metadata,
            }
        return {
            "score": -18,
            "reasons": [],
            "skip_reasons": ["Package count is much larger than the total quantity needed."],
            "metadata": metadata,
        }

    if requested_amount <= 2 and looks_like_single_each_product(ingredient, candidate):
        return {
            "score": 30,
            "reasons": ["Single-item product fits the small total quantity needed."],
            "skip_reasons": [],
            "metadata": metadata,
        }

    if requested_amount <= 2 and (
        package_unit in {"lb", "oz", "g", "kg"}
        or re.search(r"\b(?:bag|bulk|multi[-\s]?pack|pack|pound|lb)\b", text)
    ):
        return {
            "score": -26,
            "reasons": [],
            "skip_reasons": ["Bulk or weight-based package is likely more than the small count needed."],
            "metadata": metadata,
        }

    return {"score": 0, "reasons": [], "skip_reasons": [], "metadata": metadata}


def parse_candidate_package_quantity(candidate):
    text = " ".join([
        candidate.get("package_size", ""),
        candidate.get("size", ""),
        candidate.get("product_name", ""),
    ])
    match = re.search(
        r"(?<![\w.])(?P<amount>\d+(?:\.\d+)?|\d+\s+\d+/\d+|\d+/\d+)\s*"
        r"(?P<unit>fl\s*oz|fluid\s*ounces?|ounces?|oz|pounds?|lbs?|lb|grams?|g|kilograms?|kg|"
        r"count|ct|pack|pk|each|ea)\b",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return {}

    amount = parse_fraction_number(match.group("amount"))
    if amount is None:
        return {}

    return {
        "amount": float(amount),
        "unit": normalize_unit(match.group("unit")),
        "display": clean_text(match.group(0)),
    }


def requested_unit_matches_ingredient(ingredient, unit):
    unit_tokens = set(tokenize(unit))
    ingredient_variants = ingredient_match_variants(ingredient)

    if not unit_tokens:
        return False

    for variant in ingredient_variants:
        variant_tokens = set(tokenize(variant))
        if unit_tokens and unit_tokens.issubset(variant_tokens):
            return True

    return False


def units_compatible_for_quantity(left_unit, right_unit):
    left = normalize_unit(left_unit)
    right = normalize_unit(right_unit)

    if left == right:
        return True

    return quantity_unit_family(left) and quantity_unit_family(left) == quantity_unit_family(right)


def quantity_unit_family(unit):
    unit = normalize_unit(unit)
    if unit in {"oz", "lb", "g", "kg"}:
        return "weight"
    if unit in {"fl oz", "ml", "l", "cup", "tablespoon", "teaspoon"}:
        return "volume"
    if unit in {"ct", "ea", "pack", "pk"}:
        return "count"
    return ""


def convert_quantity_amount(amount, from_unit, to_unit):
    from_unit = normalize_unit(from_unit)
    to_unit = normalize_unit(to_unit)

    if from_unit == to_unit:
        return amount

    to_grams = {"oz": 28.3495, "lb": 453.592, "g": 1, "kg": 1000}
    to_ml = {"fl oz": 29.5735, "cup": 236.588, "tablespoon": 14.7868, "teaspoon": 4.92892, "ml": 1, "l": 1000}

    if from_unit in to_grams and to_unit in to_grams:
        return amount * to_grams[from_unit] / to_grams[to_unit]

    if from_unit in to_ml and to_unit in to_ml:
        return amount * to_ml[from_unit] / to_ml[to_unit]

    return None


def looks_like_single_each_product(ingredient, candidate):
    name = normalize_match_text(candidate.get("product_name", ""))
    ingredient_name = normalize_match_text(ingredient)

    if not name or not ingredient_name:
        return False

    if re.search(r"\b(?:bag|pack|pk|ct|count|lb|oz|pound)\b", name):
        return False

    first_variant = normalize_match_text(ingredient_match_variants(ingredient)[0] if ingredient_match_variants(ingredient) else ingredient)
    return (
        name == first_variant
        or name.startswith(first_variant + " ")
        or name.endswith(" " + first_variant)
        or re.search(rf"\b{re.escape(first_variant)}\b", name)
    )


def apply_egg_product_metadata(ingredient, candidate):
    if not is_egg_request(ingredient):
        return {}

    text = egg_candidate_text(candidate)
    tokens = set(tokenize(text))
    count = parse_egg_count(text)
    price_amount = parse_price_amount(candidate.get("price"))
    price_per_egg_value = None
    price_per_egg = ""

    if count and price_amount is not None:
        price_per_egg_value = round(price_amount / count, 4)
        price_per_egg = "${:.2f}/egg".format(price_amount / count)

    avoid_matches = sorted(tokens & EGG_PRODUCT_AVOID_TERMS)
    shell_score = len(tokens & EGG_PRODUCT_SHELL_TERMS)
    standard_shell = (
        not avoid_matches
        and ("egg" in tokens or "eggs" in tokens)
        and (shell_score >= 1 or bool(count))
    )

    metadata = {
        "is_egg_request": True,
        "egg_count": count,
        "price_per_egg_value": price_per_egg_value,
        "price_per_egg": price_per_egg,
        "standard_shell_egg_carton": standard_shell,
        "excluded_egg_terms": avoid_matches,
    }
    candidate["egg_product"] = metadata
    candidate["egg_count"] = count
    candidate["price_per_egg"] = price_per_egg
    candidate["price_per_egg_value"] = price_per_egg_value
    return metadata


def egg_product_preference_score(ingredient, candidate):
    metadata = apply_egg_product_metadata(ingredient, candidate)
    if not metadata:
        return {"score": 0, "reasons": [], "skip_reasons": []}

    score = 0
    reasons = []
    skip_reasons = []

    if metadata.get("standard_shell_egg_carton"):
        score += 28
        reasons.append("Standard shell egg carton match.")
    else:
        score -= 42
        skip_reasons.append("Egg product is not a standard shell egg carton.")

    count = metadata.get("egg_count")
    if count:
        if count >= 12:
            score += 18
            reasons.append(f"Egg carton count is {int(count)}.")
        else:
            score -= 10
            skip_reasons.append(f"Egg carton count is below 12 ({int(count)}).")
    else:
        skip_reasons.append("Egg carton count was not clear.")

    if metadata.get("price_per_egg_value") is not None:
        score += 10
        reasons.append(f"Price per egg calculated: {metadata.get('price_per_egg')}.")

    if metadata.get("excluded_egg_terms"):
        score -= 65
        skip_reasons.append(
            "Excluded egg-product form detected: "
            + ", ".join(metadata.get("excluded_egg_terms", []))
            + "."
        )

    return {"score": score, "reasons": reasons, "skip_reasons": skip_reasons}


def is_egg_request(ingredient):
    tokens = set(tokenize(ingredient))
    return bool(tokens & {"egg", "eggs"}) and "eggplant" not in tokens


def egg_candidate_text(candidate):
    return " ".join([
        candidate.get("product_name", ""),
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("package_size", ""),
        candidate.get("size", ""),
        candidate.get("unit_price", ""),
        candidate.get("card_text_excerpt", ""),
        candidate.get("detail_text_excerpt", ""),
    ]).lower()


def parse_egg_count(text):
    text = clean_text(text).lower()

    if re.search(r"\bdozen\b", text):
        return 12

    match = re.search(
        r"\b(\d{1,3})[-\s]*(?:count|ct|pack|pk|carton|eggs?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        value = safe_float(match.group(1))
        return int(value) if value else None

    return None


def parse_price_amount(value):
    text = normalize_price(value)
    match = PRICE_PATTERN.search(text)
    if not match:
        return None

    return safe_float(match.group(0).replace("$", ""))


def score_candidate(ingredient, candidate, quantity_context=None):
    score = 20.0
    reasons = []
    skip_reasons = []
    viable = True
    quantity_context = quantity_context or candidate.get("requested_quantity_context") or {}
    apply_quantity_context_to_candidate(candidate, quantity_context)

    if candidate.get("source") == "search-page-fallback":
        return (
            1.0,
            ["Saved store search page as a reference."],
            ["No direct product card, price, or product URL was available."],
            False,
        )

    product_name = candidate.get("product_name", "")
    detail_text = " ".join([
        product_name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    match = best_ingredient_candidate_match(ingredient, candidate)
    ingredient_tokens = match.get("ingredient_tokens", set())
    overlap = match.get("overlap", 0)
    token_ratio = match.get("token_ratio", 0)
    name_overlap = match.get("name_overlap", 0)
    name_token_ratio = match.get("name_token_ratio", 0)
    exact_name_match = match.get("exact_name_match", False)
    exact_phrase_match = match.get("exact_phrase_match", False)
    matched_ingredient = match.get("ingredient", ingredient)

    metadata = {
        "exact_name_match": exact_name_match,
        "exact_phrase_match": exact_phrase_match,
        "matched_ingredient": matched_ingredient,
        "ingredient_token_ratio": round(token_ratio, 3),
        "name_token_ratio": round(name_token_ratio, 3),
        "detail_evaluated": bool(candidate.get("detail_evaluated")),
        "organic": bool(candidate.get("is_organic")),
        "unit_price_value": candidate.get("unit_price_value"),
        "unit_price_unit": candidate.get("unit_price_unit", ""),
        "package_size": candidate.get("package_size", ""),
        "in_stock": candidate.get("in_stock"),
        "chatgpt_analysis_status": (candidate.get("chatgpt_analysis") or {}).get("status", ""),
        "chatgpt_confidence": candidate.get("chatgpt_confidence"),
        "chatgpt_ingredient_match_confidence": candidate.get("chatgpt_ingredient_match_confidence"),
        "requested_quantity": quantity_context.get("display") or candidate.get("requested_quantity", ""),
    }
    candidate["ranking_metadata"] = metadata

    if DETAIL_REQUIRED and not candidate.get("detail_evaluated"):
        if candidate_has_rankable_card_evidence(ingredient, candidate):
            score -= 8
            reasons.append("Visible product card has enough direct product evidence for ranking.")
        else:
            score -= 45
            viable = False
            skip_reasons.append("Full product page was not successfully evaluated.")
    elif candidate.get("detail_evaluated"):
        score += 15
        reasons.append("Full product page was opened and evaluated.")

    if exact_name_match:
        score += 38
        reasons.append("Exact product name match.")
    elif exact_phrase_match:
        score += 28
        reasons.append("Product name contains the exact ingredient phrase.")
    elif name_token_ratio >= 0.8:
        score += 22
        reasons.append("Product name matches most ingredient terms.")

    score += token_ratio * 25
    if token_ratio:
        if normalize_match_text(matched_ingredient) != normalize_match_text(ingredient):
            reasons.append(f"Matches {overlap} term(s) from alternative '{matched_ingredient}'.")
        else:
            reasons.append(f"Matches {overlap} ingredient term(s).")
    else:
        score -= 25
        skip_reasons.append("Product name does not clearly match the ingredient.")

    if ingredient_tokens and not exact_phrase_match and token_ratio < 0.5:
        score -= 20
        viable = False
        skip_reasons.append("Full product details do not confirm enough ingredient terms.")

    ai_analysis = candidate.get("chatgpt_analysis") or {}
    if ai_analysis.get("status") == "done":
        if ai_analysis.get("is_product_page") is False:
            score -= 60
            viable = False
            skip_reasons.append("ChatGPT analysis says the loaded page is not a product page.")

        if ai_analysis.get("is_correct_product") is False:
            score -= 120
            viable = False
            skip_reasons.append("ChatGPT analysis says the loaded page does not match the shopping item.")
        elif ai_analysis.get("is_correct_product") is True:
            score += 24
            reasons.append("ChatGPT confirmed the fully loaded page matches the shopping item.")

        match_confidence = safe_float(ai_analysis.get("ingredient_match_confidence"))
        if match_confidence is not None:
            score += match_confidence * 16
            reasons.append(f"ChatGPT ingredient-match confidence: {match_confidence:.2f}.")

        analysis_confidence = safe_float(ai_analysis.get("confidence"))
        if analysis_confidence is not None:
            score += analysis_confidence * 10
            reasons.append(f"ChatGPT page-analysis confidence: {analysis_confidence:.2f}.")
    elif ai_analysis.get("status") == "failed":
        skip_reasons.append(ai_analysis.get("message") or "ChatGPT product analysis failed.")
    elif ai_analysis.get("status") == "skipped":
        skip_reasons.append(ai_analysis.get("message") or "ChatGPT product analysis was skipped.")

    food_status = candidate.get("food_rule_status") or {}
    if food_status.get("blocked_by"):
        score -= 100
        viable = False
        skip_reasons.append("Blocked by food rules: " + "; ".join(food_status.get("blocked_by", [])))
    if food_status.get("missing_required"):
        score -= 100
        viable = False
        skip_reasons.append("Missing required food preference: " + "; ".join(food_status.get("missing_required", [])))
    elif not food_status.get("blocked_by"):
        score += 20
        reasons.append("Matches required food preferences.")

    if candidate.get("is_organic"):
        score += 18
        reasons.append("Organic option.")

    if candidate.get("price"):
        score += 10
        reasons.append("Has a visible price.")
    else:
        score -= 8
        skip_reasons.append("Price was not visible in the parsed store page.")

    if candidate.get("unit_price_value") is not None:
        score += 8
        reasons.append(f"Has unit value: {candidate.get('unit_price')}.")
    else:
        score -= 4
        skip_reasons.append("Unit value was not available from the product page.")

    if candidate.get("package_size"):
        score += 6
        reasons.append(f"Package size found: {candidate.get('package_size')}.")
    else:
        score -= 3
        skip_reasons.append("Package size was not clear from the product page.")

    quantity_adjustment = product_quantity_score(ingredient, candidate, quantity_context)
    score += quantity_adjustment.get("score", 0)
    candidate["quantity_fit"] = quantity_adjustment.get("metadata", {})
    reasons.extend(quantity_adjustment.get("reasons", []))
    skip_reasons.extend(quantity_adjustment.get("skip_reasons", []))

    egg_adjustment = egg_product_preference_score(ingredient, candidate)
    score += egg_adjustment.get("score", 0)
    reasons.extend(egg_adjustment.get("reasons", []))
    skip_reasons.extend(egg_adjustment.get("skip_reasons", []))
    if (candidate.get("egg_product") or {}).get("excluded_egg_terms") and not candidate.get("allow_edible_egg_products"):
        viable = False

    if candidate.get("in_stock") is True:
        score += 12
        reasons.append("Nearby store page indicates availability.")
    elif candidate.get("in_stock") is False:
        score -= 60
        viable = False
        skip_reasons.append("Product page indicates the product is unavailable or out of stock.")
    else:
        skip_reasons.append("Nearby store inventory was not confirmed on the product page.")

    if candidate_has_direct_product_url(candidate):
        score += 8
        reasons.append("Has a direct product URL.")
    else:
        score -= 80
        viable = False
        skip_reasons.append("A direct product URL was not available; search-page links are not selectable.")

    distance = candidate.get("store_location_distance_miles")
    if isinstance(distance, (int, float)):
        score += max(0, 12 - min(distance, 12))
        reasons.append(f"Nearest {candidate.get('store_name')} is about {distance:.1f} mi away.")
    else:
        skip_reasons.append("Nearest store distance was not available.")

    if score < 5:
        viable = False

    return score, reasons, skip_reasons, viable


def candidate_has_direct_product_url(candidate):
    product_url = str(candidate.get("product_url") or "").strip()
    search_url = str(candidate.get("search_url") or "").strip()

    return product_url.startswith(("http://", "https://")) and product_url != search_url


def select_product_choice(item_key, product_id, store_key=""):
    item_key = normalize_item_key(item_key)
    product_id = str(product_id or "").strip()
    store_key = str(store_key or "").strip()
    state = load_product_choices()
    record = state.get("items", {}).get(item_key)

    if not record:
        return {
            "ok": False,
            "error": "No product choices were saved for that ingredient.",
        }

    selected = next(
        (
            candidate
            for candidate in record.get("candidates", [])
            if candidate.get("id") == product_id
            and (not store_key or candidate.get("store_key") == store_key)
        ),
        None,
    )

    if not selected:
        return {
            "ok": False,
            "error": "That product choice was not found.",
        }

    if selected.get("viable") is False:
        return {
            "ok": False,
            "error": "That product choice is saved as a reference, but it is not selectable.",
        }

    selected["reason_selected"] = selected.get("reason_selected") or product_selection_reason(
        selected,
        selected.get("store_name", ""),
    )
    selected_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    selected["selected_by_user"] = True
    selected["selected_at"] = selected_at

    if store_key:
        store_results = record.setdefault("store_results", {})
        store_candidates = [
            candidate
            for candidate in record.get("candidates", [])
            if candidate.get("store_key") == store_key
        ]
        store_result = find_store_result(record, store_key) or {
            "store_key": store_key,
            "store_name": selected.get("store_name", ""),
            "ingredient": record.get("ingredient", item_key),
            "alternatives": store_candidates,
            "alternative_products": store_candidates,
        }
        store_result.update({
            "best_product_id": product_id,
            "best_product": selected,
            "best_product_match": selected.get("product_name", ""),
            "price": selected.get("price", ""),
            "size": product_size(selected),
            "unit_price": selected.get("unit_price", ""),
            "product_url": selected.get("product_url", ""),
            "image_url": selected.get("image_url", ""),
            "reason_selected": selected.get("reason_selected", ""),
            "reason_skipped": "",
            "skip_reason": "",
            "selected_by_user": True,
            "selected_at": selected_at,
            "alternatives": store_candidates,
            "alternative_products": store_candidates,
            "valid_alternatives": [
                candidate
                for candidate in store_candidates
                if candidate.get("viable") is not False
            ],
            "rejected_products": [
                candidate
                for candidate in store_candidates
                if candidate.get("viable") is False
            ],
        })
        store_results[store_key] = store_result
        record["store_results_list"] = upsert_store_result_list(
            record.get("store_results_list", []),
            store_result,
        )

    record["selected_product_id"] = product_id
    record["selected_product"] = selected
    record["manual_override"] = True
    record["manual_override_store_key"] = store_key
    record["selected_by_user"] = True
    record["selected_at"] = selected_at
    record["updated_at"] = selected_at
    save_product_choices(state)
    save_item_store(item_key, selected.get("store_key") or "")

    return {
        "ok": True,
        "item_key": item_key,
        "choice": product_choice_for_store(record, store_key) if store_key else record,
    }


def upsert_store_result_list(store_results_list, store_result):
    output = []
    replaced = False
    store_key = store_result.get("store_key")

    for item in store_results_list if isinstance(store_results_list, list) else []:
        if item.get("store_key") == store_key:
            output.append(store_result)
            replaced = True
        else:
            output.append(item)

    if not replaced:
        output.append(store_result)

    return output


def build_product_search_url(store, ingredient):
    base_url = str(store.get("url") or "").strip()

    if not base_url:
        return ""

    encoded = quote_plus(str(ingredient or "").strip())

    if "{query}" in base_url:
        return base_url.replace("{query}", encoded)

    if base_url.endswith(("=", "/", "?")):
        return base_url + encoded

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}q={encoded}"


def contextualized_product_search_url(search_url, store_key, full_address="", store_location=None):
    search_url = str(search_url or "").strip()
    if not search_url:
        return ""

    return search_url


def geocode_home_address(full_address):
    full_address = str(full_address or "").strip()

    if not full_address:
        return None

    for query in home_address_geocode_queries(full_address):
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "format": "jsonv2",
                    "q": query,
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers=REQUEST_HEADERS,
                timeout=(4, 10),
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue

        if not isinstance(data, list) or not data:
            continue

        try:
            return {
                "latitude": float(data[0].get("lat")),
                "longitude": float(data[0].get("lon")),
                "display_name": data[0].get("display_name", ""),
                "query": query,
            }
        except (TypeError, ValueError):
            continue

    return None


def home_address_geocode_queries(full_address):
    text = clean_text(full_address)
    if not text:
        return []

    variants = []

    def add(value):
        value = clean_text(value)
        value = re.sub(r"\s+,", ",", value)
        value = re.sub(r",\s*,+", ",", value).strip(" ,")
        if value and value not in variants:
            variants.append(value)

    without_unit = re.sub(
        r"\s+(?:(?:apt|apartment|unit|suite|ste)\b|#)\s*[A-Za-z0-9-]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    without_county = re.sub(
        r",\s*[^,]*\bcounty\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    without_unit_or_county = re.sub(
        r",\s*[^,]*\bcounty\b",
        "",
        without_unit,
        flags=re.IGNORECASE,
    )

    add(text)
    add(without_unit)
    add(without_county)
    add(without_unit_or_county)

    return variants


def find_nearest_store_location(store_key, store, full_address, home_location):
    store_name = store.get("label") or store_key.title()
    locator_url = build_store_locator_url(store, full_address)
    fallback = {
        "name": store_name,
        "address": "",
        "distance_miles": None,
        "locator_url": locator_url,
        "source": "configured-store-locator",
        "pickup_enabled": True,
        "pickup_status": "Assumed pickup-capable because the store is enabled for product search.",
    }

    if not home_location:
        fallback["skip_reason"] = "Home address could not be geocoded."
        return fallback

    lat = home_location["latitude"]
    lon = home_location["longitude"]
    delta = 0.45

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "jsonv2",
                "q": store_name,
                "limit": 8,
                "countrycodes": "us",
                "bounded": 1,
                "viewbox": f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}",
                "addressdetails": 1,
            },
            headers=REQUEST_HEADERS,
            timeout=(4, 10),
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        fallback["skip_reason"] = f"Nearest store lookup failed: {exc}"
        return fallback

    locations = []
    for item in data if isinstance(data, list) else []:
        try:
            item_lat = float(item.get("lat"))
            item_lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue

        display_name = clean_text(item.get("display_name"))
        distance = haversine_miles(lat, lon, item_lat, item_lon)
        locations.append({
            "name": store_name,
            "address": display_name,
            "latitude": item_lat,
            "longitude": item_lon,
            "distance_miles": round(distance, 2),
            "locator_url": locator_url,
            "source": "nominatim",
            "pickup_enabled": True,
            "pickup_status": "Nearest location resolved for pickup-oriented grocery search.",
        })

    if not locations:
        fallback["skip_reason"] = "No nearby store location was found."
        return fallback

    return min(locations, key=lambda item: item["distance_miles"])


def build_store_locator_url(store, full_address):
    url = str(store.get("urlStoreSelector") or "").strip()

    if not url:
        return ""

    try:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("q", full_address)
        return urlunparse(parsed._replace(query=urlencode(query)))
    except Exception:
        return url


def haversine_miles(lat1, lon1, lat2, lon2):
    radius_miles = 3958.8
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def apply_relative_candidate_preferences(candidates):
    groups = {}

    for candidate in candidates:
        if not candidate.get("viable"):
            continue

        unit = normalize_unit(candidate.get("unit_price_unit", ""))
        value = candidate.get("unit_price_value")

        if value is None or not unit:
            continue

        groups.setdefault(unit, []).append(candidate)

    for unit_candidates in groups.values():
        if len(unit_candidates) < 2:
            continue

        values = [
            candidate.get("unit_price_value")
            for candidate in unit_candidates
            if isinstance(candidate.get("unit_price_value"), (int, float))
        ]

        if not values:
            continue

        best = min(values)
        worst = max(values)
        spread = max(0.01, worst - best)

        for candidate in unit_candidates:
            value = candidate.get("unit_price_value")
            if not isinstance(value, (int, float)):
                continue

            if value == best:
                candidate["score"] = round(candidate.get("score", 0) + 14, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Best unit value among comparable products."]
                )
            else:
                value_score = max(0, 10 * ((worst - value) / spread))
                candidate["score"] = round(candidate.get("score", 0) + value_score, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Unit value compared with alternatives."]
                )

    egg_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate.get("viable")
            and isinstance(candidate.get("price_per_egg_value"), (int, float))
            and (candidate.get("egg_product") or {}).get("standard_shell_egg_carton")
        )
    ]
    if len(egg_candidates) >= 2:
        values = [candidate.get("price_per_egg_value") for candidate in egg_candidates]
        best = min(values)
        worst = max(values)
        spread = max(0.01, worst - best)

        for candidate in egg_candidates:
            value = candidate.get("price_per_egg_value")
            if value == best:
                candidate["score"] = round(candidate.get("score", 0) + 22, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Lowest price per egg among comparable shell-egg cartons."]
                )
            else:
                value_score = max(0, 14 * ((worst - value) / spread))
                candidate["score"] = round(candidate.get("score", 0) + value_score, 2)
                candidate["ranking_reasons"] = unique_texts(
                    candidate.get("ranking_reasons", [])
                    + ["Price per egg compared with comparable shell-egg cartons."]
                )

    for candidate in candidates:
        candidate["confidence"] = round(max(0.05, min(0.98, candidate.get("score", 0) / 120)), 2)

    return candidates


def dedupe_candidates(candidates):
    deduped = []
    seen = set()

    for candidate in candidates:
        key = (
            normalize_item_key(candidate.get("store_key")),
            normalize_item_key(candidate.get("product_name")),
            candidate.get("price") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    return deduped


def product_candidate_id(store_key, product_url, product_name, price):
    raw = "|".join(str(value or "") for value in [store_key, product_url, product_name, price])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def safe_float(value):
    try:
        return float(str(value or "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_unit(value):
    text = clean_text(value).lower().replace(".", "")
    text = re.sub(r"\s+", " ", text)
    aliases = {
        "ounces": "oz",
        "ounce": "oz",
        "fluid ounce": "fl oz",
        "fluid ounces": "fl oz",
        "pounds": "lb",
        "pound": "lb",
        "lbs": "lb",
        "grams": "g",
        "gram": "g",
        "kilogram": "kg",
        "kilograms": "kg",
        "count": "ct",
        "each": "ea",
        "piece": "ea",
        "pc": "ea",
        "packs": "pack",
        "pk": "pack",
        "pks": "pack",
        "cups": "cup",
        "tablespoons": "tablespoon",
        "tbsp": "tablespoon",
        "teaspoons": "teaspoon",
        "tsp": "teaspoon",
        "milliliters": "ml",
        "milliliter": "ml",
        "liters": "l",
        "liter": "l",
    }
    return aliases.get(text, text)


def ingredient_search_terms(ingredient):
    variants = ingredient_match_variants(ingredient)
    terms = []
    seen = set()

    for variant in variants:
        term = clean_ingredient_search_text(variant)
        key = normalize_match_text(term)

        if term and key not in seen:
            seen.add(key)
            terms.append(term)

    fallback = clean_ingredient_search_text(ingredient)
    if fallback and not terms:
        terms.append(fallback)

    return terms[:4] or [clean_text(ingredient)]


def ingredient_match_variants(ingredient):
    text = clean_ingredient_search_text(ingredient)
    if not text:
        return []

    parts = [
        clean_ingredient_search_text(part)
        for part in INGREDIENT_ALTERNATIVE_PATTERN.split(text)
        if clean_ingredient_search_text(part)
    ]

    if len(parts) <= 1:
        return [text]

    return unique_texts(expand_alternative_parts(parts))


def expand_alternative_parts(parts):
    if len(parts) != 2:
        return parts

    left, right = parts
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)

    if 0 < len(left_tokens) <= 2 and len(right_tokens) > len(left_tokens):
        suffix_tokens = list(right_tokens)

        while suffix_tokens and suffix_tokens[0] in QUALIFIER_TOKENS:
            suffix_tokens.pop(0)

        if suffix_tokens and not set(suffix_tokens) & set(left_tokens):
            return [
                " ".join(left_tokens + suffix_tokens),
                right,
            ]

    return parts


def clean_ingredient_search_text(value):
    text = clean_text(value).replace("*", "")
    text = re.sub(r"\s+", " ", text).strip(" ,;")

    for pattern, replacement in GROCERY_QUERY_REPLACEMENTS:
        text = pattern.sub(replacement, text)

    return clean_text(text)


def best_ingredient_candidate_match(ingredient, candidate):
    product_name = candidate.get("product_name", "")
    detail_text = " ".join([
        product_name,
        candidate.get("brand", ""),
        candidate.get("description", ""),
        candidate.get("ingredients_text", ""),
        candidate.get("detail_text_excerpt", ""),
    ])
    normalized_name = normalize_match_text(product_name)
    product_tokens = set(tokenize(detail_text))
    name_tokens = set(tokenize(product_name))
    best = None

    for option in ingredient_match_variants(ingredient):
        ingredient_tokens = set(tokenize(option))
        normalized_ingredient = normalize_match_text(option)
        overlap = len(ingredient_tokens & product_tokens)
        name_overlap = len(ingredient_tokens & name_tokens)
        token_ratio = overlap / max(1, len(ingredient_tokens))
        name_token_ratio = name_overlap / max(1, len(ingredient_tokens))
        exact_name_match = bool(normalized_ingredient and normalized_ingredient == normalized_name)
        exact_phrase_match = bool(normalized_ingredient and normalized_ingredient in normalized_name)
        rank = (
            int(exact_name_match),
            int(exact_phrase_match),
            round(name_token_ratio, 4),
            round(token_ratio, 4),
            name_overlap,
            overlap,
        )
        current = {
            "ingredient": option,
            "ingredient_tokens": ingredient_tokens,
            "overlap": overlap,
            "token_ratio": token_ratio,
            "name_overlap": name_overlap,
            "name_token_ratio": name_token_ratio,
            "exact_name_match": exact_name_match,
            "exact_phrase_match": exact_phrase_match,
            "rank": rank,
        }

        if best is None or current["rank"] > best["rank"]:
            best = current

    if best:
        return best

    return {
        "ingredient": ingredient,
        "ingredient_tokens": set(tokenize(ingredient)),
        "overlap": 0,
        "token_ratio": 0,
        "name_overlap": 0,
        "name_token_ratio": 0,
        "exact_name_match": False,
        "exact_phrase_match": False,
        "rank": (0, 0, 0, 0, 0, 0),
    }


def normalize_match_text(value):
    return " ".join(tokenize(value))


def tokenize(text):
    return [
        normalize_product_token(token)
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) > 1 and token not in {"and", "or", "the", "with", "fresh", "whole"}
    ]


def normalize_product_token(token):
    token = TOKEN_ALIASES.get(token, token)

    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"

    if len(token) > 4 and token.endswith("oes"):
        return token[:-2]

    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]

    return token


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def extract_zip_code(value):
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", str(value or ""))
    return match.group(0) if match else ""


def normalize_item_key(text):
    return " ".join(str(text or "").strip().lower().split())


def is_section_header(text):
    text = str(text or "").strip()
    return text.startswith("===") and text.endswith("===")


def unique_texts(values):
    seen = set()
    output = []

    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            output.append(text)
            seen.add(text)

    return output
