"""Runtime compatibility storage for account records.

The legacy JSON registry remains the default.  Database modes are deliberately
opt-in and never install schema.  This module converts between the existing
``users.json`` record shape and the normalized/encrypted application tables so
the rest of the account service can be cut over without changing authentication
semantics or opaque account identifiers.
"""

from __future__ import annotations

import json
import os
import hashlib
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Mapping, Optional


ACCOUNT_BACKEND_ENV = "SHOPPING_APP_ACCOUNT_BACKEND"
ACCOUNT_BACKEND_MODES = frozenset({"json", "shadow", "db_preferred", "db_only"})


class AccountRuntimeStorageError(RuntimeError):
    """Raised when an explicitly selected account backend is unsafe to use."""


class AccountRuntimeConflictError(AccountRuntimeStorageError):
    """Raised when an account registry changed after it was read."""


def account_backend_mode(environment=None) -> str:
    environment = environment if environment is not None else os.environ
    mode = str(environment.get(ACCOUNT_BACKEND_ENV, "json") or "json").strip().lower()
    if mode not in ACCOUNT_BACKEND_MODES:
        raise AccountRuntimeStorageError("Account backend mode is invalid.")
    return mode


def _application_modules():
    # Lazy imports avoid the intentional account-migration/user-service cycle.
    from PushShoppingList.services import account_data_migration_service as migration
    from PushShoppingList.services import application_data_service as application_data

    return application_data, migration


def _database_status(db_path=None):
    application_data, _migration = _application_modules()
    path = Path(application_data.application_data_db_path(db_path))
    status = application_data.application_schema_status(path)
    return path, status


def account_database_path(db_path=None) -> Path:
    path, _status = _database_status(db_path)
    return path


def _account_manifest_sha256(rows) -> str:
    material = sorted(
        (str(row["id"]), str(row["source_sha256"])) for row in rows
    )
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def database_accounts_are_authoritative(db_path=None, *, require_schema=False) -> bool:
    """Return whether every account row has a completed legacy-source marker.

    Missing schema is a normal pre-migration state for ``db_preferred``.  A
    partially installed or incompatible schema fails closed instead of falling
    back to a potentially stale JSON registry.
    """

    application_data, migration = _application_modules()
    path, status = _database_status(db_path)
    if not path.is_file() or not status.get("current_version"):
        if require_schema:
            raise AccountRuntimeStorageError("Account database schema is unavailable.")
        return False
    if not status.get("available"):
        raise AccountRuntimeStorageError("Account database schema is incompatible.")

    try:
        with application_data.existing_application_read_connection(path) as connection:
            if connection is None:
                if require_schema:
                    raise AccountRuntimeStorageError("Account database is unavailable.")
                return False
            account_rows = connection.execute(
                "SELECT id, source_sha256 FROM accounts ORDER BY id"
            ).fetchall()
            account_count = len(account_rows)
            account_manifest_sha256 = _account_manifest_sha256(account_rows)
            covered_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                      FROM accounts AS account
                      JOIN application_source_coverage AS coverage
                        ON coverage.workspace_id = account.workspace_id
                       AND coverage.domain = ?
                       AND coverage.source_key = ?
                       AND coverage.status = 'covered'
                       AND coverage.source_sha256 = account.source_sha256
                    """,
                    (migration.MIGRATION_DOMAIN, migration.SOURCE_KIND),
                ).fetchone()[0]
            )
            latest_run = connection.execute(
                """
                SELECT id, source_sha256, summary_json
                  FROM migration_runs
                 WHERE migration_kind = ? AND status = 'succeeded'
                 ORDER BY rowid DESC
                 LIMIT 1
                """,
                (migration.SOURCE_KIND,),
            ).fetchone()
            covered_by_latest_run = 0
            account_coverage_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM application_source_coverage
                     WHERE domain = ? AND source_key = ? AND status = 'covered'
                    """,
                    (migration.MIGRATION_DOMAIN, migration.SOURCE_KIND),
                ).fetchone()[0]
            )
            account_coverage_rows = connection.execute(
                """
                SELECT account.id, account.source_sha256 AS account_source_sha256,
                       coverage.source_sha256 AS coverage_source_sha256,
                       coverage.migration_run_id, coverage.status,
                       coverage.summary_json
                  FROM accounts AS account
                  LEFT JOIN application_source_coverage AS coverage
                    ON coverage.workspace_id = account.workspace_id
                   AND coverage.domain = ?
                   AND coverage.source_key = ?
                 ORDER BY account.id
                """,
                (migration.MIGRATION_DOMAIN, migration.SOURCE_KIND),
            ).fetchall()
            if latest_run is not None:
                covered_by_latest_run = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                          FROM accounts AS account
                          JOIN application_source_coverage AS coverage
                            ON coverage.workspace_id = account.workspace_id
                           AND coverage.domain = ?
                           AND coverage.source_key = ?
                           AND coverage.status = 'covered'
                           AND coverage.source_sha256 = account.source_sha256
                           AND coverage.migration_run_id = ?
                        """,
                        (
                            migration.MIGRATION_DOMAIN,
                            migration.SOURCE_KIND,
                            latest_run["id"],
                        ),
                    ).fetchone()[0]
                )
    except AccountRuntimeStorageError:
        raise
    except Exception as exc:
        raise AccountRuntimeStorageError(
            "Account database coverage could not be verified."
        ) from exc
    # The latest completed run is the registry-level cutover marker.  Its
    # expected count plus run-bound per-account coverage distinguishes a truly
    # empty migrated registry from a partially deleted database.
    if latest_run is None:
        if account_count or account_coverage_count:
            raise AccountRuntimeStorageError(
                "Account database contains rows without a completed registry migration."
            )
        return False
    try:
        summary = json.loads(str(latest_run["summary_json"] or "{}"))
        expected_count = summary.get("account_count")
        expected_manifest_sha256 = summary.get("account_manifest_sha256")
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AccountRuntimeStorageError(
            "Account registry migration marker is invalid."
        ) from exc
    if (
        not isinstance(summary, Mapping)
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count < 0
        or len(str(latest_run["source_sha256"] or "")) != 64
        or not isinstance(expected_manifest_sha256, str)
        or len(expected_manifest_sha256) != 64
    ):
        raise AccountRuntimeStorageError(
            "Account registry migration marker is invalid."
        )
    coverage_is_exact = True
    for row in account_coverage_rows:
        try:
            coverage_summary = json.loads(str(row["summary_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            coverage_is_exact = False
            break
        if (
            row["status"] != "covered"
            or row["coverage_source_sha256"] != row["account_source_sha256"]
            or row["migration_run_id"] != latest_run["id"]
            or not isinstance(coverage_summary, Mapping)
            or coverage_summary.get("registry_source_sha256")
            != latest_run["source_sha256"]
            or coverage_summary.get("registry_manifest_sha256")
            != expected_manifest_sha256
        ):
            coverage_is_exact = False
            break
    if (
        account_count != expected_count
        or account_manifest_sha256 != expected_manifest_sha256
        or covered_count != account_count
        or covered_by_latest_run != account_count
        or account_coverage_count != account_count
        or not coverage_is_exact
    ):
        raise AccountRuntimeStorageError(
            "Account database migration coverage is incomplete."
        )
    return True


def _decrypt_secrets(account: Mapping[str, object], encryptor=None) -> dict:
    envelope = account.get("encrypted_secrets")
    if not isinstance(envelope, Mapping) or not envelope:
        return {}
    if encryptor is None:
        from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor

        encryptor = AesGcmDataEncryptor.from_environment()
    _application_data, migration = _application_modules()
    value = encryptor.decrypt_json(
        json.dumps(
            dict(envelope),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        associated_data=migration.account_secret_associated_data(str(account["id"])),
    )
    if not isinstance(value, dict):
        raise AccountRuntimeStorageError("Decrypted account secrets are invalid.")
    return value


def legacy_record_from_database(account: Mapping[str, object], *, encryptor=None) -> dict:
    profile = account.get("profile")
    auth_metadata = account.get("auth_metadata")
    if not isinstance(profile, Mapping) or not isinstance(auth_metadata, Mapping):
        raise AccountRuntimeStorageError("Stored account metadata is invalid.")

    record = deepcopy(dict(profile))
    record.update(deepcopy(dict(auth_metadata)))
    record.update({
        "user_id": str(account.get("id") or ""),
        "username": str(account.get("username") or ""),
        "account_status": str(account.get("status") or "active"),
        "password_hash": str(account.get("password_hash") or ""),
        "firebase_uid": str(account.get("firebase_uid") or ""),
        "auth_provider": str(account.get("provider") or "local"),
        "created_at": str(account.get("created_at") or ""),
        "updated_at": str(account.get("updated_at") or ""),
    })

    secrets = _decrypt_secrets(account, encryptor=encryptor)
    for field, value in secrets.items():
        if field in {"two_factor", "two_factor_setup"}:
            existing = record.get(field)
            merged = deepcopy(dict(existing)) if isinstance(existing, Mapping) else {}
            if not isinstance(value, Mapping):
                raise AccountRuntimeStorageError("Stored nested account secret is invalid.")
            merged.update(deepcopy(dict(value)))
            record[field] = merged
        else:
            record[field] = deepcopy(value)
    return record


def _database_revision_from_connection(connection) -> str:
    rows = connection.execute(
        "SELECT id, row_version, source_sha256 FROM accounts ORDER BY id"
    ).fetchall()
    material = [
        [str(row["id"]), int(row["row_version"]), str(row["source_sha256"])]
        for row in rows
    ]
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def database_users_snapshot(db_path=None, *, encryptor=None):
    application_data, _migration = _application_modules()
    path, status = _database_status(db_path)
    if not path.is_file() or not status.get("available"):
        raise AccountRuntimeStorageError("Account database schema is unavailable.")
    try:
        with application_data.existing_application_read_connection(path) as connection:
            if connection is None:
                raise AccountRuntimeStorageError("Account database is unavailable.")
            ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM accounts ORDER BY created_at, id"
                ).fetchall()
            ]
            accounts = [
                application_data.get_account(account_id, connection=connection)
                for account_id in ids
            ]
            revision = _database_revision_from_connection(connection)
    except AccountRuntimeStorageError:
        raise
    except Exception as exc:
        raise AccountRuntimeStorageError("Account database read failed.") from exc
    payload = {
        "users": [
            legacy_record_from_database(account, encryptor=encryptor)
            for account in accounts
            if account is not None
        ]
    }
    return payload, revision


def database_users_payload(db_path=None, *, encryptor=None) -> dict:
    payload, _revision = database_users_snapshot(db_path, encryptor=encryptor)
    return payload


def _existing_secret_payload(account: Optional[Mapping[str, object]], encryptor) -> Optional[dict]:
    if not account:
        return None
    try:
        return _decrypt_secrets(account, encryptor=encryptor)
    except Exception:
        return None


def replace_database_users(
    payload,
    db_path=None,
    *,
    encryptor=None,
    expected_revision: Optional[str] = None,
    require_authoritative: bool = False,
) -> dict:
    """Transactionally make the database account set match a legacy payload."""

    application_data, migration = _application_modules()
    prepared = migration._prepare_accounts(payload)  # strict, payload-preserving validator
    if any(item.secret_payload for item in prepared) and encryptor is None:
        from PushShoppingList.services.data_encryption_service import AesGcmDataEncryptor

        encryptor = AesGcmDataEncryptor.from_environment()

    path, status = _database_status(db_path)
    if not path.is_file() or not status.get("available"):
        raise AccountRuntimeStorageError("Account database schema is unavailable.")

    intended_ids = {item.account_id for item in prepared}
    source_sha256 = hashlib.sha256(
        application_data.canonical_json(payload).encode("utf-8")
    ).hexdigest()
    registry_manifest_sha256 = hashlib.sha256(
        application_data.canonical_json(
            sorted(
                (item.account_id, item.record_sha256)
                for item in prepared
            )
        ).encode("utf-8")
    ).hexdigest()
    try:
        with application_data.application_data_write_connection(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if require_authoritative and not database_accounts_are_authoritative(
                path,
                require_schema=True,
            ):
                raise AccountRuntimeStorageError(
                    "Account database migration coverage is unavailable."
                )
            if (
                expected_revision is not None
                and _database_revision_from_connection(connection) != expected_revision
            ):
                raise AccountRuntimeConflictError(
                    "Account registry changed concurrently; retry the operation."
                )
            run_id = uuid.uuid4().hex
            run_result = application_data.record_application_migration_run(
                migration.SOURCE_KIND,
                "succeeded",
                run_id=run_id,
                source_sha256=source_sha256,
                summary={
                    "account_count": len(prepared),
                    "account_manifest_sha256": registry_manifest_sha256,
                    "runtime_write": True,
                    "schema_version": migration.SCHEMA_VERSION,
                },
                connection=connection,
            )
            if isinstance(run_result, Mapping) and run_result.get("id"):
                run_id = str(run_result["id"])
            existing_ids = {
                str(row["id"])
                for row in connection.execute("SELECT id FROM accounts").fetchall()
            }
            for item in prepared:
                application_data.ensure_workspace(
                    item.workspace_id,
                    migration.WORKSPACE_TYPE,
                    item.account_id,
                    lifecycle_state="active",
                    connection=connection,
                )
                existing = application_data.get_account(item.account_id, connection=connection)
                encrypted_secrets = {}
                encryption_key_id = ""
                if item.secret_payload:
                    if encryptor is None:
                        raise AccountRuntimeStorageError(
                            "Account secret encryption is unavailable."
                        )
                    existing_plaintext = _existing_secret_payload(existing, encryptor)
                    if (
                        existing_plaintext == dict(item.secret_payload)
                        and isinstance(existing, Mapping)
                        and existing.get("encryption_key_id") == encryptor.key_id
                    ):
                        encrypted_secrets = existing.get("encrypted_secrets") or {}
                    else:
                        envelope = encryptor.encrypt_json(
                            item.secret_payload,
                            associated_data=migration.account_secret_associated_data(
                                item.account_id
                            ),
                        )
                        encrypted_secrets = json.loads(envelope)
                    encryption_key_id = encryptor.key_id

                application_data.upsert_account(
                    item.account_id,
                    item.workspace_id,
                    username=item.username,
                    normalized_email=item.normalized_email,
                    status=item.status,
                    password_hash=item.password_hash,
                    firebase_uid=item.firebase_uid,
                    provider=item.provider,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    profile=json.loads(item.profile_json),
                    auth_metadata=json.loads(item.auth_metadata_json),
                    encrypted_secrets=encrypted_secrets,
                    encryption_key_id=encryption_key_id,
                    source_sha256=item.record_sha256,
                    allow_update=True,
                    connection=connection,
                )
                application_data.upsert_source_coverage(
                    item.workspace_id,
                    migration.MIGRATION_DOMAIN,
                    migration.SOURCE_KIND,
                    item.record_sha256,
                    migration_run_id=run_id,
                    status="covered",
                    summary={
                        "runtime_write": True,
                        "registry_source_sha256": source_sha256,
                        "registry_manifest_sha256": registry_manifest_sha256,
                        "schema_version": migration.SCHEMA_VERSION,
                    },
                    connection=connection,
                )

            for account_id in sorted(existing_ids - intended_ids):
                connection.execute(
                    """
                    DELETE FROM workspaces
                     WHERE id = ? AND workspace_type = 'user' AND external_id = ?
                    """,
                    (account_id, account_id),
                )
    except AccountRuntimeStorageError:
        raise
    except Exception as exc:
        raise AccountRuntimeStorageError("Account database write failed.") from exc
    return database_users_payload(path, encryptor=encryptor)


__all__ = [
    "ACCOUNT_BACKEND_ENV",
    "ACCOUNT_BACKEND_MODES",
    "AccountRuntimeConflictError",
    "AccountRuntimeStorageError",
    "account_backend_mode",
    "account_database_path",
    "database_accounts_are_authoritative",
    "database_users_payload",
    "database_users_snapshot",
    "legacy_record_from_database",
    "replace_database_users",
]
