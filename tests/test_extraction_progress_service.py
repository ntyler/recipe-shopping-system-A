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


def test_legacy_progress_exposes_stable_percent_fields_and_only_success_reaches_100():
    with TemporaryDirectory() as temp_dir, patch.object(
        service,
        "PROGRESS_FILE",
        Path(temp_dir) / "extract_progress.json",
    ), patch.object(service, "send_ntfy", lambda *args, **kwargs: None):
        urls = ["https://example.com/recipe"]
        started = service.start_progress(urls, job_id="recipe-job")
        assert started["percent_complete"] == 0
        assert started["current_stage"] == "downloading"
        assert started["total_items"] == 1

        service.mark_url_running("recipe-job", urls, 0)
        extracting = service.mark_url_message(
            "recipe-job",
            urls,
            0,
            "sending webpage content to OpenAI API...",
        )
        assert extracting["percent_complete"] == 58
        assert extracting["stage_label"] == "Extracting recipe details"

        service.mark_url_failed("recipe-job", urls, 0, "download failed")
        failed = service.finish_progress("recipe-job", ok=False)
        assert failed["status"] == "failed"
        assert failed["percent_complete"] == 95

        service.start_progress(urls, job_id="successful-job")
        service.mark_url_done("successful-job", urls, 0, 12)
        complete = service.finish_progress("successful-job", ok=True)
        assert complete["status"] == "complete"
        assert complete["percent_complete"] == 100
