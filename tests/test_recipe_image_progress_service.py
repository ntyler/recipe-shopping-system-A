import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PushShoppingList.app import create_app
from PushShoppingList.services import recipe_image_progress_service as service


class RecipeImageProgressServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch.object(
            service,
            "PROGRESS_FILE",
            Path(self.temp_dir.name) / "recipe_image_progress.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_tracks_running_and_finished_step_image(self):
        service.start_recipe_image_progress("step", "manual://recipe/demo", "1")

        running = service.load_recipe_image_progress("manual://recipe/demo")

        self.assertTrue(running["active"])
        self.assertEqual(running["items"][0]["state"], "running")
        self.assertEqual(running["items"][0]["step_number"], "1")

        service.finish_recipe_image_progress(
            "step",
            "manual://recipe/demo",
            "1",
            ok=True,
            image_url="/static/generated/recipe_steps/demo.png",
            generated_at="2026-05-31T00:00:00+00:00",
        )

        finished = service.load_recipe_image_progress("manual://recipe/demo")

        self.assertFalse(finished["active"])
        self.assertEqual(finished["items"][0]["state"], "done")
        self.assertEqual(
            finished["items"][0]["image_url"],
            "/static/generated/recipe_steps/demo.png",
        )

    def test_filters_progress_by_recipe_url(self):
        service.start_recipe_image_progress("equipment", "manual://recipe/one", "2")
        service.start_recipe_image_progress("step", "manual://recipe/two", "1")

        progress = service.load_recipe_image_progress("manual://recipe/one")

        self.assertEqual(len(progress["items"]), 1)
        self.assertEqual(progress["items"][0]["kind"], "equipment")
        self.assertEqual(progress["items"][0]["equipment_index"], "2")

    def test_idle_endpoint_does_not_create_progress_file(self):
        app = create_app()

        with app.test_client() as client:
            response = client.get("/api/recipe_image_progress")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["active"])
        self.assertFalse(service.PROGRESS_FILE.exists())


if __name__ == "__main__":
    unittest.main()
