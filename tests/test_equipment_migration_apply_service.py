import json
import sqlite3
from pathlib import Path

from PushShoppingList.services import recipe_equipment_requirement_service as requirements
from PushShoppingList.services.equipment_migration_apply_service import (
    CLI_APPROVAL_PHRASE,
    legacy_table_fingerprint,
    stage_phase3a_migration,
)


def build_legacy_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            display_name_override TEXT NOT NULL DEFAULT '',
            equipment_section TEXT NOT NULL DEFAULT 'MISC',
            image_url TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_name)
        );
        CREATE TABLE recipe_equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            recipe_id TEXT NOT NULL,
            equipment_id INTEGER NOT NULL,
            original_recipe_text TEXT NOT NULL DEFAULT '',
            optional INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
        );
        INSERT INTO equipment VALUES
            (1, 'user-a', 'wok or large skillet', 'wok or large skillet', '', 'COOKWARE', '', '', 'now', 'now'),
            (2, 'user-a', 'Wok', 'wok', '', 'COOKWARE', '', '', 'now', 'now'),
            (3, 'user-a', 'Skillet', 'skillet', '', 'COOKWARE', '', '', 'now', 'now'),
            (4, 'user-a', 'Bowl', 'bowl', '', 'PREP', '', '', 'now', 'now'),
            (5, 'user-a', 'Whisk', 'whisk', '', 'PREP', '', '', 'now', 'now');
        INSERT INTO recipe_equipment VALUES
            (1, 'user-a', 'menu://shared?menu_item=one', 1, 'wok or large skillet', 0, 0),
            (2, 'user-a', 'manual://sql-only', 5, 'Whisk', 0, 0);
        """
    )
    connection.commit()
    before = legacy_table_fingerprint(connection)
    connection.close()
    return before


def test_phase3a_stages_additive_schema_with_verified_backup_and_is_idempotent(
    monkeypatch,
    tmp_path,
):
    repository_root = tmp_path / "repo"
    db_path = repository_root / "PushShoppingList" / "user_data" / "recipe_master.sqlite3"
    output_root = (
        repository_root / "PushShoppingList" / "user_data" / "users" / "user-a"
        / "recipe-extractor" / "data" / "output"
    )
    backup_base = tmp_path / "backups"
    output_root.mkdir(parents=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_before = build_legacy_database(db_path)
    (output_root / "one.json").write_text(
        json.dumps({
            "source_url": "menu://shared",
            "recipe_record_url": "menu://shared?menu_item=one",
            "equipment": [
                {"equipment": "wok or large skillet"},
                {"equipment": "bowl"},
            ],
            "instructions": ["Cook in a wok or large skillet."],
        }),
        encoding="utf-8",
    )

    for name in (
        "RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED",
        "RECIPE_EQUIPMENT_STRUCTURED_READ_ENABLED",
        "RECIPE_EQUIPMENT_STRUCTURED_WRITE_ENABLED",
        "RECIPE_EQUIPMENT_SCHEMA_WRITES_ENABLED",
        "RECIPE_EQUIPMENT_REVIEW_WRITES_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    summary = stage_phase3a_migration(
        repository_root,
        db_path=db_path,
        backup_base=backup_base,
        approval_phrase=CLI_APPROVAL_PHRASE,
    )

    assert summary["legacy_unchanged"] is True
    assert summary["post_commit"]["legacy_unchanged"] is True
    assert summary["backup"]["verified"] is True
    assert summary["backup"]["output_file_count"] == 1
    assert Path(summary["backup"]["manifest_path"]).is_file()
    assert summary["source_kinds"] == {"json": 1, "sql_only": 1}
    assert summary["counts"]["recipes_staged"] == 2
    assert summary["counts"]["requirements_staged"] == 3
    assert summary["counts"]["options_staged"] == 4
    assert summary["counts"]["legacy_links_mapped"] == 2
    assert summary["counts"]["legacy_links_unmapped"] == 0
    assert summary["post_commit"]["pending_review_rows"] == 1

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    assert legacy_table_fingerprint(connection) == legacy_before
    assert requirements.structured_equipment_schema_available(connection)
    assert connection.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 5
    assert connection.execute("SELECT COUNT(*) FROM recipe_equipment").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM recipe_equipment_requirements").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM recipe_equipment_options").fetchone()[0] == 4
    assert connection.execute(
        "SELECT COUNT(*) FROM recipe_equipment_options WHERE equipment_id IS NOT NULL"
    ).fetchone()[0] == 4
    connection.close()

    assert requirements.structured_equipment_ui_enabled() is False
    assert requirements.structured_equipment_read_enabled() is False
    assert requirements.structured_equipment_write_enabled() is False
    assert requirements.structured_equipment_schema_writes_enabled() is False
    assert requirements.structured_equipment_review_writes_enabled() is False

    backup_dirs_before = list(backup_base.iterdir())
    rerun = stage_phase3a_migration(
        repository_root,
        db_path=db_path,
        backup_base=backup_base,
        approval_phrase=CLI_APPROVAL_PHRASE,
    )
    assert rerun["idempotent_noop"] is True
    assert list(backup_base.iterdir()) == backup_dirs_before


def test_phase3a_refuses_to_run_without_exact_approval(tmp_path):
    try:
        stage_phase3a_migration(tmp_path, approval_phrase="yes")
    except PermissionError as exc:
        assert CLI_APPROVAL_PHRASE in str(exc)
    else:
        raise AssertionError("Phase 3A staging must require the exact approval phrase")


def test_phase3a_refuses_enabled_application_feature_flags(monkeypatch, tmp_path):
    monkeypatch.setenv("RECIPE_EQUIPMENT_STRUCTURED_UI_ENABLED", "true")
    try:
        stage_phase3a_migration(
            tmp_path,
            approval_phrase=CLI_APPROVAL_PHRASE,
        )
    except RuntimeError as exc:
        assert "remain disabled" in str(exc)
    else:
        raise AssertionError("Phase 3A must refuse enabled application feature flags")
