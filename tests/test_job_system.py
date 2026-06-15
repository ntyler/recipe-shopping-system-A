import pytest

from PushShoppingList.app import create_app
from PushShoppingList.routes import job_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_queue_service
from PushShoppingList.services import job_service
from PushShoppingList.services import job_tasks
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import storage_service


def configure_job_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")


def test_job_routes_create_and_scope_jobs_to_owner(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        job_routes,
        "enqueue_job",
        lambda job_id, **kwargs: {"ok": True, "mode": "test", "job_id": job_id, **kwargs},
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.post(
            "/api/jobs/recipe-import",
            json={"urls": ["https://example.com/recipe"]},
            headers={"X-Requested-With": "fetch"},
        )
        data = response.get_json()

        assert response.status_code == 202
        assert data["job_id"]
        assert data["job"]["job_type"] == "recipe-import"
        assert data["job"]["status"] == "queued"
        assert data["job"]["queue_name"] == "ai-pantry-recipe"
        assert data["job"]["model_env_var"] == "OPENAI_RECIPE_MODEL"
        assert data["job"]["source_items"][0]["label"] == "https://example.com/recipe"

        status = client.get(
            f"/api/jobs/{data['job_id']}",
            headers={"X-Requested-With": "fetch"},
        )
        assert status.status_code == 200
        assert status.get_json()["job"]["user_id"] == "owner"

        with client.session_transaction() as session:
            session["user_id"] = "other"

        hidden = client.get(
            f"/api/jobs/{data['job_id']}",
            headers={"X-Requested-With": "fetch"},
        )
        assert hidden.status_code == 404


def test_clear_recent_jobs_removes_finished_owner_jobs_only(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    completed = job_service.create_job(
        "recipe-import",
        input_payload={"urls": ["https://example.com/completed"]},
        user_id="owner",
        total_items=1,
    )
    failed = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/failed"]},
        user_id="owner",
        total_items=1,
    )
    running = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": ["https://example.com/running"]},
        user_id="owner",
        total_items=1,
    )
    other = job_service.create_job(
        "recipe-import",
        input_payload={"urls": ["https://example.com/other"]},
        user_id="other",
        total_items=1,
    )

    job_service.complete_job(completed["id"])
    job_service.fail_job(failed["id"], "Nope")
    job_service.update_job(running["id"], status="running", started_at=job_service.now_iso())
    job_service.complete_job(other["id"])

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.delete(
            "/api/jobs/recent",
            headers={"X-Requested-With": "fetch"},
        )

    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["deleted_count"] == 2
    assert [job["id"] for job in data["jobs"]] == [running["id"]]
    assert job_service.get_job(completed["id"]) is None
    assert job_service.get_job(failed["id"]) is None
    assert job_service.get_job(running["id"]) is not None
    assert job_service.get_job(other["id"]) is not None


def test_job_for_client_shows_safe_sources_and_model_metadata(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    upload_path = tmp_path / "secret" / "staged-menu.pdf"
    upload_path.parent.mkdir(parents=True)
    upload_path.write_text("demo")

    job = job_service.create_job(
        "doc-photo-import",
        input_payload={
            "source_path": str(upload_path),
            "filename": "menu.pdf",
            "model_used": "gpt-5.5",
            "model_source": "env:OPENAI_MENU_MODEL",
            "model_env_var": "OPENAI_MENU_MODEL",
        },
        user_id="owner",
        total_items=1,
        queue_name="ai-pantry-menu",
    )
    job = job_service.update_job(
        job["id"],
        worker_id="DESKTOP-IN7S09S:73720",
        rq_job_id="rq-123",
    )

    payload = job_service.job_for_client(job)

    assert payload["model_used"] == "gpt-5.5"
    assert payload["model_source"] == "env:OPENAI_MENU_MODEL"
    assert payload["model_env_var"] == "OPENAI_MENU_MODEL"
    assert payload["model_env_var_used"] == "OPENAI_MENU_MODEL"
    assert payload["queue_name"] == "ai-pantry-menu"
    assert payload["worker_id"] == "DESKTOP-IN7S09S:73720"
    assert payload["rq_job_id"] == "rq-123"
    assert payload["source_items"] == [
        {
            "type": "file",
            "label": "menu.pdf",
            "detail": "",
        }
    ]
    assert "input_payload" not in payload
    assert str(upload_path) not in str(payload)


def test_menu_generate_job_sources_link_to_recipe_item_editor(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll"

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": [recipe_url]},
        user_id="owner",
        total_items=1,
    )

    payload = job_service.job_for_client(job)

    assert payload["source_items"] == [
        {
            "type": "recipe",
            "label": recipe_url,
            "detail": "menu item",
            "url": "/recipe/edit?url=https%3A%2F%2Fwww.velasiancuisine.com%2Frs%2Fmenu_home.action%3FresInput%3DRES4902%26menu_item%3Dspring-roll",
            "recipe_url": recipe_url,
        }
    ]


def test_menu_generate_route_returns_trigger_item_source_link(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll"
    monkeypatch.setattr(
        job_routes,
        "enqueue_job",
        lambda job_id, **kwargs: {"ok": True, "mode": "test", "job_id": job_id, **kwargs},
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.post(
            "/api/jobs/menu-generate-recipes",
            json={"recipe_urls": [recipe_url]},
            headers={"X-Requested-With": "fetch"},
        )
        data = response.get_json()

    assert response.status_code == 202
    assert data["job"]["job_type"] == "menu-generate-recipes"
    assert data["job"]["source_items"][0]["detail"] == "menu item"
    assert data["job"]["source_items"][0]["url"].startswith("/recipe/edit?url=")
    assert data["job"]["source_items"][0]["recipe_url"] == recipe_url


def test_menu_generate_job_runs_decide_all_categories_after_generation(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=crab-wonton"
    stub = {
        "source_url": recipe_url,
        "recipe_title": "Crab Wonton",
        "display_name": "Crab Wonton",
        "needs_ai_recipe": True,
        "recipe_status": "stub",
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    }
    category_calls = []

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", lambda url: {"recipe": stub})
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_batch_item_from_stub",
        lambda url, loaded_stub, index: {
            "menu_item_id": "item-1",
            "item_name": "Crab Wonton",
            "menu_section": "Appetizers",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "infer_menu_item_recipe_batch",
        lambda batch, user_id=None: {
            "ok": True,
            "items": {"item-1": {"predicted_ingredients": ["cream cheese"]}},
            "model": "gpt-test",
            "model_source": "test",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "apply_menu_batch_inference_to_stub",
        lambda url, loaded_stub, menu_item, inference, model="", model_source="": {
            "ok": True,
            "source_url": url,
            "display_name": "Crab Wonton",
            "recipe_title": "Crab Wonton",
            "ingredients": [{"ingredient": "cream cheese"}],
            "instructions": [{"instruction": "Fill and fry."}],
            "cookbook_id": loaded_stub.get("cookbook_id"),
            "cookbook_name": loaded_stub.get("cookbook_name"),
        },
    )
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", lambda url, ingredients, result: None)
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda url, name: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [entries])
    monkeypatch.setattr(cookbook_service, "cookbook_recipe_assignment_for_url", lambda url: {
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    })
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)

    def fake_category_routine(url, result, assignment, trigger_source=""):
        category_calls.append({
            "url": url,
            "title": result.get("recipe_title"),
            "assignment": assignment,
            "trigger_source": trigger_source,
        })
        return {"ok": True, "status": "updated", "categories": {"meal_type": "Dinner"}}

    monkeypatch.setattr(recipe_routes, "apply_imported_recipe_category_routine", fake_category_routine)

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": [recipe_url],
            "run_deferred_heavy_tasks": False,
        },
        user_id="owner",
        total_items=1,
    )

    finished = job_tasks.run_menu_generate_recipes_job(job["id"], job["input_payload"])

    assert finished["status"] == "completed"
    assert category_calls == [{
        "url": recipe_url,
        "title": "Crab Wonton",
        "assignment": {"cookbook_id": "cb1", "cookbook_name": "Dinner"},
        "trigger_source": "menu_generate:all",
    }]
    assert finished["result_payload"]["category_success_count"] == 1
    assert finished["result_payload"]["category_statuses"][0]["recipe_url"] == recipe_url


def test_menu_deferred_heavy_task_route_uses_recipe_item_sources(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll"
    monkeypatch.setattr(
        job_routes,
        "enqueue_job",
        lambda job_id, **kwargs: {"ok": True, "mode": "test", "job_id": job_id, **kwargs},
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.post(
            "/api/jobs/menu-deferred-heavy-tasks",
            json={"recipe_urls": [recipe_url]},
            headers={"X-Requested-With": "fetch"},
        )
        data = response.get_json()

    assert response.status_code == 202
    assert data["job"]["job_type"] == "menu-deferred-heavy-tasks"
    assert data["job"]["queue_name"] == "ai-pantry-light"
    assert data["job"]["model_env_var"] == "OPENAI_NUTRITION_MODEL"
    assert data["job"]["source_items"][0]["detail"] == "menu item"
    assert data["job"]["source_items"][0]["recipe_url"] == recipe_url


def test_cancelled_job_cannot_be_revived_by_worker_updates(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    job = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu"]},
        user_id="owner",
        total_items=1,
    )

    cancelled = job_service.cancel_job(job["id"])
    assert cancelled["status"] == "cancelled"

    progress = job_service.update_job_progress(
        job["id"],
        current_step="Inferring recipes with gpt-5.5 via OPENAI_MENU_MODEL (1/266)",
        progress_percent=35,
        completed_items=1,
        total_items=266,
    )
    completed = job_service.complete_job(job["id"], result_payload={"ok": True})
    failed = job_service.fail_job(job["id"], "Should not overwrite cancellation.")

    assert progress["status"] == "cancelled"
    assert completed["status"] == "cancelled"
    assert failed["status"] == "cancelled"
    assert job_service.get_job(job["id"])["current_step"] == "Cancelled"


def test_menu_item_inference_bubbles_job_cancellation(monkeypatch, tmp_path):
    class JobCancelled(Exception):
        pass

    monkeypatch.setattr(recipe_extract_service, "RAW_FOLDER", tmp_path)

    def cancellation_check():
        raise JobCancelled()

    with pytest.raises(JobCancelled):
        recipe_extract_service.build_menu_extract_result_from_items(
            "https://example.com/menu",
            [
                {
                    "section_name": "Entrees",
                    "items": [{"item_name": "Test Noodles", "menu_section": "Entrees"}],
                }
            ],
            cancellation_check=cancellation_check,
        )


def test_guest_cleanup_deletes_guest_jobs(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    guest_root = tmp_path / "guests" / "guest-1"
    guest_root.mkdir(parents=True)
    job = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu"]},
        guest_session_id="guest-1",
        total_items=1,
    )

    assert job_service.get_job(job["id"])

    guest_session_service.delete_guest_temporary_data("guest-1")

    assert job_service.get_job(job["id"]) is None
    assert not guest_root.exists()


def test_queue_routing_by_job_type_and_payload():
    assert job_queue_service.queue_name_for_job("menu-import", {}) == "ai-pantry-menu"
    assert job_queue_service.queue_name_for_job("recipe-import", {}) == "ai-pantry-recipe"
    assert job_queue_service.queue_name_for_job("product-matching", {}) == "ai-pantry-product"
    assert job_queue_service.queue_name_for_job("recipe-category-decision", {}) == "ai-pantry-light"
    assert job_queue_service.queue_name_for_job("menu-deferred-heavy-tasks", {}) == "ai-pantry-light"
    assert job_service.job_limit_key("menu-deferred-heavy-tasks", {}) == "menu-heavy"
    assert job_queue_service.queue_name_for_job(
        "doc-photo-import",
        {"import_mode": "menu_extract"},
    ) == "ai-pantry-menu"
    assert job_queue_service.queue_name_for_job(
        "doc-photo-import",
        {"upload_mode": "image"},
    ) == "ai-pantry-media"


def test_thread_fallback_disabled_fails_job_when_redis_unavailable(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_QUEUE_THREAD_FALLBACK", "0")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")

    job = job_service.create_job(
        "recipe-import",
        input_payload={"urls": ["https://example.com/recipe"]},
        user_id="owner",
        queue_name="ai-pantry-recipe",
    )

    result = job_queue_service.enqueue_job(job["id"])
    failed = job_service.get_job(job["id"])

    assert result["ok"] is False
    assert result["queue_name"] == "ai-pantry-recipe"
    assert "Job queue is unavailable" in result["error"]
    assert failed["status"] == "failed"
    assert failed["current_step"] == "Queue unavailable"


def test_queued_limit_blocks_sixth_user_job(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    for index in range(5):
        job_service.create_job(
            "recipe-import",
            input_payload={"urls": [f"https://example.com/recipe-{index}"]},
            user_id="owner",
            queue_name="ai-pantry-recipe",
        )

    status = job_service.queued_limit_status(
        user_id="owner",
        job_type="recipe-import",
        input_payload={"urls": ["https://example.com/recipe-6"]},
    )

    assert status["ok"] is False
    assert status["limit"] == 5
    assert status["queued_count"] == 5


def test_worker_start_defers_when_user_active_limit_is_reached(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    running = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu-a"], "extraction_mode": "menu_extract"},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )
    job_service.update_job(running["id"], status="running", started_at=job_service.now_iso())
    queued = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu-b"], "extraction_mode": "menu_extract"},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    result = job_service.try_start_job(
        queued["id"],
        queue_name="ai-pantry-menu",
        model_used="gpt-5.5",
        model_source="env:OPENAI_MENU_MODEL",
        model_env_var_used="OPENAI_MENU_MODEL",
        worker_id="test-worker",
    )
    deferred = job_service.get_job(queued["id"])

    assert result["deferred"] is True
    assert result["started"] is False
    assert deferred["status"] == "queued"
    assert "Queued behind your active menu import" in deferred["current_step"]
    assert deferred["attempts"] == 1


def test_worker_start_records_queue_model_and_worker(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    job = job_service.create_job(
        "recipe-import",
        input_payload={"urls": ["https://example.com/recipe"]},
        user_id="owner",
        queue_name="ai-pantry-recipe",
    )

    result = job_service.try_start_job(
        job["id"],
        queue_name="ai-pantry-recipe",
        model_used="gpt-5.5-mini",
        model_source="env:OPENAI_RECIPE_MODEL",
        model_env_var_used="OPENAI_RECIPE_MODEL",
        worker_id="test-worker",
    )
    started = job_service.job_for_client(job_service.get_job(job["id"]))

    assert result["started"] is True
    assert started["status"] == "running"
    assert started["queue_name"] == "ai-pantry-recipe"
    assert started["model_used"] == "gpt-5.5-mini"
    assert started["model_env_var_used"] == "OPENAI_RECIPE_MODEL"
    assert started["worker_id"] == "test-worker"
    assert started["retry_count"] == 1
