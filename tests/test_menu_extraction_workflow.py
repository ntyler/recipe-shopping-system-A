import json
import time
from pathlib import Path

from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import openai_model_service
from PushShoppingList.services import recipe_extract_service


def configure_menu_model_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_model_service, "MODEL_OVERRIDES_FILE", tmp_path / "openai_model_overrides.json")
    monkeypatch.delenv("OPENAI_MENU_MODEL", raising=False)


def test_default_menu_nutrition_inference_contains_full_nutrition_fields():
    inference = menu_mega_json_service.default_nutrition_inference()

    for field in [
        "serving_basis",
        "calories",
        "carbohydrates",
        "protein",
        "fat",
        "saturated_fat",
        "polyunsaturated_fat",
        "monounsaturated_fat",
        "trans_fat",
        "cholesterol",
        "sodium",
        "potassium",
        "fiber",
        "sugar",
        "vitamin_a",
        "vitamin_c",
        "calcium",
        "iron",
    ]:
        assert field in inference
        assert inference[field] is None

    assert inference["other"] == []
    assert inference["status"] == "not_generated"
    assert inference["calories_per_serving"] is None
    assert inference["protein_g"] is None
    assert inference["carbs_g"] is None
    assert inference["fat_g"] is None
    assert inference["sodium_mg"] is None


def test_menu_nutrition_inference_from_rows_maps_full_nutrition_fields(monkeypatch):
    monkeypatch.setattr(recipe_routes, "_utc_now_iso", lambda: "2026-06-13T12:00:00Z")

    inference = recipe_routes._menu_nutrition_inference_from_rows(
        [
            {"key": "serving_basis", "value": "per bowl"},
            {"key": "calories", "value": "659 kcal"},
            {"key": "carbohydrates", "value": "57 g"},
            {"key": "protein", "value": "17 g"},
            {"key": "fat", "value": "40 g"},
            {"key": "saturated_fat", "value": "16 g"},
            {"key": "cholesterol", "value": "37 mg"},
            {"key": "sodium", "value": "649 mg"},
            {"key": "fiber", "value": "3 g"},
            {"key": "sugar", "value": "0.2 g"},
            {"key": "caffeine", "value": "2 mg"},
        ],
        model="gpt-test",
    )

    assert inference["status"] == "generated"
    assert inference["serving_basis"] == "per bowl"
    assert inference["servings"] == "per bowl"
    assert inference["calories"] == "659 kcal"
    assert inference["carbohydrates"] == "57 g"
    assert inference["protein"] == "17 g"
    assert inference["fat"] == "40 g"
    assert inference["saturated_fat"] == "16 g"
    assert inference["cholesterol"] == "37 mg"
    assert inference["sodium"] == "649 mg"
    assert inference["fiber"] == "3 g"
    assert inference["sugar"] == "0.2 g"
    assert inference["calories_per_serving"] == 659
    assert inference["protein_g"] == 17
    assert inference["carbs_g"] == 57
    assert inference["fat_g"] == 40
    assert inference["sodium_mg"] == 649
    assert inference["other"] == [{"name": "caffeine", "value": "2 mg"}]
    assert inference["model"] == "gpt-test"
    assert inference["generated_at"] == "2026-06-13T12:00:00Z"


def test_cartana_menu_payload_extracts_sections_items_and_prices():
    payload = [
        {
            "menu": {
                "menuId": "MEN1",
                "menuData": {
                    "enMenuTitle": "Kitchen Appetizers",
                    "enMenuText": "Appetizers from the Kitchen",
                },
            },
            "itemList": [
                {
                    "price": 5.99,
                    "menuItemId": "MIT1",
                    "menuItemData": {
                        "enItemTitle": "Spring Roll",
                        "enItemText": "2 veggie golden crispy rolls.",
                    },
                    "isSpicy": False,
                    "isVeggie": True,
                }
            ],
        }
    ]

    sections = recipe_extract_service.parse_cartana_menu_sections(
        payload,
        "https://example.com/menu_home.action?resInput=RES1",
    )
    items = recipe_extract_service.flatten_menu_sections(sections)

    assert len(sections) == 1
    assert len(items) == 1
    assert items[0]["item_name"] == "Spring Roll"
    assert items[0]["menu_section"] == "Kitchen Appetizers"
    assert items[0]["description"] == "2 veggie golden crispy rolls."
    assert items[0]["price"] == "$5.99"


def test_mega_menu_json_snapshot_builds_saves_and_unpacks(tmp_path, monkeypatch):
    monkeypatch.setattr(menu_mega_json_service, "workspace_data_root", lambda: tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    sections = [
        {
            "section_name": "Kitchen Appetizers",
            "description": "Appetizers from the Kitchen",
            "items": [
                {
                    "item_name": "Spring Roll",
                    "description": "2 veggie golden crispy rolls.",
                    "price": "$5.99",
                    "menu_item_id": "MIT1",
                    "menu_id": "MEN1",
                    "is_veggie": True,
                }
            ],
        }
    ]

    mega_json = menu_mega_json_service.build_mega_menu_json(
        source_url,
        sections,
        extracted_text="Vel Asian Cuisine Spring Roll $5.99",
        diagnostics={
            "final_url": source_url,
            "http_status": 200,
            "content_type": "text/html",
            "restaurant": {"restaurant_name": "Vel Asian Cuisine"},
            "menu_extraction_source": "cartana_api",
        },
        html_text="<html><title>Vel Asian Cuisine</title><a href='/rs/menu_home.action'>Menu</a></html>",
        html_snapshot_path=str(tmp_path / "vel.html"),
    )
    snapshot = menu_mega_json_service.save_menu_mega_json_snapshot(
        mega_json,
        job_id="job-1",
        cookbook_id="cb1",
        cookbook_name="Dinner",
    )
    loaded = menu_mega_json_service.load_menu_mega_json_snapshot(snapshot["id"])
    unpacked = menu_mega_json_service.unpack_mega_menu_json_to_sections(
        loaded["menu_mega_json"],
        snapshot_id=loaded["id"],
    )

    assert loaded["item_count"] == 1
    assert loaded["section_count"] == 1
    assert loaded["menu_mega_json"]["schema_version"] == "menu_mega_json_v1"
    assert loaded["menu_mega_json"]["source"]["source_url"] == source_url
    assert loaded["menu_mega_json"]["restaurant"]["name"] == "Vel Asian Cuisine"
    assert loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0]["name"] == "Spring Roll"
    assert loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0]["price"] == 5.99
    assert loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0]["recipe_inference"]["status"] == "not_generated"
    assert loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0]["nutrition_inference"]["status"] == "not_generated"
    assert loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0]["pdf_generation"]["status"] == "not_generated"
    assert loaded["menu_mega_json"]["extraction"]["used_openai"] is False
    assert loaded["job_id"] == "job-1"
    assert loaded["import_job_id"] == "job-1"
    assert loaded["cookbook_id"] == "cb1"
    assert loaded["cookbook_name"] == "Dinner"
    assert loaded["duplicate_count"] == 0
    assert unpacked[0]["items"][0]["parent_menu_snapshot_id"] == loaded["id"]
    assert unpacked[0]["items"][0]["price"] == "$5.99"

    loaded["menu_mega_json"]["menu"]["sections"][0]["items"][0].update({
        "normalized_name": "Crispy Spring Roll",
        "normalized_section_name": "Appetizers",
        "item_type": "food",
        "broad_category": "appetizer",
        "should_create_recipe_stub": False,
        "cleanup_notes": ["duplicate"],
    })
    cleaned_unpack = menu_mega_json_service.unpack_mega_menu_json_to_sections(
        loaded["menu_mega_json"],
        snapshot_id=loaded["id"],
    )
    cleaned_item = cleaned_unpack[0]["items"][0]
    assert cleaned_item["item_name"] == "Crispy Spring Roll"
    assert cleaned_item["original_item_name"] == "Spring Roll"
    assert cleaned_item["menu_section"] == "Appetizers"
    assert cleaned_item["should_create_recipe"] is False
    assert cleaned_item["skip_reason"] == "duplicate"


def test_menu_stub_url_import_saves_mega_snapshot_and_parent_traceability(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_MENU_CLEANUP_ENABLED", raising=False)
    monkeypatch.setattr(menu_mega_json_service, "workspace_data_root", lambda: tmp_path)
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    payload = [
        {
            "menu": {
                "menuId": "MEN1",
                "menuData": {
                    "enMenuTitle": "Kitchen Appetizers",
                    "enMenuText": "Appetizers from the Kitchen",
                },
            },
            "itemList": [
                {
                    "price": 5.99,
                    "menuItemId": "MIT1",
                    "menuItemData": {
                        "enItemTitle": "Spring Roll",
                        "enItemText": "2 veggie golden crispy rolls.",
                    },
                    "isVeggie": True,
                }
            ],
        }
    ]
    saved = []
    progress_messages = []

    def fake_fetch_menu_page_html(url, cancellation_check=None, return_metadata=False):
        html = "<html><title>Vel Asian Cuisine</title><script>getRestaurantMenu_home.action</script></html>"
        metadata = {
            "final_url": url,
            "http_status": 200,
            "content_type": "text/html",
            "fetched_at": "2026-06-13T00:00:00Z",
        }
        return (html, metadata) if return_metadata else html

    def fail_openai(*_args, **_kwargs):
        raise AssertionError("Default menu URL import should not call OpenAI")

    monkeypatch.setattr(recipe_extract_service, "fetch_menu_page_html", fake_fetch_menu_page_html)
    monkeypatch.setattr(recipe_extract_service, "fetch_cartana_menu_payload", lambda url, html, cancellation_check=None: (payload, {"ok": True}))
    monkeypatch.setattr(recipe_extract_service, "send_menu_cleanup_prompt_to_openai", fail_openai)
    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe", fail_openai)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: saved.append((recipe_url, dict(json_data))) or tmp_path / "stub.json",
    )

    result = recipe_extract_service.extract_menu_stubs_from_url(
        source_url,
        progress_callback=lambda message, summary=None: progress_messages.append(message),
    )
    snapshot = menu_mega_json_service.load_menu_mega_json_snapshot(result["menu_mega_snapshot_id"])

    assert result["ok"] is True
    assert result["menu_mega_json_saved"] is True
    assert result["stubs_created"] == 1
    assert result["item_records_unpacked"] == 1
    assert result["openai_calls_used"] == 0
    assert "Building mega menu JSON" in progress_messages
    assert "Saving mega menu JSON" in progress_messages
    assert "Unpacking mega menu JSON into item JSON records" in progress_messages
    assert snapshot["menu_mega_json"]["source"]["http_status"] == 200
    assert snapshot["menu_mega_json"]["menu"]["sections"][0]["items"][0]["name"] == "Spring Roll"
    assert saved[0][1]["source_type"] == "menu_item_stub"
    assert saved[0][1]["parent_menu_snapshot_id"] == snapshot["id"]
    assert saved[0][1]["source_metadata"]["parent_menu_snapshot_id"] == snapshot["id"]
    assert saved[0][1]["recipe_inference"]["status"] == "not_generated"
    assert saved[0][1]["nutrition_inference"]["status"] == "not_generated"
    assert saved[0][1]["pdf_generation"]["status"] == "not_generated"


def test_mega_menu_json_viewer_static_hooks_are_present():
    template = Path("PushShoppingList/templates/sections/current_recipe_url_log.html").read_text(encoding="utf-8")
    script = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = Path("PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert "View Mega Menu JSON" in template
    assert "viewMegaMenuJson(this, event)" in template
    assert "copyMegaMenuJson" in script
    assert "downloadMegaMenuJson" in script
    assert "runFullRoutineForMenuSection" in script
    assert "runFullRoutineForAllMenuRecipes" in script
    assert "/api/menu_mega_json_snapshots/" in script
    assert "/api/menu_mega_json_snapshots/<snapshot_id>/download" in routes
    assert "/api/menu_mega_json_snapshots/<snapshot_id>/retry-unpack" in routes
    assert "api_menu_mega_json_snapshot_route" in routes
    assert "Run Full Routine for All" in template
    assert "Run Section Routine" in template


def test_menu_item_result_preserves_original_menu_url_and_unique_record_url(monkeypatch, tmp_path):
    configure_menu_model_defaults(monkeypatch, tmp_path)
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    sections = [
        {
            "section_name": "Entrees",
            "items": [
                {
                    "item_name": "Basil Chicken",
                    "menu_section": "Entrees",
                    "description": "Chicken with basil sauce.",
                    "price": "$13.99",
                    "source_url": source_url,
                }
            ],
        }
    ]

    def fake_infer(menu_url, item, index, total):
        return {
            "recipe_title": item["item_name"],
            "ingredients": [
                {
                    "quantity": "1",
                    "unit": "pound",
                    "ingredient": "chicken",
                    "original_text": "1 pound chicken",
                }
            ],
            "instructions": [
                {"step": 1, "instruction": "Stir fry the chicken with basil sauce."}
            ],
        }, {
            "ok": True,
            "raw_response": "{}",
        }

    saved = []
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe", fake_infer)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: saved.append((recipe_url, dict(json_data))) or tmp_path / "recipe.json",
    )

    result = recipe_extract_service.build_menu_extract_result_from_items(
        source_url,
        sections,
        diagnostics={"menu_page_fetched": True},
    )

    assert result["ok"] is True
    assert result["menu_sections_found"] == 1
    assert result["menu_items_found"] == 1
    assert result["recipes_created"] == 1
    assert result["model_used"] == "gpt-5.5"
    assert result["model_source"] == "default:gpt-5.5"
    assert result["recipes"][0]["source_url"].startswith(source_url + "&menu_item=")
    assert saved[0][1]["source_url"] == source_url
    assert saved[0][1]["recipe_record_url"].startswith(source_url + "&menu_item=")
    assert saved[0][1]["menu_description"] == "Chicken with basil sauce."
    assert saved[0][1]["menu_price"] == "$13.99"


def test_menu_item_parallel_inference_preserves_original_menu_order(monkeypatch, tmp_path):
    configure_menu_model_defaults(monkeypatch, tmp_path)
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    sections = [
        {
            "section_name": "Entrees",
            "items": [
                {
                    "item_name": f"Dish {index}",
                    "menu_section": "Entrees",
                    "description": f"Description {index}",
                    "price": "$10.00",
                    "source_url": source_url,
                }
                for index in range(4)
            ],
        }
    ]
    completion_order = []

    def fake_infer(menu_url, item, index, total, user_id=None):
        if index == 0:
            time.sleep(0.15)
        completion_order.append(index)
        return {
            "recipe_title": item["item_name"],
            "ingredients": [
                {
                    "quantity": "1",
                    "unit": "cup",
                    "ingredient": f"ingredient {index}",
                    "original_text": f"1 cup ingredient {index}",
                }
            ],
            "instructions": [
                {"step": 1, "instruction": f"Cook dish {index}."}
            ],
        }, {
            "ok": True,
            "raw_response": "{}",
        }

    saved = []
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "MENU_ITEM_INFERENCE_WORKERS", 4)
    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe", fake_infer)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: saved.append((recipe_url, dict(json_data))) or tmp_path / "recipe.json",
    )

    result = recipe_extract_service.build_menu_extract_result_from_items(
        source_url,
        sections,
        diagnostics={"menu_page_fetched": True},
    )

    assert result["ok"] is True
    assert result["debug"]["menu_item_inference_workers"] == 4
    assert completion_order[0] != 0
    assert [data["recipe_title"] for _url, data in saved] == [
        "Dish 0",
        "Dish 1",
        "Dish 2",
        "Dish 3",
    ]


def test_menu_item_inference_progress_shows_openai_menu_model_env_var(monkeypatch, tmp_path):
    configure_menu_model_defaults(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_MENU_MODEL", "gpt-4o-mini")
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    sections = [
        {
            "section_name": "Entrees",
            "items": [
                {
                    "item_name": "Basil Chicken",
                    "menu_section": "Entrees",
                    "description": "Chicken with basil sauce.",
                    "source_url": source_url,
                }
            ],
        }
    ]
    progress_messages = []

    def fake_infer(menu_url, item, index, total, user_id=None):
        return {
            "recipe_title": item["item_name"],
            "ingredients": [
                {
                    "quantity": "1",
                    "unit": "pound",
                    "ingredient": "chicken",
                    "original_text": "1 pound chicken",
                }
            ],
            "instructions": [
                {"step": 1, "instruction": "Stir fry the chicken with basil sauce."}
            ],
        }, {
            "ok": True,
            "raw_response": "{}",
        }

    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe", fake_infer)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: tmp_path / "recipe.json",
    )

    result = recipe_extract_service.build_menu_extract_result_from_items(
        source_url,
        sections,
        diagnostics={"menu_page_fetched": True},
        progress_callback=lambda message, summary=None: progress_messages.append(message),
    )

    assert result["ok"] is True
    assert result["model_used"] == "gpt-4o-mini"
    assert result["model_source"] == "environment:OPENAI_MENU_MODEL"
    assert progress_messages[0] == "Inferring recipes with gpt-4o-mini via OPENAI_MENU_MODEL"
    assert progress_messages[-1] == "Inferring recipes with gpt-4o-mini via OPENAI_MENU_MODEL (1/1)"


def test_menu_item_inference_uses_changed_override_file_without_restart(monkeypatch, tmp_path):
    configure_menu_model_defaults(monkeypatch, tmp_path)

    initial = recipe_extract_service.menu_item_recipe_model_resolution()
    assert initial.model == "gpt-5.5"
    assert initial.source == "default:gpt-5.5"

    openai_model_service.MODEL_OVERRIDES_FILE.write_text(
        json.dumps({"models": {"OPENAI_MENU_MODEL": "gpt-4o-mini"}}),
        encoding="utf-8",
    )

    changed = recipe_extract_service.menu_item_recipe_model_resolution()

    assert changed.model == "gpt-4o-mini"
    assert changed.source == "environment:OPENAI_MENU_MODEL"
    assert recipe_extract_service.menu_item_inference_progress_message(changed) == (
        "Inferring recipes with gpt-4o-mini via OPENAI_MENU_MODEL"
    )


def test_menu_stub_result_is_deterministic_without_openai(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_MENU_CLEANUP_ENABLED", raising=False)
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    sections = [
        {
            "section_name": "Entrees",
            "items": [
                {
                    "item_name": "Basil Chicken",
                    "menu_section": "Entrees",
                    "description": "Chicken with basil sauce.",
                    "price": "$13.99",
                    "source_url": source_url,
                    "menu_item_id": "MIT1",
                }
            ],
        }
    ]

    def fail_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI should not be called for default menu stubs")

    saved = []
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "send_menu_cleanup_prompt_to_openai", fail_openai)
    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe", fail_openai)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: saved.append((recipe_url, dict(json_data))) or tmp_path / "stub.json",
    )

    result = recipe_extract_service.build_menu_stub_extract_result_from_items(
        source_url,
        sections,
        diagnostics={"menu_page_fetched": True},
    )

    assert result["ok"] is True
    assert result["staged_import"] is True
    assert result["stubs_created"] == 1
    assert result["openai_calls_used"] == 0
    assert result["recipes"][0]["source_type"] == "menu_item_stub"
    assert result["recipes"][0]["needs_ai_recipe"] is True
    assert result["recipes"][0]["recipe_status"] == "stub"
    assert result["recipes"][0]["ingredients"] == []
    assert result["recipes"][0]["recipe_inference"]["status"] == "not_generated"
    assert result["recipes"][0]["nutrition_inference"]["status"] == "not_generated"
    assert result["recipes"][0]["pdf_generation"]["status"] == "not_generated"
    assert saved[0][1]["source_menu_url"] == source_url
    assert saved[0][1]["menu_item_id"] == "MIT1"


def test_menu_stub_optional_cleanup_is_one_batch_call_and_skips_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_MENU_CLEANUP_ENABLED", "true")
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    sections = [
        {
            "section_name": "Entrees",
            "items": [
                {"item_name": "Basil Chicken", "menu_section": "Entrees", "description": "A", "price": "$10"},
                {"item_name": "Basil Chicken", "menu_section": "Entrees", "description": "A", "price": "$10"},
            ],
        }
    ]
    calls = []

    def fake_cleanup(prompt_text, action_name="menu-cleanup"):
        calls.append((prompt_text, action_name))
        return json.dumps({
            "items": [
                {
                    "index": 0,
                    "normalized_item_name": "Thai Basil Chicken",
                    "normalized_section_name": "Entrees",
                    "item_type": "food",
                    "broad_category": "stir fry",
                    "duplicate_of_index": None,
                    "should_create_recipe": True,
                    "predicted_equipment": [
                        {"name": "wok", "category": "cookware", "confidence": 0.8},
                        {"name": "chef knife", "category": "prep"},
                    ],
                },
                {
                    "index": 1,
                    "normalized_item_name": "Thai Basil Chicken",
                    "normalized_section_name": "Entrees",
                    "item_type": "food",
                    "broad_category": "stir fry",
                    "duplicate_of_index": 0,
                    "should_create_recipe": False,
                    "skip_reason": "duplicate",
                },
            ]
        }), {
            "ok": True,
            "model": "gpt-4o-mini",
            "model_source": "default:gpt-4o-mini",
            "usage": {"total_tokens": 123},
        }

    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(recipe_extract_service, "send_menu_cleanup_prompt_to_openai", fake_cleanup)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: tmp_path / "stub.json",
    )

    result = recipe_extract_service.build_menu_stub_extract_result_from_items(
        source_url,
        sections,
        diagnostics={"menu_page_fetched": True},
    )

    assert len(calls) == 1
    assert result["ok"] is True
    assert result["stubs_created"] == 1
    assert result["duplicates_skipped"] == 1
    assert result["openai_calls_used"] == 1
    assert result["estimated_token_usage"]["total_tokens"] == 123
    assert result["recipes"][0]["recipe_title"] == "Thai Basil Chicken"
    assert result["recipes"][0]["equipment"] == [
        {"name": "wok", "category": "cookware", "confidence": 0.8},
        {"name": "chef knife", "category": "prep"},
    ]
    assert result["recipes"][0]["recipe_inference"]["status"] == "equipment_predicted"
    assert result["recipes"][0]["recipe_inference"]["equipment"] == result["recipes"][0]["equipment"]


def test_menu_stub_url_import_updates_snapshot_with_cookbook_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_MENU_CLEANUP_ENABLED", "true")
    monkeypatch.setattr(menu_mega_json_service, "workspace_data_root", lambda: tmp_path)
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    payload = [
        {
            "menu": {"menuId": "MEN1", "menuData": {"enMenuTitle": "Kitchen Appetizers"}},
            "itemList": [
                {
                    "price": 5.99,
                    "menuItemId": "MIT1",
                    "menuItemData": {
                        "enItemTitle": "Spring Roll",
                        "enItemText": "2 veggie golden crispy rolls.",
                    },
                }
            ],
        }
    ]

    def fake_fetch_menu_page_html(url, cancellation_check=None, return_metadata=False):
        html = "<html><title>Vel Asian Cuisine</title></html>"
        metadata = {"final_url": url, "http_status": 200, "content_type": "text/html"}
        return (html, metadata) if return_metadata else html

    def fake_cleanup(prompt_text, action_name="menu-cleanup"):
        return json.dumps({
            "items": [
                {
                    "index": 0,
                    "normalized_item_name": "Crispy Spring Roll",
                    "normalized_section_name": "Appetizers",
                    "item_type": "food",
                    "broad_category": "appetizer",
                    "should_create_recipe": True,
                    "predicted_equipment": [
                        {"name": "deep skillet", "category": "cookware"},
                        {"name": "tongs", "category": "utensil"},
                    ],
                }
            ]
        }), {
            "ok": True,
            "model": "gpt-4o-mini",
            "model_source": "default:gpt-4o-mini",
            "usage": {"total_tokens": 42},
        }

    monkeypatch.setattr(recipe_extract_service, "fetch_menu_page_html", fake_fetch_menu_page_html)
    monkeypatch.setattr(recipe_extract_service, "fetch_cartana_menu_payload", lambda url, html, cancellation_check=None: (payload, {"ok": True}))
    monkeypatch.setattr(recipe_extract_service, "send_menu_cleanup_prompt_to_openai", fake_cleanup)
    monkeypatch.setattr(recipe_extract_service, "save_extracted_recipe_json", lambda recipe_url, json_data: tmp_path / "stub.json")

    result = recipe_extract_service.extract_menu_stubs_from_url(
        source_url,
        import_job_id="job-123",
        cookbook_id="cb1",
        cookbook_name="Dinner",
    )
    snapshot = menu_mega_json_service.load_menu_mega_json_snapshot(result["menu_mega_snapshot_id"])
    item = snapshot["menu_mega_json"]["menu"]["sections"][0]["items"][0]

    assert snapshot["import_job_id"] == "job-123"
    assert snapshot["cookbook_id"] == "cb1"
    assert snapshot["cookbook_name"] == "Dinner"
    assert snapshot["used_openai"] is True
    assert snapshot["openai_model"] == "gpt-4o-mini"
    assert item["name"] == "Spring Roll"
    assert item["normalized_name"] == "Crispy Spring Roll"
    assert item["normalized_section_name"] == "Appetizers"
    assert item["item_type"] == "food"
    assert item["recipe_inference"]["status"] == "equipment_predicted"
    assert item["recipe_inference"]["equipment"] == [
        {"name": "deep skillet", "category": "cookware"},
        {"name": "tongs", "category": "utensil"},
    ]
    assert item["metadata"]["predicted_equipment_count"] == 2


def test_menu_stub_predicted_equipment_is_passed_to_full_recipe_prompt():
    stub = {
        "recipe_title": "Thai Basil Chicken",
        "menu_section": "Entrees",
        "menu_description": "Chicken with basil sauce.",
        "source_menu_url": "https://example.com/menu",
        "equipment": [
            {"name": "wok", "category": "cookware"},
            {"name": "chef knife", "category": "prep"},
        ],
        "recipe_inference": {
            "status": "equipment_predicted",
            "equipment": [{"name": "wok"}],
        },
    }

    menu_item = recipe_extract_service.menu_stub_item_from_recipe(stub)
    prompt = recipe_extract_service.build_menu_item_recipe_prompt(
        "https://example.com/menu",
        menu_item,
        0,
        1,
    )

    assert menu_item["predicted_equipment"] == [
        {"name": "wok", "category": "cookware"},
        {"name": "chef knife", "category": "prep"},
    ]
    assert "Predicted equipment hint: wok, chef knife" in prompt
    assert "Use the predicted equipment hint only when it fits" in prompt


def test_commit_menu_import_stubs_skips_full_routine(monkeypatch, tmp_path):
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    recipe_url = source_url + "&menu_item=menu-item-1-basil"
    stub = {
        "ok": True,
        "source_url": recipe_url,
        "display_name": "Basil Chicken",
        "recipe_title": "Basil Chicken",
        "source_type": "menu_item_stub",
        "ai_inferred": False,
        "needs_ai_recipe": True,
        "recipe_status": "stub",
        "ingredients": [],
        "raw": {
            "source_type": "menu_item_stub",
            "recipe_title": "Basil Chicken",
            "source_url": recipe_url,
            "source_menu_url": source_url,
            "needs_ai_recipe": True,
            "recipe_status": "stub",
        },
    }
    saved = []
    added_urls = []

    def fail_expensive(*_args, **_kwargs):
        raise AssertionError("Stubs should not run full routine work")

    monkeypatch.setattr(recipe_routes, "load_recipe_urls", lambda: [])
    monkeypatch.setattr(recipe_routes, "save_extracted_recipe_json", lambda url, data: saved.append((url, dict(data))) or tmp_path / "stub.json")
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_routes, "add_recipe_urls", lambda urls: added_urls.extend(urls))
    monkeypatch.setattr(recipe_routes, "save_import_cookbook_assignment", lambda *_args, **_kwargs: {"cookbook_id": "cb1", "cookbook_name": "Dinner"})
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_routes, "add_items", fail_expensive)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", fail_expensive)
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", fail_expensive)
    monkeypatch.setattr(recipe_routes, "run_generated_recipe_pdf_creation", fail_expensive)
    monkeypatch.setattr(recipe_routes, "apply_imported_recipe_category_routine", fail_expensive)
    monkeypatch.setattr(recipe_routes, "sort_ingredients", fail_expensive)

    result = recipe_routes.commit_menu_import_result(
        {"ok": True, "recipes": [stub], "staged_import": True},
        {"id": "cb1", "name": "Dinner"},
    )

    assert result["ok"] is True
    assert result["stubs_created"] == 1
    assert result["full_recipes_generated"] == 0
    assert result["pdfs_generated"] == 0
    assert result["pdfs_created"] == 0
    assert result["created_urls"] == [recipe_url]
    assert added_urls == [recipe_url]
    assert saved[0][1]["cookbook_id"] == "cb1"
    assert saved[0][1]["cookbook_name"] == "Dinner"
