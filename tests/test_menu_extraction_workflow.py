import json
import time

from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import openai_model_service
from PushShoppingList.services import recipe_extract_service


def configure_menu_model_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_model_service, "MODEL_OVERRIDES_FILE", tmp_path / "openai_model_overrides.json")
    monkeypatch.delenv("OPENAI_MENU_MODEL", raising=False)


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
