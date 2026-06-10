import json
import os
import re
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent.parent
MODEL_OVERRIDES_FILE = Path(
    os.getenv("SHOPPING_APP_OPENAI_MODEL_OVERRIDES_FILE", PACKAGE_DIR / "openai_model_overrides.json")
)


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

OPENAI_MODEL_CHOICES = (
    "gpt-5.5",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
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


def chatgpt_models_dashboard_for_user(user):
    from PushShoppingList.services.user_account_service import is_admin_user

    is_admin = is_admin_user(user)
    overrides = load_openai_model_overrides()
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
        model_choices = []
        for candidate in (model, setting["default_model"], *OPENAI_MODEL_CHOICES):
            candidate = normalize_model_name(candidate)
            if candidate and candidate not in model_choices:
                model_choices.append(candidate)
        rows.append({
            **setting,
            "feature": " / ".join(feature_names),
            "description": " ".join(descriptions),
            "model": model,
            "model_choices": model_choices,
            "source": source,
            "is_override": setting["env_var"] in overrides,
            "supports_temperature": supports_custom_temperature(model),
        })

    return {
        "is_admin": is_admin,
        "rows": rows if is_admin else [],
        "errors": [],
        "messages": [],
        "override_file": str(MODEL_OVERRIDES_FILE),
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
