import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PushShoppingList.services import cookbook_item_inference_service as inference
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_ingredient_service


SPRING_ROLL_URL = "menu-item://vel-asian-cuisine/kitchen-appetizers/spring-roll"
OTHER_URL = "menu-item://other-cookbook/soup"


def configure_inference_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    ingredients_file = tmp_path / "recipe_ingredients.json"

    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_ingredient_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_ingredient_service, "RECIPE_INGREDIENTS_FILE", ingredients_file)
    monkeypatch.setattr(cookbook_service, "COOKBOOKS_FILE", tmp_path / "cookbooks.json")
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(inference, "resolve_cookbook_item_model", lambda: ("gpt-test-mini", "test"))


def ai_payload(**overrides):
    payload = {
        "recipe_amount": "2 spring rolls",
        "servings": "1 appetizer serving",
        "yield": "2 pieces",
        "level": "Easy",
        "total_time": "40 minutes",
        "prep_time": "20 minutes",
        "inactive_time": "10 minutes",
        "cook_time": "10 minutes",
        "ingredients": [
            {"name": "spring roll wrappers", "quantity": "2", "unit": "", "notes": ""},
            {"name": "carrots", "quantity": "1/2", "unit": "cup", "notes": "julienned"},
            {"name": "cellophane noodles", "quantity": "1", "unit": "ounce", "notes": "soaked"},
            {"name": "mushrooms", "quantity": "1/4", "unit": "cup", "notes": "sliced"},
        ],
        "equipment": ["Cutting board", "Mixing bowl", "Skillet"],
        "instructions": [
            "Soak the noodles until pliable, then drain well.",
            "Toss the vegetables and noodles together for the filling.",
            "Wrap the filling in spring roll wrappers and fry until golden.",
        ],
        "confidence": "medium",
        "ai_inferred": True,
        "source_type": "cookbook_item_inferred",
    }
    payload.update(overrides)
    return json.dumps(payload)


def seed_cookbook_and_recipe(url=SPRING_ROLL_URL, recipe_overrides=None, cookbook_id="vel-asian-cuisine"):
    recipe = {
        "source_url": url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "recipe_title": "Spring Roll",
        "menu_section": "Kitchen Appetizers",
        "menu_item_name": "Spring Roll",
        "menu_price": "$5.99",
        "menu_description": (
            "2 veggie golden crispy brown paper wheat wrapped around mixture of carrots, "
            "mushroom and cellophane noodle."
        ),
        "recipe_amount": "",
        "servings": "",
        "yield": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "scaling": {},
        "ingredients": [{"ingredient": "", "original_text": "", "quantity": "", "unit": ""}],
        "equipment": [""],
        "instructions": [{"instruction": "", "text": ""}],
    }
    recipe.update(recipe_overrides or {})
    recipe_edit_service.save_recipe_output(url, recipe)

    cookbook_service.save_cookbooks({
        "cookbooks": [
            {
                "id": cookbook_id,
                "name": "Vel Asian Cuisine",
                "recipes": [
                    {
                        "url": url,
                        "name": "Spring Roll",
                        "source_type": "menu_item_inferred",
                        "ai_inferred": True,
                        "menu_section": "Kitchen Appetizers",
                        "menu_item_name": "Spring Roll",
                        "menu_price": "$5.99",
                        "menu_description": recipe["menu_description"],
                    }
                ],
            }
        ]
    })
    return recipe


def patch_openai_response(monkeypatch, calls=None, payload=None):
    calls = calls if isinstance(calls, list) else []

    def fake_request(prompt, model, model_source, user_id=None):
        calls.append({
            "prompt": prompt,
            "model": model,
            "model_source": model_source,
            "user_id": user_id,
        })
        return payload or ai_payload()

    monkeypatch.setattr(inference, "request_cookbook_item_details_from_openai", fake_request)
    return calls


def test_infer_missing_details_fills_placeholder_menu_item_rows(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe()
    calls = patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_recipe(
        SPRING_ROLL_URL,
        cookbook_id="vel-asian-cuisine",
        cookbook_name="Vel Asian Cuisine",
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)
    cookbook_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]

    assert result["ok"] is True
    assert result["skipped"] is False
    assert len(calls) == 1
    assert "Spring Roll" in calls[0]["prompt"]
    assert "2 veggie golden crispy" in calls[0]["prompt"]
    assert {
        "recipe_amount",
        "servings",
        "yield",
        "level",
        "total_time",
        "prep_time",
        "inactive_time",
        "cook_time",
        "ingredients",
        "equipment",
        "instructions",
    }.issubset(set(result["updated_fields"]))
    assert saved["recipe_amount"] == "2 spring rolls"
    assert saved["servings"] == "1 appetizer serving"
    assert saved["yield"] == "2 pieces"
    assert saved["level"] == "Easy"
    assert saved["total_time"] == "40 minutes"
    assert saved["source_type"] == "menu_item_inferred"
    assert saved["ai_inferred"] is True
    assert saved["inferred_by_model"] == "gpt-test-mini"
    assert saved["inference_confidence"] == "medium"
    assert "ingredients" in saved["cookbook_item_inferred_fields"]
    assert [item["ingredient"] for item in saved["ingredients"]][:2] == [
        "spring roll wrappers",
        "carrot",
    ]
    assert all(item.get("ingredient") or item.get("original_text") for item in saved["ingredients"])
    assert [item["equipment"] for item in saved["equipment"]] == ["Cutting board", "Mixing bowl", "Skillet"]
    assert all(item["instruction"] for item in saved["instructions"])
    assert saved["scaling"]["base_servings"] == "1 appetizer serving"
    assert cookbook_recipe["recipe_amount"] == "2 spring rolls"
    assert cookbook_recipe["servings"] == "1 appetizer serving"
    assert cookbook_recipe["source_type"] == "menu_item_inferred"
    assert cookbook_recipe["equipment_items"] == ["Cutting board", "Mixing bowl", "Skillet"]


def test_preview_only_returns_would_update_fields_without_saving(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    original = seed_cookbook_and_recipe()
    patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_recipe(
        SPRING_ROLL_URL,
        cookbook_id="vel-asian-cuisine",
        preview_only=True,
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert result["preview_only"] is True
    assert "ingredients" in result["would_update_fields"]
    assert saved == original


def test_overwrite_ai_fields_does_not_replace_manual_ingredients(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "user-entered cabbage", "quantity": "1", "unit": "cup"}],
    })
    patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_recipe(
        SPRING_ROLL_URL,
        cookbook_id="vel-asian-cuisine",
        overwrite_ai_fields=True,
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert "ingredients" not in result["updated_fields"]
    assert saved["ingredients"][0]["ingredient"] == "user-entered cabbage"


def test_overwrite_ai_fields_replaces_fields_tagged_from_prior_inference(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "old AI wrapper", "quantity": "2"}],
        inference.INFERRED_FIELD_METADATA_KEY: ["ingredients"],
    })
    patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_recipe(
        SPRING_ROLL_URL,
        cookbook_id="vel-asian-cuisine",
        overwrite_ai_fields=True,
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert "ingredients" in result["updated_fields"]
    assert saved["ingredients"][0]["ingredient"] == "spring roll wrappers"
    assert "old AI wrapper" not in [item["ingredient"] for item in saved["ingredients"]]


def test_cookbook_batch_only_processes_selected_cookbook(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe()
    seed_cookbook_and_recipe(
        url=OTHER_URL,
        recipe_overrides={
            "recipe_title": "Other Soup",
            "menu_item_name": "Other Soup",
            "menu_description": "A different cookbook item.",
        },
        cookbook_id="other-cookbook",
    )
    cookbook_service.save_cookbooks({
        "cookbooks": [
            {
                "id": "vel-asian-cuisine",
                "name": "Vel Asian Cuisine",
                "recipes": [{"url": SPRING_ROLL_URL, "name": "Spring Roll"}],
            },
            {
                "id": "other-cookbook",
                "name": "Other Cookbook",
                "recipes": [{"url": OTHER_URL, "name": "Other Soup"}],
            },
        ]
    })
    calls = patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_cookbook("vel-asian-cuisine")
    selected = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)
    other = recipe_edit_service.load_recipe_output(OTHER_URL)

    assert result["ok"] is True
    assert result["total_found"] == 1
    assert result["updated"] == 1
    assert len(calls) == 1
    assert '"cookbook_id": "vel-asian-cuisine"' in calls[0]["prompt"]
    assert "Other Soup" not in calls[0]["prompt"]
    assert selected["ingredients"][0]["ingredient"] == "spring roll wrappers"
    assert other["ingredients"] == [{"ingredient": "", "original_text": "", "quantity": "", "unit": ""}]


def test_cookbook_item_model_fallback_order(monkeypatch):
    monkeypatch.setattr(inference, "sync_openai_model_environment_from_overrides", lambda: None)
    monkeypatch.setattr(inference, "openai_model_recommendations", lambda: {"mappings": {}})
    monkeypatch.setattr(inference, "default_model_for_env", lambda env_var: "project-mini")
    for env_var in inference.COOKBOOK_ITEM_MODEL_FALLBACK_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)

    model, source = inference.resolve_cookbook_item_model()
    assert model == "project-mini"
    assert source == "default:OPENAI_COOKBOOK_ITEM_MODEL"

    monkeypatch.setenv("OPENAI_RECIPE_MODEL", "recipe-mini")
    model, source = inference.resolve_cookbook_item_model()
    assert (model, source) == ("recipe-mini", "configured:OPENAI_RECIPE_MODEL")

    monkeypatch.setenv("OPENAI_MENU_MODEL", "menu-mini")
    model, source = inference.resolve_cookbook_item_model()
    assert (model, source) == ("menu-mini", "configured:OPENAI_MENU_MODEL")

    monkeypatch.setenv("OPENAI_COOKBOOK_ITEM_MODEL", "cookbook-mini")
    model, source = inference.resolve_cookbook_item_model()
    assert (model, source) == ("cookbook-mini", "configured:OPENAI_COOKBOOK_ITEM_MODEL")
