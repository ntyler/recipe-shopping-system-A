import json

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import durable_document_runtime_service as runtime
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor


def installed_database(tmp_path):
    db_path = tmp_path / "application.sqlite3"
    application_data.install_application_schema(
        db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    return db_path


def document_identity(workspace_id="user-1"):
    return {
        "workspace_id": workspace_id,
        "workspace_type": "user",
        "subject_id": workspace_id,
        "domain": "pantry",
        "document_key": "inventory",
        "source_key": "pantry_inventory",
        "source_ref": "pantry_inventory.json",
    }


def read_identity(identity):
    return {
        key: identity[key]
        for key in (
            "workspace_id",
            "domain",
            "document_key",
            "source_key",
            "source_ref",
        )
    }


def test_json_mode_never_requires_or_writes_a_database(monkeypatch, tmp_path):
    monkeypatch.delenv(runtime.DURABLE_BACKEND_ENV, raising=False)
    legacy_path = tmp_path / "pantry.json"
    legacy_path.write_text('{"items":[{"id":"legacy"}]}', encoding="utf-8")

    loaded = runtime.load_json_document(
        lambda: json.loads(legacy_path.read_text(encoding="utf-8")),
        **document_identity(),
    )
    assert loaded == {"items": [{"id": "legacy"}]}

    saved = runtime.save_json_document(
        {"items": [{"id": "updated"}]},
        lambda value: runtime.atomic_write_json(legacy_path, value),
        **document_identity(),
    )
    assert saved == {"items": [{"id": "updated"}]}
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == saved
    assert not (tmp_path / "application.sqlite3").exists()


def test_db_preferred_reads_and_writes_only_after_exact_coverage(monkeypatch, tmp_path):
    db_path = installed_database(tmp_path)
    identity = document_identity()
    runtime.write_database_document(
        {"items": [{"id": "database"}]}, db_path=db_path, **identity
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")
    legacy_writes = []

    loaded = runtime.load_json_document(
        lambda: {"items": [{"id": "stale-json"}]},
        db_path=db_path,
        **identity,
    )
    assert loaded == {"items": [{"id": "database"}]}

    updated = {"items": [{"id": "database-updated"}]}
    result = runtime.save_json_document(
        updated,
        lambda value: legacy_writes.append(value),
        db_path=db_path,
        **identity,
    )
    assert result == updated
    assert legacy_writes == []
    assert runtime.read_database_document(
        db_path=db_path, **read_identity(identity)
    ) == updated


def test_partial_coverage_fails_closed_and_does_not_touch_another_workspace(
    monkeypatch, tmp_path
):
    db_path = installed_database(tmp_path)
    first = document_identity("user-1")
    unrelated = document_identity("user-2")
    runtime.write_database_document({"items": ["first"]}, db_path=db_path, **first)
    runtime.write_database_document(
        {"items": ["unrelated"]}, db_path=db_path, **unrelated
    )
    coverage_key = runtime.source_coverage_key(
        first["workspace_id"], first["source_key"], first["source_ref"]
    )
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute(
            """
            DELETE FROM application_source_coverage
             WHERE workspace_id = ? AND domain = ? AND source_key = ?
            """,
            (first["workspace_id"], first["domain"], coverage_key),
        )

    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")
    with pytest.raises(runtime.DurableDocumentRuntimeError, match="incomplete"):
        runtime.load_json_document(
            lambda: {"items": ["stale-json"]}, db_path=db_path, **first
        )

    assert runtime.read_database_document(
        db_path=db_path, **read_identity(unrelated)
    ) == {
        "items": ["unrelated"]
    }


def test_concurrent_database_write_is_rejected_and_can_be_retried(tmp_path):
    db_path = installed_database(tmp_path)
    identity = document_identity()
    runtime.write_database_document({"items": ["one"]}, db_path=db_path, **identity)
    old_sha = runtime.canonical_source_sha256({"items": ["one"]})
    runtime.write_database_document(
        {"items": ["two"]},
        db_path=db_path,
        expected_source_sha256=old_sha,
        **identity,
    )

    with pytest.raises(runtime.DurableDocumentConflictError):
        runtime.write_database_document(
            {"items": ["stale-three"]},
            db_path=db_path,
            expected_source_sha256=old_sha,
            **identity,
        )

    current_sha = runtime.canonical_source_sha256({"items": ["two"]})
    runtime.write_database_document(
        {"items": ["three"]},
        db_path=db_path,
        expected_source_sha256=current_sha,
        **identity,
    )
    assert runtime.read_database_document(
        db_path=db_path, **read_identity(identity)
    ) == {
        "items": ["three"]
    }


def test_encrypted_document_round_trip_never_stores_plaintext(tmp_path):
    db_path = installed_database(tmp_path)
    identity = {
        **document_identity(),
        "domain": "stores",
        "document_key": "credentials",
        "source_key": "store_credentials",
        "source_ref": "recipe-extractor/data/store_credentials.json",
    }
    encryptor = AesGcmDataEncryptor(b"k" * 32, key_id="test-key")
    secret_document = {
        "credentials": {"store": {"username": "person", "password": "secret-value"}}
    }

    runtime.write_database_document(
        secret_document,
        encrypted=True,
        encryptor=encryptor,
        db_path=db_path,
        **identity,
    )
    assert runtime.read_database_document(
        encrypted=True,
        encryptor=encryptor,
        db_path=db_path,
        **read_identity(identity),
    ) == secret_document
    assert b"secret-value" not in db_path.read_bytes()
