import io
from pathlib import Path

from flask import session
from PIL import Image

from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_url_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def seed_signed_in_user(client, user_id="image-user"):
    with client.session_transaction() as test_session:
        test_session["user_id"] = user_id


def configure_image_user(monkeypatch, tmp_path, user_id="image-user"):
    user_data_dir = tmp_path / "user_data"
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", user_data_dir)
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    user_account_service.save_users({
        "users": [{
            "user_id": user_id,
            "email": "image@example.com",
            "username": "image",
            "notification_topic": "topic",
            "ntfy_topic": "topic",
            "account_status": "active",
        }],
    })
    return user_id, user_data_dir


def valid_png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(output, format="PNG")
    return output.getvalue()


def test_prepare_image_bytes_converts_small_non_openai_image(tmp_path):
    image_path = tmp_path / "phone-upload.bmp"
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(image_path, format="BMP")

    image_bytes, mime_type = recipe_extract_service.prepare_image_bytes_for_openai(
        image_path,
        "image/bmp",
    )

    assert mime_type == "image/jpeg"
    assert image_bytes.startswith(b"\xff\xd8")


def test_prepare_image_bytes_normalizes_supported_image_over_threshold(monkeypatch, tmp_path):
    image_path = tmp_path / "phone-upload.png"
    Image.new("RGB", (3, 3), color=(255, 255, 255)).save(image_path, format="PNG")
    monkeypatch.setattr(recipe_extract_service, "NORMALIZE_OPENAI_UPLOAD_IMAGE_BYTES", 1)

    image_bytes, mime_type = recipe_extract_service.prepare_image_bytes_for_openai(
        image_path,
        "image/png",
    )

    assert mime_type == "image/jpeg"
    assert image_bytes.startswith(b"\xff\xd8")


def test_gpt5_models_do_not_support_custom_temperature():
    assert recipe_extract_service.supports_custom_temperature("gpt-5.5") is False
    assert recipe_extract_service.supports_custom_temperature("gpt-5") is False
    assert recipe_extract_service.supports_custom_temperature("gpt-4o-mini") is True


def test_default_models_use_menu_and_vision_gpt55_only(monkeypatch):
    monkeypatch.delenv("OPENAI_RECIPE_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MENU_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_VISION_MODEL", raising=False)

    recipe_model = recipe_extract_service.resolve_openai_model("recipe")
    menu_model = recipe_extract_service.resolve_openai_model("menu")
    vision_model = recipe_extract_service.resolve_openai_model("vision")

    assert recipe_model.model == "gpt-4o-mini"
    assert recipe_model.source == "default:gpt-4o-mini"
    assert menu_model.model == "gpt-5.5"
    assert menu_model.source == "default:gpt-5.5"
    assert vision_model.model == "gpt-5.5"
    assert vision_model.source == "default:gpt-5.5"


def write_uploaded_image(user_data_dir, user_id, filename="meal.png", data=None):
    upload_dir = user_data_dir / user_id / "recipe-extractor" / "data" / "uploads"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / filename
    upload_path.write_bytes(valid_png_bytes() if data is None else data)
    return upload_path


def test_generate_recipe_from_image_commits_estimate(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)

    upload_path = write_uploaded_image(user_data_dir, user_id)

    parsed_recipe = {
        "display_name": "Photo Rice Bowl",
        "source_type": "image",
        "extraction_mode": "image_estimate",
        "ai_inferred": True,
        "ingredients": [
            {"ingredient": "rice", "original_text": "1 cup rice"},
            {"ingredient": "onion", "original_text": "1 onion"},
        ],
        "instructions": ["Cook the rice.", "Top with onion."],
    }

    monkeypatch.setattr(
        recipe_routes,
        "generateRecipeFromImage",
        lambda *args, **kwargs: (parsed_recipe, None),
    )
    monkeypatch.setattr(
        recipe_routes,
        "save_import_cookbook_assignment",
        lambda url, result, cookbook: {"cookbook_id": "test-book"},
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment: {"ok": True, "categories": {}, "status": "updated"},
    )
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", lambda url: None)
    monkeypatch.setattr(
        recipe_routes,
        "schedule_generated_recipe_pdf_creation",
        lambda url, context="media-upload": {"queued": False, "url": url},
    )
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_routes, "sort_ingredients", lambda: None)

    app = create_app()

    with app.test_client() as client:
        seed_signed_in_user(client, user_id)
        response = client.post(
            "/api/generate-recipe-from-image",
            json={
                "uploaded_file_path": str(upload_path),
                "source_type": "image",
                "extraction_mode": "vision",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["source_type"] == "image"
    assert payload["source_type_label"] == "Image"
    assert payload["extraction_mode"] == "image_estimate"
    assert payload["extraction_mode_label"] == "Vision"
    assert payload["recipe_json"]["display_name"] == "Photo Rice Bowl"
    assert payload["recipe_json"]["recipe_title"] == "Photo Rice Bowl"
    assert payload["recipe_json"]["source_url"] == "uploaded://meal.png"
    assert payload["recipe_json"]["cover_image"]["path"] == "data/uploads/meal.png"
    assert payload["recipe_json"]["cover_image"]["source"] == "uploaded_image"
    assert payload["cover_image"]["path"] == "data/uploads/meal.png"
    assert payload["category_status"]["ok"] is True
    assert payload["success"] is True
    assert payload["debug"]["file_exists"] is True
    assert payload["debug"]["file_size"] > 0
    assert payload["debug"]["image_readable"] is True
    assert payload["debug"]["vision_request_sent"] is True
    assert payload["debug"]["vision_response_received"] is True
    assert payload["debug"]["json_parse_success"] is True
    assert payload["debug"]["ingredient_count"] == 2
    assert payload["debug"]["recipe_creation_success"] is True

    with app.test_request_context("/"):
        session["user_id"] = user_id
        assert shopping_list_service.load_items() == ["rice", "onion"]
        assert recipe_url_service.load_recipe_urls() == ["uploaded://meal.png"]
        editor_recipe = recipe_edit_service.load_editable_recipe("uploaded://meal.png")["recipe"]
        assert editor_recipe["source_url"] == "uploaded://meal.png"
        assert editor_recipe["display_name"] == "Photo Rice Bowl"
        assert editor_recipe["recipe_title"] == "Photo Rice Bowl"
        assert editor_recipe["cover_image"]["path"] == "data/uploads/meal.png"
        assert editor_recipe["cover_image"]["source"] == "uploaded_image"
        assert editor_recipe["cover_image"]["src"].startswith("/recipe_cover_image?url=")
        assert [item["ingredient"] for item in editor_recipe["ingredients"]] == ["rice", "onion"]
        assert [item["instruction"] for item in editor_recipe["instructions"]] == [
            "Cook the rice.",
            "Top with onion.",
        ]


def test_generate_recipe_from_image_passes_description_hint(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    upload_path = write_uploaded_image(user_data_dir, user_id, filename="hinted-meal.png")
    captured = {}

    parsed_recipe = {
        "display_name": "Creamy Orange Rice",
        "source_type": "image",
        "extraction_mode": "image_estimate",
        "ai_inferred": True,
        "ingredients": [
            {"ingredient": "rice", "original_text": "1 cup rice"},
            {"ingredient": "peas", "original_text": "1/2 cup peas"},
        ],
        "instructions": ["Simmer the sauce.", "Fold in rice and peas."],
    }

    def fake_generate_from_image(*args, **kwargs):
        captured.update(kwargs)
        return parsed_recipe, None

    monkeypatch.setattr(recipe_routes, "generateRecipeFromImage", fake_generate_from_image)
    monkeypatch.setattr(
        recipe_routes,
        "save_import_cookbook_assignment",
        lambda url, result, cookbook: {"cookbook_id": "test-book"},
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment: {"ok": True, "categories": {}, "status": "updated"},
    )
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", lambda url: None)
    monkeypatch.setattr(
        recipe_routes,
        "schedule_generated_recipe_pdf_creation",
        lambda url, context="media-upload": {"queued": False, "url": url},
    )
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_routes, "sort_ingredients", lambda: None)

    app = create_app()
    description = "creamy orange sauce with peas over rice"

    with app.test_client() as client:
        seed_signed_in_user(client, user_id)
        response = client.post(
            "/api/generate-recipe-from-image",
            json={
                "uploaded_file_path": str(upload_path),
                "source_type": "image",
                "extraction_mode": "vision",
                "photo_description": description,
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert captured["user_description"] == description
    assert payload["extraction_mode"] == "manual_description"
    assert payload["extraction_mode_label"] == "Vision + Description"
    assert "description" in payload["estimation_banner"]
    assert payload["recipe_json"]["manual_description"] == description
    assert payload["recipe_json"]["cover_image"]["path"] == "data/uploads/hinted-meal.png"


def test_generate_recipe_from_image_reports_unreadable_image(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    upload_path = write_uploaded_image(user_data_dir, user_id, data=b"not an image")
    app = create_app()

    with app.test_client() as client:
        seed_signed_in_user(client, user_id)
        response = client.post(
            "/api/generate-recipe-from-image",
            json={
                "uploaded_file_path": str(upload_path),
                "source_type": "image",
                "extraction_mode": "vision",
            },
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error_code"] == "IMAGE_UNREADABLE"
    assert "Uploaded image is not readable" in payload["error_message"]
    assert payload["debug"]["file_exists"] is True
    assert payload["debug"]["file_size"] > 0
    assert payload["debug"]["image_type_supported"] is True
    assert payload["debug"]["image_readable"] is False
    assert payload["debug"]["vision_request_sent"] is False


def test_generate_recipe_from_image_reports_json_parse_failure(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    upload_path = write_uploaded_image(user_data_dir, user_id)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        recipe_extract_service,
        "send_image_prompt_to_openai",
        lambda *args, **kwargs: "not json",
    )
    app = create_app()

    with app.test_client() as client:
        seed_signed_in_user(client, user_id)
        response = client.post(
            "/api/generate-recipe-from-image",
            json={
                "uploaded_file_path": str(upload_path),
                "source_type": "image",
                "extraction_mode": "vision",
            },
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error_code"] == "VISION_RESPONSE_PARSE_FAILED"
    assert "JSON parsing failed" in payload["error_message"]
    assert payload["debug"]["vision_request_sent"] is True
    assert payload["debug"]["vision_response_received"] is True
    assert payload["debug"]["response_length"] == len("not json")
    assert payload["debug"]["json_parse_success"] is False


def test_generate_recipe_from_image_success_opens_editor_after_save():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function submitRecipeMediaVision()")
    end = script.index("async function submitRecipeMediaRetry()")
    block = script[start:end]

    assert 'updateRecipeFileLoadingStep("save", "running", "Saving");' in block
    assert "Saving ingredients and refreshing the shopping list..." in block
    assert "Refreshing recipe and opening the editor..." in block
    assert "await openImportedRecipeEditorAfterMediaImport(data" in block
    assert "photo_description: photoDescription" in block
    assert "Vision + Description" in block
    assert "window.location.reload();" not in block
    assert "setRecipeFileVisionDebug(data && data.debug" in block
    assert "Reason:" in block


def test_image_import_preflight_estimates_before_creating_pdf():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function runImageBasedRecipeImportPreflightForEdit()")
    end = script.index("function buildVisionConnectionErrorMessage")
    block = script[start:end]

    assert "await submitRecipeMediaEstimatePerServing()" in block
    assert block.index("await submitRecipeMediaEstimatePerServing()") < block.index("await createRecipePdfFromMediaImport()")


def test_create_recipe_pdf_auto_estimates_uploaded_recipe(monkeypatch, tmp_path):
    user_id, _user_data_dir = configure_image_user(monkeypatch, tmp_path)
    app = create_app()
    recipe_url = "uploaded://meal.png"
    recipe_payload = {
        "source_url": recipe_url,
        "display_name": "Photo Rice Bowl",
        "recipe_title": "Photo Rice Bowl",
        "ingredients": [
            {"ingredient": "rice", "original_text": "1 cup rice"},
        ],
        "instructions": [
            {"instruction": "Cook the rice."},
        ],
    }

    monkeypatch.setattr(
        recipe_routes,
        "estimate_recipe_nutrition",
        lambda recipe: {
            "ok": True,
            "nutrition": [
                {"key": "serving_basis", "value": "per serving"},
                {"key": "calories", "value": "250 kcal"},
            ],
        },
    )
    monkeypatch.setattr(
        recipe_routes,
        "create_editable_recipe_pdf",
        lambda url: {"ok": True, "generated_cloudflare_pdf_url": "https://example.test/recipe.pdf"},
    )

    with app.test_request_context("/"):
        session["user_id"] = user_id
        save_result = recipe_edit_service.save_editable_recipe(recipe_url, recipe_payload)
        assert save_result["ok"] is True

        result = recipe_routes.create_recipe_pdf_from_url(recipe_url)
        saved_recipe = recipe_edit_service.load_editable_recipe(recipe_url)["recipe"]

    assert result["ok"] is True
    assert saved_recipe["nutrition"][0] == {"key": "serving_basis", "value": "per serving"}
    assert saved_recipe["nutrition"][1] == {"key": "calories", "value": "250 kcal"}


def test_image_estimate_upload_success_opens_editor_after_save():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function submitRecipeMediaUpload(")
    end = script.index("function recipeFileManualDescriptionValue()")
    block = script[start:end]

    assert "const isImageEstimate" in block
    assert "if (isImageEstimate)" in block
    assert "await openImportedRecipeEditorAfterMediaImport(data" in block
    assert "Refreshing recipe and opening the editor..." in block
    assert "window.location.reload();" in block


def test_media_import_editor_helper_refreshes_markup_then_opens_recipe():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function openImportedRecipeEditorAfterMediaImport")
    end = script.index("async function submitRecipeMediaVision()")
    block = script[start:end]

    assert "data.source_url || data.url" in block
    assert "recipeJson.source_url" in block
    assert "await refreshStoreMarkup({ requireRecipeLog: true, cacheBust: true });" in block
    assert "hideRecipeFileLoadingOverlay();" in block
    assert "await openRecipeEditor({ dataset: { recipeUrl } });" in block


def test_generate_recipe_from_image_debug_panel_has_requested_sections():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")

    assert "recipeFileVisionDebugPanel" in script
    assert "View Debug Details" in script
    assert "Vision Request" in script
    assert "Vision Response" in script
    assert "Recipe JSON" in script
    assert "Error Details" in script
    assert "Image Uploaded" in script
    assert "Vision Request Sent" in script
    assert "Vision Response Received" in script
    assert "Recipe JSON Parsed" in script
    assert "Recipe Created" in script
