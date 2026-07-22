import json
import os
import re
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent
MODEL_OVERRIDES_FILE = Path(
    os.getenv("SHOPPING_APP_OPENAI_MODEL_OVERRIDES_FILE", PACKAGE_DIR / "openai_model_overrides.json")
)
MODEL_LIST_CACHE_FILE = Path(
    os.getenv("SHOPPING_APP_OPENAI_MODEL_LIST_CACHE_FILE", PACKAGE_DIR / "openai_model_list_cache.json")
)
MODEL_RECOMMENDATION_CACHE_FILE = Path(
    os.getenv(
        "SHOPPING_APP_OPENAI_MODEL_RECOMMENDATION_CACHE_FILE",
        PACKAGE_DIR / "openai_model_recommendation_cache.json",
    )
)
LOCAL_ENV_FILE = Path(os.getenv("SHOPPING_APP_LOCAL_ENV_FILE", PACKAGE_DIR.parent / "local_env.bat"))
MODEL_LIST_CACHE_TTL_SECONDS = 60 * 60
LOCAL_ENV_MODEL_BLOCK_BEGIN = "rem BEGIN Chat GPT Models admin panel selections"
LOCAL_ENV_MODEL_BLOCK_END = "rem END Chat GPT Models admin panel selections"
BAT_SET_ENV_RE = re.compile(r'^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=', re.IGNORECASE)
BAT_IF_NOT_DEFINED_SET_ENV_RE = re.compile(
    r'^\s*if\s+not\s+defined\s+([A-Za-z_][A-Za-z0-9_]*)\s+set\s+"?([A-Za-z_][A-Za-z0-9_]*)=',
    re.IGNORECASE,
)
_APPLIED_MODEL_OVERRIDES_SIGNATURE = None


OPENAI_MODEL_SETTINGS = (
    {
        "env_var": "OPENAI_MENU_MODEL",
        "feature": "Import Recipe URLs (Menu)",
        "default_model": "gpt-5.5",
        "description": "Recipe URL imports and menu-driven text/document recipe extraction.",
    },
    {
        "env_var": "OPENAI_MENU_MODEL",
        "feature": "Import Doc / Photo (Menu)",
        "default_model": "gpt-5.5",
        "description": "Uploaded documents and non-vision menu import extraction.",
    },
    {
        "env_var": "OPENAI_MENU_CLEANUP_MODEL",
        "feature": "Menu Cleanup / Equipment",
        "default_model": "gpt-4o-mini",
        "description": "One-call menu item normalization plus likely equipment prediction before lightweight menu stubs are saved.",
    },
    {
        "env_var": "OPENAI_MENU_RECIPE_MODEL",
        "feature": "Menu Recipe Generation (Full)",
        "default_model": "gpt-5.5",
        "description": "Full background enrichment that turns imported menu item stubs into detailed AI-inferred recipes.",
    },
    {
        "env_var": "OPENAI_MENU_FAST_RECIPE_MODEL",
        "feature": "Menu Recipe Generation (Fast)",
        "default_model": "gpt-4o-mini",
        "description": "Fast background enrichment model for smaller menu-item recipe batches.",
    },
    {
        "env_var": "OPENAI_MENU_FAILED_ITEM_MODEL",
        "feature": "Failed Menu Item Retry",
        "default_model": "gpt-5.4-mini",
        "description": "Targeted retry model used only for menu items that fail the normal menu recipe inference pass.",
    },
    {
        "env_var": "OPENAI_VISION_MODEL",
        "feature": "Image Vision",
        "default_model": "gpt-5.5",
        "description": "Read Text, Describe Recipe, and Generate Recipe From Image for image uploads.",
    },
    {
        "env_var": "OPENAI_RECIPE_MODEL",
        "feature": "Recipe Helpers",
        "default_model": "gpt-4o-mini",
        "description": "General recipe helper fallback used outside the menu and vision import paths.",
    },
    {
        "env_var": "OPENAI_COOKBOOK_ITEM_MODEL",
        "feature": "Cookbook Item Details",
        "default_model": "gpt-5.5-mini",
        "description": "Fill missing cookbook/menu-item recipe details such as ingredients, equipment, instructions, servings, and time estimates.",
    },
    {
        "env_var": "OPENAI_RECIPE_CATEGORY_MODEL",
        "feature": "Recipe Categories",
        "default_model": "gpt-4o-mini",
        "description": "Cookbook/category suggestions for imported and edited recipes.",
    },
    {
        "env_var": "OPENAI_NUTRITION_MODEL",
        "feature": "Nutrition",
        "default_model": "gpt-4o-mini",
        "description": "Per-serving and recipe nutrition estimates.",
    },
    {
        "env_var": "OPENAI_RECIPE_NOTE_MODEL",
        "feature": "Recipe Notes",
        "default_model": "gpt-4o-mini",
        "description": "Recipe reflection and note helpers.",
    },
    {
        "env_var": "OPENAI_PRODUCT_ANALYSIS_MODEL",
        "feature": "Product Analysis",
        "default_model": "gpt-4o-mini",
        "description": "Store product matching and selection analysis.",
    },
    {
        "env_var": "OPENAI_INGREDIENT_REVIEW_MODEL",
        "feature": "Ingredient Review",
        "default_model": "gpt-4o-mini",
        "description": "Ingredient cleanup and ambiguity review.",
    },
    {
        "env_var": "OPENAI_FOOD_RULES_MODEL",
        "feature": "Food Rules",
        "default_model": "gpt-4o-mini",
        "description": "Food restriction and rule checks.",
    },
    {
        "env_var": "OPENAI_FOOD_REVIEW_MODEL",
        "feature": "Food Alternatives",
        "default_model": "gpt-4o-mini",
        "description": "Alternative suggestions for food review.",
    },
    {
        "env_var": "OPENAI_ADDRESS_MODEL",
        "feature": "Home Address",
        "default_model": "gpt-4o-mini",
        "description": "Address completion when local parsing needs help.",
    },
    {
        "env_var": "OPENAI_PING_TEXT_MODEL",
        "feature": "OpenAI Ping",
        "default_model": "gpt-4o-mini",
        "description": "Debug ping route used to verify basic text-model connectivity.",
    },
    {
        "env_var": "OPENAI_TRANSCRIPTION_MODEL",
        "feature": "Audio Transcription",
        "default_model": "whisper-1",
        "description": "Audio transcription for social video recipe imports.",
    },
    {
        "env_var": "OPENAI_STEP_IMAGE_MODEL",
        "feature": "Recipe Step Images",
        "default_model": "gpt-image-1",
        "description": "Image generation for recipe step illustrations.",
    },
)

OPENAI_MODEL_USAGE_BY_ENV = {
    "OPENAI_MENU_MODEL": {
        "kind": "import",
        "icon": "URL",
        "title": "Import workspace",
        "detail": "Recipe URLs and menu documents",
        "href": "/#importPage",
        "surfaces": ("Recipe URL", "Menu document"),
    },
    "OPENAI_MENU_CLEANUP_MODEL": {
        "kind": "menu",
        "icon": "FIX",
        "title": "Menu imports",
        "detail": "Cleanup and equipment prediction",
        "href": "/#menusPage",
        "surfaces": ("Menu cleanup", "Equipment"),
    },
    "OPENAI_MENU_RECIPE_MODEL": {
        "kind": "menu",
        "icon": "FULL",
        "title": "Menus",
        "detail": "Full recipe generation jobs",
        "href": "/#menusPage",
        "surfaces": ("Menu item", "Full generation"),
    },
    "OPENAI_MENU_FAST_RECIPE_MODEL": {
        "kind": "menu",
        "icon": "FAST",
        "title": "Menus",
        "detail": "Fast recipe generation batches",
        "href": "/#menusPage",
        "surfaces": ("Menu item", "Fast generation"),
    },
    "OPENAI_MENU_FAILED_ITEM_MODEL": {
        "kind": "menu",
        "icon": "TRY",
        "title": "Menu job recovery",
        "detail": "Retries failed menu items",
        "href": "/#menusPage",
        "surfaces": ("Failed items", "Retry"),
    },
    "OPENAI_VISION_MODEL": {
        "kind": "media",
        "icon": "IMG",
        "title": "Import from image",
        "detail": "Reads and describes uploaded photos",
        "href": "/#generateImagePage",
        "surfaces": ("Photo upload", "Vision"),
    },
    "OPENAI_RECIPE_MODEL": {
        "kind": "recipe",
        "icon": "HELP",
        "title": "Recipe helpers",
        "detail": "General recipe AI fallback",
        "href": "/#recipesPage",
        "surfaces": ("Recipes", "Editor helpers"),
    },
    "OPENAI_COOKBOOK_ITEM_MODEL": {
        "kind": "recipe",
        "icon": "BOOK",
        "title": "Cookbooks",
        "detail": "Fills missing recipe details",
        "href": "/#cookbooksPage",
        "surfaces": ("Cookbook item", "Fill details"),
    },
    "OPENAI_RECIPE_CATEGORY_MODEL": {
        "kind": "recipe",
        "icon": "TAG",
        "title": "Recipe categories",
        "detail": "Suggests cookbook organization",
        "href": "/#cookbooksPage",
        "surfaces": ("Categories", "Cookbooks"),
    },
    "OPENAI_NUTRITION_MODEL": {
        "kind": "recipe",
        "icon": "NUTR",
        "title": "Recipe editor",
        "detail": "Nutrition tab estimates",
        "href": "/#recipesPage",
        "surfaces": ("Nutrition", "Per serving"),
    },
    "OPENAI_RECIPE_NOTE_MODEL": {
        "kind": "recipe",
        "icon": "NOTE",
        "title": "Recipe editor",
        "detail": "Notes and reflection helpers",
        "href": "/#recipesPage",
        "surfaces": ("Notes", "Recipe editor"),
    },
    "OPENAI_PRODUCT_ANALYSIS_MODEL": {
        "kind": "shopping",
        "icon": "SHOP",
        "title": "Compare Prices",
        "detail": "Product matching and selection",
        "href": "/#priceComparisonPage",
        "surfaces": ("Store products", "Comparison"),
    },
    "OPENAI_INGREDIENT_REVIEW_MODEL": {
        "kind": "data",
        "icon": "DATA",
        "title": "Ingredient Master Data",
        "detail": "Cleanup, duplicates, and AI review",
        "href": "/admin/master-data/ingredients",
        "surfaces": ("Ingredients", "AI review"),
    },
    "OPENAI_FOOD_RULES_MODEL": {
        "kind": "settings",
        "icon": "RULE",
        "title": "Rules & Automation",
        "detail": "Food restriction checks",
        "href": "/#settingsRulesAutomationPanel",
        "surfaces": ("Food rules", "Restrictions"),
    },
    "OPENAI_FOOD_REVIEW_MODEL": {
        "kind": "recipe",
        "icon": "SWAP",
        "title": "Recipe alternatives",
        "detail": "Food-review substitutions",
        "href": "/#recipesPage",
        "surfaces": ("Alternatives", "Ingredients"),
    },
    "OPENAI_ADDRESS_MODEL": {
        "kind": "settings",
        "icon": "MAP",
        "title": "Location settings",
        "detail": "Home-address completion",
        "href": "/#settingsLocationPanel",
        "surfaces": ("Home address", "Location"),
    },
    "OPENAI_PING_TEXT_MODEL": {
        "kind": "settings",
        "icon": "PING",
        "title": "AI connection test",
        "detail": "Basic text-model diagnostics",
        "href": "/#userAccountSection",
        "surfaces": ("Diagnostics", "Connection"),
    },
    "OPENAI_TRANSCRIPTION_MODEL": {
        "kind": "media",
        "icon": "AUDIO",
        "title": "Import workspace",
        "detail": "Social-video audio transcription",
        "href": "/#importPage",
        "surfaces": ("Social video", "Transcription"),
    },
    "OPENAI_STEP_IMAGE_MODEL": {
        "kind": "media",
        "icon": "STEP",
        "title": "Recipe instructions",
        "detail": "Generates step illustrations",
        "href": "/#recipesPage",
        "surfaces": ("Instructions", "Step images"),
    },
}


def openai_model_usage(env_var):
    usage = OPENAI_MODEL_USAGE_BY_ENV.get(env_var) or {
        "kind": "settings",
        "icon": "AI",
        "title": "AI Pantry",
        "detail": "OpenAI-powered application feature",
        "href": "/#userAccountSection",
        "surfaces": ("AI feature",),
    }
    return {
        **usage,
        "surfaces": list(usage.get("surfaces") or []),
    }

DEFAULT_RECOMMENDED_MODEL_BY_ENV = {
    "OPENAI_MENU_MODEL": "gpt-5.5",
    "OPENAI_MENU_CLEANUP_MODEL": "gpt-5.4-mini",
    "OPENAI_MENU_RECIPE_MODEL": "gpt-5.5",
    "OPENAI_MENU_FAST_RECIPE_MODEL": "gpt-4o-mini",
    "OPENAI_MENU_FAILED_ITEM_MODEL": "gpt-5.4-mini",
    "OPENAI_VISION_MODEL": "gpt-5.5",
    "OPENAI_RECIPE_MODEL": "gpt-5.5-mini",
    "OPENAI_COOKBOOK_ITEM_MODEL": "gpt-5.5-mini",
    "OPENAI_RECIPE_CATEGORY_MODEL": "gpt-5.5-mini",
    "OPENAI_NUTRITION_MODEL": "gpt-5.5-mini",
    "OPENAI_RECIPE_NOTE_MODEL": "gpt-5.5-mini",
    "OPENAI_PRODUCT_ANALYSIS_MODEL": "gpt-5.5-mini",
    "OPENAI_INGREDIENT_REVIEW_MODEL": "gpt-5.5-mini",
    "OPENAI_FOOD_RULES_MODEL": "gpt-5.5-mini",
    "OPENAI_FOOD_REVIEW_MODEL": "gpt-5.5-mini",
    "OPENAI_ADDRESS_MODEL": "gpt-5.5-mini",
    "OPENAI_PING_TEXT_MODEL": "gpt-5.5-mini",
    "OPENAI_TRANSCRIPTION_MODEL": "whisper-1",
    "OPENAI_STEP_IMAGE_MODEL": "gpt-image-1",
}

LOWEST_VIABLE_MODEL_BY_ENV = {
    "OPENAI_MENU_MODEL": "gpt-5.4-mini",
    "OPENAI_MENU_CLEANUP_MODEL": "gpt-5.4-nano",
    "OPENAI_MENU_RECIPE_MODEL": "gpt-5.4-mini",
    "OPENAI_MENU_FAST_RECIPE_MODEL": "gpt-4o-mini",
    "OPENAI_MENU_FAILED_ITEM_MODEL": "gpt-5.4-mini",
    "OPENAI_VISION_MODEL": "gpt-5.4-mini",
    "OPENAI_RECIPE_MODEL": "gpt-5.4-nano",
    "OPENAI_COOKBOOK_ITEM_MODEL": "gpt-5.4-nano",
    "OPENAI_RECIPE_CATEGORY_MODEL": "gpt-5.4-nano",
    "OPENAI_NUTRITION_MODEL": "gpt-5.4-nano",
    "OPENAI_RECIPE_NOTE_MODEL": "gpt-5.4-nano",
    "OPENAI_PRODUCT_ANALYSIS_MODEL": "gpt-5.4-nano",
    "OPENAI_INGREDIENT_REVIEW_MODEL": "gpt-5.4-nano",
    "OPENAI_FOOD_RULES_MODEL": "gpt-5.4-nano",
    "OPENAI_FOOD_REVIEW_MODEL": "gpt-5.4-nano",
    "OPENAI_ADDRESS_MODEL": "gpt-5.4-nano",
    "OPENAI_PING_TEXT_MODEL": "gpt-5.4-nano",
    "OPENAI_TRANSCRIPTION_MODEL": "whisper-1",
    "OPENAI_STEP_IMAGE_MODEL": "gpt-image-1",
}

LEGACY_MODEL_RECOMMENDATIONS = {
    "gpt-4-0613": "gpt-5.5",
    "gpt-4-0314": "gpt-5.5",
    "gpt-4-32k": "gpt-5.5",
    "gpt-4-32k-0613": "gpt-5.5",
    "gpt-3.5-turbo": "gpt-5.5-mini",
    "gpt-3.5-turbo-0125": "gpt-5.5-mini",
    "gpt-3.5-turbo-1106": "gpt-5.5-mini",
    "gpt-3.5-turbo-16k": "gpt-5.5-mini",
    "gpt-4o-mini": "gpt-5.5-mini",
}

DEFAULT_VISIBLE_MODEL_PREFIXES = (
    "gpt-",
    "o",
    "gpt-image-",
    "gpt-audio-",
    "gpt-realtime-",
)
DEFAULT_EXCLUDED_MODEL_PREFIXES = (
    "text-embedding-",
    "whisper-",
    "tts-",
    "omni-moderation-",
    "davinci-",
    "babbage-",
)
DEFAULT_EXCLUDED_MODEL_MARKERS = (
    "deprecated",
    "legacy",
)

MODEL_GROUPS = (
    ("GPT-5 Models", lambda model: model.startswith("gpt-5")),
    ("GPT-4 Models", lambda model: model.startswith("gpt-4")),
    ("Reasoning Models", lambda model: re.match(r"^o\d", model) is not None),
    ("Image Models", lambda model: model.startswith("gpt-image-")),
    ("Audio Models", lambda model: model.startswith(("gpt-audio-", "gpt-realtime-")) or model in {"gpt-audio", "gpt-realtime"}),
)


def unique_model_settings():
    seen = set()
    settings = []
    for setting in OPENAI_MODEL_SETTINGS:
        env_var = setting["env_var"]
        if env_var in seen:
            continue
        seen.add(env_var)
        settings.append(setting)
    return settings


def supports_custom_temperature(model):
    normalized_model = str(model or "").strip().lower()
    return not normalized_model.startswith("gpt-5")


def normalize_model_name(value):
    value = str(value or "").strip()
    if not value:
        return ""

    if not re.match(r"^[A-Za-z0-9._:/-]+$", value):
        return ""

    return value[:120]


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_model_cache_timestamp(value):
    value = str(value or "").strip()
    if not value:
        return "Never"

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return value

    return parsed.strftime("%b %-d, %Y %-I:%M %p UTC") if os.name != "nt" else parsed.strftime("%b %#d, %Y %#I:%M %p UTC")


def load_openai_model_cache():
    if not MODEL_LIST_CACHE_FILE.exists():
        return {}

    try:
        payload = json.loads(MODEL_LIST_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def save_openai_model_cache(models):
    clean_models = sorted({
        normalize_model_name(model)
        for model in (models or [])
        if normalize_model_name(model)
    }, key=str.lower)
    payload = {
        "models": clean_models,
        "last_refreshed": utc_timestamp(),
        "total_count": len(clean_models),
    }
    MODEL_LIST_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_LIST_CACHE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def load_openai_model_recommendation_cache():
    if not MODEL_RECOMMENDATION_CACHE_FILE.exists():
        return {}

    try:
        payload = json.loads(MODEL_RECOMMENDATION_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def save_openai_model_recommendation_cache(mappings):
    clean_mappings = {
        env_var: normalize_model_name(model)
        for env_var, model in (mappings or {}).items()
        if env_var in {setting["env_var"] for setting in unique_model_settings()}
        and normalize_model_name(model)
    }
    payload = {
        "mappings": clean_mappings,
        "last_refreshed": utc_timestamp(),
        "total_count": len(clean_mappings),
    }
    MODEL_RECOMMENDATION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_RECOMMENDATION_CACHE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return payload


def refresh_openai_model_recommendations():
    return save_openai_model_recommendation_cache(DEFAULT_RECOMMENDED_MODEL_BY_ENV)


def refresh_lowest_viable_openai_model_recommendations():
    return save_openai_model_recommendation_cache(LOWEST_VIABLE_MODEL_BY_ENV)


def openai_model_recommendations():
    cache_payload = load_openai_model_recommendation_cache()
    cached_mappings = cache_payload.get("mappings", {}) if isinstance(cache_payload.get("mappings"), dict) else {}
    mappings = {
        **DEFAULT_RECOMMENDED_MODEL_BY_ENV,
        **{
            env_var: normalize_model_name(model)
            for env_var, model in cached_mappings.items()
            if normalize_model_name(model)
        },
    }

    if cache_payload.get("last_refreshed"):
        last_refreshed = cache_payload.get("last_refreshed", "")
        source = "Cached"
    else:
        try:
            last_refreshed = datetime.fromtimestamp(Path(__file__).stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            last_refreshed = ""
        source = "Bundled"

    return {
        "mappings": mappings,
        "source": source,
        "last_refreshed": last_refreshed,
        "last_refreshed_display": format_model_cache_timestamp(last_refreshed) if last_refreshed else "Never",
        "total_count": len([
            env_var
            for env_var in {setting["env_var"] for setting in unique_model_settings()}
            if normalize_model_name(mappings.get(env_var))
        ]),
    }


def proposed_model_for_row(env_var, active_model, recommendations):
    env_var = str(env_var or "").strip()
    active_model = normalize_model_name(active_model)
    mappings = recommendations.get("mappings", {}) if isinstance(recommendations, dict) else {}
    proposed = normalize_model_name(mappings.get(env_var))
    legacy_proposed = normalize_model_name(LEGACY_MODEL_RECOMMENDATIONS.get(active_model))

    if proposed:
        if proposed == active_model:
            return proposed, "Current model already matches recommendation."
        return proposed, "Recommended replacement based on current OpenAI model mappings."

    if legacy_proposed and legacy_proposed != active_model:
        return legacy_proposed, "Recommended replacement based on current OpenAI model mappings."

    return active_model, "No separate recommendation is configured for this route."


def openai_model_cache_is_fresh(cache_payload):
    last_refreshed = str((cache_payload or {}).get("last_refreshed") or "").strip()
    if not last_refreshed:
        return False

    try:
        refreshed = datetime.fromisoformat(last_refreshed.replace("Z", "+00:00")).timestamp()
    except Exception:
        return False

    return time.time() - refreshed < MODEL_LIST_CACHE_TTL_SECONDS


def fetch_openai_models_from_api():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return sorted(
        {
            normalize_model_name(getattr(model, "id", ""))
            for model in client.models.list().data
            if normalize_model_name(getattr(model, "id", ""))
        },
        key=str.lower,
    )


def openai_model_list(force_refresh=False):
    cache_payload = load_openai_model_cache()
    cached_models = [
        normalize_model_name(model)
        for model in cache_payload.get("models", [])
        if normalize_model_name(model)
    ]

    if not force_refresh and cached_models and openai_model_cache_is_fresh(cache_payload):
        return {
            "models": sorted(cached_models, key=str.lower),
            "source": "Cached",
            "last_refreshed": cache_payload.get("last_refreshed", ""),
            "last_refreshed_display": format_model_cache_timestamp(cache_payload.get("last_refreshed", "")),
            "total_count": int(cache_payload.get("total_count") or len(cached_models)),
            "warning": "",
        }

    try:
        live_models = fetch_openai_models_from_api()
        fresh_cache = save_openai_model_cache(live_models)
        return {
            "models": live_models,
            "source": "Live API",
            "last_refreshed": fresh_cache.get("last_refreshed", ""),
            "last_refreshed_display": format_model_cache_timestamp(fresh_cache.get("last_refreshed", "")),
            "total_count": len(live_models),
            "warning": "",
        }
    except Exception as exc:
        warning = f"Unable to refresh OpenAI model list. Showing last cached list. {exc}"
        if cached_models:
            return {
                "models": sorted(cached_models, key=str.lower),
                "source": "Cached",
                "last_refreshed": cache_payload.get("last_refreshed", ""),
                "last_refreshed_display": format_model_cache_timestamp(cache_payload.get("last_refreshed", "")),
                "total_count": int(cache_payload.get("total_count") or len(cached_models)),
                "warning": warning,
            }

        return {
            "models": [],
            "source": "Cached",
            "last_refreshed": "",
            "last_refreshed_display": "Never",
            "total_count": 0,
            "warning": warning,
        }


def model_visible_by_default(model):
    normalized = normalize_model_name(model).lower()
    if not normalized:
        return False
    if normalized.startswith(DEFAULT_EXCLUDED_MODEL_PREFIXES):
        return False
    if any(marker in normalized for marker in DEFAULT_EXCLUDED_MODEL_MARKERS):
        return False
    return normalized.startswith(DEFAULT_VISIBLE_MODEL_PREFIXES)


def group_openai_models(models):
    grouped = []
    used = set()
    clean_models = sorted({
        normalize_model_name(model)
        for model in (models or [])
        if normalize_model_name(model)
    }, key=str.lower)

    for label, matcher in MODEL_GROUPS:
        items = [model for model in clean_models if matcher(model.lower())]
        if items:
            grouped.append({"label": label, "models": items})
            used.update(items)

    other = [model for model in clean_models if model not in used]
    if other:
        grouped.append({"label": "Other Models", "models": other})

    return grouped


def model_choices_for_row(model_list, selected_model, show_advanced_models=False):
    all_models = [
        normalize_model_name(model)
        for model in (model_list or [])
        if normalize_model_name(model)
    ]
    visible_models = all_models if show_advanced_models else [
        model for model in all_models if model_visible_by_default(model)
    ]
    selected_model = normalize_model_name(selected_model)
    selected_available = bool(selected_model and selected_model in all_models)

    if selected_model and selected_model not in visible_models:
        visible_models = [selected_model, *visible_models]

    return {
        "groups": group_openai_models(visible_models),
        "selected_available": selected_available,
    }


def load_openai_model_overrides():
    if not MODEL_OVERRIDES_FILE.exists():
        return {}

    try:
        payload = json.loads(MODEL_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

    overrides = payload.get("models", {}) if isinstance(payload, dict) else {}
    if not isinstance(overrides, dict):
        return {}

    allowed = {setting["env_var"] for setting in unique_model_settings()}
    return {
        env_var: model
        for env_var, model in (
            (str(key or "").strip(), normalize_model_name(value))
            for key, value in overrides.items()
        )
        if env_var in allowed and model
    }


def openai_model_overrides_signature():
    try:
        stat = MODEL_OVERRIDES_FILE.stat()
    except OSError:
        return (str(MODEL_OVERRIDES_FILE), None, None)

    return (str(MODEL_OVERRIDES_FILE), stat.st_mtime_ns, stat.st_size)


def sync_openai_model_environment_from_overrides(force=False, clear_missing=False):
    global _APPLIED_MODEL_OVERRIDES_SIGNATURE

    signature = openai_model_overrides_signature()
    if not force and signature == _APPLIED_MODEL_OVERRIDES_SIGNATURE:
        return False

    apply_openai_model_environment(
        load_openai_model_overrides(),
        clear_missing=clear_missing,
    )
    _APPLIED_MODEL_OVERRIDES_SIGNATURE = signature
    return True


def save_openai_model_overrides(overrides):
    MODEL_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_OVERRIDES_FILE.write_text(
        json.dumps({"models": overrides}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def batch_set_line_env_var(line):
    line = str(line or "")
    match = BAT_IF_NOT_DEFINED_SET_ENV_RE.match(line)
    if match:
        return match.group(2)

    match = BAT_SET_ENV_RE.match(line)
    if match:
        return match.group(1)

    return ""


def clean_openai_model_mapping(models):
    allowed = {setting["env_var"] for setting in unique_model_settings()}
    return {
        env_var: model
        for env_var, model in (
            (str(key or "").strip(), normalize_model_name(value))
            for key, value in (models or {}).items()
        )
        if env_var in allowed and model
    }


def openai_model_env_lines(models):
    clean_models = clean_openai_model_mapping(models)
    lines = [
        LOCAL_ENV_MODEL_BLOCK_BEGIN,
    ]
    for setting in unique_model_settings():
        env_var = setting["env_var"]
        model = clean_models.get(env_var, "")
        if model:
            lines.append(f"set {env_var}={model}")
    lines.append(LOCAL_ENV_MODEL_BLOCK_END)
    return lines


def save_openai_model_local_env(models):
    clean_models = clean_openai_model_mapping(models)
    allowed_env_vars = {setting["env_var"] for setting in unique_model_settings()}
    existing_lines = []
    if LOCAL_ENV_FILE.exists():
        existing_lines = LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines()

    kept_lines = []
    skipping_model_block = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped == LOCAL_ENV_MODEL_BLOCK_BEGIN:
            skipping_model_block = True
            continue
        if stripped == LOCAL_ENV_MODEL_BLOCK_END:
            skipping_model_block = False
            continue
        if skipping_model_block:
            continue
        if batch_set_line_env_var(line) in allowed_env_vars:
            continue
        kept_lines.append(line)

    if not kept_lines:
        kept_lines = ["@echo off"]

    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()

    if clean_models:
        kept_lines.extend(["", *openai_model_env_lines(clean_models)])

    LOCAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_ENV_FILE.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")


def apply_openai_model_environment(models, clear_missing=True):
    clean_models = clean_openai_model_mapping(models)
    for setting in unique_model_settings():
        env_var = setting["env_var"]
        model = clean_models.get(env_var, "")
        if model:
            os.environ[env_var] = model
        elif clear_missing:
            os.environ.pop(env_var, None)

    refresh_openai_model_runtime_bindings()


def refresh_openai_model_runtime_bindings():
    recipe_model = os.getenv("OPENAI_RECIPE_MODEL", default_model_for_env("OPENAI_RECIPE_MODEL"))
    ping_text_model = os.getenv("OPENAI_PING_TEXT_MODEL", default_model_for_env("OPENAI_PING_TEXT_MODEL"))
    product_model = os.getenv("OPENAI_PRODUCT_ANALYSIS_MODEL", recipe_model)
    food_rules_model = os.getenv("OPENAI_FOOD_RULES_MODEL", recipe_model)
    food_review_model = os.getenv("OPENAI_FOOD_REVIEW_MODEL", recipe_model)
    ingredient_review_model = os.getenv("OPENAI_INGREDIENT_REVIEW_MODEL", recipe_model)

    module_updates = {
        "PushShoppingList.services.recipe_extract_service": {
            "MODEL": recipe_model,
            "OPENAI_PING_TEXT_MODEL": ping_text_model,
        },
        "PushShoppingList.routes.recipe_routes": {
            "MODEL": recipe_model,
            "OPENAI_PING_TEXT_MODEL": ping_text_model,
        },
        "PushShoppingList.routes.job_routes": {"MODEL": recipe_model},
        "PushShoppingList.services.recipe_edit_service": {"MODEL": recipe_model},
        "PushShoppingList.services.product_selection_service": {"PRODUCT_ANALYSIS_MODEL": product_model},
        "PushShoppingList.services.food_rules_service": {"MODEL": food_rules_model},
        "PushShoppingList.services.food_review_alternative_service": {"MODEL": food_review_model},
        "PushShoppingList.services.ingredient_text_review_service": {"MODEL": ingredient_review_model},
        "PushShoppingList.services.ingredient_duplicate_review_service": {
            "MODEL": ingredient_review_model,
            "SECOND_OPINION_MODEL": ingredient_review_model,
        },
    }
    for module_name, updates in module_updates.items():
        module = sys.modules.get(module_name)
        if not module:
            continue
        for name, value in updates.items():
            setattr(module, name, value)


def apply_openai_model_overrides():
    sync_openai_model_environment_from_overrides(force=True, clear_missing=False)


def default_model_for_env(env_var):
    for setting in unique_model_settings():
        if setting["env_var"] == env_var:
            return setting["default_model"]
    return "gpt-4o-mini"


def model_value_for_env(env_var, default_model=None):
    sync_openai_model_environment_from_overrides()
    env_var = str(env_var or "").strip()
    default_model = str(default_model or default_model_for_env(env_var)).strip() or "gpt-4o-mini"
    override = load_openai_model_overrides().get(env_var, "")
    env_model = str(os.getenv(env_var, "")).strip()
    if override:
        if env_model != override:
            os.environ[env_var] = override
            refresh_openai_model_runtime_bindings()
            return override, "admin override"
        return override, "admin override"

    if env_model:
        return env_model, "environment"

    return default_model, "default"


def chatgpt_models_dashboard_for_user(user, show_advanced_models=False, force_refresh=False):
    from PushShoppingList.services.user_account_service import is_admin_user

    is_admin = is_admin_user(user)
    sync_openai_model_environment_from_overrides()
    overrides = load_openai_model_overrides()
    recommendations = openai_model_recommendations()
    model_list = openai_model_list(force_refresh=force_refresh) if is_admin else {
        "models": [],
        "source": "Cached",
        "last_refreshed": "",
        "last_refreshed_display": "Never",
        "total_count": 0,
        "warning": "",
    }
    available_models = model_list.get("models", [])
    rows = []
    for setting in unique_model_settings():
        feature_names = [
            row["feature"]
            for row in OPENAI_MODEL_SETTINGS
            if row["env_var"] == setting["env_var"]
        ]
        descriptions = [
            row["description"]
            for row in OPENAI_MODEL_SETTINGS
            if row["env_var"] == setting["env_var"]
        ]
        model, source = model_value_for_env(setting["env_var"], setting["default_model"])
        proposed_model, proposed_model_reason = proposed_model_for_row(
            setting["env_var"],
            model,
            recommendations,
        )
        choices = model_choices_for_row(
            available_models,
            model,
            show_advanced_models=show_advanced_models,
        )
        rows.append({
            **setting,
            "feature": " / ".join(feature_names),
            "description": " ".join(descriptions),
            "model": model,
            "model_groups": choices["groups"],
            "model_choices": [
                model
                for group in choices["groups"]
                for model in group["models"]
            ],
            "selected_available": choices["selected_available"],
            "unavailable_warning": "" if choices["selected_available"] else "⚠ Deprecated or unavailable",
            "proposed_model": proposed_model,
            "proposed_model_reason": proposed_model_reason,
            "source": source,
            "is_override": setting["env_var"] in overrides,
            "supports_temperature": supports_custom_temperature(model),
            "usage": openai_model_usage(setting["env_var"]),
        })

    messages = []
    if model_list.get("warning"):
        messages.append({"category": "warning", "text": model_list["warning"]})

    return {
        "is_admin": is_admin,
        "rows": rows if is_admin else [],
        "errors": [],
        "messages": messages,
        "override_file": str(MODEL_OVERRIDES_FILE),
        "available_models_count": int(model_list.get("total_count") or 0),
        "last_refreshed": model_list.get("last_refreshed", ""),
        "last_refreshed_display": model_list.get("last_refreshed_display", "Never"),
        "model_list_source": model_list.get("source", "Cached"),
        "recommended_mapping_count": int(recommendations.get("total_count") or 0),
        "last_mapping_refreshed": recommendations.get("last_refreshed", ""),
        "last_mapping_refreshed_display": recommendations.get("last_refreshed_display", "Never"),
        "mapping_source": recommendations.get("source", "Bundled"),
        "show_advanced_models": bool(show_advanced_models),
    }


def update_openai_model_settings_for_admin(user, form):
    from PushShoppingList.services.user_account_service import is_admin_user

    if not is_admin_user(user):
        return {"ok": False, "errors": ["Admin access is required."]}

    overrides = load_openai_model_overrides()
    recommendations = openai_model_recommendations()
    action = str((form or {}).get("action") or "").strip()
    use_proposed_env = action.removeprefix("use_proposed:") if action.startswith("use_proposed:") else ""
    allowed_env_vars = {setting["env_var"] for setting in unique_model_settings()}
    if use_proposed_env not in allowed_env_vars:
        use_proposed_env = ""
    errors = []
    next_overrides = dict(overrides)

    for setting in unique_model_settings():
        env_var = setting["env_var"]
        field_name = f"model_{env_var}"
        raw_value = str((form or {}).get(field_name) or "").strip()

        if env_var == use_proposed_env:
            raw_value, _reason = proposed_model_for_row(
                env_var,
                raw_value or model_value_for_env(env_var, setting["default_model"])[0],
                recommendations,
            )

        model = normalize_model_name(raw_value)

        if raw_value and not model:
            errors.append(f"{env_var} contains unsupported characters.")
            continue

        if model:
            next_overrides[env_var] = model
        else:
            next_overrides.pop(env_var, None)

    if errors:
        return {"ok": False, "errors": errors}

    save_openai_model_overrides(next_overrides)
    save_openai_model_local_env(next_overrides)
    sync_openai_model_environment_from_overrides(force=True, clear_missing=True)
    return {"ok": True, "errors": []}
