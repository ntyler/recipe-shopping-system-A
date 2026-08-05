from PushShoppingList.app import create_app
from PushShoppingList.routes import job_routes
from PushShoppingList.routes import menu_routes
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def registered_user(user_id, *, admin=False):
    return {
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "username": user_id,
        "account_status": "active",
        "admin_access_enabled": admin,
    }


def configure_registered_users(monkeypatch, tmp_path, *users):
    monkeypatch.setattr(user_account_service, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    user_account_service.save_users({"users": list(users)})


def sign_in(client, user_id):
    with client.session_transaction() as signed_session:
        signed_session["user_id"] = user_id


def assert_private_no_store(response):
    assert response.headers.get("Cache-Control") == "private, no-store"
    assert response.headers.get("Pragma") == "no-cache"


def test_recent_jobs_rejects_duplicate_scope_and_non_admin_all(monkeypatch, tmp_path):
    regular = registered_user("regular-user")
    admin = registered_user("admin-user", admin=True)
    configure_registered_users(monkeypatch, tmp_path, regular, admin)
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    job_service.create_job("recipe-import", user_id="regular-user")
    job_service.create_job("recipe-import", user_id="admin-user")

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        sign_in(client, "regular-user")

        duplicate = client.get("/api/jobs/recent?scope=mine&scope=all")
        forbidden = client.get("/api/jobs/recent?scope=all")
        mine = client.get("/api/jobs/recent")

        sign_in(client, "admin-user")
        all_jobs = client.get("/api/jobs/recent?scope=all")

    assert duplicate.status_code == 400
    assert forbidden.status_code == 403
    assert mine.status_code == 200
    assert {job["user_id"] for job in mine.get_json()["jobs"]} == {"regular-user"}
    assert all_jobs.status_code == 200
    assert {job["user_id"] for job in all_jobs.get_json()["jobs"]} == {
        "regular-user",
        "admin-user",
    }
    for response in (duplicate, forbidden, mine, all_jobs):
        assert_private_no_store(response)


def test_debug_job_queue_requires_admin_and_explicit_nonproduction_environment(monkeypatch, tmp_path):
    regular = registered_user("regular-user")
    admin = registered_user("admin-user", admin=True)
    configure_registered_users(monkeypatch, tmp_path, regular, admin)
    monkeypatch.setattr(
        job_routes,
        "redis_queue_readiness",
        lambda check_connection=True: {"mode": "test", "checked": check_connection},
    )

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        sign_in(client, "regular-user")
        regular_response = client.get("/api/debug/job-queue")

        sign_in(client, "admin-user")
        admin_response = client.get("/api/debug/job-queue")

        app.config.update(
            TESTING=False,
            DEBUG=False,
            SHOPPING_APP_ENV="production",
        )
        production_response = client.get("/api/debug/job-queue")

    assert regular_response.status_code == 403
    assert admin_response.status_code == 200
    assert production_response.status_code == 404
    for response in (regular_response, admin_response, production_response):
        assert_private_no_store(response)


def test_menu_import_status_only_returns_the_requested_workspace_job(monkeypatch, tmp_path):
    user = registered_user("menu-user")
    configure_registered_users(monkeypatch, tmp_path, user)
    monkeypatch.setattr(
        menu_routes,
        "load_progress",
        lambda: {
            "job_id": "current-job",
            "status": "running",
            "summary": "Extracting menu",
        },
    )

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        sign_in(client, "menu-user")
        current = client.get("/menu-import/status/current-job")
        unrelated = client.get("/menu-import/status/other-job")

    assert current.status_code == 200
    assert current.get_json()["progress"]["job_id"] == "current-job"
    assert unrelated.status_code == 404
    assert "progress" not in unrelated.get_json()
    assert_private_no_store(current)
    assert_private_no_store(unrelated)
