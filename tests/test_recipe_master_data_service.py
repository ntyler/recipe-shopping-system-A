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
    assert user_b_ingredient["store_section"] == "PRODUCE"
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
    assert user_b_onion["store_section"] == "PRODUCE"
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
    assert master_data.resolve_ingredient_store_section("1 link Peruvian chorizo", "MISC") == "MEAT & SEAFOOD"
    assert master_data.resolve_ingredient_store_section("2 cups chicken broth", "MEAT & SEAFOOD") == "CANNED"
    assert master_data.resolve_ingredient_store_section("crema de huancaina sauce", "MISC") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("inca pepper", "SPICES & SEASONINGS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("inca pepper", "SAUCES & CONDIMENTS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("aji amarillo", "SAUCES & CONDIMENTS") == "PRODUCE"
    assert master_data.resolve_ingredient_store_section("aji amarillo paste", "MISC") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("aji amarillo paste", "SPICES & SEASONINGS") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("inca pepper sauce", "PRODUCE") == "SAUCES & CONDIMENTS"
    assert master_data.resolve_ingredient_store_section("mystery crunch", "MISC") == "MISC"


def test_layered_store_section_classifier_is_form_aware_and_uses_allowed_sections():
    expected = {
        "ground ginger": "SPICES & SEASONINGS",
        "ginger powder": "SPICES & SEASONINGS",
        "powdered ginger": "SPICES & SEASONINGS",
        "fresh ginger": "PRODUCE",
        "ginger root": "PRODUCE",
        "garlic powder": "SPICES & SEASONINGS",
        "fresh garlic": "PRODUCE",
        "ground cinnamon": "SPICES & SEASONINGS",
        "paprika": "SPICES & SEASONINGS",
        "cumin": "SPICES & SEASONINGS",
        "turmeric": "SPICES & SEASONINGS",
        "frozen mixed vegetables": "FROZEN",
        "canned vegetables": "CANNED",
        "long-grain rice": "PASTA, RICE & GRAINS",
        "vegetable oil": "OILS & VINEGARS",
        "soy sauce": "SAUCES & CONDIMENTS",
        "Peruvian chorizo": "MEAT & SEAFOOD",
    }

    results = {
        name: master_data.classify_ingredient_store_section_result(name, log_result=False)
        for name in expected
    }

    assert {name: result["store_section"] for name, result in results.items()} == expected
    assert results["ground ginger"]["canonical_ingredient"] == "ginger"
    assert results["ground ginger"]["form"] == "ground"
    assert results["fresh ginger"]["form"] == "fresh"
    assert all(
        result["store_section"] in master_data.ingredient_store_section_options()
        for result in results.values()
    )


def test_layered_store_section_classifier_respects_priority_and_validates_ai():
    recipe_override = master_data.classify_ingredient_store_section_result(
        "ground ginger",
        recipe_override="DRY GOODS",
        recipe_override_confirmed=True,
        user_master_data={"store_section": "PRODUCE"},
        ai_result={"store_section": "Spices", "confidence": 0.97},
        log_result=False,
    )
    user_master = master_data.classify_ingredient_store_section_result(
        "ground ginger",
        user_master_data={"store_section": "PRODUCE", "store_section_confidence": 1},
        ai_result={"store_section": "Spices", "confidence": 0.97},
        log_result=False,
    )
    ai = master_data.classify_ingredient_store_section_result(
        "mystery crunch",
        ai_result={
            "store_section": "Spices",
            "confidence": 0.97,
            "reason": "AI identified a seasoning.",
            "normalized_name": "mystery crunch",
        },
        log_result=False,
    )
    invalid_ai = master_data.classify_ingredient_store_section_result(
        "mystery crunch",
        ai_result={"store_section": "Hardware", "confidence": 0.99},
        log_result=False,
    )
    corrected_ground_ginger = master_data.classify_ingredient_store_section_result(
        "ground ginger",
        legacy_section="Produce",
        log_result=False,
    )
    corrected_fresh_ginger = master_data.classify_ingredient_store_section_result(
        "fresh ginger",
        legacy_section="Spices",
        log_result=False,
    )

    assert recipe_override["store_section"] == "DRY GOODS"
    assert recipe_override["store_section_source"] == "recipe_override"
    assert recipe_override["store_section_user_confirmed"] is True
    assert user_master["store_section"] == "PRODUCE"
    assert user_master["store_section_source"] == "user_master_data"
    assert ai["store_section"] == "SPICES & SEASONINGS"
    assert ai["store_section_source"] == "ai"
    assert ai["store_section_confidence"] == 0.97
    assert invalid_ai["store_section"] == "MISC"
    assert invalid_ai["store_section_source"] == "fallback"
    assert corrected_ground_ginger["store_section"] == "SPICES & SEASONINGS"
    assert corrected_fresh_ginger["store_section"] == "PRODUCE"


def test_misc_reclassification_previews_then_applies_only_unconfirmed_rows(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/ginger",
        recipe_data={"ingredients": [
            {"ingredient": "Ground ginger", "store_section": "MISC"},
            {"ingredient": "Fresh ginger", "store_section": "MISC"},
        ]},
        user_id="user-a",
    )
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    fresh = master_data.master_record_for_name("ingredients", "user-a", "ginger")
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE ingredients
               SET store_section = 'MISC',
                   store_section_user_confirmed = 0,
                   image_url = '/static/generated/ingredients/ground-ginger.png'
             WHERE id = ?
            """,
            (ground["id"],),
        )
        connection.execute(
            "UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 1 WHERE id = ?",
            (fresh["id"],),
        )
        connection.execute(
            "UPDATE recipe_ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE ingredient_id = ?",
            (ground["id"],),
        )

    preview = master_data.review_misc_ingredient_store_sections("user-a", apply=False)

    assert preview["applied"] is False
    assert preview["changed_count"] == 1
    assert preview["changes"][0]["ingredient"] == "Ground ginger"
    assert preview["changes"][0]["image_url"] == "/static/generated/ingredients/ground-ginger.png"
    assert preview["changes"][0]["proposed_store_section"] == "SPICES & SEASONINGS"
    assert master_data.master_record_for_name("ingredients", "user-a", "ground ginger")["store_section"] == "MISC"
    recipe_rows = master_data.recipe_master_rows(
        "recipe_ingredients", "https://example.com/ginger", user_id="user-a"
    )
    assert recipe_rows[1]["raw_name"] == "Fresh ginger"
    assert recipe_rows[1]["normalized_name"] == "ginger"
    assert recipe_rows[1]["canonical_ingredient"] == "ginger"
    assert recipe_rows[1]["form"] == "fresh"
    assert recipe_rows[1]["preparation"] == "fresh"

    applied = master_data.review_misc_ingredient_store_sections("user-a", apply=True)

    assert applied["applied"] is True
    assert applied["changed_count"] == 1
    assert master_data.master_record_for_name("ingredients", "user-a", "ground ginger")["store_section"] == "SPICES & SEASONINGS"
    assert master_data.master_record_for_name("ingredients", "user-a", "ginger")["store_section"] == "MISC"


def test_misc_reclassification_applies_reviewed_rule_ai_and_keep_misc_decisions(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/reviewed-sections",
        recipe_data={"ingredients": [
            {"ingredient": "Ground ginger", "store_section": "MISC"},
            {"ingredient": "Mystery crunch", "store_section": "MISC"},
            {"ingredient": "Unknown morsels", "store_section": "MISC"},
        ]},
        user_id="user-a",
    )
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    mystery = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    unknown = master_data.master_record_for_name("ingredients", "user-a", "unknown morsels")
    ingredient_ids = [ground["id"], mystery["id"], unknown["id"]]
    with master_data.recipe_master_connection() as connection:
        placeholders = ", ".join("?" for _value in ingredient_ids)
        connection.execute(
            f"UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE id IN ({placeholders})",
            ingredient_ids,
        )
        connection.execute(
            f"UPDATE recipe_ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE ingredient_id IN ({placeholders})",
            ingredient_ids,
        )

    applied = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [
            {
                "ingredient_id": ground["id"],
                "store_section": "Spices",
                "decision_source": "deterministic",
                "confidence": 1,
            },
            {
                "ingredient_id": mystery["id"],
                "store_section": "Sauces & Condiments",
                "decision_source": "ai",
                "confidence": 0.74,
                "reason": "The ingredient is sold as a prepared condiment.",
            },
            {
                "ingredient_id": unknown["id"],
                "store_section": "Misc",
                "decision_source": "keep_misc",
                "confidence": 1,
            },
        ],
    )

    ground_after = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    mystery_after = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    unknown_after = master_data.master_record_for_name("ingredients", "user-a", "unknown morsels")
    assert applied["ok"] is True
    assert applied["changed_count"] == 3
    assert applied["kept_misc_count"] == 1
    assert applied["batch_id"] > 0
    assert applied["undo_available"] is True
    assert master_data.latest_undoable_ingredient_store_section_reclassification(
        "user-a"
    )["batch_id"] == applied["batch_id"]
    assert ground_after["store_section"] == "SPICES & SEASONINGS"
    assert ground_after["store_section_user_confirmed"] == 0
    assert mystery_after["store_section"] == "SAUCES & CONDIMENTS"
    assert mystery_after["store_section_source"] == "manual"
    assert mystery_after["store_section_user_confirmed"] == 1
    assert unknown_after["store_section"] == "MISC"
    assert unknown_after["store_section_source"] == "manual"
    assert unknown_after["store_section_user_confirmed"] == 1

    undo_preview = master_data.ingredient_store_section_reclassification_undo_preview(
        "user-a",
        batch_id=applied["batch_id"],
    )

    assert undo_preview["ok"] is True
    assert undo_preview["batch_id"] == applied["batch_id"]
    assert undo_preview["change_count"] == 3
    assert undo_preview["recipe_reference_count"] == 3
    assert undo_preview["is_next_undo"] is True
    assert undo_preview["can_undo_now"] is True
    assert undo_preview["newer_undo_count"] == 0
    assert undo_preview["older_undo_count"] == 0
    assert [change["ingredient"] for change in undo_preview["changes"]] == [
        "Ground ginger",
        "Mystery crunch",
        "Unknown morsels",
    ]
    assert undo_preview["changes"][0]["applied_store_section"] == "SPICES & SEASONINGS"
    assert undo_preview["changes"][0]["restored_store_section"] == "MISC"
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "ground ginger"
    )["store_section"] == "SPICES & SEASONINGS"

    undone = master_data.undo_last_ingredient_store_section_reclassification(
        "user-a",
        expected_batch_id=applied["batch_id"],
    )

    assert undone["ok"] is True
    assert undone["restored_ingredient_count"] == 3
    assert undone["restored_recipe_count"] == 3
    assert undone["next_batch"] is None
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "ground ginger"
    )["store_section"] == "MISC"
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "mystery crunch"
    )["store_section_user_confirmed"] == 0
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "unknown morsels"
    )["store_section_user_confirmed"] == 0
    assert master_data.latest_undoable_ingredient_store_section_reclassification("user-a") is None


def test_misc_reclassification_rejects_stale_rule_batch_before_writing(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/atomic-review",
        recipe_data={"ingredients": [
            {"ingredient": "Mystery crunch", "store_section": "MISC"},
            {"ingredient": "Ground ginger", "store_section": "MISC"},
        ]},
        user_id="user-a",
    )
    mystery = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    ground = master_data.master_record_for_name("ingredients", "user-a", "ground ginger")
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "UPDATE ingredients SET store_section = 'MISC', store_section_user_confirmed = 0 WHERE id IN (?, ?)",
            (mystery["id"], ground["id"]),
        )

    result = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [
            {
                "ingredient_id": mystery["id"],
                "store_section": "Sauces & Condiments",
                "decision_source": "ai",
                "confidence": 0.7,
            },
            {
                "ingredient_id": ground["id"],
                "store_section": "Produce",
                "decision_source": "deterministic",
                "confidence": 1,
            },
        ],
    )

    assert result["ok"] is False
    assert result["status"] == 409
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "mystery crunch"
    )["store_section"] == "MISC"


def test_store_section_undo_preview_exposes_history_and_blocks_older_batches(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/store-section-history",
        recipe_data={"ingredients": [
            {"ingredient": "Mystery crunch", "store_section": "MISC"},
            {"ingredient": "Unknown morsels", "store_section": "MISC"},
        ]},
        user_id="user-a",
    )
    mystery = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    unknown = master_data.master_record_for_name("ingredients", "user-a", "unknown morsels")
    first = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [{
            "ingredient_id": mystery["id"],
            "store_section": "Snacks",
            "decision_source": "ai",
            "confidence": 0.8,
        }],
    )
    second = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [{
            "ingredient_id": unknown["id"],
            "store_section": "Dry Goods",
            "decision_source": "manual",
            "confidence": 1,
        }],
    )

    latest_preview = master_data.ingredient_store_section_reclassification_undo_preview("user-a")
    older_preview = master_data.ingredient_store_section_reclassification_undo_preview(
        "user-a",
        batch_id=first["batch_id"],
    )

    assert latest_preview["batch_id"] == second["batch_id"]
    assert latest_preview["can_undo_now"] is True
    assert latest_preview["older_undo_count"] == 1
    assert [batch["batch_id"] for batch in latest_preview["undoable_batches"]] == [
        second["batch_id"],
        first["batch_id"],
    ]
    assert older_preview["batch_id"] == first["batch_id"]
    assert older_preview["can_undo_now"] is False
    assert older_preview["newer_undo_count"] == 1
    assert "Undo 1 newer store-section apply batch first" in older_preview["blocked_reason"]
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "mystery crunch"
    )["store_section"] == "SNACKS"
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "unknown morsels"
    )["store_section"] == "DRY GOODS"


def test_store_section_reclassification_undo_refuses_to_overwrite_later_edits(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/undo-conflict",
        recipe_data={"ingredients": [{"ingredient": "Mystery crunch", "store_section": "MISC"}]},
        user_id="user-a",
    )
    mystery = master_data.master_record_for_name("ingredients", "user-a", "mystery crunch")
    applied = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [{
            "ingredient_id": mystery["id"],
            "store_section": "Snacks",
            "decision_source": "ai",
            "confidence": 0.8,
        }],
    )
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            "UPDATE ingredients SET store_section = 'PRODUCE', updated_at = ? WHERE id = ?",
            ("2099-01-01T00:00:00Z", mystery["id"]),
        )

    result = master_data.undo_last_ingredient_store_section_reclassification(
        "user-a",
        expected_batch_id=applied["batch_id"],
    )

    assert result["ok"] is False
    assert result["status"] == 409
    assert "changed after this reclassification" in result["error"]
    assert master_data.master_record_for_name(
        "ingredients", "user-a", "mystery crunch"
    )["store_section"] == "PRODUCE"


def test_store_section_classifier_logs_source_confidence_version_and_rule(capsys):
    result = master_data.classify_ingredient_store_section_result("ground ginger")
    output = capsys.readouterr().out

    assert result["store_section"] == "SPICES & SEASONINGS"
    assert '[StoreSectionClassifier] section="SPICES & SEASONINGS"' in output
    assert "source=global_master_data" in output
    assert "confidence=1.00" in output
    assert "classifier_version=2.0" in output
    assert 'rule="global.ground_ginger"' in output


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


def test_merge_ingredient_master_records_relinks_usage_and_preserves_alias(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/potato-soup",
        recipe_data={"ingredients": [{
            "ingredient": "Potato",
            "store_section": "Produce",
            "ingredient_image_url": "/static/generated/potato.png",
        }]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/roasted-potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    target = master_data.master_record_for_name("ingredients", "user-a", "potato")
    source = master_data.master_record_for_name("ingredients", "user-a", "potatoes")

    result = master_data.merge_ingredient_master_records(
        source["id"],
        target["id"],
        user_id="user-a",
    )

    assert result["ok"] is True
    assert result["moved_reference_count"] == 1
    assert result["combined_usage_count"] == 2
    assert result["aliases"] == ["Potatoes"]
    assert master_data.master_record_for_name("ingredients", "user-a", "potatoes") is None

    matches = master_data.list_ingredients(user_id="user-a", search="potatoes")
    assert len(matches) == 1
    assert matches[0]["id"] == target["id"]
    assert matches[0]["name"] == "Potato"
    assert matches[0]["aliases"] == ["Potatoes"]
    assert matches[0]["usage_count"] == 2

    master_data.sync_recipe_master_records(
        "https://example.com/mashed-potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes", "store_section": "Produce"}]},
        user_id="user-a",
    )
    refreshed_target = master_data.master_record_for_name("ingredients", "user-a", "potato")
    assert refreshed_target["name"] == "Potato"
    assert master_data.master_record_for_name("ingredients", "user-a", "potatoes") is None
    assert master_data.count_ingredient_usage(target["id"], user_id="user-a") == 3

    lookup = master_data.ingredient_master_records_for_items(
        [{"ingredient": "potatoes"}],
        user_id="user-a",
    )
    assert lookup["by_normalized_name"]["potatoes"]["id"] == target["id"]


def test_undo_last_ingredient_merge_restores_records_aliases_metadata_and_references(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/bean-soup",
        recipe_data={"ingredients": [{
            "ingredient": "Bean",
            "store_section": "Misc",
        }]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/roasted-beans",
        recipe_data={"ingredients": [{
            "ingredient": "Beans",
            "store_section": "Produce",
            "ingredient_image_url": "/static/generated/beans.png",
        }]},
        user_id="user-a",
    )
    target = master_data.master_record_for_name("ingredients", "user-a", "bean")
    source = master_data.master_record_for_name("ingredients", "user-a", "beans")
    with master_data.recipe_master_connection() as connection:
        now = master_data.utc_now_iso()
        connection.execute(
            """
            INSERT INTO ingredient_aliases (
                user_id, ingredient_id, alias_name, normalized_alias, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("user-a", source["id"], "Garden beans", "garden beans", now, now),
        )
        connection.execute(
            """
            INSERT INTO ingredient_aliases (
                user_id, ingredient_id, alias_name, normalized_alias, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("user-a", target["id"], "Bean pod", "bean pod", now, now),
        )

    merge_result = master_data.merge_ingredient_master_records(
        source["id"],
        target["id"],
        user_id="user-a",
    )
    merged_target = master_data.master_record_for_name("ingredients", "user-a", "bean")

    assert merge_result["ok"] is True
    assert merge_result["merge_id"] > 0
    assert merged_target["store_section"] == "PRODUCE"
    assert merged_target["image_url"] == "/static/generated/beans.png"
    assert master_data.latest_undoable_ingredient_merge("user-a")["merge_id"] == merge_result["merge_id"]

    undo_preview = master_data.ingredient_merge_undo_preview("user-a")

    assert undo_preview["ok"] is True
    assert undo_preview["merge_id"] == merge_result["merge_id"]
    assert undo_preview["source_restore"]["name"] == "Beans"
    assert undo_preview["source_restore"]["image_url"] == "/static/generated/beans.png"
    assert undo_preview["target_restore"]["name"] == "Bean"
    assert undo_preview["restored_reference_count"] == 1
    assert undo_preview["reference_previews"][0]["recipe_title"] == "Roasted Beans"
    assert undo_preview["older_undo_count"] == 0

    undo_result = master_data.undo_last_ingredient_master_merge("user-a")
    restored_source = master_data.master_record_for_name("ingredients", "user-a", "beans")
    restored_target = master_data.master_record_for_name("ingredients", "user-a", "bean")

    assert undo_result["ok"] is True
    assert undo_result["restored_reference_count"] == 1
    assert undo_result["next_merge"] is None
    assert restored_source["id"] == source["id"]
    assert restored_source["store_section"] == "PRODUCE"
    assert restored_source["image_url"] == "/static/generated/beans.png"
    assert restored_target["id"] == target["id"]
    assert restored_target["store_section"] == "MISC"
    assert restored_target["image_url"] == ""
    assert master_data.count_ingredient_usage(source["id"], user_id="user-a") == 1
    assert master_data.count_ingredient_usage(target["id"], user_id="user-a") == 1
    assert master_data.list_ingredients(user_id="user-a", search="garden beans")[0]["id"] == source["id"]
    assert master_data.list_ingredients(user_id="user-a", search="bean pod")[0]["id"] == target["id"]
    assert master_data.latest_undoable_ingredient_merge("user-a") is None


def test_ingredient_merge_history_can_be_previewed_and_undone_repeatedly(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    for name in ("Carrot", "Carrots", "Bean", "Beans"):
        master_data.sync_recipe_master_records(
            f"https://example.com/{name.lower()}",
            recipe_data={"ingredients": [{"ingredient": name, "store_section": "Produce"}]},
            user_id="user-a",
        )

    carrot = master_data.master_record_for_name("ingredients", "user-a", "carrot")
    carrots = master_data.master_record_for_name("ingredients", "user-a", "carrots")
    bean = master_data.master_record_for_name("ingredients", "user-a", "bean")
    beans = master_data.master_record_for_name("ingredients", "user-a", "beans")
    first_merge = master_data.merge_ingredient_master_records(
        carrots["id"], carrot["id"], user_id="user-a"
    )
    second_merge = master_data.merge_ingredient_master_records(
        beans["id"], bean["id"], user_id="user-a"
    )

    latest_preview = master_data.ingredient_merge_undo_preview("user-a")
    independent_older_preview = master_data.ingredient_merge_undo_preview(
        "user-a", merge_id=first_merge["merge_id"]
    )
    out_of_order_undo = master_data.undo_last_ingredient_master_merge(
        "user-a", expected_merge_id=first_merge["merge_id"]
    )
    remaining_preview = master_data.ingredient_merge_undo_preview("user-a")
    latest_undo = master_data.undo_last_ingredient_master_merge(
        "user-a", expected_merge_id=second_merge["merge_id"]
    )

    assert latest_preview["merge_id"] == second_merge["merge_id"]
    assert latest_preview["source_name"] == "Beans"
    assert latest_preview["older_undo_count"] == 1
    assert latest_preview["is_next_undo"] is True
    assert [row["merge_id"] for row in latest_preview["undoable_merges"]] == [
        second_merge["merge_id"],
        first_merge["merge_id"],
    ]
    assert latest_preview["undoable_merges"][0]["is_next_undo"] is True
    assert latest_preview["undoable_merges"][1]["newer_undo_count"] == 1
    assert latest_preview["undoable_merges"][1]["can_undo_now"] is True
    assert independent_older_preview["merge_id"] == first_merge["merge_id"]
    assert independent_older_preview["is_next_undo"] is False
    assert independent_older_preview["can_undo_now"] is True
    assert independent_older_preview["newer_undo_count"] == 1
    assert out_of_order_undo["ok"] is True
    assert out_of_order_undo["merge_id"] == first_merge["merge_id"]
    assert out_of_order_undo["next_merge"]["merge_id"] == second_merge["merge_id"]
    assert remaining_preview["merge_id"] == second_merge["merge_id"]
    assert remaining_preview["older_undo_count"] == 0
    assert latest_undo["ok"] is True
    assert latest_undo["next_merge"] is None
    assert master_data.latest_undoable_ingredient_merge("user-a") is None


def test_out_of_order_undo_blocks_dependent_merge_until_newer_merge_is_undone(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    for name in ("Scallions", "Green Onion", "Onion"):
        master_data.sync_recipe_master_records(
            f"https://example.com/{name.lower().replace(' ', '-')}",
            recipe_data={"ingredients": [{"ingredient": name, "store_section": "Produce"}]},
            user_id="user-a",
        )

    scallions = master_data.master_record_for_name("ingredients", "user-a", "scallions")
    green_onion = master_data.master_record_for_name("ingredients", "user-a", "green onion")
    onion = master_data.master_record_for_name("ingredients", "user-a", "onion")
    older_merge = master_data.merge_ingredient_master_records(
        scallions["id"], green_onion["id"], user_id="user-a"
    )
    newer_merge = master_data.merge_ingredient_master_records(
        green_onion["id"], onion["id"], user_id="user-a"
    )

    blocked_preview = master_data.ingredient_merge_undo_preview(
        "user-a", merge_id=older_merge["merge_id"]
    )
    blocked_undo = master_data.undo_last_ingredient_master_merge(
        "user-a", expected_merge_id=older_merge["merge_id"]
    )
    newer_undo = master_data.undo_last_ingredient_master_merge(
        "user-a", expected_merge_id=newer_merge["merge_id"]
    )
    unlocked_preview = master_data.ingredient_merge_undo_preview(
        "user-a", merge_id=older_merge["merge_id"]
    )

    assert blocked_preview["can_undo_now"] is False
    assert "surviving ingredient changed" in blocked_preview["blocked_reason"]
    assert blocked_preview["undoable_merges"][1]["can_undo_now"] is False
    assert blocked_undo["ok"] is False
    assert blocked_undo["status"] == 409
    assert newer_undo["ok"] is True
    assert unlocked_preview["can_undo_now"] is True


def test_undo_ingredient_merge_refuses_to_overwrite_later_target_edits(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/onion",
        recipe_data={"ingredients": [{"ingredient": "Onion", "store_section": "Produce"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/onions",
        recipe_data={"ingredients": [{"ingredient": "Onions", "store_section": "Produce"}]},
        user_id="user-a",
    )
    target = master_data.master_record_for_name("ingredients", "user-a", "onion")
    source = master_data.master_record_for_name("ingredients", "user-a", "onions")
    assert master_data.merge_ingredient_master_records(
        source["id"], target["id"], user_id="user-a"
    )["ok"] is True
    assert master_data.update_ingredient_master_record(
        target["id"], "Yellow Onion", "yellow onion", "PRODUCE", user_id="user-a"
    )["ok"] is True

    undo_result = master_data.undo_last_ingredient_master_merge("user-a")

    assert undo_result["ok"] is False
    assert undo_result["status"] == 409
    assert "changed after this merge" in undo_result["error"]
    assert master_data.master_record_for_name("ingredients", "user-a", "onions") is None
    assert master_data.latest_undoable_ingredient_merge("user-a") is not None


def test_merge_ingredient_master_records_rejects_cross_workspace_targets(monkeypatch, tmp_path):
    configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.com/user-a-potato",
        recipe_data={"ingredients": [{"ingredient": "Potato"}]},
        user_id="user-a",
    )
    master_data.sync_recipe_master_records(
        "https://example.com/user-b-potatoes",
        recipe_data={"ingredients": [{"ingredient": "Potatoes"}]},
        user_id="user-b",
    )
    user_a_target = master_data.master_record_for_name("ingredients", "user-a", "potato")
    user_b_source = master_data.master_record_for_name("ingredients", "user-b", "potatoes")

    scoped_result = master_data.merge_ingredient_master_records(
        user_b_source["id"],
        user_a_target["id"],
        user_id="user-a",
    )
    admin_result = master_data.merge_ingredient_master_records(
        user_b_source["id"],
        user_a_target["id"],
        user_id="admin-user",
        allow_other_users=True,
    )

    assert scoped_result["ok"] is False
    assert scoped_result["status"] == 404
    assert admin_result["ok"] is False
    assert admin_result["status"] == 400


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
