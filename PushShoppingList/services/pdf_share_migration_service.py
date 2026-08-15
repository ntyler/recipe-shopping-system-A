"""Safe migration and database runtime helpers for PDF share tokens.

Legacy JSON remains unchanged.  Lookup uses a SHA-256 token digest; authorized
administrative re-display decrypts an AES-GCM envelope bound to that digest.
Neither previews nor database plaintext contain the raw token.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Protocol, Sequence, Tuple

from PushShoppingList.services import application_data_service as application_data


APPLY_APPROVAL_PHRASE = "APPLY PDF SHARE MIGRATION"
MIGRATION_KIND = "pdf_share_token_migration"
MIGRATION_VERSION = "1"
TOKEN_ENCRYPTION_AAD_VERSION = "1"
GLOBAL_WORKSPACE_ID = "system:pdf-shares"
GLOBAL_WORKSPACE_TYPE = "system"
GLOBAL_EXTERNAL_ID = "pdf-shares"
COVERAGE_DOMAIN = "sharing"
COVERAGE_SOURCE_KEY = "legacy_pdf_share_links_json"
MAX_SOURCE_BYTES = 16 * 1024 * 1024

_ALLOWED_RECORD_FIELDS = frozenset({
    "token",
    "pdf_filename",
    "pdf_path",
    "original_filename",
    "created_at",
    "expires_at",
    "created_by_user_id",
    "created_by_email",
    "allow_download",
    "revoked",
    "access_count",
    "last_accessed_at",
})


class PdfShareMigrationError(RuntimeError):
    pass


class PdfShareMigrationApprovalError(PdfShareMigrationError):
    pass


class PdfShareMigrationSourceError(PdfShareMigrationError):
    pass


class StalePdfSharePreviewError(PdfShareMigrationSourceError):
    pass


class PdfShareMigrationCollisionError(PdfShareMigrationError):
    pass


class PdfShareEncryptionError(PdfShareMigrationError):
    pass


class PdfShareMigrationCoverageError(PdfShareMigrationError):
    """Raised when database cutover markers do not prove complete coverage."""

    pass


class _DuplicateJsonKeyError(ValueError):
    pass


class _ShareShapeError(ValueError):
    pass


class SecretEncryptor(Protocol):
    @property
    def key_id(self) -> str:
        ...

    def encrypt_json(self, value: object, *, associated_data: str) -> str:
        ...

    def decrypt_json(self, envelope_json: str, *, associated_data: str) -> object:
        ...


@dataclass(frozen=True)
class PdfShareMigrationPreview:
    created_at: str
    status: str
    source_sha256: Optional[str]
    byte_count: int
    record_count: int
    active_count: int
    revoked_count: int
    expired_count: int
    access_count: int
    error_code: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> Dict[str, object]:
        result = asdict(self)
        result["ready"] = self.ready
        return result


@dataclass(frozen=True)
class PdfShareMigrationApplyResult:
    applied_at: str
    source_sha256: str
    record_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int
    no_op: bool
    migration_run_id: str


@dataclass(frozen=True)
class _PreparedShare:
    token: str
    token_digest: str
    record_sha256: str
    pdf_filename: str
    pdf_path: str
    original_filename: str
    created_at: str
    expires_at: str
    created_by_user_id: str
    created_by_email: str
    allow_download: bool
    revoked: bool
    access_count: int
    last_accessed_at: str


def preview_pdf_share_migration(
    source_path,
    *,
    clock: Optional[Callable[[], datetime]] = None,
) -> PdfShareMigrationPreview:
    """Strictly inspect legacy metadata without opening SQLite."""

    try:
        raw, prepared = _scan_source(Path(source_path))
        now = _clock_value(clock)
        expired = sum(
            1 for item in prepared if _parse_timestamp(item.expires_at) <= now
        )
        revoked = sum(1 for item in prepared if item.revoked)
        return PdfShareMigrationPreview(
            created_at=_timestamp(clock),
            status="ready",
            source_sha256=hashlib.sha256(raw).hexdigest(),
            byte_count=len(raw),
            record_count=len(prepared),
            active_count=sum(
                1
                for item in prepared
                if not item.revoked and _parse_timestamp(item.expires_at) > now
            ),
            revoked_count=revoked,
            expired_count=expired,
            access_count=sum(item.access_count for item in prepared),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return PdfShareMigrationPreview(
            created_at=_timestamp(clock),
            status="invalid",
            source_sha256=None,
            byte_count=0,
            record_count=0,
            active_count=0,
            revoked_count=0,
            expired_count=0,
            access_count=0,
            error_code=_safe_error_code(exc),
        )


def apply_pdf_share_migration(
    preview: PdfShareMigrationPreview,
    source_path,
    db_path,
    encryptor: SecretEncryptor,
    *,
    approval: str,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    clock: Optional[Callable[[], datetime]] = None,
) -> PdfShareMigrationApplyResult:
    """Apply an unchanged source in one caller-owned SQLite transaction."""

    if approval != APPLY_APPROVAL_PHRASE:
        raise PdfShareMigrationApprovalError("The exact PDF-share approval phrase is required.")
    if not preview.ready or not preview.source_sha256:
        raise PdfShareMigrationSourceError("Only a ready PDF-share preview can be applied.")
    raw, prepared = _scan_source(Path(source_path))
    current_sha256 = hashlib.sha256(raw).hexdigest()
    if current_sha256 != preview.source_sha256 or len(prepared) != preview.record_count:
        raise StalePdfSharePreviewError("Legacy PDF-share metadata changed after preview.")
    _validate_encryptor(encryptor)

    applied_at = _timestamp(clock)
    run_id = "pdf-share:%s" % current_sha256
    source_manifest_sha256 = _prepared_source_manifest_sha256(prepared)
    inserted = 0
    updated = 0
    unchanged = 0
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        application_data.ensure_workspace(
            workspace_id,
            GLOBAL_WORKSPACE_TYPE,
            GLOBAL_EXTERNAL_ID,
            lifecycle_state="active",
            source_sha256=current_sha256,
            connection=connection,
        )
        coverage = application_data.get_source_coverage(
            workspace_id,
            COVERAGE_DOMAIN,
            COVERAGE_SOURCE_KEY,
            connection=connection,
        )
        if coverage and coverage["status"] == "covered" and coverage["source_sha256"] == current_sha256:
            _database_authority_from_connection(connection, workspace_id)
            for item in prepared:
                existing = application_data.get_share_link(
                    item.token_digest,
                    connection=connection,
                )
                _assert_existing_migration_row(existing, item, workspace_id, encryptor)
            return PdfShareMigrationApplyResult(
                applied_at=applied_at,
                source_sha256=current_sha256,
                record_count=len(prepared),
                inserted_count=0,
                updated_count=0,
                unchanged_count=len(prepared),
                no_op=True,
                migration_run_id=str(coverage.get("migration_run_id") or run_id),
            )

        application_data.record_application_migration_run(
            MIGRATION_KIND,
            "running",
            run_id=run_id,
            source_sha256=current_sha256,
            summary={
                "record_count": len(prepared),
                "record_manifest_sha256": source_manifest_sha256,
                "workspace_id": workspace_id,
            },
            started_at=applied_at,
            connection=connection,
        )
        for item in prepared:
            existing = application_data.get_share_link(
                item.token_digest,
                connection=connection,
            )
            if existing is None:
                envelope_json = encrypt_share_token(
                    item.token,
                    item.token_digest,
                    encryptor,
                )
                envelope = json.loads(envelope_json)
            else:
                _assert_existing_migration_row(existing, item, workspace_id, encryptor)
                unchanged += 1
                continue
            result = application_data.upsert_share_link(
                item.token_digest,
                envelope,
                str(envelope.get("key_id") or ""),
                workspace_id=workspace_id,
                created_by_user_id=item.created_by_user_id,
                created_by_email=item.created_by_email,
                pdf_filename=item.pdf_filename,
                pdf_path=item.pdf_path,
                original_filename=item.original_filename,
                created_at=item.created_at,
                expires_at=item.expires_at,
                allow_download=item.allow_download,
                revoked=item.revoked,
                access_count=item.access_count,
                last_accessed_at=item.last_accessed_at,
                updated_at=applied_at,
                source_version=MIGRATION_VERSION,
                source_sha256=item.record_sha256,
                connection=connection,
            )
            action = result["action"]
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                unchanged += 1

        application_data.upsert_source_coverage(
            workspace_id,
            COVERAGE_DOMAIN,
            COVERAGE_SOURCE_KEY,
            current_sha256,
            migration_run_id=run_id,
            status="covered",
            summary={
                "record_count": len(prepared),
                "record_manifest_sha256": source_manifest_sha256,
                "workspace_id": workspace_id,
                "inserted_count": inserted,
                "updated_count": updated,
                "unchanged_count": unchanged,
            },
            covered_at=applied_at,
            connection=connection,
        )
        application_data.record_application_migration_run(
            MIGRATION_KIND,
            "succeeded",
            run_id=run_id,
            source_sha256=current_sha256,
            summary={
                "record_count": len(prepared),
                "record_manifest_sha256": source_manifest_sha256,
                "workspace_id": workspace_id,
                "inserted_count": inserted,
                "updated_count": updated,
                "unchanged_count": unchanged,
            },
            started_at=applied_at,
            finished_at=applied_at,
            connection=connection,
        )
        _database_authority_from_connection(connection, workspace_id)

    return PdfShareMigrationApplyResult(
        applied_at=applied_at,
        source_sha256=current_sha256,
        record_count=len(prepared),
        inserted_count=inserted,
        updated_count=updated,
        unchanged_count=unchanged,
        no_op=False,
        migration_run_id=run_id,
    )


def share_token_digest(token: str) -> str:
    if not isinstance(token, str) or not token or "\x00" in token:
        raise PdfShareMigrationSourceError("PDF share token must be opaque non-empty text.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def share_token_associated_data(token_digest: str) -> str:
    if not isinstance(token_digest, str) or len(token_digest) != 64:
        raise PdfShareEncryptionError("PDF share-token digest is invalid.")
    return "pdf-share\x1f%s\x1fv%s" % (token_digest, TOKEN_ENCRYPTION_AAD_VERSION)


def encrypt_share_token(token: str, token_digest: str, encryptor: SecretEncryptor) -> str:
    _validate_encryptor(encryptor)
    if share_token_digest(token) != token_digest:
        raise PdfShareEncryptionError("PDF share token does not match its digest.")
    try:
        envelope_json = encryptor.encrypt_json(
            {"token": token},
            associated_data=share_token_associated_data(token_digest),
        )
        envelope = json.loads(envelope_json)
    except Exception:
        raise PdfShareEncryptionError("PDF share token encryption failed.") from None
    _validate_envelope(envelope, encryptor.key_id)
    return application_data.canonical_json(envelope)


def decrypt_share_token(
    stored: Mapping[str, object],
    encryptor: SecretEncryptor,
) -> str:
    token_digest = str(stored.get("token_digest") or "")
    envelope = stored.get("encrypted_token")
    _validate_encryptor(encryptor)
    _validate_envelope(envelope, str(stored.get("encryption_key_id") or ""))
    try:
        value = encryptor.decrypt_json(
            application_data.canonical_json(envelope),
            associated_data=share_token_associated_data(token_digest),
        )
    except Exception:
        raise PdfShareEncryptionError("PDF share token decryption failed.") from None
    if not isinstance(value, dict) or set(value) != {"token"}:
        raise PdfShareEncryptionError("Decrypted PDF share token has an invalid shape.")
    token = value.get("token")
    if not isinstance(token, str) or share_token_digest(token) != token_digest:
        raise PdfShareEncryptionError("Decrypted PDF share token failed digest verification.")
    return token


def database_coverage_status(db_path, *, workspace_id: str = GLOBAL_WORKSPACE_ID) -> Optional[dict]:
    return application_data.get_source_coverage(
        workspace_id,
        COVERAGE_DOMAIN,
        COVERAGE_SOURCE_KEY,
        db_path=db_path,
    )


def _manifest_sha256(material) -> str:
    return hashlib.sha256(
        application_data.canonical_json(sorted(material)).encode("utf-8")
    ).hexdigest()


def _prepared_source_manifest_sha256(prepared: Sequence[_PreparedShare]) -> str:
    return _manifest_sha256(
        (item.token_digest, item.record_sha256) for item in prepared
    )


def _database_authority_from_connection(connection, workspace_id: str) -> bool:
    rows = connection.execute(
        """
        SELECT token_digest, source_version, source_sha256
          FROM share_links
         WHERE workspace_id = ?
         ORDER BY token_digest
        """,
        (workspace_id,),
    ).fetchall()
    coverage = application_data.get_source_coverage(
        workspace_id,
        COVERAGE_DOMAIN,
        COVERAGE_SOURCE_KEY,
        connection=connection,
    )
    latest = connection.execute(
        """
        SELECT id, source_sha256, summary_json
          FROM migration_runs
         WHERE migration_kind = ? AND status = 'succeeded'
         ORDER BY rowid DESC
         LIMIT 1
        """,
        (MIGRATION_KIND,),
    ).fetchone()

    if latest is None and coverage is None:
        if rows:
            raise PdfShareMigrationCoverageError(
                "PDF-share rows exist without a completed source migration."
            )
        return False
    if latest is None or coverage is None:
        raise PdfShareMigrationCoverageError(
            "PDF-share migration run and source coverage are incomplete."
        )

    try:
        run_summary = json.loads(str(latest["summary_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PdfShareMigrationCoverageError(
            "PDF-share migration run marker is invalid."
        ) from exc
    expected_count = run_summary.get("record_count") if isinstance(run_summary, Mapping) else None
    expected_manifest = (
        run_summary.get("record_manifest_sha256")
        if isinstance(run_summary, Mapping)
        else None
    )
    source_sha256 = str(latest["source_sha256"] or "")
    expected_run_id = "pdf-share:%s" % source_sha256
    coverage_summary = coverage.get("summary")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 0
        or not isinstance(expected_manifest, str)
        or len(expected_manifest) != 64
        or len(source_sha256) != 64
        or str(latest["id"] or "") != expected_run_id
        or run_summary.get("workspace_id") != workspace_id
        or coverage.get("status") != "covered"
        or coverage.get("source_sha256") != source_sha256
        or coverage.get("migration_run_id") != latest["id"]
        or not isinstance(coverage_summary, Mapping)
        or coverage_summary.get("record_count") != expected_count
        or coverage_summary.get("record_manifest_sha256") != expected_manifest
        or coverage_summary.get("workspace_id") != workspace_id
    ):
        raise PdfShareMigrationCoverageError(
            "PDF-share migration markers do not describe one exact completed source."
        )

    if any(
        str(row["source_version"] or "") not in {MIGRATION_VERSION, "runtime"}
        for row in rows
    ):
        raise PdfShareMigrationCoverageError(
            "PDF-share database contains rows with an unknown source version."
        )
    migrated_rows = [
        row for row in rows if str(row["source_version"] or "") == MIGRATION_VERSION
    ]
    current_manifest = _manifest_sha256(
        (str(row["token_digest"]), str(row["source_sha256"] or ""))
        for row in migrated_rows
    )
    if len(migrated_rows) != expected_count or current_manifest != expected_manifest:
        raise PdfShareMigrationCoverageError(
            "PDF-share database migration coverage is incomplete."
        )
    return True


def database_share_records_are_authoritative(
    db_path,
    *,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
) -> bool:
    """Prove that database reads cover one exact completed legacy source.

    Runtime-created rows are allowed after that cutover marker, but they cannot
    substitute for a missing row from the migrated source.
    """

    with application_data.existing_application_read_connection(db_path) as connection:
        if connection is None:
            return False
        return _database_authority_from_connection(connection, workspace_id)


def database_share_records(
    db_path,
    *,
    include_tokens: bool = False,
    encryptor: Optional[SecretEncryptor] = None,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    require_authoritative: bool = False,
) -> Dict[str, list]:
    if include_tokens and encryptor is None:
        raise PdfShareEncryptionError(
            "Authorized token re-display requires a configured encryptor."
        )
    if require_authoritative:
        with application_data.existing_application_read_connection(db_path) as connection:
            if connection is None or not _database_authority_from_connection(
                connection,
                workspace_id,
            ):
                raise PdfShareMigrationCoverageError(
                    "PDF-share database migration coverage is unavailable."
                )
            rows = application_data.list_share_links(
                workspace_id=workspace_id,
                connection=connection,
            )
    else:
        rows = application_data.list_share_links(
            workspace_id=workspace_id,
            db_path=db_path,
        )
    return {
        "links": [
            legacy_record_from_database(
                row,
                token=(decrypt_share_token(row, encryptor) if include_tokens and encryptor else ""),
            )
            for row in rows
        ]
    }


def database_find_share_record(
    token: str,
    db_path,
    *,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    require_authoritative: bool = False,
) -> Optional[dict]:
    digest = share_token_digest(token)
    if require_authoritative:
        with application_data.existing_application_read_connection(db_path) as connection:
            if connection is None or not _database_authority_from_connection(
                connection,
                workspace_id,
            ):
                raise PdfShareMigrationCoverageError(
                    "PDF-share database migration coverage is unavailable."
                )
            row = application_data.get_share_link(digest, connection=connection)
    else:
        row = application_data.get_share_link(digest, db_path=db_path)
    if row and str(row.get("workspace_id") or "") != workspace_id:
        return None
    return legacy_record_from_database(row, token=token) if row else None


def database_upsert_share_record(
    record: Mapping[str, object],
    db_path,
    encryptor: SecretEncryptor,
    *,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    updated_at: str = "",
    register_artifact: bool = False,
    artifact_path=None,
    require_authoritative: bool = False,
) -> dict:
    item = _prepare_record(record)
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if require_authoritative and not _database_authority_from_connection(
            connection,
            workspace_id,
        ):
            raise PdfShareMigrationCoverageError(
                "PDF-share database migration coverage is unavailable."
            )
        application_data.ensure_workspace(
            workspace_id,
            GLOBAL_WORKSPACE_TYPE,
            GLOBAL_EXTERNAL_ID,
            connection=connection,
        )
        artifact = None
        if register_artifact:
            from PushShoppingList.services.artifact_ownership_service import (
                register_pdf_share_artifact,
            )

            artifact = register_pdf_share_artifact(
                artifact_path or item.pdf_path,
                workspace_id=workspace_id,
                workspace_type=GLOBAL_WORKSPACE_TYPE,
                subject_id=GLOBAL_EXTERNAL_ID,
                connection=connection,
            )
        existing = application_data.get_share_link(
            item.token_digest,
            connection=connection,
        )
        if existing is None:
            envelope = json.loads(
                encrypt_share_token(item.token, item.token_digest, encryptor)
            )
            envelope_key_id = encryptor.key_id
        else:
            if str(existing.get("workspace_id") or "") != workspace_id:
                raise PdfShareMigrationCollisionError(
                    "Existing PDF share digest belongs to another workspace."
                )
            try:
                stored_token = decrypt_share_token(existing, encryptor)
            except PdfShareEncryptionError as exc:
                raise PdfShareMigrationCollisionError(
                    "Existing PDF share token cannot be verified."
                ) from exc
            if stored_token != item.token:
                raise PdfShareMigrationCollisionError(
                    "Existing PDF share digest resolves to another token."
                )
            if (
                _stored_runtime_metadata_matches(existing, item, workspace_id)
                and (
                    artifact is None
                    or str(existing.get("artifact_id") or "")
                    == str(artifact.get("id") or "")
                )
            ):
                return legacy_record_from_database(existing, token=item.token)
            envelope = existing["encrypted_token"]
            envelope_key_id = str(existing.get("encryption_key_id") or "")
        result = application_data.upsert_share_link(
            item.token_digest,
            envelope,
            envelope_key_id,
            workspace_id=workspace_id,
            created_by_user_id=item.created_by_user_id,
            created_by_email=item.created_by_email,
            artifact_id=(
                str(artifact.get("id") or "")
                if artifact is not None
                else str((existing or {}).get("artifact_id") or "")
            ),
            pdf_filename=item.pdf_filename,
            pdf_path=item.pdf_path,
            original_filename=item.original_filename,
            created_at=item.created_at,
            expires_at=item.expires_at,
            allow_download=item.allow_download,
            revoked=item.revoked,
            access_count=item.access_count,
            last_accessed_at=item.last_accessed_at,
            updated_at=updated_at or (item.created_at if existing is None else _timestamp(None)),
            source_version="runtime",
            source_sha256=item.record_sha256,
            allow_update=existing is not None,
            connection=connection,
        )
    return legacy_record_from_database(result, token=item.token)


def database_revoke_share_token(
    token: str,
    db_path,
    *,
    updated_at: str,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    require_authoritative: bool = False,
) -> Optional[dict]:
    digest = share_token_digest(token)
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if require_authoritative and not _database_authority_from_connection(
            connection,
            workspace_id,
        ):
            raise PdfShareMigrationCoverageError(
                "PDF-share database migration coverage is unavailable."
            )
        existing = application_data.get_share_link(digest, connection=connection)
        if existing is None or str(existing.get("workspace_id") or "") != workspace_id:
            return None
        row = application_data.update_share_link_state(
            digest,
            revoked=True,
            updated_at=updated_at,
            expected_row_version=int(existing["row_version"]),
            connection=connection,
        )
    return legacy_record_from_database(row, token=token) if row else None


def database_record_share_access(
    token: str,
    db_path,
    *,
    accessed_at: str,
    workspace_id: str = GLOBAL_WORKSPACE_ID,
    require_authoritative: bool = False,
) -> Optional[dict]:
    digest = share_token_digest(token)
    with application_data.application_data_write_connection(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if require_authoritative and not _database_authority_from_connection(
            connection,
            workspace_id,
        ):
            raise PdfShareMigrationCoverageError(
                "PDF-share database migration coverage is unavailable."
            )
        row = application_data.get_share_link(digest, connection=connection)
        if row is None or str(row.get("workspace_id") or "") != workspace_id:
            return None
        changed = application_data.update_share_link_state(
            digest,
            access_count=int(row["access_count"]) + 1,
            last_accessed_at=accessed_at,
            updated_at=accessed_at,
            expected_row_version=int(row["row_version"]),
            connection=connection,
        )
    return legacy_record_from_database(changed, token=token)


def legacy_record_from_database(row: Optional[Mapping[str, object]], *, token: str = "") -> dict:
    if not row:
        return {}
    return {
        "token": token,
        "pdf_filename": str(row.get("pdf_filename") or ""),
        "pdf_path": str(row.get("pdf_path") or ""),
        "original_filename": str(row.get("original_filename") or ""),
        "created_at": str(row.get("created_at") or ""),
        "expires_at": str(row.get("expires_at") or ""),
        "created_by_user_id": str(row.get("created_by_user_id") or ""),
        "created_by_email": str(row.get("created_by_email") or ""),
        "allow_download": bool(row.get("allow_download", True)),
        "revoked": bool(row.get("revoked", False)),
        "access_count": int(row.get("access_count") or 0),
        "last_accessed_at": row.get("last_accessed_at") or None,
    }


def _stored_metadata_matches(row: Mapping[str, object], item: _PreparedShare) -> bool:
    return (
        str(row.get("pdf_filename") or "") == item.pdf_filename
        and str(row.get("pdf_path") or "") == item.pdf_path
        and str(row.get("original_filename") or "") == item.original_filename
        and str(row.get("created_at") or "") == item.created_at
        and str(row.get("expires_at") or "") == item.expires_at
        and str(row.get("created_by_user_id") or "") == item.created_by_user_id
        and str(row.get("created_by_email") or "") == item.created_by_email
        and bool(row.get("allow_download")) == item.allow_download
        and bool(row.get("revoked")) == item.revoked
        and int(row.get("access_count") or 0) == item.access_count
        and str(row.get("last_accessed_at") or "") == item.last_accessed_at
        and str(row.get("source_sha256") or "") == item.record_sha256
    )


def _stored_runtime_metadata_matches(
    row: Mapping[str, object],
    item: _PreparedShare,
    workspace_id: str,
) -> bool:
    return (
        str(row.get("digest_algorithm") or "") == "sha256"
        and str(row.get("workspace_id") or "") == workspace_id
        and str(row.get("source_version") or "") == "runtime"
        and _stored_metadata_matches(row, item)
    )


def _assert_existing_migration_row(
    row: Optional[Mapping[str, object]],
    item: _PreparedShare,
    workspace_id: str,
    encryptor: SecretEncryptor,
) -> None:
    if row is None:
        raise PdfShareMigrationCollisionError(
            "Coverage exists but a migrated PDF share row is missing."
        )
    try:
        token = decrypt_share_token(row, encryptor)
    except PdfShareEncryptionError as exc:
        raise PdfShareMigrationCollisionError(
            "Existing PDF share token cannot be verified."
        ) from exc
    if (
        token != item.token
        or str(row.get("digest_algorithm") or "") != "sha256"
        or str(row.get("workspace_id") or "") != workspace_id
        or str(row.get("source_version") or "") != MIGRATION_VERSION
        or not _stored_metadata_matches(row, item)
    ):
        raise PdfShareMigrationCollisionError(
            "Existing PDF share row differs from the legacy source."
        )


def _scan_source(path: Path) -> Tuple[bytes, Tuple[_PreparedShare, ...]]:
    if not path.is_file():
        raise FileNotFoundError("PDF-share source is missing.")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise _ShareShapeError("source_too_large")
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise _ShareShapeError("source_too_large")
    value = _strict_json_loads(raw)
    if isinstance(value, list):
        records = value
    elif isinstance(value, dict) and set(value) == {"links"}:
        records = value["links"]
    else:
        raise _ShareShapeError("expected_links_document")
    if not isinstance(records, list):
        raise _ShareShapeError("links_not_array")
    prepared = tuple(_prepare_record(record) for record in records)
    digests = [item.token_digest for item in prepared]
    if len(digests) != len(set(digests)):
        raise _ShareShapeError("duplicate_token_digest")
    return raw, prepared


def _prepare_record(record: object) -> _PreparedShare:
    if not isinstance(record, dict) or set(record).difference(_ALLOWED_RECORD_FIELDS):
        raise _ShareShapeError("invalid_share_record")
    token = record.get("token")
    if (
        not isinstance(token, str)
        or not token
        or token.strip() != token
        or "\x00" in token
    ):
        raise _ShareShapeError("invalid_share_token")
    pdf_filename = record.get("pdf_filename")
    if (
        not isinstance(pdf_filename, str)
        or not pdf_filename
        or Path(pdf_filename).name != pdf_filename
        or Path(pdf_filename).suffix.lower() != ".pdf"
    ):
        raise _ShareShapeError("invalid_pdf_filename")
    original = record.get("original_filename", pdf_filename)
    if not isinstance(original, str) or not original or Path(original).name != original:
        raise _ShareShapeError("invalid_original_filename")
    pdf_path = record.get("pdf_path", "")
    created_by_user_id = record.get("created_by_user_id", "")
    created_by_email = record.get("created_by_email", "")
    for value in (pdf_path, created_by_user_id, created_by_email):
        if not isinstance(value, str) or "\x00" in value:
            raise _ShareShapeError("invalid_share_text")
    created_at = _validate_timestamp(record.get("created_at"), "created_at")
    expires_at = _validate_timestamp(record.get("expires_at"), "expires_at")
    allow_download = record.get("allow_download", True)
    revoked = record.get("revoked", False)
    if not isinstance(allow_download, bool) or not isinstance(revoked, bool):
        raise _ShareShapeError("invalid_share_flags")
    access_count = record.get("access_count", 0)
    if not isinstance(access_count, int) or isinstance(access_count, bool) or access_count < 0:
        raise _ShareShapeError("invalid_access_count")
    last_access = record.get("last_accessed_at")
    if last_access in (None, ""):
        last_access = ""
    else:
        last_access = _validate_timestamp(last_access, "last_accessed_at")
    canonical_record = {
        "token": token,
        "pdf_filename": pdf_filename,
        "pdf_path": pdf_path,
        "original_filename": original,
        "created_at": created_at,
        "expires_at": expires_at,
        "created_by_user_id": created_by_user_id,
        "created_by_email": created_by_email,
        "allow_download": allow_download,
        "revoked": revoked,
        "access_count": access_count,
        "last_accessed_at": last_access or None,
    }
    return _PreparedShare(
        token=token,
        token_digest=share_token_digest(token),
        record_sha256=application_data.sha256_json(canonical_record),
        pdf_filename=pdf_filename,
        pdf_path=pdf_path,
        original_filename=original,
        created_at=created_at,
        expires_at=expires_at,
        created_by_user_id=created_by_user_id,
        created_by_email=created_by_email,
        allow_download=allow_download,
        revoked=revoked,
        access_count=access_count,
        last_accessed_at=last_access,
    )


def _strict_json_loads(raw: bytes) -> object:
    text = raw.decode("utf-8-sig", errors="strict")

    def object_pairs(pairs: Sequence[Tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise ValueError("non_finite_json_number")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def _validate_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _ShareShapeError("invalid_%s" % field_name)
    _parse_timestamp(value)
    return value


def _parse_timestamp(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise _ShareShapeError("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise _ShareShapeError("timestamp_missing_timezone")
    return parsed.astimezone(timezone.utc)


def _validate_encryptor(encryptor: object) -> None:
    if (
        encryptor is None
        or not isinstance(getattr(encryptor, "key_id", None), str)
        or not encryptor.key_id
        or not callable(getattr(encryptor, "encrypt_json", None))
        or not callable(getattr(encryptor, "decrypt_json", None))
    ):
        raise PdfShareEncryptionError("A configured token encryptor is required.")


def _validate_envelope(value: object, key_id: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "algorithm", "key_id", "nonce", "ciphertext"
    }:
        raise PdfShareEncryptionError("Encrypted token envelope has an invalid shape.")
    if any(not isinstance(value.get(key), str) or not value.get(key) for key in value):
        raise PdfShareEncryptionError("Encrypted token envelope is incomplete.")
    if value["key_id"] != key_id:
        raise PdfShareEncryptionError("Encrypted token key ID does not match.")


def _clock_value(clock: Optional[Callable[[], datetime]]) -> datetime:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(clock: Optional[Callable[[], datetime]]) -> str:
    return _clock_value(clock).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return "source_missing"
    if isinstance(exc, _DuplicateJsonKeyError):
        return "duplicate_json_key"
    if isinstance(exc, UnicodeError):
        return "invalid_utf8"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, OSError):
        return "source_io_error"
    if isinstance(exc, _ShareShapeError):
        code = str(exc)
        return code if code.replace("_", "").isalnum() else "invalid_share_source"
    return "invalid_share_source"


__all__ = [
    "APPLY_APPROVAL_PHRASE",
    "COVERAGE_DOMAIN",
    "COVERAGE_SOURCE_KEY",
    "GLOBAL_WORKSPACE_ID",
    "PdfShareEncryptionError",
    "PdfShareMigrationApplyResult",
    "PdfShareMigrationApprovalError",
    "PdfShareMigrationCollisionError",
    "PdfShareMigrationCoverageError",
    "PdfShareMigrationError",
    "PdfShareMigrationPreview",
    "PdfShareMigrationSourceError",
    "StalePdfSharePreviewError",
    "TOKEN_ENCRYPTION_AAD_VERSION",
    "apply_pdf_share_migration",
    "database_coverage_status",
    "database_find_share_record",
    "database_record_share_access",
    "database_revoke_share_token",
    "database_share_records",
    "database_share_records_are_authoritative",
    "database_upsert_share_record",
    "decrypt_share_token",
    "encrypt_share_token",
    "legacy_record_from_database",
    "preview_pdf_share_migration",
    "share_token_associated_data",
    "share_token_digest",
]
