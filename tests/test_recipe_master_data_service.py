import json

from PushShoppingList.services import recipe_master_data_service as master_data


def configure_master_db(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    return db_path


def test_sync_recipe_master_records_keeps_same_name_separate_per_user(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    recipe_url = "https://example.com/shared-soup"

    user_a_recipe = {
        "ingredients": [{
            "ingredient": "Onion",
            "quantity": "1",
            "unit": "cup",
            "buy_as": "yellow onion",
            "store_section": "Produce",
            "original_text": "1 cup chopped onion",
        }],
        "equipment": [{
            "equipment": "Large pot",
            "equipment_image_url": "/static/generated/user-a-pot.png",
        }],
    }
    user_b_recipe = {
        "ingredients": [{
            "ingredient": "Onion",
            "quantity": "2",
            "unit": "tbsp",
            "buy_as": "red onion",
            "store_section": "Produce",
            "original_text": "2 tbsp minced onion",
        }],
        "equipment": [{
            "equipment": "Large pot",
            "equipment_image_url": "/static/generated/user-b-pot.png",
        }],
    }

    master_data.sync_recipe_master_records(recipe_url, recipe_data=user_a_recipe, user_id="user-a")
    master_data.sync_recipe_master_records(recipe_url, recipe_data=user_b_recipe, user_id="user-b")

    user_a_ingredient = master_data.master_record_for_name("ingredients", "user-a", "onion")
    user_b_ingredient = master_data.master_record_for_name("ingredients", "user-b", "onion")
    user_a_equipment = master_data.master_record_for_name("equipment", "user-a", "large pot")
    user_b_equipment = master_data.master_record_for_name("equipment", "user-b", "large pot")

    assert user_a_ingredient["id"] != user_b_ingredient["id"]
    assert user_a_equipment["id"] != user_b_equipment["id"]
    assert user_a_equipment["image_url"] == "/static/generated/user-a-pot.png"
    assert user_b_equipment["image_url"] == "/static/generated/user-b-pot.png"

    user_a_rows = master_data.recipe_master_rows("recipe_ingredients", recipe_url, user_id="user-a")
    user_b_rows = master_data.recipe_master_rows("recipe_ingredients", recipe_url, user_id="user-b")

    assert len(user_a_rows) == 1
    assert len(user_b_rows) == 1
    assert user_a_rows[0]["ingredient_id"] == user_a_ingredient["id"]
    assert user_b_rows[0]["ingredient_id"] == user_b_ingredient["id"]
    assert user_a_rows[0]["quantity"] == "1"
    assert user_b_rows[0]["quantity"] == "2"


def test_sync_recipe_master_records_replaces_only_current_users_recipe_links(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    recipe_url = "https://example.com/same-recipe-url"

    master_data.sync_recipe_master_records(
        recipe_url,
        recipe_data={
            "ingredients": [{"ingredient": "Onion"}],
            "equipment": [{"equipment": "Large pot"}],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        recipe_url,
        recipe_data={
            "ingredients": [{"ingredient": "Onion"}],
            "equipment": [{"equipment": "Large pot"}],
        },
        user_id="user-b",
    )

    master_data.sync_recipe_master_records(
        recipe_url,
        recipe_data={
            "ingredients": [{"ingredient": "Garlic"}],
            "equipment": [{"equipment": "Mixing bowl"}],
        },
        user_id="user-a",
    )

    user_a_ingredients = master_data.recipe_master_rows("recipe_ingredients", recipe_url, user_id="user-a")
    user_b_ingredients = master_data.recipe_master_rows("recipe_ingredients", recipe_url, user_id="user-b")
    user_a_equipment = master_data.recipe_master_rows("recipe_equipment", recipe_url, user_id="user-a")
    user_b_equipment = master_data.recipe_master_rows("recipe_equipment", recipe_url, user_id="user-b")

    assert [row["name"] for row in user_a_ingredients] == ["Garlic"]
    assert [row["name"] for row in user_b_ingredients] == ["Onion"]
    assert [row["name"] for row in user_a_equipment] == ["Mixing bowl"]
    assert [row["name"] for row in user_b_equipment] == ["Large pot"]


def test_backfill_recipe_master_records_for_user_scopes_existing_data(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    user_a_root = tmp_path / "users" / "user-a" / "recipe-extractor" / "data"
    user_b_root = tmp_path / "users" / "user-b" / "recipe-extractor" / "data"
    for root in (user_a_root, user_b_root):
        (root / "output").mkdir(parents=True)

    recipe_url = "https://example.com/backfilled"
    for user_root, equipment_image in (
        (user_a_root, "/static/generated/backfill-a-pot.png"),
        (user_b_root, "/static/generated/backfill-b-pot.png"),
    ):
        (user_root / "recipe_ingredients.json").write_text(
            json.dumps({
                "https://example.com/backfilled": {
                    "url": recipe_url,
                    "ingredients": ["onion"],
                }
            }),
            encoding="utf-8",
        )
        (user_root / "output" / "backfilled.json").write_text(
            json.dumps({
                "source_url": recipe_url,
                "ingredients": [{"ingredient": "onion", "original_text": "1 onion"}],
                "equipment": [{
                    "equipment": "Large pot",
                    "equipment_image_url": equipment_image,
                }],
            }),
            encoding="utf-8",
        )

    master_data.backfill_recipe_master_records_for_user("user-a", extractor_data_root=user_a_root)
    master_data.backfill_recipe_master_records_for_user("user-b", extractor_data_root=user_b_root)

    user_a_equipment = master_data.master_record_for_name("equipment", "user-a", "large pot")
    user_b_equipment = master_data.master_record_for_name("equipment", "user-b", "large pot")

    assert user_a_equipment["id"] != user_b_equipment["id"]
    assert user_a_equipment["image_url"] == "/static/generated/backfill-a-pot.png"
    assert user_b_equipment["image_url"] == "/static/generated/backfill-b-pot.png"
