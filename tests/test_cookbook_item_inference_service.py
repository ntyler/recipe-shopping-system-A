import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
            {
                "name": "spring roll wrappers",
                "quantity": "2",
                "unit": "",
                "notes": "",
                "substitutions": ["rice paper wrappers"],
            },
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
        "recipe_notes": [
            {
                "heading": "Substitutions & Variations",
                "items": ["Use rice paper wrappers for a lighter version."],
            },
            {
                "heading": "Storing & Reheating",
                "items": ["Reheat in a hot oven or air fryer to keep the wrappers crisp."],
            },
            {
                "heading": "Top Tips",
                "items": ["Drain the filling well so the wrappers fry crisp."],
            },
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
        "recipe_notes": [],
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


def patch_ingredient_regeneration_response(monkeypatch, calls=None, payload=None):
    calls = calls if isinstance(calls, list) else []

    def fake_request(prompt, model, model_source, user_id=None):
        calls.append({
            "prompt": prompt,
            "model": model,
            "model_source": model_source,
            "user_id": user_id,
        })
        return payload or json.dumps({
            "ingredients": [
                {
                    "name": "yuca root",
                    "quantity": "2",
                    "unit": "large",
                    "notes": "peeled and cut into sticks",
                    "purchasable_item": "yuca root",
                    "store_section": "MISC",
                },
                {
                    "name": "vegetable oil",
                    "quantity": "2",
                    "unit": "cups",
                    "notes": "for frying",
                    "purchasable_item": "vegetable oil",
                    "store_section": "OIL",
                },
            ],
            "confidence": "high",
            "regeneration_notes": "Built from current editor context.",
        })

    monkeypatch.setattr(inference, "request_recipe_ingredients_regeneration_from_openai", fake_request)
    return calls


def patch_note_regeneration_response(monkeypatch, calls=None, payload=None):
    calls = calls if isinstance(calls, list) else []

    def fake_request(prompt, model, model_source, user_id=None):
        calls.append({
            "prompt": prompt,
            "model": model,
            "model_source": model_source,
            "user_id": user_id,
        })
        return payload or json.dumps({
            "recipe_notes": [
                {
                    "heading": "Substitutions & Variations",
                    "items": ["Swap mushrooms for shredded cabbage."],
                },
                {
                    "heading": "Storing & Reheating",
                    "items": ["Reheat in a hot oven until crisp."],
                },
                {
                    "heading": "Top Tips",
                    "items": ["Keep the filling dry before wrapping."],
                },
            ],
            "confidence": "high",
            "regeneration_notes": "Built from current editor context.",
        })

    monkeypatch.setattr(inference, "request_recipe_notes_regeneration_from_openai", fake_request)
    return calls


def test_regenerate_ingredients_preview_uses_current_editor_context_without_saving(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    original = seed_cookbook_and_recipe(recipe_overrides={
        "recipe_title": "Fried Yuca",
        "ingredients": [{"ingredient": "old parsed yuca", "quantity": "1"}],
        "equipment": [{"equipment": "Dutch oven"}],
        "instructions": [{"instruction": "Boil the yuca until tender."}],
    })
    calls = patch_ingredient_regeneration_response(monkeypatch)

    result = inference.regenerate_ingredients_for_recipe(
        SPRING_ROLL_URL,
        current_recipe={
            "recipe_title": "Garlic Fried Yuca",
            "ingredients": [{"ingredient": "current editor yuca", "quantity": "2"}],
            "equipment": [{"equipment": "Heavy pot"}],
            "instructions": [{"text": "Fry the yuca until crisp."}],
        },
        preview_only=True,
        user_id="editor",
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert result["preview_only"] is True
    assert result["would_update_fields"] == ["ingredients"]
    assert result["ingredients"][0]["ingredient"] == "yuca root"
    assert result["ingredients"][0]["preparation"] == "peeled and cut into sticks"
    assert saved == original
    assert len(calls) == 1
    assert calls[0]["user_id"] == "editor"
    assert "Garlic Fried Yuca" in calls[0]["prompt"]
    assert "current editor yuca" in calls[0]["prompt"]
    assert "Fry the yuca until crisp." in calls[0]["prompt"]
    assert "Regenerate only the Ingredients section" in calls[0]["prompt"]
    assert "stale rows to replace" in calls[0]["prompt"]
    assert "replace the entire current Ingredients section" in calls[0]["prompt"]
    assert '"current_ingredients_role": "stale_rows_to_replace"' in calls[0]["prompt"]
    assert '"preserve_current_ingredients_by_default": false' in calls[0]["prompt"]
    assert "Preserve clearly useful current ingredient details" not in calls[0]["prompt"]


def test_regenerate_ingredients_reclassifies_plain_inca_pepper_as_produce(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "recipe_title": "Papa a la Huancaina",
        "ingredients": [{"ingredient": "old pepper", "quantity": "1"}],
        "instructions": [{"instruction": "Blend the sauce and pour over potatoes."}],
    })
    patch_ingredient_regeneration_response(
        monkeypatch,
        payload=json.dumps({
            "ingredients": [
                {
                    "name": "inca pepper",
                    "quantity": "2",
                    "unit": "tablespoons",
                    "purchasable_item": "inca pepper",
                    "store_section": "SAUCES & CONDIMENTS",
                },
                {
                    "name": "aji amarillo paste",
                    "quantity": "1",
                    "unit": "tablespoon",
                    "purchasable_item": "aji amarillo paste",
                    "store_section": "PRODUCE",
                },
            ],
            "confidence": "high",
        }),
    )

    result = inference.regenerate_ingredients_for_recipe(
        SPRING_ROLL_URL,
        current_recipe={
            "recipe_title": "Papa a la Huancaina",
            "ingredients": [{"ingredient": "old pepper", "quantity": "1"}],
            "instructions": [{"text": "Blend the sauce and pour over potatoes."}],
        },
        preview_only=True,
    )

    assert result["ok"] is True
    assert [item["ingredient"] for item in result["ingredients"]] == [
        "inca pepper",
        "aji amarillo paste",
    ]
    assert [item["store_section"] for item in result["ingredients"]] == [
        "PRODUCE",
        "SAUCES & CONDIMENTS",
    ]


def test_regenerate_ingredients_saves_only_ingredients_and_preserves_recipe_type(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "source_type": "scraped_recipe",
        "ai_inferred": False,
        "recipe_title": "Fried Yuca",
        "ingredients": [{"ingredient": "old parsed yuca", "quantity": "1"}],
        "equipment": [{"equipment": "Dutch oven"}],
        "instructions": [{"instruction": "Boil the yuca until tender."}],
    })
    patch_ingredient_regeneration_response(monkeypatch)

    result = inference.regenerate_ingredients_for_recipe(
        SPRING_ROLL_URL,
        current_recipe={
            "recipe_title": "Fried Yuca",
            "ingredients": [{"ingredient": "old parsed yuca", "quantity": "1"}],
            "equipment": [{"equipment": "Dutch oven"}],
            "instructions": [{"text": "Boil the yuca until tender."}],
        },
        preview_only=False,
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert result["updated_fields"] == ["ingredients"]
    assert saved["source_type"] == "scraped_recipe"
    assert saved["ai_inferred"] is False
    assert saved["equipment"][0]["equipment"] == "Dutch oven"
    assert saved["instructions"][0]["instruction"] == "Boil the yuca until tender."
    assert [item["ingredient"] for item in saved["ingredients"]] == ["yuca root", "vegetable oil"]
    assert saved[inference.INFERRED_FIELD_METADATA_KEY] == ["ingredients"]
    assert saved[inference.INFERRED_FIELD_SOURCE_KEY]["ingredients"] == "ai_regenerated"
    assert saved["ingredients_regenerated_by_model"] == "gpt-test-mini"
    assert saved["ingredients_inference_confidence"] == "high"


def test_regenerate_recipe_notes_preview_uses_current_editor_context_without_saving(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    original = seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "user-entered cabbage", "quantity": "1", "unit": "cup"}],
        "equipment": [{"equipment": "Dutch oven"}],
        "instructions": [{"instruction": "Boil the yuca until tender."}],
        "recipe_notes": [{
            "heading": "Top Tips",
            "items": ["Old note."],
        }],
    })
    calls = patch_note_regeneration_response(monkeypatch)

    result = inference.regenerate_recipe_notes_for_recipe(
        SPRING_ROLL_URL,
        current_recipe={
            **original,
            "recipe_notes": [{
                "heading": "Top Tips",
                "items": ["Current editor note."],
            }],
        },
        cookbook_id="vel-asian-cuisine",
        preview_only=True,
        user_id="editor",
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert result["preview_only"] is True
    assert result["updated_fields"] == ["recipe_notes"]
    assert result["would_update_fields"] == ["recipe_notes"]
    assert result["recipe_notes"][0]["heading"] == "Substitutions & Variations"
    assert result["recipe"]["ingredients"][0]["ingredient"] == "user-entered cabbage"
    assert saved == original
    assert len(calls) == 1
    assert calls[0]["user_id"] == "editor"
    assert "Regenerate only the Recipe Notes section" in calls[0]["prompt"]
    assert "replace_entire_recipe_notes_section" in calls[0]["prompt"]
    assert "Current editor note." in calls[0]["prompt"]


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
        "recipe_notes",
    }.issubset(set(result["updated_fields"]))
    assert "Substitutions & Variations" in calls[0]["prompt"]
    assert "Storing & Reheating" in calls[0]["prompt"]
    assert "Top Tips" in calls[0]["prompt"]
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
    assert saved["ingredients"][0]["substitutions"] == ["rice paper wrappers"]
    assert all(item.get("ingredient") or item.get("original_text") for item in saved["ingredients"])
    assert [item["equipment"] for item in saved["equipment"]] == ["Cutting board", "Mixing bowl", "Skillet"]
    assert all(item["instruction"] for item in saved["instructions"])
    assert saved["recipe_notes"] == [
        {
            "heading": "Substitutions & Variations",
            "items": ["Use rice paper wrappers for a lighter version."],
        },
        {
            "heading": "Storing & Reheating",
            "items": ["Reheat in a hot oven or air fryer to keep the wrappers crisp."],
        },
        {
            "heading": "Top Tips",
            "items": ["Drain the filling well so the wrappers fry crisp."],
        },
    ]
    assert saved["scaling"]["base_servings"] == "1 appetizer serving"
    assert cookbook_recipe["recipe_amount"] == "2 spring rolls"
    assert cookbook_recipe["servings"] == "1 appetizer serving"
    assert cookbook_recipe["source_type"] == "menu_item_inferred"
    assert cookbook_recipe["equipment_items"] == ["Cutting board", "Mixing bowl", "Skillet"]
    assert cookbook_recipe["recipe_notes"][0]["heading"] == "Substitutions & Variations"


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
    assert "recipe_notes" in result["would_update_fields"]
    assert result["recipe"]["recipe_notes"][0]["heading"] == "Substitutions & Variations"
    assert saved == original


def test_overwrite_ai_fields_does_not_replace_manual_ingredients(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "user-entered cabbage", "quantity": "1", "unit": "cup"}],
        "recipe_notes": [{
            "heading": "Top Tips",
            "items": ["User-entered note stays put."],
        }],
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
    assert "recipe_notes" not in result["updated_fields"]
    assert saved["ingredients"][0]["ingredient"] == "user-entered cabbage"
    assert saved["recipe_notes"] == [{
        "heading": "Top Tips",
        "items": ["User-entered note stays put."],
    }]


def test_rerun_prediction_can_force_recipe_notes_without_replacing_manual_ingredients(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    original = seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "user-entered cabbage", "quantity": "1", "unit": "cup"}],
        "recipe_notes": [{
            "heading": "Top Tips",
            "items": ["Old editor note."],
        }],
    })
    calls = patch_openai_response(monkeypatch)

    result = inference.infer_missing_details_for_recipe(
        SPRING_ROLL_URL,
        cookbook_id="vel-asian-cuisine",
        overwrite_ai_fields=True,
        preview_only=True,
        current_recipe={
            **original,
            "recipe_notes": [{
                "heading": "Top Tips",
                "items": ["Current editor note should be visible to AI."],
            }],
        },
        force_fields=["recipe_notes"],
    )
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)

    assert result["ok"] is True
    assert result["preview_only"] is True
    assert "recipe_notes" in result["would_update_fields"]
    assert "ingredients" not in result["would_update_fields"]
    assert result["recipe"]["recipe_notes"][0]["heading"] == "Substitutions & Variations"
    assert result["recipe"]["ingredients"][0]["ingredient"] == "user-entered cabbage"
    assert saved == original
    assert "Current editor note should be visible to AI." in calls[0]["prompt"]
    assert "recipe_notes" in calls[0]["prompt"]


def test_overwrite_ai_fields_replaces_fields_tagged_from_prior_inference(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "ingredients": [{"ingredient": "old AI wrapper", "quantity": "2"}],
        "recipe_notes": [{
            "heading": "Top Tips",
            "items": ["Old AI note."],
        }],
        inference.INFERRED_FIELD_METADATA_KEY: ["ingredients", "recipe_notes"],
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
    assert "recipe_notes" in result["updated_fields"]
    assert saved["ingredients"][0]["ingredient"] == "spring roll wrappers"
    assert "old AI wrapper" not in [item["ingredient"] for item in saved["ingredients"]]
    assert saved["recipe_notes"][0]["heading"] == "Substitutions & Variations"


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


def test_cookbook_batch_generates_explicit_menu_stubs(monkeypatch, tmp_path):
    configure_inference_storage(monkeypatch, tmp_path)
    seed_cookbook_and_recipe(recipe_overrides={
        "needs_ai_recipe": True,
        "recipe_status": "stub",
        "ingredients": [],
        "equipment": [],
        "instructions": [],
        "recipe_inference": {"status": "not_generated"},
    })
    calls = []

    def fail_cookbook_detail_request(*_args, **_kwargs):
        raise AssertionError("Explicit menu stubs should use menu recipe generation")

    def fake_menu_batch(entries, user_id=None):
        calls.append({"entries": entries, "user_id": user_id})
        items = {}
        for entry in entries:
            item_id = entry["menu_item"]["menu_item_id"]
            items[item_id] = {
                "servings": "1 appetizer serving",
                "predicted_ingredients": [
                    {"ingredient": "spring roll wrappers", "quantity": "2", "unit": ""},
                    {"ingredient": "shredded carrots", "quantity": "1/2", "unit": "cup"},
                ],
                "predicted_equipment": ["skillet"],
                "predicted_instructions": [
                    "Fill the wrappers with vegetables.",
                    "Pan-fry until crisp.",
                ],
                "confidence": 0.74,
            }
        return {
            "ok": True,
            "items": items,
            "model": "menu-test-model",
            "model_source": "test:OPENAI_MENU_MODEL",
        }

    monkeypatch.setattr(inference, "request_cookbook_item_details_from_openai", fail_cookbook_detail_request)
    monkeypatch.setattr(inference, "infer_menu_item_recipe_batch", fake_menu_batch)

    result = inference.infer_missing_details_for_cookbook("vel-asian-cuisine", user_id="owner")
    saved = recipe_edit_service.load_recipe_output(SPRING_ROLL_URL)
    cookbook_recipe = cookbook_service.load_cookbooks()["cookbooks"][0]["recipes"][0]

    assert result["ok"] is True
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert len(calls) == 1
    assert calls[0]["user_id"] == "owner"
    assert saved["needs_ai_recipe"] is False
    assert saved["recipe_status"] == "generated"
    assert saved["ingredients"][0]["ingredient"] == "spring roll wrappers"
    assert saved["instructions"][0]["instruction"] == "Fill the wrappers with vegetables."
    assert cookbook_recipe["needs_ai_recipe"] is False
    assert cookbook_recipe["recipe_status"] == "generated"
    assert cookbook_recipe["servings"] == "1 appetizer serving"
    assert cookbook_recipe["equipment_items"] == ["skillet"]


def cookbook_batch_entry(index):
    return {
        "recipe_url": f"menu-item://vel-asian-cuisine/item-{index}",
        "menu_item": {
            "menu_item_id": f"item-{index}",
            "item_name": f"Item {index}",
            "menu_section": "Entrees",
        },
    }


def test_cookbook_item_batches_default_smaller_than_menu_batches(monkeypatch):
    monkeypatch.delenv(inference.COOKBOOK_ITEM_BATCH_INFERENCE_MAX_ITEMS_ENV_VAR, raising=False)
    monkeypatch.delenv(inference.COOKBOOK_ITEM_BATCH_INFERENCE_MIN_ITEMS_ENV_VAR, raising=False)
    monkeypatch.delenv(inference.COOKBOOK_ITEM_BATCH_INFERENCE_TARGET_CHARS_ENV_VAR, raising=False)
    entries = [cookbook_batch_entry(index) for index in range(22)]

    batches = inference.cookbook_item_inference_batches(entries)

    assert [len(batch) for batch in batches] == [8, 8, 6]


def test_cookbook_menu_stub_batch_uses_cookbook_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        inference,
        "resolve_cookbook_item_model",
        lambda: ("cookbook-mini", "configured:OPENAI_COOKBOOK_ITEM_MODEL"),
    )

    def fake_build_payload(model, endpoint_name, messages, response_format=None, temperature=None, **extra_kwargs):
        captured["model"] = model
        captured["endpoint_name"] = endpoint_name
        captured["messages"] = messages
        captured["response_format"] = response_format
        captured["temperature"] = temperature
        return {"model": model, "messages": messages}, True, model

    def fake_completion(_client, payload, action_name="", model="", kind=""):
        captured["payload_model"] = payload["model"]
        captured["action_name"] = action_name
        captured["completion_model"] = model
        captured["kind"] = kind
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({
                            "item-1": {
                                "predicted_ingredients": [{"ingredient": "ginger"}],
                                "predicted_equipment": ["skillet"],
                                "predicted_instructions": ["Cook until hot."],
                            }
                        })
                    )
                )
            ]
        )

    monkeypatch.setattr(inference, "build_openai_chat_payload", fake_build_payload)
    monkeypatch.setattr(inference, "get_openai_client", lambda: object())
    monkeypatch.setattr(inference, "throttled_chat_completion", fake_completion)
    monkeypatch.setattr(inference, "record_openai_usage", lambda *args, **kwargs: None)

    result = inference.infer_menu_item_recipe_batch([cookbook_batch_entry(1)], user_id="owner")

    assert result["ok"] is True
    assert result["model"] == "cookbook-mini"
    assert result["model_source"] == "configured:OPENAI_COOKBOOK_ITEM_MODEL"
    assert "item-1" in result["items"]
    assert captured["model"] == "cookbook-mini"
    assert captured["endpoint_name"] == inference.COOKBOOK_ITEM_BATCH_INFERENCE_ACTION
    assert captured["action_name"] == inference.COOKBOOK_ITEM_BATCH_INFERENCE_ACTION
    assert captured["completion_model"] == "cookbook-mini"
    assert captured["kind"] == "menu"


def test_cookbook_menu_stub_batch_splits_timeout_and_combines_results(monkeypatch):
    entries = [cookbook_batch_entry(index) for index in range(4)]
    calls = []

    def fake_once(batch, user_id=None):
        calls.append({"size": len(batch), "user_id": user_id})
        if len(batch) > 1:
            return {
                "ok": False,
                "items": {},
                "failures": {},
                "error_code": "OPENAI_TIMEOUT",
                "error_message": "Request timed out.",
                "technical_message": "Request timed out.",
                "exception_type": "APITimeoutError",
                "model": "cookbook-mini",
                "model_source": "configured:OPENAI_COOKBOOK_ITEM_MODEL",
            }
        item_id = batch[0]["menu_item"]["menu_item_id"]
        return {
            "ok": True,
            "items": {
                item_id: {
                    "predicted_ingredients": [{"ingredient": item_id}],
                    "predicted_equipment": ["skillet"],
                    "predicted_instructions": ["Cook it."],
                }
            },
            "failures": {},
            "model": "cookbook-mini",
            "model_source": "configured:OPENAI_COOKBOOK_ITEM_MODEL",
        }

    monkeypatch.setattr(inference, "_infer_menu_item_recipe_batch_once", fake_once)

    result = inference.infer_menu_item_recipe_batch(entries, user_id="owner")

    assert result["ok"] is True
    assert sorted(result["items"]) == ["item-0", "item-1", "item-2", "item-3"]
    assert result["failures"] == {}
    assert [call["size"] for call in calls] == [4, 2, 1, 1, 2, 1, 1]
    assert all(call["user_id"] == "owner" for call in calls)


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
