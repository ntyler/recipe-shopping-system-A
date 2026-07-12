from pathlib import Path

from flask import Flask
from flask import session

from PushShoppingList.services import menu_store_service
from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import storage_service
from PushShoppingList.routes import main_routes


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


def test_recipe_editor_loads_and_saves_recipe_notes(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url = "https://example.test/recipe-with-notes"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Recipe With Notes",
        "source_notes": [{
            "heading": "Top Tips",
            "items": ["Keep warm while serving."],
        }],
        "ingredients": [{"ingredient": "salt", "quantity": "1", "unit": "tsp"}],
        "instructions": [{"instruction": "Cook until done."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    assert loaded["recipe_notes"] == [{
        "heading": "Top Tips",
        "items": ["Keep warm while serving."],
    }]

    recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, recipe_notes=[{
            "heading": "Storing & Reheating",
            "items": ["Reheat gently.", ""],
        }]),
    )
    saved = recipe_edit_service.load_recipe_output(url)

    assert saved["recipe_notes"] == [{
        "heading": "Storing & Reheating",
        "items": ["Reheat gently."],
    }]


def test_recipe_editor_saves_ingredient_substitutions(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url = "https://example.test/recipe-with-ingredient-options"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Recipe With Ingredient Options",
        "ingredients": [{
            "ingredient": "potatoes",
            "quantity": "4",
            "unit": "medium",
            "substitutions": ["sweet potatoes"],
        }],
        "instructions": [{"instruction": "Cook until done."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    assert [
        item["ingredient"]
        for item in loaded["ingredients"][0]["substitutions"]
    ] == ["sweet potatoes"]
    assert loaded["ingredients"][0]["substitutions"][0]["store_section"] == "PRODUCE"

    recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(url, ingredients=[{
            "ingredient": "chicken broth",
            "quantity": "2",
            "unit": "cups",
            "substitutions": ["vegetable broth", "vegetable broth", {"name": "mushroom broth"}],
        }]),
    )
    saved = recipe_edit_service.load_recipe_output(url)

    assert [
        item["ingredient"]
        for item in saved["ingredients"][0]["substitutions"]
    ] == ["vegetable broth", "mushroom broth"]
    assert all(item["store_section"] for item in saved["ingredients"][0]["substitutions"])


def test_recipe_editor_menu_metadata_panels_are_wired_before_amount():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    js = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")

    restaurant_panel = template.index("recipeEditRestaurantMenuSourceDetails")
    menu_item_panel = template.index("recipeEditMenuItemDetails")
    recipe_amount = template.index("recipeEditScaleMultiplier")
    source_files_panel = template.index("recipeEditSourceFilesDetails")
    menu_item_markup = template[menu_item_panel:recipe_amount]

    assert source_files_panel < restaurant_panel < menu_item_panel < recipe_amount
    assert "Restaurant / Menu Source Info" in template
    assert "Menu Item Details" in template
    assert 'id="recipeEditMenuSourceSelect"' in template
    assert 'id="recipeEditRestaurantId"' in template
    assert 'id="recipeEditMenuId"' in template
    assert "Custom Source" in template
    assert 'id="recipeEditRestaurantWebsiteUrlLink"' in template
    assert 'id="recipeEditSourceMenuUrlLink"' in template
    assert 'id="recipeEditMenuOrderUrlLink"' in template
    assert 'id="recipeEditMenuOrderUrl"' in template
    assert "Menu Section" in menu_item_markup
    assert 'id="recipeEditCategoryMenuSection"' in menu_item_markup
    assert menu_item_markup.index("recipeEditMenuItemName") < menu_item_markup.index("recipeEditMenuSectionField")
    assert menu_item_markup.index("recipeEditMenuSectionField") < menu_item_markup.index("recipeEditMenuOrderUrl")
    menu_section_button_start = menu_item_markup.index("recipe-edit-menu-section-select")
    menu_section_button_end = menu_item_markup.index(">", menu_section_button_start)
    assert "recipe-edit-row-menu-btn" not in menu_item_markup[menu_section_button_start:menu_section_button_end]
    assert 'id="recipeEditMenuSection"' not in template
    assert '<textarea id="recipeEditMenuDescription" rows="3">' in template
    assert "panel.hidden = !showPanels;" in js
    assert "RECIPE_EDIT_MENU_RELATION_INPUT_IDS" in js
    assert "function applyRecipeMenuSourceSelection" in js
    assert "function populateRecipeMenuSourceSelect" in js
    assert "function recipeMenuMetadataPanelsVisible()" in js
    assert "return payload;" in js[js.index("function collectRecipeMenuMetadataPayload"):js.index("function currentRecipeEditorPdfFieldValues")]
    assert ".recipe-edit-menu-metadata-details" in css
    assert ".recipe-edit-menu-metadata-grid" in css
    assert ".recipe-edit-menu-source-select-field" in css


def test_menu_order_icon_hooks_and_row_data_are_present(monkeypatch):
    current_template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    cookbook_template = read_text("PushShoppingList/templates/sections/cookbooks.html")
    css = read_text("PushShoppingList/static/css/app.css")
    route_source = read_text("PushShoppingList/routes/main_routes.py")
    cookbook_service = read_text("PushShoppingList/services/cookbook_service.py")
    recipe_url = "https://velasian.example/menu#spring-roll"
    recipe_data = {
        "recipe_title": "Spring Roll",
        "source_type": "menu_item_inferred",
        "menu_order_url": "https://velasian.example/order/spring-roll",
        "deep_link_url": "https://velasian.example/order/spring-roll",
    }

    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda url: recipe_data if url == recipe_url else {})
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(main_routes, "recipe_pdf_public_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(main_routes, "recipe_archive_pdf_exists", lambda *args, **kwargs: False)

    rows = main_routes.recipe_url_log_rows([{"url": recipe_url, "name": "Spring Roll", "quantity": 1}])

    assert rows[0]["menu_order_url"] == "https://velasian.example/order/spring-roll"
    assert rows[0]["deep_link_url"] == "https://velasian.example/order/spring-roll"
    assert "recipe-url-menu-order-link" in current_template
    assert "cookbook-recipe-menu-order-link" in cookbook_template
    assert current_template.index("recipe-url-menu-order-link") < current_template.index("recipe-url-summary-menu-wrap", current_template.index("recipe-url-menu-order-link"))
    assert cookbook_template.index("cookbook-recipe-menu-order-link") < cookbook_template.index("cookbook-recipe-menu-wrap", cookbook_template.index("cookbook-recipe-menu-order-link"))
    assert ".recipe-url-summary-row:has(.recipe-url-menu-order-link)" in css
    assert ".recipe-url-menu-order-link" in css
    assert '"menu_order_url",' in cookbook_service
    assert '"deep_link_url",' in cookbook_service
    assert '"menu_order_url": clean_display_text' in route_source


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
    url, detail = seed_menu_derived_recipe()

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert loaded["is_menu_derived"] is True
    assert loaded["menu_metadata_available"] is True
    assert loaded["menu_source_value"] == f'{detail["restaurant"]["id"]}|{detail["menu"]["id"]}'
    assert any(
        option["restaurant_id"] == detail["restaurant"]["id"]
        and option["menu_id"] == detail["menu"]["id"]
        and option["restaurant_name"] == "Vel Asian Cuisine"
        for option in loaded["menu_source_options"]
    )
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


def test_menu_source_options_dedupe_same_source_records_and_prefer_menu_option(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    menu_store_service.save_menu_store({
        "restaurants": [
            {
                "id": "restaurant-primary",
                "restaurant_name": "Vel Asian Cuisine",
                "source_menu_url": source_url,
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
            },
            {
                "id": "restaurant-typo",
                "restaurant_name": "Vel Asian Cusine",
                "source_menu_url": source_url,
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
            },
        ],
        "menus": [
            {
                "id": "menu-primary",
                "restaurant_id": "restaurant-primary",
                "menu_title": "Vel Asian Cuisine Menu",
                "source_url": "",
                "source_type": "cookbook_generated_menu",
                "cookbook_id": "vel-asian-cuisine",
            },
            {
                "id": "menu-typo",
                "restaurant_id": "restaurant-typo",
                "menu_title": "Vel Asian Cusine Menu",
                "source_url": "",
                "source_type": "cookbook_generated_menu",
                "cookbook_id": "vel-asian-cusine",
            },
        ],
        "sections": [],
        "items": [],
        "pdf_logs": [],
    })

    options = recipe_edit_service.editable_menu_source_options()

    assert len(options) == 1
    assert options[0]["restaurant_id"] == "restaurant-primary"
    assert options[0]["menu_id"] == "menu-primary"
    assert options[0]["restaurant_name"] == "Vel Asian Cuisine"
    assert options[0]["source_menu_url"] == source_url


def test_menu_source_option_exposes_existing_restaurant_logo_and_rating(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    menu_store_service.save_menu_store({
        "restaurants": [{
            "id": "restaurant-pisco",
            "restaurant_name": "Pisco Mar",
            "logo_url": "https://example.com/pisco-mar-logo.png",
            "rating": "4.5",
        }],
        "menus": [],
        "sections": [],
        "items": [],
        "pdf_logs": [],
    })

    option = recipe_edit_service.editable_menu_source_options()[0]

    assert option["restaurant_logo_url"] == "https://example.com/pisco-mar-logo.png"
    assert option["restaurant_rating"] == "4.5"


def test_menu_source_option_formats_location_from_separate_restaurant_fields(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    menu_store_service.save_menu_store({
        "restaurants": [{
            "id": "restaurant-pisco",
            "restaurant_name": "Pisco Mar",
            "address_line": "9546 Allisonville Rd",
            "city": "Indianapolis",
            "state": "Indiana",
            "postal_code": "46250",
            "country": "USA",
        }],
        "menus": [],
        "sections": [],
        "items": [],
        "pdf_logs": [],
    })

    option = recipe_edit_service.editable_menu_source_options()[0]

    assert option["restaurant_address"] == "9546 Allisonville Rd, Indianapolis, Indiana 46250, USA"


def test_inline_restaurant_source_update_edits_linked_record_without_creating_duplicate(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()
    restaurant_id = detail["restaurant"]["id"]
    menu_id = detail["menu"]["id"]

    result = recipe_edit_service.update_editable_restaurant_source(url, {
        "restaurant_id": restaurant_id,
        "menu_id": menu_id,
        "restaurant_name": "Vel Asian Kitchen",
        "restaurant_logo_url": "https://velasian.example/logo.png",
        "restaurant_rating": "4.7",
        "restaurant_phone": "3175550199",
        "restaurant_website_url": "https://velasian.example",
        "source_menu_url": "https://velasian.example/new-menu",
        "menu_item_url": "https://velasian.example/new-menu?item=spring-roll",
        "restaurant_street_address": "2 Main St",
        "restaurant_city": "Indianapolis",
        "restaurant_state": "Indiana",
        "restaurant_postal_code": "46250",
        "restaurant_country": "USA",
        "restaurant_hours_text": "Monday: 11:00-21:00\nTuesday: Closed\nNotes: Holiday hours may vary",
        "restaurant_current_status": "temporarily_closed",
        "restaurant_promotions": "Lunch rewards",
        "restaurant_online_payment_available": "",
        "restaurant_delivery_available": "false",
    })
    store = menu_store_service.load_menu_store()
    restaurant = menu_store_service.restaurant_for(store, restaurant_id)
    menu = menu_store_service.find_menu(store, menu_id)

    assert result["ok"] is True
    assert len(store["restaurants"]) == 1
    assert restaurant["restaurant_name"] == "Vel Asian Kitchen"
    assert restaurant["logo_url"] == "https://velasian.example/logo.png"
    assert restaurant["rating"] == "4.7"
    assert restaurant["address_line"] == "2 Main St"
    assert restaurant["city"] == "Indianapolis"
    assert restaurant["hours_text"].startswith("Monday: 11:00-21:00")
    assert restaurant["current_status"] == "temporarily_closed"
    assert restaurant["rewards_text"] == "Lunch rewards"
    assert restaurant["online_payment_available"] is None
    assert restaurant["delivery_available"] is False
    assert menu["source_url"] == "https://velasian.example/new-menu"
    assert result["restaurant"]["menu_item_url"] == "https://velasian.example/new-menu?item=spring-roll"
    assert recipe_edit_service.load_recipe_output(url)["menu_item_url"] == "https://velasian.example/new-menu?item=spring-roll"
    assert result["restaurant"]["restaurant_address"] == "2 Main St, Indianapolis, Indiana 46250, USA"


def test_inline_restaurant_source_update_rejects_unlinked_restaurant(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, _detail = seed_menu_derived_recipe()

    result = recipe_edit_service.update_editable_restaurant_source(url, {
        "assign_restaurant": "false",
        "restaurant_id": "another-restaurant",
        "restaurant_name": "Wrong Restaurant",
    })

    assert result["ok"] is False
    assert "not linked" in result["error"]


def test_source_documents_update_preserves_recipe_identity_and_updates_linked_menu(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()

    result = recipe_edit_service.update_editable_source_documents(url, {
        "document_source_url": "https://example.com/direct-source",
        "source_menu_url": "https://example.com/full-menu",
        "menu_item_url": "https://example.com/full-menu?item=one",
    })
    saved = recipe_edit_service.load_recipe_output(url)
    menu = menu_store_service.find_menu(menu_store_service.load_menu_store(), detail["menu"]["id"])

    assert result["ok"] is True
    assert saved["source_url"] == url
    assert saved["document_source_url"] == "https://example.com/direct-source"
    assert saved["menu_item_url"] == "https://example.com/full-menu?item=one"
    assert menu["source_url"] == "https://example.com/full-menu"


def test_source_documents_update_restaurant_only_normalized_menu_url(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    created = recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Restaurant Only",
        "source_menu_url": "https://example.com/old-menu",
    })
    restaurant_id = created["restaurant"]["restaurant_id"]
    url = "https://example.com/restaurant-only-recipe"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "restaurant_id": restaurant_id,
        "source_menu_url": "https://example.com/old-menu",
        "menu_item_url": "https://example.com/old-menu?item=one",
        "recipe_title": "Restaurant Only Dish",
        "ingredients": [],
        "instructions": [],
    })

    result = recipe_edit_service.update_editable_source_documents(url, {
        "document_source_url": url,
        "source_menu_url": "https://example.com/new-menu",
        "menu_item_url": "https://example.com/new-menu?item=one",
    })
    restaurant = menu_store_service.restaurant_for(menu_store_service.load_menu_store(), restaurant_id)
    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert result["ok"] is True
    assert restaurant["menu_url"] == "https://example.com/new-menu"
    assert restaurant["source_menu_url"] == "https://example.com/new-menu"
    assert loaded["source_menu_url"] == "https://example.com/new-menu"
    assert recipe_edit_service.load_recipe_output(url)["menu_item_url"] == "https://example.com/new-menu?item=one"


def test_normalized_restaurant_menu_url_precedes_legacy_recipe_snapshot(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    created = recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Shared Menu Restaurant",
        "source_menu_url": "https://example.com/original-menu",
    })
    restaurant_id = created["restaurant"]["restaurant_id"]
    url = "https://example.com/shared-menu-recipe"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "restaurant_id": restaurant_id,
        "source_menu_url": "https://example.com/stale-embedded-menu",
        "recipe_title": "Shared Dish",
        "ingredients": [],
        "instructions": [],
    })

    result = recipe_edit_service.update_editable_restaurant(restaurant_id, {
        "restaurant_name": "Shared Menu Restaurant",
        "source_menu_url": "https://example.com/normalized-menu",
    })
    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert result["ok"] is True
    assert loaded["source_menu_url"] == "https://example.com/normalized-menu"
    assert recipe_edit_service.load_recipe_output(url)["source_menu_url"] == "https://example.com/stale-embedded-menu"


def test_restaurant_usage_is_computed_from_linked_recipes(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()

    result = recipe_edit_service.editable_restaurant_usage(detail["restaurant"]["id"])

    assert result["ok"] is True
    assert result["recipe_count"] == 1
    assert result["recipes"][0]["url"] == url
    assert result["recipes"][0]["title"]


def test_restaurant_directory_lists_searches_and_loads_stable_records(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    first = recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://fromtherestaurant.com",
        "restaurant_city": "Indianapolis",
        "restaurant_state": "Indiana",
    })
    recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Vel Asian Cuisine",
        "restaurant_city": "Loveland",
        "restaurant_state": "Ohio",
    })

    result = recipe_edit_service.list_editable_restaurants("indianapolis")
    loaded = recipe_edit_service.get_editable_restaurant(first["restaurant"]["restaurant_id"])

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["restaurants"][0]["restaurant_name"] == "Pisco Mar"
    assert loaded["restaurant"]["id"] == first["restaurant"]["restaurant_id"]
    assert loaded["restaurant"]["restaurant_id"] == first["restaurant"]["restaurant_id"]
    assert loaded["restaurant"]["created_at"]


def test_restaurant_directory_is_isolated_by_user_and_guest_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    app = Flask(__name__)
    app.secret_key = "restaurant-scope-test"

    with app.test_request_context("/"):
        session["user_id"] = "user-a"
        created = recipe_edit_service.create_editable_restaurant({"restaurant_name": "User A Cafe"})
        assert created["ok"] is True
        assert [row["restaurant_name"] for row in recipe_edit_service.list_editable_restaurants()["restaurants"]] == [
            "User A Cafe",
        ]
        stored = menu_store_service.load_menu_store()["restaurants"][0]
        assert stored["owner_user_id"] == "user-a"
        assert stored["account_scope"] == "user"

    with app.test_request_context("/"):
        session["user_id"] = "user-b"
        assert recipe_edit_service.list_editable_restaurants()["restaurants"] == []
        recipe_edit_service.create_editable_restaurant({"restaurant_name": "User B Bistro"})

    with app.test_request_context("/"):
        session["user_id"] = "stale-user"
        session["is_guest"] = True
        session["guest_session_id"] = "guest-a"
        assert recipe_edit_service.list_editable_restaurants()["restaurants"] == []
        recipe_edit_service.create_editable_restaurant({"restaurant_name": "Guest Grill"})
        stored = menu_store_service.load_menu_store()["restaurants"][0]
        assert stored["owner_user_id"] is None
        assert stored["account_scope"] == "guest:guest-a"

    with app.test_request_context("/"):
        session["user_id"] = "user-a"
        assert [row["restaurant_name"] for row in recipe_edit_service.list_editable_restaurants()["restaurants"]] == [
            "User A Cafe",
        ]


def test_restaurant_source_can_switch_normalized_association_on_save(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()
    recipe_data = recipe_edit_service.load_recipe_output(url)
    recipe_data["menu_item_url"] = "https://velasian.example/menu?item=spring-roll"
    recipe_data["restaurant_name"] = "Legacy snapshot remains for compatibility"
    recipe_edit_service.save_recipe_output(url, recipe_data)
    created = recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Pisco Mar",
        "restaurant_website_url": "https://pisco.example",
        "restaurant_city": "Indianapolis",
        "restaurant_state": "Indiana",
    })
    restaurant_id = created["restaurant"]["restaurant_id"]

    result = recipe_edit_service.update_editable_restaurant_source(url, {
        "action": "update",
        "assign_restaurant": True,
        "restaurant_id": restaurant_id,
        "restaurant_name": "Pisco Mar Updated",
        "restaurant_website_url": "https://pisco.example",
    })
    saved_recipe = recipe_edit_service.load_recipe_output(url)
    store = menu_store_service.load_menu_store()

    assert result["ok"] is True
    assert result["association_changed"] is True
    assert saved_recipe["restaurant_id"] == restaurant_id
    assert "menu_id" not in saved_recipe
    assert "menu_section_id" not in saved_recipe
    assert "menu_item_id" not in saved_recipe
    assert saved_recipe["menu_item_url"] == "https://velasian.example/menu?item=spring-roll"
    assert saved_recipe["restaurant_name"] == "Legacy snapshot remains for compatibility"
    assert menu_store_service.restaurant_for(store, restaurant_id)["restaurant_name"] == "Pisco Mar Updated"
    assert menu_store_service.restaurant_for(store, detail["restaurant"]["id"])


def test_restaurant_create_requires_explicit_duplicate_override_and_assigns_atomically(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_derived_recipe()
    recipe_data = recipe_edit_service.load_recipe_output(url)
    recipe_data["menu_item_url"] = "https://velasian.example/menu?item=spring-roll"
    recipe_edit_service.save_recipe_output(url, recipe_data)
    payload = {
        "action": "create",
        "restaurant_name": "Vel Asian Cuisine",
        "restaurant_phone": "3175550100",
        "restaurant_website_url": "https://velasian.example",
    }

    duplicate = recipe_edit_service.update_editable_restaurant_source(url, payload)
    assert duplicate["ok"] is False
    assert duplicate["duplicate_detected"] is True
    assert duplicate["error"] == "A similar restaurant already exists."
    assert duplicate["duplicates"][0]["restaurant_id"] == detail["restaurant"]["id"]
    assert len(menu_store_service.load_menu_store()["restaurants"]) == 1
    assert recipe_edit_service.load_recipe_output(url)["restaurant_id"] == detail["restaurant"]["id"]

    string_false_override = recipe_edit_service.update_editable_restaurant_source(url, {
        **payload,
        "create_anyway": "false",
    })
    assert string_false_override["duplicate_detected"] is True
    assert len(menu_store_service.load_menu_store()["restaurants"]) == 1

    created = recipe_edit_service.update_editable_restaurant_source(url, {
        **payload,
        "create_anyway": True,
    })
    saved_recipe = recipe_edit_service.load_recipe_output(url)

    assert created["ok"] is True
    assert created["created"] is True
    assert created["association_changed"] is True
    assert len(menu_store_service.load_menu_store()["restaurants"]) == 2
    assert saved_recipe["restaurant_id"] == created["restaurant"]["restaurant_id"]
    assert saved_recipe["menu_item_url"] == "https://velasian.example/menu?item=spring-roll"


def test_restaurant_update_stores_structured_aliases_and_preserves_created_at(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    created = recipe_edit_service.create_editable_restaurant({"restaurant_name": "Hours Cafe"})
    restaurant_id = created["restaurant"]["restaurant_id"]
    store = menu_store_service.load_menu_store()
    store["restaurants"][0]["created_at"] = "2020-01-01T00:00:00Z"
    store["restaurants"][0]["raw_hours_data"] = "Legacy prose hours"
    menu_store_service.save_menu_store(store)

    result = recipe_edit_service.update_editable_restaurant(restaurant_id, {
        "restaurant_name": "Hours Cafe",
        "source_menu_url": "https://hours.example/menu",
        "restaurant_hours_text": (
            "Monday: 11:00-21:00, 22:00-23:00\n"
            "Tuesday: Closed\nNotes: Kitchen closes 30 minutes early"
        ),
        "restaurant_online_payment_available": "",
        "restaurant_delivery_available": "true",
    })
    restaurant = menu_store_service.restaurant_for(menu_store_service.load_menu_store(), restaurant_id)

    assert result["ok"] is True
    assert restaurant["created_at"] == "2020-01-01T00:00:00Z"
    assert restaurant["menu_url"] == "https://hours.example/menu"
    assert restaurant["weekly_hours"]["monday"]["ranges"][1] == {"opens": "22:00", "closes": "23:00"}
    assert restaurant["weekly_hours"]["tuesday"]["closed"] is True
    assert restaurant["hours_notes"] == "Kitchen closes 30 minutes early"
    assert restaurant["raw_hours_data"] == "Legacy prose hours"
    assert restaurant["online_payment"] is None
    assert restaurant["delivery"] is True
    assert restaurant["updated_at"]


def test_legacy_embedded_restaurant_is_lazily_backfilled_without_deleting_snapshot(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    existing = recipe_edit_service.create_editable_restaurant({
        "restaurant_name": "Pisco Mar",
        "restaurant_phone": "317-537-2025",
        "restaurant_city": "Indianapolis",
    })
    url = "https://example.test/legacy-recipe"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Legacy Dish",
        "restaurant_name": "Pisco Mar",
        "restaurant_phone": "(317) 537-2025",
        "menu_item_url": "https://example.test/menu?item=legacy",
        "ingredients": [],
        "instructions": [],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    saved = recipe_edit_service.load_recipe_output(url)

    assert loaded["restaurant_id"] == existing["restaurant"]["restaurant_id"]
    assert saved["restaurant_id"] == existing["restaurant"]["restaurant_id"]
    assert saved["restaurant_name"] == "Pisco Mar"
    assert saved["restaurant_phone"] == "(317) 537-2025"
    assert saved["menu_item_url"] == "https://example.test/menu?item=legacy"


def test_url_only_legacy_recipe_backfills_from_normalized_menu_item(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, detail = seed_menu_recipe_url_match()
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "source_pdf_path": "legacy-menu.pdf",
        "recipe_title": "Spring Roll",
        "ingredients": [],
        "instructions": [],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]
    saved = recipe_edit_service.load_recipe_output(url)

    assert loaded["restaurant_id"] == detail["restaurant"]["id"]
    assert saved["restaurant_id"] == detail["restaurant"]["id"]
    assert saved["menu_id"] == detail["menu"]["id"]
    assert saved["menu_item_id"] == detail["items"][0]["id"]
    assert saved["source_pdf_path"] == "legacy-menu.pdf"


def test_legacy_backfill_logs_ambiguous_matches_without_guessing(monkeypatch, tmp_path, capsys):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    for city in ("Indianapolis", "Chicago"):
        recipe_edit_service.create_editable_restaurant({
            "restaurant_name": "Shared Name Cafe",
            "restaurant_city": city,
        }, create_anyway=True)
    url = "https://example.test/ambiguous-legacy-recipe"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Ambiguous Dish",
        "restaurant_name": "Shared Name Cafe",
        "ingredients": [],
        "instructions": [],
    })

    recipe_edit_service.load_editable_recipe(url)
    saved = recipe_edit_service.load_recipe_output(url)

    assert not saved.get("restaurant_id")
    assert "[restaurant_backfill] ambiguous" in capsys.readouterr().out


def test_menu_derived_recipe_loads_canonical_source_for_duplicate_source_ids(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    recipe_url = f"{source_url}&menu_item=menu-item-1-Spring_Roll"
    menu_store_service.save_menu_store({
        "restaurants": [
            {
                "id": "restaurant-primary",
                "restaurant_name": "Vel Asian Cuisine",
                "source_menu_url": source_url,
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
            },
            {
                "id": "restaurant-typo",
                "restaurant_name": "Vel Asian Cusine",
                "source_menu_url": source_url,
                "full_address": "912 LOVELAND MADEIRA RD, LOVELAND, OH 45140",
            },
        ],
        "menus": [
            {
                "id": "menu-primary",
                "restaurant_id": "restaurant-primary",
                "menu_title": "Vel Asian Cuisine Menu",
                "source_url": "",
                "source_type": "cookbook_generated_menu",
            },
            {
                "id": "menu-typo",
                "restaurant_id": "restaurant-typo",
                "menu_title": "Vel Asian Cusine Menu",
                "source_url": "",
                "source_type": "cookbook_generated_menu",
            },
        ],
        "sections": [],
        "items": [],
        "pdf_logs": [],
    })
    recipe_edit_service.save_recipe_output(recipe_url, {
        "source_url": recipe_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "restaurant_id": "restaurant-typo",
        "menu_id": "menu-typo",
        "restaurant_name": "Vel Asian Cusine",
        "source_menu_url": source_url,
        "recipe_title": "Spring Roll",
        "ingredients": [{"ingredient": "cabbage", "quantity": "1", "unit": "cup"}],
        "instructions": [{"instruction": "Roll and fry until golden."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(recipe_url)["recipe"]

    assert len(loaded["menu_source_options"]) == 1
    assert loaded["menu_source_value"] == "restaurant-primary|menu-primary"
    assert loaded["restaurant_id"] == "restaurant-primary"
    assert loaded["menu_id"] == "menu-primary"
    assert loaded["restaurant_name"] == "Vel Asian Cuisine"


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


def test_menu_order_url_upgrades_old_cartana_fallback_url(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    source_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    old_fallback_url = f"{source_url}&menu_item_id=MIT354158"
    expected_url = (
        "https://www.velasiancuisine.com/rs/menuItem_home.action?"
        "resInput=RES4902&menuIdInput=MEN25930&menuItemIdInput=MIT354158&orderType=null"
    )
    recipe_edit_service.save_recipe_output(old_fallback_url, {
        "source_url": old_fallback_url,
        "source_type": "menu_item_inferred",
        "ai_inferred": True,
        "menu_id": "MEN25930",
        "menu_item_id": "MIT354158",
        "menu_section": "Kitchen Appetizers",
        "menu_item_name": "Takoyi",
        "menu_order_url": old_fallback_url,
        "deep_link_url": old_fallback_url,
        "menu_price": "$8.99",
        "menu_description": "5pcs of Japanese fried octopus ball with takoyaki sauce, mayo and bonito flakes.",
    })

    loaded = recipe_edit_service.load_editable_recipe(old_fallback_url)["recipe"]

    assert loaded["source_menu_url"] == source_url
    assert loaded["menu_order_url"] == expected_url


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


def test_saving_menu_source_selection_relinks_recipe_to_shared_source(monkeypatch, tmp_path):
    configure_editor_recipe_storage(monkeypatch, tmp_path)
    url, first_detail = seed_menu_derived_recipe()
    second_detail = menu_store_service.upsert_menu_from_facts({
        "source_url": "https://thai.example/menu",
        "restaurant": {
            "restaurant_name": "Thai Garden",
            "restaurant_website_url": "https://thai.example",
            "cuisine_tags": ["Thai"],
            "phone": "317-555-0200",
            "full_address": "22 Garden Rd, Indianapolis, IN",
            "hours_text": "Daily 10-10",
            "current_status": "Open",
            "delivery_available": True,
            "online_payment_available": False,
            "rewards_text": "Lunch rewards",
        },
        "menu": {
            "menu_title": "Thai Garden Menu",
        },
        "sections": [{
            "section_name": "Appetizers",
            "items": [{
                "item_name": "Garden Roll",
                "menu_price": "$7.25",
                "menu_description": "Fresh herbs and crisp vegetables.",
            }],
        }],
    })

    result = recipe_edit_service.save_editable_recipe(
        url,
        editable_payload(
            url,
            restaurant_id=second_detail["restaurant"]["id"],
            menu_id=second_detail["menu"]["id"],
            menu_section_id="",
            menu_item_id="",
            restaurant_name="Thai Garden",
            restaurant_website_url="https://thai.example",
            source_menu_url="https://thai.example/menu",
            restaurant_cuisine_tags="Thai",
            restaurant_phone="317-555-0200",
            restaurant_address="22 Garden Rd, Indianapolis, IN",
            restaurant_hours_text="Daily 10-10",
            restaurant_current_status="Open",
            restaurant_promotions="Lunch rewards",
            restaurant_online_payment_available="false",
            restaurant_delivery_available="true",
            menu_section="Appetizers",
            menu_item_name="Garden Roll",
            menu_order_url="",
            menu_price="$7.25",
            menu_description="Fresh herbs and crisp vegetables.",
        ),
    )
    saved = recipe_edit_service.load_recipe_output(url)
    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]

    assert result["ok"] is True
    assert saved["restaurant_id"] == second_detail["restaurant"]["id"]
    assert saved["menu_id"] == second_detail["menu"]["id"]
    assert saved.get("menu_item_id") in {None, ""}
    assert saved.get("menu_section_id") in {None, ""}
    assert loaded["restaurant_id"] == second_detail["restaurant"]["id"]
    assert loaded["menu_id"] == second_detail["menu"]["id"]
    assert loaded["restaurant_id"] != first_detail["restaurant"]["id"]
    assert loaded["restaurant_name"] == "Thai Garden"
    assert loaded["source_menu_url"] == "https://thai.example/menu"
    assert loaded["menu_source_value"] == f'{second_detail["restaurant"]["id"]}|{second_detail["menu"]["id"]}'
    assert loaded["menu_item_name"] == "Garden Roll"
    assert loaded["menu_price"] == "$7.25"


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
