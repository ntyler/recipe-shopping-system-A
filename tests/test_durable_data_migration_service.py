from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

from PushShoppingList.services import durable_data_migration_service as migration


def descriptor(
    key,
    *,
    scope=migration.SCOPE_WORKSPACE,
    pattern="document.json",
    domain="test",
    document_key="document",
    classification=migration.CLASSIFICATION_DURABLE,
    handler=migration.HANDLER_CANONICAL_JSON,
    root_shape=migration.ROOT_OBJECT,
    collection_keys=(),
    exclude_names=(),
    multiple=False,
):
    return migration.SourceDescriptor(
        key=key,
        scope=scope,
        relative_pattern="" if scope == migration.SCOPE_GLOBAL else pattern,
        domain=domain,
        document_key=document_key,
        classification=classification,
        handler=handler,
        root_shape=root_shape,
        collection_keys=tuple(collection_keys),
        exclude_names=tuple(exclude_names),
        multiple=multiple,
    )


def config(tmp_path, *, global_sources=None, workspace_id="workspace-opaque-id"):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    global_root = tmp_path / "global"
    global_root.mkdir(parents=True, exist_ok=True)
    return migration.DurableMigrationConfig(
        global_sources=global_sources or {},
        workspaces=(
            migration.WorkspaceSource(
                workspace_id=workspace_id,
                workspace_type="user",
                subject_id="subject-opaque-id",
                root=workspace_root,
            ),
        ),
        global_workspace=migration.WorkspaceSource(
            workspace_id="global-workspace",
            workspace_type="system",
            subject_id="application",
            root=global_root,
        ),
    )


def install_test_schema(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE workspaces (
                workspace_id TEXT PRIMARY KEY,
                workspace_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL
            );
            CREATE TABLE documents (
                workspace_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                document_key TEXT NOT NULL,
                document_json TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                row_version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (workspace_id, domain, document_key)
            );
            CREATE TABLE coverage (
                workspace_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                source_key TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                PRIMARY KEY (workspace_id, domain, source_key)
            );
            """
        )


def sqlite_adapter(path, *, fail_coverage_for_domain=""):
    @contextmanager
    def connection_context():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def ensure_workspace(connection, workspace_id, workspace_type, subject_id, *, state):
        connection.execute(
            "INSERT OR IGNORE INTO workspaces VALUES (?, ?, ?, ?)",
            (workspace_id, workspace_type, subject_id, state),
        )

    def upsert_document(
        connection,
        workspace_id,
        domain,
        document_key,
        document_json,
        source_name,
        source_sha256,
        migrated_at,
    ):
        del migrated_at
        row = connection.execute(
            """
            SELECT document_json, source_name, source_sha256
            FROM documents
            WHERE workspace_id = ? AND domain = ? AND document_key = ?
            """,
            (workspace_id, domain, document_key),
        ).fetchone()
        if row and tuple(row) == (document_json, source_name, source_sha256):
            return {"action": "unchanged"}
        action = "updated" if row else "inserted"
        connection.execute(
            """
            INSERT INTO documents (
                workspace_id, domain, document_key, document_json,
                source_name, source_sha256
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, domain, document_key) DO UPDATE SET
                document_json = excluded.document_json,
                source_name = excluded.source_name,
                source_sha256 = excluded.source_sha256,
                row_version = documents.row_version + 1
            """,
            (
                workspace_id,
                domain,
                document_key,
                document_json,
                source_name,
                source_sha256,
            ),
        )
        return {"action": action}

    def upsert_coverage(
        connection,
        workspace_id,
        domain,
        source_key,
        source_sha256,
        status,
        covered_at,
        summary_json,
    ):
        del covered_at
        if domain == fail_coverage_for_domain:
            raise RuntimeError("injected coverage failure")
        connection.execute(
            """
            INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, domain, source_key) DO UPDATE SET
                source_sha256 = excluded.source_sha256,
                status = excluded.status,
                summary_json = excluded.summary_json
            """,
            (workspace_id, domain, source_key, source_sha256, status, summary_json),
        )

    def get_coverage(connection, workspace_id, domain, source_key):
        row = connection.execute(
            """
            SELECT source_sha256, status FROM coverage
            WHERE workspace_id = ? AND domain = ? AND source_key = ?
            """,
            (workspace_id, domain, source_key),
        ).fetchone()
        return dict(row) if row else None

    return migration.MigrationDatabaseAdapter(
        connection=connection_context,
        ensure_workspace=ensure_workspace,
        upsert_durable_document=upsert_document,
        upsert_source_coverage=upsert_coverage,
        get_source_coverage=get_coverage,
    )


def test_default_catalog_prioritizes_durable_sources_and_explicit_exclusions():
    by_key = {item.key: item for item in migration.DEFAULT_SOURCE_DESCRIPTORS}

    for key in (
        "cookbooks",
        "recipe_json",
        "restaurant_menus",
        "pantry_inventory",
        "meal_plan",
        "shopping_item_state",
        "openai_usage",
        "feedback",
        "admin_audit",
        "pdf_share_tokens",
        "store_credentials",
    ):
        assert by_key[key].classification == migration.CLASSIFICATION_DURABLE

    assert by_key["accounts_auth"].handler == migration.HANDLER_SPECIALIZED_JSON
    assert by_key["guest_sessions"].handler == migration.HANDLER_DELEGATED_JSON
    assert by_key["extract_progress_cache"].classification == migration.CLASSIFICATION_CACHE
    assert by_key["recipe_raw_artifacts"].classification == migration.CLASSIFICATION_ARTIFACT
    assert by_key["shopping_list_text"].classification == migration.CLASSIFICATION_SKIPPED
    assert by_key["recipe_json"].exclude_names == ("sorted_ingredients.json",)


def test_preview_parses_utf8_bom_and_report_contains_no_payload_path_or_raw_id(tmp_path):
    settings = config(tmp_path, workspace_id="private-workspace-uuid")
    source = settings.workspaces[0].root / "document.json"
    payload = {"items": [{"name": "jalapeño"}]}
    raw = b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
    source.write_bytes(raw)
    source_descriptor = descriptor("bom_document", collection_keys=("items",))

    preview = migration.preview_durable_data(settings, descriptors=(source_descriptor,))
    entry = preview.entries[0]

    assert entry.status == migration.STATUS_READY
    assert entry.record_count == 1
    assert entry.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert entry.document_sha256 == hashlib.sha256(
        migration.canonical_json(payload).encode("utf-8")
    ).hexdigest()
    serialized_report = json.dumps(preview.to_dict())
    assert "jalapeño" not in serialized_report
    assert str(tmp_path) not in serialized_report
    assert "private-workspace-uuid" not in serialized_report


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (b'{"items": [], "items": []}', "duplicate_json_key"),
        (b'{"value": NaN}', "invalid_json_value"),
        (b"\xff", "invalid_utf8"),
    ],
)
def test_preview_rejects_ambiguous_or_nonportable_json(tmp_path, raw, error_code):
    settings = config(tmp_path)
    (settings.workspaces[0].root / "document.json").write_bytes(raw)

    preview = migration.preview_durable_data(
        settings,
        descriptors=(descriptor("strict_document"),),
    )

    assert preview.entries[0].status == migration.STATUS_INVALID
    assert preview.entries[0].error_code == error_code


def test_share_tokens_are_digested_before_transactional_idempotent_apply(tmp_path):
    raw_token = "raw-token-never-store"
    share_path = tmp_path / "share-links.json"
    share_path.write_text(
        json.dumps({"links": [{"token": raw_token, "pdf_filename": "menu.pdf"}]}),
        encoding="utf-8",
    )
    settings = config(tmp_path, global_sources={"pdf_share_tokens": share_path})
    source_descriptor = descriptor(
        "pdf_share_tokens",
        scope=migration.SCOPE_GLOBAL,
        domain="sharing",
        document_key="pdf_share_links",
        handler=migration.HANDLER_SHARE_TOKEN_DIGEST,
        root_shape=migration.ROOT_OBJECT_OR_ARRAY,
        collection_keys=("links",),
    )
    preview = migration.preview_durable_data(settings, descriptors=(source_descriptor,))
    assert raw_token not in json.dumps(preview.to_dict())

    database = tmp_path / "application.sqlite3"
    install_test_schema(database)
    adapter = sqlite_adapter(database)
    first = migration.apply_durable_data(
        preview,
        settings,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=(source_descriptor,),
    )
    second = migration.apply_durable_data(
        preview,
        settings,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=(source_descriptor,),
    )

    with sqlite3.connect(database) as connection:
        document_json, row_version = connection.execute(
            "SELECT document_json, row_version FROM documents"
        ).fetchone()
        coverage_count = connection.execute("SELECT COUNT(*) FROM coverage").fetchone()[0]
    stored = json.loads(document_json)
    assert stored["links"][0]["token_digest"] == hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()
    assert "token" not in stored["links"][0]
    assert raw_token not in document_json
    assert first.adapter_actions == {"inserted": 1}
    assert second.adapter_actions == {"unchanged": 1}
    assert row_version == 1
    assert coverage_count == 1


class FakeEncryptor:
    key_id = "test-key"

    def __init__(self):
        self.calls = []

    def encrypt_json(self, value, *, associated_data):
        self.calls.append((value, associated_data))
        return json.dumps(
            {
                "algorithm": "TEST-AEAD",
                "key_id": self.key_id,
                "nonce": "test-nonce",
                "ciphertext": "opaque-ciphertext",
            }
        )


def test_store_credentials_fail_closed_then_store_only_encryption_envelope(tmp_path):
    settings = config(tmp_path)
    credentials_path = (
        settings.workspaces[0].root
        / "recipe-extractor"
        / "data"
        / "store_credentials.json"
    )
    credentials_path.parent.mkdir(parents=True)
    credentials_path.write_text(
        json.dumps({"credentials": {"grocer": {"username": "user", "password": "secret"}}}),
        encoding="utf-8",
    )
    source_descriptor = descriptor(
        "store_credentials",
        pattern="recipe-extractor/data/store_credentials.json",
        domain="stores",
        document_key="credentials",
        handler=migration.HANDLER_ENCRYPTED_JSON,
        collection_keys=("credentials",),
    )
    blocked_preview = migration.preview_durable_data(settings, descriptors=(source_descriptor,))
    assert blocked_preview.entries[0].status == migration.STATUS_BLOCKED

    database = tmp_path / "application.sqlite3"
    install_test_schema(database)
    adapter = sqlite_adapter(database)
    with pytest.raises(migration.SensitiveSourceError):
        migration.apply_durable_data(
            blocked_preview,
            settings,
            adapter,
            approval=migration.APPLY_APPROVAL_PHRASE,
            descriptors=(source_descriptor,),
        )

    encryptor = FakeEncryptor()
    ready_preview = migration.preview_durable_data(
        settings,
        descriptors=(source_descriptor,),
        encryptor=encryptor,
    )
    migration.apply_durable_data(
        ready_preview,
        settings,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=(source_descriptor,),
        encryptor=encryptor,
    )
    migration.apply_durable_data(
        ready_preview,
        settings,
        adapter,
        approval=migration.APPLY_APPROVAL_PHRASE,
        descriptors=(source_descriptor,),
        encryptor=encryptor,
    )

    with sqlite3.connect(database) as connection:
        document_json, row_version = connection.execute(
            "SELECT document_json, row_version FROM documents"
        ).fetchone()
    assert json.loads(document_json) == {
        "algorithm": "TEST-AEAD",
        "ciphertext": "opaque-ciphertext",
        "key_id": "test-key",
        "nonce": "test-nonce",
    }
    assert "secret" not in document_json
    assert "user" not in document_json
    assert len(encryptor.calls) == 1
    assert row_version == 1


def test_accounts_and_guests_are_inventory_only_and_secret_accounts_are_blocked(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "opaque-user",
                        "password_hash": "safe-hash",
                        "two_factor": {"secret": "recoverable-totp"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    guests = tmp_path / "guests.json"
    guests.write_text(json.dumps({"guest_sessions": [{"id": "opaque-guest"}]}), encoding="utf-8")
    settings = config(
        tmp_path,
        global_sources={"accounts_auth": accounts, "guest_sessions": guests},
    )
    descriptors = (
        descriptor(
            "accounts_auth",
            scope=migration.SCOPE_GLOBAL,
            domain="identity",
            document_key="accounts",
            classification=migration.CLASSIFICATION_SKIPPED,
            handler=migration.HANDLER_SPECIALIZED_JSON,
            collection_keys=("users",),
        ),
        descriptor(
            "guest_sessions",
            scope=migration.SCOPE_GLOBAL,
            domain="identity",
            document_key="guest_sessions",
            classification=migration.CLASSIFICATION_SKIPPED,
            handler=migration.HANDLER_DELEGATED_JSON,
            collection_keys=("guest_sessions",),
        ),
    )

    preview = migration.preview_durable_data(settings, descriptors=descriptors)
    by_key = {entry.source_key: entry for entry in preview.entries}

    assert by_key["accounts_auth"].status == migration.STATUS_BLOCKED
    assert by_key["accounts_auth"].secret_field_count == 1
    assert by_key["guest_sessions"].status == migration.STATUS_DELEGATED
    assert "recoverable-totp" not in json.dumps(preview.to_dict())


def test_recipe_identity_collision_and_cache_artifact_exclusions_are_reported(tmp_path):
    settings = config(tmp_path)
    output = settings.workspaces[0].root / "recipe-extractor" / "data" / "output"
    output.mkdir(parents=True)
    for name in ("first.json", "second.json"):
        (output / name).write_text(
            json.dumps({"source_url": "https://example.test/same", "title": name}),
            encoding="utf-8",
        )
    cache = settings.workspaces[0].root / "cache.json"
    cache.write_text("not json and intentionally unread", encoding="utf-8")
    artifacts = settings.workspaces[0].root / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw.bin").write_bytes(b"abc")
    descriptors = (
        descriptor(
            "recipes",
            pattern="recipe-extractor/data/output/*.json",
            domain="recipes",
            document_key="recipe",
            handler=migration.HANDLER_RECIPE_JSON,
            multiple=True,
        ),
        descriptor(
            "cache_file",
            pattern="cache.json",
            domain="cache",
            document_key="cache",
            classification=migration.CLASSIFICATION_CACHE,
            handler=migration.HANDLER_EXCLUDED_FILE,
        ),
        descriptor(
            "artifact_tree",
            pattern="artifacts",
            domain="artifacts",
            document_key="tree",
            classification=migration.CLASSIFICATION_ARTIFACT,
            handler=migration.HANDLER_EXCLUDED_TREE,
        ),
    )

    preview = migration.preview_durable_data(settings, descriptors=descriptors)
    recipe_entries = [entry for entry in preview.entries if entry.source_key == "recipes"]
    cache_entry = next(entry for entry in preview.entries if entry.source_key == "cache_file")
    artifact_entry = next(entry for entry in preview.entries if entry.source_key == "artifact_tree")

    assert len(recipe_entries) == 2
    assert all(entry.status == migration.STATUS_INVALID for entry in recipe_entries)
    assert all(entry.error_code == "document_identity_collision" for entry in recipe_entries)
    assert cache_entry.status == migration.STATUS_EXCLUDED
    assert cache_entry.source_sha256 is None
    assert artifact_entry.status == migration.STATUS_EXCLUDED
    assert artifact_entry.record_count == 1
    assert artifact_entry.byte_count == 3


def test_apply_rejects_stale_preview_and_rolls_back_a_later_failure(tmp_path):
    settings = config(tmp_path)
    first_path = settings.workspaces[0].root / "first.json"
    second_path = settings.workspaces[0].root / "second.json"
    first_path.write_text('{"items":[1]}', encoding="utf-8")
    second_path.write_text('{"items":[2]}', encoding="utf-8")
    descriptors = (
        descriptor("first", pattern="first.json", domain="first", collection_keys=("items",)),
        descriptor("second", pattern="second.json", domain="second", collection_keys=("items",)),
    )
    preview = migration.preview_durable_data(settings, descriptors=descriptors)
    database = tmp_path / "application.sqlite3"
    install_test_schema(database)

    first_path.write_text('{"items":[1,3]}', encoding="utf-8")
    with pytest.raises(migration.StaleMigrationPreviewError):
        migration.apply_durable_data(
            preview,
            settings,
            sqlite_adapter(database),
            approval=migration.APPLY_APPROVAL_PHRASE,
            descriptors=descriptors,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0

    fresh_preview = migration.preview_durable_data(settings, descriptors=descriptors)
    with pytest.raises(RuntimeError, match="injected coverage failure"):
        migration.apply_durable_data(
            fresh_preview,
            settings,
            sqlite_adapter(database, fail_coverage_for_domain="second"),
            approval=migration.APPLY_APPROVAL_PHRASE,
            descriptors=descriptors,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM coverage").fetchone()[0] == 0


def test_apply_requires_exact_approval_phrase(tmp_path):
    settings = config(tmp_path)
    (settings.workspaces[0].root / "document.json").write_text("{}", encoding="utf-8")
    source_descriptor = descriptor("approval_document")
    preview = migration.preview_durable_data(settings, descriptors=(source_descriptor,))
    database = tmp_path / "application.sqlite3"
    install_test_schema(database)

    with pytest.raises(migration.MigrationApprovalError):
        migration.apply_durable_data(
            preview,
            settings,
            sqlite_adapter(database),
            approval="yes",
            descriptors=(source_descriptor,),
        )
