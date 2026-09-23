from copy import deepcopy
import json

import pytest
from flask import Flask

from PushShoppingList.services import product_selection_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_preview_service
from PushShoppingList.services import recipe_preview_shopping_service
from PushShoppingList.services import recipe_quantity_service
from PushShoppingList.services import shopping_list_service
from test_ingredient_choice_shopping_scaling import choice_recipe


@pytest.fixture
def preview_shopping(monkeypatch, tmp_path):
    recipe = choice_recipe()
    recipe_url = recipe["source_url"]
    records_file = tmp_path / "recipe_ingredients.json"
    records_file.write_text(json.dumps({recipe_url: {"ingredients": ["butter", "canned cream-style corn"]}}))

    def load_records():
        return json.loads(records_file.read_text())

    def save_records(value):
        records_file.write_text(json.dumps(value))

    monkeypatch.setattr(recipe_edit_service, "load_recipe_output", lambda _url: deepcopy(recipe))
    monkeypatch.setattr(recipe_ingredient_service, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(recipe_ingredient_service, "save_recipe_ingredients", save_records)
    monkeypatch.setattr(recipe_quantity_service, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(recipe_quantity_service, "save_recipe_ingredients", save_records)
    monkeypatch.setattr(product_selection_service, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_FILE", tmp_path / "shopping.txt")
    monkeypatch.setattr(shopping_list_service, "SHOPPING_LIST_SELECTIONS_FILE", tmp_path / "selections.json")
    monkeypatch.setattr(recipe_preview_shopping_service, "add_recipe_urls", lambda _urls: None)
    monkeypatch.setattr(product_selection_service, "load_item_state", lambda: {})
    monkeypatch.setattr(product_selection_service, "recipe_url_rows", lambda: [{
        "url": recipe_url, "quantity": load_records()[recipe_url].get("quantity", 1),
    }])
    return recipe, load_records


def test_add_preview_persists_draft_bundle_and_scale_only_on_shopping_instance(preview_shopping):
    saved, load_records = preview_shopping
    original = deepcopy(saved)
    draft = deepcopy(saved)
    draft["recipe_title"] = "Unsaved recipe title"
    draft["ingredients"][1]["substitutions"][0]["quantity"] = "1/3"
    draft["ingredients"].append({"ingredient": "paprika", "notes": "optional pinch"})
    shopping_list_service.add_items(["butter", "canned cream-style corn"])

    result = recipe_preview_shopping_service.add_preview_to_shopping_list({
        "url": saved["source_url"], "recipe": draft, "options": {"scale": 3},
    })

    assert result["ok"] is True
    assert result["servings"] == "24"
    assert set(shopping_list_service.load_items()) == {"egg", "unsalted butter", "corn", "cumin", "onion", "paprika"}
    assert saved == original
    record = load_records()[saved["source_url"]]
    assert record["quantity"] == 3
    assert record["shopping_preview_recipe"]["recipe_title"] == "Unsaved recipe title"
    assert record["shopping_preview_recipe"]["ingredients"][1]["quantity"] == "1/3"
    assert not record["shopping_preview_recipe"]["ingredients"][2].get("quantity")

    context = product_selection_service.load_item_quantity_context(shopping_list_service.load_items())
    assert context["unsalted butter"]["display"] == "1 cup"
    assert context["eggs"]["display"].startswith("6")
    assert "cumin" not in context
    assert "paprika" not in context


def test_shopping_scale_changes_use_snapshot_base_once(preview_shopping):
    saved, load_records = preview_shopping
    recipe_preview_shopping_service.add_preview_to_shopping_list({
        "url": saved["source_url"], "recipe": saved, "options": {"scale": 2},
    })
    result = recipe_quantity_service.update_recipe_quantity(saved["source_url"], 3)
    assert result["servings"] == "24"
    assert result["ingredients"]["unsalted butter"]["quantity"] == "3/4"
    assert "egg" not in result["ingredients"]  # Name cache cannot represent both occurrences.
    context = product_selection_service.load_item_quantity_context(shopping_list_service.load_items())
    assert context["eggs"]["display"].startswith("6")
    assert context["unsalted butter"]["display"] == "3/4 cups"
    assert load_records()[saved["source_url"]]["shopping_preview_recipe"]["servings"] == "8"


def test_explicit_choice_is_same_in_preview_and_shopping(preview_shopping):
    saved, load_records = preview_shopping
    payload = {
        "url": saved["source_url"], "recipe": saved, "options": {"scale": 2},
        "ingredient_option_selections": {"requirement-butter": "butter-only", "requirement-corn": "corn-only"},
    }
    expected = recipe_preview_service.build_recipe_preview(payload)
    result = recipe_preview_shopping_service.add_preview_to_shopping_list(payload)
    snapshot = load_records()[saved["source_url"]]["shopping_preview_recipe"]
    assert [row["ingredient"] for row in snapshot["ingredients"]] == [row["ingredient"] for row in expected["recipe"]["ingredients"]]
    assert result["ingredient_option_selections"] == expected["ingredient_option_selections"]
    assert set(shopping_list_service.load_items()) == {"egg", "butter", "corn"}


def test_recipe_save_record_retires_shopping_snapshot(preview_shopping, monkeypatch):
    saved, load_records = preview_shopping
    recipe_preview_shopping_service.add_preview_to_shopping_list({"url": saved["source_url"], "recipe": saved})
    existing = load_records()[saved["source_url"]]
    assert "shopping_preview_recipe" in existing
    monkeypatch.setattr(recipe_edit_service, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(recipe_edit_service, "save_recipe_ingredients", recipe_ingredient_service.save_recipe_ingredients)
    monkeypatch.setattr(recipe_quantity_service, "load_saved_recipe_output", lambda _url: deepcopy(saved))
    saved["ingredients"][0]["quantity"] = "3"
    # Exercise the actual ingredient-record sync used by Save Recipe, then the
    # immediately following scale sync. Neither may retain the old snapshot.
    recipe_edit_service.update_recipe_ingredient_record(saved["source_url"], 2, saved, sync_master=False)
    assert "shopping_preview_recipe" not in load_records()[saved["source_url"]]
    recipe_quantity_service.update_recipe_quantity(saved["source_url"], 2)
    monkeypatch.setattr(product_selection_service, "load_saved_recipe_output", lambda _url: deepcopy(saved))
    context = product_selection_service.load_item_quantity_context(shopping_list_service.load_items())
    assert context["eggs"]["display"].startswith("6")


def test_unresolved_choice_does_not_partially_add_items(preview_shopping):
    saved, load_records = preview_shopping
    saved["ingredients"][1]["default_option_id"] = "removed-option"
    before = load_records()
    with pytest.raises(recipe_preview_service.RecipePreviewError):
        recipe_preview_shopping_service.add_preview_to_shopping_list({"url": saved["source_url"], "recipe": saved})
    assert shopping_list_service.load_items() == []
    assert load_records() == before


def test_shopping_route_and_display_use_persisted_preview(preview_shopping, monkeypatch):
    from PushShoppingList.routes import main_routes, recipe_routes

    saved, load_records = preview_shopping
    application = Flask(__name__)
    application.register_blueprint(recipe_routes.recipe_bp)
    response = application.test_client().post("/api/recipe_preview/shopping-list", json={
        "url": saved["source_url"], "recipe": saved, "options": {"scale": 2},
    })
    assert response.status_code == 200
    assert response.get_json()["quantity"] == 2
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda _url: pytest.fail("Shopping snapshot was ignored"))
    rows = main_routes.recipe_quantity_rows([{"url": saved["source_url"], "quantity": 2}])
    items = [item for group in rows[0]["sections"].values() for item in group]
    assert [item["name"] for item in items].count("egg") == 2
    assert not any(item["name"] == "canned cream-style corn" for item in items)
    assert next(item for item in items if item["name"] == "unsalted butter")["quantity_display"].startswith("1/2")


def test_shopping_route_preserves_preview_error_status(preview_shopping):
    from PushShoppingList.routes import recipe_routes

    saved, _load_records = preview_shopping
    saved["ingredients"][1]["default_option_id"] = "removed-option"
    application = Flask(__name__)
    application.register_blueprint(recipe_routes.recipe_bp)
    response = application.test_client().post("/api/recipe_preview/shopping-list", json={
        "url": saved["source_url"], "recipe": saved,
    })
    assert response.status_code == 409
    assert response.get_json()["selection_needed"] is True
    assert shopping_list_service.load_items() == []


@pytest.mark.parametrize("new_cover", [{"url": "https://example.test/new-cover.png"}, {}])
def test_shopping_snapshot_uses_current_cover_and_favorite(preview_shopping, monkeypatch, new_cover):
    from PushShoppingList.routes import main_routes

    saved, load_records = preview_shopping
    saved["cover_image"] = {"url": "https://example.test/old-cover.png"}
    draft = deepcopy(saved)
    draft["recipe_title"] = "Unsaved shopping title"
    draft["description"] = "Unsaved description"
    recipe_preview_shopping_service.add_preview_to_shopping_list({
        "url": saved["source_url"], "recipe": draft, "options": {"scale": 2},
    })
    saved["cover_image"] = new_cover
    saved["favorite"] = True
    monkeypatch.setattr(main_routes, "load_recipe_ingredients", load_records)
    monkeypatch.setattr(main_routes, "load_saved_recipe_output", lambda _url: deepcopy(saved))
    monkeypatch.setattr(main_routes, "recipe_pdf_public_url", lambda *_args: "")
    monkeypatch.setattr(main_routes, "recipe_archive_pdf_exists", lambda _url: False)
    application = Flask(__name__)
    with application.test_request_context("/"):
        row = main_routes.recipe_view_rows([
            {"url": saved["source_url"], "name": "Saved title", "quantity": 2},
        ], food_rules={"avoid": [], "prefer": []}, include_detail_images=False)[0]
    assert row["favorite"] is True
    assert row["cover_image"].get("url", "") == new_cover.get("url", "")
    assert row["name"] == "Unsaved shopping title"
    assert row["description"] == "Unsaved description"
    assert row["quantity"] == 2
    persisted = load_records()[saved["source_url"]]
    assert persisted["shopping_preview_recipe"]["cover_image"]["url"] == "https://example.test/old-cover.png"


def test_shopping_draft_metadata_stays_out_of_editor_fallback_fields(preview_shopping):
    saved, load_records = preview_shopping
    saved["recipe_title"] = "Saved recipe title"
    saved["servings"] = ""
    draft = deepcopy(saved)
    draft.update({
        "recipe_title": "Unsaved title", "display_name": "Unsaved display name",
        "servings": "12", "level": "Medium", "total_time": "45 min",
        "prep_time": "5 min", "cook_time": "40 min", "inactive_time": "10 min",
        "description": "Unsaved description",
    })
    recipe_preview_shopping_service.add_preview_to_shopping_list({
        "url": saved["source_url"], "recipe": draft, "options": {"scale": 2},
    })
    record = load_records()[saved["source_url"]]
    assert record["name"] == "Saved recipe title"
    for field in ("servings", "base_servings", "level", "total_time", "prep_time", "cook_time", "inactive_time"):
        assert not record[field], field
    assert record["scaled_servings"] == "24"
    assert record["shopping_preview_recipe"]["recipe_title"] == "Unsaved display name"
    assert record["shopping_preview_recipe"]["servings"] == "12"
    assert record["shopping_preview_recipe"]["total_time"] == "45 min"
