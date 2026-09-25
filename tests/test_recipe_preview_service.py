"""Preview and PDF must share draft-safe choice and scaling semantics."""

from base64 import b64decode
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from flask import Flask
import pytest

from PushShoppingList.routes.recipe_routes import recipe_bp
from PushShoppingList.services import recipe_preview_service as preview


URL = "https://example.test/preview-fixture"
STATIC = Path(__file__).resolve().parents[1] / "PushShoppingList" / "static"


def shared_preview_card(view):
    """Exercise the shipped template without starting or automating a browser."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the shared recipe renderer")
    script = """
        const fs = require('fs');
        const vm = require('vm');
        vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
        const model = JSON.parse(fs.readFileSync(0, 'utf8'));
        process.stdout.write(recipePreviewCardHtml(model));
    """
    rendered = subprocess.run(
        [node, "-e", script, str(STATIC / "js" / "recipe-preview-renderer.js")],
        input=json.dumps(view), text=True, encoding="utf-8", capture_output=True, check=True,
    ).stdout
    return BeautifulSoup(rendered, "html.parser")


def selected_ingredients(card):
    return card.select(
        ".recipe-preview-ingredients > ul > .recipe-task-row, "
        '.recipe-preview-choice-option[data-selected="true"] .recipe-task-row'
    )


def capture_pdf_export(monkeypatch, payload):
    """Capture the trusted renderer invocation through the public PDF API."""
    captured = {}

    class Driver:
        def execute_script(self, source, *arguments):
            captured["script"] = source
            captured["arguments"] = arguments
            return True

        def execute_async_script(self, source):
            captured["asset_wait"] = source
            return True

        def set_script_timeout(self, timeout):
            captured["script_timeout"] = timeout

    def render(url, html, _source, path, **kwargs):
        captured.update(url=url, html=html, path=path, **kwargs)
        kwargs["prepare_document"](Driver())
        path.write_bytes(b"%PDF-1.4 test attachment")
        return path

    monkeypatch.setattr(preview.recipe_extract_service, "write_recipe_page_pdf", render)
    captured["content"], captured["title"] = preview.create_recipe_preview_pdf(payload)
    return captured


@pytest.fixture
def recipe(monkeypatch):
    value = {
        "recipe_title": "Preview fixture", "source_url": URL, "servings": "4 servings",
        "description": "A saved description", "favorite": True, "rating": 3,
        "author": {"name": "Test cook"}, "prep_time": "5 min", "cook_time": "20 min",
        "total_time": "25 min", "meal_type": "Side Dish", "cuisine_tags": ["American"],
        "ingredients": [
            {"ingredient": "egg", "quantity": "2", "unit": "", "notes": "room temperature"},
            {"ingredient": "source butter", "quantity": "1/2", "unit": "cup",
             "recipe_ingredient_id": "butter-choice", "default_option_id": "bundle",
             "substitutions": [
                 {"ingredient": "unsalted butter", "quantity": "1/4", "unit": "cup",
                  "preparation": "melted", "alternative_id": "bundle", "option_type": "original"},
                 {"ingredient": "egg", "quantity": None, "notes": "whisked",
                  "alternative_id": "bundle", "option_type": "original"},
                 {"ingredient": "butter", "quantity": "1/2", "unit": "cup",
                  "alternative_id": "simple", "option_type": "recipe_choice"},
             ]},
        ],
        "instructions": [{"instruction": "Mix gently.\nBake until set.", "time": "20 min"}],
        "nutrition": {"serving_basis": "per serving", "calories": "200 kcal", "fat": "8 g", "sugar": 0},
    }
    monkeypatch.setattr(preview.recipe_edit_service, "load_recipe_output", lambda url: value if url == URL else None)
    monkeypatch.setattr(preview.recipe_edit_service, "save_recipe_output", lambda *_a, **_k: pytest.fail("Preview must not save"))
    monkeypatch.setattr(preview.cuisine_category_service, "cuisine_category_registry_payload",
                        preview.cuisine_category_service.default_cuisine_category_registry_payload)
    monkeypatch.setattr(preview.ingredient_type_service, "ingredient_type_registry_payload",
                        preview.ingredient_type_service.default_ingredient_type_registry_payload)
    return value


def test_projection_resolves_complete_bundle_without_duplicate_or_invented_amounts(recipe):
    original = deepcopy(recipe)
    result = preview.build_recipe_preview({"url": URL, "options": {"scale": 2}})
    view = result["recipe"]
    rows = view["ingredients"]
    assert [row["ingredient"] for row in rows] == ["egg", "unsalted butter", "egg"]
    assert [row["quantity"] for row in rows] == ["4", "1/2", None]
    assert rows[2]["notes"] == "whisked"
    assert rows[2]["requirement_id"] == "butter-choice"
    assert rows[2]["option_id"] == "bundle"
    assert view["servings"] == "8 servings"
    assert view["base_servings"] == "4 servings"
    assert view["author"] == "Test cook"
    assert view["tags"] == ["Side Dish", "American"]
    assert recipe == original


def test_equipment_preview_normalizes_saved_rows_without_scaling_or_mutating(recipe):
    recipe["equipment"] = ["mixing bowl", {"name": "oven"}, {"equipment": "2 whisks", "equipment_row_id": "whisks"}, ""]
    original = deepcopy(recipe)
    view = preview.build_recipe_preview({"url": URL, "options": {"scale": 3}})["recipe"]
    assert [row["name"] for row in view["equipment"]] == ["mixing bowl", "oven", "2 whisks"]
    assert view["equipment"][2]["id"] == "whisks"
    assert recipe == original


@pytest.mark.parametrize("fields, expected", [
    ({}, ""),
    ({"purchasable_item": "   "}, ""),
    ({"purchasable_item": " EGG "}, ""),
    ({"purchasable_item": "large free-range eggs"}, "large free-range eggs"),
    ({"buy_as": "large eggs"}, "large eggs"),
    ({"purchasable_item": "large eggs", "buy_as": "legacy name"}, "large eggs"),
])
def test_buy_as_label_omits_blank_and_matching_names_without_replacing_ingredient(recipe, fields, expected):
    recipe["ingredients"][0].update(fields)
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"scale": 2, "show_image": False}})
    row = response["recipe"]["ingredients"][0]
    assert row["ingredient"] == "egg"
    assert row["buy_as_label"] == expected
    assert row["quantity"] == "4"
    assert response["recipe"]["ingredient_groups"][0]["items"][0]["buy_as_label"] == expected
    first = selected_ingredients(shared_preview_card(response["recipe"]))[0]
    assert bool(first.select_one(".recipe-preview-buy-as")) == bool(expected)
    if expected:
        assert first.select_one(".recipe-preview-buy-as").get_text() == f"(Buy as: {expected})"
    assert recipe == original


def test_buy_as_labels_follow_selected_bundle_and_escape_pdf_text(recipe):
    recipe["ingredients"][1]["substitutions"][0]["purchasable_item"] = 'butter <special> & cream'
    recipe["ingredients"][1]["substitutions"][2]["buy_as"] = 'salted butter'
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"show_image": False}})
    group = response["recipe"]["ingredient_groups"][1]
    assert group["items"][0]["buy_as_label"] == 'butter <special> & cream'
    assert group["options"][1]["items"][0]["buy_as_label"] == 'salted butter'
    card = shared_preview_card(response["recipe"])
    selected_rows = selected_ingredients(card)
    assert selected_rows[1].select_one(".recipe-preview-buy-as").get_text() == '(Buy as: butter <special> & cream)'
    assert not card.find("special")
    assert all('(Buy as: salted butter)' not in row.get_text() for row in selected_rows)
    selected = preview.build_recipe_preview({"url": URL, "ingredient_option_selections": {"butter-choice": "simple"}})
    assert selected["recipe"]["ingredients"][1]["buy_as_label"] == 'salted butter'
    assert recipe == original


@pytest.mark.parametrize("equipment, expected", [
    ([{"text": "9-inch pan <oven safe>", "row_id": "pan"}], ["9-inch pan <oven safe>"]),
    ([], []),
])
def test_equipment_draft_and_pdf_honor_edits_and_explicit_removal(recipe, equipment, expected):
    recipe["equipment"] = ["Saved mixing bowl"]
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({
        "url": URL, "recipe": {"equipment": equipment}, "options": {"show_image": False},
    })
    assert [row["name"] for row in response["recipe"]["equipment"]] == expected
    card = shared_preview_card(response["recipe"])
    assert [heading.get_text() for heading in card.select(".recipe-preview-columns h2")] == ["Ingredients", "Equipment", "Instructions"]
    section = card.select_one(".recipe-preview-equipment")
    assert "Saved mixing bowl" not in section.get_text()
    if expected:
        assert section.select_one(".recipe-task-text").get_text() == "9-inch pan <oven safe>"
        assert not section.find("oven")
    else:
        assert "No equipment specified." in section.get_text()
    assert recipe == original


@pytest.mark.parametrize("amount, expected", [("12.50", "12.50 CAD"), (0, "0 CAD"), ("", "")])
def test_preview_assignment_uses_draft_without_scaling_price_or_restoring_cleared_price(recipe, amount, expected):
    recipe.update(cookbook_name="Saved cookbook", menu_section="Saved section", menu_price="$99")
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({
        "url": URL, "options": {"scale": 3, "show_image": False},
        "recipe": {"cookbook_name": "Weeknight & weekend", "menu_section": "Sides",
                   "menu_price_amount": amount, "menu_price_currency": "CAD"},
    })
    view = response["recipe"]
    assert (view["cookbook_name"], view["menu_section"], view["menu_price"]) == (
        "Weeknight & weekend", "Sides", expected)
    card = shared_preview_card(view)
    assignment = {row.dt.get_text(): row.dd.get_text() for row in card.select(".recipe-preview-assignment > div")}
    assert assignment == {"Cookbook": "Weeknight & weekend", "Section": "Sides", "Menu Price (optional)": expected or "Not set"}
    assert recipe == original


def test_explicit_selected_option_and_stale_selection_fallback(recipe):
    selected = preview.build_recipe_preview({
        "url": URL, "ingredient_option_selections": {"butter-choice": "simple"},
        "options": {"scale": 3},
    })
    assert [row["ingredient"] for row in selected["recipe"]["ingredients"]] == ["egg", "butter"]
    assert selected["recipe"]["ingredients"][1]["quantity"] == "1 1/2"
    stale = preview.build_recipe_preview({"url": URL, "ingredient_option_selections": {"butter-choice": "deleted"}})
    assert stale["ingredient_option_selections"]["butter-choice"] == "bundle"


@pytest.mark.parametrize("selected, names", [("bundle", ["corn", "cumin", "onion"]), ("simple", ["corn"])])
def test_preview_retains_original_corn_requirement_as_heading_not_duplicate_ingredient(recipe, selected, names):
    source = "1 cup fresh or frozen corn"
    recipe["ingredients"][1] = {
        "recipe_ingredient_id": "corn-choice", "ingredient": "corn", "source_text": source,
        "quantity": "1", "unit": "cup", "default_option_id": "bundle",
        "substitutions": [
            {"ingredient": "corn", "quantity": "1", "unit": "cup", "preparation": "fresh", "alternative_id": "bundle", "option_type": "original"},
            {"ingredient": "cumin", "alternative_id": "bundle", "option_type": "original"},
            {"ingredient": "onion", "quantity": "1", "unit": "cup", "notes": "chopped", "alternative_id": "bundle", "option_type": "original"},
            {"ingredient": "corn", "quantity": "1", "unit": "cup", "preparation": "frozen", "alternative_id": "simple", "option_type": "recipe_choice"},
        ],
    }
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"scale": 2, "show_image": False},
        "ingredient_option_selections": {"corn-choice": selected}})
    view = response["recipe"]
    group = view["ingredient_groups"][1]
    assert group["is_choice"] is True
    assert group["source_text"] == source
    assert [row["ingredient"] for row in group["items"]] == names
    assert group["items"][0]["quantity"] == "2"
    bundles = {option["id"]: option for option in group["options"]}
    assert [row["ingredient"] for row in bundles["bundle"]["items"]] == ["corn", "cumin", "onion"]
    assert [row["quantity"] for row in bundles["bundle"]["items"]] == ["2", None, "2"]
    assert bundles["bundle"]["is_default"] is True
    assert bundles["simple"]["is_default"] is False
    assert bundles["simple"]["items"][0]["quantity"] == "2"
    assert bundles["simple"]["items"][0]["preparation"] == "frozen"
    assert group["selected_option_id"] == selected
    assert [row["ingredient"] for row in resolved["ingredients"]] == ["egg", *names]
    assert len(view["ingredients"]) == 1 + len(names)
    if selected == "bundle":
        assert not group["items"][1].get("quantity")
        assert group["items"][2]["notes"] == "chopped"
    card = shared_preview_card(view)
    assert [node.get_text() for node in card.select(".recipe-preview-choice-title")] == [source]
    selected_rows = selected_ingredients(card)
    selected_text = " ".join(row.get_text() for row in selected_rows)
    assert source not in selected_text
    assert ("cumin" in selected_text) == (selected == "bundle")
    assert ("frozen" in selected_text) == (selected == "simple")
    assert recipe == original


def test_missing_required_default_is_reported_not_silently_dropped(recipe):
    recipe["ingredients"][1]["default_option_id"] = "invalid"
    with pytest.raises(preview.RecipePreviewError) as error:
        preview.build_recipe_preview({"url": URL})
    assert error.value.status == 409
    assert error.value.details["selection_needed"] is True


def test_draft_overrides_saved_values_without_mutating_recipe_or_reading_draft_image(recipe):
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({
        "original_url": URL,
        "recipe": {
            "recipe_title": "Unsaved title", "description": "Unsaved description",
            "scaling": {"selected_multiplier": 1}, "quantity": 3,
            "meal_type": "Dinner", "custom_categories": ["Family favorite"],
            "cover_image": {"path": "C:/private.txt", "url": "file:///C:/private.txt"},
        },
    })
    assert response["recipe"]["title"] == "Unsaved title"
    assert response["recipe"]["description"] == "Unsaved description"
    assert response["recipe"]["ingredients"][0]["quantity"] == "6"
    assert response["recipe"]["tags"] == ["Dinner", "American", "Family favorite"]
    assert response["recipe"]["image_url"] == ""
    assert resolved["cover_image"] == {}
    assert recipe == original


def test_preview_uses_editor_display_name_and_respects_cleared_description(recipe):
    recipe["display_name"] = "Saved display name"
    recipe["menu_description"] = "Old menu description"
    result = preview.build_recipe_preview({"url": URL, "recipe": {
        "display_name": "Draft display name", "description": "",
    }})
    assert result["recipe"]["title"] == "Draft display name"
    assert result["recipe"]["description"] == ""


def test_instruction_metadata_follows_identity_after_reorder_not_position(recipe):
    recipe["instructions"] = [
        {"instruction_id": "mix", "instruction": "Mix.", "step_number": 1, "section": "Batter", "equipment_used": ["bowl"]},
        {"instruction_id": "bake", "instruction": "Bake.", "step_number": 2, "time": "20 min", "temperature": "350 F"},
    ]
    result = preview.build_recipe_preview({"url": URL, "recipe": {"instructions": [
        {"instruction_id": "bake", "instruction": "Bake carefully.", "step_number": 1},
        {"instruction_id": "new", "instruction": "Cool.", "step_number": 2},
        {"instruction_id": "mix", "instruction": "Mix.", "step_number": 3},
    ]}})["recipe"]["instructions"]
    assert result[0]["time"] == "20 min"
    assert result[0]["temperature"] == "350 F"
    assert "time" not in result[1]
    assert result[2]["section"] == "Batter"
    assert result[2]["equipment_used"] == ["bowl"]


def test_legacy_instruction_metadata_matches_unique_text_only(recipe):
    recipe["instructions"] = [{"instruction": "Bake.", "time": "20 min"}]
    result = preview.build_recipe_preview({"url": URL, "recipe": {"instructions": [
        {"instruction": "New instruction."}, {"instruction": "Bake."},
    ]}})["recipe"]["instructions"]
    assert "time" not in result[0]
    assert result[1]["time"] == "20 min"


def test_saved_scaled_recipe_is_scaled_from_its_base_exactly_once(recipe):
    recipe["scaling"] = {"selected_multiplier": 2, "base_servings": "4 servings"}
    recipe["servings"] = "8 servings"
    recipe["ingredients"][0].update(quantity="4", base_quantity="2")
    for row in recipe["ingredients"][1]["substitutions"]:
        if row.get("quantity"):
            row["base_quantity"] = row["quantity"]
            row["quantity"] = preview.scale_quantity(row["quantity"], 2)
    view = preview.build_recipe_preview({"url": URL, "options": {"scale": 3}})["recipe"]
    assert view["servings"] == "12 servings"
    assert [row["quantity"] for row in view["ingredients"]] == ["6", "3/4", None]


@pytest.mark.parametrize("basis, mode, calories", [
    ("per serving", "per_serving", "200 kcal"),
    ("per serving", "whole_recipe", "2400 kcal"),
    ("full recipe", "per_serving", "50 kcal"),
    ("full recipe", "whole_recipe", "600 kcal"),
])
def test_nutrition_basis_controls_scaling_without_inventing_data(recipe, basis, mode, calories):
    recipe["nutrition"]["serving_basis"] = basis
    original = deepcopy(recipe)
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"scale": 3, "nutrition_mode": mode}})
    result = response["recipe"]
    assert result["nutrition_mode"] == mode
    assert result["nutrition_modes"] == ["per_serving", "whole_recipe"]
    assert {row["key"]: row["value"] for row in result["nutrition"]}["calories"] == calories
    assert {row["key"]: row["value"] for row in result["nutrition"]}["sugar"] == "0"
    assert ("Total for 12 servings" if mode == "whole_recipe" else "Per serving · Makes 12 servings") == result["nutrition_context"]
    assert calories in shared_preview_card(result).select_one(".recipe-preview-print-nutrition").get_text()
    assert recipe == original
    del recipe["nutrition"]["serving_basis"]
    unknown = preview.build_recipe_preview({"url": URL})["recipe"]
    assert unknown["nutrition_basis"] == "Serving basis not specified"
    assert unknown["nutrition_modes"] == []


@pytest.mark.parametrize("servings", ["", "0", "4–6 servings", "one loaf"])
@pytest.mark.parametrize("basis, available", [("per serving", "per_serving"), ("whole recipe", "whole_recipe")])
def test_nutrition_missing_count_keeps_known_basis_and_disables_conversion(recipe, servings, basis, available):
    recipe["servings"] = servings
    recipe["nutrition"]["serving_basis"] = basis
    view = preview.build_recipe_preview({"url": URL, "options": {"nutrition_mode": "whole_recipe" if available == "per_serving" else "per_serving"}})["recipe"]
    assert view["nutrition_modes"] == [available]
    assert view["nutrition_mode"] == available
    assert "serving count" in view["nutrition_notice"]


def test_nutrition_does_not_scale_unknown_basis_or_nonnumeric_amounts(recipe):
    recipe["nutrition"].update(serving_basis="per 100 g", calories="200 kcal")
    view = preview.build_recipe_preview({"url": URL, "options": {"scale": 3, "nutrition_mode": "whole_recipe"}})["recipe"]
    assert view["nutrition_modes"] == []
    assert view["nutrition_basis"] == "per 100 g"
    assert view["nutrition"][0]["value"] == "200 kcal"
    recipe["nutrition"].update(serving_basis="per serving", fat="trace", sodium="<1 mg")
    view = preview.build_recipe_preview({"url": URL, "options": {"scale": .5, "nutrition_mode": "whole_recipe"}})["recipe"]
    values = {row["key"]: row["value"] for row in view["nutrition"]}
    assert values["calories"] == "400 kcal"
    assert values["fat"] == "Not converted (saved: trace)"
    assert values["sodium"] == "<2 mg"


def test_nutrition_uses_base_servings_and_rejects_invalid_mode(recipe):
    recipe.update(servings="8 servings", scaling={"base_servings": "4 servings", "selected_multiplier": 2})
    recipe["nutrition"]["serving_basis"] = "whole recipe"
    result = preview.build_recipe_preview({"url": URL, "options": {"scale": 3}})["recipe"]
    assert result["nutrition"][0]["value"] == "50 kcal"
    with pytest.raises(preview.RecipePreviewError):
        preview.build_recipe_preview({"url": URL, "options": {"nutrition_mode": "anything"}})


def test_nutrition_groups_keep_zero_unknowns_and_missing_macros_distinct(recipe):
    recipe["nutrition"] = {"serving_basis": "per serving", "calories": "240 kcal", "sugar": 0,
                           "sodium": "330 mg", "vitamin_c": "2 mg", "saturated_fat": "7 g",
                           "other": [{"label": "Custom nutrient", "value": "8 mg"}]}
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"scale": 2, "show_image": False}})
    summary = response["recipe"]["nutrition_summary"]
    assert [row["value"] for row in summary["primary"]] == ["240 kcal", "", "", ""]
    grouped = {group["label"]: group["rows"] for group in summary["groups"]}
    assert grouped["Carbohydrate details"][0]["value"] == "0"
    assert {row["label"] for row in grouped["Vitamins & minerals"]} == {"Sodium", "Vitamin C"}
    assert grouped["Other nutrients"][0]["value"] == "8 mg"
    card = shared_preview_card(response["recipe"])
    assert "Not provided" in card.select_one(".recipe-preview-nutrient-grid").get_text()
    assert "Fats & cholesterol" in card.get_text()
    assert "Vitamin C" in card.select_one(".recipe-preview-print-nutrition").get_text()
    assert "Custom nutrient" in card.select_one(".recipe-preview-print-nutrition").get_text()
    assert "Nutrition is not recalculated for ingredient choices." in card.get_text()


@pytest.mark.parametrize("scale", [0, -1, "invalid", float("inf"), 1001])
def test_invalid_scale_is_rejected(recipe, scale):
    with pytest.raises(preview.RecipePreviewError):
        preview.build_recipe_preview({"url": URL, "options": {"scale": scale}})


def test_pdf_visibility_text_size_and_escaping_preserve_projection(recipe, monkeypatch):
    captured = capture_pdf_export(monkeypatch, {
        "url": URL, "recipe": {"recipe_title": "<script>unsafe</script>"},
        "options": {"scale": 2, "show_image": False, "show_nutrition": False, "text_size": "larger"},
    })
    model, options = captured["arguments"]
    assert options["text_size"] == "larger"
    assert options["show_image"] is options["show_nutrition"] is False
    card = shared_preview_card(model)
    assert not card.find("script")
    assert card.h1.get_text() == "<script>unsafe</script>"
    assert card.select_one(".recipe-preview-choice-title").get_text() == "source butter"
    selected_text = " ".join(row.get_text() for row in selected_ingredients(card))
    assert all(value in selected_text for value in ("whisked", "room temperature", "unsalted butter"))
    assert model["nutrition"]
    assert "200 kcal" in card.select_one(".recipe-preview-print-nutrition").get_text()


@pytest.mark.parametrize("enabled", [True, False])
def test_print_bundle_info_controls_export_without_changing_projection(recipe, monkeypatch, enabled):
    response, resolved = preview.prepare_recipe_preview({
        "url": URL, "options": {"show_image": False, "print_bundle_info": enabled},
    })
    assert response["options"]["print_bundle_info"] is enabled
    assert "unsalted butter" in [row["ingredient"] for row in resolved["ingredients"]]
    assert response["recipe"]["ingredient_groups"][1]["items"]
    captured = capture_pdf_export(monkeypatch, {"url": URL, "options": response["options"]})
    model, options = captured["arguments"]
    assert options["print_bundle_info"] is enabled
    card = shared_preview_card(model)
    assert card.select_one(".recipe-preview-choice-title").get_text() == "source butter"
    assert "room temperature" in card.get_text()
    assert "unsalted butter" in card.select_one('.recipe-preview-choice-option[data-selected="true"]').get_text()


def test_print_metadata_uses_saved_and_draft_categories(recipe):
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"show_image": False}})
    view = response["recipe"]
    assert (view["course"], view["cuisine"], view["author"]) == ("Side Dish", "American", "Test cook")
    card = shared_preview_card(view)
    assert card.select_one('[data-field="course"] .recipe-preview-metadata-value').get_text() == "Side Dish"
    assert card.select_one('[data-field="cuisine"] .recipe-preview-cuisine').get_text() == "American"
    assert card.select_one('[data-field="author"] .recipe-preview-metadata-value').get_text() == "Test cook"
    children = [node.get("class") for node in card.find_all(recursive=False)]
    assert children.index(["recipe-preview-metrics"]) < children.index(["recipe-preview-print-metadata"]) < children.index(["recipe-preview-columns"])
    response, resolved = preview.prepare_recipe_preview({"url": URL, "recipe": {
        "course": ["Side <Dish>", "Lunch"], "cuisine": "French & Italian", "author": [{"name": "A & B"}],
    }, "options": {"show_image": False}})
    card = shared_preview_card(response["recipe"])
    assert card.select_one('[data-field="course"] .recipe-preview-metadata-value').get_text() == "Side <Dish>, Lunch"
    assert card.select_one('[data-field="cuisine"] .recipe-preview-cuisine').get_text() == "French & Italian"
    assert card.select_one('[data-field="author"] .recipe-preview-metadata-value').get_text() == "A & B"
    assert not card.find("dish")


def test_print_metadata_omits_missing_values(recipe):
    for key in ("author", "meal_type", "cuisine_tags"):
        recipe.pop(key)
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"show_image": False}})
    assert not any(response["recipe"][key] for key in ("course", "cuisine", "author"))
    assert not shared_preview_card(response["recipe"]).select_one(".recipe-preview-print-metadata")


def test_print_metadata_includes_all_draft_classifications(recipe):
    response, resolved = preview.prepare_recipe_preview({"url": URL, "recipe": {
        "meal_type": "Dinner", "cuisine_tags": ["American", "French"], "cuisine": "American",
        "dietary_preferences": ["Dairy Free"], "dietary_preference": "Dairy Free",
        "main_ingredient": "Vegetarian", "cooking_method": "Oven Baked", "occasion": "Family Dinner",
        "custom_categories": "Comfort Food, Casserole; Vegetarian Side", "custom_tags": ["Casserole", "Easy & <quick>"],
        "prep_time_group": "Under 1 hour",
    }, "options": {"show_image": False}})
    view = response["recipe"]
    assert view["cuisine"] == "American, French"
    assert view["dietary_preferences"] == "Dairy Free"
    assert view["custom_tags"] == "Comfort Food, Casserole, Vegetarian Side, Easy & <quick>"
    card = shared_preview_card(view)
    for expected in ("Course: Dinner", "Dietary Preferences: Dairy Free",
                     "Main Ingredient: Vegetarian", "Cooking Method: Oven Baked", "Occasion: Family Dinner",
                     "Custom Tags: Comfort Food, Casserole, Vegetarian Side, Easy & <quick>", "Prep Time Group: Under 1 hour"):
        label, value = expected.split(": ", 1)
        row = next(row for row in card.select(".recipe-preview-metadata-field") if row.select_one(".recipe-preview-metadata-label").get_text() == label)
        assert row.select_one(".recipe-preview-metadata-value").get_text() == value
    assert [item["label"] for item in view["cuisine_items"]] == ["American", "French"]
    assert [node.get_text() for node in card.select('[data-field="cuisine"] .recipe-preview-cuisine')] == ["American", "French"]
    assert not card.find("quick")


def test_cuisine_flags_use_bundled_svg_in_projection_and_pdf(recipe):
    response, resolved = preview.prepare_recipe_preview({"url": URL, "options": {"show_image": False}})
    item, = response["recipe"]["cuisine_items"]
    assert item["label"] == item["source_label"] == "American"
    assert item["icon"] == "flag:us"
    assert item["glyph"] == ""
    assert item["image_url"].startswith("data:image/svg+xml;base64,")
    svg = ElementTree.fromstring(b64decode(item["image_url"].split(",", 1)[1]))
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert svg.get("viewBox") == "0 0 640 480"
    assert len(svg) > 0
    card = shared_preview_card(response["recipe"])
    image = card.select_one('[data-field="cuisine"] .recipe-preview-cuisine img')
    assert image["src"] == item["image_url"]
    assert image["alt"] == ""


@pytest.mark.parametrize("code", ["US", "GB", "PE"])
def test_exported_flag_svg_keeps_all_internal_artwork_references(code):
    svg = ElementTree.fromstring(b64decode(preview.preview_flag_image_url(code).split(",", 1)[1]))
    identifiers = {element.get("id") for element in svg.iter() if element.get("id")}
    references = set()
    for element in svg.iter():
        for attribute, value in element.attrib.items():
            if attribute.endswith("href"):
                assert value.startswith("#")
                references.add(value[1:])
            references.update(re.findall(r"url\(#([^)]+)\)", value))
    assert references <= identifiers


def test_cuisine_icons_honor_workspace_overrides_aliases_and_explicit_clear(recipe, monkeypatch):
    monkeypatch.setattr(preview.cuisine_category_service, "cuisine_category_registry_payload", lambda: {
        "categories": [
            {"value": "American", "icon": "", "aliases": []},
            {"value": "House & <special>", "icon": "flag:ca", "aliases": ["Old House"]},
            {"value": "Fusion", "icon": "symbol:globe", "aliases": []},
        ],
    })
    response, resolved = preview.prepare_recipe_preview({"url": URL, "recipe": {
        "cuisine_tags": ["American", "Old House", "Fusion"],
    }, "options": {"show_image": False}})
    american, custom, fusion = response["recipe"]["cuisine_items"]
    assert american["icon"] == american["image_url"] == american["glyph"] == ""
    assert custom["source_label"] == "Old House"
    assert custom["label"] == "House & <special>"
    assert custom["icon"] == "flag:ca" and custom["image_url"]
    assert fusion["glyph"] == "\U0001f30d" and not fusion["image_url"]
    card = shared_preview_card(response["recipe"])
    cuisine_nodes = card.select('[data-field="cuisine"] .recipe-preview-cuisine')
    assert cuisine_nodes[0].get_text() == "American"
    assert not cuisine_nodes[0].find("img")
    assert cuisine_nodes[1].get_text() == "House & <special>"
    assert not card.find("special")


def test_cuisine_icons_support_legacy_labels_without_guessing_unknown_regions(recipe):
    response = preview.build_recipe_preview({"url": URL, "recipe": {
        "cuisine_tags": ["\U0001f1fa\U0001f1f8 American", "flag:fr French", "Mediterranean", "Mystery <style>"],
    }})
    items = response["recipe"]["cuisine_items"]
    assert [item["label"] for item in items] == ["American", "French", "Mediterranean", "Mystery <style>"]
    assert [item["icon"] for item in items] == ["flag:us", "flag:fr", "", ""]
    assert all(item["image_url"] for item in items[:2])
    assert not any(item["image_url"] for item in items[2:])


def test_print_classifications_support_category_fallback_and_explicit_clear(recipe):
    recipe["categories"] = {"main_ingredient": "Vegetarian", "cooking_method": "Oven Baked", "occasion": "Family Dinner"}
    response = preview.build_recipe_preview({"url": URL})
    assert response["recipe"]["main_ingredient"] == "Vegetarian"
    response = preview.build_recipe_preview({"url": URL, "recipe": {"main_ingredient": "", "cuisine_tags": []}})
    assert response["recipe"]["main_ingredient"] == ""
    assert response["recipe"]["cuisine"] == ""


@pytest.mark.parametrize("options, included", [({}, False), ({"print_notes": False}, False), ({"print_notes": True}, True)])
def test_print_notes_only_exports_saved_notes(recipe, monkeypatch, options, included):
    recipe["recipe_notes"] = [{"heading": "Tips <saved>", "items": ["Chill & cover before baking."]}]
    response, resolved = preview.prepare_recipe_preview({"url": URL, "recipe": {
        "recipe_notes": [{"heading": "Draft", "items": ["Unsaved draft note."]}],
    }, "options": {"show_image": False, **options}})
    assert response["recipe"]["recipe_notes"][0]["heading"] == "Draft"
    captured = capture_pdf_export(monkeypatch, {"url": URL, "recipe": {
        "recipe_notes": [{"heading": "Draft", "items": ["Unsaved draft note."]}],
    }, "options": response["options"]})
    model, print_options = captured["arguments"]
    assert print_options["print_notes"] is included
    card = shared_preview_card(model)
    notes = card.select_one(".recipe-preview-print-notes")
    assert notes.h3.get_text() == "Tips <saved>"
    assert notes.li.get_text() == "Chill & cover before baking."
    assert "Unsaved draft note." not in notes.get_text()
    assert not notes.find("saved")
    assert card.select_one(".recipe-preview-nutrition").find_next("section", class_="recipe-preview-print-notes") is notes


def test_save_notes_route_preserves_recipe_and_checks_conflicts(recipe, monkeypatch):
    original = deepcopy(recipe)
    def save(_url, updated):
        recipe.clear()
        recipe.update(deepcopy(updated))
    monkeypatch.setattr(preview.recipe_edit_service, "save_recipe_output", save)
    app = Flask(__name__)
    app.register_blueprint(recipe_bp)
    client = app.test_client()
    notes = [{"heading": "My tips", "items": ["Less sugar next time."]}]
    response = client.patch('/api/recipe/notes', json={"url": URL, "recipe_notes": notes, "expected_notes": []})
    assert response.status_code == 200
    assert recipe["recipe_notes"] == notes
    assert all(recipe[key] == value for key, value in original.items())
    stale = client.patch('/api/recipe/notes', json={"url": URL, "recipe_notes": [], "expected_notes": []})
    assert stale.status_code == 409
    assert recipe["recipe_notes"] == notes
    assert client.patch('/api/recipe/notes', json={"url": "missing", "recipe_notes": []}).status_code == 404
    assert client.patch('/api/recipe/notes', json={"url": URL, "recipe_notes": "invalid"}).status_code == 400
    cleared = client.patch('/api/recipe/notes', json={"url": URL, "recipe_notes": [], "expected_notes": notes})
    assert cleared.status_code == 200
    assert recipe["recipe_notes"] == []
    def fail_save(*_args):
        raise OSError("storage unavailable")
    monkeypatch.setattr(preview.recipe_edit_service, "save_recipe_output", fail_save)
    failed = client.patch('/api/recipe/notes', json={"url": URL, "recipe_notes": notes})
    assert failed.status_code == 503
    assert recipe["recipe_notes"] == []


def test_pdf_export_is_ephemeral_and_does_not_update_persisted_archive(recipe, monkeypatch):
    seen = capture_pdf_export(monkeypatch, {"url": URL, "options": {"scale": 2}})
    assert seen["content"].read().startswith(b"%PDF-")
    assert seen["title"] == "Preview fixture"
    assert not Path(seen["path"]).exists()
    assert [row["quantity"] for row in seen["expected_recipe"]["ingredients"]] == ["4", "1/2", None]
    assert "generated_pdf_path" not in recipe
    assert seen["print_options"]["paperHeight"] == 11
    assert seen["print_options"]["scale"] == 1
    assert seen["print_options"]["preferCSSPageSize"] is True
    assert seen["print_options"]["displayHeaderFooter"] is False
    assert all(seen["print_options"][f"margin{edge}"] == 0 for edge in ("Top", "Bottom", "Left", "Right"))
    assert seen["preserve_source_styles"] is True
    assert seen["asset_wait"]


def test_pdf_shell_embeds_live_styles_with_no_duplicate_recipe_template(recipe):
    response, resolved = preview.prepare_recipe_preview({"url": URL})
    shell = BeautifulSoup(preview.build_recipe_preview_pdf_html(response["recipe"], resolved, response["options"]), "html.parser")
    styles = shell.select("style[data-preview-stylesheet]")
    assert [style["data-preview-stylesheet"] for style in styles] == ["app.css", "ingredient-choices.css", "recipe-preview.css"]
    for style in styles:
        assert style.string == (STATIC / "css" / style["data-preview-stylesheet"]).read_text(encoding="utf-8")
    assert shell.select_one("body.recipe-preview-active #appContent #recipePreviewPage .recipe-preview-card")
    assert not shell.select_one(".recipe-preview-card").contents
    assert not shell.find("script")
    assert not shell.body.find("style")
    assert "default-src 'none'" in shell.find("meta", attrs={"http-equiv": "Content-Security-Policy"})["content"]


def test_pdf_executes_only_repository_renderer_with_authoritative_projection(recipe, monkeypatch):
    payload = {"url": URL, "recipe": {"recipe_title": "Draft <title>", "instructions": [{"instruction": "Serve carefully."}]},
               "options": {"scale": 3, "text_size": "smaller"},
               "html": '<script>client_injection()</script>', "renderer_source": "client_injection()",
               "model": {"title": "Client forged projection", "ingredients": []}}
    original = deepcopy(payload)
    captured = capture_pdf_export(monkeypatch, payload)
    model, options = captured["arguments"]
    assert captured["script"].startswith((STATIC / "js" / "recipe-preview-renderer.js").read_text(encoding="utf-8"))
    assert "client_injection" not in captured["script"]
    assert "client_injection" not in captured["html"]
    assert model["title"] == "Draft <title>"
    assert [row["quantity"] for row in model["ingredients"]] == ["6", "3/4", None]
    assert model["instructions"][0]["instruction"] == "Serve carefully."
    assert options["text_size"] == "smaller"
    assert not BeautifulSoup(captured["html"], "html.parser").find("script")
    assert BeautifulSoup(captured["html"], "html.parser").title.get_text() == "Draft <title>"
    assert payload == original


def test_pdf_embeds_saved_cover_and_ignores_client_cover_path(recipe, monkeypatch):
    recipe["cover_image"] = {"path": "saved-cover.png", "url": "https://example.test/saved-cover.png"}
    covers = []
    def embed(cover):
        covers.append(deepcopy(cover))
        return "data:image/png;base64,c2F2ZWQ="
    monkeypatch.setattr(preview.recipe_extract_service, "recipe_pdf_cover_image_src", embed)
    captured = capture_pdf_export(monkeypatch, {"url": URL, "recipe": {
        "cover_image": {"path": "C:/private.txt", "url": "file:///C:/private.txt"},
    }})
    assert covers == [{"path": "saved-cover.png", "mime_type": None}]
    model, _options = captured["arguments"]
    assert model["image_url"] == "data:image/png;base64,c2F2ZWQ="
    assert shared_preview_card(model).select_one("[data-preview-image] img")["src"] == model["image_url"]


def test_pdf_preserves_live_remote_cover_precedence(recipe, monkeypatch):
    recipe["cover_image"] = {"url": "https://example.test/live.png", "src": "https://example.test/other.png"}
    monkeypatch.setattr(preview.recipe_extract_service, "recipe_pdf_cover_image_src",
                        lambda _cover: pytest.fail("URL covers must keep the live preview URL"))
    captured = capture_pdf_export(monkeypatch, {"url": URL})
    model, _options = captured["arguments"]
    assert model["image_url"] == "https://example.test/live.png"


def test_pdf_missing_saved_cover_does_not_switch_to_remote_fallback(recipe, monkeypatch):
    recipe["cover_image"] = {"path": "missing.png", "url": "https://example.test/other.png"}
    monkeypatch.setattr(preview.recipe_extract_service, "recipe_pdf_cover_image_src", lambda _cover: "")
    model, _options = capture_pdf_export(monkeypatch, {"url": URL})["arguments"]
    assert model["image_url"] == ""
    assert not shared_preview_card(model).select_one("[data-preview-image] img")


def test_projection_resolves_workspace_ingredient_type_names_for_all_bundles(recipe, monkeypatch):
    monkeypatch.setattr(preview.ingredient_type_service, "ingredient_type_registry_payload", lambda: {"types": [
        {"id": "garnish", "value": "garnish", "name": "Finishing <touch>", "seeded": True},
        {"id": "house-spice", "value": "house-spice", "name": "House Spice", "seeded": False},
    ]})
    recipe["ingredients"][0]["section"] = "Finishing <touch>"
    recipe["ingredients"][1]["substitutions"][0]["ingredient_type"] = "house-spice"
    recipe["ingredients"][1]["substitutions"][2]["optional"] = True
    view = preview.build_recipe_preview({"url": URL})["recipe"]
    assert (view["ingredients"][0]["ingredient_type_key"], view["ingredients"][0]["ingredient_type_label"]) == ("garnish", "Finishing <touch>")
    assert (view["ingredients"][1]["ingredient_type_key"], view["ingredients"][1]["ingredient_type_label"]) == ("house spice", "House Spice")
    assert view["ingredient_groups"][1]["options"][1]["items"][0]["ingredient_type_key"] == "optional"
    card = shared_preview_card(view)
    assert card.select_one('[data-preview-ingredient-type="garnish"] .recipe-preview-ingredient-type').get_text() == "Finishing <touch>"
    assert card.select_one('[data-preview-ingredient-type="house spice"] .recipe-preview-ingredient-type').get_text() == "House Spice"
    assert not card.find("touch")


def test_routes_return_projection_and_pdf_and_validation_errors(recipe, monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(recipe_bp)
    client = app.test_client()
    response = client.post("/api/recipe_preview", json={"url": URL, "options": {"scale": 2}})
    assert response.status_code == 200
    assert response.json["recipe"]["servings"] == "8 servings"
    assert client.post("/api/recipe_preview", json={"url": "missing"}).status_code == 404
    assert client.post("/api/recipe_preview", json={"url": URL, "options": {"text_size": "giant"}}).status_code == 400
    def render(_url, _html, _source, path, **_kwargs):
        path.write_bytes(b"%PDF-1.4 route attachment")
    monkeypatch.setattr(preview.recipe_extract_service, "write_recipe_page_pdf", render)
    exported = client.post("/api/recipe_preview/pdf", json={"url": URL})
    assert exported.status_code == 200
    assert exported.mimetype == "application/pdf"
    assert "attachment" in exported.headers["Content-Disposition"]
    assert 'filename="Preview fixture - AI Pantry.pdf"' in exported.headers["Content-Disposition"]
    assert exported.data.startswith(b"%PDF-")


def test_pdf_route_preserves_recipe_name_spaces_and_removes_filename_path_characters(recipe, monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(recipe_bp)
    def render(_url, _html, _source, path, **_kwargs):
        path.write_bytes(b"%PDF-1.4 route attachment")
    monkeypatch.setattr(preview.recipe_extract_service, "write_recipe_page_pdf", render)
    exported = app.test_client().post("/api/recipe_preview/pdf", json={
        "url": URL, "recipe": {"recipe_title": 'Sweet / Corn: Bake? <Family> "Favorite"'},
    })
    assert exported.status_code == 200
    filename = exported.headers["Content-Disposition"]
    assert "Sweet" in filename and "Corn" in filename and "Family" in filename
    assert " - AI Pantry.pdf" in filename
    assert not any(char in filename.split("filename=", 1)[1].strip('"') for char in '/\\:*?<>|')
