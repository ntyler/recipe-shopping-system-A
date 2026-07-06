import io
import json
from pathlib import Path

from flask import session
from PIL import Image
from werkzeug.datastructures import FileStorage

from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import job_service
from PushShoppingList.services import openai_model_service
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


def test_default_models_use_menu_and_vision_gpt55_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        openai_model_service,
        "MODEL_OVERRIDES_FILE",
        tmp_path / "openai_model_overrides.json",
    )
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


def test_equipment_image_prompt_uses_equipment_title_not_recipe_ingredients():
    prompt = recipe_edit_service.build_recipe_equipment_image_prompt(
        recipe_title="Papa Potatoe a la Huancaina",
        servings="2",
        ingredients="- potato\n- crema\n- lime",
        equipment_item_number=2,
        equipment_item="blender or food processor",
    )
    lower_prompt = prompt.lower()

    assert "blender or food processor" in lower_prompt
    assert "single obvious main subject" in lower_prompt
    assert "match it literally" in lower_prompt
    assert "plain seamless studio background" in lower_prompt
    assert "plain unlabeled object surface" in lower_prompt
    assert "not a kitchen" in lower_prompt
    assert "room interiors" in lower_prompt
    assert "recipe ingredients" not in lower_prompt
    assert "chopped food" not in lower_prompt
    assert "prepared food" not in lower_prompt
    assert "papa" not in lower_prompt
    assert "potato" not in lower_prompt
    assert "crema" not in lower_prompt
    assert "lime" not in lower_prompt


def test_ollama_equipment_prompt_request_omits_recipe_ingredient_context():
    base_prompt = recipe_edit_service.build_recipe_equipment_image_prompt(
        recipe_title="Papa Potatoe a la Huancaina",
        servings="2",
        ingredients="- potato\n- crema\n- lime",
        equipment_item_number=3,
        equipment_item="medium saucepan",
    )
    request = recipe_edit_service.build_ollama_recipe_image_prompt_request(
        {
            "recipe_title": "Papa Potatoe a la Huancaina",
            "ingredients": [
                {"ingredient": "potato"},
                {"ingredient": "crema"},
                {"ingredient": "lime"},
            ],
        },
        "Papa Potatoe a la Huancaina",
        base_prompt,
        image_purpose="recipe equipment item image",
    )
    lower_request = request.lower()

    assert "medium saucepan" in lower_request
    assert "image context" in lower_request
    assert "single obvious main subject" in lower_request
    assert "isolated, empty, clean equipment object" in lower_request
    assert "not a room" in lower_request
    assert "real-estate" in lower_request
    assert "recipe context" not in lower_request
    assert "preserve the specific recipe" not in lower_request
    assert "papa" not in lower_request
    assert "potato" not in lower_request
    assert "crema" not in lower_request
    assert "lime" not in lower_request


def test_equipment_prompt_finalizer_blocks_kitchen_interior_drift_for_generic_alternatives():
    base_prompt = recipe_edit_service.build_recipe_equipment_image_prompt(
        recipe_title="Papa Potatoe a la Huancaina",
        servings="2",
        ingredients="- potato\n- crema\n- lime",
        equipment_item_number=2,
        equipment_item="blender or immersion blender",
    )
    polished_prompt = (
        "A bright modern kitchen interior with white cabinets, a sink, windows, "
        "and a large island countertop. Soft product lighting and sharp focus."
    )

    final_prompt = recipe_edit_service.finalize_equipment_image_prompt(
        base_prompt,
        polished_prompt,
    ).lower()

    assert "blender or immersion blender" in final_prompt
    assert "single isolated product reference photo" in final_prompt
    assert "choose exactly one option" in final_prompt
    assert "plain seamless light gray studio background" in final_prompt
    assert "soft product lighting" in final_prompt
    assert "kitchen interior" not in final_prompt
    assert "cabinets" not in final_prompt
    assert "sink" not in final_prompt
    assert "window" not in final_prompt
    assert "island" not in final_prompt
    assert "countertop" not in final_prompt
    assert "potato" not in final_prompt
    assert "crema" not in final_prompt
    assert "lime" not in final_prompt


def test_equipment_prompt_finalizer_handles_required_equipment_pair():
    base_prompt = recipe_edit_service.build_recipe_equipment_image_prompt(
        recipe_title="Smoothie Prep",
        servings="2",
        ingredients="- banana\n- milk",
        equipment_item_number=1,
        equipment_item="kitchen equipment: blender and food processor",
    )

    final_prompt = recipe_edit_service.finalize_equipment_image_prompt(base_prompt).lower()

    assert "blender and food processor" in final_prompt
    assert "show all named items side by side" in final_prompt
    assert "choose exactly one option" not in final_prompt
    assert "kitchen equipment" not in final_prompt
    assert "kitchen interior" not in final_prompt
    assert "banana" not in final_prompt
    assert "milk" not in final_prompt


def test_equipment_prompt_finalizer_treats_blender_or_food_processor_as_pair():
    base_prompt = recipe_edit_service.build_recipe_equipment_image_prompt(
        recipe_title="Smoothie Prep",
        servings="2",
        ingredients="- banana\n- milk",
        equipment_item_number=1,
        equipment_item="blender or food processor",
    )

    final_prompt = recipe_edit_service.finalize_equipment_image_prompt(base_prompt).lower()

    assert "blender and food processor" in final_prompt
    assert "show all named items side by side" in final_prompt
    assert "choose exactly one option" not in final_prompt
    assert "blender or food processor" not in final_prompt
    assert "banana" not in final_prompt
    assert "milk" not in final_prompt


def test_comfyui_equipment_workflow_uses_food_negative_prompt(monkeypatch):
    monkeypatch.delenv("COMFYUI_NEGATIVE_PROMPT", raising=False)
    monkeypatch.delenv("COMFYUI_EQUIPMENT_NEGATIVE_PROMPT", raising=False)

    workflow = recipe_edit_service.build_default_comfyui_title_workflow(
        "single isolated product reference photo of one clean empty medium saucepan on a plain studio background",
        "local-model.safetensors",
        image_purpose="recipe equipment item image",
    )
    positive_prompt = workflow["6"]["inputs"]["text"].lower()
    negative_prompt = workflow["7"]["inputs"]["text"].lower()

    assert workflow["9"]["inputs"]["filename_prefix"] == "recipe_equipment"
    assert "medium saucepan" in positive_prompt
    assert "kitchen" not in positive_prompt
    assert "potatoes" not in positive_prompt
    assert "food" in negative_prompt
    assert "potatoes" in negative_prompt
    assert "prepared food" in negative_prompt
    assert "liquid" in negative_prompt
    assert "kitchen interior" in negative_prompt
    assert "cabinets" in negative_prompt
    assert "real estate photo" in negative_prompt
    assert "collage" in negative_prompt


def test_custom_comfyui_workflow_patches_recipe_prompts(monkeypatch, tmp_path):
    workflow_path = tmp_path / "equipment_api_workflow.json"
    workflow_path.write_text(
        json.dumps({
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": 42,
                    "steps": 8,
                    "cfg": 1,
                    "sampler_name": "res_multistep",
                    "scheduler": "simple",
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "5": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {
                    "width": 512,
                    "height": 512,
                    "batch_size": 1,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "placeholder positive prompt",
                    "clip": ["4", 1],
                },
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "low quality, bad anatomy",
                    "clip": ["4", 1],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["9", 0],
                },
            },
            "9": {
                "class_type": "VAELoader",
                "inputs": {
                    "vae_name": "ae.safetensors",
                },
            },
            "10": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["8", 0],
                },
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("COMFYUI_WORKFLOW_PATH", str(workflow_path))
    monkeypatch.setenv("COMFYUI_IMAGE_WIDTH", "768")
    monkeypatch.setenv("COMFYUI_IMAGE_HEIGHT", "768")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_IMAGE_WIDTH", "512")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_IMAGE_HEIGHT", "512")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_STEPS", "12")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_CFG", "6")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_SAMPLER", "euler")
    monkeypatch.setenv("COMFYUI_EQUIPMENT_SCHEDULER", "normal")

    title_workflow = recipe_edit_service.build_comfyui_workflow(
        "realistic cookbook photo of tomato soup",
        "recipe title image",
        "http://127.0.0.1:8189",
        1,
    )

    workflow = recipe_edit_service.build_comfyui_workflow(
        "single isolated product reference photo of one clean empty blender",
        "recipe equipment item image",
        "http://127.0.0.1:8189",
        1,
    )

    assert title_workflow["5"]["inputs"]["width"] == 768
    assert title_workflow["5"]["inputs"]["height"] == 768
    assert workflow["6"]["inputs"]["text"] == "single isolated product reference photo of one clean empty blender"
    assert workflow["3"]["inputs"]["seed"] != 42
    assert workflow["3"]["inputs"]["steps"] == 12
    assert workflow["3"]["inputs"]["cfg"] == 6
    assert workflow["3"]["inputs"]["sampler_name"] == "euler"
    assert workflow["3"]["inputs"]["scheduler"] == "normal"
    assert workflow["5"]["inputs"]["width"] == 512
    assert workflow["5"]["inputs"]["height"] == 512
    assert workflow["10"]["inputs"]["filename_prefix"] == "recipe_equipment"
    negative_prompt = workflow["7"]["inputs"]["text"].lower()
    assert "food" in negative_prompt
    assert "kitchen interior" in negative_prompt


def write_uploaded_image(user_data_dir, user_id, filename="meal.png", data=None):
    upload_dir = user_data_dir / user_id / "recipe-extractor" / "data" / "uploads"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / filename
    upload_path.write_bytes(valid_png_bytes() if data is None else data)
    return upload_path


def test_generate_recipe_from_image_commits_estimate(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

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


def test_image_upload_result_exposes_recipe_json_for_background_job_modal(monkeypatch, tmp_path):
    monkeypatch.setattr(recipe_extract_service, "UPLOAD_FOLDER", tmp_path / "uploads")
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path / "raw")
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", tmp_path / "output")
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", tmp_path / "pdf")
    monkeypatch.setattr(recipe_extract_service, "EXTRACTOR_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "archive_uploaded_recipe_pdf", lambda *args, **kwargs: None)
    recipe_extract_service.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    recipe_extract_service.RAW_FOLDER.mkdir(parents=True, exist_ok=True)
    recipe_extract_service.OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    recipe_extract_service.PDF_FOLDER.mkdir(parents=True, exist_ok=True)

    parsed_recipe = {
        "display_name": "Photo Soup",
        "recipe_title": "Photo Soup",
        "ingredients": [
            {"ingredient": "beef broth", "original_text": "4 cups beef broth"},
            {"ingredient": "green onion", "original_text": "2 green onions"},
        ],
        "instructions": ["Simmer and serve."],
    }
    monkeypatch.setattr(
        recipe_extract_service,
        "generateRecipeFromImage",
        lambda *args, **kwargs: (parsed_recipe, None),
    )

    result = recipe_extract_service.extract_recipe_from_upload(
        FileStorage(
            stream=io.BytesIO(valid_png_bytes()),
            filename="meal.png",
            content_type="image/png",
        ),
        upload_mode="vision",
    )

    assert result["ok"] is True
    assert result["recipe_json"]["ingredients"] == result["raw"]["ingredients"]
    assert len(result["recipe_json"]["ingredients"]) == 2


def test_generate_recipe_cover_image_saves_ai_cover(monkeypatch, tmp_path):
    url = "https://example.com/spicy-noodles"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Spicy Noodles",
        "servings": "2",
        "ingredients": [
            {"quantity": "8", "unit": "oz", "ingredient": "noodles"},
            {"quantity": "2", "unit": "tbsp", "ingredient": "chili crisp"},
        ],
    }
    saved = {}
    updated = {}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(recipe_edit_service, "COVER_IMAGE_UPLOAD_FOLDER", tmp_path / "recipe_covers")
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(recipe_edit_service, "request_recipe_title_image_bytes", lambda prompt: b"generated-png")

    def fake_extract(upload_path, mime_type, filename, recipe_url, fallback_alt=""):
        assert upload_path.read_bytes() == b"generated-png"
        assert mime_type == "image/png"
        assert recipe_url == url
        return {
            "path": "data/uploads/recipe_covers/generated.png",
            "mime_type": mime_type,
            "alt": fallback_alt,
            "source": "uploaded_image",
        }

    def fake_save(recipe_url, data):
        saved["url"] = recipe_url
        saved["data"] = data.copy()

    def fake_update(recipe_url, quantity, data):
        updated["url"] = recipe_url
        updated["quantity"] = quantity
        updated["cover_image"] = data.get("cover_image", {}).copy()

    monkeypatch.setattr(recipe_edit_service, "extract_recipe_cover_image_from_upload", fake_extract)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", fake_save)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", fake_update)
    monkeypatch.setattr(
        recipe_edit_service,
        "load_editable_recipe",
        lambda recipe_url: {"recipe": {"cover_image": saved["data"]["cover_image"]}},
    )

    result = recipe_edit_service.generate_recipe_cover_image({"url": url})

    assert result["ok"] is True
    assert saved["url"] == url
    assert saved["data"]["cover_image"]["source"] == "ai_generated_image"
    assert saved["data"]["cover_image_generated_at"]
    assert updated["url"] == url
    assert updated["cover_image"]["source"] == "ai_generated_image"
    assert result["cover_image"]["path"] == "data/uploads/recipe_covers/generated.png"


def test_generate_recipe_cover_image_comfyui_saves_local_cover_without_openai(monkeypatch, tmp_path):
    url = "https://example.com/local-title-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Local Tomato Soup",
        "description": "A bright tomato soup with basil.",
        "cuisine_tags": ["Italian"],
        "ingredients": [
            {"quantity": "2", "unit": "cups", "ingredient": "tomatoes"},
            {"quantity": "4", "unit": "leaves", "ingredient": "basil"},
        ],
    }
    saved = {}
    updated = {}
    prompt_calls = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(recipe_edit_service, "COVER_IMAGE_UPLOAD_FOLDER", tmp_path / "recipe_covers")
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_recipe_title_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("OpenAI image generation should not run")),
    )

    def fake_enhance(data, title, prompt, required=False):
        prompt_calls["required"] = required
        prompt_calls["title"] = title
        return f"polished {title}"

    def fake_comfyui(prompt):
        prompt_calls["comfyui_prompt"] = prompt
        return b"local-png"

    def fake_extract(upload_path, mime_type, filename, recipe_url, fallback_alt=""):
        assert upload_path.read_bytes() == b"local-png"
        assert mime_type == "image/png"
        assert recipe_url == url
        return {
            "path": "data/uploads/recipe_covers/local.png",
            "mime_type": mime_type,
            "alt": fallback_alt,
            "source": "uploaded_image",
        }

    def fake_save(recipe_url, data):
        saved["url"] = recipe_url
        saved["data"] = data.copy()

    def fake_update(recipe_url, quantity, data):
        updated["url"] = recipe_url
        updated["cover_image"] = data.get("cover_image", {}).copy()

    monkeypatch.setattr(recipe_edit_service, "enhance_recipe_title_image_prompt_with_ollama", fake_enhance)
    monkeypatch.setattr(recipe_edit_service, "ensure_comfyui_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "request_comfyui_title_image_bytes", fake_comfyui)
    monkeypatch.setattr(recipe_edit_service, "extract_recipe_cover_image_from_upload", fake_extract)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", fake_save)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", fake_update)
    monkeypatch.setattr(
        recipe_edit_service,
        "load_editable_recipe",
        lambda recipe_url: {"recipe": {"cover_image": saved["data"]["cover_image"]}},
    )

    result = recipe_edit_service.generate_recipe_cover_image({"url": url})

    assert result["ok"] is True
    assert prompt_calls["required"] is False
    assert prompt_calls["title"] == "Local Tomato Soup"
    assert prompt_calls["comfyui_prompt"] == "polished Local Tomato Soup"
    assert saved["url"] == url
    assert saved["data"]["cover_image"]["source"] == "local_comfyui_image"
    assert saved["data"]["cover_image"]["provider"] == "comfyui"
    assert saved["data"]["cover_image_provider"] == "comfyui"
    assert updated["url"] == url
    assert updated["cover_image"]["source"] == "local_comfyui_image"
    assert result["cover_image"]["path"] == "data/uploads/recipe_covers/local.png"


def test_generate_recipe_cover_image_payload_provider_can_choose_openai(monkeypatch):
    url = "https://example.com/chosen-openai-title-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Chosen OpenAI Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
    }
    calls = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_comfyui_title_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("ComfyUI should not run when the payload chooses OpenAI")),
    )

    def fake_openai_title_image(prompt):
        calls["openai_prompt"] = prompt
        return b"openai-png"

    def fake_save(recipe_source_url, data, image_bytes, fallback_alt, image_source, provider, fallback_used=False):
        calls["saved"] = {
            "url": recipe_source_url,
            "image_bytes": image_bytes,
            "image_source": image_source,
            "provider": provider,
            "fallback_used": fallback_used,
        }
        return {
            "ok": True,
            "url": recipe_source_url,
            "cover_image": {
                "path": "data/uploads/recipe_covers/chosen-openai.png",
                "source": image_source,
                "provider": provider,
            },
            "provider": provider,
            "fallback_used": bool(fallback_used),
        }

    monkeypatch.setattr(recipe_edit_service, "request_recipe_title_image_bytes", fake_openai_title_image)
    monkeypatch.setattr(recipe_edit_service, "save_generated_recipe_cover_image", fake_save)

    result = recipe_edit_service.generate_recipe_cover_image({
        "url": url,
        "image_provider": "chatgpt",
    })

    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert result["fallback_used"] is False
    assert calls["openai_prompt"]
    assert calls["saved"]["image_bytes"] == b"openai-png"
    assert calls["saved"]["image_source"] == "ai_generated_image"
    assert calls["saved"]["provider"] == "openai"


def test_generate_recipe_cover_image_comfyui_failure_does_not_fallback_without_opt_in(monkeypatch):
    url = "https://example.com/offline-comfyui"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Offline ComfyUI Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
    }

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(
        recipe_edit_service,
        "enhance_recipe_title_image_prompt_with_ollama",
        lambda data, title, prompt, required=False: prompt,
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "request_comfyui_title_image_bytes",
        lambda prompt: (_ for _ in ()).throw(
            recipe_edit_service.TitleImageGenerationError(
                "comfyui_connection_failed",
                recipe_edit_service.LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_UNAVAILABLE",
                local_unavailable=True,
            )
        ),
    )
    monkeypatch.setattr(recipe_edit_service, "ensure_comfyui_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_recipe_title_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("OpenAI image generation should not run")),
    )

    result = recipe_edit_service.generate_recipe_cover_image({"url": url})

    assert result == {
        "ok": False,
        "error": "Local image generation is unavailable. Start ComfyUI and try again.",
        "error_code": "COMFYUI_UNAVAILABLE",
        "provider": "comfyui",
        "local_generation_unavailable": True,
    }


def test_comfyui_checkpoint_lookup_autostarts_local_service(monkeypatch):
    calls = []
    launched = {}

    class FakeResponse:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, timeout):
        calls.append(url)
        if url.endswith("/object_info/CheckpointLoaderSimple") and calls.count(url) == 1:
            raise recipe_edit_service.requests.ConnectionError("refused")
        if url.endswith("/system_stats"):
            if "command" not in launched:
                raise recipe_edit_service.requests.ConnectionError("refused")
            return FakeResponse({"ok": True})
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return FakeResponse({
                "CheckpointLoaderSimple": {
                    "input": {
                        "required": {
                            "ckpt_name": [["local-model.safetensors"]],
                        },
                    },
                },
            })
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_popen(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("COMFYUI_START_COMMAND", r"D:\GitHub\ComfyUI\start_comfyui_local.bat")
    monkeypatch.setenv("COMFYUI_START_WAIT_SECONDS", "1")
    monkeypatch.setattr(recipe_edit_service, "COMFYUI_START_ATTEMPTED", False)
    monkeypatch.setattr(recipe_edit_service.requests, "get", fake_get)
    monkeypatch.setattr(recipe_edit_service.subprocess, "Popen", fake_popen)

    checkpoint = recipe_edit_service.comfyui_checkpoint_name("http://127.0.0.1:8188", 1)

    assert checkpoint == "local-model.safetensors"
    assert launched["command"] == r"D:\GitHub\ComfyUI\start_comfyui_local.bat"
    assert launched["kwargs"]["shell"] is True
    assert calls.count("http://127.0.0.1:8188/object_info/CheckpointLoaderSimple") == 2


def test_comfyui_preflight_uses_short_timeout(monkeypatch):
    calls = {}

    def fake_get(url, timeout):
        calls["url"] = url
        calls["timeout"] = timeout
        raise recipe_edit_service.requests.Timeout("slow local check")

    monkeypatch.setenv("COMFYUI_PREFLIGHT_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setattr(recipe_edit_service.requests, "get", fake_get)

    try:
        recipe_edit_service.ensure_comfyui_available("http://127.0.0.1:8188")
    except recipe_edit_service.TitleImageGenerationError as exc:
        error = exc
    else:
        raise AssertionError("Expected unavailable ComfyUI preflight to raise")

    assert error.error_code == "COMFYUI_TIMEOUT"
    assert error.local_unavailable is True
    assert calls["url"] == "http://127.0.0.1:8188/system_stats"
    assert calls["timeout"] == 2.5


def test_generate_recipe_equipment_image_comfyui_unavailable_skips_ollama_polish(monkeypatch):
    url = "https://example.com/offline-equipment-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Offline Equipment Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
        "equipment": [{"equipment": "blender and food processor"}],
    }
    progress = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)

    def fake_start(kind, recipe_url, target, message=None, image_prompt=""):
        progress["started"] = {
            "kind": kind,
            "url": recipe_url,
            "target": target,
            "message": message,
            "image_prompt": image_prompt,
        }

    def fake_finish(kind, recipe_url, target, ok=True, image_url="", generated_at="", error="", image_prompt=""):
        progress["finished"] = {
            "kind": kind,
            "url": recipe_url,
            "target": target,
            "ok": ok,
            "error": error,
            "image_prompt": image_prompt,
        }

    def fake_unavailable(*args, **kwargs):
        raise recipe_edit_service.TitleImageGenerationError(
            "comfyui_preflight_connection_failed",
            recipe_edit_service.LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
            error_code="COMFYUI_UNAVAILABLE",
            local_unavailable=True,
        )

    monkeypatch.setattr(recipe_edit_service, "start_recipe_image_progress", fake_start)
    monkeypatch.setattr(recipe_edit_service, "finish_recipe_image_progress", fake_finish)
    monkeypatch.setattr(recipe_edit_service, "ensure_comfyui_available", fake_unavailable)
    monkeypatch.setattr(
        recipe_edit_service,
        "enhance_recipe_image_prompt_with_ollama",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Ollama should not run when ComfyUI is unavailable")),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "request_comfyui_image_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ComfyUI image request should not run after failed preflight")),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "request_recipe_step_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("OpenAI image generation should not run")),
    )

    result = recipe_edit_service.generate_recipe_equipment_image({
        "url": url,
        "equipment_index": 1,
    })

    expected_prompt = recipe_edit_service.finalize_equipment_image_prompt(
        recipe_edit_service.build_recipe_equipment_image_prompt(
            recipe_title="Offline Equipment Soup",
            servings="",
            ingredients="- tomatoes",
            equipment_item_number=1,
            equipment_item="blender and food processor",
        )
    )

    assert result == {
        "ok": False,
        "error": recipe_edit_service.LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
        "error_code": "COMFYUI_UNAVAILABLE",
        "provider": "comfyui",
        "local_generation_unavailable": True,
        "image_prompt": expected_prompt,
    }
    assert progress["started"]["image_prompt"] == expected_prompt
    assert progress["finished"]["ok"] is False
    assert progress["finished"]["image_prompt"] == expected_prompt


def test_generate_recipe_equipment_image_comfyui_uses_local_provider_without_openai(monkeypatch, tmp_path):
    url = "https://example.com/local-equipment-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Local Tomato Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
        "equipment": [{"equipment": "large pot"}],
    }
    saved = {}
    prompt_calls = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(recipe_edit_service, "STEP_IMAGE_FOLDER", tmp_path / "recipe_steps")
    monkeypatch.setattr(recipe_edit_service, "ensure_webp_variants", lambda image_path: None)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_recipe_step_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("OpenAI image generation should not run")),
    )
    monkeypatch.setattr(recipe_edit_service, "start_recipe_image_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "finish_recipe_image_progress", lambda *args, **kwargs: None)

    def fake_enhance(data, title, prompt, required=False, image_purpose=""):
        prompt_calls["required"] = required
        prompt_calls["title"] = title
        prompt_calls["image_purpose"] = image_purpose
        return f"polished {image_purpose}"

    def fake_comfyui(prompt, image_purpose=""):
        prompt_calls["comfyui_prompt"] = prompt
        prompt_calls["comfyui_image_purpose"] = image_purpose
        return b"local-equipment-png"

    def fake_save(recipe_url, data):
        saved["url"] = recipe_url
        saved["data"] = data.copy()

    monkeypatch.setattr(recipe_edit_service, "enhance_recipe_image_prompt_with_ollama", fake_enhance)
    monkeypatch.setattr(recipe_edit_service, "ensure_comfyui_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "request_comfyui_image_bytes", fake_comfyui)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", fake_save)

    result = recipe_edit_service.generate_recipe_equipment_image({
        "url": url,
        "equipment_index": 1,
    })

    assert result["ok"] is True
    assert result["provider"] == "comfyui"
    assert result["fallback_used"] is False
    assert prompt_calls["required"] is False
    assert prompt_calls["title"] == "Local Tomato Soup"
    assert prompt_calls["image_purpose"] == "recipe equipment item image"
    assert prompt_calls["comfyui_prompt"] == "polished recipe equipment item image"
    assert prompt_calls["comfyui_image_purpose"] == "recipe equipment item image"
    assert result["image_prompt"] == "polished recipe equipment item image"
    assert saved["url"] == url
    assert saved["data"]["equipment"][0]["equipment_image_url"] == result["equipment_image_url"]
    assert saved["data"]["equipment"][0]["equipment_image_prompt"] == result["image_prompt"]
    image_filename = result["equipment_image_url"].rsplit("/", 1)[-1]
    assert (tmp_path / "recipe_steps" / image_filename).read_bytes() == b"local-equipment-png"


def test_generate_recipe_equipment_image_payload_provider_can_choose_openai(monkeypatch, tmp_path):
    url = "https://example.com/chosen-openai-equipment-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Chosen Equipment Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
        "equipment": [{"equipment": "blender or food processor"}],
    }
    calls = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_edit_service, "STEP_IMAGE_FOLDER", tmp_path / "recipe_steps")
    monkeypatch.setattr(recipe_edit_service, "ensure_webp_variants", lambda image_path: None)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", lambda recipe_url, data: calls.setdefault("saved", data.copy()))
    monkeypatch.setattr(recipe_edit_service, "start_recipe_image_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "finish_recipe_image_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_comfyui_image_bytes",
        lambda prompt, image_purpose="": (_ for _ in ()).throw(AssertionError("ComfyUI should not run when the payload chooses OpenAI")),
    )

    def fake_openai_detail_image(prompt):
        calls["openai_prompt"] = prompt
        return b"openai-equipment-png"

    monkeypatch.setattr(recipe_edit_service, "request_recipe_step_image_bytes", fake_openai_detail_image)

    result = recipe_edit_service.generate_recipe_equipment_image({
        "url": url,
        "equipment_index": 1,
        "image_provider": "openai",
    })

    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert result["fallback_used"] is False
    openai_prompt = calls["openai_prompt"].lower()
    assert "single isolated product reference photo" in openai_prompt
    assert "blender and food processor" in openai_prompt
    assert "show all named items side by side" in openai_prompt
    assert "blender or food processor" not in openai_prompt
    assert "choose exactly one option" not in openai_prompt
    assert "plain seamless light gray studio background" in openai_prompt
    assert "kitchen" not in openai_prompt
    assert "cabinet" not in openai_prompt
    assert "countertop" not in openai_prompt
    assert result["image_prompt"] == calls["openai_prompt"]
    assert calls["saved"]["equipment"][0]["equipment_image_url"] == result["equipment_image_url"]
    assert calls["saved"]["equipment"][0]["equipment_image_prompt"] == result["image_prompt"]
    image_filename = result["equipment_image_url"].rsplit("/", 1)[-1]
    assert (tmp_path / "recipe_steps" / image_filename).read_bytes() == b"openai-equipment-png"


def test_remove_recipe_equipment_image_clears_saved_fields(monkeypatch):
    url = "https://example.com/remove-equipment-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Remove Equipment Image",
        "equipment": [{
            "equipment": "blender or food processor",
            "equipment_image_url": "/static/generated/recipe_steps/old-equipment.png",
            "equipment_image_generated_at": "2026-07-06T12:00:00+00:00",
            "equipment_image_prompt": "old prompt",
        }],
    }
    saved = {}

    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", lambda recipe_url, data: saved.update({"url": recipe_url, "data": data.copy()}))

    result = recipe_edit_service.remove_recipe_detail_image(url, "equipment", 1)

    assert result == {
        "ok": True,
        "url": url,
        "kind": "equipment",
        "equipment_index": 1,
        "equipment_image_url": "",
        "equipment_image_generated_at": "",
        "image_url": "",
        "generated_at": "",
    }
    assert saved["url"] == url
    assert saved["data"]["equipment"][0]["equipment"] == "blender or food processor"
    assert saved["data"]["equipment"][0]["equipment_image_url"] == ""
    assert saved["data"]["equipment"][0]["equipment_image_generated_at"] == ""
    assert saved["data"]["equipment"][0]["equipment_image_prompt"] == ""


def test_remove_recipe_step_image_clears_saved_fields(monkeypatch):
    url = "https://example.com/remove-step-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Remove Step Image",
        "instructions": [{
            "step_number": 2,
            "instruction": "Blend until smooth.",
            "step_image_url": "/static/generated/recipe_steps/old-step.png",
            "step_image_generated_at": "2026-07-06T12:00:00+00:00",
        }],
    }
    saved = {}

    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", lambda recipe_url, data: saved.update({"url": recipe_url, "data": data.copy()}))

    result = recipe_edit_service.remove_recipe_detail_image(url, "step", 2)

    assert result == {
        "ok": True,
        "url": url,
        "kind": "step",
        "step_number": 2,
        "step_image_url": "",
        "step_image_generated_at": "",
        "image_url": "",
        "generated_at": "",
    }
    assert saved["url"] == url
    assert saved["data"]["instructions"][0]["instruction"] == "Blend until smooth."
    assert saved["data"]["instructions"][0]["step_image_url"] == ""
    assert saved["data"]["instructions"][0]["step_image_generated_at"] == ""


def test_remove_recipe_detail_image_route_calls_service(monkeypatch):
    app = create_app()
    captured = {}

    def fake_remove(url, kind, target):
        captured["url"] = url
        captured["kind"] = kind
        captured["target"] = target
        return {
            "ok": True,
            "url": url,
            "kind": kind,
            "equipment_index": 2,
            "equipment_image_url": "",
            "image_url": "",
        }

    monkeypatch.setattr(recipe_routes, "remove_recipe_detail_image", fake_remove)

    with app.test_client() as client:
        seed_signed_in_user(client)
        response = client.delete(
            "/api/recipe_detail_image",
            json={
                "url": "https://example.com/remove-route",
                "kind": "equipment",
                "equipment_index": 2,
            },
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["equipment_image_url"] == ""
    assert captured == {
        "url": "https://example.com/remove-route",
        "kind": "equipment",
        "target": 2,
    }


def test_generate_recipe_step_image_comfyui_failure_does_not_fallback_without_opt_in(monkeypatch):
    url = "https://example.com/offline-step-comfyui"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Offline Step Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
        "instructions": [{"step_number": 1, "instruction": "Simmer the soup."}],
    }
    finished = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "comfyui")
    monkeypatch.setenv("TITLE_IMAGE_FALLBACK_PROVIDER", "none")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(
        recipe_edit_service,
        "enhance_recipe_image_prompt_with_ollama",
        lambda data, title, prompt, required=False, image_purpose="": prompt,
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "request_comfyui_image_bytes",
        lambda prompt, image_purpose="": (_ for _ in ()).throw(
            recipe_edit_service.TitleImageGenerationError(
                "comfyui_connection_failed",
                recipe_edit_service.LOCAL_TITLE_IMAGE_UNAVAILABLE_MESSAGE,
                error_code="COMFYUI_UNAVAILABLE",
                local_unavailable=True,
            )
        ),
    )
    monkeypatch.setattr(recipe_edit_service, "ensure_comfyui_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        recipe_edit_service,
        "request_recipe_step_image_bytes",
        lambda prompt: (_ for _ in ()).throw(AssertionError("OpenAI image generation should not run")),
    )
    monkeypatch.setattr(recipe_edit_service, "start_recipe_image_progress", lambda *args, **kwargs: None)

    def fake_finish(kind, recipe_url, target, ok=True, image_url="", generated_at="", error="", image_prompt=""):
        finished["kind"] = kind
        finished["url"] = recipe_url
        finished["target"] = target
        finished["ok"] = ok
        finished["error"] = error
        finished["image_prompt"] = image_prompt

    monkeypatch.setattr(recipe_edit_service, "finish_recipe_image_progress", fake_finish)

    result = recipe_edit_service.generate_recipe_step_image({
        "url": url,
        "step_number": 1,
    })

    assert result == {
        "ok": False,
        "error": "Local image generation is unavailable. Start ComfyUI and try again.",
        "error_code": "COMFYUI_UNAVAILABLE",
        "provider": "comfyui",
        "local_generation_unavailable": True,
        "image_prompt": recipe_edit_service.build_recipe_step_image_prompt(
            recipe_title="Offline Step Soup",
            servings="",
            ingredients="- tomatoes",
            equipment="",
            step_number=1,
            instruction_step="Simmer the soup.",
        ),
    }
    assert finished["ok"] is False
    assert finished["error"] == "Local image generation is unavailable. Start ComfyUI and try again."
    assert finished["image_prompt"] == result["image_prompt"]


def test_generate_recipe_step_image_ollama_prompt_only_uses_existing_image_provider(monkeypatch, tmp_path):
    url = "https://example.com/ollama-step-image"
    recipe_data = {
        "source_url": url,
        "recipe_title": "Prompted Step Soup",
        "ingredients": [{"ingredient": "tomatoes"}],
        "instructions": [{"step_number": 1, "instruction": "Blend the soup."}],
    }
    prompt_calls = {}

    monkeypatch.setenv("TITLE_IMAGE_PROVIDER", "ollama_prompt_only")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(recipe_edit_service, "STEP_IMAGE_FOLDER", tmp_path / "recipe_steps")
    monkeypatch.setattr(recipe_edit_service, "ensure_webp_variants", lambda image_path: None)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda requested_url: recipe_data if requested_url == url else None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", lambda recipe_url, data: None)
    monkeypatch.setattr(recipe_edit_service, "start_recipe_image_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "finish_recipe_image_progress", lambda *args, **kwargs: None)

    def fake_enhance(data, title, prompt, required=False, image_purpose=""):
        prompt_calls["required"] = required
        prompt_calls["image_purpose"] = image_purpose
        return "polished step prompt"

    def fake_openai(prompt):
        prompt_calls["openai_prompt"] = prompt
        return b"openai-step-png"

    monkeypatch.setattr(recipe_edit_service, "enhance_recipe_image_prompt_with_ollama", fake_enhance)
    monkeypatch.setattr(recipe_edit_service, "request_recipe_step_image_bytes", fake_openai)

    result = recipe_edit_service.generate_recipe_step_image({
        "url": url,
        "step_number": 1,
    })

    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert result["fallback_used"] is False
    assert prompt_calls["required"] is True
    assert prompt_calls["image_purpose"] == "recipe instruction step image"
    assert prompt_calls["openai_prompt"] == "polished step prompt"


def test_admin_can_test_local_title_image_generation_route(monkeypatch, tmp_path):
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(user_account_service, "ADMIN_EMAIL", "admin@example.com")
    user_account_service.save_users({
        "users": [{
            "user_id": "admin",
            "email": "admin@example.com",
            "username": "admin@example.com",
            "account_status": "active",
        }],
    })
    monkeypatch.setattr(
        recipe_routes,
        "test_local_title_image_generation",
        lambda prompt="": {
            "ok": True,
            "provider": "comfyui",
            "comfyui_url": "http://127.0.0.1:8188",
            "message": "Local image generation succeeded.",
            "byte_count": 123,
        },
    )
    app = create_app()

    with app.test_client() as client:
        seed_signed_in_user(client, "admin")
        response = client.post(
            "/api/recipe_cover_image/test-local",
            json={"prompt": "test prompt"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["provider"] == "comfyui"
    assert payload["byte_count"] == 123


def test_generate_recipe_cover_image_route_uses_openai_usage_wrapper(monkeypatch):
    app = create_app()

    monkeypatch.setattr(
        recipe_routes,
        "generate_recipe_cover_image",
        lambda data: {
            "ok": True,
            "cover_image": {
                "path": "data/uploads/recipe_covers/generated.png",
                "source": "ai_generated_image",
            },
        },
    )

    with app.test_client() as client:
        seed_signed_in_user(client)
        response = client.post(
            "/api/recipe_cover_image/generate",
            json={"url": "https://example.com/spicy-noodles"},
        )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["cover_image"]["source"] == "ai_generated_image"
    assert "openai_usage_dashboard" in payload


def test_generate_recipe_from_image_passes_description_hint(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")
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


def test_generate_recipe_from_image_queues_media_job_by_default(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    upload_path = write_uploaded_image(user_data_dir, user_id)
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.delenv("JOB_QUEUE_MODE", raising=False)

    enqueued = {}

    def fake_enqueue(job_id, queue_name_override=""):
        enqueued["job_id"] = job_id
        enqueued["queue_name"] = queue_name_override
        return {"ok": True, "mode": "rq", "rq_job_id": "rq-vision", "queue_name": queue_name_override}

    monkeypatch.setattr(recipe_routes, "enqueue_job", fake_enqueue)
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

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["queued"] is True
    assert payload["job_id"] == enqueued["job_id"]
    assert enqueued["queue_name"] == "ai-pantry-media"
    job = job_service.get_job(payload["job_id"])
    assert job["job_type"] == "doc-photo-import"
    assert job["queue_name"] == "ai-pantry-media"
    assert job["input_payload"]["upload_mode"] == "vision"
    assert job["input_payload"]["model_env_var_used"] == "OPENAI_VISION_MODEL"


def test_generate_recipe_from_image_reports_json_parse_failure(monkeypatch, tmp_path):
    user_id, user_data_dir = configure_image_user(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")
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

    assert "visionRecipeJsonFromPayload(data)" in block
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


def test_equipment_image_prompt_starts_collapsed_in_editor_ui():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    start = script.index("function addRecipeEquipmentRow")
    end = script.index("function updateRecipeEquipmentRowNumbers", start)
    equipment_block = script[start:end]
    prompt_start = equipment_block.index("recipe-image-prompt recipe-image-prompt-collapsed")
    prompt_end = equipment_block.index("data-equipment-image-prompt-text", prompt_start)
    prompt_markup = equipment_block[prompt_start:prompt_end]
    setter_start = script.index("function setRecipeImagePanelPrompt")
    setter_end = script.index("function updateRecipeImagePanelUploadButton", setter_start)
    setter_block = script[setter_start:setter_end]

    assert "recipe-image-prompt recipe-image-prompt-collapsed" in prompt_markup
    assert "data-equipment-image-prompt-toggle" in prompt_markup
    assert 'aria-expanded="false"' in prompt_markup
    assert "toggleRecipeImagePrompt(this)" in prompt_markup
    assert "<pre data-equipment-image-prompt-text hidden>" in equipment_block
    assert "setRecipeImagePromptCollapsed(promptPanel, true);" in setter_block
    assert ".recipe-image-prompt-collapsed" in css
    assert ".recipe-image-prompt pre[hidden]" in css


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
