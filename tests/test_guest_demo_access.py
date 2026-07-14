from datetime import timedelta

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import job_service
from PushShoppingList.services import storage_service


def configure_guest_demo_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(job_service, "JOBS_DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")


def guest_sessions_payload():
    return guest_session_service.load_guest_sessions()


def test_guest_start_creates_24_hour_session_cookie_and_flags(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        response = client.get("/guest/start")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#userAccountSection")
        assert "guest_demo_session=" in response.headers.get("Set-Cookie", "")
        assert "Max-Age=86400" in response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in response.headers.get("Set-Cookie", "")
        assert "SameSite=Lax" in response.headers.get("Set-Cookie", "")

        with client.session_transaction() as session:
            assert session["is_guest"] is True
            guest_session_id = session["guest_session_id"]
            assert guest_session_id
            assert "user_id" not in session

    records = guest_sessions_payload()["guest_sessions"]
    assert len(records) == 1
    assert records[0]["id"] == guest_session_id
    assert records[0]["is_active"] is True
    assert (tmp_path / "guests" / guest_session_id).is_dir()


def test_guest_start_reuses_remembered_session_and_index_restores_it(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        with client.session_transaction() as session:
            first_guest_session_id = session["guest_session_id"]
            session.clear()

        restored = client.get("/")
        assert restored.status_code == 200
        with client.session_transaction() as session:
            assert session["is_guest"] is True
            assert session["guest_session_id"] == first_guest_session_id

        client.get("/guest/start")
        with client.session_transaction() as session:
            assert session["guest_session_id"] == first_guest_session_id

    records = guest_sessions_payload()["guest_sessions"]
    assert [record["id"] for record in records] == [first_guest_session_id]


def test_guest_account_page_shows_countdown_and_delete_button(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        response = client.get("/")
        html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Demo auto-deletes in" in html
    assert "data-guest-countdown" in html
    assert "data-guest-expires-at=" in html
    assert "Delete Demo Session" in html
    assert "/guest/delete" in html
    assert "Create Full Account" in html
    assert 'data-guest-auth-choice="create"' in html
    assert 'data-guest-auth-choice="sign-in"' in html
    assert 'id="firebaseCreateAccountForm"' in html
    assert 'data-guest-auth-form="create" hidden' in html
    assert 'id="firebaseSignInForm"' in html
    assert 'data-guest-auth-form="sign-in" hidden' in html


def test_expired_remembered_guest_redirects_to_expired_and_clears_cookie(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        payload = guest_sessions_payload()
        guest_session_id = payload["guest_sessions"][0]["id"]
        expired_at = guest_session_service.now_utc() - timedelta(minutes=1)
        payload["guest_sessions"][0]["expires_at"] = expired_at.isoformat() + "Z"
        guest_session_service.save_guest_sessions(payload)

        with client.session_transaction() as session:
            session.clear()

        response = client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/guest/expired")
        assert "guest_demo_session=;" in response.headers.get("Set-Cookie", "")

    payload = guest_sessions_payload()
    assert payload["guest_sessions"][0]["is_active"] is False
    assert not (tmp_path / "guests" / guest_session_id).exists()


def test_cleanup_deletes_only_expired_guest_data(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    guest_payload = {"guest_sessions": []}
    expired = guest_session_service.create_guest_session(guest_payload)
    active = guest_session_service.create_guest_session(guest_payload)
    payload = guest_sessions_payload()
    payload["guest_sessions"][0]["expires_at"] = (guest_session_service.now_utc() - timedelta(minutes=1)).isoformat() + "Z"
    guest_session_service.save_guest_sessions(payload)

    expired_file = tmp_path / "guests" / expired["id"] / "recipe-extractor" / "data" / "output" / "demo.json"
    expired_file.parent.mkdir(parents=True, exist_ok=True)
    expired_file.write_text("temporary", encoding="utf-8")
    active_file = tmp_path / "guests" / active["id"] / "keep.txt"
    active_file.write_text("active", encoding="utf-8")
    real_user_file = tmp_path / "users" / "real-user" / "shopping_list.txt"
    real_user_file.parent.mkdir(parents=True, exist_ok=True)
    real_user_file.write_text("real data", encoding="utf-8")

    guest_session_service.cleanup_expired_guest_sessions()

    assert not expired_file.exists()
    assert active_file.exists()
    assert real_user_file.exists()
    payload = guest_sessions_payload()
    assert payload["guest_sessions"][0]["is_active"] is False
    assert payload["guest_sessions"][1]["is_active"] is True


def test_guest_session_can_use_temporary_workspace_controls(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")

        pantry = client.post("/pantry/items/add", data={"ingredient_name": "Milk"})
        assert pantry.status_code == 302
        assert pantry.headers["Location"].endswith("/#aiPantryInventory")

        progress = client.post(
            "/api/start_extract_progress",
            json={"urls": ["https://example.com/recipe"], "job_id": "guest-import-job"},
            headers={"X-Requested-With": "fetch"},
        )
        assert progress.status_code == 200
        assert progress.get_json()["job_id"] == "guest-import-job"

        home = client.post(
            "/save_home_address",
            data={"ajax": "1", "address_city": "Indianapolis"},
            headers={"X-Requested-With": "fetch"},
        )
        assert home.status_code == 200
        assert home.get_json()["home_address"]["city"] == "Indianapolis"

        store = client.post(
            "/save_store_settings",
            data={"ajax": "1", "enabled_stores": "aldi"},
            headers={"X-Requested-With": "fetch"},
        )
        assert store.status_code == 200
        assert store.get_json()["enabled_stores"] == ["aldi"]


def test_guest_session_hides_move_bought_items_to_pantry_action(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")

        response = client.get("/sections/recipe-view")

    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Move Bought Items to Pantry" not in html
    assert "move-bought-pantry-btn" not in html


def test_guest_session_can_run_recipe_url_import_api(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)

    from PushShoppingList.routes import recipe_routes

    recipe_url = "https://example.com/demo-recipe"
    monkeypatch.setattr(
        recipe_routes,
        "extract_recipe_from_url",
        lambda url, progress_callback=None: {
            "ok": True,
            "display_name": "Guest Demo Pretzels",
            "recipe_title": "Guest Demo Pretzels",
            "ingredients": ["1 cup flour"],
            "source_url": url,
        },
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment: {"ok": True, "status": "skipped"},
    )
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", lambda url: {"ok": True})
    monkeypatch.setattr(recipe_routes, "schedule_generated_recipe_pdf_creation", lambda url, context="": {"ok": True})

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        client.post(
            "/api/start_extract_progress",
            json={"urls": [recipe_url], "job_id": "guest-import-job"},
            headers={"X-Requested-With": "fetch"},
        )

        response = client.post(
            "/api/extract_recipe",
            json={
                "url": recipe_url,
                "urls": [recipe_url],
                "job_id": "guest-import-job",
                "index": 0,
            },
            headers={"X-Requested-With": "fetch"},
        )

    data = response.get_json()
    guest_files = list((tmp_path / "guests").glob("*/recipe-extractor/data/output/*.json"))
    job = data["job"]
    result = job["result_payload"]

    assert response.status_code == 202
    assert data["ok"] is True
    assert data["queued"] is True
    assert job["status"] == "completed"
    assert result["ok"] is True
    assert result["created_count"] == 1
    assert result["recipe_urls"] == [recipe_url]
    assert guest_files


def test_session_scoped_demo_account_can_run_recipe_url_import_api(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)

    from PushShoppingList.routes import recipe_routes

    demo_user_id = "demo-session-account"
    recipe_url = "https://example.com/demo-session-recipe"
    monkeypatch.setattr(
        recipe_routes,
        "extract_recipe_from_url",
        lambda url, progress_callback=None: {
            "ok": True,
            "display_name": "Demo Session Pretzels",
            "recipe_title": "Demo Session Pretzels",
            "ingredients": ["1 cup flour"],
            "source_url": url,
        },
    )
    monkeypatch.setattr(
        recipe_routes,
        "apply_imported_recipe_category_routine",
        lambda url, result, assignment: {"ok": True, "status": "skipped"},
    )
    monkeypatch.setattr(recipe_routes, "create_source_url_pdf", lambda url: {"ok": True})
    monkeypatch.setattr(recipe_routes, "schedule_generated_recipe_pdf_creation", lambda url, context="": {"ok": True})

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = demo_user_id

        page = client.get("/")
        progress = client.post(
            "/api/start_extract_progress",
            json={"urls": [recipe_url], "job_id": "demo-session-import-job"},
            headers={"X-Requested-With": "fetch"},
        )
        response = client.post(
            "/api/extract_recipe",
            json={
                "url": recipe_url,
                "urls": [recipe_url],
                "job_id": "demo-session-import-job",
                "index": 0,
            },
            headers={"X-Requested-With": "fetch"},
        )

    data = response.get_json()
    user_files = list((tmp_path / "users" / demo_user_id).glob("recipe-extractor/data/output/*.json"))
    job = data["job"]
    result = job["result_payload"]

    assert page.status_code == 200
    assert progress.status_code == 200
    assert response.status_code == 202
    assert data["ok"] is True
    assert data["queued"] is True
    assert job["status"] == "completed"
    assert result["ok"] is True
    assert result["created_count"] == 1
    assert result["recipe_urls"] == [recipe_url]
    assert user_files


def test_guest_session_still_blocks_account_and_admin_surfaces(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")

        profile = client.post("/account/profile", data={"display_name": "Demo"})
        assert profile.status_code == 302
        assert profile.headers["Location"].endswith("/#userAccountSection")

        store_admin = client.post(
            "/add_store",
            data={"ajax": "1", "store_label": "Target", "store_url": "https://target.example/search?q="},
            headers={"X-Requested-With": "fetch"},
        )
        assert store_admin.status_code == 403
        assert store_admin.get_json()["guest_restricted"] is True


def test_logout_clears_guest_session_and_cookie(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        with client.session_transaction() as session:
            guest_session_id = session["guest_session_id"]
        guest_file = tmp_path / "guests" / guest_session_id / "shopping_list.txt"
        guest_file.write_text("temporary item", encoding="utf-8")

        response = client.get("/logout")

        assert response.status_code == 302
        assert response.headers["Location"] == "/"
        assert "guest_demo_session=;" in response.headers.get("Set-Cookie", "")
        assert not guest_file.exists()
        with client.session_transaction() as session:
            assert "is_guest" not in session
            assert "guest_session_id" not in session


def test_guest_delete_route_removes_temp_demo_session(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        with client.session_transaction() as session:
            guest_session_id = session["guest_session_id"]

        guest_file = tmp_path / "guests" / guest_session_id / "shopping_list.txt"
        guest_file.write_text("temporary item", encoding="utf-8")

        response = client.post("/guest/delete")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/#userAccountSection")
        assert "guest_demo_session=;" in response.headers.get("Set-Cookie", "")
        assert not guest_file.exists()

        with client.session_transaction() as session:
            assert "is_guest" not in session
            assert "guest_session_id" not in session

    payload = guest_sessions_payload()
    assert payload["guest_sessions"][0]["is_active"] is False
