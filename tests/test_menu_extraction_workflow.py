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


def shared_menu_source_pdf(url):
    canonical_url = recipe_extract_service.canonical_menu_source_url(url)
    return {
        "ok": True,
        "menu_source_url": canonical_url,
        "menu_source_pdf_status": "ready",
        "menu_source_pdf_path": "D:/shared/menu-source.pdf",
        "menu_source_cloudflare_pdf_url": "https://public.example.com/recipe-pdfs/menu-source.pdf",
        "source_pdf_path": "D:/shared/menu-source.pdf",
        "source_cloudflare_pdf_url": "https://public.example.com/recipe-pdfs/menu-source.pdf",
        "source_cloudflare_pdf_path": "https://public.example.com/recipe-pdfs/menu-source.pdf",
        "item_count": 1,
    }


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


def test_canonical_menu_source_url_removes_menu_item_deep_link():
    assert recipe_extract_service.canonical_menu_source_url(
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=menu-item-1-Spring_Roll"
    ) == "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    assert recipe_extract_service.canonical_menu_source_url(
        "https://www.velasiancuisine.com/rs/menuItem_home.action?resInput=RES4902&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    ) == "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"


def test_menu_source_pdf_validation_checks_full_item_name_set():
    sections = [
        {
            "section_name": "Appetizers",
            "items": [
                {"item_name": "Spring Roll"},
                {"item_name": "Crab Wonton (5)"},
                {"item_name": "Shrimp Shumai"},
            ],
        },
        {
            "section_name": "Noodles",
            "items": [
                {"item_name": f"Placeholder Item {index}"}
                for index in range(30)
            ] + [
                {"item_name": "Pad Thai"},
            ],
        },
    ]

    expected_names = recipe_extract_service.menu_source_pdf_expected_item_names(sections)
    validation = recipe_extract_service.validate_menu_source_capture_text(
        "Menu Info Cartana LLC Spring Roll Crab Wonton (5) Shrimp Shumai Pad Thai",
        expected_names=expected_names,
    )

    assert "Spring Roll" in expected_names
    assert "Crab Wonton (5)" in expected_names
    assert "Shrimp Shumai" in expected_names
    assert "Pad Thai" in expected_names
    assert validation["ok"] is True
    assert "Pad Thai" in validation["matched_item_names"]


def test_menu_source_pdf_validation_rejects_html_only_success(monkeypatch, tmp_path):
    pdf_path = tmp_path / "menu-source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        recipe_extract_service,
        "extract_text_from_pdf",
        lambda _path: "Info Like Menu Today Terms and Privacy Policy Cartana LLC",
    )

    result = recipe_extract_service.validate_menu_source_pdf_file(
        pdf_path,
        html_text="Spring Roll Crab Wonton Shrimp Shumai Pad Thai $12.00",
        expected_names=["Spring Roll", "Crab Wonton", "Shrimp Shumai", "Pad Thai"],
    )

    assert result["ok"] is False
    assert result["pdf_validation"]["shell_only"] is True
    assert result["html_validation"]["ok"] is True


def test_save_menu_item_preserves_shared_source_pdf_without_per_item_attach(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(
        recipe_extract_service,
        "maybe_upload_recipe_archive_pdf_to_cloudflare",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not upload per-item Source PDF")),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "attach_cloudflare_pdf_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not attach per-item Source PDF")),
    )

    recipe_url = "https://example.com/menu_home.action?resInput=RES1&menu_item=menu-item-1-basil"
    payload = {
        "source_url": recipe_url,
        "recipe_title": "Basil Chicken",
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "source_menu_url": "https://example.com/menu_home.action?resInput=RES1",
        **shared_menu_source_pdf("https://example.com/menu_home.action?resInput=RES1"),
    }

    json_path = recipe_extract_service.save_extracted_recipe_json(recipe_url, payload)
    saved = json.loads(json_path.read_text(encoding="utf-8"))

    assert saved["source_pdf_path"] == "D:/shared/menu-source.pdf"
    assert saved["source_cloudflare_pdf_url"] == "https://public.example.com/recipe-pdfs/menu-source.pdf"
    assert saved["menu_source_pdf_status"] == "ready"


def test_save_menu_item_without_valid_shared_pdf_does_not_attach_per_item_pdf(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(
        recipe_extract_service,
        "maybe_upload_recipe_archive_pdf_to_cloudflare",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not upload per-item Source PDF")),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "attach_cloudflare_pdf_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Should not attach per-item Source PDF")),
    )

    recipe_url = "https://example.com/menu_home.action?resInput=RES1&menu_item=menu-item-1-basil"
    payload = {
        "source_url": recipe_url,
        "recipe_title": "Basil Chicken",
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "source_menu_url": "https://example.com/menu_home.action?resInput=RES1",
    }

    json_path = recipe_extract_service.save_extracted_recipe_json(recipe_url, payload)
    saved = json.loads(json_path.read_text(encoding="utf-8"))

    assert saved["source_pdf_path"] == ""
    assert saved["source_cloudflare_pdf_url"] == ""
    assert saved["menu_source_pdf_status"] == "not_attached"


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
        "https://example.com/rs/menu_home.action?resInput=RES1",
    )
    items = recipe_extract_service.flatten_menu_sections(sections)

    assert len(sections) == 1
    assert len(items) == 1
    assert items[0]["item_name"] == "Spring Roll"
    assert items[0]["menu_section"] == "Kitchen Appetizers"
    assert items[0]["description"] == "2 veggie golden crispy rolls."
    assert items[0]["price"] == "$5.99"
    assert items[0]["menu_order_url"] == (
        "https://example.com/rs/menuItem_home.action?"
        "resInput=RES1&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    )
    assert items[0]["deep_link_url"] == items[0]["menu_order_url"]


def test_cartana_menu_order_url_for_takoyi_uses_item_order_page():
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    expected_url = (
        "https://www.velasiancuisine.com/rs/menuItem_home.action?"
        "resInput=RES4902&menuIdInput=MEN25930&menuItemIdInput=MIT354158&orderType=null"
    )
    payload = [{
        "menu": {
            "menuId": "MEN25930",
            "menuData": {
                "enMenuTitle": "Kitchen Appetizers",
                "enMenuText": "Appetizers from the Kitchen",
            },
        },
        "itemList": [{
            "price": 8.99,
            "menuItemId": "MIT354158",
            "menuItemData": {
                "enItemTitle": "Takoyi",
                "enItemText": "5pcs of Japanese fried octopus ball with takoyaki sauce, mayo and bonito flakes.",
            },
        }],
    }]

    sections = recipe_extract_service.parse_cartana_menu_sections(payload, source_url)
    item = recipe_extract_service.flatten_menu_sections(sections)[0]

    assert item["item_name"] == "Takoyi"
    assert item["menu_order_url"] == expected_url
    assert item["deep_link_url"] == expected_url
    assert recipe_extract_service.menu_item_deep_link(
        source_url,
        {
            "menu_id": "MEN25930",
            "menu_item_id": "MIT354158",
            "deep_link_url": f"{source_url}&menu_item_id=MIT354158",
        },
    ) == expected_url
    assert menu_mega_json_service.item_deep_link(
        source_url,
        {
            "menu_id": "MEN25930",
            "deep_link_url": f"{source_url}&menu_item_id=MIT354158",
        },
        "MIT354158",
    ) == expected_url


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
                    "menu_order_url": (
                        "https://www.velasiancuisine.com/rs/menuItem_home.action?"
                        "resInput=RES4902&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
                    ),
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
            "restaurant": {
                "restaurant_name": "Vel Asian Cuisine",
                "restaurant_website_url": "https://www.velasiancuisine.com",
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
                "current_status": "Open",
                "delivery_available": True,
            },
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
    assert unpacked[0]["items"][0]["menu_order_url"] == (
        "https://www.velasiancuisine.com/rs/menuItem_home.action?"
        "resInput=RES4902&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    )
    assert unpacked[0]["items"][0]["restaurant_address"] == "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140"
    assert unpacked[0]["items"][0]["restaurant_website_url"] == "https://www.velasiancuisine.com"
    assert unpacked[0]["items"][0]["restaurant_delivery_available"] is True
    stub = recipe_extract_service.normalize_menu_item_stub(source_url, unpacked[0]["items"][0], 0)
    assert stub["restaurant_address"] == "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140"
    assert stub["restaurant_website_url"] == "https://www.velasiancuisine.com"
    assert stub["restaurant_delivery_available"] is True
    assert stub["menu_order_url"] == unpacked[0]["items"][0]["menu_order_url"]
    assert stub["source_metadata"]["restaurant_address"] == "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140"

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
    source_pdf_calls = []
    monkeypatch.setattr(
        recipe_extract_service,
        "create_menu_source_pdf",
        lambda url, sections, progress_callback=None, cancellation_check=None: (
            source_pdf_calls.append((url, len(recipe_extract_service.flatten_menu_sections(sections)))),
            shared_menu_source_pdf(url),
        )[1],
    )
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
    assert source_pdf_calls == [(source_url, 1)]
    assert result["menu_source_pdf_status"] == "ready"
    assert result["source_pdf_path"] == "D:/shared/menu-source.pdf"
    assert result["source_cloudflare_pdf_url"] == "https://public.example.com/recipe-pdfs/menu-source.pdf"
    assert "Building mega menu JSON" in progress_messages
    assert "Saving mega menu JSON" in progress_messages
    assert "Unpacking mega menu JSON into item JSON records" in progress_messages
    assert snapshot["menu_mega_json"]["source"]["http_status"] == 200
    assert snapshot["menu_mega_json"]["menu"]["sections"][0]["items"][0]["name"] == "Spring Roll"
    assert saved[0][1]["source_type"] == "menu_item_inferred"
    assert saved[0][1]["ai_inferred"] is True
    assert saved[0][1]["parent_menu_snapshot_id"] == snapshot["id"]
    assert saved[0][1]["source_metadata"]["parent_menu_snapshot_id"] == snapshot["id"]
    assert saved[0][1]["source_pdf_path"] == "D:/shared/menu-source.pdf"
    assert saved[0][1]["source_cloudflare_pdf_url"] == "https://public.example.com/recipe-pdfs/menu-source.pdf"
    assert saved[0][1]["menu_source_pdf_path"] == "D:/shared/menu-source.pdf"
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
    assert "generateMenuStubFullSection" in script
    assert "runNutritionCategoriesForSelectedRecipes" in script
    assert "generatePdfsForSelectedRecipes" in script
    assert "/api/menu_mega_json_snapshots/" in script
    assert "/api/menu_mega_json_snapshots/<snapshot_id>/download" in routes
    assert "/api/menu_mega_json_snapshots/<snapshot_id>/retry-unpack" in routes
    assert "api_menu_mega_json_snapshot_route" in routes
    assert "Generate Full Recipes for All" in template
    assert "Generate Full Section" in template
    assert "Run Nutrition / Categories" in template
    assert "Generate PDFs" in template


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
                    "menu_id": "MEN1",
                    "menu_item_id": "MIT1",
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
    assert saved[0][1]["menu_order_url"] == (
        "https://example.com/menuItem_home.action?"
        "resInput=RES1&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    )
    assert result["recipes"][0]["menu_order_url"] == saved[0][1]["menu_order_url"]


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
    assert changed.source == "admin override:OPENAI_MENU_MODEL"
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
                    "menu_id": "MEN1",
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
    assert result["recipes"][0]["source_type"] == "menu_item_inferred"
    assert result["recipes"][0]["source_import_type"] == "menu_url_import"
    assert result["recipes"][0]["ai_inferred"] is True
    assert result["recipes"][0]["needs_ai_recipe"] is True
    assert result["recipes"][0]["recipe_status"] == "stub"
    assert result["recipes"][0]["import_status"] == "imported_basic"
    assert result["recipes"][0]["ingredients"] == []
    assert result["recipes"][0]["recipe_inference"]["status"] == "not_generated"
    assert result["recipes"][0]["nutrition_inference"]["status"] == "not_generated"
    assert result["recipes"][0]["pdf_generation"]["status"] == "not_generated"
    assert saved[0][1]["source_menu_url"] == source_url
    assert saved[0][1]["menu_item_id"] == "MIT1"
    assert saved[0][1]["menu_order_url"] == (
        "https://example.com/menuItem_home.action?"
        "resInput=RES1&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    )


def test_menu_stub_import_skips_blank_divider_items(monkeypatch, tmp_path):
    configure_menu_model_defaults(monkeypatch, tmp_path)
    source_url = "https://example.com/menu"
    saved = []
    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)
    monkeypatch.setattr(
        recipe_extract_service,
        "save_extracted_recipe_json",
        lambda recipe_url, json_data: saved.append((recipe_url, dict(json_data))) or tmp_path / "stub.json",
    )

    result = recipe_extract_service.build_menu_stub_extract_result_from_items(
        source_url,
        [
            {
                "section_name": "Entrees",
                "items": [
                    {"item_name": "--", "menu_section": "Entrees"},
                    {"item_name": "Basil Chicken", "menu_section": "Entrees"},
                ],
            }
        ],
        diagnostics={"menu_page_fetched": True},
    )

    assert result["ok"] is True
    assert result["stubs_created"] == 1
    assert result["items_skipped"][0]["reason"] == "blank_divider"
    assert saved[0][1]["recipe_title"] == "Basil Chicken"


def test_menu_inference_batches_cap_batch_size(monkeypatch):
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_MAX_ITEMS", "25")
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_TARGET_CHARS", "999999")
    entries = [
        {
            "recipe_url": f"https://example.com/menu?menu_item={index}",
            "menu_item": {
                "menu_item_id": f"item-{index}",
                "item_name": f"Item {index}",
                "menu_section": "Entrees",
            },
        }
        for index in range(52)
    ]

    batches = recipe_extract_service.menu_inference_batches(entries)

    assert [len(batch) for batch in batches] == [25, 25, 2]


def test_menu_inference_batches_use_smaller_gpt_4o_mini_defaults(monkeypatch):
    monkeypatch.delenv("MENU_ITEM_BATCH_INFERENCE_MAX_ITEMS", raising=False)
    monkeypatch.delenv("MENU_ITEM_BATCH_INFERENCE_MIN_ITEMS", raising=False)
    monkeypatch.delenv("MENU_ITEM_BATCH_INFERENCE_TARGET_CHARS", raising=False)
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_item_recipe_model_resolution",
        lambda: recipe_extract_service.OpenAIModelResolution("gpt-4o-mini", "test", "menu"),
    )
    entries = [
        {
            "recipe_url": f"https://example.com/menu?menu_item={index}",
            "menu_item": {
                "menu_item_id": f"item-{index}",
                "item_name": f"Item {index}",
                "menu_section": "Entrees",
            },
        }
        for index in range(17)
    ]

    batches = recipe_extract_service.menu_inference_batches(entries)

    assert recipe_extract_service.menu_item_batch_size_limits() == (2, 4)
    assert [len(batch) for batch in batches] == [4, 4, 4, 4, 1]


def test_menu_batch_inference_splits_timeout_and_combines_results(monkeypatch):
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_failed_item_model_resolution",
        lambda: recipe_extract_service.OpenAIModelResolution("", "disabled", "menu_failed_item"),
    )
    entries = [
        {
            "recipe_url": f"https://example.com/menu?menu_item={index}",
            "menu_item": {
                "menu_item_id": f"item-{index}",
                "item_name": f"Item {index}",
                "menu_section": "Entrees",
            },
        }
        for index in range(4)
    ]
    calls = []

    def fake_once(batch, user_id=None):
        calls.append({"size": len(batch), "user_id": user_id})
        if len(batch) > 1:
            return {
                "ok": False,
                "items": {},
                "failures": {},
                "error_code": "OPENAI_TIMEOUT",
                "error_message": "Vision AI request timed out.",
                "technical_message": "Request timed out.",
                "exception_type": "APITimeoutError",
                "model": "menu-mini",
                "model_source": "environment:OPENAI_MENU_MODEL",
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
            "model": "menu-mini",
            "model_source": "environment:OPENAI_MENU_MODEL",
        }

    monkeypatch.setattr(recipe_extract_service, "_infer_menu_item_recipe_batch_once", fake_once)

    result = recipe_extract_service.infer_menu_item_recipe_batch(entries, user_id="owner")

    assert result["ok"] is True
    assert sorted(result["items"]) == ["item-0", "item-1", "item-2", "item-3"]
    assert result["failures"] == {}
    assert [call["size"] for call in calls] == [4, 2, 1, 1, 2, 1, 1]
    assert all(call["user_id"] == "owner" for call in calls)


def test_menu_batch_inference_uses_failed_item_fallback_model(monkeypatch, capsys):
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_ATTEMPTS", "1")
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_item_recipe_model_resolution",
        lambda: recipe_extract_service.OpenAIModelResolution("gpt-4o-mini", "test:OPENAI_MENU_MODEL", "menu"),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_failed_item_model_resolution",
        lambda: recipe_extract_service.OpenAIModelResolution(
            "gpt-5.4-mini",
            "test:OPENAI_MENU_FAILED_ITEM_MODEL",
            "menu_failed_item",
        ),
    )
    entries = [
        {
            "recipe_url": f"https://example.com/menu?menu_item={index}",
            "menu_item": {
                "menu_item_id": f"item-{index}",
                "item_name": f"Item {index}",
                "menu_section": "Entrees",
            },
        }
        for index in range(2)
    ]
    calls = []

    def fake_once(batch, user_id=None, model_resolution=None):
        model = getattr(model_resolution, "model", "gpt-4o-mini")
        calls.append({"model": model, "size": len(batch), "ids": [entry["menu_item"]["menu_item_id"] for entry in batch]})
        if model == "gpt-5.4-mini":
            return {
                "ok": True,
                "items": {
                    entry["menu_item"]["menu_item_id"]: {
                        "predicted_ingredients": [{"ingredient": entry["menu_item"]["item_name"]}],
                    }
                    for entry in batch
                },
                "failures": {},
                "model": model,
                "model_source": "test:OPENAI_MENU_FAILED_ITEM_MODEL",
            }
        return {
            "ok": False,
            "items": {},
            "failures": {},
            "error_code": "OPENAI_TIMEOUT",
            "error_message": "Vision AI request timed out.",
            "technical_message": "Request timed out.",
            "exception_type": "APITimeoutError",
            "model": model,
            "model_source": "test:OPENAI_MENU_MODEL",
        }

    monkeypatch.setattr(recipe_extract_service, "_infer_menu_item_recipe_batch_once", fake_once)

    result = recipe_extract_service.infer_menu_item_recipe_batch(entries, user_id="owner")
    output = capsys.readouterr().out

    assert result["ok"] is True
    assert result["fallback_used"] is True
    assert result["fallback_model"] == "gpt-5.4-mini"
    assert sorted(result["items"]) == ["item-0", "item-1"]
    assert calls == [
        {"model": "gpt-4o-mini", "size": 2, "ids": ["item-0", "item-1"]},
        {"model": "gpt-5.4-mini", "size": 2, "ids": ["item-0", "item-1"]},
    ]
    assert "action=menu-item-recipe-failed-item-fallback_start" in output
    assert "action=menu-item-recipe-failed-item-fallback_ready" in output


def test_menu_batch_inference_retries_with_backoff_before_success(monkeypatch):
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_BACKOFF_SECONDS", "1.5")
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_MAX_BACKOFF_SECONDS", "2")
    sleeps = []
    entries = [
        {
            "recipe_url": "https://example.com/menu?menu_item=pad-thai",
            "menu_item": {
                "menu_item_id": "item-pad-thai",
                "item_name": "Pad Thai",
                "menu_section": "Noodles",
            },
        }
    ]
    calls = []

    def fake_once(batch, user_id=None):
        calls.append({"size": len(batch), "user_id": user_id})
        if len(calls) == 1:
            return {
                "ok": False,
                "items": {},
                "failures": {},
                "error_code": "OPENAI_TIMEOUT",
                "error_message": "Vision AI request timed out.",
                "technical_message": "Request timed out.",
                "exception_type": "APITimeoutError",
                "model": "gpt-4o-mini",
                "model_source": "test",
            }
        return {
            "ok": True,
            "items": {"item-pad-thai": {"predicted_ingredients": [{"ingredient": "rice noodles"}]}},
            "failures": {},
            "model": "gpt-4o-mini",
            "model_source": "test",
        }

    monkeypatch.setattr(recipe_extract_service, "_infer_menu_item_recipe_batch_once", fake_once)
    monkeypatch.setattr(recipe_extract_service.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = recipe_extract_service.infer_menu_item_recipe_batch(entries, user_id="owner")

    assert result["ok"] is True
    assert calls == [{"size": 1, "user_id": "owner"}, {"size": 1, "user_id": "owner"}]
    assert sleeps == [1.5]


def test_menu_batch_inference_logs_final_failed_item_names(monkeypatch, capsys):
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_RETRY_ATTEMPTS", "1")
    entries = [
        {
            "recipe_url": "https://example.com/menu?menu_item=pad-thai",
            "menu_item": {
                "menu_item_id": "item-pad-thai",
                "item_name": "Pad Thai",
                "menu_section": "Noodles",
            },
        }
    ]

    monkeypatch.setattr(
        recipe_extract_service,
        "_infer_menu_item_recipe_batch_once",
        lambda batch, user_id=None: {
            "ok": False,
            "items": {},
            "failures": {},
            "error_code": "BAD_RESPONSE",
            "error_message": "Unable to parse response.",
            "technical_message": "Unable to parse response.",
            "exception_type": "ValueError",
            "model": "gpt-4o-mini",
            "model_source": "test",
        },
    )

    result = recipe_extract_service.infer_menu_item_recipe_batch(entries, user_id="owner")
    output = capsys.readouterr().out

    assert result["ok"] is False
    assert "action=menu-item-recipe-batch-inference_final_failures" in output
    assert "Pad Thai" in output


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
    monkeypatch.setattr(
        recipe_extract_service,
        "create_menu_source_pdf",
        lambda url, sections, progress_callback=None, cancellation_check=None: shared_menu_source_pdf(url),
    )
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
    assert result["menu_source_pdf_status"] == "ready"
    assert result["source_pdf_path"] == "D:/shared/menu-source.pdf"
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
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "needs_ai_recipe": True,
        "recipe_status": "stub",
        "ingredients": [],
        "raw": {
            "source_type": "menu_item_inferred",
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


def test_commit_menu_import_full_recipes_reuses_shared_source_pdf(monkeypatch, tmp_path):
    source_url = "https://example.com/menu_home.action?resInput=RES1"
    recipe_urls = [
        source_url + "&menu_item=menu-item-1-basil",
        source_url + "&menu_item=menu-item-2-curry",
    ]
    shared_pdf = shared_menu_source_pdf(source_url)
    recipes = [
        {
            "ok": True,
            "source_url": recipe_urls[0],
            "display_name": "Basil Chicken",
            "recipe_title": "Basil Chicken",
            "source_type": "menu_item_inferred",
            "ai_inferred": True,
            "ingredients": ["chicken", "basil"],
            "instructions": [{"instruction": "Stir fry."}],
        },
        {
            "ok": True,
            "source_url": recipe_urls[1],
            "display_name": "Curry Chicken",
            "recipe_title": "Curry Chicken",
            "source_type": "menu_item_inferred",
            "ai_inferred": True,
            "ingredients": ["chicken", "curry paste"],
            "instructions": [{"instruction": "Simmer."}],
        },
    ]
    ingredient_metadata = []

    def fail_source_pdf(*_args, **_kwargs):
        raise AssertionError("Menu item loop must not create per-item Source PDFs")

    monkeypatch.setattr(recipe_routes, "load_recipe_urls", lambda: [])
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(
        recipe_routes,
        "save_ingredients_for_recipe",
        lambda url, ingredients, result: ingredient_metadata.append((url, dict(result))),
    )
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_routes, "add_recipe_urls", lambda urls: None)
    monkeypatch.setattr(recipe_routes, "save_import_cookbook_assignment", lambda *_args, **_kwargs: {"cookbook_id": "cb1", "cookbook_name": "Dinner"})
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", fail_source_pdf)
    monkeypatch.setattr(
        recipe_routes,
        "run_generated_recipe_pdf_creation",
        lambda url, context="menu-import": {
            "ok": True,
            "generated_pdf_path": f"D:/generated/{recipe_extract_service.safe_filename(url)}.pdf",
            "generated_cloudflare_pdf_url": f"https://public.example.com/generated/{recipe_extract_service.safe_filename(url)}.pdf",
        },
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda *_args, **_kwargs: {"ok": True, "status": "updated"},
    )
    monkeypatch.setattr(recipe_routes, "sort_ingredients", lambda: None)

    result = recipe_routes.commit_menu_import_result(
        {
            "ok": True,
            "recipes": recipes,
            "menu_extract": True,
            **shared_pdf,
        },
        {"id": "cb1", "name": "Dinner"},
    )

    assert result["ok"] is True
    assert result["created_urls"] == recipe_urls
    assert result["menu_source_pdf_status"] == "ready"
    assert {row[1]["source_pdf_path"] for row in ingredient_metadata} == {"D:/shared/menu-source.pdf"}
    assert {row[1]["source_cloudflare_pdf_url"] for row in ingredient_metadata} == {
        "https://public.example.com/recipe-pdfs/menu-source.pdf"
    }
    assert [status["shared_source_pdf"] for status in result["source_pdf_statuses"]] == [True, True]
    assert {status["source_pdf_path"] for status in result["source_pdf_statuses"]} == {"D:/shared/menu-source.pdf"}
