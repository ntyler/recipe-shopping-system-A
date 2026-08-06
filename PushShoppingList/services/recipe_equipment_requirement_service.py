"""Feature-gated structured persistence for recipe equipment requirements.

Schema creation and structured writes are explicit operations.  Importing or
reading this module never changes the application database.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone

from PushShoppingList.services.equipment_normalization_service import (
    PARSER_VERSION,
    parse_equipment_list,
    requirement_summary,
)


TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _env_enabled(name):
    return str(os.getenv(name, "") or "").strip().casefold() in TRUE_VALUES


def structured_equipment_ui_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED")


def structured_equipment_read_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED")


def structured_equipment_write_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED")


def structured_equipment_schema_writes_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED")


def structured_equipment_review_writes_enabled():
    return _env_enabled("RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def requirements_from_recipe_data(recipe_data):
    recipe_data = recipe_data if isinstance(recipe_data, dict) else {}
    return parse_equipment_list(
        recipe_data.get("equipment", []),
        instructions=recipe_data.get("instructions", []),
    )


def add_structured_equipment_preview(recipe_data):
    """Attach a structured compatibility preview when structured writes are enabled."""
    if not isinstance(recipe_data, dict) or not structured_equipment_write_enabled():
        return recipe_data
    recipe_data["equipment_requirements"] = requirements_from_recipe_data(recipe_data)
    recipe_data["equipment_requirement_parser_version"] = PARSER_VERSION
    return recipe_data


def review_queue_from_master_rows(rows):
    queue = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        requirements = parse_equipment_list([{"equipment": name}])
        summary = requirement_summary(requirements)
        has_structure = any(
            requirement.get("connector") in {"or", "and"}
            or any(
                option.get("attributes") or option.get("notes") or option.get("option_kind") != "equipment"
                for option in requirement.get("options", [])
            )
            for requirement in requirements
        )
        if not has_structure and not summary["review_requirement_count"]:
            continue
        queue.append({
            "equipment_id": row.get("id"),
            "name": name,
            "usage_count": int(row.get("usage_count") or 0),
            "review_status": (
                "needs_review" if summary["review_requirement_count"] else "ready"
            ),
            "requirements": requirements,
            "summary": summary,
        })
    return queue


def _column_names(connection, table_name):
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }


def structured_equipment_schema_available(connection):
    required = {
        "equipment_aliases",
        "recipe_equipment_requirements",
        "recipe_equipment_options",
        "equipment_normalization_reviews",
        "equipment_requirement_migration_runs",
        "equipment_requirement_migration_map",
    }
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return required.issubset(existing)


def ensure_structured_equipment_schema(connection, *, authorized=False):
    """Create the additive schema only after an explicit caller authorization."""
    if not authorized or not structured_equipment_schema_writes_enabled():
        raise PermissionError(
            "Structured equipment schema writes are locked. Set "
            "RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED=true and pass authorized=True."
        )
    if "equipment" not in {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }:
        raise RuntimeError("The legacy equipment table must exist before adding the structured schema.")

    equipment_columns = _column_names(connection, "equipment")
    additions = {
        "canonical_name": "TEXT NOT NULL DEFAULT ''",
        "canonical_key": "TEXT NOT NULL DEFAULT ''",
        "description": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'active'",
        "image_provenance_json": "TEXT NOT NULL DEFAULT '{}'",
        "merged_into_id": "INTEGER DEFAULT NULL",
    }
    for column_name, definition in additions.items():
        if column_name not in equipment_columns:
            connection.execute(
                f'ALTER TABLE equipment ADD COLUMN "{column_name}" {definition}'
            )

    connection.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_user_id_id
            ON equipment(user_id, id);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_equipment_user_canonical_key
            ON equipment(user_id, canonical_key)
            WHERE canonical_key <> '' AND status <> 'merged';

        CREATE TABLE IF NOT EXISTS equipment_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            alias_name TEXT NOT NULL,
            alias_key TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, alias_key),
            FOREIGN KEY(user_id, equipment_id)
                REFERENCES equipment(user_id, id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            source_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            quantity TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            connector TEXT NOT NULL DEFAULT 'single',
            conjunction_group TEXT NOT NULL DEFAULT '',
            parse_confidence REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'pending',
            parser_version TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, recipe_id, requirement_id),
            UNIQUE(user_id, id)
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            option_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            requirement_id INTEGER NOT NULL,
            equipment_id INTEGER DEFAULT NULL,
            source_option_text TEXT NOT NULL DEFAULT '',
            canonical_name TEXT NOT NULL DEFAULT '',
            canonical_key TEXT NOT NULL DEFAULT '',
            option_kind TEXT NOT NULL DEFAULT 'equipment',
            attributes_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            matched_alias_id INTEGER DEFAULT NULL,
            match_type TEXT NOT NULL DEFAULT '',
            match_confidence REAL NOT NULL DEFAULT 0,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(requirement_id, option_id),
            FOREIGN KEY(user_id, requirement_id)
                REFERENCES recipe_equipment_requirements(user_id, id) ON DELETE CASCADE,
            FOREIGN KEY(user_id, equipment_id)
                REFERENCES equipment(user_id, id) ON DELETE RESTRICT,
            FOREIGN KEY(matched_alias_id)
                REFERENCES equipment_aliases(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS equipment_normalization_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_record_id TEXT NOT NULL DEFAULT '',
            source_text TEXT NOT NULL,
            proposal_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            decision TEXT NOT NULL DEFAULT '',
            decision_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, source_kind, source_record_id, source_text)
        );

        CREATE TABLE IF NOT EXISTS equipment_requirement_migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT NOT NULL UNIQUE,
            mode TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            summary_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS equipment_requirement_migration_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_run_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            legacy_recipe_equipment_id INTEGER DEFAULT NULL,
            legacy_equipment_id INTEGER DEFAULT NULL,
            requirement_id TEXT NOT NULL DEFAULT '',
            option_id TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL DEFAULT '',
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(migration_run_id, user_id, recipe_id, legacy_recipe_equipment_id, option_id),
            FOREIGN KEY(migration_run_id)
                REFERENCES equipment_requirement_migration_runs(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS recipe_equipment_requirement_sync (
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            requirement_count INTEGER NOT NULL DEFAULT 0,
            parser_version TEXT NOT NULL DEFAULT '',
            synced_at TEXT NOT NULL,
            PRIMARY KEY(user_id, recipe_id)
        );

        CREATE INDEX IF NOT EXISTS idx_equipment_aliases_equipment
            ON equipment_aliases(user_id, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_requirements_recipe
            ON recipe_equipment_requirements(user_id, recipe_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_equipment_options_requirement
            ON recipe_equipment_options(user_id, requirement_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_equipment_options_equipment
            ON recipe_equipment_options(user_id, equipment_id);
        CREATE INDEX IF NOT EXISTS idx_equipment_reviews_status
            ON equipment_normalization_reviews(user_id, status, id);
        """
    )
    return True


def replace_recipe_requirements(connection, user_id, recipe_id, requirements, *, authorized=False):
    if not authorized or not structured_equipment_write_enabled():
        raise PermissionError(
            "Structured equipment writes are locked. Set "
            "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED=true and pass authorized=True."
        )
    if not structured_equipment_schema_available(connection):
        raise RuntimeError("Structured equipment schema is not installed.")

    user_id = str(user_id or "").strip()
    recipe_id = str(recipe_id or "").strip()
    now = _utc_now_iso()
    connection.execute(
        "DELETE FROM recipe_equipment_requirements WHERE user_id = ? AND recipe_id = ?",
        (user_id, recipe_id),
    )
    for requirement in requirements if isinstance(requirements, list) else []:
        cursor = connection.execute(
            """
            INSERT INTO recipe_equipment_requirements (
                requirement_id, user_id, recipe_id, source_text, optional,
                quantity, notes, sort_order, connector, conjunction_group,
                parse_confidence, review_status, parser_version, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement.get("requirement_id"), user_id, recipe_id,
                requirement.get("source_text", ""), int(bool(requirement.get("optional"))),
                requirement.get("quantity", ""), requirement.get("notes", ""),
                int(requirement.get("sort_order") or 0), requirement.get("connector", "single"),
                requirement.get("conjunction_group", ""),
                float(requirement.get("parse_confidence") or 0),
                requirement.get("review_status", "pending"),
                requirement.get("parser_version", PARSER_VERSION),
                json.dumps(requirement.get("source_metadata") or {}, sort_keys=True),
                now, now,
            ),
        )
        requirement_row_id = int(cursor.lastrowid)
        for option in requirement.get("options", []):
            connection.execute(
                """
                INSERT INTO recipe_equipment_options (
                    option_id, user_id, requirement_id, equipment_id,
                    source_option_text, canonical_name, canonical_key, option_kind,
                    attributes_json, notes, sort_order, matched_alias_id, match_type,
                    match_confidence, review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    option.get("option_id"), user_id, requirement_row_id,
                    option.get("equipment_id"), option.get("source_option_text", ""),
                    option.get("canonical_name", ""), option.get("canonical_key", ""),
                    option.get("option_kind", "unresolved"),
                    json.dumps(option.get("attributes") or {}, sort_keys=True),
                    option.get("notes", ""), int(option.get("sort_order") or 0),
                    option.get("matched_alias_id"), option.get("match_type", ""),
                    float(option.get("match_confidence") or 0),
                    option.get("review_status", "pending"), now, now,
                ),
            )
    return requirement_summary(requirements)


def compatibility_equipment_rows(requirements):
    rows = []
    for requirement in requirements if isinstance(requirements, list) else []:
        options = requirement.get("options") if isinstance(requirement, dict) else []
        options = options if isinstance(options, list) else []
        if requirement.get("connector") == "and":
            text = str((options[0] if options else {}).get("source_option_text") or "").strip()
        else:
            text = str(requirement.get("source_text") or "").strip()
        if text:
            rows.append({
                "equipment": text,
                "text": text,
                "optional": bool(requirement.get("optional")),
            })
    return rows
