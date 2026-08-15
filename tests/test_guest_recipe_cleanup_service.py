import sqlite3

import pytest

from PushShoppingList.services import guest_recipe_cleanup_service as cleanup
from PushShoppingList.services import recipe_equipment_requirement_service as equipment_requirements
from PushShoppingList.services import recipe_master_data_service as master_data


TARGET_GUEST_ID = "opaque / guest id"
TARGET_OWNER = f"guest:{TARGET_GUEST_ID}"
OTHER_GUEST_OWNER = "guest:other-guest"
ACCOUNT_OWNER = "registered-account"


def quote_identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


@pytest.fixture
def cleanup_database(monkeypatch, tmp_path):
    db_path = tmp_path / "recipe_master.sqlite3"
    monkeypatch.delenv("SHOPPING_APP_RECIPE_MASTER_DB", raising=False)
    monkeypatch.setattr(master_data, "RECIPE_MASTER_DB_PATH", db_path)

    with sqlite3.connect(db_path) as connection:
        for table_name in cleanup.OWNER_SCOPED_TABLES:
            connection.execute(
                f"""
                CREATE TABLE {quote_identifier(table_name)} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    marker TEXT NOT NULL DEFAULT ''
                )
                """
            )

        connection.execute(
            """
            CREATE TABLE recipe_ingredient_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER NOT NULL,
                marker TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE recipe_ingredient_option_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                option_id INTEGER NOT NULL,
                marker TEXT NOT NULL DEFAULT ''
            )
            """
        )

        for table_name in cleanup.PRESERVED_GLOBAL_TABLES:
            connection.execute(
                f"""
                CREATE TABLE {quote_identifier(table_name)} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    marker TEXT NOT NULL
                )
                """
            )
            connection.execute(
                f"INSERT INTO {quote_identifier(table_name)} (marker) VALUES (?)",
                (f"preserve:{table_name}",),
            )

        for table_name in cleanup.OWNER_SCOPED_TABLES:
            for owner_scope in (TARGET_OWNER, OTHER_GUEST_OWNER, ACCOUNT_OWNER):
                connection.execute(
                    f"INSERT INTO {quote_identifier(table_name)} "
                    "(user_id, marker) VALUES (?, ?)",
                    (owner_scope, f"{owner_scope}:{table_name}"),
                )

        for owner_scope in (TARGET_OWNER, OTHER_GUEST_OWNER, ACCOUNT_OWNER):
            requirement_id = connection.execute(
                """
                SELECT id
                  FROM recipe_ingredient_requirements
                 WHERE user_id = ?
                """,
                (owner_scope,),
            ).fetchone()[0]
            option_id = connection.execute(
                """
                INSERT INTO recipe_ingredient_options (requirement_id, marker)
                VALUES (?, ?)
                """,
                (requirement_id, f"{owner_scope}:option"),
            ).lastrowid
            connection.execute(
                """
                INSERT INTO recipe_ingredient_option_items (option_id, marker)
                VALUES (?, ?)
                """,
                (option_id, f"{owner_scope}:item"),
            )

    return db_path


def owner_count(connection, table_name, owner_scope):
    return int(connection.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table_name)} WHERE user_id = ?",
        (owner_scope,),
    ).fetchone()[0])


def target_child_count(connection, table_name, owner_scope):
    if table_name == "recipe_ingredient_options":
        query = """
            SELECT COUNT(*)
              FROM recipe_ingredient_options AS option_row
              JOIN recipe_ingredient_requirements AS requirement
                ON requirement.id = option_row.requirement_id
             WHERE requirement.user_id = ?
        """
    else:
        query = """
            SELECT COUNT(*)
              FROM recipe_ingredient_option_items AS item
              JOIN recipe_ingredient_options AS option_row
                ON option_row.id = item.option_id
              JOIN recipe_ingredient_requirements AS requirement
                ON requirement.id = option_row.requirement_id
             WHERE requirement.user_id = ?
        """
    return int(connection.execute(query, (owner_scope,)).fetchone()[0])


def assert_target_rows_present(db_path):
    with sqlite3.connect(db_path) as connection:
        for table_name in cleanup.OWNER_SCOPED_TABLES:
            assert owner_count(connection, table_name, TARGET_OWNER) == 1
        for table_name in cleanup.CHILD_TABLES:
            assert target_child_count(connection, table_name, TARGET_OWNER) == 1


def test_preview_and_delete_cover_every_manifest_table_without_cross_tenant_changes(
    cleanup_database,
):
    preview = cleanup.preview_guest_recipe_cleanup(TARGET_GUEST_ID)

    assert preview["ok"] is True
    assert preview["dry_run"] is True
    assert preview["owner_scope"] == TARGET_OWNER
    assert preview["total_rows"] == len(cleanup.DELETE_ORDER)
    assert set(preview["counts"]) == set(cleanup.DELETE_ORDER)
    assert all(count == 1 for count in preview["counts"].values())
    assert_target_rows_present(cleanup_database)

    result = cleanup.delete_guest_recipe_data(TARGET_GUEST_ID)

    assert result["ok"] is True
    assert result["applied"] is True
    assert result["no_op"] is False
    assert result["total_rows"] == len(cleanup.DELETE_ORDER)
    assert all(count == 1 for count in result["counts"].values())

    with sqlite3.connect(cleanup_database) as connection:
        for table_name in cleanup.OWNER_SCOPED_TABLES:
            assert owner_count(connection, table_name, TARGET_OWNER) == 0
            assert owner_count(connection, table_name, OTHER_GUEST_OWNER) == 1
            assert owner_count(connection, table_name, ACCOUNT_OWNER) == 1

        for table_name in cleanup.CHILD_TABLES:
            assert target_child_count(connection, table_name, OTHER_GUEST_OWNER) == 1
            assert target_child_count(connection, table_name, ACCOUNT_OWNER) == 1
            remaining = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
            ).fetchone()[0]
            assert remaining == 2

        # These ingredient/equipment rows had no recipe association; direct
        # owner predicates still remove them.
        assert owner_count(connection, "ingredients", TARGET_OWNER) == 0
        assert owner_count(connection, "equipment", TARGET_OWNER) == 0

        for table_name in cleanup.PRESERVED_GLOBAL_TABLES:
            marker = connection.execute(
                f"SELECT marker FROM {quote_identifier(table_name)}"
            ).fetchone()[0]
            assert marker == f"preserve:{table_name}"


def test_injected_failure_rolls_back_every_recipe_master_delete(cleanup_database):
    def inject_failure(stage, context):
        if (
            stage == "after_delete"
            and context.get("table") == "recipe_ingredient_options"
        ):
            raise RuntimeError("injected recipe cleanup failure")

    result = cleanup.delete_guest_recipe_data(
        TARGET_GUEST_ID,
        failure_injector=inject_failure,
    )

    assert result["ok"] is False
    assert result["applied"] is False
    assert result["code"] == "delete_failed"
    assert "injected recipe cleanup failure" in result["error"]
    assert_target_rows_present(cleanup_database)


def test_recipe_master_cleanup_rerun_is_an_idempotent_no_op(cleanup_database):
    first = cleanup.delete_guest_recipe_data(TARGET_GUEST_ID)
    second = cleanup.delete_guest_recipe_data(TARGET_GUEST_ID)

    assert first["ok"] is True
    assert first["total_rows"] == len(cleanup.DELETE_ORDER)
    assert second["ok"] is True
    assert second["applied"] is True
    assert second["no_op"] is True
    assert second["total_rows"] == 0
    assert all(count == 0 for count in second["counts"].values())


def test_unknown_user_id_table_blocks_preview_and_delete(cleanup_database):
    with sqlite3.connect(cleanup_database) as connection:
        connection.execute(
            """
            CREATE TABLE newly_added_recipe_owner_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO newly_added_recipe_owner_data (user_id) VALUES (?)",
            (TARGET_OWNER,),
        )

    preview = cleanup.preview_guest_recipe_cleanup(TARGET_GUEST_ID)
    result = cleanup.delete_guest_recipe_data(TARGET_GUEST_ID)

    assert preview["ok"] is False
    assert preview["code"] == "manifest_drift"
    assert preview["schema"]["unknown_user_id_tables"] == [
        "newly_added_recipe_owner_data"
    ]
    assert result["ok"] is False
    assert result["applied"] is False
    assert result["code"] == "manifest_drift"
    assert_target_rows_present(cleanup_database)
    with sqlite3.connect(cleanup_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM newly_added_recipe_owner_data WHERE user_id = ?",
            (TARGET_OWNER,),
        ).fetchone()[0] == 1


def test_manifest_covers_the_current_full_recipe_master_schema(tmp_path):
    db_path = tmp_path / "current_recipe_master_schema.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        master_data.ensure_recipe_master_schema(connection)
        equipment_requirements.ensure_structured_equipment_schema(
            connection,
            authorized=True,
            migration_token=equipment_requirements.PHASE3A_MIGRATION_TOKEN,
        )
        connection.commit()

        details = cleanup.validate_guest_recipe_cleanup_manifest(connection)

    assert set(details["present_manifest_tables"]) == set(cleanup.DELETE_ORDER)
    assert details["missing_manifest_tables"] == []
    assert details["unknown_user_id_tables"] == []
    assert details["unknown_dependent_tables"] == []
