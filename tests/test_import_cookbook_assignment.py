from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service


ROOT = Path(__file__).resolve().parents[1]


def test_find_or_create_cookbook_reuses_existing_name():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        first = cookbook_service.find_or_create_cookbook("Nates Special Book")
        second = cookbook_service.find_or_create_cookbook("  nates   special book  ")

        data = cookbook_service.load_cookbooks()
        matching = [
            cookbook
            for cookbook in data["cookbooks"]
            if cookbook_service.normalize_text(cookbook["name"]) == "nates special book"
        ]

        assert first["id"] == second["id"]
        assert len(matching) == 1


def test_import_assignment_saves_recipe_to_selected_cookbook():
    with TemporaryDirectory() as temp_dir, patch.object(
        cookbook_service,
        "COOKBOOKS_FILE",
        Path(temp_dir) / "cookbooks.json",
    ):
        cookbook = cookbook_service.find_or_create_cookbook("Nates Special Book")

        recipe_routes.save_import_cookbook_assignment(
            "https://example.com/tacos",
            {
                "display_name": "Black Bean Tacos",
                "ingredients": ["black beans", "tortillas"],
                "servings": "4 servings",
                "level": "Easy",
                "total_time": "30 min",
                "prep_time": "10 min",
                "inactive_time": "0 min",
                "cook_time": "20 min",
            },
            cookbook,
        )

        data = cookbook_service.load_cookbooks()
        target = next(item for item in data["cookbooks"] if item["id"] == cookbook["id"])

        assert len(target["recipes"]) == 1
        assert target["recipes"][0]["name"] == "Black Bean Tacos"
        assert target["recipes"][0]["servings"] == "4 servings"
        assert target["recipes"][0]["base_servings"] == "4 servings"
        assert target["recipes"][0]["level"] == "Easy"
        assert target["recipes"][0]["total_time"] == "30 min"
        assert target["recipes"][0]["prep_time"] == "10 min"
        assert target["recipes"][0]["inactive_time"] == "0 min"
        assert target["recipes"][0]["cook_time"] == "20 min"
        assert target["recipes"][0]["sections"]["INGREDIENTS"][0]["name"] == "black beans"


def test_import_cookbook_selector_static_hooks_are_present():
    template = (ROOT / "PushShoppingList/templates/sections/enter_recipe_links.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert "Save extracted recipes to cookbook:" in template
    assert "data-import-cookbook-selector" in template
    assert "Create New Cookbook" in template
    assert "Remove cookbook assignment" in template
    assert 'formData.set("cookbook_id", destination.cookbookId || "")' in script
    assert 'cookbook_id: destination.cookbookId || ""' in script
    assert "bindImportCookbookSelector()" in script
    assert "selected_import_cookbook_from_json(data)" in routes
    assert "save_import_cookbook_assignment(url, result, cookbook)" in routes


def test_enter_recipe_links_has_four_independent_import_actions():
    template = (ROOT / "PushShoppingList/templates/sections/enter_recipe_links.html").read_text(encoding="utf-8")
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")

    assert "Import Recipe URLs" in template
    assert "Import Doc / Photo" in template
    assert "Import Recipe URLs (Menu Extract)" in template
    assert "Import Doc / Photo (Menu Extract)" in template
    assert 'data-extraction-mode="menu_extract"' in template
    assert "openRecipeMediaUpload('menu_extract')" in template
    assert 'formData.set("import_mode", normalizedImportMode)' in script
    assert 'extraction_mode: extractionMode' in script
    assert "grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));" in css
    assert ".recipe-import-action-url-menu { order: 3; }" in css
    assert ".recipe-import-action-upload-menu { order: 4; }" in css


def test_menu_recipe_progress_checklist_static_hooks_are_present():
    script = (ROOT / "PushShoppingList/static/js/app.js").read_text(encoding="utf-8")
    css = (ROOT / "PushShoppingList/static/css/app.css").read_text(encoding="utf-8")
    routes = (ROOT / "PushShoppingList/routes/recipe_routes.py").read_text(encoding="utf-8")

    assert "MENU_RECIPE_CHECKLIST_GROUPS" in script
    assert "menu-recipe-completion-check" in script
    assert "checkbox.readOnly = true" in script
    assert 'checkbox.disabled = true' in script
    assert "/api/menu_recipe_estimate_per_serving" in script
    assert "runMenuRecipeServingBasisEstimate" in script
    assert ".menu-recipe-progress-card" in css
    assert ".menu-recipe-check-badge" in css
    assert "set_url_menu_recipes" in routes
    assert "update_menu_recipe_step" in routes
    assert "menu_recipe_progress_callback" in routes


def test_menu_recipe_progress_payload_uses_boolean_checklist_and_skipped_review(monkeypatch):
    monkeypatch.setattr(
        recipe_routes,
        "load_food_rules",
        lambda: {
            "require": [],
            "avoid": [{"label": "no peanuts", "terms": ["peanut"]}],
        },
    )

    payload = recipe_routes.menu_recipe_progress_payload({
        "ok": True,
        "source_url": "https://example.com/menu?menu_item=spring-roll",
        "display_name": "Spring Roll",
        "menu_section": "Kitchen Appetizers",
        "menu_description": "Crispy veggie roll.",
        "ingredients": ["carrot", "cellophane noodle"],
        "equipment": [{"name": "skillet"}],
        "instructions": [{"instruction": "Fry until crisp."}],
        "nutrition": [{"key": "calories", "value": "180"}],
    })

    assert payload["recipe_name"] == "Spring Roll"
    assert payload["menu_section"] == "Kitchen Appetizers"
    assert payload["checklist"]["recipe_extracted"] is True
    assert payload["checklist"]["recipe_information"] is True
    assert payload["checklist"]["ingredients"] is True
    assert payload["checklist"]["equipment"] is True
    assert payload["checklist"]["instructions"] is True
    assert payload["checklist"]["nutrition"] is True
    assert payload["checklist"]["food_review_applied"] is False
    assert payload["checklist"]["estimate_per_serving"] is False
    assert all(isinstance(value, bool) for value in payload["checklist"].values())
    assert payload["messages"]["food_review_applied"] == "Skipped - no matching rule"
    assert payload["messages"]["estimate_per_serving"] == "Ready to run"


def test_menu_recipe_progress_payload_checks_food_review_only_when_rule_matches(monkeypatch):
    monkeypatch.setattr(
        recipe_routes,
        "load_food_rules",
        lambda: {
            "require": [],
            "avoid": [{"label": "no peanuts", "terms": ["peanut"]}],
        },
    )

    payload = recipe_routes.menu_recipe_progress_payload({
        "ok": True,
        "source_url": "https://example.com/menu?menu_item=satay",
        "display_name": "Satay",
        "ingredients": ["peanut sauce", "chicken"],
    })

    assert payload["checklist"]["food_review_applied"] is True
    assert payload["messages"]["food_review_applied"] == "Applied - 1 matching rule"


def test_menu_import_category_routine_only_runs_for_new_recipes(monkeypatch):
    existing_url = "https://example.com/menu?menu_item=menu-item-1-existing"
    new_url = "https://example.com/menu?menu_item=menu-item-2-new"
    categorized = []
    saved = []
    estimated = []
    progress_updates = []

    monkeypatch.setattr(recipe_routes, "load_recipe_urls", lambda: [existing_url])
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", lambda url, ingredients, result: saved.append(url))
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda url, name: None)
    monkeypatch.setattr(recipe_routes, "add_recipe_urls", lambda urls: None)
    monkeypatch.setattr(
        recipe_routes,
        "save_import_cookbook_assignment",
        lambda url, result, cookbook: {"cookbook_id": cookbook["id"], "cookbook_name": cookbook["name"]},
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment: categorized.append(url) or {"ok": True, "status": "updated"},
    )
    monkeypatch.setattr(
        recipe_routes,
        "ensure_menu_recipe_serving_basis_estimate",
        lambda url, result: estimated.append(url) or {"ok": True, "recipe_url": url, "already_complete": True},
    )
    monkeypatch.setattr(
        recipe_routes,
        "create_source_url_pdf",
        lambda url: {"ok": True, "recipe_url": url},
    )
    monkeypatch.setattr(
        recipe_routes,
        "run_generated_recipe_pdf_creation",
        lambda url, context="test": {"ok": True, "pdf_path": f"{url}.pdf"},
    )
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_routes, "sort_ingredients", lambda: None)

    result = recipe_routes.commit_menu_import_result(
        {
            "ok": True,
            "menu_extract": True,
            "recipes": [
                {
                    "ok": True,
                    "source_url": existing_url,
                    "display_name": "Existing",
                    "ingredients": ["tomato"],
                    "equipment": [{"name": "pan"}],
                    "instructions": [{"instruction": "Cook."}],
                    "nutrition": [{"key": "calories", "value": "50"}],
                },
                {
                    "ok": True,
                    "source_url": new_url,
                    "display_name": "New",
                    "ingredients": ["basil"],
                    "equipment": [{"name": "bowl"}],
                    "instructions": [{"instruction": "Mix."}],
                    "nutrition": [{"key": "calories", "value": "40"}],
                },
            ],
        },
        {"id": "cookbook-1", "name": "Dinner"},
        context="test-menu-import",
        menu_recipe_progress_callback=progress_updates.append,
    )

    assert result["ok"] is True
    assert result["created_count"] == 1
    assert result["committed_count"] == 2
    assert result["created_recipe_urls"] == [new_url]
    assert result["pdfs_generated"] == 1
    assert saved == [existing_url, new_url]
    assert categorized == [new_url]
    assert estimated == []
    assert result["serving_basis_statuses"] == [{
        "ok": False,
        "recipe_url": new_url,
        "status": "manual_ready",
        "error": "",
    }]
    assert len(progress_updates) == 1
    assert progress_updates[0][0]["checklist"]["recipe_extracted"] is True
    assert progress_updates[0][0]["checklist"]["estimate_per_serving"] is False
