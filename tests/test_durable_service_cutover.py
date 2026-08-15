import base64
import json
import subprocess
import sys
import time

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import durable_document_runtime_service as runtime
from PushShoppingList.services import durable_data_migration_service as durable_migration
from PushShoppingList.services import pantry_service
from PushShoppingList.services import recipe_edit_service
from PushShoppingList.services import recipe_extract_service
from PushShoppingList.services import recipe_ingredient_service
from PushShoppingList.services import recipe_master_data_service
from PushShoppingList.services import storage_service
from PushShoppingList.services import store_settings_service
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor
from PushShoppingList.services.data_encryption_service import DATA_ENCRYPTION_KEY_ENV
from PushShoppingList.services.data_encryption_service import DATA_ENCRYPTION_KEY_ID_ENV


def install_runtime_database(monkeypatch, tmp_path):
    db_path = tmp_path / "application.sqlite3"
    application_data.install_application_schema(
        db_path,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )
    monkeypatch.setenv("SHOPPING_APP_RECIPE_MASTER_DB", str(db_path))
    monkeypatch.setattr(recipe_master_data_service, "RECIPE_MASTER_DB_PATH", db_path)
    return db_path


def test_pantry_db_preferred_cutover_leaves_legacy_json_unchanged(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "user-1"
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    legacy_path = storage_service.user_data_root(user_id) / "pantry_inventory.json"
    legacy_payload = {"items": [{"ingredient_name": "legacy carrots"}]}
    legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    identity = {
        "workspace_id": user_id,
        "workspace_type": "user",
        "subject_id": user_id,
        "domain": "pantry",
        "document_key": "inventory",
        "source_key": "pantry_inventory",
        "source_ref": "pantry_inventory.json",
    }
    runtime.write_database_document(
        {"items": [{"ingredient_name": "database onions"}]},
        db_path=db_path,
        **identity,
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    loaded = pantry_service.load_pantry_inventory(user_id=user_id)
    assert loaded["items"][0]["ingredient_name"] == "database onions"

    loaded["items"][0]["ingredient_name"] = "database shallots"
    pantry_service.save_pantry_inventory(loaded, user_id=user_id)

    assert json.loads(legacy_path.read_text(encoding="utf-8")) == legacy_payload
    stored = runtime.read_database_document(
        workspace_id=user_id,
        domain="pantry",
        document_key="inventory",
        source_key="pantry_inventory",
        source_ref="pantry_inventory.json",
        db_path=db_path,
    )
    assert stored["items"][0]["ingredient_name"] == "database shallots"


def test_store_credentials_db_preferred_are_encrypted_and_service_round_trips(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "user-credentials"
    key = b"s" * 32
    key_id = "service-test-key"
    monkeypatch.setenv(
        DATA_ENCRYPTION_KEY_ENV,
        base64.urlsafe_b64encode(key).decode("ascii").rstrip("="),
    )
    monkeypatch.setenv(DATA_ENCRYPTION_KEY_ID_ENV, key_id)
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    legacy_path = tmp_path / "store_credentials.json"
    legacy_secret = "legacy-secret-must-remain-untouched"
    legacy_path.write_text(
        json.dumps(
            {
                "credentials": {
                    "aldi": {"username": "legacy", "password": legacy_secret}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store_settings_service, "STORE_CREDENTIALS_FILE", legacy_path)

    identity = {
        "workspace_id": user_id,
        "workspace_type": "user",
        "subject_id": user_id,
        "domain": "stores",
        "document_key": "credentials",
        "source_key": "store_credentials",
        "source_ref": "recipe-extractor/data/store_credentials.json",
    }
    runtime.write_database_document(
        {
            "credentials": {
                "aldi": {"username": "database", "password": "first-secret"}
            }
        },
        encrypted=True,
        encryptor=AesGcmDataEncryptor(key, key_id=key_id),
        db_path=db_path,
        **identity,
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    assert store_settings_service.load_store_credentials()["credentials"]["aldi"] == {
        "username": "database",
        "password": "first-secret",
    }
    store_settings_service.save_store_credentials(
        {
            "credentials": {
                "aldi": {"username": "updated", "password": "second-secret"}
            }
        }
    )

    assert json.loads(legacy_path.read_text(encoding="utf-8"))["credentials"][
        "aldi"
    ]["password"] == legacy_secret
    assert store_settings_service.load_store_credentials()["credentials"]["aldi"] == {
        "username": "updated",
        "password": "second-secret",
    }
    database_bytes = db_path.read_bytes()
    assert b"first-secret" not in database_bytes
    assert b"second-secret" not in database_bytes


def test_recipe_output_db_preferred_uses_database_and_keeps_rollback_json(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "recipe-user"
    output_dir = tmp_path / "recipe-extractor" / "data" / "output"
    output_dir.mkdir(parents=True)
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_ingredient_service, "OUTPUT_FOLDER", output_dir)
    url = "https://example.test/recipes/one"
    output_path = recipe_edit_service.recipe_output_json_path(
        url, output_folder=output_dir
    )
    database_payload = {
        "source_url": url,
        "recipe_title": "Database recipe",
        "ingredients": [{"ingredient": "egg yolks"}],
    }
    output_path.write_text(json.dumps(database_payload), encoding="utf-8")
    global_root = tmp_path / "global"
    global_root.mkdir()
    configuration = durable_migration.DurableMigrationConfig(
        global_sources={},
        workspaces=(
            durable_migration.WorkspaceSource(
                user_id, "user", user_id, tmp_path
            ),
        ),
        global_workspace=durable_migration.WorkspaceSource(
            "global:application", "system", "application", global_root
        ),
    )
    recipe_descriptor = next(
        descriptor
        for descriptor in durable_migration.DEFAULT_SOURCE_DESCRIPTORS
        if descriptor.key == "recipe_json"
    )
    preview = durable_migration.preview_durable_data(
        configuration, descriptors=(recipe_descriptor,)
    )
    durable_migration.apply_durable_data(
        preview,
        configuration,
        durable_migration.application_data_service_adapter(db_path),
        approval=durable_migration.APPLY_APPROVAL_PHRASE,
        descriptors=(recipe_descriptor,),
    )
    legacy_payload = {
        "source_url": url,
        "recipe_title": "Legacy recipe",
        "ingredients": [],
    }
    output_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    identity = {
        "workspace_id": user_id,
        "workspace_type": "user",
        "subject_id": user_id,
        "domain": "recipes",
        "document_key": recipe_edit_service.recipe_output_document_key(
            database_payload
        ),
        "source_key": recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
        "source_ref": recipe_edit_service.recipe_output_source_ref(output_path),
    }
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == (
        "Database recipe"
    )
    updated = {**database_payload, "recipe_title": "Updated database recipe"}
    recipe_edit_service.save_recipe_output(url, updated)
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == (
        "Updated database recipe"
    )
    changed_paths = recipe_ingredient_service.update_saved_recipe_purchase_mapping(
        "egg yolks", "eggs"
    )
    assert changed_paths == [str(output_path)]
    assert recipe_edit_service.load_recipe_output(url)["ingredients"][0][
        "purchasable_item"
    ] == "eggs"
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload

    new_url = "https://example.test/recipes/brand-new"
    new_path = recipe_edit_service.recipe_output_json_path(
        new_url, output_folder=output_dir
    )
    recipe_edit_service.save_recipe_output(
        new_url,
        {"source_url": new_url, "recipe_title": "Brand-new database recipe"},
    )
    assert not new_path.exists()
    assert recipe_edit_service.load_recipe_output(new_url)["recipe_title"] == (
        "Brand-new database recipe"
    )

    recipe_edit_service.remove_recipe_output_file(url)
    recipe_edit_service.remove_recipe_output_file(url)
    assert output_path.is_file()
    assert recipe_edit_service.load_recipe_output(url) is None
    coverage_key = runtime.source_coverage_key(
        user_id,
        recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
        recipe_edit_service.recipe_output_source_ref(output_path),
    )
    with application_data.existing_application_read_connection(db_path) as connection:
        assert application_data.get_durable_document(
            user_id,
            "recipes",
            identity["document_key"],
            connection=connection,
        ) is None
        coverage = application_data.get_source_coverage(
            user_id, "recipes", coverage_key, connection=connection
        )
    assert coverage["status"] == "deleted"
    assert coverage["summary"]["document_key"] == identity["document_key"]
    assert coverage["summary"]["source_key"] == "recipe_json"

    recreated = {**database_payload, "recipe_title": "Recreated database recipe"}
    recipe_edit_service.save_recipe_output(url, recreated)
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == (
        "Recreated database recipe"
    )
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload

    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_only")
    monkeypatch.setattr(
        recipe_edit_service,
        "build_legacy_recipe_output_index",
        lambda: (_ for _ in ()).throw(
            AssertionError("db_only must not read recipe output JSON")
        ),
    )
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == (
        "Recreated database recipe"
    )
    db_only_update = {**database_payload, "recipe_title": "DB-only recipe"}
    recipe_edit_service.save_recipe_output(url, db_only_update)
    assert recipe_edit_service.load_recipe_output(url)["recipe_title"] == (
        "DB-only recipe"
    )
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload
    recipe_ingredient_service.update_saved_recipe_purchase_mapping(
        "egg yolks", "carton eggs"
    )
    assert recipe_edit_service.load_recipe_output(url)["ingredients"][0][
        "purchasable_item"
    ] == "carton eggs"
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload
    recipe_edit_service.remove_recipe_output_file(url)
    recipe_edit_service.remove_recipe_output_file(url)
    assert recipe_edit_service.load_recipe_output(url) is None
    assert json.loads(output_path.read_text(encoding="utf-8")) == legacy_payload


def test_guest_tombstone_fences_legacy_durable_save_and_delete(monkeypatch, tmp_path):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    guest_id = "expired-guest"
    workspace_id = "guest:%s" % guest_id
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO guest_tombstones (
                guest_session_id, workspace_id, purge_run_id,
                lifecycle_state, tombstoned_at
            ) VALUES (?, ?, ?, 'purged', ?)
            """,
            (guest_id, workspace_id, "purge-run", "2026-01-01T00:00:00Z"),
        )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "json")
    legacy_writes = []
    identity = {
        "domain": "pantry",
        "document_key": "inventory",
        "source_key": "pantry_inventory",
        "source_ref": "pantry_inventory.json",
        "workspace_id": workspace_id,
        "workspace_type": "guest",
        "subject_id": guest_id,
    }

    with pytest.raises(runtime.DurableDocumentLifecycleError):
        runtime.save_json_document(
            {"items": []}, lambda value: legacy_writes.append(value), **identity
        )
    with pytest.raises(runtime.DurableDocumentLifecycleError):
        runtime.delete_json_document(lambda: legacy_writes.append("deleted"), **identity)
    assert legacy_writes == []

    assert runtime.save_json_document(
        {"items": ["safe"]},
        lambda value: value,
        **{
            **identity,
            "workspace_id": "unrelated-user",
            "workspace_type": "user",
            "subject_id": "unrelated-user",
        },
    ) == {"items": ["safe"]}


def test_extraction_writers_create_new_db_preferred_recipes_without_json(
    monkeypatch, tmp_path
):
    install_runtime_database(monkeypatch, tmp_path)
    user_id = "extract-user"
    monkeypatch.setattr(storage_service, "USER_DATA_DIR", tmp_path / "users")
    workspace_root = storage_service.user_data_root(user_id)
    output_dir = workspace_root / "recipe-extractor" / "data" / "output"
    output_dir.mkdir(parents=True)
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    monkeypatch.setattr(recipe_extract_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(
        recipe_extract_service,
        "PDF_FOLDER",
        workspace_root / "recipe-extractor" / "data" / "pdf",
    )
    monkeypatch.setattr(
        recipe_extract_service,
        "attach_cloudflare_pdf_metadata",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    first_url = "https://example.test/new/extracted"
    first_path = recipe_extract_service.save_extracted_recipe_json(
        first_url,
        {
            "recipe_title": "Extracted into database",
            "ingredients": [{"ingredient": "flour"}],
            "instructions": [{"step": "Mix"}],
        },
    )
    assert not first_path.exists()
    assert recipe_edit_service.load_recipe_output(first_url)["recipe_title"] == (
        "Extracted into database"
    )

    second_url = "https://example.test/new/response"
    ok, saved = recipe_extract_service.save_json_response(
        second_url,
        json.dumps(
            {
                "recipe_title": "Response into database",
                "ingredients": [{"ingredient": "water"}],
                "instructions": [{"step": "Stir"}],
            }
        ),
    )
    assert ok is True
    assert saved["recipe_title"] == "Response into database"
    second_path = recipe_extract_service.recipe_output_json_path(
        second_url, output_folder=output_dir
    )
    assert not second_path.exists()
    assert recipe_edit_service.load_recipe_output(second_url)["recipe_title"] == (
        "Response into database"
    )


def test_recipe_db_preferred_create_does_not_bypass_partial_coverage(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "partial-recipe-user"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    url = "https://example.test/new/partial"
    document = {"source_url": url, "recipe_title": "Must not be created"}
    output_path = recipe_edit_service.recipe_output_json_path(
        url, output_folder=output_dir
    )
    document_key = recipe_edit_service.recipe_output_document_key(document)
    source_ref = recipe_edit_service.recipe_output_source_ref(output_path)
    coverage_key = runtime.source_coverage_key(
        user_id, recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY, source_ref
    )
    with application_data.application_data_write_connection(db_path) as connection:
        application_data.ensure_workspace(
            user_id, "user", user_id, connection=connection
        )
        application_data.upsert_source_coverage(
            user_id,
            "recipes",
            coverage_key,
            "a" * 64,
            status="covered",
            summary={
                "document_key": document_key,
                "source_key": recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
                "source_ref": source_ref,
            },
            connection=connection,
        )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    with pytest.raises(runtime.DurableDocumentRuntimeError, match="incomplete"):
        recipe_edit_service.save_recipe_output(url, document)
    assert not output_path.exists()
    with application_data.existing_application_read_connection(db_path) as connection:
        assert application_data.get_durable_document(
            user_id, "recipes", document_key, connection=connection
        ) is None


def test_recipe_update_keeps_migrated_key_and_moves_exact_coverage_on_rename(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "stable-recipe-user"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    old_url = "https://example.test/recipes/original"
    new_url = "https://example.test/recipes/renamed"
    old_path = recipe_edit_service.recipe_output_json_path(
        old_url, output_folder=output_dir
    )
    old_document = {"source_url": old_url, "recipe_title": "Original"}
    old_path.write_text(json.dumps(old_document), encoding="utf-8")
    migrated_key = recipe_edit_service.recipe_output_document_key(old_document)
    old_ref = recipe_edit_service.recipe_output_source_ref(old_path)
    runtime.write_database_document(
        old_document,
        workspace_id=user_id,
        workspace_type="user",
        subject_id=user_id,
        domain="recipes",
        document_key=migrated_key,
        source_key=recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
        source_ref=old_ref,
        db_path=db_path,
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_preferred")

    with_new_identity = {
        **old_document,
        "recipe_id": "uuid-added-by-first-editor-save",
        "recipe_title": "Edited",
    }
    assert recipe_edit_service.recipe_output_document_key(with_new_identity) != migrated_key
    recipe_edit_service.save_recipe_output(old_url, with_new_identity)
    assert recipe_edit_service.load_recipe_output(old_url)["recipe_title"] == "Edited"
    with application_data.existing_application_read_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT document_key FROM durable_documents WHERE workspace_id = ? AND domain = 'recipes'",
            (user_id,),
        ).fetchall()
    assert [row["document_key"] for row in rows] == [migrated_key]

    renamed = {**with_new_identity, "source_url": new_url, "recipe_title": "Renamed"}
    recipe_edit_service.save_recipe_output(
        new_url,
        renamed,
        previous_url=old_url,
    )
    new_path = recipe_edit_service.recipe_output_json_path(
        new_url, output_folder=output_dir
    )
    new_ref = recipe_edit_service.recipe_output_source_ref(new_path)
    assert not new_path.exists()
    assert recipe_edit_service.load_recipe_output(new_url)["recipe_title"] == "Renamed"
    with application_data.existing_application_read_connection(db_path) as connection:
        assert application_data.get_source_coverage(
            user_id,
            "recipes",
            runtime.source_coverage_key(
                user_id, recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY, old_ref
            ),
            connection=connection,
        ) is None
        moved = application_data.get_source_coverage(
            user_id,
            "recipes",
            runtime.source_coverage_key(
                user_id, recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY, new_ref
            ),
            connection=connection,
        )
    assert moved["status"] == "covered"
    assert moved["summary"]["document_key"] == migrated_key
    assert moved["summary"]["source_ref"] == new_ref

    assert recipe_edit_service.remove_stale_recipe_output(old_url, new_url) is True
    assert not old_path.exists()
    assert recipe_edit_service.load_recipe_output(new_url)["recipe_title"] == "Renamed"
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_only")
    assert recipe_edit_service.load_recipe_output(new_url)["recipe_id"] == (
        "uuid-added-by-first-editor-save"
    )
    recipe_edit_service.remove_recipe_output_file(new_url)
    recipe_edit_service.remove_recipe_output_file(new_url)
    assert recipe_edit_service.load_recipe_output(new_url) is None
    recipe_edit_service.save_recipe_output(new_url, renamed)
    assert recipe_edit_service.load_recipe_output(new_url)["recipe_title"] == "Renamed"
    with application_data.existing_application_read_connection(db_path) as connection:
        recreated_rows = connection.execute(
            "SELECT document_key FROM durable_documents WHERE workspace_id = ? AND domain = 'recipes'",
            (user_id,),
        ).fetchall()
    assert [row["document_key"] for row in recreated_rows] == [migrated_key]


def test_purchase_mapping_shadow_write_updates_json_and_database(
    monkeypatch, tmp_path
):
    install_runtime_database(monkeypatch, tmp_path)
    user_id = "shadow-recipe-user"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(storage_service, "active_guest_session_id", lambda: "")
    monkeypatch.setattr(storage_service, "active_user_id", lambda: user_id)
    monkeypatch.setattr(recipe_edit_service, "OUTPUT_FOLDER", output_dir)
    monkeypatch.setattr(recipe_ingredient_service, "OUTPUT_FOLDER", output_dir)
    url = "https://example.test/recipes/shadow"
    json_path = recipe_edit_service.recipe_output_json_path(
        url, output_folder=output_dir
    )
    json_path.write_text(
        json.dumps(
            {
                "source_url": url,
                "recipe_title": "Shadow recipe",
                "ingredients": [{"ingredient": "roma tomatoes"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "shadow")

    assert recipe_ingredient_service.update_saved_recipe_purchase_mapping(
        "roma tomatoes", "tomatoes"
    ) == [str(json_path)]
    assert json.loads(json_path.read_text(encoding="utf-8"))["ingredients"][0][
        "purchasable_item"
    ] == "tomatoes"
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "db_only")
    assert recipe_edit_service.load_recipe_output(url)["ingredients"][0][
        "purchasable_item"
    ] == "tomatoes"


def test_recipe_list_rejects_coverage_bound_to_another_source_family(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    user_id = "cross-family-user"
    document_key = "metadata-document"
    metadata = {"source_url": "https://example.test/not-a-recipe-output"}
    runtime.write_database_document(
        metadata,
        workspace_id=user_id,
        workspace_type="user",
        subject_id=user_id,
        domain="recipes",
        document_key=document_key,
        source_key="recipe_metadata",
        source_ref="recipe-extractor/data/recipe_ingredients.json",
        db_path=db_path,
    )
    forged_ref = "recipe-extractor/data/output/forged.json"
    with application_data.application_data_write_connection(db_path) as connection:
        stored = application_data.get_durable_document(
            user_id, "recipes", document_key, connection=connection
        )
        application_data.upsert_source_coverage(
            user_id,
            "recipes",
            runtime.source_coverage_key(
                user_id, recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY, forged_ref
            ),
            stored["source_sha256"],
            status="covered",
            summary={
                "document_key": document_key,
                "source_key": recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
                "source_ref": forged_ref,
            },
            connection=connection,
        )

    with pytest.raises(runtime.DurableDocumentRuntimeError, match="source family"):
        runtime.list_database_documents(
            workspace_id=user_id,
            domain="recipes",
            source_key=recipe_edit_service.RECIPE_OUTPUT_SOURCE_KEY,
            db_path=db_path,
            include_deleted=True,
        )


def test_in_flight_legacy_guest_write_finishes_before_purge_fence_and_cleanup(
    monkeypatch, tmp_path
):
    db_path = install_runtime_database(monkeypatch, tmp_path)
    monkeypatch.setenv(runtime.DURABLE_BACKEND_ENV, "json")
    guest_id = "racing-expired-guest"
    workspace_id = "guest:%s" % guest_id
    legacy_path = tmp_path / "guest" / "pantry.json"
    purge_started = tmp_path / "purge-started"
    purge_finished = tmp_path / "purge-finished"
    purge_process = None
    purge_script = "\n".join(
        (
            "import sqlite3, sys",
            "from pathlib import Path",
            "db, guest, workspace, legacy, started, finished = sys.argv[1:]",
            "Path(started).write_text('started', encoding='utf-8')",
            "connection = sqlite3.connect(db, timeout=5)",
            "connection.execute('BEGIN IMMEDIATE')",
            "connection.execute(\"INSERT INTO guest_tombstones (guest_session_id, workspace_id, purge_run_id, lifecycle_state, tombstoned_at) VALUES (?, ?, 'purge-run', 'purged', '2026-01-01T00:00:00Z')\", (guest, workspace))",
            "connection.commit()",
            "connection.close()",
            "path = Path(legacy)",
            "path.unlink() if path.exists() else None",
            "Path(finished).write_text('finished', encoding='utf-8')",
        )
    )

    def save_legacy(value):
        nonlocal purge_process
        purge_process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                purge_script,
                str(db_path),
                guest_id,
                workspace_id,
                str(legacy_path),
                str(purge_started),
                str(purge_finished),
            ]
        )
        deadline = time.monotonic() + 2
        while not purge_started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert purge_started.exists()
        time.sleep(0.05)
        # A separate process has reached BEGIN IMMEDIATE but cannot commit its
        # tombstone while the guarded legacy write holds SQLite's reservation.
        assert purge_process.poll() is None
        assert not purge_finished.exists()
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    result = runtime.save_json_document(
        {"items": ["salt"]},
        save_legacy,
        domain="pantry",
        document_key="inventory",
        source_key="pantry_inventory",
        source_ref="pantry_inventory.json",
        workspace_id=workspace_id,
        workspace_type="guest",
        subject_id=guest_id,
        db_path=db_path,
    )
    assert result == {"items": ["salt"]}
    assert purge_process is not None
    assert purge_process.wait(timeout=5) == 0
    assert purge_finished.exists()
    assert not legacy_path.exists()
