import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest
from flask import Flask

from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


RECIPE_SAVE_TEST_USER_ID = "recipe-save-test-user"


def configure_recipe_save_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_ingredient_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "user-data")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", tmp_path / "recipe_master.sqlite3")
    user_account_service.save_users({
        "users": [{
            "user_id": RECIPE_SAVE_TEST_USER_ID,
            "email": "recipe-save@example.com",
            "username": RECIPE_SAVE_TEST_USER_ID,
            "account_status": "active",
        }],
    })
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
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
    client = app.test_client()
    with client.session_transaction() as signed_session:
        signed_session["user_id"] = RECIPE_SAVE_TEST_USER_ID
    return client


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


def test_recipe_save_keeps_cuisine_tags_separate_from_category_cuisine(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/recipes/noodle-bowl"
    seed_recipe(
        url,
        cuisine="Thai category",
        cuisine_tags=["Thai", "Noodles"],
    )
    initially_loaded = recipe_edit_service.load_editable_recipe(url)
    assert initially_loaded["recipe"]["cuisine_tags"] == ["Thai", "Noodles"]

    response = recipe_route_client().post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe": editable_payload(
                url,
                cuisine_tags=["Southeast Asian", "Weeknight", "weeknight"],
                dietary_preferences=["Vegan", "Gluten Free", "vegan"],
            ),
        },
    )

    assert response.status_code == 200
    saved_recipe = recipe_edit_service.load_recipe_output(url)
    assert saved_recipe["cuisine_tags"] == ["Southeast Asian", "Weeknight"]
    assert saved_recipe["dietary_preferences"] == ["Vegan", "Gluten Free"]
    assert saved_recipe["cuisine"] == "Thai category"

    loaded = recipe_route_client().get("/api/recipe", query_string={"url": url})
    assert loaded.status_code == 200
    loaded_recipe = loaded.get_json()["recipe"]
    assert loaded_recipe["cuisine_tags"] == ["Southeast Asian", "Weeknight"]
    assert loaded_recipe["dietary_preferences"] == ["Vegan", "Gluten Free"]


def test_recipe_save_route_canonicalizes_legacy_materialized_scale(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    saved_scales = []
    monkeypatch.setattr(
        recipe_edit_service,
        "save_recipe_url_quantity",
        lambda _url, quantity: saved_scales.append(quantity),
    )
    url = "https://example.test/freeform-scale"
    seed_recipe(url)
    scaling = {
        "selected_multiplier": 1.25,
        "base_multiplier": 1,
        "base_servings": "4",
        "available_multipliers": [
            {"label": "1/2x", "value": 0.5},
            {"label": "1x", "value": 1},
            {"label": "2x", "value": 2},
            {"label": "3x", "value": 3},
        ],
    }
    payload = editable_payload(
        url,
        servings="5",
        scaling=scaling,
        ingredients=[{
            "ingredient": "broth",
            "quantity": "5/8",
            "unit": "cup",
            "base_quantity": "1/2",
            "base_unit": "cup",
        }],
    )

    client = recipe_route_client()
    response = client.post(
        "/api/recipe",
        json={"original_url": url, "recipe": payload},
    )

    assert response.status_code == 200
    saved = recipe_edit_service.load_recipe_output(url)
    assert saved["scaling"]["selected_multiplier"] == 1
    assert saved["scaling"]["base_multiplier"] == 1
    assert saved["scaling"]["base_servings"] == "4"
    assert saved["servings"] == "4"
    assert saved["ingredients"][0]["quantity"] == "1/2"
    assert saved["ingredients"][0]["base_quantity"] == "1/2"
    assert saved_scales == [1.25]

    loaded = client.get("/api/recipe", query_string={"url": url})
    assert loaded.status_code == 200
    loaded_recipe = loaded.get_json()["recipe"]
    assert loaded_recipe["scaling"]["selected_multiplier"] == 1
    assert loaded_recipe["servings"] == "4"
    assert loaded_recipe["scaling"]["base_servings"] == "4"
    assert loaded_recipe["ingredients"][0]["quantity"] == "1/2"
    assert loaded_recipe["ingredients"][0]["base_quantity"] == "1/2"


def test_recipe_get_route_preserves_database_bytes_and_store_section_sequence(
    monkeypatch, tmp_path
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/read-only-store-sections"
    output_path = recipe_edit_service.recipe_output_json_path(url)
    seed_recipe(
        url,
        ingredients=[{
            "ingredient": "broth",
            "quantity": "2",
            "unit": "cups",
        }],
        equipment=[{"equipment": "pot"}],
        instructions=[{"step_number": 1, "instruction": "Simmer."}],
    )
    master_data.ingredient_store_section_details(
        RECIPE_SAVE_TEST_USER_ID,
        include_inactive=True,
        create=True,
    )
    db_path = master_data.recipe_master_db_path()
    with sqlite3.connect(db_path) as connection:
        before_sequence = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'ingredient_store_sections'"
        ).fetchone()[0]
    before_bytes = db_path.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()
    before_output = output_path.read_bytes()

    @contextmanager
    def forbidden_writer():
        raise AssertionError("recipe GET attempted a writable master-data connection")
        yield

    monkeypatch.setattr(master_data, "existing_recipe_master_connection", forbidden_writer)
    monkeypatch.setattr(master_data, "recipe_master_connection", forbidden_writer)

    client = recipe_route_client()
    response = client.get("/api/recipe", query_string={"url": url})
    repeated = client.get("/api/recipe", query_string={"url": url})

    assert response.status_code == 200
    assert repeated.status_code == 200
    payload = response.get_json()
    assert repeated.get_json() == payload
    assert payload["recipe"]["source_url"] == url
    assert payload["recipe"]["ingredients"][0]["ingredient"] == "broth"
    assert payload["recipe"]["equipment"][0]["equipment"] == "pot"
    assert payload["store_sections"] == [
        row["section_key"]
        for row in payload["store_section_details"]
        if row["is_active"]
    ]
    after_bytes = db_path.read_bytes()
    assert output_path.read_bytes() == before_output
    assert hashlib.sha256(after_bytes).hexdigest() == before_hash, [
        index
        for index, (before, after) in enumerate(zip(before_bytes, after_bytes))
        if before != after
    ]
    with sqlite3.connect(db_path) as connection:
        after_sequence = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'ingredient_store_sections'"
        ).fetchone()[0]
    assert after_sequence == before_sequence
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM recipe_ingredient_requirement_sync
             WHERE user_id = ? AND recipe_id = ?
            """,
            (
                RECIPE_SAVE_TEST_USER_ID,
                master_data.recipe_id_for_url(url),
            ),
        ).fetchone()[0] == 0


def test_recipe_output_index_prefers_legacy_menu_record_url(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    menu_url = "menu://shared-menu"
    first_url = f"{menu_url}?menu_item=first"
    second_url = f"{menu_url}?menu_item=second"

    for recipe_url, title in ((first_url, "First"), (second_url, "Second")):
        path = recipe_extract_service.recipe_output_json_path(recipe_url, output_folder=output_dir)
        recipe_edit_service.save_recipe_output_to_path(path, {
            "source_url": menu_url,
            "recipe_record_url": recipe_url,
            "recipe_title": title,
            "ingredients": [],
            "equipment": [],
            "instructions": [],
        })

    assert recipe_edit_service.load_recipe_output(first_url)["recipe_title"] == "First"
    assert recipe_edit_service.load_recipe_output(second_url)["recipe_title"] == "Second"
    assert recipe_edit_service.load_recipe_output(menu_url) is None


def test_recipe_output_index_omits_ambiguous_duplicate_identity(monkeypatch, tmp_path):
    output_dir = configure_recipe_save_storage(monkeypatch, tmp_path)
    shared_url = "https://example.test/recipes/shared"

    for filename, title in (("first.json", "First"), ("second.json", "Second")):
        recipe_edit_service.save_recipe_output_to_path(output_dir / filename, {
            "source_url": shared_url,
            "recipe_title": title,
            "ingredients": [],
            "equipment": [],
            "instructions": [],
        })

    assert shared_url not in recipe_edit_service.build_recipe_output_index()


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


def test_selected_master_ingredient_attributes_survive_two_saves(monkeypatch, tmp_path):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/selected-master-ingredient-round-trip"
    seed_recipe(
        url,
        ingredients=[{
            "id": "ingredient-butter",
            "recipe_ingredient_id": "requirement-butter",
            "row_id": "row-butter",
            "ingredient": "Butter",
            "original_text": "2 cups butter, cooked",
            "source_text": "2 cups butter, cooked",
            "raw_name": "butter",
            "canonical_ingredient": "butter",
            "form": "salted",
            "quantity": "2",
            "quantity_text": "2 cups",
            "recipe_qty": "2",
            "base_quantity": "2",
            "unit": "cup",
            "base_unit": "cup",
            "size": "large",
            "preparation": "cooked",
            "notes": "Keep the recipe-specific details.",
            "section": "main",
            "optional": False,
            "purchasable_item": "Cultured butter",
            "store_section": "DAIRY & EGGS",
            "ingredient_image_url": "/butter.png",
            "ingredient_image_generated_at": "yesterday",
            "ingredient_image_prompt": "butter prompt",
        }],
        instructions=[{"step_number": 1, "instruction": "Cook."}],
    )

    with master_data.recipe_master_connection(user_id=RECIPE_SAVE_TEST_USER_ID) as connection:
        master_data.upsert_master_record(
            connection,
            "ingredients",
            RECIPE_SAVE_TEST_USER_ID,
            "Rice",
            image_url="/rice.png",
            store_section="PASTA, RICE & GRAINS",
            force_store_section=True,
            store_section_metadata={
                "canonical_ingredient": "grain",
                "form": "dry",
                "store_section_source": "manual",
                "store_section_confidence": 0.91,
                "store_section_user_confirmed": True,
                "classifier_version": "master-v3",
                "store_section_reason": "Reviewed master section.",
                "store_section_rule": "master.reviewed",
            },
        )
    rice = master_data.master_record_for_name(
        "ingredients",
        RECIPE_SAVE_TEST_USER_ID,
        "Rice",
    )
    assert rice

    selected_rice = {
        "id": "ingredient-butter",
        "recipe_ingredient_id": "requirement-butter",
        "row_id": "row-butter",
        "ingredient_id": str(rice["id"]),
        "ingredient": "Rice",
        "parsed_name": "Rice",
        "normalized_name": "rice",
        "master_normalized_name": "rice",
        "canonical_ingredient": "grain",
        "form": "dry",
        "original_text": "2 cups butter, cooked",
        "source_text": "2 cups butter, cooked",
        "raw_name": "butter",
        "quantity": "2",
        "quantity_text": "2 cups",
        "recipe_qty": "2",
        "base_quantity": "2",
        "unit": "cup",
        "base_unit": "cup",
        "size": "large",
        "preparation": "cooked",
        "notes": "Keep the recipe-specific details.",
        "section": "main",
        "optional": False,
        "purchasable_item": "Cultured butter",
        "store_section": "PASTA, RICE & GRAINS",
        "store_section_custom": False,
        "store_section_source": "manual",
        "store_section_confidence": 0.91,
        "store_section_user_confirmed": True,
        "store_section_save_to_master": False,
        "classifier_version": "master-v3",
        "store_section_reason": "Reviewed master section.",
        "store_section_rule": "master.reviewed",
        "ingredient_image_url": "/rice.png",
        "ingredient_image_generated_at": "",
        "ingredient_image_prompt": "",
        "match_status": "Matched",
        "match_source": "ingredient master data",
        "master_ingredient_name": "Rice",
        "matched_master_ingredient": "rice",
    }
    client = recipe_route_client()

    def assert_selected_master_values(row):
        assert str(row.get("ingredient_id") or "") == str(rice["id"])
        assert row["ingredient"] == "Rice"
        assert row["parsed_name"] == "Rice"
        assert row["normalized_name"] == "rice"
        assert row["master_normalized_name"] == "rice"
        assert row["canonical_ingredient"] == "grain"
        assert row["form"] == "dry"
        assert row["store_section"] == "PASTA, RICE & GRAINS"
        assert row["store_section_custom"] is False
        assert row["store_section_source"] == "manual"
        assert row["store_section_confidence"] == pytest.approx(0.91)
        assert row["store_section_user_confirmed"] is True
        assert row["store_section_save_to_master"] is False
        assert row["classifier_version"] == "master-v3"
        assert row["store_section_reason"] == "Reviewed master section."
        assert row["store_section_rule"] == "master.reviewed"
        assert row["ingredient_image_url"] == "/rice.png"
        assert not row.get("ingredient_image_generated_at")
        assert not row.get("ingredient_image_prompt")
        assert row["match_source"] == "ingredient master data"

    def assert_recipe_values(row):
        assert row["id"] == "ingredient-butter"
        assert row["recipe_ingredient_id"] == "requirement-butter"
        assert row["row_id"] == "row-butter"
        assert row["original_text"] == "2 cups butter, cooked"
        assert row["source_text"] == "2 cups butter, cooked"
        assert row["raw_name"] == "butter"
        assert row["quantity"] == "2"
        assert row["quantity_text"] == "2 cups"
        assert row["recipe_qty"] == "2"
        assert row["base_quantity"] == "2"
        assert row["unit"] == "cup"
        assert row["base_unit"] == "cup"
        assert row["size"] == "large"
        assert row["preparation"] == "cooked"
        assert row["notes"] == "Keep the recipe-specific details."
        assert row["section"] == "main"
        assert row["optional"] is False
        assert row["purchasable_item"] == "Cultured butter"

    first_response = client.post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe": editable_payload(url, ingredients=[selected_rice]),
        },
    )
    assert first_response.status_code == 200
    first_saved = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    first_loaded = first_response.get_json()["recipe"]["ingredients"][0]
    for row in (first_saved, first_loaded):
        assert_selected_master_values(row)
        assert_recipe_values(row)

    requirement_row = master_data.recipe_master_rows(
        "recipe_ingredients",
        url,
        user_id=RECIPE_SAVE_TEST_USER_ID,
    )[0]
    assert requirement_row["canonical_ingredient"] == "grain"
    assert requirement_row["form"] == "dry"
    assert requirement_row["store_section"] == "PASTA, RICE & GRAINS"
    assert requirement_row["store_section_source"] == "manual"
    assert requirement_row["store_section_confidence"] == pytest.approx(0.91)
    assert requirement_row["store_section_user_confirmed"] == 1
    assert requirement_row["classifier_version"] == "master-v3"
    assert requirement_row["store_section_reason"] == "Reviewed master section."
    assert requirement_row["store_section_rule"] == "master.reviewed"

    second_response = client.post(
        "/api/recipe",
        json={
            "original_url": url,
            "recipe": editable_payload(url, ingredients=[first_saved]),
        },
    )
    assert second_response.status_code == 200
    second_saved = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    second_loaded = second_response.get_json()["recipe"]["ingredients"][0]
    for row in (second_saved, second_loaded):
        assert_selected_master_values(row)
        assert_recipe_values(row)


def test_recipe_store_section_override_wins_after_master_picker_selection():
    submitted = {
        "ingredient_id": "7648",
        "ingredient": "Rice",
        "normalized_name": "rice",
        "master_normalized_name": "rice",
        "master_ingredient_name": "Rice",
        "match_source": "ingredient master data",
        "store_section": "PRODUCE",
        "store_section_source": "recipe_override",
        "store_section_confidence": 1,
        "store_section_user_confirmed": True,
        "store_section_save_to_master": False,
        "store_section_reason": "User selected this section for the current recipe.",
        "store_section_rule": "recipe.user_confirmed",
    }

    sanitized = recipe_edit_service.sanitize_ingredients([submitted])[0]
    requirement = master_data.ingredient_rows_from_sources(
        recipe_data={"ingredients": [sanitized]},
    )[0]

    for row in (sanitized, requirement):
        assert row["store_section"] == "PRODUCE"
        assert row["store_section_source"] == "recipe_override"
        assert row["store_section_confidence"] == 1
        assert row["store_section_user_confirmed"] is True
        assert row["store_section_reason"] == "User-confirmed section for this recipe ingredient."
        assert row["store_section_rule"] == "recipe.user_confirmed"


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
        lambda saved_url, quantity, recipe, **_kwargs: sync_calls.append(
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


def test_grouped_choice_selection_and_component_metadata_survive_two_saves(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/grouped-choice-two-save-round-trip"
    seed_recipe(
        url,
        ingredients=[{
            "id": "ingredient-broth-choice",
            "recipe_ingredient_id": "requirement-broth-choice",
            "ingredient": "Broth choice",
        }],
        instructions=[{"step_number": 1, "instruction": "Simmer."}],
    )
    grouped_choice = {
        "id": "ingredient-broth-choice",
        "recipe_ingredient_id": "requirement-broth-choice",
        "ingredient": "Broth choice",
        "original_text": "Choose a broth base",
        "source_text": "Choose a broth base",
        "default_option_id": "option-chicken-base",
        "selection_required": True,
        "substitutions": [
            {
                "id": "option-item-chicken-broth",
                "substitution_id": "substitution-chicken-broth",
                "alternative_id": "option-chicken-base",
                "alternative_order": 0,
                "alternative_component_order": 0,
                "alternative_label": "Chicken broth base",
                "option_type": "original",
                "is_default": True,
                "preferred": True,
                "ingredient": "Chicken broth",
                "quantity": "2",
                "unit": "cup",
                "purchasable_item": "Low-sodium chicken broth",
                "store_section": "CANNED",
            },
            {
                "id": "option-item-garlic",
                "substitution_id": "substitution-garlic",
                "alternative_id": "option-chicken-base",
                "alternative_order": 0,
                "alternative_component_order": 1,
                "alternative_label": "Chicken broth base",
                "option_type": "original",
                "is_default": True,
                "preferred": True,
                "ingredient": "Garlic",
                "quantity": "1",
                "unit": "clove",
                "purchasable_item": "Garlic",
                "store_section": "PRODUCE",
            },
            {
                "id": "option-item-vegetable-broth",
                "substitution_id": "substitution-vegetable-broth",
                "alternative_id": "option-vegetable-base",
                "alternative_order": 1,
                "alternative_component_order": 0,
                "alternative_label": "Vegetable broth base",
                "option_type": "recipe_choice",
                "is_default": False,
                "preferred": False,
                "ingredient": "Vegetable broth",
                "quantity": "2",
                "unit": "cup",
                "purchasable_item": "Vegetable broth",
                "store_section": "CANNED",
            },
        ],
    }

    first_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[grouped_choice]),
        require_existing=True,
    )
    assert first_result["ok"] is True
    first_ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]

    second_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[first_ingredient]),
        require_existing=True,
    )
    assert second_result["ok"] is True
    second_ingredient = recipe_edit_service.load_recipe_output(url)["ingredients"][0]

    assert first_ingredient["recipe_ingredient_id"] == "requirement-broth-choice"
    assert first_ingredient["default_option_id"] == "option-chicken-base"
    assert first_ingredient["selection_required"] is True
    assert second_ingredient["recipe_ingredient_id"] == first_ingredient["recipe_ingredient_id"]
    assert second_ingredient["default_option_id"] == first_ingredient["default_option_id"]
    assert second_ingredient["selection_required"] is first_ingredient["selection_required"]

    preserved_fields = (
        "id",
        "substitution_id",
        "alternative_id",
        "alternative_order",
        "alternative_component_order",
        "alternative_label",
        "option_type",
        "is_default",
        "preferred",
        "ingredient",
        "quantity",
        "unit",
        "purchasable_item",
        "store_section",
    )
    first_components = [
        {field: component.get(field) for field in preserved_fields}
        for component in first_ingredient["substitutions"]
    ]
    second_components = [
        {field: component.get(field) for field in preserved_fields}
        for component in second_ingredient["substitutions"]
    ]

    assert first_components == [
        {field: component.get(field) for field in preserved_fields}
        for component in grouped_choice["substitutions"]
    ]
    assert second_components == first_components
    assert [component["alternative_id"] for component in second_components] == [
        "option-chicken-base",
        "option-chicken-base",
        "option-vegetable-base",
    ]
    assert [component["alternative_component_order"] for component in second_components] == [
        0,
        1,
        0,
    ]
    assert [component["store_section"] for component in second_components] == [
        "CANNED",
        "PRODUCE",
        "CANNED",
    ]


def test_new_implicit_original_selection_is_canonicalized_across_two_saves(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/new-implicit-original-two-save-round-trip"
    seed_recipe(
        url,
        ingredients=[{"id": "ingredient-existing", "ingredient": "Flour"}],
        instructions=[{"step_number": 1, "instruction": "Mix."}],
    )
    submitted = {
        "ingredient": "Cream",
        "original_text": "1 cup cream",
        "source_text": "1 cup cream",
        "quantity": "1",
        "unit": "cup",
        "default_option_id": "original:ingredient-local-preview",
        "original_is_default": True,
        "selection_required": True,
        "substitutions": [{
            "alternative_id": "alternative-coconut-cream",
            "alternative_order": 0,
            "alternative_component_order": 0,
            "alternative_label": "Coconut cream",
            "option_type": "substitution",
            "is_default": False,
            "preferred": False,
            "ingredient": "Coconut cream",
            "quantity": "1",
            "unit": "cup",
        }],
    }
    existing = {
        "id": "ingredient-existing",
        "recipe_ingredient_id": "ingredient-existing",
        "ingredient": "Flour",
        "quantity": "1",
        "unit": "cup",
    }

    first_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[existing, submitted]),
        require_existing=True,
    )
    assert first_result["ok"] is True
    first_recipe = recipe_edit_service.load_recipe_output(url)
    first = first_recipe["ingredients"][1]
    canonical_original_id = f"original:{first['recipe_ingredient_id']}"

    assert first["recipe_ingredient_id"].startswith("requirement-")
    assert first["default_option_id"] == canonical_original_id
    assert first["default_option_id"] != submitted["default_option_id"]
    assert first["original_is_default"] is True
    assert first["selection_required"] is True
    assert first["substitutions"][0]["alternative_id"] == "alternative-coconut-cream"
    assert first["substitutions"][0]["preferred"] is False

    second_result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=first_recipe["ingredients"]),
        require_existing=True,
    )
    assert second_result["ok"] is True
    second = recipe_edit_service.load_recipe_output(url)["ingredients"][1]

    assert second["recipe_ingredient_id"] == first["recipe_ingredient_id"]
    assert second["default_option_id"] == canonical_original_id
    assert second["original_is_default"] is True
    assert second["selection_required"] is True
    assert second["substitutions"] == first["substitutions"]


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


def test_sql_first_save_restores_previous_requirements_when_json_write_fails(
    monkeypatch,
    tmp_path,
):
    configure_recipe_save_storage(monkeypatch, tmp_path)
    url = "https://example.test/sql-json-compensation"
    original = {
        "source_url": url,
        "recipe_title": "Original",
        "ingredients": [{
            "recipe_ingredient_id": "requirement-broth",
            "ingredient": "Broth",
            "quantity": "1",
            "unit": "cup",
        }],
    }
    recipe_edit_service.save_recipe_output_with_requirements(
        url,
        original,
        previous_recipe_data={},
    )

    changed = {
        **original,
        "recipe_title": "Changed",
        "ingredients": [{
            **original["ingredients"][0],
            "quantity": "9",
        }],
    }

    def fail_json_write(*_args, **_kwargs):
        raise OSError("simulated JSON write failure")

    monkeypatch.setattr(recipe_edit_service, "save_recipe_output", fail_json_write)
    with pytest.raises(OSError, match="simulated JSON write failure"):
        recipe_edit_service.save_recipe_output_with_requirements(
            url,
            changed,
            previous_recipe_data=original,
        )

    requirements = (
        recipe_edit_service.recipe_ingredient_requirement_service
        .load_recipe_ingredient_requirements(url, user_id="local")
    )
    original_item = requirements[0]["options"][0]["items"][0]
    assert original_item["quantity"] == "1"

    raw_output = recipe_edit_service._read_recipe_output_json(
        recipe_edit_service.recipe_output_json_path(
            url,
            output_folder=recipe_edit_service.OUTPUT_FOLDER,
        )
    )
    assert raw_output["recipe_title"] == "Original"
    assert raw_output["ingredients"][0]["quantity"] == "1"
