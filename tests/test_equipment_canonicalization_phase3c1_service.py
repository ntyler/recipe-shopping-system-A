import sqlite3

import pytest

from PushShoppingList.services import equipment_canonicalization_phase3c1_service as phase3c1
from PushShoppingList.services import recipe_equipment_requirement_service as requirements


def _build_small_staged_database(path):
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
        ) VALUES (1, 'tenant', 'Legacy item', 'legacy item', 'now', 'now');
        """
    )
    requirements.ensure_structured_equipment_schema(
        connection,
        authorized=True,
        migration_token=requirements.PHASE3A_MIGRATION_TOKEN,
    )
    now = "now"
    for index, (text, key) in enumerate((
        ("Whisk", "whisk"),
        ("Uncertain pan", "uncertain pan"),
    ), start=1):
        cursor = connection.execute(
            """
            INSERT INTO recipe_equipment_requirements (
                requirement_id, user_id, recipe_id, source_text, sort_order,
                review_status, created_at, updated_at
            ) VALUES (?, 'tenant', ?, ?, ?, 'pending', ?, ?)
            """,
            (f"requirement-{index}", f"recipe-{index}", text, index, now, now),
        )
        connection.execute(
            """
            INSERT INTO recipe_equipment_options (
                option_id, user_id, requirement_id, source_option_text,
                canonical_name, canonical_key, option_kind, review_status,
                created_at, updated_at
            ) VALUES (?, 'tenant', ?, ?, ?, ?, 'equipment', 'pending_master', ?, ?)
            """,
            (f"option-{index}", cursor.lastrowid, text, text, key, now, now),
        )
        connection.execute(
            """
            INSERT INTO equipment_normalization_reviews (
                user_id, source_kind, source_record_id, source_text,
                status, created_at, updated_at
            ) VALUES ('tenant', 'json', ?, ?, 'pending', ?, ?)
            """,
            (f"recipe-{index}#requirement-{index}", text, now, now),
        )
    connection.commit()
    return connection


def test_phase3c1_plan_separates_high_and_medium_without_writes(monkeypatch, tmp_path):
    connection = _build_small_staged_database(tmp_path / "staged.sqlite3")
    monkeypatch.setattr(phase3c1, "MEDIUM_PENDING_MASTER", {("tenant", "uncertain pan")})
    monkeypatch.setattr(phase3c1, "INDIVIDUAL_PENDING_MASTER", set())
    monkeypatch.setattr(phase3c1, "HIGH_PARSER_OPTIONS", set())
    monkeypatch.setattr(phase3c1, "MEDIUM_PARSER_OPTIONS", set())
    monkeypatch.setattr(phase3c1, "INDIVIDUAL_PARSER_OPTIONS", set())
    monkeypatch.setattr(phase3c1, "VERIFIED_REUSE_TARGETS", {})
    monkeypatch.setattr(phase3c1, "STRUCTURAL_TARGETS", set())
    expected = dict(phase3c1.EXPECTED)
    expected.update({
        "legacy_equipment_rows": 1,
        "requirements_before": 2,
        "options_before": 2,
        "ready_requirements_before": 0,
        "pending_requirements_before": 2,
        "ready_options_before": 0,
        "pending_options_before": 2,
        "high_options": 1,
        "high_requirements": 1,
        "new_equipment": 1,
        "reused_equipment": 0,
        "medium_requirements_after": 1,
        "individual_requirements_after": 0,
    })
    monkeypatch.setattr(phase3c1, "EXPECTED", expected)

    before = phase3c1._staged_fingerprint(connection)
    plan = phase3c1.build_phase3c1_plan(connection)
    after = phase3c1._staged_fingerprint(connection)

    assert len(plan["high_rows"]) == 1
    assert len(plan["high_requirement_ids"]) == 1
    assert plan["new_targets"] == {("tenant", "whisk")}
    assert plan["holdout_requirements"]["medium"]
    assert after == before
    connection.close()


def test_phase3c1_contextual_spoons_mapping():
    measuring = {
        "canonical_key": "spoons",
        "user_id": phase3c1.TENANT_U,
        "requirement_source": "measuring cups and spoons",
    }
    serving = {
        "canonical_key": "spoons",
        "user_id": phase3c1.TENANT_U,
        "requirement_source": "forks or spoons",
    }
    assert phase3c1._target_key(measuring) == "measuring spoon"
    assert phase3c1._target_key(serving) == "spoon"


def test_phase3c1_refuses_without_exact_approval(tmp_path):
    with pytest.raises(PermissionError, match=phase3c1.CLI_APPROVAL_PHRASE):
        phase3c1.apply_phase3c1_canonicalization(tmp_path, approval_phrase="approved")


def test_phase3c1_refuses_enabled_feature_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED", "true")
    with pytest.raises(RuntimeError, match="remain disabled"):
        phase3c1.apply_phase3c1_canonicalization(
            tmp_path,
            approval_phrase=phase3c1.CLI_APPROVAL_PHRASE,
        )
