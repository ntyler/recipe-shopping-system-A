import time

from PushShoppingList.services import recipe_extract_service


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
    assert result["model_source"] == "forced:menu_item_inference"
    assert result["recipes"][0]["source_url"].startswith(source_url + "&menu_item=")
    assert saved[0][1]["source_url"] == source_url
    assert saved[0][1]["recipe_record_url"].startswith(source_url + "&menu_item=")
    assert saved[0][1]["menu_description"] == "Chicken with basil sauce."
    assert saved[0][1]["menu_price"] == "$13.99"


def test_menu_item_parallel_inference_preserves_original_menu_order(monkeypatch, tmp_path):
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
