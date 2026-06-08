from pathlib import Path

from flask import session

from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_url_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def seed_signed_in_user(client, user_id="image-user"):
    with client.session_transaction() as test_session:
        test_session["user_id"] = user_id


def test_generate_recipe_from_image_commits_estimate(monkeypatch, tmp_path):
    user_id = "image-user"
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

    upload_dir = user_data_dir / user_id / "recipe-extractor" / "data" / "uploads"
    upload_dir.mkdir(parents=True)
    upload_path = upload_dir / "meal.jpg"
    upload_path.write_bytes(b"fake image bytes")

    parsed_recipe = {
        "recipe_title": "Photo Rice Bowl",
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
    assert payload["recipe_json"] == parsed_recipe
    assert payload["category_status"]["ok"] is True

    with app.test_request_context("/"):
        session["user_id"] = user_id
        assert shopping_list_service.load_items() == ["rice", "onion"]
        assert recipe_url_service.load_recipe_urls() == ["uploaded://meal.jpg"]


def test_generate_recipe_from_image_success_refreshes_after_save():
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    start = script.index("async function submitRecipeMediaVision()")
    end = script.index("async function submitRecipeMediaRetry()")
    block = script[start:end]

    assert 'updateRecipeFileLoadingStep("save", "running", "Saving");' in block
    assert "Saving ingredients and refreshing the shopping list..." in block
    assert "window.location.reload();" in block
