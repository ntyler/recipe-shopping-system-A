from copy import deepcopy
from pathlib import Path

from PushShoppingList import app as app_module
from PushShoppingList.app import create_app
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import recipe_ai_quality_service


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_quality_report_projects_explicit_saved_scores_and_provenance(monkeypatch):
    url = "https://example.com/menu/item"
    raw = {
        "source_url": url,
        "source_type": "restaurant_menu",
        "recipe_title": "Traceable Soup",
        "ai_confidence_score": 0.86,
        "source_quality_score": 92,
        "extraction_confidence_score": 88,
        "nutrition_confidence_score": 61,
        "image_confidence_score": 98,
        "restaurant_information_confidence": 84,
        "ai_inferred_fields": ["instructions", "nutrition"],
        "verified_fields": ["recipe_title", "source_url"],
        "extracted_fields": ["recipe_title", "menu_price", "source_url"],
        "field_provenance": {
            "recipe_title": {
                "status": "verified",
                "source_type": "Restaurant Menu URL",
                "source_name": "Dinner Menu",
                "source_url": url,
                "confidence": 0.97,
                "updated_at": "2026-07-14T12:00:00Z",
            },
            "instructions": {
                "status": "ai_generated",
                "source_type": "AI Generation",
                "confidence": 0.73,
            },
        },
        "ingredients": [{
            "ingredient": "broth",
            "original_text": "2 cups broth",
            "normalized_name": "broth",
            "quantity": "2",
            "unit": "cups",
            "store_section": "CANNED",
            "ingredient_id": "ingredient-1",
            "master_ingredient_name": "Broth",
            "match_confidence": 0.95,
        }],
        "instructions": [{"instruction": "Simmer.", "confidence": 0.73}],
        "nutrition": [{"nutrient": "Calories", "value": "100"}],
        "cover_image": {"url": "https://cdn.example.com/soup.jpg", "source": "downloaded"},
        "restaurant_name": "Example Cafe",
        "restaurant_id": "restaurant-1",
        "restaurant_website_url": "https://example.com",
        "source_menu_url": "https://example.com/menu",
        "restaurant_address": "1 Main St",
        "restaurant_phone": "317-555-0100",
        "cookbook_id": "cookbook-1",
        "cookbook_name": "Soups",
        "updated_at": "2026-07-14T12:00:00Z",
    }
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_output", lambda _url: deepcopy(raw))
    monkeypatch.setattr(
        recipe_ai_quality_service.recipe_edit_service,
        "load_editable_recipe",
        lambda _url: (_ for _ in ()).throw(AssertionError("report reads must not invoke editor backfills")),
    )
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_menu_metadata", lambda _raw: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_cover_image", lambda _url, recipe, _meta: recipe.get("cover_image", {}))
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_pdf_info", lambda _url, _raw: {})

    report = recipe_ai_quality_service.build_recipe_ai_quality_report(url)

    assert report["overall_confidence"] == 86
    assert report["confidence_label"] == "Good"
    assert report["categories"]["source_reliability"]["score"] == 92
    assert report["categories"]["extraction_accuracy"]["score"] == 88
    assert report["categories"]["ingredients"]["score"] == 95
    assert report["categories"]["instructions"]["score"] == 73
    assert report["categories"]["nutrition"]["score"] == 61
    assert report["categories"]["image"]["score"] == 98
    assert report["categories"]["restaurant"]["score"] == 84
    assert "restaurant menu" in report["summary"]
    assert "instructions" in report["summary"]
    assert {item["label"] for item in report["field_analysis"]} == {
        "Title", "Ingredients", "Instructions", "Equipment", "Nutrition",
        "Recipe Image", "Cookbook Assignment", "Source Information", "Restaurant Information",
    }
    instruction = next(item for item in report["field_analysis"] if item["label"] == "Instructions")
    assert instruction["status"] == "generated"
    assert instruction["confidence"] == 73
    ingredient = report["ingredient_analysis"][0]
    assert ingredient["match_status"] == "Matched"
    assert ingredient["match_confidence"] == 95
    assert ingredient["matched_master_ingredient"] == "Broth"
    title_evidence = next(item for item in report["source_evidence"] if item["key"] == "recipe_title")
    assert title_evidence["source_type"] == "Restaurant Menu URL"
    assert title_evidence["confidence"] == 97
    assert report["restaurant_analysis"]["available"] is True
    assert report["image_analysis"]["available"] is True
    assert report["last_analyzed"] is None


def test_quality_report_marks_missing_scores_unavailable_without_fabricating_values(monkeypatch):
    url = "https://example.com/recipe"
    raw = {
        "source_url": url,
        "recipe_title": "Unscored Recipe",
        "ingredients": [{"ingredient": "salt"}],
    }
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_output", lambda _url: deepcopy(raw))
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_menu_metadata", lambda _raw: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_cover_image", lambda _url, _raw, _meta: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_pdf_info", lambda _url, _raw: {})

    report = recipe_ai_quality_service.build_recipe_ai_quality_report(url)

    assert report["overall_confidence"] is None
    assert report["confidence_label"] == "Unknown"
    assert report["categories"]["source_reliability"]["score"] is None
    assert report["categories"]["source_reliability"]["status"] == "unavailable"
    assert report["categories"]["ingredients"]["score"] is None
    assert "No overall AI confidence score is stored." in report["summary"]
    assert all(
        item["confidence"] is None
        for item in report["field_analysis"]
        if item["key"] not in {"source_information"}
    )


def test_safe_fixes_normalize_units_and_only_fill_missing_store_sections(monkeypatch):
    url = "https://example.com/safe-fixes"
    saved = {
        "source_url": f"  {url}  ",
        "recipe_title": "Keep this title",
        "ingredients": [
            {"ingredient": " sugar ", "quantity": " 2 ", "unit": "tbsp", "store_section": "MISC"},
            {"ingredient": " milk ", "quantity": "1", "unit": "cup", "store_section": "MY CUSTOM SECTION"},
        ],
    }
    persisted = {}
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_output", lambda _url: deepcopy(persisted.get("recipe", saved)))
    monkeypatch.setattr(
        recipe_ai_quality_service.recipe_edit_service,
        "load_editable_recipe",
        lambda _url: (_ for _ in ()).throw(AssertionError("safe fixes must not invoke editor backfills")),
    )
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_menu_metadata", lambda _raw: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_cover_image", lambda _url, _raw, _meta: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_pdf_info", lambda _url, _raw: {})
    monkeypatch.setattr(
        recipe_ai_quality_service.recipe_edit_service,
        "review_recipe_store_sections",
        lambda recipe: {
            "ok": True,
            "recipe": {
                **deepcopy(recipe),
                "ingredients": [
                    {**deepcopy(recipe["ingredients"][0]), "store_section": "BAKING", "store_section_order": 4},
                    {**deepcopy(recipe["ingredients"][1]), "store_section": "DAIRY", "store_section_order": 2},
                ],
            },
        },
    )
    monkeypatch.setattr(
        recipe_ai_quality_service.recipe_edit_service,
        "save_recipe_output",
        lambda _url, recipe: persisted.update(recipe=deepcopy(recipe)),
    )

    result = recipe_ai_quality_service.apply_recipe_ai_quality_safe_fixes(url)

    assert result["ok"] is True
    assert result["changed_count"] > 0
    assert persisted["recipe"]["source_url"] == url
    assert persisted["recipe"]["recipe_title"] == "Keep this title"
    assert persisted["recipe"]["ingredients"][0]["ingredient"] == "sugar"
    assert persisted["recipe"]["ingredients"][0]["unit"] == "tablespoon"
    assert persisted["recipe"]["ingredients"][0]["store_section"] == "BAKING"
    assert persisted["recipe"]["ingredients"][1]["store_section"] == "MY CUSTOM SECTION"
    assert any(update["field"] == "unit" and update["after"] == "tablespoon" for update in result["safe_updates"])
    assert any(update["field"] == "store_section" and update["after"] == "BAKING" for update in result["safe_updates"])


def test_quality_report_preserves_extracted_conflicting_and_stale_provenance(monkeypatch):
    url = "https://example.com/provenance"
    raw = {
        "source_url": url,
        "recipe_title": "Provenance Test",
        "extracted_fields": ["recipe_title", "ingredients"],
        "ingredients": [{"ingredient": "pepper", "source_status": "extracted"}],
        "restaurant_name": "Example Cafe",
        "field_provenance": {
            "restaurant_phone": {"status": "conflicting"},
            "restaurant_address": {"status": "stale"},
        },
        "restaurant_phone": "317-555-0100",
        "restaurant_address": "1 Main St",
    }
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_output", lambda _url: deepcopy(raw))
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_menu_metadata", lambda _raw: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "cookbook_recipe_assignment_for_url", lambda _url: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "load_recipe_ingredients", lambda: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_cover_image", lambda _url, _raw, _meta: {})
    monkeypatch.setattr(recipe_ai_quality_service.recipe_edit_service, "editable_recipe_pdf_info", lambda _url, _raw: {})

    report = recipe_ai_quality_service.build_recipe_ai_quality_report(url)

    title = next(item for item in report["field_analysis"] if item["key"] == "title")
    assert title["status"] == "extracted"
    assert report["ingredient_analysis"][0]["origin"] == "Extracted"
    restaurant = {item["key"]: item for item in report["restaurant_analysis"]["fields"]}
    assert restaurant["restaurant_phone"]["status"] == "conflicting"
    assert restaurant["restaurant_address"]["status"] == "stale"


def test_quality_report_drawer_wiring_accessibility_and_backend_routes():
    template = read_text("PushShoppingList/templates/sections/current_recipe_url_log.html")
    script = read_text("PushShoppingList/static/js/app.js")
    css = read_text("PushShoppingList/static/css/app.css")
    routes = read_text("PushShoppingList/routes/recipe_routes.py")

    assert ">AI Quality Report</button>" in template
    assert 'id="recipeEditAiAnalysisBackdrop"' in template
    assert 'aria-modal="true"' in template
    assert 'aria-describedby="recipeEditAiAnalysisSummary"' in template
    for heading in (
        "Confidence Breakdown", "Overall Summary", "Recipe Health Details", "Ingredient Analysis",
        "Source Evidence", "Restaurant Analysis", "Image Analysis", "Recommended Improvements",
    ):
        assert heading in template
    for action in ("Close", "Reanalyze Recipe", "Apply Safe Fixes"):
        assert action in template
    assert "function loadRecipeAiQualityReport(options = {})" in script
    assert "function renderRecipeAiQualityReport(report = {})" in script
    assert "function runRecipeAiQualityReportAction(button)" in script
    assert "function applyRecipeAiQualitySafeFixes(button)" in script
    assert "function applyRecipeAiQualitySafeUpdatesToEditor(updates = [])" in script
    assert 'String(control.value ?? "") !== before' in script
    assert 'Unsaved form values were preserved.' in script
    assert 'event.key === "Escape"' in script
    assert 'event.key === "Tab"' in script
    assert 'button.focus({ preventScroll: true })' in script
    assert 'fetch(`/api/recipe/ai-quality-report?url=' in script
    assert 'fetch("/api/recipe/ai-quality-report/safe-fixes"' in script
    assert 'data-ai-report-action="${escapeAttribute(action.key)}"' in script
    assert 'data-document-input-id="${CSS.escape(button.dataset.aiReportDocument || "")}"' in script
    assert '"document": "recipeEditSourcePdfPath"' in read_text("PushShoppingList/services/recipe_ai_quality_service.py")
    assert "width: clamp(520px, 42vw, 680px);" in css
    assert "height: 100dvh;" in css
    assert ".recipe-edit-ai-analysis-body {" in css
    assert "overflow-y: auto;" in css
    assert "@media (max-width: 720px)" in css
    assert '@recipe_bp.route("/api/recipe/ai-quality-report", methods=["GET"])' in routes
    assert '@recipe_bp.route("/api/recipe/ai-quality-report/safe-fixes", methods=["POST"])' in routes


def test_quality_report_http_contract(monkeypatch):
    report = {
        "overall_confidence": 86,
        "confidence_label": "Good",
        "categories": {},
        "field_analysis": [],
        "ingredient_analysis": [],
        "source_evidence": [],
        "restaurant_analysis": {},
        "image_analysis": {},
        "recommendations": [],
    }
    monkeypatch.setattr(app_module, "current_user", lambda: {"user_id": "quality-report-user", "account_status": "active"})
    monkeypatch.setattr(recipe_routes, "build_recipe_ai_quality_report", lambda url: {**report, "recipe_name": url})
    monkeypatch.setattr(
        recipe_routes,
        "apply_recipe_ai_quality_safe_fixes",
        lambda url: {"ok": True, "changed_count": 0, "report": report, "recipe": {"source_url": url}},
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/api/recipe/ai-quality-report", query_string={"url": "https://example.com/soup"})
        safe_fixes = client.post(
            "/api/recipe/ai-quality-report/safe-fixes",
            json={"url": "https://example.com/soup"},
        )

    assert response.status_code == 200
    assert response.get_json()["report"]["overall_confidence"] == 86
    assert safe_fixes.status_code == 200
    assert safe_fixes.get_json()["changed_count"] == 0


def test_client_confidence_model_does_not_guess_from_url_or_text_labels():
    script = read_text("PushShoppingList/static/js/app.js")
    value_start = script.index("function recipeEditConfidenceValue(value)")
    value_end = script.index("function recipeEditAverageConfidence", value_start)
    model_start = script.index("function recipeEditAiConfidenceModel(source = {})")
    model_end = script.index("function updateRecipeEditAiConfidenceCard", model_start)

    value_model = script[value_start:value_end]
    confidence_model = script[model_start:model_end]
    assert 'label === "high"' not in value_model
    assert "isLegitimateWebUrl" not in confidence_model
    assert "weightedSignals" not in confidence_model
    assert "const confidence = savedConfidence;" in confidence_model
