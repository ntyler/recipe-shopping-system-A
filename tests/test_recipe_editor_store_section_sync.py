from PushShoppingList.services import menu_mega_json_service
from PushShoppingList.services import menu_store_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_master_data_service as master_data


def configure_editor_master_sync(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    pdf_dir = tmp_path / "pdf"
    output_dir.mkdir()
    pdf_dir.mkdir()
    recipe_meta = {}

    def load_recipe_meta():
        return dict(recipe_meta)

    def save_recipe_meta(data):
        recipe_meta.clear()
        recipe_meta.update(data)

    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_extract_service, "PDF_FOLDER", pdf_dir)
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", tmp_path / "recipe_master.sqlite3")
    monkeypatch.setattr(menu_store_service, "MENU_STORE_FILE", tmp_path / "restaurant_menus.json")
    monkeypatch.setattr(menu_mega_json_service, "workspace_data_root", lambda: tmp_path)
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", load_recipe_meta)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_ingredients", save_recipe_meta)
    monkeypatch.setattr(recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda url: {})
    monkeypatch.setattr(recipe_edit_service, "load_food_rules", lambda: {"require": [], "avoid": []})
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_url_name", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "update_recipe_quantity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_edit_service, "sync_saved_recipe_with_shopping_list", lambda *args, **kwargs: None)


def recipe_payload(url, ingredients):
    return {
        "source_url": url,
        "display_name": "Broth Soup",
        "recipe_title": "Broth Soup",
        "quantity": 1,
        "servings": "",
        "level": "",
        "total_time": "",
        "prep_time": "",
        "inactive_time": "",
        "cook_time": "",
        "scaling": {},
        "ingredients": ingredients,
        "equipment": [],
        "instructions": [{"instruction": "Simmer."}],
        "nutrition": [],
        "rating": 0,
        "reflection_notes": [],
    }


def test_recipe_editor_load_uses_user_master_store_section(monkeypatch, tmp_path, capsys):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/chicken-broth-soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Chicken Broth Soup",
        "ingredients": [{
            "ingredient": "Chicken broth",
            "normalized_name": "chicken broth",
            "store_section": "MEAT & SEAFOOD",
        }],
        "instructions": [{"instruction": "Simmer."}],
    })
    master_data.sync_recipe_master_records(
        url,
        recipe_data={
            "ingredients": [{
                "ingredient": "Chicken broth",
                "store_section": "Canned",
                "ingredient_image_url": "/static/generated/master/chicken-broth.png",
            }]
        },
        user_id=master_data.LOCAL_USER_ID,
    )

    loaded = recipe_edit_service.load_editable_recipe(url)
    output = capsys.readouterr().out
    ingredient = loaded["recipe"]["ingredients"][0]

    assert ingredient["store_section"] == "CANNED"
    assert ingredient["ingredient_image_url"] == "/static/generated/master/chicken-broth.png"
    assert ingredient["ingredient_id"]
    assert loaded["store_sections"] == master_data.ingredient_store_section_options()
    assert (
        '[IngredientMaster] action=store_section_loaded_from_master '
        'recipe_id=https://example.com/chicken-broth-soup '
        'ingredient="Chicken broth" section="CANNED"'
    ) in output


def test_recipe_editor_save_updates_only_active_users_master_store_section(monkeypatch, tmp_path, capsys):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/save-broth-soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Broth Soup",
        "ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    master_data.sync_recipe_master_records(
        url,
        recipe_data={"ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}]},
        user_id=master_data.LOCAL_USER_ID,
    )
    master_data.sync_recipe_master_records(
        "https://example.com/other-user-broth",
        recipe_data={"ingredients": [{"ingredient": "Chicken broth", "store_section": "BAKING"}]},
        user_id="other-user",
    )
    local_broth = master_data.master_record_for_name("ingredients", master_data.LOCAL_USER_ID, "chicken broth")
    capsys.readouterr()

    result = recipe_edit_service.save_editable_recipe(
        url,
        recipe_payload(url, [{
            "ingredient_id": str(local_broth["id"]),
            "ingredient": "Chicken broth",
            "normalized_name": "chicken broth",
            "store_section": "DRY GOODS",
            "store_section_source": "manual",
            "store_section_user_confirmed": True,
            "store_section_save_to_master": True,
        }]),
    )
    output = capsys.readouterr().out

    assert result["ok"] is True
    assert master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )["store_section"] == "DRY GOODS"
    assert master_data.master_record_for_name(
        "ingredients",
        "other-user",
        "chicken broth",
    )["store_section"] == "BAKING"
    assert recipe_edit_service.load_recipe_output(url)["ingredients"][0]["store_section"] == "DRY GOODS"
    assert [row["name"] for row in master_data.list_ingredients(
        user_id=master_data.LOCAL_USER_ID,
        store_section="DRY GOODS",
    )] == ["Chicken broth"]
    assert (
        '[IngredientMaster] action=store_section_updated_from_recipe '
        'ingredient="Chicken broth" section="DRY GOODS" user_id=local'
    ) in output


def test_recipe_editor_save_matches_master_by_normalized_name_without_id(monkeypatch, tmp_path):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/normalized-broth-soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Normalized Broth Soup",
        "ingredients": [{"ingredient": "Broth", "normalized_name": "chicken broth", "store_section": "CANNED"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    master_data.sync_recipe_master_records(
        "https://example.com/master-chicken-broth",
        recipe_data={"ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}]},
        user_id=master_data.LOCAL_USER_ID,
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        recipe_payload(url, [{
            "ingredient": "Broth",
            "normalized_name": "chicken broth",
            "store_section": "DRY GOODS",
            "store_section_source": "manual",
            "store_section_user_confirmed": True,
            "store_section_save_to_master": True,
        }]),
    )

    assert result["ok"] is True
    assert master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )["store_section"] == "DRY GOODS"
    assert master_data.master_record_for_name("ingredients", master_data.LOCAL_USER_ID, "broth") is None


def test_recipe_override_does_not_update_master_without_future_occurrences_choice(monkeypatch, tmp_path):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/recipe-only-broth-section"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Recipe-only Broth",
        "ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    master_data.sync_recipe_master_records(
        url,
        recipe_data={"ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}]},
        user_id=master_data.LOCAL_USER_ID,
    )
    master = master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        recipe_payload(url, [{
            "ingredient_id": str(master["id"]),
            "ingredient": "Chicken broth",
            "normalized_name": "chicken broth",
            "store_section": "DRY GOODS",
            "store_section_source": "recipe_override",
            "store_section_user_confirmed": True,
            "store_section_save_to_master": False,
        }]),
    )

    assert result["ok"] is True
    assert recipe_edit_service.load_recipe_output(url)["ingredients"][0]["store_section"] == "DRY GOODS"
    assert master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )["store_section"] == "CANNED"


def test_recipe_editor_custom_store_section_round_trips_without_overwriting_master(monkeypatch, tmp_path):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/international-broth-soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "International Broth Soup",
        "ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}],
        "instructions": [{"instruction": "Simmer."}],
    })
    master_data.sync_recipe_master_records(
        url,
        recipe_data={"ingredients": [{"ingredient": "Chicken broth", "store_section": "CANNED"}]},
        user_id=master_data.LOCAL_USER_ID,
    )
    local_broth = master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )

    result = recipe_edit_service.save_editable_recipe(
        url,
        recipe_payload(url, [{
            "ingredient_id": str(local_broth["id"]),
            "ingredient": "Chicken broth",
            "normalized_name": "chicken broth",
            "store_section": "International Foods",
            "store_section_custom": True,
            "substitutions": [{
                "ingredient": "Miso broth",
                "store_section": "Asian Market",
                "store_section_custom": True,
            }],
        }]),
    )

    assert result["ok"] is True
    saved = recipe_edit_service.load_recipe_output(url)["ingredients"][0]
    assert saved["store_section"] == "International Foods"
    assert saved["store_section_custom"] is True
    assert saved["substitutions"][0]["store_section"] == "Asian Market"
    assert saved["substitutions"][0]["store_section_custom"] is True

    loaded = recipe_edit_service.load_editable_recipe(url)["recipe"]["ingredients"][0]
    assert loaded["store_section"] == "International Foods"
    assert loaded["store_section_custom"] is True
    assert loaded["substitutions"][0]["store_section"] == "Asian Market"
    assert loaded["substitutions"][0]["store_section_custom"] is True
    assert master_data.master_record_for_name(
        "ingredients",
        master_data.LOCAL_USER_ID,
        "chicken broth",
    )["store_section"] == "CANNED"


def test_recipe_editor_missing_store_section_defaults_to_misc(monkeypatch, tmp_path, capsys):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/mystery-soup"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Mystery Soup",
        "ingredients": [{"ingredient": "Mystery crunch"}],
        "instructions": [{"instruction": "Serve."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)
    output = capsys.readouterr().out

    assert loaded["recipe"]["ingredients"][0]["store_section"] == "MISC"
    assert (
        '[IngredientMaster] action=store_section_missing_default '
        'ingredient="Mystery crunch" section="MISC"'
    ) in output


def test_recipe_editor_load_classifies_common_generic_or_conflicting_sections(monkeypatch, tmp_path):
    configure_editor_master_sync(monkeypatch, tmp_path)
    url = "https://example.com/huancaina"
    recipe_edit_service.save_recipe_output(url, {
        "source_url": url,
        "recipe_title": "Papa a la Huancaina",
        "ingredients": [
            {
                "ingredient": "potatoes",
                "normalized_name": "potato",
                "store_section": "MISC",
                "original_text": "4 medium potatoes",
            },
            {
                "ingredient": "crema",
                "normalized_name": "crema",
                "store_section": "MISC",
                "original_text": "1 cup crema",
            },
            {
                "ingredient": "chicken broth",
                "normalized_name": "chicken broth",
                "store_section": "MEAT & SEAFOOD",
                "original_text": "2 cups chicken broth",
            },
        ],
        "instructions": [{"instruction": "Simmer."}],
    })

    loaded = recipe_edit_service.load_editable_recipe(url)
    ingredients = loaded["recipe"]["ingredients"]

    assert [item["store_section"] for item in ingredients] == [
        "PRODUCE",
        "DAIRY & EGGS",
        "CANNED",
    ]


def test_review_recipe_store_sections_returns_preview_changes():
    result = recipe_edit_service.review_recipe_store_sections({
        "recipe_title": "Papa a la Huancaina",
        "ingredients": [
            {
                "ingredient": "potatoes",
                "store_section": "DAIRY & EGGS",
                "original_text": "4 medium potatoes",
            },
            {
                "ingredient": "chicken broth",
                "store_section": "MEAT & SEAFOOD",
                "original_text": "2 cups chicken broth",
            },
            {
                "ingredient": "inca pepper",
                "store_section": "SPICES & SEASONINGS",
                "original_text": "inca pepper",
            },
        ],
    })

    assert result["ok"] is True
    assert result["reviewed_count"] == 3
    assert result["changed_count"] == 3
    assert [change["proposed_store_section"] for change in result["changes"]] == [
        "PRODUCE",
        "CANNED",
        "PRODUCE",
    ]
    assert result["changes"][0]["current_store_section"] == "DAIRY & EGGS"
    assert [item["store_section"] for item in result["recipe"]["ingredients"]] == [
        "PRODUCE",
        "CANNED",
        "PRODUCE",
    ]
