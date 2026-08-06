import sqlite3

import pytest

from PushShoppingList.services import equipment_canonicalization_phase3c3_service as phase3c3
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
        CREATE TABLE ingredients (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT ''
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
        ) VALUES ('fixture-3c2a', 'canonicalize_medium_auto', 'fixture-source',
                  'complete', '{}', 'now', 'now')
        """
    )
    fixture_rows = (
        ("approved-alias", "Large whisk", "old whisk", '{"size":"large"}'),
        ("approved-context", "whisk handle", "whisk handle", '{}'),
        ("owner-reject", "Mystery device", "mystery", '{}'),
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
    decisions = (
        phase3c3.DecisionSpec(
            1, "tenant", "recipe-1", 1, "approved-alias", 1, "option-1", 1,
            "Large whisk", "Large whisk", "single", "", "approve_recommended",
            current_canonical_key="old whisk", equipment_id=1,
            canonical_name="Whisk", canonical_key="whisk",
            attributes={"purpose": "mixing"}, alias_name="Large whisk",
            match_type="phase3c3_owner_alias", confidence=0.95,
        ),
        phase3c3.DecisionSpec(
            2, "tenant", "recipe-2", 2, "approved-context", 2, "option-2", 2,
            "whisk handle", "whisk handle", "single", "", "approve_recommended",
            current_canonical_key="whisk handle", equipment_id=1,
            canonical_name="Whisk", canonical_key="whisk",
            attributes={"component": "handle"},
            match_type="phase3c3_contextual_component", confidence=0.8,
        ),
        phase3c3.DecisionSpec(
            3, "tenant", "recipe-3", 3, "owner-reject", 3, "option-3", 3,
            "Mystery device", "Mystery device", "single", "", "reject_keep_pending",
            current_canonical_key="mystery",
        ),
    )
    monkeypatch.setattr(phase3c3, "DECISIONS", decisions)
    monkeypatch.setattr(
        phase3c3,
        "EXPECTED_TARGETS",
        {1: phase3c3.TargetExpectation("tenant", "Whisk", "whisk", "", "")},
    )
    monkeypatch.setattr(phase3c3, "EXPECTED_INGREDIENT_TARGETS", {})
    rows = phase3c3._pending_rows(connection)
    identifier = phase3c3._identifier_hash(rows)
    record_fingerprint = phase3c3._holdout_fingerprint(connection, rows)
    quarantine_hash = _json_hash([["owner-reject", "option-3"]])
    monkeypatch.setattr(phase3c3, "EXPECTED_IDENTIFIER_SHA256", identifier)
    monkeypatch.setattr(
        phase3c3, "EXPECTED_RECORD_FINGERPRINT", record_fingerprint
    )
    monkeypatch.setattr(
        phase3c3, "EXPECTED_QUARANTINE_IDENTIFIER_SHA256", quarantine_hash
    )
    monkeypatch.setattr(phase3c3, "EXPECTED", {
        "equipment_before": 1,
        "aliases_before": 0,
        "requirements_before": 3,
        "options_before": 3,
        "ready_requirements_before": 0,
        "pending_requirements_before": 3,
        "ready_options_before": 0,
        "pending_options_before": 3,
        "pending_reviews_before": 3,
        "approved_requirements": 2,
        "approved_options": 2,
        "rejected_requirements": 1,
        "rejected_options": 1,
        "aliases_inserted": 1,
        "equipment_after": 1,
        "aliases_after": 1,
        "requirements_after": 3,
        "options_after": 3,
        "ready_requirements_after": 2,
        "pending_requirements_after": 1,
        "ready_options_after": 2,
        "pending_options_after": 1,
        "pending_reviews_after": 0,
    })
    context = {"files": [], "sha256": "fixture-context"}
    monkeypatch.setattr(phase3c3, "_verify_recipe_context", lambda _root: context)
    return identifier, quarantine_hash


def test_phase3c3_refuses_without_exact_approval(tmp_path):
    with pytest.raises(PermissionError, match=phase3c3.CLI_APPROVAL_PHRASE):
        phase3c3.apply_phase3c3_owner_decisions(
            tmp_path, approval_phrase="approved"
        )


def test_phase3c3_transaction_is_bounded_and_idempotent(monkeypatch, tmp_path):
    database = tmp_path / "fixture.sqlite3"
    connection = _build_fixture(database)
    identifier, quarantine_hash = _configure_fixture(monkeypatch, connection)
    connection.close()

    backups = tmp_path / "backups"
    summary = phase3c3.apply_phase3c3_owner_decisions(
        tmp_path,
        db_path=database,
        output_roots=[],
        backup_base=backups,
        approval_phrase=phase3c3.CLI_APPROVAL_PHRASE,
    )

    assert summary["identifier_fingerprints"]["phase3c2b_holdout"] == identifier
    assert summary["approved_scope"]["requirements_resolved"] == 2
    assert summary["approved_scope"]["reviews_rejected"] == 1
    assert summary["approved_scope"]["aliases_inserted"] == 1
    assert summary["approved_scope"]["equipment_modified"] == 0
    assert summary["post_commit"]["quarantine_identifier_sha256"] == quarantine_hash
    assert summary["post_commit"]["database_integrity_check"] == "ok"

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 1
    alias = connection.execute(
        "SELECT equipment_id, alias_name, alias_key FROM equipment_aliases"
    ).fetchone()
    assert tuple(alias) == (1, "Large whisk", "large whisk")
    attributes = connection.execute(
        "SELECT attributes_json FROM recipe_equipment_options WHERE option_id = 'option-1'"
    ).fetchone()[0]
    assert attributes == '{"purpose":"mixing","size":"large"}'
    rejected = connection.execute(
        """
        SELECT r.review_status, o.review_status, rv.status, rv.decision
          FROM recipe_equipment_requirements r
          JOIN recipe_equipment_options o ON o.requirement_id = r.id
          JOIN equipment_normalization_reviews rv
            ON rv.source_record_id = r.recipe_id || '#' || r.requirement_id
         WHERE r.requirement_id = 'owner-reject'
        """
    ).fetchone()
    assert tuple(rejected) == (
        "pending", "pending_master", "resolved", "phase3c3_rejected_keep_pending"
    )
    connection.close()

    second = phase3c3.apply_phase3c3_owner_decisions(
        tmp_path,
        db_path=database,
        output_roots=[],
        backup_base=backups,
        approval_phrase=phase3c3.CLI_APPROVAL_PHRASE,
    )
    assert second["idempotent_noop"] is True
    assert len(list(backups.glob("*/manifest.json"))) == 1


def test_phase3c3_rolls_back_every_database_write(monkeypatch, tmp_path):
    database = tmp_path / "fixture.sqlite3"
    connection = _build_fixture(database)
    _configure_fixture(monkeypatch, connection)
    connection.close()

    original = phase3c3._apply_decisions

    def fail_after_updates(connection, plan, alias_ids, run_id, now):
        original(connection, plan, alias_ids, run_id, now)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(phase3c3, "_apply_decisions", fail_after_updates)
    with pytest.raises(RuntimeError, match="injected failure"):
        phase3c3.apply_phase3c3_owner_decisions(
            tmp_path,
            db_path=database,
            output_roots=[],
            backup_base=tmp_path / "backups",
            approval_phrase=phase3c3.CLI_APPROVAL_PHRASE,
        )

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM equipment_aliases").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM recipe_equipment_requirements WHERE review_status = 'pending'"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM recipe_equipment_options WHERE review_status <> 'ready'"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM equipment_normalization_reviews WHERE status = 'pending'"
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT COUNT(*) FROM equipment_requirement_migration_runs WHERE mode = 'canonicalize_owner_decisions'"
    ).fetchone()[0] == 0
    connection.close()
