import json
import os
import re
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
MODEL_LIST_CACHE_TTL_SECONDS = 60 * 60


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
)

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


def save_openai_model_overrides(overrides):
    MODEL_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_OVERRIDES_FILE.write_text(
        json.dumps({"models": overrides}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def apply_openai_model_overrides():
    for env_var, model in load_openai_model_overrides().items():
        os.environ[env_var] = model


def default_model_for_env(env_var):
    for setting in unique_model_settings():
        if setting["env_var"] == env_var:
            return setting["default_model"]
    return "gpt-4o-mini"


def model_value_for_env(env_var, default_model=None):
    env_var = str(env_var or "").strip()
    default_model = str(default_model or default_model_for_env(env_var)).strip() or "gpt-4o-mini"
    override = load_openai_model_overrides().get(env_var, "")
    if override:
        return override, "admin override"

    env_model = str(os.getenv(env_var, "")).strip()
    if env_model:
        return env_model, "environment"

    return default_model, "default"


def chatgpt_models_dashboard_for_user(user, show_advanced_models=False, force_refresh=False):
    from PushShoppingList.services.user_account_service import is_admin_user

    is_admin = is_admin_user(user)
    overrides = load_openai_model_overrides()
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
            "unavailable_warning": "" if choices["selected_available"] else "⚠ Model not currently available to this API key",
            "source": source,
            "is_override": setting["env_var"] in overrides,
            "supports_temperature": supports_custom_temperature(model),
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
        "show_advanced_models": bool(show_advanced_models),
    }


def update_openai_model_settings_for_admin(user, form):
    from PushShoppingList.services.user_account_service import is_admin_user

    if not is_admin_user(user):
        return {"ok": False, "errors": ["Admin access is required."]}

    overrides = load_openai_model_overrides()
    errors = []

    for setting in unique_model_settings():
        env_var = setting["env_var"]
        field_name = f"model_{env_var}"
        raw_value = str((form or {}).get(field_name) or "").strip()
        model = normalize_model_name(raw_value)

        if raw_value and not model:
            errors.append(f"{env_var} contains unsupported characters.")
            continue

        if model:
            overrides[env_var] = model
            os.environ[env_var] = model
        else:
            overrides.pop(env_var, None)
            os.environ.pop(env_var, None)

    if errors:
        return {"ok": False, "errors": errors}

    save_openai_model_overrides(overrides)
    return {"ok": True, "errors": []}
