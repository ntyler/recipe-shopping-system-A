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
    assert candidates[0]["needs_review"] is True


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
