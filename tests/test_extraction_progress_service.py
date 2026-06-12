from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PushShoppingList.services import extraction_progress_service as service


def test_menu_progress_status_tracks_boolean_recipe_checklist():
    with TemporaryDirectory() as temp_dir, patch.object(
        service,
        "PROGRESS_FILE",
        Path(temp_dir) / "extract_progress.json",
    ):
        urls = ["https://example.com/menu"]
        service.start_progress(urls, job_id="menu-job", extraction_mode="menu_extract")
        progress = service.set_url_menu_recipes(
            "menu-job",
            urls,
            0,
            [
                {
                    "recipe_id": "spring-roll",
                    "recipe_url": "https://example.com/menu?menu_item=spring-roll",
                    "recipe_name": "Spring Roll",
                    "checklist": {
                        "recipe_extracted": True,
                        "recipe_information": True,
                        "ingredients": True,
                        "equipment": True,
                        "instructions": True,
                        "nutrition": True,
                        "food_review_applied": False,
                        "estimate_per_serving": False,
                    },
                    "messages": {
                        "food_review_applied": "Skipped - no matching rule",
                        "estimate_per_serving": "Ready to run",
                    },
                },
            ],
        )

        recipe = progress["urls"][0]["menu_recipes"][0]
        assert recipe["checklist"]["recipe_extracted"] is True
        assert recipe["checklist"]["estimate_per_serving"] is False
        assert all(isinstance(value, bool) for value in recipe["checklist"].values())
        assert all(isinstance(value, bool) for value in recipe["running"].values())

        progress = service.update_menu_recipe_step(
            "menu-job",
            recipe_id="spring-roll",
            step="estimate_per_serving",
            checked=False,
            running=True,
            message="Updating...",
            error="",
        )
        recipe = progress["urls"][0]["menu_recipes"][0]
        assert recipe["checklist"]["estimate_per_serving"] is False
        assert recipe["running"]["estimate_per_serving"] is True
        assert recipe["messages"]["estimate_per_serving"] == "Updating..."

        progress = service.update_menu_recipe_step(
            "menu-job",
            recipe_id="spring-roll",
            step="estimate_per_serving",
            checked=True,
            running=False,
            message="Complete",
            error="",
        )
        recipe = progress["urls"][0]["menu_recipes"][0]
        assert recipe["checklist"]["estimate_per_serving"] is True
        assert recipe["running"]["estimate_per_serving"] is False
        assert recipe["messages"]["estimate_per_serving"] == "Complete"
        assert recipe["errors"] == {}
