import hashlib
import json
import sqlite3
from pathlib import Path

from PushShoppingList.services.equipment_migration_preview_service import (
    build_equipment_migration_preview,
)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preview_resolves_legacy_menu_source_collision_without_writes(tmp_path):
    repository_root = tmp_path / "repo"
    db_path = repository_root / "PushShoppingList" / "user_data" / "recipe_master.sqlite3"
    output_root = (
        repository_root
        / "PushShoppingList"
        / "user_data"
        / "users"
        / "user-a"
        / "recipe-extractor"
        / "data"
        / "output"
    )
    output_root.mkdir(parents=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL
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
        INSERT INTO equipment VALUES (1, 'user-a', 'knife and cutting board');
        INSERT INTO recipe_equipment VALUES (
            1, 'user-a', 'menu://shared?menu_item=first', 1,
            'knife and cutting board', 0, 0
        );
        """
    )
    connection.commit()
    connection.close()

    shared_url = "menu://shared"
    for index, equipment in enumerate(("wok or large skillet", "paper towels"), start=1):
        recipe_url = f"{shared_url}?menu_item=item-{index}"
        (output_root / f"recipe-{index}.json").write_text(
            json.dumps({
                "source_url": shared_url,
                "recipe_record_url": recipe_url,
                "equipment": [{"equipment": equipment}],
                "instructions": [],
            }),
            encoding="utf-8",
        )

    before = file_hash(db_path)
    report = build_equipment_migration_preview(repository_root, db_path=db_path)
    after = file_hash(db_path)

    assert before == after
    assert report["read_only"] is True
    assert report["write_operations_performed"] is False
    assert report["database"]["unchanged"] is True
    assert report["identity"]["legacy_collision_keys"] == 1
    assert report["identity"]["stable_collision_keys"] == 0
    assert report["identity"]["stable_divergent_collision_keys"] == 0
    assert report["outputs"]["stable_unique_recipes"] == 2
    assert report["proposed"]["sql_parse"]["conjoined_requirements"] == 2
    assert report["proposed"]["json_parse"]["alternative_requirements"] == 1
    assert report["proposed"]["json_parse"]["supply_options"] == 1


def test_preview_discovery_excludes_hidden_backup_outputs(tmp_path):
    repository_root = tmp_path / "repo"
    active = (
        repository_root / "PushShoppingList" / "user_data" / "users" / "user-a"
        / "recipe-extractor" / "data" / "output"
    )
    backup = (
        repository_root / "PushShoppingList" / "user_data" / ".migration-backups"
        / "users" / "user-a" / "recipe-extractor" / "data" / "output"
    )
    active.mkdir(parents=True)
    backup.mkdir(parents=True)

    from PushShoppingList.services.equipment_migration_preview_service import discover_output_roots

    assert discover_output_roots(repository_root) == [active.resolve()]


def test_workspace_resolution_uses_repository_users_segment_on_windows_style_path():
    from PushShoppingList.services.equipment_migration_preview_service import workspace_id_for_output_root

    path = Path(
        "C:/Users/Tyler/repo/PushShoppingList/user_data/users/workspace-a/"
        "recipe-extractor/data/output"
    )
    assert workspace_id_for_output_root(path) == "workspace-a"
