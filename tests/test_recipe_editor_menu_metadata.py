from pathlib import Path

from PushShoppingList.services import menu_store_service
from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def configure_editor_recipe_storage(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    monkeypatch.setattr(menu_mega_json_service, "workspace_data_root", lambda: tmp_path)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_ingredient_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *args, **kwargs: None)

    return output_dir, pdf_dir


def seed_menu_derived_recipe():
    detail = menu_store_service.upsert_menu_from_facts({
        "source_url": "https://velasian.example/menu",
        "restaurant": {
            "restaurant_name": "Vel Asian Cuisine",
            "restaurant_website_url": "https://velasian.example",
            "cuisine_tags": ["Asian", "Thai"],
            "phone": "317-555-0100",
            "full_address": "1 Main St, Indianapolis, IN",
            "hours_text": "Mon-Sat 10-9",
            "current_status": "Open",
            "rewards_text": "Rewards members get lunch specials",
            "online_payment_available": True,
            "delivery_available": True,
        },
        "menu": {
            "menu_title": "Vel Asian Cuisine Menu",
        },
        "sections": [{
            "section_name": "Kitchen Appetizers",
            "items": [{
                "item_name": "Spring Roll",
                "menu_price": "$5.99",
                "menu_description": "Two veggie golden crispy rolls.",
                "menu_order_url": "https://velasian.example/order/spring-roll",
            }],
        }],
    })
    menu = detail["menu"]
    restaurant = detail["restaurant"]
    section = detail["sections"][0]
    item = detail["items"][0]
    url = "https://velasian.example/menu#spring-roll"

    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "menu_order_url": "https://velasian.example/order/spring-roll",
        "restaurant_id": restaurant["id"],
        "menu_id": menu["id"],
        "menu_section_id": section["id"],
        "menu_item_id": item["id"],
        "recipe_title": "Spring Roll",
        "ingredients": [{"ingredient": "cabbage", "quantity": "1", "unit": "cup"}],
        "instructions": [{"instruction": "Roll and fry until golden."}],
    })

    return url, detail


def seed_menu_recipe_url_match():
    url = "https://velasian.example/menu?resInput=RES4902&menu_item=menu-item-1-AI-Inferred_Crispy_Vegetable_Spring_Rolls"
    detail = menu_store_service.upsert_menu_from_facts({
        "source_url": "",
        "restaurant": {
            "restaurant_name": "Vel Asian Cuisine",
        },
        "menu": {
            "menu_title": "Vel Asian Cuisine Menu",
        },
        "sections": [{
            "section_name": "Vegetarian",
            "items": [{
                "item_name": "Spring Roll",
                "menu_price": "$18.95",
                "menu_description": "Featuring wheat spring roll wrappers, cellophane noodles, carrot.",
                "menu_order_url": "https://velasian.example/order/spring-roll",
                "recipe_url": url,
            }],
        }],
    })
    return url, detail


def editable_payload(url, **overrides):
    payload = {
        "source_url": url,
        "display_name": overrides.pop("display_name", "Spring Roll"),
        "recipe_title": overrides.pop("recipe_title", "Spring Roll"),
        "quantity": 1,
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "scaling": {},
        "ingredients": [{"ingredient": "cabbage", "quantity": "1", "unit": "cup"}],
        "equipment": [],
        "instructions": [{"instruction": "Roll and fry until golden."}],
        "nutrition": [],
        "rating": 0,
        "reflection_notes": [],
    }
    payload.update(overrides)
    return payload


def empty_menu_metadata_payload():
    return {
        "restaurant_name": "",
        "restaurant_website_url": "",
        "source_menu_url": "",
        "restaurant_cuisine_tags": "",
        "restaurant_phone": "",
        "restaurant_address": "",
        "restaurant_hours_text": "",
        "restaurant_current_status": "",
        "restaurant_promotions": "",
        "restaurant_online_payment_available": "",
        "restaurant_delivery_available": "",
        "menu_section": "",
        "menu_item_name": "",
        "menu_order_url": "",
        "menu_price": "",
        "menu_description": "",
    }


def test_recipe_editor_menu_metadata_panels_are_wired_before_amount():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    js = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    restaurant_panel = template.index("recipeEditRestaurantMenuSourceDetails")
    menu_item_panel = template.index("recipeEditMenuItemDetails")
    recipe_amount = template.index("recipeEditScaleMultiplier")
    source_files_panel = template.index("recipeEditSourceFilesDetails")

    assert source_files_panel < restaurant_panel < menu_item_panel < recipe_amount
    assert "Restaurant / Menu Source Info" in template
    assert "Menu Item Details" in template
    assert 'id="recipeEditRestaurantWebsiteUrlLink"' in template
    assert 'id="recipeEditSourceMenuUrlLink"' in template
    assert 'id="recipeEditMenuOrderUrlLink"' in template
    assert 'id="recipeEditMenuOrderUrl"' in template
    assert '<textarea id="recipeEditMenuDescription" rows="3">' in template
    assert "panel.hidden = !showPanels;" in js
    assert "function recipeMenuMetadataPanelsVisible()" in js
    assert "return payload;" in js[js.index("function collectRecipeMenuMetadataPayload"):js.index("function currentRecipeEditorPdfFieldValues")]
    assert ".recipe-edit-menu-metadata-details" in css
    assert ".recipe-edit-menu-metadata-grid" in css


def test_normal_recipe_load_and_save_do_not_add_menu_metadata(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Tomato Soup",
        "ingredients": [{"ingredient": "tomato"}],
        "instructions": [{"instruction": "Simmer."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["is_menu_derived"] is False
    assert loaded["menu_metadata_available"] is False
    assert loaded["restaurant_name"] == ""
    assert loaded["menu_price"] == ""
    assert loaded["servings"] == ""
    assert loaded["level"] == ""
    assert loaded["total_time"] == ""

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            display_name="Tomato Soup",
            recipe_title="Tomato Soup",
            ingredients=[{"ingredient": "tomato"}],
            instructions=[{"instruction": "Simmer."}],
            **empty_menu_metadata_payload(),
        ),
    )
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    for field in recipe_edit_service.RESTAURANT_MENU_METADATA_FIELDS:
        assert field not in saved


def test_generated_menu_recipe_load_backfills_blank_recipe_info_defaults(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url = "https://velasian.example/menu#spring-roll"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "needs_ai_recipe": False,
        "recipe_status": "generated",
        "recipe_title": "Spring Roll",
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "scaling": {},
        "ingredients": [{"ingredient": "cabbage", "quantity": "1", "unit": "cup"}],
        "instructions": [{"instruction": "Roll and fry until golden."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["servings"] == "4 servings"
    assert loaded["level"] == "Easy"
    assert loaded["total_time"] == "45 min"
    assert loaded["prep_time"] == "15 min"
    assert loaded["inactive_time"] == "0 min"
    assert loaded["cook_time"] == "30 min"
    assert loaded["scaling"]["base_servings"] == "4 servings"


def test_menu_batch_generation_preserves_editor_restaurant_metadata(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(recipe_extract_service, "maybe_upload_recipe_archive_pdf_to_cloudflare", lambda *_args, **_kwargs: {})
    url = "https://velasian.example/menu#spring-roll"
    stub = editable_payload(
        url,
        source_type="menu_item_inferred",
        ai_inferred=True,
        needs_ai_recipe=True,
        recipe_status="stub",
        source_menu_url="https://velasian.example/menu",
        restaurant_name="Vel Asian Cuisine",
        restaurant_website_url="https://velasian.example",
        restaurant_cuisine_tags="Asian, Thai",
        restaurant_phone="317-555-0100",
        restaurant_address="1 Main St, Indianapolis, IN",
        restaurant_hours_text="Mon-Sat 10-9",
        restaurant_current_status="Open",
        restaurant_promotions="Rewards members get lunch specials",
        restaurant_online_payment_available="false",
        restaurant_delivery_available="true",
        menu_section="Kitchen Appetizers",
        menu_item_name="Spring Roll",
        menu_price="$5.99",
        menu_description="Two veggie golden crispy rolls.",
        ingredients=[],
        instructions=[],
    )

    menu_item = recipe_extract_service.menu_batch_item_from_stub(url, stub, 0)
    result = recipe_extract_service.apply_menu_batch_inference_to_stub(
        url,
        stub,
        menu_item,
        {
            "predicted_ingredients": [{"ingredient": "cabbage", "quantity": "1", "unit": "cup"}],
            "predicted_instructions": [{"instruction": "Roll and fry until golden."}],
        },
        model="gpt-test",
        model_source="test",
    )
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    assert menu_item["restaurant_name"] == "Vel Asian Cuisine"
    assert menu_item["restaurant_address"] == "1 Main St, Indianapolis, IN"
    assert menu_item["restaurant_online_payment_available"] == "false"
    assert saved["restaurant_name"] == "Vel Asian Cuisine"
    assert saved["restaurant_address"] == "1 Main St, Indianapolis, IN"
    assert saved["restaurant_online_payment_available"] == "false"
    assert saved["restaurant_delivery_available"] == "true"
    assert saved["source_metadata"]["restaurant_name"] == "Vel Asian Cuisine"
    assert saved["source_metadata"]["restaurant_address"] == "1 Main St, Indianapolis, IN"
    assert saved["servings"]
    assert saved["scaling"]["base_servings"] == saved["servings"]


def test_menu_derived_recipe_loads_restaurant_and_menu_item_metadata(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, _detail = seed_menu_derived_recipe()

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["is_menu_derived"] is True
    assert loaded["menu_metadata_available"] is True
    assert loaded["restaurant_name"] == "Vel Asian Cuisine"
    assert loaded["restaurant_website_url"] == "https://velasian.example"
    assert loaded["source_menu_url"] == "https://velasian.example/menu"
    assert loaded["restaurant_cuisine_tags"] == "Asian, Thai"
    assert loaded["restaurant_phone"] == "317-555-0100"
    assert loaded["restaurant_address"] == "1 Main St, Indianapolis, IN"
    assert loaded["restaurant_hours_text"] == "Mon-Sat 10-9"
    assert loaded["restaurant_current_status"] == "Open"
    assert loaded["restaurant_online_payment_available"] == "true"
    assert loaded["restaurant_delivery_available"] == "true"
    assert loaded["menu_section"] == "Kitchen Appetizers"
    assert loaded["menu_item_name"] == "Spring Roll"
    assert loaded["menu_order_url"] == "https://velasian.example/order/spring-roll"
    assert loaded["menu_price"] == "$5.99"
    assert loaded["menu_description"] == "Two veggie golden crispy rolls."


def test_menu_metadata_can_resolve_from_section_link(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()
    recipe_data = recipe_edit_service.load_recipe_output(url)
    recipe_data.pop("restaurant_id", None)
    recipe_data.pop("menu_id", None)
    recipe_data.pop("menu_item_id", None)
    recipe_edit_service.save_recipe_output(url, recipe_data)

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["is_menu_derived"] is True
    assert loaded["menu_section_id"] == detail["sections"][0]["id"]
    assert loaded["restaurant_name"] == "Vel Asian Cuisine"
    assert loaded["source_menu_url"] == "https://velasian.example/menu"
    assert loaded["menu_section"] == "Kitchen Appetizers"


def test_menu_metadata_resolves_from_menu_item_url_when_recipe_json_has_only_pdf_fields(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_recipe_url_match()
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "source_pdf_path": "D:/recipes/spring-roll.pdf",
        "generated_pdf_path": "D:/recipes/spring-roll-generated.pdf",
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["is_menu_derived"] is True
    assert loaded["menu_metadata_available"] is True
    assert loaded["restaurant_id"] == detail["restaurant"]["id"]
    assert loaded["menu_id"] == detail["menu"]["id"]
    assert loaded["menu_section_id"] == detail["sections"][0]["id"]
    assert loaded["menu_item_id"] == detail["items"][0]["id"]
    assert loaded["restaurant_name"] == "Vel Asian Cuisine"
    assert loaded["source_menu_url"] == "https://velasian.example/menu?resInput=RES4902"
    assert loaded["menu_section"] == "Vegetarian"
    assert loaded["menu_item_name"] == "Spring Roll"
    assert loaded["menu_order_url"] == "https://velasian.example/order/spring-roll"
    assert loaded["menu_price"] == "$18.95"
    assert loaded["menu_description"] == "Featuring wheat spring roll wrappers, cellophane noodles, carrot."


def test_menu_metadata_loads_restaurant_fields_from_menu_mega_snapshot(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    recipe_url = f"{source_url}&menu_item=menu-item-1-Spring_Roll"
    mega_json = menu_mega_json_service.build_mega_menu_json(
        source_url,
        [{
            "section_name": "Kitchen Appetizers",
            "items": [{
                "item_name": "Spring Roll",
                "description": "Two veggie golden crispy rolls.",
                "price": "$5.99",
                "menu_item_id": "MIT354155",
                "menu_id": "MEN25930",
                "menu_order_url": (
                    "https://www.velasiancuisine.com/rs/menuItem_home.action?"
                    "resInput=RES4902&menuIdInput=MEN25930&menuItemIdInput=MIT354155&orderType=null"
                ),
            }],
        }],
        extracted_text="Vel Asian Cuisine Spring Roll $5.99",
        diagnostics={
            "final_url": source_url,
            "restaurant": {
                "restaurant_name": "Vel Asian Cuisine",
                "restaurant_website_url": "https://www.velasiancuisine.com",
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
                "phone": "513-555-0100",
                "hours_text": "Mon-Sat 11-9",
                "current_status": "Open",
                "delivery_available": True,
                "online_payment_available": False,
                "rewards_text": "Rewards available",
            },
        },
    )
    menu_mega_json_service.save_menu_mega_json_snapshot(mega_json, job_id="job-1")
    recipe_edit_service.save_recipe_output(recipe_url, {
        "source_url": recipe_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "source_menu_url": source_url,
        "restaurant_name": "",
        "restaurant_website_url": "",
        "restaurant_address": "",
        "restaurant_phone": "",
        "restaurant_hours_text": "",
        "restaurant_current_status": "",
        "restaurant_online_payment_available": "",
        "restaurant_delivery_available": "",
        "restaurant_promotions": "",
        "menu_section": "Kitchen Appetizers",
        "menu_item_name": "Spring Roll",
        "menu_order_url": "",
        "menu_price": "$5.99",
        "menu_description": "Two veggie golden crispy rolls.",
    })

    loaded = recipe_edit_service.load_editable_recipe(recipe_url)["recipe"]

    assert loaded["restaurant_name"] == "Vel Asian Cuisine"
    assert loaded["restaurant_website_url"] == "https://www.velasiancuisine.com"
    assert loaded["source_menu_url"] == source_url
    assert loaded["restaurant_phone"] == "513-555-0100"
    assert loaded["restaurant_address"] == "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140"
    assert loaded["restaurant_hours_text"] == "Mon-Sat 11-9"
    assert loaded["restaurant_current_status"] == "Open"
    assert loaded["restaurant_promotions"] == "Rewards available"
    assert loaded["restaurant_online_payment_available"] == "false"
    assert loaded["restaurant_delivery_available"] == "true"
    assert loaded["menu_order_url"] == (
        "https://www.velasiancuisine.com/rs/menuItem_home.action?"
        "resInput=RES4902&menuIdInput=MEN25930&menuItemIdInput=MIT354155&orderType=null"
    )


def test_menu_metadata_matches_menu_store_by_base_url_and_preserves_recipe_item_fields(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    recipe_url = f"{source_url}&menu_item=menu-item-1-Spring_Roll"
    menu_store_service.upsert_menu_from_facts({
        "source_url": "",
        "restaurant": {
            "restaurant_name": "Vel Asian Cuisine",
            "delivery_available": False,
            "online_payment_available": False,
        },
        "menu": {"menu_title": "Vel Asian Cuisine Menu"},
        "sections": [{
            "section_name": "Vegetarian",
            "items": [{
                "item_name": "Spring Roll",
                "menu_price": "$18.95",
                "menu_description": "Featuring wheat spring roll wrappers, cellophane noodles, carrot.",
                "menu_order_url": (
                    "https://www.velasiancuisine.com/rs/menuItem_home.action?"
                    "resInput=RES4902&menuIdInput=MEN25930&menuItemIdInput=MIT354155&orderType=null"
                ),
                "recipe_url": (
                    f"{source_url}&menu_item=menu-item-1-"
                    "AI-Inferred_Crispy_Vegetable_Spring_Rolls"
                ),
            }],
        }],
    })
    recipe_edit_service.save_recipe_output(recipe_url, {
        "source_url": recipe_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "source_menu_url": source_url,
        "restaurant_name": "",
        "restaurant_online_payment_available": "",
        "restaurant_delivery_available": "",
        "menu_section": "Kitchen Appetizers",
        "menu_item_name": "Spring Roll",
        "menu_price": "$5.99",
        "menu_description": "2 veggie golden crispy brown paper wheat wrapped around mixture of carrots.",
    })

    loaded = recipe_edit_service.load_editable_recipe(recipe_url)["recipe"]

    assert loaded["restaurant_name"] == "Vel Asian Cuisine"
    assert loaded["restaurant_online_payment_available"] == "false"
    assert loaded["restaurant_delivery_available"] == "false"
    assert loaded["menu_section"] == "Kitchen Appetizers"
    assert loaded["menu_price"] == "$5.99"
    assert loaded["menu_description"] == "2 veggie golden crispy brown paper wheat wrapped around mixture of carrots."


def test_url_matched_menu_metadata_save_updates_menu_store(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_recipe_url_match()
    item_id = detail["items"][0]["id"]
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "source_pdf_path": "D:/recipes/spring-roll.pdf",
    })

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            menu_section="Small Plates",
            menu_item_name="Spring Roll",
            menu_order_url="https://velasian.example/order/spring-roll-updated",
            menu_price="$19.49",
            menu_description="Updated spring roll description.",
        ),
    )
    item = menu_store_service.find_menu_item(menu_store_service.load_menu_store(), item_id)
    saved = recipe_edit_service.load_recipe_output(url)

    assert result["ok"] is True
    assert item["menu_section"] == "Small Plates"
    assert item["menu_order_url"] == "https://velasian.example/order/spring-roll-updated"
    assert item["menu_price"] == "$19.49"
    assert item["menu_description"] == "Updated spring roll description."
    assert saved["menu_price"] == "$19.49"
    assert saved["menu_order_url"] == "https://velasian.example/order/spring-roll-updated"
    assert saved["menu_description"] == "Updated spring roll description."


def test_saving_menu_derived_recipe_persists_metadata_updates(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()
    restaurant_id = detail["restaurant"]["id"]
    menu_id = detail["menu"]["id"]
    item_id = detail["items"][0]["id"]

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            restaurant_name="Vel Asian Kitchen",
            restaurant_website_url="https://velasian.example",
            source_menu_url="https://velasian.example/current-menu",
            restaurant_cuisine_tags="Asian, Thai, Vegetarian",
            restaurant_phone="317-555-0199",
            restaurant_address="2 Main St, Indianapolis, IN",
            restaurant_hours_text="Daily 11-8",
            restaurant_current_status="Open now",
            restaurant_promotions="Happy hour rolls",
            restaurant_online_payment_available="false",
            restaurant_delivery_available="true",
            menu_section="Starters",
            menu_item_name="Spring Roll",
            menu_order_url="https://velasian.example/order/spring-roll-updated",
            menu_price="$6.49",
            menu_description="Updated crispy veggie rolls.",
        ),
    )
    store = menu_store_service.load_menu_store()
    restaurant = menu_store_service.restaurant_for(store, restaurant_id)
    menu = menu_store_service.find_menu(store, menu_id)
    item = menu_store_service.find_menu_item(store, item_id)
    saved = recipe_edit_service.load_recipe_output(url)
    loaded = result["recipe"]

    assert result["ok"] is True
    assert restaurant["restaurant_name"] == "Vel Asian Kitchen"
    assert restaurant["cuisine_tags"] == ["Asian", "Thai", "Vegetarian"]
    assert restaurant["phone"] == "317-555-0199"
    assert restaurant["full_address"] == "2 Main St, Indianapolis, IN"
    assert restaurant["hours_text"] == "Daily 11-8"
    assert restaurant["current_status"] == "Open now"
    assert restaurant["online_payment_available"] is False
    assert restaurant["delivery_available"] is True
    assert menu["source_url"] == "https://velasian.example/current-menu"
    assert item["menu_section"] == "Starters"
    assert item["menu_order_url"] == "https://velasian.example/order/spring-roll-updated"
    assert item["menu_price"] == "$6.49"
    assert item["menu_description"] == "Updated crispy veggie rolls."
    assert saved["source_menu_url"] == "https://velasian.example/current-menu"
    assert saved["menu_order_url"] == "https://velasian.example/order/spring-roll-updated"
    assert saved["menu_price"] == "$6.49"
    assert saved["menu_description"] == "Updated crispy veggie rolls."
    assert loaded["restaurant_name"] == "Vel Asian Kitchen"
    assert loaded["menu_order_url"] == "https://velasian.example/order/spring-roll-updated"
    assert loaded["menu_price"] == "$6.49"


def test_generated_recipe_pdf_includes_menu_metadata_for_menu_recipes(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, _detail = seed_menu_derived_recipe()
    captured = {}

    def fake_write_recipe_page_pdf(recipe_url, html_text, html_path, pdf_path):
        captured["html"] = html_text
        path = Path(pdf_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return path

    monkeypatch.setattr(recipe_edit_service, "write_recipe_page_pdf", fake_write_recipe_page_pdf)

    result = recipe_edit_service.generate_editable_recipe_pdf_file(url)
    html = captured["html"]

    assert result["ok"] is True
    assert "Restaurant / Menu Source Info" in html
    assert "Menu Item Details" in html
    assert "Vel Asian Cuisine" in html
    assert "https://velasian.example" in html
    assert "https://velasian.example/menu" in html
    assert "https://velasian.example/order/spring-roll" in html
    assert "Kitchen Appetizers" in html
    assert "$5.99" in html
    assert "Two veggie golden crispy rolls." in html


def test_normal_recipe_pdf_does_not_include_menu_metadata(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url = "https://example.com/recipes/soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Tomato Soup",
        "ingredients": [{"ingredient": "tomato"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    captured = {}

    def fake_write_recipe_page_pdf(recipe_url, html_text, html_path, pdf_path):
        captured["html"] = html_text
        path = Path(pdf_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return path

    monkeypatch.setattr(recipe_edit_service, "write_recipe_page_pdf", fake_write_recipe_page_pdf)

    result = recipe_edit_service.generate_editable_recipe_pdf_file(url)
    html = captured["html"]

    assert result["ok"] is True
    assert "Restaurant / Menu Source Info" not in html
    assert "Menu Item Details" not in html
    assert "Tomato Soup" in html
