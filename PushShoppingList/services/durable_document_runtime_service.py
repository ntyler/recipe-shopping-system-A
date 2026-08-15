"""Opt-in compatibility reads and writes for migrated durable JSON documents.

Legacy JSON remains authoritative unless an operator explicitly selects another
backend.  Database-preferred reads require a document and its exact source
coverage marker to agree, so a partial backfill cannot silently hide newer JSON
data.  Shadow writes keep serving JSON and make database divergence observable.

This module never installs schema, removes a legacy file, or runs cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Callable, Mapping, Optional


DURABLE_BACKEND_ENV = "SHOPPING_APP_DURABLE_DATA_BACKEND"
DURABLE_BACKEND_MODES = frozenset({"json", "shadow", "db_preferred", "db_only"})
GLOBAL_WORKSPACE_ID = "global:application"
GLOBAL_WORKSPACE_TYPE = "system"
GLOBAL_SUBJECT_ID = "application"


class DurableDocumentRuntimeError(RuntimeError):
    """Raised when a selected durable-document backend cannot be used safely."""


class DurableDocumentConflictError(DurableDocumentRuntimeError):
    """Raised when a concurrent writer changed a document after it was read."""


class DurableDocumentDeletedError(DurableDocumentRuntimeError):
    """Raised when an authoritative database tombstone hides legacy JSON."""


class DurableDocumentLifecycleError(DurableDocumentRuntimeError):
    """Raised when guest lifecycle state forbids recreating durable data."""


def durable_backend_mode(environment=None) -> str:
    environment = environment if environment is not None else os.environ
    mode = str(environment.get(DURABLE_BACKEND_ENV, "json") or "json").strip().lower()
    if mode not in DURABLE_BACKEND_MODES:
        raise DurableDocumentRuntimeError("Durable data backend mode is invalid.")
    return mode


def active_workspace_identity(
    *,
    workspace_id: str = "",
    workspace_type: str = "",
    subject_id: str = "",
):
    """Resolve the opaque database identity without deriving it from a path."""

    if workspace_id:
        resolved_id = str(workspace_id)
        resolved_type = str(workspace_type or "user")
        resolved_subject = str(subject_id or workspace_id)
    else:
        from PushShoppingList.services import storage_service

        guest_id = storage_service.active_guest_session_id()
        if guest_id:
            resolved_id = "guest:%s" % guest_id
            resolved_type = "guest"
            resolved_subject = guest_id
        else:
            user_id = storage_service.active_user_id()
            if not user_id:
                raise DurableDocumentRuntimeError(
                    "A durable document requires an explicit or active workspace."
                )
            resolved_id = user_id
            resolved_type = "user"
            resolved_subject = user_id

    for name, value in (
        ("workspace_id", resolved_id),
        ("workspace_type", resolved_type),
        ("subject_id", resolved_subject),
    ):
        if not value or "\x00" in value:
            raise DurableDocumentRuntimeError("%s is invalid." % name)
    return resolved_id, resolved_type, resolved_subject


def _write_workspace_identity(
    *,
    workspace_id: str = "",
    workspace_type: str = "",
    subject_id: str = "",
    required: bool,
):
    if workspace_id:
        return active_workspace_identity(
            workspace_id=workspace_id,
            workspace_type=workspace_type,
            subject_id=subject_id,
        )
    from PushShoppingList.services import storage_service

    guest_id = storage_service.active_guest_session_id()
    if guest_id:
        return "guest:%s" % guest_id, "guest", guest_id
    user_id = storage_service.active_user_id()
    if user_id:
        return user_id, "user", user_id
    if required:
        raise DurableDocumentRuntimeError(
            "A durable document requires an explicit or active workspace."
        )
    return "", "", ""


def _assert_workspace_write_is_allowed(
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    *,
    connection=None,
    db_path=None,
):
    if not workspace_id:
        return
    application_data = _application_data()
    if application_data.guest_workspace_write_is_fenced(
        workspace_id,
        workspace_type=workspace_type,
        external_id=subject_id,
        guest_session_id=subject_id if workspace_type == "guest" else "",
        connection=connection,
        db_path=db_path,
    ):
        raise DurableDocumentLifecycleError(
            "Guest workspace lifecycle forbids recreating durable data."
        )


@contextmanager
def _legacy_workspace_write_guard(
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    *,
    db_path=None,
):
    """Serialize the final fence check with in-process purge commits.

    Guest purge database operations use the same application-data lock.  By
    holding it through the legacy callback, an in-flight request either writes
    before the tombstone (so cleanup observes the file) or sees the committed
    tombstone and does not write at all.
    """

    application_data = _application_data()
    with application_data.APPLICATION_DATA_LOCK:
        # A persisted guest tombstone implies a fully installed application
        # schema.  Hold SQLite's cross-process writer reservation through the
        # callback so another process cannot commit the purge fence between
        # this final check and the legacy file mutation.
        if workspace_type == "guest":
            status = application_data.application_schema_status(db_path)
            if status.get("available"):
                with application_data.application_data_write_connection(db_path) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    _assert_workspace_write_is_allowed(
                        workspace_id,
                        workspace_type,
                        subject_id,
                        connection=connection,
                    )
                    yield
                return

        # JSON-only deployments without the approved schema must not create a
        # database merely to run a compatibility saver.  The read-only helper
        # still recognizes a tombstone table if one exists.
        _assert_workspace_write_is_allowed(
            workspace_id,
            workspace_type,
            subject_id,
            db_path=db_path,
        )
        yield


def source_coverage_key(workspace_id: str, source_key: str, source_ref: str) -> str:
    """Return the same stable source key used by the staged JSON backfill."""

    values = tuple(str(value) for value in (workspace_id, source_key, source_ref))
    if any(not value or "\x00" in value for value in values):
        raise DurableDocumentRuntimeError("Source coverage identity is invalid.")
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def canonical_source_sha256(document: object) -> str:
    from PushShoppingList.services.application_data_service import canonical_json

    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _application_data():
    from PushShoppingList.services import application_data_service

    return application_data_service


def _schema_path_and_status(db_path=None):
    application_data = _application_data()
    path = Path(application_data.application_data_db_path(db_path))
    status = application_data.application_schema_status(path)
    return application_data, path, status


def _document_and_coverage(
    workspace_id: str,
    domain: str,
    document_key: str,
    coverage_key: str,
    *,
    db_path=None,
):
    application_data, path, status = _schema_path_and_status(db_path)
    if not path.is_file() or not status.get("current_version"):
        return None, None, status
    if not status.get("available"):
        raise DurableDocumentRuntimeError(
            "Application database schema is incompatible with durable reads."
        )
    try:
        with application_data.existing_application_read_connection(path) as connection:
            if connection is None:
                return None, None, status
            document = application_data.get_durable_document(
                workspace_id,
                domain,
                document_key,
                connection=connection,
            )
            coverage = application_data.get_source_coverage(
                workspace_id,
                domain,
                coverage_key,
                connection=connection,
            )
    except DurableDocumentRuntimeError:
        raise
    except Exception as exc:
        raise DurableDocumentRuntimeError("Durable database read failed.") from exc
    return document, coverage, status


def database_document_is_authoritative(
    *,
    workspace_id: str,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    db_path=None,
) -> bool:
    return database_document_state(
        workspace_id=workspace_id,
        domain=domain,
        document_key=document_key,
        source_key=source_key,
        source_ref=source_ref,
        db_path=db_path,
    ) in {"covered", "deleted"}


def database_document_state(
    *,
    workspace_id: str,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    db_path=None,
) -> str:
    """Return ``absent``, ``covered``, or ``deleted`` after strict validation."""

    coverage_key = source_coverage_key(workspace_id, source_key, source_ref)
    document, coverage, status = _document_and_coverage(
        workspace_id,
        domain,
        document_key,
        coverage_key,
        db_path=db_path,
    )
    if not status.get("current_version"):
        return "absent"
    if document is None and coverage is None:
        return "absent"
    if (
        document is None
        and coverage is not None
        and coverage.get("status") == "deleted"
    ):
        return "deleted"
    if document is None or coverage is None:
        raise DurableDocumentRuntimeError(
            "Durable document and migration coverage are incomplete."
        )
    if (
        coverage.get("status") != "covered"
        or coverage.get("source_sha256") != document.get("source_sha256")
    ):
        raise DurableDocumentRuntimeError(
            "Durable document does not match its migration coverage."
        )
    return "covered"


def _associated_data(
    workspace_id: str,
    domain: str,
    document_key: str,
    source_sha256: str,
) -> str:
    return "\x1f".join((workspace_id, domain, document_key, source_sha256))


def _configured_encryptor(encryptor=None):
    if encryptor is not None:
        return encryptor
    from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor

    return AesGcmDataEncryptor.from_environment()


def _decoded_document(row: Mapping[str, object], *, encrypted: bool, encryptor=None):
    document = deepcopy(row.get("document"))
    if not encrypted:
        return document
    if not isinstance(document, Mapping):
        raise DurableDocumentRuntimeError("Encrypted durable document is invalid.")
    configured = _configured_encryptor(encryptor)
    envelope = json.dumps(
        dict(document), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    try:
        value = configured.decrypt_json(
            envelope,
            associated_data=_associated_data(
                str(row.get("workspace_id") or ""),
                str(row.get("domain") or ""),
                str(row.get("document_key") or ""),
                str(row.get("source_sha256") or ""),
            ),
        )
    except Exception as exc:
        raise DurableDocumentRuntimeError("Durable document decryption failed.") from exc
    return value


def read_database_document(
    *,
    workspace_id: str,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    encrypted: bool = False,
    encryptor=None,
    db_path=None,
    require_coverage: bool = True,
):
    coverage_key = source_coverage_key(workspace_id, source_key, source_ref)
    document, coverage, status = _document_and_coverage(
        workspace_id,
        domain,
        document_key,
        coverage_key,
        db_path=db_path,
    )
    if not status.get("available"):
        raise DurableDocumentRuntimeError("Durable database schema is unavailable.")
    if (
        document is None
        and coverage is not None
        and coverage.get("status") == "deleted"
    ):
        raise DurableDocumentDeletedError(
            "Durable database document was deleted after migration."
        )
    if document is None:
        raise DurableDocumentRuntimeError("Durable database document is missing.")
    if require_coverage and (
        coverage is None
        or coverage.get("status") != "covered"
        or coverage.get("source_sha256") != document.get("source_sha256")
    ):
        raise DurableDocumentRuntimeError(
            "Durable database document has no matching coverage marker."
        )
    return _decoded_document(document, encrypted=encrypted, encryptor=encryptor)


def write_database_document(
    document: object,
    *,
    workspace_id: str,
    workspace_type: str,
    subject_id: str,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    encrypted: bool = False,
    encryptor=None,
    db_path=None,
    expected_source_sha256: Optional[str] = None,
    previous_source_ref: str = "",
    new_artifact_paths=(),
):
    _assert_workspace_write_is_allowed(
        workspace_id,
        workspace_type,
        subject_id,
        db_path=db_path,
    )
    application_data, path, status = _schema_path_and_status(db_path)
    if not path.is_file() or not status.get("available"):
        raise DurableDocumentRuntimeError("Durable database schema is unavailable.")
    source_sha256 = canonical_source_sha256(document)
    coverage_key = source_coverage_key(workspace_id, source_key, source_ref)
    previous_source_ref = str(previous_source_ref or "")
    previous_coverage_key = (
        source_coverage_key(workspace_id, source_key, previous_source_ref)
        if previous_source_ref and previous_source_ref != source_ref
        else ""
    )
    stored_document = deepcopy(document)
    encryption_key_id = ""
    if encrypted:
        configured = _configured_encryptor(encryptor)
        encryption_key_id = configured.key_id
        envelope = configured.encrypt_json(
            document,
            associated_data=_associated_data(
                workspace_id, domain, document_key, source_sha256
            ),
        )
        stored_document = json.loads(envelope)

    try:
        with application_data.application_data_write_connection(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            application_data.ensure_workspace(
                workspace_id,
                workspace_type,
                subject_id,
                lifecycle_state="active",
                connection=connection,
            )
            existing = application_data.get_durable_document(
                workspace_id,
                domain,
                document_key,
                connection=connection,
            )
            if previous_coverage_key:
                previous_coverage = application_data.get_source_coverage(
                    workspace_id,
                    domain,
                    previous_coverage_key,
                    connection=connection,
                )
                target_coverage = application_data.get_source_coverage(
                    workspace_id,
                    domain,
                    coverage_key,
                    connection=connection,
                )
                if target_coverage is not None:
                    raise DurableDocumentConflictError(
                        "The destination source already has durable coverage."
                    )
                if previous_coverage is None:
                    raise DurableDocumentConflictError(
                        "The previous durable source coverage changed; retry the operation."
                    )
                previous_summary = previous_coverage.get("summary")
                if (
                    not isinstance(previous_summary, Mapping)
                    or previous_summary.get("document_key") != document_key
                    or previous_summary.get("source_key") != source_key
                    or previous_summary.get("source_ref") != previous_source_ref
                ):
                    raise DurableDocumentRuntimeError(
                        "The previous durable source coverage binding is invalid."
                    )
                previous_status = str(previous_coverage.get("status") or "")
                previous_is_covered = (
                    previous_status == "covered"
                    and existing is not None
                    and previous_coverage.get("source_sha256")
                    == existing.get("source_sha256")
                )
                previous_is_deleted = (
                    previous_status == "deleted" and existing is None
                )
                if not previous_is_covered and not previous_is_deleted:
                    raise DurableDocumentRuntimeError(
                        "The previous durable source coverage is incomplete."
                    )
            if expected_source_sha256 is not None:
                actual_source_sha256 = (
                    str(existing.get("source_sha256") or "") if existing else ""
                )
                if actual_source_sha256 != expected_source_sha256:
                    raise DurableDocumentConflictError(
                        "Durable document changed concurrently; retry the operation."
                    )
            run_id = uuid.uuid4().hex
            application_data.record_application_migration_run(
                "runtime_durable_write",
                "succeeded",
                run_id=run_id,
                source_sha256=source_sha256,
                summary={
                    "documents": 1,
                    "encrypted": bool(encrypted),
                    "source_key": source_key,
                },
                connection=connection,
            )
            result = application_data.upsert_durable_document(
                workspace_id,
                domain,
                document_key,
                stored_document,
                source_kind="runtime_json_compat",
                source_name=source_key,
                source_sha256=source_sha256,
                source_version="1",
                connection=connection,
            )
            application_data.upsert_source_coverage(
                workspace_id,
                domain,
                coverage_key,
                source_sha256,
                migration_run_id=run_id,
                status="covered",
                summary={
                    "document_key": document_key,
                    "encrypted": bool(encrypted),
                    "encryption_key_id": encryption_key_id,
                    "runtime_write": True,
                    "source_key": source_key,
                    "source_ref": source_ref,
                },
                connection=connection,
            )
            if previous_coverage_key:
                cursor = connection.execute(
                    """
                    DELETE FROM application_source_coverage
                     WHERE workspace_id = ? AND domain = ? AND source_key = ?
                    """,
                    (workspace_id, domain, previous_coverage_key),
                )
                if cursor.rowcount != 1:
                    raise DurableDocumentConflictError(
                        "The previous durable source coverage changed; retry the operation."
                    )
            # Ownership metadata is part of the same transaction as the
            # durable document.  JSON-only compatibility mode never reaches
            # this path, and shadow failures are handled by the caller's
            # existing redacted divergence log.
            from PushShoppingList.services.artifact_ownership_service import (
                register_document_artifacts,
            )

            register_document_artifacts(
                document,
                workspace_id=workspace_id,
                workspace_type=workspace_type,
                subject_id=subject_id,
                source_sha256=source_sha256,
                connection=connection,
            )
            if new_artifact_paths:
                from PushShoppingList.services.artifact_ownership_service import (
                    register_new_local_artifacts,
                )

                register_new_local_artifacts(
                    new_artifact_paths,
                    workspace_id=workspace_id,
                    workspace_type=workspace_type,
                    subject_id=subject_id,
                    connection=connection,
                )
    except DurableDocumentRuntimeError:
        raise
    except Exception as exc:
        raise DurableDocumentRuntimeError("Durable database write failed.") from exc
    return deepcopy(document), result


def list_database_documents(
    *,
    workspace_id: str,
    domain: str,
    source_key: str,
    encrypted: bool = False,
    encryptor=None,
    db_path=None,
    require_schema: bool = True,
    include_deleted: bool = False,
):
    """List one migrated source family with an exact marker per document."""

    application_data, path, status = _schema_path_and_status(db_path)
    if not path.is_file() or not status.get("current_version"):
        if require_schema:
            raise DurableDocumentRuntimeError("Durable database schema is unavailable.")
        return []
    if not status.get("available"):
        raise DurableDocumentRuntimeError(
            "Application database schema is incompatible with durable reads."
        )
    try:
        with application_data.existing_application_read_connection(path) as connection:
            if connection is None:
                if require_schema:
                    raise DurableDocumentRuntimeError(
                        "Durable database schema is unavailable."
                    )
                return []
            document_rows = connection.execute(
                """
                SELECT * FROM durable_documents
                 WHERE workspace_id = ? AND domain = ?
                 ORDER BY document_key
                """,
                (workspace_id, domain),
            ).fetchall()
            coverage_rows = connection.execute(
                """
                SELECT * FROM application_source_coverage
                 WHERE workspace_id = ? AND domain = ?
                 ORDER BY source_key
                """,
                (workspace_id, domain),
            ).fetchall()
    except DurableDocumentRuntimeError:
        raise
    except Exception as exc:
        raise DurableDocumentRuntimeError("Durable database list failed.") from exc

    documents = {str(row["document_key"]): dict(row) for row in document_rows}
    relevant_document_keys = {
        key
        for key, row in documents.items()
        if str(row.get("source_name") or "") == source_key
        or str(row.get("source_name") or "").startswith(source_key + "-")
    }
    results = []
    covered_keys = set()
    for raw_coverage in coverage_rows:
        coverage = dict(raw_coverage)
        try:
            summary = json.loads(str(coverage.pop("summary_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DurableDocumentRuntimeError(
                "Durable source coverage summary is invalid."
            ) from exc
        if not isinstance(summary, Mapping) or summary.get("source_key") != source_key:
            continue
        summary_source_ref = str(summary.get("source_ref") or "")
        if (
            not summary_source_ref
            or source_coverage_key(workspace_id, source_key, summary_source_ref)
            != str(coverage.get("source_key") or "")
        ):
            raise DurableDocumentRuntimeError(
                "Durable source coverage has no exact source reference."
            )
        document_key = str(summary.get("document_key") or "")
        if not document_key:
            raise DurableDocumentRuntimeError(
                "Durable source coverage has no document binding."
            )
        if document_key in covered_keys:
            raise DurableDocumentRuntimeError(
                "Durable source coverage contains a document collision."
            )
        covered_keys.add(document_key)
        document_row = documents.get(document_key)
        coverage_status = str(coverage.get("status") or "")
        if coverage_status == "deleted":
            if document_row is not None:
                raise DurableDocumentRuntimeError(
                    "A deleted durable document still has a live row."
                )
            if include_deleted:
                results.append(
                    {
                        "document": None,
                        "document_key": document_key,
                        "source_ref": summary_source_ref,
                        "source_sha256": str(coverage.get("source_sha256") or ""),
                        "status": "deleted",
                    }
                )
            continue
        if coverage_status != "covered" or document_row is None:
            raise DurableDocumentRuntimeError(
                "Durable multi-document coverage is incomplete."
            )
        if document_key not in relevant_document_keys:
            raise DurableDocumentRuntimeError(
                "Durable source coverage references another source family."
            )
        if coverage.get("source_sha256") != document_row.get("source_sha256"):
            raise DurableDocumentRuntimeError(
                "Durable multi-document coverage does not match its row."
            )
        try:
            stored_document = json.loads(str(document_row.get("document_json") or ""))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DurableDocumentRuntimeError("Durable document JSON is invalid.") from exc
        decoded = _decoded_document(
            {**document_row, "document": stored_document},
            encrypted=encrypted,
            encryptor=encryptor,
        )
        results.append(
            {
                "document": decoded,
                "document_key": document_key,
                "source_ref": summary_source_ref,
                "source_sha256": str(document_row.get("source_sha256") or ""),
                "status": "covered",
            }
        )

    if relevant_document_keys.difference(covered_keys):
        raise DurableDocumentRuntimeError(
            "Durable source rows are missing exact coverage bindings."
        )
    return results


def delete_database_document(
    *,
    workspace_id: str,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    db_path=None,
):
    """Atomically replace one covered document with an idempotent tombstone."""

    resolved_type = "guest" if str(workspace_id).startswith("guest:") else ""
    resolved_subject = (
        str(workspace_id).split(":", 1)[1] if resolved_type == "guest" else ""
    )
    _assert_workspace_write_is_allowed(
        workspace_id,
        resolved_type,
        resolved_subject,
        db_path=db_path,
    )
    application_data, path, status = _schema_path_and_status(db_path)
    if not path.is_file() or not status.get("available"):
        raise DurableDocumentRuntimeError("Durable database schema is unavailable.")
    coverage_key = source_coverage_key(workspace_id, source_key, source_ref)
    try:
        with application_data.application_data_write_connection(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            document = application_data.get_durable_document(
                workspace_id, domain, document_key, connection=connection
            )
            coverage = application_data.get_source_coverage(
                workspace_id, domain, coverage_key, connection=connection
            )
            if document is None and coverage is None:
                return {"action": "absent", "document_key": document_key}
            if (
                document is None
                and coverage is not None
                and coverage.get("status") == "deleted"
            ):
                return {"action": "unchanged", "document_key": document_key}
            if (
                document is None
                or coverage is None
                or coverage.get("status") != "covered"
                or coverage.get("source_sha256") != document.get("source_sha256")
            ):
                raise DurableDocumentRuntimeError(
                    "Durable document cannot be deleted with incomplete coverage."
                )
            run_id = uuid.uuid4().hex
            source_sha256 = str(document.get("source_sha256") or "")
            application_data.record_application_migration_run(
                "runtime_durable_delete",
                "succeeded",
                run_id=run_id,
                source_sha256=source_sha256,
                summary={"documents": 1, "source_key": source_key},
                connection=connection,
            )
            cursor = connection.execute(
                """
                DELETE FROM durable_documents
                 WHERE workspace_id = ? AND domain = ? AND document_key = ?
                """,
                (workspace_id, domain, document_key),
            )
            if cursor.rowcount != 1:
                raise DurableDocumentConflictError(
                    "Durable document changed concurrently; retry the operation."
                )
            application_data.upsert_source_coverage(
                workspace_id,
                domain,
                coverage_key,
                source_sha256,
                migration_run_id=run_id,
                status="deleted",
                summary={
                    "document_key": document_key,
                    "runtime_delete": True,
                    "source_key": source_key,
                    "source_ref": source_ref,
                },
                connection=connection,
            )
    except DurableDocumentRuntimeError:
        raise
    except Exception as exc:
        raise DurableDocumentRuntimeError("Durable database delete failed.") from exc
    return {"action": "deleted", "document_key": document_key}


def load_json_document(
    legacy_loader: Callable[[], object],
    *,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    workspace_id: str = "",
    workspace_type: str = "",
    subject_id: str = "",
    encrypted: bool = False,
    encryptor=None,
    db_path=None,
):
    mode = durable_backend_mode()
    if mode in {"json", "shadow"}:
        return legacy_loader()
    identity = active_workspace_identity(
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
    )
    resolved_id, _resolved_type, _resolved_subject = identity
    if mode == "db_only":
        return read_database_document(
            workspace_id=resolved_id,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=source_ref,
            encrypted=encrypted,
            encryptor=encryptor,
            db_path=db_path,
        )
    if mode == "db_preferred" and database_document_is_authoritative(
        workspace_id=resolved_id,
        domain=domain,
        document_key=document_key,
        source_key=source_key,
        source_ref=source_ref,
        db_path=db_path,
    ):
        return read_database_document(
            workspace_id=resolved_id,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=source_ref,
            encrypted=encrypted,
            encryptor=encryptor,
            db_path=db_path,
        )
    return legacy_loader()


def save_json_document(
    document: object,
    legacy_saver: Callable[[object], object],
    *,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    workspace_id: str = "",
    workspace_type: str = "",
    subject_id: str = "",
    encrypted: bool = False,
    encryptor=None,
    db_path=None,
    db_preferred_create_if_legacy_missing: Optional[Callable[[], bool]] = None,
    previous_source_ref: str = "",
    new_artifact_paths=(),
):
    mode = durable_backend_mode()
    resolved_id, resolved_type, resolved_subject = _write_workspace_identity(
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        required=mode != "json",
    )
    _assert_workspace_write_is_allowed(
        resolved_id,
        resolved_type,
        resolved_subject,
        db_path=db_path,
    )

    def write_legacy():
        with _legacy_workspace_write_guard(
            resolved_id,
            resolved_type,
            resolved_subject,
            db_path=db_path,
        ):
            return legacy_saver(document)

    if mode == "json":
        return write_legacy()

    def write_database(*, require_authoritative=False):
        authoritative_source_ref = str(previous_source_ref or source_ref)
        coverage_key = source_coverage_key(
            resolved_id, source_key, authoritative_source_ref
        )
        existing, coverage, _status = _document_and_coverage(
            resolved_id,
            domain,
            document_key,
            coverage_key,
            db_path=db_path,
        )
        if require_authoritative:
            covered = (
                existing is not None
                and coverage is not None
                and coverage.get("status") == "covered"
                and coverage.get("source_sha256") == existing.get("source_sha256")
            )
            deleted = (
                existing is None
                and coverage is not None
                and coverage.get("status") == "deleted"
            )
            if not covered and not deleted:
                raise DurableDocumentRuntimeError(
                    "Durable document is not authoritative for this write."
                )
        expected_source_sha256 = (
            str(existing.get("source_sha256") or "") if existing else ""
        )
        result, _metadata = write_database_document(
            document,
            workspace_id=resolved_id,
            workspace_type=resolved_type,
            subject_id=resolved_subject,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=source_ref,
            encrypted=encrypted,
            encryptor=encryptor,
            db_path=db_path,
            expected_source_sha256=expected_source_sha256,
            previous_source_ref=(
                authoritative_source_ref
                if authoritative_source_ref != source_ref
                else ""
            ),
            new_artifact_paths=new_artifact_paths,
        )
        return result

    if mode == "db_only":
        return write_database()
    if mode == "db_preferred":
        state = database_document_state(
            workspace_id=resolved_id,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=str(previous_source_ref or source_ref),
            db_path=db_path,
        )
        if state in {"covered", "deleted"}:
            return write_database(require_authoritative=True)
        if callable(db_preferred_create_if_legacy_missing):
            _application_data_service, database_path, schema_status = (
                _schema_path_and_status(db_path)
            )
            if (
                database_path.is_file()
                and schema_status.get("available")
                and bool(db_preferred_create_if_legacy_missing())
            ):
                return write_database()
        return write_legacy()
    if mode == "shadow":
        saved = write_legacy()
        try:
            write_database()
        except Exception as exc:
            from PushShoppingList.services.maintenance_log_service import (
                emit_maintenance_event,
            )

            emit_maintenance_event(
                event="durable_shadow_write",
                run_id=uuid.uuid4().hex,
                phase="compatibility_write",
                mode=mode,
                outcome="failed",
                counts={"documents": 1},
                workspace_id=resolved_id,
                error_code=type(exc).__name__,
            )
        return saved
    return write_legacy()


def delete_json_document(
    legacy_deleter: Callable[[], object],
    *,
    domain: str,
    document_key: str,
    source_key: str,
    source_ref: str,
    workspace_id: str = "",
    workspace_type: str = "",
    subject_id: str = "",
    db_path=None,
):
    """Delete through the selected backend without resurrecting rollback JSON."""

    mode = durable_backend_mode()
    resolved_id, _resolved_type, resolved_subject = _write_workspace_identity(
        workspace_id=workspace_id,
        workspace_type=workspace_type,
        subject_id=subject_id,
        required=mode != "json",
    )
    _assert_workspace_write_is_allowed(
        resolved_id,
        _resolved_type,
        resolved_subject,
        db_path=db_path,
    )

    def delete_legacy():
        with _legacy_workspace_write_guard(
            resolved_id,
            _resolved_type,
            resolved_subject,
            db_path=db_path,
        ):
            return legacy_deleter()

    if mode == "json":
        return delete_legacy()

    def delete_database():
        return delete_database_document(
            workspace_id=resolved_id,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=source_ref,
            db_path=db_path,
        )

    if mode == "db_only":
        return delete_database()
    if mode == "db_preferred":
        state = database_document_state(
            workspace_id=resolved_id,
            domain=domain,
            document_key=document_key,
            source_key=source_key,
            source_ref=source_ref,
            db_path=db_path,
        )
        if state in {"covered", "deleted"}:
            return delete_database()
        return delete_legacy()
    if mode == "shadow":
        deleted = delete_legacy()
        try:
            delete_database()
        except Exception as exc:
            from PushShoppingList.services.maintenance_log_service import (
                emit_maintenance_event,
            )

            emit_maintenance_event(
                event="durable_shadow_delete",
                run_id=uuid.uuid4().hex,
                phase="compatibility_delete",
                mode=mode,
                outcome="failed",
                counts={"documents": 1},
                workspace_id=resolved_id,
                error_code=type(exc).__name__,
            )
        return deleted
    return delete_legacy()


def atomic_write_json(path, document: object, *, newline: bool = True):
    """Replace one legacy JSON file atomically without changing its role."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, ensure_ascii=False)
    if newline:
        text += "\n"
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(resolved.parent),
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, resolved)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return document


__all__ = [
    "DURABLE_BACKEND_ENV",
    "DURABLE_BACKEND_MODES",
    "DurableDocumentConflictError",
    "DurableDocumentDeletedError",
    "DurableDocumentLifecycleError",
    "DurableDocumentRuntimeError",
    "GLOBAL_SUBJECT_ID",
    "GLOBAL_WORKSPACE_ID",
    "GLOBAL_WORKSPACE_TYPE",
    "active_workspace_identity",
    "atomic_write_json",
    "canonical_source_sha256",
    "database_document_is_authoritative",
    "database_document_state",
    "delete_database_document",
    "delete_json_document",
    "durable_backend_mode",
    "list_database_documents",
    "load_json_document",
    "read_database_document",
    "save_json_document",
    "source_coverage_key",
    "write_database_document",
]
