import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PushShoppingList.services import openai_model_service as models


ADMIN_USER = {"email": "admin@example.com"}
EXPECTED_OPENAI_MODEL_ENV_VARS = {
    "OPENAI_MENU_MODEL",
    "OPENAI_MENU_CLEANUP_MODEL",
    "OPENAI_MENU_RECIPE_MODEL",
    "OPENAI_MENU_FAST_RECIPE_MODEL",
    "OPENAI_MENU_FAILED_ITEM_MODEL",
    "OPENAI_VISION_MODEL",
    "OPENAI_RECIPE_MODEL",
    "OPENAI_COOKBOOK_ITEM_MODEL",
    "OPENAI_RECIPE_CATEGORY_MODEL",
    "OPENAI_NUTRITION_MODEL",
    "OPENAI_RECIPE_NOTE_MODEL",
    "OPENAI_PRODUCT_ANALYSIS_MODEL",
    "OPENAI_INGREDIENT_REVIEW_MODEL",
    "OPENAI_FOOD_RULES_MODEL",
    "OPENAI_FOOD_REVIEW_MODEL",
    "OPENAI_ADDRESS_MODEL",
    "OPENAI_PING_TEXT_MODEL",
    "OPENAI_TRANSCRIPTION_MODEL",
    "OPENAI_STEP_IMAGE_MODEL",
}


def configure_model_files(monkeypatch, tmp_path, available_models):
    monkeypatch.setattr(models, "MODEL_OVERRIDES_FILE", tmp_path / "openai_model_overrides.json")
    monkeypatch.setattr(models, "MODEL_LIST_CACHE_FILE", tmp_path / "openai_model_list_cache.json")
    monkeypatch.setattr(models, "LOCAL_ENV_FILE", tmp_path / "local_env.bat")
    monkeypatch.setattr(
        models,
        "MODEL_RECOMMENDATION_CACHE_FILE",
        tmp_path / "openai_model_recommendation_cache.json",
    )
    models.save_openai_model_cache(available_models)
    for setting in models.unique_model_settings():
        monkeypatch.delenv(setting["env_var"], raising=False)


def form_with_default_models():
    return {
        f"model_{setting['env_var']}": setting["default_model"]
        for setting in models.unique_model_settings()
    }


def test_dashboard_always_includes_proposed_model_and_reason(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.5", "gpt-5.5-mini", "gpt-4o-mini"],
    )

    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    rows = {row["env_var"]: row for row in dashboard["rows"]}

    assert rows["OPENAI_MENU_MODEL"]["model"] == "gpt-5.5"
    assert rows["OPENAI_MENU_MODEL"]["proposed_model"] == "gpt-5.5"
    assert rows["OPENAI_MENU_MODEL"]["proposed_model_reason"] == (
        "Current model already matches recommendation."
    )
    assert rows["OPENAI_RECIPE_MODEL"]["model"] == "gpt-4o-mini"
    assert rows["OPENAI_RECIPE_MODEL"]["proposed_model"] == "gpt-5.5-mini"
    assert rows["OPENAI_RECIPE_MODEL"]["proposed_model_reason"] == (
        "Recommended replacement based on current OpenAI model mappings."
    )
    assert dashboard["recommended_mapping_count"] == len(models.DEFAULT_RECOMMENDED_MODEL_BY_ENV)
    assert dashboard["last_mapping_refreshed_display"] != ""


def test_dashboard_includes_all_openai_model_environment_variables(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.5", "gpt-5.5-mini", "gpt-4o-mini", "whisper-1", "gpt-image-1"],
    )

    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    row_env_vars = {row["env_var"] for row in dashboard["rows"]}

    assert row_env_vars == EXPECTED_OPENAI_MODEL_ENV_VARS
    assert set(models.DEFAULT_RECOMMENDED_MODEL_BY_ENV) == EXPECTED_OPENAI_MODEL_ENV_VARS
    assert set(models.LOWEST_VIABLE_MODEL_BY_ENV) == EXPECTED_OPENAI_MODEL_ENV_VARS
    assert set(models.OPENAI_MODEL_USAGE_BY_ENV) == EXPECTED_OPENAI_MODEL_ENV_VARS
    assert dashboard["recommended_mapping_count"] == len(EXPECTED_OPENAI_MODEL_ENV_VARS)

    rows = {row["env_var"]: row for row in dashboard["rows"]}
    assert rows["OPENAI_MENU_MODEL"]["usage"] == {
        "kind": "import",
        "icon": "URL",
        "title": "Import workspace",
        "detail": "Recipe URLs and menu documents",
        "href": "/#importPage",
        "surfaces": ["Recipe URL", "Menu document"],
    }
    assert rows["OPENAI_INGREDIENT_REVIEW_MODEL"]["usage"]["title"] == "Ingredient Master Data"
    assert rows["OPENAI_INGREDIENT_REVIEW_MODEL"]["usage"]["href"] == "/admin/master-data/ingredients"
    assert all(row["usage"]["title"] for row in dashboard["rows"])
    assert all(row["usage"]["href"] for row in dashboard["rows"])


def test_use_proposed_model_persists_recommended_value(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.5", "gpt-5.5-mini", "gpt-4o-mini"],
    )
    form = form_with_default_models()
    form["model_OPENAI_RECIPE_MODEL"] = "gpt-4o-mini"
    form["action"] = "use_proposed:OPENAI_RECIPE_MODEL"

    result = models.update_openai_model_settings_for_admin(ADMIN_USER, form)

    assert result == {"ok": True, "errors": []}
    overrides = json.loads(models.MODEL_OVERRIDES_FILE.read_text(encoding="utf-8"))
    assert overrides["models"]["OPENAI_RECIPE_MODEL"] == "gpt-5.5-mini"
    assert models.LOCAL_ENV_FILE.read_text(encoding="utf-8").count("OPENAI_RECIPE_MODEL") == 1
    assert "set OPENAI_RECIPE_MODEL=gpt-5.5-mini" in models.LOCAL_ENV_FILE.read_text(encoding="utf-8")
    assert os.environ["OPENAI_RECIPE_MODEL"] == "gpt-5.5-mini"


def test_save_models_updates_environment_and_local_env_file(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4o-mini"],
    )
    models.LOCAL_ENV_FILE.write_text(
        "\n".join([
            "@echo off",
            "",
            "rem Existing local setting",
            "set SHOPPING_APP_SMTP_HOST=smtp.gmail.com",
            "if not defined OPENAI_MENU_MODEL set OPENAI_MENU_MODEL=old-menu-model",
            "set OPENAI_RECIPE_MODEL=old-recipe-model",
        ])
        + "\n",
        encoding="utf-8",
    )
    form = form_with_default_models()
    form["model_OPENAI_MENU_MODEL"] = "gpt-5.4-mini"
    form["model_OPENAI_RECIPE_MODEL"] = "gpt-5.4-nano"
    form["model_OPENAI_MENU_CLEANUP_MODEL"] = "gpt-5.4-nano"
    form["model_OPENAI_TRANSCRIPTION_MODEL"] = "whisper-1"
    form["model_OPENAI_STEP_IMAGE_MODEL"] = "gpt-image-1"

    result = models.update_openai_model_settings_for_admin(ADMIN_USER, form)

    assert result == {"ok": True, "errors": []}
    assert os.environ["OPENAI_MENU_MODEL"] == "gpt-5.4-mini"
    assert os.environ["OPENAI_RECIPE_MODEL"] == "gpt-5.4-nano"
    assert os.environ["OPENAI_MENU_CLEANUP_MODEL"] == "gpt-5.4-nano"
    assert os.environ["OPENAI_TRANSCRIPTION_MODEL"] == "whisper-1"
    assert os.environ["OPENAI_STEP_IMAGE_MODEL"] == "gpt-image-1"
    local_env = models.LOCAL_ENV_FILE.read_text(encoding="utf-8")
    assert "set SHOPPING_APP_SMTP_HOST=smtp.gmail.com" in local_env
    assert "old-menu-model" not in local_env
    assert "old-recipe-model" not in local_env
    assert "set OPENAI_MENU_MODEL=gpt-5.4-mini" in local_env
    assert "set OPENAI_RECIPE_MODEL=gpt-5.4-nano" in local_env
    assert "set OPENAI_MENU_CLEANUP_MODEL=gpt-5.4-nano" in local_env
    assert "set OPENAI_TRANSCRIPTION_MODEL=whisper-1" in local_env
    assert "set OPENAI_STEP_IMAGE_MODEL=gpt-image-1" in local_env
    assert local_env.count("OPENAI_MENU_MODEL") == 1

    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    rows = {row["env_var"]: row for row in dashboard["rows"]}
    assert rows["OPENAI_MENU_MODEL"]["model"] == "gpt-5.4-mini"
    assert rows["OPENAI_MENU_MODEL"]["source"] == "admin override"


def test_model_value_syncs_changed_override_file_without_restart(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.5", "gpt-5.4-mini", "gpt-4o-mini"],
    )

    model, source = models.model_value_for_env("OPENAI_MENU_MODEL", "gpt-5.5")

    assert model == "gpt-5.5"
    assert source == "default"
    assert "OPENAI_MENU_MODEL" not in os.environ

    models.MODEL_OVERRIDES_FILE.write_text(
        json.dumps({"models": {"OPENAI_MENU_MODEL": "gpt-4o-mini"}}),
        encoding="utf-8",
    )

    model, source = models.model_value_for_env("OPENAI_MENU_MODEL", "gpt-5.5")
    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    rows = {row["env_var"]: row for row in dashboard["rows"]}

    assert model == "gpt-4o-mini"
    assert source == "admin override"
    assert os.environ["OPENAI_MENU_MODEL"] == "gpt-4o-mini"
    assert rows["OPENAI_MENU_MODEL"]["model"] == "gpt-4o-mini"
    assert rows["OPENAI_MENU_MODEL"]["source"] == "admin override"


def test_lowest_viable_model_refresh_updates_recommended_mappings(monkeypatch, tmp_path):
    configure_model_files(
        monkeypatch,
        tmp_path,
        ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5"],
    )

    payload = models.refresh_lowest_viable_openai_model_recommendations()
    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    rows = {row["env_var"]: row for row in dashboard["rows"]}

    assert payload["mappings"]["OPENAI_MENU_MODEL"] == "gpt-5.4-mini"
    assert payload["mappings"]["OPENAI_RECIPE_MODEL"] == "gpt-5.4-nano"
    assert rows["OPENAI_MENU_MODEL"]["proposed_model"] == "gpt-5.4-mini"
    assert rows["OPENAI_RECIPE_MODEL"]["proposed_model"] == "gpt-5.4-nano"


def test_unavailable_active_model_stays_visible_with_warning(monkeypatch, tmp_path):
    configure_model_files(monkeypatch, tmp_path, ["gpt-5.5", "gpt-5.5-mini"])
    monkeypatch.setenv("OPENAI_MENU_MODEL", "gpt-4-0613")

    dashboard = models.chatgpt_models_dashboard_for_user(ADMIN_USER)
    menu_row = next(row for row in dashboard["rows"] if row["env_var"] == "OPENAI_MENU_MODEL")

    assert menu_row["model"] == "gpt-4-0613"
    assert menu_row["selected_available"] is False
    assert menu_row["unavailable_warning"] == "⚠ Deprecated or unavailable"
    assert menu_row["proposed_model"] == "gpt-5.5"
    assert "gpt-4-0613" in menu_row["model_choices"]
