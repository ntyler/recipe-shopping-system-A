"""Repository-wide deterministic Flask session configuration for tests."""

import os

import pytest


os.environ["SHOPPING_APP_ENV"] = "testing"
os.environ["SHOPPING_APP_SECRET_KEY"] = (
    "tests-only-deterministic-session-signing-key-2026-08-04"
)


@pytest.fixture(autouse=True)
def isolate_recipe_master_database(monkeypatch, tmp_path):
    """Never let a test touch the live recipe master SQLite database."""
    from PushShoppingList.services import recipe_master_data_service

    monkeypatch.delenv("SHOPPING_APP_RECIPE_MASTER_DB", raising=False)
    monkeypatch.setattr(
        recipe_master_data_service,
        "RECIPE_MASTER_DB_PATH",
        tmp_path / "recipe_master.sqlite3",
    )
