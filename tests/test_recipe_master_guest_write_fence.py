import sqlite3
import threading

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import recipe_master_data_service as master_data


def install_combined_schema(database):
    master_data.RECIPE_MASTER_DB_PATH = database
    master_data.ensure_recipe_master_schema()
    application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    assert application_data.application_schema_available(database)


def insert_ingredient(connection, user_id, name):
    timestamp = "2026-08-15T00:00:00Z"
    connection.execute(
        """
        INSERT INTO ingredients (
            user_id, name, normalized_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, name, name.casefold(), timestamp, timestamp),
    )


def insert_tombstone(connection, guest_session_id):
    connection.execute(
        """
        INSERT INTO guest_tombstones (
            guest_session_id, workspace_id, purge_run_id,
            lifecycle_state, tombstoned_at
        ) VALUES (?, ?, 'purge-run', 'purging', '2026-08-15T00:00:00Z')
        """,
        (guest_session_id, "guest:" + guest_session_id),
    )


def ingredient_owners(database):
    with sqlite3.connect(str(database)) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT user_id FROM ingredients ORDER BY user_id"
            ).fetchall()
        ]


def test_tombstone_blocks_declared_and_actual_guest_owner_writes(tmp_path):
    database = tmp_path / "combined.sqlite3"
    install_combined_schema(database)
    guest_id = "expired-guest"
    owner_id = "guest:" + guest_id

    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        insert_tombstone(connection, guest_id)

    with pytest.raises(master_data.RecipeMasterGuestWriteFencedError):
        with master_data.recipe_master_connection(user_id=owner_id) as connection:
            insert_ingredient(connection, owner_id, "blocked declared owner")

    # The connection-local trigger checks NEW.user_id, not only the identity a
    # background/admin caller declared when it opened the transaction.
    with pytest.raises(master_data.RecipeMasterGuestWriteFencedError):
        with master_data.recipe_master_connection(user_id="unrelated-user") as connection:
            insert_ingredient(connection, owner_id, "blocked actual owner")

    with master_data.recipe_master_connection(user_id="unrelated-user") as connection:
        insert_ingredient(connection, "unrelated-user", "allowed")

    assert ingredient_owners(database) == ["unrelated-user"]


def test_externally_managed_bulk_writer_uses_actual_owner_fence(tmp_path):
    database = tmp_path / "combined.sqlite3"
    install_combined_schema(database)
    guest_id = "bulk-job-guest"
    owner_id = "guest:" + guest_id
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        insert_tombstone(connection, guest_id)

    with sqlite3.connect(str(database)) as connection:
        master_data.install_recipe_master_connection_guest_write_fences(connection)
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError, match="purge fenced"):
            insert_ingredient(connection, owner_id, "blocked bulk row")

    assert ingredient_owners(database) == []


def test_actual_owner_fence_blocks_background_update_and_delete(tmp_path):
    database = tmp_path / "combined.sqlite3"
    install_combined_schema(database)
    guest_id = "background-guest"
    owner_id = "guest:" + guest_id
    with master_data.recipe_master_connection(user_id=owner_id) as connection:
        insert_ingredient(connection, owner_id, "existing guest row")
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        insert_tombstone(connection, guest_id)

    with pytest.raises(master_data.RecipeMasterGuestWriteFencedError):
        with master_data.recipe_master_connection(user_id="maintenance-job") as connection:
            connection.execute(
                "UPDATE ingredients SET name = 'changed' WHERE user_id = ?",
                (owner_id,),
            )
    with pytest.raises(master_data.RecipeMasterGuestWriteFencedError):
        with master_data.recipe_master_connection(user_id="maintenance-job") as connection:
            connection.execute(
                "DELETE FROM ingredients WHERE user_id = ?",
                (owner_id,),
            )

    assert ingredient_owners(database) == [owner_id]


def test_in_flight_guest_writer_commits_before_purge_then_is_deleted(tmp_path):
    database = tmp_path / "combined.sqlite3"
    install_combined_schema(database)
    guest_id = "racing-guest"
    owner_id = "guest:" + guest_id
    writer_holds_reservation = threading.Event()
    release_writer = threading.Event()
    purge_attempted = threading.Event()
    failures = []

    with master_data.recipe_master_connection(user_id="unrelated-user") as connection:
        insert_ingredient(connection, "unrelated-user", "keep me")

    def writer():
        try:
            with master_data.recipe_master_connection(user_id=owner_id) as connection:
                insert_ingredient(connection, owner_id, "guest row")
                writer_holds_reservation.set()
                assert release_writer.wait(10)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def purge():
        try:
            assert writer_holds_reservation.wait(10)
            with sqlite3.connect(str(database), timeout=10) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                purge_attempted.set()
                connection.execute("BEGIN IMMEDIATE")
                insert_tombstone(connection, guest_id)
                connection.execute(
                    "DELETE FROM ingredients WHERE user_id = ?", (owner_id,)
                )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    writer_thread = threading.Thread(target=writer)
    purge_thread = threading.Thread(target=purge)
    writer_thread.start()
    purge_thread.start()
    assert writer_holds_reservation.wait(10)
    assert purge_attempted.wait(10)
    release_writer.set()
    writer_thread.join(10)
    purge_thread.join(10)

    assert not writer_thread.is_alive()
    assert not purge_thread.is_alive()
    assert failures == []
    assert ingredient_owners(database) == ["unrelated-user"]

    # A writer arriving after the purge transaction sees the committed fence
    # and cannot recreate a recipe-master row.
    with pytest.raises(master_data.RecipeMasterGuestWriteFencedError):
        with master_data.recipe_master_connection(user_id=owner_id) as connection:
            insert_ingredient(connection, owner_id, "late guest row")
    assert ingredient_owners(database) == ["unrelated-user"]


def test_distinct_installed_application_database_fails_closed_for_guest(tmp_path):
    recipe_database = tmp_path / "recipe.sqlite3"
    application_database = tmp_path / "application.sqlite3"
    master_data.RECIPE_MASTER_DB_PATH = recipe_database
    application_data.install_application_schema(
        application_database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )

    with pytest.raises(master_data.RecipeMasterNonAtomicDatabaseLayoutError):
        with master_data.recipe_master_connection(
            user_id="guest:cannot-order-atomically",
            application_db_path=application_database,
        ) as connection:
            insert_ingredient(
                connection,
                "guest:cannot-order-atomically",
                "must not commit",
            )

    with master_data.recipe_master_connection(
        user_id="unrelated-user",
        application_db_path=application_database,
    ) as connection:
        insert_ingredient(connection, "unrelated-user", "allowed")

    assert ingredient_owners(recipe_database) == ["unrelated-user"]


def test_legacy_recipe_database_allows_guest_without_creating_app_schema(tmp_path):
    database = tmp_path / "legacy-recipe.sqlite3"
    master_data.RECIPE_MASTER_DB_PATH = database

    with master_data.recipe_master_connection(user_id="guest:legacy") as connection:
        insert_ingredient(connection, "guest:legacy", "legacy row")

    with sqlite3.connect(str(database)) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'guest_tombstones'"
        ).fetchone() is None
    assert ingredient_owners(database) == ["guest:legacy"]
