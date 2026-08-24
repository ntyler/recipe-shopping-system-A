"""Transactional cleanup for recipe-master data owned by one guest session.

This module deliberately handles only rows stored in the recipe-master SQLite
database.  Jobs, workspace files, generated static assets, and the guest
session tombstone are separate phases of the outer guest purge saga.

Ownership in the existing recipe-master schema is represented by the exact
``user_id`` value ``guest:<opaque-session-id>``.  Session ids are never
trimmed, normalized, or interpreted as paths here.
"""

import sqlite3
from pathlib import Path

from PushShoppingList.services import recipe_master_data_service as master_data


MANIFEST_VERSION = 1


class GuestRecipeCleanupManifestError(RuntimeError):
    """Raised when the live schema is not covered by the cleanup manifest."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details if isinstance(details, dict) else {}


class GuestRecipeCleanupOwnershipError(RuntimeError):
    """Raised when an ID-only foreign key could delete another owner's row."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details if isinstance(details, dict) else {}


# Every current recipe-master table whose rows are directly owned through a
# user_id column.  Keep this explicit: schema drift must be reviewed instead
# of being deleted through a guessed predicate.
OWNER_SCOPED_TABLES = (
    "equipment",
    "equipment_aliases",
    "equipment_normalization_reviews",
    "equipment_requirement_migration_map",
    "ingredient_aliases",
    "ingredient_duplicate_reviews",
    "ingredient_duplicate_scans",
    "ingredient_merge_history",
    "ingredient_store_section_reclassification_history",
    "ingredient_store_sections",
    "ingredients",
    "recipe_equipment",
    "recipe_equipment_options",
    "recipe_equipment_requirement_sync",
    "recipe_equipment_requirements",
    "recipe_ingredient_requirement_migration_runs",
    "recipe_ingredient_requirement_sync",
    "recipe_ingredient_requirements",
    "recipe_ingredients",
    "workspace_ingredient_type_registry_seeds",
    "workspace_ingredient_types",
    "workspace_cuisine_category_registry_seeds",
    "workspace_cuisine_categories",
    "workspace_unit_aliases",
    "workspace_unit_registry_seeds",
    "workspace_units",
)


# These tables have no user_id of their own.  Their guest ownership is proven
# by joining through recipe_ingredient_requirements.user_id.
CHILD_TABLES = (
    "recipe_ingredient_option_items",
    "recipe_ingredient_options",
)


# These known tables are intentionally global and are never deleted here.
# Unknown tables without a user_id are also preserved by default.
PRESERVED_GLOBAL_TABLES = (
    "canonical_units",
    "equipment_requirement_migration_runs",
    "recipe_master_migrations",
    "unit_aliases",
    "unit_normalization_reports",
)


# Child-first ordering prevents a parent cascade from making per-table counts
# ambiguous.  It also removes orphan master ingredient/equipment records by
# deleting those directly by owner rather than relying on recipe references.
DELETE_ORDER = (
    "recipe_ingredient_option_items",
    "recipe_ingredient_options",
    "recipe_ingredient_requirements",
    "recipe_equipment_options",
    "recipe_equipment_requirements",
    "recipe_ingredients",
    "recipe_equipment",
    "ingredient_aliases",
    "equipment_aliases",
    "ingredient_duplicate_reviews",
    "ingredient_duplicate_scans",
    "ingredient_merge_history",
    "ingredient_store_section_reclassification_history",
    "ingredient_store_sections",
    "equipment_normalization_reviews",
    "equipment_requirement_migration_map",
    "recipe_ingredient_requirement_sync",
    "recipe_ingredient_requirement_migration_runs",
    "recipe_equipment_requirement_sync",
    "ingredients",
    "equipment",
    "workspace_unit_aliases",
    "workspace_unit_registry_seeds",
    "workspace_units",
    "workspace_ingredient_type_registry_seeds",
    "workspace_ingredient_types",
    "workspace_cuisine_category_registry_seeds",
    "workspace_cuisine_categories",
)


CHILD_REQUIRED_COLUMNS = {
    "recipe_ingredient_options": {"id", "requirement_id"},
    "recipe_ingredient_option_items": {"option_id"},
}


def guest_recipe_owner_scope(guest_session_id):
    """Return the exact recipe-master owner value for an opaque session id."""
    if not isinstance(guest_session_id, str) or not guest_session_id:
        raise ValueError("guest_session_id must be a non-empty string.")
    if "\x00" in guest_session_id:
        raise ValueError("guest_session_id cannot contain a NUL character.")
    return f"guest:{guest_session_id}"


def recipe_master_cleanup_db_path(db_path=None):
    """Resolve the database lazily so tests and deployments can override it."""
    if db_path is not None:
        return Path(db_path)
    return Path(master_data.recipe_master_db_path())


def _quote_identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


def _table_names(connection):
    return {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
              FROM sqlite_master
             WHERE type = 'table'
               AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }


def _table_columns(connection, table_name):
    return {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_quote_identifier(table_name)})"
        ).fetchall()
    }


def _foreign_key_parent_tables(connection, table_name):
    return {
        str(row[2])
        for row in connection.execute(
            f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
        ).fetchall()
    }


def _foreign_key_groups(connection, table_name):
    groups = {}
    for row in connection.execute(
        f"PRAGMA foreign_key_list({_quote_identifier(table_name)})"
    ).fetchall():
        group = groups.setdefault(
            int(row[0]),
            {
                "parent_table": str(row[2]),
                "on_delete": str(row[6] or "").upper(),
                "columns": [],
            },
        )
        group["columns"].append((str(row[3]), str(row[4])))
    return tuple(groups.values())


def _dangerous_master_foreign_keys(connection, present_tables, columns_by_table):
    """Return ID-only cascades whose child ownership must be checked.

    The legacy recipe-master schema uses globally unique integer IDs but keeps
    tenant ownership in a separate ``user_id`` column.  An ID-only CASCADE or
    SET NULL can therefore affect a different tenant if corrupt/imported data
    crosses that boundary.  Composite ``(user_id, id)`` references are safe.
    """

    edges = []
    unresolved = []
    for child_table in sorted(present_tables):
        for foreign_key in _foreign_key_groups(connection, child_table):
            parent_table = foreign_key["parent_table"]
            if (
                parent_table not in {"ingredients", "equipment"}
                or foreign_key["on_delete"] not in {"CASCADE", "SET NULL"}
            ):
                continue
            mappings = tuple(foreign_key["columns"])
            if ("user_id", "user_id") in mappings:
                continue
            id_mappings = [mapping for mapping in mappings if mapping[1] == "id"]
            if len(id_mappings) != 1:
                unresolved.append(f"{child_table}->{parent_table}")
                continue
            if (
                "user_id" not in columns_by_table.get(child_table, set())
                and child_table != "recipe_ingredient_option_items"
            ):
                unresolved.append(f"{child_table}->{parent_table}")
                continue
            edges.append(
                {
                    "child_table": child_table,
                    "child_column": id_mappings[0][0],
                    "parent_table": parent_table,
                    "on_delete": foreign_key["on_delete"],
                }
            )
    return edges, sorted(unresolved)


def validate_guest_recipe_cleanup_manifest(connection):
    """Inspect the live schema and fail closed on uncovered owner tables."""
    configured = set(OWNER_SCOPED_TABLES) | set(CHILD_TABLES)
    if set(DELETE_ORDER) != configured or len(DELETE_ORDER) != len(configured):
        raise GuestRecipeCleanupManifestError(
            "The guest recipe cleanup manifest is internally inconsistent.",
            {
                "delete_order_tables": sorted(set(DELETE_ORDER)),
                "configured_tables": sorted(configured),
            },
        )

    present_tables = _table_names(connection)
    columns_by_table = {
        table_name: _table_columns(connection, table_name)
        for table_name in present_tables
    }
    actual_user_id_tables = {
        table_name
        for table_name, columns in columns_by_table.items()
        if "user_id" in columns
    }
    unknown_user_id_tables = sorted(
        actual_user_id_tables - set(OWNER_SCOPED_TABLES)
    )
    owner_tables_missing_user_id = sorted(
        table_name
        for table_name in set(OWNER_SCOPED_TABLES) & present_tables
        if "user_id" not in columns_by_table.get(table_name, set())
    )

    missing_child_columns = {}
    for table_name, required_columns in CHILD_REQUIRED_COLUMNS.items():
        if table_name not in present_tables:
            continue
        missing = sorted(required_columns - columns_by_table.get(table_name, set()))
        if missing:
            missing_child_columns[table_name] = missing

    if "recipe_ingredient_options" in present_tables:
        requirement_columns = columns_by_table.get(
            "recipe_ingredient_requirements", set()
        )
        missing = sorted({"id", "user_id"} - requirement_columns)
        if missing:
            missing_child_columns["recipe_ingredient_requirements"] = missing

    managed_tables = set(OWNER_SCOPED_TABLES) | set(CHILD_TABLES)
    unknown_dependent_tables = sorted(
        table_name
        for table_name in present_tables - managed_tables
        if _foreign_key_parent_tables(connection, table_name) & managed_tables
    )
    _dangerous_edges, unresolved_cascade_ownership = (
        _dangerous_master_foreign_keys(
            connection,
            present_tables,
            columns_by_table,
        )
    )

    details = {
        "manifest_version": MANIFEST_VERSION,
        "present_manifest_tables": sorted(present_tables & managed_tables),
        "missing_manifest_tables": sorted(managed_tables - present_tables),
        "unknown_user_id_tables": unknown_user_id_tables,
        "owner_tables_missing_user_id": owner_tables_missing_user_id,
        "missing_child_columns": missing_child_columns,
        "unknown_dependent_tables": unknown_dependent_tables,
        "unresolved_cascade_ownership": unresolved_cascade_ownership,
    }
    if (
        unknown_user_id_tables
        or owner_tables_missing_user_id
        or missing_child_columns
        or unknown_dependent_tables
        or unresolved_cascade_ownership
    ):
        raise GuestRecipeCleanupManifestError(
            "The recipe-master schema is not fully covered by the guest cleanup manifest.",
            details,
        )
    return details


def validate_guest_recipe_owner_isolation(
    connection,
    owner_scope,
    schema_details=None,
):
    """Fail closed before an ID-only cascade can cross a tenant boundary."""

    schema_details = schema_details or validate_guest_recipe_cleanup_manifest(
        connection
    )
    present_tables = _table_names(connection)
    columns_by_table = {
        table_name: _table_columns(connection, table_name)
        for table_name in present_tables
    }
    edges, unresolved = _dangerous_master_foreign_keys(
        connection,
        present_tables,
        columns_by_table,
    )
    if unresolved:
        raise GuestRecipeCleanupManifestError(
            "A cascading recipe-master relationship has no reviewed owner resolver.",
            {**schema_details, "unresolved_cascade_ownership": unresolved},
        )

    cross_owner_counts = {}
    for edge in edges:
        child_table = edge["child_table"]
        parent_table = edge["parent_table"]
        child_column = edge["child_column"]
        edge_name = f"{child_table}->{parent_table}"
        if child_table == "recipe_ingredient_option_items":
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                  FROM {_quote_identifier(child_table)} AS child
                  JOIN {_quote_identifier(parent_table)} AS parent
                    ON parent.id = child.{_quote_identifier(child_column)}
                  JOIN recipe_ingredient_options AS option_row
                    ON option_row.id = child.option_id
                  JOIN recipe_ingredient_requirements AS requirement
                    ON requirement.id = option_row.requirement_id
                 WHERE parent.user_id = ?
                   AND requirement.user_id <> ?
                """,
                (owner_scope, owner_scope),
            ).fetchone()
        else:
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                  FROM {_quote_identifier(child_table)} AS child
                  JOIN {_quote_identifier(parent_table)} AS parent
                    ON parent.id = child.{_quote_identifier(child_column)}
                 WHERE parent.user_id = ?
                   AND child.user_id <> ?
                """,
                (owner_scope, owner_scope),
            ).fetchone()
        count = int(row[0] or 0)
        if count:
            cross_owner_counts[edge_name] = count

    if cross_owner_counts:
        raise GuestRecipeCleanupOwnershipError(
            "Recipe-master ownership is inconsistent; deletion was blocked.",
            {
                "owner_scope": owner_scope,
                "cross_owner_references": cross_owner_counts,
            },
        )
    return {"cross_owner_references": {}}


def _ownership_where(table_name):
    if table_name == "recipe_ingredient_options":
        return (
            "requirement_id IN ("
            "SELECT requirement.id "
            "FROM recipe_ingredient_requirements AS requirement "
            "WHERE requirement.user_id = ?"
            ")"
        )
    if table_name == "recipe_ingredient_option_items":
        return (
            "option_id IN ("
            "SELECT option_row.id "
            "FROM recipe_ingredient_options AS option_row "
            "JOIN recipe_ingredient_requirements AS requirement "
            "  ON requirement.id = option_row.requirement_id "
            "WHERE requirement.user_id = ?"
            ")"
        )
    return "user_id = ?"


def _owner_counts(connection, owner_scope, schema_details):
    present_tables = set(schema_details.get("present_manifest_tables", []))
    counts = {}
    for table_name in DELETE_ORDER:
        if table_name not in present_tables:
            counts[table_name] = 0
            continue
        row = connection.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
            f"WHERE {_ownership_where(table_name)}",
            (owner_scope,),
        ).fetchone()
        counts[table_name] = int(row[0] or 0)
    return counts


def _base_result(action, guest_session_id, owner_scope, db_path):
    return {
        "ok": False,
        "action": action,
        "dry_run": action == "preview",
        "applied": False,
        "guest_session_id": guest_session_id,
        "owner_scope": owner_scope,
        "database_path": str(db_path),
        "manifest_version": MANIFEST_VERSION,
        "counts": {table_name: 0 for table_name in DELETE_ORDER},
        "total_rows": 0,
    }


def _readonly_connection(db_path):
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def preview_guest_recipe_cleanup(guest_session_id, *, db_path=None):
    """Return exact owner row counts without creating or modifying the DB."""
    resolved_path = recipe_master_cleanup_db_path(db_path)
    try:
        owner_scope = guest_recipe_owner_scope(guest_session_id)
    except ValueError as exc:
        result = _base_result("preview", guest_session_id, "", resolved_path)
        result.update({"code": "invalid_guest_session_id", "error": str(exc)})
        return result

    result = _base_result(
        "preview", guest_session_id, owner_scope, resolved_path
    )
    if not resolved_path.is_file():
        result.update({
            "code": "database_not_found",
            "error": "The recipe-master database does not exist.",
        })
        return result

    connection = None
    try:
        connection = _readonly_connection(resolved_path)
        schema = validate_guest_recipe_cleanup_manifest(connection)
        validate_guest_recipe_owner_isolation(connection, owner_scope, schema)
        counts = _owner_counts(connection, owner_scope, schema)
        result.update({
            "ok": True,
            "code": "preview_complete",
            "schema": schema,
            "counts": counts,
            "total_rows": sum(counts.values()),
        })
        return result
    except GuestRecipeCleanupManifestError as exc:
        result.update({
            "code": "manifest_drift",
            "error": str(exc),
            "schema": exc.details,
        })
        return result
    except GuestRecipeCleanupOwnershipError as exc:
        result.update({
            "code": "cross_owner_reference",
            "error": str(exc),
            "ownership": exc.details,
        })
        return result
    except sqlite3.Error as exc:
        result.update({"code": "database_error", "error": str(exc)})
        return result
    finally:
        if connection is not None:
            connection.close()


def _run_failure_injector(failure_injector, stage, **context):
    if callable(failure_injector):
        failure_injector(stage, dict(context))


def delete_guest_recipe_data_with_connection(
    connection,
    guest_session_id,
    *,
    failure_injector=None,
):
    """Delete guest recipe rows inside a caller-owned open transaction.

    The caller owns commit/rollback.  This lets the outer purge transaction
    atomically remove application-workspace rows and legacy recipe-master rows
    because both sets live in the same SQLite database.
    """
    owner_scope = guest_recipe_owner_scope(guest_session_id)
    schema = validate_guest_recipe_cleanup_manifest(connection)
    validate_guest_recipe_owner_isolation(connection, owner_scope, schema)
    expected_counts = _owner_counts(connection, owner_scope, schema)
    deleted_counts = {}
    present_tables = set(schema.get("present_manifest_tables", []))

    for table_name in DELETE_ORDER:
        if table_name not in present_tables:
            deleted_counts[table_name] = 0
            continue
        _run_failure_injector(
            failure_injector,
            "before_delete",
            table=table_name,
        )
        cursor = connection.execute(
            f"DELETE FROM {_quote_identifier(table_name)} "
            f"WHERE {_ownership_where(table_name)}",
            (owner_scope,),
        )
        deleted_counts[table_name] = max(0, int(cursor.rowcount or 0))
        _run_failure_injector(
            failure_injector,
            "after_delete",
            table=table_name,
            deleted_count=deleted_counts[table_name],
        )

    if deleted_counts != expected_counts:
        raise RuntimeError(
            "Guest recipe cleanup row counts changed inside the locked transaction."
        )

    remaining_counts = _owner_counts(connection, owner_scope, schema)
    if any(remaining_counts.values()):
        raise RuntimeError(
            "Guest recipe cleanup left owner-scoped rows in the database."
        )
    return {
        "schema": schema,
        "counts": deleted_counts,
        "total_rows": sum(deleted_counts.values()),
        "no_op": not any(deleted_counts.values()),
    }


def delete_guest_recipe_data(
    guest_session_id,
    *,
    db_path=None,
    failure_injector=None,
):
    """Delete exactly one guest owner scope in a single SQLite transaction."""
    resolved_path = recipe_master_cleanup_db_path(db_path)
    try:
        owner_scope = guest_recipe_owner_scope(guest_session_id)
    except ValueError as exc:
        result = _base_result("delete", guest_session_id, "", resolved_path)
        result.update({"code": "invalid_guest_session_id", "error": str(exc)})
        return result

    result = _base_result("delete", guest_session_id, owner_scope, resolved_path)
    if not resolved_path.is_file():
        result.update({
            "code": "database_not_found",
            "error": "The recipe-master database does not exist.",
        })
        return result

    connection = None
    try:
        with master_data.RECIPE_MASTER_DB_LOCK:
            connection = sqlite3.connect(
                str(resolved_path),
                timeout=30,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            _run_failure_injector(
                failure_injector,
                "after_begin",
                owner_scope=owner_scope,
            )
            deletion = delete_guest_recipe_data_with_connection(
                connection,
                guest_session_id,
                failure_injector=failure_injector,
            )

            _run_failure_injector(
                failure_injector,
                "before_commit",
                total_rows=deletion["total_rows"],
            )
            connection.commit()
            result.update({
                "ok": True,
                "code": "delete_complete",
                "applied": True,
                **deletion,
            })
            return result
    except GuestRecipeCleanupManifestError as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        result.update({
            "code": "manifest_drift",
            "error": str(exc),
            "schema": exc.details,
        })
        return result
    except GuestRecipeCleanupOwnershipError as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        result.update({
            "code": "cross_owner_reference",
            "error": str(exc),
            "ownership": exc.details,
        })
        return result
    except Exception as exc:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        result.update({
            "code": "delete_failed",
            "error": str(exc),
        })
        return result
    finally:
        if connection is not None:
            connection.close()
