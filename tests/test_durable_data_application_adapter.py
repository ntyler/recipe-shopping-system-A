import json

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor
from PushShoppingList.services import durable_data_migration_service as migration


def installed_db(tmp_path):
    db_path = tmp_path / "application.sqlite3"
    application_data.install_application_schema(
        db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    return db_path


def cookbook_config(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "cookbooks.json").write_text(
        json.dumps({"cookbooks": [{"id": "one", "name": "One", "recipes": []}]}),
        encoding="utf-8",
    )
    return migration.DurableMigrationConfig(
        global_sources={},
        workspaces=(migration.WorkspaceSource(
            workspace_id="user-uuid",
            workspace_type="user",
            subject_id="user-uuid",
            root=workspace_root,
        ),),
        global_workspace=migration.WorkspaceSource(
            workspace_id="global:application",
            workspace_type="system",
            subject_id="application",
            root=tmp_path,
        ),
    )


def cookbook_descriptors():
    return tuple(
        descriptor
        for descriptor in migration.DEFAULT_SOURCE_DESCRIPTORS
        if descriptor.key == "cookbooks"
    )


def test_application_adapter_records_run_and_repairs_missing_document(tmp_path):
    db_path = installed_db(tmp_path)
    config = cookbook_config(tmp_path)
    descriptors = cookbook_descriptors()
    preview = migration.preview_durable_data(config, descriptors=descriptors)
    adapter = migration.application_data_service_adapter(db_path)

    first = migration.apply_durable_data(
        preview,
        config,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=descriptors,
    )
    assert first.adapter_actions == {"inserted": 1}
    with application_data.application_data_write_connection(db_path) as connection:
        coverage = connection.execute(
            "SELECT migration_run_id FROM application_source_coverage"
        ).fetchone()
        assert coverage["migration_run_id"]
        run = connection.execute(
            "SELECT status FROM migration_runs WHERE id = ?",
            (coverage["migration_run_id"],),
        ).fetchone()
        assert run["status"] == "succeeded"
        connection.execute(
            "DELETE FROM durable_documents WHERE workspace_id = ?",
            ("user-uuid",),
        )

    repaired = migration.apply_durable_data(
        preview,
        config,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=descriptors,
    )
    assert repaired.adapter_actions == {"inserted": 1}
    with application_data.existing_application_read_connection(db_path) as connection:
        document = application_data.get_durable_document(
            "user-uuid", "cookbooks", "catalog", connection=connection
        )
    assert document["document"]["cookbooks"][0]["id"] == "one"


def test_application_adapter_authenticates_and_repairs_encrypted_credentials(tmp_path):
    db_path = installed_db(tmp_path)
    workspace_root = tmp_path / "workspace"
    credentials = workspace_root / "recipe-extractor" / "data" / "store_credentials.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(
        json.dumps(
            {
                "credentials": {
                    "grocer": {"username": "person", "password": "secret-value"}
                }
            }
        ),
        encoding="utf-8",
    )
    config = migration.DurableMigrationConfig(
        global_sources={},
        workspaces=(
            migration.WorkspaceSource(
                workspace_id="user-uuid",
                workspace_type="user",
                subject_id="user-uuid",
                root=workspace_root,
            ),
        ),
        global_workspace=migration.WorkspaceSource(
            workspace_id="global:application",
            workspace_type="system",
            subject_id="application",
            root=tmp_path,
        ),
    )
    descriptors = tuple(
        descriptor
        for descriptor in migration.DEFAULT_SOURCE_DESCRIPTORS
        if descriptor.key == "store_credentials"
    )
    encryptor = AesGcmDataEncryptor(b"k" * 32, key_id="test-key")
    preview = migration.preview_durable_data(
        config,
        descriptors=descriptors,
        encryptor=encryptor,
    )
    adapter = migration.application_data_service_adapter(db_path)

    migration.apply_durable_data(
        preview,
        config,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=descriptors,
        encryptor=encryptor,
    )
    with application_data.application_data_write_connection(db_path) as connection:
        row = connection.execute(
            "SELECT document_json FROM durable_documents WHERE workspace_id = ?",
            ("user-uuid",),
        ).fetchone()
        assert "secret-value" not in row["document_json"]
        envelope = json.loads(row["document_json"])
        envelope["ciphertext"] = envelope["ciphertext"][:-1] + (
            "A" if envelope["ciphertext"][-1] != "A" else "B"
        )
        connection.execute(
            "UPDATE durable_documents SET document_json = ? WHERE workspace_id = ?",
            (application_data.canonical_json(envelope), "user-uuid"),
        )

    repaired = migration.apply_durable_data(
        preview,
        config,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=descriptors,
        encryptor=encryptor,
    )
    assert repaired.adapter_actions == {"updated": 1}
    with application_data.existing_application_read_connection(db_path) as connection:
        stored = application_data.get_durable_document(
            "user-uuid", "stores", "credentials", connection=connection
        )
    associated_data = "\x1f".join(
        ("user-uuid", "stores", "credentials", stored["source_sha256"])
    )
    decrypted = encryptor.decrypt_json(
        json.dumps(stored["document"]),
        associated_data=associated_data,
    )
    assert decrypted["credentials"]["grocer"]["password"] == "secret-value"
