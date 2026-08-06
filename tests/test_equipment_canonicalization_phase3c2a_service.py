import sqlite3

import pytest

from PushShoppingList.services import equipment_canonicalization_phase3c2a_service as phase3c2a
from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services.equipment_migration_apply_service import _json_hash


def _build_fixture(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            equipment_section TEXT NOT NULL DEFAULT 'MISC',
            display_name_override TEXT NOT NULL DEFAULT '',
            UNIQUE(user_id, normalized_name)
        );
        CREATE TABLE recipe_equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO equipment (
            id, user_id, name, normalized_name, created_at, updated_at
        ) VALUES (1, 'tenant', 'Whisk', 'whisk', 'before', 'before');
        """
    )
    requirements.ensure_structured_equipment_schema(
        connection,
        authorized=True,
        migration_token=requirements.PHASE3A_MIGRATION_TOKEN,
    )
    connection.execute(
        """
        INSERT INTO equipment_requirement_migration_runs (
            run_key, mode, source_hash, status, summary_json, started_at, completed_at
        ) VALUES ('fixture-stage', 'stage', 'fixture-source', 'complete', '{}', 'now', 'now')
        """
    )
    connection.execute(
        """
        INSERT INTO equipment_requirement_migration_runs (
            run_key, mode, source_hash, status, summary_json, started_at, completed_at
        ) VALUES ('fixture-3c1', 'canonicalize_high', 'fixture-source', 'complete', '{}', 'now', 'now')
        """
    )
    fixture_rows = (
        ("approved-existing", "Large whisk", "old whisk", '{"size":"large"}'),
        ("approved-new", "Heavy pan", "old pan", '{}'),
        ("owner-decision", "Mystery device", "mystery", '{}'),
    )
    for index, (logical_id, source_text, key, attributes) in enumerate(
        fixture_rows, start=1
    ):
        cursor = connection.execute(
            """
            INSERT INTO recipe_equipment_requirements (
                requirement_id, user_id, recipe_id, source_text, sort_order,
                review_status, created_at, updated_at
            ) VALUES (?, 'tenant', ?, ?, ?, 'pending', 'before', 'before')
            """,
            (logical_id, f"recipe-{index}", source_text, index),
        )
        connection.execute(
            """
            INSERT INTO recipe_equipment_options (
                option_id, user_id, requirement_id, source_option_text,
                canonical_name, canonical_key, option_kind, attributes_json,
                review_status, created_at, updated_at
            ) VALUES (?, 'tenant', ?, ?, ?, ?, 'equipment', ?,
                      'pending_master', 'before', 'before')
            """,
            (
                f"option-{index}", cursor.lastrowid, source_text,
                source_text, key, attributes,
            ),
        )
        connection.execute(
            """
            INSERT INTO equipment_normalization_reviews (
                user_id, source_kind, source_record_id, source_text,
                status, created_at, updated_at
            ) VALUES ('tenant', 'json', ?, ?, 'pending', 'before', 'before')
            """,
            (f"recipe-{index}#{logical_id}", source_text),
        )
    connection.commit()
    return connection


def _configure_fixture(monkeypatch, connection):
    targets = {
        ("tenant", "old whisk"): phase3c2a.TargetSpec(
            "tenant", "whisk", "Whisk", 1
        ),
        ("tenant", "old pan"): phase3c2a.TargetSpec(
            "tenant", "frying pan", "Frying pan"
        ),
    }
    monkeypatch.setattr(phase3c2a, "TARGET_SPECS", targets)
    monkeypatch.setattr(
        phase3c2a, "EXPECTED_REUSE_NORMALIZED_NAMES", {1: "whisk"}
    )
    monkeypatch.setattr(
        phase3c2a,
        "ATTRIBUTE_OVERRIDES_BY_PENDING_KEY",
        {("tenant", "old whisk"): {"purpose": "mixing"}},
    )
    rows = phase3c2a._pending_rows(connection)
    automatic = [row for row in rows if phase3c2a._is_approved_row(row)]
    holdouts = [row for row in rows if not phase3c2a._is_approved_row(row)]
    automatic_hash = _json_hash([
        [row["logical_requirement_id"], row["option_id"]] for row in automatic
    ])
    holdout_hash = _json_hash([
        [row["logical_requirement_id"], row["option_id"]] for row in holdouts
    ])
    monkeypatch.setattr(
        phase3c2a, "EXPECTED_AUTOMATIC_IDENTIFIER_SHA256", automatic_hash
    )
    monkeypatch.setattr(
        phase3c2a, "EXPECTED_HOLDOUT_IDENTIFIER_SHA256", holdout_hash
    )
    monkeypatch.setattr(phase3c2a, "EXPECTED", {
        "equipment_before": 1,
        "aliases_before": 0,
        "requirements_before": 3,
        "options_before": 3,
        "ready_requirements_before": 0,
        "pending_requirements_before": 3,
        "ready_options_before": 0,
        "pending_options_before": 3,
        "pending_reviews_before": 3,
        "automatic_requirements": 2,
        "automatic_options": 2,
        "holdout_requirements": 1,
        "holdout_options": 1,
        "new_equipment": 1,
        "reused_equipment": 1,
        "aliases_inserted": 2,
        "attributes_enhanced": 1,
        "equipment_after": 2,
        "aliases_after": 2,
        "requirements_after": 3,
        "options_after": 3,
        "ready_requirements_after": 2,
        "pending_requirements_after": 1,
        "ready_options_after": 2,
        "pending_options_after": 1,
        "pending_reviews_after": 1,
    })
    return automatic_hash, holdout_hash


def test_phase3c2a_selector_excludes_measurement_edges_and_individual_cases():
    base = {"user_id": phase3c2a.TENANT_LOCAL, "canonical_key": "measuring spoon"}
    assert phase3c2a._is_approved_row({**base, "source_option_text": "measuring spoons"})
    assert not phase3c2a._is_approved_row({**base, "source_option_text": "teaspoon"})
    assert not phase3c2a._is_approved_row({**base, "source_option_text": "tablespoon"})
    assert not phase3c2a._is_approved_row({
        "user_id": phase3c2a.TENANT_U,
        "canonical_key": "lid",
        "source_option_text": "lid",
    })


def test_phase3c2a_refuses_without_exact_approval(tmp_path):
    with pytest.raises(PermissionError, match=phase3c2a.CLI_APPROVAL_PHRASE):
        phase3c2a.apply_phase3c2a_canonicalization(
            tmp_path, approval_phrase="approved"
        )


def test_phase3c2a_transaction_is_bounded_and_idempotent(monkeypatch, tmp_path):
    database = tmp_path / "fixture.sqlite3"
    connection = _build_fixture(database)
    automatic_hash, holdout_hash = _configure_fixture(monkeypatch, connection)
    plan = phase3c2a.build_phase3c2a_plan(connection)
    holdout_before = phase3c2a._holdout_fingerprint(connection, plan["holdout_rows"])
    connection.close()

    backups = tmp_path / "backups"
    summary = phase3c2a.apply_phase3c2a_canonicalization(
        tmp_path,
        db_path=database,
        output_roots=[],
        backup_base=backups,
        approval_phrase=phase3c2a.CLI_APPROVAL_PHRASE,
    )

    assert summary["approved_scope"]["requirements_resolved"] == 2
    assert summary["approved_scope"]["options_resolved"] == 2
    assert summary["approved_scope"]["canonical_equipment_created"] == 1
    assert summary["approved_scope"]["aliases_inserted"] == 2
    assert summary["approved_scope"]["attributes_enhanced"] == 1
    assert summary["identifier_fingerprints"] == {
        "automatic": automatic_hash,
        "holdout": holdout_hash,
    }
    assert summary["post_commit"]["database_integrity_check"] == "ok"

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    pending = phase3c2a._pending_rows(connection)
    assert len(pending) == 1
    assert pending[0]["logical_requirement_id"] == "owner-decision"
    assert phase3c2a._holdout_fingerprint(connection, pending) == holdout_before
    enhanced = connection.execute(
        "SELECT attributes_json FROM recipe_equipment_options WHERE option_id = 'option-1'"
    ).fetchone()[0]
    assert enhanced == '{"purpose":"mixing","size":"large"}'
    connection.close()

    second = phase3c2a.apply_phase3c2a_canonicalization(
        tmp_path,
        db_path=database,
        output_roots=[],
        backup_base=backups,
        approval_phrase=phase3c2a.CLI_APPROVAL_PHRASE,
    )
    assert second["idempotent_noop"] is True
    assert len(list(backups.glob("*/manifest.json"))) == 1
