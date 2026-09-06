import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from PushShoppingList.services import ingredient_type_service as types
from PushShoppingList.services import recipe_master_data_service as master_data


@pytest.fixture
def type_database(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(db_path))
    return db_path


def stored_rows(db_path):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT * FROM workspace_ingredient_types ORDER BY user_id, id"
        ).fetchall()


def test_moves_keep_complete_order_append_new_types_and_preserve_other_workspaces(type_database):
    types.save_workspace_ingredient_type({"name": "Extra"}, user_id="other")
    other = types.ingredient_type_registry_payload("other")
    result = types.move_workspace_ingredient_type("substitute", 1, user_id="mine")
    assert result["ok"] and result["changed"]
    items = types.ingredient_type_registry_payload("mine")["types"]
    assert [item["id"] for item in items] == ["substitute", "main", "optional", "garnish", "topping", "sauce"]
    assert [item["sort_order"] for item in items] == list(range(6))
    assert types.ingredient_type_registry_payload("other") == other
    created = types.save_workspace_ingredient_type({"name": "Finishing"}, user_id="mine")
    assert created["registry"]["types"][-1]["sort_order"] == 6
    assert created["registry"]["types"][-1]["id"] == created["type_id"]

    types.move_workspace_ingredient_type("substitute", 999, user_id="mine")
    assert types.ingredient_type_registry_payload("mine")["types"][-1]["id"] == "substitute"
    types.move_workspace_ingredient_type("substitute", 0, user_id="mine")
    before = stored_rows(type_database)
    assert not types.move_workspace_ingredient_type("substitute", 1, user_id="mine")["changed"]
    assert stored_rows(type_database) == before


def test_mid_reorder_database_failure_rolls_back_every_position(type_database):
    types.save_workspace_ingredient_type({"name": "Extra"}, user_id="mine")
    before = stored_rows(type_database)
    with sqlite3.connect(type_database) as connection:
        connection.execute("""
            CREATE TRIGGER fail_mid_order BEFORE UPDATE OF sort_order ON workspace_ingredient_types
            WHEN NEW.id = 'garnish'
            BEGIN SELECT RAISE(ABORT, 'injected order failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="injected order failure"):
        types.move_workspace_ingredient_type("sauce", 1, user_id="mine")
    assert stored_rows(type_database) == before


def legacy_table(connection, with_order=True):
    connection.row_factory = sqlite3.Row
    order_column = "sort_order INTEGER," if with_order else ""
    connection.execute(f"""
        CREATE TABLE workspace_ingredient_types (
            user_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
            normalized_name TEXT NOT NULL, is_seeded INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1, {order_column}
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, id), UNIQUE(user_id, normalized_name)
        )
    """)


def insert_legacy_types(connection, owner, positions=None):
    for index, (type_id, name) in reversed(list(enumerate(types.INGREDIENT_TYPE_SEEDS))):
        name = "Entree" if type_id == "main" else name
        values = [owner, type_id, name, name.lower(), "created", "untouched"]
        fields = "user_id, id, name, normalized_name, created_at, updated_at"
        if positions is not None:
            fields += ", sort_order"
            values.append(positions[index])
        placeholders = ",".join("?" for _ in values)
        connection.execute(f"INSERT INTO workspace_ingredient_types ({fields}) VALUES ({placeholders})", values)


@pytest.mark.parametrize("positions", [None, [0] * 6, [None] * 6, [-1] * 6, ["unset"] * 6])
def test_schema_backfill_uses_seed_ids_preserves_names_and_is_idempotent(positions):
    connection = sqlite3.connect(":memory:")
    legacy_table(connection, with_order=positions is not None)
    insert_legacy_types(connection, "old", positions)
    master_data.ensure_recipe_master_schema(connection)
    rows = connection.execute("SELECT * FROM workspace_ingredient_types ORDER BY sort_order").fetchall()
    assert [row["id"] for row in rows] == [item[0] for item in types.INGREDIENT_TYPE_SEEDS]
    assert [row["sort_order"] for row in rows] == list(range(6))
    assert rows[0]["name"] == "Entree"
    assert {row["updated_at"] for row in rows} == {"untouched"}
    before = [dict(row) for row in rows]
    assert master_data.migrate_ingredient_type_order(connection) == 0
    assert [dict(row) for row in connection.execute("SELECT * FROM workspace_ingredient_types ORDER BY sort_order")] == before
    connection.close()


def test_backfill_preserves_existing_order_and_appends_unpositioned_custom_types():
    connection = sqlite3.connect(":memory:")
    legacy_table(connection)
    insert_legacy_types(connection, "ordered", [5, 4, 3, 2, 1, 0])
    insert_legacy_types(connection, "legacy", [0] * 6)
    for type_id, name, created_at in [("custom_b", "Alpha", "2026-02"), ("custom_a", "Zulu", "2026-01")]:
        connection.execute("""INSERT INTO workspace_ingredient_types
            (user_id, id, name, normalized_name, sort_order, created_at, updated_at)
            VALUES ('legacy', ?, ?, ?, NULL, ?, 'untouched')""", (type_id, name, name.lower(), created_at))
    ordered_before = [tuple(row) for row in connection.execute("SELECT * FROM workspace_ingredient_types WHERE user_id='ordered' ORDER BY id")]
    master_data.ensure_recipe_master_schema(connection)
    ordered_after = [tuple(row) for row in connection.execute("SELECT * FROM workspace_ingredient_types WHERE user_id='ordered' ORDER BY id")]
    assert ordered_before == ordered_after
    legacy = connection.execute("SELECT id, sort_order FROM workspace_ingredient_types WHERE user_id='legacy' ORDER BY sort_order").fetchall()
    assert [row["id"] for row in legacy] == [item[0] for item in types.INGREDIENT_TYPE_SEEDS] + ["custom_a", "custom_b"]
    assert [row["sort_order"] for row in legacy] == list(range(8))
    connection.close()


def test_migration_cli_dry_run_and_repeat_apply_are_safe(type_database):
    with sqlite3.connect(type_database) as connection:
        legacy_table(connection, with_order=False)
        insert_legacy_types(connection, "legacy")
    before = type_database.read_bytes()
    command = [sys.executable, "-m", "PushShoppingList.scripts.migrate_ingredient_type_order", "--database", str(type_database)]
    dry = subprocess.run([*command, "--dry-run"], check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(dry.stdout.splitlines()[-1]) == {"changed_rows": 5, "dry_run": True}
    assert type_database.read_bytes() == before
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    migrated = stored_rows(type_database)
    again = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(again.stdout.splitlines()[-1])["changed_rows"] == 0
    assert stored_rows(type_database) == migrated


def test_separate_processes_serialize_adds_and_moves(type_database):
    types.move_workspace_ingredient_type("main", 1, user_id="mine")
    script = """
import sys
from PushShoppingList.services import ingredient_type_service as types
assert types.save_workspace_ingredient_type({'name': sys.argv[1]}, user_id='mine')['ok']
assert types.move_workspace_ingredient_type(sys.argv[2], 1, user_id='mine')['ok']
"""
    processes = [subprocess.Popen(
        [sys.executable, "-c", script, name, type_id],
        cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for name, type_id in [("Concurrent A", "sauce"), ("Concurrent B", "optional")]]
    for process in processes:
        stdout, stderr = process.communicate(timeout=40)
        assert process.returncode == 0, stdout + stderr
    items = types.ingredient_type_registry_payload("mine")["types"]
    assert len(items) == 8
    assert [item["sort_order"] for item in items] == list(range(8))
    assert {item["name"] for item in items} == {name for _id, name in types.INGREDIENT_TYPE_SEEDS} | {"Concurrent A", "Concurrent B"}
