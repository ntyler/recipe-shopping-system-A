import json

from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_master_image_service as master_images


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


def test_sync_recipe_master_records_skips_open_suspicious_ingredient_reviews(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    recipe_url = "https://example.com/yuca-huancaina"

    result = master_data.sync_recipe_master_records(
        recipe_url,
        recipe_data={
            "ingredients": [
                {
                    "ingredient": "potato milk",
                    "quantity": "2",
                    "unit": "cups",
                    "original_text": "2 cups potato milk",
                    "food_review": {
                        "needs_review": True,
                        "kind": "suspicious_ingredient",
                        "status": "open",
                    },
                },
                {"ingredient": "yuca", "quantity": "2", "unit": "large"},
            ],
        },
        user_id="user-a",
    )

    assert result["ingredient_count"] == 1
    assert master_data.master_record_for_name("ingredients", "user-a", "potato milk") is None
    assert master_data.master_record_for_name("ingredients", "user-a", "yuca") is not None


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


def test_backfill_recipe_master_records_reports_recipe_progress(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    user_root = tmp_path / "users" / "user-a" / "recipe-extractor" / "data"
    (user_root / "output").mkdir(parents=True)
    recipe_url = "https://example.com/progress-soup"
    (user_root / "recipe_ingredients.json").write_text(
        json.dumps({
            recipe_url: {
                "url": recipe_url,
                "name": "Progress Soup",
                "ingredients": ["Carrot"],
            }
        }),
        encoding="utf-8",
    )
    (user_root / "output" / "progress-soup.json").write_text(
        json.dumps({
            "source_url": recipe_url,
            "ingredients": [{"ingredient": "Carrot"}],
            "equipment": [{"equipment": "Sheet pan"}],
        }),
        encoding="utf-8",
    )
    events = []

    result = master_data.backfill_recipe_master_records_for_user(
        "user-a",
        extractor_data_root=user_root,
        progress_callback=lambda event, payload: events.append((event, payload)),
    )

    assert result["recipes"] == 1
    assert [event for event, _payload in events] == [
        "user_start",
        "recipe_start",
        "recipe_done",
        "user_done",
    ]
    recipe_start = events[1][1]
    recipe_done = events[2][1]
    assert recipe_start["label"] == "Progress Soup"
    assert recipe_start["recipe_url"] == recipe_url
    assert recipe_done["ingredient_count"] == 1
    assert recipe_done["equipment_count"] == 1


def test_list_master_records_searches_sorts_and_counts_usage(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)

    master_data.sync_recipe_master_records(
        "https://example.com/first",
        recipe_data={
            "ingredients": [
                {"ingredient": "Tomato", "ingredient_image_url": "/static/generated/tomato.png"},
                {"ingredient": "Basil"},
            ],
            "equipment": [{"equipment": "Sheet pan"}],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/second",
        recipe_data={
            "ingredients": [{"ingredient": "Tomato"}],
            "equipment": [{"equipment": "Mixing bowl"}],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/other-user",
        recipe_data={"ingredients": [{"ingredient": "Tomato"}]},
        user_id="user-b",
    )

    rows = master_data.list_ingredients(
        user_id="user-a",
        search="tom",
        sort="usage_count_desc",
    )

    assert [row["name"] for row in rows] == ["Tomato"]
    assert rows[0]["usage_count"] == 2
    assert rows[0]["image_url"] == "/static/generated/tomato.png"
    assert master_data.count_ingredients(user_id="user-a", search="tom") == 1
    assert master_data.count_ingredient_usage(rows[0]["id"], user_id="user-a") == 2


def test_missing_master_image_rows_scope_to_ingredients_without_images(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)

    master_data.sync_recipe_master_records(
        "https://example.com/user-a-images",
        recipe_data={
            "ingredients": [
                {"ingredient": "Tomato", "ingredient_image_url": "/static/generated/tomato.png"},
                {"ingredient": "Basil"},
            ],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-images",
        recipe_data={"ingredients": [{"ingredient": "Garlic"}]},
        user_id="user-b",
    )

    user_a_rows = master_images.missing_master_image_rows(user_id="user-a")
    all_rows = master_images.missing_master_image_rows(include_all_users=True)

    assert [row["name"] for row in user_a_rows] == ["Basil"]
    assert [row["name"] for row in all_rows] == ["Garlic", "Basil"]


def test_generate_missing_master_images_reports_missing_openai_key(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    master_data.sync_recipe_master_records(
        "https://example.com/missing-key-images",
        recipe_data={"ingredients": [{"ingredient": "Basil"}]},
        user_id="user-a",
    )

    job_id = "missing-image-key-test"
    master_images.start_master_image_progress(job_id, user_id="user-a")
    progress = master_images.generate_missing_master_images(job_id, user_id="user-a")

    assert progress["status"] == "failed"
    assert progress["total"] == 1
    assert progress["completed"] == 0
    assert "OPENAI_API_KEY" in progress["summary"]
