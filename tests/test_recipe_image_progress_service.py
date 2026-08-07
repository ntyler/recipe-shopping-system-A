import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import recipe_image_progress_service as service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


TEST_SECRET_KEY = "recipe-image-progress-tests-only-key-2026"


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
        for target, attribute, value in (
            (storage_service, "USER_DATA_DIR", Path(self.temp_dir.name) / "users"),
            (storage_service, "GUEST_DATA_DIR", Path(self.temp_dir.name) / "guests"),
            (guest_session_service, "GUEST_DATA_DIR", Path(self.temp_dir.name) / "guests"),
            (
                guest_session_service,
                "GUEST_SESSIONS_FILE",
                Path(self.temp_dir.name) / "guest_sessions.json",
            ),
            (job_service, "JOBS_DB_PATH", Path(self.temp_dir.name) / "jobs.sqlite3"),
        ):
            path_patcher = patch.object(target, attribute, value)
            path_patcher.start()
            self.addCleanup(path_patcher.stop)
        users_patcher = patch.object(
            user_account_service,
            "USERS_FILE",
            Path(self.temp_dir.name) / "users.json",
        )
        users_patcher.start()
        self.addCleanup(users_patcher.stop)
        user_account_service.save_users({
            "users": [{
                "user_id": "image-progress-user",
                "username": "image-progress-user",
                "email": "image-progress@example.com",
                "account_status": "active",
            }],
        })

    def create_test_app(self):
        return create_app({
            "TESTING": True,
            "SHOPPING_APP_ENV": "testing",
            "SECRET_KEY": TEST_SECRET_KEY,
        })

    def write_progress_fixture(self, payload):
        service.PROGRESS_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return service.PROGRESS_FILE.read_bytes(), service.PROGRESS_FILE.stat().st_mtime_ns

    def assert_progress_file_unchanged(self, before_bytes, before_mtime_ns):
        self.assertEqual(service.PROGRESS_FILE.read_bytes(), before_bytes)
        self.assertEqual(service.PROGRESS_FILE.stat().st_mtime_ns, before_mtime_ns)

    def stale_progress_fixture(self):
        old = time.time() - service.RUNNING_STALE_SECONDS - 60
        return {
            "active": True,
            "items": [
                {
                    "key": "step|manual://recipe/stale|1",
                    "kind": "step",
                    "url": "manual://recipe/stale",
                    "target": "1",
                    "state": "running",
                    "updated_at": old,
                },
                {
                    "key": "step|manual://recipe/expired|2",
                    "kind": "step",
                    "url": "manual://recipe/expired",
                    "target": "2",
                    "state": "done",
                    "updated_at": old,
                },
            ],
            "updated_at": old,
        }

    def test_tracks_running_and_finished_step_image(self):
        self.assertFalse(service.PROGRESS_FILE.exists())
        service.start_recipe_image_progress("step", "manual://recipe/demo", "1")

        running_bytes = service.PROGRESS_FILE.read_bytes()
        running_disk = json.loads(running_bytes.decode("utf-8"))
        self.assertTrue(running_disk["active"])
        self.assertEqual(running_disk["items"][0]["state"], "running")

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

        finished_bytes = service.PROGRESS_FILE.read_bytes()
        finished_disk = json.loads(finished_bytes.decode("utf-8"))
        self.assertNotEqual(finished_bytes, running_bytes)
        self.assertFalse(finished_disk["active"])
        self.assertEqual(finished_disk["items"][0]["state"], "done")

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

    def test_tracks_image_prompt_while_running_and_finished(self):
        service.start_recipe_image_progress(
            "equipment",
            "manual://recipe/prompt",
            "2",
            image_prompt="single isolated product photo of a blender",
        )

        running = service.load_recipe_image_progress("manual://recipe/prompt")

        self.assertEqual(
            running["items"][0]["image_prompt"],
            "single isolated product photo of a blender",
        )

        service.finish_recipe_image_progress(
            "equipment",
            "manual://recipe/prompt",
            "2",
            ok=True,
            image_url="/static/generated/recipe_steps/blender.png",
            image_prompt="single isolated product photo of a blender",
        )

        finished = service.load_recipe_image_progress("manual://recipe/prompt")

        self.assertEqual(
            finished["items"][0]["image_prompt"],
            "single isolated product photo of a blender",
        )

    def test_idle_endpoint_does_not_create_progress_file(self):
        app = self.create_test_app()

        with app.test_client() as client:
            with client.session_transaction() as test_session:
                test_session["user_id"] = "image-progress-user"
            response = client.get("/api/recipe_image_progress")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["active"])
        self.assertFalse(service.PROGRESS_FILE.exists())

    def test_service_read_keeps_existing_empty_file_byte_identical(self):
        before_bytes, before_mtime_ns = self.write_progress_fixture({
            "active": False,
            "items": [],
            "updated_at": 1.0,
        })

        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("read path invoked the progress writer"),
        ):
            progress = service.load_recipe_image_progress()

        self.assertFalse(progress["active"])
        self.assertEqual(progress["items"], [])
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_service_read_compacts_stale_entries_only_in_memory(self):
        before_bytes, before_mtime_ns = self.write_progress_fixture(
            self.stale_progress_fixture()
        )

        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("read path invoked the progress writer"),
        ):
            progress = service.load_recipe_image_progress()

        self.assertFalse(progress["active"])
        self.assertEqual(len(progress["items"]), 1)
        self.assertEqual(progress["items"][0]["state"], "failed")
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_authenticated_route_get_keeps_existing_empty_file_byte_identical(self):
        before_bytes, before_mtime_ns = self.write_progress_fixture({
            "active": False,
            "items": [],
            "updated_at": 1.0,
        })
        app = self.create_test_app()

        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("GET invoked the progress writer"),
        ):
            with app.test_client() as client:
                with client.session_transaction() as test_session:
                    test_session["user_id"] = "image-progress-user"
                response = client.get("/api/recipe_image_progress")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["active"])
        self.assertEqual(response.get_json()["items"], [])
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_authenticated_route_get_compacts_stale_entries_only_in_memory(self):
        before_bytes, before_mtime_ns = self.write_progress_fixture(
            self.stale_progress_fixture()
        )
        app = self.create_test_app()

        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("GET invoked the progress writer"),
        ):
            with app.test_client() as client:
                with client.session_transaction() as test_session:
                    test_session["user_id"] = "image-progress-user"
                response = client.get("/api/recipe_image_progress")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["active"])
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["state"], "failed")
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)


if __name__ == "__main__":
    unittest.main()
