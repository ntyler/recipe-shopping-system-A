import hashlib
import json
import sqlite3

import pytest

from PushShoppingList.app import create_app
from PushShoppingList.services import guest_session_service
from PushShoppingList.services import ingredient_duplicate_review_service as duplicate_reviews
from PushShoppingList.services import ingredient_type_service
from PushShoppingList.services import recipe_master_data_service as master_data
from PushShoppingList.services import recipe_master_image_service as master_images
from PushShoppingList.services import storage_service
from PushShoppingList.services import user_account_service


def database_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlite_sequences(path):
    with sqlite3.connect(path) as connection:
        return dict(connection.execute("SELECT name, seq FROM sqlite_sequence"))


def configure_master_db(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)
    return db_path


def initialize_master_db(db_path):
    with master_data.recipe_master_connection():
        pass
    assert db_path.is_file()


def test_missing_database_read_services_use_nonpersistent_defaults(monkeypatch, tmp_path):
    db_path = configure_master_db(monkeypatch, tmp_path)

    assert master_data.read_workspace_unit_registry("user-a") is None
    assert master_data.workspace_unit_registry_with_usage("user-a")["units"]
    assert ingredient_type_service.ingredient_type_registry_payload("user-a")["types"]
    assert master_data.ingredient_store_section_details("user-a")
    assert master_data.list_master_records("ingredients", user_id="user-a") == []
    assert master_data.master_record_for_name("ingredients", "user-a", "onion") is None
    assert duplicate_reviews.list_duplicate_reviews("user-a") == []
    assert master_images.missing_master_image_rows(user_id="user-a") == []
    assert not db_path.exists()


def test_incomplete_schema_read_services_fail_closed_without_repair(monkeypatch, tmp_path):
    db_path = configure_master_db(monkeypatch, tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    before = database_sha256(db_path)

    assert master_data.read_workspace_unit_registry("user-a") is None
    assert master_data.workspace_unit_registry_with_usage("user-a")["units"]
    assert ingredient_type_service.ingredient_type_registry_payload("user-a")["types"]
    assert master_data.ingredient_store_section_details("user-a")
    assert master_data.list_master_records("equipment", user_id="user-a") == []
    assert master_data.recipe_master_user_ids() == []
    assert database_sha256(db_path) == before


def test_recipe_master_read_services_open_only_query_only_connections(
    monkeypatch,
    tmp_path,
):
    db_path = configure_master_db(monkeypatch, tmp_path)
    initialize_master_db(db_path)
    master_data.ensure_workspace_unit_registry("user-a")
    ingredient_type_service.save_workspace_ingredient_type(
        {"name": "Preparation", "active": True},
        user_id="user-a",
    )
    master_data.ingredient_store_section_details(
        "user-a",
        include_inactive=True,
        create=True,
    )
    before = database_sha256(db_path)
    sequences_before = sqlite_sequences(db_path)

    original_connect = sqlite3.connect
    opened = []
    statements = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        target = str(args[0]) if args else ""
        if "recipe_master.sqlite3" in target:
            opened.append({"target": target, "uri": bool(kwargs.get("uri"))})
            connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(master_data.sqlite3, "connect", traced_connect)

    master_data.read_workspace_unit_registry("user-a")
    master_data.workspace_unit_registry_with_usage("user-a")
    master_data.workspace_unit_recipe_references("volume_teaspoon", "user-a")
    master_data.validate_workspace_unit_candidate(
        {
            "canonical_name": "scoop",
            "category": "count_package",
            "aliases": ["scoops"],
        },
        user_id="user-a",
    )
    ingredient_type_service.ingredient_type_registry_payload(
        "user-a",
        include_usage=True,
    )
    ingredient_type_service.workspace_ingredient_type_recipe_references(
        "main",
        "user-a",
    )
    master_data.ingredient_store_section_details("user-a", include_inactive=True)
    master_data.list_master_records("ingredients", user_id="user-a")
    master_data.count_master_records("ingredients", user_id="user-a")
    master_data.equipment_summary_counts(user_id="user-a")
    master_data.recipe_master_user_ids()
    duplicate_reviews.duplicate_scan_summary("user-a")
    duplicate_reviews.list_duplicate_reviews("user-a")
    duplicate_reviews.list_duplicate_decision_history("user-a")
    master_images.missing_master_image_rows(user_id="user-a")

    assert opened
    assert all(item["uri"] and "mode=ro" in item["target"] for item in opened)
    normalized_statements = [" ".join(statement.upper().split()) for statement in statements]
    assert any(statement == "PRAGMA QUERY_ONLY=ON" for statement in normalized_statements)
    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "REPLACE ",
        "CREATE ",
        "ALTER ",
        "DROP ",
        "BEGIN ",
        "COMMIT",
        "VACUUM",
        "REINDEX",
    )
    assert not any(
        any(token in statement for token in forbidden)
        for statement in normalized_statements
    )
    assert database_sha256(db_path) == before
    assert sqlite_sequences(db_path) == sequences_before


@pytest.fixture
def read_path_app(monkeypatch, tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(
        json.dumps({
            "users": [{
                "user_id": "user-a",
                "username": "user-a",
                "email": "user-a@example.com",
                "account_status": "active",
            }],
        }),
        encoding="utf-8",
    )
    db_path = configure_master_db(monkeypatch, tmp_path)
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    monkeypatch.setattr(storage_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setattr(user_account_service, "USERS_FILE", users_file)
    monkeypatch.setattr(
        guest_session_service,
        "GUEST_SESSIONS_FILE",
        tmp_path / "guest_sessions.json",
    )
    monkeypatch.setattr(guest_session_service, "GUEST_DATA_DIR", tmp_path / "guests")
    monkeypatch.setenv("JOB_QUEUE_MODE", "inline")

    initialize_master_db(db_path)
    app = create_app()
    app.config.update(TESTING=True)
    return app, db_path


def test_master_data_get_matrix_is_database_immutable(read_path_app):
    app, db_path = read_path_app
    before = database_sha256(db_path)
    sequences_before = sqlite_sequences(db_path)
    paths = (
        "/admin/master-data/ingredients",
        "/admin/master-data/equipment",
        "/admin/master-data/units",
        "/admin/master-data/types",
        "/admin/master-data/store-sections",
        "/api/master-data/units",
        "/api/master-data/types",
        "/api/master-data/ingredients/options",
        "/api/master-data/ingredients/duplicate-reviews",
        "/api/master-data/ingredients/duplicate-reviews/history",
        "/api/master-data/ingredients/reclassify-misc/undo-preview",
        "/api/master-data/ingredients/merges/undo-preview",
    )

    with app.test_client() as client:
        with client.session_transaction() as active_session:
            active_session["user_id"] = "user-a"
        responses = [client.get(path, follow_redirects=True) for path in paths]

    assert all(response.status_code < 500 for response in responses)
    assert database_sha256(db_path) == before
    assert sqlite_sequences(db_path) == sequences_before


def test_store_section_undo_preview_with_history_is_query_only(
    monkeypatch,
    tmp_path,
):
    db_path = configure_master_db(monkeypatch, tmp_path)
    master_data.sync_recipe_master_records(
        "https://example.test/read-only-undo-preview",
        recipe_data={"ingredients": [{
            "ingredient": "Ground ginger",
            "store_section": "MISC",
        }]},
        user_id="user-a",
    )
    ingredient = master_data.master_record_for_name(
        "ingredients",
        "user-a",
        "ground ginger",
    )
    with master_data.recipe_master_connection() as connection:
        connection.execute(
            """
            UPDATE ingredients
               SET store_section = 'MISC', store_section_user_confirmed = 0
             WHERE id = ? AND user_id = 'user-a'
            """,
            (ingredient["id"],),
        )
        connection.execute(
            """
            UPDATE recipe_ingredients
               SET store_section = 'MISC', store_section_user_confirmed = 0
             WHERE ingredient_id = ? AND user_id = 'user-a'
            """,
            (ingredient["id"],),
        )
    applied = master_data.apply_misc_ingredient_store_section_decisions(
        "user-a",
        [{
            "ingredient_id": ingredient["id"],
            "store_section": "Spices",
            "decision_source": "deterministic",
            "confidence": 1,
        }],
    )
    assert applied["ok"] is True

    before = database_sha256(db_path)
    sequences_before = sqlite_sequences(db_path)
    original_connect = sqlite3.connect
    opened = []
    statements = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        target = str(args[0]) if args else ""
        if "recipe_master.sqlite3" in target:
            opened.append({"target": target, "uri": bool(kwargs.get("uri"))})
            connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(master_data.sqlite3, "connect", traced_connect)
    preview = master_data.ingredient_store_section_reclassification_undo_preview(
        "user-a",
        batch_id=applied["batch_id"],
        ingredient_id=ingredient["id"],
    )

    assert preview["ok"] is True
    assert opened
    assert all(item["uri"] and "mode=ro" in item["target"] for item in opened)
    assert all(
        not " ".join(statement.upper().split()).startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ", "CREATE ")
        )
        for statement in statements
    )
    assert database_sha256(db_path) == before
    assert sqlite_sequences(db_path) == sequences_before


def test_explicit_mutations_still_initialize_and_seed_transactionally(
    monkeypatch,
    tmp_path,
):
    db_path = configure_master_db(monkeypatch, tmp_path)

    units = master_data.ensure_workspace_unit_registry("user-a")
    created_type = ingredient_type_service.save_workspace_ingredient_type(
        {"name": "Preparation", "active": True},
        user_id="user-a",
    )
    sections = master_data.ingredient_store_section_details(
        "user-a",
        include_inactive=True,
        create=True,
    )

    assert units["units"]
    assert created_type["ok"] is True
    assert sections
    assert db_path.is_file()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM canonical_units"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM workspace_units WHERE user_id = 'user-a'"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM workspace_ingredient_types WHERE user_id = 'user-a'"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM ingredient_store_sections WHERE user_id = 'user-a'"
        ).fetchone()[0] > 0
