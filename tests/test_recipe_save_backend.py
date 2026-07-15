from pathlib import Path
from urllib.parse import quote

import pytest
from flask import Flask

from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


def configure_recipe_save_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "ingredient_store_section_options", lambda: [])
    monkeypatch.setattr(recipe_edit_service, "editable_menu_source_options", lambda: [])
    monkeypatch.setattr(
        recipe_edit_service,
        "lazy_backfill_editable_recipe_restaurant",
        lambda _url, recipe: recipe,
    )
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "replace_recipe_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "move_recipe_meta", lambda *_args, **_kwargs: None)
    return output_dir


def recipe_route_client():
    app = Flask("recipe-save-backend-tests")
    app.config.update(TESTING=True, SECRET_KEY="recipe-save-tests")
    app.register_blueprint(recipe_routes.recipe_bp)
    return app.test_client()


def editable_payload(source_url, **overrides):
    payload = {
        "source_url": source_url,
        "display_name": "Saved Soup",
        "recipe_title": "Saved Soup",
        "quantity": 1,
        "servings": "4",
        "rating": 4,
        "ingredients": [{"ingredient": "broth", "quantity": "2", "unit": "cups"}],
        "equipment": [{"equipment": "pot"}],
        "instructions": [{"step_number": 1, "instruction": "Simmer."}],
        "nutrition": [{"key": "calories", "value": "120 kcal"}],
        "recipe_notes": [],
        "reflection_notes": [],
    }
    payload.update(overrides)
    return payload


def seed_recipe(url, **overrides):
    recipe = {
        "recipe_id": "recipe-stable-id",
        "source_url": url,
        "recipe_title": "Soup",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "nutrition": {},
    }
    recipe.update(overrides)
    recipe_edit_service.save_recipe_output(url, recipe)
    return recipe


def test_recipe_save_route_round_trips_encoded_source_url(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    url = (
        "https://example.test/menu?category=Small%20Plates"
        "&menu_item=Soup%20%26%20Salad"
    )
    seed_recipe(url)

    client = recipe_route_client()
    response = client.post(
        "/api/recipe",
        json={"original_url": url, "recipe": editable_payload(url)},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["success"] is True
    assert data["message"] == "Recipe saved successfully"
    assert data["recipe_id"] == "recipe-stable-id"
    assert data["updated_at"]
    saved_recipe = recipe_edit_service.load_recipe_output(url)
    assert saved_recipe["recipe_title"] == "Saved Soup"
    assert saved_recipe["rating"] == 4
    assert len(list(output_dir.glob("*.json"))) == 1

    loaded = client.get("/api/recipe", query_string={"url": url})
    assert loaded.status_code == 200
    loaded_recipe = loaded.get_json()["recipe"]
    assert loaded_recipe["source_url"] == url
    assert loaded_recipe["rating"] == 4


def test_recipe_load_and_save_preserve_ingredient_match_analysis_metadata(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/ingredient-match-analysis-round-trip"
    match_metadata = {
        "matching_status": "best available",
        "match_confidence": 0.94,
        "master_match_confidence": "high",
        "normalization_confidence": 0.98,
        "matched_master_ingredient": "Yukon Gold potato",
        "master_ingredient_name": "Potato",
        "matched_ingredient": "Yukon Gold potato",
        "best_match": True,
        "is_best_match": False,
        "best_available_match": True,
        "alternative_matches": [
            {"ingredient": "Russet potato", "confidence": 0.82},
            "Red potato",
        ],
        "match_alternatives": ["Russet potato", "Red potato"],
        "match_candidates": [{"name": "Yukon Gold potato", "score": 0.94}],
        "candidates": ["Yukon Gold potato", "Russet potato"],
        "match_source": "ingredient_master",
        "matching_source": "normalized ingredient master",
        "match_reason": "Exact normalized-name match",
        "matching_reason": "Normalized name and store section agree",
        "match_attempted": True,
        "needs_match_review": False,
        "review_match": False,
        "multiple_matches": False,
        "pantry_staple": False,
        "is_pantry_staple": False,
    }
    seed_recipe(
        url,
        ingredients=[{
            "id": "ingredient-potato",
            "ingredient": "Potato",
            "quantity": "4",
            "unit": "medium",
            **match_metadata,
        }],
        instructions=[{"step_number": 1, "instruction": "Boil."}],
    )

    client = recipe_route_client()
    loaded_response = client.get("/api/recipe", query_string={"url": url})

    assert loaded_response.status_code == 200
    loaded_ingredient = loaded_response.get_json()["recipe"]["ingredients"][0]
    assert {
        field: loaded_ingredient.get(field)
        for field in match_metadata
    } == match_metadata

    save_response = client.post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe": editable_payload(
                url,
                ingredients=[{
                    "id": "ingredient-potato",
                    "ingredient": "Potato",
                    "quantity": "5",
                    "unit": "medium",
                }],
            ),
        },
    )

    assert save_response.status_code == 200
    response_ingredient = save_response.get_json()["recipe"]["ingredients"][0]
    saved_ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    for ingredient in (response_ingredient, saved_ingredient):
        assert {
            field: ingredient.get(field)
            for field in match_metadata
        } == match_metadata


def test_recipe_save_accepts_match_analysis_metadata_without_coercing_values(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/submitted-ingredient-match-analysis"
    seed_recipe(
        url,
        ingredients=[{"id": "ingredient-broth", "ingredient": "Broth"}],
        instructions=[{"step_number": 1, "instruction": "Simmer."}],
    )
    submitted_metadata = {
        "match_confidence": "87%",
        "master_match_confidence": 0.87,
        "matched_master_ingredient": "Low-sodium chicken broth",
        "best_match": False,
        "is_best_match": True,
        "best_available_match": False,
        "alternative_matches": ["Vegetable broth", "Chicken stock"],
        "match_source": "recipe import",
        "match_reason": "Two close candidates; user selected this match",
    }

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            ingredients=[{
                "id": "ingredient-broth",
                "ingredient": "Broth",
                **submitted_metadata,
            }],
        ),
        require_existing=True,
    )

    assert result["ok"] is True
    saved_ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    returned_ingredient = result["recipe"]["ingredients"][0]
    for ingredient in (saved_ingredient, returned_ingredient):
        assert {
            field: ingredient.get(field)
            for field in submitted_metadata
        } == submitted_metadata


def test_single_ingredient_save_patches_only_the_stable_target_and_runs_existing_syncs(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-ingredient-save"
    match_metadata = {
        "match_confidence": 0.96,
        "matched_master_ingredient": "Cultured buttermilk",
        "best_available_match": True,
        "alternative_matches": ["Plain yogurt", "Milk and lemon juice"],
        "match_source": "ingredient_master",
        "match_reason": "Exact normalized-name match",
    }
    seed_recipe(
        url,
        recipe_title="Persisted Recipe Title",
        description="Persisted description",
        ingredients=[
            {
                "id": "ingredient-potato",
                "recipe_ingredient_id": "recipe-row-potato",
                "ingredient": "Potato",
                "quantity": "4",
                "unit": "medium",
                "notes": "Leave unchanged",
            },
            {
                "id": "ingredient-buttermilk",
                "recipe_ingredient_id": "recipe-row-buttermilk",
                "ingredient": "Buttermilk",
                "quantity": "1",
                "unit": "cup",
                "store_section": "DAIRY",
                "store_section_custom": True,
                "substitutions": [{
                    "id": "substitution-yogurt",
                    "ingredient": "Plain yogurt",
                    "quantity": "1",
                    "unit": "cup",
                }],
                **match_metadata,
            },
        ],
        instructions=[{"step_number": 1, "instruction": "Mix gently."}],
    )
    before = recipe_edit_service.load_recipe_output(url)
    sync_calls = []
    monkeypatch.setattr(
        recipe_edit_service,
        "update_recipe_ingredient_record",
        lambda saved_url, quantity, recipe: sync_calls.append(
            ("master", saved_url, quantity, recipe["ingredients"][1]["notes"])
        ),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "update_recipe_quantity",
        lambda saved_url, quantity: sync_calls.append(("quantity", saved_url, quantity)),
    )
    monkeypatch.setattr(
        recipe_edit_service,
        "sync_saved_recipe_with_shopping_list",
        lambda recipe, previous: sync_calls.append(
            ("shopping", recipe["ingredients"][1]["notes"], list(previous))
        ),
    )

    response = recipe_route_client().post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "recipe_id": "recipe-stable-id",
            "ingredient_index": 0,
            "ingredient_ref": {"recipe_ingredient_id": "recipe-row-buttermilk"},
            "ingredient": {
                "id": "ingredient-buttermilk",
                "recipe_ingredient_id": "recipe-row-buttermilk",
                "ingredient": "Buttermilk",
                "quantity": "2",
                "notes": "Use full-fat when available.",
            },
            "recipe": {
                "recipe_title": "Unsaved unrelated draft title",
                "instructions": [{"instruction": "Unsaved unrelated draft instruction"}],
            },
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["ok"] is True
    assert result["success"] is True
    assert result["ingredient_index"] == 1
    assert result["matched_by"] == "stable_id"
    assert result["ingredient"]["id"] == "ingredient-buttermilk"
    assert result["ingredient"]["recipe_ingredient_id"] == "recipe-row-buttermilk"
    assert result["ingredient"]["quantity"] == "2"
    assert result["ingredient"]["notes"] == "Use full-fat when available."
    assert {field: result["ingredient"].get(field) for field in match_metadata} == match_metadata

    saved = recipe_edit_service.load_recipe_output(url)
    assert saved["recipe_title"] == "Persisted Recipe Title"
    assert saved["description"] == "Persisted description"
    assert saved["instructions"] == before["instructions"]
    assert saved["ingredients"][0] == before["ingredients"][0]
    assert saved["ingredients"][1]["quantity"] == "2"
    assert saved["ingredients"][1]["unit"] == "cup"
    assert saved["ingredients"][1]["store_section"] == "DAIRY"
    assert saved["ingredients"][1]["store_section_custom"] is True
    assert saved["ingredients"][1]["notes"] == "Use full-fat when available."
    assert saved["ingredients"][1]["substitutions"] == before["ingredients"][1]["substitutions"]
    assert {field: saved["ingredients"][1].get(field) for field in match_metadata} == match_metadata
    assert [call[0] for call in sync_calls] == ["master", "quantity", "shopping"]


def test_single_ingredient_save_explicit_create_inserts_without_reusing_an_existing_row(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-ingredient-create"
    seed_recipe(
        url,
        ingredients=[
            {
                "id": "ingredient-pepper",
                "recipe_ingredient_id": "recipe-row-pepper",
                "ingredient": "Pepper",
                "notes": "First existing row",
            },
            {
                "id": "ingredient-salt",
                "recipe_ingredient_id": "recipe-row-salt",
                "ingredient": "Salt",
                "notes": "Existing same-name row",
            },
        ],
        instructions=[{"step_number": 1, "instruction": "Season."}],
    )
    before = recipe_edit_service.load_recipe_output(url)

    response = recipe_route_client().post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "recipe_id": "recipe-stable-id",
            "ingredient_ref": {"create": True, "index": 1},
            "ingredient": {
                "id": "ingredient-salt",
                "recipe_ingredient_id": "recipe-row-salt",
                "row_id": "stale-row-id",
                "ingredient": "Salt",
                "quantity": "1",
                "unit": "pinch",
                "notes": "New same-name row",
            },
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["created"] is True
    assert result["ingredient_index"] == 1
    assert result["matched_by"] == "create"
    assert result["ingredient"]["notes"] == "New same-name row"
    assert not any(
        result["ingredient"].get(field)
        for field in ("id", "recipe_ingredient_id", "row_id")
    )

    saved = recipe_edit_service.load_recipe_output(url)
    assert len(saved["ingredients"]) == 3
    assert saved["ingredients"][0] == before["ingredients"][0]
    assert saved["ingredients"][2] == before["ingredients"][1]
    assert saved["ingredients"][1]["ingredient"] == "Salt"
    assert saved["ingredients"][1]["notes"] == "New same-name row"
    assert not any(
        saved["ingredients"][1].get(field)
        for field in ("id", "recipe_ingredient_id", "row_id")
    )


def test_single_ingredient_save_supports_safe_index_and_original_name_fallback(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-ingredient-index-fallback"
    seed_recipe(
        url,
        ingredients=[
            {"ingredient": "Crema", "quantity": "1", "unit": "cup"},
            {"ingredient": "Salt", "quantity_text": "to taste"},
        ],
        instructions=[{"step_number": 1, "instruction": "Mix."}],
    )

    response = recipe_route_client().post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "recipe_id": "recipe-stable-id",
            "ingredient_ref": {"index": 0, "ingredient": "Crema"},
            "ingredient": {
                "ingredient": "Mexican crema",
                "quantity": "1.5",
                "unit": "cups",
            },
        },
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["matched_by"] == "index_and_name"
    saved = recipe_edit_service.load_recipe_output(url)
    assert saved["ingredients"][0]["ingredient"] == "Mexican crema"
    assert saved["ingredients"][0]["quantity"] == "1.5"
    assert saved["ingredients"][1]["ingredient"] == "Salt"


def test_single_ingredient_save_rejects_stale_recipe_or_ingredient_identity(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-ingredient-conflicts"
    seed_recipe(
        url,
        ingredients=[{
            "id": "ingredient-potato",
            "recipe_ingredient_id": "recipe-row-potato",
            "ingredient": "Potato",
            "quantity": "4",
        }],
        instructions=[{"step_number": 1, "instruction": "Boil."}],
    )
    before = recipe_edit_service.load_recipe_output(url)
    client = recipe_route_client()

    recipe_conflict = client.post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "recipe_id": "different-recipe-id",
            "ingredient_ref": {"recipe_ingredient_id": "recipe-row-potato"},
            "ingredient": {"ingredient": "Potato", "quantity": "8"},
        },
    )
    ingredient_missing = client.post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "recipe_id": "recipe-stable-id",
            "ingredient_ref": {"recipe_ingredient_id": "missing-row"},
            "ingredient": {"ingredient": "Potato", "quantity": "8"},
        },
    )

    assert recipe_conflict.status_code == 409
    assert recipe_conflict.get_json()["error"] == "recipe_conflict"
    assert ingredient_missing.status_code == 404
    assert ingredient_missing.get_json()["error"] == "ingredient_not_found"
    assert recipe_edit_service.load_recipe_output(url) == before


def test_single_ingredient_save_rejects_ambiguous_name_and_blank_required_name(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-ingredient-validation"
    seed_recipe(
        url,
        ingredients=[
            {"id": "salt-one", "ingredient": "Salt", "quantity_text": "to taste"},
            {"id": "salt-two", "ingredient": "Salt", "quantity": "1", "unit": "teaspoon"},
        ],
        instructions=[{"step_number": 1, "instruction": "Season."}],
    )
    before = recipe_edit_service.load_recipe_output(url)
    client = recipe_route_client()

    ambiguous = client.post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "ingredient": {"ingredient": "Salt", "notes": "Ambiguous edit"},
        },
    )
    blank_name = client.post(
        "/api/recipe/ingredient",
        json={
            "original_url": url,
            "ingredient_ref": {"id": "salt-one"},
            "ingredient": {"ingredient": ""},
        },
    )

    assert ambiguous.status_code == 409
    assert ambiguous.get_json()["error"] == "ingredient_conflict"
    assert blank_name.status_code == 422
    assert blank_name.get_json()["field_errors"] == {
        "ingredient.ingredient": "Ingredient name is required."
    }
    assert recipe_edit_service.load_recipe_output(url) == before


def test_double_encoded_original_url_is_rejected_without_duplicate(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/menu?category=Small%20Plates&menu_item=Soup%20%26%20Salad"
    seed_recipe(url)

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": quote(url, safe=""),
            "recipe": editable_payload(url),
        },
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"
    assert len(list(output_dir.glob("*.json"))) == 1
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Soup"


def test_stale_original_url_resolves_existing_recipe_by_stable_id(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/menu?category=Small%20Plates&menu_item=Soup%20%26%20Salad"
    recipe_id = "stable-stale-url-id"
    seed_recipe(url, recipe_id=recipe_id)

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": quote(url, safe=""),
            "recipe_id": recipe_id,
            "recipe": editable_payload(url),
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["recipe_id"] == recipe_id
    assert len(list(output_dir.glob("*.json"))) == 1
    saved = recipe_edit_service.load_recipe_output(url)
    assert saved["recipe_id"] == recipe_id
    assert saved["source_url"] == url
    assert saved["recipe_title"] == "Saved Soup"


def test_stale_original_url_with_wrong_recipe_id_stays_not_found(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/menu?category=Small%20Plates&menu_item=Soup%20%26%20Salad"
    seed_recipe(url, recipe_id="actual-stable-id")

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": quote(url, safe=""),
            "recipe_id": "wrong-stable-id",
            "recipe": editable_payload(url),
        },
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"
    assert len(list(output_dir.glob("*.json"))) == 1
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Soup"


def test_recipe_save_route_returns_field_errors_without_writing(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/invalid"
    seed_recipe(url)
    payload = editable_payload(
        url,
        ingredients=[
            {"ingredient": "salt", "quantity": f"1{chr(0x2013)}2", "optional": True},
            {"ingredient": "pepper", "quantity": "1..2"},
        ],
        instructions=[{"step_number": 0, "instruction": "Season."}],
        nutrition=[{"key": "protein", "value": "12..3 g"}],
    )

    response = recipe_route_client().post(
        "/api/recipe",
        json={"original_url": url, "recipe": payload},
    )

    assert response.status_code == 422
    data = response.get_json()
    assert data["error"] == "validation_error"
    assert data["message"] == "Some fields need attention."
    assert "ingredients.0.amount" not in data["field_errors"]
    assert data["field_errors"]["ingredients.1.amount"] == "Ingredient amount is invalid."
    assert "instructions.0.step_number" in data["field_errors"]
    assert "nutrition.0.value" in data["field_errors"]
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Soup"


@pytest.mark.parametrize(
    "amount",
    [
        "1 heaping",
        "2 (14-ounce)",
        "1 or 2",
        "1,000",
        "1, 1/2",
        "1 - 2",
        f"1{chr(0x2013)}2",
        "to taste",
    ],
)
def test_recipe_amount_validation_allows_free_form_quantities(amount):
    assert recipe_edit_service.recipe_amount_is_valid(amount) is True


@pytest.mark.parametrize(
    "amount",
    ["1/0", "1 1/0", "1..2", "1,,2", "1//2", "1.2.3", "-1", "NaN", "Infinity", "1e309"],
)
def test_recipe_amount_validation_rejects_clear_numeric_errors(amount):
    assert recipe_edit_service.recipe_amount_is_valid(amount) is False


def test_recipe_save_route_requires_an_ingredient_and_instruction(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/missing-required-rows"
    seed_recipe(url)

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe": editable_payload(url, ingredients=[], instructions=[]),
        },
    )

    assert response.status_code == 422
    data = response.get_json()
    assert data["field_errors"]["ingredients"] == "Add at least one ingredient."
    assert data["field_errors"]["instructions"] == "Add at least one instruction."
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Soup"


def test_recipe_save_route_returns_json_for_not_found_and_exception(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/missing"
    client = recipe_route_client()

    missing = client.post(
        "/api/recipe",
        json={"original_url": url, "recipe": editable_payload(url)},
    )
    assert missing.status_code == 404
    assert missing.get_json()["error"] == "not_found"
    assert missing.get_json()["field_errors"]["original_url"] == "Recipe was not found."

    def fail_save(*_args, **_kwargs):
        raise OSError("private disk failure detail")

    monkeypatch.setattr(recipe_routes, "save_editable_recipe", fail_save)
    failed = client.post(
        "/api/recipe",
        json={"original_url": url, "recipe": editable_payload(url)},
    )
    assert failed.status_code == 500
    assert failed.is_json
    assert failed.get_json() == {
        "ok": False,
        "success": False,
        "error": "save_failed",
        "message": "The recipe could not be saved.",
        "field_errors": {},
    }


def test_nested_reorder_delete_and_row_metadata_are_persisted(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/nested"
    seed_recipe(
        url,
        ingredients=[
            {
                "id": "ingredient-row-a",
                "recipe_ingredient_id": "recipe-ingredient-a",
                "ingredient_id": "101",
                "ingredient": "onion",
                "quantity": "1",
                "substitutions": [{"id": "sub-a", "substitution_id": "substitution-a", "ingredient": "shallot"}],
            },
            {
                "id": "ingredient-row-b",
                "recipe_ingredient_id": "recipe-ingredient-b",
                "ingredient_id": "102",
                "ingredient": "carrot",
                "quantity": "2",
                "substitutions": [{
                    "id": "sub-b",
                    "substitution_id": "substitution-b",
                    "ingredient": "parsnip",
                }],
            },
            {"id": "ingredient-row-delete", "ingredient": "celery", "quantity": "1"},
        ],
        instructions=[
            {"instruction_id": "step-a", "step_number": 1, "instruction": "Chop.", "temperature": "cold"},
            {"instruction_id": "step-b", "step_number": 2, "instruction": "Cook.", "time": "10 minutes"},
            {"instruction_id": "step-delete", "step_number": 3, "instruction": "Discard."},
        ],
        equipment=[
            {"equipment_id": "equipment-a", "equipment": "knife", "section": "Prep"},
            {"equipment_id": "equipment-b", "equipment": "pot", "section": "Cook"},
        ],
        nutrition={
            "calories": "100 kcal",
            "protein": "4 g",
            "_row_metadata": {
                "calories": {"id": "nutrition-a", "source": "label"},
                "protein": {"id": "nutrition-b", "source": "estimate"},
            },
            "other": [{"id": "nutrition-delete", "label": "Potassium", "value": "2 mg"}],
        },
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            ingredients=[
                {
                    "id": "ingredient-row-b",
                    "recipe_ingredient_id": "recipe-ingredient-b",
                    "ingredient_id": "102",
                    "ingredient": "carrot",
                    "quantity": "3",
                },
                {
                    "id": "ingredient-row-a",
                    "recipe_ingredient_id": "recipe-ingredient-a",
                    "ingredient_id": "101",
                    "ingredient": "onion",
                    "quantity": "1",
                    "substitutions": [],
                },
            ],
            instructions=[
                {"instruction_id": "step-b", "step_number": 1, "instruction": "Cook."},
                {"instruction_id": "step-a", "step_number": 2, "instruction": "Chop."},
            ],
            equipment=[{"equipment_id": "equipment-b", "equipment": "pot"}],
            nutrition=[
                {"id": "nutrition-b", "key": "protein", "value": "5 g"},
                {"id": "nutrition-a", "key": "calories", "value": "110 kcal"},
            ],
        ),
        require_existing=True,
    )

    assert result["ok"] is True
    saved = recipe_edit_service.load_recipe_output(url)
    assert [row["id"] for row in saved["ingredients"]] == ["ingredient-row-b", "ingredient-row-a"]
    assert [row["recipe_ingredient_id"] for row in saved["ingredients"]] == [
        "recipe-ingredient-b",
        "recipe-ingredient-a",
    ]
    assert saved["ingredients"][1]["substitutions"] == []
    assert saved["ingredients"][0]["substitutions"][0]["id"] == "sub-b"
    assert saved["ingredients"][0]["substitutions"][0]["substitution_id"] == "substitution-b"
    assert [row["instruction_id"] for row in saved["instructions"]] == ["step-b", "step-a"]
    assert saved["instructions"][0]["time"] == "10 minutes"
    assert saved["instructions"][1]["temperature"] == "cold"
    assert saved["equipment"] == [{
        "equipment_id": "equipment-b",
        "equipment": "pot",
        "text": "pot",
        "section": "Cook",
        "equipment_image_url": "",
        "equipment_image_generated_at": "",
        "equipment_image_prompt": "",
    }]
    assert saved["nutrition"]["_row_metadata"]["protein"]["id"] == "nutrition-b"
    assert saved["nutrition"]["_row_metadata"]["protein"]["source"] == "estimate"
    assert "other" not in saved["nutrition"]


def test_grouped_substitution_alternative_round_trips_as_flat_component_rows(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/grouped-substitution"
    seed_recipe(
        url,
        ingredients=[{"id": "ingredient-buttermilk", "ingredient": "buttermilk", "quantity": "1", "unit": "cup"}],
        instructions=[{"step_number": 1, "instruction": "Mix."}],
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            ingredients=[{
                "id": "ingredient-buttermilk",
                "ingredient": "buttermilk",
                "quantity": "1",
                "unit": "cup",
                "substitutions": [{
                    "alternative_id": "alternative-milk-lemon",
                    "alternative_order": 1,
                    "ingredients": [
                        {
                            "id": "substitution-milk",
                            "ingredient": "Milk",
                            "quantity": "1",
                            "unit": "cup",
                        },
                        {
                            "id": "substitution-lemon",
                            "ingredient": "Lemon Juice",
                            "quantity": "1",
                            "unit": "tablespoon",
                        },
                    ],
                }],
            }],
        ),
        require_existing=True,
    )

    assert result["ok"] is True
    substitutions = recipe_edit_service.load_recipe_output(url)["ingredients"][0]["substitutions"]
    assert [row["ingredient"] for row in substitutions] == ["Milk", "Lemon Juice"]
    assert [row["id"] for row in substitutions] == ["substitution-milk", "substitution-lemon"]
    assert {row["alternative_id"] for row in substitutions} == {"alternative-milk-lemon"}
    assert [row["alternative_order"] for row in substitutions] == [1, 1]
    assert [row["alternative_component_order"] for row in substitutions] == [0, 1]
    assert all("ingredients" not in row for row in substitutions)


def test_single_component_alternative_preserves_normalized_fields_across_two_saves(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/single-alternative-two-save-round-trip"
    seed_recipe(
        url,
        ingredients=[{"id": "ingredient-potato", "ingredient": "Potato"}],
        instructions=[{"step_number": 1, "instruction": "Roast."}],
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            ingredients=[{
                "id": "ingredient-potato",
                "ingredient": "Potato",
                "quantity": "4",
                "unit": "",
                "size": "medium",
                "substitutions": [{
                    "alternative_id": "alternative-sweet-potato",
                    "alternative_order": 0,
                    "alternative_label": "Sweet potato",
                    "match_status": "best_match",
                    "preferred": True,
                    "ingredients": [{
                        "id": "substitution-sweet-potato",
                        "substitution_id": "substitution-stable-id",
                        "ingredient": "Sweet Potato",
                        "parsed_name": "sweet potato",
                        "normalized_name": "sweet_potato",
                        "quantity": "4",
                        "quantity_text": "",
                        "unit": "",
                        "size": "medium",
                        "preparation": "peeled",
                        "purchasable_item": "Orange sweet potatoes",
                        "store_section": "PRODUCE",
                        "store_section_custom": False,
                        "notes": "Use an equal total weight.",
                        "ingredient_image_url": "/static/generated/ingredients/sweet-potato.webp",
                        "ingredient_image_generated_at": "2026-07-14T12:00:00Z",
                        "ingredient_image_prompt": "Four orange sweet potatoes",
                    }],
                }],
            }],
        ),
        require_existing=True,
    )

    assert result["ok"] is True
    first_ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    first_alternative = first_ingredient["substitutions"][0]

    second_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[first_ingredient]),
        require_existing=True,
    )

    assert second_result["ok"] is True
    second_alternative = recipe_edit_service.load_recipe_output(url)["ingredients"][0]["substitutions"][0]
    preserved_fields = (
        "id",
        "substitution_id",
        "alternative_id",
        "alternative_order",
        "alternative_component_order",
        "alternative_label",
        "ingredient",
        "parsed_name",
        "normalized_name",
        "quantity",
        "quantity_text",
        "unit",
        "size",
        "preparation",
        "purchasable_item",
        "store_section",
        "store_section_custom",
        "notes",
        "match_status",
        "preferred",
        "ingredient_image_url",
        "ingredient_image_generated_at",
        "ingredient_image_prompt",
    )
    assert {field: second_alternative.get(field) for field in preserved_fields} == {
        field: first_alternative.get(field) for field in preserved_fields
    }
    assert second_alternative["alternative_id"] == "alternative-sweet-potato"
    assert second_alternative["alternative_component_order"] == 0
    assert second_alternative["ingredient"] == "Sweet Potato"
    assert second_alternative["purchasable_item"] == "Orange sweet potatoes"
    assert second_alternative["preferred"] is True


def test_read_first_ingredient_and_multi_component_alternative_preserve_normalized_fields(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/read-first-normalized-fields"
    seed_recipe(
        url,
        ingredients=[{"id": "ingredient-buttermilk", "ingredient": "Buttermilk"}],
        instructions=[{"step_number": 1, "instruction": "Mix."}],
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            ingredients=[{
                "id": "ingredient-buttermilk",
                "ingredient": "Buttermilk",
                "quantity": "",
                "quantity_text": "as needed",
                "unit": "",
                "size": "large",
                "preparation": "shaken",
                "purchasable_item": "Cultured buttermilk",
                "store_section": "Specialty Dairy",
                "store_section_custom": True,
                "section": "Finishing Sauce",
                "optional": False,
                "notes": "Use full-fat when available.",
                "match_status": "best_match",
                "confidence": "high",
                "ingredient_image_url": "/static/generated/ingredients/buttermilk.webp",
                "substitutions": [{
                    "alternative_id": "alternative-milk-lemon",
                    "alternative_order": 1,
                    "alternative_label": "Milk and lemon juice",
                    "match_status": "good_match",
                    "preferred": True,
                    "ingredients": [
                        {
                            "id": "substitution-milk",
                            "ingredient": "Milk",
                            "quantity": "1",
                            "quantity_text": "",
                            "unit": "cup",
                            "size": "",
                            "preparation": "room temperature",
                            "purchasable_item": "Whole milk",
                            "store_section": "Alternative Dairy",
                            "store_section_custom": True,
                            "notes": "Do not use skim milk.",
                            "ingredient_image_url": "/static/generated/ingredients/milk.webp",
                            "ingredient_image_generated_at": "2026-07-14T12:00:00Z",
                            "ingredient_image_prompt": "A glass jug of whole milk",
                        },
                        {
                            "id": "substitution-lemon",
                            "ingredient": "Lemon Juice",
                            "quantity": "",
                            "quantity_text": "to taste",
                            "unit": "",
                            "size": "small",
                            "preparation": "freshly squeezed",
                            "purchasable_item": "Fresh lemon juice",
                            "store_section": "PRODUCE",
                            "notes": "Add gradually.",
                            "ingredient_image_url": "/static/generated/ingredients/lemon.webp",
                        },
                    ],
                }],
            }],
        ),
        require_existing=True,
    )

    assert result["ok"] is True
    ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    assert {
        "ingredient": ingredient["ingredient"],
        "quantity": ingredient["quantity"],
        "quantity_text": ingredient["quantity_text"],
        "unit": ingredient["unit"],
        "size": ingredient["size"],
        "preparation": ingredient["preparation"],
        "purchasable_item": ingredient["purchasable_item"],
        "store_section": ingredient["store_section"],
        "section": ingredient["section"],
        "optional": ingredient["optional"],
        "notes": ingredient["notes"],
        "match_status": ingredient["match_status"],
        "confidence": ingredient["confidence"],
        "ingredient_image_url": ingredient["ingredient_image_url"],
    } == {
        "ingredient": "Buttermilk",
        "quantity": None,
        "quantity_text": "as needed",
        "unit": "",
        "size": "large",
        "preparation": "shaken",
        "purchasable_item": "Cultured buttermilk",
        "store_section": "Specialty Dairy",
        "section": "Finishing Sauce",
        "optional": False,
        "notes": "Use full-fat when available.",
        "match_status": "best_match",
        "confidence": "high",
        "ingredient_image_url": "/static/generated/ingredients/buttermilk.webp",
    }

    substitutions = ingredient["substitutions"]
    assert [row["ingredient"] for row in substitutions] == ["Milk", "Lemon Juice"]
    assert {row["alternative_id"] for row in substitutions} == {"alternative-milk-lemon"}
    assert {row["alternative_label"] for row in substitutions} == {"Milk and lemon juice"}
    assert {row["match_status"] for row in substitutions} == {"good_match"}
    assert all(row["preferred"] is True for row in substitutions)

    milk, lemon = substitutions
    assert {
        "quantity": milk["quantity"],
        "quantity_text": milk["quantity_text"],
        "unit": milk["unit"],
        "size": milk["size"],
        "preparation": milk["preparation"],
        "purchasable_item": milk["purchasable_item"],
        "store_section": milk["store_section"],
        "notes": milk["notes"],
        "ingredient_image_url": milk["ingredient_image_url"],
        "ingredient_image_generated_at": milk["ingredient_image_generated_at"],
        "ingredient_image_prompt": milk["ingredient_image_prompt"],
    } == {
        "quantity": "1",
        "quantity_text": "",
        "unit": "cup",
        "size": "",
        "preparation": "room temperature",
        "purchasable_item": "Whole milk",
        "store_section": "Alternative Dairy",
        "notes": "Do not use skim milk.",
        "ingredient_image_url": "/static/generated/ingredients/milk.webp",
        "ingredient_image_generated_at": "2026-07-14T12:00:00Z",
        "ingredient_image_prompt": "A glass jug of whole milk",
    }
    assert {
        "quantity": lemon["quantity"],
        "quantity_text": lemon["quantity_text"],
        "unit": lemon["unit"],
        "size": lemon["size"],
        "preparation": lemon["preparation"],
        "purchasable_item": lemon["purchasable_item"],
        "store_section": lemon["store_section"],
        "notes": lemon["notes"],
        "ingredient_image_url": lemon["ingredient_image_url"],
    } == {
        "quantity": "",
        "quantity_text": "to taste",
        "unit": "",
        "size": "small",
        "preparation": "freshly squeezed",
        "purchasable_item": "Fresh lemon juice",
        "store_section": "PRODUCE",
        "notes": "Add gradually.",
        "ingredient_image_url": "/static/generated/ingredients/lemon.webp",
    }

    lemon_before_second_save = dict(lemon)
    milk["notes"] = "Use whole milk; avoid skim milk."
    second_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[ingredient]),
        require_existing=True,
    )

    assert second_result["ok"] is True
    second_substitutions = recipe_edit_service.load_recipe_output(url)["ingredients"][0]["substitutions"]
    assert [row["ingredient"] for row in second_substitutions] == ["Milk", "Lemon Juice"]
    assert {row["alternative_id"] for row in second_substitutions} == {"alternative-milk-lemon"}
    assert [row["alternative_component_order"] for row in second_substitutions] == [0, 1]
    assert {row["alternative_label"] for row in second_substitutions} == {"Milk and lemon juice"}
    assert {row["match_status"] for row in second_substitutions} == {"good_match"}
    assert all(row["preferred"] is True for row in second_substitutions)
    assert second_substitutions[0]["notes"] == "Use whole milk; avoid skim milk."
    untouched_fields = (
        "id",
        "ingredient",
        "quantity",
        "quantity_text",
        "unit",
        "size",
        "preparation",
        "purchasable_item",
        "store_section",
        "notes",
        "ingredient_image_url",
    )
    assert {field: second_substitutions[1].get(field) for field in untouched_fields} == {
        field: lemon_before_second_save.get(field) for field in untouched_fields
    }


def test_substitution_metadata_merge_is_scoped_to_alternative_group():
    substitutions = recipe_edit_service.normalize_ingredient_substitutions(
        [
            {"alternative_id": "alternative-a", "ingredient": "Milk", "quantity": "1"},
            {"alternative_id": "alternative-b", "ingredient": "Milk", "quantity": "2"},
        ],
        [
            {"id": "milk-a", "alternative_id": "alternative-a", "ingredient": "Milk"},
            {"id": "milk-b", "alternative_id": "alternative-b", "ingredient": "Milk"},
        ],
    )

    assert [(row["alternative_id"], row["id"]) for row in substitutions] == [
        ("alternative-a", "milk-a"),
        ("alternative-b", "milk-b"),
    ]


def test_cover_image_prompt_round_trips_and_is_preserved_when_omitted(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/cover-prompt"
    cover_image = {
        "path": "data/uploads/recipe_covers/soup.png",
        "mime_type": "image/png",
        "alt": "Soup",
        "prompt": "Existing cover prompt",
    }
    seed_recipe(
        url,
        cover_image=cover_image,
        cover_image_prompt="Existing cover prompt",
    )

    recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url),
        require_existing=True,
    )
    assert recipe_edit_service.load_recipe_output(url)["cover_image_prompt"] == "Existing cover prompt"

    recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, cover_image_prompt="Top-level cover prompt"),
        require_existing=True,
    )
    assert recipe_edit_service.load_editable_recipe(url)["recipe"]["cover_image_prompt"] == "Top-level cover prompt"

    nested_cover = {**cover_image, "prompt": "Nested cover prompt"}
    recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, cover_image=nested_cover),
        require_existing=True,
    )
    saved = recipe_edit_service.load_recipe_output(url)
    assert saved["cover_image_prompt"] == "Nested cover prompt"
    assert saved["cover_image"]["prompt"] == "Nested cover prompt"


def test_source_url_change_migrates_one_output_and_preserves_recipe_id(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    original_url = "manual://recipe/source-change"
    source_url = "https://example.test/recipes/source-change?category=soup&menu_item=one"
    seed_recipe(original_url, recipe_id="immutable-recipe-id")

    result = recipe_edit_service.save_editable_recipe(
        original_url,
        editable_payload(source_url),
        require_existing=True,
    )

    assert result["ok"] is True
    assert result["recipe_id"] == "immutable-recipe-id"
    assert len(list(output_dir.glob("*.json"))) == 1
    assert recipe_edit_service.load_recipe_output(original_url) is None
    assert recipe_edit_service.load_recipe_output(source_url)["recipe_id"] == "immutable-recipe-id"


def test_source_url_migration_failure_restores_original_output(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    original_url = "manual://recipe/migration-rollback"
    source_url = "https://example.test/recipes/migration-rollback"
    seed_recipe(original_url, recipe_id="rollback-recipe-id", recipe_title="Original")

    def fail_move(*_args, **_kwargs):
        raise OSError("metadata move failed")

    monkeypatch.setattr(recipe_edit_service, "move_recipe_meta", fail_move)
    with pytest.raises(OSError, match="metadata move failed"):
        recipe_edit_service.save_editable_recipe(
            original_url,
            editable_payload(source_url, recipe_title="Changed"),
            require_existing=True,
        )

    assert len(list(output_dir.glob("*.json"))) == 1
    assert recipe_edit_service.load_recipe_output(source_url) is None
    restored = recipe_edit_service.load_recipe_output(original_url)
    assert restored["recipe_id"] == "rollback-recipe-id"
    assert restored["recipe_title"] == "Original"


def test_conflicting_source_url_is_rejected_without_overwrite(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    original_url = "https://example.test/recipes/one"
    conflicting_url = "https://example.test/recipes/two"
    seed_recipe(original_url, recipe_id="recipe-one", recipe_title="One")
    seed_recipe(conflicting_url, recipe_id="recipe-two", recipe_title="Two")

    result = recipe_edit_service.save_editable_recipe(
        original_url,
        editable_payload(conflicting_url),
        require_existing=True,
    )

    assert result["ok"] is False
    assert result["error"] == "recipe_conflict"
    assert result["status_code"] == 409
    assert recipe_edit_service.load_recipe_output(original_url)["recipe_title"] == "One"
    assert recipe_edit_service.load_recipe_output(conflicting_url)["recipe_title"] == "Two"


def test_mismatched_recipe_id_is_rejected(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/recipes/identity"
    seed_recipe(url, recipe_id="stored-recipe-id")

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe_id": "different-recipe-id",
            "recipe": editable_payload(url),
        },
    )

    assert response.status_code == 409
    data = response.get_json()
    assert data["error"] == "recipe_conflict"
    assert data["field_errors"]["recipe_id"] == "Reload the recipe before saving these changes."
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Soup"


def test_derived_sync_failure_is_a_success_with_warning(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/derived-warning"
    seed_recipe(url)

    def fail_master_sync(*_args, **_kwargs):
        raise OSError("master database unavailable")

    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", fail_master_sync)
    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url),
        require_existing=True,
    )

    assert result["ok"] is True
    assert result["success"] is True
    assert "Ingredient and equipment master data could not be synchronized." in result["warnings"]
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == "Saved Soup"


def test_recipe_output_uses_atomic_replace(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    real_replace = recipe_edit_service.os.replace
    replacements = []

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(recipe_edit_service.os, "replace", record_replace)
    url = "https://example.test/atomic"
    seed_recipe(url)

    assert len(replacements) == 1
    assert replacements[0][1] == output_dir / "example_test_atomic.json"
    assert not list(output_dir.glob("*.tmp"))
