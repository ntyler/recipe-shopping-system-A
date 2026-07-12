from pathlib import Path
from io import BytesIO

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import menu_import_service
from PushShoppingList.services import menu_builder_service
from PushShoppingList.services import menu_pdf_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import user_account_service
from PushShoppingList.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def sample_menu_facts(source_url="https://example.com/menu"):
    return {
        "source_url": source_url,
        "source_type": "imported_menu",
        "restaurant": {
            "restaurant_name": "Vel Asian Cuisine",
            "restaurant_website_url": "https://example.com",
            "cuisine_tags": ["Asian", "Japanese"],
            "phone": "(317) 300-1057",
        },
        "menu": {
            "menu_title": "Vel Asian Cuisine Menu",
            "menu_subtitle": "Asian, Burmese, Sushi, Thai, Vietnamese",
        },
        "sections": [
            {
                "section_name": "Kitchen Appetizers",
                "section_description": "Appetizers from the Kitchen",
                "items": [
                    {
                        "item_name": "Spring Roll",
                        "menu_price": "$5.99",
                        "menu_description": "2 veggie golden crispy rolls.",
                        "menu_order_url": "https://example.com/order/spring-roll",
                        "dietary_tags": ["Vegetarian"],
                    },
                    {
                        "item_name": "Crab Wonton",
                        "menu_price": None,
                        "menu_description": None,
                    },
                ],
            }
        ],
    }


def test_menu_store_persists_preview_entities_without_recipes(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")

    detail = menu_store_service.upsert_menu_from_facts(
        sample_menu_facts(),
        cookbook_id="dinner",
        cookbook_name="Dinner",
    )
    store = menu_store_service.load_menu_store()

    assert detail["menu"]["cookbook_id"] == "dinner"
    assert detail["restaurant"]["restaurant_name"] == "Vel Asian Cuisine"
    assert len(store["restaurants"]) == 1
    assert len(store["menus"]) == 1
    assert len(store["sections"]) == 1
    assert len(store["items"]) == 2
    assert "recipes" not in store
    assert store["items"][1]["menu_price"] is None
    assert store["items"][1]["menu_description"] is None
    assert store["items"][0]["menu_order_url"] == "https://example.com/order/spring-roll"


def test_menu_reimport_same_source_updates_without_duplicate_records(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    facts = sample_menu_facts()

    first = menu_store_service.upsert_menu_from_facts(facts, cookbook_id="dinner", cookbook_name="Dinner")
    facts["sections"][0]["items"].append({"item_name": "Takoyi", "menu_price": "$8.99"})
    second = menu_store_service.upsert_menu_from_facts(facts, cookbook_id="dinner", cookbook_name="Dinner")
    store = menu_store_service.load_menu_store()

    assert second["menu"]["id"] == first["menu"]["id"]
    assert len(store["restaurants"]) == 1
    assert len(store["menus"]) == 1
    assert len(store["sections"]) == 1
    assert len(store["items"]) == 3


def test_menu_reimport_same_source_with_typo_reuses_existing_source(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    facts = sample_menu_facts("https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902")

    first = menu_store_service.upsert_menu_from_facts(
        facts,
        cookbook_id="vel-asian-cuisine",
        cookbook_name="Vel Asian Cuisine",
    )
    typo_facts = sample_menu_facts("https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902")
    typo_facts["restaurant"]["restaurant_name"] = "Vel Asian Cusine"
    typo_facts["menu"]["menu_title"] = "Vel Asian Cusine Menu"
    second = menu_store_service.upsert_menu_from_facts(
        typo_facts,
        cookbook_id="vel-asian-cusine",
        cookbook_name="Vel Asian Cusine",
    )
    store = menu_store_service.load_menu_store()

    assert second["restaurant"]["id"] == first["restaurant"]["id"]
    assert second["menu"]["id"] == first["menu"]["id"]
    assert len(store["restaurants"]) == 1
    assert len(store["menus"]) == 1
    assert store["restaurants"][0]["restaurant_name"] == "Vel Asian Cuisine"
    assert store["menus"][0]["cookbook_id"] == "vel-asian-cuisine"


def test_selected_menu_items_keep_restaurant_menu_section_and_item_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    detail = menu_store_service.upsert_menu_from_facts(sample_menu_facts(), cookbook_id="dinner")
    selected_item = detail["items"][0]

    sections = menu_store_service.selected_items_as_sections(
        detail["menu"]["id"],
        [selected_item["id"]],
    )
    item = sections[0]["items"][0]

    assert item["item_name"] == "Spring Roll"
    assert item["restaurant_id"] == detail["restaurant"]["id"]
    assert item["menu_id"] == detail["menu"]["id"]
    assert item["menu_section_id"] == selected_item["menu_section_id"]
    assert item["menu_item_id"] == selected_item["id"]
    assert item["description"] == "2 veggie golden crispy rolls."
    assert item["price"] == "$5.99"
    assert item["menu_order_url"] == "https://example.com/order/spring-roll"


def test_menu_fact_url_extraction_uses_cartana_payload_without_recipe_generation(monkeypatch):
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

    monkeypatch.setattr(menu_import_service, "fetch_menu_page_html", lambda url: "<html><title>Vel Asian Cuisine</title></html>")
    monkeypatch.setattr(menu_import_service, "menu_page_visible_text", lambda html: "Vel Asian Cuisine Asian Japanese")
    monkeypatch.setattr(menu_import_service, "fetch_cartana_menu_payload", lambda url, html: (payload, {"ok": True}))

    result = menu_import_service.extract_menu_facts_from_url("https://example.com/rs/menu_home.action?resInput=RES1")

    assert result["ok"] is True
    assert result["menu_sections_found"] == 1
    assert result["menu_items_found"] == 1
    assert result["sections"][0]["items"][0]["item_name"] == "Spring Roll"
    assert result["sections"][0]["items"][0]["menu_price"] == "$5.99"
    assert result["sections"][0]["items"][0]["menu_order_url"] == (
        "https://example.com/rs/menuItem_home.action?"
        "resInput=RES1&menuIdInput=MEN1&menuItemIdInput=MIT1&orderType=null"
    )
    assert "recipes" not in result


def test_menu_pdf_upload_uses_menu_pdf_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    detail = menu_store_service.upsert_menu_from_facts(sample_menu_facts(), cookbook_id="dinner")
    pdf_path = tmp_path / "vel-menu.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    log = menu_store_service.record_menu_pdf_generated(
        detail["menu"]["id"],
        "Vel Menu",
        pdf_path,
        generated_by_model="gpt-5.5",
    )
    upload_calls = []

    def fake_upload(path, object_prefix=cloudflare_r2_storage.PDF_OBJECT_PREFIX):
        upload_calls.append({"path": Path(path), "object_prefix": object_prefix})
        return {
            "ok": True,
            "object_key": f"{object_prefix}{Path(path).name}",
            "public_url": f"https://public.example.com/{object_prefix}{Path(path).name}",
        }

    monkeypatch.setattr(menu_pdf_service.cloudflare_r2_storage, "upload_pdf", fake_upload)

    result = menu_pdf_service.upload_menu_pdf(detail["menu"]["id"], log_id=log["id"])

    assert result["ok"] is True
    assert upload_calls[0]["object_prefix"] == cloudflare_r2_storage.MENU_PDF_OBJECT_PREFIX
    assert result["cloudflare_pdf_path"] == "menu-pdfs/vel-menu.pdf"


def test_menu_workflow_static_hooks_are_present():
    entry_template = (ROOT / "PushShoppingList/templates/sections/enter_recipe_links.html").read_text(encoding="utf-8")
    cookbooks_template = (ROOT / "PushShoppingList/templates/sections/cookbooks.html").read_text(encoding="utf-8")
    cookbook_builder_template = (ROOT / "PushShoppingList/templates/menus/cookbook_menu_builder.html").read_text(encoding="utf-8")
    preview_template = (ROOT / "PushShoppingList/templates/menus/menu_preview.html").read_text(encoding="utf-8")
    view_template = (ROOT / "PushShoppingList/templates/menus/menu_view.html").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/menu_routes.py").read_text(encoding="utf-8")
    app_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")
    app_css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    menu_builder_css = (ROOT / "PushShoppingList/static/css/menu_builder.css").read_text(encoding="utf-8")

    assert "Import Menu URL" in entry_template
    assert 'id="enterRecipeLinks"' in entry_template
    assert "menuImportUrlPreviewForm" in entry_template
    assert "menuMediaPreviewForm" in entry_template
    assert "Custom Restaurant Menu Builder" in entry_template
    assert "recipe-import-action-menu-builder" in entry_template
    assert "selected_cookbook_menu_builder_route" in entry_template
    assert 'id="customMenuBuilderImportForm"' in entry_template
    assert 'onsubmit="prepareImportCookbookDestination()"' in entry_template
    assert entry_template.count("data-import-cookbook-id-field") == 5
    assert ".recipe-import-action-menu-builder" in app_css
    assert "background: #155999" in app_css
    assert "Custom Restaurant Menu Builder" not in cookbooks_template
    assert "cookbook-menu-builder-launcher" not in cookbooks_template
    assert "Create a restaurant-style menu from this cookbook." in cookbook_builder_template
    assert "Back to Enter Recipe Links" in cookbook_builder_template
    assert "#enterRecipeLinks" in cookbook_builder_template
    assert "Select Cookbook" in cookbook_builder_template
    assert 'name="cookbook_id"' in cookbook_builder_template
    assert "Use Cookbook" in cookbook_builder_template
    assert '{% extends "layouts/app_layout.html" %}' in cookbook_builder_template
    assert '{% set app_html_class = "menu-builder-document" %}' in cookbook_builder_template
    assert '{% set app_active_nav_item = "cookbooks" %}' in cookbook_builder_template
    assert ".menu-builder-document" in menu_builder_css
    assert "min-height: 100vh" in menu_builder_css
    assert "Create Restaurant Menu Page" in cookbook_builder_template
    assert '{% extends "layouts/app_layout.html" %}' in preview_template
    assert '{% set app_active_nav_item = "menus" %}' in preview_template
    assert "Review Menu Items Before Recipe Generation" in preview_template
    assert "Generate Selected Recipes" in preview_template
    assert "Create Restaurant Menu Page" in preview_template
    assert "Export Menu PDF" in preview_template
    assert "Create Recipes From Menu Items" in view_template
    assert '{% extends "layouts/app_layout.html" %}' in view_template
    assert '{% set app_active_nav_item = "menus" %}' in view_template
    assert "Created from cookbook:" in view_template
    assert "Generated by AI Pantry" in view_template
    assert "Menu PDF Log" in view_template
    assert "/menu-import/preview" in routes
    assert "/menu-import/generate" in routes
    assert "/cookbooks/<cookbook_id>/menu-builder" in routes
    assert "/menus/<menu_id>/export-upload-pdf" in routes
    assert "menu_builder.css" in app_template


def test_menu_import_preview_requires_admin(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.post(
            "/menu-import/preview",
            data={"menu_url": "https://example.com/menu"},
            headers={"X-Requested-With": "fetch"},
        )

    assert response.status_code == 403
    assert response.get_json()["error"].startswith("Menu import is admin-only.")


def test_menu_import_job_route_requires_admin(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.post(
            "/api/jobs/menu-import",
            json={"urls": ["https://example.com/menu"]},
        )

    assert response.status_code == 403
    assert response.get_json()["error"].startswith("Menu import is admin-only.")


def test_menu_doc_photo_import_job_requires_admin_before_upload_staging(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("PushShoppingList.routes.job_routes.workspace_data_root", lambda: tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.post(
            "/api/jobs/doc-photo-import",
            data={
                "import_mode": "menu_extract",
                "menu_media": (BytesIO(b"menu text"), "menu.txt"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 403
    assert response.get_json()["error"].startswith("Menu import is admin-only.")
    assert not (tmp_path / "job_uploads").exists()


def sample_cookbook_payload():
    return {
        "cookbooks": [
            {
                "id": "vel-asian-cuisine",
                "name": "Vel Asian Cuisine",
                "menu_section_order": ["Sushi Appetizers", "Kitchen Appetizers"],
                "recipes": [
                    {
                        "url": "https://example.com/spring-roll",
                        "name": "Spring Roll",
                        "description": "Crispy vegetable rolls with sweet chili sauce.",
                        "restaurant_menu_category": "Starters",
                        "menu_section": "Kitchen Appetizers",
                        "cuisine": "Asian",
                        "sections": {"MISC": [{"name": "cabbage"}, {"name": "carrot"}]},
                    },
                    {
                        "url": "https://example.com/mango-salad",
                        "name": "Mango Salad",
                        "description": "Fresh mango salad with herbs.",
                        "restaurant_menu_category": "Salads",
                        "menu_section": "Sushi Appetizers",
                        "cuisine": "Asian",
                    },
                ],
            }
        ]
    }


def configure_menu_builder_test_paths(monkeypatch, tmp_path, user_id="menu-user"):
    monkeypatch.setattr(cookbook_service, "COOKBOOKS_FILE", tmp_path / "cookbooks.json")
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    cookbook_service.save_cookbooks(sample_cookbook_payload())
    user_account_service.save_users({
        "users": [{
            "user_id": user_id,
            "email": "menu@example.com",
            "username": "menu",
            "account_status": "active",
        }]
    })
    return user_id


def sign_in_menu_user(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_cookbook_menu_builder_route_loads_selected_cookbook(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.get("/cookbooks/vel-asian-cuisine/menu-builder")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Custom Restaurant Menu Builder" in body
    assert "Vel Asian Cuisine" in body
    assert "Cookbook" in body
    assert "Recipes" in body
    assert "Spring Roll" in body
    assert "Mango Salad" in body
    assert "Menu Section" in body


def test_cookbook_menu_builder_entry_selects_cookbook_inside_builder(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.get("/cookbooks/menu-builder")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Custom Restaurant Menu Builder" in body
    assert "Select Cookbook" in body
    assert "Use Cookbook" in body
    assert "Vel Asian Cuisine" in body
    assert "Spring Roll" not in body
    assert "Create Restaurant Menu Page" not in body


def test_cookbook_menu_builder_entry_uses_import_cookbook_query(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.get("/cookbooks/menu-builder?cookbook_id=vel-asian-cuisine")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/cookbooks/vel-asian-cuisine/menu-builder")


def test_cookbook_menu_builder_creates_cookbook_linked_menu(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        response = client.post(
            "/cookbooks/vel-asian-cuisine/menu-builder/create",
            data={
                "source_content": "all",
                "menu_title": "Vel Asian Cuisine Menu",
                "menu_subtitle": "Cookbook favorites",
                "restaurant_name": "Vel Asian Cuisine",
                "cuisine_type": "Asian",
                "theme": "polished casual",
                "price_style": "casual",
                "category_mode": "restaurant_menu",
                "include_descriptions": "1",
                "include_prices": "1",
                "include_dietary_tags": "1",
                "include_images": "1",
                "include_ai_generated_descriptions": "1",
                "include_ai_generated_prices": "1",
            },
            follow_redirects=True,
        )

    store = menu_store_service.load_menu_store()
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Vel Asian Cuisine Menu" in body
    assert "Spring Roll" in body
    assert "Mango Salad" in body
    assert len(store["menus"]) == 1
    assert store["menus"][0]["cookbook_id"] == "vel-asian-cuisine"
    assert store["menus"][0]["created_from_cookbook_id"] == "vel-asian-cuisine"
    assert store["menus"][0]["source_type"] == "cookbook_generated_menu"
    assert store["sections"][0]["cookbook_id"] == "vel-asian-cuisine"
    assert {item["recipe_url"] for item in store["items"]} == {
        "https://example.com/spring-roll",
        "https://example.com/mango-salad",
    }
    assert all(item["source_type"] == "cookbook_recipe" for item in store["items"])


def test_cookbook_generated_menu_service_uses_selected_recipes(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    cookbook = sample_cookbook_payload()["cookbooks"][0]

    result = menu_builder_service.create_menu_from_cookbook(
        cookbook,
        options={
            "source_content": "selected",
            "menu_title": "Selected Vel Menu",
            "restaurant_name": "Vel Asian Cuisine",
            "include_descriptions": True,
            "include_prices": True,
            "include_dietary_tags": True,
            "include_images": False,
            "include_ai_generated_descriptions": True,
            "include_ai_generated_prices": True,
        },
        selected_recipe_urls=["https://example.com/spring-roll"],
    )
    detail = menu_store_service.get_menu(result["menu_id"])

    assert result["source_type"] == "cookbook_generated_menu"
    assert detail["menu"]["cookbook_id"] == "vel-asian-cuisine"
    assert detail["menu"]["source_type"] == "cookbook_generated_menu"
    assert [item["recipe_url"] for item in detail["items"]] == ["https://example.com/spring-roll"]
    assert detail["items"][0]["recipe_id"] == "https://example.com/spring-roll"


def test_cookbook_generated_menu_service_can_group_by_saved_menu_section(monkeypatch, tmp_path):
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    cookbook = sample_cookbook_payload()["cookbooks"][0]

    result = menu_builder_service.create_menu_from_cookbook(
        cookbook,
        options={
            "source_content": "all",
            "menu_title": "Menu Section Vel Menu",
            "restaurant_name": "Vel Asian Cuisine",
            "category_mode": "menu_section",
            "include_descriptions": True,
            "include_prices": True,
            "include_dietary_tags": True,
            "include_images": False,
            "include_ai_generated_descriptions": True,
            "include_ai_generated_prices": True,
        },
    )
    detail = menu_store_service.get_menu(result["menu_id"])

    assert [section["section_name"] for section in detail["sections"]] == [
        "Sushi Appetizers",
        "Kitchen Appetizers",
    ]
    assert detail["sections"][0]["items"][0]["item_name"] == "Mango Salad"
    assert detail["sections"][1]["items"][0]["item_name"] == "Spring Roll"
    assert detail["sections"][1]["items"][0]["source_menu_section"] == "Kitchen Appetizers"


def test_existing_cookbook_menu_can_be_ordered_by_saved_menu_section(monkeypatch, tmp_path):
    user_id = configure_menu_builder_test_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        sign_in_menu_user(client, user_id)
        create_response = client.post(
            "/cookbooks/vel-asian-cuisine/menu-builder/create",
            data={
                "source_content": "all",
                "menu_title": "Vel Asian Cuisine Menu",
                "restaurant_name": "Vel Asian Cuisine",
                "price_style": "casual",
                "category_mode": "restaurant_menu",
                "include_descriptions": "1",
                "include_prices": "1",
                "include_dietary_tags": "1",
                "include_images": "1",
                "include_ai_generated_descriptions": "1",
                "include_ai_generated_prices": "1",
            },
        )

        menu_id = menu_store_service.load_menu_store()["menus"][0]["id"]
        before_detail = menu_store_service.get_menu(menu_id)
        before_item_ids = {
            item["item_name"]: item["id"]
            for item in before_detail["items"]
        }
        order_response = client.post(
            f"/menus/{menu_id}/order-by-menu-section",
            follow_redirects=True,
        )

    after_detail = menu_store_service.get_menu(menu_id)
    after_item_ids = {
        item["item_name"]: item["id"]
        for item in after_detail["items"]
    }

    assert create_response.status_code == 302
    assert order_response.status_code == 200
    assert [section["section_name"] for section in before_detail["sections"]] == [
        "Starters",
        "Salads",
    ]
    assert [section["section_name"] for section in after_detail["sections"]] == [
        "Sushi Appetizers",
        "Kitchen Appetizers",
    ]
    assert before_item_ids == after_item_ids
    assert after_detail["sections"][0]["items"][0]["item_name"] == "Mango Salad"
    assert after_detail["sections"][1]["items"][0]["item_name"] == "Spring Roll"
