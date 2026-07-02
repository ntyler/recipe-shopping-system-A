import json
from pathlib import Path

from flask import session

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

    price_details = {candidate["product_name"]: candidate for candidate in candidates}
    assert {candidate["purchased_date"] for candidate in candidates} == {"2026-06-28"}
    assert price_details["Green Onions"]["unit_price_label"] == "$1.09"
    assert price_details["Green Onions"]["line_total_label"] == "$1.09"
    assert price_details["Green Onions"]["expiration_date"] == "2026-07-05"
    assert price_details["Green Onions"]["freeze_by_date"] == "2026-07-03"
    assert price_details["Baked Beans"]["unit_price_label"] == "$2.39"
    assert price_details["Baked Beans"]["line_total_label"] == "$4.78"
    assert price_details["Baked Beans"]["expiration_date"] == "2027-06-28"
    assert price_details["Baked Beans"].get("freeze_by_date", "") == ""
    assert price_details["Honey Ham Stk"]["expiration_date"] == "2026-07-03"
    assert price_details["Honey Ham Stk"]["freeze_by_date"] == "2026-06-30"
    assert price_details["Hanks Soda"]["expiration_date"] == "2026-12-25"
    assert price_details["Hanks Soda"].get("freeze_by_date", "") == ""
    assert price_details["Whole Milk"]["expiration_date"] == "2026-07-05"
    assert price_details["Frozen Pizza"]["expiration_date"] == "2026-12-25"
    assert price_details["Frozen Pizza"].get("freeze_by_date", "") == ""
    assert price_details["Meijer Jerky"]["expiration_date"] == "2026-12-25"
    assert price_details["Meijer Jerky"].get("freeze_by_date", "") == ""
    assert price_details["Atlantic Salmo"]["unit_price_label"] == "$9.99"
    assert price_details["Atlantic Salmo"]["line_total_label"] == "$19.98"
    assert price_details["Atlantic Salmo"]["expiration_date"] == "2026-06-29"
    assert price_details["Atlantic Salmo"]["freeze_by_date"] == "2026-06-29"
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
    assert "Bought 2026-07-01" in inventory[0]["notes"]
    assert "Opened 2026-07-02" in inventory[0]["notes"]
    assert "Use by 2026-07-08" in inventory[0]["notes"]
    assert "Freeze by 2026-07-05" in inventory[0]["notes"]


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
    assert 'value="2026-06-28"' in html
    assert 'value="2026-06-29"' in html


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
    assert 'name="opened_date"' in template
    assert 'name="freeze_by_date"' in template
    assert "ai-pantry-add-date-label" in template
    assert "ai-pantry-review-dates" in template
    assert 'name="candidate_{{ loop.index0 }}_purchased_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_opened_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_expiration_date"' in template
    assert 'name="candidate_{{ loop.index0 }}_freeze_by_date"' in template
    assert "<span>Bought</span>" in template
    assert "<span>Opened</span>" in template
    assert "<span>Use by</span>" in template
    assert "<span>Freeze by</span>" in template
    assert "mark_opened" in template


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
