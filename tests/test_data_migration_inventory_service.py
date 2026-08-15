import json
from datetime import datetime, timezone

from PushShoppingList.services import data_migration_inventory_service as inventory_service
from PushShoppingList.services import durable_data_migration_service as durable_migration


def write_registry(path, key, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: records}), encoding="utf-8")


def configured_environment(tmp_path):
    return {
        "SHOPPING_APP_USERS_FILE": str(tmp_path / "users.json"),
        "SHOPPING_APP_GUEST_SESSIONS_FILE": str(tmp_path / "guest_sessions.json"),
        "SHOPPING_APP_USER_DATA_DIR": str(tmp_path / "user_data" / "users"),
        "SHOPPING_APP_GUEST_DATA_DIR": str(tmp_path / "user_data" / "guests"),
        "SHOPPING_APP_FEEDBACK_FILE": str(tmp_path / "feedback.json"),
        "SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE": str(tmp_path / "audit.json"),
        "SHOPPING_APP_FEEDBACK_UPLOAD_DIR": str(tmp_path / "feedback_uploads"),
        "SHOPPING_APP_AVATAR_UPLOAD_DIR": str(tmp_path / "avatar_uploads"),
    }


def test_inventory_preserves_opaque_user_and_guest_ids_and_classifies_orphans(tmp_path):
    environment = configured_environment(tmp_path)
    opaque_user_id = " User / UUID 01 "
    write_registry(
        tmp_path / "users.json",
        "users",
        [{"user_id": opaque_user_id}],
    )
    write_registry(
        tmp_path / "guest_sessions.json",
        "guest_sessions",
        [{
            "id": "guest-active",
            "is_active": True,
            "expires_at": "2026-09-01T00:00:00Z",
        }],
    )
    (tmp_path / "user_data" / "users" / "UserUUID01").mkdir(parents=True)
    (tmp_path / "user_data" / "guests" / "guest-active").mkdir(parents=True)
    (tmp_path / "user_data" / "guests" / "guest-orphan").mkdir(parents=True)

    inventory = inventory_service.build_default_migration_inventory(
        environment=environment,
        clock=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert inventory.ready is True
    assert inventory.user_workspace_count == 1
    assert inventory.guest_workspace_count == 1
    assert inventory.orphan_guest_workspace_count == 1
    by_id = {workspace.workspace_id: workspace for workspace in inventory.config.workspaces}
    assert by_id[opaque_user_id].subject_id == opaque_user_id
    assert by_id["guest:guest-active"].lifecycle_state == "active"
    assert by_id["guest:guest-orphan"].lifecycle_state == "inactive"

    preview = durable_migration.preview_durable_data(inventory.config)
    assert preview.counts_by_classification[durable_migration.CLASSIFICATION_ARTIFACT] > 0
    report = json.dumps(preview.to_dict(), sort_keys=True)
    assert opaque_user_id not in report
    assert "guest-active" not in report


def test_unmapped_user_directory_blocks_apply_configuration(tmp_path):
    environment = configured_environment(tmp_path)
    write_registry(tmp_path / "users.json", "users", [])
    write_registry(tmp_path / "guest_sessions.json", "guest_sessions", [])
    unexpected = tmp_path / "user_data" / "users" / "unmapped-user"
    unexpected.mkdir(parents=True)

    inventory = inventory_service.build_default_migration_inventory(
        environment=environment
    )

    assert inventory.ready is False
    assert [issue.to_dict() for issue in inventory.issues] == [{
        "blocking": True,
        "code": "unmapped_user_workspace",
        "count": 1,
    }]
    assert unexpected.is_dir()


def test_inventory_does_not_create_missing_roots_or_sources(tmp_path):
    environment = configured_environment(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    inventory = inventory_service.build_default_migration_inventory(
        environment=environment
    )

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert inventory.ready is True
    assert before == after == []

