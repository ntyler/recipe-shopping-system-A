import sqlite3
from types import SimpleNamespace

import pytest

from PushShoppingList.app import create_app
from PushShoppingList.routes import main_routes
from PushShoppingList.services import job_queue_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_ingredient_requirement_service as requirements


TEST_SECRET = "performance-regression-test-session-key-2026-08-14"


def test_requirement_reads_reuse_one_connection_per_request_and_close_it(
    monkeypatch,
    tmp_path,
):
    db_path = tmp_path / "recipe-master.sqlite3"
    original_connect = sqlite3.connect
    with original_connect(str(db_path)) as connection:
        connection.execute("CREATE TABLE probe (value INTEGER NOT NULL)")
        connection.execute("INSERT INTO probe (value) VALUES (1)")

    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(db_path))
    opened = []
    target_uri = db_path.resolve().as_uri().lower()

    def traced_connect(database, *args, **kwargs):
        connection = original_connect(database, *args, **kwargs)
        if target_uri in str(database).lower():
            opened.append(connection)
        return connection

    monkeypatch.setattr(requirements.sqlite3, "connect", traced_connect)
    app = create_app({"TESTING": True, "SECRET_KEY": TEST_SECRET})

    @app.get("/__test/requirement-connection")
    def requirement_connection_probe():
        with requirements._existing_requirement_connection() as first:
            assert first.execute("SELECT value FROM probe").fetchone()[0] == 1
        with requirements._existing_requirement_connection() as second:
            assert second.execute("SELECT value FROM probe").fetchone()[0] == 1
        return {"same_connection": first is second}

    response = app.test_client().get("/__test/requirement-connection")

    assert response.status_code == 200
    assert response.get_json()["same_connection"] is True
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        opened[0].execute("SELECT 1")


def test_saved_recipe_output_cache_avoids_duplicate_reads_and_returns_copies(monkeypatch):
    calls = []

    def fake_load(recipe_url, *, equipment_consumer):
        calls.append((recipe_url, equipment_consumer))
        return {
            "source_url": recipe_url,
            "ingredients": [{"ingredient": "synthetic"}],
        }

    monkeypatch.setattr(main_routes, "load_recipe_output", fake_load)
    app = create_app({"TESTING": True, "SECRET_KEY": TEST_SECRET})

    with app.test_request_context("/"):
        first = main_routes.load_saved_recipe_output("https://synthetic.invalid/one")
        first["ingredients"][0]["ingredient"] = "mutated"
        second = main_routes.load_saved_recipe_output("https://synthetic.invalid/one")

    assert calls == [
        ("https://synthetic.invalid/one", "recipe_display"),
    ]
    assert second["ingredients"][0]["ingredient"] == "synthetic"


def test_thread_fallback_is_opt_in_even_in_development(monkeypatch):
    monkeypatch.delenv("JOB_QUEUE_THREAD_FALLBACK", raising=False)
    monkeypatch.setenv("SHOPPING_APP_ENV", "development")

    assert job_queue_service.thread_fallback_enabled() is False

    monkeypatch.setenv("JOB_QUEUE_THREAD_FALLBACK", "1")
    assert job_queue_service.thread_fallback_enabled() is True

    monkeypatch.setenv("SHOPPING_APP_ENV", "production")
    assert job_queue_service.thread_fallback_enabled() is False

    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")
    assert job_queue_service.inline_jobs_enabled() is False


def test_vision_client_uses_bounded_timeout_and_disables_nested_sdk_retries(monkeypatch):
    sentinel = object()
    options = []

    class FakeClient:
        def with_options(self, **kwargs):
            options.append(kwargs)
            return sentinel

    monkeypatch.setattr(recipe_extract_service, "get_openai_client", FakeClient)

    assert recipe_extract_service.openai_vision_client() is sentinel
    assert options == [{
        "timeout": min(120, max(5, recipe_extract_service.VISION_REQUEST_TIMEOUT_SECONDS)),
        "max_retries": 0,
    }]


def test_vision_request_uses_the_bounded_shared_client(monkeypatch, tmp_path):
    image_path = tmp_path / "synthetic.jpg"
    image_path.write_bytes(b"synthetic-image-bytes")
    sentinel_client = object()
    observed_clients = []
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"items": []}'))],
    )

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        recipe_extract_service,
        "normalize_image_bytes_for_openai",
        lambda *_args, **_kwargs: (b"normalized-image", "image/jpeg", {}),
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "openai_vision_client",
        lambda: sentinel_client,
    )

    def fake_completion(client, _payload, **_kwargs):
        observed_clients.append(client)
        return response

    monkeypatch.setattr(
        recipe_extract_service,
        "throttled_chat_completion",
        fake_completion,
    )
    monkeypatch.setattr(recipe_extract_service, "record_openai_usage", lambda *_args, **_kwargs: None)

    result = recipe_extract_service.call_openai_vision_image(
        image_path,
        "Synthetic prompt.",
        "synthetic-vision-test",
        preferred_model="gpt-4o-mini",
    )

    assert result.ok is True
    assert observed_clients == [sentinel_client]
