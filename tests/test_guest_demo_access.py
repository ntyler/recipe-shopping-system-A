from datetime import timedelta

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import storage_service


def configure_guest_demo_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(guest_session_service, "GUEST_SESSIONS_FILE", tmp_path / "guest_sessions.json")
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")


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


def test_guest_routes_block_sensitive_surfaces(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")

        pantry = client.post("/pantry/items/add", data={"ingredient_name": "Milk"})
        assert pantry.status_code == 302
        assert pantry.headers["Location"].endswith("/#userAccountSection")

        usage = client.get("/api/openai_usage_dashboard")
        assert usage.status_code == 403
        assert usage.get_json()["guest_restricted"] is True

        home = client.post("/save_home_address", data={"address_city": "Indianapolis"})
        assert home.status_code == 302
        assert home.headers["Location"].endswith("/#userAccountSection")

        store = client.post("/update_store/aldi", data={"username": "demo", "password": "secret"})
        assert store.status_code == 302
        assert store.headers["Location"].endswith("/#userAccountSection")


def test_logout_clears_guest_session_and_cookie(monkeypatch, tmp_path):
    configure_guest_demo_paths(monkeypatch, tmp_path)
    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        client.get("/guest/start")
        response = client.get("/logout")

        assert response.status_code == 302
        assert "guest_demo_session=;" in response.headers.get("Set-Cookie", "")
        with client.session_transaction() as session:
            assert "is_guest" not in session
            assert "guest_session_id" not in session
