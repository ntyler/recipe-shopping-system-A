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
        self.clear_transition_cache()
        self.addCleanup(self.clear_transition_cache)
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

    def clear_transition_cache(self):
        with service.PROGRESS_LOCK:
            service._STALE_TRANSITION_CACHE.clear()

    def write_progress_fixture(self, payload, progress_path=None):
        progress_path = progress_path or service.PROGRESS_FILE
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return progress_path.read_bytes(), progress_path.stat().st_mtime_ns

    def assert_progress_file_unchanged(
        self,
        before_bytes,
        before_mtime_ns,
        progress_path=None,
    ):
        progress_path = progress_path or service.PROGRESS_FILE
        self.assertEqual(progress_path.read_bytes(), before_bytes)
        self.assertEqual(progress_path.stat().st_mtime_ns, before_mtime_ns)

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

    def stale_running_fixture(
        self,
        observed_at,
        url="manual://recipe/stale-lifecycle",
        target="1",
    ):
        old = observed_at - service.RUNNING_STALE_SECONDS - 1
        return {
            "active": True,
            "items": [{
                "key": service.image_progress_key("step", url, target),
                "kind": "step",
                "url": url,
                "target": target,
                "state": "running",
                "updated_at": old,
            }],
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

    def test_stale_service_read_lifecycle_is_stable_and_read_only(self):
        first_observed_at = 10_000.0
        before_bytes, before_mtime_ns = self.write_progress_fixture(
            self.stale_running_fixture(first_observed_at)
        )

        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("read path invoked the progress writer"),
        ):
            with patch.object(service, "_now", return_value=first_observed_at):
                first = service.load_recipe_image_progress()
            with patch.object(service, "_now", return_value=first_observed_at + 1):
                immediate_repeat = service.load_recipe_image_progress()
            with patch.object(
                service,
                "_now",
                return_value=first_observed_at + service.RECENT_RESULT_SECONDS - 1,
            ):
                before_expiry = service.load_recipe_image_progress()
            with patch.object(
                service,
                "_now",
                return_value=first_observed_at + service.RECENT_RESULT_SECONDS + 1,
            ):
                expired = service.load_recipe_image_progress()
            with patch.object(
                service,
                "_now",
                return_value=first_observed_at + service.RECENT_RESULT_SECONDS + 500,
            ):
                still_expired = service.load_recipe_image_progress()

        self.assertEqual(first["items"][0]["state"], "failed")
        self.assertEqual(first["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(
            immediate_repeat["items"][0]["updated_at"],
            first_observed_at,
        )
        self.assertEqual(before_expiry["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(expired["items"], [])
        self.assertEqual(still_expired["items"], [])
        self.assertEqual(list(service._STALE_TRANSITION_CACHE.values()), [None])
        cache_key = next(iter(service._STALE_TRANSITION_CACHE))
        self.assertEqual(len(cache_key[2]), 64)
        self.assertNotIn("manual://recipe/stale-lifecycle", cache_key[2])
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_authenticated_get_stale_lifecycle_is_stable_and_read_only(self):
        first_observed_at = 20_000.0
        before_bytes, before_mtime_ns = self.write_progress_fixture(
            self.stale_running_fixture(first_observed_at)
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

                payloads = []
                for observed_at in (
                    first_observed_at,
                    first_observed_at + 1,
                    first_observed_at + service.RECENT_RESULT_SECONDS - 1,
                    first_observed_at + service.RECENT_RESULT_SECONDS + 1,
                    first_observed_at + service.RECENT_RESULT_SECONDS + 500,
                ):
                    with patch.object(service, "_now", return_value=observed_at):
                        response = client.get("/api/recipe_image_progress")
                    self.assertEqual(response.status_code, 200)
                    payloads.append(response.get_json())
                    self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

        self.assertEqual(payloads[0]["items"][0]["state"], "failed")
        self.assertEqual(payloads[0]["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(payloads[1]["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(payloads[2]["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(payloads[3]["items"], [])
        self.assertEqual(payloads[4]["items"], [])
        self.assertEqual(list(service._STALE_TRANSITION_CACHE.values()), [None])

    def test_transition_cache_isolated_by_path(self):
        first_observed_at = 30_000.0
        paths = [
            Path(self.temp_dir.name) / "tenant-a" / "recipe_image_progress.json",
            Path(self.temp_dir.name) / "tenant-b" / "recipe_image_progress.json",
        ]
        fixture = self.stale_running_fixture(first_observed_at)
        fingerprints = [self.write_progress_fixture(fixture, path) for path in paths]
        transitions = []

        for index, progress_path in enumerate(paths):
            with patch.object(service, "PROGRESS_FILE", progress_path):
                with patch.object(
                    service,
                    "_now",
                    return_value=first_observed_at + index * 10,
                ):
                    progress = service.load_recipe_image_progress()
            transitions.append(progress["items"][0]["updated_at"])

        self.assertEqual(transitions, [first_observed_at, first_observed_at + 10])
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 2)
        self.assertEqual(
            {cache_key[0] for cache_key in service._STALE_TRANSITION_CACHE},
            {service._progress_scope_key(path.resolve()) for path in paths},
        )
        for progress_path, (before_bytes, before_mtime_ns) in zip(paths, fingerprints):
            self.assert_progress_file_unchanged(
                before_bytes,
                before_mtime_ns,
                progress_path,
            )

    def test_transition_cache_isolated_by_item(self):
        first_observed_at = 40_000.0
        first_url = "manual://recipe/item-one"
        second_url = "manual://recipe/item-two"
        payload = self.stale_running_fixture(first_observed_at, url=first_url)
        second_item = self.stale_running_fixture(
            first_observed_at + 6,
            url=second_url,
            target="2",
        )["items"][0]
        payload["items"].append(second_item)
        before_bytes, before_mtime_ns = self.write_progress_fixture(payload)

        with patch.object(service, "_now", return_value=first_observed_at):
            first = service.load_recipe_image_progress()
        with patch.object(service, "_now", return_value=first_observed_at + 10):
            second = service.load_recipe_image_progress()
        with patch.object(
            service,
            "_now",
            return_value=first_observed_at + service.RECENT_RESULT_SECONDS + 1,
        ):
            partly_expired = service.load_recipe_image_progress()

        self.assertEqual(
            [(item["url"], item["state"]) for item in first["items"]],
            [(first_url, "failed"), (second_url, "running")],
        )
        self.assertEqual(
            {item["url"]: item["updated_at"] for item in second["items"]},
            {first_url: first_observed_at, second_url: first_observed_at + 10},
        )
        self.assertEqual(
            [(item["url"], item["updated_at"]) for item in partly_expired["items"]],
            [(second_url, first_observed_at + 10)],
        )
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 2)
        self.assertEqual(
            len({cache_key[2] for cache_key in service._STALE_TRANSITION_CACHE}),
            2,
        )
        self.assertEqual(
            sorted(
                transition is None
                for transition in service._STALE_TRANSITION_CACHE.values()
            ),
            [False, True],
        )
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_changed_source_fingerprint_starts_new_lifecycle_and_prunes_old_entries(self):
        first_observed_at = 50_000.0
        payload = self.stale_running_fixture(first_observed_at)
        self.write_progress_fixture(payload)

        with patch.object(service, "_now", return_value=first_observed_at):
            first = service.load_recipe_image_progress()
        with patch.object(
            service,
            "_now",
            return_value=first_observed_at + service.RECENT_RESULT_SECONDS + 1,
        ):
            expired = service.load_recipe_image_progress()
        old_fingerprint = next(iter(service._STALE_TRANSITION_CACHE))[1]

        payload["source_revision"] = 2
        before_bytes, before_mtime_ns = self.write_progress_fixture(payload)
        new_observed_at = first_observed_at + service.RECENT_RESULT_SECONDS + 2
        with patch.object(service, "_now", return_value=new_observed_at):
            changed = service.load_recipe_image_progress()

        self.assertEqual(first["items"][0]["updated_at"], first_observed_at)
        self.assertEqual(expired["items"], [])
        self.assertEqual(changed["items"][0]["updated_at"], new_observed_at)
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 1)
        new_fingerprint = next(iter(service._STALE_TRANSITION_CACHE))[1]
        self.assertNotEqual(new_fingerprint, old_fingerprint)
        self.assertNotIn(
            old_fingerprint,
            {cache_key[1] for cache_key in service._STALE_TRANSITION_CACHE},
        )
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_explicit_start_and_finish_persist_and_invalidate_transition_cache(self):
        first_observed_at = 60_000.0
        self.write_progress_fixture(self.stale_running_fixture(first_observed_at))

        with patch.object(service, "_now", return_value=first_observed_at):
            service.load_recipe_image_progress()
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 1)

        with patch.object(service, "_now", return_value=first_observed_at + 1):
            service.start_recipe_image_progress(
                "step",
                "manual://recipe/stale-lifecycle",
                "1",
                image_prompt="preserve this prompt after cache expiry",
            )
        running_bytes = service.PROGRESS_FILE.read_bytes()
        running = json.loads(running_bytes.decode("utf-8"))
        self.assertEqual(running["items"][0]["state"], "running")
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 0)

        stale_observed_at = (
            first_observed_at + service.RUNNING_STALE_SECONDS + 2
        )
        with patch.object(service, "_now", return_value=stale_observed_at):
            stale = service.load_recipe_image_progress()
        self.assertEqual(stale["items"][0]["state"], "failed")
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 1)

        expired_at = stale_observed_at + service.RECENT_RESULT_SECONDS + 1
        with patch.object(service, "_now", return_value=expired_at):
            expired = service.load_recipe_image_progress()
        self.assertEqual(expired["items"], [])
        self.assertEqual(list(service._STALE_TRANSITION_CACHE.values()), [None])

        with patch.object(service, "_now", return_value=expired_at + 1):
            service.finish_recipe_image_progress(
                "step",
                "manual://recipe/stale-lifecycle",
                "1",
                ok=True,
                image_url="/static/generated/recipe_steps/lifecycle.png",
            )
        finished_bytes = service.PROGRESS_FILE.read_bytes()
        finished = json.loads(finished_bytes.decode("utf-8"))
        self.assertNotEqual(finished_bytes, running_bytes)
        self.assertEqual(finished["items"][0]["state"], "done")
        self.assertEqual(
            finished["items"][0]["started_at"],
            running["items"][0]["started_at"],
        )
        self.assertEqual(
            finished["items"][0]["image_prompt"],
            "preserve this prompt after cache expiry",
        )
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 0)

    def test_empty_and_missing_files_prune_transition_state_without_writes(self):
        first_observed_at = 70_000.0
        self.write_progress_fixture(self.stale_running_fixture(first_observed_at))
        with patch.object(service, "_now", return_value=first_observed_at):
            service.load_recipe_image_progress()
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 1)

        service.PROGRESS_FILE.unlink()
        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("missing-file read invoked the writer"),
        ):
            missing = service.load_recipe_image_progress()
        self.assertFalse(service.PROGRESS_FILE.exists())
        self.assertEqual(missing["items"], [])
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 0)

        before_bytes, before_mtime_ns = self.write_progress_fixture({
            "active": False,
            "items": [],
            "updated_at": 1.0,
        })
        with patch.object(
            service,
            "save_recipe_image_progress",
            side_effect=AssertionError("empty-file read invoked the writer"),
        ):
            empty = service.load_recipe_image_progress()
        self.assertEqual(empty["items"], [])
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 0)
        self.assert_progress_file_unchanged(before_bytes, before_mtime_ns)

    def test_transition_cache_bound_evicts_least_recent_history(self):
        first_observed_at = 80_000.0
        paths = [
            Path(self.temp_dir.name) / f"tenant-{index}" / "recipe_image_progress.json"
            for index in range(3)
        ]
        fixture = self.stale_running_fixture(first_observed_at)
        fingerprints = [self.write_progress_fixture(fixture, path) for path in paths]

        with patch.object(service, "STALE_TRANSITION_CACHE_MAX_ENTRIES", 2):
            for index, progress_path in enumerate(paths):
                with patch.object(service, "PROGRESS_FILE", progress_path):
                    with patch.object(
                        service,
                        "_now",
                        return_value=first_observed_at + index,
                    ):
                        service.load_recipe_image_progress()

            self.assertEqual(len(service._STALE_TRANSITION_CACHE), 2)
            cached_scopes = {
                cache_key[0] for cache_key in service._STALE_TRANSITION_CACHE
            }
            self.assertNotIn(service._progress_scope_key(paths[0].resolve()), cached_scopes)

            with patch.object(service, "PROGRESS_FILE", paths[0]):
                with patch.object(
                    service,
                    "_now",
                    return_value=first_observed_at + 10,
                ):
                    reobserved = service.load_recipe_image_progress()

        self.assertEqual(reobserved["items"][0]["updated_at"], first_observed_at + 10)
        self.assertEqual(len(service._STALE_TRANSITION_CACHE), 2)
        for progress_path, (before_bytes, before_mtime_ns) in zip(paths, fingerprints):
            self.assert_progress_file_unchanged(
                before_bytes,
                before_mtime_ns,
                progress_path,
            )


if __name__ == "__main__":
    unittest.main()
