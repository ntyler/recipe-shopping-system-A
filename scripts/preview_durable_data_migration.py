"""Print a redacted, read-only preview of the durable-data migration.

This command intentionally has no apply option.  It inventories configured
legacy sources, inspects the existing application schema read-only, and runs
the account, guest-session, PDF-share, and general durable-data previews.  It
does not install schema, open a write connection, create directories, or alter
legacy files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Mapping, Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from PushShoppingList.services import account_data_migration_service  # noqa: E402
from PushShoppingList.services import application_data_service  # noqa: E402
from PushShoppingList.services import artifact_ownership_service  # noqa: E402
from PushShoppingList.services import data_migration_inventory_service  # noqa: E402
from PushShoppingList.services import durable_data_migration_service  # noqa: E402
from PushShoppingList.services import guest_session_migration_service  # noqa: E402
from PushShoppingList.services import pdf_share_migration_service  # noqa: E402
from PushShoppingList.services.data_encryption_service import (  # noqa: E402
    AesGcmDataEncryptor,
    DATA_ENCRYPTION_KEY_ENV,
    DATA_ENCRYPTION_KEY_ID_ENV,
    DataEncryptionError,
)


REPORT_VERSION = 1
READ_ONLY_COMMAND = "durable_data_migration_preview"


def _error_code(exc: BaseException) -> str:
    """Return a stable payload-free error code."""

    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    return re.sub(r"[^a-z0-9_]+", "_", name).strip("_") or "preview_error"


def _optional_source_preview(path: Path, preview_builder, empty_counts: Mapping[str, int]):
    """Preview a specialized source, treating an absent file as an empty phase."""

    if not path.is_file():
        return {
            "status": "missing",
            "source_ready": True,
            "source_sha256": None,
            "byte_count": 0,
            **dict(empty_counts),
        }
    preview = preview_builder(path)
    payload = preview.to_dict()
    payload["source_ready"] = bool(preview.ready)
    # ``ready`` on service previews describes the source parse only.  The
    # operator report uses ``migration_ready`` for all phase prerequisites.
    payload.pop("ready", None)
    return payload


def _encryption_preflight(environment: Mapping[str, str]):
    supplied = bool(
        str(environment.get(DATA_ENCRYPTION_KEY_ENV, "") or "").strip()
        or str(environment.get(DATA_ENCRYPTION_KEY_ID_ENV, "") or "").strip()
    )
    try:
        encryptor = AesGcmDataEncryptor.from_environment(environment)
    except DataEncryptionError:
        return None, {
            "configured": False,
            "status": "invalid_configuration" if supplied else "not_configured",
        }
    return encryptor, {"configured": True, "status": "ready"}


def _schema_report(db_path=None):
    """Return only schema metadata; never echo the configured database path."""

    try:
        status = application_data_service.application_schema_status(db_path)
        dry_run = application_data_service.install_application_schema(
            db_path,
            dry_run=True,
        )
    except Exception as exc:  # The report must fail closed without leaking paths.
        return {
            "available": False,
            "compatible": False,
            "migration_ready": False,
            "status": "invalid",
            "error_code": _error_code(exc),
        }

    allowed_status = {
        "available",
        "checksum_matches",
        "compatible",
        "current_version",
        "exists",
        "expected_checksum",
        "issues",
        "missing_tables",
        "pending_versions",
        "target_version",
    }
    allowed_plan = {
        "action",
        "applied_versions",
        "authorized",
        "current_version",
        "issues",
        "missing_tables",
        "pending_versions",
        "target_version",
        "would_create_database",
    }
    report = {key: status[key] for key in sorted(allowed_status) if key in status}
    report["dry_run_plan"] = {
        key: dry_run[key] for key in sorted(allowed_plan) if key in dry_run
    }
    report["migration_ready"] = bool(status.get("compatible"))
    report["status"] = "ready" if report["migration_ready"] else "invalid"
    return report


def _durable_summary(preview, *, include_entries: bool):
    counts_by_status = preview.counts_by_status
    counts_by_classification = preview.counts_by_classification
    payload = {
        "catalog_sha256": preview.catalog_sha256,
        "config_sha256": preview.config_sha256,
        "counts_by_classification": counts_by_classification,
        "counts_by_status": counts_by_status,
        "created_at": preview.created_at,
        "entry_count": len(preview.entries),
        "record_count": sum(entry.record_count for entry in preview.entries),
        "byte_count": sum(entry.byte_count for entry in preview.entries),
        "secret_field_count": sum(
            entry.secret_field_count for entry in preview.entries
        ),
    }
    blocking_count = sum(
        counts_by_status.get(status, 0)
        for status in (
            durable_data_migration_service.STATUS_BLOCKED,
            durable_data_migration_service.STATUS_INVALID,
        )
    )
    payload["blocking_entry_count"] = blocking_count
    payload["migration_ready"] = blocking_count == 0
    payload["status"] = "ready" if blocking_count == 0 else "blocked"
    if include_entries:
        # PreviewEntry.to_dict removes workspace IDs and replaces them with a
        # one-way short fingerprint.  It never includes document payloads.
        payload["entries"] = [entry.to_dict() for entry in preview.entries]
    return payload


def _artifact_summary(preview, *, include_entries: bool):
    """Return a path-free ownership summary suitable for operator reports."""

    counts = dict(preview.counts)
    blocked = int(counts.get("blocked") or 0)
    payload = {
        "counts": counts,
        "manifest_sha256": preview.manifest_sha256,
        "migration_ready": blocked == 0,
        "status": "ready" if blocked == 0 else "blocked",
    }
    if include_entries:
        # Candidate reports contain only one-way owner/storage fingerprints,
        # classifications, and counts. They never contain paths or object keys.
        payload["artifacts"] = [
            candidate.report_dict() for candidate in preview.candidates
        ]
    return payload


def build_preview_report(
    *,
    environment: Optional[Mapping[str, str]] = None,
    db_path=None,
    include_entries: bool = False,
):
    """Build the complete read-only report for CLI and automated preflight use."""

    environment = dict(os.environ if environment is None else environment)
    inventory = data_migration_inventory_service.build_default_migration_inventory(
        environment=environment
    )
    config = inventory.config
    encryptor, encryption = _encryption_preflight(environment)

    account_path = Path(config.global_sources["accounts_auth"])
    guest_path = Path(config.global_sources["guest_sessions"])
    share_path = Path(config.global_sources["pdf_share_tokens"])

    accounts = _optional_source_preview(
        account_path,
        account_data_migration_service.preview_account_data_migration,
        {
            "account_count": 0,
            "accounts_requiring_encryption": 0,
            "profile_field_count": 0,
            "auth_metadata_field_count": 0,
        },
    )
    account_needs_encryption = int(
        accounts.get("accounts_requiring_encryption") or 0
    ) > 0
    accounts["migration_ready"] = bool(accounts.get("source_ready")) and (
        not account_needs_encryption or encryption["configured"]
    )

    guest_sessions = _optional_source_preview(
        guest_path,
        guest_session_migration_service.preview_guest_session_migration,
        {
            "session_count": 0,
            "active_count": 0,
            "inactive_count": 0,
            "expired_count": 0,
            "active_unexpired_count": 0,
        },
    )
    guest_sessions["migration_ready"] = bool(guest_sessions.get("source_ready"))

    pdf_shares = _optional_source_preview(
        share_path,
        pdf_share_migration_service.preview_pdf_share_migration,
        {
            "record_count": 0,
            "active_count": 0,
            "revoked_count": 0,
            "expired_count": 0,
            "access_count": 0,
        },
    )
    pdf_shares["migration_ready"] = bool(pdf_shares.get("source_ready")) and (
        int(pdf_shares.get("record_count") or 0) == 0 or encryption["configured"]
    )

    durable_preview = durable_data_migration_service.preview_durable_data(
        config,
        encryptor=encryptor,
    )
    durable = _durable_summary(durable_preview, include_entries=include_entries)
    artifact_preview = artifact_ownership_service.preview_default_artifact_ownership(
        inventory
    )
    artifacts = _artifact_summary(
        artifact_preview,
        include_entries=include_entries,
    )
    schema = _schema_report(db_path)
    inventory_report = inventory.to_dict()

    validation_counts = {
        "accounts": int(accounts.get("account_count") or 0),
        "active_unexpired_guest_sessions": int(
            guest_sessions.get("active_unexpired_count") or 0
        ),
        "artifact_references": int(
            artifacts.get("counts", {}).get("references") or 0
        ),
        "artifacts": int(artifacts.get("counts", {}).get("artifacts") or 0),
        "blocked_artifacts": int(
            artifacts.get("counts", {}).get("blocked") or 0
        ),
        "durable_bytes": int(durable.get("byte_count") or 0),
        "durable_records": int(durable.get("record_count") or 0),
        "durable_source_entries": int(durable.get("entry_count") or 0),
        "guest_sessions": int(guest_sessions.get("session_count") or 0),
        "pdf_share_links": int(pdf_shares.get("record_count") or 0),
        "workspaces": int(inventory.user_workspace_count)
        + int(inventory.guest_workspace_count)
        + int(inventory.orphan_guest_workspace_count),
    }
    migration_ready = all(
        (
            inventory.ready,
            bool(schema.get("migration_ready")),
            bool(accounts.get("migration_ready")),
            bool(guest_sessions.get("migration_ready")),
            bool(pdf_shares.get("migration_ready")),
            bool(durable.get("migration_ready")),
            bool(artifacts.get("migration_ready")),
        )
    )
    return {
        "command": READ_ONLY_COMMAND,
        "dry_run": True,
        "encryption": encryption,
        "inventory": inventory_report,
        "migration_ready": migration_ready,
        "phases": {
            "accounts_auth": accounts,
            "application_schema": schema,
            "artifact_ownership": artifacts,
            "durable_documents": durable,
            "guest_sessions": guest_sessions,
            "pdf_share_tokens": pdf_shares,
        },
        "report_version": REPORT_VERSION,
        "validation_counts": validation_counts,
        "write_performed": False,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the staged durable-data migration and print a redacted JSON "
            "report. This command is always read-only and has no apply mode."
        )
    )
    parser.add_argument(
        "--database",
        default="",
        help=(
            "Application/recipe SQLite database to inspect read-only. When omitted, "
            "the application's configured default is inspected."
        ),
    )
    parser.add_argument("--users-file", default="", help="Override legacy users.json.")
    parser.add_argument(
        "--guest-sessions-file",
        default="",
        help="Override legacy guest_sessions.json.",
    )
    parser.add_argument("--user-data-dir", default="", help="Override user workspace root.")
    parser.add_argument("--guest-data-dir", default="", help="Override guest workspace root.")
    parser.add_argument("--feedback-file", default="", help="Override feedback JSON.")
    parser.add_argument("--admin-audit-file", default="", help="Override audit JSON.")
    parser.add_argument(
        "--include-entries",
        action="store_true",
        help="Include payload-free source entries with hashed workspace references.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return exit status 3 when a blocker is present; the report is still printed.",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")
    return parser


def _environment_with_overrides(args) -> dict:
    environment = dict(os.environ)
    overrides = {
        "SHOPPING_APP_USERS_FILE": args.users_file,
        "SHOPPING_APP_GUEST_SESSIONS_FILE": args.guest_sessions_file,
        "SHOPPING_APP_USER_DATA_DIR": args.user_data_dir,
        "SHOPPING_APP_GUEST_DATA_DIR": args.guest_data_dir,
        "SHOPPING_APP_FEEDBACK_FILE": args.feedback_file,
        "SHOPPING_APP_ADMIN_SUPPORT_AUDIT_FILE": args.admin_audit_file,
    }
    environment.update({key: value for key, value in overrides.items() if value})
    return environment


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = build_preview_report(
            environment=_environment_with_overrides(args),
            db_path=args.database or None,
            include_entries=args.include_entries,
        )
    except Exception as exc:
        report = {
            "command": READ_ONLY_COMMAND,
            "dry_run": True,
            "error_code": _error_code(exc),
            "migration_ready": False,
            "report_version": REPORT_VERSION,
            "write_performed": False,
        }
        print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
        return 2

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    if args.require_ready and not report["migration_ready"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
