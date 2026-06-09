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
