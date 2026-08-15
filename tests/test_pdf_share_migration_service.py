from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from PushShoppingList.services import application_data_service as application_data
from PushShoppingList.services import pdf_share_migration_service as migration
from PushShoppingList.services import pdf_share_service
from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor


def install(database):
    application_data.install_application_schema(
        database,
        dry_run=False,
        authorized=True,
        approval=application_data.SCHEMA_INSTALL_APPROVAL_PHRASE,
    )


def encryptor():
    return AesGcmDataEncryptor(bytes(range(32)), key_id="test-pdf-key")


def record(token="existing-share-token", **overrides):
    value = {
        "token": token,
        "pdf_filename": "shared.pdf",
        "pdf_path": "PushShoppingList/services/recipe-extractor/data/pdf/shared.pdf",
        "original_filename": "Dinner Menu.pdf",
        "created_at": "2026-08-14T10:00:00Z",
        "expires_at": "2099-08-14T10:00:00Z",
        "created_by_user_id": "account-opaque-id",
        "created_by_email": "owner@example.test",
        "allow_download": False,
        "revoked": False,
        "access_count": 7,
        "last_accessed_at": "2026-08-14T12:00:00Z",
    }
    value.update(overrides)
    return value


def write_source(path, links, *, bom=False):
    raw = json.dumps({"links": links}, ensure_ascii=False).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw)
    return path.read_bytes()


def configure_runtime(monkeypatch, tmp_path, database, cipher, mode):
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    (pdf_dir / "shared.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (pdf_dir / "new.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    legacy = tmp_path / "pdf_share_links.json"
    monkeypatch.setattr(pdf_share_service, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(pdf_share_service, "PDF_SHARE_LINKS_FILE", legacy)
    monkeypatch.setattr(pdf_share_service, "PDF_SHARE_DB_PATH", database)
    monkeypatch.setattr(pdf_share_service, "pdf_share_encryptor", lambda: cipher)
    monkeypatch.setenv(pdf_share_service.PDF_SHARE_BACKEND_ENV, mode)
    return pdf_dir, legacy


def test_schema_contains_complete_encrypted_share_metadata_without_raw_token_column(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(share_links)")
        }

    assert {
        "token_digest",
        "encrypted_token_json",
        "encryption_key_id",
        "pdf_filename",
        "pdf_path",
        "original_filename",
        "created_by_user_id",
        "created_by_email",
        "created_at",
        "expires_at",
        "allow_download",
        "revoked",
        "access_count",
        "last_accessed_at",
        "updated_at",
        "source_version",
        "source_sha256",
    }.issubset(columns)
    assert "token" not in columns


def test_schema_status_rejects_a_plaintext_share_token_column(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE share_links ADD COLUMN token TEXT")

    status = application_data.application_schema_status(database)

    assert status["available"] is False
    assert status["compatible"] is False
    assert "share_links:forbidden_token_column" in status["issues"]


def test_utf8_bom_preview_reports_only_counts_and_preserves_source(tmp_path):
    source = tmp_path / "shares.json"
    raw = write_source(
        source,
        [
            record(),
            record(
                "revoked-token",
                pdf_filename="revoked.pdf",
                original_filename="Revoked.pdf",
                revoked=True,
                access_count=2,
            ),
        ],
        bom=True,
    )

    preview = migration.preview_pdf_share_migration(
        source,
        clock=lambda: datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    report = json.dumps(preview.to_dict())

    assert preview.ready is True
    assert preview.byte_count == len(raw)
    assert preview.record_count == 2
    assert preview.active_count == 1
    assert preview.revoked_count == 1
    assert preview.access_count == 9
    assert "existing-share-token" not in report
    assert "owner@example.test" not in report
    assert source.read_bytes() == raw


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (b'{"links":[],"links":[]}', "duplicate_json_key"),
        (b'{"links":[{"token":"x"}]}', "invalid_pdf_filename"),
        (
            json.dumps({"links": [record(" padded-token ")]}).encode("utf-8"),
            "invalid_share_token",
        ),
        (b"\xff", "invalid_utf8"),
    ],
)
def test_corrupt_or_ambiguous_source_fails_strict_preview(tmp_path, raw, error_code):
    source = tmp_path / "shares.json"
    source.write_bytes(raw)

    preview = migration.preview_pdf_share_migration(source)

    assert preview.ready is False
    assert preview.error_code == error_code


def test_apply_preserves_metadata_encrypts_tokens_and_is_idempotent(tmp_path):
    source = tmp_path / "shares.json"
    legacy_bytes = write_source(source, [record()])
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    preview = migration.preview_pdf_share_migration(source)

    first = migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    second = migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )

    digest = migration.share_token_digest("existing-share-token")
    stored = application_data.get_share_link(digest, db_path=database)
    with sqlite3.connect(database) as connection:
        raw_database_values = "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM share_links")
            for value in row
            if value is not None
        )
        row_version = connection.execute(
            "SELECT row_version FROM share_links WHERE token_digest = ?", (digest,)
        ).fetchone()[0]
        coverage_count = connection.execute(
            "SELECT COUNT(*) FROM application_source_coverage"
        ).fetchone()[0]

    assert first.inserted_count == 1
    assert first.no_op is False
    assert second.no_op is True
    assert second.unchanged_count == 1
    assert stored["pdf_path"] == record()["pdf_path"]
    assert stored["original_filename"] == "Dinner Menu.pdf"
    assert stored["created_by_user_id"] == "account-opaque-id"
    assert stored["created_by_email"] == "owner@example.test"
    assert stored["allow_download"] is False
    assert stored["access_count"] == 7
    assert migration.decrypt_share_token(stored, cipher) == "existing-share-token"
    assert "existing-share-token" not in raw_database_values
    assert row_version == 1
    assert coverage_count == 1
    assert source.read_bytes() == legacy_bytes


def test_same_hash_rerun_rejects_a_changed_database_row(tmp_path):
    source = tmp_path / "shares.json"
    write_source(source, [record()])
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    preview = migration.preview_pdf_share_migration(source)
    migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    application_data.update_share_link_state(
        migration.share_token_digest("existing-share-token"),
        access_count=8,
        updated_at="2026-08-14T13:00:00Z",
        db_path=database,
    )

    with pytest.raises(migration.PdfShareMigrationCollisionError):
        migration.apply_pdf_share_migration(
            preview,
            source,
            database,
            cipher,
            approval=migration.APPLY_APPROVAL_PHRASE,
        )


def test_apply_requires_exact_phrase_and_rechecks_source_hash(tmp_path):
    source = tmp_path / "shares.json"
    write_source(source, [record()])
    database = tmp_path / "application.sqlite3"
    install(database)
    preview = migration.preview_pdf_share_migration(source)

    with pytest.raises(migration.PdfShareMigrationApprovalError):
        migration.apply_pdf_share_migration(
            preview, source, database, encryptor(), approval="yes"
        )
    write_source(source, [record(), record("new-token", pdf_filename="new.pdf")])
    with pytest.raises(migration.StalePdfSharePreviewError):
        migration.apply_pdf_share_migration(
            preview,
            source,
            database,
            encryptor(),
            approval=migration.APPLY_APPROVAL_PHRASE,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM share_links").fetchone()[0] == 0


def test_database_only_runtime_resolves_existing_and_creates_revokes_and_counts(tmp_path, monkeypatch):
    source = tmp_path / "legacy.json"
    original = write_source(source, [record()])
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    preview = migration.preview_pdf_share_migration(source)
    migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    _pdf_dir, legacy_runtime = configure_runtime(
        monkeypatch, tmp_path, database, cipher, "db_only"
    )

    resolved = pdf_share_service.resolve_share_token("existing-share-token")
    accessed = pdf_share_service.record_share_access(" existing-share-token ")
    created = pdf_share_service.create_pdf_share_link(
        "new.pdf",
        current_user={"user_id": "creator", "email": "creator@example.test"},
    )
    listed = pdf_share_service.load_share_links(include_tokens=True)
    redacted = pdf_share_service.load_share_links(include_tokens=False)
    revoked = pdf_share_service.revoke_share_token(
        " %s " % created["record"]["token"]
    )
    revoked_resolution = pdf_share_service.resolve_share_token(created["record"]["token"])

    assert resolved["ok"] is True
    assert accessed["access_count"] == 8
    assert created["ok"] is True and created["created"] is True
    assert {item["token"] for item in listed["links"]} == {
        "existing-share-token",
        created["record"]["token"],
    }
    assert all(item["token"] == "" for item in redacted["links"])
    assert revoked["ok"] is True
    assert revoked_resolution["status"] == 410
    assert not legacy_runtime.exists()
    assert source.read_bytes() == original
    with sqlite3.connect(database) as connection:
        database_text = "\n".join(
            str(value)
            for row in connection.execute("SELECT * FROM share_links")
            for value in row
            if value is not None
        )
    assert "existing-share-token" not in database_text
    assert created["record"]["token"] not in database_text


def test_db_preferred_covered_zero_is_authoritative_and_absent_coverage_falls_back(
    tmp_path, monkeypatch
):
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, cipher, "db_preferred"
    )
    write_source(legacy, [record()])

    assert pdf_share_service.load_share_links()["links"][0]["token"] == "existing-share-token"

    write_source(legacy, [])
    empty_preview = migration.preview_pdf_share_migration(legacy)
    migration.apply_pdf_share_migration(
        empty_preview,
        legacy,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    write_source(legacy, [record()])

    assert pdf_share_service.load_share_links() == {"links": []}


@pytest.mark.parametrize("mode", ["json", "shadow"])
def test_legacy_backends_honor_explicit_token_redaction(tmp_path, monkeypatch, mode):
    database = tmp_path / "application.sqlite3"
    cipher = encryptor()
    if mode == "shadow":
        install(database)
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, cipher, mode
    )
    write_source(legacy, [record()])

    redacted = pdf_share_service.load_share_links(include_tokens=False)

    assert redacted["links"][0]["token"] == ""
    assert pdf_share_service.load_share_links(include_tokens=True)["links"][0]["token"] == (
        "existing-share-token"
    )


def test_database_runtime_is_scoped_to_the_pdf_share_workspace(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    application_data.ensure_workspace(
        "other-workspace",
        "system",
        "other-shares",
        db_path=database,
    )
    other = record("other-workspace-token")
    digest = migration.share_token_digest(other["token"])
    envelope = json.loads(migration.encrypt_share_token(other["token"], digest, cipher))
    application_data.upsert_share_link(
        digest,
        envelope,
        cipher.key_id,
        workspace_id="other-workspace",
        pdf_filename=other["pdf_filename"],
        pdf_path=other["pdf_path"],
        original_filename=other["original_filename"],
        created_at=other["created_at"],
        expires_at=other["expires_at"],
        source_sha256=migration.share_token_digest("other-source"),
        db_path=database,
    )

    assert migration.database_share_records(database) == {"links": []}
    assert migration.database_find_share_record(other["token"], database) is None
    assert migration.database_revoke_share_token(
        other["token"],
        database,
        updated_at="2026-08-14T13:00:00Z",
    ) is None
    assert migration.database_record_share_access(
        other["token"],
        database,
        accessed_at="2026-08-14T13:00:00Z",
    ) is None
    assert application_data.get_share_link(digest, db_path=database)["revoked"] is False


def test_db_preferred_database_error_never_falls_back_to_json(tmp_path, monkeypatch):
    database = tmp_path / "application.sqlite3"
    install(database)
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, encryptor(), "db_preferred"
    )
    write_source(legacy, [record()])
    monkeypatch.setattr(
        migration,
        "database_share_records_are_authoritative",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.DatabaseError("broken")),
    )

    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()


def test_db_preferred_incompatible_schema_never_falls_back_to_json(tmp_path, monkeypatch):
    database = tmp_path / "application.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE share_links (token_digest TEXT PRIMARY KEY)")
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, encryptor(), "db_preferred"
    )
    write_source(legacy, [record()])

    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()


def test_db_preferred_incomplete_coverage_never_falls_back_to_json(tmp_path, monkeypatch):
    database = tmp_path / "application.sqlite3"
    install(database)
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, encryptor(), "db_preferred"
    )
    write_source(legacy, [record()])
    application_data.ensure_workspace(
        migration.GLOBAL_WORKSPACE_ID,
        "system",
        "pdf-shares",
        db_path=database,
    )
    application_data.upsert_source_coverage(
        migration.GLOBAL_WORKSPACE_ID,
        migration.COVERAGE_DOMAIN,
        migration.COVERAGE_SOURCE_KEY,
        migration.share_token_digest("failed-source"),
        status="failed",
        db_path=database,
    )

    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()


def test_shadow_runtime_keeps_atomic_json_and_database_in_sync(tmp_path, monkeypatch):
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    _pdf_dir, legacy = configure_runtime(monkeypatch, tmp_path, database, cipher, "shadow")

    created = pdf_share_service.create_pdf_share_link("new.pdf")
    token = created["record"]["token"]
    pdf_share_service.record_share_access(token)
    pdf_share_service.revoke_share_token(token)

    json_record = pdf_share_service.find_share_record(token, pdf_share_service._load_json_share_links())
    database_record = migration.database_find_share_record(token, database)
    assert legacy.exists()
    assert json_record["revoked"] is True
    assert json_record["access_count"] == 1
    assert database_record["revoked"] is True
    assert database_record["access_count"] == 1


def test_runtime_database_upsert_is_idempotent_without_reencrypting(tmp_path):
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()

    first = migration.database_upsert_share_record(record(), database, cipher)
    second = migration.database_upsert_share_record(record(), database, cipher)
    stored = application_data.get_share_link(
        migration.share_token_digest("existing-share-token"),
        db_path=database,
    )

    assert first == second
    assert stored["row_version"] == 1


@pytest.mark.parametrize("schema_state", ["installed", "partial"])
def test_db_only_rejects_schema_without_completed_share_migration(
    tmp_path, monkeypatch, schema_state
):
    database = tmp_path / "application.sqlite3"
    if schema_state == "installed":
        install(database)
    else:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE share_links (token_digest TEXT PRIMARY KEY)"
            )
    cipher = encryptor()
    _pdf_dir, legacy = configure_runtime(
        monkeypatch, tmp_path, database, cipher, "db_only"
    )
    original = write_source(legacy, [record()])

    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()
    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.create_pdf_share_link("new.pdf")

    assert legacy.read_bytes() == original
    if schema_state == "installed":
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM share_links").fetchone()[0] == 0


def test_empty_share_source_is_authoritative_and_allows_db_only_create_and_updates(
    tmp_path, monkeypatch
):
    source = tmp_path / "legacy-empty.json"
    original = write_source(source, [])
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    preview = migration.preview_pdf_share_migration(source)
    first = migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    second = migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    _pdf_dir, runtime_legacy = configure_runtime(
        monkeypatch, tmp_path, database, cipher, "db_only"
    )

    created = pdf_share_service.create_pdf_share_link("new.pdf")
    token = created["record"]["token"]
    accessed = pdf_share_service.record_share_access(token)
    revoked = pdf_share_service.revoke_share_token(token)

    assert first.no_op is False
    assert second.no_op is True
    assert accessed["access_count"] == 1
    assert revoked["record"]["revoked"] is True
    assert migration.database_share_records_are_authoritative(database) is True
    assert not runtime_legacy.exists()
    assert source.read_bytes() == original


def test_db_only_rejects_missing_migrated_row_and_stale_run_coverage(
    tmp_path, monkeypatch
):
    source = tmp_path / "legacy.json"
    write_source(source, [record()])
    database = tmp_path / "application.sqlite3"
    install(database)
    cipher = encryptor()
    preview = migration.preview_pdf_share_migration(source)
    migration.apply_pdf_share_migration(
        preview,
        source,
        database,
        cipher,
        approval=migration.APPLY_APPROVAL_PHRASE,
    )
    configure_runtime(monkeypatch, tmp_path, database, cipher, "db_only")

    application_data.record_application_migration_run(
        migration.MIGRATION_KIND,
        "succeeded",
        run_id="pdf-share:%s" % ("f" * 64),
        source_sha256="f" * 64,
        summary={
            "record_count": 1,
            "record_manifest_sha256": "e" * 64,
            "workspace_id": migration.GLOBAL_WORKSPACE_ID,
        },
        db_path=database,
    )
    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()

    with application_data.application_data_write_connection(database) as connection:
        connection.execute(
            "DELETE FROM migration_runs WHERE id = ?",
            ("pdf-share:%s" % ("f" * 64),),
        )
        connection.execute(
            "DELETE FROM share_links WHERE token_digest = ?",
            (migration.share_token_digest("existing-share-token"),),
        )

    with pytest.raises(pdf_share_service.PdfShareStorageError):
        pdf_share_service.load_share_links()


def test_offset_expiration_is_compared_in_utc():
    assert pdf_share_service.is_share_expired(
        {"expires_at": "2000-01-01T01:00:00+01:00"}
    ) is True


def test_atomic_json_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    metadata = tmp_path / "shares.json"
    metadata.write_text('{"links":[]}\n', encoding="utf-8")
    monkeypatch.setattr(pdf_share_service, "PDF_SHARE_LINKS_FILE", metadata)
    monkeypatch.setenv(pdf_share_service.PDF_SHARE_BACKEND_ENV, "json")
    monkeypatch.setattr(
        pdf_share_service.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("injected replace failure")),
    )

    with pytest.raises(OSError, match="injected replace failure"):
        pdf_share_service.save_share_links({"links": [record()]})

    assert metadata.read_text(encoding="utf-8") == '{"links":[]}\n'
    assert list(tmp_path.glob(".*.tmp")) == []
