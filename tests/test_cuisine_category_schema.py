import sqlite3

from PushShoppingList.services import recipe_master_data_service as master_data


def _column_details(connection, table_name):
    return {
        row["name"]: row
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def test_fresh_cuisine_category_schema_includes_optional_display_fields():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    master_data.ensure_recipe_master_schema(connection)

    columns = _column_details(connection, "workspace_cuisine_categories")
    assert columns["icon"]["type"] == "TEXT"
    assert columns["icon"]["notnull"] == 0
    assert columns["icon"]["dflt_value"] == "NULL"
    assert columns["abbreviation"]["type"] == "TEXT"
    assert columns["abbreviation"]["notnull"] == 0
    assert columns["abbreviation"]["dflt_value"] == "NULL"


def test_existing_cuisine_category_schema_upgrades_without_changing_rows():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE workspace_cuisine_categories (
            user_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            is_seeded INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, id),
            UNIQUE(user_id, normalized_name)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO workspace_cuisine_categories (
            user_id, id, name, normalized_name, aliases_json, is_seeded,
            is_active, sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "user-a",
            "custom_british",
            "United Kingdom",
            "united kingdom",
            '["British"]',
            0,
            1,
            12,
            "created",
            "updated",
        ),
    )

    master_data.ensure_recipe_master_schema(connection)
    master_data.ensure_recipe_master_schema(connection)

    row = connection.execute(
        """
        SELECT name, normalized_name, aliases_json, is_active, sort_order,
               icon, abbreviation
          FROM workspace_cuisine_categories
         WHERE user_id = ? AND id = ?
        """,
        ("user-a", "custom_british"),
    ).fetchone()
    assert dict(row) == {
        "name": "United Kingdom",
        "normalized_name": "united kingdom",
        "aliases_json": '["British"]',
        "is_active": 1,
        "sort_order": 12,
        "icon": None,
        "abbreviation": None,
    }
