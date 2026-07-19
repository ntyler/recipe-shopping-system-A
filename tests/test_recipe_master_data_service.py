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
            "store_section": "Dairy & Eggs",
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
    assert user_a_ingredient["store_section"] == "PRODUCE"
    assert user_b_ingredient["store_section"] == "DAIRY & EGGS"
    assert user_a_equipment["id"] != user_b_equipment["id"]
    assert "store_section" not in user_a_equipment
    assert user_a_equipment["equipment_section"] == "COOKWARE"
    assert user_b_equipment["equipment_section"] == "COOKWARE"
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


def test_backfill_ingredient_store_sections_choose_most_common_per_user(monkeypatch, tmp_path, capsys):
    configure_master_db(monkeypatch, tmp_path)
    user_a_root = tmp_path / "users" / "user-a" / "recipe-extractor" / "data"
    user_b_root = tmp_path / "users" / "user-b" / "recipe-extractor" / "data"
    for root in (user_a_root, user_b_root):
        (root / "output").mkdir(parents=True)

    user_a_recipes = {
        "https://example.com/a-one": {
            "url": "https://example.com/a-one",
            "ingredients": ["Onion"],
        },
        "https://example.com/a-two": {
            "url": "https://example.com/a-two",
            "ingredients": ["Onion"],
        },
        "https://example.com/a-three": {
            "url": "https://example.com/a-three",
            "ingredients": ["Onion", "Mystery salt"],
        },
    }
    user_b_recipes = {
        "https://example.com/b-one": {
            "url": "https://example.com/b-one",
            "ingredients": ["Onion"],
        },
    }
    (user_a_root / "recipe_ingredients.json").write_text(json.dumps(user_a_recipes), encoding="utf-8")
    (user_b_root / "recipe_ingredients.json").write_text(json.dumps(user_b_recipes), encoding="utf-8")

    for filename, source_url, ingredients in (
        ("a-one.json", "https://example.com/a-one", [{"ingredient": "Onion", "store_section": "CANNED"}]),
        ("a-two.json", "https://example.com/a-two", [{"ingredient": "Onion", "store_section": "PRODUCE"}]),
        (
            "a-three.json",
            "https://example.com/a-three",
            [
                {"ingredient": "Onion", "store_section": "Produce"},
                {"ingredient": "Mystery crunch"},
            ],
        ),
    ):
        (user_a_root / "output" / filename).write_text(
            json.dumps({"source_url": source_url, "ingredients": ingredients}),
            encoding="utf-8",
        )
    (user_b_root / "output" / "b-one.json").write_text(
        json.dumps({
            "source_url": "https://example.com/b-one",
            "ingredients": [{"ingredient": "Onion", "store_section": "Dairy and Eggs"}],
        }),
        encoding="utf-8",
    )

    master_data.backfill_recipe_master_records_for_user("user-a", extractor_data_root=user_a_root)
    master_data.backfill_recipe_master_records_for_user("user-b", extractor_data_root=user_b_root)

    user_a_onion = master_data.master_record_for_name("ingredients", "user-a", "onion")
    user_b_onion = master_data.master_record_for_name("ingredients", "user-b", "onion")
    user_a_mystery = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    output = capsys.readouterr().out

    assert user_a_onion["store_section"] == "PRODUCE"
    assert user_b_onion["store_section"] == "DAIRY & EGGS"
    assert user_a_mystery["store_section"] == "MISC"
    assert "[IngredientMaster] action=store_section_backfill_start user_id=user-a" in output
    assert 'action=store_section_set' in output
    assert 'normalized_name="onion"' in output
    assert 'section="PRODUCE"' in output
    assert 'action=store_section_defaulted' in output
    assert 'normalized_name="mystery crunch"' in output
    assert "[IngredientMaster] action=store_section_backfill_complete" in output


def test_resolve_ingredient_store_section_repairs_generic_or_conflicting_values():
    assert master_data.resolve_ingredient_store_section("4 medium potatoes", "MISC") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("1 cup crema", "") == "DAIRY & EGGS"
    assert master_data.resolve_ingredient_store_section("2 cups chicken broth", "MEAT & SEAFOOD") == "CANNED"
    assert master_data.resolve_ingredient_store_section("crema de huancaina sauce", "MISC") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("inca pepper", "SPICES & SEASONINGS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("inca pepper", "SAUCES & CONDIMENTS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("aji amarillo", "SAUCES & CONDIMENTS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("aji amarillo paste", "MISC") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("aji amarillo paste", "SPICES & SEASONINGS") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("inca pepper sauce", "PRODUCE") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("mystery crunch", "MISC") == "MISC"


def test_resolve_equipment_section_classifies_common_equipment():
    assert master_data.resolve_equipment_section("medium saucepan") == "COOKWARE"
    assert master_data.resolve_equipment_section("blender and food processor") == "APPLIANCES"
    assert master_data.resolve_equipment_section("mixing bowl") == "MIXING BOWLS"
    assert master_data.resolve_equipment_section("sheet pan") == "BAKEWARE"
    assert master_data.resolve_equipment_section("measuring cups") == "MEASURING"
    assert master_data.resolve_equipment_section("storage container") == "SERVING & STORAGE"
    assert master_data.resolve_equipment_section("mystery tool") == "MISC"


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
                {
                    "ingredient": "Tomato",
                    "ingredient_image_url": "/static/generated/tomato.png",
                    "store_section": "Produce",
                },
                {"ingredient": "Basil", "store_section": "Spices & Seasonings"},
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
    assert rows[0]["store_section"] == "PRODUCE"
    assert master_data.count_ingredients(user_id="user-a", search="tom") == 1
    assert master_data.count_ingredient_usage(rows[0]["id"], user_id="user-a") == 2
    produce_rows = master_data.list_ingredients(user_id="user-a", store_section="PRODUCE")
    assert [row["name"] for row in produce_rows] == ["Tomato"]
    assert master_data.count_ingredients(user_id="user-a", store_section="PRODUCE") == 1
    bakeware_rows = master_data.list_equipment(user_id="user-a", equipment_section="BAKEWARE")
    mixing_rows = master_data.list_equipment(user_id="user-a", equipment_section="MIXING BOWLS")
    assert [row["name"] for row in bakeware_rows] == ["Sheet pan"]
    assert bakeware_rows[0]["equipment_section"] == "BAKEWARE"
    assert [row["name"] for row in mixing_rows] == ["Mixing bowl"]
    assert master_data.count_equipment(user_id="user-a", equipment_section="BAKEWARE") == 1


def test_update_ingredient_master_record_changes_identity_without_breaking_recipe_links(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    recipe_url = "https://example.com/master-edit"
    master_data.sync_recipe_master_records(
        recipe_url,
        recipe_data={"ingredients": [
            {"ingredient": "Onion", "store_section": "Produce"},
            {"ingredient": "Garlic", "store_section": "Produce"},
        ]},
        user_id="user-a",
    )
    onion = master_data.master_record_for_name("ingredients", "user-a", "onion")
    garlic = master_data.master_record_for_name("ingredients", "user-a", "garlic")

    result = master_data.update_ingredient_master_record(
        onion["id"],
        "Yellow Onion",
        "yellow onion",
        "PRODUCE",
        user_id="user-a",
    )

    renamed = master_data.master_record_for_name("ingredients", "user-a", "yellow onion")
    recipe_rows = master_data.recipe_master_rows("recipe_ingredients", recipe_url, user_id="user-a")
    assert result["ok"] is True
    assert result["changed"] is True
    assert renamed["id"] == onion["id"]
    assert renamed["name"] == "Yellow Onion"
    assert master_data.master_record_for_name("ingredients", "user-a", "onion") is None
    assert any(row["ingredient_id"] == onion["id"] and row["name"] == "Yellow Onion" for row in recipe_rows)

    duplicate = master_data.update_ingredient_master_record(
        garlic["id"],
        "Another Onion",
        "yellow onion",
        "PRODUCE",
        user_id="user-a",
    )
    assert duplicate["ok"] is False
    assert duplicate["status"] == 409
    assert master_data.master_record_for_name("ingredients", "user-a", "garlic")["id"] == garlic["id"]


def test_list_master_record_recipe_references_returns_usage_details(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    monkeypatch.setattr(master_data.storage_service, "USER_DATA_DIR", tmp_path / "users")

    first_url = "https://example.com/onion-soup"
    second_url = "https://example.com/onion-salad"
    master_data.sync_recipe_master_records(
        first_url,
        recipe_data={
            "ingredients": [{
                "ingredient": "Onion",
                "quantity": "1",
                "unit": "large",
                "buy_as": "yellow onion",
                "store_section": "Produce",
                "original_text": "1 large yellow onion, diced",
            }],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        second_url,
        recipe_data={
            "ingredients": [{
                "ingredient": "Onion",
                "quantity": "1/2",
                "unit": "cup",
                "store_section": "Produce",
                "optional": True,
                "original_text": "1/2 cup onion",
            }],
        },
        user_id="user-a",
    )
    metadata_path = (
        tmp_path
        / "users"
        / "user-a"
        / "recipe-extractor"
        / "data"
        / "recipe_ingredients.json"
    )
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({
            master_data.recipe_id_for_url(first_url): {
                "url": first_url,
                "name": "Onion Soup",
                "cover_image": {
                    "path": "data/uploads/recipe_covers/onion_soup.png",
                    "alt": "Onion Soup title image",
                },
            },
            master_data.recipe_id_for_url(second_url): {
                "url": second_url,
                "recipe_title": "Onion Salad",
            },
        }),
        encoding="utf-8",
    )

    onion = master_data.master_record_for_name("ingredients", "user-a", "onion")
    result = master_data.list_master_record_recipe_references(
        "ingredients",
        onion["id"],
        user_id="user-a",
    )
    blocked_result = master_data.list_master_record_recipe_references(
        "ingredients",
        onion["id"],
        user_id="user-b",
    )

    assert result["record"]["name"] == "Onion"
    assert result["total"] == 2
    assert [row["recipe_title"] for row in result["references"]] == ["Onion Salad", "Onion Soup"]
    soup_reference = result["references"][1]
    assert soup_reference["recipe_url"] == first_url
    assert soup_reference["quantity"] == "1"
    assert soup_reference["unit"] == "piece"
    assert soup_reference["size"] == "large"
    assert soup_reference["buy_as"] == "yellow onion"
    assert soup_reference["store_section"] == "PRODUCE"
    assert soup_reference["original_recipe_text"] == "1 large yellow onion, diced"
    assert soup_reference["cover_image"] == {
        "path": "data/uploads/recipe_covers/onion_soup.png",
        "alt": "Onion Soup title image",
    }
    assert blocked_result["record"] is None
    assert blocked_result["references"] == []


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


def test_missing_master_image_rows_scope_to_equipment_without_images(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)

    master_data.sync_recipe_master_records(
        "https://example.com/user-a-equipment-images",
        recipe_data={
            "equipment": [
                {"equipment": "Baking sheet", "equipment_image_url": "/static/generated/sheet.png"},
                {"equipment": "Rolling pin"},
            ],
        },
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-equipment-images",
        recipe_data={"equipment": [{"equipment": "Whisk"}]},
        user_id="user-b",
    )

    user_a_rows = master_images.missing_master_image_rows(record_type="equipment", user_id="user-a")
    all_rows = master_images.missing_master_image_rows(record_type="equipment", include_all_users=True)

    assert [row["name"] for row in user_a_rows] == ["Rolling pin"]
    assert [row["name"] for row in all_rows] == ["Whisk", "Rolling pin"]


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


def test_generate_missing_master_images_updates_equipment_table(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    master_data.sync_recipe_master_records(
        "https://example.com/equipment-image-generation",
        recipe_data={"equipment": [{"equipment": "Rolling pin"}]},
        user_id="user-a",
    )

    def fake_request_image(prompt, row, record_type="ingredients"):
        captured["prompt"] = prompt
        captured["row"] = dict(row)
        captured["record_type"] = record_type
        return b"image-bytes"

    def fake_save_image(row, image_bytes, record_type="ingredients"):
        captured["saved"] = {
            "row": dict(row),
            "image_bytes": image_bytes,
            "record_type": record_type,
        }
        return "/static/generated/recipe_steps/master_equipment.png", str(tmp_path / "master_equipment.png")

    monkeypatch.setattr(master_images, "request_master_image_bytes", fake_request_image)
    monkeypatch.setattr(master_images, "save_master_record_image", fake_save_image)

    job_id = "equipment-image-generation-test"
    progress = master_images.generate_missing_master_images(job_id, record_type="equipment", user_id="user-a")
    row = master_data.list_equipment(user_id="user-a")[0]

    assert progress["status"] == "complete"
    assert progress["record_type"] == "equipment"
    assert progress["generated"] == 1
    assert captured["record_type"] == "equipment"
    assert captured["saved"]["record_type"] == "equipment"
    assert "rolling pin" in captured["prompt"].lower()
    assert row["image_url"] == "/static/generated/recipe_steps/master_equipment.png"
