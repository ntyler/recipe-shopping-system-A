import json
from io import BytesIO
from pathlib import Path

from flask import session
from werkzeug.datastructures import FileStorage

from PushShoppingList.app import create_app
from PushShoppingList.services import pantry_service
from PushShoppingList.services import shopping_list_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service as accounts


def configure_scoped_data(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "user_data")


def configure_users_file(monkeypatch, tmp_path):
    monkeypatch.setattr(accounts, "USERS_FILE", tmp_path / "users.json")


def sign_in(client, user_id="pantry-user"):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def test_add_or_increment_pantry_item_uses_normalized_name(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        pantry_service.add_or_increment_pantry_item({
            "ingredient_name": "Eggs",
            "quantity": 1,
            "source": "manual",
        })
        result = pantry_service.add_or_increment_pantry_item({
            "ingredient_name": "egg",
            "quantity": 2,
            "source": "shopping_list",
        })

        inventory = pantry_service.load_pantry_inventory()["items"]

    assert result["created"] is False
    assert len(inventory) == 1
    assert inventory[0]["normalized_name"] == "egg"
    assert inventory[0]["quantity"] == 3
    assert inventory[0]["source"] == "shopping_list"


def test_purchased_chicken_gets_freeze_and_expiration_suggestions(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        result = pantry_service.add_or_increment_pantry_item(
            {
                "ingredient_name": "Chicken breasts",
                "quantity": 1,
                "source": "shopping_list",
            },
            reference_date="2026-07-02",
        )

    item = result["item"]
    assert item["purchased_date"] == "2026-07-02"
    assert item["storage_location"] == "fridge"
    assert item["freeze_by_date"] == "2026-07-03"
    assert item["expiration_date"] == "2026-07-04"


def test_mark_frozen_records_frozen_date(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        result = pantry_service.add_or_increment_pantry_item(
            {
                "ingredient_name": "Chicken breasts",
                "quantity": 1,
                "source": "shopping_list",
            },
            reference_date="2026-07-02",
        )
        updated = pantry_service.update_pantry_item_lifecycle_action(
            result["item"]["id"],
            "mark_frozen",
            reference_date="2026-07-03",
        )

    assert updated["ok"] is True
    assert updated["item"]["status"] == "frozen"
    assert updated["item"]["storage_location"] == "freezer"
    assert updated["item"]["frozen_date"] == "2026-07-03"


def test_pantry_storage_locations_are_account_specific(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user-a"
        result = pantry_service.add_pantry_storage_location("Garage shelf")
        options = pantry_service.pantry_storage_location_options_for_view()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user-b"
        other_options = pantry_service.pantry_storage_location_options_for_view()

    assert result["ok"] is True
    assert result["created"] is True
    assert result["location"] == "garage-shelf"
    assert "garage-shelf" in [option["value"] for option in options]
    assert next(option for option in options if option["value"] == "garage-shelf")["removable"] is True
    assert next(option for option in options if option["value"] == "fridge")["removable"] is False
    assert "garage-shelf" not in [option["value"] for option in other_options]
    assert [option["value"] for option in other_options][:4] == [
        "pantry",
        "fridge",
        "freezer",
        "counter",
    ]


def test_remove_pantry_storage_location_keeps_defaults(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user-a"
        pantry_service.add_pantry_storage_location("Garage shelf")
        result = pantry_service.remove_pantry_storage_locations(["garage-shelf", "fridge"])
        options = pantry_service.pantry_storage_location_options_for_view()

    values = [option["value"] for option in options]

    assert result["ok"] is True
    assert result["deleted_count"] == 1
    assert result["locations"] == ["garage-shelf"]
    assert "garage-shelf" not in values
    assert "fridge" in values


def test_rename_pantry_storage_location_updates_items(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user-a"
        pantry_service.add_pantry_storage_location("Garage shelf")
        pantry_service.add_or_increment_pantry_item({
            "ingredient_name": "Paper towels",
            "quantity": 1,
            "source": "manual",
            "storage_location": "garage-shelf",
        })
        result = pantry_service.rename_pantry_storage_location("garage-shelf", "Basement shelf")
        inventory = pantry_service.load_pantry_inventory()
        options = pantry_service.pantry_storage_location_options_for_view()

    values = [option["value"] for option in options]

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["old_location"] == "garage-shelf"
    assert result["location"] == "basement-shelf"
    assert "garage-shelf" not in values
    assert "basement-shelf" in values
    assert inventory["items"][0]["storage_location"] == "basement-shelf"


def test_add_pantry_storage_location_route_persists_for_account(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "pantry-route-user")
        response = client.post(
            "/pantry/locations/add",
            data={"storage_location": "Basement freezer"},
        )

    inventory = pantry_service.load_pantry_inventory(user_id="pantry-route-user")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#aiPantryLocations")
    assert "basement-freezer" in inventory["storage_locations"]


def test_delete_pantry_storage_location_route_removes_selected_custom(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "pantry-route-user")
        client.post(
            "/pantry/locations/add",
            data={"storage_location": "Basement freezer"},
        )
        response = client.post(
            "/pantry/locations/delete",
            data={"storage_location": "basement-freezer"},
        )

    inventory = pantry_service.load_pantry_inventory(user_id="pantry-route-user")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#aiPantryLocations")
    assert "basement-freezer" not in inventory["storage_locations"]
    assert "fridge" in inventory["storage_locations"]


def test_update_pantry_storage_location_route_renames_custom_location(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client, "pantry-route-user")
        client.post(
            "/pantry/locations/add",
            data={"storage_location": "Basement freezer"},
        )
        response = client.post(
            "/pantry/locations/update",
            data={
                "old_storage_location": "basement-freezer",
                "storage_location": "Garage freezer",
            },
        )

    inventory = pantry_service.load_pantry_inventory(user_id="pantry-route-user")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#aiPantryLocations")
    assert "basement-freezer" not in inventory["storage_locations"]
    assert "garage-freezer" in inventory["storage_locations"]


def test_pantry_item_image_upload_persists_image_fields(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_IMAGE_FOLDER", tmp_path / "pantry_images")
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        created = pantry_service.add_or_increment_pantry_item(
            {
                "ingredient_name": "Atlantic salmon",
                "quantity": 1,
                "source": "manual",
            },
            reference_date="2026-07-02",
        )
        upload = FileStorage(
            stream=BytesIO(b"not-a-real-image-but-valid-upload-by-extension"),
            filename="salmon.png",
            content_type="image/png",
        )
        result = pantry_service.save_pantry_item_image_upload(created["item"]["id"], upload)
        inventory = pantry_service.load_pantry_inventory()["items"]

    assert result["ok"] is True
    assert result["image_url"].startswith("/static/generated/pantry_items/atlantic_salmon_")
    assert result["image_generated_at"]
    assert inventory[0]["image_url"] == result["image_url"]
    assert inventory[0]["image_generated_at"] == result["image_generated_at"]
    assert any((tmp_path / "pantry_images").iterdir())


def test_pantry_inventory_recovers_matching_generated_image(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_IMAGE_FOLDER", tmp_path / "pantry_images")
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        pantry_service.PANTRY_IMAGE_FOLDER.mkdir(parents=True)
        (pantry_service.PANTRY_IMAGE_FOLDER / "orphan_parsley_fc45e8f772e2.png").write_bytes(b"fake image")
        pantry_service.save_pantry_inventory({
            "items": [
                {
                    "id": "orphan-parsley-1",
                    "ingredient_name": "orphan parsley",
                    "product_name": "Orphan Parsley",
                    "quantity": 1,
                    "source": "receipt",
                    "image_url": "",
                }
            ],
        })

    with app.test_client() as client:
        sign_in(client)
        response = client.get("/sections/pantry")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "No image generated for this item." not in html
    assert "/static/generated/pantry_items/orphan_parsley_fc45e8f772e2.png" in html
    assert 'data-deferred-src="/static/generated/pantry_items/orphan_parsley_fc45e8f772e2.png"' in html


def test_pantry_name_suggestion_keeps_original_until_applied():
    suggestion = pantry_service.pantry_name_suggestion("Atlantic Salmo")

    assert suggestion["original_name"] == "Atlantic Salmo"
    assert suggestion["suggested_name"] == "Atlantic Salmon"
    assert suggestion["suggested_normalized_name"] == "atlantic salmon"


def test_apply_pantry_item_name_suggestion_updates_display_and_normalized_name(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        created = pantry_service.add_or_increment_pantry_item(
            {
                "ingredient_name": "atlantic salmo",
                "product_name": "Atlantic Salmo",
                "quantity": 1,
                "source": "receipt",
            },
            reference_date="2026-07-02",
        )
        result = pantry_service.apply_pantry_item_name_suggestion(created["item"]["id"])
        inventory = pantry_service.load_pantry_inventory()["items"]

    assert result["ok"] is True
    assert result["ingredient_name"] == "Atlantic Salmon"
    assert result["product_name"] == "Atlantic Salmon"
    assert result["normalized_name"] == "atlantic salmon"
    assert inventory[0]["ingredient_name"] == "Atlantic Salmon"
    assert inventory[0]["product_name"] == "Atlantic Salmon"


def test_opened_broth_gets_opened_shelf_life_suggestions(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        result = pantry_service.add_or_increment_pantry_item(
            {
                "ingredient_name": "Chicken broth",
                "opened_date": "2026-07-02",
                "source": "manual",
            },
            reference_date="2026-07-02",
        )

    item = result["item"]
    assert item["status"] == "opened"
    assert item["storage_location"] == "fridge"
    assert item["freeze_by_date"] == "2026-07-09"
    assert item["expiration_date"] == "2026-07-12"


def test_parse_receipt_text_returns_purchase_candidates():
    candidates = pantry_service.parse_receipt_text(
        """
        2 X EGGS $3.99
        WHOLE MILK 4.49
        SUBTOTAL 8.48
        TAX 0.00
        """
    )

    assert [candidate["normalized_name"] for candidate in candidates] == ["egg", "milk"]
    assert candidates[0]["quantity"] == 2
    assert candidates[0]["unit_price_label"] == "$2.00"
    assert candidates[0]["line_total_label"] == "$3.99"
    assert candidates[1]["unit_price_label"] == "$4.49"
    assert candidates[1]["line_total_label"] == "$4.49"
    assert candidates[0]["needs_review"] is True


def test_parse_receipt_text_filters_meijer_receipt_sections():
    candidates = pantry_service.parse_receipt_text(
        """
          06/28/26             LEXI
        MEIJER SAVINGS
        SPECIALS                      11.98
        SAVINGS TOTAL   11.98
          YOUR TOTAL SAVINGS
              SINCE 01/01/26
        GROCERY
        4068           GREEN ONIONS       1.09  F
        3940001612     BAKED BEANS
             2  @  2.39                   4.78  F
        71928352782    HONEY HAM STK      4.49  F
        71076040004    HANKS SODA         4.99   T
        4148302201     WHOLE MILK         5.29  F
        3120506000     FROZEN PIZZA       7.99  F
        71373300834    MEIJER JERKY       8.99  F
        71373360156    ATLANTIC SALMO
             2  @  9.99                  19.98  F
        85005647228    SALMON MIGNON     14.99  F
        1644710027     BISON STEAK       15.99  F
        *4125018910    MJR IM CRAB
             1  @ 2 / 5.00
             was      3.49       now      2.50  F
        *4125018911    MJR IM CRAB
             1  @ 2 / 5.00
             was      3.49       now      2.50  F
        *4125018912    IM LOBSTER
             1  @ 2 / 5.00
             was      3.49       now      2.50  F
        *71373300827   CAB STEAK
             2  @  16.99
             was     37.98       now     33.98  F
        *71373365883   SNOW CRAB
             was     28.99       now     23.98  F
                   mPerks # -- ********03
        TOTAL
                   IN 7% Sales Tax       .35
                   TOTAL TAX             .35
                   TOTAL              154.39
        PAYMENTS
          VISA Payment         TENDER   154.39
        XXXXXXXXXXXX4901        (X)
         APPROVAL CODE 104445
         US DEBIT
         AID A0000000980840
         TC  F6B002DB9C4CF5F6
         NO CVM REQUIRED
                   NUMBER OF ITEMS         18
        Tx:296  Op:2218927 Tm:17  St:134  18:13:57
        """
    )

    product_names = [candidate["product_name"] for candidate in candidates]

    assert product_names == [
        "Green Onions",
        "Baked Beans",
        "Honey Ham Stk",
        "Hanks Soda",
        "Whole Milk",
        "Frozen Pizza",
        "Meijer Jerky",
        "Atlantic Salmo",
        "Salmon Mignon",
        "Bison Steak",
        "Mjr Im Crab",
        "Mjr Im Crab",
        "Im Lobster",
        "Cab Steak",
        "Snow Crab",
    ]
    assert {candidate["product_name"] for candidate in candidates}.isdisjoint(
        {
            "Lexi",
            "Meijer Savings",
            "Specials",
            "Since",
            "Grocery",
            "Mperks",
            "Payments",
            "Number Of Items",
            "Tx Op Tm St",
        }
    )
    quantities = {candidate["product_name"]: candidate["quantity"] for candidate in candidates}
    assert quantities["Baked Beans"] == 2
    assert quantities["Atlantic Salmo"] == 2
    assert quantities["Cab Steak"] == 2
    assert quantities["Mjr Im Crab"] == 1
    assert sum(candidate["quantity"] for candidate in candidates) == 18
    atlantic_salmo = next(candidate for candidate in candidates if candidate["product_name"] == "Atlantic Salmo")
    assert atlantic_salmo["suggested_product_name"] == "Atlantic Salmon"
    assert atlantic_salmo["suggested_normalized_name"] == "atlantic salmon"

    price_details = {candidate["product_name"]: candidate for candidate in candidates}
    assert {candidate["purchased_date"] for candidate in candidates} == {"2026-06-28"}
    assert price_details["Green Onions"]["unit_price_label"] == "$1.09"
    assert price_details["Green Onions"]["line_total_label"] == "$1.09"
    assert price_details["Green Onions"]["expiration_date"] == "2026-07-05"
    assert price_details["Green Onions"]["freeze_by_date"] == "2026-07-03"
    assert price_details["Green Onions"]["storage_location"] == "fridge"
    assert price_details["Green Onions"]["storage_location_label"] == "Fridge"
    assert price_details["Baked Beans"]["unit_price_label"] == "$2.39"
    assert price_details["Baked Beans"]["line_total_label"] == "$4.78"
    assert price_details["Baked Beans"]["expiration_date"] == "2027-06-28"
    assert price_details["Baked Beans"].get("freeze_by_date", "") == ""
    assert price_details["Baked Beans"]["storage_location"] == "pantry"
    assert price_details["Honey Ham Stk"]["expiration_date"] == "2026-07-03"
    assert price_details["Honey Ham Stk"]["freeze_by_date"] == "2026-06-30"
    assert price_details["Hanks Soda"]["expiration_date"] == "2026-12-25"
    assert price_details["Hanks Soda"].get("freeze_by_date", "") == ""
    assert price_details["Whole Milk"]["expiration_date"] == "2026-07-05"
    assert price_details["Frozen Pizza"]["expiration_date"] == "2026-12-25"
    assert price_details["Frozen Pizza"].get("freeze_by_date", "") == ""
    assert price_details["Frozen Pizza"]["storage_location"] == "freezer"
    assert price_details["Meijer Jerky"]["expiration_date"] == "2026-12-25"
    assert price_details["Meijer Jerky"].get("freeze_by_date", "") == ""
    assert price_details["Meijer Jerky"]["storage_location"] == "pantry"
    assert price_details["Atlantic Salmo"]["unit_price_label"] == "$9.99"
    assert price_details["Atlantic Salmo"]["line_total_label"] == "$19.98"
    assert price_details["Atlantic Salmo"]["expiration_date"] == "2026-06-29"
    assert price_details["Atlantic Salmo"]["freeze_by_date"] == "2026-06-29"
    assert price_details["Atlantic Salmo"]["storage_location"] == "fridge"
    assert price_details["Cab Steak"]["unit_price_label"] == "$16.99"
    assert price_details["Cab Steak"]["line_total_label"] == "$33.98"
    assert price_details["Cab Steak"]["expiration_date"] == "2026-07-01"
    assert price_details["Cab Steak"]["freeze_by_date"] == "2026-06-30"
    assert price_details["Mjr Im Crab"]["unit_price_label"] == "$2.50"
    assert price_details["Mjr Im Crab"]["line_total_label"] == "$2.50"
    assert price_details["Snow Crab"]["unit_price_label"] == "$23.98"
    assert price_details["Snow Crab"]["line_total_label"] == "$23.98"


def test_add_receipt_candidate_saves_lifecycle_dates(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_RECEIPT_HISTORY_FILE", tmp_path / "pantry_receipt_history.json")
    app = create_app()
    candidate = pantry_service.parse_receipt_text(
        """
        07/01/26             LEXI
        4148302201     WHOLE MILK         5.29  F
        """
    )[0]

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [candidate],
            }

        response = client.post(
            "/pantry/receipt/add",
            data={
                "action": "selected",
                "candidate_index": "0",
                "candidate_0_purchased_date": "2026-07-01",
                "candidate_0_opened_date": "2026-07-02",
                "candidate_0_expiration_date": "2026-07-08",
                "candidate_0_freeze_by_date": "2026-07-05",
                "candidate_0_frozen_date": "2026-07-04",
            },
        )

    assert response.status_code == 302
    inventory_file = tmp_path / "user_data" / "pantry-user" / "pantry_inventory.json"
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))["items"]

    assert len(inventory) == 1
    assert inventory[0]["purchased_date"] == "2026-07-01"
    assert inventory[0]["opened_date"] == "2026-07-02"
    assert inventory[0]["expiration_date"] == "2026-07-08"
    assert inventory[0]["freeze_by_date"] == "2026-07-05"
    assert inventory[0]["frozen_date"] == "2026-07-04"
    assert inventory[0]["status"] == "frozen"
    assert inventory[0]["storage_location"] == "freezer"
    assert "Bought 2026-07-01" in inventory[0]["notes"]
    assert "Opened 2026-07-02" in inventory[0]["notes"]
    assert "Use by 2026-07-08" in inventory[0]["notes"]
    assert "Freeze by 2026-07-05" in inventory[0]["notes"]
    assert "Frozen on 2026-07-04" in inventory[0]["notes"]
    assert "Storage Freezer" in inventory[0]["notes"]


def test_add_receipt_candidate_saves_custom_storage_location(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_RECEIPT_HISTORY_FILE", tmp_path / "pantry_receipt_history.json")
    app = create_app()
    candidate = pantry_service.parse_receipt_text(
        """
        07/01/26             LEXI
        1234567890     BAKED BEANS        2.39  F
        """
    )[0]

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [candidate],
            }

        response = client.post(
            "/pantry/receipt/add",
            data={
                "action": "selected",
                "candidate_index": "0",
                "candidate_0_storage_location": "__custom__",
                "candidate_0_storage_location_custom": "Garage shelf",
            },
        )

    assert response.status_code == 302
    inventory_file = tmp_path / "user_data" / "pantry-user" / "pantry_inventory.json"
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))["items"]

    assert inventory[0]["storage_location"] == "garage-shelf"
    assert "Storage Garage Shelf" in inventory[0]["notes"]

    assert pantry_service.storage_location_label(inventory[0]["storage_location"]) == "Garage Shelf"


def test_add_receipt_candidate_saves_source_receipt_reference(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_RECEIPT_HISTORY_FILE", tmp_path / "pantry_receipt_history.json")
    app = create_app()
    candidate = pantry_service.parse_receipt_text(
        """
        07/01/26             LEXI
        4148302201     WHOLE MILK         5.29  F
        """
    )[0]

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [candidate],
            }

        response = client.post(
            "/pantry/receipt/add",
            data={
                "action": "selected",
                "candidate_index": "0",
            },
        )

    inventory_file = tmp_path / "user_data" / "pantry-user" / "pantry_inventory.json"
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))["items"]

    assert response.status_code == 302
    assert inventory[0]["source_receipt_id"] == "receipt-1"
    assert inventory[0]["source_receipt_line"] == candidate["raw_line"]


def test_pantry_inventory_links_uploaded_receipt_pdf(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        stored_name = "receipt-1_meijer.pdf"
        (pantry_service.PANTRY_RECEIPT_UPLOAD_DIR / stored_name).write_bytes(b"%PDF-1.4\nreceipt")
        pantry_service.save_receipt_history({
            "receipts": [
                {
                    "receipt_id": "receipt-1",
                    "created_at": "2026-07-02T22:25:11Z",
                    "stored_path": f"pantry_receipts/{stored_name}",
                    "text_excerpt": "4148302201     WHOLE MILK         5.29  F",
                    "candidate_count": 1,
                    "status": "added",
                }
            ],
        })
        pantry_service.save_pantry_inventory({
            "items": [
                {
                    "id": "milk-1",
                    "ingredient_name": "milk",
                    "product_name": "Whole Milk",
                    "quantity": 1,
                    "source": "receipt",
                    "source_receipt_id": "receipt-1",
                    "source_receipt_line": "4148302201     WHOLE MILK         5.29  F",
                }
            ],
        })
        item = pantry_service.pantry_items_for_view()[0]

    assert item["source_receipt"]["receipt_id"] == "receipt-1"
    assert item["source_receipt"]["file_label"] == "meijer.pdf"
    assert item["source_receipt"]["is_pdf"] is True

    with app.test_client() as client:
        sign_in(client)
        section_response = client.get("/sections/pantry")
        file_response = client.get("/pantry/receipts/receipt-1/file")

    html = section_response.get_data(as_text=True)

    assert section_response.status_code == 200
    assert "View Receipt PDF" in html
    assert "Filter This Receipt" in html
    assert "ai-pantry-inventory-source-filter-btn" in html
    assert "Receipt PDFs" in html
    assert "meijer.pdf" in html
    assert 'data-pantry-source-detail-type="receipt-pdf"' in html
    assert 'data-pantry-source-detail-id="receipt-1"' in html
    assert 'data-pantry-receipt-id="receipt-1"' in html
    assert 'data-pantry-receipt-file-kind="pdf"' in html
    assert "/pantry/receipts/receipt-1/file" in html
    assert file_response.status_code == 200
    assert file_response.mimetype == "application/pdf"
    assert file_response.get_data().startswith(b"%PDF-1.4")


def test_pantry_inventory_filters_uploaded_receipt_images(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        stored_name = "receipt-img_meijer.jpg"
        (pantry_service.PANTRY_RECEIPT_UPLOAD_DIR / stored_name).write_bytes(b"fake image")
        pantry_service.save_receipt_history({
            "receipts": [
                {
                    "receipt_id": "receipt-img",
                    "created_at": "2026-07-02T22:25:11Z",
                    "stored_path": f"pantry_receipts/{stored_name}",
                    "text_excerpt": "4068           GREEN ONIONS       1.09  F",
                    "candidate_count": 1,
                    "status": "added",
                }
            ],
        })
        pantry_service.save_pantry_inventory({
            "items": [
                {
                    "id": "onion-1",
                    "ingredient_name": "green onion",
                    "product_name": "Green Onions",
                    "quantity": 1,
                    "source": "receipt",
                    "source_receipt_id": "receipt-img",
                    "source_receipt_line": "4068           GREEN ONIONS       1.09  F",
                }
            ],
        })
        item = pantry_service.pantry_items_for_view()[0]

    assert item["source_receipt"]["receipt_id"] == "receipt-img"
    assert item["source_receipt"]["file_label"] == "meijer.jpg"
    assert item["source_receipt"]["is_pdf"] is False

    with app.test_client() as client:
        sign_in(client)
        section_response = client.get("/sections/pantry")

    html = section_response.get_data(as_text=True)

    assert section_response.status_code == 200
    assert "Uploaded Images" in html
    assert "Filter Image Set" in html
    assert "ai-pantry-inventory-source-filter-btn" in html
    assert "meijer.jpg" in html
    assert 'data-pantry-source-detail-type="receipt-image"' in html
    assert 'data-pantry-source-detail-id="receipt-img"' in html
    assert 'data-pantry-receipt-id="receipt-img"' in html
    assert 'data-pantry-receipt-file-kind="image"' in html
    assert 'data-pantry-image-source="1"' in html


def test_pantry_inventory_links_legacy_receipt_item_from_notes(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()
    raw_line = "4068           GREEN ONIONS       1.09  F"

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        stored_name = "receipt-legacy_meijer.pdf"
        (pantry_service.PANTRY_RECEIPT_UPLOAD_DIR / stored_name).write_bytes(b"%PDF-1.4\nlegacy")
        pantry_service.save_receipt_history({
            "receipts": [
                {
                    "receipt_id": "receipt-legacy",
                    "created_at": "2026-07-02T22:25:11Z",
                    "stored_path": f"pantry_receipts/{stored_name}",
                    "text_excerpt": raw_line,
                    "candidate_count": 1,
                    "status": "added",
                }
            ],
        })
        pantry_service.save_pantry_inventory({
            "items": [
                {
                    "id": "onion-1",
                    "ingredient_name": "green onion",
                    "product_name": "Green Onions",
                    "quantity": 1,
                    "source": "receipt",
                    "notes": f"{raw_line} | Receipt details: Qty 1",
                }
            ],
        })
        item = pantry_service.pantry_items_for_view()[0]

    assert item["source_receipt"]["receipt_id"] == "receipt-legacy"
    assert item["source_receipt"]["file_label"] == "meijer.pdf"


def test_hydrate_receipt_review_dates_uses_receipt_history(monkeypatch, tmp_path):
    monkeypatch.setattr(pantry_service, "PANTRY_RECEIPT_HISTORY_FILE", tmp_path / "pantry_receipt_history.json")
    pantry_service.save_receipt_history(
        {
            "receipts": [
                {
                    "receipt_id": "receipt-1",
                    "created_at": "2026-07-02T22:25:11Z",
                    "text_excerpt": "06/28/26             LEXI\nGROCERY\n4148302201     WHOLE MILK         5.29  F",
                    "candidate_count": 1,
                    "status": "pending",
                }
            ],
        }
    )
    review = {
        "receipt_id": "receipt-1",
        "candidates": [
            {
                "raw_line": "4148302201     WHOLE MILK         5.29  F",
                "product_name": "Whole Milk",
                "normalized_name": "milk",
                "quantity": 1,
                "confidence": 0.85,
            }
        ],
    }

    hydrated = pantry_service.hydrate_receipt_review_dates(review)
    candidate = hydrated["candidates"][0]

    assert hydrated["purchased_date"] == "2026-06-28"
    assert candidate["purchased_date"] == "2026-06-28"
    assert candidate["expiration_date"] == "2026-07-05"
    assert candidate.get("freeze_by_date", "") == ""


def test_receipt_candidate_review_status_prioritizes_use_by_over_freeze_by():
    status = pantry_service.receipt_candidate_review_status(
        {
            "expiration_date": "2026-07-01",
            "freeze_by_date": "2026-06-30",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "use-expired"
    assert status["label"] == "Past use by"
    assert status["date_statuses"]["expiration_date"]["urgency"] == "expired"
    assert status["date_statuses"]["freeze_by_date"]["urgency"] == "freeze-expired"


def test_receipt_candidate_review_status_marks_past_freeze_by_amber():
    status = pantry_service.receipt_candidate_review_status(
        {
            "expiration_date": "2026-07-05",
            "freeze_by_date": "2026-06-30",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "freeze-expired"
    assert status["label"] == "Freeze window passed"
    assert status["next_action"]["label"] == "Next: Freeze window passed Jun 30, 2026"
    assert status["next_action"]["urgency"] == "warning"


def test_receipt_candidate_review_status_marks_today_or_tomorrow_dates_due_soon():
    status = pantry_service.receipt_candidate_review_status(
        {
            "expiration_date": "2026-07-03",
            "freeze_by_date": "",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "due-soon"
    assert status["label"] == "Use by tomorrow"
    assert status["next_action"]["label"] == "Next: Use by Jul 3, 2026"
    assert status["next_action"]["urgency"] == "due-soon"


def test_receipt_candidate_review_status_marks_blank_freezer_freeze_by_safe():
    status = pantry_service.receipt_candidate_review_status(
        {
            "storage_location": "freezer",
            "expiration_date": "2026-12-25",
            "freeze_by_date": "",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "fresh"
    assert status["label"] == ""
    assert status["date_statuses"]["freeze_by_date"]["urgency"] == "frozen-safe"
    assert status["date_statuses"]["freeze_by_date"]["label"] == "Already in freezer"
    assert status["next_action"]["label"] == "Next: Best frozen until Dec 25, 2026"
    assert status["next_action"]["urgency"] == "safe"


def test_receipt_candidate_review_status_suppresses_use_by_when_frozen_before_deadline():
    status = pantry_service.receipt_candidate_review_status(
        {
            "product_name": "Atlantic Salmo",
            "normalized_name": "salmon",
            "expiration_date": "2026-06-29",
            "freeze_by_date": "2026-06-29",
            "frozen_date": "2026-06-29",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "frozen-in-time"
    assert status["label"] == "Frozen before deadline"
    assert status["date_statuses"]["expiration_date"]["urgency"] == "frozen-safe"
    assert status["date_statuses"]["freeze_by_date"]["urgency"] == "frozen-safe"
    assert status["date_statuses"]["frozen_date"]["urgency"] == "frozen-safe"
    assert status["date_statuses"]["expiration_date"]["label"] == "Original use by preserved"
    assert status["date_statuses"]["frozen_date"]["label"] == "Best frozen until Sep 27, 2026"
    assert status["next_action"]["label"] == "Next: Best frozen until Sep 27, 2026"
    assert status["next_action"]["urgency"] == "safe"


def test_receipt_candidate_review_status_marks_frozen_after_deadline():
    status = pantry_service.receipt_candidate_review_status(
        {
            "expiration_date": "2026-07-05",
            "freeze_by_date": "2026-06-30",
            "frozen_date": "2026-07-01",
        },
        reference_date="2026-07-02",
    )

    assert status["row_status"] == "freeze-expired"
    assert status["label"] == "Freeze window passed"
    assert status["date_statuses"]["frozen_date"]["urgency"] == "frozen-late"
    assert status["date_statuses"]["frozen_date"]["label"] == "Frozen after deadline"


def test_pantry_section_marks_receipt_candidate_frozen_before_deadline(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [
                    {
                        "raw_line": "65000000000    ATLANTIC SALMO    19.98  F",
                        "product_name": "Atlantic Salmo",
                        "normalized_name": "salmon",
                        "quantity": 2,
                        "confidence": 0.85,
                        "purchased_date": "2026-06-28",
                        "expiration_date": "2026-06-29",
                        "freeze_by_date": "2026-06-29",
                        "frozen_date": "2026-06-29",
                    }
                ],
            }

        response = client.get("/sections/pantry")
        html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ai-pantry-review-row-frozen-in-time" in html
    assert "Frozen before deadline" in html
    assert "Original use by preserved" in html
    assert "Freeze deadline met" in html
    assert "Best frozen until Sep 27, 2026" in html
    assert "Next: Best frozen until Sep 27, 2026" in html
    assert 'data-pantry-review-freezer-days="90"' in html
    assert "ai-pantry-date-field-frozen-safe" in html


def test_add_receipt_candidate_can_use_suggested_name(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [
                    {
                        "raw_line": "71373360156    ATLANTIC SALMO",
                        "product_name": "Atlantic Salmo",
                        "normalized_name": "atlantic salmo",
                        "quantity": 2,
                        "confidence": 0.85,
                        "purchased_date": "2026-06-28",
                    }
                ],
            }

        response = client.post(
            "/pantry/receipt/add",
            data={
                "candidate_index": "0",
                "candidate_0_use_suggested_name": "1",
                "candidate_0_suggested_product_name": "Atlantic Salmon",
            },
        )
        inventory = pantry_service.load_pantry_inventory(user_id="pantry-user")["items"]

    assert response.status_code == 302
    assert inventory[0]["ingredient_name"] == "Atlantic Salmon"
    assert inventory[0]["product_name"] == "Atlantic Salmon"
    assert inventory[0]["normalized_name"] == "atlantic salmon"
    assert "Name corrected from Atlantic Salmo to Atlantic Salmon" in inventory[0]["notes"]


def test_pantry_section_shows_next_action_for_freezer_receipt_candidate(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "purchased_date": "2026-06-28",
                "candidates": [
                    {
                        "raw_line": "87000000000    FROZEN PIZZA      7.99  F",
                        "product_name": "Frozen Pizza",
                        "normalized_name": "frozen pizza",
                        "quantity": 1,
                        "confidence": 0.85,
                    }
                ],
            }

        response = client.get("/sections/pantry")
        html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-pantry-review-next-action' in html
    assert "Next: Best frozen until Dec 25, 2026" in html
    assert "Already in freezer" in html


def test_pantry_items_for_view_shows_best_frozen_until_for_frozen_items(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        pantry_service.add_or_increment_pantry_item({
            "ingredient_name": "Green Onions",
            "product_name": "Green Onions",
            "normalized_name": "green onions",
            "quantity": 1,
            "source": "receipt",
            "purchased_date": "2026-06-28",
            "expiration_date": "2026-07-05",
            "freeze_by_date": "2026-07-03",
            "frozen_date": "2026-07-02",
        })
        items = pantry_service.pantry_items_for_view()

    assert items[0]["expiration_date"] == "2026-07-05"
    assert items[0]["frozen_best_by_date"] == "2026-09-30"
    assert items[0]["frozen_best_by_date_label"] == "Sep 30, 2026"


def test_pantry_items_for_view_sorts_by_store_section(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        pantry_service.save_pantry_inventory({
            "items": [
                {
                    "id": "beans-1",
                    "ingredient_name": "Baked beans",
                    "category": "receipt",
                    "source": "receipt",
                },
                {
                    "id": "salmon-1",
                    "ingredient_name": "Atlantic salmon",
                    "category": "receipt",
                    "source": "receipt",
                },
                {
                    "id": "apple-1",
                    "ingredient_name": "Apple",
                    "store_section": "PRODUCE",
                    "source": "manual",
                },
            ],
        })

        items = pantry_service.pantry_items_for_view()

    assert [item["ingredient_name"] for item in items] == [
        "Apple",
        "Atlantic salmon",
        "Baked beans",
    ]
    assert [item["store_section"] for item in items] == [
        "PRODUCE",
        "MEAT & SEAFOOD",
        "CANNED",
    ]


def test_pantry_receipt_date_fields_keep_inputs_top_aligned():
    css = (Path(__file__).resolve().parents[1] / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    grid_start = css.index(".ai-pantry-review-dates {")
    label_start = css.index(".ai-pantry-review-dates label {", grid_start)
    grid_css = css[grid_start:label_start]
    label_css = css[label_start:css.index("}", label_start)]

    assert "align-items: start;" in grid_css
    assert "align-content: start;" in label_css


def test_pantry_section_hydrates_old_receipt_review_dates(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    monkeypatch.setattr(pantry_service, "PANTRY_RECEIPT_HISTORY_FILE", tmp_path / "pantry_receipt_history.json")
    pantry_service.save_receipt_history(
        {
            "receipts": [
                {
                    "receipt_id": "receipt-1",
                    "created_at": "2026-07-02T22:25:11Z",
                    "text_excerpt": "06/28/26             LEXI\nGROCERY\n85005647228    SALMON MIGNON     14.99  F",
                    "candidate_count": 1,
                    "status": "pending",
                }
            ],
        }
    )
    app = create_app()

    with app.test_client() as client:
        sign_in(client)
        with client.session_transaction() as session:
            session["pantry_receipt_review"] = {
                "receipt_id": "receipt-1",
                "candidates": [
                    {
                        "raw_line": "85005647228    SALMON MIGNON     14.99  F",
                        "product_name": "Salmon Mignon",
                        "normalized_name": "salmon mignon",
                        "quantity": 1,
                        "confidence": 0.85,
                    }
                ],
            }

        response = client.get("/sections/pantry")
        html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="candidate_0_purchased_date"' in html
    assert 'name="candidate_0_expiration_date"' in html
    assert 'name="candidate_0_freeze_by_date"' in html
    assert 'name="candidate_0_frozen_date"' in html
    assert 'value="2026-06-28"' in html
    assert 'value="2026-06-29"' in html
    assert 'data-pantry-review-storage="fridge"' in html
    assert 'data-pantry-review-suggested-storage="fridge"' in html
    assert "Storage: Fridge" in html
    assert "ai-pantry-review-storage-fridge" in html


def test_match_recipe_to_pantry_reports_missing_ingredients(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    recipe = {
        "name": "Rice Bowl",
        "sections": [
            {
                "items": [
                    {"name": "Jasmine Rice", "display_name": "Jasmine Rice"},
                    {"name": "Eggs", "display_name": "Eggs"},
                    {"name": "Avocado", "display_name": "Avocado"},
                ],
            },
        ],
    }
    pantry_items = [
        {"ingredient_name": "rice", "normalized_name": "rice"},
        {"ingredient_name": "egg", "normalized_name": "egg"},
    ]

    match = pantry_service.match_recipe_to_pantry(recipe, pantry_items)

    assert match["matched_count"] == 2
    assert match["missing_count"] == 1
    assert match["status"] == "Missing 1 item"
    assert match["missing_ingredients"][0]["display_name"] == "Avocado"


def test_move_bought_items_to_pantry_route(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_client() as client:
        sign_in(client)
        response = client.post(
            "/pantry/move_bought_items",
            json={"items": [{"name": "Whole Milk"}, {"name": "Eggs"}]},
            headers={"X-Requested-With": "fetch"},
        )

        with client.session_transaction() as session:
            assert session["user_id"] == "pantry-user"

    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    inventory_file = tmp_path / "user_data" / "pantry-user" / "pantry_inventory.json"
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))["items"]

    assert {item["normalized_name"] for item in inventory} == {"milk", "egg"}
    assert all(item["source"] == "shopping_list" for item in inventory)


def test_delete_selected_pantry_items_route(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()
    pantry_service.save_pantry_inventory(
        {
            "items": [
                {"id": "milk-1", "ingredient_name": "Milk", "normalized_name": "milk"},
                {"id": "egg-1", "ingredient_name": "Eggs", "normalized_name": "egg"},
                {"id": "bean-1", "ingredient_name": "Beans", "normalized_name": "bean"},
            ],
        },
        user_id="pantry-user",
    )

    with app.test_client() as client:
        sign_in(client)
        response = client.post(
            "/pantry/items/delete_selected",
            data={"pantry_item_id": ["milk-1", "bean-1"]},
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/#aiPantryInventory")

    inventory = pantry_service.load_pantry_inventory(user_id="pantry-user")["items"]

    assert [item["id"] for item in inventory] == ["egg-1"]


def test_send_due_pantry_reminders_sends_once_and_records_marker(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    configure_users_file(monkeypatch, tmp_path)
    accounts.save_users({
        "users": [
            {
                "user_id": "user-1",
                "username": "user@example.com",
                "email": "user@example.com",
                "notification_topic": "shopping-user-reminder-topic",
                "ntfy_topic": "shopping-user-reminder-topic",
                "notifications_enabled": True,
            }
        ]
    })
    pantry_service.save_pantry_inventory(
        {
            "items": [
                {
                    "id": "broth-1",
                    "ingredient_name": "Chicken broth",
                    "quantity": 1,
                    "source": "manual",
                    "purchased_date": "2026-07-01",
                    "expiration_date": "2026-07-03",
                }
            ]
        },
        user_id="user-1",
    )
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, data=None, headers=None, timeout=None):
        posts.append({
            "url": url,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        })
        return FakeResponse()

    monkeypatch.setattr(accounts.requests, "post", fake_post)

    first_result = pantry_service.send_due_pantry_reminders(
        user_ids=["user-1"],
        reference_date="2026-07-02",
    )
    second_result = pantry_service.send_due_pantry_reminders(
        user_ids=["user-1"],
        reference_date="2026-07-02",
    )
    inventory = pantry_service.load_pantry_inventory(user_id="user-1")["items"]

    assert first_result["sent_count"] == 1
    assert second_result["sent_count"] == 0
    assert posts[0]["url"] == "https://ntfy.sh/shopping-user-reminder-topic"
    assert posts[0]["headers"]["Title"] == "Use soon: Chicken broth"
    assert b"Use by is tomorrow" in posts[0]["data"]
    assert inventory[0]["last_reminder_key"] == "broth-1:expiration_date:2026-07-03"


def test_ai_pantry_template_includes_lifecycle_controls():
    template = Path("PushShoppingList/templates/sections/ai_pantry.html").read_text(encoding="utf-8")

    assert 'href="#aiPantryUseSoon"' in template
    assert "pantry-lifecycle-badge" in template
    assert "item.storage_location_label" in template
    assert 'name="opened_date"' in template
    assert 'name="freeze_by_date"' in template
    assert 'name="frozen_date"' in template
    assert "ai-pantry-add-date-label" in template
    assert "ai-pantry-review-dates" in template
    assert 'name="candidate_{{ loop.index0 }}_purchased_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_opened_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_expiration_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_freeze_by_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_frozen_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_storage_location"' in template
    assert "data-pantry-image-panel" in template
    assert "generatePantryItemImage(this)" in template
    assert "uploadPantryItemImage(this)" in template
    assert "data-pantry-name-suggestion" in template
    assert "applyPantryNameSuggestion(this)" in template
    assert 'name="candidate_{{ loop.index0 }}_use_suggested_name"' in template
    assert 'name="candidate_{{ loop.index0 }}_storage_location_custom"' in template
    assert "data-pantry-review-row" in template
    assert 'data-pantry-review-date-field="expiration_date"' in template
    assert 'data-pantry-review-date-field="freeze_by_date"' in template
    assert 'data-pantry-review-date-field="frozen_date"' in template
    assert "data-pantry-review-storage-select" in template
    assert "data-pantry-review-storage-custom" in template
    assert "Custom..." in template
    assert "data-pantry-review-date-status" in template
    assert "data-pantry-review-row-status" in template
    assert "data-pantry-review-storage-badge" in template
    assert "data-pantry-review-suggested-storage" in template
    assert "data-pantry-review-next-action" in template
    assert "data-pantry-review-confidence-toggle" in template
    assert "data-pantry-review-confidence" in template
    assert "Show confidence" in template
    meta_start = template.index('class="ai-pantry-review-meta"')
    meta_end = template.index('class="ai-pantry-review-dates"', meta_start)
    meta_markup = template[meta_start:meta_end]
    assert meta_markup.index("ai-pantry-review-purchase-meta") < meta_markup.index("ai-pantry-review-badges")
    assert meta_markup.index("data-pantry-review-confidence") < meta_markup.index("ai-pantry-review-badges")
    assert meta_markup.index("data-pantry-review-next-action") < meta_markup.index("data-pantry-review-storage-badge")
    assert meta_markup.index("data-pantry-review-row-status") < meta_markup.index("data-pantry-review-storage-badge")
    assert "ai-pantry-review-row-{{ review_status.row_status or 'fresh' }}" in template
    assert "ai-pantry-review-next-badge" in template
    assert "ai-pantry-review-date-badge" in template
    assert "ai-pantry-review-storage-badge" in template
    assert "ai-pantry-date-field-{{ use_by_status.urgency or 'fresh' }}" in template
    assert "ai-pantry-date-field-{{ freeze_by_status.urgency or 'fresh' }}" in template
    assert "ai-pantry-date-field-{{ frozen_status.urgency or 'fresh' }}" in template
    assert "<span>Bought</span>" in template
    assert "<span>Opened</span>" in template
    assert "<span>Use by</span>" in template
    assert "<span>Freeze by</span>" in template
    assert "<span>Frozen on</span>" in template
    assert "<span>Storage</span>" in template
    assert "mark_opened" in template


def test_ai_pantry_receipt_warning_assets_include_live_status_hooks():
    js = Path("PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = Path("PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "function bindPantryReceiptDateWarnings" in js
    assert "function updatePantryReceiptReviewRow" in js
    assert "function updatePantryReceiptStorageBadge" in js
    assert "function normalizePantryReceiptStorage" in js
    assert "function pantryReceiptReviewStorageValue" in js
    assert "function syncPantryReceiptStorageCustomInput" in js
    assert "function pantryReceiptNextAction" in js
    assert "function setPantryReceiptNextAction" in js
    assert "function bindPantryReceiptConfidenceToggle" in js
    assert "PANTRY_RECEIPT_CONFIDENCE_STORAGE_KEY" in js
    assert "Next: ${prefix} ${dateLabel}" in js
    assert "Storage: ${pantryReceiptStorageLabel(storage)}" in js
    assert "Frozen before deadline" in js
    assert "Frozen after deadline" in js
    assert "Already in freezer" in js
    assert "Best frozen until" in js
    assert "data-pantry-review-storage-select" in js
    assert "data-pantry-review-storage-custom" in js
    assert '["bindPantryReceiptConfidenceToggle", bindPantryReceiptConfidenceToggle]' in js
    assert "bindPantryReceiptConfidenceToggle(options.root || document);" in js
    assert '["bindPantryReceiptDateWarnings", bindPantryReceiptDateWarnings]' in js
    assert "bindPantryReceiptDateWarnings(options.root || document);" in js
    assert ".ai-pantry-confidence-toggle" in css
    assert "[data-pantry-review-confidence][hidden]" in css
    assert ".ai-pantry-review-storage-custom" in css
    assert ".ai-pantry-review-storage-field input" in css
    assert ".ai-pantry-review-next-badge" in css
    assert ".ai-pantry-review-next-safe" in css
    assert ".ai-pantry-date-field-frozen-late input" in css
    assert ".ai-pantry-date-field-frozen-safe input" in css
    assert ".ai-pantry-review-meta {\n    display: grid;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));" in css
    assert ".ai-pantry-review-purchase-meta" in css
    assert ".ai-pantry-review-badges" in css
    assert "flex-wrap: wrap;" in css
    badges_start = css.index(".ai-pantry-review-badges {")
    badges_end = css.index("}", badges_start)
    assert "overflow: hidden;" not in css[badges_start:badges_end]
    assert ".ai-pantry-review-badges .ai-pantry-review-next-badge" in css
    assert "@media (max-width: 560px)" in css
    assert ".ai-pantry-review-storage-badge" in css
    assert ".ai-pantry-review-storage-fridge" in css
    assert ".ai-pantry-review-storage-freezer" in css


def test_add_missing_ingredients_route_dedupes_shopping_list(monkeypatch, tmp_path):
    configure_scoped_data(monkeypatch, tmp_path)
    app = create_app()

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        shopping_list_service.save_items(["Eggs"])

    with app.test_client() as client:
        sign_in(client)
        response = client.post(
            "/pantry/add_missing",
            data={"missing_items": ["Eggs", "Flour"]},
        )

    assert response.status_code == 302

    with app.test_request_context("/"):
        session["user_id"] = "pantry-user"
        items = shopping_list_service.load_items()

    assert items.count("Eggs") == 1
    assert "Flour" in items


def test_add_items_keeps_exact_dedupe_when_batch_has_repeats(monkeypatch, tmp_path):
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_FILE", tmp_path / "shopping_list.txt")

    shopping_list_service.save_items(["Eggs"])
    shopping_list_service.add_items(["Eggs", "Flour", "Flour", "Sugar"])

    assert shopping_list_service.load_items() == ["Eggs", "egg", "Flour", "Sugar"]
