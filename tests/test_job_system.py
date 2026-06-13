from PushShoppingList.app import create_app
from PushShoppingList.routes import job_routes
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
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
        lambda job_id: {"ok": True, "mode": "test", "job_id": job_id},
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
    )

    payload = job_service.job_for_client(job)

    assert payload["model_used"] == "gpt-5.5"
    assert payload["model_source"] == "env:OPENAI_MENU_MODEL"
    assert payload["model_env_var"] == "OPENAI_MENU_MODEL"
    assert payload["source_items"] == [
        {
            "type": "file",
            "label": "menu.pdf",
            "detail": "",
        }
    ]
    assert "input_payload" not in payload
    assert str(upload_path) not in str(payload)


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
