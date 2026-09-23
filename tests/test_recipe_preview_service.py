"""Preview and PDF must share draft-safe choice and scaling semantics."""

from copy import deepcopy
from pathlib import Path

from flask import Flask
import pytest

from PushShoppingList.routes.recipe_routes import recipe_bp
from PushShoppingList.services import recipe_preview_service as preview


URL = "https://example.test/preview-fixture"


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
    html = preview.build_recipe_preview_pdf_html(view, resolved, response["options"])
    assert "Cookbook: Weeknight &amp; weekend" in html
    assert "Section: Sides" in html
    assert f'Menu Price (optional): {expected or "Not set"}' in html
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


@pytest.mark.parametrize("basis, calories", [("per serving", "200 kcal"), ("full recipe", "600 kcal")])
def test_nutrition_basis_controls_scaling_without_inventing_data(recipe, basis, calories):
    recipe["nutrition"]["serving_basis"] = basis
    result = preview.build_recipe_preview({"url": URL, "options": {"scale": 3}})["recipe"]
    assert result["nutrition_basis"] == basis
    assert {row["key"]: row["value"] for row in result["nutrition"]}["calories"] == calories
    assert {row["key"]: row["value"] for row in result["nutrition"]}["sugar"] == "0"
    del recipe["nutrition"]["serving_basis"]
    unknown = preview.build_recipe_preview({"url": URL})["recipe"]
    assert unknown["nutrition_basis"] == "Serving basis not specified"


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
    html = preview.build_recipe_preview_pdf_html(response["recipe"], resolved, response["options"])
    assert "Not provided" in html
    assert "Fats &amp; cholesterol" in html
    assert "Vitamin C" in html
    assert "Custom nutrient" in html
    assert "Nutrition is not recalculated for ingredient choices." in html


@pytest.mark.parametrize("scale", [0, -1, "invalid", float("inf"), 1001])
def test_invalid_scale_is_rejected(recipe, scale):
    with pytest.raises(preview.RecipePreviewError):
        preview.build_recipe_preview({"url": URL, "options": {"scale": scale}})


def test_pdf_visibility_text_size_and_escaping_preserve_projection(recipe, monkeypatch):
    monkeypatch.setattr(preview.recipe_extract_service, "format_video_recipe_title_image_for_pdf", lambda _recipe: '<figure class="title-image"><img src="data:image/png;base64,AA"></figure>')
    response, resolved = preview.prepare_recipe_preview({
        "url": URL, "recipe": {"recipe_title": "<script>unsafe</script>"},
        "options": {"scale": 2, "show_image": False, "show_nutrition": False, "text_size": "larger"},
    })
    html = preview.build_recipe_preview_pdf_html(response["recipe"], resolved, response["options"])
    assert "<script>unsafe</script>" not in html
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert '<figure class="title-image">' not in html
    assert "<h2>Nutrition" not in html
    assert "font: 13pt/1.5" in html
    assert "source butter" not in html
    assert "whisked" in html
    assert "room temperature" in html
    assert "unsalted butter" in html
    assert response["recipe"]["nutrition"]
    response["options"].update(show_image=True, show_nutrition=True)
    visible = preview.build_recipe_preview_pdf_html(response["recipe"], resolved, response["options"])
    assert '<figure class="title-image">' in visible
    assert "Nutrition <small>per serving" in visible
    assert "200 kcal" in visible


def test_pdf_export_is_ephemeral_and_does_not_update_persisted_archive(recipe, monkeypatch):
    seen = {}
    def render(url, html, _source, path, **kwargs):
        seen.update(path=path, html=html, expected=kwargs["expected_recipe"], print_options=kwargs["print_options"])
        path.write_bytes(b"%PDF-1.4 test attachment")
        return path
    monkeypatch.setattr(preview.recipe_extract_service, "write_recipe_page_pdf", render)
    content, title = preview.create_recipe_preview_pdf({"url": URL, "options": {"scale": 2}})
    assert content.read().startswith(b"%PDF-")
    assert title == "Preview fixture"
    assert not Path(seen["path"]).exists()
    assert [row["quantity"] for row in seen["expected"]["ingredients"]] == ["4", "1/2", None]
    assert "generated_pdf_path" not in recipe
    assert seen["print_options"]["paperHeight"] == 11
    assert seen["print_options"]["scale"] == 1


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
    assert exported.data.startswith(b"%PDF-")
