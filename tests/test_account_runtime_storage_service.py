import base64
import json
import logging
import sqlite3

import pytest

from PushShoppingList.services import account_data_migration_service as migration
from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import account_runtime_storage_service as runtime
from PushShoppingList.services import user_account_service as accounts
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor
from PushShoppingList.services.data_encryption_service import DATA_ENCRYPTION_KEY_ENV
from PushShoppingList.services.data_encryption_service import DATA_ENCRYPTION_KEY_ID_ENV


def account_record(account_id="account-uuid-1"):
    return {
        "user_id": account_id,
        "username": "alice",
        "email": "Alice@Example.test",
        "account_status": "active",
        "auth_provider": "local",
        "password_hash": "scrypt:preserved-hash",
        "notification_topic": "private-notification-topic",
        "two_factor": {
            "enabled": True,
            "secret": "JBSWY3DPEHPK3PXP",
            "backup_codes": [],
            "trusted_devices": [],
        },
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }


def configure_encryption(monkeypatch):
    key = b"a" * 32
    monkeypatch.setenv(
        DATA_ENCRYPTION_KEY_ENV,
        base64.urlsafe_b64encode(key).decode("ascii"),
    )
    monkeypatch.setenv(DATA_ENCRYPTION_KEY_ID_ENV, "account-test-key")
    return AesGcmDataEncryptor(key, key_id="account-test-key")


def migrate_accounts(monkeypatch, tmp_path, users):
    users_path = tmp_path / "users.json"
    db_path = tmp_path / "recipe.sqlite3"
    users_path.write_text(
        json.dumps({"users": users}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    encryptor = configure_encryption(monkeypatch)
    preview = migration.preview_account_data_migration(users_path)
    assert preview.ready is True
    migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=db_path,
        encryptor=encryptor,
    )
    monkeypatch.setattr(accounts, "USERS_FILE", users_path)
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(db_path))
    return users_path, db_path


def test_db_preferred_preserves_uuid_and_secrets_then_stops_writing_json(
    monkeypatch, tmp_path
):
    original = account_record()
    users_path, db_path = migrate_accounts(monkeypatch, tmp_path, [original])
    users_path.write_text(
        json.dumps({"users": [{**original, "username": "stale-json"}]}),
        encoding="utf-8",
    )
    stale_bytes = users_path.read_bytes()
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_preferred")

    loaded = accounts.load_users()
    assert loaded["users"][0]["user_id"] == "account-uuid-1"
    assert loaded["users"][0]["username"] == "alice"
    assert loaded["users"][0]["notification_topic"] == "private-notification-topic"
    assert loaded["users"][0]["two_factor"]["secret"] == "JBSWY3DPEHPK3PXP"

    loaded["users"][0]["username"] = "database-only-update"
    saved = accounts.save_users(loaded)
    assert saved["users"][0]["username"] == "database-only-update"
    assert users_path.read_bytes() == stale_bytes
    assert b"private-notification-topic" not in db_path.read_bytes()
    assert b"JBSWY3DPEHPK3PXP" not in db_path.read_bytes()


def test_empty_migrated_registry_does_not_fall_back_to_stale_json(
    monkeypatch, tmp_path
):
    original = account_record()
    users_path, _db_path = migrate_accounts(monkeypatch, tmp_path, [original])
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_preferred")

    assert accounts.save_users({"users": []}) == {"users": []}
    assert json.loads(users_path.read_text(encoding="utf-8"))["users"] == [original]
    assert accounts.load_users() == {"users": []}


def test_shadow_failure_keeps_primary_json_and_emits_redacted_event(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.INFO, logger="shopping_app.maintenance")
    users_path = tmp_path / "users.json"
    monkeypatch.setattr(accounts, "USERS_FILE", users_path)
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "shadow")
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(tmp_path / "missing.sqlite3"))

    payload = {"users": [account_record()]}
    assert accounts.save_users(payload) == payload
    assert json.loads(users_path.read_text(encoding="utf-8")) == payload
    assert "account_shadow_write" in caplog.text
    assert "private-notification-topic" not in caplog.text


def test_json_concurrent_change_is_preserved_and_operation_can_be_retried(
    monkeypatch, tmp_path
):
    users_path = tmp_path / "users.json"
    monkeypatch.setattr(accounts, "USERS_FILE", users_path)
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "json")
    accounts.save_users({"users": [account_record()]})
    stale = accounts.load_users()

    concurrent = {"users": [{**account_record(), "username": "concurrent"}]}
    users_path.write_text(json.dumps(concurrent), encoding="utf-8")
    stale["users"][0]["username"] = "stale-writer"
    with pytest.raises(accounts.AccountRegistryConflictError):
        accounts.save_users(stale)
    assert json.loads(users_path.read_text(encoding="utf-8")) == concurrent

    latest = accounts.load_users()
    latest["users"][0]["username"] = "retried"
    accounts.save_users(latest)
    assert accounts.load_users()["users"][0]["username"] == "retried"


def test_database_concurrent_change_is_rejected_without_lost_update(
    monkeypatch, tmp_path
):
    _users_path, db_path = migrate_accounts(
        monkeypatch, tmp_path, [account_record()]
    )
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_only")
    stale = accounts.load_users()
    concurrent = {"users": [{**account_record(), "username": "concurrent"}]}
    runtime.replace_database_users(concurrent, db_path=db_path)

    stale["users"][0]["username"] = "stale-writer"
    with pytest.raises(runtime.AccountRuntimeConflictError):
        accounts.save_users(stale)
    assert accounts.load_users()["users"][0]["username"] == "concurrent"


def test_db_preferred_rejects_a_silently_missing_covered_account(
    monkeypatch, tmp_path
):
    original = account_record()
    users_path, db_path = migrate_accounts(monkeypatch, tmp_path, [original])
    legacy_bytes = users_path.read_bytes()
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute(
            "DELETE FROM workspaces WHERE id = ?",
            (original["user_id"],),
        )
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_preferred")

    with pytest.raises(
        runtime.AccountRuntimeStorageError,
        match="coverage is incomplete",
    ):
        accounts.load_users()
    assert users_path.read_bytes() == legacy_bytes


@pytest.mark.parametrize("schema_state", ["installed", "partial"])
def test_db_only_rejects_schema_without_a_completed_registry_migration(
    monkeypatch, tmp_path, schema_state
):
    users_path = tmp_path / "users.json"
    original = {"users": [account_record()]}
    users_path.write_text(json.dumps(original), encoding="utf-8")
    database = tmp_path / "application.sqlite3"
    if schema_state == "installed":
        application_data.install_application_schema(
            database,
            dry_run=False,
            authorized=True,
            approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
        )
    else:
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY)")
    monkeypatch.setattr(accounts, "USERS_FILE", users_path)
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(database))
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_only")

    with pytest.raises(runtime.AccountRuntimeStorageError):
        accounts.load_users()
    with pytest.raises(runtime.AccountRuntimeStorageError):
        accounts.save_users(original)

    assert json.loads(users_path.read_text(encoding="utf-8")) == original
    if schema_state == "installed":
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_empty_account_source_is_authoritative_idempotent_and_accepts_normal_db_only_writes(
    monkeypatch, tmp_path
):
    users_path = tmp_path / "users.json"
    users_path.write_text('{"users":[]}\n', encoding="utf-8")
    legacy_bytes = users_path.read_bytes()
    database = tmp_path / "application.sqlite3"
    configure_encryption(monkeypatch)
    preview = migration.preview_account_data_migration(users_path)

    first = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=database,
    )
    second = migration.apply_account_data_migration(
        preview,
        approval=migration.APPLY_APPROVAL_PHRASE,
        source_path=users_path,
        db_path=database,
    )

    assert first.migration_run_id
    assert first.no_op is False
    assert second.no_op is True
    assert runtime.database_accounts_are_authoritative(database) is True

    monkeypatch.setattr(accounts, "USERS_FILE", users_path)
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(database))
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_only")
    assert accounts.load_users() == {"users": []}
    created = accounts.save_users({"users": [account_record()]})
    created["users"][0]["username"] = "updated-in-db"
    accounts.save_users(created)

    assert accounts.load_users()["users"][0]["username"] == "updated-in-db"
    assert users_path.read_bytes() == legacy_bytes
    assert runtime.database_accounts_are_authoritative(database) is True


def test_db_only_rejects_missing_rows_and_stale_latest_run_coverage(
    monkeypatch, tmp_path
):
    original = account_record()
    _users_path, database = migrate_accounts(monkeypatch, tmp_path, [original])
    monkeypatch.setenv(runtime.ACCOUNT_BACKEND_ENV, "db_only")

    with application_data.application_data_write_connection(database) as connection:
        application_data.record_application_migration_run(
            migration.SOURCE_KIND,
            "succeeded",
            run_id="stale-later-run",
            source_sha256="f" * 64,
            summary={
                "account_count": 1,
                "account_manifest_sha256": "e" * 64,
            },
            connection=connection,
        )

    with pytest.raises(runtime.AccountRuntimeStorageError):
        accounts.load_users()

    # Removing the later marker does not make a missing covered row acceptable.
    with application_data.application_data_write_connection(database) as connection:
        connection.execute("DELETE FROM migration_runs WHERE id = ?", ("stale-later-run",))
        connection.execute(
            "DELETE FROM workspaces WHERE id = ?",
            (original["user_id"],),
        )

    with pytest.raises(
        runtime.AccountRuntimeStorageError,
        match="coverage is incomplete",
    ):
        accounts.load_users()
