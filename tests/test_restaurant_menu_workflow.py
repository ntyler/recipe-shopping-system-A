from pathlib import Path

from PushShoppingList.services import cloudflare_r2_storage
from PushShoppingList.services import menu_import_service
from PushShoppingList.services import menu_pdf_service
from PushShoppingList.services import menu_store_service


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
    preview_template = (ROOT / "PushShoppingList/templates/menus/menu_preview.html").read_text(encoding="utf-8")
    view_template = (ROOT / "PushShoppingList/templates/menus/menu_view.html").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/menu_routes.py").read_text(encoding="utf-8")
    app_template = (ROOT / "PushShoppingList/templates/index.html").read_text(encoding="utf-8")

    assert "Import Menu URL" in entry_template
    assert "menuImportUrlPreviewForm" in entry_template
    assert "menuMediaPreviewForm" in entry_template
    assert "Custom Restaurant Menu Builder" in entry_template
    assert "Review Menu Items Before Recipe Generation" in preview_template
    assert "Generate Selected Recipes" in preview_template
    assert "Create Restaurant Menu Page" in preview_template
    assert "Export Menu PDF" in preview_template
    assert "Create Recipes From Menu Items" in view_template
    assert "Menu PDF Log" in view_template
    assert "/menu-import/preview" in routes
    assert "/menu-import/generate" in routes
    assert "/menus/<menu_id>/export-upload-pdf" in routes
    assert "menu_builder.css" in app_template
