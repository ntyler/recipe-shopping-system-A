import threading
from datetime import timedelta

import pytest

from PushShoppingList.app import create_app
from PushShoppingList.routes import job_routes
from PushShoppingList.routes import recipe_routes
from PushShoppingList.services import cookbook_service
from PushShoppingList.services import cookbook_item_inference_service
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_queue_service
from PushShoppingList.services import job_service
from PushShoppingList.services import job_tasks
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_url_service
from PushShoppingList.services import storage_service


def configure_job_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    output_folder = tmp_path / "extractor" / "output"
    output_folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_folder)
    monkeypatch.setattr(recipe_ingredient_service, "OUTPUT_FOLDER", output_folder)
    monkeypatch.setattr(recipe_ingredient_service, "RECIPE_INGREDIENTS_FILE", tmp_path / "extractor" / "recipe_ingredients.json")
    monkeypatch.setattr(recipe_url_service, "RECIPE_INGREDIENTS_FILE", tmp_path / "extractor" / "recipe_urls.json")


def successful_menu_serving_basis(recipe_url, result):
    recipe_json = dict(result or {})
    recipe_json["nutrition"] = [
        {"key": "serving_basis", "value": "per serving"},
        {"key": "calories", "value": "100 kcal"},
    ]
    recipe_json["nutrition_inference"] = {"status": "generated"}
    return {
        "ok": True,
        "recipe_url": recipe_url,
        "recipe_json": recipe_json,
        "nutrition": recipe_json["nutrition"],
    }


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


def test_job_queue_debug_route_returns_readiness(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        job_routes,
        "redis_queue_readiness",
        lambda check_connection=True: {
            "mode": "redis/rq",
            "redis_package_installed": True,
            "rq_package_installed": True,
            "redis_url_configured": True,
            "redis_connection_succeeded": True,
            "menu_queue": "ai-pantry-menu",
        },
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.get(
            "/api/debug/job-queue",
            headers={"X-Requested-With": "fetch"},
        )
        data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["job_queue"]["mode"] == "redis/rq"
    assert data["job_queue"]["menu_queue"] == "ai-pantry-menu"


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
    events = []

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
    monkeypatch.setattr("PushShoppingList.services.recipe_ingredient_service.save_ingredients_for_recipes", lambda records: None)
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.save_recipe_url_names", lambda records: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [entries])
    monkeypatch.setattr(cookbook_service, "cookbook_recipe_assignment_for_url", lambda url: {
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    })
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)
    monkeypatch.setattr(
        recipe_routes,
        "ensure_menu_recipe_serving_basis_estimate",
        lambda url, result: events.append(("nutrition", url)) or successful_menu_serving_basis(url, result),
    )

    def fake_category_routine(url, result, assignment, trigger_source=""):
        events.append(("categories", url, result.get("nutrition")))
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
    assert events == [
        ("nutrition", recipe_url),
        ("categories", recipe_url, [
            {"key": "serving_basis", "value": "per serving"},
            {"key": "calories", "value": "100 kcal"},
        ]),
    ]
    assert category_calls == [{
        "url": recipe_url,
        "title": "Crab Wonton",
        "assignment": {"cookbook_id": "cb1", "cookbook_name": "Dinner"},
        "trigger_source": "menu_generate:all",
    }]
    assert finished["result_payload"]["nutrition_completed"] == 1
    assert finished["result_payload"]["category_success_count"] == 1
    assert finished["result_payload"]["category_statuses"][0]["recipe_url"] == recipe_url


def test_menu_generate_job_finishes_all_nutrition_before_categories(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_urls = [
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll",
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=pad-thai",
    ]
    stubs = {
        recipe_urls[0]: {
            "source_url": recipe_urls[0],
            "recipe_title": "Spring Roll",
            "display_name": "Spring Roll",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-1",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
        recipe_urls[1]: {
            "source_url": recipe_urls[1],
            "recipe_title": "Pad Thai",
            "display_name": "Pad Thai",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-2",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
    }
    events = []
    ingredient_save_batches = []

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", lambda url: {"recipe": stubs[url]})
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_batch_item_from_stub",
        lambda url, loaded_stub, index: {
            "menu_item_id": loaded_stub["menu_item_id"],
            "item_name": loaded_stub["recipe_title"],
            "menu_section": "Entrees",
        },
    )
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [entries])
    monkeypatch.setattr(
        recipe_extract_service,
        "infer_menu_item_recipe_batch",
        lambda batch, user_id=None: {
            "ok": True,
            "items": {
                "item-1": {"predicted_ingredients": ["wrapper"]},
                "item-2": {"predicted_ingredients": ["noodles"]},
            },
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
            "display_name": loaded_stub["display_name"],
            "recipe_title": loaded_stub["recipe_title"],
            "ingredients": [{"ingredient": "test ingredient"}],
            "instructions": [{"instruction": "Cook."}],
            "cookbook_id": loaded_stub.get("cookbook_id"),
            "cookbook_name": loaded_stub.get("cookbook_name"),
        },
    )
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", lambda url, ingredients, result: None)
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda url, name: None)
    monkeypatch.setattr(
        "PushShoppingList.services.recipe_ingredient_service.save_ingredients_for_recipes",
        lambda records: ingredient_save_batches.append([record["url"] for record in records]),
    )
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.save_recipe_url_names", lambda records: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(cookbook_service, "cookbook_recipe_assignment_for_url", lambda url: {
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    })
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)

    def fake_serving_basis(url, result):
        events.append(("nutrition", url))
        return successful_menu_serving_basis(url, result)

    def fake_category(url, result, assignment, trigger_source=""):
        events.append(("categories", url))
        return {"ok": True, "status": "updated"}

    monkeypatch.setattr(recipe_routes, "ensure_menu_recipe_serving_basis_estimate", fake_serving_basis)
    monkeypatch.setattr(recipe_routes, "apply_imported_recipe_category_routine", fake_category)

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": recipe_urls,
            "run_deferred_heavy_tasks": False,
        },
        user_id="owner",
        total_items=2,
    )

    finished = job_tasks.run_menu_generate_recipes_job(job["id"], job["input_payload"])

    assert finished["status"] == "completed"
    nutrition_event_indexes = [index for index, event in enumerate(events) if event[0] == "nutrition"]
    category_event_indexes = [index for index, event in enumerate(events) if event[0] == "categories"]
    assert sorted(event[1] for event in events if event[0] == "nutrition") == sorted(recipe_urls)
    assert sorted(event[1] for event in events if event[0] == "categories") == sorted(recipe_urls)
    assert max(nutrition_event_indexes) < min(category_event_indexes)
    assert finished["result_payload"]["nutrition_completed"] == 2
    assert finished["result_payload"]["category_success_count"] == 2
    assert ingredient_save_batches == [recipe_urls]


def test_menu_generate_job_keeps_partial_batch_predictions(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_urls = [
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll",
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=crab-wonton",
    ]
    stubs = {
        recipe_urls[0]: {
            "source_url": recipe_urls[0],
            "recipe_title": "Spring Roll",
            "display_name": "Spring Roll",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-1",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
        recipe_urls[1]: {
            "source_url": recipe_urls[1],
            "recipe_title": "Crab Wonton",
            "display_name": "Crab Wonton",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-2",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
    }
    saved_urls = []

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", lambda url: {"recipe": stubs[url]})
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_batch_item_from_stub",
        lambda url, loaded_stub, index: {
            "menu_item_id": loaded_stub["menu_item_id"],
            "item_name": loaded_stub["recipe_title"],
            "menu_section": "Appetizers",
        },
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "infer_menu_item_recipe_batch",
        lambda batch, user_id=None: {
            "ok": False,
            "items": {"item-1": {"predicted_ingredients": ["rice paper"]}},
            "failures": {"item-2": {"error": "Vision AI request timed out."}},
            "error_message": "Vision AI request timed out.",
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
            "display_name": loaded_stub["display_name"],
            "recipe_title": loaded_stub["recipe_title"],
            "ingredients": [{"ingredient": "rice paper"}],
            "instructions": [{"instruction": "Roll and serve."}],
            "cookbook_id": loaded_stub.get("cookbook_id"),
            "cookbook_name": loaded_stub.get("cookbook_name"),
        },
    )
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", lambda url, ingredients, result: saved_urls.append(url))
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda url, name: None)
    monkeypatch.setattr(
        "PushShoppingList.services.recipe_ingredient_service.save_ingredients_for_recipes",
        lambda records: saved_urls.extend(record["url"] for record in records),
    )
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.save_recipe_url_names", lambda records: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [entries])
    monkeypatch.setattr(cookbook_service, "cookbook_recipe_assignment_for_url", lambda url: {
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    })
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment, trigger_source="": {"ok": True, "status": "updated"},
    )
    monkeypatch.setattr(
        recipe_routes,
        "ensure_menu_recipe_serving_basis_estimate",
        successful_menu_serving_basis,
    )

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": recipe_urls,
            "run_deferred_heavy_tasks": False,
        },
        user_id="owner",
        total_items=2,
    )

    finished = job_tasks.run_menu_generate_recipes_job(job["id"], job["input_payload"])

    assert finished["status"] == "completed"
    assert saved_urls == [recipe_urls[0]]
    assert finished["result_payload"]["created_count"] == 1
    assert finished["result_payload"]["failed_count"] == 1
    assert finished["result_payload"]["generated_recipe_urls"] == [recipe_urls[0]]
    assert finished["result_payload"]["failed_recipe_items"] == [{
        "recipe_url": recipe_urls[1],
        "recipe_name": "Crab Wonton",
        "stage": "Recipe generation",
        "error": "Vision AI request timed out.",
    }]
    assert any("keeping 1 predicted recipe" in warning for warning in finished["warning_messages"])
    assert any("Vision AI request timed out." in warning for warning in finished["warning_messages"])
    assert any("Crab Wonton" in warning for warning in finished["warning_messages"])


def test_menu_generate_job_predicts_batches_in_parallel(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MENU_ITEM_BATCH_INFERENCE_WORKERS", "2")
    recipe_urls = [
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=spring-roll",
        "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=pad-thai",
    ]
    stubs = {
        recipe_urls[0]: {
            "source_url": recipe_urls[0],
            "recipe_title": "Spring Roll",
            "display_name": "Spring Roll",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-1",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
        recipe_urls[1]: {
            "source_url": recipe_urls[1],
            "recipe_title": "Pad Thai",
            "display_name": "Pad Thai",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": "item-2",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        },
    }
    started_item_ids = []
    started_lock = threading.Lock()
    both_started = threading.Event()
    saved_urls = []

    monkeypatch.setattr(recipe_routes, "load_editable_recipe", lambda url: {"recipe": stubs[url]})
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_batch_item_from_stub",
        lambda url, loaded_stub, index: {
            "menu_item_id": loaded_stub["menu_item_id"],
            "item_name": loaded_stub["recipe_title"],
            "menu_section": "Entrees",
        },
    )
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [[entry] for entry in entries])

    def fake_infer_batch(batch, user_id=None):
        item_id = batch[0]["menu_item"]["menu_item_id"]
        with started_lock:
            started_item_ids.append(item_id)
            if len(started_item_ids) == 2:
                both_started.set()
        assert both_started.wait(2), "menu prediction batches did not overlap"
        return {
            "ok": True,
            "items": {item_id: {"predicted_ingredients": [{"ingredient": item_id}]}},
            "failures": {},
            "model": "gpt-test",
            "model_source": "test",
        }

    monkeypatch.setattr(recipe_extract_service, "infer_menu_item_recipe_batch", fake_infer_batch)
    monkeypatch.setattr(
        recipe_extract_service,
        "apply_menu_batch_inference_to_stub",
        lambda url, loaded_stub, menu_item, inference, model="", model_source="": {
            "ok": True,
            "source_url": url,
            "display_name": loaded_stub["display_name"],
            "recipe_title": loaded_stub["recipe_title"],
            "ingredients": [{"ingredient": "test ingredient"}],
            "instructions": [{"instruction": "Cook."}],
            "cookbook_id": loaded_stub.get("cookbook_id"),
            "cookbook_name": loaded_stub.get("cookbook_name"),
        },
    )
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(recipe_routes, "save_ingredients_for_recipe", lambda url, ingredients, result: saved_urls.append(url))
    monkeypatch.setattr(recipe_routes, "save_recipe_url_name", lambda url, name: None)
    monkeypatch.setattr(
        "PushShoppingList.services.recipe_ingredient_service.save_ingredients_for_recipes",
        lambda records: saved_urls.extend(record["url"] for record in records),
    )
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.save_recipe_url_names", lambda records: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(cookbook_service, "cookbook_recipe_assignment_for_url", lambda url: {
        "cookbook_id": "cb1",
        "cookbook_name": "Dinner",
    })
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment, trigger_source="": {"ok": True, "status": "updated"},
    )
    monkeypatch.setattr(
        recipe_routes,
        "ensure_menu_recipe_serving_basis_estimate",
        successful_menu_serving_basis,
    )

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": recipe_urls,
            "run_deferred_heavy_tasks": False,
        },
        user_id="owner",
        total_items=2,
    )

    finished = job_tasks.run_menu_generate_recipes_job(job["id"], job["input_payload"])

    assert finished["status"] == "completed"
    assert started_item_ids == ["item-1", "item-2"]
    assert saved_urls == recipe_urls
    assert finished["result_payload"]["batch_workers"] == 2


def test_menu_generate_job_bulk_saves_predicted_recipes_with_throttled_progress(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MENU_SAVE_PROGRESS_EVERY", "10")
    recipe_urls = [
        f"https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902&menu_item=item-{index}"
        for index in range(12)
    ]
    stubs = {
        url: {
            "source_url": url,
            "recipe_title": f"Menu Item {index + 1}",
            "display_name": f"Menu Item {index + 1}",
            "needs_ai_recipe": True,
            "recipe_status": "stub",
            "menu_item_id": f"item-{index}",
            "cookbook_id": "cb1",
            "cookbook_name": "Dinner",
        }
        for index, url in enumerate(recipe_urls)
    }
    progress_updates = []
    saved_url_batches = []
    real_update_progress = job_tasks.update_job_progress

    def recording_update_progress(*args, **kwargs):
        progress_updates.append(kwargs)
        return real_update_progress(*args, **kwargs)

    monkeypatch.setattr(job_tasks, "update_job_progress", recording_update_progress)
    monkeypatch.setattr(recipe_routes, "load_editable_recipe", lambda url: {"recipe": stubs[url]})
    monkeypatch.setattr(
        recipe_extract_service,
        "menu_batch_item_from_stub",
        lambda url, loaded_stub, index: {
            "menu_item_id": loaded_stub["menu_item_id"],
            "item_name": loaded_stub["recipe_title"],
            "menu_section": "Entrees",
        },
    )
    monkeypatch.setattr(recipe_extract_service, "menu_inference_batches", lambda entries: [entries])
    monkeypatch.setattr(
        recipe_extract_service,
        "infer_menu_item_recipe_batch",
        lambda batch, user_id=None: {
            "ok": True,
            "items": {
                entry["menu_item"]["menu_item_id"]: {
                    "predicted_ingredients": [f"ingredient {index + 1}"],
                    "predicted_instructions": ["Cook and serve."],
                }
                for index, entry in enumerate(batch)
            },
            "model": "gpt-test",
            "model_source": "test",
        },
    )
    monkeypatch.setattr(recipe_routes, "add_items", lambda ingredients: None)
    monkeypatch.setattr(
        "PushShoppingList.services.recipe_ingredient_service.save_ingredients_for_recipes",
        lambda records: saved_url_batches.append([record["url"] for record in records]),
    )
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.save_recipe_url_names", lambda records: None)
    monkeypatch.setattr("PushShoppingList.services.recipe_url_service.add_recipe_urls", lambda urls: None)
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)
    monkeypatch.setattr(recipe_routes, "record_recipe_import_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cookbook_service,
        "cookbook_recipe_assignment_for_url",
        lambda url: {"cookbook_id": "cb1", "cookbook_name": "Dinner"},
    )
    monkeypatch.setattr(recipe_routes, "ensure_menu_recipe_serving_basis_estimate", successful_menu_serving_basis)
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment, trigger_source="": {"ok": True, "status": "updated"},
    )

    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": recipe_urls,
            "run_deferred_heavy_tasks": False,
        },
        user_id="owner",
        total_items=len(recipe_urls),
    )

    finished = job_tasks.run_menu_generate_recipes_job(job["id"], job["input_payload"])

    save_updates = [
        update for update in progress_updates
        if (update.get("result_payload") or {}).get("stage") == "Saving predicted recipes"
    ]
    nutrition_updates = [
        update for update in progress_updates
        if (update.get("result_payload") or {}).get("stage") == "Estimating per serving basis"
    ]
    category_updates = [
        update for update in progress_updates
        if (update.get("result_payload") or {}).get("stage") == "Generating categories"
    ]
    assert finished["status"] == "completed"
    assert finished["result_payload"]["created_count"] == len(recipe_urls)
    assert saved_url_batches == [recipe_urls]
    assert len(save_updates) < len(recipe_urls)
    assert save_updates[-1]["result_payload"]["save_progress_every"] == 10
    assert len(nutrition_updates) < len(recipe_urls)
    assert len(category_updates) < len(recipe_urls)
    assert nutrition_updates[-1]["result_payload"]["followup_progress_every"] == 10
    assert category_updates[-1]["result_payload"]["followup_progress_every"] == 10


def test_menu_import_queues_recipe_generation_after_source_completed(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    menu_url = "https://www.velasiancuisine.com/rs/menu_home.action?resInput=RES4902"
    recipe_urls = [
        f"{menu_url}&menu_item=menu-item-1-Spring_Roll",
        f"{menu_url}&menu_item=menu-item-2-Crab_Wonton_5",
    ]
    job = job_service.create_job(
        "menu-import",
        input_payload={"urls": [menu_url], "extraction_mode": "menu_extract"},
        user_id="owner",
        total_items=1,
        queue_name="ai-pantry-menu",
    )
    job_service.update_job(job["id"], status="running", started_at=job_service.now_iso())
    observed_source_statuses = []

    monkeypatch.setattr(recipe_routes, "extract_menu_stubs_from_url", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        recipe_routes,
        "commit_menu_import_result",
        lambda *args, **kwargs: {
            "ok": True,
            "created_urls": recipe_urls,
            "stubs_created": len(recipe_urls),
            "item_records_unpacked": len(recipe_urls),
            "menu_items_found": len(recipe_urls),
            "menu_sections_found": 1,
            "menu_source_url": menu_url,
            "menu_source_pdf_status": "ready",
            "menu_source_pdf_path": "velasiancuisine_com_rs_menu_home_action_resInput_RES4902.pdf",
            "menu_source_cloudflare_pdf_url": "https://cdn.example/menu.pdf",
        },
    )
    monkeypatch.setattr("PushShoppingList.scripts.sort_ingredients.main", lambda: None)

    def fake_enqueue_followup(job_type, payload, total_items=0):
        observed_source_statuses.append(job_service.get_job(payload["source_job_id"])["status"])
        return {"queued": True, "job_id": "followup-job", "queue": {"mode": "test"}}

    monkeypatch.setattr(job_tasks, "enqueue_followup_job", fake_enqueue_followup)

    finished = job_tasks.run_import_urls_job(job["id"], job["input_payload"], menu_extract=True)

    assert observed_source_statuses == ["completed"]
    assert finished["status"] == "completed"
    assert finished["result_payload"]["recipe_inference_job_id"] == "followup-job"
    assert finished["result_payload"]["recipe_inference_job"]["queued"] is True


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


def test_cookbook_infer_missing_details_route_queues_full_routine(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_url = "menu-item://dinner/spring-roll"
    monkeypatch.setattr(
        job_routes,
        "enqueue_job",
        lambda job_id, **kwargs: {"ok": True, "mode": "test", "job_id": job_id, **kwargs},
    )
    monkeypatch.setattr(
        cookbook_item_inference_service,
        "recipe_context_from_cookbook",
        lambda cookbook_id: {
            "id": cookbook_id,
            "name": "Dinner",
            "recipes": [{"url": recipe_url, "name": "Spring Roll"}],
        },
    )
    monkeypatch.setattr(
        cookbook_item_inference_service,
        "resolve_cookbook_item_model",
        lambda: ("gpt-cookbook-test", "test"),
    )
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = "owner"

        response = client.post(
            "/api/jobs/cookbook-infer-missing-details",
            json={"cookbook_id": "dinner", "overwrite_ai_fields": True},
            headers={"X-Requested-With": "fetch"},
        )
        data = response.get_json()

    assert response.status_code == 202
    assert data["job"]["job_type"] == "cookbook-infer-missing-details"
    assert data["job"]["queue_name"] == "ai-pantry-light"
    assert data["job"]["model_env_var"] == "OPENAI_COOKBOOK_ITEM_MODEL"
    assert data["job"]["source_items"][0]["label"] == "Spring Roll"
    assert data["job"]["source_items"][0]["detail"] == "menu item"
    assert data["job"]["source_items"][0]["recipe_url"] == recipe_url


def test_cookbook_infer_missing_details_job_runs_estimate_and_decide_all(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    recipe_urls = ["menu-item://dinner/spring-roll", "menu-item://dinner/crab-wonton"]
    events = []

    monkeypatch.setattr(
        cookbook_item_inference_service,
        "recipe_context_from_cookbook",
        lambda cookbook_id: {
            "id": cookbook_id,
            "name": "Dinner",
            "recipes": [{"url": url, "name": url.rsplit("/", 1)[-1]} for url in recipe_urls],
        },
    )
    monkeypatch.setattr(
        cookbook_item_inference_service,
        "resolve_cookbook_item_model",
        lambda: ("gpt-cookbook-test", "test"),
    )
    progress_updates = []
    real_update_progress = job_tasks.update_job_progress

    def recording_update_progress(*args, **kwargs):
        progress_updates.append(kwargs)
        return real_update_progress(*args, **kwargs)

    monkeypatch.setattr(job_tasks, "update_job_progress", recording_update_progress)

    def fake_infer(cookbook_id, **kwargs):
        events.append(("infer", cookbook_id, kwargs.get("overwrite_ai_fields"), kwargs.get("preview_only")))
        progress_callback = kwargs.get("progress_callback")
        assert callable(progress_callback)
        progress_callback({
            "phase": "details",
            "event": "started",
            "recipe_url": recipe_urls[0],
            "recipe_name": "spring-roll",
            "index": 1,
            "total": 2,
        })
        return {
            "ok": True,
            "cookbook_id": cookbook_id,
            "cookbook_name": "Dinner",
            "total_found": 2,
            "updated": 2,
            "skipped": 0,
            "failed": 0,
            "results": [],
        }

    monkeypatch.setattr(cookbook_item_inference_service, "infer_missing_details_for_cookbook", fake_infer)
    monkeypatch.setattr(
        recipe_routes,
        "load_editable_recipe",
        lambda url: {"recipe": {"source_url": url, "recipe_title": url.rsplit("/", 1)[-1], "ingredients": [{"ingredient": "wrapper"}]}},
    )
    monkeypatch.setattr(recipe_routes, "_has_per_serving_estimate", lambda nutrition: False)

    def fake_estimate(recipe):
        events.append(("estimate", recipe["source_url"]))
        return {"ok": True, "nutrition": [{"key": "calories", "value": "100"}]}

    monkeypatch.setattr(recipe_routes, "estimate_recipe_nutrition", fake_estimate)
    monkeypatch.setattr(recipe_routes, "_menu_nutrition_inference_from_rows", lambda rows, model="": {"model": model})
    monkeypatch.setattr(recipe_routes, "save_editable_recipe", lambda url, recipe: {"ok": True})
    monkeypatch.setattr(
        cookbook_service,
        "cookbook_recipe_assignment_for_url",
        lambda url: {"cookbook_id": "dinner", "cookbook_name": "Dinner"},
    )

    def fake_category(url, recipe, assignment, trigger_source=""):
        events.append(("decide_all", url, trigger_source, assignment["cookbook_id"]))
        return {"ok": True, "categories": {"meal_type": "Dinner"}}

    monkeypatch.setattr(recipe_routes, "apply_imported_recipe_category_routine", fake_category)

    job = job_service.create_job(
        "cookbook-infer-missing-details",
        input_payload={"cookbook_id": "dinner", "overwrite_ai_fields": True},
        user_id="owner",
        total_items=2,
    )

    finished = job_tasks.run_cookbook_infer_missing_details_job(job["id"], job["input_payload"])

    assert finished["status"] == "completed"
    assert events == [
        ("infer", "dinner", True, False),
        ("estimate", recipe_urls[0]),
        ("estimate", recipe_urls[1]),
        ("decide_all", recipe_urls[0], "cookbook_infer:all", "dinner"),
        ("decide_all", recipe_urls[1], "cookbook_infer:all", "dinner"),
    ]
    assert finished["result_payload"]["nutrition_completed"] == 2
    assert finished["result_payload"]["categories_completed"] == 2
    detail_payloads = [
        update.get("result_payload", {})
        for update in progress_updates
        if isinstance(update.get("result_payload"), dict)
    ]
    assert any(
        payload.get("current_recipe_stage") == "details"
        and "spring-roll" in payload.get("current_recipe_detail", "")
        for payload in detail_payloads
    )
    assert any(
        payload.get("current_recipe_stage") == "nutrition"
        and "crab-wonton" in payload.get("current_recipe_detail", "")
        for payload in detail_payloads
    )
    assert any(
        payload.get("current_recipe_stage") == "categories"
        and "crab-wonton" in payload.get("current_recipe_detail", "")
        for payload in detail_payloads
    )


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


def test_job_queue_readiness_reports_missing_redis_dependency(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("JOB_QUEUE_THREAD_FALLBACK", "1")
    monkeypatch.setattr(
        job_queue_service,
        "_package_installed",
        lambda module_name: False if module_name == "redis" else True,
    )

    readiness = job_queue_service.redis_queue_readiness(check_connection=True)

    assert readiness["redis_package_installed"] is False
    assert readiness["rq_package_installed"] is True
    assert readiness["redis_url_configured"] is False
    assert readiness["redis_connection_succeeded"] is False
    assert readiness["reason"] == "missing_redis_package"
    assert readiness["mode"] == "local/thread"


def test_menu_import_enqueues_to_rq_menu_queue_when_redis_ready(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.delenv("JOB_QUEUE_MODE", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://example.test:6379/0")
    enqueued = {}

    class FakeQueue:
        def __init__(self, name, connection):
            enqueued["queue_name"] = name
            enqueued["connection"] = connection

        def enqueue(self, import_path, job_id, **kwargs):
            enqueued["import_path"] = import_path
            enqueued["job_id"] = job_id
            enqueued["kwargs"] = kwargs
            return type("FakeRQJob", (), {"id": "rq-job-1"})()

    monkeypatch.setattr(
        job_queue_service,
        "redis_queue_connection",
        lambda: ("redis-connection", FakeQueue),
    )

    job = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu"]},
        user_id="owner",
    )

    result = job_queue_service.enqueue_job(job["id"])
    saved = job_service.get_job(job["id"])

    assert result["ok"] is True
    assert result["mode"] == "rq"
    assert result["queue_name"] == "ai-pantry-menu"
    assert result["rq_job_id"] == "rq-job-1"
    assert enqueued["queue_name"] == "ai-pantry-menu"
    assert enqueued["import_path"] == "PushShoppingList.workers.job_worker.run_job"
    assert enqueued["job_id"] == job["id"]
    assert saved["rq_job_id"] == "rq-job-1"


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


def test_menu_generate_waits_for_source_menu_import_then_starts(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    source = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu"], "extraction_mode": "menu_extract"},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )
    job_service.update_job(source["id"], status="running", started_at=job_service.now_iso())
    queued = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": ["https://example.com/menu?menu_item=spring-roll"],
            "source_job_id": source["id"],
        },
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    waiting = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert waiting["deferred"] is True
    assert waiting["defer_reason"] == "waiting_for_menu_import"
    assert waiting["source_job_id"] == source["id"]
    assert waiting["source_job_status"] == "running"

    job_service.complete_job(source["id"], result_payload={"ok": True})
    started = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert started["started"] is True
    assert job_service.get_job(queued["id"])["status"] == "running"


def test_try_start_job_reports_running_lock_details(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    blockers = []
    for index in range(3):
        blocker = job_service.create_job(
            "menu-generate-recipes",
            input_payload={"recipe_urls": [f"https://example.com/menu?menu_item={index}"]},
            user_id="owner",
            queue_name="ai-pantry-menu",
        )
        job_service.update_job(blocker["id"], status="running", started_at=job_service.now_iso())
        blockers.append(blocker)
    queued = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": ["https://example.com/menu?menu_item=new"]},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    result = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert result["deferred"] is True
    assert result["defer_reason"] == "running_lock"
    assert result["lock_name"] == "menu-ai"
    assert result["lock_owner_job_id"] == blockers[0]["id"]
    assert isinstance(result["lock_age_seconds"], int)
    assert result["lock_stale"] is False


def test_try_start_job_cleans_stale_running_lock(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    blockers = []
    for index in range(3):
        blocker = job_service.create_job(
            "menu-generate-recipes",
            input_payload={"recipe_urls": [f"https://example.com/menu?menu_item={index}"]},
            user_id="owner",
            queue_name="ai-pantry-menu",
        )
        job_service.update_job(
            blocker["id"],
            status="running",
            started_at=job_service.now_iso(),
            completed_at=job_service.now_iso(),
        )
        blockers.append(blocker)
    queued = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": ["https://example.com/menu?menu_item=new"]},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    result = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert result["started"] is True
    assert job_service.get_job(queued["id"])["status"] == "running"
    assert job_service.get_job(blockers[0]["id"])["status"] == "failed"
    assert "Stale job lock cleared" in job_service.get_job(blockers[0]["id"])["current_step"]


def test_try_start_job_cleans_idle_menu_ai_lock_after_menu_timeout(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MENU_AI_LOCK_STALE_MINUTES", "1")
    real_now_iso = job_service.now_iso
    old_iso = (job_service.utc_now() - timedelta(minutes=2)).isoformat() + "Z"
    blockers = []

    monkeypatch.setattr(job_service, "now_iso", lambda: old_iso)
    for index in range(3):
        blocker = job_service.create_job(
            "menu-generate-recipes",
            input_payload={"recipe_urls": [f"https://example.com/menu?menu_item={index}"]},
            user_id="owner",
            queue_name="ai-pantry-menu",
        )
        job_service.update_job(
            blocker["id"],
            status="running",
            started_at=old_iso,
            worker_id="test-worker",
        )
        blockers.append(blocker)
    monkeypatch.setattr(job_service, "now_iso", real_now_iso)

    queued = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": ["https://example.com/menu?menu_item=new"]},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    result = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert result["started"] is True
    assert job_service.get_job(queued["id"])["status"] == "running"
    assert all(job_service.get_job(blocker["id"])["status"] == "failed" for blocker in blockers)


def test_menu_generate_defer_limit_exceeded(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("MENU_GENERATE_RECIPES_MAX_DEFER_ATTEMPTS", "1")
    source = job_service.create_job(
        "menu-import",
        input_payload={"urls": ["https://example.com/menu"], "extraction_mode": "menu_extract"},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )
    job_service.update_job(source["id"], status="running", started_at=job_service.now_iso())
    queued = job_service.create_job(
        "menu-generate-recipes",
        input_payload={
            "recipe_urls": ["https://example.com/menu?menu_item=spring-roll"],
            "source_job_id": source["id"],
        },
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    first = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")
    second = job_service.try_start_job(queued["id"], queue_name="ai-pantry-menu")

    assert first["deferred"] is True
    assert second["ok"] is False
    assert second["defer_limit_exceeded"] is True
    assert second["defer_reason"] == "waiting_for_menu_import"
    assert "max_defer_attempts=1" in second["error"]


def test_enqueue_without_redis_uses_single_local_thread(monkeypatch, tmp_path):
    configure_job_paths(monkeypatch, tmp_path)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("JOB_QUEUE_THREAD_FALLBACK", "1")
    monkeypatch.setattr(
        job_queue_service,
        "redis_queue_connection",
        lambda: (_ for _ in ()).throw(AssertionError("Redis should not be contacted without REDIS_URL")),
    )
    monkeypatch.setattr(job_queue_service, "_ACTIVE_THREAD_JOB_IDS", set())
    monkeypatch.setattr(job_queue_service, "_REDIS_NOT_CONFIGURED_LOGGED", False)
    started_threads = []

    class FakeThread:
        def __init__(self, target, args=(), name="", daemon=False):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            started_threads.append(self.name)

    monkeypatch.setattr(job_queue_service.threading, "Thread", FakeThread)
    job = job_service.create_job(
        "menu-generate-recipes",
        input_payload={"recipe_urls": ["https://example.com/menu?menu_item=spring-roll"]},
        user_id="owner",
        queue_name="ai-pantry-menu",
    )

    first = job_queue_service.enqueue_job(job["id"])
    second = job_queue_service.enqueue_job(job["id"])

    assert first["ok"] is True
    assert first["mode"] == "thread"
    assert first["reason"] == "redis_not_configured"
    assert second["ok"] is True
    assert second["already_running"] is True
    assert started_threads == [f"job-worker-{job['id'][:8]}"]


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
